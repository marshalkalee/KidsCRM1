# Домен: platform

Владелец домена: общий фундамент — используется всеми доменами.

Приложения этого домена: core tenants users notifications tasks leads.

`core` — общие абстрактные базовые классы (`TenantModel`,
`TimestampedSoftDeleteModel`, `UUIDPrimaryKeyModel`) и baseline-миграция
(расширения PostgreSQL). Не бизнес-модель сама по себе.

- `tenants` — корень модели данных: `Organization`, `Branch`, `Room`.
  Мультифилиальность — с первого дня, N филиалов на организацию. Поля — по
  согласованной схеме `docs/db-schema-v1`, кроме `Organization.timezone`/
  `settings` (добавлены по формулировке задачи, в схеме их пока нет —
  сверить с командой).
- `users` — кастомная модель `User` (`AUTH_USER_MODEL`): `phone`+`full_name`
  вместо `username` (по db-schema-v1), привязка к организации и к
  **нескольким** филиалам (`ManyToMany`) — в db-schema-v1 у User одна
  nullable-связь `branch_id`, здесь осознанно иначе, см. докстринг
  `users/models.py`, — сверить с командой. Роль (`role`) как атрибут есть,
  сами права по ролям — отдельная задача (RBAC).

Тесты на изоляцию тенантов помечены `@tag("tenant_isolation")` — этот тег
подхватывает блокирующий job в CI (`.github/workflows/ci.yml`).
