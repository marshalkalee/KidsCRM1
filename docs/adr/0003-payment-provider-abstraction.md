# ADR-003: Абстракция провайдера оплаты

## Статус

Принято, реализовано в TRU-65. Ничего из описанного ниже не подключено —

ТЗ п. 12 прямо помечает эквайринг как BACKLOG, трогать сейчас нечего.

## Контекст

ТЗ п. 4.4: «архитектура платежей должна позволять добавить платёжный шлюз

без переделки модели Payment». Ручная фиксация — временное состояние MVP,

не постоянное.

## Решение

Ручная фиксация — `Payment.Provider.MANUAL`, один из провайдеров, а не

единственный путь. Общий протокол `PaymentProvider` `payments/providers.py`,

метод `record()`), `ManualProvider` — единственная реализация сейчас,

сразу выставляет `status=CONFIRMED` (администратор уже проверил оплату

глазами). Поля под внешнюю транзакцию в модели уже есть, но пустые:

`provider_transaction_id`, `status`, `confirmed_at`, `provider_raw_response`.

Уникальность `provider_transaction_id` — готовая идемпотентность под

повторные вебхуки (NULL не конфликтует с NULL в Postgres, ручные оплаты

не задеты).

## Сценарий подключения эквайринга (только на бумаге, не реализовано)

​```python

class KaspiGatewayProvider(PaymentProvider):

    def record(self, *, subscription, amount, transaction_id, raw_response, actor=None, comment=""):

        payment, created = Payment.objects.get_or_create(

            provider=Payment.Provider.KASPI_GATEWAY,

            provider_transaction_id=transaction_id,

            defaults=dict(

                organization=subscription.organization, subscription=subscription,

                amount=to_tenge(amount), method=Payment.Method.KASPI_TRANSFER,

                status=Payment.Status.PENDING, provider_raw_response=raw_response,

                received_by=actor, comment=comment,

            ),

        )

        return payment  # created=False на повторный вебхук — идемпотентно

​```

Что реально меняется при подключении:

1. Новое значение `Payment.Provider.KASPI_GATEWAY` в `TextChoices` — миграции

   базы не требует: колонка как была `CharField`, так и остаётся, choices

   проверяются на уровне Django, не БД.

2. Новый класс `KaspiGatewayProvider`, тот же протокол `PaymentProvider`.

3. Новый эндпоинт-приёмник вебхука, вызывающий его `record()`.

Ни одно из трёх не трогает существующие поля `Payment` и не требует

`makemigrations`.

## Открыто

Автоматическая сверка с банковской выпиской — BACKLOG (ТЗ п. 12), не сюда.

## Обновление (05.10.2026): удалённая оплата убрана

По решению Анель удалённая оплата Kaspi убрана целиком: `PaymentRequest` (миграция `payments/0007`), `remote.py`, `kaspi.py`, вебхук, `KaspiPayProvider`, настройка `kaspi_payment_details`. При оплате — только `ManualProvider` с выбором способа. Раздел ниже — история решения; вернуть — из PR #130.

## Обновление (01.10.2026): удалённая оплата через Kaspi (история)

Сделано по схеме выше, но с отдельной сущностью «счёт»:

- `PaymentRequest` — счёт родителю: телефон, сумма, статус «ждёт оплаты /
  оплачен / отменён / истёк». Пока счёт не оплачен, это не оплата: долг и
  выручка считают только подтверждённые `Payment`, поэтому ждущий счёт их не
  трогает, и `Payment` не засоряется счетами, которые так и не оплатили.
- Оплаченный счёт создаёт обычную `Payment` через `KaspiPayProvider`
  (`provider=kaspi_pay`, `method=kaspi_transfer`, сразу CONFIRMED).
  `provider_transaction_id` = организация + номер операции Kaspi — повторный
  вебхук возвращает ту же оплату, как и было задумано.
- Два канала (`payments/remote.py`):
  - **сообщение** (по умолчанию, без договора с Kaspi): текст родителю с
    суммой и реквизитами центра (`Organization.settings["kaspi_payment_details"]`)
    уходит в WhatsApp, оплату подтверждает администратор кнопкой
    «Оплата пришла»;
  - **шлюз** (`KASPI_PAY_GATEWAY`): счёт уходит в Kaspi на телефон
    родителя, оплату подтверждает вебхук `POST /api/v1/payments/kaspi/webhook/`.
    Интерфейс — `payments/kaspi.py` `KaspiGateway`; реализован только
    тестовый шлюз `fake` (стенд и тесты). Класс для настоящего Kaspi пишется
    по их документации после договора — формат API и подписи вебхука Kaspi
    выдаёт вместе с доступом.

Значение `Payment.Provider.KASPI_PAY` добавлено миграцией вместе с таблицей
счетов (Django пишет изменение choices в миграцию, схема `payment` не меняется).
