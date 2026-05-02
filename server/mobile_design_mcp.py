# Copyright 2026 zoltan-alt — Licensed under Apache-2.0. See LICENSE.

"""mobile-design-verify MCP server.

Stdio transport. Tools registered:
  ping            — connectivity check
  screenshot      — capture booted iOS sim / Android device
  view_hierarchy  — pruned a11y tree of the foreground app
  launch_app      — foreground an app by bundle id / applicationId
  kill_app        — stop / force-quit an app by bundle id
  tap             — tap by id, text, or point
  scroll          — directional scroll with short/long distance
  swipe           — coordinate-based swipe
  type_text       — input text into the focused field
  press_key       — press hardware/system key (BACK/HOME/ENTER/...)
  wait_for        — block until id/text becomes visible
  assert_visible  — assert id/text is visible right now

Underlying driver: Maestro (`_run_maestro`). Action tools render
`string.Template` flows from server/flows/*.yaml.tmpl and run via
`maestro test`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import string
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from config import (
    DEFAULT_ANDROID_AVD,
    DEFAULT_IOS_DEVICE,
    DEVICE_ID_ENV,
    MAESTRO_DEFAULT_TIMEOUT_SEC,
    SCREENSHOTS_DIR,
    SERVER_NAME,
)

Platform = Literal["ios", "android"]
_FLOWS_DIR = Path(__file__).parent / "flows"


# ---------------------------------------------------------------------------
# §2.2 — Device selection + Maestro shell-out
# ---------------------------------------------------------------------------


def _booted_ios_devices() -> list[str]:
    if not shutil.which("xcrun"):
        return []
    try:
        proc = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "booted", "-j"],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    udids: list[str] = []
    for runtime_devices in data.get("devices", {}).values():
        for d in runtime_devices:
            if d.get("state") == "Booted":
                udids.append(d["udid"])
    return udids


def _online_android_devices() -> list[str]:
    if not shutil.which("adb"):
        return []
    try:
        proc = subprocess.run(
            ["adb", "devices"],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return []
    if proc.returncode != 0:
        return []
    serials: list[str] = []
    for line in proc.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _select_device_id(platform: Platform) -> str:
    """Pick the device-id for Maestro. Never guesses silently."""
    explicit = os.environ.get(DEVICE_ID_ENV)
    if explicit:
        return explicit

    candidates = (
        _booted_ios_devices() if platform == "ios" else _online_android_devices()
    )
    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) == 0:
        suggested = (
            f'Boot one (e.g. "{DEFAULT_IOS_DEVICE}" simulator) and retry.'
            if platform == "ios"
            else f'Start the "{DEFAULT_ANDROID_AVD}" emulator (or any AVD) and retry.'
        )
        raise RuntimeError(
            f"No {platform} devices available. {suggested} "
            f"Or set {DEVICE_ID_ENV} to override."
        )

    raise RuntimeError(
        f"Multiple {platform} devices detected ({candidates}). "
        f"Set {DEVICE_ID_ENV} to one of these to disambiguate."
    )


def _find_maestro() -> str | None:
    """Find maestro: PATH first, then ~/.maestro/bin/maestro[.bat]."""
    on_path = shutil.which("maestro")
    if on_path:
        return on_path
    if os.name == "nt":
        bat = Path.home() / ".maestro" / "bin" / "maestro.bat"
        if bat.exists():
            return str(bat)
    fallback = Path.home() / ".maestro" / "bin" / "maestro"
    if fallback.exists():
        return str(fallback)
    return None


def _run_maestro(
    args: list[str],
    timeout: int = MAESTRO_DEFAULT_TIMEOUT_SEC,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Run maestro CLI. Always returns a dict — never raises subprocess errors."""
    maestro_exe = _find_maestro()
    if not maestro_exe:
        return {
            "ok": False,
            "error": (
                "`maestro` not found on PATH or at ~/.maestro/bin/. Install: "
                "https://maestro.mobile.dev/getting-started/installing-maestro"
            ),
            "stdout": "", "stderr_tail": "", "exit": -1,
        }
    try:
        proc = subprocess.run(
            [maestro_exe, *args],
            capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "error": f"maestro {' '.join(args)} timed out after {timeout}s",
            "stdout": (e.stdout or "")[-500:] if e.stdout else "",
            "stderr_tail": (e.stderr or "")[-500:] if e.stderr else "",
            "exit": -1,
        }
    return {
        "ok": proc.returncode == 0,
        "error": None if proc.returncode == 0 else f"maestro exited with code {proc.returncode}",
        "stdout": proc.stdout,
        "stderr_tail": proc.stderr[-500:],
        "exit": proc.returncode,
    }


