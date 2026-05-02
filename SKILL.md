---
name: mobile-design-verify
description: |
  Build, screenshot, tap, verify, AND design native iOS / Flutter / Android
  UIs through real simulators and emulators. Two modes:
  - Verify mode — close the visual feedback loop on existing UI work.
  - Designer mode — use a temp Flutter playground + hot reload to design
    screens directly in Flutter from moodboards / aesthetics.
when_to_use: |
  - Activated automatically when editing .swift, .dart, or *Compose*.kt files
    in this project.
  - Use after every meaningful UI change (layout, color, copy, navigation).
  - Use to recover from "what's on screen?" ambiguity instead of asking the
    user to describe it.
  - Use Designer mode when the user shares a moodboard / aesthetic / vibes
    and asks for a screen design produced in Flutter.
  - Use before claiming a UI task is done.
---

# mobile-design-verify

A Claude Code skill that closes the visual feedback loop on mobile UI work
and lets Claude design mobile screens directly in Flutter — analogous to
Chrome MCP for web design.

## Two modes

| Mode | Trigger | Workspace | Loop |
| --- | --- | --- | --- |
| **Verify** | Editing UI in an existing project; user wants to confirm the rendered result matches a spec. | The user's project. | Edit → build → screenshot → compare → iterate. |
| **Designer** | User shares a moodboard / aesthetic / vibes and asks for a screen design. | A fresh `flutter create` playground in `%TEMP%/mobile-design-playground/`. | Sketch → hot reload (~2s) → diff against reference → iterate. |

Both share the same MCP toolset; Designer mode adds `playground_create`,
`flutter_run`, `flutter_hot_reload`, `inspect_widget`, and
`compare_to_reference`.

## Verify loop

When you change mobile UI code:

1. **Edit** the SwiftUI view / Flutter widget / Compose composable.
2. **Build & install** to the target. On Windows + Claude Code:
   - `python scripts/_claude-windows-build.py <flutter_project>` — runs
     the Flutter build via Windows Task Scheduler so it escapes the
     Java/NIO sandbox restriction. Then `adb install -r ...` and
     `adb shell am start -n ...` work fine from the Bash tool.
   - On macOS / Linux, run `scripts/verify-flutter.sh` directly.
3. **Capture** what's on screen: `mcp__mobile-design-verify__screenshot`.
4. **Read** the captured PNG (the Read tool renders it). Compare to the
   design.
5. **Read the hierarchy** if needed:
   `mcp__mobile-design-verify__view_hierarchy`. The pruned tree shows
   interactive element ids.
6. **Interact**: `tap`, `scroll`, `swipe`, `type_text`, `press_key`.
7. **Verify state changes**: re-screenshot or `assert_visible`.
8. **Loop** until the UI matches the spec.

**Don't declare a UI task done without running this loop.**

## Designer loop

When the user gives you a moodboard or describes an aesthetic and asks
for a screen, **don't immediately code**. Follow this loop:

1. **Read the moodboard structurally** — see the checklist below.
2. **Describe back what you see** — every element, with measurements
   (rotation, line spacing, exact endpoints relative to glyphs, color
   tokens). Wait for confirmation before coding.
3. **Spin up a playground** if one isn't running:
   `mcp__mobile-design-verify__playground_create(name)` →
   `mcp__mobile-design-verify__flutter_run(project_path, platform)`. The
   first creates a temp Flutter project; the second launches it with
   `flutter run --hot` in the background and returns the VM service URL.
4. **Sketch the screen** — write Dart in the playground.
5. **Hot reload** instead of full rebuild:
   `mcp__mobile-design-verify__flutter_hot_reload(project_path)`. ~2s
   instead of ~30s. **This is the iteration unit.**
6. **Inspect when measurements matter**:
   `mcp__mobile-design-verify__inspect_widget(platform, identifier)`
   returns `{rect, color, fontSize, baseline}`. Use it instead of
   computing font metrics by hand.
7. **Diff against the reference**:
   `mcp__mobile-design-verify__compare_to_reference(reference_path)`
   compares the latest screenshot to the moodboard image and returns
   regions that differ. Catches mistakes before the user has to.
8. **Loop**, narrating what you changed each round. Stop when the user
   says it's matching.
9. **Log the session** to `docs/design-corpus/<session-id>/` —
   moodboard summary, iteration history, accepted spec. Future sessions
   read from this corpus to prime moodboard-reading.

### Moodboard-reading checklist

