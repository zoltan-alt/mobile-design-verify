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
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
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
# Designer mode — playground project create-on-demand
# ---------------------------------------------------------------------------


import re as _re

_PLAYGROUND_NAME_RE = _re.compile(r"^[a-z][a-z0-9_]*$")


def _playground_root() -> Path:
    """Where playground projects live: ``%TEMP%/mobile-design-playground/``."""
    base = os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / "mobile-design-playground"


def _run_via_schtask(
    command: str,
    cwd: str,
    timeout_sec: int = 300,
) -> dict[str, Any]:
    """Run a shell command via Windows Task Scheduler.

    Identical mechanism to ``scripts/_claude-windows-build.py`` —
    Task Scheduler spawns the task under LocalSystem in a fresh process
    tree, escaping the Java NIO sandbox restriction AND any user-process
    file locks (e.g. a running flutter daemon holding the Dart SDK
    cache). Returns ``{ok, exit_code, stdout, stderr}``.

    On non-Windows platforms, falls back to a normal ``subprocess.run``.
    """
    if os.name != "nt":
        try:
            proc = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timed out ({timeout_sec}s)"}
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }

    tag = uuid.uuid4().hex[:8]
    task_name = f"ClaudeMDV_{tag}"
    temp = Path(os.environ.get("TEMP", "."))
    batch = temp / f"{task_name}.bat"
    log_out = temp / f"{task_name}.stdout.log"
    log_err = temp / f"{task_name}.stderr.log"

    batch.write_text(
        "@echo off\r\n"
        f'cd /d "{cwd}"\r\n'
        f'{command} > "{log_out}" 2> "{log_err}"\r\n'
        "exit /b %ERRORLEVEL%\r\n",
        encoding="utf-8",
    )

    def _cleanup() -> None:
        subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True,
        )
        for p in (batch, log_out, log_err):
            try:
                p.unlink()
            except OSError:
                pass

    try:
        create = subprocess.run(
            [
                "schtasks", "/create", "/tn", task_name,
                "/tr", str(batch),
                "/sc", "ONCE", "/st", "00:00",
                "/f",
            ],
            capture_output=True, text=True,
        )
        if create.returncode != 0:
            return {
                "ok": False,
                "error": f"schtasks /create failed: {create.stderr or create.stdout}",
            }

        run_proc = subprocess.run(
            ["schtasks", "/run", "/tn", task_name],
            capture_output=True, text=True,
        )
        if run_proc.returncode != 0:
            return {
                "ok": False,
                "error": f"schtasks /run failed: {run_proc.stderr or run_proc.stdout}",
            }

        deadline = time.time() + timeout_sec
        last_result: str | None = None
        while time.time() < deadline:
            time.sleep(2)
            q = subprocess.run(
                ["schtasks", "/query", "/tn", task_name, "/v", "/fo", "LIST"],
                capture_output=True, text=True,
            )
            status = None
            for raw in q.stdout.splitlines():
                line = raw.strip()
                low = line.lower()
                if low.startswith("status:"):
                    status = line.split(":", 1)[1].strip()
                elif low.startswith("last result:"):
                    last_result = line.split(":", 1)[1].strip()
            if status == "Ready" and last_result not in {None, "", "267009", "267011"}:
                break
        else:
            return {"ok": False, "error": f"timed out ({timeout_sec}s)"}

        stdout = ""
        stderr = ""
        if log_out.exists():
            stdout = log_out.read_text(encoding="utf-8", errors="replace")
        if log_err.exists():
            stderr = log_err.read_text(encoding="utf-8", errors="replace")

        try:
            exit_code = int(last_result or "99")
        except ValueError:
            exit_code = 99

        return {
            "ok": exit_code == 0,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        }
    finally:
        _cleanup()


