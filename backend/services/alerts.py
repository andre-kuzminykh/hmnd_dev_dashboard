"""F-08 Alerts engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha1
from typing import Any, Callable

from data.db import get_conn


@dataclass
class AlertCandidate:
    type: str
    severity: str
    subject_kind: str
    subject_id: int | None
    message: str
    dedup_key: str


def _hash_key(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return sha1(raw.encode()).hexdigest()


# --- rules (FR-08.1.1.2) ---


def rule_user_daily_spend(conn, today: datetime) -> list[AlertCandidate]:
    """user_daily_spend > $50."""
    rows = conn.execute(
        """
        SELECT user_id, SUM(cost_usd) AS today_cost
        FROM daily_costs
        WHERE day = ?
        GROUP BY user_id
        HAVING today_cost > 50
        """,
        (today.date().isoformat(),),
    ).fetchall()
    return [
        AlertCandidate(
            type="spend_spike",
            severity="high",
            subject_kind="user",
            subject_id=r["user_id"],
            message=f"User #{r['user_id']} spent ${r['today_cost']:.2f} today",
            dedup_key=_hash_key("user_daily_spend", r["user_id"], today.date()),
        )
        for r in rows
    ]


def rule_team_monthly_budget(conn, today: datetime) -> list[AlertCandidate]:
    """team_monthly_budget_exceed > 80%."""
    month_start = today.replace(day=1).date().isoformat()
    rows = conn.execute(
        """
        SELECT t.id AS team_id, t.name, t.monthly_budget_usd,
               COALESCE(SUM(dc.cost_usd), 0) AS spent
        FROM teams t
        LEFT JOIN users u ON u.team_id = t.id
        LEFT JOIN daily_costs dc ON dc.user_id = u.id AND dc.day >= ?
        GROUP BY t.id
        HAVING t.monthly_budget_usd > 0 AND spent > t.monthly_budget_usd * 0.8
        """,
        (month_start,),
    ).fetchall()
    out = []
    for r in rows:
        ratio = r["spent"] / r["monthly_budget_usd"]
        sev = "critical" if ratio >= 1.0 else "high"
        out.append(
            AlertCandidate(
                type="budget_exceed",
                severity=sev,
                subject_kind="team",
                subject_id=r["team_id"],
                message=(
                    f"Team {r['name']} used ${r['spent']:.0f} of "
                    f"${r['monthly_budget_usd']:.0f} budget ({ratio:.0%})"
                ),
                dedup_key=_hash_key("team_monthly_budget", r["team_id"], today.strftime("%Y-%m")),
            )
        )
    return out


def rule_inactive_seat(conn, today: datetime) -> list[AlertCandidate]:
    """inactive_paid_seat > 14d."""
    threshold = (today - timedelta(days=14)).isoformat(sep=" ")
    rows = conn.execute(
        """
        SELECT id, user_id, seat_type
        FROM seats
        WHERE assigned = 1
          AND (last_used_at IS NULL OR last_used_at < ?)
        """,
        (threshold,),
    ).fetchall()
    return [
        AlertCandidate(
            type="inactive_seat",
            severity="medium",
            subject_kind="seat",
            subject_id=r["id"],
            message=f"Seat #{r['id']} ({r['seat_type']}) inactive >14 days",
            dedup_key=_hash_key("inactive_seat", r["id"]),
        )
        for r in rows
    ]


def rule_ai_code_in_critical(conn, today: datetime) -> list[AlertCandidate]:
    """ai_code_pct_in_critical > 60."""
    rows = conn.execute(
        """
        SELECT r.id, r.name,
               COALESCE(SUM(att.ai_lines), 0)    AS ai_lines,
               COALESCE(SUM(att.total_lines), 0) AS total_lines
        FROM repositories r
        LEFT JOIN ai_code_attribution att ON att.repo_id = r.id
        WHERE r.is_critical = 1
        GROUP BY r.id
        HAVING total_lines > 0 AND (ai_lines * 100.0 / total_lines) > 60
        """
    ).fetchall()
    return [
        AlertCandidate(
            type="ai_code_high",
            severity="high",
            subject_kind="repo",
            subject_id=r["id"],
            message=(
                f"Critical repo {r['name']} has "
                f"{r['ai_lines']*100/r['total_lines']:.1f}% AI-attributed code"
            ),
            dedup_key=_hash_key("ai_code_in_critical", r["id"], today.strftime("%Y-%m")),
        )
        for r in rows
    ]


def rule_pr_no_review(conn, today: datetime) -> list[AlertCandidate]:
    """pr_ai_code_pct > 80 AND no_human_review."""
    threshold = (today - timedelta(days=14)).isoformat(sep=" ")
    rows = conn.execute(
        """
        SELECT pr.id, pr.number, r.name AS repo,
               COALESCE(SUM(att.ai_lines), 0) AS ai_lines,
               COALESCE(SUM(att.total_lines), 0) AS total_lines,
               pr.has_human_review
        FROM pull_requests pr
        LEFT JOIN ai_code_attribution att ON att.pr_id = pr.id
        JOIN repositories r ON r.id = pr.repo_id
        WHERE pr.created_at >= ?
        GROUP BY pr.id
        HAVING total_lines > 0
           AND (ai_lines * 100.0 / total_lines) > 80
           AND pr.has_human_review = 0
        """,
        (threshold,),
    ).fetchall()
    return [
        AlertCandidate(
            type="pr_no_review",
            severity="high",
            subject_kind="pr",
            subject_id=r["id"],
            message=f"PR #{r['number']} in {r['repo']} >80% AI code, no human review",
            dedup_key=_hash_key("pr_no_review", r["id"]),
        )
        for r in rows
    ]


def rule_provider_spike(conn, today: datetime) -> list[AlertCandidate]:
    """provider_usage_spike > 3x_avg."""
    today_iso = today.date().isoformat()
    horizon = (today - timedelta(days=14)).date().isoformat()
    rows = conn.execute(
        """
        SELECT provider_id,
               SUM(CASE WHEN day = ? THEN cost_usd ELSE 0 END) AS today_cost,
               AVG(CASE WHEN day < ? THEN cost_usd END)        AS avg_cost
        FROM daily_costs
        WHERE day >= ?
        GROUP BY provider_id
        """,
        (today_iso, today_iso, horizon),
    ).fetchall()
    out = []
    for r in rows:
        today_cost = r["today_cost"] or 0
        avg_cost = r["avg_cost"] or 0
        if avg_cost > 5 and today_cost > 3 * avg_cost:
            out.append(
                AlertCandidate(
                    type="provider_spike",
                    severity="high",
                    subject_kind="provider",
                    subject_id=r["provider_id"],
                    message=(
                        f"Provider #{r['provider_id']} usage today ${today_cost:.2f} "
                        f">3x avg ${avg_cost:.2f}"
                    ),
                    dedup_key=_hash_key("provider_spike", r["provider_id"], today_iso),
                )
            )
    return out


RULES: list[Callable] = [
    rule_user_daily_spend,
    rule_team_monthly_budget,
    rule_inactive_seat,
    rule_ai_code_in_critical,
    rule_pr_no_review,
    rule_provider_spike,
]


def evaluate_alert_rules(now: datetime | None = None) -> int:
    """FR-08.1.1.1 — запускает все правила, дедуплицирует по dedup_key."""
    today = now or datetime.utcnow()
    inserted = 0
    with get_conn() as conn:
        for rule in RULES:
            for c in rule(conn, today):
                cur = conn.execute(
                    "SELECT 1 FROM alerts WHERE dedup_key = ?", (c.dedup_key,)
                )
                if cur.fetchone():
                    continue
                conn.execute(
                    """INSERT INTO alerts(type, severity, subject_kind, subject_id,
                                          message, dedup_key, status)
                       VALUES(?,?,?,?,?,?, 'new')""",
                    (
                        c.type,
                        c.severity,
                        c.subject_kind,
                        c.subject_id,
                        c.message,
                        c.dedup_key,
                    ),
                )
                inserted += 1
        conn.commit()
    return inserted


def list_alerts(status: str | None = None, severity: str | None = None) -> list[dict[str, Any]]:
    where, params = ["1=1"], []
    if status and status != "all":
        where.append("status = ?")
        params.append(status)
    if severity and severity != "all":
        where.append("severity = ?")
        params.append(severity)
    sql = f"""
        SELECT id, created_at, type, severity, subject_kind, subject_id, message, status
        FROM alerts
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
    """
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def update_status(alert_id: int, new_status: str) -> None:
    """FR-08.1.1.4."""
    if new_status not in ("new", "ack", "resolved"):
        raise ValueError("invalid status")
    with get_conn() as conn:
        conn.execute(
            "UPDATE alerts SET status = ?, resolved_at = CASE WHEN ? = 'resolved' THEN datetime('now') ELSE resolved_at END WHERE id = ?",
            (new_status, new_status, alert_id),
        )
        conn.commit()
