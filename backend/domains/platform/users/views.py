from rest_framework import viewsets

from domains.platform.core.permissions import IsStaffOfOrganization

from .models import User
from .serializers import UserSerializer


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_queryset(self):
        return User.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)
