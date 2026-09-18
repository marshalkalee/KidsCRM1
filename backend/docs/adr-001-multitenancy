# ADR-001: Модель мультитенантности

## Решение

Единая БД PostgreSQL. В каждой таблице поле `organization_id` (FK на `Organization`).

Фильтрация гарантируется кастомным `TenantManager` — данные доступны только через `Model.objects.for_tenant(organization)`. Прямой `.objects.all()` в бизнес-коде запрещён и не пройдёт code review.

```python
# Правильно
children = Child.objects.for_tenant(request.organization)

# Запрещено
children = Child.objects.all()
```

Все бизнес-модели наследуют абстрактный `TenantModel` с обязательным `organization` и подключённым `TenantManager`.

Кросс-тенантный доступ покрыт автотестом в CI — тенант А никогда не видит данные тенанта Б.

---

## Последствия

- Каждая новая модель обязана наследовать `TenantModel`
- Миграции простые — один `ALTER TABLE` на всех
- Бэкап одной организации — логическая выгрузка с фильтром по `organization_id`

---
