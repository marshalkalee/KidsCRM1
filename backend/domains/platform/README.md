# Домен: platform

Владелец домена: общий фундамент — используется всеми доменами.

Приложения этого домена: core tenants users notifications tasks leads.

`core` — общие абстрактные базовые классы (`TenantModel`,
`TimestampedSoftDeleteModel`, `UUIDPrimaryKeyModel`) и baseline-миграция
(расширения PostgreSQL). Не бизнес-модель сама по себе — конкретные
сущности (Organization, Branch, ...) заводятся в задачах по доменам,
см. `docs/db-schema-v1` (согласованная схема) и раздел «Миграции» в
корневом README.
