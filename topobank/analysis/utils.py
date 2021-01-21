from django.db.models import OuterRef, Subquery
from django.db import transaction
from django.db.models import Q
import inspect
import pickle
import math
import logging

from topobank.analysis.models import Analysis

_log = logging.getLogger(__name__)


def request_analysis(user, analysis_func, topography, *other_args, **kwargs):
    """Request an analysis for a given user.

    :param user: User instance, user who want to see this analysis
    :param topography: Topography instance which will be used to extract first argument to analysis function
    :param analysis_func: AnalysisFunc instance
    :param other_args: other positional arguments for analysis_func
    :param kwargs: keyword arguments for analysis func
    :returns: Analysis object

    The returned analysis can be a precomputed one or a new analysis is
    submitted may or may not be completed in future. Check database fields
    (e.g. task_state) in order to check for completion.

    The analysis will be marked such that the "users" field points to
    the given user and that there is no other analysis for same function
    and topography that points to that user.
    """

    #
    # Build function signature with current arguments
    #
    pyfunc = analysis_func.python_function(type(topography))  # TODO implement for all argument types

    sig = inspect.signature(pyfunc)

    bound_sig = sig.bind(topography, *other_args, **kwargs)
    bound_sig.apply_defaults()

    pyfunc_kwargs = dict(bound_sig.arguments)

    # topography will always be second positional argument
    # and has an extra column, do not safe reference
    del pyfunc_kwargs['topography']

    # progress recorder should also not be saved:
    if 'progress_recorder' in pyfunc_kwargs:
        del pyfunc_kwargs['progress_recorder']

    # same for storage prefix
    if 'storage_prefix' in pyfunc_kwargs:
        del pyfunc_kwargs['storage_prefix']

    #
    # Search for analyses with same topography, function and (pickled) function args
    #
    pickled_pyfunc_kwargs = pickle.dumps(pyfunc_kwargs)
    analysis = Analysis.objects.filter(\
        Q(topography=topography)
        & Q(function=analysis_func)
        & Q(kwargs=pickled_pyfunc_kwargs)).order_by('start_time').last() # will be None if not found
    # what if pickle protocol changes? -> No match, old must be sorted out later
    # See also GH 426.

    if analysis is None:
        analysis = submit_analysis(users=[user], analysis_func=analysis_func, topography=topography,
                                   pickled_pyfunc_kwargs=pickled_pyfunc_kwargs)
        _log.info("Submitted new analysis..")
    elif user not in analysis.users.all():
        analysis.users.add(user)
        _log.info("Added user %d to existing analysis %d.", user.id, analysis.id)
    else:
        _log.info("User %d already registered for analysis %d.", user.id, analysis.id)

    #
    # Retrigger an analysis if there was a failure, maybe sth has been fixed in the meantime
    #
    if analysis.task_state == 'fa':
        new_analysis = submit_analysis(users=analysis.users.all(), analysis_func=analysis_func, topography=topography,
                                       pickled_pyfunc_kwargs=pickled_pyfunc_kwargs)
        _log.info("Submitted analysis %d again because of failure..", analysis.id)
        analysis.delete()
        analysis = new_analysis

    #
    # Remove user from other analyses with same topography and function
    #
    other_analyses_with_same_user = Analysis.objects.filter(
        ~Q(id=analysis.id) \
        & Q(topography=topography) \
        & Q(function=analysis_func) \
        & Q(users__in=[user]))
    for a in other_analyses_with_same_user:
        a.users.remove(user)
        _log.info("Removed user %s from analysis %s with kwargs %s.", user, analysis, pickle.loads(analysis.kwargs))

    return analysis


def renew_analysis(analysis, use_default_kwargs=False):
    """Delete existing analysis and recreate and submit with some arguments and users.

    Parameters
    ----------
    analysis

    Returns
    -------
    New analysis object.

    """
    users = analysis.users.all()
    func = analysis.function
    topography = analysis.topography
    surface = analysis.surface
    if topography is None:
        subject = surface
    else:
        subject = topography
    subject_type = type(subject)

    if use_default_kwargs:
        pickled_pyfunc_kwargs = pickle.dumps(func.get_default_kwargs(subject_type=subject_type))
    else:
        pickled_pyfunc_kwargs = analysis.kwargs

    _log.info("Renewing analysis %d for %d users, function %s, subject type %s, subject id %d .. kwargs: %s",
              analysis.id, len(users), func.name, subject_type, subject.id, pickle.loads(pickled_pyfunc_kwargs))
    analysis.delete()
    return submit_analysis(users, func, topography=topography, surface=surface,
                           pickled_pyfunc_kwargs=pickled_pyfunc_kwargs)


