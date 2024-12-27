"""
Models related to analyses.
"""

import json
import logging
from typing import Union

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.reverse import reverse

from ..authorization.mixins import PermissionMixin
from ..authorization.models import AuthorizedManager, PermissionSet
from ..files.models import Folder, Manifest
from ..manager.models import Surface, Tag, Topography
from ..supplib.dict import load_split_dict, store_split_dict
from ..taskapp.models import Configuration, TaskStateModel
from .registry import get_implementation

_log = logging.getLogger(__name__)

RESULT_FILE_BASENAME = "result"


class AnalysisSubjectManager(models.Manager):
    def create(self, subject=None, *args, **kwargs):
        if subject:
            if isinstance(subject, Tag):
                kwargs["tag"] = subject
            elif isinstance(subject, Topography):
                kwargs["topography"] = subject
            elif isinstance(subject, Surface):
                kwargs["surface"] = subject
            else:
                raise ValueError(
                    "`subject` argument must be of type `Tag`, `Topography` or "
                    "`Surface`."
                )
        return super().create(*args, **kwargs)


class AnalysisSubject(models.Model):
    """Analysis subject, which can be either a Tag, a Topography or a Surface"""

    objects = AnalysisSubjectManager()

    tag = models.ForeignKey(Tag, null=True, blank=True, on_delete=models.CASCADE)
    topography = models.ForeignKey(
        Topography, null=True, blank=True, on_delete=models.CASCADE
    )
    surface = models.ForeignKey(
        Surface, null=True, blank=True, on_delete=models.CASCADE
    )

    @staticmethod
    def Q(subject):
        if isinstance(subject, Tag):
            return models.Q(subject_dispatch__tag_id=subject.id)
        elif isinstance(subject, Topography):
            return models.Q(subject_dispatch__topography_id=subject.id)
        elif isinstance(subject, Surface):
            return models.Q(subject_dispatch__surface_id=subject.id)
        else:
            raise ValueError(
                "`subject` argument must be of type `Tag`, `Topography` or `Surface`, "
                f"not {type(subject)}."
            )

    def Qs(user, subjects):
        tag_ids = []
        topography_ids = []
        surface_ids = []
        for subject in subjects:
            if isinstance(subject, Tag):
                tag_ids += [subject.id]
            elif isinstance(subject, Topography):
                topography_ids += [subject.id]
            elif isinstance(subject, Surface):
                surface_ids += [subject.id]
            else:
                raise ValueError(
                    "`subject` argument must be of type `Tag`, `Topography` or `Surface`, "
                    f"not {type(subject)}."
                )
        query = None
        if len(tag_ids) > 0:
            query = models.Q(subject_dispatch__tag_id__in=tag_ids) & Q(
                permissions__user_permissions__user=user
            )
        elif isinstance(subject, Topography):
            q = models.Q(subject_dispatch__topography_id=topography_ids)
            query = query | q if query else q
        elif isinstance(subject, Surface):
            q = models.Q(subject_dispatch__surface_id=surface_ids)
            query = query | q if query else q
        return query

    def get(self):
        if self.tag is not None:
            return self.tag
        elif self.topography is not None:
            return self.topography
        elif self.surface is not None:
            return self.surface
        else:
            raise RuntimeError(
                "Database corruption: All subjects appear to be None/null."
            )

    def save(self, *args, **kwargs):
        if (
            sum(
                [
                    self.tag is not None,
                    self.topography is not None,
                    self.surface is not None,
                ]
            )
            != 1
        ):
            raise ValidationError("Only of of tag, topography or tag can be defined.")
        super().save(*args, **kwargs)


