# ruff: noqa: E501 — промпты: связный текст, резать строки ради длины хуже для чтения.
"""
ИИ-помощник, вторая волна (эксперимент, ветка experiment/ai-assistant):
- reminders — напоминания о долге или продлении пачкой, каждому родителю своё;
- communication_note — заметка «как получилось» после звонка → запись коммуникации;
- child_brief — «перед звонком»: главное о ребёнке в 3–5 строках;
- lead_groups — в какую группу записать заявку (группы подбирает код, ИИ выбирает и объясняет);
- daily_plan — утренний список дел из того, что уже посчитали уведомления;
- rejection_reason — причина отказа из справочника по свободному комментарию.

Общий принцип: цифры и списки считает код (долги, свободные места, посещаемость),
ИИ пишет текст и выбирает только из того, что ему дали. Телефоны в модель не уходят.
"""

import datetime
import json
from decimal import Decimal

from django.utils import timezone

from .services import AIError, _ask_json

LANG = {"ru": "русском", "kk": "казахском"}

TONE = """Тепло, вежливо, по-человечески, без канцелярита, без давления и без угроз. Обращение на «Вы», по имени родителя (без фамилии).
Коротко: 2–4 предложения, до 450 символов. Можно один нейтральный эмодзи (🙂 или 🌸).
Используй только факты из данных. Не придумывай цены, скидки, сроки и обещания.
Пиши только на указанном языке; казахский — естественный разговорный, без дословного перевода."""


def _first_name(full_name: str) -> str:
    """«Ахметова Динара» / «Динара Ахметова» — берём то, что похоже на имя:
    в CRM чаще «Фамилия Имя», фамилия обычно на -ова/-ева/-ина/-ов/-ев/-ин."""
    parts = (full_name or "").split()
    if len(parts) < 2:
        return full_name or ""
    surname_endings = ("ова", "ева", "ина", "ов", "ев", "ин", "ко", "ская", "ский", "ұлы", "қызы")
    if parts[0].lower().endswith(surname_endings):
        return parts[1]
    return parts[0]


