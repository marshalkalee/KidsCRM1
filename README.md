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
3. Поднять всё: Postgres, Redis, backend, nginx (соберётся сам при первом
   запуске).
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
   `/admin/`. Логи: `docker compose logs -f backend` / `nginx`.
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

## Дальше

- Ветки, коммиты, PR — [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Архитектурные решения — [`docs/adr/`](docs/adr/).
- Контракты между доменами — `docs/contracts.md` (на момент написания —
  в ветке `feature/domain-contracts`, переносится в `main` при мерже).
