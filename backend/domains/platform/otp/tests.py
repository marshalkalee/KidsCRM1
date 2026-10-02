"""Отправка кода входа (otp/senders.py): порядок каналов и запасной канал,
формат запросов к провайдерам. Сеть подменена."""

from unittest import mock

from django.test import SimpleTestCase, override_settings

from . import senders

PHONE = "+77011234567"


@override_settings(
    OTP_TELEGRAM_TOKEN="tg-token", OTP_MOBIZON_API_KEY="mz-key", OTP_MOBIZON_SENDER="KidsCRM"
)
class SendCodeTests(SimpleTestCase):
    @override_settings(OTP_CHANNELS="console")
    def test_console_logs_code_and_sends_nothing(self):
        with (
            mock.patch.object(senders, "_post") as post,
            self.assertLogs(senders.logger, "WARNING") as logs,
        ):
            self.assertEqual(senders.send_code(PHONE, "4821"), "console")
        post.assert_not_called()
        self.assertIn("4821", logs.output[0])
        self.assertNotIn("1234567", logs.output[0])  # номер в логе замаскирован

    @override_settings(OTP_CHANNELS="telegram,sms")
    def test_falls_back_to_sms_when_no_telegram(self):
        responses = [
            {"ok": False, "error": "PHONE_NUMBER_NOT_FOUND"},
            {"code": 0, "data": {"messageId": "1"}},
        ]
        with mock.patch.object(senders, "_post", side_effect=responses) as post:
            self.assertEqual(senders.send_code(PHONE, "4821"), "sms")
        telegram, sms = post.call_args_list
        self.assertEqual(telegram.kwargs["json_body"]["phone_number"], PHONE)
        self.assertEqual(telegram.kwargs["json_body"]["code"], "4821")
        self.assertEqual(telegram.kwargs["headers"], {"Authorization": "Bearer tg-token"})
        data = sms.kwargs["data"]
        self.assertEqual(
            (data["recipient"], data["apiKey"], data["from"]), ("77011234567", "mz-key", "KidsCRM")
        )
        self.assertIn("4821", data["text"])

    @override_settings(OTP_CHANNELS="telegram,sms")
    def test_network_error_is_a_failed_channel(self):
        with mock.patch.object(senders, "_post", side_effect=senders.SendFailed("timeout")):
            self.assertIsNone(senders.send_code(PHONE, "4821"))

    @override_settings(OTP_CHANNELS="sms", OTP_MOBIZON_API_KEY="")
    def test_missing_key_is_a_failed_channel(self):
        with mock.patch.object(senders, "_post") as post:
            self.assertIsNone(senders.send_code(PHONE, "4821"))
        post.assert_not_called()

    @override_settings(OTP_CHANNELS="sms,pigeon")
    def test_unknown_channel_is_a_config_error(self):
        with self.assertRaisesMessage(ValueError, "pigeon"):
            senders.send_code(PHONE, "4821")

    def test_sms_text_does_not_name_the_center(self):
        self.assertEqual(
            senders.message_text("4821"), "KidsCRM: код входа 4821. Никому его не сообщайте."
        )
