"""
Basic models for the web app for handling topography data.
"""

import io
import itertools
import logging
import os.path
import sys
import tempfile
from collections import defaultdict
from typing import List

import django.dispatch
import matplotlib.pyplot
import numpy as np
import PIL
import tagulous.models as tm
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from rest_framework.reverse import reverse
from SurfaceTopography.Container.SurfaceContainer import SurfaceContainer
from SurfaceTopography.Exceptions import UndefinedDataError
from SurfaceTopography.Metadata import InstrumentParametersModel
from SurfaceTopography.Support.UnitConversion import get_unit_conversion_factor

from ..authorization.mixins import PermissionMixin
from ..authorization.models import AuthorizedManager, PermissionSet, ViewEditFull
from ..files.models import Folder, Manifest
from ..taskapp.models import TaskStateModel
from ..taskapp.utils import run_task
from .utils import get_topography_reader, render_deepzoom

_log = logging.getLogger(__name__)

post_refresh_cache = django.dispatch.Signal()

MAX_LENGTH_DATAFILE_FORMAT = (
    15  # some more characters than currently needed, we may have sub formats in future
)
SQUEEZED_DATAFILE_FORMAT = "nc"

# Detect whether we are running within a Celery worker. This solution was suggested here:
# https://stackoverflow.com/questions/39003282/how-can-i-detect-whether-im-running-in-a-celery-worker
_IN_CELERY_WORKER_PROCESS = (
    sys.argv and sys.argv[0].endswith("celery") and "worker" in sys.argv
)


def _get_unit(channel):
    if isinstance(channel.unit, tuple):
        lateral_unit, data_unit = channel.unit
        return data_unit
    return channel.unit


class ThumbnailGenerationException(Exception):
    """Failure while generating thumbnails for a topography."""

    def __init__(self, topo, message):
        self._topo = topo
        self._message = message

    def __str__(self):
        return self._message


class DZIGenerationException(ThumbnailGenerationException):
    """Failure while generating DZI files for a topography."""

    pass


class TopobankLazySurfaceContainer(SurfaceContainer):
    """Wraps a `Surface` with lazy loading of topography data"""

    def __init__(self, surface):
        self._surface = surface
        self._topographies = self._surface.topography_set.all()

    def __len__(self):
        return len(self._topographies)

    def __getitem__(self, item):
        return self._topographies[item].read()


class SubjectMixin:
    """Extra methods common to all instances which can be subject to an analysis."""

    # This is needed for objects to be able to serve as subjects
    #     for analysis, because some template code uses this.
    # Probably this could be made faster by caching the result.
    # Not sure whether this should be done at compile time.
    @classmethod
    def get_content_type(cls):
        """Returns ContentType for own class."""
        return ContentType.objects.get_for_model(cls)

    @classmethod
    def get_subject_type(cls):
        """Returns a human readable name for this subject type."""
        return cls._meta.model_name

    def is_shared(self, user: settings.AUTH_USER_MODEL) -> bool:
        """Returns True, if this subject is shared with a given user.

        Always returns True if user is the creator of the related surface.

        :param with_user: User to test
        :param allow_change: If True, only return True if surface can be changed by given user
        :return: True or False
        """
        raise NotImplementedError()

    def get_related_surfaces(self):
        """Returns a list of related surfaces. This can be either the parent
        surface (for a topography), the child surfaces (for a tag), or the
        surface itself (for a surface).

        Returns
        -------
        surfaces : list of Surface
            The surfaces that are related to this object.
        """
        raise NotImplementedError()


