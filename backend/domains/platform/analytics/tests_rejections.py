"""Отчёт по причинам отказов (TRU-117)."""

import io

import openpyxl

from domains.platform.leads.models import LeadRejectionReason, LeadStatusChange

from .tests_funnel import FunnelFixtures, S

URL = "/api/v1/analytics/rejections/"


class RejectionsTests(FunnelFixtures):
    def setUp(self):
        super().setUp()
        reasons = LeadRejectionReason.objects.filter(organization=self.org)
        self.expensive = reasons.get(kind="new", name="Дорого")
        self.far = reasons.get(kind="new", name="Далеко")
        self.no_show = reasons.get(kind="new", name="Не пришёл на пробное")
        self.renewal_reason = reasons.get(kind="renewal", name="Переезд")

    def reject(self, *path, reason, comment="", **kwargs):
        lead = self.lead(*path, S.REJECTED, **kwargs)
        LeadStatusChange.objects.filter(lead=lead, to_status=S.REJECTED).update(
            rejection_reason=reason, comment=comment
        )
        return lead

    def test_new_org_marks_no_show_as_lost_contact(self):
        self.assertTrue(self.no_show.is_lost_contact)
        self.assertFalse(self.expensive.is_lost_contact)

    def test_reasons_stages_and_lost_contact_apart(self):
        self.reject(S.NEW, S.CONTACTED, reason=self.expensive)
        self.reject(S.NEW, S.CONTACTED, S.TRIAL_SCHEDULED, S.TRIAL_ATTENDED, reason=self.expensive)
        self.reject(S.NEW, reason=self.far)
        self.reject(S.NEW, S.CONTACTED, S.TRIAL_SCHEDULED, reason=self.no_show)
        data = self.client.get(URL).data["summary"]
        self.assertEqual((data["total"], data["real"], data["lost_contact"]), (4, 3, 1))
        reasons = {r["label"]: r for r in data["reasons"]}
        self.assertNotIn("Не пришёл на пробное", reasons)
        self.assertEqual(reasons["Дорого"]["value"], 2)
        self.assertEqual(reasons["Дорого"]["share"], 66.7)
        self.assertEqual(
            reasons["Дорого"]["stages"],
            {"before_contact": 0, "after_contact": 1, "trial_booked": 0, "after_trial": 1},
        )
        self.assertEqual(reasons["Далеко"]["stages"]["before_contact"], 1)
        self.assertEqual(
            [r["label"] for r in data["lost_contact_reasons"]], ["Не пришёл на пробное"]
        )

    def test_renewals_counted_separately(self):
        self.reject(S.NEW, reason=self.expensive)
        self.reject(S.NEW, S.CONTACTED, reason=self.renewal_reason, kind="renewal")
        self.assertEqual(self.client.get(URL).data["summary"]["total"], 1)
        renewals = self.client.get(URL, {"kind": "renewal"}).data["summary"]
        self.assertEqual([r["label"] for r in renewals["reasons"]], ["Переезд"])
        self.assertEqual(self.client.get(URL, {"kind": "other"}).status_code, 400)

    def test_comments_list_and_by_source(self):
        self.reject(
            S.NEW,
            S.CONTACTED,
            reason=self.expensive,
            comment="Дорого для двоих",
            source=self.instagram,
        )
        self.reject(S.NEW, reason=self.far, source=self.instagram)
        self.reject(S.NEW, reason=self.far)
        data = self.client.get(URL).data
        self.assertEqual([c["comment"] for c in data["comments"]], ["Дорого для двоих"])
        self.assertEqual(data["comments"][0]["stage"], "После звонка")
        items = self.client.get(f"{URL}by/", {"by": "source"}).data["items"]
        self.assertEqual(items[0]["label"], "Instagram")
        self.assertEqual((items[0]["value"], items[0]["top_share"]), (2, 50.0))
        # Отказы без источника и без причины тоже видны, а не теряются.
        self.assertEqual(items[1]["label"], None)

    def test_manager_sees_own_branch_and_export(self):
        self.reject(S.NEW, reason=self.far)
        self.reject(S.NEW, reason=self.far, branch=self.saina)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.get(URL).data["summary"]["total"], 1)
        self.client.force_authenticate(self.owner)
        response = self.client.get("/api/v1/analytics/export/", {"report": "rejections"})
        book = openpyxl.load_workbook(io.BytesIO(response.content))
        self.assertEqual(
            book.sheetnames,
            ["Причины", "Потеря контакта", "По месяцам", "По источникам", "Комментарии"],
        )
