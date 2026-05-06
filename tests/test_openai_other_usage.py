"""Integration-level tests for OpenAI connector beyond the completions endpoint."""
from __future__ import annotations

from data.connectors.openai import OpenAIConnector


def test_other_usage_method_exists():
    """The connector must expose _sync_other_usage so spend reconciliation
    against OpenAI's billing UI doesn't silently miss embeddings/images/audio.
    """
    assert hasattr(OpenAIConnector, "_sync_other_usage")
    assert callable(getattr(OpenAIConnector, "_sync_other_usage"))


def test_other_usage_endpoints_covered():
    """Read the source of _sync_other_usage and assert it covers every
    usage endpoint OpenAI exposes — embeddings, moderations, audio
    (speeches + transcriptions), images, vector_stores, code_interpreter.

    This is intentionally a static assertion: if anyone removes one of
    these endpoints from the loop, the test fails before sync ever runs
    against a real org.
    """
    import inspect
    src = inspect.getsource(OpenAIConnector._sync_other_usage)
    expected = [
        "usage/embeddings",
        "usage/moderations",
        "usage/audio_speeches",
        "usage/audio_transcriptions",
        "usage/images",
        "usage/vector_stores",
        "usage/code_interpreter_sessions",
    ]
    missing = [e for e in expected if e not in src]
    assert not missing, f"endpoints missing in _sync_other_usage: {missing}"
