import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.people.clients.services import ChildService
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule.models import Lesson

from .models import Lead
from .services import change_status, create_lead
from .trial_booking import book_trial


def authenticated_client(user):
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class LeadConversionApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Балет", slug="conversion-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Центр")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.owner = User.objects.create_user(
            phone="+77010000400",
            password="pass",
            full_name="Владелец Тестов",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.client = authenticated_client(self.owner)
        self.lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="Айгерим Серикова",
            phone="+77071112233",
            child_name="Алия Серикова",
            child_age=7,
            branch=self.branch,
            direction=self.direction,
        )
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет 7–9",
            capacity=12,
            age_min=7,
            age_max=9,
        )
        starts = timezone.now() + datetime.timedelta(days=1)
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=starts,
            ends_at=starts + datetime.timedelta(hours=1),
        )
        self.lead, self.enrollment = book_trial(self.lead, self.lesson.id, actor=self.owner)
        self.candidate = self.enrollment.child
        self.lead = change_status(
            self.lead,
            to_status=Lead.Status.TRIAL_ATTENDED,
            actor=self.owner,
        )

    @property
    def url(self):
        return f"/api/v1/leads/{self.lead.id}/conversion/"

    def payload(self, **overrides):
        data = {
            "decision": "create_new",
            "child_name": "Алия Серикова",
            "birth_date": "2019-04-12",
            "gender": "female",
            "parent_name": "Айгерим Серикова",
            "link_role": "mother",
            "consent_given": True,
        }
        data.update(overrides)
        return data

    def test_without_duplicates_creates_complete_family_and_moves_trial_history(self):
        Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.candidate,
            status=Attendance.Status.PRESENT,
            marked_by=self.owner,
            marked_at=timezone.now(),
            consume_outcome="trial_no_charge",
        )

        preview = self.client.get(self.url)
        response = self.client.post(self.url, self.payload(), format="json")

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data["matches"], [])
        self.assertEqual(response.status_code, 201, response.data)
        self.lead.refresh_from_db()
        child = self.lead.converted_child
        self.assertNotEqual(child.id, self.candidate.id)
        self.assertEqual(child.full_name, "Алия Серикова")
        self.assertEqual(child.birth_date, datetime.date(2019, 4, 12))
        self.assertFalse(child.birth_date_is_estimated)
        self.assertEqual(child.gender, Child.Gender.FEMALE)
        self.assertEqual(child.status, Child.Status.ACTIVE)
        self.assertTrue(child.consent_given)
        self.assertTrue(child.directions.filter(pk=self.direction.pk).exists())
        link = ChildContact.objects.select_related("parent_contact").get(child=child)
        self.assertEqual(link.parent_contact.full_name, "Айгерим Серикова")
        self.assertEqual(link.parent_contact.phones.get().number, "+77071112233")
        self.assertTrue(link.is_primary_contact)
        self.assertTrue(link.is_payer)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.child, child)
        self.assertTrue(Attendance.objects.filter(lesson=self.lesson, child=child).exists())
        deleted_candidate = Child.objects.all_with_deleted().get(pk=self.candidate.pk)
        self.assertIsNotNone(deleted_candidate.deleted_at)

    def test_same_phone_other_child_reuses_parent_and_creates_second_child(self):
        first_child = ChildService.create_with_parent(
            self.org,
            child_data={
                "full_name": "Старшая Серикова",
                "birth_date": datetime.date(2015, 3, 1),
                "gender": Child.Gender.FEMALE,
                "consent_given": True,
            },
            parent_data={"full_name": "Айгерим Серикова", "phones": [self.lead.phone]},
            link_role=ChildContact.Role.MOTHER,
        )
        parent = first_child.contacts.get().parent_contact

        preview = self.client.get(
            self.url,
            {"child_name": "Алия Серикова", "birth_date": "2019-04-12"},
        )
        response = self.client.post(
            self.url,
            self.payload(decision="existing_parent", parent_id=str(parent.id)),
            format="json",
        )

        self.assertEqual(preview.status_code, 200)
        family_match = next(
            row for row in preview.data["matches"] if row["reason"] == "existing_parent_new_child"
        )
        self.assertEqual(family_match["parent"]["id"], str(parent.id))
        self.assertEqual(response.status_code, 201, response.data)
        self.lead.refresh_from_db()
        self.assertNotEqual(self.lead.converted_child, first_child)
        self.assertEqual(ParentContact.objects.for_tenant(self.org).count(), 1)
        self.assertEqual(
            ChildContact.objects.for_tenant(self.org).filter(parent_contact=parent).count(), 2
        )

    def test_existing_child_is_only_linked_after_explicit_choice(self):
        existing = ChildService.create_with_parent(
            self.org,
            child_data={
                "full_name": "Алия Серикова",
                "birth_date": datetime.date(2019, 4, 12),
                "gender": Child.Gender.FEMALE,
                "consent_given": False,
            },
            parent_data={"full_name": "Айгерим Серикова", "phones": [self.lead.phone]},
            link_role=ChildContact.Role.MOTHER,
        )

        preview = self.client.get(
            self.url,
            {"child_name": "Алия Серикова", "birth_date": "2019-04-12"},
        )
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.converted_child)
        self.assertTrue(Child.objects.filter(pk=self.candidate.pk).exists())
        exact = next(row for row in preview.data["matches"] if row["reason"] == "phone")
        self.assertEqual(exact["child"]["id"], str(existing.id))

        response = self.client.post(
            self.url,
            self.payload(decision="existing_child", child_id=str(existing.id)),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.lead.refresh_from_db()
        existing.refresh_from_db()
        self.assertEqual(self.lead.converted_child, existing)
        self.assertTrue(existing.consent_given)
        self.assertTrue(existing.directions.filter(pk=self.direction.pk).exists())
        self.assertFalse(Child.objects.filter(pk=self.candidate.pk).exists())

    def test_requires_complete_data_and_consent(self):
        response = self.client.post(
            self.url,
            self.payload(child_name="Алия", consent_given=False),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("child_name", response.data)
        self.assertIn("consent_given", response.data)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.converted_child)

    def test_cannot_select_match_from_another_organization(self):
        other_org = Organization.objects.create(name="Другая", slug="other-conversion")
        other_parent = ParentContact.objects.create(
            organization=other_org, full_name="Чужой Родитель"
        )
        ContactPhone.objects.create(parent_contact=other_parent, number=self.lead.phone)

        response = self.client.post(
            self.url,
            self.payload(decision="existing_parent", parent_id=str(other_parent.id)),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.converted_child)

    def test_converted_child_card_links_back_to_lead(self):
        response = self.client.post(self.url, self.payload(), format="json")
        child_id = response.data["converted_child"]

        card = self.client.get(f"/api/v1/clients/children/{child_id}/card/")

        self.assertEqual(card.status_code, 200, card.data)
        self.assertEqual(card.data["leads"][0]["id"], str(self.lead.id))
        self.assertEqual(card.data["leads"][0]["branch_name"], self.branch.name)
        self.assertEqual(card.data["leads"][0]["direction_name"], self.direction.name)
        self.assertEqual(card.data["leads"][0]["lead_child_age"], 7)
