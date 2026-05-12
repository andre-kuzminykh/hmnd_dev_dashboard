"""Config + feature flags. Reads env vars and (optionally) .streamlit/secrets.toml.

Secrets never persist to DB and are never logged (FR-09.1.1.2).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_SECRETS_PATHS = [
    Path("/app/.streamlit/secrets.toml"),
    Path.cwd() / ".streamlit" / "secrets.toml",
    Path.home() / ".streamlit" / "secrets.toml",
]


def _running_inside_streamlit() -> bool:
    try:
        from streamlit.runtime import exists  # type: ignore
        return bool(exists())
    except Exception:
        return False


def _secrets_file_exists() -> bool:
    return any(p.exists() for p in _SECRETS_PATHS)


def _from_env_or_secrets(name: str, default: str = "") -> str:
    """Env first; only consult st.secrets when running inside Streamlit AND a
    secrets.toml file actually exists (otherwise Streamlit prints a noisy
    'No secrets found' message on the page).
    """
    val = os.environ.get(name)
    if val:
        return val
    if not _running_inside_streamlit() or not _secrets_file_exists():
        return default
    try:
        import streamlit as st  # noqa: WPS433
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class OpenAIOrg:
    label: str            # short name shown in UI / dropdown (e.g. 'Artem', 'Humanoid')
    api_key: str
    external_id: str | None = None  # set after first sync from /organization metadata


@dataclass
class Config:
    openai_key: str
    openai_orgs: list[OpenAIOrg]       # multi-org sync targets (incl. legacy single key)
    anthropic_key: str
    github_token: str
    github_enabled: bool       # F-05/F-06 visible only when True
    demo_data: bool            # seed demo dataset on first run
    anthropic_mock: bool       # synthesise Anthropic data when admin key missing


def _parse_openai_orgs(legacy_key: str) -> list[OpenAIOrg]:
    """Read OPENAI_API_KEYS (JSON list of {label, key}) if present; otherwise
    fall back to the single OPENAI_API_KEY env (labelled 'default').

    Examples:
        OPENAI_API_KEYS='[{"label":"Artem","key":"sk-admin-..."},
                          {"label":"Humanoid","key":"sk-admin-..."}]'
    """
    raw = os.environ.get("OPENAI_API_KEYS", "").strip()
    if raw:
        try:
            import json
            items = json.loads(raw)
            out: list[OpenAIOrg] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                key = (it.get("key") or "").strip()
                label = (it.get("label") or "default").strip() or "default"
                if key:
                    out.append(OpenAIOrg(label=label, api_key=key))
            if out:
                return out
        except Exception:
            pass
    if legacy_key:
        return [OpenAIOrg(label="default", api_key=legacy_key)]
    return []


def load_config() -> Config:
    openai_key = _from_env_or_secrets("OPENAI_API_KEY")
    return Config(
        openai_key=openai_key,
        openai_orgs=_parse_openai_orgs(openai_key),
        anthropic_key=_from_env_or_secrets("ANTHROPIC_API_KEY"),
        github_token=_from_env_or_secrets("GITHUB_TOKEN"),
        github_enabled=_bool_env("HMND_GITHUB_ENABLED", default=False),
        demo_data=_bool_env("HMND_DEMO_DATA", default=False),
        anthropic_mock=_bool_env("HMND_ANTHROPIC_MOCK", default=False),
    )
