"""
СТАРЫЙ веб (Django-шаблоны, до TRU-88). Для frontend2 вкладки подключаются
в frontend2/src/components/child-card/tabs.js — см. docs/contracts.md, §6.

Контракт вкладки карточки ребёнка (ТЗ п. 4.1) — интерфейс, по которому
Дарья ("Посещения") и Bekzat ("Абонементы", "Оплаты", позже "Задачи" в M2)
подключают свои вкладки без импорта чего-либо из этого домена.

Как подключить вкладку:
1. Постройте у себя в домене Django-view, который принимает один
   позиционный аргумент — child_id (UUID) — и отдаёт HTML-ФРАГМЕНТ
   (без <html>/<body>, без общей навигации) с содержимым вкладки. Это
   тот же принцип, что у AJAX-модалок форм в этом проекте (см.
   tenants/web_views.py: _is_ajax, *_form_fields.html) — контент без
   обвязки страницы, потому что карточка вставляет его в свою панель.
2. Права на просмотр/действия внутри вкладки — забота вашего домена
   (карточка проверяет только то, что пользователь вообще может видеть
   ребёнка). Если запись не найдена/чужая организация — обычный 404.
3. Зарегистрируйте вкладку в CHILD_CARD_TABS ниже: замените заглушку
   (url_name=None) на имя вашего маршрута. Порядок — по полю order.

Пока url_name is None — вкладка рисует заглушку "Скоро здесь появится..."
на клиенте, без похода на сервер (см. child_card.html).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChildCardTab:
    slug: str
    label_key: str  # ключ i18n
    label_fallback: str  # русский текст по умолчанию — как везде в проекте
    url_name: str | None  # None => пока заглушка, ничего не подключено
    order: int


CHILD_CARD_TABS = [
    ChildCardTab(
        slug="contacts",
        label_key="child_card.tab_contacts",
        label_fallback="Контакты",
        url_name="clients_web:child-tab-contacts",
        order=10,
    ),
    ChildCardTab(
        slug="communications",
        label_key="child_card.tab_communications",
        label_fallback="Коммуникации",
        url_name="clients_web:child-tab-communications",
        order=20,
    ),
    # Заглушки — подключаются другими доменами отдельными тикетами.
    ChildCardTab(
        slug="subscriptions",
        label_key="child_card.tab_subscriptions",
        label_fallback="Абонементы",
        url_name=None,
        order=30,
    ),
    ChildCardTab(
        slug="payments",
        label_key="child_card.tab_payments",
        label_fallback="Оплаты",
        url_name="payments_web:child-tab-payments",
        order=40,
    ),
    ChildCardTab(
        slug="attendance",
        label_key="child_card.tab_attendance",
        label_fallback="Посещения",
        url_name=None,
        order=50,
    ),
]


def get_child_card_tabs() -> list[ChildCardTab]:
    return sorted(CHILD_CARD_TABS, key=lambda tab: tab.order)
