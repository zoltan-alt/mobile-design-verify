# Third-Party Licenses

This file lists all third-party software incorporated into or required by
`mobile-design-verify`, along with their licenses.

## Python (server/)

| Package | License | Source |
| --- | --- | --- |
| (none yet) | — | — |

Populated automatically as dependencies are added; verified via `pip-licenses` in the pre-publish checklist.

## External tools (not bundled — runtime dependencies)

These tools are **not bundled** with `mobile-design-verify`. The user installs them themselves; the project shells out to them.

| Tool | License | Purpose |
| --- | --- | --- |
| Maestro | Apache-2.0 | UI automation backend |
| Xcode / xcodebuild | Apple proprietary | iOS build (user-installed) |
| Android SDK / Gradle | Apache-2.0 / Google EULA | Android build (user-installed) |
| Flutter SDK | BSD-3-Clause | Flutter build (user-installed) |
