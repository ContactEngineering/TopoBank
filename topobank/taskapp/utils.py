import importlib

from django.db import transaction

from watchman.decorators import check as watchman_check

from ..analysis.models import Dependency, Version


class ConfigurationException(Exception):
    pass


def get_package_version_tuple(pkg_name, version_expr):
    """

    :param pkg_name: name of the package which is used in import statement
    :param version_expr: expression used to get the version from already imported module
    :return: version tuple
    """
    mod = importlib.import_module(pkg_name)

    version = eval(version_expr, {pkg_name: mod})

    version_tuple = version.split('.')

    try:
        major: int = int(version_tuple[0])
    except:
        raise ConfigurationException("Cannot determine major version of package '{}'. Full version string: {}",
                                     format(pkg_name, version))

    try:
        minor: int = int(version_tuple[1])
    except:
        raise ConfigurationException("Cannot determine minor version of package '{}'. Full version string: {}",
                                     format(pkg_name, version))

    try:
        micro: int = int(version_tuple[2].split('+')[0])  # because of version strings like '0.51.0+0.g2c488bd.dirty'
        s = f'{version_tuple[0]}.{version_tuple[1]}.{micro}'
    except:
        micro = None
        s = f'{version_tuple[0]}.{version_tuple[1]}'

    try:
        extra: str = version[len(s):]  # the rest of the version string
    except:
        extra = None

    return major, minor, micro, extra


@transaction.atomic(durable=True)
def get_package_version_instance(pkg_name, version_expr):
    """
    Return version instance for currently installed version of a package.
    The function creates the entry in the dependency and version tables if
    they are missing. This serves to track versions of packages that are used
    for generating analysis results.

    Parameters
    ----------
    pkg_name : str
        name of the package which is used in import statement
    version_expr : str
        expression (Python code) used to get the version from already
        imported module

    Returns
    -------
    version : Version
        Instance of the Version class
    """
    major, minor, micro, extra = get_package_version_tuple(pkg_name, version_expr)

    # create dependency object if it does not yet exist
    dep, created = Dependency.objects.get_or_create(import_name=pkg_name)

    # make sure the current version of the dependency is available in database
    version, created = Version.objects.get_or_create(dependency=dep, major=major, minor=minor, micro=micro, extra=extra)

    return version


def celery_worker_check():
    return {
        'celery': _celery_worker_check(),
    }


@watchman_check
def _celery_worker_check():
    """Used with watchman in order to check whether celery workers are available."""
    # See https://github.com/mwarkentin/django-watchman/issues/8
    from .celeryapp import app
    MIN_NUM_WORKERS_EXPECTED = 1
    d = app.control.broadcast('ping', reply=True, timeout=0.5, limit=MIN_NUM_WORKERS_EXPECTED)
    return {
        'num_workers_available': len(d),
        'min_num_workers_expected': MIN_NUM_WORKERS_EXPECTED,
        'ok': len(d) >= MIN_NUM_WORKERS_EXPECTED,
    }