# ---------------------------------------------------------------------------
# §2.5 — Flow rendering + execution helpers
# ---------------------------------------------------------------------------


def _ts() -> str:
    """ISO-8601 timestamp with microseconds for unique filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _yaml_str(s: str) -> str:
    """Quote a string for safe YAML embedding (JSON string syntax)."""
    return json.dumps(s)


def _selector_yaml(*, id: str | None = None, text: str | None = None) -> str | None:
    """Build a Maestro selector fragment. Returns None if neither is provided."""
    if id is not None:
        return f"id: {_yaml_str(id)}"
    if text is not None:
        return f"text: {_yaml_str(text)}"
    return None


def _render_flow(template_name: str, **kwargs: str) -> str:
    """Render server/flows/<template_name>.yaml.tmpl with substitutions."""
    path = _FLOWS_DIR / f"{template_name}.yaml.tmpl"
    template = string.Template(path.read_text(encoding="utf-8"))
    return template.substitute(**kwargs)


def _run_flow(
    platform: Platform,
    flow_yaml: str,
    timeout: int = MAESTRO_DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Write a YAML flow to a temp file and run it via `maestro test`."""
    try:
        device_id = _select_device_id(platform)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    tmp_dir = Path(SCREENSHOTS_DIR).resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    flow_path = tmp_dir / f"_flow_{_ts()}.yaml"
    flow_path.write_text(flow_yaml, encoding="utf-8")

    try:
        result = _run_maestro(
            ["--device", device_id, "test", str(flow_path)],
            cwd=str(tmp_dir),
            timeout=timeout,
        )
    finally:
        flow_path.unlink(missing_ok=True)

    if not result["ok"]:
        return {
            "ok": False,
            "error": result.get("error") or "flow failed",
            "stderr_tail": result.get("stderr_tail", ""),
        }
    return {"ok": True}


# ---------------------------------------------------------------------------
# View-hierarchy pruning (used by view_hierarchy)
# ---------------------------------------------------------------------------

_KEPT_KEYS = ("text", "resource-id", "accessibilityIdentifier", "bounds", "class")


