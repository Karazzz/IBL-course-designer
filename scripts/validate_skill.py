#!/usr/bin/env python3
"""Validate the ADP Skill source selection or a generated ZIP archive."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from skill_utils import ValidationError, validate_source, validate_zip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--source", type=Path, default=Path("."), help="Skill source root")
    group.add_argument("--zip", dest="zip_path", type=Path, help="ZIP archive to validate")
    args = parser.parse_args()

    try:
        if args.zip_path:
            metadata = validate_zip(args.zip_path)
            target = args.zip_path
            count = "archive entries checked"
        else:
            metadata, files = validate_source(args.source)
            target = args.source
            count = f"{len(files)} package files checked"
    except (OSError, ValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    version = metadata.get("metadata", {}).get("version", "unknown")
    print(f"OK: {target} ({count}; name={metadata['name']}; version={version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
