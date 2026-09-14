from django.test import RequestFactory, TestCase
from rest_framework_simplejwt.tokens import RefreshToken

from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User

def get_response(request):
    return None


class TenantMiddlewareTest(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = TenantMiddleware(get_response)

        self.org_a = Organization.objects.create(name="Балет Астана", slug="ballet-astana")
        self.org_b = Organization.objects.create(name="Школа танцев", slug="shkola-tantsev")

        self.user = User.objects.create_user(
            phone="77001234567",
            password="testpass",
            full_name="Тест Пользователь",
            organization=self.org_a,
        )

    def _get_token_for_user(self, user):
        refresh = RefreshToken.for_user(user)
        refresh["organization_id"] = str(user.organization_id)
        return str(refresh.access_token)

    def test_request_without_token_has_no_organization(self):
        request = self.factory.get("/api/v1/")
        self.middleware(request)
        self.assertIsNone(request.organization)

    def test_request_with_token_sets_organization(self):
        token = self._get_token_for_user(self.user)
        request = self.factory.get("/api/v1/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.middleware(request)
        self.assertEqual(request.organization, self.org_a)

    def test_cross_tenant_access_impossible(self):
        Branch.objects.create(name="Филиал А", organization=self.org_a)
        Branch.objects.create(name="Филиал Б", organization=self.org_b)

        result = Branch.objects.for_tenant(self.org_a)
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first().name, "Филиал А")

    def test_cross_tenant_write_protection(self):
        Branch.objects.create(name="Филиал Б", organization=self.org_b)

        result = Branch.objects.for_tenant(self.org_a)
        self.assertEqual(result.count(), 0)