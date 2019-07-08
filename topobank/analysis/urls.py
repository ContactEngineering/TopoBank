from django.conf.urls import url
from django.contrib.auth.decorators import login_required

from . import views

app_name = "analysis"
urlpatterns = [
    url(
        regex=r'list/$',
        view=login_required(views.AnalysesListView.as_view()),
        name='list'
    ),
    url(
        regex=r'download/(?P<ids>[\d,]+)/(?P<card_view_flavor>[\w\s]+)/(?P<file_format>\w+)$',
        view=login_required(views.download_analyses),
        name='download'
    ),
    url(
        regex=r'function/(?P<pk>[\d,]+)/$',
        view=login_required(views.AnalysisFunctionDetailView.as_view()),
        name='function-detail'
    ),
    url(
        regex=r'card/submit$',
        view=login_required(views.submit_analyses_view),
        name='card-submit'
    ),
    url(
        regex=r'card/contact-mechanics-data$',
        view=login_required(views.contact_mechanics_data),
        name='contact-mechanics-data'
    ),
    url(
        regex=r'card/$',
        view=login_required(views.switch_card_view),
        name='card'
    ),
]
