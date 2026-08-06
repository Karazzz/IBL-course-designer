#!/usr/bin/env python3
"""Validation and deterministic packaging helpers for the ADP Skill."""

from __future__ import annotations

import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

MAX_PACKAGE_BYTES = 10 * 1024 * 1024
MAX_PACKAGE_FILES = 300
MAX_SKILL_LINES = 500
PACKAGE_DIRS = ("references",)
IGNORED_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}
IGNORED_PARTS = {
    ".git",
    ".idea",
    ".vscode",
    "__MACOSX",
    "__pycache__",
}
FORBIDDEN_SUFFIXES = {
    ".7z",
    ".avi",
    ".bmp",
    ".class",
    ".dll",
    ".doc",
    ".docx",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".pyc",
    ".pyo",
    ".rar",
    ".so",
    ".tar",
    ".wav",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}
ALLOWED_TEXT_SUFFIXES = {
    ".cfg",
    ".conf",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".svg",
    ".template",
    ".toml",
    ".ts",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class ValidationError(ValueError):
    """Raised when a Skill source or archive violates the ADP contract."""


def _parse_scalar(value: str, line_number: int) -> Any:
    value = value.strip()
    if not value:
        raise ValidationError(f"Frontmatter line {line_number}: empty values are not allowed")
    if value[0:1] in {"'", '"'}:
        if len(value) < 2 or value[-1] != value[0]:
            raise ValidationError(f"Frontmatter line {line_number}: unterminated quoted value")
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"Frontmatter line {line_number}: invalid double-quoted value"
                ) from exc
        return value[1:-1].replace("''", "'")
    if value in {"|", ">", "|-", ">-", "|+", ">+"}:
        raise ValidationError(
            "Multiline YAML scalars are valid ADP syntax but are intentionally "
            "unsupported by this dependency-free validator; use one plain line"
        )
    if value.startswith(("[", "{", "&", "*", "!")):
        raise ValidationError(
            f"Frontmatter line {line_number}: use scalar values or nested mappings only"
        )
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse the conservative YAML subset used by ADP Skill metadata."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0] != "---":
        raise ValidationError("SKILL.md must start with a YAML '---' delimiter")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as exc:
        raise ValidationError("SKILL.md frontmatter is missing its closing '---'") from exc
    if closing_index == 1:
        raise ValidationError("SKILL.md frontmatter is empty")

    result: dict[str, Any] = {}
    current_mapping: dict[str, Any] | None = None
    for index, raw_line in enumerate(lines[1:closing_index], start=2):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if "\t" in raw_line:
            raise ValidationError(f"Frontmatter line {index}: tabs are not allowed")
        indentation = len(raw_line) - len(raw_line.lstrip(" "))
        if indentation not in {0, 2}:
            raise ValidationError(
                f"Frontmatter line {index}: only zero or two-space indentation is supported"
            )
        content = raw_line.strip()
        if ":" not in content:
            raise ValidationError(f"Frontmatter line {index}: expected 'key: value'")
        key, value = content.split(":", 1)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key):
            raise ValidationError(f"Frontmatter line {index}: invalid key {key!r}")

        if indentation == 0:
            if key in result:
                raise ValidationError(f"Frontmatter line {index}: duplicate key {key!r}")
            if value.strip():
                result[key] = _parse_scalar(value, index)
                current_mapping = None
            else:
                result[key] = {}
                current_mapping = result[key]
        else:
            if current_mapping is None:
                raise ValidationError(
                    f"Frontmatter line {index}: nested value has no parent mapping"
                )
            if key in current_mapping:
                raise ValidationError(f"Frontmatter line {index}: duplicate key {key!r}")
            current_mapping[key] = _parse_scalar(value, index)

    body = "\n".join(lines[closing_index + 1 :])
    if not body.strip():
        raise ValidationError("SKILL.md must contain Markdown instructions after frontmatter")
    return result, body


def validate_metadata(metadata: dict[str, Any]) -> None:
    allowed = {"name", "description", "license", "compatibility", "metadata"}
    unexpected = sorted(set(metadata) - allowed)
    if unexpected:
        raise ValidationError(
            "Unsupported top-level frontmatter field(s): " + ", ".join(unexpected)
        )

    for required in ("name", "description"):
        if not isinstance(metadata.get(required), str) or not metadata[required].strip():
            raise ValidationError(f"Frontmatter field {required!r} is required")

    name = metadata["name"]
    if not 3 <= len(name) <= 64 or not NAME_PATTERN.fullmatch(name):
        raise ValidationError(
            "Frontmatter 'name' must be 3-64 lowercase letters, digits, and single hyphens"
        )
    description = metadata["description"]
    if not 1 <= len(description) <= 1024:
        raise ValidationError("Frontmatter 'description' must be 1-1024 characters")
    compatibility = metadata.get("compatibility")
    if compatibility is not None and (
        not isinstance(compatibility, str) or len(compatibility) > 500
    ):
        raise ValidationError("Frontmatter 'compatibility' must be at most 500 characters")
    license_value = metadata.get("license")
    if license_value is not None and not isinstance(license_value, str):
        raise ValidationError("Frontmatter 'license' must be a scalar string")
    custom = metadata.get("metadata", {})
    if not isinstance(custom, dict):
        raise ValidationError("Frontmatter 'metadata' must be a nested mapping")
    version = custom.get("version")
    if version is not None and (
        not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version)
    ):
        raise ValidationError("metadata.version must use SemVer, for example 2.0.0")