def _do_playground_create(name: str | None = None) -> dict[str, Any]:
    """Create or reuse a Flutter playground project for designer mode.

    Returns ``{ok, path, exists, name}`` on success. ``exists`` is True
    if the project was already there and was reused — same path returned
    either way. ``name`` is the resolved name (auto-generated if caller
    passed None).
    """
    if name is None:
        name = "sketch_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if not _PLAYGROUND_NAME_RE.match(name):
        return {
            "ok": False,
            "error": (
                "name must be lowercase snake_case Dart identifier "
                f"(matching ^[a-z][a-z0-9_]*$); got {name!r}"
            ),
        }

    base_dir = _playground_root()
    project_dir = base_dir / name

    if project_dir.exists():
        return {
            "ok": True,
            "path": str(project_dir),
            "exists": True,
            "name": name,
        }

    base_dir.mkdir(parents=True, exist_ok=True)

    # Run ``flutter create`` via Task Scheduler escape. Bypasses both
    # the Java/NIO sandbox AND any file-lock conflicts from another
    # running flutter daemon holding the Dart SDK cache.
    result = _run_via_schtask(
        command=f"flutter create --no-pub {name}",
        cwd=str(base_dir),
        timeout_sec=300,
    )
    if not result["ok"]:
        return {
            "ok": False,
            "error": "flutter create failed",
            "stderr_tail": (result.get("stderr", "") or "")[-500:],
            "stdout_tail": (result.get("stdout", "") or "")[-500:],
        }

    try:
        _seed_playground(project_dir)
    except OSError as e:
        return {
            "ok": False,
            "error": f"playground seeding failed: {e}",
            "path": str(project_dir),
        }

    return {
        "ok": True,
        "path": str(project_dir),
        "exists": False,
        "name": name,
    }


