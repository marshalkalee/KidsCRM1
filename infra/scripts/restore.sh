#!/usr/bin/env sh
# Восстановление БД из бэкапа, снятого backup.sh.
#
# ВНИМАНИЕ: перезаписывает текущую базу целиком. Использование:
#   ./infra/scripts/restore.sh infra/backups/kidscrm-20260101-030000.sql.gz
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.staging.yml}"
DUMP_FILE="${1:?Использование: restore.sh <путь-к-дампу.sql.gz>}"

if [ ! -f "$DUMP_FILE" ]; then
    echo "Файл не найден: $DUMP_FILE" >&2
    exit 1
fi

echo "Пересоздаю базу kidscrm из $DUMP_FILE ..."

docker compose -f "$COMPOSE_FILE" exec -T db psql -U kidscrm -d postgres \
    -c "DROP DATABASE IF EXISTS kidscrm;" \
    -c "CREATE DATABASE kidscrm OWNER kidscrm;"

gunzip -c "$DUMP_FILE" | docker compose -f "$COMPOSE_FILE" exec -T db psql -U kidscrm -d kidscrm

echo "Восстановление завершено."
