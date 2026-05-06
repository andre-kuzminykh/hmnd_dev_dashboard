"""Tests for OpenAI connector pricing and cost computation."""
from __future__ import annotations

from data.connectors.openai import OPENAI_DEFAULT_PRICES, _model_price_lookup


def test_price_lookup_exact():
    assert _model_price_lookup("gpt-4o") == OPENAI_DEFAULT_PRICES["gpt-4o"]
    assert _model_price_lookup("gpt-4o-mini") == OPENAI_DEFAULT_PRICES["gpt-4o-mini"]


def test_price_lookup_versioned_prefix():
    """Versioned models (gpt-4o-2024-08-06) should pick the longest matching base."""
    assert _model_price_lookup("gpt-4o-2024-08-06") == OPENAI_DEFAULT_PRICES["gpt-4o"]
    assert _model_price_lookup("gpt-4o-mini-2024-07-18") == OPENAI_DEFAULT_PRICES["gpt-4o-mini"]
    # gpt-4o-mini is longer than gpt-4o, must win
    assert _model_price_lookup("gpt-4o-mini-2024-07-18") != OPENAI_DEFAULT_PRICES["gpt-4o"]


def test_price_lookup_unknown_returns_none():
    assert _model_price_lookup("totally-fake-model") is None
    assert _model_price_lookup("") is None
    assert _model_price_lookup(None) is None  # type: ignore[arg-type]


def test_price_lookup_embeddings():
    p = _model_price_lookup("text-embedding-3-small")
    assert p is not None
    assert p[1] == 0  # output cost is 0 for embeddings