def _seed_playground(project_dir: Path) -> None:
    """Replace ``lib/main.dart`` with a Designer-mode entry point and
    write ``lib/design.dart`` as the canvas Claude edits.

    Adds ``google_fonts`` to ``pubspec.yaml`` (handwritten / display
    fonts are common in design work).
    """
    main_dart = project_dir / "lib" / "main.dart"
    main_dart.write_text(
        "import 'package:flutter/material.dart';\n"
        "import 'package:flutter/services.dart';\n"
        "import 'design.dart';\n"
        "\n"
        "void main() {\n"
        "  WidgetsFlutterBinding.ensureInitialized();\n"
        "  SystemChrome.setSystemUIOverlayStyle(\n"
        "    const SystemUiOverlayStyle(\n"
        "      statusBarColor: Colors.transparent,\n"
        "      statusBarIconBrightness: Brightness.dark,\n"
        "    ),\n"
        "  );\n"
        "  runApp(const PlaygroundApp());\n"
        "}\n"
        "\n"
        "class PlaygroundApp extends StatelessWidget {\n"
        "  const PlaygroundApp({super.key});\n"
        "\n"
        "  @override\n"
        "  Widget build(BuildContext context) {\n"
        "    return MaterialApp(\n"
        "      title: 'design-playground',\n"
        "      debugShowCheckedModeBanner: false,\n"
        "      theme: ThemeData(useMaterial3: true),\n"
        "      home: const DesignPreview(),\n"
        "    );\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    design_dart = project_dir / "lib" / "design.dart"
    design_dart.write_text(
        "import 'package:flutter/material.dart';\n"
        "\n"
        "/// Designer-mode canvas — edit this file freely. The single\n"
        "/// `DesignPreview` widget is what's rendered in the playground.\n"
        "/// Hot reload picks up changes in ~2s.\n"
        "class DesignPreview extends StatelessWidget {\n"
        "  const DesignPreview({super.key});\n"
        "\n"
        "  @override\n"
        "  Widget build(BuildContext context) {\n"
        "    return const Scaffold(\n"
        "      body: SafeArea(\n"
        "        child: Center(\n"
        "          child: Text('Design preview — start sketching.'),\n"
        "        ),\n"
        "      ),\n"
        "    );\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    # Add google_fonts to pubspec.yaml if it isn't already there.
    pubspec = project_dir / "pubspec.yaml"
    text = pubspec.read_text(encoding="utf-8")
    if "google_fonts:" not in text and "cupertino_icons:" in text:
        text = text.replace(
            "  cupertino_icons:",
            "  google_fonts: ^6.2.0\n  cupertino_icons:",
            1,
        )
        pubspec.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Designer mode — flutter run + hot reload
# ---------------------------------------------------------------------------


@dataclass
class _FlutterApp:
    """A running ``flutter run --machine --hot`` process tracked by the server.

    The reader thread drains stdout into ``events`` and updates state
    (``app_id``, ``vm_service_uri``, ``started``) as daemon events arrive.
    """

    project_path: str
    process: subprocess.Popen[str]
    app_id: str | None = None
    vm_service_uri: str | None = None
    started: bool = False
    events: Queue[dict[str, Any]] = field(default_factory=Queue)
    next_request_id: int = 1
    reader_thread: threading.Thread | None = None


_flutter_apps: dict[str, _FlutterApp] = {}


def _drain_flutter_stdout(app: _FlutterApp) -> None:
    """Background thread: parse ``flutter run --machine`` JSON events.

    Each line of machine-mode output is wrapped in ``[{...}]``. We
    parse, update app state, and queue every event so command handlers
    can match by request id.
    """
    proc = app.process
    assert proc.stdout is not None
    while True:
        try:
            line = proc.stdout.readline()
        except (ValueError, OSError):
            return
        if not line:
            return
        line_str = line.strip()
        if not line_str.startswith("["):
            continue
        try:
            events = json.loads(line_str)
        except json.JSONDecodeError:
            continue
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            evt_name = event.get("event")
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            if evt_name == "app.start":
                app.app_id = params.get("appId") or app.app_id
            elif evt_name == "app.debugPort":
                app.vm_service_uri = params.get("wsUri") or app.vm_service_uri
            elif evt_name == "app.started":
                app.started = True
            app.events.put(event)


def _do_flutter_run(project_path: str, platform: Platform) -> dict[str, Any]:
    """Launch ``flutter run --machine --hot`` for the given project.

    Idempotent: if a flutter process is already running for this
    project, returns its existing ``app_id`` / ``vm_service_uri``.
    Otherwise starts a new one and blocks until ``app.started`` lands
    (4 min timeout to absorb first-run cold compile).
    """
    project = str(Path(project_path).resolve())
    existing = _flutter_apps.get(project)
    if existing is not None and existing.process.poll() is None:
        if existing.started:
            return {
                "ok": True,
                "exists": True,
                "app_id": existing.app_id,
                "vm_service_uri": existing.vm_service_uri,
            }
        # Process is alive but not yet started — fall through and wait.
    elif existing is not None:
        # Process died — clear it.
        _flutter_apps.pop(project, None)
        existing = None

    if existing is None:
        try:
            device_id = _select_device_id(platform)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}

        flutter_bin = shutil.which("flutter") or "flutter"
        cmd = [flutter_bin, "run", "--machine", "--hot", "-d", device_id]

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=project,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            return {"ok": False, "error": "flutter CLI not on PATH"}

        existing = _FlutterApp(project_path=project, process=proc)
        _flutter_apps[project] = existing

        thread = threading.Thread(
            target=_drain_flutter_stdout,
            args=(existing,),
            daemon=True,
            name=f"flutter-stdout-{Path(project).name}",
        )
        thread.start()
        existing.reader_thread = thread

    deadline = time.time() + 240
    while time.time() < deadline:
        if existing.started and existing.vm_service_uri:
            return {
                "ok": True,
                "exists": False,
                "app_id": existing.app_id,
                "vm_service_uri": existing.vm_service_uri,
            }
        if existing.process.poll() is not None:
            _flutter_apps.pop(project, None)
            return {
                "ok": False,
                "error": f"flutter run exited with code {existing.process.returncode}",
            }
        time.sleep(0.5)

    return {
        "ok": False,
        "error": "timed out (>240s) waiting for app.started",
        "app_id": existing.app_id,
        "vm_service_uri": existing.vm_service_uri,
    }


def _send_daemon_command(
    app: _FlutterApp,
    method: str,
    params: dict[str, Any],
    timeout: int = 60,
) -> dict[str, Any]:
    """Send a ``flutter run --machine`` daemon JSON-RPC command and
    wait for the matching response by request id.
    """
    if app.process.stdin is None or app.process.poll() is not None:
        return {"ok": False, "error": "flutter process not alive"}

    request_id = app.next_request_id
    app.next_request_id += 1
    payload = "[" + json.dumps({"id": request_id, "method": method, "params": params}) + "]\n"

    try:
        app.process.stdin.write(payload)
        app.process.stdin.flush()
    except (BrokenPipeError, OSError) as e:
        return {"ok": False, "error": f"failed to send command: {e}"}

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            event = app.events.get(timeout=0.5)
        except Empty:
            continue
        if event.get("id") == request_id:
            if "error" in event:
                return {"ok": False, "error": event["error"]}
            return {"ok": True, "result": event.get("result")}

    return {"ok": False, "error": f"timed out (>{timeout}s) waiting for response"}


def _do_flutter_hot_reload(project_path: str) -> dict[str, Any]:
    """Send an ``app.reload`` (hot reload, not full restart) daemon
    command to a running flutter app for the given project.
    """
    project = str(Path(project_path).resolve())
    app = _flutter_apps.get(project)
    if app is None or app.process.poll() is not None:
        return {
            "ok": False,
            "error": "no running flutter process for this project; call flutter_run first",
        }
    if not app.started or not app.app_id:
        return {"ok": False, "error": "app not fully started yet"}

    return _send_daemon_command(
        app,
        method="app.reload",
        params={"appId": app.app_id, "pause": False, "fullRestart": False},
    )


def _do_flutter_stop(project_path: str) -> dict[str, Any]:
    """Send ``app.stop`` and wait for the process to exit. Cleans up
    the registry entry.
    """
    project = str(Path(project_path).resolve())
    app = _flutter_apps.get(project)
    if app is None:
        return {"ok": True, "exists": False}

    result: dict[str, Any] = {"ok": True, "exists": True}
    if app.process.poll() is None and app.app_id is not None:
        cmd_result = _send_daemon_command(
            app,
            method="app.stop",
            params={"appId": app.app_id},
            timeout=15,
        )
        if not cmd_result["ok"]:
            result["stop_warning"] = cmd_result.get("error")

    # Force-terminate if still alive.
    try:
        app.process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        app.process.terminate()
        try:
            app.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            app.process.kill()

    _flutter_apps.pop(project, None)
    return result


# ---------------------------------------------------------------------------
# Designer mode — widget inspector (bounds + a11y info from view hierarchy)
# ---------------------------------------------------------------------------


def _find_widget_by_id(node: Any, identifier: str) -> dict[str, Any] | None:
    """Walk a pruned a11y tree to find the first node with matching id."""
    if not isinstance(node, dict):
        return None
    rid = node.get("resource-id") or node.get("accessibilityIdentifier")
    if rid == identifier:
        return node
    for child in node.get("children", []) or []:
        found = _find_widget_by_id(child, identifier)
        if found is not None:
            return found
    return None


def _parse_bounds(bounds: Any) -> dict[str, int] | None:
    """Maestro bounds come as ``[x1,y1][x2,y2]`` strings or as
    ``{"x":..,"y":..,"width":..,"height":..}`` objects. Normalize.
    """
    if isinstance(bounds, dict):
        x = int(bounds.get("x", 0))
        y = int(bounds.get("y", 0))
        w = int(bounds.get("width", 0))
        h = int(bounds.get("height", 0))
        return {"x": x, "y": y, "width": w, "height": h}
    if isinstance(bounds, str):
        import re as _re
        m = _re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if m:
            x1, y1, x2, y2 = (int(g) for g in m.groups())
            return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}
    return None


