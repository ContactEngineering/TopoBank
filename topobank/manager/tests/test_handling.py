import datetime
import os.path
import yaml
import zipfile
from pathlib import Path
from io import BytesIO

import pytest
from pytest import approx

import requests

from django.shortcuts import reverse
from django.conf import settings
from django.core.files.storage import default_storage
from django.utils.text import slugify
from rest_framework.test import APIRequestFactory

from trackstats.models import Metric, Period


from .utils import FIXTURE_DIR, SurfaceFactory, Topography1DFactory, Topography2DFactory, UserFactory, two_topos, \
    one_line_scan
from ..models import Topography, Surface, MAX_LENGTH_DATAFILE_FORMAT
from ..views import DEFAULT_CONTAINER_FILENAME

from topobank.utils import assert_in_content, \
    assert_redirects, assert_no_form_errors, assert_form_error


def _upload_file(fn, surface_id, api_client, django_capture_on_commit_callbacks, final_task_state='su',
                 **kwargs):
    # create new topography (and request file upload location)
    name = fn.split('/')[-1]
    response = api_client.post(reverse('manager:topography-api-list'),
                               {
                                   'surface': reverse('manager:surface-api-detail',
                                                      kwargs=dict(pk=surface_id)),
                                   'name': name,
                                   **kwargs
                               })
    assert response.status_code == 201, response.data  # Created
    topography_id = response.data['id']

    # upload file
    post_data = response.data['post_data']  # The POST request above informs us how to upload the file
    with open(fn, mode='rb') as fp:
        # We need to use `requests` as the upload is directly to S3, not to the Django app
        response = requests.post(post_data['url'], data={**post_data['fields']}, files={'file': fp})
    assert response.status_code == 204, response.data  # Created

    # We need to execute on commit actions, because this is where the renew_cache task is triggered
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        # Get info on file (this will trigger the inspection). In the production instance, the first GET triggers a
        # background (Celery) task and always returns a 'pe'nding state. In this testing environment, this is run
        # immediately after the `save` but not yet reflected in the returned dictionary.
        response = api_client.get(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)))
        assert response.status_code == 200, response.data
        assert response.data['task_state'] == 'pe'
        # We need to close the commit capture here because the file inspection runs on commit

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        # Get info on file again, this should not report a successful file inspection.
        response = api_client.get(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)))
        assert response.status_code == 200, response.data
        assert response.data['task_state'] == final_task_state

    return response


#######################################################################
# Selections
#######################################################################

@pytest.mark.django_db
def test_empty_surface_selection(client, handle_usage_statistics):
    #
    # database objects
    #
    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    assert surface.topography_set.count() == 0

    client.force_login(user)

    client.post(reverse('manager:surface-select', kwargs=dict(pk=surface.pk)))

    #
    # Now the selection should contain one empty surface
    #
    assert client.session['selection'] == [f'surface-{surface.pk}']


@pytest.mark.django_db
def test_download_selection(client, mocker, handle_usage_statistics):
    record_mock = mocker.patch('trackstats.models.StatisticByDateAndObject.objects.record')

    user = UserFactory()
    surface1 = SurfaceFactory(creator=user)
    surface2 = SurfaceFactory(creator=user)
    topo1a = Topography1DFactory(surface=surface1)
    topo1b = Topography2DFactory(surface=surface1)
    topo2a = Topography1DFactory(surface=surface2)

    factory = APIRequestFactory()

    request = factory.get(reverse('manager:download-selection'))
    request.user = user
    request.session = {
        'selection': [f'topography-{topo1a.id}', f'surface-{surface2.id}']
    }
    from ..views import download_selection_as_surfaces
    response = download_selection_as_surfaces(request)
    assert response.status_code == 200, response.data
    assert response['Content-Disposition'] == f'attachment; filename="{DEFAULT_CONTAINER_FILENAME}"'

    # open zip file and look into meta file, there should be two surfaces and three topographies
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        meta_file = zf.open('meta.yml')
        meta = yaml.safe_load(meta_file)
        assert len(meta['surfaces']) == 2
        assert len(meta['surfaces'][0]['topographies']) == 2
        assert len(meta['surfaces'][1]['topographies']) == 1

    # each downloaded surface is counted once
    metric = Metric.objects.SURFACE_DOWNLOAD_COUNT
    today = datetime.date.today()
    if settings.ENABLE_USAGE_STATS:
        record_mock.assert_any_call(metric=metric, object=surface1, period=Period.DAY,
                                    value=1, date=today)
        record_mock.assert_any_call(metric=metric, object=surface2, period=Period.DAY,
                                    value=1, date=today)


#######################################################################
# Topographies
#######################################################################

