"""F-16 — '?' help tooltips on KPIs and section titles.

We don't actually render Streamlit here (would need a browser); we
intercept `st.markdown` to capture the HTML the components emit and
assert the help-icon shape.
"""
from __future__ import annotations

from typing import Any


class _StCapture:
    """Minimal stub that records every markdown call so tests can inspect
    the HTML the components produced.
    """

    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def markdown(self, body: str, **kw):
        self.calls.append((body, kw))

    def columns(self, n, gap=None):  # used by kpi_row (Streamlit signature: columns(spec, *, gap))
        return [self for _ in range(n)]

    # context-manager protocol (Streamlit uses `with col:`)
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patched(monkeypatch):
    """Replace `streamlit` in the components module with our capture."""
    import frontend.components as comp
    cap = _StCapture()
    monkeypatch.setattr(comp, "st", cap)
    return comp, cap


def test_section_renders_help_icon(monkeypatch):
    """FR-16.1.1.1 — section(title, help=...) emits a '?' badge."""
    comp, cap = _patched(monkeypatch)
    comp.section("Code Quality", help="Качество кода через призму AI")
    assert cap.calls, "section should call st.markdown"
    html = cap.calls[0][0]
    assert 'class="hmnd-help"' in html
    assert "Качество кода" in html
    # title still rendered
    assert "Code Quality" in html


def test_kpi_row_renders_help_icon_per_card(monkeypatch):
    """FR-16.1.1.2 — kpi_row passes through help to each card.
    Cards with help → '?' badge in HTML. Cards without help → no badge.
    """
    comp, cap = _patched(monkeypatch)
    comp.kpi_row([
        {"label": "Bug rate", "value": "30%",
         "help": "Какой % коммитов — баг-фиксы"},
        {"label": "Reverts",  "value": "0.5%"},  # no help — no '?'
    ])
    # 2 markdown calls (one per card)
    htmls = [c[0] for c in cap.calls]
    assert len(htmls) == 2
    # First card has the badge, second doesn't.
    with_help = next(h for h in htmls if "Bug rate" in h)
    no_help   = next(h for h in htmls if "Reverts" in h)
    assert 'class="hmnd-help"' in with_help
    assert "Какой %" in with_help
    assert 'class="hmnd-help"' not in no_help


def test_help_icon_escapes_html(monkeypatch):
    """FR-16.1.1.3 — angle brackets / quotes in help text are escaped
    so they don't break the data-tip attribute or surrounding HTML.
    """
    from frontend.components import _help_icon
    out = _help_icon('AI > 50% && <script>alert("x")</script>')
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "&amp;&amp;" in out
    assert "&quot;" in out  # the quote escaped inside data-tip
    # must still be one well-formed <span>
    assert out.startswith('<span class="hmnd-help"')


def test_section_without_help_has_no_icon(monkeypatch):
    """FR-16.1.1.4 — backward compatibility: existing section('Title') calls
    without help produce zero '?' badges.
    """
    comp, cap = _patched(monkeypatch)
    comp.section("Plain Section")
    html = cap.calls[0][0]
    assert 'class="hmnd-help"' not in html
    assert "Plain Section" in html

    # And the helper itself:
    from frontend.components import _help_icon
    assert _help_icon(None) == ""
    assert _help_icon("") == ""


def test_help_icon_carries_aria_label():
    """FR-16.1.2.1 — '?' badge is keyboard-focusable (tabindex=0) and
    has aria-label for assistive tech.
    """
    from frontend.components import _help_icon
    out = _help_icon("Объяснение метрики")
    assert 'tabindex="0"' in out
    assert 'aria-label="Объяснение метрики"' in out