def submit_analysis(users, analysis_func, topography=None, surface=None, pickled_pyfunc_kwargs=None):
    """Create an analysis entry and submit a task to the task queue.

    :param users: sequence of User instances; users which should see the analysis
    :param topography: Topography instance which will be used to extract first argument to analysis function (or None)
    :param surface: Surface instance which will be used to extract first argument to analysis function (or None)
    :param analysis_func: AnalysisFunc instance
    :param pickled_pyfunc_kwargs: pickled kwargs for function which should be saved to database
    :returns: Analysis object

    You must specify exactly one of the keyword arguments 'topography' or 'surface'.
    The other one must be None.
    """
    #
    # create entry in Analysis table
    #
    if pickled_pyfunc_kwargs is None:
        if topography is None:
            subject_type = type(surface)
        else:
            subject_type = type(topography)

        # Instead of an empty dict, we explicitly store the current default arguments of the analysis function
        pickled_pyfunc_kwargs = pickle.dumps(analysis_func.get_default_kwargs(subject_type=subject_type))

    analysis = Analysis.objects.create(
        topography=topography,
        surface=surface,
        function=analysis_func,
        task_state=Analysis.PENDING,
        kwargs=pickled_pyfunc_kwargs)

    analysis.users.set(users)

    #
    # delete all completed old analyses for same function and topography and arguments
    # There should be only one analysis per function, topography and arguments
    #
    Analysis.objects.filter(
        ~Q(id=analysis.id)
        & Q(topography=topography)
        & Q(surface=surface)
        & Q(function=analysis_func)
        & Q(kwargs=pickled_pyfunc_kwargs)
        & Q(task_state__in=[Analysis.FAILURE, Analysis.SUCCESS])).delete()

    #
    # TODO delete all started old analyses, where the task does not exist any more
    #
    #maybe_aborted_analyses = Analysis.objects.filter(
    #    ~Q(id=analysis.id)
    #    & Q(topography=topography)
    #    & Q(function=analysis_func)
    #    & Q(task_state__in=[Analysis.STARTED]))
    # How to find out if task is still running?
    #
    #for a in maybe_aborted_analyses:
    #    result = app.AsyncResult(a.task_id)

    # Send task to the queue if the analysis has been created
    from topobank.taskapp.tasks import perform_analysis
    transaction.on_commit(lambda: perform_analysis.delay(analysis.id))

    return analysis


def get_latest_analyses(user, function_id, topography_ids):
    """Get latest analyses for given function and topographies and user.

    :param user: user which views the analyses
    :param function_id: id of AnalysisFunction instance
    :param topography_ids: iterable of ids of Topography instances

    :return: Queryset of analyses

    The returned queryset is comprised of only the latest analyses,
    so for each topography id there should be at most one result.
    Only analyses for the given function are returned.
    """

    sq_analyses = Analysis.objects \
                .filter(topography_id__in=topography_ids,
                        function_id=function_id,
                        users__in=[user]) \
                .filter(topography=OuterRef('topography'), function=OuterRef('function'),
                        kwargs=OuterRef('kwargs')) \
                .order_by('-start_time')

    # Use this subquery for finding only latest analyses for each (topography, kwargs) group
    analyses = Analysis.objects \
        .filter(pk=Subquery(sq_analyses.values('pk')[:1])) \
        .order_by('topography__name')

    # thanks to minkwe for the contribution at https://gist.github.com/ryanpitts/1304725
    # maybe be better solved with PostGreSQL and Window functions

    return analyses

def mangle_sheet_name(s: str) -> str:
    """Return a string suitable for a sheet name in Excel/Libre Office.

    :param s: sheet name
    :return: string which should be suitable for sheet names
    """

    replacements = {
        ':': '',
        '[': '(',
        ']': ')',
        '*': '',
        '?': '',
        "'": '"',
        "\\": ""
    }

    for x, y in replacements.items():
        s = s.replace(x, y)

    return s

def round_to_significant_digits(x, num_dig_digits):
    """Round given number to given number of significant digits

    Parameters
    ----------
    x: flost
        Number to be rounded
    num_dig_digits: int
        Number of significant digits


    Returns
    -------
    Rounded number.

    For NaN, NaN is returned.
    """
    if math.isnan(x):
        return x
    try:
        return round(x, num_dig_digits - int(math.floor(math.log10(abs(x)))) - 1)
    except ValueError:
        return x

##############################################################################
# TODO: _unicode_map and super and subscript functions: Are these still used?

