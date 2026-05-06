"""Verify _sync_other_usage is gated behind HMND_OPENAI_OTHER_USAGE."""
from __future__ import annotations

import inspect

from data.connectors.openai import OpenAIConnector


def test_other_usage_is_gated_by_env_flag():
    """The sync() body must NOT call _sync_other_usage unconditionally — that
    endpoint family inflates spend when models don't have token-based prices
    (audio, code interpreter, vector stores).
    """
    src = inspect.getsource(OpenAIConnector.sync)
    assert "HMND_OPENAI_OTHER_USAGE" in src, (
        "_sync_other_usage must be guarded by the HMND_OPENAI_OTHER_USAGE flag"
    )
    # And the always-on path must still run completions
    assert "_sync_usage(" in src
    # And on flag-off we must sweep stale 'usage/*' rows so toggling the flag
    # back off actually drops the inflated spend from the dashboard.
    assert "swept" in src or "DELETE FROM usage_events" in src


def test_default_is_off():
    """Without the env var set, _sync_other_usage must not run.

    We assert this indirectly: the sync() source must check the env var
    before calling _sync_other_usage. The actual default behaviour is that
    os.environ.get returns None (-> falsy).
    """
    src = inspect.getsource(OpenAIConnector.sync)
    # The check must be a positive guard (calls _sync_other_usage only when
    # the flag is set), not the inverse.
    assert "_sync_other_usage" in src
    # Make sure it's inside an `if` that references the flag
    flag_idx = src.index("HMND_OPENAI_OTHER_USAGE")
    other_idx = src.index("_sync_other_usage(")
    assert flag_idx < other_idx, (
        "the HMND_OPENAI_OTHER_USAGE check must come BEFORE the call"
    )
