#!/usr/bin/env python3
"""Render and validate the Nginx reverse-proxy template from environment values."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

PLACEHOLDER = re.compile(r"{{([A-Z][A-Z0-9_]*)}}")
DOMAIN = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,63}$"
)
REQUIRED = {
    "PUBLIC_DOMAIN",
    "TLS_CERT_PATH",
    "TLS_KEY_PATH",
    "NGINX_ACCESS_LOG",
    "PROXY_CA_CERT_PATH",
}


class RenderError(ValueError):
    pass


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise RenderError(f"Environment file not found: {path}")
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise RenderError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            raise RenderError(f"{path}:{line_number}: invalid environment key")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise RenderError(f"{path}:{line_number}: unterminated quoted value")
            value = value[1:-1]
        os.environ.setdefault(key, value)


def safe_value(name: str, value: str) -> str:
    if not value:
        raise RenderError(f"Required environment variable {name} is empty")
    if any(character in value for character in "\r\n\x00;{}"):
        raise RenderError(f"Unsafe character in {name}")
    if name == "PUBLIC_DOMAIN":
        if not DOMAIN.fullmatch(value):
            raise RenderError("PUBLIC_DOMAIN must be a fully qualified DNS name")
        return value.lower()
    if not value.startswith("/"):
        raise RenderError(f"{name} must be an absolute Linux path")
    return value


def render(template_path: Path) -> str:
    template = template_path.read_text(encoding="utf-8")
    placeholders = set(PLACEHOLDER.findall(template))
    missing_in_template = REQUIRED - placeholders
    if missing_in_template:
        raise RenderError(
            "Template is missing required placeholders: " + ", ".join(sorted(missing_in_template))
        )
    values = {name: safe_value(name, os.environ.get(name, "")) for name in placeholders}
    rendered = PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
    leftovers = PLACEHOLDER.findall(rendered)
    if leftovers:
        raise RenderError("Unresolved placeholders: " + ", ".join(sorted(set(leftovers))))
    required_fragments = (
        "proxy_pass https://qyapi.weixin.qq.com;",
        "proxy_pass https://chan.lke.cloud.tencent.com;",
        "ssl_protocols TLSv1.2 TLSv1.3;",
        "proxy_ssl_verify on;",
        '"$request_method $uri $server_protocol"',
    )
    for fragment in required_fragments:
        if fragment not in rendered:
            raise RenderError(f"Rendered config is missing safety requirement: {fragment}")
    return rendered


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=path.parent, newline="\n"
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("deploy/nginx/ibl-course-designer.conf.template"),
    )
    parser.add_argument("--output", type=Path, help="Write rendered config instead of stdout")
    parser.add_argument("--env-file", type=Path, help="Load missing values from this file")
    args = parser.parse_args()
    try:
        if args.env_file:
            load_env_file(args.env_file)
        rendered = render(args.template)
        if args.output:
            atomic_write(args.output, rendered)
            print(f"OK: rendered {args.output}")
        else:
            sys.stdout.write(rendered)
    except (OSError, RenderError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
