"""Aggregates project-key probes into a list of inventories. Caching is
per-session via Streamlit's @cache_data when called from the UI; here we
expose the raw probe so tests and CLI can use it too.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from backend.config import load_config
from data.connectors.openai_project import OpenAIProjectInspector


def get_project_inventories() -> list[dict[str, Any]]:
    """Probe every configured project key. Returns a list of dicts; failures
    produce an entry with `ok=False` and `errors` populated."""
    cfg = load_config()
    out: list[dict[str, Any]] = []
    for pk in cfg.openai_project_keys:
        inspector = OpenAIProjectInspector(api_key=pk.api_key, label=pk.label)
        out.append(asdict(inspector.probe()))
    return out
