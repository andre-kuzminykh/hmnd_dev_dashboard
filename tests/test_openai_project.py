"""Tests for OpenAIProjectInspector probe + project-keys config."""
from __future__ import annotations

import json


def test_redact_short_returns_unset():
    from data.connectors.openai_project import _redact
    assert _redact("") == "(unset)"
    assert _redact("sk") == "(unset)"


def test_redact_long():
    from data.connectors.openai_project import _redact
    out = _redact("sk-proj-AAAAAAAABBBBCCCC1234")
    assert out.startswith("sk-proj-")
    assert out.endswith("1234")
    assert "…" in out


def test_probe_handles_401(monkeypatch):
    """When the key is unauthorised we get a structured failure, not a crash."""
    from data.connectors.openai_project import OpenAIProjectInspector

    class _Resp:
        status_code = 401
        headers = {}
        text = "unauthorized"
        def json(self):  # noqa: D401
            return {"error": {"message": "Invalid key"}}

    def _fake_request(self, path, params=None):
        return _Resp()

    monkeypatch.setattr(OpenAIProjectInspector, "_request", _fake_request)
    res = OpenAIProjectInspector("sk-proj-bad", "TestOrg").probe()
    assert res.ok is False
    assert any("models" in e for e in res.errors)


def test_probe_collects_models_assistants(monkeypatch):
    """Successful probe pulls models + assistants + headers."""
    from data.connectors.openai_project import OpenAIProjectInspector

    class _Resp:
        def __init__(self, status, json_body=None, headers=None):
            self.status_code = status
            self._j = json_body or {}
            self.headers = headers or {}
            self.text = ""
        def json(self):
            return self._j

    def _fake_request(self, path, params=None):
        if path == "models":
            return _Resp(200,
                         {"data": [{"id": "gpt-4o"}, {"id": "gpt-5"}]},
                         {"openai-organization": "org-test-123",
                          "openai-project": "proj-abc"})
        if path == "assistants":
            return _Resp(200, {"data": [
                {"id": "asst_1", "name": "CEO Bot", "model": "gpt-5",
                 "created_at": 1700000000, "tools": [{"type": "code_interpreter"}]},
            ]})
        if path == "files":
            return _Resp(200, {"data": [
                {"id": "f1", "bytes": 1024, "purpose": "assistants"},
                {"id": "f2", "bytes": 2048, "purpose": "fine-tune"},
            ]})
        if path == "vector_stores":
            return _Resp(200, {"data": [
                {"id": "vs1", "name": "kb", "file_counts": {"total": 5},
                 "usage_bytes": 12345},
            ]})
        return _Resp(404)

    monkeypatch.setattr(OpenAIProjectInspector, "_request", _fake_request)
    res = OpenAIProjectInspector("sk-proj-good", "Humanoid").probe()
    assert res.ok is True
    assert res.org_id == "org-test-123"
    assert res.project_id == "proj-abc"
    assert "gpt-4o" in res.models and "gpt-5" in res.models
    assert len(res.assistants) == 1
    assert res.assistants[0]["tools"] == ["code_interpreter"]
    assert res.files["count"] == 2
    assert res.files["bytes_total"] == 3072
    assert res.files["by_purpose"] == {"assistants": 1, "fine-tune": 1}
    assert len(res.vector_stores) == 1


def test_project_keys_config(monkeypatch):
    monkeypatch.setenv(
        "OPENAI_PROJECT_KEYS",
        json.dumps([
            {"label": "Humanoid", "key": "sk-proj-h"},
            {"label": "Test",     "key": "sk-proj-t"},
        ]),
    )
    from importlib import reload
    import backend.config as cfg
    reload(cfg)
    c = cfg.load_config()
    assert len(c.openai_project_keys) == 2
    labels = [p.label for p in c.openai_project_keys]
    assert labels == ["Humanoid", "Test"]


def test_project_keys_config_empty(monkeypatch):
    monkeypatch.delenv("OPENAI_PROJECT_KEYS", raising=False)
    from importlib import reload
    import backend.config as cfg
    reload(cfg)
    c = cfg.load_config()
    assert c.openai_project_keys == []