def _schema(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


# --- Напоминания пачкой ----------------------------------------------------

REMINDER_GOALS = {
    "debt": "вежливо напомнить об оплате абонемента: назвать сумму долга, предложить удобный способ оплаты (Kaspi-перевод или на месте) и спросить, когда будет удобно оплатить",
    "renewal": "напомнить, что абонемент скоро заканчивается (по дате или по остатку занятий), и предложить продлить, чтобы ребёнок не пропускал занятия",
}


def _money(value) -> str | None:
    """12500 → «12 500 ₸» — суммы форматирует код, модель переписывает как есть."""
    amount = int(Decimal(value or 0))
    return f"{amount:,}".replace(",", " ") + " ₸" if amount else None


def _payer(child):
    from domains.people.clients.models import ChildContact

    link = (
        ChildContact.objects.for_tenant(child.organization)
        .filter(child=child, parent_contact__deleted_at__isnull=True)
        .select_related("parent_contact")
        .prefetch_related("parent_contact__phones")
        .order_by("-is_payer", "created_at")
        .first()
    )
    if link is None:
        return None, ""
    parent = link.parent_contact
    phones = [p.number for p in parent.phones.all()]
    return parent, parent.whatsapp or (phones[0] if phones else "")


def reminders(user, child_ids, *, kind: str, language: str) -> list[dict]:
    from domains.money.subscriptions.debt import debt_by_child
    from domains.money.subscriptions.models import Subscription
    from domains.people.clients.models import Child

    if kind not in REMINDER_GOALS:
        raise AIError("Неизвестный вид напоминания.")
    if language not in LANG:
        raise AIError("Неизвестный язык.")
    organization = user.organization
    children = list(
        Child.objects.for_tenant(organization).filter(id__in=child_ids[:50]).order_by("full_name")
    )
    if not children:
        raise AIError("Выберите детей.")
    debts = debt_by_child(organization, [c.id for c in children])
    items, facts = [], []
    for number, child in enumerate(children, start=1):
        parent, phone = _payer(child)
        subscription = (
            Subscription.objects.for_tenant(organization)
            .filter(child=child)
            .select_related("subscription_type_version", "direction")
            .order_by("-starts_on")
            .first()
        )
        items.append({"child": child, "parent": parent, "phone": phone})
        facts.append(
            {
                "номер": number,
                "родитель": _first_name(parent.full_name) if parent else None,
                "ребёнок": _first_name(child.full_name),
                "направление": subscription.direction.name if subscription else None,
                "абонемент": subscription.subscription_type_version.name if subscription else None,
                "действует до": f"{subscription.ends_on:%d.%m.%Y}" if subscription else None,
                "осталось занятий": subscription.sessions_remaining_cache if subscription else None,
                "долг": _money(debts.get(child.id)),
            }
        )

    def write(batch):
        data = _ask_json(
            system=f"Ты пишешь сообщения родителям от имени администратора детского центра {organization.name} в Казахстане. Каждое сообщение уйдёт отдельно в WhatsApp, администратор проверит и отправит сам.\n{TONE}",
            user=(
                f"Цель каждого сообщения: {REMINDER_GOALS[kind]}.\nЯзык: {LANG[language]}.\n"
                f"Напиши по одному сообщению на КАЖДЫЙ номер из списка ({len(batch)} шт.), с учётом его данных. Суммы пиши ровно как в данных:\n{json.dumps(batch, ensure_ascii=False, indent=1)}"
            ),
            schema=_schema(
                {
                    "messages": {
                        "type": "array",
                        "items": _schema(
                            {"number": {"type": "integer"}, "text": {"type": "string"}}
                        ),
                    }
                }
            ),
            max_tokens=12000,
        )
        return {
            m.get("number"): (m.get("text") or "").strip()
            for m in data.get("messages") or []
            if (m.get("text") or "").strip()
        }

    texts = write(facts)
    # Модель иногда пишет не всем — недостающих дозапрашиваем один раз.
    missing = [f for f in facts if f["номер"] not in texts]
    if missing:
        texts.update(write(missing))
    return [
        {
            "child": str(item["child"].id),
            "child_name": item["child"].full_name,
            "parent_name": item["parent"].full_name if item["parent"] else "",
            "phone": item["phone"],
            "text": texts.get(number, ""),
        }
        for number, item in enumerate(items, start=1)
    ]


# --- Заметка о звонке ------------------------------------------------------

NOTE_SYSTEM = """Администратор детского центра наскоро записал, как прошёл контакт с родителем (или надиктовал голосом — текст может быть без знаков препинания, с оговорками).
Сделай из этого аккуратную запись в журнал:
- channel — call (звонок), whatsapp (переписка) или comment (просто пометка, если контакта не было);
- note — 1–3 коротких предложения по-русски: все факты, договорённости, вопросы и просьбы родителя (даты, суммы, причины). Ничего из сказанного не теряй, но и не выдумывай. Имена пиши правильно, как в тексте;
- next_step — все действия, которые из этого следуют, с датой, если она есть («Проверить оплату в пятницу; ответить про перевод в субботнюю группу»). Пусто, если действий нет."""


def communication_note(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise AIError("Напишите, как прошёл разговор.")
    if len(text) > 3000:
        raise AIError("Слишком длинная заметка.")
    data = _ask_json(
        system=NOTE_SYSTEM,
        user=f"Сегодня: {timezone.localdate():%d.%m.%Y}\nЗаметка:\n<note>\n{text}\n</note>",
        schema=_schema(
            {
                "channel": {"type": "string", "enum": ["call", "whatsapp", "comment"]},
                "note": {"type": "string"},
                "next_step": {"type": "string"},
            }
        ),
        max_tokens=1500,
    )
    return {
        "channel": data.get("channel") or "comment",
        "note": (data.get("note") or "").strip(),
        "next_step": (data.get("next_step") or "").strip(),
    }


# --- Перед звонком ---------------------------------------------------------

BRIEF_SYSTEM = """Ты готовишь администратору детского центра короткую справку перед звонком родителю.
По данным о ребёнке напиши:
- points — 3–5 коротких пунктов по-русски: самое важное (как ходит, что с абонементом и оплатой, о чём договаривались в прошлый раз). Факты только из данных, цифры как есть;
- suggestion — одно предложение: о чём стоит поговорить в этот раз. Пусто, если поводов нет.
Не пересказывай всё подряд — только то, что поможет разговору."""


def child_brief(child, user) -> dict:
    from domains.money.subscriptions.debt import debt_by_child
    from domains.money.subscriptions.models import Subscription
    from domains.people.clients.models import CommunicationLog
    from domains.platform.core.role_permissions import can_view_client_money
    from domains.scheduling.attendance.models import Attendance
    from domains.scheduling.groups.models import GroupMembership

    organization = child.organization
    since = timezone.now() - datetime.timedelta(days=30)
    attendance = list(
        Attendance.objects.for_tenant(organization)
        .filter(child=child, lesson__starts_at__gte=since)
        .order_by("lesson__starts_at")
        .values_list("status", "lesson__starts_at")
    )
    streak = 0
    for status, _ in reversed(attendance):
        if status != "absent":
            break
        streak += 1
    groups = list(
        GroupMembership.objects.for_tenant(organization)
        .filter(child=child, left_at__isnull=True)
        .values_list("group__name", flat=True)
    )
    facts = {
        "ребёнок": child.full_name,
        "возраст": child.age,
        "статус": child.get_status_display(),
        "группы": groups or None,
        "посещения за 30 дней": {
            "был": sum(1 for s, _ in attendance if s in ("present", "makeup")),
            "не был": sum(1 for s, _ in attendance if s == "absent"),
            "пропусков подряд сейчас": streak,
            "последнее посещение": next(
                (
                    f"{timezone.localtime(at):%d.%m}"
                    for s, at in reversed(attendance)
                    if s in ("present", "makeup")
                ),
                None,
            ),
        },
        "последние контакты (свежие первыми)": [
            f"{timezone.localtime(log.created_at):%d.%m} {log.get_channel_display()}: {log.note[:300]}"
            for log in CommunicationLog.objects.for_tenant(organization)
            .filter(child=child)
            .order_by("-created_at")[:5]
        ]
        or None,
        "медицинские заметки": child.medical_notes or None,
    }
    if can_view_client_money(user):
        subscription = (
            Subscription.objects.for_tenant(organization)
            .filter(child=child)
            .select_related("subscription_type_version")
            .order_by("-starts_on")
            .first()
        )
        facts["абонемент"] = (
            {
                "название": subscription.subscription_type_version.name,
                "статус": subscription.get_status_display(),
                "до": f"{subscription.ends_on:%d.%m.%Y}",
                "осталось занятий": subscription.sessions_remaining_cache,
            }
            if subscription
            else "нет"
        )
        facts["долг"] = _money(debt_by_child(organization, [child.id]).get(child.id)) or "нет"
    data = _ask_json(
        system=BRIEF_SYSTEM,
        user=f"Сегодня: {timezone.localdate():%d.%m.%Y}\nДанные:\n{json.dumps(facts, ensure_ascii=False, indent=1)}",
        schema=_schema(
            {
                "points": {"type": "array", "items": {"type": "string"}},
                "suggestion": {"type": "string"},
            }
        ),
        max_tokens=1500,
    )
    return {
        "points": [p.strip() for p in data.get("points") or [] if p.strip()][:5],
        "suggestion": (data.get("suggestion") or "").strip(),
    }


# --- Подбор группы для заявки -----------------------------------------------

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

GROUPS_SYSTEM = """Ты помогаешь администратору детского центра выбрать группу для ребёнка из заявки.
Тебе дают заявку (возраст, направление, филиал, комментарии с пожеланиями родителя) и список подходящих групп со свободными местами и расписанием.
Выбери до 3 групп — только из списка, по номерам, от лучшей к худшей — и для каждой одной фразой по-русски объясни, чем подходит (время под пожелания, места, возраст, филиал) или в чём не совпадает.
Если пожеланий нет — предпочитай группы с большим числом свободных мест и тем же филиалом.
summary — одно предложение для администратора: что выбрать. Если ни одна группа не совпадает с пожеланиями, честно скажи, чего нет («Групп по субботам нет — ближе всего …»)."""


def lead_groups(lead) -> dict:
    from domains.scheduling.groups.models import Group
    from domains.scheduling.groups.queries import active_template, with_members_count

    groups = with_members_count(
        Group.objects.for_tenant(lead.organization)
        .filter(status=Group.Status.ACTIVE)
        .select_related("branch", "direction")
        .prefetch_related("schedule_templates__slots")
    )
    if lead.direction_id:
        groups = groups.filter(direction_id=lead.direction_id)
    candidates = []
    for group in groups:
        free = (group.capacity or 0) - group.members_count
        if free <= 0:
            continue
        age = lead.child_age
        if age is not None and (
            (group.age_min is not None and age < group.age_min)
            or (group.age_max is not None and age > group.age_max)
        ):
            continue
        template = active_template(group)
        slots = (
            sorted(template.slots.all(), key=lambda s: (s.weekday, s.start_time))
            if template
            else []
        )
        schedule = (
            ", ".join(f"{WEEKDAYS[s.weekday]} {s.start_time:%H:%M}" for s in slots)
            or "расписания нет"
        )
        candidates.append({"group": group, "free": free, "schedule": schedule})
    candidates.sort(key=lambda c: (c["group"].branch_id != lead.branch_id, -c["free"]))
    candidates = candidates[:8]
    if not candidates:
        return {"picks": [], "note": "Нет групп с местами под возраст и направление заявки."}
    comments = list(lead.comments.order_by("-created_at").values_list("text", flat=True)[:5])
    listing = [
        {
            "номер": number,
            "группа": c["group"].name,
            "филиал": c["group"].branch.name if c["group"].branch_id else None,
            "возраст": f"{c['group'].age_min or '—'}–{c['group'].age_max or '—'}",
            "свободно мест": c["free"],
            "расписание": c["schedule"],
        }
        for number, c in enumerate(candidates, start=1)
    ]
    request = {
        "возраст ребёнка": lead.child_age,
        "направление": lead.direction.name if lead.direction_id else None,
        "филиал заявки": lead.branch.name if lead.branch_id else None,
        "пожелания и комментарии": comments or None,
    }
    data = _ask_json(
        system=GROUPS_SYSTEM,
        user=f"Заявка: {json.dumps(request, ensure_ascii=False)}\nГруппы: {json.dumps(listing, ensure_ascii=False, indent=1)}",
        schema=_schema(
            {
                "picks": {
                    "type": "array",
                    "items": _schema({"number": {"type": "integer"}, "reason": {"type": "string"}}),
                },
                "summary": {"type": "string"},
            }
        ),
        max_tokens=1500,
    )
    picks = []
    for pick in data.get("picks") or []:
        number = pick.get("number")
        if (
            isinstance(number, int)
            and 1 <= number <= len(candidates)
            and all(p["number"] != number for p in picks)
        ):
            c = candidates[number - 1]
            picks.append(
                {
                    "number": number,
                    "id": str(c["group"].id),
                    "name": c["group"].name,
                    "branch": c["group"].branch.name if c["group"].branch_id else "",
                    "schedule": c["schedule"],
                    "free": c["free"],
                    "reason": (pick.get("reason") or "").strip(),
                }
            )
    return {"picks": picks[:3], "note": (data.get("summary") or "").strip()}


# --- План на день -----------------------------------------------------------

PLAN_SYSTEM = """Ты помогаешь администратору детского центра начать день. Тебе дают сводку: что требует внимания (с цифрами) и занятия на сегодня.
Составь список дел на сегодня по порядку важности: 3–6 пунктов, каждый — одно короткое действие по-русски с цифрой, если она есть («Позвонить 4 новым заявкам»). Суммы пиши ровно как в сводке.
Сначала то, что теряет деньги или клиентов (новые заявки, просроченные долги), потом посещаемость, потом остальное.
link — ровно одно значение из списка ссылок, куда вести за этим делом. Не придумывай дел, которых нет в сводке."""


def daily_plan(request) -> dict:
    from domains.platform.notifications.views import collect
    from domains.scheduling.schedule.models import Lesson

    items = [i for i in collect(request) if i["available"] and i["count"]]
    organization = request.user.organization
    tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
    today = timezone.now().astimezone(tz).date()
    lessons = (
        Lesson.objects.for_tenant(organization)
        .filter(starts_at__date=today)
        .exclude(status="cancelled")
    )
    if request.user.role == "teacher":
        lessons = lessons.filter(teacher=request.user)
    titles = {
        "new_leads": "новые заявки ждут звонка",
        "unmarked_lessons": "вчерашние занятия без отметки посещаемости",
        "overdue_debts": "дети с просроченным долгом",
        "no_subscription": "дети ходят без действующего абонемента",
    }
    summary = [
        {
            "что": titles.get(i["kind"], i["kind"]),
            "сколько": i["count"],
            "ссылка": i["link"],
            **({"сумма": _money(i["total"])} if i.get("total") else {}),
        }
        for i in items
    ]
    links = sorted({i["link"] for i in items} | {"/schedule", "/attendance"})
    if not summary and not lessons.exists():
        return {
            "tasks": [
                {
                    "text": "Срочных дел нет — хороший день, чтобы обзвонить тех, кто «думает».",
                    "link": "/leads",
                }
            ]
        }
    data = _ask_json(
        system=PLAN_SYSTEM,
        user=json.dumps(
            {
                "сегодня": today.isoformat(),
                "требует внимания": summary,
                "занятий сегодня": lessons.count(),
                "ссылки": links,
            },
            ensure_ascii=False,
        ),
        schema=_schema(
            {
                "tasks": {
                    "type": "array",
                    "items": _schema(
                        {"text": {"type": "string"}, "link": {"type": "string", "enum": links}}
                    ),
                }
            }
        ),
        max_tokens=1500,
    )
    return {"tasks": [t for t in data.get("tasks") or [] if (t.get("text") or "").strip()][:6]}


# --- Причина отказа ----------------------------------------------------------


def rejection_reason(organization, *, text: str, kind: str) -> dict:
    from domains.platform.leads.models import LeadRejectionReason

    text = (text or "").strip()
    if not text:
        raise AIError("Напишите, почему отказались.")
    reasons = {
        r.name: r
        for r in LeadRejectionReason.objects.for_tenant(organization).filter(
            is_active=True, kind=kind
        )
    }
    if not reasons:
        raise AIError("Справочник причин пуст.")
    data = _ask_json(
        system="Подбери причину отказа из справочника центра по комментарию администратора. Только значение из списка; если не подходит ничего конкретное — «Другое», а если и его нет — пустая строка.",
        user=f"Справочник: {json.dumps(list(reasons), ensure_ascii=False)}\nКомментарий: {text[:1000]}",
        schema=_schema({"reason": {"type": "string", "enum": [*reasons, ""]}}),
        max_tokens=300,
    )
    reason = reasons.get(data.get("reason") or "")
    return {"reason": str(reason.id) if reason else None, "name": reason.name if reason else ""}
