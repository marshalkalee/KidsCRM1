from datetime import timedelta

from django.test import TestCase, tag
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .defaults import DEFAULT_REJECTION_REASONS, DEFAULT_SOURCES, ensure_default_dictionaries
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
        # Значения по умолчанию заводятся сигналом при создании организации (TRU-93).
        self.instagram = LeadSource.objects.get(organization=self.org, name="Instagram")
        self.expensive = LeadRejectionReason.objects.get(organization=self.org, name="Дорого")
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
        self.assertEqual(
            response.data["allowed_transitions"],
            ["contacted", "trial_scheduled", "thinking", "rejected"],
        )

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


SOURCES_URL = f"{URL}sources/"
REASONS_URL = f"{URL}rejection-reasons/"


class LeadDictionaryDefaultsTests(TestCase):
    def test_new_organization_gets_defaults(self):
        org = Organization.objects.create(name="Новый центр", slug="new")
        self.assertEqual(
            sorted(LeadSource.objects.for_tenant(org).values_list("name", flat=True)),
            sorted(DEFAULT_SOURCES),
        )
        self.assertEqual(
            sorted(LeadRejectionReason.objects.for_tenant(org).values_list("name", flat=True)),
            sorted(DEFAULT_REJECTION_REASONS),
        )

    def test_signup_gets_defaults(self):
        response = APIClient().post(
            "/api/v1/users/auth/register/",
            {
                "org_name": "Студия",
                "full_name": "Владелец",
                "phone": "+77075550011",
                "password": "Str0ng-pass-42",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        org = User.objects.get(phone="+77075550011").organization
        self.assertEqual(LeadSource.objects.for_tenant(org).count(), len(DEFAULT_SOURCES))

    def test_ensure_defaults_is_idempotent_and_keeps_custom_values(self):
        org = Organization.objects.create(name="Центр", slug="c")
        LeadSource.objects.for_tenant(org).update(is_active=False)
        LeadSource.objects.create(organization=org, name="Блогер")
        ensure_default_dictionaries(org)
        # Уже есть значения (пусть архивные) — не добавляем заново.
        self.assertEqual(LeadSource.objects.for_tenant(org).count(), len(DEFAULT_SOURCES) + 1)
        self.assertEqual(LeadSource.objects.for_tenant(org).filter(is_active=True).count(), 1)


class LeadDictionaryApiTests(LeadFixtures):
    def setUp(self):
        super().setUp()
        self.manager = self.make_user("77040000001", User.Role.MANAGER)

    def names(self, url, client=None):
        return [row["name"] for row in (client or self.client_owner).get(url).data]

    def test_list_orders_frequent_first(self):
        website = LeadSource.objects.get(organization=self.org, name="Сайт")
        for _ in range(2):
            self.make_lead(source=website)
        self.make_lead(source=self.instagram)
        rows = self.client_owner.get(SOURCES_URL).data
        self.assertEqual([r["name"] for r in rows[:2]], ["Сайт", "Instagram"])
        self.assertEqual(rows[0]["usage_count"], 2)

    def test_rejection_reasons_counted_by_rejections(self):
        far = LeadRejectionReason.objects.get(organization=self.org, name="Далеко")
        lead = self.make_lead()
        change_status(lead, to_status=Lead.Status.REJECTED, actor=self.owner, rejection_reason=far)
        change_status(lead, to_status=Lead.Status.CONTACTED, actor=self.owner)
        rows = self.client_owner.get(REASONS_URL).data
        self.assertEqual((rows[0]["name"], rows[0]["usage_count"]), ("Далеко", 1))

    def test_create_rename_archive_restore(self):
        response = self.client_owner.post(
            SOURCES_URL, {"name": "  Реклама у блогера "}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["name"], "Реклама у блогера")
        source_id = response.data["id"]
        response = self.client_owner.patch(
            f"{SOURCES_URL}{source_id}/", {"name": "Блогер"}, format="json"
        )
        self.assertEqual(response.data["name"], "Блогер")
        self.client_owner.patch(f"{SOURCES_URL}{source_id}/", {"is_active": False}, format="json")
        self.assertNotIn("Блогер", self.names(f"{SOURCES_URL}?active=1"))
        self.assertEqual(self.names(SOURCES_URL)[-1], "Блогер")  # архивные — в конце
        self.client_owner.patch(f"{SOURCES_URL}{source_id}/", {"is_active": True}, format="json")
        self.assertIn("Блогер", self.names(f"{SOURCES_URL}?active=1"))

    def test_duplicate_name_rejected(self):
        response = self.client_owner.post(SOURCES_URL, {"name": "instagram"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.client_owner.post(REASONS_URL, {"name": " "}, format="json").status_code, 400
        )

    def test_no_delete(self):
        response = self.client_owner.delete(f"{SOURCES_URL}{self.instagram.id}/")
        self.assertEqual(response.status_code, 405)

    def test_archived_value_stays_on_old_lead(self):
        lead = self.make_lead(source=self.instagram)
        self.client_owner.patch(
            f"{SOURCES_URL}{self.instagram.id}/", {"is_active": False}, format="json"
        )
        self.assertEqual(self.client_owner.get(f"{URL}{lead.id}/").data["source_name"], "Instagram")

    def test_roles(self):
        teacher = self.make_user("77040000002", User.Role.TEACHER)
        admin_client = make_client(self.admin)
        self.assertEqual(admin_client.get(SOURCES_URL).status_code, 200)
        self.assertEqual(
            admin_client.post(SOURCES_URL, {"name": "Новый"}, format="json").status_code, 403
        )
        self.assertEqual(
            make_client(self.manager)
            .post(SOURCES_URL, {"name": "Новый"}, format="json")
            .status_code,
            201,
        )
        self.assertEqual(make_client(teacher).get(SOURCES_URL).status_code, 403)
        flags = make_client(self.manager).get("/api/v1/users/auth/me/").data["permissions"]
        self.assertTrue(flags["can_manage_lead_dictionaries"])
        self.assertFalse(
            admin_client.get("/api/v1/users/auth/me/").data["permissions"][
                "can_manage_lead_dictionaries"
            ]
        )


@tag("tenant_isolation")
class LeadDictionaryTenantIsolationTests(LeadFixtures):
    def test_foreign_org_cannot_see_or_edit(self):
        org_b = Organization.objects.create(name="Чужой", slug="b")
        client_b = make_client(self.make_user("77050000001", User.Role.OWNER, organization=org_b))
        ids = {row["id"] for row in client_b.get(SOURCES_URL).data}
        self.assertNotIn(str(self.instagram.id), ids)
        response = client_b.patch(
            f"{SOURCES_URL}{self.instagram.id}/", {"name": "X"}, format="json"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(client_b.get(f"{REASONS_URL}{self.expensive.id}/").status_code, 404)


BOARD_URL = f"{URL}board/"


class LeadBoardTests(LeadFixtures):
    def column(self, data, status):
        return next(c for c in data["columns"] if c["status"] == status)

    def test_columns_counts_and_order(self):
        older = self.make_lead(parent_name="Старая")
        Lead.objects.filter(pk=older.pk).update(
            status_changed_at=timezone.now() - timedelta(days=2)
        )
        newer = self.make_lead(parent_name="Новая")
        contacted = self.make_lead()
        change_status(contacted, to_status=Lead.Status.CONTACTED, actor=self.owner)
        data = self.client_owner.get(BOARD_URL).data
        self.assertEqual([c["status"] for c in data["columns"]], Lead.Status.values)
        new = self.column(data, "new")
        self.assertEqual(new["count"], 2)
        self.assertEqual(new["label"], "Новая")
        self.assertEqual([r["id"] for r in new["results"]], [str(newer.id), str(older.id)])
        self.assertEqual(self.column(data, "contacted")["count"], 1)
        self.assertEqual(self.column(data, "thinking")["results"], [])
        self.assertIn("contacted", data["transitions"]["new"])
        self.assertEqual(data["transitions"]["purchased"], [])

    def test_limit_and_load_more(self):
        for i in range(5):
            self.make_lead(parent_name=f"Родитель {i}")
        first = self.column(self.client_owner.get(f"{BOARD_URL}?limit=2").data, "new")
        self.assertEqual((len(first["results"]), first["count"], first["has_more"]), (2, 5, True))
        more = self.client_owner.get(f"{BOARD_URL}?limit=2&column=new&offset=4").data
        self.assertEqual(len(more["columns"]), 1)
        self.assertEqual(
            (len(more["columns"][0]["results"]), more["columns"][0]["has_more"]), (1, False)
        )

    def test_closed_columns_only_recent(self):
        old = self.make_lead()
        change_status(
            old, to_status=Lead.Status.REJECTED, actor=self.owner, rejection_reason=self.expensive
        )
        Lead.objects.filter(pk=old.pk).update(status_changed_at=timezone.now() - timedelta(days=40))
        recent = self.make_lead()
        change_status(
            recent,
            to_status=Lead.Status.REJECTED,
            actor=self.owner,
            rejection_reason=self.expensive,
        )
        rejected = self.column(self.client_owner.get(BOARD_URL).data, "rejected")
        self.assertEqual([r["id"] for r in rejected["results"]], [str(recent.id)])
        # Явный период — показываем и старые.
        rejected = self.column(
            self.client_owner.get(f"{BOARD_URL}?created_from=2000-01-01").data, "rejected"
        )
        self.assertEqual(rejected["count"], 2)

    def test_open_columns_not_limited_by_period(self):
        lead = self.make_lead()
        Lead.objects.filter(pk=lead.pk).update(
            status_changed_at=timezone.now() - timedelta(days=90)
        )
        self.assertEqual(self.column(self.client_owner.get(BOARD_URL).data, "new")["count"], 1)

    def test_filters_apply(self):
        self.make_lead(source=self.instagram)
        self.make_lead()
        data = self.client_owner.get(f"{BOARD_URL}?source={self.instagram.id}").data
        self.assertEqual(self.column(data, "new")["count"], 1)

    def test_stale_flag(self):
        lead = self.make_lead()
        self.assertFalse(self.client_owner.get(f"{URL}{lead.id}/").data["is_stale"])
        Lead.objects.filter(pk=lead.pk).update(
            status_changed_at=timezone.now() - timedelta(days=1, hours=1)
        )
        self.assertTrue(self.client_owner.get(f"{URL}{lead.id}/").data["is_stale"])
        change_status(lead, to_status=Lead.Status.CONTACTED, actor=self.owner)
        Lead.objects.filter(pk=lead.pk).update(status_changed_at=timezone.now() - timedelta(days=2))
        self.assertFalse(self.client_owner.get(f"{URL}{lead.id}/").data["is_stale"])

    def test_closed_never_stale(self):
        lead = self.make_lead()
        change_status(
            lead, to_status=Lead.Status.REJECTED, actor=self.owner, rejection_reason=self.expensive
        )
        Lead.objects.filter(pk=lead.pk).update(
            status_changed_at=timezone.now() - timedelta(days=20)
        )
        self.assertFalse(self.client_owner.get(f"{URL}{lead.id}/").data["is_stale"])

    def test_board_query_count_does_not_grow_with_leads(self):
        for i in range(60):
            self.make_lead(
                parent_name=f"Родитель {i}",
                source=self.instagram,
                direction=self.direction,
                branch=self.branch,
            )
        # Счётчики одним запросом + по запросу на колонку, связи — select_related.
        with self.assertNumQueries(12):
            response = self.client_owner.get(BOARD_URL)
        self.assertEqual(self.column(response.data, "new")["count"], 60)

    def test_board_requires_lead_permission(self):
        teacher = self.make_user("77060000001", User.Role.TEACHER)
        self.assertEqual(make_client(teacher).get(BOARD_URL).status_code, 403)


class LeadPhoneCheckTests(LeadFixtures):
    def check(self, phone, client=None):
        return (client or self.client_owner).get(f"{URL}check-phone/", {"phone": phone}).data

    def test_finds_open_leads_by_any_phone_format(self):
        lead = self.make_lead(child_name="Алия")
        data = self.check("8 707 111 22 33")
        self.assertEqual(data["phone"], "+77071112233")
        self.assertEqual([row["id"] for row in data["leads"]], [str(lead.id)])
        self.assertEqual(data["leads"][0]["status_label"], "Новая")

    def test_purchased_leads_not_reported(self):
        lead = self.make_lead()
        for step in (Lead.Status.CONTACTED, Lead.Status.PURCHASED):
            change_status(lead, to_status=step, actor=self.owner)
        self.assertEqual(self.check("+77071112233")["leads"], [])

    def test_finds_parent_with_children(self):
        from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact

        parent = ParentContact.objects.create(organization=self.org, full_name="Айгерим Сейтова")
        ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77071112233"
        )
        child = Child.objects.create(
            organization=self.org,
            full_name="Алия Сейтова",
            birth_date="2019-03-14",
            gender="female",
        )
        ChildContact.objects.create(
            organization=self.org, child=child, parent_contact=parent, role="mother"
        )
        data = self.check("+7 707 111 2233")
        self.assertEqual(
            data["parents"],
            [
                {
                    "id": str(parent.id),
                    "full_name": "Айгерим Сейтова",
                    "children": [{"id": str(child.id), "full_name": "Алия Сейтова"}],
                }
            ],
        )

    def test_incomplete_phone_gives_empty_answer(self):
        self.make_lead()
        self.assertEqual(self.check("+7707"), {"phone": None, "leads": [], "parents": []})

    def test_other_org_not_visible(self):
        self.make_lead()
        org_b = Organization.objects.create(name="Чужой", slug="b2")
        client_b = make_client(self.make_user("77080000001", User.Role.OWNER, organization=org_b))
        self.assertEqual(self.check("+77071112233", client=client_b)["leads"], [])

    def test_requires_lead_permission(self):
        teacher = self.make_user("77080000002", User.Role.TEACHER)
        self.assertEqual(
            make_client(teacher).get(f"{URL}check-phone/", {"phone": "+77071112233"}).status_code,
            403,
        )


class LeadChildLinkTests(LeadFixtures):
    def setUp(self):
        super().setUp()
        from domains.people.clients.models import Child

        self.child = Child.objects.create(
            organization=self.org,
            full_name="Алия Сейтова",
            birth_date="2019-03-14",
            gender="female",
        )
        self.lead = self.make_lead(source=self.instagram)
        Lead.objects.filter(pk=self.lead.pk).update(converted_child=self.child)

    def test_lead_shows_child(self):
        data = self.client_owner.get(f"{URL}{self.lead.id}/").data
        self.assertEqual(
            (data["converted_child"], data["converted_child_name"]), (self.child.id, "Алия Сейтова")
        )

    def test_child_card_shows_lead(self):
        data = self.client_owner.get(f"/api/v1/clients/children/{self.child.id}/card/").data
        self.assertEqual(
            [(row["id"], row["source_name"]) for row in data["leads"]],
            [(str(self.lead.id), "Instagram")],
        )

    def test_child_card_hides_leads_without_permission(self):
        teacher = self.make_user("77090000001", User.Role.TEACHER)
        data = make_client(teacher).get(f"/api/v1/clients/children/{self.child.id}/card/").data
        self.assertEqual(data["leads"], [])

    def test_me_has_organization_name(self):
        self.assertEqual(
            self.client_owner.get("/api/v1/users/auth/me/").data["organization_name"], "Балет"
        )


class LeadTableTests(LeadFixtures):
    def setUp(self):
        super().setUp()
        self.a = self.make_lead(
            parent_name="Айгерим", child_name="Бота", child_age=7, source=self.instagram
        )
        self.b = self.make_lead(
            parent_name="Дина", child_name="Алия", child_age=5, phone="+77019998877"
        )
        self.c = self.make_lead(
            parent_name="Вера", child_name="Вика", child_age=9, phone="+77019998866"
        )
        Lead.objects.filter(pk=self.c.pk).update(
            status_changed_at=timezone.now() - timedelta(days=5)
        )

    def names(self, ordering):
        return [
            row["child_name"]
            for row in self.client_owner.get(URL, {"ordering": ordering}).data["results"]
        ]

    def test_ordering(self):
        self.assertEqual(self.names("child_name"), ["Алия", "Бота", "Вика"])
        self.assertEqual(self.names("-child_age"), ["Вика", "Бота", "Алия"])
        self.assertEqual(self.names("-days_in_status")[0], "Вика")
        self.assertEqual(self.names("days_in_status")[-1], "Вика")
        self.assertEqual(len(self.names("nonsense")), 3)

    def bulk(self, payload, client=None):
        return (client or self.client_owner).post(f"{URL}bulk/", payload, format="json")

    def test_bulk_status_writes_history_for_each(self):
        response = self.bulk(
            {"ids": [str(self.a.id), str(self.b.id)], "action": "status", "status": "contacted"}
        )
        self.assertEqual(response.data, {"updated": 2, "failed": []})
        for lead in (self.a, self.b):
            self.assertEqual(
                list(lead.status_changes.values_list("to_status", flat=True)), ["new", "contacted"]
            )

    def test_bulk_reports_invalid_transitions_and_keeps_others(self):
        change_status(self.a, to_status=Lead.Status.CONTACTED, actor=self.owner)
        response = self.bulk(
            {"ids": [str(self.a.id), str(self.b.id)], "action": "status", "status": "purchased"}
        )
        self.assertEqual(response.data["updated"], 1)
        self.assertEqual([row["id"] for row in response.data["failed"]], [str(self.b.id)])
        self.assertIn("нельзя перейти", response.data["failed"][0]["error"])

    def test_bulk_reject_requires_reason(self):
        response = self.bulk({"ids": [str(self.a.id)], "action": "status", "status": "rejected"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("rejection_reason", response.data)
        response = self.bulk(
            {
                "ids": [str(self.a.id)],
                "action": "status",
                "status": "rejected",
                "rejection_reason": str(self.expensive.id),
            }
        )
        self.assertEqual(response.data["updated"], 1)

    def test_bulk_assign(self):
        response = self.bulk(
            {
                "ids": [str(self.a.id), str(self.c.id)],
                "action": "assign",
                "assigned_to": str(self.admin.id),
            }
        )
        self.assertEqual(response.data["updated"], 2)
        self.assertEqual(Lead.objects.filter(assigned_to=self.admin).count(), 2)

    def test_bulk_ignores_invisible_and_foreign_leads(self):
        org_b = Organization.objects.create(name="Чужой", slug="b3")
        owner_b = self.make_user("77100000001", User.Role.OWNER, organization=org_b)
        response = self.bulk(
            {"ids": [str(self.a.id)], "action": "status", "status": "contacted"},
            client=make_client(owner_b),
        )
        self.assertEqual(response.data["updated"], 0)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, "new")

    def test_export_xlsx_uses_filters(self):
        import io

        import openpyxl

        response = self.client_owner.get(f"{URL}export/", {"source": str(self.instagram.id)})
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])
        sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
        rows = list(sheet.iter_rows(values_only=True))
        self.assertEqual(rows[0][:3], ("Ребёнок", "Возраст", "Родитель"))
        self.assertEqual([row[0] for row in rows[1:]], ["Бота"])
        self.assertEqual(rows[1][6], "Новая")

    def test_export_requires_permission(self):
        teacher = self.make_user("77100000002", User.Role.TEACHER)
        self.assertEqual(make_client(teacher).get(f"{URL}export/").status_code, 403)