#
# Different formats are handled by SurfaceTopography
# and should be tested there in general, but
# we add some tests for formats which had problems because
# of the topobank code
#
@pytest.mark.django_db
def test_upload_topography_di(api_client, settings, handle_usage_statistics, django_capture_on_commit_callbacks):
    settings.CELERY_TASK_ALWAYS_EAGER = True  # perform tasks locally

    name = 'example3.di'
    input_file_path = Path(f'{FIXTURE_DIR}/{name}')  # maybe use package 'pytest-datafiles' here instead
    description = "test description"
    category = 'exp'

    user = UserFactory()

    api_client.force_login(user)

    # first create a surface
    response = api_client.post(reverse('manager:surface-api-list'))
    assert response.status_code == 201, response.data  # Created
    surface_id = response.data['id']

    # populate surface with some info
    response = api_client.patch(reverse('manager:surface-api-detail', kwargs=dict(pk=surface_id)),
                                {
                                    'name': 'surface1',
                                    'category': category,
                                    'description': description
                                })
    assert response.status_code == 200, response.data

    response = _upload_file(str(input_file_path), surface_id, api_client, django_capture_on_commit_callbacks)

    # we should have four datasources as options
    assert response.data['name'] == 'example3.di'
    assert response.data['channel_names'] == [['ZSensor', 'nm'], ['AmplitudeError', None],
                                              ['Phase', None], ['Height', 'nm']]

    # Update metadata
    topography_id = response.data['id']
    response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                {
                                    'measurement_date': '2018-06-21',
                                    'data_source': 0,
                                    'description': description,
                                })
    assert response.status_code == 200, response.data
    assert response.data['measurement_date'] == '2018-06-21'
    assert response.data['description'] == description

    # Update more metadata
    response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                {
                                    'size_x': '9000',
                                    'size_y': '9000',
                                    'unit': 'nm',
                                    'height_scale': 0.3,
                                    'detrend_mode': 'height',
                                    'resolution_x': 256,
                                    'resolution_y': 256,
                                    'instrument_type': Topography.INSTRUMENT_TYPE_UNDEFINED,
                                    'fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
                                })
    assert response.status_code == 400, response.data

    # Check that updating fixed metadata leads to an error
    response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                {
                                    'size_x': '1.0',
                                })
    assert response.status_code == 400, response.data

    response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                {
                                    'unit': 'm',
                                    'height_scale': 1.3,
                                })
    assert response.status_code == 400, response.data

    response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                {
                                    'resolution_x': 300,
                                })
    assert response.status_code == 400, response.data  # resolution_x is read only

    surface = Surface.objects.get(name='surface1')
    topos = surface.topography_set.all()

    assert len(topos) == 1

    t = topos[0]

    assert t.measurement_date == datetime.date(2018, 6, 21)
    assert t.description == description
    assert "example3" in t.datafile.name
    assert 256 == t.resolution_x
    assert 256 == t.resolution_y
    assert t.creator == user
    assert t.datafile_format == 'di'


@pytest.mark.django_db
def test_upload_topography_npy(api_client, settings, handle_usage_statistics, django_capture_on_commit_callbacks):
    settings.CELERY_TASK_ALWAYS_EAGER = True  # perform tasks locally

    user = UserFactory()
    surface = SurfaceFactory(creator=user, name="surface1")
    description = "Some description"
    api_client.force_login(user)

    # upload file
    name = 'example-2d.npy'
    input_file_path = Path(f'{FIXTURE_DIR}/{name}')  # maybe use package 'pytest-datafiles' here instead
    response = _upload_file(str(input_file_path), surface.id, api_client, django_capture_on_commit_callbacks)

    # idiot-check some response properties
    assert response.data['name'] == 'example-2d.npy'

    # Updated metadata
    topography_id = response.data['id']
    response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                {
                                    'measurement_date': '2020-10-21',
                                    'data_source': 0,
                                    'description': description,
                                })
    assert response.status_code == 200, response.data
    assert response.data['measurement_date'] == '2020-10-21'
    assert response.data['description'] == description

    # Update more metadata
    response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                {
                                    'size_x': '1',
                                    'size_y': '1',
                                    'unit': 'nm',
                                    'height_scale': 1,
                                    'detrend_mode': 'height',
                                    'resolution_x': 2,
                                    'resolution_y': 2,
                                    'instrument_type': Topography.INSTRUMENT_TYPE_UNDEFINED,
                                    'fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
                                })
    assert response.status_code == 400, response.data  # resolution_x and resolution_y are read only

    # Update more metadata
    response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                {
                                    'size_x': '1',
                                    'size_y': '1',
                                    'unit': 'nm',
                                    'height_scale': 1,
                                    'detrend_mode': 'height',
                                    'instrument_type': Topography.INSTRUMENT_TYPE_UNDEFINED,
                                    'fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
                                })
    assert response.status_code == 200, response.data  # without resolution_x and resolution_y

    surface = Surface.objects.get(name='surface1')
    topos = surface.topography_set.all()

    assert len(topos) == 1

    t = topos[0]

    assert t.measurement_date == datetime.date(2020, 10, 21)
    assert t.description == description
    assert "example-2d" in t.datafile.name
    assert 2 == t.resolution_x
    assert 2 == t.resolution_y
    assert t.creator == user
    assert t.datafile_format == 'npy'


@pytest.mark.parametrize(("input_filename", "exp_datafile_format",
                          "exp_resolution_x", "exp_resolution_y",
                          "physical_sizes_to_be_set", "exp_physical_sizes"),
                         [(FIXTURE_DIR + "/10x10.txt", 'asc', 10, 10, (1, 1), (1, 1)),
                          (FIXTURE_DIR + "/line_scan_1.asc", 'xyz', 11, None, None, (9.0,)),
                          (FIXTURE_DIR + "/line_scan_1_minimal_spaces.asc", 'xyz', 11, None, None, (9.0,)),
                          (FIXTURE_DIR + "/example6.txt", 'asc', 9, None, (1.,), (1.,))])
