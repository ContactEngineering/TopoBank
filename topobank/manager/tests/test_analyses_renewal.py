"""
Test whether analyses are recalculated on certain events.
"""
import pytest

from pathlib import Path
from django.shortcuts import reverse
from django.contrib.contenttypes.models import ContentType
from django_capture_on_commit_callbacks import capture_on_commit_callbacks

from .utils import FIXTURE_DIR, Topography1DFactory, SurfaceFactory, UserFactory
from topobank.analysis.tests.utils import SurfaceAnalysisFactory, AnalysisFunctionFactory, \
    AnalysisFunctionImplementationFactory, TopographyAnalysisFactory
from topobank.utils import assert_in_content, assert_no_form_errors


@pytest.mark.django_db
def test_renewal_on_topography_change(client, mocker):
    """Check whether methods for renewal are called on significant topography change.
    """

    renew_topo_analyses_mock = mocker.patch('topobank.manager.views.renew_analyses_related_to_topography.delay')
    renew_topo_thumbnail_mock = mocker.patch('topobank.manager.views.renew_topography_thumbnail.delay')
    renew_topo_squeezed_mock = mocker.patch('topobank.manager.views.renew_squeezed_datafile.delay')

    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    topo = Topography1DFactory(surface=surface, size_y=1)

    client.force_login(user)

    with capture_on_commit_callbacks(execute=True) as callbacks:
        response = client.post(reverse('manager:topography-update', kwargs=dict(pk=topo.pk)),
                               data={
                                   'save-stay': 1,  # we want to save, but stay on page
                                   'surface': surface.pk,
                                   'data_source': 0,
                                   'name': topo.name,
                                   'measurement_date': topo.measurement_date,
                                   'description': "something",
                                   'size_x': 1,
                                   'size_y': 100,  # here is a change at least
                                   'unit': 'nm',
                                   'height_scale': 1,
                                   'detrend_mode': 'center',
                               }, follow=True)

    assert response.status_code == 200

    assert len(callbacks) == 3

    assert renew_topo_analyses_mock.called
    assert renew_topo_thumbnail_mock.called
    assert renew_topo_squeezed_mock.called


@pytest.mark.django_db
def test_analysis_removal_on_topography_deletion(client, handle_usage_statistics):
    """Check whether surface analyses are deleted if topography is deleted.
    """

    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    topo = Topography1DFactory(surface=surface)

    func = AnalysisFunctionFactory()
    AnalysisFunctionImplementationFactory(function=func,
                                          subject_type=ContentType.objects.get_for_model(topo))
    AnalysisFunctionImplementationFactory(function=func,
                                          subject_type=ContentType.objects.get_for_model(surface))
    TopographyAnalysisFactory(subject=topo, function=func)
    SurfaceAnalysisFactory(subject=surface, function=func)
    SurfaceAnalysisFactory(subject=surface, function=func)

    assert topo.analyses.count() == 1
    assert surface.analyses.count() == 2

    #
    # Now remove topography and see whether all analyses are deleted
    #
    client.force_login(user)

    response = client.post(reverse('manager:topography-delete', kwargs=dict(pk=topo.pk)))

    assert response.status_code == 302

    # No more topography analyses left
    assert topo.analyses.count() == 0
    # No more surface analyses left
    assert surface.analyses.count() == 0


@pytest.mark.django_db
def test_renewal_on_topography_creation(client, mocker, handle_usage_statistics):

    renew_topo_analyses_mock = mocker.patch('topobank.manager.views.renew_analyses_related_to_topography.delay')
    renew_topo_thumbnail_mock = mocker.patch('topobank.manager.views.renew_topography_thumbnail.delay')

    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    client.force_login(user)

    #
    # open first step of wizard: file upload
    #
    input_file_path = Path(FIXTURE_DIR + '/example-2d.npy')  # maybe use package 'pytest-datafiles' here instead
    with open(str(input_file_path), mode='rb') as fp:
        response = client.post(reverse('manager:topography-create',
                                       kwargs=dict(surface_id=surface.id)),
                               data={
                                   'topography_create_wizard-current_step': 'upload',
                                   'upload-datafile': fp,
                                   'upload-datafile_format': '',
                                   'upload-surface': surface.id,
                               }, follow=True)

    assert response.status_code == 200
    assert_no_form_errors(response)

    #
    # now we should be on the page with second step
    #
    assert_in_content(response, "Step 2 of 3")
    assert_in_content(response, '<option value="0">Default</option>')
    assert response.context['form'].initial['name'] == 'example-2d.npy'

    #
    # Send data for second page
    #
    response = client.post(reverse('manager:topography-create',
                                   kwargs=dict(surface_id=surface.id)),
                           data={
                               'topography_create_wizard-current_step': 'metadata',
                               'metadata-name': 'topo1',
                               'metadata-measurement_date': '2020-10-21',
                               'metadata-data_source': 0,
                               'metadata-description': "description",
                           }, follow=True)
    assert_no_form_errors(response)

    #
    # Send data for third page
    #
    assert_in_content(response, "Step 3 of 3")
    with capture_on_commit_callbacks(execute=True) as callbacks:
        response = client.post(reverse('manager:topography-create',
                                       kwargs=dict(surface_id=surface.id)),
                               data={
                                   'topography_create_wizard-current_step': 'units',
                                   'units-size_x': '1',
                                   'units-size_y': '1',
                                   'units-unit': 'nm',
                                   'units-height_scale': 1,
                                   'units-detrend_mode': 'height',
                                   'units-resolution_x': 2,
                                   'units-resolution_y': 2,
                               }, follow=True)

    assert_no_form_errors(response)

    assert len(callbacks) == 2  # for thumbnail and for analyses
    assert renew_topo_analyses_mock.called
    assert renew_topo_thumbnail_mock.called


