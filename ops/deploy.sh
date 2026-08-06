#!/bin/sh

set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
. "$SCRIPT_DIR/common.sh"

parse_apply_args "$@"

ENV_FILE=${ENV_FILE:-"$PROJECT_DIR/.env"}
TEMPLATE=${NGINX_TEMPLATE:-"$PROJECT_DIR/deploy/nginx/ibl-course-designer.conf.template"}
RENDERED=${NGINX_RENDERED_PATH:-"$PROJECT_DIR/.state/ibl-course-designer.conf"}
TARGET=${NGINX_CONFIG_PATH:-/etc/nginx/conf.d/ibl-course-designer.conf}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/ibl-course-designer}
NGINX_BIN=${NGINX_BIN:-nginx}

"${PYTHON_BIN:-python3}" "$SCRIPT_DIR/render_nginx.py" --env-file "$ENV_FILE" --template "$TEMPLATE" --output "$RENDERED"
DIGEST=$(file_hash "$RENDERED")
if [ -f "$TARGET" ]; then
    TARGET_DIGEST=$(file_hash "$TARGET")
else
    TARGET_DIGEST=absent
fi
EXPECTED=$(approval_hash deploy "$TARGET" "$DIGEST" "$TARGET_DIGEST" "$BACKUP_DIR" "$NGINX_BIN")

printf '%s\n' "Deployment plan"
printf '%s\n' "  rendered: $RENDERED"
printf '%s\n' "  target:   $TARGET"
printf '%s\n' "  backup:   $BACKUP_DIR"
printf '%s\n' "  actions:  backup existing config, install, nginx -t, nginx -s reload"
printf '%s\n' "  approval: $EXPECTED"

if [ "$APPLY" -ne 1 ]; then
    printf '%s\n' "PLAN ONLY: rerun with --apply --approve $EXPECTED after review."
    exit 0
fi
require_approval "$EXPECTED" "$APPROVE"
require_parent_directory "$TARGET"
acquire_ops_lock
[ "$(file_hash "$RENDERED")" = "$DIGEST" ] || {
    printf '%s\n' "ERROR: rendered config changed after approval" >&2
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
BACKUP=""
if [ -f "$TARGET" ]; then
    BACKUP="$BACKUP_DIR/ibl-course-designer.conf.$STAMP.$$"
    [ ! -e "$BACKUP" ] || { printf '%s\n' "ERROR: backup collision: $BACKUP" >&2; exit 1; }
    atomic_copy_file "$TARGET" "$BACKUP" "$TARGET_DIGEST"
    write_latest_marker "$BACKUP_DIR" "$BACKUP"
fi

atomic_install_0644 "$RENDERED" "$TARGET" "$DIGEST"
if ! "$NGINX_BIN" -t; then
    if [ -n "$BACKUP" ]; then
        atomic_copy_file "$BACKUP" "$TARGET" "$TARGET_DIGEST"
    else
        mv -- "$TARGET" "$BACKUP_DIR/ibl-course-designer.conf.failed.$STAMP"
    fi
    printf '%s\n' "ERROR: nginx test failed; previous state restored and no reload attempted" >&2
    exit 1
fi
if ! "$NGINX_BIN" -s reload; then
    if [ -n "$BACKUP" ]; then
        atomic_copy_file "$BACKUP" "$TARGET" "$TARGET_DIGEST"
    else
        mv -- "$TARGET" "$BACKUP_DIR/ibl-course-designer.conf.failed-reload.$STAMP.$$"
    fi
    "$NGINX_BIN" -t || true
    printf '%s\n' "ERROR: nginx reload failed; on-disk config restored" >&2
    exit 1
fi
printf '%s\n' "OK: deployed and reloaded Nginx"
