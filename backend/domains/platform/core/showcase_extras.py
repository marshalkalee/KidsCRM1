"""
Наполнение витрины тем, без чего экраны выглядят пустыми на показе
заказчику (seed_showcase --extras): задачи на сегодня и вперёд, объявления,
запросы родителей, журнал рассылок, отказы этого месяца, обращения к API,
профиль центра для каталога, история импорта детей.

Пишет через те же сервисы и API, что приложение, — поэтому, например,
объявление само попадает в журнал рассылок. Один раз на организацию
(метка Organization.settings["showcase_extras"]); повторный запуск ничего
не дублирует.
"""

import datetime
import io
import json
import random
import time

from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw
from rest_framework.test import APIClient

from domains.people.clients.models import Child, ImportJob, ParentContact
from domains.people.portal.lesson_requests import (
    ParentRequestError,
    create_parent_request,
    regular_candidate_lessons,
)
from domains.people.portal.models import ParentAccount, ParentLessonRequest
from domains.people.portal.request_processing import (
    approve_parent_request,
    reject_parent_request,
)
from domains.platform.leads.models import Lead, LeadRejectionReason
from domains.platform.leads.services import change_status
from domains.platform.notifications.messaging import service as messaging
from domains.platform.notifications.models import MessageCategory, MessagingConsent
from domains.platform.public_api.models import ApiKey, ApiRequestLog
from domains.platform.tasks.models import Task
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule.models import Lesson

MARK = "showcase_extras"

ANNOUNCEMENTS = [
    (
        "Отчётный концерт 21 декабря",
        "Дорогие родители! 21 декабря в 15:00 — отчётный концерт всех групп в ДК «Алатау». "
        "Костюмы выдаём за неделю, репетиция в зале 19 декабря. Билеты для семьи — "
        "у администратора, по два на ребёнка.",
        "organization",
    ),
    (
        "Каникулы: расписание с 28 октября",
        "На осенних каникулах (28 октября — 3 ноября) занятия идут по обычному расписанию, "
        "кроме групп 4–7 лет: у них в эти дни перерыв. Абонемент на эти дни не списывается.",
        "organization",
    ),
    (
        "Открытый урок для родителей",
        "Приглашаем на открытый урок: посмотреть, чему дети научились за месяц. "
        "Приходите за 10 минут, сменную обувь не нужно.",
        "group",
    ),
    (
        "Новый зал в филиале «Орбита»",
        "С 15 октября часть занятий в «Орбите» переезжает в новый большой зал на 2 этаже. "
        "Номер зала будет в расписании в кабинете родителя.",
        "branch",
    ),
]

GROUP_DESCRIPTIONS = {
    "Балет": "Классический экзерсис у станка, постановка корпуса и рук, первые танцы. "
    "С собой: купальник, балетки, волосы в пучок.",
    "Растяжка": "Гибкость, шпагаты и здоровая спина — мягко, без боли. "
    "С собой: удобная форма, носки, коврик не нужен.",
    "Гимнастика": "Кувырки, равновесие, координация — через игру. "
    "С собой: футболка, шорты, чешки.",
    "Хореография": "Ритм, народные и эстрадные танцы, выступления на праздниках. "
    "С собой: удобная форма и чешки.",
    "Contemporary": "Современный танец: импровизация, работа с полом, свои постановки. "
    "С собой: свободная одежда, босиком или в носках.",
}

TASKS = [
    # (тип, заголовок, описание, сдвиг срока в часах от сейчас, роль исполнителя)
    ("call_back", "Перезвонить маме Алии — вопрос по расписанию",
     "Просит перевести в субботнюю группу.", 3, "admin"),
    ("payment_reminder", "Напомнить об оплате — Жумабаев Нурсултан",
     "Абонемент закончился 2 дня назад, занимается без оплаты.", 5, "admin"),
    ("trial_signup", "Записать на пробное — заявка из Instagram",
     "Девочка 6 лет, интересует балет, удобно после 17:00.", 26, "manager"),
    ("renewal_offer", "Предложить продление — 3 занятия осталось",
     "Предложить абонемент на 12 занятий со скидкой за продление.", 48, "manager"),
    ("other", "Подготовить костюмы к концерту",
     "Сверить размеры у групп 10–14 и заказать у швеи.", 72, "owner"),
    ("call_back", "Узнать у родителей, почему пропускает",
     "Три пропуска подряд, на звонки администратора не ответили.", -20, "admin"),
]  # fmt: skip

