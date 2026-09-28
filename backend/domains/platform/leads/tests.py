from datetime import timedelta

from django.test import TestCase, tag
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .models import Lead, LeadRejectionReason, LeadSource, LeadStatusChange
from .services import LeadTransitionError, change_status, create_lead

URL = "/api/v1/leads/"


def make_client(user):
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class LeadFixtures(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Балет", slug="ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Центр")
        self.other_branch = Branch.objects.create(organization=self.org, name="Орбита")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.instagram = LeadSource.objects.create(organization=self.org, name="Instagram")
        self.expensive = LeadRejectionReason.objects.create(organization=self.org, name="Дорого")
        self.owner = self.make_user("77010000001", User.Role.OWNER)
        self.admin = self.make_user("77010000002", User.Role.ADMIN)
        self.client_owner = make_client(self.owner)

    def make_user(self, phone, role, organization=None, branches=()):
        user = User.objects.create_user(
            phone=phone,
            password="pass",
            full_name=f"{role} {phone[-2:]}",
            organization=organization or self.org,
            role=role,
        )
        user.branches.set(branches)
        return user

    def make_lead(self, **fields):
        fields.setdefault("parent_name", "Айгерим")
        fields.setdefault("phone", "+77071112233")
        return create_lead(organization=self.org, actor=self.owner, **fields)

    def move(self, lead, to_status, client=None, **extra):
        return (client or self.client_owner).post(
            f"{URL}{lead.id}/status/", {"status": to_status, **extra}, format="json"
        )


class LeadCreateTests(LeadFixtures):
    def test_create_with_phone_and_name_only(self):
        response = self.client_owner.post(
            URL, {"parent_name": "Айгерим", "phone": "8 (707) 111-22-33"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        lead = Lead.objects.get(pk=response.data["id"])
        self.assertEqual(lead.phone, "+77071112233")
        self.assertEqual(lead.status, Lead.Status.NEW)
        # Ответственный по умолчанию — кто завёл.
        self.assertEqual(lead.assigned_to, self.owner)
        change = lead.status_changes.get()
        self.assertEqual(
            (change.from_status, change.to_status, change.changed_by), ("", "new", self.owner)
        )

    def test_phone_and_name_required(self):
        response = self.client_owner.post(URL, {"child_name": "Алия"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.data)
        self.assertIn("parent_name", response.data)

    def test_bad_phone_rejected(self):
        response = self.client_owner.post(URL, {"parent_name": "А", "phone": "123"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.data)

    def test_all_fields(self):
        response = self.client_owner.post(
            URL,
            {
                "parent_name": "Айгерим",
                "phone": "+77071112233",
                "child_name": "Алия",
                "child_age": 6,
                "branch": str(self.branch.id),
                "direction": str(self.direction.id),
                "source": str(self.instagram.id),
                "assigned_to": str(self.admin.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["source_name"], "Instagram")
        self.assertEqual(response.data["assigned_to_name"], self.admin.full_name)
        self.assertEqual(response.data["status_label"], "Новая")
        self.assertEqual(response.data["days_in_status"], 0)

    def test_archived_source_not_accepted_for_new_lead(self):
        self.instagram.is_active = False
        self.instagram.save()
        response = self.client_owner.post(
            URL,
            {"parent_name": "А", "phone": "+77071112233", "source": str(self.instagram.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("source", response.data)

    def test_archived_source_kept_when_editing_other_fields(self):
        lead = self.make_lead(source=self.instagram)
        self.instagram.is_active = False
        self.instagram.save()
        response = self.client_owner.patch(
            f"{URL}{lead.id}/",
            {"child_name": "Алия", "source": str(self.instagram.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["source_name"], "Instagram")


class LeadStatusTests(LeadFixtures):
    def test_valid_transition_writes_history(self):
        lead = self.make_lead()
        response = self.move(lead, "contacted")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "contacted")
        history = self.client_owner.get(f"{URL}{lead.id}/history/").data
        self.assertEqual(
            [(h["from_status"], h["to_status"]) for h in history],
            [("", "new"), ("new", "contacted")],
        )
        self.assertEqual(history[1]["changed_by_name"], self.owner.full_name)
        self.assertEqual(history[1]["from_status_label"], "Новая")
        self.assertTrue(history[1]["changed_at"])

    def test_full_funnel(self):
        lead = self.make_lead()
        for step in ("contacted", "trial_scheduled", "trial_attended", "purchased"):
            self.assertEqual(self.move(lead, step).status_code, 200, step)
        self.assertEqual(lead.status_changes.count(), 5)

    def test_invalid_transition_rejected(self):
        lead = self.make_lead()
        response = self.move(lead, "purchased")
        self.assertEqual(response.status_code, 400)
        self.assertIn("нельзя перейти", response.data["detail"])
        lead.refresh_from_db()
        self.assertEqual(lead.status, "new")
        self.assertEqual(lead.status_changes.count(), 1)

    def test_purchased_is_final(self):
        lead = self.make_lead()
        for step in ("contacted", "purchased"):
            self.move(lead, step)
        self.assertEqual(
            self.move(lead, "rejected", rejection_reason=str(self.expensive.id)).status_code, 400
        )

    def test_same_status_rejected(self):
        lead = self.make_lead()
        self.assertEqual(self.move(lead, "new").status_code, 400)

    def test_reject_without_reason_fails_at_api(self):
        lead = self.make_lead()
        response = self.move(lead, "rejected")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Укажите причину отказа.")
        lead.refresh_from_db()
        self.assertEqual(lead.status, "new")

    def test_reject_with_reason(self):
        lead = self.make_lead()
        response = self.move(
            lead, "rejected", rejection_reason=str(self.expensive.id), comment="Посмотрят зимой"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["rejection_reason_name"], "Дорого")
        self.assertEqual(response.data["rejection_comment"], "Посмотрят зимой")
        change = lead.status_changes.last()
        self.assertEqual(
            (change.to_status, change.rejection_reason, change.comment),
            ("rejected", self.expensive, "Посмотрят зимой"),
        )

    def test_reopen_after_reject_clears_reason_but_keeps_history(self):
        lead = self.make_lead()
        self.move(lead, "rejected", rejection_reason=str(self.expensive.id))
        response = self.move(lead, "contacted")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["rejection_reason"])
        self.assertTrue(lead.status_changes.filter(rejection_reason=self.expensive).exists())

    def test_archived_reason_rejected(self):
        self.expensive.is_active = False
        self.expensive.save()
        lead = self.make_lead()
        self.assertEqual(
            self.move(lead, "rejected", rejection_reason=str(self.expensive.id)).status_code, 400
        )

    def test_reason_only_for_rejection(self):
        lead = self.make_lead()
        self.assertEqual(
            self.move(lead, "contacted", rejection_reason=str(self.expensive.id)).status_code, 400
        )

    def test_status_not_writable_through_patch(self):
        lead = self.make_lead()
        response = self.client_owner.patch(
            f"{URL}{lead.id}/", {"status": "purchased"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.status, "new")

    def test_service_blocks_reject_without_reason(self):
        lead = self.make_lead()
        with self.assertRaises(LeadTransitionError):
            change_status(lead, to_status=Lead.Status.REJECTED, actor=self.owner)

    def test_history_is_append_only(self):
        change = self.make_lead().status_changes.get()
        with self.assertRaises(PermissionError):
            change.save()
        with self.assertRaises(PermissionError):
            change.delete()

    def test_days_in_status(self):
        lead = self.make_lead()
        Lead.objects.filter(pk=lead.pk).update(status_changed_at=timezone.now() - timedelta(days=4))
        self.assertEqual(self.client_owner.get(f"{URL}{lead.id}/").data["days_in_status"], 4)


class LeadPermissionTests(LeadFixtures):
    def test_roles(self):
        lead = self.make_lead()
        for index, (role, expected) in enumerate(
            [
                (User.Role.MANAGER, 200),
                (User.Role.ADMIN, 200),
                (User.Role.TEACHER, 403),
                (User.Role.ACCOUNTANT, 403),
            ]
        ):
            user = self.make_user(f"7702000000{index}", role)
            self.assertEqual(make_client(user).get(f"{URL}{lead.id}/").status_code, expected, role)

    def test_me_exposes_flag(self):
        teacher = self.make_user("77020000009", User.Role.TEACHER)
        self.assertTrue(
            self.client_owner.get("/api/v1/users/auth/me/").data["permissions"]["can_manage_leads"]
        )
        self.assertFalse(
            make_client(teacher)
            .get("/api/v1/users/auth/me/")
            .data["permissions"]["can_manage_leads"]
        )

    def test_branch_staff_sees_own_branch_unassigned_and_own_leads(self):
        manager = self.make_user("77020000011", User.Role.MANAGER, branches=[self.branch])
        own = self.make_lead(branch=self.branch)
        unassigned = self.make_lead()
        foreign = self.make_lead(branch=self.other_branch)
        mine_elsewhere = self.make_lead(branch=self.other_branch, assigned_to=manager)
        client = make_client(manager)
        ids = {row["id"] for row in client.get(URL).data["results"]}
        self.assertEqual(ids, {str(own.id), str(unassigned.id), str(mine_elsewhere.id)})
        self.assertEqual(client.get(f"{URL}{foreign.id}/").status_code, 404)
        self.assertEqual(self.move(foreign, "contacted", client=client).status_code, 404)

    def test_owner_sees_all_branches(self):
        self.make_lead(branch=self.other_branch)
        self.assertEqual(self.client_owner.get(URL).data["count"], 1)


class LeadListFilterTests(LeadFixtures):
    def setUp(self):
        super().setUp()
        self.a = self.make_lead(
            parent_name="Айгерим",
            phone="+77071112233",
            source=self.instagram,
            branch=self.branch,
            assigned_to=self.owner,
        )
        self.b = self.make_lead(
            parent_name="Дина", child_name="Алия", phone="+77019998877", assigned_to=self.admin
        )
        change_status(self.b, to_status=Lead.Status.CONTACTED, actor=self.owner)

    def ids(self, query=""):
        return {row["id"] for row in self.client_owner.get(f"{URL}?{query}").data["results"]}

    def test_filters(self):
        self.assertEqual(self.ids("status=contacted"), {str(self.b.id)})
        self.assertEqual(self.ids("status=new,contacted"), {str(self.a.id), str(self.b.id)})
        self.assertEqual(self.ids(f"source={self.instagram.id}"), {str(self.a.id)})
        self.assertEqual(self.ids(f"assigned_to={self.admin.id}"), {str(self.b.id)})
        self.assertEqual(self.ids("assigned_to=me"), {str(self.a.id)})
        self.assertEqual(self.ids(f"branch={self.branch.id}"), {str(self.a.id)})

    def test_search_by_names_and_phone(self):
        self.assertEqual(self.ids("q=алия"), {str(self.b.id)})
        self.assertEqual(self.ids("q=айгер"), {str(self.a.id)})
        self.assertEqual(self.ids("q=999 88"), {str(self.b.id)})

    def test_created_period(self):
        today = timezone.localdate().isoformat()
        self.assertEqual(len(self.ids(f"created_from={today}&created_to={today}")), 2)
        self.assertEqual(self.ids("created_to=2000-01-01"), set())

    def test_bad_uuid_gives_empty_list(self):
        response = self.client_owner.get(f"{URL}?source=not-a-uuid")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_active_branch_header(self):
        response = self.client_owner.get(URL, HTTP_X_BRANCH_ID=str(self.branch.id))
        self.assertEqual({row["id"] for row in response.data["results"]}, {str(self.a.id)})


class LeadCommentTests(LeadFixtures):
    def test_add_and_list_comments(self):
        lead = self.make_lead()
        response = self.client_owner.post(
            f"{URL}{lead.id}/comments/", {"text": "Перезвонить вечером"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["author_name"], self.owner.full_name)
        comments = self.client_owner.get(f"{URL}{lead.id}/comments/").data
        self.assertEqual([c["text"] for c in comments], ["Перезвонить вечером"])

    def test_empty_comment_rejected(self):
        lead = self.make_lead()
        self.assertEqual(
            self.client_owner.post(
                f"{URL}{lead.id}/comments/", {"text": ""}, format="json"
            ).status_code,
            400,
        )

    def test_delete_is_soft(self):
        lead = self.make_lead()
        self.assertEqual(self.client_owner.delete(f"{URL}{lead.id}/").status_code, 204)
        self.assertFalse(Lead.objects.filter(pk=lead.pk).exists())
        self.assertTrue(Lead.objects.all_with_deleted().filter(pk=lead.pk).exists())


@tag("tenant_isolation")
class LeadTenantIsolationTests(LeadFixtures):
    def setUp(self):
        super().setUp()
        self.org_b = Organization.objects.create(name="Чужой центр", slug="other")
        self.owner_b = self.make_user("77030000001", User.Role.OWNER, organization=self.org_b)
        self.client_b = make_client(self.owner_b)
        self.lead = self.make_lead()

    def test_foreign_org_cannot_list_or_read(self):
        self.assertEqual(self.client_b.get(URL).data["count"], 0)
        self.assertEqual(self.client_b.get(f"{URL}{self.lead.id}/").status_code, 404)
        self.assertEqual(self.client_b.get(f"{URL}{self.lead.id}/history/").status_code, 404)
        self.assertEqual(self.client_b.get(f"{URL}{self.lead.id}/comments/").status_code, 404)

    def test_foreign_org_cannot_change(self):
        self.assertEqual(
            self.client_b.patch(
                f"{URL}{self.lead.id}/", {"parent_name": "X"}, format="json"
            ).status_code,
            404,
        )
        self.assertEqual(self.move(self.lead, "contacted", client=self.client_b).status_code, 404)
        self.assertEqual(self.client_b.delete(f"{URL}{self.lead.id}/").status_code, 404)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.parent_name, self.lead.status), ("Айгерим", "new"))

    def test_foreign_dictionaries_and_staff_not_accepted(self):
        response = self.client_b.post(
            URL,
            {
                "parent_name": "Б",
                "phone": "+77071112233",
                "source": str(self.instagram.id),
                "branch": str(self.branch.id),
                "direction": str(self.direction.id),
                "assigned_to": str(self.admin.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        for field in ("source", "branch", "direction", "assigned_to"):
            self.assertIn(field, response.data)

    def test_foreign_rejection_reason_not_accepted(self):
        lead_b = create_lead(
            organization=self.org_b, actor=self.owner_b, parent_name="Б", phone="+77071112233"
        )
        response = self.move(
            lead_b, "rejected", client=self.client_b, rejection_reason=str(self.expensive.id)
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(LeadStatusChange.objects.filter(lead=lead_b).count(), 1)
