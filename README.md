# KidsCRM

SaaS CRM для детских образовательных и спортивных центров. Стек и формат
API зафиксированы в [ADR-002](docs/adr/); доменное деление кода описано в
[`backend/domains/README.md`](backend/domains/README.md).

## Стек

- Один Django-проект: Python 3.12, Django 5, DRF, PostgreSQL, Celery + Redis.
- Веб — серверный рендеринг Django-шаблонами (`backend/templates/`) +
  jQuery 3.5.1 и вендорные плагины без сборщика (Bootstrap, Select2,
  DataTables, FullCalendar, Chart.js и др., `backend/static/site/js/vendor/`).
  Никакого `package.json`/webpack/Vite — см. ADR-002.
- API: REST, версионирование через `/api/v1/` — на него же ходят AJAX-вызовы
  со страниц, отдельного «внутреннего» API нет.
- nginx перед backend (`infra/nginx/nginx.conf`) — единая точка входа, тот
  же путь запроса локально и в проде. Статику отдаёт сам Django через
  whitenoise, nginx её не подхватывает отдельно — см. ADR-002.
- `worker` — Celery worker на той же кодовой базе, что и `backend`, слушает
  Redis. Реальных фоновых задач пока нет (см. `backend/config/celery.py`) —
  сервис поднят, чтобы окружение у всех троих было одинаковым с первого дня.

## Быстрый старт с нуля

Разработка — через Docker (как и в других продуктах AEM Solutions): никакого
venv, зависимости ставятся прямо в образ. Нужны: **Docker**. Node/npm не
нужны — фронтенд не собирается.

1. Клонировать репозиторий и перейти в него.
   ```bash
   git clone https://github.com/marshalkalee/KidsCRM1.git && cd KidsCRM1
   ```
2. Завести `.env` из примера.
   ```bash
   cp backend/.env.example backend/.env
   ```
3. Поднять всё: Postgres, Redis, backend, worker, nginx (соберётся сам при
   первом запуске).
   ```bash
   docker compose up -d --build
   ```
4. Применить миграции и собрать i18n-бандл (нужно один раз и после правки
   словарей в `backend/i18n_src/`).
   ```bash
   docker compose exec backend python manage.py migrate
   docker compose exec backend python scripts/build_i18n_bundle.py
   ```
5. Открыть в браузере.

   Основной вход — `http://localhost/` (через nginx, `infra/nginx/nginx.conf`
   — тот же путь запроса, что и в проде). `http://localhost:8000/` — тот же
   backend напрямую, без nginx, для отладки. API — `/api/v1/`, админка —
   `/admin/`. Логи: `docker compose logs -f backend` / `worker` / `nginx`.
6. Установить pre-commit хуки (один раз после клонирования; сам pre-commit
   ставится на хост, не в контейнер — он вызывается git-хуком при `git commit`).
   ```bash
   pip install pre-commit
   pre-commit install
   ```

Итого — 6 шагов от клона до работающего сервера. Если что-то не завелось
по этой инструкции — это баг README, а не повод спрашивать в чате команды.

Если на машине уже занят порт 5432 (например, локально установленным
Postgres для другого проекта) — это не проблема: наш Postgres слушает хост
на 5433 (`docker-compose.yml`), backend ходит к нему по внутренней
docker-сети (`db:5432`), порт 5432 на хосте вообще не используется.

Вендорные JS/CSS-библиотеки (jQuery, Bootstrap и т.д.) в репозиторий пока
не положены — см. [`backend/static/site/js/vendor/README.md`](backend/static/site/js/vendor/README.md).
Без них сервер и страницы всё равно поднимаются (шаги выше пройдут), но
без стилей и интерактивности плагинов.

## Линтер и форматтер

Одна команда проверяет всё (Python-код и Django-шаблоны):

```bash
pre-commit run --all-files
```

Она же выполняется автоматически при `git commit` после шага 6 (сами
`ruff`/`djlint` pre-commit ставит в собственный изолированный кэш — Docker
и `backend/.venv` тут не нужны). Точечно, внутри контейнера:

```bash
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
docker compose exec backend djlint templates --profile django --check
```

## Миграции

Инструмент — встроенные миграции Django, ничего дополнительного не
подключается (это уже часть выбранного стека, ADR-002). Работают per-app:
у каждого Django-приложения (`tenants`, `users`, `clients`, ...) своя
независимая нумерация — конфликт номеров в принципе возможен только когда
**два человека одновременно меняют модели одного и того же приложения**, а
не вообще при параллельной работе троих (у каждого приложения один
доменный владелец, см. `backend/domains/README.md`).

Baseline (`domains/platform/core/migrations/0001_baseline.py`) не создаёт
таблиц — только расширение PostgreSQL `pg_trgm` (частичный/нечувствительный
к регистру поиск, ТЗ п. 4.1). Общие типы для бизнес-моделей — абстрактные
классы `TenantModel`/`TimestampedSoftDeleteModel`/`UUIDPrimaryKeyModel` в
`domains/platform/core/models.py`: UUID PK, `organization_id` обязателен,
soft delete, timestamps — по согласованной схеме (`db-schema-v1`).

Команды (внутри контейнера, `docker compose exec backend ...`):

```bash
# применить все миграции (после git pull, если появились новые)
python manage.py migrate

# статус — что применено, что нет, по каждому приложению
python manage.py showmigrations

# откатить последнюю миграцию конкретного приложения
python manage.py migrate <app> <предыдущая_миграция>
# откатить приложение полностью (до состояния "миграций не было")
python manage.py migrate <app> zero

# создать миграцию после правки models.py — всегда с описательным --name,
# не полагаться на автосгенерированное имя
python manage.py makemigrations <app> --name <короткое_описание>
```

**Правило отката**: любая миграция обязана откатываться, либо явно быть
необратимой. Django сам откатывает операции над схемой (`CreateModel`,
`AddField` и т.п.) — ничего специально делать не нужно. Для `RunPython`
(миграции данных) — всегда передавать `reverse_code`, если откат
семантически возможен; если нет — `reverse_code` не указывать вообще
(Django откажет в откате с `IrreversibleError` вместо фальшивого no-op,
который оставил бы данные в неконсистентном состоянии).

**Конфликт миграций в двух ветках** (два человека одновременно меняли один
и тот же app — редко, но если случилось):

1. Не удалять чужой файл миграции, даже если он «мешает» смержиться.
2. Перед пушем: `git pull`, затем `python manage.py makemigrations <app>` —
   Django сам предложит либо продолжить номер после чужой миграции, либо
   создать merge-миграцию.
3. Если обе миграции уже запушены как два независимых листа графа —
   `python manage.py makemigrations --merge` создаёт настоящую
   merge-миграцию с зависимостью от обеих. Не переименовывать/не
   перезаписывать номер миграции, которую кто-то уже применил у себя.

*Статус: предложено, финальное согласование — на созвоне троих (как и
другие процессные решения в этом репозитории).*

**CI**: прогонять `migrate` на чистой БД должен CI-пайплайн — это отдельная
задача (workflow ещё не заведён в этом репозитории). Команда для CI, когда
он появится: `docker compose run --rm backend python manage.py migrate`
против пустого volume.

## Дальше

- Ветки, коммиты, PR — [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Архитектурные решения — [`docs/adr/`](docs/adr/).
- Контракты между доменами — `docs/contracts.md` (на момент написания —
  в ветке `feature/domain-contracts`, переносится в `main` при мерже).
