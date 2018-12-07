from django.contrib.staticfiles.templatetags.staticfiles import static
from django.conf import settings
import django
import bokeh
import celery

import PyCo


def versions_processor(request):

    # key 'links': dicts with keys display_name:url

    versions = [
        dict(module='TopoBank',
             version=settings.TOPOBANK_VERSION,
             links={'Changelog': static('other/CHANGELOG.md')}), # needs 'manage.py collectstatic' before!
        dict(module='PyCo',
             version=PyCo.__version__,
             links={}),
        dict(module='Django',
             version=django.__version__,
             links={'Website': 'https://www.djangoproject.com/'}),
        dict(module='Celery',
             version=celery.__version__,
             links={'Website': 'http://www.celeryproject.org/'}),
        dict(module='Bokeh',
             version=bokeh.__version__,
             links={'Website': 'https://bokeh.pydata.org/en/latest/'}),

    ]

    return dict(versions=versions)
