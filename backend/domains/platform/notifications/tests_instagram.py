import datetime

from django.test import TestCase, tag
from rest_framework.test import APIClient

from domains.people.clients.models import Child, ChildContact, CommunicationLog, ParentContact
from domains.platform.leads.models import Lead, LeadComment
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .messaging.instagram import InstagramError, handle_webhook, looks_like_lead, send_reply
from .models import (
    InboundInstagramMessage,
    InstagramConnection,
    InstagramIdentity,
)


class InstagramMessagingTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="True Ballet", slug="instagram-test")
        self.owner = User.objects.create_user(
            phone="77009990173",
            password="password",
            full_name="Владелец",
            organization=self.organization,
            role=User.Role.OWNER,
        )
        self.connection = InstagramConnection.objects.create(
            organization=self.organization,
            mode=InstagramConnection.Mode.CONSOLE,
            status=InstagramConnection.Status.CONNECTED,
            instagram_account_id="ig-business-1",
        )
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def direct_payload(self, event_id="mid.1", text="Сколько стоит балет?"):
        return {
            "entry": [
                {
                    "id": "ig-business-1",
                    "messaging": [
                        {
                            "sender": {"id": "ig-user-1", "username": "mama"},
                            "timestamp": 1_780_000_000_000,
                            "message": {"mid": event_id, "text": text},
                        }
                    ],
                }
            ]
        }

    def comment_payload(self, text, event_id="comment.1"):
        return {
            "entry": [
                {
                    "id": "ig-business-1",
                    "changes": [
                        {
                            "field": "comments",
                            "value": {
                                "id": event_id,
                                "text": text,
                                "from": {"id": "ig-user-2", "username": "visitor"},
                                "media": {
                                    "id": "post-1",
                                    "permalink": "https://instagram.com/p/demo/",
                                },
                            },
                        }
                    ],
                }
            ]
        }

    def test_comment_filter_rejects_noise_and_accepts_questions(self):
        self.assertFalse(looks_like_lead("❤️❤️"))
        self.assertFalse(looks_like_lead("@friend"))
        self.assertTrue(looks_like_lead("Сколько стоит абонемент?"))
        self.assertTrue(looks_like_lead("Сенбіге топта орын бар ма?"))

    def test_direct_creates_instagram_direct_lead_idempotently(self):
        payload = self.direct_payload()
        self.assertEqual(handle_webhook(payload), 1)
        self.assertEqual(handle_webhook(payload), 0)
        message = InboundInstagramMessage.objects.get(organization=self.organization)
        self.assertEqual(message.status, InboundInstagramMessage.Status.LINKED)
        self.assertEqual(message.lead.source.name, "Instagram Direct")
        self.assertEqual(Lead.objects.filter(organization=self.organization).count(), 1)
        self.assertIn("Instagram Direct", LeadComment.objects.get(lead=message.lead).text)

    def test_noise_comment_is_kept_out_of_funnel_but_can_be_promoted(self):
        handle_webhook(self.comment_payload("❤️", "comment-heart"))
        message = InboundInstagramMessage.objects.get(provider_event_id="comment-heart")
        self.assertEqual(message.status, InboundInstagramMessage.Status.IGNORED)
        self.assertFalse(Lead.objects.filter(organization=self.organization).exists())
        response = self.api.post(
            f"/api/v1/messaging/instagram/inbox/{message.id}/promote/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertTrue(message.manually_promoted)
        self.assertEqual(message.lead.source.name, "Instagram комментарий")
        self.assertIn("instagram.com/p/demo", LeadComment.objects.get(lead=message.lead).text)

    def test_known_identity_goes_to_child_communication(self):
        parent = ParentContact.objects.create(
            organization=self.organization, full_name="Исаева Мария"
        )
        child = Child.objects.create(
            organization=self.organization,
            full_name="Исаева Милана",
            birth_date=datetime.date(2016, 1, 1),
        )
        ChildContact.objects.create(
            organization=self.organization,
            child=child,
            parent_contact=parent,
            role=ChildContact.Role.MOTHER,
        )
        InstagramIdentity.objects.create(
            organization=self.organization, scoped_user_id="ig-user-1", parent=parent
        )
        handle_webhook(self.direct_payload("known.1", "Перенесите, пожалуйста"))
        message = InboundInstagramMessage.objects.get(provider_event_id="known.1")
        self.assertEqual(message.child, child)
        self.assertEqual(message.communication_log.child, child)
        self.assertEqual(CommunicationLog.objects.filter(child=child).count(), 1)

    def test_public_reply_rejects_personal_data_but_direct_allows_text(self):
        handle_webhook(self.comment_payload("Сколько стоит?", "public.1"))
        comment = InboundInstagramMessage.objects.get(provider_event_id="public.1")
        with self.assertRaisesRegex(InstagramError, "личные данные"):
            send_reply(comment, "Позвоните +7 700 123 45 67")
        direct_payload = self.direct_payload("direct.reply", "Здравствуйте")
        handle_webhook(direct_payload)
        direct = InboundInstagramMessage.objects.get(provider_event_id="direct.reply")
        self.assertTrue(send_reply(direct, "Ответ в Direct").startswith("console-instagram-"))

    @tag("tenant_isolation")
    def test_other_organization_cannot_read_inbox(self):
        handle_webhook(self.direct_payload("isolated.1"))
        other = Organization.objects.create(name="Other", slug="other-instagram")
        other_owner = User.objects.create_user(
            phone="77009990174",
            password="password",
            full_name="Other",
            organization=other,
            role=User.Role.OWNER,
        )
        self.api.force_authenticate(other_owner)
        response = self.api.get("/api/v1/messaging/instagram/inbox/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])
