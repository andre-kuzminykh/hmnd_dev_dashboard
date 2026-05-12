"""Project-scoped OpenAI key inspector.

A `sk-proj-...` key cannot read org-wide usage, but it CAN list everything
inside the project it belongs to and the response headers reveal the
parent organisation + project ids. This connector probes the key and
returns a structured inventory we can show in the dashboard so the user
gets *some* value even before getting an Admin key.

Endpoints we probe (all read-only):
    /v1/models                  -> list of accessible models
    /v1/assistants              -> list of configured Assistants v2
    /v1/files                   -> uploaded files (size + count)
    /v1/vector_stores           -> RAG vector stores
    /v1/batches                 -> Batch API jobs in flight / done
    /v1/fine_tuning/jobs        -> Fine-tuning jobs
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProbeResult:
    label: str
    api_key_redacted: str
    ok: bool = False
    org_id: str | None = None          # from openai-organization header
    project_id: str | None = None      # from openai-project header (if present)
    models: list[str] = field(default_factory=list)
    assistants: list[dict[str, Any]] = field(default_factory=list)
    files: dict[str, Any] = field(default_factory=dict)
    vector_stores: list[dict[str, Any]] = field(default_factory=list)
    batches: list[dict[str, Any]] = field(default_factory=list)
    fine_tuning_jobs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _redact(key: str) -> str:
    if not key or len(key) < 12:
        return "(unset)"
    return f"{key[:8]}…{key[-4:]}"


class OpenAIProjectInspector:
    """Read-only probe over project-scoped endpoints. Failures on any endpoint
    are recorded in `errors` and do not abort the probe — partial info is
    better than none.
    """

    BASE = "https://api.openai.com/v1"

    def __init__(self, api_key: str, label: str = "default"):
        self.api_key = api_key
        self.label = label

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _request(self, path: str, params: dict[str, Any] | None = None):
        import requests
        try:
            r = requests.get(
                f"{self.BASE}/{path}", headers=self._headers(),
                params=params or {}, timeout=15,
            )
            return r
        except Exception as exc:  # noqa: BLE001
            class _Fake:
                status_code = 0
                headers: dict[str, str] = {}
                def json(self):  # noqa: D401
                    return {}
                text = str(exc)
            return _Fake()

    def probe(self) -> ProbeResult:
        res = ProbeResult(label=self.label, api_key_redacted=_redact(self.api_key))
        if not self.api_key:
            res.errors.append("api key missing")
            return res

        # First call: /models — tells us key is alive + leaks org/project in headers.
        r = self._request("models", {"limit": 100})
        if r.status_code == 200:
            res.ok = True
            data = r.json().get("data", [])
            res.models = sorted({m.get("id") for m in data if m.get("id")})
        else:
            res.errors.append(f"GET /models -> {r.status_code}")
            return res
        res.org_id = r.headers.get("openai-organization") or None
        res.project_id = r.headers.get("openai-project") or None

        # /assistants
        r = self._request("assistants", {"limit": 100})
        if r.status_code == 200:
            for a in r.json().get("data", []):
                res.assistants.append({
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "model": a.get("model"),
                    "created_at": a.get("created_at"),
                    "tools": [t.get("type") for t in a.get("tools", []) if t.get("type")],
                })
        elif r.status_code not in (404,):
            res.errors.append(f"GET /assistants -> {r.status_code}")

        # /files
        r = self._request("files", {"limit": 100})
        if r.status_code == 200:
            files = r.json().get("data", [])
            res.files = {
                "count": len(files),
                "bytes_total": sum((f.get("bytes") or 0) for f in files),
                "by_purpose": _group_count(files, "purpose"),
            }
        elif r.status_code not in (404,):
            res.errors.append(f"GET /files -> {r.status_code}")

        # /vector_stores
        r = self._request("vector_stores", {"limit": 100})
        if r.status_code == 200:
            for vs in r.json().get("data", []):
                res.vector_stores.append({
                    "id": vs.get("id"),
                    "name": vs.get("name"),
                    "file_count": (vs.get("file_counts") or {}).get("total"),
                    "usage_bytes": vs.get("usage_bytes"),
                })
        elif r.status_code not in (404,):
            res.errors.append(f"GET /vector_stores -> {r.status_code}")

        # /batches
        r = self._request("batches", {"limit": 50})
        if r.status_code == 200:
            for b in r.json().get("data", []):
                res.batches.append({
                    "id": b.get("id"),
                    "status": b.get("status"),
                    "endpoint": b.get("endpoint"),
                    "created_at": b.get("created_at"),
                    "request_counts": b.get("request_counts"),
                })
        elif r.status_code not in (404,):
            res.errors.append(f"GET /batches -> {r.status_code}")

        # /fine_tuning/jobs
        r = self._request("fine_tuning/jobs", {"limit": 50})
        if r.status_code == 200:
            for j in r.json().get("data", []):
                res.fine_tuning_jobs.append({
                    "id": j.get("id"),
                    "status": j.get("status"),
                    "model": j.get("model"),
                    "created_at": j.get("created_at"),
                })
        elif r.status_code not in (404,):
            res.errors.append(f"GET /fine_tuning/jobs -> {r.status_code}")

        return res


def _group_count(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        v = it.get(key) or "(unknown)"
        out[v] = out.get(v, 0) + 1
    return out