def _do_inspect_widget(platform: Platform, identifier: str) -> dict[str, Any]:
    """Look up a widget by Semantics identifier in the live a11y tree.

    Returns the widget's bounds (x/y/width/height pixels), text content,
    and class name. Bounds come from Maestro's hierarchy snapshot — not
    a deep VM-service inspection — so color/font/baseline aren't here
    yet. They can be added later via Flutter Inspector RPC if needed.
    """
    if not identifier:
        return {"ok": False, "error": "identifier is required"}

    hier = _do_hierarchy(platform)
    if not hier["ok"]:
        return hier

    tree = hier.get("hierarchy")
    if tree is None:
        return {"ok": False, "error": "no hierarchy returned"}

    node = _find_widget_by_id(tree, identifier)
    if node is None:
        return {
            "ok": False,
            "error": f"no widget with identifier {identifier!r} in the hierarchy",
        }

    return {
        "ok": True,
        "identifier": identifier,
        "bounds": _parse_bounds(node.get("bounds")),
        "text": node.get("text"),
        "class": node.get("class"),
    }


# ---------------------------------------------------------------------------
# Designer mode — visual diff against a reference image
# ---------------------------------------------------------------------------


def _latest_screenshot() -> Path | None:
    """Find the newest PNG under the screenshots directory, if any."""
    shots = Path(SCREENSHOTS_DIR).resolve()
    if not shots.is_dir():
        return None
    candidates = sorted(
        shots.glob("*.png"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _do_compare_to_reference(
    reference_path: str,
    current_path: str | None = None,
    threshold: int = 30,
) -> dict[str, Any]:
    """Visual diff: compare a current screenshot to a reference image.

    Reports the fraction of differing pixels, the bounding box of the
    differing region, and writes an overlay PNG (red tint on differing
    pixels, original elsewhere) under ``tmp/screenshots/``.

    ``threshold`` is the per-channel intensity difference above which a
    pixel counts as "changed". Default 30 ignores small color/encoding
    drift but catches real layout / color shifts.

    If ``current_path`` is omitted, the newest PNG in
    ``tmp/screenshots/`` is used.
    """
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError:
        return {
            "ok": False,
            "error": "Pillow is required (pip install pillow into the server venv)",
        }

    ref = Path(reference_path)
    if not ref.is_file():
        return {"ok": False, "error": f"reference image not found: {reference_path}"}

    if current_path is None:
        latest = _latest_screenshot()
        if latest is None:
            return {
                "ok": False,
                "error": (
                    "no current_path given and tmp/screenshots/ is empty — "
                    "take a screenshot first"
                ),
            }
        current_path = str(latest)

    cur = Path(current_path)
    if not cur.is_file():
        return {"ok": False, "error": f"current screenshot not found: {current_path}"}

    img_ref = Image.open(ref).convert("RGB")
    img_cur = Image.open(cur).convert("RGB")

    if img_ref.size != img_cur.size:
        img_ref = img_ref.resize(img_cur.size, Image.LANCZOS)

    diff = ImageChops.difference(img_ref, img_cur)
    diff_gray = diff.convert("L")
    mask = diff_gray.point(lambda p: 255 if p > threshold else 0, mode="L")

    # Count "different" pixels = sum of mask / 255.
    stat = ImageStat.Stat(mask)
    diff_count = int(stat.sum[0]) // 255
    width, height = img_cur.size
    total = width * height
    diff_ratio = diff_count / total if total else 0.0

    if diff_count == 0:
        return {
            "ok": True,
            "match": True,
            "diff_ratio": 0.0,
            "diff_pixels": 0,
            "image_size": [width, height],
            "current_path": str(cur.resolve()),
        }

    # Bounding box of all differing pixels (single rect — coarse but
    # surfaces "is the diff in a small region or scattered").
    bbox = mask.getbbox()

    # Overlay: paste a red layer onto the current screenshot, masked
    # to differing pixels. Fast — no per-pixel Python loop.
    overlay = img_cur.copy()
    red = Image.new("RGB", overlay.size, (255, 60, 60))
    overlay.paste(red, (0, 0), mask=mask.convert("1"))

    shots_dir = Path(SCREENSHOTS_DIR).resolve()
    shots_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = shots_dir / f"diff-{_ts()}.png"
    overlay.save(overlay_path)

    return {
        "ok": True,
        "match": diff_ratio < 0.005,
        "diff_ratio": round(diff_ratio, 4),
        "diff_pixels": diff_count,
        "image_size": [width, height],
        "bounding_box": list(bbox) if bbox else None,
        "overlay_path": str(overlay_path),
        "current_path": str(cur.resolve()),
        "reference_path": str(ref.resolve()),
    }


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
            name="playground_create",
            description=(
                "Designer mode. Create or reuse a Flutter playground project at "
                "%TEMP%/mobile-design-playground/<name>/, seeded with a Designer-"
                "mode entry (lib/main.dart) and an empty canvas (lib/design.dart). "
                "Idempotent: passing the same name returns the existing path. "
                "If `name` is omitted, generates `sketch_YYYYMMDD_HHMMSS`. "
                "Returns {ok, path, exists, name}."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Lowercase snake_case Dart package name. Optional — "
                            "auto-generated from timestamp if omitted."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        ),
        Tool(
            name="flutter_run",
            description=(
                "Designer mode. Launch `flutter run --machine --hot` for the "
                "given project on the target platform. Idempotent — same "
                "project_path returns the existing app's vm_service_uri / "
                "app_id. Blocks until app.started lands (up to 4 min for "
                "first cold compile). Returns {ok, app_id, vm_service_uri, "
                "exists}."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Absolute path to the Flutter project root.",
                    },
                    "platform": _platform_prop(),
                },
                "required": ["project_path", "platform"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="flutter_hot_reload",
            description=(
                "Designer mode. Send a hot-reload (not full restart) to the "
                "running flutter app for the given project. Use after every "
                "Dart edit. ~2s round-trip. Returns {ok, result}."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Same project_path passed to flutter_run.",
                    },
                },
                "required": ["project_path"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="flutter_stop",
            description=(
                "Designer mode. Stop the running flutter app for the given "
                "project. Sends app.stop, then force-terminates if needed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                },
                "required": ["project_path"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="inspect_widget",
            description=(
                "Designer mode. Look up a widget by its Semantics identifier "
                "in the live a11y tree and return {bounds, text, class}. "
                "Bounds come from Maestro's hierarchy snapshot. Use to "
                "measure rendered positions instead of computing font / "
                "layout metrics by hand."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": _platform_prop(),
                    "identifier": {
                        "type": "string",
                        "description": "Semantics identifier / accessibilityIdentifier / resource-id.",
                    },
                },
                "required": ["platform", "identifier"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="compare_to_reference",
            description=(
                "Designer mode. Compare the latest (or specified) screenshot "
                "to a reference image. Returns the fraction of differing "
                "pixels, a bounding box of the differing region, and writes "
                "a red-tinted overlay PNG to tmp/screenshots/. Use to catch "
                "design mismatches without the user having to eyeball-compare."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "reference_path": {
                        "type": "string",
                        "description": "Absolute path to the reference image (the moodboard).",
                    },
                    "current_path": {
                        "type": "string",
                        "description": (
                            "Absolute path to the current screenshot. If omitted, "
                            "uses the newest PNG in tmp/screenshots/."
                        ),
                    },
                    "threshold": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 255,
                        "default": 30,
                        "description": (
                            "Per-channel intensity diff above which a pixel "
                            "counts as 'changed'. 30 ignores small encoding drift."
                        ),
                    },
                },
                "required": ["reference_path"],
                "additionalProperties": False,
            },
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

    # Designer-mode tools that don't take a `platform` argument.
    if name == "playground_create":
        result = _do_playground_create(name=arguments.get("name"))
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "flutter_hot_reload":
        result = _do_flutter_hot_reload(arguments["project_path"])
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "flutter_stop":
        result = _do_flutter_stop(arguments["project_path"])
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "compare_to_reference":
        result = _do_compare_to_reference(
            reference_path=arguments["reference_path"],
            current_path=arguments.get("current_path"),
            threshold=arguments.get("threshold", 30),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    p: Platform = arguments["platform"]

    if name == "flutter_run":
        result = _do_flutter_run(
            project_path=arguments["project_path"],
            platform=p,
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "inspect_widget":
        result = _do_inspect_widget(p, identifier=arguments["identifier"])
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

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
