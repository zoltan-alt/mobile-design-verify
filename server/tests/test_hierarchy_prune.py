# Copyright 2026 zoltan-alt — Licensed under Apache-2.0. See LICENSE.

"""Unit tests for view-hierarchy pruning (no device required)."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the server package importable when tests are invoked from any cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mobile_design_mcp import _prune_hierarchy  # noqa: E402


def test_keeps_text_only_node():
    raw = {"text": "Save", "class": "Button", "bounds": "[0,0][100,50]"}
    assert _prune_hierarchy(raw) == {
        "text": "Save",
        "class": "Button",
        "bounds": "[0,0][100,50]",
    }


def test_keeps_node_with_resource_id():
    raw = {"resource-id": "todo-card-0", "class": "View"}
    assert _prune_hierarchy(raw) == {
        "resource-id": "todo-card-0",
        "class": "View",
    }


def test_keeps_node_with_accessibility_identifier():
    raw = {"accessibilityIdentifier": "todo-detail-1", "class": "ImageView"}
    assert _prune_hierarchy(raw) == {
        "accessibilityIdentifier": "todo-detail-1",
        "class": "ImageView",
    }


def test_drops_subtree_with_no_text_no_id_no_children():
    raw = {
        "class": "ContainerView",
        "children": [
            {"class": "Spacer"},
            {"class": "EmptyView", "children": []},
        ],
    }
    assert _prune_hierarchy(raw) is None


def test_keeps_branch_with_id_descendant():
    raw = {
        "class": "ScrollView",
        "children": [
            {
                "class": "VStack",
                "children": [
                    {"resource-id": "todo-step-row-0", "class": "Cell"},
                ],
            },
        ],
    }
    result = _prune_hierarchy(raw)
    assert result is not None
    assert result["class"] == "ScrollView"
    assert result["children"][0]["children"][0]["resource-id"] == "todo-step-row-0"


def test_drops_empty_string_values():
    raw = {"text": "", "resource-id": "", "class": "Empty"}
    assert _prune_hierarchy(raw) is None


def test_passes_through_non_dict_input():
    assert _prune_hierarchy("just a string") == "just a string"
    assert _prune_hierarchy(None) is None
    assert _prune_hierarchy([]) == []


def test_realistic_pruning_keeps_visible_text():
    """Mirrors the v1 smoke test: todo-card-0 must survive pruning."""
    raw = {
        "class": "Application",
        "children": [
            {
                "class": "ScrollView",
                "bounds": "[0,0][390,844]",
                "children": [
                    {"class": "DecorativeImage"},  # dropped
                    {
                        "accessibilityIdentifier": "todo-card-0",
                        "text": "Buy groceries",
                        "class": "Card",
                    },
                    {
                        "accessibilityIdentifier": "todo-card-1",
                        "text": "Reply to emails",
                        "class": "Card",
                    },
                ],
            },
        ],
    }
    result = _prune_hierarchy(raw)
    flat = repr(result)
    assert "todo-card-0" in flat
    assert "todo-card-1" in flat
    assert "DecorativeImage" not in flat


# ---------------------------------------------------------------------------
# Real Maestro hierarchy shape: properties wrapped in `attributes` sub-object
# ---------------------------------------------------------------------------


def test_keeps_attributes_wrapped_node():
    """Maestro's actual hierarchy wraps properties in an `attributes` dict."""
    raw = {
        "attributes": {
            "resource-id": "todo-card-0",
            "text": "Buy groceries",
            "class": "FrameLayout",
        },
        "children": [],
    }
    assert _prune_hierarchy(raw) == {
        "resource-id": "todo-card-0",
        "text": "Buy groceries",
        "class": "FrameLayout",
    }


def test_drops_attributes_wrapped_node_with_empty_text_and_id():
    """Empty-string text/id inside attributes is treated the same as missing."""
    raw = {
        "attributes": {"text": "", "resource-id": "", "class": "FrameLayout"},
        "children": [],
    }
    assert _prune_hierarchy(raw) is None


def test_keeps_attributes_branch_with_id_descendant():
    """Outer attributes-wrapped node empty; inner has resource-id — branch survives."""
    raw = {
        "attributes": {"text": "", "resource-id": "", "class": "RootView"},
        "children": [
            {
                "attributes": {"resource-id": "todo-step-row-0", "class": "Cell"},
                "children": [],
            },
        ],
    }
    result = _prune_hierarchy(raw)
    assert result is not None
    assert result["children"][0]["resource-id"] == "todo-step-row-0"
