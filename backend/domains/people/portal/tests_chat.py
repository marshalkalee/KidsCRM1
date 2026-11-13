"""Чат с центром в кабинете родителя — та же переписка, что WhatsApp."""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.platform.notifications.models import (
    InboundWhatsAppMessage,
    OutboundMessage,
    WhatsAppConnection,
)
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .auth import issue_password, login

PHONE = "+77001234567"


class PortalChatTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="portal-chat")
        self.parent = ParentContact.objects.create(organization=self.org, full_name="Исаева Мария")
        ContactPhone.objects.create(organization=self.org, parent_contact=self.parent, number=PHONE)
        self.child = Child.objects.create(
            organization=self.org, full_name="Милана Исаева", birth_date=date(2017, 1, 1)
        )
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        self.owner = User.objects.create_user(
            phone="77009990061",
            password="password",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        WhatsAppConnection.objects.create(
            organization=self.org,
            mode=WhatsAppConnection.Mode.EVOLUTION,
            status=WhatsAppConnection.Status.CONNECTED,
            business_phone="+77070000000",
        )
        password = issue_password(PHONE)
        token = login(PHONE, password, {"ip": "127.0.0.1", "user_agent": "test"})["token"]
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Parent {token}")
        self.url = f"/api/v1/portal/children/{self.child.id}/chat/"

    def test_parent_writes_from_cabinet_and_center_sees_it_in_crm(self):
        response = self.api.post(self.url, {"text": "Можно перенести занятие?"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["results"][0]["direction"], "me")
        message = InboundWhatsAppMessage.objects.get()
        self.assertEqual((message.parent, message.message_type), (self.parent, "portal"))
        staff = APIClient()
        staff.force_authenticate(self.owner)
        row = staff.get("/api/v1/messaging/whatsapp/thread/", {"parent": str(self.parent.id)}).data[
            "results"
        ][0]
        self.assertEqual((row["text"], row["source"]), ("Можно перенести занятие?", "portal"))

    def test_center_reply_is_seen_in_cabinet(self):
        OutboundMessage.objects.create(
            organization=self.org,
            parent=self.parent,
            event="whatsapp_manual",
            category="utility",
            dedup_key="reply-1",
            channel="whatsapp",
            recipient=PHONE,
            body="Да, конечно",
            status=OutboundMessage.Status.READ,
        )
        rows = self.api.get(self.url).data["results"]
        self.assertEqual([(r["direction"], r["text"]) for r in rows], [("center", "Да, конечно")])

    def test_other_family_chat_is_not_visible(self):
        stranger = Child.objects.create(
            organization=self.org, full_name="Чужой", birth_date=date(2017, 1, 1)
        )
        response = self.api.get(f"/api/v1/portal/children/{stranger.id}/chat/")
        self.assertEqual(response.status_code, 404)

    def delete(self, row, for_everyone=False):
        direction = "in" if row["direction"] == "me" else "out"
        return self.api.post(
            f"{self.url}messages/{direction}/{row['id']}/delete/",
            {"for_everyone": for_everyone},
            format="json",
        )

    def crm_thread(self):
        staff = APIClient()
        staff.force_authenticate(self.owner)
        return staff.get(
            "/api/v1/messaging/whatsapp/thread/", {"parent": str(self.parent.id)}
        ).data["results"]

    def test_parent_deletes_own_cabinet_message_for_everyone(self):
        mine = self.api.post(self.url, {"text": "Ой, не туда"}, format="json").data["results"][0]
        self.assertTrue(mine["can_revoke"])
        response = self.delete(mine, for_everyone=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["results"][0]["revoked"])
        self.assertTrue(self.crm_thread()[0]["revoked"])

    def test_delete_for_me_hides_only_in_cabinet(self):
        OutboundMessage.objects.create(
            organization=self.org,
            parent=self.parent,
            event="whatsapp_manual",
            category="utility",
            dedup_key="reply-2",
            channel="whatsapp",
            recipient=PHONE,
            body="Ответ центра",
            status=OutboundMessage.Status.READ,
        )
        center = self.api.get(self.url).data["results"][0]
        response = self.delete(center)
        self.assertEqual(response.data["results"], [])
        # В CRM сообщение осталось.
        self.assertEqual(self.crm_thread()[0]["text"], "Ответ центра")

    def test_center_message_cannot_be_deleted_for_everyone_by_parent(self):
        OutboundMessage.objects.create(
            organization=self.org,
            parent=self.parent,
            event="whatsapp_manual",
            category="utility",
            dedup_key="reply-3",
            channel="whatsapp",
            recipient=PHONE,
            body="Ответ центра",
            status=OutboundMessage.Status.READ,
        )
        center = self.api.get(self.url).data["results"][0]
        self.assertEqual(self.delete(center, for_everyone=True).status_code, 400)

    def test_empty_message_rejected(self):
        self.assertEqual(self.api.post(self.url, {"text": "  "}, format="json").status_code, 400)


MEDIA_TMP = __import__("tempfile").mkdtemp(prefix="kidscrm-portal-chat-")


@__import__("django.test", fromlist=["override_settings"]).override_settings(MEDIA_ROOT=MEDIA_TMP)
class PortalChatFilesTests(PortalChatTests):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        __import__("shutil").rmtree(MEDIA_TMP, ignore_errors=True)

    def upload(self, name, content, content_type, text=""):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.api.post(
            self.url,
            {"text": text, "file": SimpleUploadedFile(name, content, content_type=content_type)},
            format="multipart",
        )

    def test_voice_from_cabinet_plays_in_crm(self):
        response = self.upload("голосовое.webm", b"webm", "audio/webm")
        self.assertEqual(response.status_code, 201, response.data)
        mine = response.data["results"][0]
        self.assertEqual(mine["media"]["kind"], "audio")
        own = self.api.get(f"/api/v1/portal/{mine['media']['url']}")
        self.assertEqual(b"".join(own.streaming_content), b"webm")
        staff = APIClient()
        staff.force_authenticate(self.owner)
        row = staff.get("/api/v1/messaging/whatsapp/thread/", {"parent": str(self.parent.id)}).data[
            "results"
        ][0]
        self.assertEqual((row["media"]["kind"], row["source"]), ("audio", "portal"))

    def test_photo_with_caption(self):
        response = self.upload("чек.jpg", b"jpeg", "image/jpeg", text="Оплатила")
        mine = response.data["results"][0]
        self.assertEqual((mine["text"], mine["media"]["kind"]), ("Оплатила", "image"))

    def test_executable_rejected(self):
        response = self.upload("x.exe", b"MZ", "application/octet-stream")
        self.assertEqual(response.status_code, 400)