class Tag(tm.TagTreeModel, SubjectMixin):
    """This is the common tag model for surfaces and topographies."""

    _user = None

    def get_absolute_url(self, request=None):
        """URL of API endpoint for this tag"""
        return reverse(
            "manager:tag-api-detail", kwargs=dict(name=self.name), request=request
        )

    def authorize_user(
        self,
        user: settings.AUTH_USER_MODEL = None,
        access_level: ViewEditFull = "view",
        permissions: PermissionSet = None,
    ):
        if access_level != "view":
            raise PermissionError(
                f"Cannot elevate permission to '{access_level}' because tags are not "
                "editable."
            )
        if user is not None:
            if permissions is not None:
                raise RuntimeError(
                    "Can authorize with either user name or permission set, not both."
                )
            self._user = user
        elif permissions is not None:
            users = permissions.get_users()
            if len(users) == 0:
                raise RuntimeError(
                    "Trying to authorize with permission set that has no users."
                )
            elif len(users) > 1:
                raise PermissionError(
                    "Trying to authorize with permission set with more than one user."
                )
            self._user, _ = users[0]
        else:
            raise RuntimeError("Need user name or permission set to authorize.")

    def is_shared(self, user: settings.AUTH_USER_MODEL) -> bool:
        return True  # Tags are generally shared, but the surfaces may not

    def get_authorized_user(self) -> settings.AUTH_USER_MODEL:
        return self._user

    def get_related_surfaces(self):
        """Return all surfaces with exactly this tag"""
        if self._user is None:
            raise PermissionError(
                "Cannot return surfaces belonging to a tag because "
                "no user was specified. Use `authorize_user` "
                "to restrict user permissions."
            )
        return Surface.objects.for_user(self._user).filter(tags=self.id)

    def get_children(self) -> List[str]:
        def make_child(tag_name):
            tag_suffix = tag_name[len(self.name) + 1 :]
            name, rest = (tag_suffix + "/").split("/", maxsplit=1)
            return f"{self.name}/{name}"

        if self._user is None:
            raise PermissionError(
                "Cannot return children of a tag because "
                "no user was specified. Use `authorize_user` "
                "to restrict user permissions."
            )
        all_tags = set(
            itertools.chain.from_iterable(
                Surface.objects.for_user(self._user)
                .filter(tags__name__startswith=f"{self.name}/")
                .values_list("tags__name")
            )
        )
        return list(
            set(make_child(tag) for tag in all_tags if tag.startswith(f"{self.name}/"))
        )

    def get_descendant_surfaces(self):
        """Return all surfaces with exactly this tag or a descendant tag"""
        if self._user is None:
            raise PermissionError(
                "Cannot return surfaces belonging to a tag because "
                "no user was specified. Use `authorize_user` "
                "to restrict user permissions."
            )
        return (
            Surface.objects.for_user(self._user)
            .filter(Q(tags=self) | Q(tags__name__startswith=f"{self.name}/"))
            .distinct()
        )

    def get_properties(self, kind=None):
        """
        Collects unique properties for a given tag based on the kind of property.

        Parameters
        ----------
        self : Tag
            The tag to collect unique properties for.
        kind : str, optional
            The kind of property to collect. Can be 'categorical', 'numerical', or None.
            If None, collects all properties. Default is None.

        Raises
        ------
        ValueError
            If the kind is not None, 'categorical', or 'numerical'.

        Returns
        -------
        property_values : dict
            Keys are property names and values are lists of property values for
            each surface related to the tag.
        property_infos : dict
            Keys are property names and values are either a list of categories for
            categorical properties or a dictionary with min and max values for
            numerical properties.
        """
        if kind not in [None, "categorical", "numerical"]:
            raise ValueError(f"Invalid value for kind: {kind}")

        nb_surfaces = len(self.get_descendant_surfaces())

        # Initialize a dictionary to collect all properties. The default value for
        # each property is a list of np.nan of length equal to the number of
        # surfaces.
        property_values = defaultdict(lambda: [np.nan] * nb_surfaces)
        categorical_properties = set()

        # Iterate over all surfaces related to the tag
        for i, surface in enumerate(self.get_descendant_surfaces()):
            # For each surface, iterate over all its properties
            for p in surface.properties.all():
                # If the property is categorical, add its name to the set of
                # categorical properties and set its value for the current surface
                if p.is_categorical:
                    categorical_properties.add(str(p.name))
                    if kind is None or kind == "categorical":
                        property_values[str(p.name)][i] = p.value
                # If the property is not categorical, set its value for the
                # current surface (np.nan if the value is None)
                elif kind is None or kind == "numerical":
                    property_values[str(p.name)][i] = (
                        np.nan if p.value is None else p.value
                    )

        # Initialize a dictionary to store additional information about each property
        property_infos = {}

        # For each property, if it's categorical, store its categories (excluding
        # np.nan). If it's numerical, store its min and max values.
        for key, values in property_values.items():
            if key in categorical_properties:
                property_infos[key] = {"categories": list(set(values) - set([np.nan]))}
            else:
                property_infos[key] = {
                    "min_value": np.nanmin(values),
                    "max_value": np.nanmax(values),
                }

        return property_values, property_infos


