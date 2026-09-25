from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, tag

from domains.platform.core.active_branch import get_active_branch
from domains.platform.tenants.models import Branch, Organization

User = get_user_model()


@tag("tenant_isolation")
class ActiveBranchHeaderTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.other = Organization.objects.create(name="Other", slug="other")
        self.branch = Branch.objects.create(organization=self.org, name="Центральный")
        self.user = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )

    def _request(self, header=None):
        extra = {"HTTP_X_BRANCH_ID": header} if header is not None else {}
        request = RequestFactory().get("/api/v1/", **extra)
        request.user = self.user
        return request

    def test_no_header_means_all_branches(self):
        self.assertIsNone(get_active_branch(self._request()))

    def test_own_active_branch(self):
        self.assertEqual(get_active_branch(self._request(str(self.branch.id))), self.branch)

    def test_other_organizations_branch_is_ignored(self):
        foreign = Branch.objects.create(organization=self.other, name="Чужой")

        self.assertIsNone(get_active_branch(self._request(str(foreign.id))))

    def test_archived_branch_is_ignored(self):
        self.branch.is_active = False
        self.branch.save()

        self.assertIsNone(get_active_branch(self._request(str(self.branch.id))))

    def test_garbage_header_is_ignored(self):
        self.assertIsNone(get_active_branch(self._request("not-a-uuid")))