_unicode_map = {
    # superscript subscript
    '0': ('\u2070', '\u2080'),
    '1': ('\u00B9', '\u2081'),
    '2': ('\u00B2', '\u2082'),
    '3': ('\u00B3', '\u2083'),
    '4': ('\u2074', '\u2084'),
    '5': ('\u2075', '\u2085'),
    '6': ('\u2076', '\u2086'),
    '7': ('\u2077', '\u2087'),
    '8': ('\u2078', '\u2088'),
    '9': ('\u2079', '\u2089'),
    'a': ('\u1d43', '\u2090'),
    'b': ('\u1d47', '?'),
    'c': ('\u1d9c', '?'),
    'd': ('\u1d48', '?'),
    'e': ('\u1d49', '\u2091'),
    'f': ('\u1da0', '?'),
    'g': ('\u1d4d', '?'),
    'h': ('\u02b0', '\u2095'),
    'i': ('\u2071', '\u1d62'),
    'j': ('\u02b2', '\u2c7c'),
    'k': ('\u1d4f', '\u2096'),
    'l': ('\u02e1', '\u2097'),
    'm': ('\u1d50', '\u2098'),
    'n': ('\u207f', '\u2099'),
    'o': ('\u1d52', '\u2092'),
    'p': ('\u1d56', '\u209a'),
    'q': ('?', '?'),
    'r': ('\u02b3', '\u1d63'),
    's': ('\u02e2', '\u209b'),
    't': ('\u1d57', '\u209c'),
    'u': ('\u1d58', '\u1d64'),
    'v': ('\u1d5b', '\u1d65'),
    'w': ('\u02b7', '?'),
    'x': ('\u02e3', '\u2093'),
    'y': ('\u02b8', '?'),
    'z': ('?', '?'),
    'A': ('\u1d2c', '?'),
    'B': ('\u1d2e', '?'),
    'C': ('?', '?'),
    'D': ('\u1d30', '?'),
    'E': ('\u1d31', '?'),
    'F': ('?', '?'),
    'G': ('\u1d33', '?'),
    'H': ('\u1d34', '?'),
    'I': ('\u1d35', '?'),
    'J': ('\u1d36', '?'),
    'K': ('\u1d37', '?'),
    'L': ('\u1d38', '?'),
    'M': ('\u1d39', '?'),
    'N': ('\u1d3a', '?'),
    'O': ('\u1d3c', '?'),
    'P': ('\u1d3e', '?'),
    'Q': ('?', '?'),
    'R': ('\u1d3f', '?'),
    'S': ('?', '?'),
    'T': ('\u1d40', '?'),
    'U': ('\u1d41', '?'),
    'V': ('\u2c7d', '?'),
    'W': ('\u1d42', '?'),
    'X': ('?', '?'),
    'Y': ('?', '?'),
    'Z': ('?', '?'),
    '+': ('\u207A', '\u208A'),
    '-': ('\u207B', '\u208B'),
    '=': ('\u207C', '\u208C'),
    '(': ('\u207D', '\u208D'),
    ')': ('\u207E', '\u208E'),
    ':alpha': ('\u1d45', '?'),
    ':beta': ('\u1d5d', '\u1d66'),
    ':gamma': ('\u1d5e', '\u1d67'),
    ':delta': ('\u1d5f', '?'),
    ':epsilon': ('\u1d4b', '?'),
    ':theta': ('\u1dbf', '?'),
    ':iota': ('\u1da5', '?'),
    ':pho': ('?', '\u1d68'),
    ':phi': ('\u1db2', '?'),
    ':psi': ('\u1d60', '\u1d69'),
    ':chi': ('\u1d61', '\u1d6a'),
    ':coffee': ('\u2615', '\u2615')
}



def unicode_superscript(s):
    """
    Convert a string into the unicode superscript equivalent.

    :param s: Input string
    :return: String with superscript numerals
    """
    return ''.join(_unicode_map[c][0] if c in _unicode_map else c for c in s)


def unicode_subscript(s):
    """
    Convert numerals inside a string into the unicode subscript equivalent.

    :param s: Input string
    :return: String with superscript numerals
    """
    return ''.join(_unicode_map[c][1] if c in _unicode_map else c for c in s)


def float_to_unicode(f, digits=3):
    """
    Convert a floating point number into a human-readable unicode representation.
    Examples are: 1.2×10³, 120.43, 120×10⁻³. Exponents will be multiples of three.

    :param f: Floating-point number for conversion.
    :param digits: Number of significant digits.
    :return: Human-readable unicode string.
    """
    e = int(np.floor(np.log10(f)))
    m = f / 10 ** e

    e3 = (e // 3) * 3
    m *= 10 ** (e - e3)

    if e3 == 0:
        return ('{{:.{}g}}'.format(digits)).format(m)

    else:
        return ('{{:.{}g}}×10{{}}'.format(digits)).format(m, unicode_superscript(str(e3)))
