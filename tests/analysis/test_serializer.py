import pytest

from topobank.analysis.serializers import AnalysisResultSerializer
from topobank.manager.models import Tag
from topobank.testing.factories import AnalysisFactory


@pytest.mark.django_db
def test_serializer_subject_topography(api_rf, one_line_scan, test_analysis_function):
    topo = one_line_scan
    request = api_rf.get("/")
    analysis = AnalysisFactory(
        subject_topography=topo, user=topo.creator, function=test_analysis_function
    )
    data = AnalysisResultSerializer(analysis, context={"request": request}).data
    assert data == {
        "id": analysis.id,
        "url": f"http://testserver/analysis/api/result/{analysis.id}/",
        "function": f"http://testserver/analysis/api/function/{test_analysis_function.id}/",
        "subject": {
            "id": analysis.subject_dispatch.id,
            "tag": None,
            "topography": f"http://testserver/manager/api/topography/{topo.id}/",
            "surface": None,
        },
        "kwargs": {"a": 1, "b": "foo"},
        "task_progress": 1.0,
        "task_state": "su",
        "task_memory": None,
        "creation_time": analysis.creation_time.astimezone().isoformat(),
        "start_time": analysis.start_time.astimezone().isoformat(),
        "end_time": analysis.end_time.astimezone().isoformat(),
        "dois": [],
        "configuration": None,
        "duration": analysis.duration,
        "error": None,
        "folder": f"http://testserver/files/folder/{analysis.folder.id}/",
    }


@pytest.mark.django_db
def test_serializer_subject_tag(api_rf, one_line_scan, test_analysis_function):
    topo = one_line_scan
    topo.tags = ["my-tag"]
    topo.save()
    assert Tag.objects.count() == 1
    tag = Tag.objects.all().first()
    tag.authorize_user(topo.creator)
    request = api_rf.get("/")
    analysis = AnalysisFactory(
        subject_tag=tag, user=topo.creator, function=test_analysis_function
    )
    data = AnalysisResultSerializer(analysis, context={"request": request}).data
    assert data == {
        "id": analysis.id,
        "url": f"http://testserver/analysis/api/result/{analysis.id}/",
        "function": f"http://testserver/analysis/api/function/{test_analysis_function.id}/",
        "subject": {
            "id": analysis.subject_dispatch.id,
            "tag": f"http://testserver/manager/api/tag/{tag.name}/",
            "topography": None,
            "surface": None,
        },
        "kwargs": {"a": 1, "b": "foo"},
        "task_progress": 1.0,
        "task_state": "su",
        "task_memory": None,
        "creation_time": analysis.creation_time.astimezone().isoformat(),
        "start_time": analysis.start_time.astimezone().isoformat(),
        "end_time": analysis.end_time.astimezone().isoformat(),
        "dois": [],
        "configuration": None,
        "duration": analysis.duration,
        "error": None,
        "folder": f"http://testserver/files/folder/{analysis.folder.id}/",
    }