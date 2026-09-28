"""Поиск обычным языком, посещаемость по фото, чистка импорта — модель
подменена: проверяем, что уходит в модель и как ответ превращается в
фильтры, отметки и файл."""

import base64
import datetime
import io
import json

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import Child
from domains.platform.leads.models import LeadSource
from domains.platform.tenants.models import Branch
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from . import services
from .tests import AIFixtures, fake_response, patched_client


def as_user(role, org, phone):
    user = User.objects.create_user(
        phone=phone, password="pass", full_name=role, organization=org, role=role
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


SEARCH_EMPTY = {
    "screen": "children",
    "text": "",
    "branch": "",
    "direction": "",
    "group": "",
    "child_status": "",
    "has_debt": False,
    "debt_overdue": False,
    "expiring": False,
    "no_subscription": False,
    "lead_kind": "new",
    "lead_source": "",
    "only_mine": False,
    "created_from": "",
    "created_to": "",
    "explanation": "",
}


class SearchTests(AIFixtures):
    def setUp(self):
        super().setUp()
        self.orbit = Branch.objects.create(organization=self.org, name="Орбита")

    def search(self, answer, client=None):
        patch, create = patched_client(fake_response({**SEARCH_EMPTY, **answer}))
        with patch:
            response = (client or self.client_api).post(
                "/api/v1/ai/search/", {"query": "что-то"}, format="json"
            )
        return response, create

    def test_children_with_overdue_debt_in_branch(self):
        response, create = self.search(
            {"branch": "Орбита", "debt_overdue": True, "explanation": "Должники Орбиты"}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["path"], f"/children?branch={self.orbit.id}&has_debt=1&debt_overdue=1"
        )
        self.assertEqual(response.data["explanation"], "Должники Орбиты")
        schema = create.call_args.kwargs["output_config"]["format"]["schema"]
        self.assertIn("Орбита", schema["properties"]["branch"]["enum"])

    def test_leads_from_instagram_for_month(self):
        instagram = LeadSource.objects.get(organization=self.org, name="Instagram")
        response, _ = self.search(
            {
                "screen": "leads",
                "lead_source": "Instagram",
                "created_from": "2026-09-01",
                "created_to": "2026-09-30",
            }
        )
        self.assertEqual(
            response.data["path"],
            f"/leads?source={instagram.id}&created_from=2026-09-01&created_to=2026-09-30&view=table",
        )

    def test_garbage_values_ignored(self):
        response, _ = self.search({"branch": "", "created_from": "вчера", "text": "Алия"})
        self.assertEqual(response.data["path"], "/children?q=%D0%90%D0%BB%D0%B8%D1%8F")

    def test_teacher_gets_no_money_filters_and_no_leads(self):
        _, teacher_client = as_user(User.Role.TEACHER, self.org, "77010000031")
        response, create = self.search({"screen": "leads", "has_debt": True}, client=teacher_client)
        self.assertEqual(response.data["path"], "/children")
        schema = create.call_args.kwargs["output_config"]["format"]["schema"]
        self.assertEqual(schema["properties"]["screen"]["enum"], ["children"])


class AttendancePhotoTests(AIFixtures):
    def setUp(self):
        super().setUp()
        branch = Branch.objects.create(organization=self.org, name="Центр")
        group = Group.objects.create(
            organization=self.org,
            branch=branch,
            direction=self.ballet,
            name="Балет 5–7",
            capacity=12,
        )
        self.teacher, self.teacher_client = as_user(User.Role.TEACHER, self.org, "77010000041")
        self.kids = []
        for name in ("Бекова Алия", "Абаева Дана", "Ким Ева"):
            child = Child.objects.create(
                organization=self.org,
                full_name=name,
                birth_date=datetime.date(2019, 1, 1),
                gender="female",
            )
            GroupMembership.objects.create(
                organization=self.org, group=group, child=child, joined_at=datetime.date.today()
            )
            self.kids.append(child)
        start = timezone.now()
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=group,
            teacher=self.teacher,
            starts_at=start,
            ends_at=start + datetime.timedelta(hours=1),
        )

    def upload(self, client, content_type="image/jpeg"):
        image = SimpleUploadedFile("journal.jpg", b"\xff\xd8fakejpeg", content_type=content_type)
        return client.post(
            "/api/v1/ai/attendance-photo/", {"lesson": str(self.lesson.id), "image": image}
        )

    def test_marks_mapped_by_roster_order(self):
        # Список уходит в модель по алфавиту: 1 Абаева, 2 Бекова, 3 Ким.
        answer = {
            "marks": [{"number": 1, "status": "present"}, {"number": 2, "status": "absent"}],
            "note": "",
        }
        patch, create = patched_client(fake_response(answer))
        with patch:
            response = self.upload(self.teacher_client)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [(m["full_name"], m["status"]) for m in response.data["marks"]],
            [("Абаева Дана", "present"), ("Бекова Алия", "absent"), ("Ким Ева", "unknown")],
        )
        content = create.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertIn("1. Абаева Дана", content[1]["text"])

    def test_other_teacher_forbidden(self):
        _, other = as_user(User.Role.TEACHER, self.org, "77010000042")
        self.assertEqual(self.upload(other).status_code, 403)

    def test_not_an_image(self):
        patch, _ = patched_client(fake_response({"marks": [], "note": ""}))
        with patch:
            response = self.upload(self.teacher_client, content_type="application/pdf")
        self.assertEqual(response.status_code, 400)


