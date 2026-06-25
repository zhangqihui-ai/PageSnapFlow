"""Locate adb.exe on Windows (PATH, Android SDK, project tools/)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent


def resolve_adb_path() -> str:
    found = shutil.which("adb")
    if found:
        return found

    candidates: list[Path] = []
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        sdk = os.environ.get(key)
        if sdk:
            candidates.append(Path(sdk) / "platform-tools" / "adb.exe")

    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        candidates.append(Path(localappdata) / "Android" / "Sdk" / "platform-tools" / "adb.exe")

    candidates.append(_ROOT / "tools" / "platform-tools" / "adb.exe")

    for path in candidates:
        if path.is_file():
            return str(path)

    raise FileNotFoundError(
        "adb not found. Install Android SDK Platform-Tools in Android Studio "
        "(Settings → Android SDK → SDK Tools → Android SDK Platform-Tools), "
        "or set ANDROID_HOME / add platform-tools to PATH."
    )


def default_device_id(adb_path: str) -> str:
    out = subprocess.check_output(
        [adb_path, "devices"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in out.splitlines()[1:]:
        if "\tdevice" in line:
            return line.split("\t")[0].strip()
    raise RuntimeError("No adb device connected. Run: adb devices")


def _adb_shell(adb_path: str, device: str | None, *args: str) -> subprocess.CompletedProcess[bytes]:
    cmd = [adb_path]
    if device:
        cmd.extend(["-s", device])
    cmd.extend(["shell", *args])
    return subprocess.run(cmd, check=False, capture_output=True)


def hide_gesture_hint_bar(adb_path: str, device: str | None, use_overlay: bool = False) -> None:
    """Hide thin gesture hint line. Overlay off by default (breaks some apps)."""
    _adb_shell(
        adb_path,
        device,
        "settings",
        "put",
        "global",
        "navigation_bar_gesture_hint",
        "0",
    )
    if use_overlay:
        _adb_shell(
            adb_path,
            device,
            "cmd",
            "overlay",
            "enable",
            "com.android.internal.systemui.navbar.transparent",
        )


def restore_gesture_hint_bar(adb_path: str, device: str | None) -> None:
    _adb_shell(
        adb_path,
        device,
        "settings",
        "put",
        "global",
        "navigation_bar_gesture_hint",
        "1",
    )
    _adb_shell(
        adb_path,
        device,
        "cmd",
        "overlay",
        "disable",
        "com.android.internal.systemui.navbar.transparent",
    )


def hide_system_nav_bar(adb_path: str, device: str | None, package: str) -> None:
    """Soft hide via immersive policy only (does not break 3-button nav UI)."""
    _adb_shell(
        adb_path,
        device,
        "settings",
        "put",
        "global",
        "policy_control",
        f"immersive.navigation={package}",
    )


def restore_system_nav_bar(adb_path: str, device: str | None) -> None:
    """Restore navigation bar and clear immersive policy."""
    restore_gesture_hint_bar(adb_path, device)
    _adb_shell(adb_path, device, "settings", "put", "global", "policy_control", "null")
    _adb_shell(adb_path, device, "cmd", "window", "set-hide-nav-bar", "false")


def relaunch_app(adb_path: str, device: str | None, package: str) -> None:
    """Force-stop and relaunch so immersive nav policy applies."""
    _adb_shell(adb_path, device, "am", "force-stop", package)
    cmd = [adb_path]
    if device:
        cmd.extend(["-s", device])
    cmd.extend(
        [
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ]
    )
    subprocess.run(cmd, check=False, capture_output=True)
