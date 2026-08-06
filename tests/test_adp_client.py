from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adp_client import (  # noqa: E402
    ConfigError,
    Settings,
    TC3Client,
    atomic_write_json,
    build_plan,
    choose_exact,
    load_env_file,
    iter_sse,
    redact,
    subset_matches,
    verify_approval,
)


def settings(**overrides) -> Settings:
    values = {
        "endpoint": "adp.tencentcloudapi.com",
        "chat_endpoint": "https://wss.lke.cloud.tencent.com/adp/v2/chat",
        "region": "ap-guangzhou",
        "secret_id": "test-id",
        "secret_key": "test-key",
        "session_token": "",
        "account_fingerprint": "test-account",
        "space_id": "default_space",
        "space_name": "Test Space",
        "space_description": "Test",
        "app_name": "Test App",
        "app_description": "Test",
        "agent_name": "Test Agent",
        "agent_description": "Test",
        "model_id": "test/model",
        "skill_id": "skill-test-id",
        "skill_name": "ibl-course-designer",
        "skill_file_url": "",
        "skill_version": "2.0.0",
        "user_id": "test-user",
        "instructions_path": ROOT / "config" / "agent-instructions.txt",
        "acceptance_path": ROOT / "config" / "acceptance-cases.json",
        "state_path": ROOT / ".state" / "unit-test-state.json",
        "max_reasoning_rounds": 100,
        "timeout_seconds": 10,
        "release_timeout_seconds": 30,
        "verbose": False,
    }
    values.update(overrides)
    return Settings(**values)


class AdpClientTests(unittest.TestCase):
    def test_tc3_authorization_is_deterministic_and_does_not_expose_key(self) -> None:
        client = TC3Client(settings())
        authorization, headers = client.authorization(
            "DescribeSpaceList", '{"Query":""}', 1_700_000_000
        )
        self.assertEqual(headers["X-TC-Version"], "2026-05-20")
        self.assertIn("Credential=test-id/", authorization)
        self.assertNotIn("test-key", authorization)
        self.assertRegex(authorization, r"Signature=[0-9a-f]{64}$")

    def test_redaction_covers_all_credentials_and_signed_urls(self) -> None:
        value = {
            "SecretKey": "value",
            "AppKey": "value",
            "FileUrl": "value",
            "nested": {"Token": "value"},
            "safe": "visible",
        }
        redacted = redact(value)
        self.assertEqual(redacted["safe"], "visible")
        self.assertEqual(redacted["SecretKey"], "<redacted>")
        self.assertEqual(redacted["nested"]["Token"], "<redacted>")

    def test_choose_exact_always_stops_on_ambiguity(self) -> None:
        items = [
            {"AppId": "one", "Name": "Same"},
            {"AppId": "two", "Name": "Same"},
        ]
        with self.assertRaisesRegex(ConfigError, "Ambiguous"):
            choose_exact(
                items,
                name="Same",
                name_getter=lambda item: item["Name"],
                id_key="AppId",
                state_id="two",
                resource="app",
            )

    def test_subset_match_ignores_server_fields_but_not_desired_drift(self) -> None:
        current = {"ModelId": "m1", "Alias": "server alias", "ContextWordsLimit": 20000}
        self.assertTrue(subset_matches(current, {"ModelId": "m1"}))
        self.assertFalse(subset_matches(current, {"ModelId": "m2"}))

    def test_plan_approval_detects_tampering_and_environment_drift(self) -> None:
        configured = settings()
        plan = build_plan(configured)
        serialized = json.dumps(plan)
        self.assertNotIn("test-key", serialized)
        self.assertEqual(
            plan["desired"]["api"]["chat_endpoint"],
            "https://wss.lke.cloud.tencent.com/adp/v2/chat",
        )
        self.assertIsNotNone(plan["desired"]["api"]["credential_identity_sha256"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            atomic_write_json(path, plan)
            verify_approval(configured, path, plan["approval_hash"])
            tampered = json.loads(path.read_text(encoding="utf-8"))
            tampered["desired"]["app"]["name"] = "Changed"
            atomic_write_json(path, tampered)
            with self.assertRaisesRegex(ConfigError, "integrity"):
                verify_approval(configured, path, plan["approval_hash"])

    def test_env_file_does_not_override_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("ADP_REGION=from-file\nADP_MODEL_ID='model-id'\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"ADP_REGION": "from-process"}, clear=True):
                load_env_file(path)
                self.assertEqual(os.environ["ADP_REGION"], "from-process")
                self.assertEqual(os.environ["ADP_MODEL_ID"], "model-id")

    def test_non_tencent_chat_endpoint_is_rejected(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"ADP_CHAT_ENDPOINT": "https://attacker.example/adp/v2/chat"},
            clear=True,
        ):
            with self.assertRaisesRegex(ConfigError, "official Tencent endpoint"):
                Settings.from_env(require_credentials=False)

    def test_sse_done_marker_and_invalid_json(self) -> None:
        events = list(iter_sse([b'data: {"Type":"text.delta","Text":"ok"}\n', b"\n", b"data: [DONE]\n", b"\n"]))
        self.assertEqual(events[0]["Text"], "ok")
        self.assertEqual(events[1]["Type"], "response.completed")
        with self.assertRaisesRegex(Exception, "invalid SSE JSON"):
            list(iter_sse([b"data: not-json\n", b"\n"]))


if __name__ == "__main__":
    unittest.main()
