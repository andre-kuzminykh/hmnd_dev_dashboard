"""Синтезатор Anthropic-данных, когда нет admin-ключа.

Генерирует правдоподобный pattern: те же юзеры, что в OpenAI, плюс
случайное распределение по моделям claude-* и сравнимый порядок расхода.

Не зависит от сети, детерминирован по `seed_offset` (по умолчанию — день UTC),
чтобы одни и те же сутки давали одинаковые цифры между запусками.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from data.db import get_conn

ANTHROPIC_MODELS: list[tuple[str, str, float, float, float]] = [
    # name, family, input/1k, output/1k, cache/1k
    ("claude-opus-4-7", "claude-4", 0.015, 0.075, 0.0075),
    ("claude-sonnet-4-6", "claude-4", 0.003, 0.015, 0.0015),
    ("claude-haiku-4-5", "claude-4", 0.001, 0.005, 0.0005),
]


def _ensure_provider_and_models() -> tuple[int, dict[str, int], dict[str, tuple[float, float, float]]]:
    """Заводим provider=anthropic и три модели, если их ещё нет."""
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM providers WHERE name='anthropic'").fetchone()
        if row:
            pid = row["id"]
        else:
            pid = conn.execute("INSERT INTO providers(name) VALUES('anthropic')").lastrowid

        model_ids: dict[str, int] = {}
        prices: dict[str, tuple[float, float, float]] = {}
        for name, family, p_in, p_out, p_cache in ANTHROPIC_MODELS:
            r = conn.execute(
                "SELECT id FROM models WHERE provider_id=? AND name=?", (pid, name)
            ).fetchone()
            if r:
                mid = r["id"]
            else:
                mid = conn.execute(
                    "INSERT INTO models(provider_id, name, family) VALUES(?,?,?)",
                    (pid, name, family),
                ).lastrowid
                conn.execute(
                    """INSERT INTO model_prices(model_id, valid_from, input_per_1k, output_per_1k, cache_read_per_1k)
                       VALUES(?,?,?,?,?)""",
                    (mid, "2026-01-01", p_in, p_out, p_cache),
                )
            model_ids[name] = mid
            prices[name] = (p_in, p_out, p_cache)
        conn.commit()
    return pid, model_ids, prices


def _ensure_user_keys(provider_id: int, user_ids: list[int]) -> dict[int, int]:
    """Генерим по одному синтетическому ключу на юзера, чтобы заполнить срез API Keys."""
    keys_by_user: dict[int, int] = {}
    with get_conn() as conn:
        for uid in user_ids:
            ext = f"sk-ant-mock-u{uid:05d}"
            row = conn.execute(
                "SELECT id FROM api_keys WHERE provider_id=? AND external_id=?",
                (provider_id, ext),
            ).fetchone()
            if row:
                kid = row["id"]
            else:
                kid = conn.execute(
                    """INSERT INTO api_keys(provider_id, external_id, name, redacted_value,
                                            owner_user_id, is_admin)
                       VALUES(?,?,?,?,?,0)""",
                    (provider_id, ext, f"mock-key-{uid}", f"sk-ant-mock-…u{uid:05d}", uid),
                ).lastrowid
            keys_by_user[uid] = kid
        conn.commit()
    return keys_by_user


def synth_anthropic(period_days: int = 30) -> dict[str, Any]:
    """Заполняет usage_events и daily_costs синтетикой по Anthropic.

    Идемпотентно: предварительно удаляет события Anthropic в окне.
    """
    # Конец окна = конец сегодняшнего дня. Это важно для идемпотентности: иначе
    # события на час позже end не попадут в DELETE и повторный sync задвоит данные.
    end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    start = end - timedelta(days=period_days)

    with get_conn() as conn:
        users = conn.execute(
            "SELECT id, full_name FROM users ORDER BY id"
        ).fetchall()
    if not users:
        # на свежей базе ещё не было OpenAI sync — нет смысла мокать
        return {"inserted": 0, "skipped": 1, "note": "no users yet — run OpenAI sync first"}

    pid, model_ids, prices = _ensure_provider_and_models()
    keys_by_user = _ensure_user_keys(pid, [u["id"] for u in users])

    with get_conn() as conn:
        conn.execute(
            "DELETE FROM usage_events WHERE provider_id = ? AND occurred_at BETWEEN ? AND ?",
            (
                pid,
                start.strftime("%Y-%m-%d %H:%M:%S"),
                end.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.execute(
            "DELETE FROM daily_costs WHERE provider_id = ? AND day BETWEEN ? AND ?",
            (pid, start.date().isoformat(), end.date().isoformat()),
        )
        conn.commit()

    inserted = 0
    cost_rows = 0
    rng = random.Random(42)

    for d in range(period_days):
        day_dt = end - timedelta(days=period_days - 1 - d)
        day_iso = day_dt.date().isoformat()
        # эмулируем недельный паттерн: чуть тише в выходные
        weekday = day_dt.weekday()
        weekday_factor = 0.45 if weekday >= 5 else 1.0

        for u_index, u in enumerate(users):
            # heavy users — первые 3, light — последние 3 (в пределах списка)
            heavy = u_index < 3
            light = u_index >= len(users) - 3
            base_factor = 2.4 if heavy else (0.4 if light else 1.0)

            day_total_cost = 0.0
            day_tokens_in = 0
            day_tokens_out = 0
            day_requests = 0
            rows: list[tuple] = []
            for _ in range(rng.randint(2, 6)):
                model_name, _, p_in, p_out, p_cache = rng.choices(
                    ANTHROPIC_MODELS, weights=[0.2, 0.5, 0.3]
                )[0]
                model_id = model_ids[model_name]
                tokens_in = rng.randint(800, 6_000) * (3 if heavy else 1)
                tokens_out = rng.randint(300, 3_500) * (3 if heavy else 1)
                tokens_cached = int(tokens_in * rng.uniform(0.0, 0.4))
                tokens_in = int(tokens_in * base_factor * weekday_factor)
                tokens_out = int(tokens_out * base_factor * weekday_factor)
                cost = (
                    (tokens_in - tokens_cached) / 1000.0 * p_in
                    + tokens_cached / 1000.0 * p_cache
                    + tokens_out / 1000.0 * p_out
                )
                latency = rng.randint(500, 4500)
                is_error = 1 if rng.random() < 0.025 else 0
                hour = rng.randint(8, 22)
                minute = rng.randint(0, 59)
                ts = day_dt.replace(hour=hour, minute=minute).strftime("%Y-%m-%d %H:%M:%S")
                rows.append((
                    u["id"], pid, model_id, keys_by_user[u["id"]], ts,
                    tokens_in, tokens_out, tokens_cached, round(cost, 4),
                    latency, is_error, rng.choice(["IDE", "API", "Agent", "Chat"]),
                ))
                day_total_cost += cost
                day_tokens_in += tokens_in
                day_tokens_out += tokens_out
                day_requests += 1

            if rows:
                with get_conn() as conn:
                    conn.executemany(
                        """INSERT INTO usage_events(
                            user_id, provider_id, model_id, api_key_id, occurred_at,
                            tokens_in, tokens_out, tokens_cached, cost_usd,
                            latency_ms, is_error, purpose
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        rows,
                    )
                    conn.execute(
                        """INSERT INTO daily_costs(user_id, provider_id, day,
                                                   cost_usd, tokens_in, tokens_out, requests)
                           VALUES(?,?,?,?,?,?,?)
                           ON CONFLICT(user_id, provider_id, day)
                           DO UPDATE SET cost_usd = excluded.cost_usd,
                                         tokens_in = excluded.tokens_in,
                                         tokens_out = excluded.tokens_out,
                                         requests = excluded.requests""",
                        (
                            u["id"], pid, day_iso,
                            round(day_total_cost, 4), day_tokens_in, day_tokens_out, day_requests,
                        ),
                    )
                    conn.commit()
                inserted += len(rows)
                cost_rows += 1

    return {"inserted": inserted, "daily_costs": cost_rows, "period_from": start.date().isoformat(), "period_to": end.date().isoformat()}
