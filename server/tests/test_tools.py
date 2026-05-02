# Copyright 2026 zoltan-alt — Licensed under Apache-2.0. See LICENSE.

"""Unit tests for tool helpers (no device required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from mobile_design_mcp import (  # noqa: E402
    _normalize_key,
    _render_flow,
    _scroll_coords,
    _selector_yaml,
    _yaml_str,
)


# ---------------------------------------------------------------------------
# _yaml_str
# ---------------------------------------------------------------------------


def test_yaml_str_simple():
    assert _yaml_str("hello") == '"hello"'


def test_yaml_str_with_quotes():
    assert _yaml_str('say "hi"') == '"say \\"hi\\""'


def test_yaml_str_with_backslash():
    assert _yaml_str("a\\b") == '"a\\\\b"'


def test_yaml_str_empty():
    assert _yaml_str("") == '""'


# ---------------------------------------------------------------------------
# _selector_yaml
# ---------------------------------------------------------------------------


def test_selector_yaml_id():
    assert _selector_yaml(id="todo-card-0") == 'id: "todo-card-0"'


def test_selector_yaml_text():
    assert _selector_yaml(text="Save") == 'text: "Save"'


def test_selector_yaml_id_takes_precedence():
    assert _selector_yaml(id="x", text="y") == 'id: "x"'


def test_selector_yaml_neither_returns_none():
    assert _selector_yaml() is None


def test_selector_yaml_escapes_quotes_in_text():
    assert _selector_yaml(text='He said "hi"') == 'text: "He said \\"hi\\""'


# ---------------------------------------------------------------------------
# _scroll_coords
# ---------------------------------------------------------------------------


def test_scroll_coords_up_short():
    start, end = _scroll_coords("up", "short")
    # short = 30%, half = 15. mid = 50. UP: start lower, end higher.
    assert start == "50%, 65%"
    assert end == "50%, 35%"


def test_scroll_coords_down_short():
    start, end = _scroll_coords("down", "short")
    assert start == "50%, 35%"
    assert end == "50%, 65%"


def test_scroll_coords_up_long():
    start, end = _scroll_coords("up", "long")
    # long = 70%, half = 35. UP: start lower, end higher.
    assert start == "50%, 85%"
    assert end == "50%, 15%"


def test_scroll_coords_down_long():
    start, end = _scroll_coords("down", "long")
    assert start == "50%, 15%"
    assert end == "50%, 85%"


def test_scroll_coords_left_short():
    start, end = _scroll_coords("left", "short")
    assert start == "65%, 50%"
    assert end == "35%, 50%"


def test_scroll_coords_right_long():
    start, end = _scroll_coords("right", "long")
    assert start == "15%, 50%"
    assert end == "85%, 50%"


def test_scroll_coords_case_insensitive_direction():
    start, _ = _scroll_coords("UP", "short")
    assert start == "50%, 65%"


def test_scroll_coords_invalid_direction():
    with pytest.raises(ValueError, match="direction"):
        _scroll_coords("sideways", "short")


def test_scroll_coords_invalid_distance():
    with pytest.raises(ValueError, match="distance"):
        _scroll_coords("up", "medium")


# ---------------------------------------------------------------------------
# _normalize_key
# ---------------------------------------------------------------------------


def test_normalize_key_canonical_uppercase():
    assert _normalize_key("BACK") == "BACK"
    assert _normalize_key("HOME") == "HOME"
    assert _normalize_key("ENTER") == "ENTER"
    assert _normalize_key("ESCAPE") == "ESCAPE"


def test_normalize_key_lowercase():
    assert _normalize_key("back") == "BACK"
    assert _normalize_key("home") == "HOME"


def test_normalize_key_synonyms():
    assert _normalize_key("esc") == "ESCAPE"
    assert _normalize_key("ESC") == "ESCAPE"
    assert _normalize_key("del") == "DELETE"
    assert _normalize_key("vol_up") == "VOLUME_UP"


def test_normalize_key_unknown():
    with pytest.raises(ValueError, match="unknown key"):
        _normalize_key("ALT_F4")


# ---------------------------------------------------------------------------
# _render_flow — covers template loading + substitution
# ---------------------------------------------------------------------------


def test_render_flow_launch_app():
    rendered = _render_flow("launch_app", bundle_id="com.example.todo_verify")
    assert 'launchApp: "com.example.todo_verify"' in rendered
    assert 'appId: "*"' in rendered


def test_render_flow_tap_with_id_selector():
    selector = _selector_yaml(id="todo-card-1")
    rendered = _render_flow("tap", selector=selector)
    assert 'tapOn:' in rendered
    assert 'id: "todo-card-1"' in rendered


def test_render_flow_swipe():
    rendered = _render_flow("swipe", start="50%, 80%", end="50%, 20%")
    assert "start: 50%, 80%" in rendered
    assert "end: 50%, 20%" in rendered


def test_render_flow_press_key():
    rendered = _render_flow("press_key", key="BACK")
    assert "pressKey: BACK" in rendered


def test_render_flow_wait_for():
    selector = _selector_yaml(id="todo-detail-1")
    rendered = _render_flow("wait_for", selector=selector, timeout_ms="5000")
    assert "extendedWaitUntil:" in rendered
    assert 'id: "todo-detail-1"' in rendered
    assert "timeout: 5000" in rendered


def test_render_flow_assert_visible():
    selector = _selector_yaml(text="Buy groceries")
    rendered = _render_flow("assert_visible", selector=selector)
    assert "assertVisible:" in rendered
    assert 'text: "Buy groceries"' in rendered


def test_render_flow_input_text_escapes_quotes():
    rendered = _render_flow("input_text", text=_yaml_str('hello "world"'))
    # The substituted token already contains escaped quotes in JSON form
    assert 'inputText:' in rendered
    assert '\\"world\\"' in rendered
