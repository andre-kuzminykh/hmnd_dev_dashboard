"""Tests for connector type-coercion helpers."""
from __future__ import annotations

from data.connectors.base import to_float, to_int


def test_to_float_handles_string_numbers():
    assert to_float("0.123") == 0.123
    assert to_float("1") == 1.0
    assert to_float(0.5) == 0.5
    assert to_float(None) == 0.0
    assert to_float("") == 0.0
    assert to_float("not a number") == 0.0


def test_to_int_handles_string_numbers():
    assert to_int("42") == 42
    assert to_int(7) == 7
    assert to_int("3.7") == 3
    assert to_int(None) == 0
    assert to_int("garbage") == 0


def test_to_int_default():
    assert to_int(None, default=1) == 1
    assert to_int("", default=5) == 5
