#!/usr/bin/env python3
"""Plan, provision, publish, and test a Tencent Cloud ADP Claw application.

The client uses only Python's standard library. Mutating and chat commands require
an approval hash emitted by the offline ``plan`` command. It never persists or
prints SecretKey, temporary tokens, AppKey, or signed Skill file URLs.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SERVICE = "adp"
API_VERSION = "2026-05-20"
DEFAULT_REGION = "ap-guangzhou"
DEFAULT_ENDPOINT = "adp.tencentcloudapi.com"
DEFAULT_CHAT_ENDPOINT = "https://wss.lke.cloud.tencent.com/adp/v2/chat"
ALLOWED_ENDPOINTS = {"adp.tencentcloudapi.com", "capi.adp.tencent.com"}
ALLOWED_CHAT_ENDPOINTS = {
    "https://wss.lke.cloud.tencent.com/adp/v2/chat",
    "https://adp.tencent.com/adp/v2/chat",
}
SENSITIVE_KEY_PATTERN = re.compile(
    r"(secret|token|appkey|authorization|password|fileurl|aeskey)", re.IGNORECASE
)
MUTATING_ACTIONS = {
    "CreateAgent",
    "CreateApp",
    "CreateConversation",
    "CreateRelease",
    "CreateSkill",
    "CreateSpace",
    "ModifyAgent",
    "ModifyApp",
}


class ConfigError(ValueError):
    """Raised for missing or unsafe local configuration."""


class ApiError(RuntimeError):
    """Raised for a definite Tencent Cloud API error."""

    def __init__(self, code: str, message: str, request_id: str = "") -> None:
        suffix = f" (RequestId={request_id})" if request_id else ""
        super().__init__(f"{code}: {message}{suffix}")
        self.code = code
        self.request_id = request_id


class UncertainMutationError(RuntimeError):
    """Raised when a create/modify request may have reached the server."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward TC3 signatures or AppKey bodies to redirected hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if SENSITIVE_KEY_PATTERN.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def redact_message(message: str, settings: "Settings", body: Any = None) -> str:
    secrets = {
        settings.secret_id,
        settings.secret_key,
        settings.session_token,
        settings.skill_file_url,
    }

    def collect(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                if SENSITIVE_KEY_PATTERN.search(str(child_key)) and isinstance(child_value, str):
                    secrets.add(child_value)
                collect(child_value, str(child_key))
        elif isinstance(value, list):
            for item in value:
                collect(item, key)

    collect(body)
    sanitized = message
    for secret in sorted((value for value in secrets if len(value) >= 3), key=len, reverse=True):
        sanitized = sanitized.replace(secret, "<redacted>")
    return sanitized


def get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def get_int_env(name: str, default: int) -> int:
    raw = get_env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs without expansion; existing process variables win."""
    if not path.is_file():
        raise ConfigError(f"Environment file not found: {path}")
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            raise ConfigError(f"{path}:{line_number}: invalid environment key")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigError(f"{path}:{line_number}: unterminated quoted value")
            value = value[1:-1]
        os.environ.setdefault(key, value)


def configure_stdio() -> None:
    """Use UTF-8 for Chinese plans on Windows consoles and redirected output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=path.parent, newline="\n"
    ) as handle:
        handle.write(serialized)
        temporary = Path(handle.name)
    try:
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"Expected a JSON object in {path}")
    return value


