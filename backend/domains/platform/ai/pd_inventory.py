# ruff: noqa: E501 — описания функций: связный текст, резать ради длины хуже для чтения.
"""
Что ИИ-функции отправляют во внешнюю модель (TRU-156, ТЗ п. 8 и 10.3).

Это опись фактического положения, а не желаемого: её сверяет
tests_pd_flow.py — подменяет модель, прогоняет каждую функцию на данных с
известными метками (фамилия ребёнка, телефон, дата рождения, медзаметка…)
и смотрит, какие метки ушли в запрос. Код начал отправлять новое — тест
падает, пока опись не обновлена; обновление описи — повод для решения
(docs/adr/0008-ai-boundaries.md), а не формальность.

Категории — то, что ловит тест по меткам в данных CRM. INPUT — функция
отправляет то, что сотрудник сам вставил или загрузил (текст, фото, файл):
что в нём, код не контролирует.
"""

CHILD_NAME = "child_name"  # ФИО ребёнка
BIRTH_DATE = "birth_date"  # дата рождения ребёнка
MEDICAL = "medical"  # медицинские заметки
PARENT_NAME = "parent_name"  # ФИО родителя / контакта заявки
PHONE = "phone"  # номер телефона
EMAIL = "email"
STAFF_NAME = "staff_name"  # ФИО сотрудника
INPUT = "input"  # текст, фото или файл от сотрудника

# Функция → эндпоинт (route — имя в ai/urls.py), кто может вызвать, сколько
# запросов к модели на действие, что уходит (sends) и пояснение. Инструменты
# чата («chat:…») — то, что модель получает, когда сама запрашивает данные.
LEADS = "владелец, управляющий, администратор"
ALL = "все сотрудники"
CHAT = "владелец, управляющий, администратор (через чат)"

