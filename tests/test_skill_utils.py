from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from skill_utils import (  # noqa: E402
    ValidationError,
    parse_frontmatter,
    validate_entries,
    validate_source,
    validate_zip,
)


class SkillValidationTests(unittest.TestCase):
    def test_repository_skill_source_is_valid(self) -> None:
        metadata, files = validate_source(ROOT)
        self.assertEqual(metadata["name"], "ibl-course-designer")
        self.assertEqual(metadata["metadata"]["version"], "2.0.0")
        self.assertEqual(files[0][1], PurePosixPath("SKILL.md"))
        self.assertTrue(all(path.suffix.lower() == ".md" for path, _ in files))

    def test_missing_root_skill_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "exactly one SKILL.md"):
            validate_entries(
                [(PurePosixPath("nested/SKILL.md"), b"---\nname: abc\ndescription: x\n---\n# x")]
            )

    def test_binary_file_is_rejected(self) -> None:
        skill = b"---\nname: abc\ndescription: test\n---\n# Test\n"
        with self.assertRaisesRegex(ValidationError, "binary"):
            validate_entries(
                [
                    (PurePosixPath("SKILL.md"), skill),
                    (PurePosixPath("assets/image.png"), b"\x89PNG\r\n\x00"),
                ]
            )

    def test_path_traversal_is_rejected(self) -> None:
        skill = b"---\nname: abc\ndescription: test\n---\n# Test\n"
        with self.assertRaisesRegex(ValidationError, "Unsafe package path"):
            validate_entries(
                [
                    (PurePosixPath("SKILL.md"), skill),
                    (PurePosixPath("../secret.txt"), b"not a secret"),
                ]
            )

    def test_frontmatter_rejects_duplicate_keys(self) -> None:
        text = "---\nname: abc\nname: def\ndescription: test\n---\n# Test\n"
        with self.assertRaisesRegex(ValidationError, "duplicate key"):
            parse_frontmatter(text)

    def test_source_selection_excludes_unrelated_root_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("SKILL.md").write_text(
                "---\nname: abc\ndescription: test\nmetadata:\n  version: 1.0.0\n---\n# Test\n",
                encoding="utf-8",
            )
            root.joinpath("reference.docx").write_bytes(b"binary outside package manifest")
            _, files = validate_source(root)
            self.assertEqual([relative.as_posix() for _, relative in files], ["SKILL.md"])

    def test_declared_oversized_zip_is_rejected_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "large.zip"
            skill = "---\nname: abc\ndescription: test\n---\n# Test\n"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("SKILL.md", skill)
                archive.writestr("references/large.txt", "x" * (10 * 1024 * 1024))
            with self.assertRaisesRegex(ValidationError, "uncompressed content limit"):
                validate_zip(archive_path)

    def test_non_scalar_license_is_rejected(self) -> None:
        skill = (
            b"---\nname: abc\ndescription: test\nlicense:\n  type: MIT\n---\n# Test\n"
        )
        with self.assertRaisesRegex(ValidationError, "license"):
            validate_entries([(PurePosixPath("SKILL.md"), skill)])


if __name__ == "__main__":
    unittest.main()
