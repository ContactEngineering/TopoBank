"""
Testing management commands for manager app.
"""
from django.core.management import call_command
from django.shortcuts import reverse

import pytest
import datetime
from pathlib import Path
import tempfile

from topobank.manager.models import Surface
from topobank.manager.tests.utils import UserFactory, FIXTURE_DIR, SurfaceFactory, \
    Topography2DFactory, Topography1DFactory


@pytest.mark.django_db
def test_import_downloaded_surface_archive(client):

    username = 'test_user'
    surface_name = "Test Surface for Import"
    surface_category = 'dum'
    user = UserFactory(username=username)
    surface = SurfaceFactory(creator=user, name=surface_name, category=surface_category)
    topo1 = Topography2DFactory(surface=surface, name='2D Measurement', size_x=10, size_y=10, unit='mm')
    topo2 = Topography1DFactory(surface=surface, name='1D Measurement', size_x=10, unit='µm')

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





