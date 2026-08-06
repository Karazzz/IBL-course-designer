#!/bin/sh

set -eu

approval_hash() {
    "${PYTHON_BIN:-python3}" -c 'import hashlib, sys; print(hashlib.sha256("|".join(sys.argv[1:]).encode("utf-8")).hexdigest())' "$@"
}

file_hash() {
    "${PYTHON_BIN:-python3}" -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$1"
}

require_approval() {
    expected=$1
    supplied=$2
    if [ "$expected" != "$supplied" ]; then
        printf '%s\n' "ERROR: approval hash does not match the displayed plan" >&2
        exit 1
    fi
}

require_parent_directory() {
    parent=$(dirname "$1")
    if [ ! -d "$parent" ]; then
        printf '%s\n' "ERROR: parent directory does not exist: $parent" >&2
        exit 1
    fi
}

acquire_ops_lock() {
    OPS_LOCK_DIR=${OPS_LOCK_DIR:-/tmp/ibl-course-designer-nginx.lock}
    if ! mkdir -- "$OPS_LOCK_DIR" 2>/dev/null; then
        printf '%s\n' "ERROR: another Nginx operation holds lock: $OPS_LOCK_DIR" >&2
        exit 1
    fi
    trap 'rmdir -- "$OPS_LOCK_DIR" 2>/dev/null || true' EXIT
    trap 'exit 1' HUP INT TERM
}

write_latest_marker() {
    marker_dir=$1
    marker_value=$2
    marker_temp="$marker_dir/latest.$$"
    printf '%s\n' "$marker_value" > "$marker_temp"
    mv -- "$marker_temp" "$marker_dir/latest"
}

atomic_copy_file() {
    source_file=$1
    target_file=$2
    approved_digest=$3
    temporary_file="${target_file}.tmp.$$"
    [ ! -e "$temporary_file" ] || {
        printf '%s\n' "ERROR: temporary file already exists: $temporary_file" >&2
        exit 1
    }
    cp -p -- "$source_file" "$temporary_file"
    [ "$approved_digest" = "$(file_hash "$temporary_file")" ] || {
        printf '%s\n' "ERROR: temporary copy does not match approved digest" >&2
        exit 1
    }
    mv -- "$temporary_file" "$target_file"
}

atomic_install_0644() {
    source_file=$1
    target_file=$2
    approved_digest=$3
    temporary_file="${target_file}.tmp.$$"
    [ ! -e "$temporary_file" ] || {
        printf '%s\n' "ERROR: temporary file already exists: $temporary_file" >&2
        exit 1
    }
    install -m 0644 -- "$source_file" "$temporary_file"
    [ "$approved_digest" = "$(file_hash "$temporary_file")" ] || {
        printf '%s\n' "ERROR: temporary install does not match approved digest" >&2
        exit 1
    }
    mv -- "$temporary_file" "$target_file"
}

parse_apply_args() {
    APPLY=0
    APPROVE=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --apply)
                APPLY=1
                ;;
            --approve)
                shift
                [ "$#" -gt 0 ] || { printf '%s\n' "ERROR: --approve needs a hash" >&2; exit 1; }
                APPROVE=$1
                ;;
            *)
                printf '%s\n' "ERROR: unknown argument: $1" >&2
                exit 1
                ;;
        esac
        shift
    done
}
