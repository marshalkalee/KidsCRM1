"""Город и координаты филиала (TRU-178)."""

import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from domains.platform.users.models import User

from .geocoding import geocode_branch
from .models import Branch, Organization

URL = "/api/v1/branches/"


def nominatim(lat="43.238949", lon="76.889709", place="10, проспект Абая, Алматы, Казахстан"):
    response = mock.MagicMock()
    response.read.return_value = json.dumps(
        [{"lat": lat, "lon": lon, "display_name": place}]
    ).encode()
    response.__enter__.return_value = response
    return response


@override_settings(GEOCODER="nominatim")
class BranchGeoTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Центр", slug="geo")
        owner = User.objects.create_user(
            phone="77010000001", password="p", full_name="Владелец", organization=self.org,
            role=User.Role.OWNER,
        )  # fmt: skip
        self.api = APIClient()
        self.api.force_authenticate(owner)

    def create(self, **data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.api.post(URL, {"name": "Алмалы", **data}, format="json")

    def test_city_is_required_and_from_the_list(self):
        self.assertEqual(self.create().status_code, 400)
        self.assertEqual(self.create(city="Готэм").status_code, 400)
        with mock.patch("domains.platform.tenants.tasks.geocode_branch_task.delay"):
            self.assertEqual(self.create(city="Алматы").status_code, 201)

    def test_old_branch_without_city_still_editable(self):
        branch = Branch.objects.create(organization=self.org, name="Старый")
        response = self.api.patch(f"{URL}{branch.id}/", {"phone": "+77011112233"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_coordinates_from_address_in_background(self):
        with mock.patch("urllib.request.urlopen", return_value=nominatim()) as call:
            with mock.patch(
                "domains.platform.tenants.tasks.geocode_branch_task.delay",
                side_effect=lambda branch_id: __import__(
                    "domains.platform.tenants.tasks", fromlist=["x"]
                ).geocode_branch_task(branch_id),
            ):
                response = self.create(city="Алматы", address="пр. Абая, 10, 2 этаж")
        self.assertEqual(response.status_code, 201)
        branch = Branch.objects.get(pk=response.data["id"])
        self.assertEqual(
            (branch.latitude, branch.longitude, branch.coordinates_source),
            (Decimal("43.238949"), Decimal("76.889709"), "auto"),
        )
        from urllib.parse import unquote_plus

        url = unquote_plus(call.call_args.args[0].full_url)
        self.assertIn("street=проспект Абая 10", url)
        self.assertIn("city=Алматы", url)

    def test_manual_point_is_not_overwritten(self):
        with mock.patch("domains.platform.tenants.tasks.geocode_branch_task.delay") as later:
            response = self.create(
                city="Алматы", address="Абая 10", latitude="43.250000", longitude="76.900000"
            )
        self.assertEqual(response.data["coordinates_source"], "manual")
        later.assert_not_called()
        branch = Branch.objects.get(pk=response.data["id"])
        with mock.patch("urllib.request.urlopen", return_value=nominatim()):
            self.assertFalse(geocode_branch(branch))
        branch.refresh_from_db()
        self.assertEqual(branch.latitude, Decimal("43.250000"))

    def test_point_outside_kazakhstan_is_rejected(self):
        response = self.create(city="Алматы", latitude="55.75", longitude="37.61")
        self.assertEqual(response.status_code, 400)

    @override_settings(GEOCODER="")
    def test_geocoder_off_does_nothing(self):
        branch = Branch.objects.create(
            organization=self.org, name="Б", address="Абая 10", city="Алматы"
        )
        with mock.patch("urllib.request.urlopen") as call:
            self.assertFalse(geocode_branch(branch))
        call.assert_not_called()


@override_settings(GEOCODER="nominatim")
class GeocoderAccuracyTests(TestCase):
    def test_street_part_keeps_street_type_and_drops_floor(self):
        from .geocoding import street_part

        self.assertEqual(street_part("пр. Абая, 150, 2 этаж"), "проспект Абая 150")
        self.assertEqual(street_part("ул. Жибек Жолы, 64, офис 5"), "улица Жибек Жолы 64")
        self.assertEqual(street_part("мкр. Орбита-2, 15"), "микрорайон Орбита-2 15")

    def test_point_in_another_town_is_rejected(self):
        """Одноимённая улица в соседнем посёлке — неверная точка хуже никакой."""
        from .geocoding import geocode

        elsewhere = nominatim(place="64, улица Жибек Жолы, Шамалган, Карасайский район")
        with mock.patch("urllib.request.urlopen", return_value=elsewhere), mock.patch("time.sleep"):
            self.assertIsNone(geocode("ул. Жибек Жолы, 64", "Алматы"))