# Add this for a larger file: ("topobank/manager/fixtures/500x500_random.txt", 500)]) # takes quire long
@pytest.mark.django_db
def test_upload_topography_txt(api_client, django_user_model, django_capture_on_commit_callbacks,
                               input_filename,
                               exp_datafile_format,
                               exp_resolution_x, exp_resolution_y,
                               physical_sizes_to_be_set, exp_physical_sizes,
                               handle_usage_statistics):
    settings.CELERY_TASK_ALWAYS_EAGER = True  # perform tasks locally

    input_file_path = Path(input_filename)
    expected_toponame = input_file_path.name

    description = "test description"

    username = 'testuser'
    password = 'abcd$1234'

    user = django_user_model.objects.create_user(username=username, password=password)

    assert api_client.login(username=username, password=password)

    # first create a surface
    response = api_client.post(reverse('manager:surface-api-list'),
                               data={
                                   'name': 'surface1',
                                   'category': 'sim'
                               })
    assert response.status_code == 201, response.data

    # populate surface with some info
    surface_id = response.data['id']
    response = api_client.patch(reverse('manager:surface-api-detail', kwargs=dict(pk=surface_id)),
                                {
                                    'category': 'exp',
                                    'description': description
                                })
    assert response.status_code == 200, response.data

    response = _upload_file(str(input_file_path), surface_id, api_client, django_capture_on_commit_callbacks)
    assert response.data['name'] == expected_toponame

    # Updated metadata
    topography_id = response.data['id']
    response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                {
                                    'measurement_date': '2018-06-21',
                                    'data_source': 0,
                                    'description': description,
                                })
    assert response.status_code == 200, response.data
    assert response.data['measurement_date'] == '2018-06-21'
    assert response.data['description'] == description

    # Update more metadata
    if exp_resolution_y is None:
        data = {}
        if physical_sizes_to_be_set is not None:
            data['size_x'] = physical_sizes_to_be_set[0]
        response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                    {
                                        **data,
                                        'unit': 'nm',
                                        'height_scale': 1,
                                        'detrend_mode': 'height',
                                        'instrument_type': Topography.INSTRUMENT_TYPE_UNDEFINED,
                                        'fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
                                    })
    else:
        data = {}
        if physical_sizes_to_be_set is not None:
            data['size_x'] = physical_sizes_to_be_set[0]
            data['size_y'] = physical_sizes_to_be_set[1]
        response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=topography_id)),
                                    {
                                        **data,
                                        'unit': 'nm',
                                        'height_scale': 1,
                                        'detrend_mode': 'height',
                                        'instrument_type': Topography.INSTRUMENT_TYPE_UNDEFINED,
                                        'fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
                                    })
    assert response.status_code == 200, response.data

    surface = Surface.objects.get(name='surface1')
    topos = surface.topography_set.all()

    assert len(topos) == 1

    t = topos[0]

    assert t.measurement_date == datetime.date(2018, 6, 21)
    assert t.description == description
    assert input_file_path.stem in t.datafile.name
    assert exp_resolution_x == t.resolution_x
    assert exp_resolution_y == t.resolution_y
    assert t.datafile_format == exp_datafile_format
    assert t.instrument_type == Topography.INSTRUMENT_TYPE_UNDEFINED
    assert t.instrument_parameters == {}

    #
    # Also check some properties of the SurfaceTopography.Topography
    #
    st_topo = t.topography(allow_cache=False, allow_squeezed=False)
    assert st_topo.physical_sizes == exp_physical_sizes


@pytest.mark.parametrize("instrument_type,resolution_value,resolution_unit,tip_radius_value,tip_radius_unit",
                         [
                             (Topography.INSTRUMENT_TYPE_UNDEFINED, '', '', '', ''),  # empty instrument params
                             (Topography.INSTRUMENT_TYPE_UNDEFINED, 10.0, 'km', 2.0, 'nm'),  # also empty params
                             (Topography.INSTRUMENT_TYPE_MICROSCOPE_BASED, 10.0, 'nm', '', ''),
                             (Topography.INSTRUMENT_TYPE_MICROSCOPE_BASED, '', 'nm', '', ''),  # no value! -> also empty
                             (Topography.INSTRUMENT_TYPE_CONTACT_BASED, '', '', 1.0, 'mm'),
                             (Topography.INSTRUMENT_TYPE_CONTACT_BASED, '', '', '', 'mm'),  # no value! -> also empty
                         ])
@pytest.mark.django_db
def test_upload_topography_instrument_parameters(api_client, settings, django_capture_on_commit_callbacks,
                                                 django_user_model,
                                                 instrument_type, resolution_value,
                                                 resolution_unit, tip_radius_value, tip_radius_unit,
                                                 handle_usage_statistics):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    input_file_path = Path(FIXTURE_DIR + "/10x10.txt")
    expected_toponame = input_file_path.name

    description = "test description"

    username = 'testuser'
    password = 'abcd$1234'

    instrument_name = "My Profilometer"

    user = django_user_model.objects.create_user(username=username, password=password)

    assert api_client.login(username=username, password=password)

    # first create a surface
    response = api_client.post(reverse('manager:surface-api-list'),
                               {
                                   'name': 'surface1',
                                   'category': 'sim'
                               })
    assert response.status_code == 201

    surface = Surface.objects.get(name='surface1')

    response = _upload_file(str(input_file_path), surface.id, api_client, django_capture_on_commit_callbacks)
    assert response.data['name'] == expected_toponame

    # create parameters dictionary
    instrument_parameters = {}
    if instrument_type == Topography.INSTRUMENT_TYPE_MICROSCOPE_BASED:
        instrument_parameters['resolution'] = {
            'value': resolution_value,
            'unit': resolution_unit
        }
    elif instrument_type == Topography.INSTRUMENT_TYPE_CONTACT_BASED:
        instrument_parameters['tip_radius'] = {
            'value': tip_radius_value,
            'unit': tip_radius_unit
        }

    # Update metadata
    response = api_client.patch(reverse('manager:topography-api-detail',
                                        kwargs=dict(pk=response.data['id'])),
                                {
                                    'name': 'topo1',
                                    'measurement_date': '2018-06-21',
                                    'data_source': 0,
                                    'description': description,
                                    'size_x': 1,
                                    'size_y': 1,
                                    'unit': 'nm',
                                    'height_scale': 1,
                                    'detrend_mode': 'height',
                                    'instrument_name': instrument_name,
                                    'instrument_type': instrument_type,
                                    'instrument_parameters': instrument_parameters,
                                    'fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
                                })
    assert response.status_code == 200, response.data

    surface = Surface.objects.get(name='surface1')
    topos = surface.topography_set.all()

    assert len(topos) == 1

    t = topos[0]

    assert t.measurement_date == datetime.date(2018, 6, 21)
    assert t.description == description
    assert input_file_path.stem in t.datafile.name
    assert t.instrument_type == instrument_type
    expected_instrument_parameters = {}
    if instrument_type == Topography.INSTRUMENT_TYPE_MICROSCOPE_BASED:
        expected_instrument_parameters = {
            "resolution": {
                "value": resolution_value,
                "unit": resolution_unit,
            }
        }
        if resolution_value == '':
            del expected_instrument_parameters['resolution']['value']
    elif instrument_type == Topography.INSTRUMENT_TYPE_CONTACT_BASED:
        expected_instrument_parameters = {
            "tip_radius": {
                "value": tip_radius_value,
                "unit": tip_radius_unit,
            }
        }
        if tip_radius_value == '':
            del expected_instrument_parameters['tip_radius']['value']

    assert t.instrument_parameters == expected_instrument_parameters

    #
    # Also check some properties of the SurfaceTopography.Topography
    #
    st_topo = t.topography(allow_cache=False, allow_squeezed=False)
    assert st_topo.info["instrument"] == {'name': instrument_name,
                                          'parameters': expected_instrument_parameters,
                                          'type': instrument_type}


