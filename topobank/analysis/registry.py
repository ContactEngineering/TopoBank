"""
Registry for collection analysis functions.

Each function has an `visualization_type`, determines the type of standardized
results an analysis function produces. This standardization applies to
which files are placed in the S3 under the `data` route of the analysis.

The frontend selects a visualization ui app based on the vizui type, that
expects certain files to be present. This means the same vizui type is
visualized by the same frontend app, but it may be produced by a different
analysis function.

As an example, analyses producing simply x-y plots (height distribution,
autocorrelationm, power spectrum) have the same visualization type and are
visualized using the same frontend app.

Frontend apps are implemented as Vue.js components.
"""

import logging

_log = logging.getLogger(__name__)


#
# Exceptions
#


class RegistryException(Exception):
    """Generic exception for problems while handling analysis functions."""

    pass


class UnknownAnalysisFunctionException(RegistryException):
    """No analysis function with given name known."""

    def __init__(self, name):
        self._name = name

    def __str__(self):
        return f"No analysis function defined with name '{self._name}'."


class UnimplementedAnalysisFunctionException(RegistryException):
    """No implementation for analysis function with given name registered."""

    def __init__(self, name):
        self._name = name

    def __str__(self):
        return f"No implementation has been registered for analysis function '{self._name}'."


class AlreadyRegisteredAnalysisFunctionException(
    RegistryException
):  # TODO replace with  AlreadyRegisteredException ?
    """An implementation of an analysis function has already been defined."""

    def __init__(self, visualization_type, name, subject_app_name, subject_model):
        self._visualization_type = visualization_type
        self._name = name
        self._subject_app_name = subject_app_name
        self._subject_model = subject_model

    def __str__(self):
        return (
            f"An implementation for analysis function '{self._name}' "
            f"(visualization type: {self._visualization_type}) with subject type "
            f"'{self._subject_model}' (app '{self._subject_app_name}') has already been defined."
        )


class DefaultKwargsDifferException(RegistryException):
    def __init__(
        self,
        name,
        subject_app_name1,
        subject_model1,
        default_kwargs1,
        subject_app_name2,
        subject_model2,
        default_kwargs2,
    ):
        self._name = name
        self._subject_app_name1 = subject_app_name1
        self._subject_model1 = subject_model1
        self._default_kwargs1 = default_kwargs1
        self._subject_app_name2 = subject_app_name2
        self._subject_model2 = subject_model2
        self._default_kwargs2 = default_kwargs2

    def __str__(self):
        return (
            f"Analysis function '{self._name}' has already been registered for model "
            f"'{self._subject_app_name1}|{self._subject_model1}' with default keyword arguments "
            f"'{self._default_kwargs1}. The implementation for '{self._subject_app_name2}|{self._subject_model2}' "
            f"has different default keyword arguments of '{self._default_kwargs2}."
        )


class AlreadyRegisteredException(RegistryException):
    """A function has already been registered for the given key."""

    def __init__(self, key):
        self._key = key

    def __str__(self):
        return f"An implementation for key '{self._key}' has already been defined."


class ImplementationMissingAnalysisFunctionException(RegistryException):
    """An analysis function implementation was not found for given subject type."""

    def __init__(self, name, subject_model):
        self._name = name
        self._subject_model = subject_model

    def __str__(self):
        return (
            f"Implementation of analysis function '{self._name}' for "
            f"subject '{self._subject_model}' not found."
        )


class InconsistentAnalysisResultTypeException(RegistryException):
    """visualization type for an analysis function is not unique."""

    def __init__(self, name, curr_visualization_type, new_visualization_type):
        self._name = name
        self._curr_visualization_type = curr_visualization_type
        self._new_visualization_type = new_visualization_type

    def __str__(self):
        return (
            f"An implementation for analysis function '{self._name}' was given with "
            + f"visualization type '{self._new_visualization_type}', but before "
            + f"visualization type '{self._curr_visualization_type}' was defined. It should be unique."
        )


class UnknownCardViewFlavorException(RegistryException):
    """Card view flavor for an analysis function is not known."""

    def __init__(self, key):
        self._key = key

    def __str__(self):
        return f"An unknown card view flavor was given in key '{self._key}' while registering a function."


class UnknownKeyException(RegistryException):
    """A key was requested which is not known."""

    def __init__(self, key):
        self._key = key

    def __str__(self):
        return f"Key '{self._key}' is unknown."


#
# Handling of analysis function implementations
#

_implementation_classes_by_display_name = {}
# key: (name, subject_app_name, subject_model)
#      where
#      name: str, Unique function name,
#      subject_app_name: str, application name for subject_model
#      subject_model: str, e.g. "topography" or "surface",
#                     should correspond to first argument of analysis function implementations
#                     and to model class name
# value: reference to implementation of analysis function

_implementation_classes_by_name = {}
# key: (name, subject_app_name, subject_model)
#      where
#      name: str, Unique function name,
#      subject_app_name: str, application name for subject_model
#      subject_model: str, e.g. "topography" or "surface",
#                     should correspond to first argument of analysis function implementations
#                     and to model class name
# value: reference to implementation of analysis function

_app_name = {}
# key: visualization_type: str, visualization type
# value: Name of Django app/plugin where the visualization resides

