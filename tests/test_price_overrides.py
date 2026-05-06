"""Tests for HMND_OPENAI_PRICES_OVERRIDE env support."""
from __future__ import annotations

import json


def test_override_exact_name(monkeypatch):
    monkeypatch.setenv(
        "HMND_OPENAI_PRICES_OVERRIDE",
        json.dumps({"gpt-5.5": [0.002, 0.008, 0.0005]}),
    )
    from data.connectors.openai import _model_price_lookup
    p = _model_price_lookup("gpt-5.5")
    assert p == (0.002, 0.008, 0.0005)


def test_override_prefix_match(monkeypatch):
    """Versioned model name should pick up the override via prefix."""
    monkeypatch.setenv(
        "HMND_OPENAI_PRICES_OVERRIDE",
        json.dumps({"gpt-5.5": [0.002, 0.008, 0.0005]}),
    )
    from data.connectors.openai import _model_price_lookup
    p = _model_price_lookup("gpt-5.5-2026-04-23")
    assert p == (0.002, 0.008, 0.0005)


def test_override_wins_over_defaults(monkeypatch):
    """If a default and override both match, the override must take priority."""
    monkeypatch.setenv(
        "HMND_OPENAI_PRICES_OVERRIDE",
        # override gpt-4o with absurdly high values to verify it's used
        json.dumps({"gpt-4o": [99.0, 99.0, 99.0]}),
    )
    from data.connectors.openai import _model_price_lookup
    p = _model_price_lookup("gpt-4o-2024-08-06")
    assert p == (99.0, 99.0, 99.0)


def test_invalid_json_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("HMND_OPENAI_PRICES_OVERRIDE", "{not valid json")
    from data.connectors.openai import _model_price_lookup, OPENAI_DEFAULT_PRICES
    p = _model_price_lookup("gpt-4o")
    assert p == OPENAI_DEFAULT_PRICES["gpt-4o"]


def test_no_override_unchanged(monkeypatch):
    monkeypatch.delenv("HMND_OPENAI_PRICES_OVERRIDE", raising=False)
    from data.connectors.openai import _model_price_lookup, OPENAI_DEFAULT_PRICES
    assert _model_price_lookup("gpt-4o") == OPENAI_DEFAULT_PRICES["gpt-4o"]
    assert _model_price_lookup("totally-fake-xyz") is None
