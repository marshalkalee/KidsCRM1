# KidsCRM

SaaS CRM для детских образовательных и спортивных центров. Стек и формат
API зафиксированы в [ADR-002](backend/docs/adr-002-stack-repo-api), фронтенд —
в [ADR-004](backend/docs/adr-004-frontend-spa.md); доменное деление кода описано в
[`backend/domains/README.md`](backend/domains/README.md).

## Стек

- Backend — Django-проект: Python 3.12, Django 5, DRF, PostgreSQL, Celery + Redis.
- Веб — React-приложение `frontend2/` (Vite, Tailwind, react-router), ходит
  только в REST API `/api/v1/` с JWT (ADR-004). Идёт переезд со старого
  серверного веба (Django-шаблоны + jQuery, `backend/templates/`) — эпик
  TRU-78: старые страницы работают параллельно до TRU-88.
- API: REST, версионирование через `/api/v1/`, JWT (вход `auth/login/`,
  продление `auth/refresh/` — фронт продлевает токен сам).
- nginx (`infra/nginx/`) — единая точка входа, тот же путь запроса локально
  и в проде: отдаёт собранный `frontend2` на `/`, проксирует на Django
  `/api/`, `/admin/`, `/static/`, `/media/` и старые страницы
  (`infra/nginx/app.conf`). Образ nginx сам собирает фронт
  (`infra/nginx/Dockerfile`).
- `worker` — Celery worker на той же кодовой базе, что и `backend`, слушает
  Redis. Реальных фоновых задач пока нет (см. `backend/config/celery.py`) —
  сервис поднят, чтобы окружение у всех троих было одинаковым с первого дня.

## Быстрый старт с нуля

Разработка — через Docker (как и в других продуктах AEM Solutions): никакого
venv, зависимости ставятся прямо в образ. Для запуска нужен только
**Docker** — фронт собирается внутри образа nginx. Node 22+ нужен, только
если разрабатываете фронт с горячей перезагрузкой (см. «Фронтенд» ниже).

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
5. (По желанию) наполнить свою организацию демо-данными — чтобы экраны
   смотреть на «живом» центре: 3 филиала, 20 групп, ~150 детей с
   родителями, абонементы с долгами, расписание, коммуникации. Только при
   `DEBUG=True`, повторный запуск ничего не дублирует.
   ```bash
   docker compose exec backend python manage.py seed_demo --phone +7XXXXXXXXXX
   ```
6. Открыть в браузере.

   Основной вход — `http://localhost/` — React-приложение (через nginx, тот
   же путь запроса, что и в проде). API — `/api/v1/`, админка — `/admin/`.
   Старые серверные страницы на время переезда — по своим адресам со слешем
   на конце: `/clients/children/`, `/settings/organization/`, `/groups/`,
   вход в них — `/login/`. `http://localhost:8000/` — backend напрямую, без
   nginx, для отладки. Логи: `docker compose logs -f backend` / `worker` / `nginx`.
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

## Фронтенд (frontend2)

После правок фронта образ nginx нужно пересобрать:

```bash
docker compose up -d --build nginx
```

Для разработки с горячей перезагрузкой — dev-сервер Vite поверх того же
backend (запросы `/api` он проксирует на `http://localhost:80`):

```bash
cd frontend2
npm ci
npm run dev      # http://localhost:5173
npm run lint     # oxlint
npm run build
```

Все запросы к API идут через `src/api/axios.js`: он подставляет токен и
продлевает его по refresh при 401 (если refresh протух — выход на `/login`).

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

## CI

Пайплайн — `.github/workflows/ci.yml`, запускается на каждый PR (в `main`
и `develop`) и на пуш в них. Пять независимых job'ов, идут параллельно:

| Job | Что делает |
|---|---|
| `lint` | `ruff check`/`ruff format --check`/`djlint` — аннотации ruff видны прямо на диффе PR (`--output-format=github`), не только в логе. |
| `test` | Поднимает Postgres+Redis (`services:` GitHub Actions, не наш `docker-compose.yml` — так же, как CI в других продуктах AEM Solutions: `pip install` прямо на раннере, без Docker), гоняет `migrate` на пустой БД + тесты + `coverage report`. Отчёт о покрытии — без порога, но виден в Summary прогона, не только в логе. |
| `tenant-isolation` | Отдельный **блокирующий** job: `python manage.py test --tag=tenant_isolation`. Конвенция — любой тест на изоляцию тенантов помечается `@tag("tenant_isolation")` (`django.test.tag`). Пока в репозитории нет бизнес-моделей с `organization_id` — тестов с этим тегом нет, job проходит на 0 тестах. Это не подделка проверки: как только появится первая такая модель, тест на её изоляцию обязан получить тег — иначе он не покрыт этим job'ом. |
| `frontend` | `frontend2`: `npm ci`, `npm run lint` (oxlint), `npm run build`. |
| `build` | Собирает образы: `backend/Dockerfile` и nginx со сборкой frontend2 (`infra/nginx/Dockerfile`) — те же, что локально и на staging. |

Все команды локально проверены (venv + реальный Postgres/Redis, без
Docker для самого прогона — как и будет в CI).

