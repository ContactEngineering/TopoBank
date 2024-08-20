from ..users.models import User
from .models import ViewEditFull, ViewEditFullNone


class PermissionMixin:
    def get_permission_for_user(self, user: User) -> ViewEditFullNone:
        perm = self.permissions.get_for_user(user)
        if perm is None:
            return None
        else:
            return perm.allow

    def grant_permission_for_user(self, user: User, allow: ViewEditFull):
        self.permissions.grant_for_user(user, allow)

    def revoke_from_user(self, user: User):
        self.permissions.revoke_from_user(user)

    def has_permission(self, user: User, access_level: ViewEditFullNone) -> bool:
        return self.permissions.has_permission(user, access_level)

    def authorize_user(self, user: User, access_level: ViewEditFullNone):
        self.permissions.authorize_user(user, access_level)
