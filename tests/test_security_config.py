from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SecurityConfigurationTests(unittest.TestCase):
    def test_example_file_contains_no_secret_values(self) -> None:
        values: dict[str, str] = {}
        for raw_line in ROOT.joinpath(".env.example").read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        for key in (
            "TENCENTCLOUD_SECRET_ID",
            "TENCENTCLOUD_SECRET_KEY",
            "TENCENTCLOUD_SESSION_TOKEN",
            "ADP_SKILL_FILE_URL",
        ):
            self.assertIn(key, values)
            self.assertEqual(values[key], "", f"{key} must be empty in .env.example")

    def test_private_key_material_is_not_present_in_text_sources(self) -> None:
        suffixes = {".md", ".py", ".sh", ".json", ".txt", ".template", ".example"}
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("-----BEGIN " + "PRIVATE KEY-----", text, str(path))
            self.assertNotIn("-----BEGIN " + "RSA PRIVATE KEY-----", text, str(path))


if __name__ == "__main__":
    unittest.main()
