"""Первое сообщение в WhatsApp с незнакомого номера — сразу заявка в «Заявках»."""

from domains.platform.leads.models import Lead, LeadStatusChange
from domains.platform.users.models import User

from .tests_whatsapp_evolution import EvolutionBase

STRANGER = "77015556677@s.whatsapp.net"


class FirstMessageBecomesLeadTests(EvolutionBase):
    def leads(self, user=None):
        if user:
            self.api.force_authenticate(user)
        data = self.api.get("/api/v1/leads/").data
        return data["results"] if isinstance(data, dict) else data

    def test_first_message_creates_lead_seen_in_leads_list(self):
        connection = self.number(self.orbita)
        self.upsert(connection, jid=STRANGER, push_name="Динара", text="Сколько стоит балет?")
        lead = Lead.objects.get(phone="+77015556677")
        self.assertEqual((lead.status, lead.kind), (Lead.Status.NEW, "new"))
        self.assertEqual(lead.source.name, "WhatsApp")
        self.assertEqual(lead.branch, self.orbita)
        self.assertIsNotNone(lead.status_changed_at)
        self.assertTrue(
            LeadStatusChange.objects.filter(lead=lead, to_status=Lead.Status.NEW).exists()
        )
        self.assertIn(str(lead.id), [str(row["id"]) for row in self.leads()])

    def test_branch_admin_sees_lead_of_own_branch_number(self):
        connection = self.number(self.orbita)
        admin = User.objects.create_user(
            phone="77009990041",
            password="password",
            full_name="Админ Орбиты",
            organization=self.organization,
            role=User.Role.ADMIN,
        )
        admin.branches.add(self.orbita)
        self.upsert(connection, jid=STRANGER, push_name="Динара")
        lead = Lead.objects.get(phone="+77015556677")
        self.assertIn(str(lead.id), [str(row["id"]) for row in self.leads(admin)])

    def test_next_messages_go_to_same_lead(self):
        connection = self.number()
        self.upsert(connection, jid=STRANGER, push_name="Динара", message_id="first")
        self.upsert(connection, jid=STRANGER, push_name="Динара", message_id="second")
        self.assertEqual(Lead.objects.filter(phone="+77015556677").count(), 1)

    def test_known_parent_does_not_become_lead(self):
        connection = self.number()
        self.upsert(connection, text="Здравствуйте")
        self.assertFalse(Lead.objects.exists())

    def test_deleted_parent_number_becomes_lead_again(self):
        from domains.people.clients.models import ChildContact

        connection = self.number()
        ChildContact.objects.all().delete()
        self.parent.delete()
        self.upsert(connection, push_name="Мария", text="Здравствуйте")
        lead = Lead.objects.get(phone="+77001234567")
        self.assertEqual(lead.source.name, "WhatsApp")
