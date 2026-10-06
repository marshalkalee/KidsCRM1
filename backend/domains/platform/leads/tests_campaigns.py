"""TRU-165: публикации и кампании — с какого ролика пришла заявка."""

from urllib.parse import unquote

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from domains.platform.ai import services as ai_services
from domains.platform.ai.tests import fake_response, patched_client
from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User

from .campaigns import find_campaign
from .models import Lead, LeadCampaign, LeadSource
from .services import change_status
from .tests import URL, LeadFixtures, make_client

CAMPAIGNS = f"{URL}campaigns/"


class CampaignFixtures(LeadFixtures):
    def setUp(self):
        super().setUp()
        self.org.website_domain = "https://trueballet.kz"
        self.org.save(update_fields=["website_domain"])
        Branch.objects.filter(pk=self.branch.pk).update(phone="+77272001122")
        self.whatsapp = LeadSource.objects.get(organization=self.org, name="WhatsApp")

    def add(self, name="Reel про пробное", source=None):
        response = self.client_owner.post(
            CAMPAIGNS, {"name": name, "source": str((source or self.instagram).id)}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data


class CampaignDictionaryTests(CampaignFixtures):
    def test_codes_and_links(self):
        first, second = self.add(), self.add("Reel про гимнастику")
        self.assertEqual((first["code"], second["code"]), ("K1", "K2"))
        link = first["whatsapp_links"][0]
        self.assertEqual(link["branch"], "Центр")
        self.assertTrue(link["url"].startswith("https://wa.me/77272001122?text="))
        self.assertIn("(код K1)", unquote(link["url"]))
        self.assertEqual(
            first["site_link"], "https://trueballet.kz/?utm_source=instagram&utm_content=K1"
        )
        self.assertEqual(first["source_name"], "Instagram")

    def test_code_is_not_editable_and_not_reused(self):
        data = self.add()
        self.client_owner.patch(f"{CAMPAIGNS}{data['id']}/", {"code": "K99"}, format="json")
        self.assertEqual(LeadCampaign.objects.get(pk=data["id"]).code, "K1")
        self.client_owner.patch(f"{CAMPAIGNS}{data['id']}/", {"is_active": False}, format="json")
        self.assertEqual(self.add("Новый ролик")["code"], "K2")

    def test_filter_by_source_and_usage(self):
        reel = self.add()
        self.add("Пост в WhatsApp-статусе", source=self.whatsapp)
        rows = self.client_owner.get(CAMPAIGNS, {"source": str(self.instagram.id)}).data
        self.assertEqual([r["id"] for r in rows], [reel["id"]])
        self.make_lead(campaign_id=reel["id"])
        rows = self.client_owner.get(CAMPAIGNS, {"source": str(self.instagram.id)}).data
        self.assertEqual(rows[0]["usage_count"], 1)

    def test_admin_reads_owner_manages(self):
        admin = make_client(self.admin)
        self.assertEqual(admin.get(CAMPAIGNS).status_code, 200)
        response = admin.post(
            CAMPAIGNS, {"name": "X", "source": str(self.instagram.id)}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_other_org_is_isolated(self):
        reel = self.add()
        other = Organization.objects.create(name="Другой", slug="other")
        stranger = make_client(self.make_user("77019999999", User.Role.OWNER, organization=other))
        self.assertEqual(stranger.get(CAMPAIGNS).data, [])
        response = stranger.post(
            URL, {"parent_name": "А", "phone": "87071112233", "campaign": reel["id"]}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("campaign", response.data)


class LeadCampaignTests(CampaignFixtures):
    def test_campaign_fills_source(self):
        reel = self.add()
        response = self.client_owner.post(
            URL,
            {"parent_name": "Айгерим", "phone": "87071112233", "campaign": reel["id"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["source_name"], "Instagram")
        self.assertEqual(response.data["campaign_name"], "Reel про пробное")

    def test_campaign_from_other_source_is_an_error(self):
        reel = self.add()
        response = self.client_owner.post(
            URL,
            {
                "parent_name": "Айгерим",
                "phone": "87071112233",
                "source": str(self.whatsapp.id),
                "campaign": reel["id"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("campaign", response.data)

    def test_list_filter_by_campaign(self):
        reel = self.add()
        lead = self.make_lead(campaign_id=reel["id"], source=self.instagram)
        self.make_lead(phone="+77072223344")
        rows = self.client_owner.get(URL, {"campaign": reel["id"]}).data["results"]
        self.assertEqual([r["id"] for r in rows], [str(lead.id)])

    def test_find_code_in_text(self):
        reel = LeadCampaign.objects.get(pk=self.add()["id"])
        for text in ("Хочу на пробное (код K1)", "код к1", "К-1 пожалуйста", "k1"):
            with self.subTest(text=text):
                self.assertEqual(find_campaign(self.org, text), reel)
        self.assertIsNone(find_campaign(self.org, "квартира K12, корпус 3"))
        LeadCampaign.objects.filter(pk=reel.pk).update(is_active=False)
        self.assertIsNone(find_campaign(self.org, "код K1"))

    @override_settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="test-key", OPENAI_API_KEY="")
    def test_lead_from_text_picks_campaign_by_code(self):
        reel = self.add()
        payload = {
            "parent_name": "Айгерим",
            "phone": "8 707 111 22 33",
            "child_name": "",
            "child_age": 0,
            "direction": "",
            "source": "WhatsApp",
            "summary": "",
        }
        patch, _ = patched_client(fake_response(payload))
        with patch:
            fields = ai_services.lead_from_text(
                self.org, "Здравствуйте! Хочу записаться на пробное занятие (код K1)"
            )
        self.assertEqual(fields["campaign"], reel["id"])
        # Код точнее догадки модели: источник — публикации, а не «WhatsApp».
        self.assertEqual(fields["source"], str(self.instagram.id))


class CampaignAnalyticsTests(CampaignFixtures):
    def test_campaigns_in_sources_report(self):
        reel = self.add()
        bought = self.make_lead(campaign_id=reel["id"], source=self.instagram)
        self.make_lead(phone="+77072223344", campaign_id=reel["id"], source=self.instagram)
        self.make_lead(phone="+77073334455", source=self.instagram)
        change_status(bought, to_status="contacted", actor=self.owner)
        change_status(bought, to_status="purchased", actor=self.owner)
        data = self.client_owner.get("/api/v1/analytics/sources/").data
        self.assertEqual(len(data["campaigns"]), 1)
        row = data["campaigns"][0]
        self.assertEqual((row["label"], row["source"]), ("Reel про пробное · K1", "Instagram"))
        self.assertEqual((row["leads"], row["purchased"]), (2, 1))
        instagram = next(i for i in data["items"] if i["label"] == "Instagram")
        self.assertEqual(instagram["leads"], 3)


class PublicFormCampaignTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="True Ballet", slug="tb")
        self.instagram = LeadSource.objects.get(organization=self.org, name="Instagram")
        self.reel = LeadCampaign.objects.create(
            organization=self.org, source=self.instagram, name="Reel", code="K7"
        )
        self.client = APIClient()

    def post(self, **extra):
        return self.client.post(
            f"/api/v1/public/leads/{self.org.public_api_key}/",
            {"parent_name": "Гульнара", "phone": "87071234567", **extra},
            format="json",
        )

    def test_utm_content_sets_campaign_and_source(self):
        self.assertEqual(self.post(utm_content="K7").status_code, 201)
        lead = Lead.objects.get(organization=self.org)
        self.assertEqual((lead.campaign, lead.source), (self.reel, self.instagram))

    def test_unknown_code_falls_back_to_site(self):
        self.post(campaign="K99")
        lead = Lead.objects.get(organization=self.org)
        self.assertIsNone(lead.campaign)
        self.assertEqual(lead.source.name, "Сайт")