@pytest.mark.django_db
def test_upload_topography_and_name_like_an_existing_for_same_surface(api_client, settings,
                                                                      django_capture_on_commit_callbacks):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    input_file_path = Path(FIXTURE_DIR + "/10x10.txt")

    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    topo1 = Topography1DFactory(surface=surface,
                                name="TOPO")  # <-- we will try to create another topography named TOPO later

    api_client.force_login(user)

    response = _upload_file(str(input_file_path), surface.id, api_client, django_capture_on_commit_callbacks,
                            measurement_date='2018-06-21',
                            data_source=0,
                            description="bla")

    response = api_client.patch(reverse('manager:topography-api-detail', kwargs=dict(pk=response.data['id'])),
                                {'name': 'TOPO'})
    assert response.status_code == 400, response.data  # There can only be one topography with the same name

    # topo2 = Topography.objects.get(pk=response.data['id'])
    # Both can have same name
    # assert topo1.name == 'TOPO'
    # assert topo2.name == 'TOPO'


@pytest.mark.django_db
def test_trying_upload_of_topography_file_with_unknown_format(api_client, settings, django_capture_on_commit_callbacks,
                                                              django_user_model, handle_usage_statistics):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    input_file_path = Path(FIXTURE_DIR + "/../../static/other/CHANGELOG.md")  # this is nonsense

    username = 'testuser'
    password = 'abcd$1234'

    user = django_user_model.objects.create_user(username=username, password=password)

    assert api_client.login(username=username, password=password)

    # first create a surface
    response = api_client.post(reverse('manager:surface-api-list'),
                               data={
                                   'name': 'surface1',
                                   'category': 'dum',
                               })
    assert response.status_code == 201, response.data

    surface = Surface.objects.get(name='surface1')

    # upload file
    response = _upload_file(str(input_file_path), surface.id, api_client, django_capture_on_commit_callbacks,
                            final_task_state='fa')
    assert response.data['error'] == 'The data file is of an unknown or unsupported format.'


@pytest.mark.skip  # Skip test, this is not handled gracefully by the current implementation
@pytest.mark.django_db(transaction=True)
def test_trying_upload_of_topography_file_with_too_long_format_name(api_client, settings,
                                                                    django_capture_on_commit_callbacks,
                                                                    django_user_model, mocker,
                                                                    handle_usage_statistics):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    import SurfaceTopography.IO

    too_long_datafile_format = 'a' * (MAX_LENGTH_DATAFILE_FORMAT + 1)

    m = mocker.patch('SurfaceTopography.IO.DIReader.format')
    m.return_value = too_long_datafile_format
    # this special detect_format function returns a format which is too long
    # this should result in an error message
    assert SurfaceTopography.IO.DIReader.format() == too_long_datafile_format

    input_file_path = Path(FIXTURE_DIR + '/example3.di')

    user = UserFactory()

    api_client.force_login(user)

    surface = SurfaceFactory(creator=user)

    response = _upload_file(str(input_file_path), surface.id, api_client, django_capture_on_commit_callbacks)
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_trying_upload_of_corrupted_topography_file(api_client, settings, django_capture_on_commit_callbacks,
                                                    django_user_model):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    input_file_path = Path(FIXTURE_DIR + '/example3_corrupt.di')
    # I used the correct file "example3.di" and broke it on purpose
    # The headers are still okay, but the topography can't be read by PyCo
    # using .topography() and leads to a "ValueError: buffer is smaller
    # than requested size"

    description = "test description"
    category = 'exp'

    username = 'testuser'
    password = 'abcd$1234'

    user = django_user_model.objects.create_user(username=username, password=password)

    assert api_client.login(username=username, password=password)

    # first create a surface
    response = api_client.post(reverse('manager:surface-api-list'),
                               {
                                   'name': 'surface1',
                                   'category': category,
                               })
    assert response.status_code == 201, response.data

    surface = Surface.objects.get(name='surface1')

    # file upload
    response = _upload_file(str(input_file_path), surface.id, api_client, django_capture_on_commit_callbacks,
                            final_task_state='fa')

    # This should yield an error
    assert response.data['error'] == 'The data file is of an unknown or unsupported format.'

    #
    # Topography has been saved, but with state failed
    #
    surface = Surface.objects.get(name='surface1')
    topos = surface.topography_set.all()

    assert len(topos) == 1
    assert topos[0].task_state == 'fa'
    assert topos[0].task_error == 'The data file is of an unknown or unsupported format.'


