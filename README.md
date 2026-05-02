# mobile-design-verify

A Claude Code skill plus an MCP server that lets Claude build, screenshot, tap, and verify native iOS / Flutter / Android UIs against real simulators and emulators — closing the visual feedback loop on mobile UI work.

When Claude edits a SwiftUI view, a Flutter widget, or a Compose composable, it can:

1. Build and install the app to a connected device or simulator (`scripts/verify-{ios,flutter,android}.sh`).
2. Capture a screenshot, read it back as an image, and compare to the design.
3. Read the (pruned) accessibility tree to discover interactive element ids.
4. Tap / scroll / swipe / type / wait / assert against the rendered UI.
5. Loop.

It's not a UI-test framework — it's a visual feedback channel for an LLM working on mobile UI.

## Status

- ✅ **Flutter** target on Android device / emulator — verified end-to-end with smoke tests against [`examples/todo-verify/flutter/`](examples/todo-verify/flutter/).
- 🚧 **iOS** target — code is in place; smoke tests pending verification on a Mac.
- 🚧 **Native Compose** target — `verify-android.sh` and example app pending.

## Prerequisites

| Tool | Why | Where |
| --- | --- | --- |
| **Maestro** ≥ 2.5 | UI driver | `curl -Ls "https://get.maestro.mobile.dev" \| bash` |
| **JDK** ≥ 17 | required by Maestro and Gradle | Adoptium Temurin — or Android Studio's bundled JBR 21 |
| **Python** ≥ 3.10 | runs the MCP server | python.org / OS package manager |
| **Flutter SDK** | only if you build Flutter targets | flutter.dev/docs/get-started/install |
| **Android SDK** + emulator | only if you target Android | Android Studio bundles the SDK manager |
| **Xcode** + Simulator | only if you target iOS (Mac only) | Mac App Store |

## Install

```bash
# 1. Clone
git clone https://github.com/zoltan-alt/mobile-design-verify.git
cd mobile-design-verify

# 2. Create a Python venv and install the MCP server (editable)
python -m venv server/.venv

# macOS / Linux:
server/.venv/bin/pip install -e ./server
# Windows:
server/.venv/Scripts/pip install -e ./server

# 3. Register the MCP server with Claude Code (project-scoped).
#    Use the venv python you just created.

# macOS / Linux:
claude mcp add --transport stdio --scope project mobile-design-verify -- \
  "$(pwd)/server/.venv/bin/python" -m mobile_design_mcp

# Windows (PowerShell):
claude mcp add --transport stdio --scope project mobile-design-verify -- `
  "$(Get-Location)\server\.venv\Scripts\python.exe" -m mobile_design_mcp
```

Then restart Claude Code. Run `/mcp` and confirm `mobile-design-verify` shows as **connected**.

## Quick start

Boot a simulator or connect a device:

```bash
# Android emulator
emulator -avd Pixel_7_API_34 &

# Or iOS simulator (Mac only)
xcrun simctl boot "iPhone 15 Pro" && open -a Simulator
```

Build and install the example Flutter app:

```bash
scripts/verify-flutter.sh examples/todo-verify/flutter
```

Now ask Claude (in this project):

> Take a screenshot of what's on screen and tell me what you see.

Claude will call `mcp__mobile-design-verify__screenshot`, read the PNG, and describe it. From there it can tap, scroll, assert, and iterate against the UI.

## How it works

The skill wraps Maestro behind 12 MCP tools (`screenshot`, `view_hierarchy`, `tap`, `assert_visible`, `wait_for`, `scroll`, `swipe`, `type_text`, `press_key`, `launch_app`, `kill_app`, `ping`) and a build script per platform.

- [SKILL.md](SKILL.md) — the verify-loop workflow and full tool reference.
- [docs/conventions.md](docs/conventions.md) — accessibility-identifier conventions (the `kind-noun-modifier` pattern), with per-platform code samples.
- [docs/platforms.md](docs/platforms.md) — per-platform gotchas (SwiftUI `.combine`, Compose `testTagsAsResourceId`, Flutter `Semantics(identifier:)`).
- [docs/troubleshooting.md](docs/troubleshooting.md) — common issues and the Windows + Claude Code Bash tool limitation.

The example app at [`examples/todo-verify/flutter/`](examples/todo-verify/flutter/) is a deliberately generic 3-todo list with `Semantics(identifier: ...)` wrappers — used as the smoke-test target.

## Multi-device / multi-platform

When more than one simulator is booted or more than one device is connected, set:

```bash
export MOBILE_DESIGN_VERIFY_DEVICE_ID=<udid-or-serial>
```

Honored by the MCP server (`_select_device_id`) and by `scripts/verify-*.sh`.

## Smoke tests

The v1 smoke tests (run on Android with the example app installed):

1. `screenshot("android")` returns a PNG with size > 0.
2. After launching `todo-verify`, `view_hierarchy("android")` JSON contains `todo-card-0`.
3. `tap("android", id="todo-card-1")` then `assert_visible("android", id="todo-detail-1")` succeeds.

Gated behind `MOBILE_DESIGN_VERIFY_E2E=1` so they don't run unintentionally.

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md). Common items:

- **Windows + Claude Code:** Java builds run from Claude's Bash tool fail with "Unable to establish loopback connection". Workarounds: either run `scripts/verify-flutter.sh` in your own PowerShell / Git Bash terminal, or have Claude invoke `python scripts/_claude-windows-build.py <flutter-dir>` which spawns the build via Windows Task Scheduler (escapes the process tree restriction). The MCP tools themselves are unaffected.
- **"No android devices available":** `adb devices` should list your device as `device` (not `offline` or `unauthorized`).
- **Maestro can't find element:** make sure your widget exposes the right accessibility identifier — see [docs/conventions.md](docs/conventions.md). On Compose specifically, `testTag` is invisible without `Modifier.semantics { testTagsAsResourceId = true }` at the Compose root.

## Contributing

Pull requests welcome. By submitting a PR, you agree your changes are licensed under Apache-2.0. No CLA required.

## License

`mobile-design-verify` is licensed under the [Apache License 2.0](LICENSE). See [`NOTICE`](NOTICE) for required attributions and [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) for the full dependency license list.

## Non-affiliation

`mobile-design-verify` is an independent open-source project. It is **not affiliated with, endorsed by, or sponsored by** Apple Inc., Google LLC, Anthropic PBC, or mobile.dev Inc. (Maestro). All product names, logos, and trademarks referenced are property of their respective owners; their mention here is purely descriptive (nominative fair use) and does not imply any partnership, certification, or warranty.