class Surface(PermissionMixin, models.Model, SubjectMixin):
    """
    A physical surface of a specimen.

    There can be many topographies (measurements) for one surface.
    """

    CATEGORY_CHOICES = [
        ("exp", "Experimental data"),
        ("sim", "Simulated data"),
        ("dum", "Dummy data"),
    ]

    LICENSE_CHOICES = [
        (k, settings.CC_LICENSE_INFOS[k]["option_name"])
        for k in ["cc0-1.0", "ccby-4.0", "ccbysa-4.0"]
    ]

    class Meta:
        ordering = ["name"]
        permissions = (
            ("share_surface", "Can share surface"),
            ("publish_surface", "Can publish surface"),
        )

    #
    # Manager
    #
    objects = AuthorizedManager()

    #
    # Permissions
    #
    permissions = models.ForeignKey(PermissionSet, on_delete=models.CASCADE, null=True)

    #
    # Model data
    #
    name = models.CharField(max_length=80, blank=True)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    description = models.TextField(blank=True)
    category = models.CharField(
        max_length=3, choices=CATEGORY_CHOICES, null=True, blank=False
    )
    tags = tm.TagField(to=Tag)
    attachments = models.ForeignKey(Folder, on_delete=models.SET_NULL, null=True)
    creation_datetime = models.DateTimeField(auto_now_add=True, null=True)
    modification_datetime = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        s = self.name
        if self.is_published:
            s += f" (version {self.publication.version})"
        return s

    @property
    def label(self):
        return str(self)

    def get_related_surfaces(self):
        return [self]

    def get_absolute_url(self, request=None):
        """URL of API endpoint for this surface"""
        return reverse(
            "manager:surface-api-detail", kwargs=dict(pk=self.pk), request=request
        )

    def num_topographies(self):
        return self.topography_set.count()

    def save(self, *args, **kwargs):
        created = self.pk is None
        if created and self.permissions is None:
            # Create a new permission set for this dataset
            _log.debug(
                f"Creating an empty permission set for surface {self.id} which was "
                f"just created."
            )
            self.permissions = PermissionSet.objects.create()
        if self.attachments is None:
            # Create a new folder for attachments
            _log.debug(
                f"Creating an empty folder for attachments to surface {self.id}."
            )
            self.attachments = Folder.objects.create(
                permissions=self.permissions, read_only=False
            )
        super().save(*args, **kwargs)
        if created:
            # Grant permissions to creator
            self.permissions.grant_for_user(self.creator, "full")

    def to_dict(self):
        """Create dictionary for export of metadata to json or yaml.

        Does not include topographies. They can be added like this:

         surface_dict = surface.to_dict()
         surface_dict['topographies'] = [t.to_dict() for t in surface.topography_set.order_by('name')]

        The publication URL will be based on the official contact.engineering URL.

        Returns:
            dict
        """
        creator = {"name": self.creator.name}
        if self.creator.orcid_id is not None:
            creator["orcid"] = self.creator.orcid_id
        d = {
            "name": self.name,
            "category": self.category,
            "creator": creator,
            "description": self.description,
            "tags": [t.name for t in self.tags.order_by("name")],
            "is_published": self.is_published,
        }
        if self.is_published:
            d["publication"] = {
                "url": self.publication.get_full_url(),
                "license": self.publication.get_license_display(),
                "authors": self.publication.get_authors_string(),
                "version": self.publication.version,
                "date": str(self.publication.datetime.date()),
                "doi_url": self.publication.doi_url or "",
                "doi_state": self.publication.doi_state or "",
            }
        if self.properties.count() > 0:
            d["properties"] = [p.to_dict() for p in self.properties.all()]
        return d

    def is_shared(self, user: settings.AUTH_USER_MODEL) -> bool:
        """
        Returns True if this surface is shared with a given user.

        Always returns True if the user is the creator of the surface.

        Parameters
        ----------
        user : User
            The user to check for sharing status.

        Returns
        -------
        bool
            True if the surface is shared with the given user, False otherwise.
        """
        return self.get_permission(user) is not None

    def grant_permission(
        self, user: settings.AUTH_USER_MODEL, allow: ViewEditFull = "view"
    ):
        if self.is_published:
            raise PermissionError(
                "Permissions of a published dataset cannot be changed."
            )

        super().grant_permission(user, allow)

    def revoke_permission(self, user: settings.AUTH_USER_MODEL):
        if self.is_published:
            raise PermissionError(
                "Permissions of a published dataset cannot be changed."
            )

        super().revoke_permission(user)

    def deepcopy(self):
        """Creates a copy of this surface with all topographies and meta data.

        The database entries for this surface and all related
        topographies are copied, therefore all meta data.
        All files will be copied.

        References to instruments will not be copied.

        The automated analyses will be triggered for this new surface.

        Returns
        -------
        The copy of the surface.

        """
        # Copy of the surface entry
        # (see https://docs.djangoproject.com/en/2.2/topics/db/queries/#copying-model-instances)

        surface = Surface.objects.get(pk=self.pk)
        surface.pk = None
        surface.permissions = None  # Will be autogenerated on save
        surface.task_id = None  # We need to indicate that no tasks have run
        surface.tags = self.tags.get_tag_list()
        surface.attachments = surface.attachments.deepcopy()
        surface.save()  # This will create a new PermissionSet
        # TODO: handle permissions of attachments

        for topography in self.topography_set.all():
            topography.deepcopy(surface)
            # we pass the surface here because there is a constraint that (surface_id +
            # topography name) must be unique, i.e. a surface should never have two
            # topographies of the same name, so we can't set the new surface as the
            # second step
        for property in self.properties.all():
            property.deepcopy(surface)

        _log.info("Created deepcopy of surface %s -> surface %s", self.pk, surface.pk)
        return surface

    @property
    def is_published(self):
        """Returns True, if a publication for this surface exists."""
        return hasattr(
            self, "publication"
        )  # checks whether the related object surface.publication exists

    def lazy_read(self):
        """
        Returns a `SurfaceTopography.Container.SurfaceContainer`
        representation of this dataset. Reading of actual data is deferred
        to the point where it is actually needed.
        """
        return TopobankLazySurfaceContainer(self)


