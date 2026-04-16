"""PII-safe helpers for telemetry attributes and trace text."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b")
_GUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_TOKEN_RE = re.compile(r"(?i)\b(?:bearer|token|secret|password|api[_-]?key)\s*[:=]\s*\S+")
_LONG_NUMBER_RE = re.compile(r"\b\d{7,}\b")
_NAME_FIELD_RE = re.compile(
    r"(?i)(?<![A-Z0-9_])(?P<prefix>['\"]?"
    r"(?:employee_name|employee name|new_hire_name|new hire name|candidate_name|candidate name|"
    r"hiring_manager_name|hiring manager name|manager_name|manager name|treasurer_name|"
    r"treasurer name|staff_name|staff name|name)"
    r"['\"]?\s*[:=]\s*['\"])(?P<value>[^'\"]+)(?P<suffix>['\"])",
)

_SENSITIVE_KEY_PARTS = (
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "connection_string",
    "cosmos_key",
    "envelope_id",
    "graph_excel_drive_id",
    "graph_excel_item_id",
    "key",
    "password",
    "private_key",
    "secret",
    "token",
)

_NAME_KEYS = {
    "candidate_name",
    "employee_name",
    "hiring_manager_name",
    "manager_name",
    "name",
    "new_hire_name",
    "staff_name",
    "treasurer_name",
}


def hash_identifier(value: str | None, *, salt: str = "") -> str:
    """Return a stable short hash for identifiers without exposing the raw value."""
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    digest = hashlib.sha256(f"{salt}:{normalized}".encode()).hexdigest()
    return digest[:16]


def email_domain(value: str | None) -> str:
    """Return only the email domain, or an empty string when the value is not email-like."""
    raw = str(value or "").strip()
    if "@" not in raw:
        return ""
    return raw.rsplit("@", 1)[1].lower()


def redact_text(value: Any, *, salt: str = "", capture_full_payloads: bool = False) -> str:
    """Redact text before it is exported to AI observability backends."""
    text = str(value or "")
    if capture_full_payloads:
        return text

    def _replace_email(match: re.Match[str]) -> str:
        email = match.group(0)
        domain = match.group(1).lower()
        return f"<EMAIL:{hash_identifier(email, salt=salt)}@{domain}>"

    redacted = _EMAIL_RE.sub(_replace_email, text)
    redacted = _NAME_FIELD_RE.sub(lambda match: f"{match.group('prefix')}<NAME>{match.group('suffix')}", redacted)
    redacted = _GUID_RE.sub("<ID>", redacted)
    redacted = _TOKEN_RE.sub(lambda match: match.group(0).split()[0] + " <REDACTED>", redacted)
    redacted = _LONG_NUMBER_RE.sub("<NUMBER>", redacted)
    return redacted


def safe_attribute_value(value: Any, *, salt: str = "", capture_full_payloads: bool = False) -> Any:
    """Normalize an attribute value into an OpenTelemetry-safe, PII-conscious value."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return redact_text(value, salt=salt, capture_full_payloads=capture_full_payloads)
    if isinstance(value, list | tuple):
        return [safe_attribute_value(item, salt=salt, capture_full_payloads=capture_full_payloads) for item in value[:20]]
    if isinstance(value, Mapping):
        return json.dumps(
            safe_attributes(value, salt=salt, capture_full_payloads=capture_full_payloads),
            sort_keys=True,
            default=str,
        )[:4000]
    return redact_text(value, salt=salt, capture_full_payloads=capture_full_payloads)


def safe_attributes(
    attrs: Mapping[str, Any],
    *,
    salt: str = "",
    capture_full_payloads: bool = False,
) -> dict[str, Any]:
    """Return telemetry attributes with sensitive keys redacted and values normalized."""
    safe: dict[str, Any] = {}
    for raw_key, value in attrs.items():
        key = str(raw_key)
        lowered = key.lower()
        if _is_name_key(lowered):
            if value:
                safe[key] = "<NAME>"
            continue
        if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            if value:
                safe[key] = "<REDACTED>"
            continue
        safe[key] = safe_attribute_value(
            value,
            salt=salt,
            capture_full_payloads=capture_full_payloads,
        )
    return safe


def _is_name_key(key: str) -> bool:
    normalized = key.replace(" ", "_").replace("-", "_")
    return normalized in _NAME_KEYS


def identifier_attributes(
    *,
    employee_email: str = "",
    submission_id: str = "",
    teams_conversation_id: str = "",
    teams_user_id: str = "",
    salt: str = "",
) -> dict[str, str]:
    """Build stable hashed identifier attributes for common production debugging."""
    attrs: dict[str, str] = {}
    if employee_email:
        attrs["employee.email_hash"] = hash_identifier(employee_email, salt=salt)
        domain = email_domain(employee_email)
        if domain:
            attrs["employee.email_domain"] = domain
    if submission_id:
        attrs["submission.id_hash"] = hash_identifier(submission_id, salt=salt)
    if teams_conversation_id:
        attrs["teams.conversation_hash"] = hash_identifier(teams_conversation_id, salt=salt)
    if teams_user_id:
        attrs["teams.user_hash"] = hash_identifier(teams_user_id, salt=salt)
    return attrs
