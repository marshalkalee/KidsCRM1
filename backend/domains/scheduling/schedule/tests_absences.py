"""
Отсутствия сотрудников и занятия «нужна замена» (TRU-182): права, филиалы
сотрудника (Д36), границы дней по часам центра, изоляция организаций.
"""

import datetime

from django.test import tag
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Branch, Direction, Organization, Room
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group

from .models import Lesson, StaffAbsence

TZ = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
URL = "/api/v1/schedule/absences/"
MONDAY = datetime.date(2026, 11, 2)


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=TZ)


class AbsenceBase(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="absences")
        self.abay = Branch.objects.create(organization=self.org, name="Абая")
        self.orbita = Branch.objects.create(organization=self.org, name="Орбита")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.room = Room.objects.create(organization=self.org, branch=self.abay, name="Большой зал")
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.abay,
            direction=self.ballet,
            name="Балет 6–8",
            capacity=12,
        )
        self.owner = self.user("+77010000001", "Владелец", User.Role.OWNER)
        self.admin = self.user("+77010000002", "Админ Абая", User.Role.ADMIN, [self.abay])
        self.admin_orbita = self.user(
            "+77010000003", "Админ Орбиты", User.Role.ADMIN, [self.orbita]
        )
        self.teacher = self.user("+77010000004", "Алия", User.Role.TEACHER, [self.abay])
        self.other_teacher = self.user("+77010000005", "Дина", User.Role.TEACHER, [self.abay])

    def user(self, phone, name, role, branches=()):
        user = User.objects.create_user(
            phone=phone, password="x", full_name=name, organization=self.org, role=role
        )
        user.branches.set(branches)
        return user

    def lesson(self, starts_at, teacher=None, **extra):
        return Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            teacher=teacher or self.teacher,
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=1),
            **extra,
        )

    def as_user(self, user):
        # Организацию запросу задаёт claim JWT (TenantMiddleware), а не
        # force_authenticate — как _authenticated_client в tests.py.
        refresh = RefreshToken.for_user(user)
        refresh["organization_id"] = str(user.organization_id)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def add(
        self, staff=None, starts_on=MONDAY, ends_on=MONDAY + datetime.timedelta(days=4), **extra
    ):
        return self.client.post(
            URL,
            {
                "staff": str((staff or self.teacher).pk),
                "kind": "vacation",
                "starts_on": starts_on.isoformat(),
                "ends_on": ends_on.isoformat(),
                **extra,
            },
        )


class UncoveredLessonsTests(AbsenceBase):
    def test_absence_marks_lessons_in_schedule_and_uncovered_list(self):
        inside = [self.lesson(at(MONDAY + datetime.timedelta(days=d), 16)) for d in (0, 2, 4)]
        after = self.lesson(at(MONDAY + datetime.timedelta(days=7), 16))
        self.as_user(self.admin)

        created = self.add()
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["lessons_affected"], 3)

        week = self.client.get(
            "/api/v1/schedule/",
            {
                "date_from": MONDAY.isoformat(),
                "date_to": (MONDAY + datetime.timedelta(days=7)).isoformat(),
            },
        ).data
        marked = {row["id"]: row["teacher_absence"] for row in week}
        for lesson in inside:
            self.assertEqual(marked[str(lesson.id)]["kind"], "vacation")
            self.assertEqual(marked[str(lesson.id)]["ends_on"], "2026-11-06")
        self.assertIsNone(marked[str(after.id)])

        uncovered = self.client.get(
            URL + "uncovered/", {"date_from": "2026-11-01", "date_to": "2026-11-30"}
        ).data
        self.assertEqual(uncovered["count"], 3)
        self.assertEqual([r["id"] for r in uncovered["results"]], [str(x.id) for x in inside])
        self.assertEqual(uncovered["results"][0]["teacher_name"], "Алия")
        self.assertEqual(uncovered["results"][0]["branch_name"], "Абая")

    def test_mark_disappears_after_substitute_or_cancel(self):
        replaced = self.lesson(at(MONDAY, 16))
        cancelled = self.lesson(at(MONDAY, 18))
        kept = self.lesson(at(MONDAY + datetime.timedelta(days=1), 16))
        self.as_user(self.admin)
        self.add()
        replaced.teacher = self.other_teacher
        replaced.save()
        cancelled.status = Lesson.Status.CANCELLED
        cancelled.save()

        rows = self.client.get(
            URL + "uncovered/", {"date_from": "2026-11-01", "date_to": "2026-11-30"}
        ).data["results"]
        self.assertEqual([r["id"] for r in rows], [str(kept.id)])
        self.assertIsNone(
            self.client.get(f"/api/v1/schedule/{replaced.id}/").data["teacher_absence"]
        )

    def test_days_are_center_days(self):
        # 00:30 по Алматы в субботу — это уже не пятница, хотя в UTC ещё пятница.
        late_friday = self.lesson(at(MONDAY + datetime.timedelta(days=4), 23, 0))
        saturday_night = self.lesson(at(MONDAY + datetime.timedelta(days=5), 0, 30))
        self.as_user(self.admin)
        self.add()
        rows = self.client.get(
            URL + "uncovered/", {"date_from": "2026-11-01", "date_to": "2026-11-30"}
        ).data["results"]
        ids = [r["id"] for r in rows]
        self.assertIn(str(late_friday.id), ids)
        self.assertNotIn(str(saturday_night.id), ids)


