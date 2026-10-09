"""Демо-данные — только в разработке или на демо-сервере с явным флагом."""

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


class DemoGuardTests(TestCase):
    @override_settings(DEMO_DATA_ALLOWED=False)
    def test_showcase_refuses_without_flag(self):
        with self.assertRaisesMessage(CommandError, "DEMO_DATA_ALLOWED"):
            call_command("seed_showcase")
        with self.assertRaisesMessage(CommandError, "DEMO_DATA_ALLOWED"):
            call_command("seed_demo")


class ExtrasOnServerTests(TestCase):
    """Дополнения витрины ходят во внутренний API — на сервере с HTTPS и
    своим доменом это должно работать так же, как локально."""

    def test_center_profile_on_https_server(self):
        import shutil
        import tempfile

        from domains.platform.core.showcase_extras import Extras
        from domains.platform.public_api.models import CenterProfile
        from domains.platform.tenants.models import Organization
        from domains.platform.users.models import User

        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, True)
        org = Organization.objects.create(name="Demo", slug="demo-server")
        User.objects.create_user(
            phone="77050000001", password="p", full_name="Владелец", organization=org,
            role=User.Role.OWNER,
        )  # fmt: skip
        with override_settings(
            ALLOWED_HOSTS=["kidscrm-demo.duckdns.org"],
            SECURE_SSL_REDIRECT=True,
            SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
            MEDIA_ROOT=media,
        ):
            self.assertEqual(Extras(org, lambda *_: None).center_profile(), "опубликован")
        profile = CenterProfile.objects.get(organization=org)
        self.assertTrue(profile.logo_url.startswith("https://kidscrm-demo.duckdns.org/"))