API_CALLS = [
    ("GET", "/api/public/v1/groups/", 200),
    ("GET", "/api/public/v1/schedule/?date_from=2026-10-01", 200),
    ("GET", "/api/public/v1/subscription-types/", 200),
    ("POST", "/api/public/v1/leads/", 201),
    ("GET", "/api/public/v1/children/", 403),
    ("GET", "/api/public/v1/groups/", 429),
]


def _png(color, text, size=(960, 640)):
    """Простая картинка-заглушка для фото: градиент и подпись."""
    width, height = size
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        shade = tuple(int(c + (255 - c) * y / height * 0.45) for c in color)
        draw.line([(0, y), (width, y)], fill=shade)
    draw.text((40, height - 70), text, fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.name = "photo.png"
    buffer.seek(0)
    return buffer


class Extras:
    def __init__(self, org, out):
        self.org = org
        self.out = out
        self.rng = random.Random(77)
        self.owner = User.objects.get(organization=org, role=User.Role.OWNER)
        self.staff = {
            role: User.objects.filter(organization=org, role=role, is_active=True).first()
            for role in ("owner", "admin", "manager")
        }
        self.api = APIClient(HTTP_HOST="localhost")
        self.api.force_authenticate(self.owner)

    def run(self):
        if (self.org.settings or {}).get(MARK):
            self.out("Витрина уже дополнена — пропускаю.")
            return
        counts = {
            "задач": self.tasks(),
            "описаний групп": self.group_descriptions(),
            "объявлений": self.announcements(),
            "отказов в этом месяце": self.rejections(),
            "запросов родителей": self.parent_requests(),
            "сообщений родителям": self.messages(),
            "обращений к API": self.api_calls(),
            "профиль центра": self.center_profile(),
            "импорт детей": self.child_import(),
        }
        self.org.refresh_from_db()
        self.org.settings = {**(self.org.settings or {}), MARK: timezone.now().isoformat()}
        self.org.save(update_fields=["settings"])
        self.out(", ".join(f"{name}: {value}" for name, value in counts.items()))

    # --- задачи --------------------------------------------------------------

    def tasks(self):
        children = list(Child.objects.for_tenant(self.org).order_by("full_name")[:40])
        now = timezone.now()
        created = 0
        for index, (kind, title, text, hours, role) in enumerate(TASKS):
            child = children[index * 5] if children else None
            Task.objects.create(
                organization=self.org,
                type=kind,
                title=title,
                description=text,
                assigned_to=self.staff.get(role) or self.owner,
                created_by=self.owner,
                due_at=now + datetime.timedelta(hours=hours),
                child=child if kind in ("payment_reminder", "renewal_offer", "other") else None,
            )
            created += 1
        return created

    # --- каталог: описания групп и профиль центра ---------------------------

    def group_descriptions(self):
        updated = 0
        for group in Group.objects.for_tenant(self.org).select_related("direction"):
            name = group.direction.name if group.direction_id else group.name
            text = next((v for k, v in GROUP_DESCRIPTIONS.items() if k in name), "")
            if text and not group.description:
                group.description = text
                group.save(update_fields=["description"])
                updated += 1
        return updated

    def center_profile(self):
        url = "/api/v1/api-keys/center-profile/"
        self.api.post(f"{url}logo/", {"file": _png((228, 88, 110), "DK", (400, 400))})
        for color, caption in [
            ((124, 58, 237), "Большой зал, «Орбита»"),
            ((236, 72, 153), "Отчётный концерт"),
            ((14, 165, 233), "Группа 4–7 лет"),
        ]:
            self.api.post(f"{url}photos/", {"file": _png(color, caption)})
        response = self.api.patch(
            url,
            {
                "description": "Танцевальная студия для детей 4–17 лет в трёх районах Алматы: "
                "балет, растяжка, гимнастика, хореография и contemporary. "
                "Маленькие группы до 12 человек, отчётные концерты дважды в год, "
                "первое пробное занятие — бесплатно.",
                "phone": "77272501010",
                "instagram": "dancekids.almaty",
                "is_published": True,
            },
            format="json",
        )
        return "опубликован" if response.status_code == 200 else f"ошибка {response.status_code}"

    # --- объявления (сами уходят родителям в журнал рассылок) ---------------

    def announcements(self):
        group = Group.objects.for_tenant(self.org).order_by("name").first()
        branch = group.branch if group else None
        created = 0
        for title, body, audience in ANNOUNCEMENTS:
            data = {"title": title, "body": body, "audience": audience}
            if audience == "group":
                data["group"] = str(group.id)
            if audience == "branch":
                data["branch"] = str(branch.id)
            response = self.api.post("/api/v1/announcements/", data, format="json")
            if response.status_code != 201:
                self.out(f"  объявление «{title}»: {response.status_code} {response.data}")
                continue
            self.api.post(f"/api/v1/announcements/{response.data['id']}/publish/")
            created += 1
        return created

    # --- отказы этого месяца (аналитика «Отказы») ----------------------------

    def rejections(self):
        reasons = list(LeadRejectionReason.objects.for_tenant(self.org).filter(kind="new"))
        leads = list(
            Lead.objects.for_tenant(self.org)
            .filter(status__in=["new", "contacted", "thinking"])
            .order_by("created_at")[:6]
        )
        for index, lead in enumerate(leads):
            with transaction.atomic():
                change_status(
                    lead,
                    to_status=Lead.Status.REJECTED,
                    actor=self.staff.get("manager") or self.owner,
                    rejection_reason=reasons[index % len(reasons)],
                    comment="Отказ при звонке",
                )
        return len(leads)

    # --- запросы родителей из кабинета --------------------------------------

    def parent_requests(self):
        made = 0
        children = (
            Child.objects.for_tenant(self.org)
            .filter(status="active")
            .prefetch_related("contacts__parent_contact__phones")
            .order_by("full_name")
        )
        now = timezone.now()
        plans = ["cancel", "enroll", "cancel", "enroll", "cancel", "cancel", "enroll"]
        for child in children:
            if made >= len(plans):
                break
            link = child.contacts.select_related("parent_contact").first()
            phone = link and link.parent_contact.phones.first()
            if not phone:
                continue
            account, _ = ParentAccount.objects.get_or_create(phone=phone.number)
            kind = plans[made]
            try:
                with transaction.atomic():
                    if kind == "cancel":
                        lesson = (
                            Lesson.objects.for_tenant(self.org)
                            .filter(status=Lesson.Status.SCHEDULED, starts_at__gt=now)
                            .filter(group__memberships__child=child)
                            .order_by("starts_at")
                            .first()
                        )
                        if lesson is None:
                            continue
                        create_parent_request(
                            account=account,
                            child=child,
                            lesson_id=lesson.id,
                            request_type=ParentLessonRequest.Type.CANCEL,
                            cancel_reason=self.rng.choice(["illness", "family"]),
                            comment=self.rng.choice(
                                ["Температура, пропустим", "Уезжаем к бабушке", ""]
                            ),
                        )
                    else:
                        lessons = regular_candidate_lessons(child)
                        if not lessons:
                            continue
                        create_parent_request(
                            account=account,
                            child=child,
                            lesson_id=lessons[0].id,
                            request_type=ParentLessonRequest.Type.ENROLL,
                            comment="Хотим дополнительное занятие перед концертом",
                        )
                made += 1
            except ParentRequestError:
                continue
        # Пара уже обработанных — чтобы был виден и итог.
        processed = ParentLessonRequest.objects.for_tenant(self.org).order_by("created_at")
        first, second = list(processed[:2]) + [None] * (2 - min(2, processed.count()))
        actor = self.staff.get("admin") or self.owner
        if first:
            with transaction.atomic():
                approve_parent_request(first.id, actor=actor)
        if second:
            with transaction.atomic():
                reject_parent_request(
                    second.id, actor=actor, reason="В группе нет мест на эту дату"
                )
        return made

    # --- журнал рассылок -----------------------------------------------------

    def messages(self):
        parents = list(ParentContact.objects.for_tenant(self.org).order_by("full_name")[:30])
        for index, parent in enumerate(parents):
            if index % 6 != 5 and not parent.email:
                parent.email = f"parent{index + 1}@example.com"
                parent.save(update_fields=["email"])
            if index % 7 != 3:
                messaging.set_consent(
                    parent,
                    MessageCategory.UTILITY,
                    MessagingConsent.Status.OPTED_IN,
                    MessagingConsent.Source.ADMIN_FORM,
                    user=self.owner,
                )
        messaging.set_consent(
            parents[-1],
            MessageCategory.UTILITY,
            MessagingConsent.Status.OPTED_OUT,
            MessagingConsent.Source.UNSUBSCRIBE_LINK,
        )
        events = [
            ("subscription_ending", {"left": "2 занятия"}),
            ("payment_due", {"amount": "18 000 ₸"}),
            ("lesson_cancelled", {"group": "Балет 4–9", "when": "15 октября, 17:00",
                                  "note": "Отработка — в субботу в 11:00."}),
        ]  # fmt: skip
        made = []
        for index, parent in enumerate(parents[:24]):
            event, context = events[index % len(events)]
            link = parent.child_links.select_related("child").first()
            name = link.child.full_name.split()[-1] if link else "Алия"
            context = {**context, "child": name}
            with transaction.atomic():
                message = messaging.notify(
                    parent, event, context, dedup_key=f"showcase:{event}:{parent.id}"
                )
            made.append(message.id)
        # Разослать сразу, не дожидаясь очереди: журнал видно на показе.
        for message_id in made:
            messaging.deliver(message_id)
        time.sleep(1)
        return len(made)

    # --- обращения к публичному API ------------------------------------------

    def api_calls(self):
        key = ApiKey.objects.filter(organization=self.org, revoked_at__isnull=True).first()
        if key is None:
            return 0
        now = timezone.now()
        rows = []
        for minutes in range(0, 60 * 30, 47):
            method, path, status = API_CALLS[(minutes // 47) % len(API_CALLS)]
            rows.append(
                ApiRequestLog(
                    organization=self.org, key=key, method=method, path=path, status=status
                )
            )
        created = ApiRequestLog.objects.bulk_create(rows)
        for index, row in enumerate(created):
            ApiRequestLog.objects.filter(pk=row.pk).update(
                created_at=now - datetime.timedelta(minutes=47 * index)
            )
        key.last_used_at = now
        key.save(update_fields=["last_used_at"])
        return len(created)

    # --- импорт детей из Excel -----------------------------------------------

    def child_import(self):
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.append(["ФИО ребёнка", "Дата рождения", "Пол", "Родитель", "Телефон"])
        rows = [
            ("Сейткали Амина", "12.03.2017", "ж", "Сейткали Динара", "+77015550101"),
            ("Ахметов Тимур", "05.11.2015", "м", "Ахметова Гульнар", "+77015550102"),
            ("Ким Валерия", "21.07.2018", "ж", "Ким Ольга", "+77015550103"),
            ("Нурланова Дана", "30.01.2014", "ж", "Нурланов Ерлан", "+77015550104"),
            ("Ли Арина", "17.09.2016", "ж", "Ли Светлана", "+77015550105"),
        ]
        for row in rows:
            sheet.append(list(row))
        buffer = io.BytesIO()
        book.save(buffer)
        buffer.name = "children.xlsx"
        buffer.seek(0)
        base = "/api/v1/clients/children/import/"
        analyzed = self.api.post(f"{base}analyze/", {"file": buffer}, format="multipart")
        if analyzed.status_code != 200:
            return f"разбор: {analyzed.status_code}"
        buffer.seek(0)
        mapping = analyzed.data.get("mapping") or {}
        preview = self.api.post(
            f"{base}preview/",
            {"file": buffer, "mapping": json.dumps(mapping)},
            format="multipart",
        )
        job_id = (preview.data or {}).get("job_id")
        if not job_id:
            return f"сухой прогон: {preview.status_code}"
        # Сухой прогон идёт в очереди; импорт можно запустить только после него.
        for _ in range(60):
            if ImportJob.objects.get(pk=job_id).status not in ("pending", "running"):
                break
            time.sleep(1)
        confirmed = self.api.post(f"{base}confirm/", {"job_id": job_id}, format="json")
        return (
            "проведён"
            if confirmed.status_code in (200, 201, 202)
            else (f"запуск: {confirmed.status_code}")
        )
