"""
Публикации и кампании (TRU-165): код публикации в сообщении или ссылке →
публикация заявки. Ссылки под ролик — WhatsApp филиала с готовым текстом
и сайт центра с меткой utm_content.
"""

import re
from urllib.parse import quote, urlencode

from domains.platform.tenants.models import Branch

from .models import LeadCampaign

# K12, К12 (кириллицей — набрали руками), K-12; в любом регистре.
CODE = re.compile(r"(?<!\w)[KК]-?(\d{1,4})(?!\w)", re.IGNORECASE)
PREFIX = "K"
MESSAGE = "Здравствуйте! Хочу записаться на пробное занятие (код {code})"


def next_code(organization) -> str:
    """K1, K2, … — следующий свободный номер в организации (архивные и
    удалённые коды не переиспользуются: старые ссылки под роликами живут)."""
    codes = (
        LeadCampaign.objects.all_with_deleted()
        .filter(organization=organization)
        .values_list("code", flat=True)
    )
    numbers = [int(c[1:]) for c in codes if c[:1] == PREFIX and c[1:].isdigit()]
    return f"{PREFIX}{max(numbers, default=0) + 1}"


def find_campaign(organization, *texts):
    """Первая активная публикация, чей код встретился в тексте."""
    for text in texts:
        for match in CODE.finditer(text or ""):
            campaign = (
                LeadCampaign.objects.for_tenant(organization)
                .filter(code=f"{PREFIX}{int(match.group(1))}", is_active=True)
                .select_related("source")
                .first()
            )
            if campaign is not None:
                return campaign
    return None


def whatsapp_links(campaign) -> list[dict]:
    """По ссылке на каждый филиал с телефоном: родитель жмёт — открывается
    WhatsApp филиала с текстом, где уже стоит код публикации."""
    text = quote(MESSAGE.format(code=campaign.code))
    branches = Branch.objects.for_tenant(campaign.organization).filter(is_active=True)
    links = []
    for branch in branches.order_by("name"):
        digits = "".join(ch for ch in branch.phone or "" if ch.isdigit())
        if digits:
            links.append({"branch": branch.name, "url": f"https://wa.me/{digits}?text={text}"})
    return links


def site_link(campaign) -> str | None:
    """Ссылка на сайт центра с меткой — форма сайта (TRU-110) сохранит
    публикацию в заявке."""
    domain = (campaign.organization.website_domain or "").strip().rstrip("/")
    if not domain:
        return None
    if not domain.startswith("http"):
        domain = f"https://{domain}"
    params = urlencode({"utm_source": campaign.source.name.lower(), "utm_content": campaign.code})
    return f"{domain}/?{params}"
