# Схема БД v1

**Дата:** 11 сентября 2026
**Участники:** Tess, Dev 2, Dev 3
**Статус:** Принято

---

## Сущности

### Organization
Корневой тенант.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| name | varchar(255) | ✓ | Название |
| slug | varchar(100) | ✓ | Уникальный идентификатор (поддомен) |
| plan | varchar(50) | ✓ | Тариф |
| subscription_status | varchar(20) | ✓ | active / trial / suspended |
| is_active | boolean | ✓ | default=True |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

Индексы: `slug` unique

---

### Branch
Филиал организации.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| name | varchar(255) | ✓ | |
| address | text | | |
| phone | varchar(20) | | |
| working_hours | jsonb | | Часы работы по дням недели |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

---

### Child
Ребёнок.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| full_name | varchar(255) | ✓ | |
| birth_date | date | | Возраст вычисляется |
| gender | varchar(10) | | male / female |
| photo | varchar(500) | | URL фото, опционально |
| medical_notes | text | | Медицинские заметки, свободное поле |
| status | varchar(20) | ✓ | active / frozen / left |
| cause_of_leaving | text | | Причина ухода, заполняется при status=left |
| notes | text | | |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

Индексы: `(organization_id, status)`, `(organization_id, full_name)` GIN для поиска

---

### Parent
Родитель или контактное лицо.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| full_name | varchar(255) | ✓ | |
| phone | varchar(20) | ✓ | Основной телефон |
| phone_secondary | varchar(20) | | Дополнительный телефон |
| whatsapp | varchar(20) | | Может отличаться от phone |
| notes | text | | |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

Индексы: `(organization_id, phone)` unique

---

### ChildParent (M2M)
Связь ребёнка и родителя. Не FK на Child.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| child_id | uuid | ✓ | FK → Child |
| parent_id | uuid | ✓ | FK → Parent |
| role | varchar(20) | ✓ | mother / father / guardian / other |
| is_payer | boolean | ✓ | Признак плательщика |

Индексы: `(child_id, parent_id)` unique

---

### Room
Зал внутри филиала.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| branch_id | uuid | ✓ | FK → Branch |
| name | varchar(100) | ✓ | Название зала |
| capacity | integer | | Вместимость |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

Индексы: `(organization_id, branch_id)`

---

### ChildGroup (M2M)
Связь ребёнка и группы.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| child_id | uuid | ✓ | FK → Child |
| group_id | uuid | ✓ | FK → Group |
| enrolled_at | date | ✓ | Дата зачисления |
| left_at | date | | Дата выхода, null = активен |

Индексы: `(child_id, group_id)` unique

> Направления ребёнка вычисляются через группы: `Child → ChildGroup → Group → Direction`

---

### Direction
Направление (балет, гимнастика, английский и т.д.).

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| name | varchar(100) | ✓ | |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |


---
###DirectionBranch (M2M)

Какие направления доступны в каком филиале.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| direction_id | uuid | ✓ | FK → Direction |
| branch_id | uuid | ✓ | FK → Branch |


---

### Group
Учебная группа.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| branch_id | uuid | ✓ | FK → Branch |
| direction_id | uuid | ✓ | FK → Direction |
| teacher_id | uuid | | FK → User |
| name | varchar(100) | ✓ | |
| age_min | integer | | Минимальный возраст |
| age_max | integer | | Максимальный возраст |
| capacity | integer | | Вместимость для расчёта заполняемости |
| schedule_template | jsonb | | Регулярное расписание: дни недели + время + зал |
| status | varchar(20) | ✓ | active / archived |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

---

### Lesson
Материализованный экземпляр занятия. Генерируется заранее из шаблона группы, не вычисляется на лету.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| group_id | uuid | | FK → Group, null для индивидуальных |
| room_id | uuid | | FK → Room |
| teacher_id | uuid | | FK → User |
| started_at | timestamptz | ✓ | |
| ended_at | timestamptz | ✓ | |
| status | varchar(20) | ✓ | scheduled / completed / cancelled / rescheduled |
| original_lesson_id | uuid | | FK → Lesson, заполняется при переносе |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

Индексы: `(organization_id, group_id, started_at)`, `(organization_id, started_at)`

