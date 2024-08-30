import datetime
from pathlib import Path

import pytest
from django.shortcuts import reverse
from notifications.models import Notification

from topobank.manager.models import Topography
from topobank.testing.factories import (
    FIXTURE_DATA_DIR,
    SurfaceFactory,
    Topography1DFactory,
    Topography2DFactory,
    UserFactory,
)
from topobank.testing.utils import upload_topography_file


def test_individual_read_access_permissions(
    api_client, django_user_model, handle_usage_statistics
):
    #
    # create database objects
    #
    username_1 = "A"
    username_2 = "B"
    password = "secret"

    user_1 = django_user_model.objects.create_user(
        username=username_1, password=password
    )
    user_2 = django_user_model.objects.create_user(
        username=username_2, password=password
    )

    surface = SurfaceFactory(creator=user_1)

    surface_detail_url = reverse(
        "manager:surface-api-detail", kwargs=dict(pk=surface.pk)
    )

    #
    # now user 1 has access to surface detail page
    #
    assert api_client.login(username=username_1, password=password)
    response = api_client.get(surface_detail_url)

    assert response.status_code == 200

    api_client.logout()

    #
    # User 2 has no access
    #
    assert api_client.login(username=username_2, password=password)
    response = api_client.get(surface_detail_url)

    assert response.status_code == 404  # forbidden

    api_client.logout()

    #
    # Now grant access and user 2 should be able to access
    #

    surface.grant_permission(user_2, "view")

    assert api_client.login(username=username_2, password=password)
    response = api_client.get(surface_detail_url)

    assert response.status_code == 200  # now it's okay

    #
    # Write access is still not possible
    #
    response = api_client.patch(surface_detail_url)

    assert response.status_code == 403  # forbidden

    api_client.logout()


@pytest.mark.django_db
def test_list_surface_permissions(api_client, handle_usage_statistics):
    #
    # create database objects
    #
    password = "secret"

    user1 = UserFactory(password=password)
    user2 = UserFactory(name="Bob Marley")
    user3 = UserFactory(name="Alice Cooper")

    surface = SurfaceFactory(creator=user1)
    surface.share(user2)
    surface.grant_permission(user3, "edit")

    surface_detail_url = reverse(
        "manager:surface-api-detail", kwargs=dict(pk=surface.pk)
    )

    #
    # now user 1 has access to surface detail page
    #
    assert api_client.login(username=user1.username, password=password)
    response = api_client.get(f"{surface_detail_url}?permissions=yes")

    # related to user 1
    assert response.data["permissions"]["current_user"]["user"]["id"] == user1.id
    assert response.data["permissions"]["current_user"]["permission"] == "full"

    other_permissions = response.data["permissions"]["other_users"]
    assert len(other_permissions) == 2
    for permissions in other_permissions:
        if permissions["user"]["id"] == user2.id:
            # related to user 2
            assert permissions["permission"] == "view"
        elif permissions["user"]["id"] == user3.id:
            # related to user 3
            assert permissions["permission"] == "edit"
        else:
            assert False, "Unknown user"


@pytest.mark.django_db(transaction=True)
def test_notification_when_deleting_shared_stuff(api_client):
    user1 = UserFactory()
    user2 = UserFactory()
    surface = SurfaceFactory(creator=user1)
    topography = Topography1DFactory(surface=surface)

    surface.grant_permission(user2, "full")

    #
    # First: user2 deletes the topography, user1 should be notified
    #
    api_client.force_login(user2)

    response = api_client.delete(
        reverse("manager:topography-api-detail", kwargs=dict(pk=topography.pk))
    )
    assert response.status_code == 204  # redirect

    assert (
        Notification.objects.filter(
            recipient=user1, verb="delete", description__contains=topography.name
        ).count()
        == 1
    )
    api_client.logout()

    #
    # Second: user1 deletes the surface, user2 should be notified
    #
    api_client.force_login(user1)

    response = api_client.delete(
        reverse("manager:surface-api-detail", kwargs=dict(pk=surface.pk))
    )
    assert response.status_code == 204  # redirect

    assert (
        Notification.objects.filter(
            recipient=user2, verb="delete", description__contains=surface.name
        ).count()
        == 1
    )
    api_client.logout()


