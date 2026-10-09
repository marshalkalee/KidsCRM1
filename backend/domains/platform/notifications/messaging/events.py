"""
События, о которых система пишет родителю (TRU-168, ADR-0010 п. 3).

Вызывающий код говорит **что** случилось (событие и подстановки), а не
**как** отправить. Тексты по умолчанию — здесь, на ru и kk; центр может
поправить email-текст под себя (MessageTemplate). Подстановки —
`{child}` и т. п.; других в тексте быть не может (проверяется при
сохранении), чтобы шаблон не упал на отправке.

Новое событие — запись в EVENTS; кто и когда его вызывает — TRU-171.
"""

from dataclasses import dataclass, field

from ..models import MessageCategory

# Подстановки, которые есть у любого события.
COMMON_VARS = {
    "parent": "Имя родителя",
    "center": "Название центра",
}


@dataclass(frozen=True)
class Event:
    key: str
    label: str
    category: str
    variables: dict = field(default_factory=dict)
    # {"ru": (тема, текст), "kk": (тема, текст)} — email.
    email: dict = field(default_factory=dict)
    # {"ru": (заголовок, строка)} — push: коротко, одно действие.
    push: dict = field(default_factory=dict)
    # Куда открыть кабинет по нажатию на push.
    link: str = "/parent"

    @property
    def all_variables(self) -> dict:
        return {**COMMON_VARS, **self.variables}


EVENTS = {
    e.key: e
    for e in [
        Event(
            key="subscription_ending",
            label="Абонемент заканчивается",
            category=MessageCategory.UTILITY,
            variables={"child": "Имя ребёнка", "left": "Сколько осталось (занятий или дней)"},
            email={
                "ru": (
                    "{center}: заканчивается абонемент — {child}",
                    "Здравствуйте, {parent}!\n\n"
                    "{child}: заканчивается абонемент, осталось {left}. "
                    "Чтобы занятия шли без перерыва, продлите его у администратора.\n\n"
                    "{center}",
                ),
                "kk": (
                    "{center}: {child} абонементі аяқталып жатыр",
                    "Сәлеметсіз бе, {parent}!\n\n"
                    "{child} абонементі аяқталып жатыр: {left} қалды. "
                    "Сабақтар үзіліссіз жалғасуы үшін әкімшіден ұзартыңыз.\n\n"
                    "{center}",
                ),
            },
            push={
                "ru": (
                    "Заканчивается абонемент",
                    "{child}: осталось {left}. Продлите у администратора.",
                ),
                "kk": ("Абонемент аяқталып жатыр", "{child}: {left} қалды. Әкімшіден ұзартыңыз."),
            },
            link="/parent/subscription",
        ),
        Event(
            key="payment_due",
            label="Напоминание об оплате",
            category=MessageCategory.UTILITY,
            variables={"child": "Имя ребёнка", "amount": "Сумма к оплате"},
            email={
                "ru": (
                    "{center}: напоминание об оплате",
                    "Здравствуйте, {parent}!\n\n"
                    "Напоминаем об оплате занятий. {child}: к оплате {amount}. "
                    "Если уже оплатили — спасибо, просто не обращайте внимания.\n\n"
                    "{center}",
                ),
                "kk": (
                    "{center}: төлем туралы еске салу",
                    "Сәлеметсіз бе, {parent}!\n\n"
                    "{child} сабақтарының төлемін еске саламыз: төлеуге {amount}. "
                    "Егер төлеп қойсаңыз — рақмет, назар аудармаңыз.\n\n"
                    "{center}",
                ),
            },
            push={
                "ru": ("Напоминание об оплате", "{child}: к оплате {amount}."),
                "kk": ("Төлем туралы еске салу", "{child}: төлеуге {amount}."),
            },
            link="/parent/subscription",
        ),
        Event(
            key="lesson_cancelled",
            label="Занятие отменено или перенесено",
            category=MessageCategory.UTILITY,
            variables={
                "child": "Имя ребёнка",
                "group": "Группа",
                "when": "Дата и время занятия",
                "note": "Что вместо (перенос, отработка)",
            },
            email={
                "ru": (
                    "{center}: изменение в расписании",
                    "Здравствуйте, {parent}!\n\n"
                    "{child}: занятие в группе «{group}» {when} отменено. {note}\n\n"
                    "{center}",
                ),
                "kk": (
                    "{center}: кестедегі өзгеріс",
                    "Сәлеметсіз бе, {parent}!\n\n"
                    "{child} «{group}» тобындағы {when} сабағы болмайды. {note}\n\n"
                    "{center}",
                ),
            },
            push={
                "ru": ("Занятие отменено", "{child}, «{group}», {when}. {note}"),
                "kk": ("Сабақ болмайды", "{child}, «{group}», {when}. {note}"),
            },
            link="/parent/schedule",
        ),
        Event(
            key="announcement",
            label="Новое объявление центра",
            category=MessageCategory.UTILITY,
            variables={"title": "Заголовок объявления"},
            email={
                "ru": (
                    "{center}: {title}",
                    "Здравствуйте, {parent}!\n\n"
                    "В кабинете родителя новое объявление: «{title}».\n\n"
                    "{center}",
                ),
                "kk": (
                    "{center}: {title}",
                    "Сәлеметсіз бе, {parent}!\n\n"
                    "Ата-ана кабинетінде жаңа хабарландыру: «{title}».\n\n"
                    "{center}",
                ),
            },
            push={
                "ru": ("{center}: объявление", "{title}"),
                "kk": ("{center}: хабарландыру", "{title}"),
            },
            link="/parent/announcements",
        ),
    ]
}

LANGUAGES = ("ru", "kk")

# Имя ребёнка в русских текстах стоит отдельно («Алия: …»): подстановка не
# склоняется, и «оплате занятий Алия» читалось бы как ошибка.

# Подвал письма — не редактируется центром: отписка обязательна (ТЗ п. 10.3,
# правила Meta и почтовых провайдеров).
UNSUBSCRIBE_FOOTER = {
    "ru": "\n\n—\nВы получили это письмо как родитель ученика центра «{center}». "
    "Не хотите получать такие письма: {unsubscribe_url}",
    "kk": "\n\n—\nБұл хатты «{center}» орталығы оқушысының ата-анасы ретінде алдыңыз. "
    "Мұндай хаттарды алғыңыз келмесе: {unsubscribe_url}",
}
