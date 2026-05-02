# Platform-Specific Notes

`mobile-design-verify`'s MCP tools work the same on every platform —
`screenshot`, `tap`, `view_hierarchy`, etc. all take `platform: "ios" | "android"`
and Just Work. But each platform has its own quirks for **making your UI
elements visible to Maestro's accessibility tree**. This doc covers them.

## iOS (SwiftUI)

### Accessibility identifiers don't always propagate

A common surprise: an outer view has `.accessibilityIdentifier(...)`, but
Maestro can't find it because the inner content is what surfaces to the a11y
tree.

**Fix:** combine children explicitly:

```swift
HStack {
    Image(systemName: "checkmark")
    Text("Done")
}
.accessibilityElement(children: .combine)         // <- merges children
.accessibilityIdentifier("status-indicator-done")
```

`.combine` makes the row a single a11y leaf with the identifier you set.
Without it, the children may show up as separate elements and the outer
identifier might not propagate.

For destinations of `NavigationLink`, set the identifier on the destination
view's root (not the link):

```swift
NavigationLink(destination: DetailView()
    .accessibilityIdentifier("detail-view-root")
) {
    ContentView()
}
```

### Native rebuild required

The skill assumes a native rebuild loop (no InjectionIII). For each round of
edits:

```bash
scripts/verify-ios.sh path/to/MyApp.xcworkspace SchemeName
```

### Simulator must be booted before tools work

Tools fail with "No ios devices available" until you boot a sim:

```bash
xcrun simctl boot "iPhone 15 Pro"
open -a Simulator
```

`scripts/verify-ios.sh` handles this for you.

## Android (Compose / Kotlin)

### `testTag` is invisible to Maestro by default

This is the single biggest gotcha on Android. By default,
`Modifier.testTag("foo")` puts a tag in Compose's semantics tree but **does
not** surface as `resource-id` in Android's accessibility tree — which is what
Maestro reads.

**Fix:** opt in at the Compose root, exactly once:

```kotlin
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MyAppTheme {
                Surface(
                    modifier = Modifier
                        .fillMaxSize()
                        .semantics { testTagsAsResourceId = true },  // <-- here
                ) {
                    AppNavHost()
                }
            }
        }
    }
}
```

After this single root-level opt-in, every `Modifier.testTag("...")` in your
tree becomes a `resource-id` in Maestro's view hierarchy.

### Emulator startup wait

Booting an AVD takes time. The pattern:

```bash
emulator -avd Pixel_7_API_34 -no-snapshot &
adb wait-for-device
adb shell while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done
```

`scripts/verify-android.sh` handles this.

### Multiple devices / serial selection

If you have multiple devices connected, `_select_device_id` will hard-fail
with the full list. Set:

```bash
export MOBILE_DESIGN_VERIFY_DEVICE_ID=R5CW72Z2LDK   # one of the listed serials
```

Honored by both the MCP server and `scripts/verify-*.sh`.

### USB debugging must be authorized

`adb devices` shows `unauthorized` until you tap "Allow USB debugging" on the
device. Once accepted, replug and confirm `device` (not `unauthorized`,
`offline`).

## Flutter

### Widgets are opaque to native a11y by default

Flutter renders to a single native `FlutterActivity` / `FlutterView`. Individual
widgets do **not** show up in the native a11y tree unless you explicitly opt
in.

**Fix:** wrap interactive widgets in `Semantics(identifier: ...)`:

```dart
Semantics(
  identifier: 'todo-card-0',
  child: ListTile(/* ... */),
)
```

This maps to:

- **iOS**: `accessibilityIdentifier` on the underlying `UIView`
- **Android**: `resource-id` (Flutter ≥ 3.10)

Verified working on Flutter 3.41.5 with the `mobile-design-verify` smoke
tests against `examples/todo-verify/flutter/`.

### Hot reload from script is out of scope (v0)

`flutter run` with hot reload is awkward to script reliably. Use
`scripts/verify-flutter.sh` which does `flutter build` + `adb install` +
launch. If you want hot reload during dev, run `flutter run` in a separate
terminal yourself.

### Cross-platform bundle id mismatch

Flutter projects use different ids on each platform:

- Android `applicationId`: `com.example.todo_verify` (snake_case allowed)
- iOS `CFBundleIdentifier`: `com.example.todoVerify` (camelCase, derived from
  the project name)

When passing `bundle_id` to `launch_app` / `kill_app`, use the value that
matches the platform you're targeting.

## Maestro & JDK

Maestro requires JDK 17+. Verified working with:

- Oracle JDK 20.0.2
- Android Studio JBR 21.0.10

Older JDKs (< 17) will not work — Maestro's CLI fails to start.

## Windows + Claude Code Bash tool

Java builds (`flutter build`, `gradle ...`, `mvn ...`) **fail in Claude Code's
Bash tool** with `Unable to establish loopback connection` on Windows. The
restriction propagates to all child processes (cmd.exe, powershell.exe,
`start /wait`). Run those commands in your interactive PowerShell or Git Bash
terminal instead.

The MCP tools themselves are **unaffected** — Claude Code spawns the MCP
server through a different mechanism. So `screenshot`, `view_hierarchy`, `tap`,
`assert_visible`, etc. all work normally from Claude.

See [troubleshooting.md](troubleshooting.md) for the full diagnosis and the
upstream issue link.
