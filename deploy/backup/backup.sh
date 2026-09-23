#!/bin/sh
# Requires age and a public recipient; private key must stay off the application server.
set -eu
umask 077
: "${BACKUP_DIR:?Defina um diretório protegido para backups}"
: "${AGE_RECIPIENT:?Defina a chave pública age}"
mkdir -p "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dump=$(mktemp "$BACKUP_DIR/.isp-backup.XXXXXX")
trap 'rm -f "$dump"' EXIT HUP INT TERM
docker compose exec -T db pg_dump -U isp_owner -d isp_panel --format=custom --no-owner > "$dump"
age -r "$AGE_RECIPIENT" -o "$BACKUP_DIR/isp-panel-$stamp.dump.age" "$dump"
printf '%s\n' "Backup criptografado criado. Replicar para armazenamento externo conforme docs/operations.md."
