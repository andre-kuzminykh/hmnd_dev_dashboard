"""Tests for backend.config."""
from __future__ import annotations


def test_github_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HMND_GITHUB_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    from importlib import reload
    import backend.config as cfgmod
    reload(cfgmod)
    cfg = cfgmod.load_config()
    assert cfg.github_enabled is False
    assert cfg.openai_key == ""
    assert cfg.anthropic_key == ""


def test_env_keys_pulled(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("HMND_GITHUB_ENABLED", "true")
    from importlib import reload
    import backend.config as cfgmod
    reload(cfgmod)
    cfg = cfgmod.load_config()
    assert cfg.openai_key == "sk-test"
    assert cfg.github_enabled is True
