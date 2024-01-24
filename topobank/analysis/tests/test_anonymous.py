import pytest
from django.shortcuts import reverse

from ...manager.tests.utils import SurfaceFactory, Topography1DFactory, UserFactory
from .utils import TopographyAnalysisFactory

#
# The code in these tests rely on a middleware which replaces
# Django's AnonymousUser by the one of django guardian
#

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
