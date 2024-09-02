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

from ..authorization.mixins import PermissionMixin
from ..authorization.models import PermissionSet
from ..files.models import Folder
from ..manager.models import Surface, Tag, Topography
from ..supplib.dict import load_split_dict, store_split_dict
from ..taskapp.models import Configuration, TaskStateModel
from .registry import get_implementation

_log = logging.getLogger(__name__)

RESULT_FILE_BASENAME = "result"


class AnalysisSubject(models.Model):
    """Analysis subject, which can be either a Tag, a Topography or a Surface"""

    tag = models.ForeignKey(Tag, null=True, blank=True, on_delete=models.CASCADE)
    topography = models.ForeignKey(
        Topography, null=True, blank=True, on_delete=models.CASCADE
    )
    surface = models.ForeignKey(
        Surface, null=True, blank=True, on_delete=models.CASCADE
    )

    @classmethod
    def create(cls, subject):
        tag = topography = surface = None
        if isinstance(subject, Tag):
            tag = subject
        elif isinstance(subject, Topography):
            topography = subject
        elif isinstance(subject, Surface):
            surface = subject
        else:
            raise ValueError(
                "`subject` argument must be of type `Tag`, `Topography` or `Surface`."
            )
        return cls.objects.create(tag=tag, topography=topography, surface=surface)

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
    # Permissions
    #
    permissions = models.ForeignKey(PermissionSet, on_delete=models.CASCADE, null=True)

    #
    # Analysis parameters
    #

    # Actual implementation of the analysis as a Python function
    function = models.ForeignKey("AnalysisFunction", on_delete=models.CASCADE)

    # Definition of the subject
    subject_dispatch = models.OneToOneField(
        AnalysisSubject, null=True, on_delete=models.CASCADE
    )

    # Keyword arguments passed to the Python analysis function
    kwargs = models.JSONField(default=dict)

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
        return "Task {} with state {}".format(
            self.task_id, self.get_task_state_display()
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
        if self._result is not None:
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
        return self.subject_dispatch.get()

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
        if self._result_cache is None:
            self._result_cache = load_split_dict(
                self.storage_prefix, RESULT_FILE_BASENAME
            )
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
        if self._result_metadata_cache is None:
            self._result_metadata_cache = json.load(
                default_storage.open(
                    f"{self.storage_prefix}/{RESULT_FILE_BASENAME}.json"
                )
            )
        return self._result_metadata_cache

    @property
    def result_file_name(self):
        """Returns name of the result file in storage backend as string."""
        return f"{self.storage_prefix}/{RESULT_FILE_BASENAME}.json"

    @property
    def has_result_file(self):
        """Returns True if result file exists in storage backend, else False."""
        return default_storage.exists(self.result_file_name)

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

    @property
    def storage_files(self):
        """Return all file names in analysis id directory.

        List of files names ['<file_prefix_name>/file'].
        If storage is on filesystem, the prefix should correspond
        to a real directory.
        """
        if self.id is None:
            raise RuntimeError(
                "This `Analysis` does not have an id yet; the storage file names is "
                "not yet known."
            )
        try:
            dir_tuple = default_storage.listdir(self.storage_prefix)
            file_lists = dir_tuple[1]
            return [f"{self.storage_prefix}/{file_name}" for file_name in file_lists]
        # FIXME!!! InMemoryStorage raise a PathDoesNotExist error, but I don't know
        # how to check for this generically
        except:  # noqa: E722
            return []

    def get_related_surfaces(self):
        """Returns sequence of surface instances related to the subject of this analysis."""
        return self.subject.get_related_surfaces()

    def get_implementation(self):
        return self.function.get_implementation()

    def authorize_user(self, user):
        """
        Returns an exception if given user should not be able to see this analysis.
        """
        # Check availability of analysis function
        if not self.get_implementation().has_permission(user):
            raise PermissionError(
                f"User {user} is not allowed to use this analysis function."
            )

        # Check if the user can access this analysis
        super().authorize_user(user, "view")

        # Double check access rights to the underlying measurements
        if not all(s.has_permission(user, "view") for s in self.get_related_surfaces()):
            raise PermissionError(
                f"User {user} is not allowed to access some of the surfaces that are "
                "the subject of the analysis."
            )

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

    def eval_self(self, kwargs=None, progress_recorder=None):
        if self.is_tag_related:
            users = self.permissions.user_permissions.all()
            if users.count() != 1:
                raise PermissionError(
                    "This is a tag analysis, which should only be assigned to a single "
                    "user."
                )
            self.subject.authorize_user(users.first().user, "view")

        return self.function.eval(
            self.subject,
            kwargs=kwargs,
            folder=self.folder,
            progress_recorder=progress_recorder,
        )

    def submit_again(self):
        self.function.submit_again(self)


class AnalysisFunction(models.Model):
    """
    A convenience wrapper around the AnalysisImplementation that has representation in the
    SQL database.
    """

    name = models.CharField(
        max_length=80, help_text="A human-readable name.", unique=True
    )

    def __str__(self):
        return self.name

    def get_implementation(self):
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

    def has_permission(self, user: settings.AUTH_USER_MODEL):
        """
        Check if this analysis function is available to the user. The function
        is available to `user` if it is available for any of the `models`
        specified.
        """
        return self.get_implementation().has_permission(user)

    def get_default_kwargs(self):
        """
        Return default keyword arguments as a dictionary.
        """
        return self.get_implementation().Parameters().dict()

    def validate_kwargs(self, kwargs):
        raise self.get_implementation().Parameters().dict()

    def eval(self, subject, kwargs, folder, progress_recorder=None):
        """
        First argument is the subject of the analysis (`Surface`, `Topography` or `Tag`).
        """
        runner_class = self.get_implementation()
        runner = runner_class(kwargs)
        return runner.eval(subject, folder, progress_recorder)

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
        kwargs = self.get_implementation().clean_kwargs(kwargs)

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
                subject_dispatch=AnalysisSubject.create(subject),
                function=self,
                task_state=Analysis.PENDING,
                kwargs=kwargs,
                folder=folder,
            )
            analysis.grant_permission(user, "view")

            # Send task to the queue if the analysis has been created
            # Note: on_commit will not execute in tests, unless transaction=True is
            # added to pytest.mark.django_db
            def do_submit():
                from .tasks import perform_analysis

                _log.debug(f"Submitting task for analysis {analysis.id}...")
                perform_analysis.delay(analysis.id)

            transaction.on_commit(do_submit)
        else:
            # There seem to be viable analyses. Fetch the latest one.
            analysis = existing_analyses.order_by("start_time").last()
            # Grant access to current user
            analysis.grant_permission(user, "view")

        return analysis

    def submit_again(self, analysis: Analysis):
        """
        Delete existing analysis and recreate and submit with same arguments and user.

        Parameters
        ----------
        analysis: Analysis
            Analysis instance to be renewed.
        use_default_kwargs: boolean
            If True, use default arguments of the corresponding analysis function implementation.
            If False (default), use the keyword arguments of the given analysis.

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
        analysis.save()

        # Send task to the queue if the analysis has been created
        # Note: on_commit will not execute in tests, unless transaction=True is
        # added to pytest.mark.django_db
        def do_submit():
            from .tasks import perform_analysis

            _log.debug(f"Submitting task for analysis {analysis.id}...")
            perform_analysis.delay(analysis.id)

        transaction.on_commit(do_submit)
        return analysis
