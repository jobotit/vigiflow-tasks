"""Run parameters and where they come from.

Precedence, highest first:

1. the input work item payload (so Control Room can set it per run),
2. the process environment (``devdata/env-for-*.json`` locally, the step
   configuration in Control Room),
3. the defaults in this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

DEFAULT_TEMPLATE = "reportes_vigiflow.xlsx"
# The Control Room vault item holding the VigiFlow url, username and password.
DEFAULT_VAULT_SECRET = "Vigiflow_C001_Credentials"
RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
TEMPLATES_DIR = RESOURCES_DIR / "templates"
FIELD_MAPPING_PATH = RESOURCES_DIR / "field_mapping.json"


class ConfigError(ValueError):
    """A parameter was supplied but is not usable."""


_MISSING = object()


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _first_given(*candidates: Any) -> Any:
    """First candidate that was actually supplied.

    Unlike ``or``, this keeps a deliberate ``0`` or ``""`` instead of falling
    through to the next source, so an out-of-range value is reported rather
    than silently replaced by the default.
    """
    for candidate in candidates:
        if candidate is not _MISSING and candidate is not None:
            return candidate
    return _MISSING


def _as_int(raw: Any, name: str) -> int:
    """Strict integer conversion: no truncation of 1.5, no bool sneaking in."""
    if isinstance(raw, bool):
        raise ConfigError(f"{name} must be a whole number, got {raw!r}")
    if isinstance(raw, float) and not raw.is_integer():
        raise ConfigError(f"{name} must be a whole number, got {raw!r}")
    try:
        return int(raw)
    except (TypeError, ValueError) as err:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from err


def resolve_template(payload: dict[str, Any] | None = None) -> str:
    """File name of the Excel template to fill, relative to the templates dir."""
    name = (payload or {}).get("template") or _env("VIGIFLOW_TEMPLATE") or DEFAULT_TEMPLATE
    return str(name)


def template_path(name: str) -> Path:
    """Absolute path of a template, kept inside the templates directory."""
    candidate = (TEMPLATES_DIR / name).resolve()
    if not str(candidate).startswith(str(TEMPLATES_DIR.resolve())):
        raise ConfigError(f"Template name escapes the templates directory: {name!r}")
    return candidate


def resolve_start_number(payload: dict[str, Any] | None = None) -> int:
    """First value of the N. correlative in column D.

    The correlative runs continuously across daily files: the sample report
    for 31-08-2026 ends at 637, so the next run starts at 638. Nothing in
    VigiFlow knows this number, so it has to be supplied per run. Getting it
    wrong duplicates or skips numbers in a register people rely on, which is
    why there is no silent default beyond 1.
    """
    raw = _first_given(
        (payload or {}).get("start_number", _MISSING),
        _env("VIGIFLOW_START_NUMBER"),
        1,
    )
    value = _as_int(raw, "start_number")
    if value < 1:
        raise ConfigError(f"start_number must be 1 or more, got {value}")
    return value


def resolve_validation_date(payload: dict[str, Any] | None = None) -> date:
    """The date written into every row of column A, and used in the filename.

    Defaults to today, which is what a run scheduled for the day it reports
    should use. Set it explicitly to rerun a past day.
    """
    raw = _first_given(
        (payload or {}).get("validation_date", _MISSING),
        _env("VIGIFLOW_VALIDATION_DATE"),
    )
    if raw is _MISSING or raw in (None, ""):
        return date.today()
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ConfigError(f"validation_date is not a recognised date: {raw!r}")


# Vault items get named by whoever creates them. Accepting the usual spellings,
# in English and Spanish, avoids a failed run over a capital letter.
# The live item Vigiflow_C001_Credentials uses the VIGIFLOW_* spellings, which
# is why they come first. The rest are accepted so a differently named item in
# another workspace still works.
URL_KEYS = ("VIGIFLOW_URL", "url", "URL", "Url", "endpoint", "host", "site", "direccion")
USERNAME_KEYS = (
    "VIGIFLOW_USERNAME",
    "username",
    "Username",
    "USERNAME",
    "user",
    "login",
    "usuario",
    "Usuario",
)
PASSWORD_KEYS = (
    "VIGIFLOW_PASSWORD",
    "password",
    "Password",
    "PASSWORD",
    "pass",
    "clave",
    "Clave",
    "contrasena",
)


def _pick(secret: Any, candidates: tuple[str, ...], secret_name: str, label: str) -> str:
    """Read the first key the vault item actually carries.

    The error names the keys that are present, never their values, so a
    misnamed field is obvious from the run log without leaking anything.
    """
    for key in candidates:
        try:
            value = secret[key]
        except (KeyError, TypeError):
            continue
        if value:
            return str(value)

    try:
        present = sorted(secret.keys())
    except Exception:  # pragma: no cover - depends on the vault backend
        present = []
    raise ConfigError(
        f"Vault item {secret_name!r} has no {label}. "
        f"Looked for {', '.join(candidates[:4])}. Keys present: {present or 'unknown'}"
    )


@dataclass
class VigiFlowConfig:
    """How to reach VigiFlow. Credentials come from the Control Room vault."""

    url: str
    username: str
    password: str
    headless: bool = True
    slowmo_ms: int = 0
    timeout_ms: int = 30_000
    vault_secret: str = DEFAULT_VAULT_SECRET

    @classmethod
    def from_vault(cls, secret_name: str | None = None) -> "VigiFlowConfig":
        """Read credentials from the vault, with env overrides for local runs."""
        secret_name = secret_name or _env("VIGIFLOW_VAULT_SECRET") or DEFAULT_VAULT_SECRET
        url = _env("VIGIFLOW_URL")
        username = _env("VIGIFLOW_USERNAME")
        password = _env("VIGIFLOW_PASSWORD")

        if not (url and username and password):
            from robocorp import vault  # imported lazily, keeps tests browser-free

            secret = vault.get_secret(secret_name)
            url = url or _pick(secret, URL_KEYS, secret_name, "url")
            username = username or _pick(secret, USERNAME_KEYS, secret_name, "username")
            password = password or _pick(secret, PASSWORD_KEYS, secret_name, "password")

        return cls(
            url=url,
            username=username,
            password=password,
            headless=(_env("VIGIFLOW_HEADLESS") or "true").lower() not in ("false", "0", "no"),
            slowmo_ms=int(_env("VIGIFLOW_SLOWMO_MS") or 0),
            timeout_ms=int(_env("VIGIFLOW_TIMEOUT_MS") or 30_000),
            vault_secret=secret_name,
        )


def client_kind() -> str:
    """Which VigiFlow implementation to open. Only ``browser`` exists."""
    return (_env("VIGIFLOW_CLIENT") or "browser").lower()
