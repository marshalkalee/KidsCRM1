"""
Координаты филиала по адресу (TRU-178). По умолчанию — Nominatim
(OpenStreetMap): бесплатно, без ключа, до 1 запроса в секунду — хватает,
филиалы заводят редко. GEOCODER="" — выключено (тесты, офлайн).
Поставил точку вручную — автоматика её больше не трогает.

Сначала структурный запрос «улица + город»: свободный текст находит
одноимённую улицу в соседнем посёлке (проверено: «ул. Жибек Жолы, 64,
Алматы» → Каскелен). Точка принимается, только если в найденном адресе есть
город филиала: неверная точка хуже, чем никакой.
"""

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from decimal import Decimal

from django.conf import settings

logger = logging.getLogger(__name__)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Тип улицы — полным словом: «проспект Абая» и «улица Абая» — разные места.
_STREET_TYPES = [
    (re.compile(r"^\s*(ул\.?|улица)\s+", re.I), "улица "),
    (re.compile(r"^\s*(пр\.?|пр-т|просп\.?|проспект)\s+", re.I), "проспект "),
    (re.compile(r"^\s*(мкр\.?|микрорайон)\s+", re.I), "микрорайон "),
]
# Уточнения внутри здания геокодеру не нужны.
_INSIDE = re.compile(
    r"\b(\d+\s*этаж|этаж\s*\d+|офис\s*\S+|оф\.\s*\S+|кв\.?\s*\S+|каб\.?\s*\S+)", re.I
)


def street_part(address: str) -> str:
    """«ул. Жибек Жолы, 64, 2 этаж» → «улица Жибек Жолы 64»."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    parts = [p for p in parts if not _INSIDE.search(p)]
    text = " ".join(parts[:2])
    for pattern, full in _STREET_TYPES:
        text = pattern.sub(full, text)
    return text.strip()


def _search(params):
    url = f"{NOMINATIM_URL}?" + urllib.parse.urlencode(
        {**params, "format": "json", "limit": 3, "countrycodes": "kz"}
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": settings.GEOCODER_USER_AGENT, "Accept-Language": "ru"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def _in_city(row, city):
    return not city or city.lower() in (row.get("display_name") or "").lower()


def geocode(address: str, city: str) -> tuple[Decimal, Decimal] | None:
    if settings.GEOCODER != "nominatim" or not (address or city):
        return None
    attempts = []
    if address and city:
        attempts.append({"street": street_part(address), "city": city, "country": "Казахстан"})
    attempts.append({"q": ", ".join(p for p in (address, city, "Казахстан") if p)})
    for number, params in enumerate(attempts):
        if number:
            time.sleep(1)  # правило Nominatim: не чаще раза в секунду
        try:
            rows = _search(params)
        except (OSError, ValueError) as exc:
            logger.warning("Geocoding failed for %r: %s", params, exc)
            return None
        row = next((r for r in rows if _in_city(r, city)), None)
        if row:
            return (
                Decimal(row["lat"]).quantize(Decimal("0.000001")),
                Decimal(row["lon"]).quantize(Decimal("0.000001")),
            )
    return None


def geocode_branch(branch) -> bool:
    """Поставить координаты из адреса, если их не ставили вручную."""
    if branch.coordinates_source == branch.CoordinatesSource.MANUAL:
        return False
    point = geocode(branch.address, branch.city)
    if point is None:
        return False
    branch.latitude, branch.longitude = point
    branch.coordinates_source = branch.CoordinatesSource.AUTO
    branch.save(update_fields=["latitude", "longitude", "coordinates_source", "updated_at"])
    return True
