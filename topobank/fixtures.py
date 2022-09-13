#
# Common settings and fixtures used with pytest
#
import datetime

import pytest
from django.core.management import call_command
import logging

from freezegun import freeze_time
from trackstats.models import Domain, Metric

from topobank.manager.tests.utils import SurfaceFactory
from topobank.users.tests.factories import UserFactory

################################################################################
# remove these deps once the fixtures have been moved to extension projects
from io import StringIO

from topobank.analysis.models import AnalysisFunction
from topobank.analysis.tests.utils import TopographyAnalysisFactory
################################################################################

_log = logging.getLogger(__name__)

PASSWORD = "secret"


@pytest.fixture
def handle_usage_statistics():
    """This fixture is needed in the tests which affect usage statistics.
    Otherwise, you get a foreign key error because entries remain
    without a corresponding foreign key in the metric table.

    Returns
    -------
        None
    """
    from topobank.usage_stats.utils import register_metrics
    register_metrics()
    yield
    #
    # Teardown code which is run after the test function
    #
    Domain.objects.clear_cache()
    Metric.objects.clear_cache()


@pytest.fixture(scope='function')
def user_alice():
    return UserFactory(username='alice', password=PASSWORD, name='Alice Wonderland')


@pytest.fixture(scope='function')
def user_bob():
    return UserFactory(username='bob', password=PASSWORD, name='Bob Marley')


@pytest.fixture(scope='function')
def user_alice_logged_in(live_server, browser, user_alice, handle_usage_statistics):
    # passing "handle_usage_statistics" is important, otherwise
    # the following tests may fail in a strange way because of foreign key errors

    browser.visit(live_server.url + "/accounts/login")  # we don't want to use ORCID here for testing

    assert browser.is_element_present_by_text('Sign In', wait_time=1)

    #
    # Logging in
    #
    browser.fill('login', user_alice.username)
    browser.fill('password', PASSWORD)
    browser.find_by_text('Sign In').last.click()

    try:
        yield browser, user_alice
    finally:
        #
        # Logging out
        #
        # important to have new session on next login
        browser.find_by_id("userDropdown", wait_time=5).click()  # may cause problems..
        browser.find_by_text("Sign Out").first.click()
        browser.is_element_present_by_text("Ready to Leave?", wait_time=1)
        browser.find_by_text("Sign Out").last.click()

        browser.is_element_present_by_text('You have signed out.', wait_time=1)
        browser.quit()

        # remove session variables for user alice such these do no
        # affect subsequent tests
        call_command('clearsessions')  # TODO is this effective?
        _log.info("Cleared all sessions.")


@pytest.fixture(scope="function", autouse=True)
def sync_analysis_functions(db):
    _log.info("Syncing analysis functions in registry with database objects..")
    from topobank.analysis.registry import AnalysisRegistry
    reg = AnalysisRegistry()
    reg.sync_analysis_functions(cleanup=True)
    _log.info("Done synchronizing registry with database.")


@pytest.fixture(scope="function")
def test_analysis_function(db):
    from topobank.analysis.models import AnalysisFunction
    return AnalysisFunction.objects.get(name="test")


@pytest.fixture
def example_authors():
    authors = [
        {
            'first_name': 'Hermione',
            'last_name': 'Granger',
            'orcid_id': '9999-9999-9999-999X',
            'affiliations': [
                {
                    'name': 'Hogwarts'
                }
            ]
        },
        {'first_name': 'Harry',
         'last_name': 'Potter',
         'orcid_id': '9999-9999-9999-9999',
         'affiliations': [
             {
                 'name': 'University of Freiburg',
                 'ror_id': '0245cg223'
             },
             {
                 'name': 'Hogwarts'
             }
         ]
         },
    ]
    return authors


@pytest.mark.django_db
@pytest.fixture
def example_pub(example_authors):
    """Fixture returning a publication which can be used as test example"""

    user = UserFactory()

    publication_date = datetime.date(2020, 1, 1)
    description = "This is a nice surface for testing."
    name = "Diamond Structure"

    surface = SurfaceFactory(name=name, creator=user, description=description)
    surface.tags = ['diamond']

    with freeze_time(publication_date):
        pub = surface.publish('cc0-1.0', example_authors)

    return pub


@pytest.fixture()
def use_dummy_cache_backend(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.dummy.DummyCache",
        }
    }


@pytest.mark.django_db
@pytest.fixture
def example_contact_analysis(test_analysis_function):
    func = AnalysisFunction.objects.get(name="Contact mechanics")

    storage_prefix = "test_contact_mechanics/"

    result = dict(
        name='Contact mechanics',
        area_per_pt=0.1,
        maxiter=100,
        min_pentol=0.01,
        mean_pressures=[1, 2, 3, 4],
        total_contact_areas=[2, 4, 6, 8],
        mean_displacements=[3, 5, 7, 9],
        mean_gaps=[4, 6, 8, 10],
        converged=[True, True, False, True],
        data_paths=[storage_prefix + "step-0", storage_prefix + "step-1",
                    storage_prefix + "step-2", storage_prefix + "step-3", ],
        effective_kwargs=dict(
            substrate_str="periodic",
            hardness=1,
            nsteps=11,
            pressures=[1, 2, 3, 4],
            maxiter=100,
        )
    )

    analysis = TopographyAnalysisFactory(function=func, result=result)

    # create files in storage for zipping
    from django.core.files.storage import default_storage

    # files_to_delete = []

    for k in range(4):
        fn = f"{analysis.storage_prefix}/step-{k}/nc/results.nc"
        default_storage.save(fn, StringIO(f"test content for step {k}"))

    return analysis