class Topography(PermissionMixin, TaskStateModel, SubjectMixin):
    """
    A single topography measurement of a surface of a specimen.
    """

    celery_queue = settings.TOPOBANK_MANAGER_QUEUE

    LENGTH_UNIT_CHOICES = [
        ("km", "kilometers"),
        ("m", "meters"),
        ("mm", "millimeters"),
        ("µm", "micrometers"),
        ("nm", "nanometers"),
        ("Å", "angstrom"),
        ("pm", "picometers"),  # This is the default unit for VK files so we need it
    ]

    HAS_UNDEFINED_DATA_DESCRIPTION = {
        None: "contact.engineering could not (yet) determine if this topography has undefined data points.",
        True: "The dataset has undefined/missing data points.",
        False: "No undefined/missing data found.",
    }

    FILL_UNDEFINED_DATA_MODE_NOFILLING = "do-not-fill"
    FILL_UNDEFINED_DATA_MODE_HARMONIC = "harmonic"

    FILL_UNDEFINED_DATA_MODE_CHOICES = [
        (FILL_UNDEFINED_DATA_MODE_NOFILLING, "Do not fill undefined data points"),
        (
            FILL_UNDEFINED_DATA_MODE_HARMONIC,
            "Interpolate undefined data points with harmonic functions",
        ),
    ]

    DETREND_MODE_CHOICES = [
        ("center", "No detrending, but subtract mean height"),
        ("height", "Remove tilt"),
        ("curvature", "Remove curvature and tilt"),
    ]

    INSTRUMENT_TYPE_UNDEFINED = "undefined"
    INSTRUMENT_TYPE_MICROSCOPE_BASED = "microscope-based"
    INSTRUMENT_TYPE_CONTACT_BASED = "contact-based"

    INSTRUMENT_TYPE_CHOICES = [
        (
            INSTRUMENT_TYPE_UNDEFINED,
            "Instrument of unknown type - all data considered as reliable",
        ),
        (
            INSTRUMENT_TYPE_MICROSCOPE_BASED,
            "Microscope-based instrument with known resolution",
        ),
        (
            INSTRUMENT_TYPE_CONTACT_BASED,
            "Contact-based instrument with known tip radius",
        ),
    ]

    class Meta:
        ordering = ["measurement_date", "pk"]
        unique_together = (("surface", "name"),)
        verbose_name = "measurement"
        verbose_name_plural = "measurements"

    #
    # Manager
    #
    objects = AuthorizedManager()

    #
    # Model hierarchy and permissions
    #
    permissions = models.ForeignKey(PermissionSet, on_delete=models.CASCADE, null=True)
    surface = models.ForeignKey(Surface, on_delete=models.CASCADE)

    #
    # Descriptive fields
    #
    name = models.TextField()  # This must be identical to the file name on upload
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    measurement_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    tags = tm.TagField(to=Tag)
    attachments = models.ForeignKey(Folder, on_delete=models.SET_NULL, null=True)
    creation_datetime = models.DateTimeField(auto_now_add=True, null=True)
    modification_datetime = models.DateTimeField(auto_now=True, null=True)

    #
    # Fields related to raw data
    #
    datafile = models.ForeignKey(
        Manifest,
        null=True,
        on_delete=models.SET_NULL,
        related_name="topography_datafiles",
    )
    datafile_format = models.CharField(
        max_length=MAX_LENGTH_DATAFILE_FORMAT, null=True, default=None, blank=True
    )
    channel_names = models.JSONField(default=list)
    data_source = models.IntegerField(null=True)  # Channel index
    # Django documentation discourages the use of null=True on a CharField. We use it
    # here nevertheless, because we need this values as argument to a function where
    # None has a special meaning (autodetection of format). If we used an empty string
    # as proposed in the docs, we would need extra logic everywhere the field
    # 'datafile_format' is used.

    # All data is also stored in a standardized and "squeezed" (all filters, e.g.
    # scaling and detrending, applied) format for faster loading and processing. This
    # file is a netCDF3 file.
    squeezed_datafile = models.ForeignKey(
        Manifest,
        null=True,
        on_delete=models.SET_NULL,
        related_name="topography_squeezed_datafiles",
    )

    #
    # Fields with physical meta data
    #
    size_editable = models.BooleanField(default=False, editable=False)
    size_x = models.FloatField(null=True, validators=[MinValueValidator(0.0)])
    size_y = models.FloatField(
        null=True, validators=[MinValueValidator(0.0)]
    )  # null for line scans

    unit_editable = models.BooleanField(default=False, editable=False)
    unit = models.TextField(choices=LENGTH_UNIT_CHOICES, null=True)

    height_scale_editable = models.BooleanField(default=False, editable=False)
    height_scale = models.FloatField(default=1)

    has_undefined_data = models.BooleanField(
        null=True, default=None
    )  # default is undefined
    fill_undefined_data_mode = models.TextField(
        choices=FILL_UNDEFINED_DATA_MODE_CHOICES,
        default=FILL_UNDEFINED_DATA_MODE_NOFILLING,
    )

    detrend_mode = models.TextField(choices=DETREND_MODE_CHOICES, default="center")

    resolution_x = models.IntegerField(
        null=True, editable=False, validators=[MinValueValidator(0)]
    )  # null for line scans
    resolution_y = models.IntegerField(
        null=True, editable=False, validators=[MinValueValidator(0)]
    )  # null for line scans

    bandwidth_lower = models.FloatField(
        null=True, default=None, editable=False
    )  # in meters
    bandwidth_upper = models.FloatField(
        null=True, default=None, editable=False
    )  # in meters
    short_reliability_cutoff = models.FloatField(
        null=True, default=None, editable=False
    )

    is_periodic_editable = models.BooleanField(default=True, editable=False)
    is_periodic = models.BooleanField(default=False)

    #
    # Fields about instrument and its parameters
    #
    instrument_name = models.CharField(max_length=200, blank=True)
    instrument_type = models.TextField(
        choices=INSTRUMENT_TYPE_CHOICES, default=INSTRUMENT_TYPE_UNDEFINED
    )
    instrument_parameters = models.JSONField(default=dict)

    #
    # Thumnbnail and deep zoom files
    #
    thumbnail = models.ForeignKey(
        Manifest,
        null=True,
        on_delete=models.SET_NULL,
        related_name="topography_thumbnails",
    )
    deepzoom = models.ForeignKey(
        Folder,
        null=True,
        on_delete=models.SET_NULL,
        related_name="topography_deepzooms",
    )

    # Changes in these fields trigger a refresh of the topography cache and of all analyses
    _significant_fields = {
        "size_x",
        "size_y",
        "unit",
        "is_periodic",
        "height_scale",
        "fill_undefined_data_mode",
        "detrend_mode",
        "data_source",
        "instrument_type",
    }  # + 'instrument_parameters'

    #
    # Methods
    #
    def save(self, *args, **kwargs):
        created = self.pk is None
        if created:
            if self.creator is None:
                self.creator = self.surface.creator
            self.permissions = self.surface.permissions
        if self.attachments is None:
            _log.debug(
                f"Creating an empty folder for attachments to topography {self.id}."
            )
            self.attachments = Folder.objects.create(
                permissions=self.permissions, read_only=False
            )

        # Reset to no refresh
        refresh_dependent_data = False

        # Strategies to detect changes in significant fields:
        # https://stackoverflow.com/questions/1355150/when-saving-how-can-you-check-if-a-field-has-changed
        try:
            # Do not check for None in self.id as this breaks should we switch to UUIDs
            old_obj = Topography.objects.get(pk=self.pk)
        except self.DoesNotExist:
            pass  # Do nothing, we have just created a new topography
        else:
            # Check which fields actually changed
            changed_fields = [
                getattr(self, name) != getattr(old_obj, name)
                for name in self._significant_fields
            ]

            changed_fields = [
                name
                for name, changed in zip(self._significant_fields, changed_fields)
                if changed
            ]

            # `instrument_parameters` is special as it can contain non-significant entries
            if InstrumentParametersModel(
                **self.instrument_parameters
            ) != InstrumentParametersModel(**old_obj.instrument_parameters):
                changed_fields += ["instrument_parameters"]

            # We need to refresh if any of the significant fields changed during this save
            refresh_dependent_data = any(changed_fields)

            if refresh_dependent_data:
                _log.debug(
                    f"The following significant fields of topography {self.id} changed: "
                )
                for name in changed_fields:
                    _log.debug(
                        f"{name}: was '{getattr(old_obj, name)}', is now '{getattr(self, name)}'"
                    )

        # Check if we need to run the update task
        if refresh_dependent_data:
            run_task(self)

        # Save after run task, because run task may update the task state
        super().save(*args, **kwargs)

    def save_datafile(self, fobj):
        self.datafile = Manifest.objects.create(
            permissions=self.permissions,
            filename=self.name,
            kind="raw",
            file=File(fobj),
        )

    def remove_files(self):
        """Remove files associated with a topography instance before removal of the topography."""

        def delete(x):
            if x:
                x.delete()

        delete(self.datafile)
        delete(self.squeezed_datafile)
        delete(self.thumbnail)
        delete(self.deepzoom)

    def __str__(self):
        return "Topography '{0}' from {1}".format(self.name, self.measurement_date)

    @property
    def label(self):
        """Return a string which can be used in the UI."""
        return self.name

    @property
    def storage_prefix(self):
        """Return prefix used for storage.

        Looks like a relative path to a directory.
        If storage is on filesystem, the prefix should correspond
        to a real directory.
        """
        if self.id is None:
            raise RuntimeError(
                "This `Topography` does not have an id yet; the storage prefix is not yet known."
            )
        return f"topographies/{self.id}"

    def get_related_surfaces(self):
        """Returns sequence of related surfaces.

        :return: True or False
        """
        return [self.surface]

    def get_absolute_url(self, request=None):
        """URL of API endpoint for this topography."""
        return reverse(
            "manager:topography-api-detail", kwargs=dict(pk=self.pk), request=request
        )

    def is_shared(self, user: settings.AUTH_USER_MODEL) -> bool:
        """Returns True, if this topography is shared with a given user.

        Just returns whether the related surface is shared with the user
        or not.

        :param user: User to test
        :param allow_change: If True, only return True if topography can be changed by given user
        :return: True or False
        """
        return self.permissions.get_for_user(user) is not None

    @property
    def instrument_info(self):
        # Build dictionary with instrument information from database... this may override data provided by the
        # topography reader
        return {
            "instrument": {
                "name": self.instrument_name,
                "parameters": InstrumentParametersModel(
                    **self.instrument_parameters
                ).model_dump(exclude_none=True),
            }
        }

    def _read(self, reader):
        """Construct kwargs for reading topography given channel information"""
        if not _IN_CELERY_WORKER_PROCESS and self.size_y is not None:
            _log.warning(
                "You are requesting to load a (2D) topography and you are not within in a Celery worker "
                "process. This operation is potentially slow and may require a lot of memory - do not use "
                "`Topography.read` within the main Django server!"
            )

        reader_kwargs = dict(channel_index=self.data_source, periodic=self.is_periodic)

        channel = reader.channels[self.data_source]

        # Set size if physical size was not given in datafile
        # (see also  TopographyCreateWizard.get_form_initial)
        # Physical size is always a tuple or None.
        if channel.physical_sizes is None:
            if self.size_y is None:
                reader_kwargs["physical_sizes"] = (self.size_x,)
            else:
                reader_kwargs["physical_sizes"] = self.size_x, self.size_y

        if channel.height_scale_factor is None and self.height_scale:
            # Adjust height scale to value chosen by user
            reader_kwargs["height_scale_factor"] = self.height_scale

            # This is only possible and needed, if no height scale was given in the data file already.
            # So default is to use the factor from the file.

        # Set the unit, if not already given by file contents
        if channel.unit is None:
            reader_kwargs["unit"] = self.unit

        # Populate instrument information
        reader_kwargs["info"] = self.instrument_info

        # Eventually get topography from module "SurfaceTopography" using the given keywords
        topo = reader.topography(**reader_kwargs)
        if (
            self.fill_undefined_data_mode
            != Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING
            and topo.is_uniform
        ):
            topo = topo.interpolate_undefined_data(self.fill_undefined_data_mode)
        return topo.detrend(detrend_mode=self.detrend_mode)

    def read(self, allow_squeezed=True, return_reader=False):
        """Return a SurfaceTopography.Topography/UniformLineScan/NonuniformLineScan instance.

        This instance is guaranteed to

        - have a 'unit' property
        - have a size: .physical_sizes
        - have been scaled and detrended with the saved parameters

        It has not necessarily a pipeline with all these steps
        and a 'detrend_mode` attribute.

        This is only always the case
        if allow_squeezed=False. In this case the returned instance
        was regenerated from the original file with additional steps
        applied.

        If allow_squeezed=True, the returned topography may be read
        from a cached file which scaling and detrending already applied.

        Parameters
        ----------
        allow_squeezed: bool
            If True (default), the instance is allowed to be generated
            from a squeezed datafile which is not the original datafile.
            This is often faster than the original file format.

        return_reader: bool
            If True, return a tuple containing the topography and the reader.
            (Default: False)
        """
        #
        # Try to get topography from cache if possible
        #
        toporeader = None
        topo = None
        if allow_squeezed and self.squeezed_datafile:
            if not _IN_CELERY_WORKER_PROCESS and self.size_y is not None:
                _log.warning(
                    "You are requesting to load a (2D) topography and you are not within in a Celery worker "
                    "process. This operation is potentially slow and may require a lot of memory - do not use "
                    "`Topography.read` within the main Django server!"
                )

            # Okay, we can use the squeezed datafile, it's already there.
            toporeader = get_topography_reader(
                self.squeezed_datafile.file, format=SQUEEZED_DATAFILE_FORMAT
            )
            topo = toporeader.topography(info=self.instrument_info)
            # In the squeezed format, these things are already applied/included:
            # unit, scaling, detrending, physical sizes
            # so don't need to provide them to the .topography() method
            _log.info(
                f"Using squeezed datafile instead of original datafile for topography id {self.id}."
            )

        if topo is None:
            # Read raw file if squeezed file is unavailable
            toporeader = get_topography_reader(
                self.datafile.file, format=self.datafile_format
            )
            topo = self._read(toporeader)

        if return_reader:
            return topo, toporeader
        else:
            return topo

    topography = read  # Renaming this, mark `topography` as deprecated before v2

    def to_dict(self):
        """Create dictionary for export of metadata to json or yaml"""
        # FIXME!! This code should be moved to a separate serializer class
        result = {
            "name": self.name,
            "datafile": {
                "original": self.datafile.filename,
                "squeezed-netcdf": (
                    self.squeezed_datafile.filename if self.squeezed_datafile else None
                ),
            },
            "data_source": self.data_source,
            "has_undefined_data": self.has_undefined_data,
            "fill_undefined_data_mode": self.fill_undefined_data_mode,
            "detrend_mode": self.detrend_mode,
            "is_periodic": self.is_periodic,
            "creator": {"name": self.creator.name, "orcid": self.creator.orcid_id},
            "measurement_date": self.measurement_date,
            "description": self.description,
            "unit": self.unit,
            "size": (
                [self.size_x] if self.size_y is None else [self.size_x, self.size_y]
            ),
            "tags": [t.name for t in self.tags.order_by("name")],
            "instrument": {
                "name": self.instrument_name,
                "type": self.instrument_type,
                "parameters": self.instrument_parameters,
            },
        }
        if self.height_scale_editable:
            result["height_scale"] = self.height_scale
            # see GH 718

        return result

    def deepcopy(self, to_surface):
        """Creates a copy of this topography with all data files copied.

        Parameters
        ----------
        to_surface: Surface
            target surface

        Returns
        -------
        The copied topography.
        The reference to an instrument is not copied, it is always None.

        """
        copy = Topography.objects.get(pk=self.pk)
        copy.pk = None  # This will lead to the creation of a new instance on save
        copy.task_id = None  # We need to indicate that no tasks have run
        copy.surface = to_surface

        # Set permissions
        copy.permissions = to_surface.permissions

        # Copy datafile
        copy.datafile = self.datafile.deepcopy(to_surface.permissions)

        # Set file names of derived data to None, otherwise they will be deleted and become unavailable to the
        # original topography
        copy.thumbnail = None
        copy.squeezed_datafile = None

        # Copy tags
        copy.tags = self.tags.get_tag_list()

        # Recreate cache to recreate derived files
        _log.info(
            f"Creating cached properties of new {copy.get_subject_type()} {copy.id}..."
        )
        run_task(copy)
        copy.save()  # run_task sets the initial task state to 'pe', so we need to save

        return copy

    def _render_thumbnail(self, width=400, height=400, cmap=None, st_topo=None):
        """
        Make thumbnail image.

        Parameters
        ----------
        width : int, optional
            Maximum width of the thumbnail. (Default: 400)
        height : int, optional
            Maximum height of the thumbnail. (Default: 400)
        cmap : str or colormap, optional
            Color map for rendering the topography. (Default: None)

        Returns
        -------
        image : bytes-like
            Thumbnail image.
        """
        if st_topo is None:
            st_topo = self.read()  # SurfaceTopography instance (=st)
        image_file = io.BytesIO()
        if st_topo.dim == 1:
            dpi = 100
            fig, ax = matplotlib.pyplot.subplots(figsize=[width / dpi, height / dpi])
            x, y = st_topo.positions_and_heights()
            ax.plot(x, y, "-")
            ax.set_axis_off()
            fig.savefig(
                image_file,
                bbox_inches="tight",
                dpi=100,
                format=settings.TOPOBANK_THUMBNAIL_FORMAT,
            )
            matplotlib.pyplot.close(fig)  # probably saves memory, see issue 898
        elif st_topo.dim == 2:
            # Compute thumbnail size (keeping aspect ratio)
            sx, sy = st_topo.physical_sizes
            width2 = int(sx * height / sy)
            height2 = int(sy * width / sx)
            if width2 <= width:
                width = width2
            else:
                height = height2

            # Get heights and rescale to interval 0, 1
            heights = st_topo.heights()
            mx, mn = heights.max(), heights.min()
            heights = (heights - mn) / (mx - mn)
            # Get color map
            cmap = matplotlib.pyplot.get_cmap(cmap)
            # Convert to image
            colors = (cmap(heights.T) * 255).astype(np.uint8)
            # Remove alpha channel before writing
            PIL.Image.fromarray(colors[:, :, :3]).resize((width, height)).save(
                image_file, format=settings.TOPOBANK_THUMBNAIL_FORMAT
            )
        else:
            raise RuntimeError(
                f"Don't know how to create thumbnail for topography of dimension {st_topo.dim}."
            )
        return image_file

    def _make_thumbnail(self, st_topo=None):
        """Renews thumbnail.

        Returns
        -------
        None
        """
        if st_topo is None:
            st_topo = self.read()

        image_file = self._render_thumbnail(st_topo=st_topo)

        # Save the contents of in-memory file in Django image field
        if self.thumbnail is not None:
            self.thumbnail.delete()
        filename = f"thumbnail.{settings.TOPOBANK_THUMBNAIL_FORMAT}"
        self.thumbnail = Manifest.objects.create(
            permissions=self.permissions, filename=filename, kind="der"
        )
        self.thumbnail.save_file(ContentFile(image_file.getvalue()))

    def _make_deepzoom(self, st_topo=None):
        """Renew deep zoom images.

        Returns
        -------
        None
        """
        if st_topo is None:
            st_topo = self.read()
        if self.size_y is not None:
            # This is a topography (map), we need to create a Deep Zoom Image
            if self.deepzoom is not None:
                self.deepzoom.delete()
            self.deepzoom = Folder.objects.create(permissions=self.permissions)
            render_deepzoom(st_topo, self.deepzoom)

    def make_thumbnail(self, none_on_error=True, st_topo=None):
        """Renew thumbnail field.

        Parameters
        ----------
        none_on_error: bool
            If True (default), sets thumbnail to None if there are any errors.
            If False, exceptions have to be caught outside.

        Returns
        -------
        None

        Raises
        ------
        ThumbnailGenerationException
        """
        try:
            self._make_thumbnail(st_topo=st_topo)
        except Exception as exc:
            if none_on_error:
                self.thumbnail = None
                self.save()
                _log.warning(
                    f"Problems while generating thumbnail for topography {self.id}:"
                    f" {exc}. Saving <None> instead."
                )
                import traceback

                _log.warning(f"Traceback: {traceback.format_exc()}")
            else:
                raise ThumbnailGenerationException(self, str(exc)) from exc

    def make_deepzoom(self, none_on_error=True, st_topo=None):
        """Renew deep zoom image files.

        Parameters
        ----------
        none_on_error: bool
            If True (default), do not raise an exception if there are any errors.
            If False, exceptions have to be caught outside.

        Returns
        -------
        None

        Raises
        ------
        DZIGenerationException
        """
        try:
            self._make_deepzoom(st_topo=st_topo)
        except Exception as exc:
            if none_on_error:
                _log.warning(
                    f"Problems while generating deep zoom images for topography {self.id}: {exc}."
                )
                import traceback

                _log.warning(f"Traceback: {traceback.format_exc()}")
            else:
                raise DZIGenerationException(self, str(exc)) from exc

    def make_squeezed(self, st_topo=None, save=False):
        if st_topo is None:
            st_topo = self.read()
        with tempfile.NamedTemporaryFile() as tmp:
            # Write and upload NetCDF file
            st_topo.to_netcdf(tmp.name)
            # Delete old squeezed file
            if self.squeezed_datafile:
                self.squeezed_datafile.delete()
            # Upload new squeezed file
            dirname, basename = os.path.split(self.datafile.filename)
            orig_stem, orig_ext = os.path.splitext(basename)
            squeezed_name = f"{orig_stem}-squeezed.nc"
            self.squeezed_datafile = Manifest.objects.create(
                permissions=self.permissions,
                filename=squeezed_name,
                kind="der",
                file=File(open(tmp.name, mode="rb")),
            )
        if save:
            self.save()

    def refresh_bandwidth_cache(self, st_topo=None):
        """Renew bandwidth cache.

        Cache bandwidth for bandwidth plot in database. Data is stored in units of meter.
        """
        if st_topo is None:
            st_topo = self.read()
        if st_topo.unit is not None:
            bandwidth_lower, bandwidth_upper = st_topo.bandwidth()
            fac = get_unit_conversion_factor(st_topo.unit, "m")
            self.bandwidth_lower = fac * bandwidth_lower
            self.bandwidth_upper = fac * bandwidth_upper

            try:
                short_reliability_cutoff = (
                    st_topo.short_reliability_cutoff()
                )  # Return float or None
            except UndefinedDataError:
                # Short reliability cutoff can only be computed on topographies without undefined data
                short_reliability_cutoff = None
            if short_reliability_cutoff is not None:
                short_reliability_cutoff *= fac
            self.short_reliability_cutoff = (
                short_reliability_cutoff  # None is also saved here
            )

    @property
    def is_metadata_complete(self):
        """Check whether we have all metadata to actually read the file"""
        return (
            self.size_x is not None
            and self.unit is not None
            and self.height_scale is not None
        )

    def notify_users(self, sender, verb, description):
        self.permissions.notify_users(sender, verb, description)

    def refresh_cache(self):
        """
        Inspect datafile and renew cached properties, in particular database entries on
        resolution, size etc. and the squeezed NetCDF representation of the data.
        """
        # First check if we have a datafile
        if not self.datafile.exists():
            raise RuntimeError(
                f"Topography {self.id} does not appear to have a data file. Cannot "
                f"refresh cached data."
            )

        # Check if this is the first time we are opening this file...
        populate_initial_metadata = self.data_source is None

        if populate_initial_metadata:
            # Notify users that a new file has been uploaded
            self.notify_users(
                self.creator,
                "create",
                f"User '{self.creator}' added the measurement '{self.name}' to "
                f"digital surface twin '{self.surface.name}'.",
            )

        # Populate datafile information in the database.
        # (We never load the topography in the web server, so we don't know this until
        # the Celery task refreshes the cache. Fields that are undefined are
        # autodetected.)
        _log.info(f"Caching properties of topography {self.id}...")

        # Open topography file
        reader = get_topography_reader(self.datafile.file)
        self.datafile_format = reader.format()

        # Update channel names
        self.channel_names = [
            (channel.name, _get_unit(channel)) for channel in reader.channels
        ]

        # Idiot check
        if len(self.channel_names) == 0:
            raise RuntimeError(
                f"Datafile of measurement '{self.name}' could be opened, but it "
                "appears to contain no valid data."
            )

        # Check whether the user already selected a (valid) channel, if not set to
        # default channel
        if (
            self.data_source is None
            or self.data_source < 0
            or self.data_source >= len(self.channel_names)
        ):
            self.data_source = reader.default_channel.index

        # Select channel
        channel = reader.channels[self.data_source]

        #
        # Look for necessary metadata. We override values in the database. This may be
        # necessary if the underlying reader changes (e.g. through bug fixes).
        #

        # Populate resolution information in the database
        if channel.dim == 1:
            (n,) = channel.nb_grid_pts
            self.resolution_x = int(n)
            self.resolution_y = None  # This indicates that this is a line scan
        elif channel.dim == 2:
            self.resolution_x, self.resolution_y = (int(n) for n in channel.nb_grid_pts)
        else:
            # This should not happen
            raise NotImplementedError(
                f"Cannot handle topographies of dimension {channel.dim}."
            )

        # Populate size information in the database
        if channel.physical_sizes is None:
            # Data file *does not* provide size information; the user must provide it
            self.size_editable = True
        else:
            # Data file *does* provide size information; the user cannot override it
            self.size_editable = False
            # Reset size information here
            if channel.dim == 1:
                (s,) = channel.physical_sizes
                self.size_x = float(s)
                self.size_y = None
            elif channel.dim == 2:
                self.size_x, self.size_y = (float(s) for s in channel.physical_sizes)
            else:
                # This should not happen
                raise NotImplementedError(
                    f"Cannot handle topographies of dimension {channel.dim}."
                )

        # Populate unit information in the database
        if channel.unit is None:
            # Data file *does not* provide unit information; the user must provide it
            self.unit_editable = True
        else:
            # Data file *does* provide unit information; the user cannot override it
            self.unit_editable = False
            # Reset unit information here
            if isinstance(channel.unit, tuple):
                raise NotImplementedError(
                    f"Data channel '{channel.name}' contains information that is not "
                    "height."
                )
            self.unit = channel.unit

        # Populate height scale information in the database
        if channel.height_scale_factor is None:
            # Data file *does not* provide height scale information; the user must provide it
            self.height_scale_editable = True
        else:
            # Data file *does* provide height scale information; the user cannot override it
            self.height_scale_editable = False
            # Reset unit information here
            self.height_scale = channel.height_scale_factor

        # Populate information on periodicity
        if not channel.is_uniform:
            # This is a nonuniform line scan that does not support periodicity
            self.is_periodic_editable = False
            self.is_periodic = False
        elif self.is_periodic is None:
            # This is a uniform line scan or map, periodicity is supported
            self.is_periodic_editable = True
            self.is_periodic = channel.is_periodic

        #
        # We now look for optional metadata. Only import it from the file on first read,
        # otherwise we may override what the user has painfully adjusted when refreshing
        # the cache.
        #

        if populate_initial_metadata:
            # Measurement time
            try:
                self.measurement_date = channel.info["acquisition_time"]
            except:  # noqa: E722
                pass

            # Instrument name
            try:
                self.instrument_name = channel.info["instrument"]["name"]
            except:  # noqa: E722
                pass

            # Instrument parameters
            try:
                self.instrument_parameters = channel.info["instrument"]["parameters"]
                if "tip_radius" in self.instrument_parameters:
                    self.instrument_type = self.INSTRUMENT_TYPE_CONTACT_BASED
                elif "resolution" in self.instrument_parameters:
                    self.instrument_type = self.INSTRUMENT_TYPE_MICROSCOPE_BASED
            except:  # noqa: E722
                self.instrument_type = self.INSTRUMENT_TYPE_UNDEFINED

        # Read the file if metadata information is complete
        if self.is_metadata_complete:
            _log.info(f"Metadata of {self} is complete. Generating images.")
            st_topo = self._read(reader)

            # Check whether original data file has undefined data point and update
            # database accordingly. (`has_undefined_data` can be undefined if
            # undetermined.)
            self.has_undefined_data = bool(st_topo.has_undefined_data)

            # Refresh other cached quantities
            self.refresh_bandwidth_cache(st_topo=st_topo)
            self.make_thumbnail(st_topo=st_topo)
            self.make_deepzoom(st_topo=st_topo)
            self.make_squeezed(st_topo=st_topo)

        # Save dataset
        self.save()

        # Send signal
        _log.debug(f"Sending `post_refresh_cache` signal from {self}...")
        post_refresh_cache.send(sender=Topography, instance=self)

    def get_undefined_data_status(self):
        """Get human-readable description about status of undefined data as string."""
        s = self.HAS_UNDEFINED_DATA_DESCRIPTION[self.has_undefined_data]
        if (
            self.fill_undefined_data_mode
            == Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING
        ):
            s += " No correction of undefined data is performed."
        elif (
            self.fill_undefined_data_mode
            == Topography.FILL_UNDEFINED_DATA_MODE_HARMONIC
        ):
            s += (
                " Undefined/missing values are filled in with values obtained from a "
                "harmonic interpolation."
            )
        return s

    def task_worker(self):
        self.refresh_cache()
