#!/bin/sh
# Резервне копіювання PostgreSQL (NFR-2.2: RPO ≤ 15 хв). Без аргументів — одна копія; --loop — циклічно.
set -eu
DIR=${BACKUP_DIR:-/backups}
KEEP=${BACKUP_KEEP:-96}
INTERVAL=${BACKUP_INTERVAL_SECONDS:-900}
mkdir -p "$DIR"
one() {
  f="$DIR/wms_$(date +%Y%m%d_%H%M%S).dump"
  pg_dump -Fc -f "$f.tmp" && mv "$f.tmp" "$f" && echo "backup: $f"
  ls -1t "$DIR"/wms_*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
}
if [ "${1:-}" = "--loop" ]; then
  while true; do one || echo "backup: помилка"; sleep "$INTERVAL"; done
else
  one
fi
