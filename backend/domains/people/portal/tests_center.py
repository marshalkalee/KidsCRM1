"""«О центре» в кабинете родителя: профиль центра, филиалы, группы ребёнка."""

from datetime import date

from domains.platform.public_api.models import CenterProfile
from domains.platform.tenants.models import Branch, Direction
from domains.scheduling.groups.models import Group, GroupMembership

from .tests_auth import PortalAuthBase


class ParentCenterTests(PortalAuthBase):
    def setUp(self):
        super().setUp()
        self.mine = Branch.objects.create(
            organization=self.org, name="Орбита", city="Алматы", address="мкр. Орбита-2, 15",
            phone="+77272502020", latitude="43.21", longitude="76.85",
        )  # fmt: skip
        self.other = Branch.objects.create(
            organization=self.org, name="Абая", city="Алматы", address="пр. Абая, 150"
        )
        Branch.objects.create(organization=self.org, name="Закрыт", is_active=False)
        group = Group.objects.create(
            organization=self.org, branch=self.mine,
            direction=Direction.objects.create(organization=self.org, name="Балет"),
            name="Балет 4–9", capacity=12, description="С собой: купальник и балетки.",
        )  # fmt: skip
        GroupMembership.objects.create(
            organization=self.org, child=self.child, group=group, joined_at=date(2026, 9, 1)
        )
        self.client = self.as_parent(self.login())

    def get(self):
        response = self.client.get(f"/api/v1/portal/children/{self.child.id}/center/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_branches_child_first_with_map_and_whatsapp(self):
        data = self.get()
        names = [b["name"] for b in data["branches"]]
        self.assertEqual(names[0], "Орбита")  # филиал ребёнка — первым
        self.assertIn("Абая", names)
        self.assertNotIn("Закрыт", names)
        orbita = data["branches"][0]
        self.assertTrue(orbita["is_childs"])
        self.assertEqual(orbita["whatsapp_url"], "https://wa.me/77272502020")
        self.assertIn("2gis.kz/geo/76.85", orbita["map_url"])
        abaya = next(b for b in data["branches"] if b["name"] == "Абая")
        self.assertIn("2gis.kz/search/", abaya["map_url"])
        self.assertFalse(abaya["is_childs"])

    def test_groups_with_description(self):
        group = self.get()["groups"][0]
        self.assertEqual((group["name"], group["branch"]), ("Балет 4–9", "Орбита"))
        self.assertEqual(group["description"], "С собой: купальник и балетки.")

    def test_center_profile_only_when_published(self):
        profile = CenterProfile.objects.create(
            organization=self.org, description="Танцевальная студия", instagram="dance.kids"
        )
        self.assertIsNone(self.get()["profile"])
        profile.is_published = True
        profile.save()
        data = self.get()["profile"]
        self.assertEqual(data["description"], "Танцевальная студия")
        self.assertEqual(data["instagram_url"], "https://instagram.com/dance.kids")
