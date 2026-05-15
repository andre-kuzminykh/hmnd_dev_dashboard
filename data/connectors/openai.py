"""OpenAI Admin API connector — Usage + Costs + Users."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .base import BaseConnector, SyncReport, to_float, to_int
from data.db import get_conn


# Hard-coded $/1K-token prices for the most common OpenAI models.
# Used to compute cost_usd per usage event when the org's costs endpoint
# can't be group_by-ed at user_id level.
# Format: model_name -> (input_per_1k, output_per_1k, cache_read_per_1k)
OPENAI_DEFAULT_PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-4o":                  (0.0025,   0.01,    0.00125),
    "gpt-4o-mini":             (0.00015,  0.0006,  0.000075),
    "gpt-4o-realtime-preview": (0.005,    0.02,    0.0025),
    "gpt-4.1":                 (0.002,    0.008,   0.0005),
    "gpt-4.1-mini":            (0.0004,   0.0016,  0.0001),
    "gpt-4.1-nano":            (0.0001,   0.0004,  0.000025),
    "gpt-4-turbo":             (0.01,     0.03,    0.0),
    "gpt-4":                   (0.03,     0.06,    0.0),
    "gpt-3.5-turbo":           (0.0005,   0.0015,  0.0),
    "gpt-5":                   (0.005,    0.030,   0.0005),
    "gpt-5-mini":              (0.0008,   0.0024,  0.0004),
    "gpt-5.1":                 (0.005,    0.030,   0.0005),
    "gpt-5.1-mini":            (0.0008,   0.0024,  0.0004),
    "gpt-5.4":                 (0.005,    0.030,   0.0005),
    "gpt-5.5-pro":             (0.030,    0.180,   0.0),
    "gpt-5.5":                 (0.005,    0.030,   0.0005),
    "gpt-4o-mini-transcribe":  (0.00015,  0.0006,  0.000075),
    "o1":                      (0.015,    0.06,    0.0075),
    "o1-mini":                 (0.003,    0.012,   0.0015),
    "o1-preview":              (0.015,    0.06,    0.0075),
    "o3":                      (0.002,    0.008,   0.001),
    "o3-mini":                 (0.0011,   0.0044,  0.00055),
    "o4-mini":                 (0.0011,   0.0044,  0.00055),
    "text-embedding-3-small":  (0.00002,  0.0,     0.0),
    "text-embedding-3-large":  (0.00013,  0.0,     0.0),
    "text-embedding-ada-002":  (0.0001,   0.0,     0.0),
}


def _load_price_overrides() -> dict[str, tuple[float, float, float]]:
    """Read HMND_OPENAI_PRICES_OVERRIDE — a JSON object mapping model name
    (or prefix) to a 3-tuple [input, output, cached] $/1K. Empty dict on
    invalid JSON.

    Example:
        HMND_OPENAI_PRICES_OVERRIDE='{"gpt-5.5":[0.002,0.008,0.0005]}'
    """
    raw = os.environ.get("HMND_OPENAI_PRICES_OVERRIDE", "").strip()
    if not raw:
        return {}
    try:
        import json
        data = json.loads(raw)
    except Exception:
        return {}
    out: dict[str, tuple[float, float, float]] = {}
    for name, p in data.items():
        if isinstance(p, (list, tuple)) and len(p) == 3:
            try:
                out[name] = (float(p[0]), float(p[1]), float(p[2]))
            except (TypeError, ValueError):
                continue
    return out


def _model_price_lookup(name: str) -> tuple[float, float, float] | None:
    """Find prices for `name`. Priority order:
        1. Exact match in HMND_OPENAI_PRICES_OVERRIDE
        2. Exact match in OPENAI_DEFAULT_PRICES
        3. Longest-prefix match in HMND_OPENAI_PRICES_OVERRIDE
        4. Longest-prefix match in OPENAI_DEFAULT_PRICES

    Returns None when no match is found — caller should default to 0.
    """
    if not name:
        return None
    overrides = _load_price_overrides()
    # 1) exact override
    if name in overrides:
        return overrides[name]
    # 2) exact default
    if name in OPENAI_DEFAULT_PRICES:
        return OPENAI_DEFAULT_PRICES[name]
    # 3) prefix override (overrides win over defaults at the same prefix length)
    for base in sorted(overrides.keys(), key=len, reverse=True):
        if name.startswith(base):
            return overrides[base]
    # 4) prefix default
    for base in sorted(OPENAI_DEFAULT_PRICES.keys(), key=len, reverse=True):
        if name.startswith(base):
            return OPENAI_DEFAULT_PRICES[base]
    return None


class OpenAIConnector(BaseConnector):
    name = "openai"
    BASE = "https://api.openai.com/v1/organization"

    def __init__(self, api_key: str | None = None, mock: bool = True,
                 org_label: str = "default", org_id: int | None = None):
        super().__init__(api_key=api_key, mock=mock)
        # Local-DB organisation context. None = legacy single-org mode where
        # rows are written without org_id (existing behaviour). When org_id is
        # set, every users/api_keys/usage_events row gets it tagged.
        self.org_label = org_label
        self.org_id = org_id

    # ---- helpers ----
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any]) -> dict | None:
        import requests

        try:
            r = requests.get(
                f"{self.BASE}/{path}", headers=self._headers(), params=params, timeout=30
            )
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            return None

    def test_connection(self) -> bool:
        if self.mock:
            return True
        data = self._get("users", {"limit": 1})
        return data is not None

    # ---- main sync ----
    def sync(self, period_days: int = 7) -> SyncReport:
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=period_days)
        report = SyncReport(provider=self.name, period_from=start_dt.date(), period_to=end_dt.date())
        if self.mock:
            report.skipped = 1
            return report

        users_by_id = self._sync_users(report)
        provider_id, model_ids = self._ensure_provider_and_models(report)
        # Backfill default prices for models created by previous sync runs
        self._backfill_prices(provider_id)
        keys_by_external = self._sync_api_keys(provider_id, users_by_id, report)
        self._sync_usage(start_dt, end_dt, users_by_id, provider_id, model_ids, keys_by_external, report)
        # Non-completion endpoints (embeddings / images / audio / vector_stores /
        # code_interpreter / moderations) are gated behind an env flag because
        # the cost model for some of them (audio: seconds/characters; code
        # interpreter: sessions) doesn't fit the per-token formula and can
        # inflate the dashboard spend in misleading ways. Enable explicitly:
        #   HMND_OPENAI_OTHER_USAGE=true
        if os.environ.get("HMND_OPENAI_OTHER_USAGE", "").lower() in {"1", "true", "yes", "on"}:
            self._sync_other_usage(start_dt, end_dt, users_by_id, provider_id, model_ids, keys_by_external, report)
        else:
            # Sweep any rows previously inserted by _sync_other_usage in case
            # the flag was on earlier — otherwise the dashboard would still
            # show the inflated spend after we toggle the flag back off.
            with get_conn() as conn:
                cur = conn.execute(
                    """DELETE FROM usage_events
                       WHERE provider_id = ?
                         AND purpose LIKE 'usage/%'
                         AND date(occurred_at) >= date(?)
                         AND date(occurred_at) <= date(?)""",
                    (
                        provider_id,
                        start_dt.date().isoformat(),
                        end_dt.date().isoformat(),
                    ),
                )
                if cur.rowcount:
                    report.errors.append(f"swept {cur.rowcount} stale 'usage/*' rows")
                conn.commit()
        # Org-level totals from /costs endpoint are kept as a sanity log only;
        # per-event cost_usd is now computed from model prices in _sync_usage,
        # which gives accurate per-user attribution that the costs endpoint
        # cannot provide (it does not support group_by=user_id).
        self._sync_costs_report_only(start_dt, end_dt, report)
        # F-13.x — calibrate per-event cost_usd to match the provider's own
        # daily totals from /costs. Default on; turn off with
        # HMND_CALIBRATE_TO_BILLING=false if you want raw model-priced numbers.
        if os.environ.get("HMND_CALIBRATE_TO_BILLING", "true").lower() in {"1", "true", "yes", "on"}:
            self._calibrate_to_reported(start_dt, end_dt, provider_id, report)
        if self.org_id is not None:
            self._tag_org_on_synced_rows(provider_id, list(users_by_id.values()),
                                          list(keys_by_external.values()),
                                          start_dt, end_dt, report)
        return report

    def _tag_org_on_synced_rows(
        self,
        provider_id: int,
        user_ids: list[int],
        api_key_ids: list[int],
        start_dt: datetime,
        end_dt: datetime,
        report: SyncReport,
    ) -> None:
        """Stamp organization_id on rows we just synced for this org. Keeps
        rows from different orgs separable in queries when both legacy
        (org_id IS NULL) and multi-org data coexist.
        """
        if not user_ids and not api_key_ids:
            return
        with get_conn() as conn:
            if user_ids:
                placeholders = ",".join(["?"] * len(user_ids))
                conn.execute(
                    f"UPDATE users SET organization_id = ? WHERE id IN ({placeholders})",
                    [self.org_id, *user_ids],
                )
            if api_key_ids:
                placeholders = ",".join(["?"] * len(api_key_ids))
                conn.execute(
                    f"UPDATE api_keys SET organization_id = ? WHERE id IN ({placeholders})",
                    [self.org_id, *api_key_ids],
                )
                # Events inserted in _sync_usage are deleted+reinserted per
                # period; tag them by api_key_id (which we just set).
                conn.execute(
                    f"""UPDATE usage_events SET organization_id = ?
                        WHERE api_key_id IN ({placeholders})
                          AND date(occurred_at) >= date(?)
                          AND date(occurred_at) <= date(?)""",
                    [self.org_id, *api_key_ids,
                     start_dt.date().isoformat(), end_dt.date().isoformat()],
                )
            conn.commit()

    def _calibrate_to_reported(
        self, start_dt: datetime, end_dt: datetime, provider_id: int, report: SyncReport
    ) -> None:
        """Per-day proportional rescale so SUM(usage_events.cost_usd) == provider_totals.

        Per-user breakdown stays proportional to that user's token share of the
        day; the total now matches OpenAI's billing UI exactly (modulo sync
        lag for the current day).
        """
        days_calibrated = 0
        with get_conn() as conn:
            # Iterate every (provider, day) we have a reported total for in
            # the sync window — there are at most ~31 of them.
            rows = conn.execute(
                """SELECT day, cost_usd FROM provider_totals
                   WHERE provider_id = ? AND day BETWEEN ? AND ?""",
                (provider_id, start_dt.date().isoformat(), end_dt.date().isoformat()),
            ).fetchall()
            for r in rows:
                day = r["day"]
                reported = float(r["cost_usd"] or 0)
                if reported <= 0:
                    continue
                computed_row = conn.execute(
                    """SELECT COALESCE(SUM(cost_usd), 0) AS s
                       FROM usage_events
                       WHERE provider_id = ? AND date(occurred_at) = ?""",
                    (provider_id, day),
                ).fetchone()
                computed = float(computed_row["s"] or 0)
                if computed <= 0:
                    continue
                scale = reported / computed
                # Skip near-no-op scaling to keep the diff log small.
                if abs(scale - 1.0) < 0.001:
                    continue
                conn.execute(
                    """UPDATE usage_events SET cost_usd = ROUND(cost_usd * ?, 6)
                       WHERE provider_id = ? AND date(occurred_at) = ?""",
                    (scale, provider_id, day),
                )
                days_calibrated += 1
            conn.commit()
        if days_calibrated:
            report.errors.append(f"calibrated {days_calibrated} days to provider_totals")

    # ---- api keys ----
    def _sync_api_keys(
        self, provider_id: int, users_by_id: dict[str, int], report: SyncReport
    ) -> dict[str, int]:
        """`/v1/organization/admin_api_keys` (admin keys) и `/v1/organization/api_keys`.

        Возвращает mapping external_id → local id.
        """
        keys_by_external: dict[str, int] = {}
        for endpoint, is_admin in (("admin_api_keys", 1), ("api_keys", 0)):
            after = None
            while True:
                params = {"limit": 100}
                if after:
                    params["after"] = after
                data = self._get(endpoint, params)
                if data is None:
                    # endpoint может быть недоступен в зависимости от прав
                    break
                items = data.get("data", []) if isinstance(data, dict) else []
                for k in items:
                    ext = k.get("id") or k.get("key_id")
                    if not ext:
                        continue
                    name = k.get("name") or "(unnamed)"
                    redacted = k.get("redacted_value") or k.get("redacted_key") or ""
                    owner_ext = (k.get("owner") or {}).get("id") if isinstance(k.get("owner"), dict) else None
                    owner_local = users_by_id.get(owner_ext) if owner_ext else None
                    created_at = k.get("created_at")
                    last_used = k.get("last_used_at")
                    with get_conn() as conn:
                        # Race-safe upsert keyed on (provider_id, external_id).
                        cur = conn.execute(
                            """INSERT OR IGNORE INTO api_keys(
                                    provider_id, external_id, name, redacted_value,
                                    owner_user_id, is_admin, created_at, last_used_at)
                               VALUES(?,?,?,?,?,?,?,?)""",
                            (provider_id, ext, name, redacted, owner_local, is_admin, created_at, last_used),
                        )
                        if cur.rowcount:
                            report.inserted += 1
                        else:
                            # Existing row — refresh mutable fields.
                            conn.execute(
                                """UPDATE api_keys SET name=?, redacted_value=?, owner_user_id=?,
                                                       is_admin=?, last_used_at=?
                                   WHERE provider_id=? AND external_id=?""",
                                (name, redacted, owner_local, is_admin, last_used, provider_id, ext),
                            )
                        kid = conn.execute(
                            "SELECT id FROM api_keys WHERE provider_id=? AND external_id=?",
                            (provider_id, ext),
                        ).fetchone()["id"]
                        conn.commit()
                    keys_by_external[ext] = kid
                if not data.get("has_more"):
                    break
                after = data.get("last_id")
        return keys_by_external

    # ---- pieces ----
    def _ensure_provider_and_models(self, report: SyncReport) -> tuple[int, dict[str, int]]:
        with get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO providers(name) VALUES('openai')")
            provider_id = conn.execute(
                "SELECT id FROM providers WHERE name = 'openai'"
            ).fetchone()["id"]
            rows = conn.execute(
                "SELECT id, name FROM models WHERE provider_id = ?", (provider_id,)
            ).fetchall()
            conn.commit()
        return provider_id, {r["name"]: r["id"] for r in rows}

    def _ensure_model(
        self,
        name: str,
        provider_id: int,
        model_ids: dict[str, int],
        prices_by_model: dict[int, tuple[float, float, float]] | None = None,
    ) -> int:
        """Insert (provider_id, name) into models if absent and add the matching
        default price row. If `prices_by_model` is provided, it is updated in-place
        with the new model's price so the caller's per-event cost computation can
        see prices for models that were just created by this very sync.
        """
        if name in model_ids:
            return model_ids[name]
        with get_conn() as conn:
            # INSERT OR IGNORE handles the race where another sync process
            # (e.g. the hourly sidecar running in parallel with a manual
            # reset/sync) inserted the same (provider, name) row first.
            conn.execute(
                "INSERT OR IGNORE INTO models(provider_id, name, family) VALUES(?,?,?)",
                (provider_id, name, name.split("-")[0]),
            )
            row = conn.execute(
                "SELECT id FROM models WHERE provider_id = ? AND name = ?",
                (provider_id, name),
            ).fetchone()
            mid = row["id"]
            price = _model_price_lookup(name)
            if price:
                conn.execute(
                    """INSERT OR IGNORE INTO model_prices(
                            model_id, valid_from, input_per_1k, output_per_1k, cache_read_per_1k)
                       VALUES(?, '2026-01-01', ?, ?, ?)""",
                    (mid, *price),
                )
            conn.commit()
        model_ids[name] = mid
        if prices_by_model is not None:
            # Always populate the cache so a missing entry no longer means
            # 'cost = 0' for newly-created models. Unknown prices fall back
            # to (0,0,0) — caller can still detect them via the dict miss.
            prices_by_model[mid] = price or (0.0, 0.0, 0.0)
        return mid

    def _backfill_prices(self, provider_id: int) -> int:
        """For OpenAI models that exist without a price row, insert defaults."""
        inserted = 0
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT m.id, m.name FROM models m
                   LEFT JOIN model_prices mp ON mp.model_id = m.id
                   WHERE m.provider_id = ? AND mp.id IS NULL""",
                (provider_id,),
            ).fetchall()
            for r in rows:
                price = _model_price_lookup(r["name"])
                if not price:
                    continue
                conn.execute(
                    """INSERT INTO model_prices(model_id, valid_from,
                                                input_per_1k, output_per_1k, cache_read_per_1k)
                       VALUES(?, '2026-01-01', ?, ?, ?)""",
                    (r["id"], *price),
                )
                inserted += 1
            conn.commit()
        return inserted

    def _price_cache(self, provider_id: int) -> dict[int, tuple[float, float, float]]:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT model_id, input_per_1k, output_per_1k, cache_read_per_1k
                   FROM model_prices mp
                   JOIN models m ON m.id = mp.model_id
                   WHERE m.provider_id = ?""",
                (provider_id,),
            ).fetchall()
        return {
            r["model_id"]: (r["input_per_1k"], r["output_per_1k"], r["cache_read_per_1k"])
            for r in rows
        }

    def _sync_users(self, report: SyncReport) -> dict[str, int]:
        """`/v1/organization/users` → upsert по email."""
        users_by_id: dict[str, int] = {}
        after = None
        while True:
            params = {"limit": 100}
            if after:
                params["after"] = after
            data = self._get("users", params)
            if data is None:
                report.errors.append("users endpoint failed")
                break
            items = data.get("data", []) if isinstance(data, dict) else []
            for u in items:
                email = u.get("email") or f"{u.get('id','unknown')}@openai"
                full_name = u.get("name") or email
                role = u.get("role")
                with get_conn() as conn:
                    # Race-safe upsert: another sync may have inserted the
                    # same email moments ago. INSERT OR IGNORE keeps us happy.
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO users(email, full_name, role, monthly_limit_usd, is_active)
                           VALUES(?,?,?,?,1)""",
                        (email, full_name, role, 200),
                    )
                    if cur.rowcount:
                        report.inserted += 1
                    uid = conn.execute(
                        "SELECT id FROM users WHERE email = ?", (email,)
                    ).fetchone()["id"]
                    conn.commit()
                users_by_id[u.get("id", "")] = uid
            if not data.get("has_more"):
                break
            after = data.get("last_id")
        return users_by_id

    def _sync_usage(
        self,
        start_dt: datetime,
        end_dt: datetime,
        users_by_id: dict[str, int],
        provider_id: int,
        model_ids: dict[str, int],
        keys_by_external: dict[str, int],
        report: SyncReport,
    ) -> None:
        """`/usage/completions` группируем по user_id и model, bucket = 1d.

        Идемпотентность: перед загрузкой удаляем уже существующие события
        OpenAI в окне, чтобы повторный sync не дублировал записи.
        Tokens равномерно делим между requests'ами одного bucket'а — это даёт
        нормальные `COUNT(*)` в models breakdown и аккуратные суммы в KPI.
        """
        with get_conn() as conn:
            # Use date() comparisons so we wipe FULL days, not the half-day windows
            # implied by datetime-precise bounds. Otherwise re-syncing the same
            # period with a slightly-different now() leaks rows from buckets
            # that started before the new lower bound (each OpenAI bucket starts
            # at 00:00 UTC), producing duplicates on every re-run.
            conn.execute(
                """DELETE FROM usage_events
                   WHERE provider_id = ?
                     AND date(occurred_at) >= date(?)
                     AND date(occurred_at) <= date(?)""",
                (
                    provider_id,
                    start_dt.date().isoformat(),
                    end_dt.date().isoformat(),
                ),
            )
            conn.commit()

        params: dict[str, Any] = {
            "start_time": int(start_dt.timestamp()),
            "end_time": int(end_dt.timestamp()),
            "bucket_width": "1d",
            "group_by": "user_id,model,api_key_id",
            "limit": 31,
        }
        # Preload prices once per sync (one query, then in-memory lookup).
        prices_by_model = self._price_cache(provider_id)
        page = None
        while True:
            if page:
                params["page"] = page
            data = self._get("usage/completions", params)
            if data is None:
                report.errors.append("usage/completions failed")
                return
            for bucket in data.get("data", []):
                ts = bucket.get("start_time")
                if not ts:
                    continue
                bucket_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                with get_conn() as conn:
                    rows: list[tuple] = []
                    for r in bucket.get("results", []):
                        user_ext = r.get("user_id")
                        user_id = users_by_id.get(user_ext)
                        if not user_id:
                            continue
                        model_name = r.get("model") or "unknown"
                        model_id = self._ensure_model(
                            model_name, provider_id, model_ids, prices_by_model
                        )
                        tokens_in = to_int(r.get("input_tokens"))
                        tokens_out = to_int(r.get("output_tokens"))
                        tokens_cached = to_int(r.get("input_cached_tokens"))
                        requests_n = max(to_int(r.get("num_model_requests"), default=1), 1)
                        per_in = tokens_in // requests_n
                        per_out = tokens_out // requests_n
                        per_cached = tokens_cached // requests_n
                        # Compute cost per event using model prices.
                        p_in, p_out, p_cache = prices_by_model.get(model_id, (0.0, 0.0, 0.0))
                        billed_in = max(per_in - per_cached, 0)
                        per_cost = round(
                            billed_in / 1000.0 * p_in
                            + per_cached / 1000.0 * p_cache
                            + per_out / 1000.0 * p_out,
                            6,
                        )
                        ts_str = bucket_dt.strftime("%Y-%m-%d %H:%M:%S")
                        api_key_ext = r.get("api_key_id")
                        api_key_id = keys_by_external.get(api_key_ext) if api_key_ext else None
                        for _ in range(requests_n):
                            rows.append((
                                user_id, provider_id, model_id, api_key_id,
                                self.org_id, ts_str,
                                per_in, per_out, per_cached, per_cost, 0, "API",
                            ))
                    if rows:
                        conn.executemany(
                            """INSERT INTO usage_events(
                                user_id, provider_id, model_id, api_key_id,
                                organization_id, occurred_at,
                                tokens_in, tokens_out, tokens_cached, cost_usd,
                                is_error, purpose
                            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                            rows,
                        )
                        report.inserted += len(rows)
                    conn.commit()
            if not data.get("has_more"):
                break
            page = data.get("next_page")

    def _sync_other_usage(
        self,
        start_dt: datetime,
        end_dt: datetime,
        users_by_id: dict[str, int],
        provider_id: int,
        model_ids: dict[str, int],
        keys_by_external: dict[str, int],
        report: SyncReport,
    ) -> None:
        """Pull non-completion usage endpoints so we don't miss embeddings,
        images, audio etc. when reconciling with OpenAI's billing UI.

        Each endpoint contributes per-bucket events to usage_events using the
        same model-price formula as completions. Cost may be 0 for endpoints
        we don't have prices for (e.g. images, audio) — that's fine, the
        events still show up in counts/tokens; the cross-check string in the
        sync report will flag the difference vs the org total.
        """
        prices_by_model = self._price_cache(provider_id)
        endpoints = [
            ("usage/embeddings", ("input_tokens",)),
            ("usage/moderations", ("input_tokens",)),
            ("usage/audio_speeches", ("characters",)),
            ("usage/audio_transcriptions", ("seconds",)),
            ("usage/images", ()),
            ("usage/vector_stores", ()),
            ("usage/code_interpreter_sessions", ()),
        ]
        for endpoint, _fields in endpoints:
            params: dict[str, Any] = {
                "start_time": int(start_dt.timestamp()),
                "end_time": int(end_dt.timestamp()),
                "bucket_width": "1d",
                "group_by": "user_id,model,api_key_id",
                "limit": 31,
            }
            page = None
            with get_conn() as conn:
                conn.execute(
                    """DELETE FROM usage_events
                       WHERE provider_id = ?
                         AND purpose = ?
                         AND date(occurred_at) >= date(?)
                         AND date(occurred_at) <= date(?)""",
                    (
                        provider_id,
                        endpoint,
                        start_dt.date().isoformat(),
                        end_dt.date().isoformat(),
                    ),
                )
                conn.commit()

            while True:
                if page:
                    params["page"] = page
                data = self._get(endpoint, params)
                if data is None:
                    break  # endpoint may not be available on this org tier
                for bucket in data.get("data", []):
                    ts = bucket.get("start_time")
                    if not ts:
                        continue
                    bucket_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    rows: list[tuple] = []
                    with get_conn() as conn:
                        for r in bucket.get("results", []):
                            user_ext = r.get("user_id")
                            user_id = users_by_id.get(user_ext)
                            if not user_id:
                                continue
                            model_name = r.get("model") or endpoint.split("/")[-1]
                            model_id = self._ensure_model(
                                model_name, provider_id, model_ids, prices_by_model
                            )
                            tokens_in = to_int(r.get("input_tokens"))
                            tokens_out = to_int(r.get("output_tokens"))
                            requests_n = max(to_int(r.get("num_model_requests"), default=1), 1)
                            per_in = tokens_in // requests_n
                            per_out = tokens_out // requests_n
                            p_in, p_out, p_cache = prices_by_model.get(model_id, (0.0, 0.0, 0.0))
                            per_cost = round(
                                per_in / 1000.0 * p_in + per_out / 1000.0 * p_out, 6
                            )
                            ts_str = bucket_dt.strftime("%Y-%m-%d %H:%M:%S")
                            api_key_ext = r.get("api_key_id")
                            api_key_id = keys_by_external.get(api_key_ext) if api_key_ext else None
                            for _ in range(requests_n):
                                rows.append((
                                    user_id, provider_id, model_id, api_key_id,
                                    self.org_id, ts_str,
                                    per_in, per_out, 0, per_cost, 0, endpoint,
                                ))
                        if rows:
                            conn.executemany(
                                """INSERT INTO usage_events(
                                    user_id, provider_id, model_id, api_key_id,
                                    organization_id, occurred_at,
                                    tokens_in, tokens_out, tokens_cached, cost_usd,
                                    is_error, purpose
                                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                                rows,
                            )
                            report.inserted += len(rows)
                        conn.commit()
                if not data.get("has_more"):
                    break
                page = data.get("next_page")

    def _sync_costs_report_only(
        self, start_dt: datetime, end_dt: datetime, report: SyncReport
    ) -> None:
        """Pull org daily totals from /costs and persist them into
        provider_totals so the dashboard can show OpenAI's authoritative
        number alongside our model-priced computation. The report's
        `openai_reported_total_usd` line keeps the cumulative figure for
        a glance during the sync run.
        """
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM providers WHERE name = 'openai'"
            ).fetchone()
        if not row:
            return
        provider_id = row["id"]

        params: dict[str, Any] = {
            "start_time": int(start_dt.timestamp()),
            "end_time": int(end_dt.timestamp()),
            "bucket_width": "1d",
            "limit": 31,
        }
        page = None
        total = 0.0

        # Wipe period rows so any model/provider re-pricing is fully reflected.
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM provider_totals WHERE provider_id = ? AND day BETWEEN ? AND ?",
                (provider_id, start_dt.date().isoformat(), end_dt.date().isoformat()),
            )
            conn.commit()

        while True:
            if page:
                params["page"] = page
            data = self._get("costs", params)
            if data is None:
                report.errors.append("costs endpoint failed (cross-check skipped)")
                return
            for bucket in data.get("data", []):
                ts = bucket.get("start_time")
                if not ts:
                    continue
                day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
                day_cost = 0.0
                for r in bucket.get("results", []):
                    day_cost += to_float((r.get("amount") or {}).get("value"))
                total += day_cost
                with get_conn() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO provider_totals(provider_id, day, cost_usd)
                           VALUES(?,?,?)""",
                        (provider_id, day, round(day_cost, 4)),
                    )
                    conn.commit()
            if not data.get("has_more"):
                break
            page = data.get("next_page")
        report.errors.append(f"openai_reported_total_usd={round(total, 2)}")

    def _sync_costs_legacy(
        self, start_dt: datetime, end_dt: datetime, provider_id: int, report: SyncReport
    ) -> None:
        """`/costs` → daily_costs (на уровне организации)."""
        params: dict[str, Any] = {
            "start_time": int(start_dt.timestamp()),
            "end_time": int(end_dt.timestamp()),
            "bucket_width": "1d",
            "limit": 31,
        }
        page = None
        while True:
            if page:
                params["page"] = page
            data = self._get("costs", params)
            if data is None:
                report.errors.append("costs failed")
                return
            for bucket in data.get("data", []):
                ts = bucket.get("start_time")
                day = (
                    datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
                    if ts
                    else None
                )
                if not day:
                    continue
                cost = 0.0
                for r in bucket.get("results", []):
                    cost += to_float((r.get("amount") or {}).get("value"))
                # пишем в daily_costs на «организационного» юзера id=NULL не позволит схема,
                # поэтому маппим на первого юзера из users_by_id; либо обновим existing rows.
                with get_conn() as conn:
                    row = conn.execute(
                        "SELECT id FROM users ORDER BY id LIMIT 1"
                    ).fetchone()
                    if not row:
                        continue
                    conn.execute(
                        """INSERT INTO daily_costs(user_id, provider_id, day,
                                                   cost_usd, tokens_in, tokens_out, requests)
                           VALUES(?,?,?,?,0,0,0)
                           ON CONFLICT(user_id, provider_id, day)
                           DO UPDATE SET cost_usd = excluded.cost_usd""",
                        (row["id"], provider_id, day, round(cost, 4)),
                    )
                    conn.commit()
                    report.updated += 1
            if not data.get("has_more"):
                break
            page = data.get("next_page")