@pytest.mark.django_db
def test_upload_opd_file_check(api_client, settings, django_capture_on_commit_callbacks, handle_usage_statistics):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    user = UserFactory()
    surface = SurfaceFactory(creator=user, name="surface1")
    description = "Some description"
    api_client.force_login(user)

    # file upload
    input_file_path = Path(FIXTURE_DIR + '/example.opd')  # maybe use package 'pytest-datafiles' here instead
    response = _upload_file(str(input_file_path), surface.id, api_client, django_capture_on_commit_callbacks,
                            measurement_date='2021-06-09',
                            description=description,
                            detrend_mode='height')

    assert response.data['channel_names'] == [['Raw', 'mm']]
    assert response.data['name'] == 'example.opd'

    # check whether known values for size and height scale are in content
    assert response.data['size_x'] == approx(0.1485370245)
    assert response.data['size_y'] == approx(0.1500298589)
    assert response.data['height_scale'] == approx(0.0005343980102539062)

    surface = Surface.objects.get(name='surface1')
    topos = surface.topography_set.all()

    assert len(topos) == 1

    t = topos[0]

    assert t.measurement_date == datetime.date(2021, 6, 9)
    assert t.description == description
    assert "example" in t.datafile.name
    assert t.size_x == approx(0.1485370245)
    assert t.size_y == approx(0.1500298589)
    assert t.resolution_x == approx(199)
    assert t.resolution_y == approx(201)
    assert t.height_scale == approx(0.0005343980102539062)
    assert t.creator == user
    assert t.datafile_format == 'opd'
    assert not t.size_editable
    assert not t.height_scale_editable
    assert not t.unit_editable


@pytest.mark.django_db
def test_topography_list(client, two_topos, django_user_model, handle_usage_statistics):
    username = 'testuser'
    password = 'abcd$1234'

    assert client.login(username=username, password=password)

    # response = client.get(reverse('manager:surface-detail', kwargs=dict(pk=1)))

    #
    # all topographies for 'testuser' and surface1 should be listed
    #
    surface = Surface.objects.get(name="Surface 1", creator__username=username)
    topos = Topography.objects.filter(surface=surface)

    response = client.get(reverse('manager:surface-detail', kwargs=dict(pk=surface.pk)))

    content = str(response.content)
    for t in topos:
        # currently 'listed' means: name in list
        assert t.name in content

        # click on a bar should lead to details, so URL must be included
        assert reverse('manager:topography-detail', kwargs=dict(pk=t.pk)) in content

        # TODO tests missing for bar length and position (selenium??)


@pytest.fixture
def topo_example3(two_topos):
    return Topography.objects.get(name='Example 3 - ZSensor')


@pytest.fixture
def topo_example4(two_topos):
    return Topography.objects.get(name='Example 4 - Default')


@pytest.mark.django_db
def test_edit_topography(client, django_user_model, topo_example3, handle_usage_statistics):
    new_name = "This is a better name"
    new_measurement_date = "2018-07-01"
    new_description = "New results available"

    username = 'testuser'
    password = 'abcd$1234'

    assert client.login(username=username, password=password)

    #
    # First get the form and look whether all the expected data is in there
    #
    response = client.get(reverse('manager:topography-update', kwargs=dict(pk=topo_example3.pk)))
    assert response.status_code == 200

    assert 'form' in response.context

    form = response.context['form']
    initial = form.initial

    assert initial['name'] == topo_example3.name
    assert initial['measurement_date'] == datetime.date(2018, 1, 1)
    assert initial['description'] == 'description1'
    assert initial['size_x'] == approx(10)
    assert initial['size_y'] == approx(10)
    assert initial['height_scale'] == approx(0.29638271279074097)
    assert initial['detrend_mode'] == 'height'

    #
    # Then send a post with updated data
    #
    response = client.post(reverse('manager:topography-update', kwargs=dict(pk=topo_example3.pk)),
                           data={
                               'save-stay': 1,  # we want to save, but stay on page
                               'surface': topo_example3.surface.pk,
                               'data_source': 0,
                               'name': new_name,
                               'measurement_date': new_measurement_date,
                               'description': new_description,
                               'size_x': 500,
                               'size_y': 1000,
                               'unit': 'nm',
                               'height_scale': 0.1,
                               'detrend_mode': 'height',
                               'tags': 'ab, bc',  # needs a string
                               'instrument_type': Topography.INSTRUMENT_TYPE_UNDEFINED,
                               'fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
                               'has_undefined_data': False,
                           }, follow=True)

    assert_no_form_errors(response)
    assert_in_content(response, 'Fill undefined data mode')

    # we should stay on the update page for this topography
    assert_redirects(response, reverse('manager:topography-update', kwargs=dict(pk=topo_example3.pk)))

    #
    # let's check whether it has been changed
    #
    topos = Topography.objects.filter(surface=topo_example3.surface).order_by('pk')

    assert len(topos) == 1

    t = topos[0]

    assert t.measurement_date == datetime.date(2018, 7, 1)
    assert t.description == new_description
    assert t.name == new_name
    assert "example3" in t.datafile.name
    assert t.size_x == approx(500)
    assert t.size_y == approx(1000)
    assert t.tags == ['ab', 'bc']

    #
    # the changed topography should also appear in the list of topographies
    #
    response = client.get(reverse('manager:surface-detail', kwargs=dict(pk=t.surface.pk)))
    assert bytes(new_name, 'utf-8') in response.content


