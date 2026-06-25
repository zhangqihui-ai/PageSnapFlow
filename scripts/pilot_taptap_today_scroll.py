#!/usr/bin/env python3
"""TapTap Today Games: scroll down + capture with first-game text alignment."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from adb_taptap_capture import AdbDevice, ShotWriter, load_settings
from taptap_today_alignment import align_frame, swipe_today_list, today_alignment_cfg, wait_for_today_list


def wait_for_taptap_ready(adb: AdbDevice, timeout_sec: int = 120) -> bool:
    print(f"Waiting for TapTap main UI (up to {timeout_sec}s)...", flush=True)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        proc = subprocess.run(
            ["adb", "-s", adb.device, "shell", "dumpsys", "window"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        focus = proc.stdout or ""
        if "taptap" in focus.lower() and "SplashAct" not in focus:
            print("TapTap is ready.", flush=True)
            adb.sleep_ms(800)
            return True
        time.sleep(2)
    print("Warning: TapTap main UI not detected before timeout.", flush=True)
    return False


def navigate_to_today_games(adb: AdbDevice, config: dict) -> None:
    bottom = None
    top = None
    for tab in config["bottom_tabs"]:
        if tab["id"] == "b01":
            bottom = tab
            for child in tab["top_tabs"]:
                if child["id"] == "t02":
                    top = child
                    break
            break
    if not bottom or not top:
        raise RuntimeError("Could not find b01/t02 in taptap_tabs.yaml")

    adb.tap_point(bottom["point"])
    adb.sleep_ms(300)
    adb.tap_point(top["point"])
    adb.sleep_ms(500)
    print("Navigated: find_games -> today_games", flush=True)
    wait_for_today_list(adb, config)


def save_aligned_frame(
    *,
    adb: AdbDevice,
    writer: ShotWriter,
    config: dict,
    label: str,
    post_swipe_delay_ms: int,
    align_cfg: dict,
) -> tuple[Path | None, bool]:
    if align_cfg.get("enabled", False):
        temp, _report = align_frame(
            adb,
            config,
            post_swipe_delay_ms=post_swipe_delay_ms,
            overrides=align_cfg,
        )
        if temp is not None:
            return writer.capture_from_path(temp, label)
    return writer.capture(label)


def capture_today_scroll(
    *,
    adb: AdbDevice,
    config: dict,
    writer: ShotWriter,
    post_swipe_delay_ms: int,
    timing: dict,
    max_swipes: int,
    align_cfg: dict,
) -> None:
    defaults = timing.get("capture_defaults", {})
    stop_after_dupes = int(defaults.get("scroll_stop_after_dupes", 3))
    consecutive_dupes = 0

    for n in range(1, max_swipes + 1):
        swipe_today_list(adb, config)
        adb.sleep_ms(post_swipe_delay_ms)
        _, is_dup = save_aligned_frame(
            adb=adb,
            writer=writer,
            config=config,
            label=f"scroll_{n:02d}",
            post_swipe_delay_ms=post_swipe_delay_ms,
            align_cfg=align_cfg,
        )
        if is_dup:
            consecutive_dupes += 1
            if consecutive_dupes >= stop_after_dupes:
                print(f"  scroll: stopped early at {n} ({stop_after_dupes} consecutive duplicates)", flush=True)
                break
        else:
            consecutive_dupes = 0


def main() -> int:
    parser = argparse.ArgumentParser(description="TapTap Today Games scroll capture.")
    parser.add_argument("--shots", type=int, default=None, help="Total screenshots (1 start + N-1 swipes)")
    parser.add_argument("--full", action="store_true", help="Scroll until duplicate stop (max scroll_swipes)")
    parser.add_argument("--prefix", default="b01_t02", help="Filename prefix")
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--skip-nav",
        action="store_true",
        help="Skip navigation (already on Today Games tab)",
    )
    args = parser.parse_args()

    if not args.full and (args.shots is None or args.shots < 1):
        raise SystemExit("Provide --shots N or --full")

    tabs, _, timing, _ = load_settings(
        _ROOT / "config" / "taptap_tabs.yaml",
        _ROOT / "config" / "taptap_adb.yaml",
        _ROOT / "config" / "taptap_capture_profiles.yaml",
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "today_full" if args.full else f"today_{args.shots}"
    output_dir = _ROOT / "screenshots" / "taptap_lite" / f"pilot_{label}_{stamp}"
    shots_dir = output_dir / "adb_raw" / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    adb = AdbDevice(args.device, tap_delay_ms=int(timing.get("tap_delay_ms", 150)))
    post_swipe_delay_ms = int(timing.get("post_swipe_delay_ms", 0))
    align_cfg = today_alignment_cfg(tabs)

    if args.full:
        dup_threshold = float(timing.get("duplicate_threshold", 0.95))
        skip_dupes = bool(timing.get("skip_duplicate_saves", True))
        max_swipes = int(tabs.get("scroll_swipes", 150))
    else:
        dup_threshold = None
        skip_dupes = False
        max_swipes = max(0, int(args.shots) - 1)

    writer = ShotWriter(
        adb=adb,
        shots_dir=shots_dir,
        prefix=args.prefix,
        post_swipe_delay_ms=post_swipe_delay_ms,
        duplicate_threshold=dup_threshold,
        skip_duplicate_saves=skip_dupes,
    )

    print(f"Device: {adb.device}, screen: {adb.size[0]}x{adb.size[1]}", flush=True)
    if args.skip_nav:
        print("Skip-nav: using screen content check only.", flush=True)
        wait_for_today_list(adb, tabs)
    else:
        wait_for_taptap_ready(adb, timeout_sec=30)
        navigate_to_today_games(adb, tabs)

    mode = f"full scroll (max {max_swipes} swipes)" if args.full else f"{args.shots} screenshot(s)"
    print(f"Capturing Today Games {mode} (first-game text aligned)...", flush=True)

    save_aligned_frame(
        adb=adb,
        writer=writer,
        config=tabs,
        label="00_start",
        post_swipe_delay_ms=post_swipe_delay_ms,
        align_cfg=align_cfg,
    )
    if max_swipes:
        capture_today_scroll(
            adb=adb,
            config=tabs,
            writer=writer,
            post_swipe_delay_ms=post_swipe_delay_ms,
            timing=timing,
            max_swipes=max_swipes,
            align_cfg=align_cfg,
        )

    print(f"Saved {len(writer.paths)} file(s) -> {shots_dir}", flush=True)
    for path in writer.paths:
        print(f"  {path.name}", flush=True)
    print(f"OUTPUT_DIR={output_dir}", flush=True)
    latest_marker = _ROOT / "screenshots" / "taptap_lite" / "latest_today_output_dir.txt"
    latest_marker.parent.mkdir(parents=True, exist_ok=True)
    latest_marker.write_text(str(output_dir), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
