"""
Test of downloads module.
"""

from django.shortcuts import reverse

from topobank.analysis.downloads import download_plot_analyses_to_txt
from topobank.analysis.tests.utils import TopographyAnalysisFactory, AnalysisFunction
from topobank.analysis.functions import VIZ_SERIES
from topobank.utils import assert_in_content

import pytest


@pytest.mark.django_db
def test_download_plot_analyses_to_txt(rf):
    func = AnalysisFunction.objects.get(name="test")
    analysis = TopographyAnalysisFactory(function=func)
    request = rf.get(reverse('analysis:download',
                             kwargs=dict(ids=str(analysis.id),
                                         art=VIZ_SERIES,
                                         file_format='txt')))

    response = download_plot_analyses_to_txt(request, [analysis])

    assert_in_content(response, 'Fibonacci')
    assert_in_content(response, '1.000000000000000000e+00 0.000000000000000000e+00 0.000000000000000000e+00')
    assert_in_content(response, '8.000000000000000000e+00 1.300000000000000000e+01 0.000000000000000000e+00')


@pytest.mark.parametrize("user_has_plugin", [False, True])
@pytest.mark.django_db
def test_download_view_permission_for_function_from_plugin(mocker,client, user_has_plugin, handle_usage_statistics):
    """Simple test, whether analyses which should not be visible lead to an error during download.
    """
    func = AnalysisFunction.objects.get(name="test")

    analysis = TopographyAnalysisFactory(function=func)

    m = mocker.patch('topobank.analysis.models.Analysis.is_visible_for_user')
    m.return_value = user_has_plugin

    response = client.get(reverse('analysis:download',
                          kwargs=dict(ids=str(analysis.id),
                                      art=VIZ_SERIES,
                                      file_format='txt')))
    if user_has_plugin:
        assert response.status_code == 200
    else:
        assert response.status_code == 403


