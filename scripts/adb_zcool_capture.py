#!/usr/bin/env python3
"""Zcool home / recommend feed capture via ADB screencap + row-aligned scroll."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from adb_util import (
    default_device_id,
    hide_gesture_hint_bar,
    hide_system_nav_bar,
    relaunch_app,
    resolve_adb_path,
    restore_gesture_hint_bar,
    restore_system_nav_bar,
)

THUMB_W = 160
THUMB_H = 90


def scene_signature(img: Image.Image) -> np.ndarray:
    gray = img.convert("L")
    gray = gray.resize((THUMB_W, THUMB_H), Image.Resampling.BILINEAR)
    return np.asarray(gray, dtype=np.float32)


def scene_signature_feed(img: Image.Image, margins: dict) -> np.ndarray:
    gray = img.convert("L")
    w, h = gray.size
    top_y = int(h * float(margins.get("top", 0.265)))
    bottom_y = int(h * float(margins.get("bottom", 0.865)))
    crop = gray.crop((0, top_y, w, bottom_y))
    crop = crop.resize((THUMB_W, THUMB_H), Image.Resampling.BILINEAR)
    return np.asarray(crop, dtype=np.float32)


def signature_from_path(path: Path, margins: dict | None = None) -> np.ndarray | None:
    try:
        with Image.open(path) as img:
            if margins:
                return scene_signature_feed(img, margins)
            return scene_signature(img)
    except OSError:
        return None


def similarity(left: np.ndarray, right: np.ndarray) -> float:
    diff = np.abs(left - right)
    return 1.0 - float(np.mean(diff)) / 255.0


def safe_unlink(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def crop_system_gesture_bar(path: Path, bottom_ratio: float) -> int:
    """Crop thin system gesture bar from bottom of screenshot. Returns pixels removed."""
    if bottom_ratio <= 0:
        return 0
    try:
        with Image.open(path) as img:
            w, h = img.size
            strip = max(1, int(h * bottom_ratio))
            if strip >= h:
                return 0
            cropped = img.crop((0, 0, w, h - strip))
            cropped.save(path)
            return strip
    except OSError:
        return 0


@dataclass
class AdbDevice:
    device: str | None = None
    tap_delay_ms: int = 400
    adb_path: str = field(default_factory=resolve_adb_path)

    def __post_init__(self) -> None:
        if not self.device:
            self.device = default_device_id(self.adb_path)

    def _adb(self, *args: str) -> subprocess.CompletedProcess[str]:
        cmd = [self.adb_path]
        if self.device:
            cmd.extend(["-s", self.device])
        cmd.extend(args)
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    def _shell(self, *args: str) -> None:
        self._adb("shell", *args)

    def sleep_ms(self, ms: int) -> None:
        if ms > 0:
            time.sleep(ms / 1000.0)

    @property
    def size(self) -> tuple[int, int]:
        proc = self._adb("shell", "wm", "size")
        text = proc.stdout or proc.stderr or ""
        for line in text.splitlines():
            if "size:" in line.lower():
                part = line.split(":")[-1].strip()
                if "x" in part:
                    w_str, h_str = part.split("x", 1)
                    return int(w_str), int(h_str)
        raise RuntimeError(f"Could not parse screen size from: {text!r}")

    @staticmethod
    def parse_point(point: str, width: int, height: int) -> tuple[int, int]:
        x_part, y_part = [p.strip() for p in point.split(",", 1)]
        x = int(float(x_part.rstrip("%")) / 100.0 * width)
        y = int(float(y_part.rstrip("%")) / 100.0 * height)
        return x, y

    def tap_point(self, point: str) -> None:
        x, y = self.parse_point(point, *self.size)
        self._shell("input", "tap", str(x), str(y))
        self.sleep_ms(self.tap_delay_ms)

    def swipe_points(self, start: str, end: str, duration_ms: int) -> None:
        w, h = self.size
        x1, y1 = self.parse_point(start, w, h)
        x2, y2 = self.parse_point(end, w, h)
        self._shell(
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        )

    def screencap(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = [self.adb_path]
        if self.device:
            cmd.extend(["-s", self.device])
        cmd.extend(["exec-out", "screencap", "-p"])
        with dest.open("wb") as fp:
            subprocess.run(cmd, check=True, stdout=fp, timeout=30)


@dataclass
class ShotWriter:
    adb: AdbDevice
    shots_dir: Path
    prefix: str
    duplicate_threshold: float
    margins: dict
    crop_gesture_ratio: float = 0.0
    skip_deduplication: bool = False
    seq: int = 0
    skipped_duplicates: int = 0
    last_sig: np.ndarray | None = None
    paths: list[Path] = field(default_factory=list)

    def _sig(self, path: Path) -> np.ndarray | None:
        return signature_from_path(path, self.margins)

    def capture(self, label: str) -> tuple[Path | None, bool]:
        safe_label = re.sub(r"[^\w\-]+", "_", label).strip("_") or "shot"
        filename = f"{self.prefix}_{self.seq:05d}_{safe_label}.png"
        dest = self.shots_dir / filename
        self.adb.screencap(dest)
        if self.crop_gesture_ratio > 0:
            crop_system_gesture_bar(dest, self.crop_gesture_ratio)

        sig = self._sig(dest)
        is_duplicate = False
        if not self.skip_deduplication and sig is not None and self.last_sig is not None:
            is_duplicate = similarity(sig, self.last_sig) >= self.duplicate_threshold

        if is_duplicate:
            if not safe_unlink(dest):
                self.paths.append(dest)
                self.seq += 1
                self.last_sig = sig
                return dest, True
            self.skipped_duplicates += 1
            return None, True

        self.paths.append(dest)
        self.seq += 1
        if sig is not None:
            self.last_sig = sig
        return dest, False

    def feed_similarity_to_last(self, path: Path) -> float | None:
        sig = self._sig(path)
        if sig is None or self.last_sig is None:
            return None
        return similarity(sig, self.last_sig)


def navigate_to_home_subtab(adb: AdbDevice, nav: dict, subtab_point: str) -> None:
    adb.tap_point(nav["home_tab"])
    adb.sleep_ms(nav.get("tap_delay_ms", 400))
    adb.tap_point(subtab_point)
    adb.sleep_ms(nav.get("tap_delay_ms", 400))


def navigate_to_recommend(adb: AdbDevice, nav: dict) -> None:
    navigate_to_home_subtab(adb, nav, nav["recommend_tab"])


def apply_tab_profile(
    cfg: dict,
    tab: str,
) -> tuple[dict, dict, str, str, str, str, str | None]:
    scroll = dict(cfg["scroll"])
    margins = dict(cfg.get("feed_margins", {}))
    capture_cfg = cfg["capture"]
    prefix = capture_cfg["prefix"]
    flow_name = "home_recommend_scroll"
    subtab_point = cfg["navigation"].get("recommend_tab", "35%, 27%")
    mode = "feed_scroll"
    bottom_tab: str | None = None

    tabs = cfg.get("tabs", {})
    if tab in tabs:
        profile = tabs[tab]
        prefix = profile.get("prefix", prefix)
        flow_name = profile.get("flow", f"home_{tab}_scroll")
        subtab_point = profile.get("point", subtab_point)
        mode = profile.get("mode", "feed_scroll")
        bottom_tab = profile.get("bottom_tab")
        scroll.update(profile.get("scroll", {}))
        margins.update(profile.get("feed_margins", {}))

    return scroll, margins, prefix, flow_name, subtab_point, mode, bottom_tab


def navigate_to_bottom_tab(adb: AdbDevice, nav: dict, bottom_tab: str) -> None:
    adb.tap_point(bottom_tab)
    adb.sleep_ms(nav.get("tap_delay_ms", 400))


def video_swipe_next(adb: AdbDevice, scroll: dict) -> None:
    """Swipe down on video feed to load the next full-screen video."""
    duration = int(scroll.get("fling_duration_ms", scroll["duration_ms"]))
    adb.swipe_points(scroll["start"], scroll["end"], duration)
    adb.sleep_ms(int(scroll.get("post_swipe_delay_ms", 150)))


def wait_before_video_capture(adb: AdbDevice, scroll: dict) -> None:
    """Wait for the next video frame to settle after a swipe."""
    delay_ms = int(scroll.get("pre_capture_delay_ms", 1000))
    if delay_ms > 0:
        adb.sleep_ms(delay_ms)


def run_video_feed_capture(
    output_dir: Path,
    cfg: dict,
    device: str | None,
    skip_nav: bool,
    count: int | None,
    until_bottom: bool,
    navigate: bool,
    tab: str,
    scroll: dict,
    margins: dict,
    prefix: str,
    flow_name: str,
    bottom_tab: str | None,
    capture_cfg: dict,
    bottom_cfg: dict,
) -> dict:
    nav = cfg["navigation"]
    package = cfg.get("package", "com.zcool.community")
    hide_nav_bar = bool(capture_cfg.get("hide_system_nav_bar", False))
    hide_gesture_hint = bool(capture_cfg.get("hide_gesture_hint", False))
    gesture_hint_use_overlay = bool(capture_cfg.get("gesture_hint_use_overlay", False))
    relaunch_for_nav_bar = bool(capture_cfg.get("relaunch_for_nav_bar", False))
    crop_gesture = bool(capture_cfg.get("crop_system_gesture_bar", False))
    crop_gesture_ratio = float(capture_cfg.get("crop_system_gesture_ratio", 0.028))
    skip_navigation = (skip_nav or bool(capture_cfg.get("skip_navigation", True))) and not navigate
    video_profile = cfg.get("tabs", {}).get(tab, {})
    skip_dedup = bool(
        video_profile.get("skip_deduplication", scroll.get("skip_deduplication", True))
    )
    threshold = float(capture_cfg.get("duplicate_threshold", scroll.get("duplicate_threshold", 0.92)))
    progress_every = int(bottom_cfg.get("progress_every", 25))
    max_until_bottom = int(bottom_cfg.get("max_shots", 5000))
    stop_after_dupes = int(bottom_cfg.get("stop_after_consecutive_duplicates", 3))

    if until_bottom:
        target = count if count is not None else max_until_bottom
    else:
        target = count if count is not None else int(capture_cfg["target_count"])

    adb_path = resolve_adb_path()
    adb = AdbDevice(device=device, tap_delay_ms=int(nav.get("tap_delay_ms", 400)), adb_path=adb_path)
    shots_dir = output_dir
    shots_dir.mkdir(parents=True, exist_ok=True)
    probe_path = shots_dir / "_video_advance_probe.png"

    saved = 0
    swipe_count = 0
    consecutive_stuck = 0
    reached_end = False
    started = time.monotonic()
    nav_bar_hidden = False
    gesture_hint_hidden = False
    mode_label = "until_bottom" if until_bottom else "fixed_count"

    writer = ShotWriter(
        adb=adb,
        shots_dir=shots_dir,
        prefix=prefix,
        duplicate_threshold=threshold,
        margins=margins,
        crop_gesture_ratio=crop_gesture_ratio if crop_gesture else 0.0,
        skip_deduplication=skip_dedup,
    )

    try:
        if hide_gesture_hint:
            hide_gesture_hint_bar(adb_path, adb.device, use_overlay=gesture_hint_use_overlay)
            adb.sleep_ms(400)
            gesture_hint_hidden = True

        if hide_nav_bar:
            hide_system_nav_bar(adb_path, adb.device, package)
            if relaunch_for_nav_bar:
                relaunch_app(adb_path, adb.device, package)
                adb.sleep_ms(800)
            else:
                adb.sleep_ms(200)
            nav_bar_hidden = True

        if not skip_navigation and bottom_tab:
            navigate_to_bottom_tab(adb, nav, bottom_tab)
            adb.sleep_ms(int(scroll.get("post_swipe_delay_ms", 1000)))
        else:
            initial_delay = int(scroll.get("initial_capture_delay_ms", 500))
            print(
                f"  skip navigation: swipe down, wait {scroll.get('pre_capture_delay_ms', 1000)}ms, capture",
                flush=True,
            )
            if initial_delay > 0:
                adb.sleep_ms(initial_delay)

        while until_bottom or saved < target:
            label = f"{saved:03d}"
            path, _ = writer.capture(label)
            if path is not None:
                saved += 1
                if saved == 1 or saved % progress_every == 0:
                    elapsed = time.monotonic() - started
                    rate = saved / elapsed if elapsed > 0 else 0
                    print(
                        f"  saved {saved} (swipes {swipe_count}, {rate:.1f} shots/s)",
                        flush=True,
                    )

            if not until_bottom and saved >= target:
                break
            if until_bottom and saved >= target:
                break

            before_sig: np.ndarray | None = None
            if until_bottom:
                adb.screencap(probe_path)
                before_sig = signature_from_path(probe_path, margins)

            video_swipe_next(adb, scroll)
            swipe_count += 1
            wait_before_video_capture(adb, scroll)

            if until_bottom and before_sig is not None:
                adb.screencap(probe_path)
                after_sig = signature_from_path(probe_path, margins)
                if after_sig is not None:
                    sim = similarity(after_sig, before_sig)
                    if sim >= float(scroll.get("advance_change_threshold", 0.88)):
                        consecutive_stuck += 1
                        if consecutive_stuck >= stop_after_dupes:
                            print("  reached end: video feed unchanged", flush=True)
                            reached_end = True
                            break
                    else:
                        consecutive_stuck = 0

    finally:
        safe_unlink(probe_path)
        if gesture_hint_hidden or nav_bar_hidden:
            restore_system_nav_bar(adb_path, adb.device)

    elapsed_sec = round(time.monotonic() - started, 1)
    report = {
        "app": "zcool",
        "tab": tab,
        "flow": flow_name,
        "mode": mode_label,
        "capture_style": "video_feed",
        "target_count": target,
        "saved": saved,
        "skipped_duplicates": writer.skipped_duplicates,
        "swipe_attempts": swipe_count,
        "reached_bottom": reached_end,
        "duration_seconds": elapsed_sec,
        "screenshots": [p.name for p in writer.paths],
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    if saved > 0 and elapsed_sec > 0:
        report["seconds_per_screenshot"] = round(elapsed_sec / saved, 2)
    (output_dir / "capture_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def text_ink_rows(gray_band: np.ndarray) -> np.ndarray:
    if gray_band.size == 0:
        return np.array([])
    return 255.0 - gray_band.mean(axis=1)


def cut_line_at_top(ink: np.ndarray) -> bool:
    if ink.size < 18:
        return False
    top = ink[:3].mean()
    gap = ink[3:7].mean()
    body = ink[7:16].mean()
    if top < 24 or body < 18:
        return False
    return gap < top * 0.32 and gap < body * 0.32 and top > body * 0.85


def feed_top_clipped(path: Path, margins: dict) -> bool:
    try:
        with Image.open(path) as img:
            gray = np.asarray(img.convert("L"), dtype=np.float32)
    except OSError:
        return False
    h = gray.shape[0]
    top_y = int(h * float(margins.get("top", 0.265)))
    band_h = max(32, int(h * float(margins.get("band_ratio", 0.055))))
    top_band = gray[top_y : top_y + band_h, :]
    return cut_line_at_top(text_ink_rows(top_band))


def scroll_to_top(adb: AdbDevice, scroll: dict) -> None:
    start = scroll.get("scroll_to_top_start", "50%, 28%")
    end = scroll.get("scroll_to_top_end", "50%, 78%")
    duration = int(scroll.get("scroll_to_top_duration_ms", 200))
    repeats = int(scroll.get("scroll_to_top_repeats", 8))
    for _ in range(repeats):
        adb.swipe_points(start, end, duration)
    adb.sleep_ms(int(scroll.get("post_swipe_delay_ms", 350)))


def feed_swipe(adb: AdbDevice, scroll: dict, kind: str = "main") -> None:
    if kind == "nudge":
        adb.swipe_points(
            scroll["nudge_start"],
            scroll["nudge_end"],
            int(scroll["nudge_duration_ms"]),
        )
    else:
        adb.swipe_points(scroll["start"], scroll["end"], int(scroll["duration_ms"]))
    adb.sleep_ms(int(scroll.get("post_swipe_delay_ms", 300)))
    pre_capture_ms = int(scroll.get("pre_capture_delay_ms", 0))
    if pre_capture_ms > 0:
        adb.sleep_ms(pre_capture_ms)


def swipe_until_clean_top(
    adb: AdbDevice,
    scroll: dict,
    margins: dict,
    temp_dir: Path,
) -> None:
    max_nudges = int(scroll.get("max_nudges", 6))
    temp = temp_dir / "_probe.png"
    for _ in range(max_nudges):
        adb.screencap(temp)
        if not feed_top_clipped(temp, margins):
            return
        feed_swipe(adb, scroll, kind="nudge")
    feed_swipe(adb, scroll, kind="main")
    for _ in range(max_nudges):
        adb.screencap(temp)
        if not feed_top_clipped(temp, margins):
            return
        feed_swipe(adb, scroll, kind="nudge")


def scroll_feed(
    adb: AdbDevice,
    scroll: dict,
    margins: dict,
    probe_dir: Path,
) -> None:
    feed_swipe(adb, scroll, kind="main")
    swipe_until_clean_top(adb, scroll, margins, probe_dir)


def try_reject_clipped(
    path: Path,
    writer: ShotWriter,
    margins: dict,
    adb: AdbDevice,
    scroll: dict,
    probe_dir: Path,
) -> bool:
    """Return True if frame was clipped and rejected (caller should retry scroll)."""
    if not feed_top_clipped(path, margins):
        return False
    clipped_name = path.name
    safe_unlink(path)
    writer.paths.pop()
    writer.seq -= 1
    if writer.paths:
        writer.last_sig = writer._sig(writer.paths[-1])
    else:
        writer.last_sig = None
    print(f"  rejected clipped top: {clipped_name}", flush=True)
    scroll_feed(adb, scroll, margins, probe_dir)
    return True


def confirm_bottom_stuck(
    writer: ShotWriter,
    adb: AdbDevice,
    scroll: dict,
    margins: dict,
    probe_dir: Path,
    bottom_threshold: float,
    extra_swipes: int,
) -> bool:
    """True when extra swipes cannot change feed content (really at bottom)."""
    temp = probe_dir / "_bottom_probe.png"
    for _ in range(extra_swipes):
        scroll_feed(adb, scroll, margins, probe_dir)
        adb.screencap(temp)
        sim = writer.feed_similarity_to_last(temp)
        if sim is None or sim < bottom_threshold:
            return False
    return True


def run_capture(
    output_dir: Path,
    config_path: Path,
    device: str | None,
    skip_nav: bool,
    count: int | None,
    until_bottom: bool = False,
    navigate: bool = False,
    tab: str = "recommend",
) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    nav = cfg["navigation"]
    capture_cfg = cfg["capture"]
    bottom_cfg = capture_cfg.get("until_bottom", {})
    scroll, margins, prefix, flow_name, subtab_point, tab_mode, bottom_tab = apply_tab_profile(
        cfg, tab
    )

    if tab_mode == "video_feed":
        return run_video_feed_capture(
            output_dir=output_dir,
            cfg=cfg,
            device=device,
            skip_nav=skip_nav,
            count=count,
            until_bottom=until_bottom,
            navigate=navigate,
            tab=tab,
            scroll=scroll,
            margins=margins,
            prefix=prefix,
            flow_name=flow_name,
            bottom_tab=bottom_tab,
            capture_cfg=capture_cfg,
            bottom_cfg=bottom_cfg,
        )

    package = cfg.get("package", "com.zcool.community")
    hide_nav_bar = bool(capture_cfg.get("hide_system_nav_bar", False))
    hide_gesture_hint = bool(capture_cfg.get("hide_gesture_hint", False))
    gesture_hint_use_overlay = bool(capture_cfg.get("gesture_hint_use_overlay", False))
    relaunch_for_nav_bar = bool(capture_cfg.get("relaunch_for_nav_bar", False))
    crop_gesture = bool(capture_cfg.get("crop_system_gesture_bar", False))
    crop_gesture_ratio = float(capture_cfg.get("crop_system_gesture_ratio", 0.028))
    if crop_gesture and crop_gesture_ratio <= 0:
        crop_gesture_ratio = 0.028
    skip_navigation = (skip_nav or bool(capture_cfg.get("skip_navigation", True))) and not navigate
    scroll_to_top_on_start = bool(capture_cfg.get("scroll_to_top_on_start", False))

    threshold = float(capture_cfg["duplicate_threshold"])
    stop_after_dupes = int(bottom_cfg.get("stop_after_consecutive_duplicates", 3))
    bottom_extra_swipes = int(bottom_cfg.get("bottom_extra_swipes", 4))
    bottom_threshold = float(bottom_cfg.get("bottom_threshold", 0.985))
    progress_every = int(bottom_cfg.get("progress_every", 25))
    max_until_bottom = int(bottom_cfg.get("max_shots", 5000))

    if until_bottom:
        target = count if count is not None else max_until_bottom
        max_attempts = target * 4
    else:
        target = count if count is not None else int(capture_cfg["target_count"])
        max_attempts = int(capture_cfg["max_attempts"])

    adb_path = resolve_adb_path()
    adb = AdbDevice(device=device, tap_delay_ms=int(nav.get("tap_delay_ms", 400)), adb_path=adb_path)
    shots_dir = output_dir
    shots_dir.mkdir(parents=True, exist_ok=True)
    probe_dir = output_dir / "_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    attempts = 0
    extra_on_dup = bool(scroll.get("extra_swipe_on_duplicate", True))
    clipped_rejected = 0
    consecutive_bottom = 0
    mode = "until_bottom" if until_bottom else "fixed_count"
    started = time.monotonic()
    nav_bar_hidden = False
    gesture_hint_hidden = False

    try:
        if hide_gesture_hint:
            hide_gesture_hint_bar(adb_path, adb.device, use_overlay=gesture_hint_use_overlay)
            adb.sleep_ms(400)
            gesture_hint_hidden = True
            print("  gesture hint bar hidden (ADB, no crop)", flush=True)

        if hide_nav_bar:
            hide_system_nav_bar(adb_path, adb.device, package)
            if relaunch_for_nav_bar:
                relaunch_app(adb_path, adb.device, package)
                adb.sleep_ms(800)
            else:
                adb.sleep_ms(200)
            nav_bar_hidden = True
            print("  system nav bar: immersive policy only (screen layout unchanged)", flush=True)
        if crop_gesture:
            print(
                f"  screenshots: crop system gesture bar (bottom {crop_gesture_ratio:.1%})",
                flush=True,
            )

        if not skip_navigation:
            navigate_to_home_subtab(adb, nav, subtab_point)
            scroll_to_top(adb, scroll)
        elif scroll_to_top_on_start:
            if until_bottom:
                scroll_cfg = dict(scroll)
                scroll_cfg["scroll_to_top_repeats"] = int(
                    bottom_cfg.get(
                        "scroll_to_top_repeats",
                        scroll.get("scroll_to_top_repeats", 8) * 3,
                    )
                )
                scroll_to_top(adb, scroll_cfg)
            else:
                scroll_to_top(adb, scroll)
        else:
            initial_delay = int(scroll.get("initial_capture_delay_ms", 0))
            print("  skip navigation: screenshot current screen", flush=True)
            if initial_delay > 0:
                adb.sleep_ms(initial_delay)

        writer = ShotWriter(
            adb=adb,
            shots_dir=shots_dir,
            prefix=prefix,
            duplicate_threshold=threshold,
            margins=margins,
            crop_gesture_ratio=crop_gesture_ratio if crop_gesture else 0.0,
        )

        while saved < target and attempts < max_attempts:
            label = "overview" if saved == 0 else f"scroll_{saved:05d}"
            if saved > 0:
                scroll_feed(adb, scroll, margins, probe_dir)
                attempts += 1

            path, is_dup = writer.capture(label)
            if path is not None and try_reject_clipped(
                path, writer, margins, adb, scroll, probe_dir
            ):
                clipped_rejected += 1
                attempts += 1
                continue

            if path is not None:
                saved += 1
                consecutive_bottom = 0
                if until_bottom:
                    if saved == 1 or saved % progress_every == 0:
                        elapsed = time.monotonic() - started
                        rate = saved / elapsed if elapsed > 0 else 0
                        print(
                            f"  saved {saved} (scroll attempts {attempts}, "
                            f"{rate:.1f} shots/s, dup skipped {writer.skipped_duplicates})",
                            flush=True,
                        )
                else:
                    print(f"  saved {saved}/{target}: {path.name}", flush=True)
            elif is_dup and until_bottom and saved > 0:
                if confirm_bottom_stuck(
                    writer,
                    adb,
                    scroll,
                    margins,
                    probe_dir,
                    bottom_threshold,
                    bottom_extra_swipes,
                ):
                    consecutive_bottom += 1
                    attempts += bottom_extra_swipes
                    if consecutive_bottom >= stop_after_dupes:
                        print(
                            f"  reached bottom: feed unchanged after "
                            f"{bottom_extra_swipes} extra swipes "
                            f"({stop_after_dupes} cycles)",
                            flush=True,
                        )
                        break
                else:
                    attempts += bottom_extra_swipes
                    path, is_dup = writer.capture(label)
                    if path is not None and try_reject_clipped(
                        path, writer, margins, adb, scroll, probe_dir
                    ):
                        clipped_rejected += 1
                        attempts += 1
                        continue
                    if path is not None:
                        saved += 1
                        consecutive_bottom = 0
                        if saved == 1 or saved % progress_every == 0:
                            elapsed = time.monotonic() - started
                            rate = saved / elapsed if elapsed > 0 else 0
                            print(
                                f"  saved {saved} (scroll attempts {attempts}, "
                                f"{rate:.1f} shots/s, dup skipped {writer.skipped_duplicates})",
                                flush=True,
                            )

            if saved >= target and not until_bottom:
                break

            if is_dup and extra_on_dup and not until_bottom:
                print("  duplicate frame, extra scroll", flush=True)
                scroll_feed(adb, scroll, margins, probe_dir)
                attempts += 1

    finally:
        if gesture_hint_hidden or nav_bar_hidden:
            restore_system_nav_bar(adb_path, adb.device)
            print("  navigation bar settings restored", flush=True)

    elapsed_sec = round(time.monotonic() - started, 1)
    report = {
        "app": "zcool",
        "tab": tab,
        "flow": flow_name,
        "mode": mode,
        "target_count": target,
        "saved": saved,
        "skipped_duplicates": writer.skipped_duplicates,
        "clipped_rejected": clipped_rejected,
        "scroll_attempts": attempts,
        "reached_bottom": until_bottom and consecutive_bottom >= stop_after_dupes,
        "duration_seconds": elapsed_sec,
        "screenshots": [p.name for p in writer.paths],
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    if saved > 0 and elapsed_sec > 0:
        report["seconds_per_screenshot"] = round(elapsed_sec / saved, 2)
    (output_dir / "capture_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Zcool home recommend ADB capture")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory for PNG files",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_ROOT / "config" / "zcool_adb.json",
    )
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--skip-nav",
        action="store_true",
        help="Alias for default: do not tap tabs or scroll to top",
    )
    parser.add_argument(
        "--nav",
        action="store_true",
        help="Tap 首页/推荐 and scroll to top before capture",
    )
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument(
        "--tab",
        default="recommend",
        choices=["recommend", "first_pick", "video", "competition", "online_activity"],
        help="Home sub-tab profile (default: recommend)",
    )
    parser.add_argument(
        "--until-bottom",
        action="store_true",
        help="Scroll until feed bottom (consecutive duplicate frames), up to max_shots",
    )
    args = parser.parse_args()

    if args.output is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = _ROOT / "screenshots" / "zcool" / stamp

    print(f"Output: {args.output}", flush=True)
    try:
        adb_path = resolve_adb_path()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"ADB: {adb_path}", flush=True)
    report = run_capture(
        output_dir=args.output,
        config_path=args.config,
        device=args.device,
        skip_nav=args.skip_nav,
        count=args.count,
        until_bottom=args.until_bottom,
        navigate=args.nav,
        tab=args.tab,
    )
    if report.get("mode") == "until_bottom":
        print(
            f"Done: {report['saved']} unique screenshots "
            f"({report['duration_seconds']}s, "
            f"{report.get('seconds_per_screenshot', '?')}s/shot), "
            f"bottom={'yes' if report.get('reached_bottom') else 'cap/stopped'}, "
            f"{report['skipped_duplicates']} dup skipped",
            flush=True,
        )
        return 0 if report["saved"] > 0 else 1
    print(
        f"Done: {report['saved']}/{report['target_count']} screenshots, "
        f"{report['skipped_duplicates']} duplicates skipped",
        flush=True,
    )
    return 0 if report["saved"] >= report["target_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