_visualization_type_by_function_name = {}
# key: name: str, Unique function name,
# value: visualization_type: str, visualization type


def register_implementation(klass):
    """
    Register implementation of an analysis function.

    Parameters
    ----------
    klass: AnalysisImplementation
        Runner class that has the Python function which implements the analysis, and
        additional metadata
    """
    _implementation_classes_by_display_name[klass.Meta.display_name] = klass
    _implementation_classes_by_name[klass.Meta.name] = klass


def get_implementation(display_name=None, name=None):
    """
    Return AnalysisFunctionImplementation for given analysis function and subject type.

    Parameters
    ----------
    name : str
        Name of analysis function.

    Returns
    -------
    runner : AnalysisImplementation
        The analysis function
    """
    if display_name is not None:
        return _implementation_classes_by_display_name[display_name]
    elif name is not None:
        return _implementation_classes_by_name[name]
    else:
        raise RuntimeError("Please specify either `name` or `display_name`.")


def get_analysis_function_names(user=None):
    """
    Returns function names as list.

    If given a user, only the functions are returned
    which have at least one implementation for the given user.
    """
    runner_classes = _implementation_classes_by_name
    if user is not None:
        # filter for user
        runner_classes = {
            k: runner_class
            for k, runner_class in runner_classes.items()
            if runner_class.has_permission(user)
        }

    return list(runner_classes.keys())


def get_visualization_type(display_name=None, name=None):
    """Return visualization type for given function name."""
    runner_class = get_implementation(display_name=display_name, name=name)
    try:
        return runner_class.Meta.visualization_type
    except AttributeError:
        return "generic"


def sync_implementation_classes(cleanup=False):
    """
    Make sure all analysis functions are represented in database.

    It's recommended to run this with cleanup=True if an analysis
    function should be removed.

    Parameters
    ----------

    cleanup: bool
        If True, delete all analysis functions for which no implementations exist
        and also delete all analyses related to those functions.
        Be careful, might delete existing analyses.
    """
    from .models import Analysis, AnalysisFunction

    counts = dict(
        funcs_updated=0,
        funcs_created=0,
        funcs_deleted=0,
    )

    function_names_used = list(_implementation_classes_by_display_name.keys())

    #
    # Ensure all analysis functions needed to exist in database
    #
    _log.info(
        f"Syncing analysis functions with database - {len(function_names_used)} "
        "functions used - .."
    )

    for name in function_names_used:
        func, created = AnalysisFunction.objects.update_or_create(name=name)
        if created:
            counts["funcs_created"] += 1
        else:
            counts["funcs_updated"] += 1

    #
    # Optionally delete all analysis functions which are no longer needed
    #
    for func in AnalysisFunction.objects.all():
        if func.name not in function_names_used:
            _log.info(f"Function '{func.name}' is no longer used in the code.")
            dangling_analyses = Analysis.objects.filter(function=func)
            num_analyses = dangling_analyses.filter(function=func).count()
            _log.info(f"There are still {num_analyses} analyses for this function.")
            if cleanup:
                _log.info("Deleting those..")
                dangling_analyses.delete()
                func.delete()
                _log.info(f"Deleted function '{func.name}' and all its analyses.")
                counts["funcs_deleted"] += 1

    return counts


#
# Handling of download functions
#

_download_functions = {}
# key: (visualization_type, spec, file_format) where
#
#      visualization_type: str, visualization type
#      spec: str, short name for what should be downloaded, e.g. 'results'
#      file_format: str, e.g. 'txt' or 'xlsx'
# value: reference to implementation of download function


def add_download_function(visualization_type, spec, file_format, func):
    """Register implementation of a download function.

    You can use the @register_download_function decorator in order to
    add an implementation to the registry.

    Parameters
    ----------
    visualization_type: str
        visualization type
    spec: str
        Short name for what should be downloaded, e.g. 'results'
    file_format: str
        File format provided by the iven function
    func: function
        Python function which implements the download function
    """

    key = (visualization_type, spec, file_format)

    # Each implementation should only be defined once
    if key in _download_functions:
        raise AlreadyRegisteredException(key)

    _download_functions[key] = func


def get_download_function(visualization_type, spec, file_format):
    """Return Python function for given parameters.

    Parameters
    ----------
    visualization_type: str
        visualization type
    spec: str
        Short name for what should be downloaded, e.g. 'results'
    file_format: str
        File format provided by the iven function

    Returns
    -------
    Reference to Python function of form

       download_func(request, analyses)

    where request: HttpRequest, analyses: sequence of Analysis objects

    The referenced function returns a HttpResponse with a file download.
    """
    key = (visualization_type, spec, file_format)

    try:
        return _download_functions[key]
    except KeyError as exc:
        raise UnknownKeyException(key) from exc


def register_download_function(visualization_type, spec, file_format):
    """
    Decorator for marking a function as a download function.

    Parameters
    ----------
    visualization_type: str
        visualization type.
    spec: str
            Short name for what should be downloaded, e.g. 'results'
    file_format: str
        File format provided by the given function
    """

    def register_decorator(func):
        add_download_function(visualization_type, spec, file_format, func)
        return func

    return register_decorator
