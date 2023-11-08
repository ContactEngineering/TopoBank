import pytest
from django.shortcuts import reverse

from ...analysis.tests.utils import TopographyAnalysisFactory
from ...utils import assert_in_content, assert_not_in_content
from ..utils import selection_from_session, selection_to_instances
from .utils import UserFactory, SurfaceFactory, Topography1DFactory


#
# The code in these tests rely on a middleware which replaces
# Django's AnonymousUser by the one of django guardian
#


@pytest.mark.django_db
def test_anonymous_user_only_published_as_default(client):
    response = client.get(reverse('manager:select'))
    assert_not_in_content(response, 'All accessible surfaces')
    assert_not_in_content(response, 'Only own surfaces')
    assert_not_in_content(response, 'Only surfaces shared with you')
    assert_not_in_content(response, 'Only surfaces shared by you')
    assert_not_in_content(response, 'Only surfaces published by you')
    assert_in_content(response, 'Only surfaces published by others')


@pytest.mark.django_db
def test_anonymous_user_can_see_published(api_client, handle_usage_statistics, example_authors):
    #
    # publish a surface
    #
    bob = UserFactory(name="Bob")
    surface_name = "Diamond Structure"
    surface = SurfaceFactory(creator=bob, name=surface_name)
    topo = Topography1DFactory(surface=surface)

    pub = surface.publish('cc0-1.0', example_authors)

    # no one is logged in now, assuming the select tab sends a search request
    response = api_client.get(reverse('manager:search'))

    # should see the published surface
    assert_in_content(response, surface_name)


@pytest.mark.django_db
def test_anonymous_user_can_select_published(client, handle_usage_statistics):
    bob = UserFactory(name="Bob")
    surface_name = "Diamond Structure"
    surface = SurfaceFactory(creator=bob, name=surface_name)
    topo = Topography1DFactory(surface=surface)
    pub = surface.publish('cc0-1.0', bob.name)
    published_surface = pub.surface
    published_topo = published_surface.topography_set.first()

    response = client.post(reverse('manager:topography-select', kwargs=dict(pk=published_topo.pk)))
    assert response.status_code == 200
    sel_topos, sel_surfs, sel_tags = selection_to_instances(selection_from_session(client.session))
    assert len(sel_topos) == 1
    assert published_topo in sel_topos

    response = client.post(reverse('manager:topography-unselect', kwargs=dict(pk=published_topo.pk)))
    assert response.status_code == 200
    sel_topos, sel_surfs, sel_tags = selection_to_instances(selection_from_session(client.session))
    assert len(sel_topos) == 0

    response = client.post(reverse('manager:surface-select', kwargs=dict(pk=published_surface.pk)))
    assert response.status_code == 200
    sel_topos, sel_surfs, sel_tags = selection_to_instances(selection_from_session(client.session))
    assert len(sel_surfs) == 1
    assert published_surface in sel_surfs

    response = client.post(reverse('manager:surface-unselect', kwargs=dict(pk=published_surface.pk)))
    assert response.status_code == 200
    sel_topos, sel_surfs, sel_tags = selection_to_instances(selection_from_session(client.session))
    assert len(sel_surfs) == 0


@pytest.mark.django_db
def test_anonymous_user_cannot_change(client, handle_usage_statistics):
    bob = UserFactory(name="Bob")
    surface_name = "Diamond Structure"
    surface = SurfaceFactory(creator=bob, name=surface_name)
    topo = Topography1DFactory(surface=surface)

    response = client.get(reverse('manager:surface-api-list'))
    assert response.status_code == 405  # Method not allowed

    response = client.get(reverse('manager:surface-api-detail', kwargs=dict(pk=surface.pk)))
    assert response.status_code == 404  # Not found

    response = client.post(reverse('manager:surface-api-list'))
    assert response.status_code == 403  # Forbidden

    response = client.put(reverse('manager:surface-api-detail', kwargs=dict(pk=surface.pk)))
    assert response.status_code == 403  # Forbidden

    response = client.patch(reverse('manager:surface-api-detail', kwargs=dict(pk=surface.pk)))
    assert response.status_code == 403  # Forbidden

    response = client.delete(reverse('manager:surface-api-detail', kwargs=dict(pk=surface.pk)))
    assert response.status_code == 403  # Forbidden

    response = client.get(reverse('manager:topography-api-list'))
    assert response.status_code == 405  # Method not allowed

    response = client.get(reverse('manager:topography-api-detail', kwargs=dict(pk=topo.pk)))
    assert response.status_code == 404  # Not found

    response = client.post(reverse('manager:topography-api-list'))
    assert response.status_code == 403  # Forbidden

    response = client.put(reverse('manager:topography-api-detail', kwargs=dict(pk=topo.pk)))
    assert response.status_code == 403  # Forbidden

    response = client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topo.pk)))
    assert response.status_code == 403  # Forbidden

    response = client.delete(reverse('manager:topography-api-detail', kwargs=dict(pk=topo.pk)))
    assert response.status_code == 403  # Forbidden


@pytest.mark.django_db
def test_download_analyses_without_permission(client, test_analysis_function, handle_usage_statistics):
    bob = UserFactory()
    surface = SurfaceFactory(creator=bob)
    topo = Topography1DFactory(surface=surface)
    analysis = TopographyAnalysisFactory(subject_topography=topo, function=test_analysis_function)

    response = client.get(reverse('analysis:download',
                                  kwargs=dict(ids=f"{analysis.id}",
                                              file_format='txt')))
    assert response.status_code == 403