INVENTORY = {
    "lead_from_text": {
        "route": "lead-from-text",
        "who": LEADS,
        "calls": "1",
        "sends": {INPUT, PARENT_NAME, PHONE},
        "what": "Вставленное сообщение родителя целиком: имя, телефон, имя ребёнка.",
    },
    "lead_message": {
        "route": "lead-message",
        "who": LEADS,
        "calls": "1",
        "sends": {PARENT_NAME, CHILD_NAME},
        "what": "Имя родителя и ребёнка из заявки, возраст, направление, статус, комментарии. Телефона нет.",
    },
    "search": {
        "route": "search",
        "who": ALL,
        "calls": "1",
        "sends": {INPUT},
        "what": "Только текст запроса и справочники центра (филиалы, направления).",
    },
    "attendance_photo": {
        "route": "attendance-photo",
        "who": ALL + " (преподаватель — свои занятия)",
        "calls": "1",
        "sends": {INPUT},
        "what": "Фото бумажного журнала — на нём рукописные имена детей. Список группы в модель не уходит, сопоставление у нас.",
    },
    "import_clean": {
        "route": "import-clean",
        "who": LEADS,
        "calls": "1 на файл",
        "sends": {INPUT, CHILD_NAME, PARENT_NAME, PHONE},
        "what": "Весь загруженный файл клиентов: ФИО, даты рождения, телефоны родителей.",
    },
    "reminders": {
        "route": "reminders",
        "who": LEADS,
        "calls": "1 на пачку до 50 детей",
        "sends": {CHILD_NAME, PARENT_NAME},
        "what": "Имена детей и плательщиков, суммы долга, даты абонемента. Телефонов нет.",
    },
    "communication_note": {
        "route": "communication-note",
        "who": ALL,
        "calls": "1",
        "sends": {INPUT},
        "what": "Только текст заметки о звонке, который ввёл сотрудник.",
    },
    "child_brief": {
        "route": "child-brief",
        "who": ALL + " (включая преподавателя)",
        "calls": "1",
        "sends": {CHILD_NAME},
        "what": "«Перед звонком»: имя ребёнка, посещаемость, абонемент и долг (если роли можно), последние коммуникации. Медзаметки — нет (с 05.10.2026).",
    },
    "lead_groups": {
        "route": "lead-groups",
        "who": LEADS,
        "calls": "1",
        "sends": set(),
        "what": "Возраст, направление, филиал, пожелания из комментариев и группы с местами — без имён.",
    },
    "daily_plan": {
        "route": "daily-plan",
        "who": ALL,
        "calls": "1",
        "sends": set(),
        "what": "Счётчики дня (заявки, долги, занятия) — без имён.",
    },
    "rejection_reason": {
        "route": "rejection-reason",
        "who": LEADS,
        "calls": "1",
        "sends": {INPUT},
        "what": "Текст объяснения отказа и список причин центра.",
    },
    "chat": {
        "route": "chat",
        "who": CHAT,
        "calls": "1–8 (модель сама запрашивает данные инструментами ниже)",
        "sends": {INPUT, STAFF_NAME},
        "what": "Вопрос сотрудника, история чата, имя и роль спрашивающего. Данные CRM — через инструменты.",
    },
    "chat:attention_today": {"sends": set(), "what": "Счётчики «требует внимания»."},
    "chat:branches": {"sends": set(), "what": "Филиалы."},
    "chat:directions": {"sends": set(), "what": "Направления."},
    "chat:staff": {"sends": {STAFF_NAME}, "what": "ФИО и роли сотрудников."},
    "chat:search": {"sends": {CHILD_NAME}, "what": "Найденные дети и родители по имени."},
    "chat:children": {
        "sends": {CHILD_NAME, BIRTH_DATE},
        "what": "Список детей: ФИО, дата рождения, группы, абонемент, долг.",
    },
    "chat:child_card": {
        "sends": {CHILD_NAME, BIRTH_DATE},
        "what": "Карточка ребёнка: ФИО, дата рождения, группы, абонементы, события. Медзаметки — нет (с 05.10.2026).",
    },
    "chat:child_payments": {
        "sends": {PARENT_NAME, STAFF_NAME},
        "what": "Оплаты ребёнка: плательщик, кто принял, суммы.",
    },
    "chat:child_attendance": {"sends": set(), "what": "Посещения ребёнка."},
    "chat:parent_card": {
        "sends": {PARENT_NAME, CHILD_NAME},
        "what": "Карточка родителя: ФИО, дети, деньги. Телефонов и почты нет.",
    },
    "chat:debtors": {
        "sends": {CHILD_NAME, PARENT_NAME},
        "what": "Должники: ребёнок, плательщик, сумма.",
    },
    "chat:renewals": {
        "sends": set(),
        "what": "Продления (в тестовых данных пусто — при данных уходят имена детей).",
    },
    "chat:lessons": {"sends": {STAFF_NAME}, "what": "Занятия и преподаватели."},
    "chat:unmarked_yesterday": {"sends": set(), "what": "Неотмеченные занятия."},
    "chat:groups": {"sends": set(), "what": "Группы и заполняемость."},
    "chat:group_members": {"sends": {CHILD_NAME}, "what": "Состав группы: ФИО детей."},
    "chat:leads": {
        "sends": {PARENT_NAME, CHILD_NAME},
        "what": "Заявки: имя родителя и ребёнка, статус.",
    },
    "chat:lead": {"sends": {PARENT_NAME, CHILD_NAME}, "what": "Заявка целиком без телефона."},
    "chat:analytics_catalog": {"sends": set(), "what": "Список метрик."},
    "chat:metrics": {"sends": set(), "what": "Числа аналитики."},
    "chat:breakdown": {"sends": set(), "what": "Разрезы аналитики."},
    "chat:sales_funnel": {"sends": set(), "what": "Воронка — числа."},
    "chat:lead_sources": {"sends": set(), "what": "Источники заявок — числа."},
    "chat:group_occupancy": {"sends": set(), "what": "Заполняемость — числа."},
}
