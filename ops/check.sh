#!/bin/sh

set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

ENV_FILE=${ENV_FILE:-"$PROJECT_DIR/.env"}
TEMPLATE=${NGINX_TEMPLATE:-"$PROJECT_DIR/deploy/nginx/ibl-course-designer.conf.template"}
RENDERED=${NGINX_RENDERED_PATH:-"$PROJECT_DIR/.state/ibl-course-designer.conf"}
NGINX_BIN=${NGINX_BIN:-nginx}
SERVER_CHECK=0
REMOTE_CHECK=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --server) SERVER_CHECK=1 ;;
        --remote) REMOTE_CHECK=1 ;;
        *) printf '%s\n' "ERROR: unknown argument: $1" >&2; exit 1 ;;
    esac
    shift
done

"${PYTHON_BIN:-python3}" "$SCRIPT_DIR/render_nginx.py" --env-file "$ENV_FILE" --template "$TEMPLATE" --output "$RENDERED"
printf '%s\n' "OK: template rendered with no unresolved placeholders"

if [ "$SERVER_CHECK" -eq 1 ]; then
    "$NGINX_BIN" -t
    printf '%s\n' "OK: nginx configuration test passed"
fi

if [ "$REMOTE_CHECK" -eq 1 ]; then
    PUBLIC_DOMAIN=$("${PYTHON_BIN:-python3}" -c 'import os, pathlib, sys; p=pathlib.Path(sys.argv[1]); values={}; [values.setdefault(*(line.split("=",1))) for line in p.read_text(encoding="utf-8").splitlines() if line and not line.lstrip().startswith("#") and "=" in line]; print(os.environ.get("PUBLIC_DOMAIN", values.get("PUBLIC_DOMAIN", "")).strip().strip("\"\x27"))' "$ENV_FILE")
    [ -n "$PUBLIC_DOMAIN" ] || { printf '%s\n' "ERROR: PUBLIC_DOMAIN is empty" >&2; exit 1; }
    curl --silent --show-error --max-time 15 --output /dev/null "https://$PUBLIC_DOMAIN/cgi-bin/gettoken"
    curl --silent --show-error --max-time 15 --output /dev/null "https://$PUBLIC_DOMAIN/online/channel/callback/"
    printf '%s\n' "OK: both HTTPS proxy paths returned an HTTP response"
fi
