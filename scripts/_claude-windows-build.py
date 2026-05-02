#!/usr/bin/env python3
# Copyright 2026 zoltan-alt — Licensed under Apache-2.0. See LICENSE.

"""Run ``flutter build apk`` via Windows Task Scheduler.

Workaround for the Claude-Code-on-Windows limitation where Java/Gradle
builds fail with ``Unable to establish loopback connection`` (Java NIO
selector can't bind a loopback port inside Claude Code's Bash tool process
tree). The Task Scheduler service spawns the task in a fresh process tree
under LocalSystem, escaping the restriction.

Usage::

    python scripts/_claude-windows-build.py <flutter-project-dir>
    python scripts/_claude-windows-build.py <flutter-project-dir> --build-mode debug

The script blocks until the build finishes, streams its stdout/stderr back,
and exits with the build's exit code. Cleans up the temporary scheduled
task + log files on the way out (including on Ctrl-C).

Scope:
    - Windows + Claude Code only. On macOS / Linux, builds run fine
      directly from Claude Code's Bash and this script is unnecessary.
    - Build only. ``adb install`` / ``adb shell am start`` work fine from
      Claude's Bash since they don't spawn a JVM — call them directly
      after this returns 0.

Upstream: anthropics/claude-code#41432.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

# schtasks "Last Result" sentinel values for in-flight states.
_STILL_RUNNING = {"267009", "267011"}


def _query_task(task_name: str) -> tuple[str | None, str | None]:
    """Return (status, last_result) from ``schtasks /query``."""
    proc = subprocess.run(
        ["schtasks", "/query", "/tn", task_name, "/v", "/fo", "LIST"],
        capture_output=True,
        text=True,
    )
    status: str | None = None
    last_result: str | None = None
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        low = line.lower()
        if low.startswith("status:"):
            status = line.split(":", 1)[1].strip()
        elif low.startswith("last result:"):
            last_result = line.split(":", 1)[1].strip()
    return status, last_result


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run a Flutter build via Windows Task Scheduler "
                    "(Claude Code + Windows workaround).",
    )
    ap.add_argument(
        "project_dir",
        type=Path,
        help="Path to the Flutter project (must contain pubspec.yaml).",
    )
    ap.add_argument(
        "--build-mode",
        default="debug",
        choices=["debug", "profile", "release"],
        help="Flutter build mode (default: debug).",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Max seconds to wait for the build (default: 600).",
    )
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not (project / "pubspec.yaml").is_file():
        print(f"error: {project} has no pubspec.yaml", file=sys.stderr)
        sys.exit(2)

    if os.name != "nt":
        print(
            "warning: this script is a Windows-specific workaround. "
            "On macOS / Linux, run `flutter build` directly.",
            file=sys.stderr,
        )

    tag = uuid.uuid4().hex[:8]
    task_name = f"ClaudeWinBuild_{tag}"
    temp = Path(os.environ.get("TEMP", "."))
    batch = temp / f"{task_name}.bat"
    log_out = temp / f"{task_name}.stdout.log"
    log_err = temp / f"{task_name}.stderr.log"

    cmd = f"flutter build apk --{args.build_mode}"
    batch.write_text(
        "@echo off\r\n"
        f'cd /d "{project}"\r\n'
        f'{cmd} > "{log_out}" 2> "{log_err}"\r\n'
        "exit /b %ERRORLEVEL%\r\n",
        encoding="utf-8",
    )

    cleanup_task = lambda: subprocess.run(
        ["schtasks", "/delete", "/tn", task_name, "/f"],
        capture_output=True,
    )

    try:
        # Defensive cleanup in case a previous run with the same name leaked.
        cleanup_task()

        create = subprocess.run(
            [
                "schtasks", "/create", "/tn", task_name,
                "/tr", str(batch),
                "/sc", "ONCE", "/st", "00:00",
                "/f",
            ],
            capture_output=True,
            text=True,
        )
        if create.returncode != 0:
            print(
                "failed to create scheduled task: "
                f"{create.stderr or create.stdout}",
                file=sys.stderr,
            )
            sys.exit(3)

        run_proc = subprocess.run(
            ["schtasks", "/run", "/tn", task_name],
            capture_output=True,
            text=True,
        )
        if run_proc.returncode != 0:
            print(
                "failed to start scheduled task: "
                f"{run_proc.stderr or run_proc.stdout}",
                file=sys.stderr,
            )
            sys.exit(4)

        deadline = time.time() + args.timeout
        last_result: str | None = None
        while time.time() < deadline:
            time.sleep(2)
            status, last_result = _query_task(task_name)
            if status == "Ready" and last_result not in {None, ""} | _STILL_RUNNING:
                break
        else:
            print(
                f"timeout: build did not finish within {args.timeout}s",
                file=sys.stderr,
            )
            sys.exit(5)

        # Stream the task's captured output back through this process.
        # Write raw bytes via the underlying buffer so non-ASCII characters
        # (e.g. the "√ Built ..." check mark in flutter's success line) don't
        # crash on Windows' default cp1252 stdout encoding.
        if log_out.exists():
            sys.stdout.buffer.write(log_out.read_bytes())
            sys.stdout.flush()
        if log_err.exists():
            err_bytes = log_err.read_bytes()
            if err_bytes:
                sys.stderr.buffer.write(err_bytes)
                sys.stderr.flush()

        try:
            sys.exit(int(last_result or "99"))
        except ValueError:
            print(
                f"unexpected last_result from schtasks: {last_result!r}",
                file=sys.stderr,
            )
            sys.exit(99)
    except KeyboardInterrupt:
        # Best-effort cancel of the in-flight task.
        subprocess.run(
            ["schtasks", "/end", "/tn", task_name],
            capture_output=True,
        )
        sys.exit(130)
    finally:
        cleanup_task()
        for p in (batch, log_out, log_err):
            try:
                p.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    main()
