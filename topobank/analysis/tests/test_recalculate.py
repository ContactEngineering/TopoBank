import pytest
from django.shortcuts import reverse
from django.db import transaction

from ...analysis.models import Analysis
from ...analysis.tests.utils import TopographyAnalysisFactory
from ...manager.tests.utils import SurfaceFactory, Topography1DFactory, UserFactory
from ...manager.utils import subjects_to_dict


@pytest.mark.django_db
def test_submit_analyses_api(api_client, test_analysis_function, handle_usage_statistics):
    """Test API to submit new analyses."""

    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    topo1 = Topography1DFactory(surface=surface)
    topo2 = Topography1DFactory(surface=surface)

    func = test_analysis_function

    api_client.force_login(user)

    with transaction.atomic():
        # trigger "recalculate" for two topographies
        response = api_client.post(reverse('analysis:card-submit'), {
            'function_id': func.id,
            'subjects': subjects_to_dict([topo1, topo2]),
            'function_kwargs': {}
        })  # we need an AJAX request
        assert response.status_code == 200

    #
    # Analysis objects should be there and marked for the user
    #
    analysis1 = Analysis.objects.get(function=func, topography=topo1)
    analysis2 = Analysis.objects.get(function=func, topography=topo2)

    assert user in analysis1.users.all()
    assert user in analysis2.users.all()

    #
    # Don't know yet how execute tasks locally without task queue
    # Celery's "task_always_eager" is not suitable for unit testing.
    #
    #
    # assert analysis1.task_state == 'su'
    # assert analysis2.task_state == 'su'
    #
    # #
    # # Collection object should be there and contain those analyses
    # #
    # collection = AnalysisCollection.objects.get(owner=user)
    #
    # assert collection.analyses.count() == 2
    # assert analysis1 in collection.analyses.all()
    # assert analysis2 in collection.analyses.all()
    #
    # #
    # # Notification should be there, since the task has already performed
    # #
    # note = Notification.objects.get(recipient=user, description__contains="Tasks finished")
    # assert note.href == reverse('analysis:collection', kwargs=dict(collection_id=collection.id))


@pytest.mark.django_db
def test_renew_analyses_api(client, test_analysis_function):
    """Test whether existing analyses can be renewed by API call."""

    user = UserFactory()
    surface = SurfaceFactory(creator=user)
    topo1 = Topography1DFactory(surface=surface)
    topo2 = Topography1DFactory(surface=surface)

    func = test_analysis_function

    analysis1a = TopographyAnalysisFactory(subject=topo1, function=func)
    analysis2a = TopographyAnalysisFactory(subject=topo2, function=func)

    client.force_login(user)

    with transaction.atomic():
        # trigger "renew" for two specific analyses
        response = client.post(reverse('analysis:renew'), {
            'analyses_ids[]': [analysis1a.id, analysis2a.id],
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')  # we need an AJAX request
        assert response.status_code == 200

    #
    # Old analyses should be deleted
    #
    with pytest.raises(Analysis.DoesNotExist):
        Analysis.objects.get(id=analysis1a.id)
    with pytest.raises(Analysis.DoesNotExist):
        Analysis.objects.get(id=analysis2a.id)

    #
    # New Analysis objects should be there and marked for the user
    #
    analysis1b = Analysis.objects.get(function=func, topography=topo1)
    analysis2b = Analysis.objects.get(function=func, topography=topo2)

    assert user in analysis1b.users.all()
    assert user in analysis2b.users.all()