@pytest.mark.django_db
def test_notification_when_editing_shared_stuff(api_client, handle_usage_statistics):
    user1 = UserFactory()
    user2 = UserFactory()
    surface = SurfaceFactory(creator=user1)
    topography = Topography2DFactory(surface=surface, size_y=512)

    surface.grant_permission(user2, "edit")

    #
    # First: user2 edits the topography, user1 should be notified
    #
    api_client.force_login(user2)

    response = api_client.patch(
        reverse("manager:topography-api-detail", kwargs=dict(pk=topography.pk)),
        {
            "data_source": 0,
            "name": topography.name,
            "measurement_date": topography.measurement_date,
            "description": topography.description,
            "height_scale": 0.1,  # we also change a significant value here -> recalculate
            "detrend_mode": "height",
            "instrument_type": Topography.INSTRUMENT_TYPE_UNDEFINED,
            "has_undefined_data": False,
            "fill_undefined_data_mode": Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
        },
    )
    assert response.status_code == 200, response.content

    note = Notification.objects.get(
        recipient=user1, verb="change", description__contains=topography.name
    )
    assert "changed digital surface twin" in note.description
    api_client.logout()

    #
    # Second: user1 edits the surface, user2 should be notified
    #
    api_client.force_login(user1)

    new_name = "This is a better surface name"
    new_description = "This is new description"
    new_category = "dum"

    response = api_client.patch(
        reverse("manager:surface-api-detail", kwargs=dict(pk=surface.pk)),
        {"name": new_name, "description": new_description, "category": new_category},
    )

    assert response.status_code == 200, response.content

    assert (
        Notification.objects.filter(
            recipient=user2, verb="change", description__contains=new_name
        ).count()
        == 1
    )
    api_client.logout()


@pytest.mark.django_db
def test_upload_topography_for_shared_surface(
    api_client, settings, handle_usage_statistics, django_capture_on_commit_callbacks
):
    input_file_path = Path(FIXTURE_DATA_DIR + "/example3.di")
    description = "test description"

    password = "abcd$1234"

    user1 = UserFactory(password=password)
    user2 = UserFactory(password=password)

    surface = SurfaceFactory(creator=user1)
    surface.share(user2)  # first without allowing change

    assert api_client.login(username=user2.username, password=password)

    #
    # open first step of wizard: file upload
    #
    response = api_client.post(
        reverse("manager:topography-api-list"),
        {
            "surface": reverse(
                "manager:surface-api-detail", kwargs=dict(pk=surface.id)
            ),
            "name": "example3.di",
        },
    )
    assert response.status_code == 403  # user2 is not allowed to change

    #
    # Now allow to change and get response again
    #
    surface.grant_permission(user2, "edit")
    response = upload_topography_file(
        str(input_file_path),
        surface.id,
        api_client,
        django_capture_on_commit_callbacks,
        **{
            "measurement_date": "2018-06-21",
            "data_source": 0,
            "description": description,
            "size_x": "9000",
            "size_y": "9000",
            "unit": "nm",
            "height_scale": 0.3,
            "detrend_mode": "height",
            "instrument_type": Topography.INSTRUMENT_TYPE_UNDEFINED,
            "fill_undefined_data_mode": Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING,
        },
    )
    assert response.data["name"] == "example3.di"
    assert response.data["channel_names"] == [
        ["ZSensor", "nm"],
        ["AmplitudeError", None],
        ["Phase", None],
        ["Height", "nm"],
    ]

    topos = surface.topography_set.all()

    assert len(topos) == 1

    t = topos[0]

    assert t.measurement_date == datetime.date(2018, 6, 21)
    assert t.description == description
    assert "example3" in t.datafile.filename
    assert 256 == t.resolution_x
    assert 256 == t.resolution_y
    assert t.creator == user2

    #
    # Test little badge which shows who uploaded data
    #
    response = api_client.get(
        reverse("manager:topography-api-detail", kwargs=dict(pk=t.pk))
    )
    assert response.status_code == 200
    api_client.logout()

    assert api_client.login(username=user1.username, password=password)
    response = api_client.get(
        reverse("manager:topography-api-detail", kwargs=dict(pk=t.pk))
    )
    assert response.status_code == 200
    api_client.logout()

    #
    # There should be a notification of the user
    #
    exp_mesg = f"User '{user2}' added the measurement '{t.name}' to digital surface twin '{t.surface.name}'."
    assert (
        Notification.objects.filter(
            unread=True, recipient=user1, verb="create", description__contains=exp_mesg
        ).count()
        == 1
    )
