#
# Some helpers useful during testing
#
import datetime
from django.utils import formats
from django.test import SimpleTestCase

DEFAULT_DEBUG_HTML_FILENAME = '/tmp/response.html'

def export_reponse_as_html(response, fname=DEFAULT_DEBUG_HTML_FILENAME):
    """
    Helper function which can be used for debugging.

    :param response: HTTPResponse
    :param fname: name of HTML output file
    """
    f = open(fname, mode='w')

    f.write(response.content.decode('utf-8').replace('\\n','\n'))
    f.close()

def assert_in_content(response, x):
    """Check whether x is in the content of given response"""

    if isinstance(x, datetime.date):
        representation = formats.date_format(x)
    else:
        representation = str(x)

    in_content = bytes(representation, encoding='utf-8') in response.content

    if not in_content:
        export_reponse_as_html(response) # for debugging

    assert in_content, f"Cannot find '{representation}' in this content:\n{response.content}.\n\n"+\
        f"See file://{DEFAULT_DEBUG_HTML_FILENAME} in order to view the output."

def assert_not_in_content(response, x):
    """Check whether x is NOT in the content of given response"""

    if isinstance(x, datetime.date):
        representation = formats.date_format(x)
    else:
        representation = str(x)

    in_content = bytes(representation, encoding='utf-8') in response.content

    if in_content:
        export_reponse_as_html(response) # for debugging

    assert not in_content, f"Unexpectedly, there is '{representation}' in this content:\n{response.content}.\n\n"+\
        f"See file://{DEFAULT_DEBUG_HTML_FILENAME} in order to view the output."


def assert_no_form_errors(response):
    """Asserts that there is no more form, and if there is, show errors in form"""
    assert ('form' not in response.context) or (len(response.context['form'].errors) == 0), \
        "Form is still in context, with errors: {}".format(response.context['form'].errors)


def assert_form_error(response, error_msg_fragment, field_name):
    """Asserts that there is an error in form.

    The error message must contain the given error_msg_fragment.
    """
    assert ('form' in response.context) and (len(response.context['form'].errors) > 0), \
        "Form is expected to show errors, but there is no error."

    assert field_name in response.context['form'].errors, \
        f"Form shows errors, but not for field '{field_name}' which is expected"

    errors = response.context['form'].errors[field_name]

    assert any((error_msg_fragment in err) for err in errors), \
        f"Form has errors as expected, but no error contains the given error message fragment '{error_msg_fragment}'."+\
        f" Instead: {errors}"

# abbreviation for use with pytest
assert_redirects = SimpleTestCase().assertRedirects
