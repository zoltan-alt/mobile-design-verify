#!/usr/bin/env bash
# Copyright 2026 zoltan-alt — Licensed under Apache-2.0. See LICENSE.
#
# verify-flutter.sh — Build + install + launch a Flutter app on the currently
# booted iOS Simulator or connected Android device, leaving it foregrounded so
# `mobile-design-verify`'s screenshot / view_hierarchy tools can inspect it.
#
# Usage:
#   scripts/verify-flutter.sh [<flutter_project_dir>] [--platform=auto|android|ios] [--release|--debug]
#
# Defaults:
#   project dir = examples/todo-verify/flutter
#   platform    = auto (Android if a device is connected, else iOS sim)
#   build mode  = debug
#
# Honors MOBILE_DESIGN_VERIFY_DEVICE_ID to disambiguate when multiple devices /
# simulators are connected (matches the MCP server's _select_device_id contract).

set -euo pipefail

# ---- arg parsing ----
PROJECT_DIR="${1:-examples/todo-verify/flutter}"
[[ "$PROJECT_DIR" == --* ]] && PROJECT_DIR="examples/todo-verify/flutter" || shift || true

PLATFORM="auto"
BUILD_MODE="debug"
while (( $# > 0 )); do
    case "$1" in
        --platform=auto|--platform=android|--platform=ios) PLATFORM="${1#--platform=}" ;;
        --release) BUILD_MODE="release" ;;
        --debug)   BUILD_MODE="debug" ;;
        -h|--help) sed -n '4,17p' "$0"; exit 0 ;;
        *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
    esac
    shift
done

if [[ ! -d "$PROJECT_DIR" ]]; then
    echo "ERROR: Flutter project dir not found: $PROJECT_DIR" >&2
    exit 1
fi

# ---- platform detection ----
detect_platform() {
    if command -v adb >/dev/null 2>&1 && \
       adb devices 2>/dev/null | awk 'NR>1 && $2=="device" {found=1; exit} END {exit !found}'; then
        echo "android"
    elif command -v xcrun >/dev/null 2>&1 && \
         xcrun simctl list devices booted -j 2>/dev/null | grep -q '"state" *: *"Booted"'; then
        echo "ios"
    else
        echo "none"
    fi
}

if [[ "$PLATFORM" == "auto" ]]; then
    PLATFORM=$(detect_platform)
    if [[ "$PLATFORM" == "none" ]]; then
        echo "ERROR: no Android device connected and no iOS Simulator booted" >&2
        echo "  Connect via USB or boot a sim, then retry." >&2
        exit 1
    fi
    echo "[*] auto-detected platform: $PLATFORM"
fi

DEVICE_ID="${MOBILE_DESIGN_VERIFY_DEVICE_ID:-}"

# ---- pub get ----
echo "[*] flutter pub get"
(cd "$PROJECT_DIR" && flutter pub get >/dev/null)

case "$PLATFORM" in
    android)
        ADB_ARGS=()
        [[ -n "$DEVICE_ID" ]] && ADB_ARGS=(-s "$DEVICE_ID")

        APK_NAME="app-${BUILD_MODE}.apk"
        APK_PATH="$PROJECT_DIR/build/app/outputs/flutter-apk/$APK_NAME"

        echo "[*] flutter build apk --$BUILD_MODE"
        (cd "$PROJECT_DIR" && flutter build apk "--$BUILD_MODE")

        if [[ ! -f "$APK_PATH" ]]; then
            echo "ERROR: built APK not found at $APK_PATH" >&2
            exit 1
        fi

        echo "[*] adb install -r $APK_PATH"
        adb "${ADB_ARGS[@]}" install -r "$APK_PATH"

        # Derive applicationId from android/app/build.gradle{,.kts}
        APP_ID=""
        for f in "$PROJECT_DIR/android/app/build.gradle.kts" "$PROJECT_DIR/android/app/build.gradle"; do
            [[ -f "$f" ]] || continue
            APP_ID=$(grep -m1 'applicationId' "$f" | grep -oE '"[^"]+"' | head -1 | tr -d '"')
            [[ -n "$APP_ID" ]] && break
        done
        if [[ -z "$APP_ID" ]]; then
            echo "ERROR: could not derive applicationId from android/app/build.gradle{,.kts}" >&2
            exit 1
        fi

        echo "[*] adb shell am start -n $APP_ID/.MainActivity"
        adb "${ADB_ARGS[@]}" shell am start -n "$APP_ID/.MainActivity"
        ;;

    ios)
        echo "[*] flutter build ios --simulator --$BUILD_MODE --no-codesign"
        (cd "$PROJECT_DIR" && flutter build ios --simulator "--$BUILD_MODE" --no-codesign)

        APP_PATH=$(find "$PROJECT_DIR/build/ios/iphonesimulator" -maxdepth 2 -name "*.app" -type d 2>/dev/null | head -1)
        if [[ -z "$APP_PATH" ]]; then
            echo "ERROR: built .app bundle not found under build/ios/iphonesimulator/" >&2
            exit 1
        fi

        SIM_TARGET="${DEVICE_ID:-booted}"
        echo "[*] xcrun simctl install $SIM_TARGET $APP_PATH"
        xcrun simctl install "$SIM_TARGET" "$APP_PATH"

        BUNDLE_ID=$(plutil -extract CFBundleIdentifier raw "$APP_PATH/Info.plist" 2>/dev/null)
        if [[ -z "$BUNDLE_ID" ]]; then
            echo "ERROR: could not read CFBundleIdentifier from $APP_PATH/Info.plist" >&2
            exit 1
        fi

        echo "[*] xcrun simctl launch $SIM_TARGET $BUNDLE_ID"
        xcrun simctl launch "$SIM_TARGET" "$BUNDLE_ID"
        ;;
esac

echo "[*] Done. App should be foregrounded."
echo "[*] mobile-design-verify can now: screenshot(\"$PLATFORM\"), view_hierarchy(\"$PLATFORM\")."
