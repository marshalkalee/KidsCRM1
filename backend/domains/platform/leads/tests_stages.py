"""TRU-154: этапы воронки центра поверх системных ролей."""

import io

import openpyxl

from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .models import Lead, LeadStage, LeadStatusChange
from .services import LeadTransitionError, change_status, move_to_stage
from .stages import DEFAULT_STAGES
from .tests import URL, LeadFixtures, make_client

STAGES_URL = f"{URL}stages/"
BOARD_URL = f"{URL}board/"


class StageFixtures(LeadFixtures):
    def stage(self, role):
        return LeadStage.objects.get(organization=self.org, role=role, is_system=True)

    def add_stage(self, name="Тестирование уровня", role=Lead.Status.CONTACTED, **extra):
        response = self.client_owner.post(
            STAGES_URL, {"name": name, "role": role, **extra}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        return LeadStage.objects.get(pk=response.data["id"])

    def to_stage(self, lead, stage, client=None, **extra):
        return (client or self.client_owner).post(
            f"{URL}{lead.id}/status/", {"stage": str(stage.id), **extra}, format="json"
        )

    def board(self, **params):
        return self.client_owner.get(BOARD_URL, params).data

    def labels(self, **params):
        return [column["label"] for column in self.board(**params)["columns"]]


class DefaultStagesTests(StageFixtures):
    def test_new_org_gets_mvp_funnel_unchanged(self):
        stages = list(LeadStage.objects.filter(organization=self.org))
        self.assertEqual([(s.role, s.name) for s in stages], [(r, n) for r, n, _ in DEFAULT_STAGES])
        self.assertTrue(all(s.is_system for s in stages))
        self.assertEqual(self.labels(), [n for _, n, _ in DEFAULT_STAGES])
        board = self.board()
        self.assertEqual([c["status"] for c in board["columns"]], [r for r, _, _ in DEFAULT_STAGES])
        # Старый формат переходов по ролям — на месте.
        self.assertIn("contacted", board["transitions"]["new"])

    def test_renewal_board_keeps_its_order(self):
        self.assertEqual(
            [c["status"] for c in self.board(kind="renewal")["columns"]],
            Lead.RENEWAL_STATUSES,
        )

    def test_stage_counts_include_leads_on_main_stage(self):
        self.make_lead()
        testing = self.add_stage()
        move_to_stage(self.make_lead(phone="+77072223344"), stage=testing, actor=self.owner)
        counts = {s["name"]: s["lead_count"] for s in self.client_owner.get(STAGES_URL).data}
        self.assertEqual((counts["Новая"], counts["Тестирование уровня"]), (1, 1))
        self.assertEqual(counts["Связались"], 0)

    def test_lead_without_stage_shows_system_stage(self):
        lead = self.make_lead()
        data = self.client_owner.get(f"{URL}{lead.id}/").data
        self.assertEqual(data["stage"], str(self.stage("new").id))
        self.assertEqual((data["stage_name"], data["stage_color"]), ("Новая", "blue"))


class RenameTests(StageFixtures):
    def test_rename_shows_everywhere(self):
        lead = self.make_lead(child_name="Алия")
        contacted = self.stage("contacted")
        self.client_owner.patch(
            f"{STAGES_URL}{contacted.id}/", {"name": "Дозвонились"}, format="json"
        )
        self.assertEqual(self.move(lead, "contacted").status_code, 200)

        self.assertIn("Дозвонились", self.labels())
        data = self.client_owner.get(f"{URL}{lead.id}/").data
        self.assertEqual((data["status_label"], data["stage_name"]), ("Дозвонились",) * 2)
        history = self.client_owner.get(f"{URL}{lead.id}/history/").data
        self.assertEqual(history[-1]["to_status_label"], "Дозвонились")
        # Переименовали ещё раз — история читается новым названием (ссылка, не текст).
        self.client_owner.patch(f"{STAGES_URL}{contacted.id}/", {"name": "На связи"}, format="json")
        history = self.client_owner.get(f"{URL}{lead.id}/history/").data
        self.assertEqual(history[-1]["to_status_label"], "На связи")

        workbook = openpyxl.load_workbook(
            io.BytesIO(self.client_owner.get(f"{URL}export/").content)
        )
        self.assertIn("На связи", [cell.value for cell in workbook.active[2]])

        funnel = self.client_owner.get("/api/v1/analytics/funnel/").data["funnel"]
        stages = {stage["key"]: stage for stage in funnel["stages"]}
        self.assertEqual(stages["contacted"]["label"], "На связи")
        self.assertEqual(stages["contacted"]["count"], 1)

    def test_duplicate_or_empty_name_rejected(self):
        contacted = self.stage("contacted")
        for name in ("Новая", "  "):
            response = self.client_owner.patch(
                f"{STAGES_URL}{contacted.id}/", {"name": name}, format="json"
            )
            self.assertEqual(response.status_code, 400)


class CustomStageTests(StageFixtures):
    def test_custom_stage_in_middle_of_funnel(self):
        testing = self.add_stage()
        ids = [str(s.id) for s in LeadStage.objects.filter(organization=self.org)]
        ids.remove(str(testing.id))
        ids.insert(2, str(testing.id))  # после «Связались»
        response = self.client_owner.post(f"{STAGES_URL}reorder/", {"ids": ids}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            self.labels()[:4], ["Новая", "Связались", "Тестирование уровня", "Записан на пробное"]
        )

        lead = self.make_lead()
        response = self.to_stage(lead, testing)
        self.assertEqual(response.status_code, 200, response.data)
        lead.refresh_from_db()
        self.assertEqual((lead.status, lead.stage), ("contacted", testing))
        self.assertEqual(response.data["stage_name"], "Тестирование уровня")
        column = next(c for c in self.board()["columns"] if c["stage"] == str(testing.id))
        self.assertEqual([r["id"] for r in column["results"]], [str(lead.id)])
        contacted_column = next(c for c in self.board()["columns"] if c["label"] == "Связались")
        self.assertEqual(contacted_column["count"], 0)
        # Фильтр таблицы по этапу.
        listed = self.client_owner.get(URL, {"stage": str(testing.id)}).data["results"]
        self.assertEqual([row["id"] for row in listed], [str(lead.id)])

        # Дальше по воронке — по правилам роли.
        self.assertEqual(self.to_stage(lead, self.stage("trial_scheduled")).status_code, 200)
        lead.refresh_from_db()
        self.assertEqual((lead.status, lead.stage), ("trial_scheduled", None))

    def test_move_within_role_is_stage_change_not_conversion(self):
        testing = self.add_stage()
        lead = self.make_lead()
        self.move(lead, "contacted")
        response = self.to_stage(lead, testing)
        self.assertEqual(response.status_code, 200, response.data)
        last = lead.status_changes.order_by("changed_at").last()
        self.assertEqual(last.event_type, LeadStatusChange.EventType.STAGE_CHANGE)
        self.assertEqual((last.from_status, last.to_status), ("contacted", "contacted"))
        # Обратно на основной этап — тоже смена этапа; история читается по этапам.
        self.assertEqual(self.to_stage(lead, self.stage("contacted")).status_code, 200)
        history = self.client_owner.get(f"{URL}{lead.id}/history/").data
        self.assertEqual(
            [(h["from_status_label"], h["to_status_label"]) for h in history[-2:]],
            [("Связались", "Тестирование уровня"), ("Тестирование уровня", "Связались")],
        )
        self.assertEqual(self.to_stage(lead, self.stage("contacted")).status_code, 400)
        funnel = self.client_owner.get("/api/v1/analytics/funnel/").data["funnel"]
        counts = {stage["key"]: stage["count"] for stage in funnel["stages"]}
        self.assertEqual((counts["new"], counts["contacted"]), (1, 1))

    def test_transition_rules_follow_roles(self):
        testing = self.add_stage()
        lead = self.make_lead()
        # «Новая» → «Купил» запрещено ролью, как и раньше.
        response = self.to_stage(lead, self.stage("purchased"))
        self.assertEqual(response.status_code, 400)
        board = self.board()
        new_id = str(self.stage("new").id)
        self.assertIn(str(testing.id), board["stage_transitions"][new_id])
        self.assertNotIn(str(self.stage("purchased").id), board["stage_transitions"][new_id])
        data = self.client_owner.get(f"{URL}{lead.id}/").data
        self.assertIn(str(testing.id), data["allowed_stages"])

    def test_rejection_still_needs_reason(self):
        lead = self.make_lead()
        rejected = self.stage("rejected")
        self.assertEqual(self.to_stage(lead, rejected).status_code, 400)
        response = self.to_stage(lead, rejected, rejection_reason=str(self.expensive.id))
        self.assertEqual(response.status_code, 200, response.data)

    def test_custom_stage_only_inside_work_roles(self):
        for role in (Lead.Status.PURCHASED, Lead.Status.REJECTED):
            response = self.client_owner.post(
                STAGES_URL, {"name": f"Свой {role}", "role": role}, format="json"
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("role", response.data)

    def test_system_stage_cannot_be_hidden_or_change_role(self):
        new = self.stage("new")
        url = f"{STAGES_URL}{new.id}/"
        self.assertEqual(
            self.client_owner.patch(url, {"is_hidden": True}, format="json").status_code, 400
        )
        self.assertEqual(
            self.client_owner.patch(url, {"role": "contacted"}, format="json").status_code, 400
        )
        self.assertEqual(self.client_owner.delete(url).status_code, 400)
        # Каждую роль по-прежнему несёт ровно один системный этап.
        self.assertEqual(LeadStage.objects.filter(organization=self.org, is_system=True).count(), 7)

    def test_hide_moves_leads_to_system_stage_and_delete_only_unused(self):
        testing = self.add_stage()
        lead = self.make_lead()
        self.to_stage(lead, testing)
        url = f"{STAGES_URL}{testing.id}/"
        self.assertEqual(self.client_owner.delete(url).status_code, 400)
        self.assertEqual(
            self.client_owner.patch(url, {"is_hidden": True}, format="json").status_code, 200
        )
        lead.refresh_from_db()
        self.assertEqual((lead.status, lead.stage), ("contacted", None))
        self.assertNotIn("Тестирование уровня", self.labels())
        self.assertEqual(self.to_stage(lead, testing).status_code, 400)
        # Был в истории — удалить нельзя, только скрыть.
        self.assertEqual(self.client_owner.delete(url).status_code, 400)
        unused = self.add_stage(name="Ждёт набора группы", role=Lead.Status.THINKING)
        self.assertEqual(self.client_owner.delete(f"{STAGES_URL}{unused.id}/").status_code, 204)

    def test_reorder_needs_all_stages(self):
        ids = [str(s.id) for s in LeadStage.objects.filter(organization=self.org)][:3]
        response = self.client_owner.post(f"{STAGES_URL}reorder/", {"ids": ids}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_services_keep_custom_stage_consistent(self):
        """Пути, которые меняют статус сами (пробные, продажа, сайт), ставят
        заявку на системный этап новой роли — свой этап не «залипает»."""
        testing = self.add_stage()
        lead = self.make_lead()
        move_to_stage(lead, stage=testing, actor=self.owner)
        change_status(lead, to_status=Lead.Status.TRIAL_SCHEDULED, actor=None, is_automatic=True)
        lead.refresh_from_db()
        self.assertIsNone(lead.stage)
        with self.assertRaises(LeadTransitionError):
            change_status(lead, to_status=Lead.Status.THINKING, actor=self.owner, to_stage=testing)


class StagePermissionTests(StageFixtures):
    def test_admin_reads_and_uses_but_does_not_configure(self):
        admin = make_client(self.admin)
        self.assertEqual(admin.get(STAGES_URL).status_code, 200)
        self.assertEqual(
            admin.post(STAGES_URL, {"name": "X", "role": "contacted"}, format="json").status_code,
            403,
        )
        testing = self.add_stage()
        lead = self.make_lead()
        self.assertEqual(self.to_stage(lead, testing, client=admin).status_code, 200)

    def test_other_org_stage_is_not_found(self):
        other = Organization.objects.create(name="Другой", slug="other")
        foreign = LeadStage.objects.get(organization=other, role="contacted", is_system=True)
        lead = self.make_lead()
        response = self.to_stage(lead, foreign)
        self.assertEqual(response.status_code, 400)
        self.assertIn("stage", response.data)
        stranger = make_client(self.make_user("77019999999", User.Role.OWNER, organization=other))
        self.assertEqual(
            stranger.patch(
                f"{STAGES_URL}{self.stage('new').id}/", {"name": "X"}, format="json"
            ).status_code,
            404,
        )
