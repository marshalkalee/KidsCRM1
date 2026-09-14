from rest_framework.permissions import BasePermission


class IsStaffOfOrganization(BasePermission):
    """
    Базовое право для доменных API: пользователь аутентифицирован и
    привязан к организации. Гранулярные роли (Owner/Manager/Admin/...) —
    отдельная задача (RBAC), здесь только факт принадлежности к тенанту.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "organization_id", None)
        )
