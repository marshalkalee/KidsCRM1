from rest_framework.permissions import SAFE_METHODS, BasePermission

from domains.platform.core.active_branch import allowed_branch_ids
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


class CanViewClientMoney(IsStaffOfOrganization):
    """Деньги по детям и родителям — абонементы, оплаты, долги, продления.
    Чтение — can_view_client_money (преподавателю, если центр открыл ему
    финансы, TRU-153); запись — как раньше, все, кроме преподавателя."""

    def has_permission(self, request, view):
        from domains.platform.core.role_permissions import (
            can_change_client_money,
            can_view_client_money,
        )

        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return can_view_client_money(request.user)
        return can_change_client_money(request.user)


class CanAcceptPayments(IsStaffOfOrganization):
    """Принять и отменить оплату — по роли или особому праву сотрудника."""

    def has_permission(self, request, view):
        from domains.platform.core.role_permissions import can_accept_payments

        return super().has_permission(request, view) and can_accept_payments(request.user)


class CanViewAIDigest(IsStaffOfOrganization):
    """Дайджест недели — по роли или особому праву сотрудника."""

    def has_permission(self, request, view):
        from domains.platform.core.role_permissions import can_view_ai_digest

        return super().has_permission(request, view) and can_view_ai_digest(request.user)


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
            # Филиалы не выбраны — сотруднику доступны все (как в списках).
            allowed = allowed_branch_ids(request.user)
            return allowed is None or branch.pk in allowed
        return True
