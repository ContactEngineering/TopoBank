"""
Models related to analyses.
"""
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage

import pickle
import json

from ..utils import store_split_dict, load_split_dict
from topobank.users.models import User

from .registry import ImplementationMissingAnalysisFunctionException, AnalysisRegistry, AnalysisFunctionImplementation

RESULT_FILE_BASENAME = 'result'


class Dependency(models.Model):
    """A dependency of analysis results, e.g. "SurfaceTopography", "topobank"
    """
    # this is used with "import":
    import_name = models.CharField(max_length=30, unique=True)

    def __str__(self):
        return self.import_name


class Version(models.Model):
    """
    A specific version of a dependency.
    Part of a configuration.
    """
    dependency = models.ForeignKey(Dependency, on_delete=models.CASCADE)

    major = models.SmallIntegerField()
    minor = models.SmallIntegerField()
    micro = models.SmallIntegerField(null=True)

    # the following can be used to indicate that this
    # version should not be used any more / or the analyses
    # should be recalculated
    # valid = models.BooleanField(default=True)

    # TODO After upgrade to Django 2.2, use contraints: https://docs.djangoproject.com/en/2.2/ref/models/constraints/
    class Meta:
        unique_together = (('dependency', 'major', 'minor', 'micro'),)

    def number_as_string(self):
        x = f"{self.major}.{self.minor}"
        if self.micro is not None:
            x += f".{self.micro}"
        return x

    def __str__(self):
        return f"{self.dependency} {self.number_as_string()}"


class Configuration(models.Model):
    """For keeping track which versions were used for an analysis.
    """
    valid_since = models.DateTimeField(auto_now_add=True)
    versions = models.ManyToManyField(Version)

    def __str__(self):
        versions = [ str(v) for v in self.versions.all()]
        return f"Valid since: {self.valid_since}, versions: {versions}"