@pytest.mark.django_db
def test_edit_line_scan(client, one_line_scan, django_user_model, handle_usage_statistics):
    new_name = "This is a better name"
    new_measurement_date = "2018-07-01"
    new_description = "New results available"

    username = 'testuser'
    password = 'abcd$1234'

    topo_id = one_line_scan.id
    surface_id = one_line_scan.surface.id

    assert client.login(username=username, password=password)

    #
    # First get the form and look whether all the expected data is in there
    #
    response = client.get(reverse('manager:topography-update', kwargs=dict(pk=topo_id)))
    assert response.status_code == 200

    assert 'form' in response.context

    form = response.context['form']
    initial = form.initial

    assert initial['name'] == 'Simple Line Scan'
    assert initial['measurement_date'] == datetime.date(2018, 1, 1)
    assert initial['description'] == 'description1'
    assert initial['size_x'] == 9
    assert initial['height_scale'] == approx(1.)
    assert initial['detrend_mode'] == 'height'
    assert 'size_y' not in form.fields  # should have been removed by __init__
    assert initial['is_periodic'] == False

    #
    # Then send a post with updated data
    #
    response = client.post(reverse('manager:topography-update', kwargs=dict(pk=topo_id)),
                           data={
                               'save-stay': 1,  # we want to save, but stay on page
                               'surface': surface_id,
                               'data_source': 0,
                               'name': new_name,
                               'measurement_date': new_measurement_date,
                               'description': new_description,
                               'size_x': 500,
                               'unit': 'nm',
                               'height_scale': 0.1,
                               'detrend_mode': 'height',
                               'instrument_type': Topography.INSTRUMENT_TYPE_UNDEFINED,
                               'fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
                               'has_undefined_data': False,
                           })

    assert response.context is None, "Errors in form: {}".format(response.context['form'].errors)
    assert response.status_code == 302

    # due to the changed topography editing, we should stay on update page
    assert reverse('manager:topography-update', kwargs=dict(pk=topo_id)) == response.url

    topos = Topography.objects.filter(surface__creator__username=username).order_by('pk')

    assert len(topos) == 1

    t = topos[0]

    assert t.measurement_date == datetime.date(2018, 7, 1)
    assert t.description == new_description
    assert t.name == new_name
    assert "line_scan_1" in t.datafile.name
    assert t.size_x == approx(500)
    assert t.size_y is None

    #
    # should also appear in the list of topographies
    #
    response = client.get(reverse('manager:surface-detail', kwargs=dict(pk=t.surface.pk)))
    assert bytes(new_name, 'utf-8') in response.content


@pytest.mark.django_db
def test_edit_topography_only_detrend_center_when_periodic(client, django_user_model):
    input_file_path = Path(FIXTURE_DIR + "/10x10.txt")
    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    client.force_login(user)

    #
    # Create a topography without sizes given in original file
    #
    # Step 1
    with input_file_path.open(mode='rb') as fp:
        response = client.post(reverse('manager:topography-create',
                                       kwargs=dict(surface_id=surface.id)),
                               data={
                                   'topography_create_wizard-current_step': 'upload',
                                   'upload-datafile': fp,
                                   'upload-surface': surface.id,
                               }, follow=True)

    assert response.status_code == 200
    assert_no_form_errors(response)

    #
    # Step 2
    #
    response = client.post(reverse('manager:topography-create',
                                   kwargs=dict(surface_id=surface.id)),
                           data={
                               'topography_create_wizard-current_step': 'metadata',
                               'metadata-name': 'topo1',
                               'metadata-measurement_date': '2019-11-22',
                               'metadata-data_source': 0,
                               'metadata-description': "only for test",
                           })

    assert response.status_code == 200
    assert_no_form_errors(response)

    #
    # Step 3
    #
    response = client.post(reverse('manager:topography-create',
                                   kwargs=dict(surface_id=surface.id)),
                           data={
                               'topography_create_wizard-current_step': 'units',
                               'units-size_x': '9',
                               'units-size_y': '9',
                               'units-unit': 'nm',
                               'units-height_scale': 1,
                               'units-detrend_mode': 'height',
                               'units-resolution_x': 10,
                               'units-resolution_y': 10,
                               'units-instrument_type': Topography.INSTRUMENT_TYPE_UNDEFINED,
                               'units-instrument_name': '',
                               'units-instrument_parameters': {},
                               'units-fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
                           })

    assert response.status_code == 302

    # there should be only one topography now
    topo = Topography.objects.get(surface=surface)

    #
    # First get the form and look whether all the expected data is in there
    #
    response = client.get(reverse('manager:topography-update', kwargs=dict(pk=topo.pk)))
    assert response.status_code == 200
    assert 'form' in response.context

    #
    # Then send a post with updated data
    #
    response = client.post(reverse('manager:topography-update', kwargs=dict(pk=topo.pk)),
                           data={
                               'save-stay': 1,  # we want to save, but stay on page
                               'surface': surface.pk,
                               'data_source': 0,
                               'name': topo.name,
                               'measurement_date': topo.measurement_date,
                               'description': topo.description,
                               'size_x': 500,
                               'size_y': 1000,
                               'unit': 'nm',
                               'height_scale': 0.1,
                               'detrend_mode': 'height',
                               'is_periodic': True,  # <--------- this should not be allowed with detrend_mode 'height'
                               'instrument_type': Topography.INSTRUMENT_TYPE_MICROSCOPE_BASED,
                               'instrument_parameters': "{'resolution': { 'value': 1, 'unit':'mm'}}",
                               'instrument_name': 'AFM',
                               'fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
                               'has_undefined_data': False,
                           }, follow=True)

    assert Topography.DETREND_MODE_CHOICES[0][0] == 'center'
    # this asserts that the clean() method of form has the correct reference

    assert_form_error(response, "When enabling periodicity only detrend mode", "detrend_mode")