Before coding from a reference image, **describe back to the user**:

- **Text**:
  - verbatim copy on each line
  - font feel (handwritten? sans? serif?)
  - rotation (often subtle — check whether the right side leans up or
    down vs the horizontal)
  - line height (tight where descenders almost touch ascenders? loose?)
  - alignment (left-aligned? centered? slight indent?)
  - color (is it actually black, or a dark navy / dark plum?)
- **Strokes / underlines / squiggles**:
  - **count** — one stroke or two? Two parallel? Two staggered?
  - **shape** — straight line? sine wave? simple arc? two arcs?
  - **endpoints** — relative to which letter? (e.g. "starts at the 'e'
    of 'Pet', ends at the 'e' of 'Parent'")
  - **thickness, caps** — round? flat? variable?
  - **rotation** — does the whole stroke tilt?
- **Stickers / decorations** (heart, star, paw):
  - hand-drawn outline vs system emoji? (these look very different)
  - position relative to surrounding elements (above, below, between
    text lines)
- **Cards / containers**:
  - corner radius (gentle ~14-18 vs full pill ~30+)
  - elevation / shadow (tight vs spread)
  - border (none, hand-drawn, system?)
  - ALSO: any overflow — does an element hang off the card edge?
- **Spacing / proportions**:
  - vertical rhythm (gap between header and section, between section
    and first card)
  - horizontal rhythm (margin from screen edge)
- **Texture**:
  - paper grain? noise? colored background tints?
  - tilt-angle variations (cards alternating slight tilts feels
    organic)

**The default failure mode**: scanning for ELEMENTS present (heart ✓,
star ✓, bell ✓) and skipping how they're DRAWN. That maps "squiggle
underline" to a sine wave instead of looking at the actual two-stroke
shape. That treats hand-drawn graphic stickers as system emojis.

After shipping a design iteration, **don't say "it matches"** — say
"matches except X, Y", listing specific differences you spot in the
screenshot.

### Designer mode workflow rules

- **Describe → STOP → wait.** When iterating on visual details from a
  reference, after each describe step, stop and wait for the user's
  go-ahead before changing code. Don't describe-and-immediately-execute
  unless the user explicitly told you to "just do it".
- **No `ListView`-as-only-child of a `Stack`** without `clipBehavior:
  Clip.none` — overflowing decorations (washi tape, brush wash, etc.)
  get cut.
- **All hand-drawn marks have variation.** A "border" that's literally
  a 1.5px constant stroke looks digital. Add a base layer + segmented
  pen-pressure variation (see `_PressureBorderPainter` in
  `pet-ops/lib/core/widgets/pressure_border.dart` for the canonical
  recipe).
- **Cap pen-pressure variations at ~90% alpha** — never solid 100%.
  100% next to 50% reads as a line break.
- **Tilt only as much as the moodboard shows.** Mood-board tilts are
  usually -3° to -6°, not -10°+.

## Tool reference

| Tool | When to use |
| --- | --- |
| `playground_create(name)` | **Designer mode**. Create a fresh `flutter create` project in `%TEMP%/mobile-design-playground/<name>/`, seeded with `AppColors`+`AppLayout` skeletons and an empty `DesignPreview` screen. |
| `flutter_run(project_path, platform)` | **Designer mode**. Launch `flutter run --hot --machine` detached, return the VM service URL. |
| `flutter_hot_reload(project_path)` | **Designer mode**. Send a hot reload to the running Flutter VM. ~2s. Use after every Dart edit. |
| `inspect_widget(platform, identifier)` | **Designer mode**. Return `{rect, color, fontSize, baseline}` for a Semantics-tagged widget. Use instead of computing font metrics by hand. |
| `compare_to_reference(reference_path)` | **Designer mode**. Diff the latest screenshot against the reference image. Returns diff overlay PNG + regions list. |
| `screenshot(platform)` | Visual snapshot of the foreground app. Returns a PNG path; Read it. |
| `screenshot_scrolling(platform, count)` | Multi-shot capture for content taller than viewport. Use when a single `screenshot` would miss content below the fold. |
| `view_hierarchy(platform)` | Pruned a11y tree of the foreground app. Use to discover tappable element ids. |
| `launch_app(platform, bundle_id)` | Foreground an app by its bundle id / Android `applicationId`. |
| `kill_app(platform, bundle_id)` | Force-quit. Useful for "reset to clean state" before a flow. |
| `tap(platform, id\|text\|point)` | Tap an element. Prefer `id`, fall back to `text`, last resort `point`. |
| `scroll(platform, direction, distance)` | Directional scroll. `distance`: `"short"` (~30%) or `"long"` (~50%). Endpoints clamped to the safe band 25-75% so the swipe doesn't land on app bars / sticky CTAs. |
| `swipe(platform, start, end)` | Coordinate-based swipe (e.g. `"50%, 80%"` → `"50%, 20%"`). |
| `type_text(platform, text)` | Input into the currently-focused field. |
| `press_key(platform, key)` | Hardware/system key: `BACK`, `HOME`, `ENTER`, `ESCAPE`, `TAB`, `DELETE`, `BACKSPACE`, `VOLUME_UP`, `VOLUME_DOWN` (case-insensitive). |
| `wait_for(platform, id\|text, timeout?)` | Block until visible (default 10s). |
| `assert_visible(platform, id\|text)` | Assert visible right now. Use after `tap` / `wait_for` to confirm state. |
| `ping()` | Connectivity check; no platform argument. |

`platform` is always `"ios"` or `"android"`. The MCP server selects the
right device automatically (single booted simulator or single connected
device); set `MOBILE_DESIGN_VERIFY_DEVICE_ID` to disambiguate when more
than one is present. See `_select_device_id` in
`server/mobile_design_mcp.py`.

## Conventions

Every tappable / verifiable element needs a stable accessibility
identifier. Use the `kind-noun-modifier` pattern:

- `todo-card-0` — first todo card on the home screen
- `todo-detail-1` — detail screen for the second todo
- `todo-step-row-2` — third step in a detail screen
- `setting-toggle-notifications`
- `dialog-confirm-delete`

See [docs/conventions.md](docs/conventions.md) for per-platform code
samples (SwiftUI, Flutter, Compose) and the full set of rules.

Important platform gotchas:

- **Flutter**: wrap interactive widgets in `Semantics(identifier: ...)`
  — Flutter widgets are otherwise opaque to native a11y on Android.
- **Compose**: `Modifier.testTag(...)` is invisible to Maestro by
  default — needs `Modifier.semantics { testTagsAsResourceId = true }`
  at the Compose root.
- **iOS**: a11y identifiers don't always propagate through nested
  containers; sometimes need `.accessibilityElement(children: .combine)`
  on the parent or an explicit identifier on the leaf.

See [docs/platforms.md](docs/platforms.md) for the full list.

## Common patterns

### Verify a screen looks right after edit

```
1. python scripts/_claude-windows-build.py <flutter_project>
2. adb install -r <flutter_project>/build/app/outputs/flutter-apk/app-debug.apk
3. adb shell am start -n <applicationId>/.MainActivity
4. mcp__mobile-design-verify__screenshot(platform="android")
5. Read the returned PNG path
6. Compare to the spec; if wrong, edit and repeat
```

### Designer mode — sketch a new screen from a moodboard

```
1. User shares a moodboard image.
2. Describe back what you see (use the checklist). STOP for confirmation.
3. mcp__mobile-design-verify__playground_create(name="home-sketch-2")
   → returns project path
4. mcp__mobile-design-verify__flutter_run(project_path, platform="android")
   → launches with --hot, returns VM URL
5. Edit lib/main.dart in the playground.
6. mcp__mobile-design-verify__flutter_hot_reload(project_path)
7. mcp__mobile-design-verify__screenshot(platform="android"); Read it.
8. mcp__mobile-design-verify__compare_to_reference(reference_image)
   → diff overlay + regions list. Catches mismatches.
9. Iterate (steps 5-8) until the user accepts.
10. Log the session under docs/design-corpus/<session-id>/.
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

See [README.md](README.md) for installing prerequisites (Maestro,
Flutter, Android SDK / Xcode) and registering the MCP server with
Claude Code.

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md). Notable: on
Windows, Java-based builds (Gradle / Flutter) **fail in Claude Code's
Bash tool** — workaround is `scripts/_claude-windows-build.py` which
runs the build via Windows Task Scheduler. The MCP tools themselves
are unaffected.

## Self-improvement

See [docs/design-corpus/README.md](docs/design-corpus/README.md). Each
designer-mode session ends with a structured log in
`docs/design-corpus/<session-id>/` — moodboard summary, iteration
history, accepted spec. Future sessions read from this corpus to prime
moodboard-reading and avoid repeating mistakes.