---

### Attendance
Посещение — пересечение занятия и ребёнка.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| lesson_id | uuid | ✓ | FK → Lesson |
| child_id | uuid | ✓ | FK → Child |
| status | varchar(20) | ✓ | present / absent / makeup |
| absence_reason | varchar(50) | | illness / family / no_reason / other |
| was_charged | boolean | ✓ | Списано ли занятие с абонемента |
| subscription_charge_id | uuid | | FK → SubscriptionCharge |
| notes | text | | |
| created_at | timestamptz | ✓ | |
| updated_at | timestamptz | ✓ | |

Индексы: `(lesson_id, child_id)` unique, `(organization_id, child_id)`

---

### SubscriptionType
Шаблон абонемента.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| name | varchar(100) | ✓ | Например: «8 занятий / месяц» |
| lessons_count | integer | | Кол-во занятий, null = безлимит |
| is_unlimited | boolean | ✓ | Безлимит на период |
| validity_days | integer | ✓ | Срок действия в днях |
| price | decimal(12,0) | ✓ | Цена в тенге |
| burns_on_miss | boolean | ✓ | Сгорают ли пропуски |
| max_freezes | integer | ✓ | Максимум заморозок, default=0 |
| makeup_deadline_days | integer | | Срок отработок в днях |
| is_active | boolean | ✓ | default=True |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

---

### Subscription
Абонемент ребёнка.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| child_id | uuid | ✓ | FK → Child |
| subscription_type_id | uuid | ✓ | FK → SubscriptionType |
| price | decimal(12,0) | ✓ | Фактическая цена (может быть со скидкой) |
| discount | decimal(12,0) | | Скидка в тенге |
| discount_reason | text | | Причина скидки |
| started_at | date | ✓ | |
| expires_at | date | ✓ | |
| status | varchar(20) | ✓ | active / expired / frozen / exhausted |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

> ⚠️ Остаток занятий не хранится счётчиком — пересчитывается:
> `lessons_count − COUNT(SubscriptionCharge WHERE subscription_id = X AND cancelled_at IS NULL)`

Индексы: `(organization_id, child_id, status)`

---

### SubscriptionCharge
Журнал списаний с абонемента. Источник правды об остатке занятий.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| subscription_id | uuid | ✓ | FK → Subscription |
| attendance_id | uuid | | FK → Attendance |
| charged_at | timestamptz | ✓ | |
| cancelled_at | timestamptz | | Отмена списания (возврат занятия) |
| notes | text | | |

---

### SubscriptionFreeze
История заморозок абонемента.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| subscription_id | uuid | ✓ | FK → Subscription |
| frozen_from | date | ✓ | |
| frozen_to | date | ✓ | |
| reason | text | | |
| created_by | uuid | ✓ | FK → User |
| created_at | timestamptz | ✓ | |

---

### Payment
Оплата абонемента. Один абонемент — несколько платежей (частичная оплата).

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| subscription_id | uuid | ✓ | FK → Subscription |
| amount | decimal(12,0) | ✓ | Сумма в тенге |
| method | varchar(20) | ✓ | kaspi / cash / card / other |
| paid_at | timestamptz | ✓ | |
| received_by | uuid | | FK → User |
| notes | text | | |
| created_at | timestamptz | ✓ | |

> Задолженность = `subscription.price − SUM(payments.amount)` — вычисляется, не хранится.

Индексы: `(organization_id, subscription_id)`

---

### Lead
Заявка из воронки продаж.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| branch_id | uuid | | FK → Branch |
| child_name | varchar(255) | ✓ | |
| parent_name | varchar(255) | | |
| phone | varchar(20) | ✓ | |
| direction_id | uuid | | FK → Direction |
| source | varchar(50) | | instagram / website / referral / other |
| status | varchar(20) | ✓ | new / in_progress / trial_scheduled / converted / rejected |
| rejection_reason | text | | Обязательно при status=rejected |
| assigned_to | uuid | | FK → User |
| trial_lesson_id | uuid | | FK → Lesson |
| converted_child_id | uuid | | FK → Child, заполняется при конвертации |
| created_at | timestamptz | ✓ | |
| updated_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