class AbsenceRulesTests(AbsenceBase):
    def test_validation(self):
        self.as_user(self.admin)
        backwards = self.add(starts_on=MONDAY, ends_on=MONDAY - datetime.timedelta(days=1))
        self.assertEqual(backwards.status_code, 400)
        self.assertEqual(self.add().status_code, 201)
        overlap = self.add(
            starts_on=MONDAY + datetime.timedelta(days=3),
            ends_on=MONDAY + datetime.timedelta(days=9),
        )
        self.assertEqual(overlap.status_code, 400)
        self.assertIn("уже есть отсутствие", str(overlap.data["starts_on"]))
        # Другому сотруднику на те же даты — можно.
        self.assertEqual(self.add(staff=self.other_teacher).status_code, 201)

    def test_edit_keeps_itself_out_of_overlap_and_is_audited(self):
        self.as_user(self.admin)
        absence_id = self.add().data["id"]
        changed = self.client.patch(
            f"{URL}{absence_id}/", {"ends_on": "2026-11-10", "kind": "sick"}
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["kind_display"], "Больничный")
        self.assertEqual(self.client.delete(f"{URL}{absence_id}/").status_code, 204)
        self.assertFalse(StaffAbsence.objects.for_tenant(self.org).exists())
        actions = list(
            AuditLog.objects.filter(object_id=absence_id)
            .order_by("created_at")
            .values_list("action", flat=True)
        )
        self.assertEqual(actions, ["create", "update", "delete"])

    def test_teacher_sees_only_own_and_cannot_edit(self):
        self.as_user(self.admin)
        self.add()
        self.add(staff=self.other_teacher)
        self.as_user(self.other_teacher)
        own = self.client.get(URL).data
        self.assertEqual([row["staff_name"] for row in own], ["Дина"])
        # Карточка коллеги: чужих отсутствий нет, и свои туда не подмешиваются.
        self.assertEqual(self.client.get(URL, {"staff": str(self.teacher.pk)}).data, [])
        self.assertEqual(
            self.add(
                staff=self.other_teacher,
                starts_on=datetime.date(2026, 12, 1),
                ends_on=datetime.date(2026, 12, 2),
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get(URL + "uncovered/").status_code, 403)

    def test_branch_admin_works_only_with_own_branch_staff(self):
        self.as_user(self.admin)
        self.add()
        self.as_user(self.admin_orbita)
        self.assertEqual(self.client.get(URL).data, [])
        refused = self.add(staff=self.other_teacher)
        self.assertEqual(refused.status_code, 400)
        self.assertIn("другом филиале", str(refused.data["staff"]))
        self.assertEqual(
            self.client.get(
                URL + "uncovered/", {"date_from": "2026-11-01", "date_to": "2026-11-30"}
            ).data["count"],
            0,
        )
        # Владелец видит всё.
        self.as_user(self.owner)
        self.assertEqual(len(self.client.get(URL).data), 1)


@tag("tenant_isolation")
class AbsenceIsolationTests(AbsenceBase):
    def test_other_center_absences_and_staff_are_invisible(self):
        other = Organization.objects.create(name="Другой центр", slug="absences-other")
        stranger = User.objects.create_user(
            phone="+77019999999",
            password="x",
            full_name="Чужой",
            organization=other,
            role=User.Role.TEACHER,
        )
        foreign = StaffAbsence.objects.create(
            organization=other, staff=stranger, starts_on=MONDAY, ends_on=MONDAY
        )
        self.as_user(self.owner)
        self.assertEqual(self.client.get(URL).data, [])
        self.assertEqual(self.client.get(f"{URL}{foreign.id}/").status_code, 404)
        self.assertEqual(self.client.delete(f"{URL}{foreign.id}/").status_code, 404)
        self.assertEqual(self.add(staff=stranger).status_code, 400)
        self.assertTrue(StaffAbsence.objects.filter(pk=foreign.pk).exists())