class Analysis(models.Model):
    """Concrete Analysis with state, function reference, arguments, and results.

    Additionally, it saves the configuration which was present when
    executing the analysis, i.e. versions of the main libraries needed.
    """
    PENDING = 'pe'
    STARTED = 'st'
    RETRY = 're'
    FAILURE = 'fa'
    SUCCESS = 'su'

    TASK_STATE_CHOICES = (
        (PENDING, 'pending'),
        (STARTED, 'started'),
        (RETRY, 'retry'),
        (FAILURE, 'failure'),
        (SUCCESS, 'success'),
    )

    function = models.ForeignKey('AnalysisFunction', on_delete=models.CASCADE)

    # Definition of the subject
    subject_type = models.ForeignKey(ContentType, null=True, on_delete=models.CASCADE)
    subject_id = models.PositiveIntegerField(null=True)
    subject = GenericForeignKey('subject_type', 'subject_id')

    # According to github #208, each user should be able to see analysis with parameters chosen by himself
    users = models.ManyToManyField(User)

    kwargs = models.BinaryField()  # for pickle

    task_id = models.CharField(max_length=155, unique=True, null=True)
    task_state = models.CharField(max_length=7,
                                  choices=TASK_STATE_CHOICES)

    start_time = models.DateTimeField(null=True)
    end_time = models.DateTimeField(null=True)

    # Bibliography
    dois = models.JSONField(default=[])

    configuration = models.ForeignKey(Configuration, null=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name_plural = "analyses"

    def __init__(self, *args, result=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._result = result  # temporary storage
        self._result_cache = result  # cached result
        self._result_metadata_cache = None  # cached toplevel result file

    def __str__(self):
        return "Task {} with state {}".format(self.task_id, self.get_task_state_display())

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # If a result dict is given on input, we store it. However, we can only do this once we have an id.
        # This happens during testing.
        if self._result is not None:
            store_split_dict(self.storage_prefix, RESULT_FILE_BASENAME, self._result)
            self._result = None

    def duration(self):
        """Returns duration of computation or None if not finished yet.

        Does not take into account the queue time.

        :return: Returns datetime.timedelta or None
        """
        if self.end_time is None:
            return None

        return self.end_time-self.start_time

    def get_kwargs_display(self):
        return str(pickle.loads(self.kwargs))

    @property
    def result(self):
        """Return result object or None if there is nothing yet."""
        if self._result_cache is None:
            self._result_cache = load_split_dict(self.storage_prefix, RESULT_FILE_BASENAME)
        return self._result_cache

    @property
    def result_metadata(self):
        """Return the toplevel result object without series data, i.e. the raw result.json without unsplitting it"""
        if self._result_metadata_cache is None:
            self._result_metadata_cache = json.load(
                default_storage.open(f'{self.storage_prefix}/{RESULT_FILE_BASENAME}.json')
            )
        return self._result_metadata_cache

    @property
    def result_file_name(self):
        """Returns name of the result file in storage backend as string."""
        return f'{self.storage_prefix}/{RESULT_FILE_BASENAME}.json'

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
            raise RuntimeError('This `Analysis` does not have an id yet; the storage prefix is not yet known.')
        return "analyses/{}".format(self.id)

    @property
    def related_surface(self):
        """Returns surface instance related to this analysis."""
        subject = self.subject
        if hasattr(subject, 'surface'):
            surface = subject.surface
        else:
            surface = subject
        return surface

    def is_visible_for_user(self, user):
        """Returns True if given user should be able to see this analysis."""
        allowed_to_view_surface = user.has_perm("view_surface", self.related_surface)
        allowed_to_use_implementation = self.function.get_implementation(self.subject_type).is_available_for_user(user)
        return allowed_to_use_implementation and allowed_to_view_surface

    @property
    def is_topography_related(self):
        """Returns True, if analysis is related to a specific topography, else False.
        """
        topography_ct = ContentType.objects.get_by_natural_key('manager', 'topography')
        return topography_ct == self.subject_type

    @property
    def is_surface_related(self):
        """Returns True, if analysis is related to a specific surface, else False.
        """
        surface_ct = ContentType.objects.get_by_natural_key('manager', 'surface')
        return surface_ct == self.subject_type


class AnalysisFunction(models.Model):
    """Represents an analysis function from a user perspective.

    Examples:
        - name: 'Height distribution'
        - name: 'Contact mechanics'

    These functions are referenced by the analyses. Each function "knows"
    how to find the appropriate implementation for given arguments.
    """
    name = models.CharField(max_length=80, help_text="A human-readable name.", unique=True)

    def __str__(self):
        return self.name

    def get_implementation(self, subject_type):
        """Return implementation for given subject type.

        Parameters
        ----------
        subject_type: ContentType
            Type of first argument of analysis function

        Returns
        -------
        AnalysisFunctionImplementation instance

        Raises
        ------
        ImplementationMissingException
            in case the implementation is missing
        """
        return AnalysisRegistry().get_implementation(self.name, subject_type=subject_type)

    def python_function(self, subject_type):
        """Return function for given first argument type.

        Parameters
        ----------
        subject_type: ContentType
            Type of first argument of analysis function

        Returns
        -------
        Python function which implements the analysis, where first argument must be the given type,
        and there maybe more arguments needed.

        Raises
        ------
        ImplementationMissingException
            if implementation for given subject type does not exist
        """
        return AnalysisRegistry().get_implementation(self.name, subject_type).python_function()

    def get_implementation_types(self):
        """Return list of content types for which this function is implemented.
        """
        return AnalysisRegistry().get_implementation_types(self.name)

    def is_implemented_for_type(self, subject_type):
        """Returns True if function is implemented for given content type, else False"""
        try:
            self.python_function(subject_type)
        except ImplementationMissingAnalysisFunctionException:
            return False
        return True

    def get_default_kwargs(self, subject_type):
        """Return default keyword arguments as dict.

        Administrative arguments like
        'storage_prefix' and 'progress_recorder'
        which are common to all functions, are excluded.

        Parameters
        ----------
        subject_type: ContentType
            Type of first argument of analysis function

        Returns
        -------

        dict
        """
        return self.get_implementation(subject_type).get_default_kwargs()

    def eval(self, subject, **kwargs):
        """Call appropriate python function.

        First argument is the subject of the analysis (topography or surface),
        all other arguments are keyword arguments.
        """
        if subject is None:
            raise ValueError(f"Cannot evaluate analysis function '{self.name}' with None as subject.")
        try:
            subject_type = ContentType.objects.get_for_model(subject)
        except Exception as exc:
            raise ValueError(f"Cannot find content type for subject '{subject}'.")
        return self.get_implementation(subject_type).eval(subject, **kwargs)


class AnalysisCollection(models.Model):
    """A collection of analyses which belong together for some reason."""
    name = models.CharField(max_length=160)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    analyses = models.ManyToManyField(Analysis)
    combined_task_state = models.CharField(max_length=7,
                                           choices=Analysis.TASK_STATE_CHOICES)

    # We have a manytomany field, because an analysis could be part of multiple collections.
    # This happens e.g. if the user presses "recalculate" several times and
    # one analysis becomes part in each of these requests.