Индексы: `(organization_id, status)`, `(organization_id, phone)`

---

### Task
Задача администратору. Создаётся вручную или автоматически системой.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| type | varchar(50) | ✓ | call_back / remind_payment / schedule_trial / other |
| assigned_to | uuid | | FK → User |
| created_by | uuid | | FK → User, null = система |
| title | varchar(255) | ✓ | |
| due_date | date | | |
| status | varchar(20) | ✓ | open / in_progress / done / cancelled |
| priority | varchar(10) | ✓ | low / medium / high |
| content_type | varchar(50) | | Тип связанной сущности: child / lead / subscription |
| object_id | uuid | | ID связанной сущности |
| created_at | timestamptz | ✓ | |
| updated_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

Индексы: `(organization_id, assigned_to, status)`, `(organization_id, due_date)`

---

### CommunicationLog
История контактов с родителем.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| parent_id | uuid | | FK → Parent |
| lead_id | uuid | | FK → Lead |
| author_id | uuid | ✓ | FK → User |
| channel | varchar(20) | ✓ | call / whatsapp / in_person / other |
| summary | text |  | |
| contacted_at | timestamptz | ✓ | |
| created_at | timestamptz | ✓ | |

> Заполняется `parent_id` или `lead_id`, не оба сразу.

---

### User
Сотрудник системы.

| Поле | Тип | Обязательно | Описание |
|---|---|---|---|
| id | uuid | ✓ | PK |
| organization_id | uuid | ✓ | FK → Organization |
| branch_id | uuid | | FK → Branch, null = доступ ко всем филиалам |
| full_name | varchar(255) | ✓ | |
| phone | varchar(20) | ✓ | |
| role | varchar(20) | ✓ | owner / manager / admin / teacher / accountant |
| is_active | boolean | ✓ | default=True |
| created_at | timestamptz | ✓ | |
| deleted_at | timestamptz | | Soft delete |

Индексы: `(organization_id, phone)` unique, `(organization_id, role)`

---

## Сквозные инварианты

- `organization_id` — в каждой таблице, обязательное поле
- `deleted_at` — soft delete везде, физического удаления нет
- Все `DateTime` — `timestamptz` (с таймзоной), хранятся в UTC
- Деньги — `decimal(12,0)` в тенге, без тиынов, без float
- PK — UUID везде

---

## Открытые вопросы (решить на Discovery)

> Не решены наугад — ждут уточнения у заказчика

1. **Заморозка** — приостанавливает только срок (`expires_at`) или также блокирует списания?
2. **Отработка** — новая `Attendance` в другой группе или перепривязка существующей?
3. **Максимум заморозок** — ТЗ п. 13 не конкретизирует число
4. **Безлимитный абонемент** — как считается заполняемость и списания?

---

## ER-диаграмма

```mermaid
erDiagram
    Organization ||--o{ Branch : has
    Organization ||--o{ User : has
    Organization ||--o{ Child : has
    Organization ||--o{ Parent : has
    Organization ||--o{ Direction : has
    Organization ||--o{ Lead : has
    Organization ||--o{ Task : has

    Child ||--o{ ChildParent : linked
    Parent ||--o{ ChildParent : linked
    Child ||--o{ ChildGroup : enrolled
    Group ||--o{ ChildGroup : has
    ChildParent {
        string role
        boolean is_payer
    }

    Branch ||--o{ Room : has
    Direction ||--o{ Group : has
    Branch ||--o{ Group : has
    Group ||--o{ Lesson : generates
    Room ||--o{ Lesson : hosts

    Lesson ||--o{ Attendance : has
    Child ||--o{ Attendance : has

    Child ||--o{ Subscription : has
    SubscriptionType ||--o{ Subscription : template
    Subscription ||--o{ SubscriptionFreeze : has
    Subscription ||--o{ Payment : has
    Subscription ||--o{ SubscriptionCharge : has
    SubscriptionCharge ||--o| Attendance : charges

    Lead ||--o| Lesson : trial
    Lead ||--o| Child : converts_to

    Task }o--o| User : assigned_to
    CommunicationLog }o--o| Parent : about
    CommunicationLog }o--o| Lead : about
```

---
