#!/bin/sh

set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
. "$SCRIPT_DIR/common.sh"

APPLY=0
APPROVE=""
BACKUP=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --apply) APPLY=1 ;;
        --approve) shift; [ "$#" -gt 0 ] || exit 1; APPROVE=$1 ;;
        --backup) shift; [ "$#" -gt 0 ] || exit 1; BACKUP=$1 ;;
        *) printf '%s\n' "ERROR: unknown argument: $1" >&2; exit 1 ;;
    esac
    shift
done

TARGET=${NGINX_CONFIG_PATH:-/etc/nginx/conf.d/ibl-course-designer.conf}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/ibl-course-designer}
NGINX_BIN=${NGINX_BIN:-nginx}
if [ -z "$BACKUP" ]; then
    [ -f "$BACKUP_DIR/latest" ] || { printf '%s\n' "ERROR: no latest backup marker" >&2; exit 1; }
    BACKUP=$(sed -n '1p' "$BACKUP_DIR/latest")
fi
[ -f "$BACKUP" ] || { printf '%s\n' "ERROR: backup does not exist: $BACKUP" >&2; exit 1; }
DIGEST=$(file_hash "$BACKUP")
if [ -f "$TARGET" ]; then
    TARGET_DIGEST=$(file_hash "$TARGET")
else
    TARGET_DIGEST=absent
fi
EXPECTED=$(approval_hash rollback "$BACKUP" "$TARGET" "$DIGEST" "$TARGET_DIGEST" "$BACKUP_DIR" "$NGINX_BIN")

printf '%s\n' "Rollback plan"
printf '%s\n' "  backup:   $BACKUP"
printf '%s\n' "  target:   $TARGET"
printf '%s\n' "  actions:  restore, nginx -t, nginx -s reload"
printf '%s\n' "  approval: $EXPECTED"
if [ "$APPLY" -ne 1 ]; then
    printf '%s\n' "PLAN ONLY: rerun with --apply --backup '$BACKUP' --approve $EXPECTED after review."
    exit 0
fi
require_approval "$EXPECTED" "$APPROVE"
require_parent_directory "$TARGET"
acquire_ops_lock
[ "$(file_hash "$BACKUP")" = "$DIGEST" ] || {
    printf '%s\n' "ERROR: selected backup changed after approval" >&2
    exit 1
}
if [ -f "$TARGET" ]; then
    CURRENT_TARGET_DIGEST=$(file_hash "$TARGET")
else
    CURRENT_TARGET_DIGEST=absent
fi
[ "$CURRENT_TARGET_DIGEST" = "$TARGET_DIGEST" ] || {
    printf '%s\n' "ERROR: target config changed after approval" >&2
    exit 1
}
[ -d "$BACKUP_DIR" ] || mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PREVIOUS=""
if [ -f "$TARGET" ]; then
    PREVIOUS="$BACKUP_DIR/pre-rollback.conf.$STAMP.$$"
    [ ! -e "$PREVIOUS" ] || { printf '%s\n' "ERROR: backup collision: $PREVIOUS" >&2; exit 1; }
    atomic_copy_file "$TARGET" "$PREVIOUS" "$TARGET_DIGEST"
fi
atomic_copy_file "$BACKUP" "$TARGET" "$DIGEST"
if ! "$NGINX_BIN" -t; then
    if [ -n "$PREVIOUS" ]; then
        atomic_copy_file "$PREVIOUS" "$TARGET" "$TARGET_DIGEST"
    else
        mv -- "$TARGET" "$BACKUP_DIR/failed-rollback.conf.$STAMP.$$"
    fi
    printf '%s\n' "ERROR: rollback candidate failed nginx -t; previous config restored" >&2
    exit 1
fi
if ! "$NGINX_BIN" -s reload; then
    if [ -n "$PREVIOUS" ]; then
        atomic_copy_file "$PREVIOUS" "$TARGET" "$TARGET_DIGEST"
    else
        mv -- "$TARGET" "$BACKUP_DIR/failed-rollback-reload.conf.$STAMP.$$"
    fi
    "$NGINX_BIN" -t || true
    printf '%s\n' "ERROR: rollback reload failed; previous on-disk config restored" >&2
    exit 1
fi
if [ -n "$PREVIOUS" ]; then
    write_latest_marker "$BACKUP_DIR" "$PREVIOUS"
fi
printf '%s\n' "OK: rollback completed"