def _prune_hierarchy(node: Any) -> Any:
    """Aggressively trim a Maestro hierarchy node (handles `attributes` wrapper)."""
    if not isinstance(node, dict):
        return node

    attrs = node.get("attributes") if isinstance(node.get("attributes"), dict) else None
    source = attrs if attrs is not None else node

    kept: dict[str, Any] = {}
    for k in _KEPT_KEYS:
        v = source.get(k)
        if v not in (None, ""):
            kept[k] = v
    if attrs is not None:
        for k in _KEPT_KEYS:
            if k not in kept and node.get(k) not in (None, ""):
                kept[k] = node[k]

    children_in = node.get("children") or []
    children_out: list[Any] = []
    for child in children_in:
        pruned = _prune_hierarchy(child)
        if pruned is not None:
            children_out.append(pruned)

    has_id = "resource-id" in kept or "accessibilityIdentifier" in kept
    has_text = "text" in kept
    if not has_id and not has_text and not children_out:
        return None

    if children_out:
        kept["children"] = children_out
    return kept


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _do_screenshot(platform: Platform) -> dict[str, Any]:
    """Capture PNG via `takeScreenshot:` flow (saved to tmp/screenshots/)."""
    try:
        device_id = _select_device_id(platform)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    out_dir = Path(SCREENSHOTS_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{platform}-{_ts()}"
    flow_path = out_dir / f"_flow_{base}.yaml"
    expected_png = out_dir / f"{base}.png"

    flow_path.write_text(
        f'appId: "*"\n'
        f'---\n'
        f'- takeScreenshot: {base}\n'
    )

    try:
        result = _run_maestro(
            ["--device", device_id, "test", str(flow_path)],
            cwd=str(out_dir),
        )
    finally:
        flow_path.unlink(missing_ok=True)

    if not result["ok"]:
        return {
            "ok": False,
            "error": result.get("error") or "screenshot flow failed",
            "stderr_tail": result.get("stderr_tail", ""),
        }
    if not expected_png.exists():
        return {
            "ok": False,
            "error": f"flow ran but screenshot not found at {expected_png}",
            "stderr_tail": result.get("stderr_tail", ""),
        }
    return {"ok": True, "path": str(expected_png)}


def _do_hierarchy(platform: Platform) -> dict[str, Any]:
    try:
        device_id = _select_device_id(platform)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    result = _run_maestro(["--device", device_id, "hierarchy"])
    if not result["ok"]:
        return {
            "ok": False,
            "error": result.get("error") or "hierarchy failed",
            "stderr_tail": result.get("stderr_tail", ""),
        }
    try:
        raw = json.loads(result["stdout"])
    except json.JSONDecodeError as e:
        return {
            "ok": False,
            "error": f"Maestro returned non-JSON hierarchy: {e}",
            "stderr_tail": result.get("stderr_tail", ""),
        }
    return {"ok": True, "hierarchy": _prune_hierarchy(raw)}


def _do_launch_app(platform: Platform, bundle_id: str) -> dict[str, Any]:
    flow = _render_flow("launch_app", bundle_id=bundle_id)
    return _run_flow(platform, flow)


def _do_kill_app(platform: Platform, bundle_id: str) -> dict[str, Any]:
    flow = _render_flow("kill_app", bundle_id=bundle_id)
    return _run_flow(platform, flow)


def _do_tap(
    platform: Platform,
    id: str | None = None,
    text: str | None = None,
    point: str | None = None,
) -> dict[str, Any]:
    if id is not None:
        selector = f"id: {_yaml_str(id)}"
    elif text is not None:
        selector = f"text: {_yaml_str(text)}"
    elif point is not None:
        selector = f"point: {_yaml_str(point)}"
    else:
        return {"ok": False, "error": "tap requires one of: id, text, point"}
    flow = _render_flow("tap", selector=selector)
    return _run_flow(platform, flow)


def _scroll_coords(direction: str, distance: str) -> tuple[str, str]:
    """Compute (start, end) percentage coordinates for a directional scroll.

    Endpoints stay inside a safe band (25-75%) so the gesture doesn't land on
    fixed top app bars, bottom navigation bars, or sticky CTA buttons that
    would otherwise absorb the touch instead of scrolling the content.

    direction: "up" / "down" / "left" / "right" (finger movement)
    distance:  "short" (~30% travel) or "long" (~50% travel)
    """
    if distance == "short":
        near, far = 65, 35
    elif distance == "long":
        near, far = 75, 25
    else:
        raise ValueError(f"distance must be 'short' or 'long' (got {distance!r})")
    mid = 50

    direction = direction.lower()
    if direction == "up":
        return f"{mid}%, {near}%", f"{mid}%, {far}%"
    if direction == "down":
        return f"{mid}%, {far}%", f"{mid}%, {near}%"
    if direction == "left":
        return f"{near}%, {mid}%", f"{far}%, {mid}%"
    if direction == "right":
        return f"{far}%, {mid}%", f"{near}%, {mid}%"
    raise ValueError(f"direction must be up/down/left/right (got {direction!r})")


def _do_scroll(
    platform: Platform,
    direction: str = "down",
    distance: str = "short",
) -> dict[str, Any]:
    try:
        start, end = _scroll_coords(direction, distance)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    flow = _render_flow("swipe", start=start, end=end)
    return _run_flow(platform, flow)


def _do_swipe(platform: Platform, start: str, end: str) -> dict[str, Any]:
    flow = _render_flow("swipe", start=start, end=end)
    return _run_flow(platform, flow)


def _do_type_text(platform: Platform, text: str) -> dict[str, Any]:
    flow = _render_flow("input_text", text=_yaml_str(text))
    return _run_flow(platform, flow)


_KEY_MAP = {
    "back": "BACK",
    "home": "HOME",
    "enter": "ENTER",
    "esc": "ESCAPE",
    "escape": "ESCAPE",
    "tab": "TAB",
    "delete": "DELETE",
    "del": "DELETE",
    "backspace": "BACKSPACE",
    "vol_up": "VOLUME_UP",
    "vol_down": "VOLUME_DOWN",
    "volume_up": "VOLUME_UP",
    "volume_down": "VOLUME_DOWN",
}


def _normalize_key(key: str) -> str:
    """Normalize a user-friendly key name to a Maestro pressKey value."""
    upper = key.upper()
    if upper in set(_KEY_MAP.values()):
        return upper
    mapped = _KEY_MAP.get(key.lower())
    if mapped:
        return mapped
    raise ValueError(
        f"unknown key: {key!r}. Known: {', '.join(sorted(set(_KEY_MAP.values())))}"
    )


def _do_press_key(platform: Platform, key: str) -> dict[str, Any]:
    try:
        normalized = _normalize_key(key)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    flow = _render_flow("press_key", key=normalized)
    return _run_flow(platform, flow)


def _do_wait_for(
    platform: Platform,
    id: str | None = None,
    text: str | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    selector = _selector_yaml(id=id, text=text)
    if selector is None:
        return {"ok": False, "error": "wait_for requires one of: id, text"}
    flow = _render_flow("wait_for", selector=selector, timeout_ms=str(timeout * 1000))
    # Give the maestro process a buffer beyond the in-flow wait
    return _run_flow(platform, flow, timeout=timeout + 30)


def _do_assert_visible(
    platform: Platform,
    id: str | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    selector = _selector_yaml(id=id, text=text)
    if selector is None:
        return {"ok": False, "error": "assert_visible requires one of: id, text"}
    flow = _render_flow("assert_visible", selector=selector)
    return _run_flow(platform, flow)


def _do_screenshot_scrolling(
    platform: Platform,
    count: int = 3,
) -> dict[str, Any]:
    """Take ``count`` screenshots while scrolling down to capture tall content.

    Each iteration: take a screenshot at the current scroll position, then
    swipe upward by ~70% of viewport (finger movement up = content scrolls up,
    revealing what's below) before the next capture. If the screen has fewer
    pages of content than ``count``, trailing screenshots may show the same
    view (already at the bottom). Leaves the screen at its final scroll
    position; call ``scroll(direction="down", distance="long")`` to return.

    Returns ``{"ok": True, "paths": [...]}`` with paths in top-to-bottom order.
    """
    if count < 1:
        return {"ok": False, "error": "count must be >= 1"}

    paths: list[str] = []
    for i in range(count):
        if i > 0:
            scroll_result = _do_scroll(platform, direction="up", distance="long")
            if not scroll_result["ok"]:
                return {
                    "ok": False,
                    "error": f"scroll between captures {i - 1} and {i} failed: "
                             f"{scroll_result.get('error')}",
                    "paths_captured": paths,
                }
        shot = _do_screenshot(platform)
        if not shot["ok"]:
            return {
                "ok": False,
                "error": f"screenshot {i} failed: {shot.get('error')}",
                "paths_captured": paths,
            }
        paths.append(shot["path"])
    return {"ok": True, "paths": paths}


# ---------------------------------------------------------------------------
# MCP server + tool registration
# ---------------------------------------------------------------------------

server: Server = Server(SERVER_NAME)


def _platform_prop(description: str = "Target platform.") -> dict[str, Any]:
    return {"type": "string", "enum": ["ios", "android"], "description": description}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="ping",
            description="No-op tool that confirms the server is reachable. Returns 'pong'.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="screenshot",
            description=(
                "Capture a PNG screenshot of the currently-booted iOS Simulator or "
                "Android device. Returns the absolute file path on success."
            ),
            inputSchema={
                "type": "object",
                "properties": {"platform": _platform_prop()},
                "required": ["platform"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="view_hierarchy",
            description=(
                "Read the accessibility / view hierarchy of the foreground app. "
                "Aggressively pruned — keeps only text, resource-id / "
                "accessibilityIdentifier, bounds, class, non-empty children."
            ),
            inputSchema={
                "type": "object",
                "properties": {"platform": _platform_prop()},
                "required": ["platform"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="screenshot_scrolling",
            description=(
                "Capture multiple PNG screenshots while scrolling down, to "
                "cover content taller than a single viewport. Returns an "
                "ordered list of file paths (top -> bottom). Use when a single "
                "`screenshot` would miss content below the fold. Leaves the "
                "screen at the final scroll position."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "count": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 3,
                        "description": "Number of screenshots to take.",
                    },
                },
                "required": ["platform"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="launch_app",
            description="Launch (foreground) an app by its bundle id / Android applicationId.",
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "bundle_id": {
                        "type": "string",
                        "description": "Android applicationId or iOS CFBundleIdentifier.",
                    },
                },
                "required": ["platform", "bundle_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="kill_app",
            description="Stop / force-quit an app by its bundle id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "bundle_id": {"type": "string"},
                },
                "required": ["platform", "bundle_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="tap",
            description=(
                "Tap on an element. Provide exactly one of: id (preferred), text, or "
                "point (\"x,y\" coordinates). Precedence: id > text > point."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "id": {"type": "string", "description": "Accessibility identifier or resource-id."},
                    "text": {"type": "string", "description": "Visible text content."},
                    "point": {"type": "string", "description": "Coordinates as \"x,y\" (pixels)."},
                },
                "required": ["platform"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="scroll",
            description=(
                "Directional scroll on the foreground screen. distance \"short\" is ~30% "
                "of the screen, \"long\" is ~70%. direction is finger-movement direction."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                        "description": "Finger-movement direction.",
                    },
                    "distance": {
                        "type": "string",
                        "enum": ["short", "long"],
                        "default": "short",
                    },
                },
                "required": ["platform", "direction"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="swipe",
            description=(
                "Coordinate-based swipe. start and end are \"X%, Y%\" or \"X, Y\" "
                "strings (e.g. \"50%, 80%\")."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
                "required": ["platform", "start", "end"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="type_text",
            description="Input text into the currently-focused field.",
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "text": {"type": "string"},
                },
                "required": ["platform", "text"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="press_key",
            description=(
                "Press a hardware/system key. Accepts BACK, HOME, ENTER, ESCAPE, TAB, "
                "DELETE, BACKSPACE, VOLUME_UP, VOLUME_DOWN (case-insensitive; "
                "synonyms: esc, del, vol_up, vol_down)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "key": {"type": "string"},
                },
                "required": ["platform", "key"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="wait_for",
            description=(
                "Wait until an element with the given id or text becomes visible. "
                "timeout is in seconds (default 10)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "timeout": {"type": "integer", "minimum": 1, "default": 10},
                },
                "required": ["platform"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="assert_visible",
            description="Assert an element with the given id or text is currently visible.",
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["platform"],
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "ping":
        return [TextContent(type="text", text="pong")]

    p: Platform = arguments["platform"]

    if name == "screenshot":
        result = _do_screenshot(p)
    elif name == "view_hierarchy":
        result = _do_hierarchy(p)
    elif name == "screenshot_scrolling":
        result = _do_screenshot_scrolling(
            p,
            count=arguments.get("count", 3),
        )
    elif name == "launch_app":
        result = _do_launch_app(p, arguments["bundle_id"])
    elif name == "kill_app":
        result = _do_kill_app(p, arguments["bundle_id"])
    elif name == "tap":
        result = _do_tap(
            p,
            id=arguments.get("id"),
            text=arguments.get("text"),
            point=arguments.get("point"),
        )
    elif name == "scroll":
        result = _do_scroll(
            p,
            direction=arguments["direction"],
            distance=arguments.get("distance", "short"),
        )
    elif name == "swipe":
        result = _do_swipe(p, start=arguments["start"], end=arguments["end"])
    elif name == "type_text":
        result = _do_type_text(p, arguments["text"])
    elif name == "press_key":
        result = _do_press_key(p, arguments["key"])
    elif name == "wait_for":
        result = _do_wait_for(
            p,
            id=arguments.get("id"),
            text=arguments.get("text"),
            timeout=arguments.get("timeout", 10),
        )
    elif name == "assert_visible":
        result = _do_assert_visible(
            p,
            id=arguments.get("id"),
            text=arguments.get("text"),
        )
    else:
        raise ValueError(f"Unknown tool: {name}")

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _run() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
