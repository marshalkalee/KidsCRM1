import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from .models import Lead, LeadStatusChange
from .services import create_lead


def authenticated_client(user):
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class TrialBookingApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Балет", slug="trial-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Центр")
        self.other_branch = Branch.objects.create(organization=self.org, name="Орбита")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.other_direction = Direction.objects.create(organization=self.org, name="Гимнастика")
        self.owner = User.objects.create_user(
            phone="+77010000100",
            password="pass",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.client = authenticated_client(self.owner)
        self.lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="Айгерим",
            phone="+77071112233",
            child_name="Алия",
            child_age=7,
            branch=self.branch,
            direction=self.direction,
        )
        self.group = self.make_group(name="Балет 7–9", capacity=3, age_min=7, age_max=9)
        self.lesson = self.make_lesson(self.group, days=2)

    def make_group(
        self,
        *,
        name,
        capacity=10,
        age_min=None,
        age_max=None,
        branch=None,
        direction=None,
    ):
        return Group.objects.create(
            organization=self.org,
            branch=branch or self.branch,
            direction=direction or self.direction,
            name=name,
            capacity=capacity,
            age_min=age_min,
            age_max=age_max,
        )

    def make_lesson(self, group, *, days=1, status=Lesson.Status.SCHEDULED):
        starts = timezone.now() + datetime.timedelta(days=days)
        return Lesson.objects.create(
            organization=self.org,
            group=group,
            starts_at=starts,
            ends_at=starts + datetime.timedelta(hours=1),
            status=status,
        )

    def make_child(self, name="Участник"):
        return Child.objects.create(
            organization=self.org,
            full_name=name,
            birth_date=timezone.localdate() - datetime.timedelta(days=365 * 8),
            gender=Child.Gender.FEMALE,
        )

    def candidates(self):
        return self.client.get(f"/api/v1/leads/{self.lead.id}/trial-lessons/")

    def test_candidates_match_direction_age_branch_future_and_capacity(self):
        wrong_direction = self.make_group(name="Не то направление", direction=self.other_direction)
        wrong_branch = self.make_group(name="Не тот филиал", branch=self.other_branch)
        wrong_age = self.make_group(name="Подростки", age_min=12, age_max=16)
        full = self.make_group(name="Полная", capacity=1)
        full_child = self.make_child()
        GroupMembership.objects.create(
            organization=self.org,
            group=full,
            child=full_child,
            joined_at=timezone.localdate(),
        )
        for group in (wrong_direction, wrong_branch, wrong_age, full):
            self.make_lesson(group)
        self.make_lesson(self.group, days=-2)
        self.make_lesson(self.group, status=Lesson.Status.CANCELLED)

        response = self.candidates()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["id"] for row in response.data], [str(self.lesson.id)])
        self.assertEqual(response.data[0]["spots_left"], 3)

    def test_booking_creates_trial_child_enrollment_status_and_history(self):
        response = self.client.post(
            f"/api/v1/leads/{self.lead.id}/book-trial/",
            {"lesson": str(self.lesson.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, Lead.Status.TRIAL_SCHEDULED)
        enrollment = LessonEnrollment.objects.get(source_lead=self.lead)
        self.assertEqual(enrollment.kind, LessonEnrollment.Kind.TRIAL)
        self.assertEqual(enrollment.lesson, self.lesson)
        child = enrollment.child
        self.assertEqual(child.full_name, "Алия")
        self.assertEqual(child.status, Child.Status.TRIAL)
        self.assertTrue(child.birth_date_is_estimated)
        self.assertEqual(child.gender, "")
        self.assertEqual(child.age, 7)
        self.assertTrue(child.directions.filter(pk=self.direction.pk).exists())
        self.assertTrue(self.lesson.participants().filter(pk=child.pk).exists())
        change = LeadStatusChange.objects.filter(lead=self.lead).latest("changed_at")
        self.assertEqual(change.to_status, Lead.Status.TRIAL_SCHEDULED)
        self.assertIn(self.group.name, change.comment)
        self.assertEqual(response.data["trial_booking"]["lesson_id"], str(self.lesson.id))
        self.assertEqual(response.data["trial_booking"]["child_id"], str(child.id))

    def test_booking_rechecks_capacity_and_does_not_create_candidate(self):
        response = self.candidates()
        self.assertEqual(len(response.data), 1)
        for index in range(self.group.capacity):
            child = self.make_child(f"Участник {index}")
            GroupMembership.objects.create(
                organization=self.org,
                group=self.group,
                child=child,
                joined_at=timezone.localdate(),
            )

        response = self.client.post(
            f"/api/v1/leads/{self.lead.id}/book-trial/",
            {"lesson": str(self.lesson.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, Lead.Status.NEW)
        self.assertFalse(Child.objects.filter(full_name="Алия").exists())
        self.assertFalse(LessonEnrollment.objects.filter(source_lead=self.lead).exists())

    def test_second_booking_is_rejected(self):
        url = f"/api/v1/leads/{self.lead.id}/book-trial/"
        first = self.client.post(url, {"lesson": str(self.lesson.id)}, format="json")
        second_lesson = self.make_lesson(self.group, days=3)

        second = self.client.post(url, {"lesson": str(second_lesson.id)}, format="json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(
            LessonEnrollment.objects.filter(
                source_lead=self.lead, cancelled_at__isnull=True
            ).count(),
            1,
        )

    def test_missing_lead_filters_explain_what_to_fill(self):
        lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="Родитель",
            phone="+77071112244",
        )

        response = self.client.get(f"/api/v1/leads/{lead.id}/trial-lessons/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("имя ребёнка", response.data["detail"])
        self.assertIn("возраст", response.data["detail"])
        self.assertIn("направление", response.data["detail"])
        self.assertIn("филиал", response.data["detail"])

    def test_foreign_organization_cannot_see_or_book_lead(self):
        other_org = Organization.objects.create(name="Другая", slug="other-trial")
        other_owner = User.objects.create_user(
            phone="+77010000101",
            password="pass",
            full_name="Другой",
            organization=other_org,
            role=User.Role.OWNER,
        )
        other_client = authenticated_client(other_owner)

        candidates = other_client.get(f"/api/v1/leads/{self.lead.id}/trial-lessons/")
        booking = other_client.post(
            f"/api/v1/leads/{self.lead.id}/book-trial/",
            {"lesson": str(self.lesson.id)},
            format="json",
        )

        self.assertEqual(candidates.status_code, 404)
        self.assertEqual(booking.status_code, 404)