@pytest.mark.parametrize("kind", ["resolution", "tip_radius"])
@pytest.mark.django_db
def test_instrument_parameters_empty_if_no_value_on_topography_change(client, handle_usage_statistics, kind):
    """Check whether instrument parameters are empty if no value was given
    """
    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    topo = Topography2DFactory(surface=surface, size_x=1, size_y=1, size_editable=True,
                               instrument_type=Topography.INSTRUMENT_TYPE_CONTACT_BASED,
                               instrument_parameters={
                                   kind: {
                                       "value": 1.0,
                                       "unit": "mm"
                                   }
                               })
    client.force_login(user)

    changed_data_for_post = {
        'save-stay': 'Save and keep editing',  # we want to save, but stay on page
        'surface': str(surface.pk),
        'data_source': str(topo.data_source),
        'description': topo.description,
        'name': topo.name,
        'size_x': str(topo.size_x),
        'size_y': str(topo.size_y),
        'size_editable': "True",
        'unit': topo.unit,
        'unit_editable': "True",
        'height_scale': str(topo.height_scale),
        'height_scale_editable': "True",
        'detrend_mode': 'center',
        'measurement_date': format(topo.measurement_date, '%Y-%m-%d'),
        'tags': '',
        'instrument_name': '',
        'instrument_type': topo.instrument_type,
        'instrument_parameters': f'{{"{kind}": {{ "value": 1.0, "unit": "mm"}} }}',
        # add some helper fields which have been added to the form, such that
        # the POST request has all parameters as the original HTML form
        'tip_radius_value': '',  # No value
        'tip_radius_unit': 'mm',
        'fill_undefined_data_mode': Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
    }

    #
    # we post the changed data, instrument parameters should saved as empty
    #
    response = client.post(reverse('manager:topography-update', kwargs=dict(pk=topo.pk)),
                           data=changed_data_for_post, follow=True)
    assert_no_form_errors(response)
    assert response.status_code == 200

    changed_topo = Topography.objects.get(pk=topo.pk)
    assert changed_topo.instrument_parameters == {}


@pytest.mark.django_db
def test_topography_detail(client, two_topos, django_user_model, topo_example4, handle_usage_statistics):
    username = 'testuser'
    password = 'abcd$1234'

    topo_pk = topo_example4.pk

    django_user_model.objects.get(username=username)

    assert client.login(username=username, password=password)

    response = client.get(reverse('manager:topography-detail', kwargs=dict(pk=topo_pk)))
    assert response.status_code == 200

    # resolution should be written somewhere
    assert_in_content(response, "305 x 75")

    # .. as well as detrending mode
    assert_in_content(response, "Remove tilt")

    # .. description
    assert_in_content(response, "description2")

    # .. physical size
    assert_in_content(response, "112.80791 µm x 27.73965 µm")


@pytest.mark.django_db
def test_delete_topography(client, two_topos, django_user_model, topo_example3, handle_usage_statistics):
    username = 'testuser'
    password = 'abcd$1234'

    # topography 1 is still in database
    topo = topo_example3
    surface = topo.surface

    # make squeezed datafile
    topo.renew_squeezed_datafile()
    topo.renew_images()

    # store names of files in storage system
    pk = topo.pk
    topo_datafile_name = topo.datafile.name
    squeezed_datafile_name = topo.squeezed_datafile.name
    thumbnail_name = topo.thumbnail.name
    dzi_name = f'{topo.storage_prefix}/dzi'

    # check that files actually exist
    assert default_storage.exists(topo_datafile_name)
    assert default_storage.exists(squeezed_datafile_name)
    assert default_storage.exists(thumbnail_name)
    assert default_storage.exists(f'{dzi_name}/dzi.json')
    assert default_storage.exists(f'{dzi_name}/dzi_files/0/0_0.jpg')

    assert client.login(username=username, password=password)

    response = client.get(reverse('manager:topography-delete', kwargs=dict(pk=pk)))

    # user should be asked if he/she is sure
    assert b'Are you sure' in response.content

    response = client.post(reverse('manager:topography-delete', kwargs=dict(pk=pk)))

    # user should be redirected to surface details
    assert reverse('manager:surface-detail', kwargs=dict(pk=surface.pk)) == response.url

    # topography topo_id is no more in database
    assert not Topography.objects.filter(pk=pk).exists()

    # topography file should also be deleted
    assert not default_storage.exists(topo_datafile_name)
    assert not default_storage.exists(squeezed_datafile_name)
    assert not default_storage.exists(thumbnail_name)
    assert not default_storage.exists(f'{dzi_name}/dzi.json')
    assert not default_storage.exists(f'{dzi_name}/dzi_files/0/0_0.jpg')


@pytest.mark.skip("Cannot be implemented up to now, because don't know how to reuse datafile")
@pytest.mark.django_db
def test_delete_topography_with_its_datafile_used_by_others(client, two_topos, django_user_model):
    username = 'testuser'
    password = 'abcd$1234'
    topo_id = 1

    # topography 1 is still in database
    topo = Topography.objects.get(pk=topo_id)
    surface = topo.surface

    topo_datafile_path = topo.datafile.path

    # make topography 2 use the same datafile
    topo2 = Topography.objects.get(pk=2)
    topo2.datafile.path = topo_datafile_path  # This does not work

    assert client.login(username=username, password=password)

    response = client.get(reverse('manager:topography-delete', kwargs=dict(pk=topo_id)))

    # user should be asked if he/she is sure
    assert b'Are you sure' in response.content

    response = client.post(reverse('manager:topography-delete', kwargs=dict(pk=topo_id)))

    # user should be redirected to surface details
    assert reverse('manager:surface-detail', kwargs=dict(pk=surface.pk)) == response.url

    # topography topo_id is no more in database
    assert not Topography.objects.filter(pk=topo_id).exists()

    # topography file should **not** have been deleted, because still used by topo2
    assert os.path.exists(topo_datafile_path)


