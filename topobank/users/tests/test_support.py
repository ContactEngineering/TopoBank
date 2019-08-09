"""
Tests related to user support.
"""
from django.urls import reverse
from django.core.management import call_command
import pytest

from topobank.manager.models import Surface
from topobank.analysis.models import AnalysisFunction, Analysis

@pytest.mark.db_django
def test_initial_surface(live_server, client, django_user_model):

    import topobank.users.signals # in order to have signals activated

    # Make sure, we have automated analysis functions
    call_command('register_analysis_functions')

    # we read from static files, they should be up-to-date
    call_command('collectstatic', '--noinput')

    #
    # signup for an account, this triggers signal to create example surface
    #
    email = "testuser@example.org"
    password = "test$1234"
    name = 'New User'

    response = client.post(reverse('account_signup'),
                {
                    'email': email,
                    'password1': password,
                    'password2': password,
                    'name': name,
                })

    assert 'form' not in response.context, "Errors in form: {}".format(response.context['form'].errors)

    assert response.status_code == 302 # redirect

    user = django_user_model.objects.get(email=email)

    # user is already authenticated
    assert user.is_authenticated

    #
    # After login, there should be an example surface now with three topographies
    #
    surface = Surface.objects.get(creator=user, name="Example Surface")

    assert surface.category == 'sim'

    topos = surface.topography_set.all()

    assert len(topos) == 3

    assert sorted([ t.name for t in topos]) == [ "50000x50000_random.txt",
                                                 "5000x5000_random.txt",
                                                 "500x500_random.txt" ]

    #
    # All these topographies should have the same size as in the database
    # and the height scale should be editable
    #
    for topo in topos:
        assert topo.size_x == topo.size_y # so far all examples are like this, want to ensure here that size_y is set
        pyco_topo = topo.topography()
        assert pyco_topo.info['unit'] == 'µm'
        assert pyco_topo.physical_sizes == (topo.size_x, topo.size_y)

        assert topo.height_scale_editable
    #
    # For all these topographies, all analyses for all automated analysis functions
    # should have been triggered
    #
    for af in AnalysisFunction.objects.filter(automatic=True):
        analyses = Analysis.objects.filter(topography__surface_id=surface.id, function=af)
        assert analyses.count() == len(topos)







