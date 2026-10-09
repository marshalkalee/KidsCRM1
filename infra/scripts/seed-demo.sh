#!/usr/bin/env sh
# Демо-данные на демо-сервере одной командой: витрина «Dance Kids Almaty»
# с логинами всех ролей (пароль DemoKids2026) и дополнения — задачи,
# объявления, запросы родителей, рассылки, профиль центра, импорт.
#
# Запускать на сервере из папки проекта:
#   cd /opt/kidscrm && ./infra/scripts/seed-demo.sh           # собрать, если витрины нет
#   cd /opt/kidscrm && ./infra/scripts/seed-demo.sh --reset   # старую в архив, собрать заново
#
# Нужен DEMO_DATA_ALLOWED=true в backend/.env (на боевом сервере не ставить —
# команды создают выдуманных детей и общий пароль). Перед сборкой — бэкап.
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.staging.yml}"
RESET="${1:-}"
run() { docker compose -f "$COMPOSE_FILE" exec -T backend python manage.py "$@"; }

./infra/scripts/backup.sh

run migrate --noinput
if [ "$RESET" = "--reset" ]; then
  run seed_showcase --reset
else
  run seed_showcase
fi
run seed_showcase --extras

echo "Готово. Вход: +7 777 000 00 01 (владелец), пароль DemoKids2026."
