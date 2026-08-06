#!/bin/sh

set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
. "$SCRIPT_DIR/common.sh"

parse_apply_args "$@"

SOURCE=${NGINX_CONFIG_PATH:-/etc/nginx/conf.d/ibl-course-designer.conf}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/ibl-course-designer}
[ -f "$SOURCE" ] || { printf '%s\n' "ERROR: source config does not exist: $SOURCE" >&2; exit 1; }
DIGEST=$(file_hash "$SOURCE")
EXPECTED=$(approval_hash backup "$SOURCE" "$BACKUP_DIR" "$DIGEST")

printf '%s\n' "Backup plan"
printf '%s\n' "  source:   $SOURCE"
printf '%s\n' "  backup:   $BACKUP_DIR"
printf '%s\n' "  approval: $EXPECTED"
if [ "$APPLY" -ne 1 ]; then
    printf '%s\n' "PLAN ONLY: rerun with --apply --approve $EXPECTED after review."
    exit 0
fi
require_approval "$EXPECTED" "$APPROVE"
acquire_ops_lock
[ "$(file_hash "$SOURCE")" = "$DIGEST" ] || {
    printf '%s\n' "ERROR: source config changed after approval" >&2
    exit 1
}
[ -d "$BACKUP_DIR" ] || mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DESTINATION="$BACKUP_DIR/ibl-course-designer.conf.$STAMP.$$"
[ ! -e "$DESTINATION" ] || { printf '%s\n' "ERROR: backup collision: $DESTINATION" >&2; exit 1; }
atomic_copy_file "$SOURCE" "$DESTINATION" "$DIGEST"
write_latest_marker "$BACKUP_DIR" "$DESTINATION"
printf '%s\n' "OK: backup created at $DESTINATION"
