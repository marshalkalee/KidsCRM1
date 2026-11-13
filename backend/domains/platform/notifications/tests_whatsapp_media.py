"""Фото, голосовые и документы в чате WhatsApp — в обе стороны."""

import base64
import shutil
import tempfile
from unittest import mock

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .messaging import service
from .messaging.tasks import sync_evolution_states
from .messaging.whatsapp import handle_evolution_webhook
from .models import InboundWhatsAppMessage, OutboundMessage
from .tests_whatsapp_evolution import REQUEST, SLEEP, EvolutionBase

MEDIA_TMP = tempfile.mkdtemp(prefix="kidscrm-wa-media-")


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class MediaTests(EvolutionBase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TMP, ignore_errors=True)

    def webhook(self, connection, data):
        with mock.patch(
            "domains.platform.notifications.messaging.tasks.process_evolution_webhook.delay"
        ) as delay:
            APIClient().post(
                f"/api/v1/messaging/whatsapp/evolution/{connection.webhook_secret}/",
                {"event": "messages.upsert", "data": data},
                format="json",
            )
        handle_evolution_webhook(*delay.call_args.args)

    def test_incoming_photo_is_saved_and_shown_in_chat(self):
        connection = self.number()
        self.webhook(
            connection,
            {
                "key": {"remoteJid": "77001234567@s.whatsapp.net", "fromMe": False, "id": "IMG1"},
                "pushName": "Мария",
                "message": {
                    "imageMessage": {"mimetype": "image/jpeg", "caption": "Чек"},
                    "base64": base64.b64encode(b"jpeg-bytes").decode(),
                },
                "messageType": "imageMessage",
                "messageTimestamp": int(timezone.now().timestamp()),
            },
        )
        message = InboundWhatsAppMessage.objects.get()
        self.assertTrue(message.media_file.name.endswith(".jpg"))
        row = self.api.get(
            "/api/v1/messaging/whatsapp/thread/", {"parent": str(self.parent.id)}
        ).data["results"][0]
        self.assertEqual(row["text"], "Чек")
        self.assertEqual(row["media"]["kind"], "image")
        response = self.api.get(f"/api/v1/{row['media']['url']}")
        self.assertEqual(b"".join(response.streaming_content), b"jpeg-bytes")

    def test_voice_message_is_audio_in_chat(self):
        connection = self.number()
        self.webhook(
            connection,
            {
                "key": {"remoteJid": "77001234567@s.whatsapp.net", "fromMe": False, "id": "AUD1"},
                "message": {
                    "audioMessage": {"mimetype": "audio/ogg; codecs=opus", "ptt": True},
                    "base64": base64.b64encode(b"ogg").decode(),
                },
                "messageType": "audioMessage",
                "messageTimestamp": int(timezone.now().timestamp()),
            },
        )
        row = self.api.get(
            "/api/v1/messaging/whatsapp/thread/", {"parent": str(self.parent.id)}
        ).data["results"][0]
        self.assertEqual(row["media"]["kind"], "audio")
        self.assertEqual(row["text"], "")

    def test_video_and_round_video_note_play_in_chat(self):
        connection = self.number()
        now = int(timezone.now().timestamp())
        for message_id, kind in (("VID1", "videoMessage"), ("PTV1", "ptvMessage")):
            self.webhook(
                connection,
                {
                    "key": {
                        "remoteJid": "77001234567@s.whatsapp.net",
                        "fromMe": False,
                        "id": message_id,
                    },
                    "message": {
                        kind: {"mimetype": "video/mp4"},
                        "base64": base64.b64encode(b"mp4").decode(),
                    },
                    "messageType": kind,
                    "messageTimestamp": now,
                },
            )
        rows = self.api.get(
            "/api/v1/messaging/whatsapp/thread/", {"parent": str(self.parent.id)}
        ).data["results"]
        self.assertEqual(sorted(row["media"]["kind"] for row in rows), ["video", "video_note"])
        self.assertTrue(all(row["media"]["name"].endswith(".mp4") for row in rows))

    def test_media_of_ignored_message_is_not_kept(self):
        connection = self.number()
        self.webhook(
            connection,
            {
                "key": {"remoteJid": "120363@g.us", "fromMe": False, "id": "GRP1"},
                "message": {
                    "imageMessage": {"mimetype": "image/png"},
                    "base64": base64.b64encode(b"png").decode(),
                },
                "messageTimestamp": int(timezone.now().timestamp()),
            },
        )
        self.assertFalse(InboundWhatsAppMessage.objects.exists())
        folder = f"whatsapp/{self.organization.id}"
        dirs = default_storage.listdir(folder)[0] if default_storage.exists(folder) else []
        files = [f for d in dirs for f in default_storage.listdir(f"{folder}/{d}")[1]]
        self.assertEqual(files, [])

    def send_file(self, name, content, content_type, text=""):
        with mock.patch(
            "domains.platform.notifications.messaging.tasks.send_manual_whatsapp_task.delay"
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.api.post(
                    "/api/v1/messaging/whatsapp/send/",
                    {
                        "parent_id": str(self.parent.id),
                        "text": text,
                        "file": SimpleUploadedFile(name, content, content_type=content_type),
                    },
                    format="multipart",
                )
        self.assertEqual(response.status_code, 202, response.data)
        with mock.patch(REQUEST, return_value={"key": {"id": "3EB0FILE"}}) as request:
            with mock.patch(SLEEP):
                message = service.deliver_manual(response.data["id"])
        return message, request

    def test_photo_goes_as_media_with_caption(self):
        self.number()
        message, request = self.send_file("фото.jpg", b"jpeg", "image/jpeg", text="Расписание")
        self.assertEqual(message.status, OutboundMessage.Status.SENT)
        path, body = request.call_args.args[1], request.call_args.args[2]
        self.assertTrue(path.startswith("message/sendMedia/"))
        self.assertEqual(body["mediatype"], "image")
        self.assertEqual(body["caption"], "Расписание")
        self.assertEqual(base64.b64decode(body["media"]), b"jpeg")
        row = self.api.get(
            "/api/v1/messaging/whatsapp/thread/", {"parent": str(self.parent.id)}
        ).data["results"][0]
        self.assertEqual((row["direction"], row["media"]["name"]), ("out", "фото.jpg"))

    def test_audio_goes_as_voice_message(self):
        self.number()
        _message, request = self.send_file("запись.mp3", b"mp3", "audio/mpeg")
        self.assertTrue(request.call_args.args[1].startswith("message/sendWhatsAppAudio/"))

    def test_voice_recorded_in_browser_goes_as_voice_message(self):
        self.number()
        message, request = self.send_file("голосовое.webm", b"webm", "audio/webm")
        self.assertEqual(message.status, OutboundMessage.Status.SENT)
        self.assertTrue(request.call_args.args[1].startswith("message/sendWhatsAppAudio/"))

    def test_document_goes_as_document(self):
        self.number()
        _message, request = self.send_file("договор.pdf", b"%PDF", "application/pdf")
        self.assertEqual(request.call_args.args[2]["mediatype"], "document")
        self.assertEqual(request.call_args.args[2]["fileName"], "договор.pdf")

    def test_executable_is_rejected(self):
        self.number()
        response = self.api.post(
            "/api/v1/messaging/whatsapp/send/",
            {
                "parent_id": str(self.parent.id),
                "file": SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

    def test_sync_keeps_file_delivery_enabled_on_server(self):
        connection = self.number()
        with mock.patch(REQUEST, return_value={"instance": {"state": "open"}}) as request:
            sync_evolution_states()
        webhook_call = next(
            call for call in request.call_args_list if call.args[1].startswith("webhook/set/")
        )
        self.assertTrue(webhook_call.args[2]["webhook"]["base64"])
        self.assertIn(connection.webhook_secret, webhook_call.args[2]["webhook"]["url"])