class ImportCleanTests(AIFixtures):
    CSV = "Ученик;Контакты\nИванова Алия 12.03.2019;мама Айгерим 8 707 111 22 33\nИтого;1\n"

    def upload(self, text):
        file = SimpleUploadedFile("kids.csv", text.encode("utf-8"), content_type="text/csv")
        return self.client_api.post("/api/v1/ai/import-clean/", {"file": file})

    def test_clean_file_in_template_format(self):
        answer = {
            "rows": [
                {
                    "row": 2,
                    "child_name": "Иванова Алия",
                    "birth_date": "12.03.2019",
                    "gender": "Ж",
                    "parent_name": "Айгерим",
                    "phone": "8 707 111 22 33",
                    "role": "мама",
                    "medical_notes": "",
                    "reported_balance": "",
                    "direction": "",
                    "group": "",
                    "problem": "пол определён по имени",
                }
            ]
        }
        patch, create = patched_client(fake_response(answer))
        with patch:
            response = self.upload(self.CSV)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["source_rows"], response.data["problems"]), (2, 1))
        sheet = openpyxl.load_workbook(io.BytesIO(base64.b64decode(response.data["file"]))).active
        rows = list(sheet.iter_rows(values_only=True))
        self.assertEqual(
            rows[0][:5],
            (
                "ФИО ребёнка",
                "Дата рождения ребёнка",
                "Пол ребёнка",
                "ФИО родителя",
                "Телефон родителя",
            ),
        )
        self.assertEqual(
            rows[1][:5], ("Иванова Алия", "12.03.2019", "Ж", "Айгерим", "8 707 111 22 33")
        )
        sent = json.loads(create.call_args.kwargs["messages"][0]["content"].split("Строки: ", 1)[1])
        self.assertEqual(
            sent[0]["cells"], ["Иванова Алия 12.03.2019", "мама Айгерим 8 707 111 22 33"]
        )

    def test_too_many_rows(self):
        text = "Ученик\n" + "".join(f"Ребёнок {i}\n" for i in range(services.IMPORT_MAX_ROWS + 1))
        self.assertEqual(self.upload(text).status_code, 400)

    def test_teacher_forbidden(self):
        _, teacher_client = as_user(User.Role.TEACHER, self.org, "77010000051")
        file = SimpleUploadedFile("kids.csv", self.CSV.encode(), content_type="text/csv")
        self.assertEqual(
            teacher_client.post("/api/v1/ai/import-clean/", {"file": file}).status_code, 403
        )


@override_settings(ANTHROPIC_API_KEY="")
class DisabledTests(AIFixtures):
    def test_all_tools_off_without_key(self):
        response = self.client_api.post("/api/v1/ai/search/", {"query": "должники"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("не настроен", response.data["detail"])
