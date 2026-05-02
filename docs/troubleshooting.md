# Troubleshooting

## "Unable to establish loopback connection" when running Flutter / Gradle from Claude Code's Bash tool

**Symptom.** `scripts/verify-flutter.sh`, `flutter build apk`, `./gradlew assembleDebug`, or any Java-based build invoked from Claude Code's Bash tool fails with:

```
java.io.IOException: Unable to establish loopback connection
    at java.base/sun.nio.ch.PipeImpl$Initializer.run(PipeImpl.java:103)
Caused by: java.net.SocketException: Invalid argument: connect
    at java.base/sun.nio.ch.UnixDomainSockets.connect0(Native Method)
```

**Cause.** Java's NIO `Selector.open()` calls `UnixDomainSockets.connect0` for its internal Pipe. On Windows, this returns `EINVAL` when invoked from a process spawned by Claude Code's Bash tool. The restriction propagates to grandchildren — wrapping in `cmd.exe`, `powershell.exe`, or `cmd /c start /wait /b` all fail the same way. The same Java code succeeds when launched from a user's interactive PowerShell or Git Bash.

The `mobile-design-verify` **MCP server is not affected** because Claude Code spawns it via `.mcp.json` through a different mechanism. So `screenshot`, `view_hierarchy`, `tap`, `assert_visible`, and the other MCP tools work normally from Claude — only Java builds via the Bash tool fail.

**Workaround.** Run build scripts in your **own interactive terminal**, not through Claude Code:

```powershell
# Open a fresh PowerShell or Git Bash, in the project root:
scripts/verify-flutter.sh examples/todo-verify/flutter
```

Once the app is installed and foregrounded on your device/simulator, return to Claude Code and use the MCP tools (`screenshot`, `view_hierarchy`, `tap`, `scroll`, `assert_visible`, etc.) normally.

**Things that do not bypass it** (tested 2026-05-02, Windows 11 26H1, JDK 20.0.2 + Android Studio JBR 21.0.10):

- `--no-daemon` / `-Dorg.gradle.daemon=false`
- `-Djava.net.preferIPv4Stack=true`
- `-Dsun.nio.ch.disableUnixDomainSockets=true`
- `-Djdk.nio.userForceUnixDomainSocket=false`
- `dangerouslyDisableSandbox: true` on the Bash tool
- Switching JDK (Oracle 20 → JBR 21)
- Wrapping in `cmd.exe /c`, `powershell.exe -Command`, `cmd /c start /wait /b`
- `PreToolUse` hooks (run before the tool, can't change subprocess token)

**Upstream.** Same root cause as [anthropics/claude-code#41432](https://github.com/anthropics/claude-code/issues/41432) — JVM-based stdio MCP servers / builds breaking under Claude Code's Windows subprocess sandbox. Closed there as a platform-side issue. If/when Anthropic addresses it upstream, this workaround can be retired.

## Other troubleshooting

(Pending; will be expanded as new issues surface.)
