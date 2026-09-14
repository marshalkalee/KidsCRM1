#!/usr/bin/env sh
# Ежедневный бэкап БД. Запускать на сервере через cron (см. README
# "Staging и деплой"), не внутри контейнера — сам скрипт зовёт
# `docker compose exec` снаружи.
#
# Пример crontab на сервере (бэкап каждый день в 03:00 по времени сервера):
#   0 3 * * * cd /opt/kidscrm && ./infra/scripts/backup.sh >> /var/log/kidscrm-backup.log 2>&1
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.staging.yml}"
BACKUP_DIR="${BACKUP_DIR:-infra/backups}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUT_FILE="$BACKUP_DIR/kidscrm-$TIMESTAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

docker compose -f "$COMPOSE_FILE" exec -T db pg_dump -U kidscrm kidscrm | gzip > "$OUT_FILE"

echo "Бэкап сохранён: $OUT_FILE"

# Храним только последние 14 дней — без ротации диск на сервере со
# временем забьётся полностью.
find "$BACKUP_DIR" -name "kidscrm-*.sql.gz" -mtime +14 -delete
