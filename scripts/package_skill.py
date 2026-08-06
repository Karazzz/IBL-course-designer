#!/usr/bin/env python3
"""Build a deterministic Tencent Cloud ADP Skill ZIP."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from skill_utils import ValidationError, validate_source, validate_zip


def write_entry(archive: zipfile.ZipFile, relative: str, data: bytes) -> None:
    info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.flag_bits |= 0x800
    archive.writestr(info, data, compresslevel=9)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("."), help="Skill source root")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/IBL-course-designer.zip"),
        help="Output ZIP path",
    )
    args = parser.parse_args()

    try:
        _, files = validate_source(args.source)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="ibl-course-designer-", suffix=".zip", delete=False, dir=args.output.parent
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            with zipfile.ZipFile(temporary_path, "w") as archive:
                for file_path, relative in sorted(files, key=lambda item: str(item[1])):
                    write_entry(archive, relative.as_posix(), file_path.read_bytes())
            validate_zip(temporary_path)
            os.replace(temporary_path, args.output)
        finally:
            temporary_path.unlink(missing_ok=True)
    except (OSError, ValidationError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f"OK: wrote {args.output} ({args.output.stat().st_size} bytes, sha256={digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
