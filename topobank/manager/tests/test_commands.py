"""
Testing management commands for manager app.
"""
from django.core.management import call_command
from django.shortcuts import reverse

import pytest
import tempfile
import math

from topobank.manager.models import Surface, Topography
from topobank.manager.tests.utils import UserFactory, SurfaceFactory, \
    Topography2DFactory, Topography1DFactory


@pytest.mark.django_db
def test_import_downloaded_surface_archive(client):
    username = 'test_user'
    surface_name = "Test Surface for Import"
    surface_category = 'dum'
    user = UserFactory(username=username)
    surface = SurfaceFactory(creator=user, name=surface_name, category=surface_category)
    Topography2DFactory(surface=surface, name='2D Measurement', size_x=10, size_y=10, unit='mm')
    Topography1DFactory(surface=surface, name='1D Measurement', size_x=9, unit='µm')

    client.force_login(user)

    download_url = reverse('manager:surface-download', kwargs=dict(surface_id=surface.id))
    response = client.get(download_url)

    # write downloaded data to temporary file and open
    with tempfile.NamedTemporaryFile(mode='wb') as zip_archive:
        zip_archive.write(response.content)
        zip_archive.seek(0)

        # reimport the surface
        call_command('import_surfaces', username, zip_archive.name)

    surface_copy = Surface.objects.get(description__icontains='imported from file')

    #
    # Check surface
    #
    assert surface_copy.name == surface.name
    assert surface_copy.category == surface.category
    assert surface.description in surface_copy.description
    assert surface_copy.tags == surface.tags

    #
    # Check imported topographies
    #
    assert surface_copy.num_topographies() == surface.num_topographies()

    for tc, t in zip(surface_copy.topography_set.order_by('name'), surface.topography_set.order_by('name')):

        #
        # Compare individual topographies
        #
        for attrname in ['name', 'description', 'size_x', 'size_y', 'height_scale',
                         'measurement_date', 'unit', 'creator', 'data_source', 'tags']:
            assert getattr(tc, attrname) == getattr(t, attrname)


@pytest.mark.django_db
def test_fix_sizes(two_topos):
    topo = two_topos[0]
    assert topo.name == 'Example 3 - ZSensor'
    # this file comes from a DI file where sizes are fixed

    # let's save wrong values to fix it
    topo.size_editable = True  # this is wrong
    topo.size_x = 1.  # also wrong
    topo.size_y = 2.
    topo.save()

    call_command('fix_sizes')

    # Reload topography from database
    new_topo = Topography.objects.get(id=topo.id)
    assert not new_topo.size_editable
    assert math.isclose(new_topo.size_x, 1e4, abs_tol=1e-8)
    assert math.isclose(new_topo.size_y, 1e4, abs_tol=1e-8)


@pytest.mark.django_db
def test_fix_height_scale(two_topos):
    topo = two_topos[0]
    assert topo.name == 'Example 3 - ZSensor'
    # this file comes from a DI file where height scales are fixed

    # let's save wrong values to fix it
    topo.height_scale_editable = True  # this is wrong
    topo.height_scale = 9999.  # also wrong
    topo.save()

    call_command('fix_height_scale')

    # Reload topography from database
    new_topo = Topography.objects.get(id=topo.id)
    assert not new_topo.height_scale_editable
    assert math.isclose(new_topo.height_scale, 0.296382712790741, abs_tol=1e-8)


@pytest.mark.django_db
def test_renew_cache(mocker):
    Topography2DFactory()
    renew_cache_mock = mocker.patch('topobank.manager.models.Topography.renew_cache')

    call_command('renew_cache', background=False)

    assert renew_cache_mock.called
