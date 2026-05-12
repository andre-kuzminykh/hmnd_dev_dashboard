"""Tests for multi-org OPENAI_API_KEYS env parsing.

The single OPENAI_API_KEY env still maps to a single 'default' org so
the existing code paths keep working until the user provides the JSON.
"""
from __future__ import annotations

import json


def test_legacy_single_key_still_works(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEYS", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-admin-legacy")
    from importlib import reload
    import backend.config as cfg
    reload(cfg)
    c = cfg.load_config()
    assert c.openai_key == "sk-admin-legacy"
    assert len(c.openai_orgs) == 1
    assert c.openai_orgs[0].label == "default"
    assert c.openai_orgs[0].api_key == "sk-admin-legacy"


def test_multi_org_json(monkeypatch):
    monkeypatch.setenv(
        "OPENAI_API_KEYS",
        json.dumps([
            {"label": "Artem", "key": "sk-admin-a"},
            {"label": "Humanoid", "key": "sk-admin-h"},
        ]),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-admin-legacy")
    from importlib import reload
    import backend.config as cfg
    reload(cfg)
    c = cfg.load_config()
    assert len(c.openai_orgs) == 2
    labels = [o.label for o in c.openai_orgs]
    assert labels == ["Artem", "Humanoid"]


def test_malformed_json_falls_back_to_legacy(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEYS", "{not valid json")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-admin-legacy")
    from importlib import reload
    import backend.config as cfg
    reload(cfg)
    c = cfg.load_config()
    assert len(c.openai_orgs) == 1
    assert c.openai_orgs[0].api_key == "sk-admin-legacy"


def test_empty_keys_means_no_orgs(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEYS", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from importlib import reload
    import backend.config as cfg
    reload(cfg)
    c = cfg.load_config()
    assert c.openai_key == ""
    assert c.openai_orgs == []


def test_ensure_organization_idempotent(tmp_db):
    from backend.services.sync import _ensure_organization
    a = _ensure_organization("openai", "Artem")
    b = _ensure_organization("openai", "Artem")
    c = _ensure_organization("openai", "Humanoid")
    assert a == b           # same label -> same id
    assert a != c           # different label -> different id
