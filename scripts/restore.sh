#!/bin/sh
# Відновлення з резервної копії (NFR-2.2: RTO ≤ 4 год). Запуск з хоста:
#   docker compose stop api worker
#   docker compose exec backup sh -c 'ls -1t /backups'            # вибрати файл
#   docker compose exec backup sh /restore.sh /backups/wms_YYYYmmdd_HHMMSS.dump
#   docker compose start api worker
set -eu
FILE=${1:?Вкажіть файл резервної копії}
pg_restore --clean --if-exists --no-owner -d "${PGDATABASE:-wms}" "$FILE"
echo "restore: відновлено з $FILE"
