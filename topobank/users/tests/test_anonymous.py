import pytest
from django.shortcuts import reverse
from django.utils import timezone
from django.contrib import auth
from django.utils.http import urlencode

from topobank.utils import assert_in_content, assert_not_in_content
from topobank.manager.tests.utils import UserFactory
from termsandconditions.models import TermsAndConditions


@pytest.mark.django_db
def test_terms_conditions_as_anonymous(client):

    # Install terms and conditions for test
    TermsAndConditions.objects.create(slug='test-terms', name="Test of T&amp;C",
                                      text="some text", date_active=timezone.now())

    response = client.get(reverse('terms'))
    assert_in_content(response, "Test of T&amp;C")

    response = client.get(reverse('tc_accept_specific_page', kwargs=dict(slug='test-terms')))
    assert_in_content(response, "some text")




