"""Детерминированная генерация демо-данных.

Создаёт реалистичную картину 30 дней использования OpenAI и Anthropic с:
* командами и пользователями;
* сидениями (часть неактивных);
* usage_events с разными моделями;
* daily_costs (агрегированная);
* репозиториями, PR, коммитами;
* AI-code-attribution с разными источниками;
* парой намеренных аномалий — чтобы alert engine был не пустой.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .db import get_conn, init_schema, DB_PATH

RNG = random.Random(42)

TEAMS = [
    ("Backend", 4_000),
    ("Frontend", 2_500),
    ("Data", 3_000),
    ("Product", 1_500),
]

USERS = [
    ("ivan@hmnd.ai", "Ivan Petrov", "Backend", "Senior Engineer", 250),
    ("anna@hmnd.ai", "Anna Smirnova", "Backend", "Engineer", 200),
    ("daniil@hmnd.ai", "Daniil Volkov", "Backend", "Tech Lead", 400),
    ("maria@hmnd.ai", "Maria Sokolova", "Frontend", "Senior Engineer", 200),
    ("oleg@hmnd.ai", "Oleg Sidorov", "Frontend", "Engineer", 200),
    ("kate@hmnd.ai", "Kate Ivanova", "Frontend", "Engineer", 200),
    ("denis@hmnd.ai", "Denis Orlov", "Data", "ML Engineer", 350),
    ("polina@hmnd.ai", "Polina Belyaeva", "Data", "Data Scientist", 250),
    ("artem@hmnd.ai", "Artem Pavlov", "Data", "ML Engineer", 250),
    ("nika@hmnd.ai", "Nika Egorova", "Product", "PM", 150),
    ("max@hmnd.ai", "Max Lebedev", "Product", "PM", 150),
    ("sergey@hmnd.ai", "Sergey Kuznetsov", "Product", "Designer", 120),
]

PROVIDERS = ["openai", "anthropic"]

MODELS = [
    ("openai", "gpt-5.1", "gpt-5", 0.005, 0.015, 0.0025),
    ("openai", "gpt-5.1-mini", "gpt-5", 0.0008, 0.0024, 0.0004),
    ("openai", "o4-mini", "o4", 0.0011, 0.0044, 0.0006),
    ("anthropic", "claude-opus-4-7", "claude-4", 0.015, 0.075, 0.0075),
    ("anthropic", "claude-sonnet-4-6", "claude-4", 0.003, 0.015, 0.0015),
    ("anthropic", "claude-haiku-4-5", "claude-4", 0.001, 0.005, 0.0005),
]

SEAT_PLANS = [
    ("ChatGPT Business", "openai", 30),
    ("Claude Team", "anthropic", 30),
]

REPOS = [
    ("backend-api", "hmnd/backend-api", True),
    ("frontend-app", "hmnd/frontend-app", False),
    ("ml-pipelines", "hmnd/ml-pipelines", True),
    ("ops-tools", "hmnd/ops-tools", False),
    ("docs-site", "hmnd/docs-site", False),
]

ATTRIBUTION_SOURCES = [
    ("commit_message_marker", 0.95),
    ("pr_template_flag", 0.9),
    ("agent_metadata", 0.85),
    ("heuristic_block_size", 0.55),
]


def _exec(conn, sql: str, params: Iterable | None = None):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    return cur.lastrowid


def _isodt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def seed(db_path: Path | str | None = None, days: int = 30) -> None:
    init_schema(db_path)
    conn = get_conn(db_path)
    cur = conn.cursor()

    # wipe existing demo data so re-runs are idempotent
    for table in [
        "ai_code_attribution",
        "alerts",
        "pull_requests",
        "commits",
        "repositories",
        "daily_costs",
        "usage_events",
        "seats",
        "model_prices",
        "models",
        "providers",
        "users",
        "teams",
    ]:
        cur.execute(f"DELETE FROM {table}")
    conn.commit()

    team_ids: dict[str, int] = {}
    for name, budget in TEAMS:
        team_ids[name] = _exec(
            conn,
            "INSERT INTO teams(name, monthly_budget_usd) VALUES(?,?)",
            (name, budget),
        )

    provider_ids: dict[str, int] = {}
    for p in PROVIDERS:
        provider_ids[p] = _exec(conn, "INSERT INTO providers(name) VALUES(?)", (p,))

    model_ids: dict[str, int] = {}
    for provider, name, family, p_in, p_out, p_cache in MODELS:
        mid = _exec(
            conn,
            "INSERT INTO models(provider_id, name, family) VALUES(?,?,?)",
            (provider_ids[provider], name, family),
        )
        model_ids[name] = mid
        _exec(
            conn,
            """INSERT INTO model_prices(model_id, valid_from, input_per_1k, output_per_1k, cache_read_per_1k)
               VALUES(?,?,?,?,?)""",
            (mid, "2026-01-01", p_in, p_out, p_cache),
        )

    user_ids: dict[str, int] = {}
    for email, full_name, team, role, limit in USERS:
        user_ids[email] = _exec(
            conn,
            """INSERT INTO users(email, full_name, team_id, role, monthly_limit_usd, is_active)
               VALUES(?,?,?,?,?,1)""",
            (email, full_name, team_ids[team], role, limit),
        )

    # Seats: купленных мест 50; назначенных 22 (12 OpenAI + 10 Anthropic, 2 не используются)
    bought_open = 25
    bought_anth = 25
    # 22 assigned (по 11 на провайдера через заранее выбранных юзеров)
    open_seat_users = list(user_ids.values())[:11]
    anth_seat_users = list(user_ids.values())[:10]
    for plan_name, provider_name, monthly_cost in SEAT_PLANS:
        users_for_plan = open_seat_users if provider_name == "openai" else anth_seat_users
        bought = bought_open if provider_name == "openai" else bought_anth
        for i in range(bought):
            assigned_user = users_for_plan[i] if i < len(users_for_plan) else None
            assigned = 1 if assigned_user else 0
            assigned_at = _isodt(datetime.utcnow() - timedelta(days=60)) if assigned else None
            # сделаем 2 сидения "stale" — last_used_at очень давно
            if assigned and i in (0, 1):
                last_used = _isodt(datetime.utcnow() - timedelta(days=45))
            elif assigned:
                last_used = _isodt(datetime.utcnow() - timedelta(days=RNG.randint(0, 5)))
            else:
                last_used = None
            _exec(
                conn,
                """INSERT INTO seats(user_id, provider_id, seat_type, assigned, monthly_cost_usd,
                                     assigned_at, last_used_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    assigned_user,
                    provider_ids[provider_name],
                    plan_name,
                    assigned,
                    monthly_cost,
                    assigned_at,
                    last_used,
                ),
            )

    # Usage events
    end = datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
    user_id_list = list(user_ids.values())
    daily_acc: dict[tuple[int, int, str], dict] = {}
    for d in range(days):
        day = end - timedelta(days=days - 1 - d)
        for user_id in user_id_list:
            # Heavy users — первые 3, light — последние 3
            heavy = user_id in user_id_list[:3]
            light = user_id in user_id_list[-3:]
            base_requests = (12 if heavy else 6 if not light else 2) + RNG.randint(0, 4)
            for _ in range(base_requests):
                provider = RNG.choices(["openai", "anthropic"], weights=[0.55, 0.45])[0]
                provider_models = [m for m in MODELS if m[0] == provider]
                m = RNG.choices(provider_models, weights=[0.5, 0.3, 0.2])[0]
                m_name, p_in, p_out, p_cache = m[1], m[3], m[4], m[5]
                tokens_in = RNG.randint(800, 4_500) * (3 if heavy else 1)
                tokens_out = RNG.randint(300, 2_500) * (3 if heavy else 1)
                tokens_cached = int(tokens_in * RNG.uniform(0.0, 0.4))
                cost = (
                    (tokens_in - tokens_cached) / 1000.0 * p_in
                    + tokens_cached / 1000.0 * p_cache
                    + tokens_out / 1000.0 * p_out
                )
                latency = RNG.randint(400, 4500)
                is_error = 1 if RNG.random() < (0.04 if "haiku" in m_name else 0.02) else 0
                occurred = day + timedelta(
                    hours=RNG.randint(8, 22), minutes=RNG.randint(0, 59)
                )
                _exec(
                    conn,
                    """INSERT INTO usage_events(
                        user_id, provider_id, model_id, occurred_at,
                        tokens_in, tokens_out, tokens_cached, cost_usd,
                        latency_ms, is_error, purpose
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        user_id,
                        provider_ids[provider],
                        model_ids[m_name],
                        _isodt(occurred),
                        tokens_in,
                        tokens_out,
                        tokens_cached,
                        round(cost, 4),
                        latency,
                        is_error,
                        RNG.choice(["IDE", "API", "Agent", "Chat"]),
                    ),
                )
                key = (user_id, provider_ids[provider], day.date().isoformat())
                acc = daily_acc.setdefault(
                    key,
                    {"cost": 0.0, "in": 0, "out": 0, "req": 0},
                )
                acc["cost"] += cost
                acc["in"] += tokens_in
                acc["out"] += tokens_out
                acc["req"] += 1
    conn.commit()

    # Намеренная аномалия: Ivan получает $80 сегодня
    spike_user = user_ids["ivan@hmnd.ai"]
    spike_day = end
    _exec(
        conn,
        """INSERT INTO usage_events(
            user_id, provider_id, model_id, occurred_at,
            tokens_in, tokens_out, tokens_cached, cost_usd, latency_ms, is_error, purpose
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            spike_user,
            provider_ids["anthropic"],
            model_ids["claude-opus-4-7"],
            _isodt(spike_day),
            500_000,
            150_000,
            0,
            80.0,
            5400,
            0,
            "Agent",
        ),
    )
    key = (spike_user, provider_ids["anthropic"], spike_day.date().isoformat())
    acc = daily_acc.setdefault(key, {"cost": 0.0, "in": 0, "out": 0, "req": 0})
    acc["cost"] += 80.0
    acc["in"] += 500_000
    acc["out"] += 150_000
    acc["req"] += 1

    # daily_costs
    for (uid, pid, day), v in daily_acc.items():
        _exec(
            conn,
            """INSERT INTO daily_costs(user_id, provider_id, day, cost_usd, tokens_in, tokens_out, requests)
               VALUES(?,?,?,?,?,?,?)""",
            (uid, pid, day, round(v["cost"], 4), v["in"], v["out"], v["req"]),
        )

    # Repositories + commits + PRs + AI attribution
    repo_ids = {}
    for name, full_name, critical in REPOS:
        repo_ids[name] = _exec(
            conn,
            "INSERT INTO repositories(name, full_name, is_critical) VALUES(?,?,?)",
            (name, full_name, 1 if critical else 0),
        )

    for repo_name, _, critical in REPOS:
        rid = repo_ids[repo_name]
        n_commits = RNG.randint(60, 200)
        for i in range(n_commits):
            author = RNG.choice(user_id_list)
            authored = end - timedelta(days=RNG.randint(0, days - 1), hours=RNG.randint(0, 23))
            additions = RNG.randint(5, 400)
            deletions = RNG.randint(0, 200)
            ai_marker = RNG.random() < 0.35
            message = "feat: new feature"
            if ai_marker:
                message += "\n\nAI-assisted: yes\nCo-authored-by: claude <noreply@anthropic.com>"
            cid = _exec(
                conn,
                """INSERT INTO commits(repo_id, sha, author_id, authored_at, message, additions, deletions)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    rid,
                    f"{repo_name}-{i:04d}",
                    author,
                    _isodt(authored),
                    message,
                    additions,
                    deletions,
                ),
            )
            if ai_marker:
                source, conf = RNG.choice(ATTRIBUTION_SOURCES)
                ai_lines = int(additions * RNG.uniform(0.3, 0.95))
                _exec(
                    conn,
                    """INSERT INTO ai_code_attribution(repo_id, commit_id, user_id, ai_lines,
                                                       total_lines, source, confidence)
                       VALUES(?,?,?,?,?,?,?)""",
                    (rid, cid, author, ai_lines, additions, source, conf),
                )

        # PRs: 20–40 per repo
        n_prs = RNG.randint(20, 40)
        for j in range(n_prs):
            author = RNG.choice(user_id_list)
            created = end - timedelta(days=RNG.randint(0, days - 1))
            merged_at = created + timedelta(hours=RNG.randint(2, 48)) if RNG.random() < 0.85 else None
            additions = RNG.randint(20, 1500)
            deletions = RNG.randint(0, 800)
            review_comments = RNG.randint(0, 12)
            critical_files = RNG.randint(0, 4) if critical else RNG.randint(0, 1)
            bug_count = 1 if RNG.random() < 0.1 else 0
            rolled_back = 1 if RNG.random() < 0.04 else 0
            has_human_review = 1 if RNG.random() > 0.05 else 0
            pr_id = _exec(
                conn,
                """INSERT INTO pull_requests(
                    repo_id, number, title, author_id, created_at, merged_at, state,
                    additions, deletions, review_comments, critical_files_changed,
                    bug_count, rolled_back, has_human_review
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rid,
                    j + 1,
                    f"PR #{j + 1} in {repo_name}",
                    author,
                    _isodt(created),
                    _isodt(merged_at) if merged_at else None,
                    "merged" if merged_at else "open",
                    additions,
                    deletions,
                    review_comments,
                    critical_files,
                    bug_count,
                    rolled_back,
                    has_human_review,
                ),
            )
            if RNG.random() < 0.5:
                source, conf = RNG.choice(ATTRIBUTION_SOURCES)
                ai_lines = int(additions * RNG.uniform(0.2, 0.95))
                _exec(
                    conn,
                    """INSERT INTO ai_code_attribution(
                        repo_id, pr_id, user_id, ai_lines, total_lines, source, confidence
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (rid, pr_id, author, ai_lines, additions, source, conf),
                )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    seed()
    print(f"Seed ok → {DB_PATH}")
