from rest_framework.permissions import BasePermission

from domains.platform.users.models import User


class IsStaffOfOrganization(BasePermission):
    """
    Базовое право: пользователь аутентифицирован и привязан к организации.
    Все доменные эндпоинты используют это по умолчанию.
    Новый эндпоинт без явных прав — закрыт.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "organization_id", None)
        )


class IsOwner(IsStaffOfOrganization):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == User.Role.OWNER


class IsOwnerOrManager(IsStaffOfOrganization):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role in (
            User.Role.OWNER,
            User.Role.MANAGER,
        )


class IsOwnerOrManagerOrAdmin(IsStaffOfOrganization):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role in (
            User.Role.OWNER,
            User.Role.MANAGER,
            User.Role.ADMIN,
        )


class IsNotTeacher(IsStaffOfOrganization):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role != User.Role.TEACHER


class IsNotAccountant(IsStaffOfOrganization):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role != User.Role.ACCOUNTANT


class BranchScopedPermission(IsStaffOfOrganization):
    def has_object_permission(self, request, view, obj):
        if request.user.role == User.Role.OWNER:
            return True
        if request.user.role == User.Role.MANAGER:
            branch = getattr(obj, "branch", obj if hasattr(obj, "staff") else None)
            if branch is None:
                return True
            return request.user.branches.filter(pk=branch.pk).exists()
        return True