def validate_skill_text(text: str) -> dict[str, Any]:
    metadata, _ = parse_frontmatter(text)
    validate_metadata(metadata)
    if len(text.splitlines()) > MAX_SKILL_LINES:
        raise ValidationError(
            f"SKILL.md has more than the recommended {MAX_SKILL_LINES} lines; "
            "move detail to references/"
        )
    return metadata


def _is_ignored(relative: PurePosixPath) -> bool:
    return (
        relative.name in IGNORED_NAMES
        or relative.name.startswith("._")
        or any(part in IGNORED_PARTS for part in relative.parts)
    )


def package_files(source_root: Path) -> list[tuple[Path, PurePosixPath]]:
    root = source_root.resolve()
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        raise ValidationError(f"Missing required file: {skill_file}")
    files: list[tuple[Path, PurePosixPath]] = [(skill_file, PurePosixPath("SKILL.md"))]
    for directory_name in PACKAGE_DIRS:
        directory = root / directory_name
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise ValidationError(f"Expected a directory: {directory}")
        for file_path in sorted(path for path in directory.rglob("*") if path.is_file()):
            relative = PurePosixPath(file_path.relative_to(root).as_posix())
            if not _is_ignored(relative):
                files.append((file_path, relative))
    return files


def validate_text_file(data: bytes, relative: PurePosixPath) -> str:
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ValidationError(f"Unsupported binary/archive extension: {relative}")
    if relative.suffix.lower() not in ALLOWED_TEXT_SUFFIXES:
        raise ValidationError(f"Unsupported package file extension: {relative}")
    if b"\x00" in data:
        raise ValidationError(f"NUL byte indicates a binary file: {relative}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"Package file is not valid UTF-8 text: {relative}") from exc


def validate_entries(entries: Iterable[tuple[PurePosixPath, bytes]]) -> dict[str, Any]:
    entry_list = list(entries)
    paths = [relative for relative, _ in entry_list]
    if paths.count(PurePosixPath("SKILL.md")) != 1:
        raise ValidationError("ZIP root must contain exactly one SKILL.md")
    if len(paths) != len(set(paths)):
        raise ValidationError("Package contains duplicate paths")
    if len(paths) > MAX_PACKAGE_FILES:
        raise ValidationError(f"Package exceeds {MAX_PACKAGE_FILES} effective files")
    if sum(len(data) for _, data in entry_list) > MAX_PACKAGE_BYTES:
        raise ValidationError("Package exceeds the 10 MB uncompressed content limit")

    skill_text = ""
    for relative, data in entry_list:
        if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
            raise ValidationError(f"Unsafe package path: {relative}")
        if _is_ignored(relative):
            raise ValidationError(f"Unrelated system file should not be packaged: {relative}")
        text = validate_text_file(data, relative)
        if relative == PurePosixPath("SKILL.md"):
            skill_text = text
    return validate_skill_text(skill_text)


def validate_source(source_root: Path) -> tuple[dict[str, Any], list[tuple[Path, PurePosixPath]]]:
    files = package_files(source_root)
    entries = [(relative, path.read_bytes()) for path, relative in files]
    return validate_entries(entries), files


def validate_zip(archive_path: Path) -> dict[str, Any]:
    if not archive_path.is_file():
        raise ValidationError(f"ZIP file does not exist: {archive_path}")
    if archive_path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValidationError("ZIP archive exceeds the 10 MB upload limit")
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            all_infos = archive.infolist()
            infos = [info for info in all_infos if not info.is_dir()]
            if len(infos) > MAX_PACKAGE_FILES:
                raise ValidationError(f"Package exceeds {MAX_PACKAGE_FILES} effective files")
            declared_size = 0
            seen: set[PurePosixPath] = set()
            for info in all_infos:
                relative = PurePosixPath(info.filename)
                if relative in seen:
                    raise ValidationError(f"Package contains duplicate path: {relative}")
                seen.add(relative)
                if relative.is_absolute() or ".." in relative.parts or "\\" in info.filename:
                    raise ValidationError(f"Unsafe package path: {relative}")
                if info.flag_bits & 0x1:
                    raise ValidationError(f"Encrypted ZIP entries are not supported: {relative}")
                mode = info.external_attr >> 16
                if info.create_system == 3 and mode:
                    expected_type = stat.S_ISDIR(mode) if info.is_dir() else stat.S_ISREG(mode)
                    if not expected_type:
                        raise ValidationError(f"ZIP entry has an unsupported file mode: {relative}")
                if not info.is_dir():
                    declared_size += info.file_size
                if declared_size > MAX_PACKAGE_BYTES:
                    raise ValidationError("Package exceeds the 10 MB uncompressed content limit")

            entries: list[tuple[PurePosixPath, bytes]] = []
            actual_size = 0
            for info in infos:
                chunks: list[bytes] = []
                with archive.open(info, "r") as member:
                    while chunk := member.read(64 * 1024):
                        actual_size += len(chunk)
                        if actual_size > MAX_PACKAGE_BYTES:
                            raise ValidationError(
                                "Package exceeds the 10 MB uncompressed content limit"
                            )
                        chunks.append(chunk)
                entries.append((PurePosixPath(info.filename), b"".join(chunks)))
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"Invalid ZIP archive: {archive_path}") from exc
    return validate_entries(entries)
