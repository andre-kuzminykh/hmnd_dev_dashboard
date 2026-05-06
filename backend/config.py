"""Конфиг + feature flags. Читает переменные окружения и .streamlit/secrets.toml.

Никогда не хранит ключи в БД и не логирует их (FR-09.1.1.2).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _running_inside_streamlit() -> bool:
    try:
        from streamlit.runtime import exists  # type: ignore
        return bool(exists())
    except Exception:
        return False


def _from_env_or_secrets(name: str, default: str = "") -> str:
    """Сначала env, затем st.secrets — но только если мы внутри Streamlit-сессии.
    В CLI/sync режиме лезть в st.secrets не нужно: оно печатает шумные warnings.
    """
    val = os.environ.get(name)
    if val:
        return val
    if not _running_inside_streamlit():
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
class Config:
    openai_key: str
    anthropic_key: str
    github_token: str
    github_enabled: bool       # F-05/F-06 показываются только когда True
    demo_data: bool            # засеять демо-данные при пустой БД
    anthropic_mock: bool       # синтезировать Anthropic-данные, когда нет admin-ключа


def load_config() -> Config:
    return Config(
        openai_key=_from_env_or_secrets("OPENAI_API_KEY"),
        anthropic_key=_from_env_or_secrets("ANTHROPIC_API_KEY"),
        github_token=_from_env_or_secrets("GITHUB_TOKEN"),
        github_enabled=_bool_env("HMND_GITHUB_ENABLED", default=False),
        demo_data=_bool_env("HMND_DEMO_DATA", default=False),
        anthropic_mock=_bool_env("HMND_ANTHROPIC_MOCK", default=False),
    )
