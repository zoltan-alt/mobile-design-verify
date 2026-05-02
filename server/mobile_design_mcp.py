# Copyright 2026 zoltan-alt — Licensed under Apache-2.0. See LICENSE.

"""mobile-design-verify MCP server.

Stdio transport. Tools registered:
  ping (§2.1)            — connectivity check.
  screenshot (§2.3 #1)   — capture booted iOS Sim / Android emu.
  view_hierarchy (§2.3 #2) — pruned a11y / view tree of foreground app.

Maestro is the underlying driver (§2.2 `_run_maestro` shell-out helper).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
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


# ---------------------------------------------------------------------------
# §2.2 — Device selection + Maestro shell-out
# ---------------------------------------------------------------------------


def _booted_ios_devices() -> list[str]:
    """List of currently-Booted iOS Simulator UDIDs (empty if xcrun missing)."""
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
    """List of online Android device serials (excludes 'offline', 'unauthorized')."""
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
    for line in proc.stdout.splitlines()[1:]:  # skip "List of devices attached"
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _select_device_id(platform: Platform) -> str:
    """Pick the device-id to pass to Maestro.

    Resolution order:
      1. ``MOBILE_DESIGN_VERIFY_DEVICE_ID`` env var (always wins).
      2. Single booted iOS sim / online Android device.
      3. Hard-fail with full device list if 0 or >1 candidates.

    Never guesses silently.
    """
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


def _run_maestro(
    args: list[str], timeout: int = MAESTRO_DEFAULT_TIMEOUT_SEC
) -> dict[str, Any]:
    """Run the maestro CLI. Always returns a dict — never raises subprocess errors.

    Return shape:
      ``{"ok": bool, "error": str|None, "stdout": str, "stderr_tail": str, "exit": int}``
    """
    if not shutil.which("maestro"):
        return {
            "ok": False,
            "error": (
                "`maestro` not found on PATH. Install: "
                "https://maestro.mobile.dev/getting-started/installing-maestro"
            ),
            "stdout": "",
            "stderr_tail": "",
            "exit": -1,
        }
    try:
        proc = subprocess.run(
            ["maestro", *args],
            capture_output=True, text=True, timeout=timeout,
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
# View-hierarchy pruning (used by §2.3 #2)
# ---------------------------------------------------------------------------

_KEPT_KEYS = ("text", "resource-id", "accessibilityIdentifier", "bounds", "class")


def _prune_hierarchy(node: Any) -> Any:
    """Aggressively trim a Maestro hierarchy node.

    Keeps: text, resource-id / accessibilityIdentifier, bounds, class, children.
    Drops: subtrees with no text, no id, AND no surviving children.
    Non-dict input is passed through unchanged.
    """
    if not isinstance(node, dict):
        return node

    kept: dict[str, Any] = {
        k: node[k] for k in _KEPT_KEYS if node.get(k) not in (None, "")
    }

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
# §2.3 #1 — screenshot
# ---------------------------------------------------------------------------


def _ts() -> str:
    """ISO-8601 timestamp suitable for filenames (UTC, basic format, no colons)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _do_screenshot(platform: Platform) -> dict[str, Any]:
    try:
        device_id = _select_device_id(platform)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    out_dir = Path(SCREENSHOTS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (out_dir / f"{platform}-{_ts()}.png").resolve()

    result = _run_maestro(["--device", device_id, "screenshot", str(out_path)])
    if not result["ok"]:
        return {
            "ok": False,
            "error": result.get("error") or "screenshot failed",
            "stderr_tail": result.get("stderr_tail", ""),
        }
    return {"ok": True, "path": str(out_path)}


# ---------------------------------------------------------------------------
# §2.3 #2 — view_hierarchy
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# MCP server + tool registration
# ---------------------------------------------------------------------------

server: Server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="ping",
            description="No-op tool that confirms the server is reachable. Returns 'pong'.",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        Tool(
            name="screenshot",
            description=(
                "Capture a PNG screenshot of the currently-booted iOS Simulator or "
                "Android emulator. Returns the absolute file path on success."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "enum": ["ios", "android"],
                        "description": "Target platform.",
                    },
                },
                "required": ["platform"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="view_hierarchy",
            description=(
                "Read the accessibility / view hierarchy of the foreground app on the "
                "currently-booted iOS Simulator or Android emulator. Aggressively pruned "
                "to keep only text, resource-id / accessibilityIdentifier, bounds, class, "
                "and non-empty children — to keep model context small."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "enum": ["ios", "android"],
                    },
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

    if name == "screenshot":
        result = _do_screenshot(arguments["platform"])
    elif name == "view_hierarchy":
        result = _do_hierarchy(arguments["platform"])
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