class Analysis(PermissionMixin, TaskStateModel):
    """
    Concrete Analysis with state, function reference, arguments, and results.

    Additionally, it saves the configuration which was present when
    executing the analysis, i.e. versions of the main libraries needed.
    """

    #
    # Manager
    #
    objects = AuthorizedManager()

    #
    # Permissions
    #
    permissions = models.ForeignKey(PermissionSet, on_delete=models.CASCADE, null=True)

    #
    # Analysis parameters
    #

    # Actual implementation of the analysis as a Python function
    function = models.ForeignKey(
        "AnalysisFunction", on_delete=models.SET_NULL, null=True
    )

    # Definition of the subject
    subject_dispatch = models.OneToOneField(
        AnalysisSubject, on_delete=models.CASCADE, null=True
    )

    # Unique, user-specified name
    name = models.TextField(null=True)

    # Keyword arguments passed to the Python analysis function
    kwargs = models.JSONField(default=dict)

    # Dependencies
    dependencies = models.JSONField(default=dict)

    # Results
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, null=True)

    # Bibliography
    dois = models.JSONField(default=list)

    # Server configuration (version information)
    configuration = models.ForeignKey(
        Configuration, null=True, on_delete=models.SET_NULL
    )

    class Meta:
        verbose_name_plural = "analyses"

    def __init__(self, *args, result=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._result = result  # temporary storage
        self._result_cache = result  # cached result
        self._result_metadata_cache = None  # cached toplevel result file

    def __str__(self):
        return (
            f"Analysis {self.id} on subject {self.subject} with state {self.task_state}"
        )

    def save(self, *args, **kwargs):
        """
        Save the analysis instance to the database.

        This method performs the following steps:
        1. Sets the creation time if the instance does not have an ID.
        2. Calls the parent class's save method to save the instance.
        3. Stores the result dictionary in the storage backend if it is provided.

        Parameters
        ----------
        *args : tuple
            Variable length argument list.
        **kwargs : dict
            Arbitrary keyword arguments.
        """
        if not self.id:
            self.creation_time = timezone.now()
        super().save(*args, **kwargs)
        # If a result dict is given on input, we store it. However, we can only do this
        # once we have an id. This happens during testing.
        if self._result is not None and self.folder is not None:
            store_split_dict(self.folder, RESULT_FILE_BASENAME, self._result)
            self._result = None

    @property
    def subject(self):
        """
        Return the subject of the analysis, which can be a Tag, a Topography, or a
        Surface.

        Returns
        -------
        Tag, Topography, or Surface
            The subject of the analysis.
        """
        if self.subject_dispatch:
            return self.subject_dispatch.get()
        else:
            return None

    @property
    def result(self):
        """
        Return the result object or None if there is nothing yet.

        This property checks if the result cache is empty. If it is, it loads the result
        from the storage backend using the storage prefix and result file basename.
        The loaded result is then cached for future access.

        Returns
        -------
        dict or None
            The result object if available, otherwise None.
        """
        self.fix_folder()
        if self._result_cache is None:
            self._result_cache = load_split_dict(self.folder, RESULT_FILE_BASENAME)
        return self._result_cache

    @property
    def result_metadata(self):
        """
        Return the toplevel result object without series data, i.e. the raw result.json
        without unsplitting it.

        This property checks if the result metadata cache is empty. If it is, it loads
        the metadata from the storage backend using the storage prefix and result file
        basename. The loaded metadata is then cached for future access.

        Returns
        -------
        dict
            The toplevel result object without series data.
        """
        self.fix_folder()
        if self._result_metadata_cache is None:
            self._result_metadata_cache = json.load(
                self.folder.open_file(f"{RESULT_FILE_BASENAME}.json")
            )
        return self._result_metadata_cache

    @property
    def result_file_name(self):
        """Returns name of the result file in storage backend as string."""
        return f"{RESULT_FILE_BASENAME}.json"

    @property
    def has_result_file(self):
        """Returns True if result file exists in storage backend, else False."""
        self.fix_folder()
        return self.folder.exists(self.result_file_name)

    def get_absolute_url(self, request=None):
        """URL of API endpoint for this tag"""
        return reverse(
            "analysis:result-detail", kwargs=dict(pk=self.id), request=request
        )

    @property
    def storage_prefix(self):
        """Return prefix used for storage.

        Looks like a relative path to a directory.
        If storage is on filesystem, the prefix should correspond
        to a real directory.
        """
        if self.id is None:
            raise RuntimeError(
                "This `Analysis` does not have an id yet; the storage prefix is not "
                "yet known."
            )
        return "analyses/{}".format(self.id)

    def fix_folder(self):
        """
        Fill folder, if yet unfilled.

        List of files names ['<file_prefix_name>/file'].
        If storage is on filesystem, the prefix should correspond
        to a real directory.
        """
        if self.folder:
            return
        if self.id is None:
            raise RuntimeError(
                "This `Analysis` does not have an id yet; the storage file names is "
                "not yet known."
            )
        self.folder = Folder.objects.create(
            permissions=self.permissions, read_only=True
        )
        self.save(update_fields=["folder"])
        dir_tuple = default_storage.listdir(self.storage_prefix)
        for filename in dir_tuple[1]:
            manifest = Manifest.objects.create(
                permissions=self.permissions,
                folder=self.folder,
                filename=filename,
                kind="der",
            )
            manifest.file.name = f"{self.storage_prefix}/{filename}"
            manifest.save(update_fields=["file"])

    def get_related_surfaces(self):
        """Returns sequence of surface instances related to the subject of this analysis."""
        return self.subject.get_related_surfaces()

    @property
    def implementation(self):
        return self.function.implementation

    def authorize_user(self, user: settings.AUTH_USER_MODEL):
        """
        Returns an exception if given user should not be able to see this analysis.
        """
        # Check availability of analysis function
        if not self.implementation.has_permission(user):
            raise PermissionError(
                f"User {user} is not allowed to use this analysis function."
            )

        if self.is_tag_related:
            # Check if the user can access this analysis
            super().authorize_user(user, "view")

        # Check if user can access the subject of this analysis
        self.subject.authorize_user(user, "view")
        self.grant_permission(user, "view")  # Required so files can be accessed

    @property
    def is_topography_related(self):
        """Returns True, if the analysis subject is a topography, else False."""
        return self.subject_dispatch.topography is not None

    @property
    def is_surface_related(self):
        """Returns True, if the analysis subject is a surface, else False."""
        return self.subject_dispatch.surface is not None

    @property
    def is_tag_related(self):
        """Returns True, if the analysis subject is a tag, else False."""
        return self.subject_dispatch.tag is not None

    def eval_self(self, **auxiliary_kwargs):
        if self.is_tag_related:
            users = self.permissions.user_permissions.all()
            if users.count() != 1:
                raise PermissionError(
                    "This is a tag analysis, which should only be assigned to a single "
                    "user."
                )
            self.subject.authorize_user(users.first().user, "view")

        return self.function.eval(
            self,
            **auxiliary_kwargs,
        )

    def submit_again(self):
        return self.function.submit_again(self)

    def set_name(self, name: str):
        """
        Setting a name essentially saves the analysis, i.e. it is no longer deleted
        when the analysis subject is deleted.
        """
        self.name = name
        self.subject_dispatch = None
        self.save()


class AnalysisFunction(models.Model):
    """
    A convenience wrapper around the AnalysisImplementation that has representation in the
    SQL database.
    """

    display_name = models.CharField(
        max_length=80, help_text="A human-readable name.", unique=True
    )

    def __str__(self):
        return self.name

    @property
    def implementation(self):
        """Return implementation for given subject type.

        Returns
        -------
        AnalysisImplementation instance

        Raises
        ------
        ImplementationMissingException
            in case the implementation is missing
        """
        return get_implementation(self.name)

    def has_implementation(self, model_class):
        """
        Returns whether implementation function for a specific subject model exists
        """
        impl = self.implementation
        if impl is not None:
            return impl.has_implementation(model_class)
        return False

    def has_permission(self, user: settings.AUTH_USER_MODEL):
        """
        Check if this analysis function is available to the user. The function
        is available to `user` if it is available for any of the `models`
        specified.
        """
        impl = self.implementation
        if impl is not None:
            return impl.has_permission(user)
        return False

    def get_default_kwargs(self):
        """
        Return default keyword arguments as a dictionary.
        """
        return self.implementation.Parameters().dict()

    def get_kwargs_schema(self):
        """
        JSON schema describing the keyword arguments.
        """
        return self.implementation.Parameters().model_json_schema()["properties"]

    def clean_kwargs(self, kwargs: Union[dict, None], fill_missing: bool = True):
        """
        Validate keyword arguments (parameters) and return validated dictionary

        Parameters
        ----------
        kwargs: Union[dict, None]
            Keyword arguments
        fill_missing: bool, optional
            Fill missing keys with default values. (Default: True)

        Raises
        ------
        pydantic.ValidationError if validation fails
        """
        return self.implementation.clean_kwargs(kwargs, fill_missing=fill_missing)

    def get_dependencies(self, analysis):
        return self.implementation(**analysis.kwargs).get_dependencies(analysis)

    def eval(self, analysis, **auxiliary_kwargs):
        """
        First argument is the subject of the analysis (`Surface`, `Topography` or `Tag`).
        """
        runner = self.implementation(**analysis.kwargs)
        return runner.eval(analysis, **auxiliary_kwargs)

    def submit(
        self,
        user: settings.AUTH_USER_MODEL,
        subject: Union[Tag, Surface, Topography],
        kwargs: dict = None,
        force_submit: bool = False,
    ):
        """
        user : topobank.users.models.User
            Users which should see the analysis.
        subject : Tag or Topography or Surface
            Instance which will be subject of the analysis (first argument of analysis
            function).
        kwargs : dict, optional
            Keyword arguments for the function which should be saved to database. If
            None is given, the default arguments for the given analysis function are
            used. The default arguments are the ones used in the function
            implementation (python function). (Default: None)
        force_submit : bool, optional
            Submit even if analysis already exists. (Default: False)
        """
        # Check if user can actually access the subject
        subject.authorize_user(user, "view")

        # Make sure the parameters are correct and fill in missing values from defaults
        kwargs = self.clean_kwargs(kwargs)

        # Query for all existing analyses with the same parameters
        q = AnalysisSubject.Q(subject) & Q(function=self) & Q(kwargs=kwargs)

        # If subject is tag, we need to restrict this to the current user because those
        # analyses cannot be shared
        if isinstance(subject, Tag):
            q &= Q(permissions__user_permissions__user=user)

        # All existing analyses
        existing_analyses = Analysis.objects.filter(q)

        # Analyses, excluding those that have failed or that have not been submitted
        # to the task queue for some reason (state "no"t run)
        successful_or_running_analyses = existing_analyses.filter(
            task_state__in=[
                Analysis.PENDING,
                Analysis.RETRY,
                Analysis.STARTED,
                Analysis.SUCCESS,
            ]
        )

        # We submit a new analysis only if we are either forced to do so or if there is
        # no analysis with the same parameter pending, running or successfully completed.
        if force_submit or successful_or_running_analyses.count() == 0:
            # Delete *all* existing analyses (which now may only contain failed ones)
            existing_analyses.delete()

            # New analysis needs its own permissions
            permissions = PermissionSet.objects.create()
            permissions.grant_for_user(user, "view")  # analysis can never be edited

            # Folder will store results
            folder = Folder.objects.create(permissions=permissions, read_only=True)

            # Create new entry in the analysis table and grant access to current user
            analysis = Analysis.objects.create(
                permissions=permissions,
                subject_dispatch=AnalysisSubject.objects.create(subject),
                function=self,
                task_state=Analysis.PENDING,
                kwargs=kwargs,
                folder=folder,
            )

            # Send task to the queue if the analysis has been created
            # Note: on_commit will not execute in tests, unless transaction=True is
            # added to pytest.mark.django_db
            def do_submit():
                from .tasks import perform_analysis

                _log.debug(f"Submitting task for analysis {analysis.id}...")
                perform_analysis.delay(analysis.id, force_submit)

            transaction.on_commit(do_submit)
        else:
            # There seem to be viable analyses. Fetch the latest one.
            analysis = existing_analyses.order_by("start_time").last()
            # Grant access to current user
            analysis.grant_permission(user, "view")

        return analysis

    def submit_again(self, analysis: Analysis):
        """
        Submit analysis with same arguments and users.

        Parameters
        ----------
        analysis: Analysis
            Analysis instance to be renewed.

        Returns
        -------
        New analysis object.
        """
        _log.info(
            f"Renewing analysis {analysis.id}: Users "
            f"{[user for user, allow in analysis.permissions.get_users()]}, "
            f"function {self}, subject {analysis.subject}, kwargs: {analysis.kwargs}"
        )
        analysis.task_state = Analysis.PENDING
        analysis.task_error = ""
        analysis.task_traceback = None
        analysis.save()

        # Send task to the queue if the analysis has been created
        # Note: on_commit will not execute in tests, unless transaction=True is
        # added to pytest.mark.django_db
        def do_submit():
            from .tasks import perform_analysis

            _log.debug(f"Submitting task for analysis {analysis.id}...")
            perform_analysis.delay(analysis.id, True)

        transaction.on_commit(do_submit)
        return analysis
