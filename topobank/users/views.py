from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import DetailView, ListView, RedirectView, UpdateView
from django.core.exceptions import PermissionDenied

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from .models import User
from .serializers import UserSerializer
from .utils import are_collaborating


class UserViewSet(mixins.RetrieveModelMixin,
                  mixins.ListModelMixin,
                  viewsets.GenericViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        name = self.request.query_params.get('name')
        max_results = int(self.request.query_params.get('max', 5))
        if name is None:
            return User.objects.none()
        else:
            return User.objects.filter(name__icontains=name)[0:max_results]


class UserDetailView(LoginRequiredMixin, DetailView):
    model = User
    # These next two lines tell the view to index lookups by username
    slug_field = "username"
    slug_url_kwarg = "username"

    def dispatch(self, request, *args, **kwargs):
        user_to_view = User.objects.get(username=kwargs['username'])

        if not are_collaborating(user_to_view, request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['extra_tabs'] = [
            {
                'title': f"User profile",
                'icon': "user",
                'href': self.request.path,
                'active': True,
                'login_required': False,
            }
        ]
        return context


class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self):
        return reverse("users:detail", kwargs={"username": self.request.user.username})


class UserUpdateView(LoginRequiredMixin, UpdateView):
    fields = ["name"]

    # we already imported User in the view code above, remember?
    model = User

    # send the user back to their own page after a successful update

    def get_success_url(self):
        return reverse("users:detail", kwargs={"username": self.request.user.username})

    def get_object(self, queryset=None):
        # Only get the User record for the user making the request
        return User.objects.get(username=self.request.user.username)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['extra_tabs'] = [
            {
                'title': f"User Profile",
                'icon': "user",
                'href': reverse('users:detail', kwargs=dict(username=self.request.user.username)),
                'active': False,
            },
            {
                'title': f"Update user",
                'icon': "edit",
                'href': self.request.path,
                'active': True,
            }
        ]
        return context


class UserListView(LoginRequiredMixin, ListView):
    model = User
    # These next two lines tell the view to index lookups by username
    slug_field = "username"
    slug_url_kwarg = "username"