**Обязательно вручную, я не могу это сделать сама**: включить branch
protection в GitHub, чтобы PR нельзя было влить с красным пайплайном —
это настройка репозитория, не файл в коде.

1. GitHub → Settings → Branches → Add rule (для `main`, повторить для `develop`).
2. Включить **Require status checks to pass before merging**.
3. Выбрать все пять job'ов (`lint`, `test`, `tenant-isolation`, `frontend`, `build`) —
   появятся в списке только после первого прогона пайплайна на любом PR.
4. Включить **Require branches to be up to date before merging**.

*До этого шага критерий «PR нельзя влить с красным пайплайном» не
выполнен — пайплайн будет показывать красный/зелёный статус, но
физически смержить можно будет в любом случае.*

## Staging и деплой

### Статус: инфраструктура готова, живого staging нет

ADR-002 оставляет хостинг-провайдера и регион открытым вопросом Discovery
— конкретного сервера пока нет физически. Всё ниже — то, что заработает
на любом VPS, как только провайдер выберется, без правок кода:
`.github/workflows/deploy-staging.yml`, `docker-compose.staging.yml`,
`infra/nginx/nginx.staging.conf`, `infra/scripts/backup.sh`/`restore.sh`.

Из критериев приёмки этого тикета реально проверено, а что — нет:

| Критерий | Статус |
|---|---|
| Мёрдж в main выкатывается на staging автоматически | Workflow написан и корректен по структуре, но не может быть проверен без реального сервера — секретов (`STAGING_SSH_HOST` и т.п.) нет |
| Staging открывается по HTTPS с телефона | Конфиг nginx+certbot готов, но без реального домена сертификат физически не выпустить — нечего открывать |
| Бэкап по расписанию + проверенное восстановление | **Проверено реально** — на локальном стеке: сняла бэкап, снесла таблицу, восстановила скриптом `restore.sh`, данные вернулись. Расписание (`cron`) не проверено — нет сервера, где его ставить |
| Секреты не в репозитории и записано, кто имеет доступ | Сделано — см. ниже |

### Как поднять на реальном сервере (когда появится)

1. Скопировать репозиторий на сервер, создать `backend/.env` из
   [`backend/.env.staging.example`](backend/.env.staging.example) с реальными секретами.
2. В `infra/nginx/nginx.staging.conf` заменить `STAGING_DOMAIN` на реальный домен.
3. Первый запуск — без HTTPS (см. комментарий в начале
   `nginx.staging.conf`), выпустить сертификат через `certbot`, затем
   включить блок `:443`.
4. `docker compose -f docker-compose.staging.yml up -d --build`,
   `docker compose -f docker-compose.staging.yml exec backend python manage.py migrate`.
5. Прописать `infra/scripts/backup.sh` в `crontab` сервера (пример — в
   комментарии самого скрипта).
6. Завести секреты в GitHub: Settings → Environments → создать `staging`
   → добавить `STAGING_SSH_HOST`, `STAGING_SSH_USER`, `STAGING_SSH_KEY`,
   `STAGING_DOMAIN`. После этого мёрдж в `main` начнёт реально выкатывать.

### Где лежат секреты и у кого доступ

- **Секреты деплоя** (`STAGING_SSH_HOST`, `STAGING_SSH_USER`,
  `STAGING_SSH_KEY`, `STAGING_DOMAIN`) — в GitHub, Settings → Environments
  → `staging`. Не в репозитории, не в переменных workflow-файла.
- **Секреты приложения** (`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`,
  `DATABASE_URL`) — в `backend/.env` на самом сервере staging, создаётся
  вручную при бутстрапе из `.env.staging.example`. В `.gitignore` — не
  попадёт в git даже случайно.
- **Бэкапы БД** (`infra/backups/*.sql.gz`) — на диске сервера, тоже в
  `.gitignore` — это дамп реальных данных, не то, что можно коммитить.
- **Доступ**: *предложение, не решение* — SSH-ключ от сервера и права
  редактировать GitHub Environment secrets — только у того, кто отвечает
  за деплой (сейчас это не распределено явно между Bekzat/Дарьей/Анель) —
  свести на созвоне троих, как и другие процессные решения в этом репозитории.

### Мониторинг и логи

- Логи — `docker compose -f docker-compose.staging.yml logs -f <сервис>`
  на самом сервере. Централизованного сбора логов нет — не строим раньше,
  чем понадобится (п. 1.3 ТЗ).
- Доступность — `/healthz/` (проверяет реальное соединение с БД, не
  просто "процесс жив") + `.github/workflows/staging-healthcheck.yml`,
  дёргает его каждые 15 минут. Красный прогон в Actions = знак, что
  staging упал. Это не замена настоящему алертингу (Slack/PagerDuty), а
  минимум, который не требует стороннего сервиса.

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

**CI**: миграции на чистой БД прогоняются в пайплайне на каждый PR — см.
раздел «CI» ниже.

## Дальше

- Ветки, коммиты, PR — [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Архитектурные решения — [`docs/adr/`](docs/adr/).
- Контракты между доменами — `docs/contracts.md` (на момент написания —
  в ветке `feature/domain-contracts`, переносится в `main` при мерже).
