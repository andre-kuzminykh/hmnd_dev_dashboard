"""F-09 Connectors."""
from __future__ import annotations

from data.connectors import AnthropicConnector, GitHubConnector, OpenAIConnector
from data.connectors.github import GitHubConnector as GH


def test_fr_09_1_1_1_connector_contract():
    """Все коннекторы реализуют test_connection() и sync()."""
    for cls in [OpenAIConnector, AnthropicConnector, GitHubConnector]:
        c = cls(api_key=None, mock=True)
        assert hasattr(c, "test_connection") and callable(c.test_connection)
        assert hasattr(c, "sync") and callable(c.sync)
        assert c.test_connection() is True
        report = c.sync(7)
        assert report.provider == cls.name


def test_nfr_09_1_1_1_mock_when_no_key():
    """Без ключа коннектор переходит в mock автоматически."""
    c = OpenAIConnector(api_key=None, mock=False)
    assert c.mock is True


def test_fr_05_1_1_2_ai_attribution_priority():
    # commit message marker — самый сильный сигнал
    src, conf = GH.detect_ai_source("feat: foo\n\nAI-assisted: yes")
    assert src == "commit_message_marker"
    assert conf >= 0.9
    src, conf = GH.detect_ai_source("feat\n\nCo-authored-by: claude <noreply@anthropic.com>")
    assert src == "agent_metadata"
    src, conf = GH.detect_ai_source("just a commit")
    assert src is None