def assert_no_secrets(value: Any, location: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if SENSITIVE_KEY_PATTERN.search(str(key)):
                raise ConfigError(f"Refusing to persist sensitive field {key!r} in {location}")
            assert_no_secrets(item, location)
    elif isinstance(value, list):
        for item in value:
            assert_no_secrets(item, location)


@dataclass(frozen=True)
class Settings:
    endpoint: str
    chat_endpoint: str
    region: str
    secret_id: str
    secret_key: str
    session_token: str
    account_fingerprint: str
    space_id: str
    space_name: str
    space_description: str
    app_name: str
    app_description: str
    agent_name: str
    agent_description: str
    model_id: str
    skill_id: str
    skill_name: str
    skill_file_url: str
    skill_version: str
    user_id: str
    instructions_path: Path
    acceptance_path: Path
    state_path: Path
    max_reasoning_rounds: int
    timeout_seconds: int
    release_timeout_seconds: int
    verbose: bool = False

    @classmethod
    def from_env(cls, *, require_credentials: bool, verbose: bool = False) -> "Settings":
        endpoint = get_env("ADP_ENDPOINT", DEFAULT_ENDPOINT)
        if "://" in endpoint or "/" in endpoint:
            raise ConfigError("ADP_ENDPOINT must be a hostname without scheme or path")
        if endpoint not in ALLOWED_ENDPOINTS:
            raise ConfigError(
                "ADP_ENDPOINT must be an official Tencent endpoint: "
                + ", ".join(sorted(ALLOWED_ENDPOINTS))
            )
        chat_default = (
            "https://adp.tencent.com/adp/v2/chat"
            if endpoint == "capi.adp.tencent.com"
            else DEFAULT_CHAT_ENDPOINT
        )
        settings = cls(
            endpoint=endpoint,
            chat_endpoint=get_env("ADP_CHAT_ENDPOINT", chat_default),
            region=get_env("ADP_REGION", DEFAULT_REGION),
            secret_id=get_env("TENCENTCLOUD_SECRET_ID"),
            secret_key=get_env("TENCENTCLOUD_SECRET_KEY"),
            session_token=get_env("TENCENTCLOUD_SESSION_TOKEN"),
            account_fingerprint=get_env("ADP_ACCOUNT_FINGERPRINT"),
            space_id=get_env("ADP_SPACE_ID", "default_space"),
            space_name=get_env("ADP_SPACE_NAME", "IBL Course Design"),
            space_description=get_env(
                "ADP_SPACE_DESCRIPTION", "AI research-based learning course design"
            ),
            app_name=get_env("ADP_APP_NAME", "IBL课程设计助手"),
            app_description=get_env(
                "ADP_APP_DESCRIPTION", "面向教师的AI与研究性学习课程设计Claw应用"
            ),
            agent_name=get_env("ADP_AGENT_NAME", "IBL课程设计主Agent"),
            agent_description=get_env(
                "ADP_AGENT_DESCRIPTION", "生成整套课程、单节教案、课件和学生物料"
            ),
            model_id=get_env("ADP_MODEL_ID"),
            skill_id=get_env("ADP_SKILL_ID"),
            skill_name=get_env("ADP_SKILL_NAME", "ibl-course-designer"),
            skill_file_url=get_env("ADP_SKILL_FILE_URL"),
            skill_version=get_env("ADP_SKILL_VERSION", "2.0.0"),
            user_id=get_env("ADP_TEST_USER_ID", "ibl-course-designer-acceptance"),
            instructions_path=Path(
                get_env("ADP_AGENT_INSTRUCTIONS_FILE", "config/agent-instructions.txt")
            ),
            acceptance_path=Path(
                get_env("ADP_ACCEPTANCE_FILE", "config/acceptance-cases.json")
            ),
            state_path=Path(get_env("ADP_STATE_FILE", ".state/adp-state.json")),
            max_reasoning_rounds=get_int_env("ADP_MAX_REASONING_ROUNDS", 100),
            timeout_seconds=get_int_env("ADP_HTTP_TIMEOUT_SECONDS", 60),
            release_timeout_seconds=get_int_env("ADP_RELEASE_TIMEOUT_SECONDS", 600),
            verbose=verbose,
        )
        if require_credentials and (not settings.secret_id or not settings.secret_key):
            raise ConfigError(
                "TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY are required"
            )
        if not settings.instructions_path.is_file():
            raise ConfigError(f"Agent instructions file not found: {settings.instructions_path}")
        if not settings.chat_endpoint.startswith("https://"):
            raise ConfigError("ADP_CHAT_ENDPOINT must use HTTPS")
        if settings.chat_endpoint not in ALLOWED_CHAT_ENDPOINTS:
            raise ConfigError(
                "ADP_CHAT_ENDPOINT must be an official Tencent endpoint: "
                + ", ".join(sorted(ALLOWED_CHAT_ENDPOINTS))
            )
        if settings.max_reasoning_rounds <= 0:
            raise ConfigError("ADP_MAX_REASONING_ROUNDS must be positive")
        return settings

    def instructions(self) -> str:
        return self.instructions_path.read_text(encoding="utf-8").strip()

    def desired(self) -> dict[str, Any]:
        blockers: list[str] = []
        if not self.model_id:
            blockers.append("Set ADP_MODEL_ID to a model returned for ModelScene=18")
        if not self.skill_id and not self.skill_file_url:
            blockers.append(
                "Upload dist/IBL-course-designer.zip in ADP, then set ADP_SKILL_ID; "
                "or set ADP_SKILL_FILE_URL from an authenticated console upload"
            )
        return {
            "api": {
                "endpoint": self.endpoint,
                "chat_endpoint": self.chat_endpoint,
                "region": self.region,
                "version": API_VERSION,
                "credential_identity_sha256": sha256_hex(
                    self.account_fingerprint or self.secret_id
                )
                if self.account_fingerprint or self.secret_id
                else None,
            },
            "space": {
                "id": self.space_id or None,
                "name": self.space_name,
                "description": self.space_description,
            },
            "app": {
                "name": self.app_name,
                "description": self.app_description,
                "mode": 4,
            },
            "agent": {
                "name": self.agent_name,
                "description": self.agent_description,
                "model_id": self.model_id or None,
                "instructions_sha256": sha256_hex(self.instructions()),
                "max_reasoning_rounds": self.max_reasoning_rounds,
            },
            "skill": {
                "id": self.skill_id or None,
                "name": self.skill_name,
                "version": self.skill_version,
                "file_url_configured": bool(self.skill_file_url),
                "file_url_sha256": sha256_hex(self.skill_file_url)
                if self.skill_file_url
                else None,
            },
            "test_user_id": self.user_id,
            "state_file_sha256": sha256_hex(str(self.state_path.resolve())),
            "acceptance_file_sha256": sha256_hex(self.acceptance_path.read_bytes())
            if self.acceptance_path.is_file()
            else None,
            "blockers": blockers,
        }


class TC3Client:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.url = f"https://{settings.endpoint}/"
        self.ssl_context = ssl.create_default_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.ssl_context), NoRedirectHandler()
        )

    def authorization(
        self, action: str, payload: str, timestamp: int
    ) -> tuple[str, dict[str, str]]:
        date = dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).strftime("%Y-%m-%d")
        content_type = "application/json; charset=utf-8"
        canonical_headers = f"content-type:{content_type}\nhost:{self.settings.endpoint}\n"
        signed_headers = "content-type;host"
        canonical_request = (
            "POST\n/\n\n"
            + canonical_headers
            + "\n"
            + signed_headers
            + "\n"
            + sha256_hex(payload)
        )
        credential_scope = f"{date}/{SERVICE}/tc3_request"
        string_to_sign = (
            "TC3-HMAC-SHA256\n"
            + str(timestamp)
            + "\n"
            + credential_scope
            + "\n"
            + sha256_hex(canonical_request)
        )

        def sign(key: bytes, message: str) -> bytes:
            return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

        secret_date = sign(("TC3" + self.settings.secret_key).encode("utf-8"), date)
        secret_service = sign(secret_date, SERVICE)
        secret_signing = sign(secret_service, "tc3_request")
        signature = hmac.new(
            secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        authorization = (
            "TC3-HMAC-SHA256 "
            f"Credential={self.settings.secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        headers = {
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": self.settings.endpoint,
            "X-TC-Action": action,
            "X-TC-Version": API_VERSION,
            "X-TC-Region": self.settings.region,
            "X-TC-Timestamp": str(timestamp),
        }
        if self.settings.session_token:
            headers["X-TC-Token"] = self.settings.session_token
        return authorization, headers

    def call(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = canonical_json(body)
        _, headers = self.authorization(action, payload, int(time.time()))
        if self.settings.verbose:
            print(f"REQUEST {action}: {canonical_json(redact(body))}", file=sys.stderr)
        request = urllib.request.Request(
            self.url, data=payload.encode("utf-8"), headers=headers, method="POST"
        )
        attempts = 1 if action in MUTATING_ACTIONS else 3
        for attempt in range(1, attempts + 1):
            try:
                with self.opener.open(request, timeout=self.settings.timeout_seconds) as response:
                    response_body = response.read()
                break
            except urllib.error.HTTPError as exc:
                response_body = exc.read()
                if 300 <= exc.code < 400:
                    raise ApiError(
                        "UnexpectedRedirect",
                        f"{action} endpoint returned HTTP {exc.code}; redirect refused",
                    ) from exc
                if action in MUTATING_ACTIONS and exc.code in {408, 429, 500, 502, 503, 504}:
                    raise UncertainMutationError(
                        f"{action} returned HTTP {exc.code} without a definite mutation outcome. "
                        "Do not retry it directly; rerun apply for discovery and reconciliation."
                    ) from exc
                if action not in MUTATING_ACTIONS and exc.code in {429, 500, 502, 503, 504}:
                    if attempt < attempts:
                        time.sleep(2 ** (attempt - 1))
                        continue
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                if action in MUTATING_ACTIONS:
                    raise UncertainMutationError(
                        f"{action} ended without a definite response. Do not retry it directly; "
                        "rerun apply so resource discovery can reconcile the result."
                    ) from exc
                if attempt == attempts:
                    raise ApiError("NetworkError", str(exc.reason if hasattr(exc, "reason") else exc)) from exc
                time.sleep(2 ** (attempt - 1))
        try:
            document = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("InvalidResponse", f"{action} returned invalid JSON") from exc
        response_value = document.get("Response")
        if not isinstance(response_value, dict):
            raise ApiError("InvalidResponse", f"{action} response has no Response object")
        error = response_value.get("Error")
        if isinstance(error, dict):
            raise ApiError(
                str(error.get("Code", "UnknownError")),
                redact_message(
                    str(error.get("Message", "Unknown Tencent Cloud API error")),
                    self.settings,
                    body,
                ),
                str(response_value.get("RequestId", "")),
            )
        if self.settings.verbose:
            print(
                f"RESPONSE {action}: RequestId={response_value.get('RequestId', '<missing>')}",
                file=sys.stderr,
            )
        return response_value


def page_number_list(
    api: TC3Client,
    action: str,
    body: dict[str, Any],
    list_key: str,
    *,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 0
    while True:
        request_body = dict(body, PageNumber=page, PageSize=page_size)
        response = api.call(action, request_body)
        page_items = response.get(list_key) or []
        if not isinstance(page_items, list):
            raise ApiError("InvalidResponse", f"{action}.{list_key} is not an array")
        items.extend(item for item in page_items if isinstance(item, dict))
        total = int(response.get("TotalCount") or len(items))
        if len(items) >= total or len(page_items) < page_size:
            return items
        page += 1


def choose_exact(
    items: Iterable[dict[str, Any]],
    *,
    name: str,
    name_getter,
    id_key: str,
    state_id: str = "",
    resource: str,
) -> dict[str, Any] | None:
    exact = [item for item in items if name_getter(item) == name]
    if len(exact) > 1:
        ids = ", ".join(str(item.get(id_key, "<unknown>")) for item in exact)
        raise ConfigError(f"Ambiguous {resource} name {name!r}; exact-match IDs: {ids}")
    if state_id and exact and str(exact[0].get(id_key, "")) != state_id:
        print(
            f"WARN: stored {resource} ID {state_id} no longer matches the unique exact-name resource",
            file=sys.stderr,
        )
    return exact[0] if exact else None


def subset_matches(current: Any, desired: Any) -> bool:
    if isinstance(desired, dict):
        return isinstance(current, dict) and all(
            key in current and subset_matches(current[key], value) for key, value in desired.items()
        )
    if isinstance(desired, list):
        return isinstance(current, list) and current == desired
    return current == desired


class Provisioner:
    def __init__(self, settings: Settings, api: TC3Client) -> None:
        self.settings = settings
        self.api = api
        self.state = self._load_state()
        self.changed = False

    def _load_state(self) -> dict[str, Any]:
        if not self.settings.state_path.exists():
            return {"schema_version": 1, "resources": {}}
        state = read_json(self.settings.state_path)
        assert_no_secrets(state, str(self.settings.state_path))
        state.setdefault("schema_version", 1)
        state.setdefault("resources", {})
        return state

    def save(self) -> None:
        assert_no_secrets(self.state, str(self.settings.state_path))
        atomic_write_json(self.settings.state_path, self.state)

    @property
    def resources(self) -> dict[str, Any]:
        return self.state.setdefault("resources", {})

    def ensure_space(self) -> str:
        if self.settings.space_id:
            self.resources["space_id"] = self.settings.space_id
            self.save()
            print(f"REUSE space {self.settings.space_id}")
            return self.settings.space_id
        response = self.api.call("DescribeSpaceList", {"Query": self.settings.space_name})
        spaces = response.get("SpaceList") or []
        selected = choose_exact(
            spaces,
            name=self.settings.space_name,
            name_getter=lambda item: item.get("Name"),
            id_key="SpaceId",
            state_id=str(self.resources.get("space_id", "")),
            resource="space",
        )
        if selected:
            space_id = str(selected["SpaceId"])
            print(f"REUSE space {space_id}")
        else:
            response = self.api.call(
                "CreateSpace",
                {
                    "Name": self.settings.space_name,
                    "Description": self.settings.space_description,
                },
            )
            space_id = str(response["SpaceId"])
            self.changed = True
            print(f"CREATE space {space_id}")
        self.resources["space_id"] = space_id
        self.save()
        return space_id

    def ensure_app(self, space_id: str) -> str:
        apps = page_number_list(
            self.api,
            "DescribeAppSummaryList",
            {
                "SpaceId": space_id,
                "Query": self.settings.app_name,
                "FilterList": [
                    {"Name": "AppMode", "Operator": 0, "ValueList": ["4"]}
                ],
            },
            "AppSummaryList",
        )
        selected = choose_exact(
            apps,
            name=self.settings.app_name,
            name_getter=lambda item: item.get("Name"),
            id_key="AppId",
            state_id=str(self.resources.get("app_id", "")),
            resource="Claw application",
        )
        if selected:
            app_id = str(selected["AppId"])
            print(f"REUSE app {app_id}")
        else:
            response = self.api.call(
                "CreateApp",
                {
                    "SpaceId": space_id,
                    "AppMode": 4,
                    "Name": self.settings.app_name,
                    "Description": self.settings.app_description,
                },
            )
            app_id = str(response["AppId"])
            self.changed = True
            print(f"CREATE app {app_id}")
        self.resources["app_id"] = app_id
        self.save()
        return app_id

    def ensure_model(self, space_id: str) -> str:
        if not self.settings.model_id:
            raise ConfigError("ADP_MODEL_ID is required before apply")
        models = page_number_list(
            self.api,
            "DescribeModelList",
            {"ModelScene": 18, "SpaceId": space_id},
            "ModelList",
        )
        available = {
            str((item.get("ModelBasic") or {}).get("ModelId", "")) for item in models
        }
        if self.settings.model_id not in available:
            raise ConfigError(
                f"ADP_MODEL_ID {self.settings.model_id!r} is not available for Claw ModelScene=18"
            )
        print(f"VERIFY model {self.settings.model_id}")
        return self.settings.model_id

    def ensure_skill(self, space_id: str) -> str:
        if self.settings.skill_id:
            skills = page_number_list(
                self.api,
                "DescribeSkillSummaryList",
                {
                    "SpaceId": space_id,
                    "FilterList": [
                        {
                            "Name": "SkillIdList",
                            "Operator": 0,
                            "ValueList": [self.settings.skill_id],
                        }
                    ],
                },
                "SkillSummaryList",
            )
            id_matches = [
                item for item in skills if str(item.get("SkillId", "")) == self.settings.skill_id
            ]
            if len(id_matches) != 1:
                raise ConfigError(
                    f"ADP_SKILL_ID {self.settings.skill_id!r} was not found uniquely in {space_id}"
                )
            selected = id_matches[0]
        else:
            skills = page_number_list(
                self.api,
                "DescribeSkillSummaryList",
                {"SpaceId": space_id, "Query": self.settings.skill_name},
                "SkillSummaryList",
            )
            selected = choose_exact(
                skills,
                name=self.settings.skill_name,
                name_getter=lambda item: (item.get("Profile") or {}).get("Name"),
                id_key="SkillId",
                state_id=str(self.resources.get("skill_id", "")),
                resource="Skill",
            )
        if selected:
            current_version = str(
                (selected.get("CurrentVersionInfo") or {}).get("Version", "")
            )
            current_version_id = str(
                (selected.get("CurrentVersionInfo") or {}).get("VersionId", "")
            )
            if current_version != self.settings.skill_version:
                raise ConfigError(
                    f"Skill version mismatch: expected {self.settings.skill_version}, "
                    f"found {current_version or '<missing>'}. Upload/select the intended version."
                )
            analysis_status = (
                ((selected.get("CurrentVersionInfo") or {}).get("AnalysisInfo") or {}).get(
                    "AnalysisStatus"
                )
            )
            if analysis_status is None or int(analysis_status) != 2:
                raise ConfigError(
                    f"Skill security analysis is not available (status {analysis_status}); "
                    "wait for ADP analysis to complete before apply"
                )
            skill_id = str(selected["SkillId"])
            print(f"REUSE verified Skill {skill_id} version {current_version}")
            self.resources["skill_id"] = skill_id
            self.resources["skill_version"] = current_version
            self.resources["skill_version_id"] = current_version_id
            self.save()
            return skill_id
        if not self.settings.skill_file_url:
            raise ConfigError(
                "Skill not found. Upload dist/IBL-course-designer.zip in ADP and set "
                "ADP_SKILL_ID, or provide ADP_SKILL_FILE_URL obtained from the console."
            )
        response = self.api.call(
            "CreateSkill",
            {
                "CreateType": 1,
                "FileUrl": self.settings.skill_file_url,
                "SpaceId": space_id,
                "Name": self.settings.skill_name,
                "SkillVersion": self.settings.skill_version,
                "DisplayName": "IBL课程设计师",
                "DisplayDescription": "生成整套课程、单节教案、课件和学生留痕物料",
                "UpdateDescription": "Automated idempotent provisioning",
            },
        )
        skill_id = str(response["SkillId"])
        self.changed = True
        print(f"CREATE Skill {skill_id}; waiting for ADP security analysis")
        self.resources["skill_id"] = skill_id
        self.resources["skill_version"] = self.settings.skill_version
        self.resources["skill_version_id"] = str(response.get("VersionId", ""))
        self.save()
        deadline = time.monotonic() + self.settings.release_timeout_seconds
        while time.monotonic() < deadline:
            matches = page_number_list(
                self.api,
                "DescribeSkillSummaryList",
                {
                    "SpaceId": space_id,
                    "FilterList": [
                        {"Name": "SkillIdList", "Operator": 0, "ValueList": [skill_id]}
                    ],
                },
                "SkillSummaryList",
            )
            exact_matches = [
                item
                for item in matches
                if str(item.get("SkillId", "")) == skill_id
                and str((item.get("CurrentVersionInfo") or {}).get("Version", ""))
                == self.settings.skill_version
            ]
            if len(exact_matches) > 1:
                raise ConfigError(f"Skill {skill_id} returned duplicate version summaries")
            if exact_matches:
                analysis_status = (
                    (
                        (exact_matches[0].get("CurrentVersionInfo") or {}).get("AnalysisInfo")
                        or {}
                    ).get("AnalysisStatus")
                )
                if analysis_status is not None and int(analysis_status) == 2:
                    self.resources["skill_version_id"] = str(
                        (exact_matches[0].get("CurrentVersionInfo") or {}).get(
                            "VersionId", self.resources.get("skill_version_id", "")
                        )
                    )
                    self.save()
                    print(f"AVAILABLE Skill {skill_id}")
                    return skill_id
                if analysis_status is not None and int(analysis_status) in {3, 4}:
                    raise ApiError(
                        "SkillAnalysisFailed",
                        f"Skill {skill_id} security analysis ended with status {analysis_status}",
                    )
            time.sleep(2)
        raise ApiError(
            "SkillAnalysisTimeout",
            f"Skill {skill_id} did not become available within "
            f"{self.settings.release_timeout_seconds} seconds; rerun apply to reconcile it",
        )

    def _desired_agent(self, model_id: str, skill_id: str) -> dict[str, Any]:
        return {
            "Profile": {
                "Name": self.settings.agent_name,
                "Role": 0,
                "Description": self.settings.agent_description,
            },
            "Instructions": self.settings.instructions(),
            "Model": {
                "ModelId": model_id,
                "ContextWordsLimit": 20000,
                "InstructionsWordsLimit": 20000,
            },
            "ToolList": [],
            "PluginList": [],
            "SkillList": [{"SkillId": skill_id}],
            "AdvancedConfig": {"MaxReasoningRound": self.settings.max_reasoning_rounds},
        }

    def ensure_agent(self, app_id: str, model_id: str, skill_id: str) -> str:
        agents = page_number_list(
            self.api,
            "DescribeAgentSummaryList",
            {"Scope": 0, "AppId": app_id},
            "AgentList",
        )
        selected = choose_exact(
            agents,
            name=self.settings.agent_name,
            name_getter=lambda item: (item.get("Profile") or {}).get("Name"),
            id_key="AgentId",
            state_id=str(self.resources.get("agent_id", "")),
            resource="Agent",
        )
        desired = self._desired_agent(model_id, skill_id)
        if not selected:
            response = self.api.call(
                "CreateAgent", {"AppId": app_id, "Kind": 0, "Agent": desired}
            )
            agent_id = str(response["AgentId"])
            self.changed = True
            print(f"CREATE Agent {agent_id}")
        else:
            agent_id = str(selected["AgentId"])
            detail = self.api.call(
                "DescribeAgentDetail", {"AppId": app_id, "AgentId": agent_id}
            ).get("Agent") or {}
            update: dict[str, Any] = {}
            paths: list[str] = []
            profile = detail.get("Profile") or {}
            if profile.get("Role") not in {None, 0}:
                raise ConfigError(
                    f"Existing Agent {agent_id} is not a main Agent (Role={profile.get('Role')})"
                )
            if profile.get("Name") != self.settings.agent_name:
                update["Profile"] = {"Name": self.settings.agent_name}
                paths.append("Profile.Name")
            for field, path in (
                ("Instructions", "Instructions"),
                ("Model", "Model"),
                ("AdvancedConfig", "AdvancedConfig"),
            ):
                if not subset_matches(detail.get(field), desired[field]):
                    update[field] = desired[field]
                    paths.append(path)
            current_tools = detail.get("ToolList") or []
            if current_tools:
                update["ToolList"] = []
                paths.append("ToolList")
            current_plugins = detail.get("PluginList") or []
            if current_plugins:
                update["PluginList"] = []
                paths.append("PluginList")
            current_skill_ids = [
                str(item.get("SkillId"))
                for item in detail.get("SkillList") or []
                if item.get("SkillId")
            ]
            if current_skill_ids != [skill_id]:
                update["SkillList"] = [{"SkillId": skill_id}]
                paths.append("SkillList")
            if paths:
                self.api.call(
                    "ModifyAgent",
                    {
                        "AppId": app_id,
                        "AgentId": agent_id,
                        "Agent": update,
                        "UpdateMask": {"Paths": paths},
                    },
                )
                self.changed = True
                print(f"UPDATE Agent {agent_id}: {', '.join(paths)}")
            else:
                print(f"REUSE Agent {agent_id}; configuration already matches")
        self.resources["agent_id"] = agent_id
        release_identity = {
            "app_id": app_id,
            "agent_id": agent_id,
            "skill_id": skill_id,
            "skill_version": self.resources.get("skill_version"),
            "skill_version_id": self.resources.get("skill_version_id"),
            "agent": desired,
        }
        self.resources["agent_config_sha256"] = sha256_hex(canonical_json(release_identity))
        self.save()
        return agent_id

    def publish_if_changed(self, app_id: str) -> str:
        desired_hash = str(self.resources.get("agent_config_sha256", ""))
        published_hash = str(self.resources.get("published_agent_config_sha256", ""))
        expected_description = self._release_description(desired_hash)
        if desired_hash and hmac.compare_digest(desired_hash, published_hash):
            release_id = str(self.resources.get("release_id", ""))
            if release_id:
                summary = self._release_summary(app_id, release_id)
                if (
                    int(summary.get("Status") or 0) == 3
                    and summary.get("Description") == expected_description
                ):
                    print(
                        "SKIP release; matching configuration and ReleaseId are remotely confirmed"
                    )
                    return release_id
            self.resources.pop("published_agent_config_sha256", None)
            self.save()

        previous_release = str(self.resources.get("release_id", ""))
        previous_hash = str(self.resources.get("release_agent_config_sha256", ""))
        if previous_release and previous_hash == desired_hash:
            summary = self._release_summary(app_id, previous_release)
            status = int(summary.get("Status") or 0)
            description_matches = summary.get("Description") == expected_description
            if status == 3 and description_matches:
                self.resources["published_agent_config_sha256"] = desired_hash
                self.save()
                print(f"RECONCILE published release {previous_release}")
                return previous_release
            if description_matches and status not in {4, 7, 12}:
                return self._complete_release(app_id, previous_release, desired_hash)

        uncertain_hash = str(self.resources.get("uncertain_release_config_sha256", ""))
        if uncertain_hash == desired_hash:
            raise ConfigError(
                "A prior CreateRelease may have succeeded but returned no ReleaseId. "
                "Inspect the ADP release list and reconcile .state before creating another release."
            )

        self.resources["uncertain_release_config_sha256"] = desired_hash
        self.save()
        try:
            response = self.api.call(
                "CreateRelease",
                {
                    "AppId": app_id,
                    "Description": expected_description,
                },
            )
        except ApiError:
            self.resources.pop("uncertain_release_config_sha256", None)
            self.save()
            raise
        release_id = str(response["ReleaseId"])
        self.resources.pop("uncertain_release_config_sha256", None)
        self.resources["release_id"] = release_id
        self.resources["release_agent_config_sha256"] = desired_hash
        self.save()
        print(f"CREATE release {release_id}; waiting for completion")
        return self._complete_release(app_id, release_id, desired_hash)

    @staticmethod
    def _release_description(desired_hash: str) -> str:
        return f"IBL course designer config {desired_hash[:16]}"

    def _release_summary(self, app_id: str, release_id: str) -> dict[str, Any]:
        summary = self.api.call(
            "DescribeReleaseSummary", {"AppId": app_id, "ReleaseId": release_id}
        ).get("ReleaseSummary") or {}
        if not isinstance(summary, dict):
            raise ApiError("InvalidResponse", "DescribeReleaseSummary returned invalid data")
        return summary

    def _wait_for_release(
        self, app_id: str, release_id: str, *, wait_for_pending: bool
    ) -> int:
        deadline = time.monotonic() + self.settings.release_timeout_seconds
        while True:
            summary = self._release_summary(app_id, release_id)
            status = int(summary.get("Status") or 0)
            if status in {3, 4, 7, 9, 12}:
                return status
            if not wait_for_pending:
                return status
            if time.monotonic() >= deadline:
                raise ApiError(
                    "ReleaseTimeout",
                    f"Release {release_id} did not reach status 3 within "
                    f"{self.settings.release_timeout_seconds} seconds",
                )
            time.sleep(2)

    def _complete_release(self, app_id: str, release_id: str, desired_hash: str) -> str:
        status = self._wait_for_release(app_id, release_id, wait_for_pending=True)
        if status == 3:
            print(f"PUBLISHED release {release_id}")
            self.resources["published_agent_config_sha256"] = desired_hash
            self.save()
            return release_id
        if status in {4, 7, 12}:
            raise ApiError("ReleaseFailed", f"Release {release_id} ended with status {status}")
        raise ApiError("ReleasePaused", f"Release {release_id} requires intervention")

    def app_key(self, app_id: str) -> str:
        response = self.api.call(
            "DescribeApp", {"AppId": app_id, "FieldMask": {"Paths": ["SecretInfo"]}}
        )
        app_key = str(((response.get("App") or {}).get("SecretInfo") or {}).get("AppKey", ""))
        if not app_key:
            raise ApiError("MissingAppKey", "DescribeApp returned no SecretInfo.AppKey")
        return app_key

    def ensure_conversation(self, app_id: str, app_key: str, user_id: str) -> str:
        response = self.api.call(
            "DescribeConversationList",
            {
                "Type": 5,
                "AppId": app_id,
                "AppKey": app_key,
                "UserId": user_id,
                "Offset": 0,
                "Limit": 100,
            },
        )
        conversations = response.get("ConversationList")
        if conversations is None:
            conversations = response.get("Conversations") or []
        state_conversations = self.resources.setdefault("conversations", {})
        state_id = str(state_conversations.get(user_id, ""))
        selected = next(
            (
                item
                for item in conversations
                if isinstance(item, dict) and str(item.get("ConversationId", "")) == state_id
            ),
            None,
        )
        if selected is None and conversations:
            selected = max(
                (item for item in conversations if isinstance(item, dict)),
                key=lambda item: int(item.get("UpdateTime") or item.get("CreateTime") or 0),
            )
        if selected:
            conversation_id = str(selected["ConversationId"])
            print(f"REUSE conversation {conversation_id} for {user_id}")
        else:
            response = self.api.call(
                "CreateConversation",
                {"Type": 5, "AppId": app_id, "AppKey": app_key, "UserId": user_id},
            )
            conversation_id = str(response["ConversationId"])
            print(f"CREATE conversation {conversation_id} for {user_id}")
        state_conversations[user_id] = conversation_id
        self.save()
        return conversation_id

    def apply(self) -> dict[str, str]:
        space_id = self.ensure_space()
        app_id = self.ensure_app(space_id)
        model_id = self.ensure_model(space_id)
        skill_id = self.ensure_skill(space_id)
        agent_id = self.ensure_agent(app_id, model_id, skill_id)
        release_id = self.publish_if_changed(app_id)
        app_key = self.app_key(app_id)
        conversation_id = self.ensure_conversation(
            app_id, app_key, self.settings.user_id
        )
        return {
            "space_id": space_id,
            "app_id": app_id,
            "skill_id": skill_id,
            "agent_id": agent_id,
            "release_id": release_id,
            "conversation_id": conversation_id,
        }


def iter_sse(response) -> Iterable[dict[str, Any]]:
    def decode(data_lines: list[str]) -> dict[str, Any] | None:
        data = "\n".join(data_lines)
        if data == "[DONE]":
            return {"Type": "response.completed"}
        try:
            event = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ApiError("InvalidSSE", "Chat endpoint returned invalid SSE JSON") from exc
        return event if isinstance(event, dict) else None

    data_lines: list[str] = []
    for raw_line in response:
        try:
            line = raw_line.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            raise ApiError("InvalidSSE", "Chat endpoint returned non-UTF-8 SSE data") from exc
        if not line:
            if data_lines:
                event = decode(data_lines)
                if event:
                    yield event
                data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        event = decode(data_lines)
        if event:
            yield event


def chat(
    settings: Settings,
    *,
    conversation_id: str,
    app_key: str,
    visitor_id: str,
    message: str,
) -> tuple[str, list[dict[str, Any]]]:
    body = {
        "RequestId": uuid.uuid4().hex,
        "ConversationId": conversation_id,
        "AppKey": app_key,
        "VisitorId": visitor_id,
        "Contents": [{"Type": "text", "Text": message}],
        "Incremental": True,
        "EnableMultiIntent": True,
        "Stream": "enable",
    }
    request = urllib.request.Request(
        settings.chat_endpoint,
        data=canonical_json(body).encode("utf-8"),
        headers={"Accept": "text/event-stream", "Content-Type": "application/json"},
        method="POST",
    )
    text_parts: list[str] = []
    final_text_parts: list[str] = []
    files: list[dict[str, Any]] = []
    completed = False
    try:
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            NoRedirectHandler(),
        )
        with opener.open(request, timeout=settings.timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/event-stream" not in content_type:
                raise ApiError(
                    "InvalidChatContentType",
                    f"Expected text/event-stream, received {content_type or '<missing>'}",
                )
            for event in iter_sse(response):
                event_type = str(event.get("Type", ""))
                if event.get("Error") or event_type in {
                    "error",
                    "request.error",
                    "response.failed",
                    "message.failed",
                }:
                    error = event.get("Error") or event
                    raise ApiError(
                        "ChatFailed",
                        redact_message(canonical_json(error), settings, body),
                    )
                if event_type == "text.delta":
                    text_parts.append(str(event.get("Text", "")))
                elif event_type == "message.done":
                    message_value = event.get("Message") or event
                    for content in message_value.get("Contents") or []:
                        if content.get("Type") == "text" and content.get("Text"):
                            final_text_parts.append(str(content["Text"]))
                        if content.get("Type") == "file" and isinstance(content.get("File"), dict):
                            file_info = content["File"]
                            files.append(
                                {
                                    "FileName": file_info.get("FileName"),
                                    "FileSize": file_info.get("FileSize"),
                                    "FileType": file_info.get("FileType"),
                                    "FileUrl": "<redacted>",
                                }
                            )
                elif event_type == "response.completed":
                    completed = True
                    break
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise ApiError(
                "UnexpectedChatRedirect",
                f"Chat endpoint returned HTTP {exc.code}; redirect refused",
            ) from exc
        raise ApiError("ChatHTTPError", f"HTTP {exc.code} from chat endpoint") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError("ChatNetworkError", str(exc.reason if hasattr(exc, "reason") else exc)) from exc
    if not completed:
        raise ApiError("IncompleteChat", "Chat SSE stream ended before response.completed")
    return "".join(text_parts) or "".join(final_text_parts), files


def build_plan(settings: Settings) -> dict[str, Any]:
    desired = settings.desired()
    base = {
        "schema_version": 1,
        "desired": desired,
        "operations": [
            "Resolve or create workspace by exact identity",
            "Resolve or create AppMode=4 application by exact name",
            "Verify ModelScene=18 model",
            "Resolve or create the custom Skill",
            "Resolve, create, or minimally update the main Agent",
            "Publish only when a managed resource or Agent configuration changed",
            "Resolve or create one API test conversation",
            "Reconcile an explicitly reviewed ReleaseId after an uncertain response",
        ],
        "safety": {
            "mutation_retries": 0,
            "ambiguous_exact_matches": "stop",
            "secrets_persisted": False,
            "skill_file_url_persisted": False,
            "approved_online_commands": [
                "apply",
                "test",
                "acceptance",
                "reconcile-release",
            ],
        },
    }
    base["approval_hash"] = sha256_hex(canonical_json(base))
    return base


def write_plan(settings: Settings, path: Path) -> dict[str, Any]:
    plan = build_plan(settings)
    atomic_write_json(path, plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print(f"\nPlan written to {path}")
    print(f"Approval hash: {plan['approval_hash']}")
    print("No network request or cloud mutation was performed.")
    return plan


def verify_approval(settings: Settings, path: Path, supplied_hash: str) -> dict[str, Any]:
    if not supplied_hash:
        raise ConfigError("This online operation requires --approve <hash> from the plan command")
    plan = read_json(path)
    expected_hash = str(plan.get("approval_hash", ""))
    unsigned = dict(plan)
    unsigned.pop("approval_hash", None)
    calculated = sha256_hex(canonical_json(unsigned))
    if not hmac.compare_digest(expected_hash, calculated):
        raise ConfigError("Plan file integrity check failed; generate a new plan")
    if not hmac.compare_digest(expected_hash, supplied_hash):
        raise ConfigError("Approval hash does not match the reviewed plan")
    current_desired = settings.desired()
    if current_desired != plan.get("desired"):
        raise ConfigError("Environment/configuration changed after planning; generate and review a new plan")
    blockers = current_desired.get("blockers") or []
    if blockers:
        raise ConfigError("Plan has unresolved blocker(s): " + "; ".join(blockers))
    return plan


def load_runtime(
    settings: Settings, *, with_app_key: bool = True
) -> tuple[TC3Client, Provisioner, str, str]:
    api = TC3Client(settings)
    provisioner = Provisioner(settings, api)
    app_id = str(provisioner.resources.get("app_id", ""))
    if not app_id:
        raise ConfigError("No app_id in state; run an approved apply first")
    space_id = str(provisioner.resources.get("space_id", ""))
    if not space_id:
        raise ConfigError("No space_id in state; run an approved apply first")
    if settings.space_id and settings.space_id != space_id:
        raise ConfigError("State space_id does not match the approved ADP_SPACE_ID")
    if not settings.space_id:
        spaces = api.call("DescribeSpaceList", {"Query": settings.space_name}).get(
            "SpaceList"
        ) or []
        matching_spaces = [
            item
            for item in spaces
            if item.get("Name") == settings.space_name
            and str(item.get("SpaceId", "")) == space_id
        ]
        exact_name_count = sum(item.get("Name") == settings.space_name for item in spaces)
        if exact_name_count != 1 or len(matching_spaces) != 1:
            raise ConfigError(
                "State space_id is not the unique approved-name workspace"
            )
    apps = page_number_list(
        api,
        "DescribeAppSummaryList",
        {
            "SpaceId": space_id,
            "Query": settings.app_name,
            "FilterList": [{"Name": "AppMode", "Operator": 0, "ValueList": ["4"]}],
        },
        "AppSummaryList",
    )
    selected = choose_exact(
        apps,
        name=settings.app_name,
        name_getter=lambda item: item.get("Name"),
        id_key="AppId",
        state_id=app_id,
        resource="runtime Claw application",
    )
    if not selected or str(selected.get("AppId", "")) != app_id:
        raise ConfigError(
            "State app_id is not the unique approved-name Claw application in the approved space"
        )
    app_key = provisioner.app_key(app_id) if with_app_key else ""
    return api, provisioner, app_id, app_key


def run_acceptance(settings: Settings) -> int:
    _, provisioner, app_id, app_key = load_runtime(settings)
    specification = read_json(settings.acceptance_path)
    cases = specification.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ConfigError("Acceptance file must contain a non-empty cases array")
    failures: list[str] = []
    for case in cases:
        name = str(case.get("name", "unnamed"))
        visitor_id = str(case.get("user_id", f"acceptance-{sha256_hex(name)[:12]}"))
        conversation_id = provisioner.ensure_conversation(app_id, app_key, visitor_id)
        print(f"CASE {name}")
        for index, turn in enumerate(case.get("turns") or [], start=1):
            response_text, files = chat(
                settings,
                conversation_id=conversation_id,
                app_key=app_key,
                visitor_id=visitor_id,
                message=str(turn.get("message", "")),
            )
            print(f"  TURN {index}: {len(response_text)} chars, {len(files)} file(s)")
            for required in turn.get("must_contain_all") or []:
                if required not in response_text:
                    failures.append(f"{name} turn {index}: missing required text {required!r}")
            any_values = turn.get("must_contain_any") or []
            if any_values and not any(value in response_text for value in any_values):
                failures.append(
                    f"{name} turn {index}: none of {', '.join(repr(v) for v in any_values)} found"
                )
            for forbidden in turn.get("must_not_contain") or []:
                if forbidden in response_text:
                    failures.append(f"{name} turn {index}: forbidden text {forbidden!r} found")
            maximum = turn.get("max_question_marks")
            if maximum is not None and response_text.count("？") + response_text.count("?") > int(maximum):
                failures.append(f"{name} turn {index}: more than {maximum} question marks")
    if failures:
        print("ACCEPTANCE FAILED", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ACCEPTANCE PASSED")
    return 0


def print_status(settings: Settings) -> int:
    api = TC3Client(settings)
    state = read_json(settings.state_path) if settings.state_path.exists() else {"resources": {}}
    assert_no_secrets(state, str(settings.state_path))
    resources = state.get("resources") or {}
    print(json.dumps({"local_state": resources}, ensure_ascii=False, indent=2))
    app_id = str(resources.get("app_id", ""))
    agent_id = str(resources.get("agent_id", ""))
    if app_id:
        app = api.call("DescribeApp", {"AppId": app_id}).get("App") or {}
        print(
            json.dumps(
                {
                    "remote_app": {
                        "AppId": app.get("AppId"),
                        "Name": app.get("Name"),
                        "AppMode": app.get("AppMode"),
                        "Status": app.get("Status"),
                    }
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    if app_id and agent_id:
        agent = api.call(
            "DescribeAgentDetail", {"AppId": app_id, "AgentId": agent_id}
        ).get("Agent") or {}
        print(
            json.dumps(
                {
                    "remote_agent": {
                        "AgentId": agent.get("AgentId"),
                        "Name": (agent.get("Profile") or {}).get("Name"),
                        "SkillIds": [
                            item.get("SkillId") for item in agent.get("SkillList") or []
                        ],
                    }
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="Log redacted request metadata")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Load missing environment variables from KEY=VALUE lines",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Create an offline, reviewable plan")
    plan.add_argument("--plan-file", type=Path, default=Path(".state/adp-plan.json"))

    apply = subparsers.add_parser("apply", help="Apply a previously approved plan")
    apply.add_argument("--plan-file", type=Path, default=Path(".state/adp-plan.json"))
    apply.add_argument("--approve", required=True, help="Approval hash printed by plan")

    status = subparsers.add_parser("status", help="Read local and remote resource status")
    status.set_defaults(read_only=True)

    test = subparsers.add_parser("test", help="Send one test message to the API conversation")
    test.add_argument("--plan-file", type=Path, default=Path(".state/adp-plan.json"))
    test.add_argument("--approve", required=True)
    test.add_argument("--message", required=True)

    acceptance = subparsers.add_parser("acceptance", help="Run multi-turn acceptance cases")
    acceptance.add_argument("--plan-file", type=Path, default=Path(".state/adp-plan.json"))
    acceptance.add_argument("--approve", required=True)

    reconcile = subparsers.add_parser(
        "reconcile-release",
        help="Bind and poll a console-reviewed ReleaseId after an uncertain create",
    )
    reconcile.add_argument("--plan-file", type=Path, default=Path(".state/adp-plan.json"))
    reconcile.add_argument("--approve", required=True)
    reconcile.add_argument("--release-id", required=True)
    return parser


def main() -> int:
    configure_stdio()
    parser = make_parser()
    args = parser.parse_args()
    require_credentials = args.command != "plan"
    try:
        if args.env_file:
            load_env_file(args.env_file)
        settings = Settings.from_env(
            require_credentials=require_credentials, verbose=args.verbose
        )
        if args.command == "plan":
            write_plan(settings, args.plan_file)
            return 0
        if args.command in {"apply", "test", "acceptance", "reconcile-release"}:
            verify_approval(settings, args.plan_file, args.approve)
        if args.command == "apply":
            resources = Provisioner(settings, TC3Client(settings)).apply()
            print(json.dumps(resources, ensure_ascii=False, indent=2))
            return 0
        if args.command == "status":
            return print_status(settings)
        if args.command == "test":
            _, provisioner, app_id, app_key = load_runtime(settings)
            conversation_id = provisioner.ensure_conversation(
                app_id, app_key, settings.user_id
            )
            response_text, files = chat(
                settings,
                conversation_id=conversation_id,
                app_key=app_key,
                visitor_id=settings.user_id,
                message=args.message,
            )
            print(response_text)
            if files:
                print(json.dumps({"files": files}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "acceptance":
            return run_acceptance(settings)
        if args.command == "reconcile-release":
            _, provisioner, app_id, _ = load_runtime(settings, with_app_key=False)
            desired_hash = str(provisioner.resources.get("agent_config_sha256", ""))
            uncertain_hash = str(
                provisioner.resources.get("uncertain_release_config_sha256", "")
            )
            if not desired_hash or uncertain_hash != desired_hash:
                raise ConfigError(
                    "State has no uncertain CreateRelease for the current Agent configuration"
                )
            summary = provisioner._release_summary(app_id, args.release_id)
            expected_description = provisioner._release_description(desired_hash)
            if summary.get("Description") != expected_description:
                raise ConfigError(
                    "Release description does not match the current configuration fingerprint"
                )
            provisioner.resources["release_id"] = args.release_id
            provisioner.resources["release_agent_config_sha256"] = desired_hash
            provisioner.resources.pop("uncertain_release_config_sha256", None)
            provisioner.save()
            provisioner._complete_release(app_id, args.release_id, desired_hash)
            return 0
        parser.error(f"Unsupported command: {args.command}")
    except (ConfigError, ApiError, UncertainMutationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
