"""Compare every number from the colleague's HTML report against the current DB.

For each metric prints:  <metric> | report | DB | delta | OK/!=

Usage:
    docker compose exec dashboard python -m scripts.audit_against_report
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from data.db import get_conn

# ---- Numbers from the colleague's report (HTML snapshot block) ----
REPORT = {
    "total_30d_usd":       23353,
    "active_humans_30d":   140,
    "top10_share_pct":     63.2,
    "top10_spend_usd":     14757,
    "anthropic_pct":       57.2,
    "cursor_pct":          29.9,
    "openai_pct":          12.9,
    "anthropic_spend":     13779, "anthropic_users": 111, "anthropic_events": 6808,
    "cursor_spend":         7214, "cursor_active": 67,     "cursor_seats": 81, "cursor_events": 1876,
    "openai_spend":         3112, "openai_humans": 7,      "openai_bots": 1,   "openai_events": 57392,
    "top5_spend":          10443,
    "top15_spend":         16737,
}

REPORT_TOP15 = [
    ("Oleg Sinavski",    2936),
    ("Atindra Nair",     2340),
    ("Eugene Lyapustin", 2319),
    ("Richard",          1558),
    ("Sam Pfeiffer",     1289),
    ("Cody Griffin",     1240),
    ("Andy Park",         987),
    ("Matt Klingensmith", 791),
    ("Artem",             687),
    ("Saeid Samadi",      610),
    ("Daksh Dhingra",     494),
    ("Richard Osterloh",  433),
    ("ber131",            355),
    ("Vaibhav Mehta",     354),
    ("cfil",              344),
]


def _check(label: str, report_val: float, db_val: float, tol_pct: float = 5.0) -> None:
    if report_val == 0:
        delta = db_val
        pct = float("inf") if db_val else 0
    else:
        delta = db_val - report_val
        pct = (delta / report_val) * 100
    ok = abs(pct) <= tol_pct
    mark = "  OK" if ok else " !!!"
    delta_str = f"{delta:+,.0f}" if isinstance(delta, (int, float)) else str(delta)
    pct_str = f"({pct:+.1f}%)" if report_val else ""
    print(f"  {mark}  {label:<32} report={report_val:>10,.0f}  db={db_val:>10,.0f}  Δ={delta_str:>+10s} {pct_str}")


def _now_30d():
    end = datetime.utcnow()
    start = end - timedelta(days=30)
    return (start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"))


def main() -> int:
    s_iso, e_iso = _now_30d()
    with get_conn() as c:
        # Per-source spend / users / events
        anth = c.execute(
            """SELECT ROUND(SUM(cost_usd),2) s, COUNT(DISTINCT user_id) u, COUNT(*) c
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='anthropic' AND occurred_at BETWEEN ? AND ?""",
            (s_iso, e_iso),
        ).fetchone()
        oai = c.execute(
            """SELECT ROUND(SUM(cost_usd),2) s, COUNT(DISTINCT user_id) u, COUNT(*) c
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='openai' AND occurred_at BETWEEN ? AND ?""",
            (s_iso, e_iso),
        ).fetchone()
        cur = c.execute(
            """SELECT ROUND(SUM(cost_usd),2) s, COUNT(DISTINCT user_id) u, COUNT(*) c
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='cursor' AND occurred_at BETWEEN ? AND ?""",
            (s_iso, e_iso),
        ).fetchone()
        all_users = c.execute(
            """SELECT COUNT(DISTINCT user_id) u FROM usage_events
               WHERE occurred_at BETWEEN ? AND ?""", (s_iso, e_iso),
        ).fetchone()
        # Top spenders cross-tool
        top_all = c.execute(
            """SELECT u.full_name name, ROUND(SUM(ue.cost_usd),2) s
               FROM usage_events ue JOIN users u ON u.id=ue.user_id
               WHERE occurred_at BETWEEN ? AND ?
               GROUP BY u.id HAVING s > 0 ORDER BY s DESC""", (s_iso, e_iso),
        ).fetchall()

    anth_s = float(anth["s"] or 0); oai_s = float(oai["s"] or 0); cur_s = float(cur["s"] or 0)
    total_db = anth_s + oai_s + cur_s

    print("=" * 100)
    print(f"REPORT vs CURRENT DB — last 30 days ({s_iso[:10]} → {e_iso[:10]})")
    print("=" * 100)
    print()
    print("── TOTALS ──")
    _check("Total spend (30d, USD)", REPORT["total_30d_usd"], total_db, tol_pct=2)
    _check("Active humans (30d)",   REPORT["active_humans_30d"], all_users["u"])
    print()
    print("── PER-SOURCE ──")
    _check("Anthropic spend",  REPORT["anthropic_spend"],  anth_s)
    _check("Anthropic users",  REPORT["anthropic_users"],  anth["u"])
    _check("Anthropic events", REPORT["anthropic_events"], anth["c"])
    print()
    _check("OpenAI spend",     REPORT["openai_spend"],     oai_s)
    _check("OpenAI users",     REPORT["openai_humans"] + REPORT["openai_bots"], oai["u"])
    _check("OpenAI events",    REPORT["openai_events"],    oai["c"])
    print()
    _check("Cursor spend",     REPORT["cursor_spend"],     cur_s)
    _check("Cursor users",     REPORT["cursor_active"],    cur["u"])
    _check("Cursor events",    REPORT["cursor_events"],    cur["c"])
    print()
    print("── TOOL MIX (%) ──")
    if total_db:
        _check("Anthropic %", REPORT["anthropic_pct"], round(anth_s/total_db*100, 1))
        _check("Cursor %",    REPORT["cursor_pct"],    round(cur_s/total_db*100, 1))
        _check("OpenAI %",    REPORT["openai_pct"],    round(oai_s/total_db*100, 1))
    print()
    print("── CONCENTRATION ──")
    top10_db = sum(float(r["s"]) for r in top_all[:10])
    _check("Top 10 spend",      REPORT["top10_spend_usd"], top10_db)
    if total_db:
        _check("Top 10 share %",
               REPORT["top10_share_pct"], round(top10_db/total_db*100, 1))
    _check("Top 5 spend",       REPORT["top5_spend"],  sum(float(r["s"]) for r in top_all[:5]))
    _check("Top 15 spend",      REPORT["top15_spend"], sum(float(r["s"]) for r in top_all[:15]))
    print()
    print("── TOP-15 SPENDERS (name match by substring) ──")
    db_by_name = {r["name"]: float(r["s"]) for r in top_all}
    for name, report_v in REPORT_TOP15:
        # Find by substring (handles e.g. "Atindra Nair" vs "Atindra Nair (atin)")
        candidates = [(n, v) for n, v in db_by_name.items() if name.lower() in n.lower()]
        if candidates:
            db_v = max(c[1] for c in candidates)
            _check(name, report_v, db_v, tol_pct=10)
        else:
            print(f"  ???  {name:<32} report={report_v:>10,.0f}  db=NOT FOUND")
    print()
    # Anthropic JSON file inspection
    print("── ANTHROPIC JSON ON DISK ──")
    for p in (Path("/app/sources"), Path("sources")):
        if p.exists():
            for f in sorted(p.glob("Anthropic*_*.json")):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    meta = d.get("_meta") or {}
                    roll = d.get("rollups") or {}
                    cents = float(roll.get("totalSpend") or 0)
                    print(f"  {f.name}")
                    print(f"     rangeStart:    {meta.get('rangeStart')}")
                    print(f"     rangeEnd:      {meta.get('rangeEnd')}")
                    print(f"     totalSpend:    {cents:,.0f} cents → ${cents/100:,.2f}")
                    print(f"     totalUsers:    {roll.get('totalUsers')}")
                    print(f"     totalRequests: {roll.get('totalRequests')}")
                    sbp = roll.get("spendByProduct") or {}
                    if sbp:
                        print(f"     spendByProduct:")
                        for k, v in sbp.items():
                            print(f"       {k:<14} {float(v):,.0f} cents → ${float(v)/100:,.2f}")
                except Exception as exc:
                    print(f"  {f.name} (read failed: {exc})")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
