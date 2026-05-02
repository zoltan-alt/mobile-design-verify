# Copyright 2026 zoltan-alt — Licensed under Apache-2.0. See LICENSE.

"""Unit tests for tool helpers (no device required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from mobile_design_mcp import (  # noqa: E402
    _do_playground_create,
    _find_widget_by_id,
    _normalize_key,
    _parse_bounds,
    _playground_root,
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
    # long: endpoints clamped to safe band 25-75% so the swipe doesn't land
    # on top app bars / bottom nav / sticky CTAs that would absorb the touch.
    assert start == "50%, 75%"
    assert end == "50%, 25%"


def test_scroll_coords_down_long():
    start, end = _scroll_coords("down", "long")
    assert start == "50%, 25%"
    assert end == "50%, 75%"


def test_scroll_coords_left_short():
    start, end = _scroll_coords("left", "short")
    assert start == "65%, 50%"
    assert end == "35%, 50%"


def test_scroll_coords_right_long():
    start, end = _scroll_coords("right", "long")
    assert start == "25%, 50%"
    assert end == "75%, 50%"


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


# ---------------------------------------------------------------------------
# _do_playground_create — validation + idempotency
# ---------------------------------------------------------------------------


def test_playground_create_rejects_invalid_name_uppercase():
    result = _do_playground_create(name="MyProject")
    assert result["ok"] is False
    assert "lowercase" in result["error"]


def test_playground_create_rejects_invalid_name_starts_with_digit():
    result = _do_playground_create(name="1sketch")
    assert result["ok"] is False


def test_playground_create_rejects_invalid_name_with_dash():
    result = _do_playground_create(name="my-sketch")
    assert result["ok"] is False


def test_playground_create_rejects_invalid_name_empty():
    result = _do_playground_create(name="")
    assert result["ok"] is False


def test_playground_create_idempotent_when_path_exists(tmp_path, monkeypatch):
    # Stub the playground root to a tmp path with a pre-existing project dir.
    fake_existing = tmp_path / "preexisting_sketch"
    fake_existing.mkdir()
    monkeypatch.setattr(
        "mobile_design_mcp._playground_root",
        lambda: tmp_path,
    )
    result = _do_playground_create(name="preexisting_sketch")
    assert result["ok"] is True
    assert result["exists"] is True
    assert result["path"] == str(fake_existing)
    assert result["name"] == "preexisting_sketch"


def test_playground_root_returns_path_under_temp(monkeypatch):
    monkeypatch.setenv("TEMP", r"C:\fake-temp")
    root = _playground_root()
    assert "mobile-design-playground" in str(root)


# ---------------------------------------------------------------------------
# _parse_bounds — Maestro's two formats
# ---------------------------------------------------------------------------


def test_parse_bounds_string_format():
    result = _parse_bounds("[10,20][110,220]")
    assert result == {"x": 10, "y": 20, "width": 100, "height": 200}


def test_parse_bounds_dict_format():
    result = _parse_bounds({"x": 5, "y": 8, "width": 50, "height": 60})
    assert result == {"x": 5, "y": 8, "width": 50, "height": 60}


def test_parse_bounds_invalid_string_returns_none():
    assert _parse_bounds("not bounds") is None


def test_parse_bounds_none_returns_none():
    assert _parse_bounds(None) is None


# ---------------------------------------------------------------------------
# _find_widget_by_id
# ---------------------------------------------------------------------------


def test_find_widget_by_id_root():
    tree = {"resource-id": "home-greeting", "bounds": "[0,0][1080,200]"}
    found = _find_widget_by_id(tree, "home-greeting")
    assert found is tree


def test_find_widget_by_id_recurses():
    tree = {
        "resource-id": "root",
        "children": [
            {"resource-id": "child-a"},
            {
                "resource-id": "child-b",
                "children": [{"resource-id": "grandchild"}],
            },
        ],
    }
    found = _find_widget_by_id(tree, "grandchild")
    assert found == {"resource-id": "grandchild"}


def test_find_widget_by_id_uses_accessibility_identifier_too():
    tree = {"accessibilityIdentifier": "ios-style-id"}
    found = _find_widget_by_id(tree, "ios-style-id")
    assert found is tree


def test_find_widget_by_id_returns_none_when_missing():
    tree = {"resource-id": "root", "children": [{"resource-id": "a"}]}
    assert _find_widget_by_id(tree, "nope") is None


def test_find_widget_by_id_handles_non_dict_input():
    assert _find_widget_by_id("not a dict", "anything") is None
    assert _find_widget_by_id(None, "anything") is None
