class TenantCreateMixin:
    def perform_create(self, serializer):
        if self.request.organization is None:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Организация не определена.")
        serializer.save(organization=self.request.organization)