@pytest.mark.django_db
def test_only_positive_size_values_on_edit(client, handle_usage_statistics):
    #
    # prepare database
    #
    username = 'testuser'
    password = 'abcd$1234'

    user = UserFactory(username=username, password=password)
    surface = SurfaceFactory(creator=user)
    topography = Topography2DFactory(surface=surface, size_x=1024, size_y=1024, size_editable=True)

    assert client.login(username=username, password=password)

    #
    # Then send a post with negative size values
    #
    response = client.post(reverse('manager:topography-update', kwargs=dict(pk=topography.pk)),
                           data={
                               'surface': surface.id,
                               'data_source': topography.data_source,
                               'name': topography.name,
                               'measurement_date': topography.measurement_date,
                               'description': topography.description,
                               'size_x': -500.0,  # negative, should be > 0
                               'size_y': 0,  # zero, should be > 0
                               'unit': 'nm',
                               'height_scale': 0.1,
                               'detrend_mode': 'height',
                               'instrument_type': Topography.INSTRUMENT_TYPE_UNDEFINED,
                               'instrument_parameters': '{}',
                               'instrument_name': '',
                           })

    assert response.status_code == 200
    assert 'form' in response.context
    assert "Size x must be greater than zero" in response.context['form'].errors['size_x'][0]
    assert "Size y must be greater than zero" in response.context['form'].errors['size_y'][0]


#######################################################################
# Surfaces
#######################################################################

@pytest.mark.django_db
def test_create_surface(client, django_user_model, handle_usage_statistics):
    description = "My description. hasdhahdlahdla"
    name = "Surface 1 kjfhakfhökadsökdf"
    category = "exp"

    username = 'testuser'
    password = 'abcd$1234'

    user = django_user_model.objects.create_user(username=username, password=password)

    assert client.login(username=username, password=password)

    assert 0 == Surface.objects.count()

    #
    # Create first surface
    #
    response = client.post(reverse('manager:surface-create'),
                           data={
                               'name': name,
                               'creator': user.id,
                               'description': description,
                               'category': category,
                           }, follow=True)

    assert ('context' not in response) or ('form' not in response.context), "Still on form: {}".format(
        response.context['form'].errors)

    assert response.status_code == 200

    assert description.encode() in response.content
    assert name.encode() in response.content
    assert b"Experimental data" in response.content

    assert 1 == Surface.objects.count()


@pytest.mark.django_db
def test_edit_surface(client):
    category = 'sim'

    user = UserFactory()
    surface = SurfaceFactory(creator=user, category=category)

    client.force_login(user)

    new_name = "This is a better surface name"
    new_description = "This is new description"
    new_category = 'dum'

    response = client.post(reverse('manager:surface-update', kwargs=dict(pk=surface.id)),
                           data={
                               'name': new_name,
                               'creator': user.id,
                               'description': new_description,
                               'category': new_category
                           })

    assert ('context' not in response) or ('form' not in response.context), "Still on form: {}".format(
        response.context['form'].errors)

    assert response.status_code == 302
    assert reverse('manager:surface-detail', kwargs=dict(pk=surface.id)) == response.url

    surface = Surface.objects.get(pk=surface.id)

    assert new_name == surface.name
    assert new_description == surface.description
    assert new_category == surface.category


@pytest.mark.django_db
def test_delete_surface(client, handle_usage_statistics):
    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    client.force_login(user)

    assert Surface.objects.all().count() == 1

    response = client.get(reverse('manager:surface-delete', kwargs=dict(pk=surface.id)))

    assert response.status_code == 200

    # user should be asked if he/she is sure
    assert b'Are you sure' in response.content

    response = client.post(reverse('manager:surface-delete', kwargs=dict(pk=surface.id)))

    assert ('context' not in response) or ('form' not in response.context), "Still on form: {}".format(
        response.context['form'].errors)

    assert response.status_code == 302
    assert reverse('manager:select') == response.url

    assert Surface.objects.all().count() == 0


@pytest.mark.django_db
def test_usage_of_cached_container_on_download_of_published_surface(client, example_pub, mocker,
                                                                    handle_usage_statistics):
    user = UserFactory()
    client.force_login(user)

    assert not example_pub.container.name

    surface = example_pub.surface

    # we don't need the correct container here, so we just return some fake data
    import topobank.manager.containers
    write_container_mock = mocker.patch('topobank.manager.views.write_surface_container', autospec=True)
    write_container_mock.return_value = BytesIO(b'Hello Test')

    def download_published():
        """Download published surface, returns HTTPResponse"""
        return client.get(reverse('manager:surface-download', kwargs=dict(surface_id=surface.id)), follow=True)

    #
    # first download
    #
    response = download_published()
    assert response.status_code == 200

    # now container has been set because write_container was called
    assert write_container_mock.called
    assert write_container_mock.call_count == 1
    assert example_pub.container is not None

    #
    # second download
    #
    response = download_published()
    assert response.status_code == 200

    # no extra call of write_container because it is a published surface
    assert write_container_mock.call_count == 1


@pytest.mark.django_db
def test_download_of_unpublished_surface(client, handle_usage_statistics):
    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    topo1 = Topography1DFactory(surface=surface)
    topo2 = Topography2DFactory(surface=surface)

    client.force_login(user)

    response = client.get(reverse('manager:surface-download', kwargs=dict(surface_id=surface.id)),
                          follow=True)
    assert response.status_code == 200
    assert response['Content-Disposition'] == f'attachment; filename="{slugify(surface.name) + ".zip"}"'
