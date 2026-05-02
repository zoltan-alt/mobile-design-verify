---
name: mobile-design-verify
description: |
  Build, screenshot, tap, and verify native iOS / Flutter / Android UIs through
  real simulators and emulators. Use whenever you've changed mobile UI code
  (SwiftUI views, Flutter widgets, Compose composables) and need to verify the
  rendered result before declaring the task done.
when_to_use: |
  - Activated automatically when editing .swift, .dart, or *Compose*.kt files
    in this project.
  - Use after every meaningful UI change (layout, color, copy, navigation).
  - Use to recover from "what's on screen?" ambiguity instead of asking the
    user to describe it.
  - Use before claiming a UI task is done.
---

# mobile-design-verify

A Claude Code skill that closes the visual feedback loop on mobile UI work.
Build, screenshot, tap, and verify native iOS / Flutter / Android UIs through
real simulators and emulators.

## The verify loop

When you change mobile UI code:

1. **Edit** the SwiftUI view / Flutter widget / Compose composable.
2. **Build & install** to the target via the right script (run in the user's
   own terminal — see [troubleshooting](docs/troubleshooting.md) for the
   Windows-on-Claude-Code build limitation):
   - `scripts/verify-flutter.sh <flutter_project>` for Flutter
   - `scripts/verify-ios.sh <project> <scheme>` for native iOS
   - `scripts/verify-android.sh <module>` for native Android Compose
3. **Capture** what's on screen: `mcp__mobile-design-verify__screenshot`.
4. **Read** the captured PNG (the Read tool renders it). Compare to the design.
5. **Read the hierarchy** if needed: `mcp__mobile-design-verify__view_hierarchy`.
   The pruned tree shows interactive element ids.
6. **Interact**: `tap`, `scroll`, `swipe`, `type_text`, `press_key`.
7. **Verify state changes**: re-screenshot or `assert_visible`.
8. **Loop** until the UI matches the spec.

**Don't declare a UI task done without running this loop.**

## Tool reference

| Tool | When to use |
| --- | --- |
| `screenshot(platform)` | Visual snapshot of the foreground app. Returns a PNG path; Read it. |
| `view_hierarchy(platform)` | Pruned a11y tree of the foreground app. Use to discover tappable element ids. |
| `launch_app(platform, bundle_id)` | Foreground an app by its bundle id / Android `applicationId`. |
| `kill_app(platform, bundle_id)` | Force-quit. Useful for "reset to clean state" before a flow. |
| `tap(platform, id\|text\|point)` | Tap an element. Prefer `id`, fall back to `text`, last resort `point`. |
| `scroll(platform, direction, distance)` | Directional scroll. `distance`: `"short"` (~30%) or `"long"` (~70%). |
| `swipe(platform, start, end)` | Coordinate-based swipe (e.g. `"50%, 80%"` → `"50%, 20%"`). |
| `type_text(platform, text)` | Input into the currently-focused field. |
| `press_key(platform, key)` | Hardware/system key: `BACK`, `HOME`, `ENTER`, `ESCAPE`, `TAB`, `DELETE`, `BACKSPACE`, `VOLUME_UP`, `VOLUME_DOWN` (case-insensitive). |
| `wait_for(platform, id\|text, timeout?)` | Block until visible (default 10s). |
| `assert_visible(platform, id\|text)` | Assert visible right now. Use after `tap` / `wait_for` to confirm state. |
| `ping()` | Connectivity check; no platform argument. |

`platform` is always `"ios"` or `"android"`. The MCP server selects the right
device automatically (single booted simulator or single connected device);
set `MOBILE_DESIGN_VERIFY_DEVICE_ID` to disambiguate when more than one is
present. See `_select_device_id` in `server/mobile_design_mcp.py`.

## Conventions

Every tappable / verifiable element needs a stable accessibility identifier.
Use the `kind-noun-modifier` pattern:

- `todo-card-0` — first todo card on the home screen
- `todo-detail-1` — detail screen for the second todo
- `todo-step-row-2` — third step in a detail screen
- `setting-toggle-notifications`
- `dialog-confirm-delete`

See [docs/conventions.md](docs/conventions.md) for per-platform code samples
(SwiftUI, Flutter, Compose) and the full set of rules.

Important platform gotchas:

- **Flutter**: wrap interactive widgets in `Semantics(identifier: ...)` —
  Flutter widgets are otherwise opaque to native a11y on Android.
- **Compose**: `Modifier.testTag(...)` is invisible to Maestro by default —
  needs `Modifier.semantics { testTagsAsResourceId = true }` at the Compose
  root.
- **iOS**: a11y identifiers don't always propagate through nested containers;
  sometimes need `.accessibilityElement(children: .combine)` on the parent
  or an explicit identifier on the leaf.

See [docs/platforms.md](docs/platforms.md) for the full list.

## Common patterns

### Verify a screen looks right after edit

```
1. (in your terminal) scripts/verify-flutter.sh examples/todo-verify/flutter
2. mcp__mobile-design-verify__screenshot(platform="android")
3. Read the returned PNG path
4. Compare to the spec; if wrong, edit and repeat
```

### Verify navigation: tap → wait_for → assert_visible

```
1. assert_visible(platform="android", id="todo-card-0")    # confirm starting state
2. tap(platform="android", id="todo-card-1")               # perform action
3. wait_for(platform="android", id="todo-detail-1",        # absorb animation
            timeout=5)
4. assert_visible(platform="android", id="todo-detail-1")  # confirm landed
```

### Verify a state change: snapshot → tap → re-snapshot

```
1. screenshot(platform="android")            # before; Read it
2. tap(platform="android", id="some-button")
3. screenshot(platform="android")            # after; Read it
4. Compare the two; confirm the visual diff matches the expectation
```

### Recover from a stuck app

```
1. kill_app(platform="android", bundle_id="com.example.todo_verify")
2. launch_app(platform="android", bundle_id="com.example.todo_verify")
3. assert_visible(platform="android", id="todo-card-0")
```

## Setup

See [README.md](README.md) for installing prerequisites (Maestro, Flutter,
Android SDK / Xcode) and registering the MCP server with Claude Code.

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md). Notable: on Windows,
Java-based builds (Gradle / Flutter) **must be run from your interactive
terminal**, not Claude Code's Bash tool — a known platform limitation. The
MCP tools themselves are unaffected.
