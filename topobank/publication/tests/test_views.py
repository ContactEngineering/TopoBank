"""Tests related to views."""
import pytest
from django.shortcuts import reverse
import zipfile
from io import BytesIO
import yaml

from .utils import example_pub
from topobank.manager.tests.utils import UserFactory
from topobank.utils import assert_in_content


@pytest.mark.django_db
def test_go_link(client, example_pub):
    user = UserFactory()
    client.force_login(user)
    response = client.get(reverse('publication:go', kwargs=dict(short_url=example_pub.short_url)), follow=True)
    assert response.status_code == 200
    assert_in_content(response, example_pub.surface.name)


@pytest.mark.django_db
def test_go_download_link(client, example_pub):
    user = UserFactory()
    client.force_login(user)
    response = client.get(reverse('publication:go-download', kwargs=dict(short_url=example_pub.short_url)), follow=True)
    assert response.status_code == 200

    surface = example_pub.surface

    # open zip file and look into meta file, there should be two surfaces and three topographies
    with zipfile.ZipFile(BytesIO(response.content)) as zf:
        meta_file = zf.open('meta.yml')
        meta = yaml.load(meta_file)
        assert len(meta['surfaces']) == 1
        assert len(meta['surfaces'][0]['topographies']) == surface.num_topographies()
        assert meta['surfaces'][0]['name'] == surface.name

    assert_in_content(response, example_pub.surface.name)
