"""F-08 Alerts."""
from __future__ import annotations

from backend.services.alerts import RULES, evaluate_alert_rules, list_alerts, update_status


def test_fr_08_1_1_1_dedup(tmp_db):
    n1 = evaluate_alert_rules()
    n2 = evaluate_alert_rules()  # повторный запуск не должен ничего вставить
    assert n1 >= 1, "seed аномалия должна породить хотя бы один алерт"
    assert n2 == 0


def test_fr_08_1_1_2_rules_set():
    """Минимальный набор правил из спеки представлен."""
    names = {r.__name__ for r in RULES}
    expected = {
        "rule_user_daily_spend",
        "rule_team_monthly_budget",
        "rule_inactive_seat",
        "rule_ai_code_in_critical",
        "rule_pr_no_review",
        "rule_provider_spike",
    }
    assert expected == names


def test_fr_08_1_1_4_status_transitions(tmp_db):
    evaluate_alert_rules()
    alerts = list_alerts(status="new")
    assert alerts
    aid = alerts[0]["id"]
    update_status(aid, "ack")
    assert list_alerts(status="ack")
    update_status(aid, "resolved")
    assert list_alerts(status="resolved")


def test_inactive_seat_rule_fires(tmp_db):
    """В seed заложены 2 stale seat'а — алерт inactive_seat должен сработать."""
    evaluate_alert_rules()
    alerts = list_alerts(status="all")
    types = {a["type"] for a in alerts}
    assert "inactive_seat" in types
