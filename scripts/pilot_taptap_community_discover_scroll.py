#!/usr/bin/env python3
"""TapTap 社区-发现 (b03_t02): scroll down + screenshot until bottom."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from adb_taptap_capture import AdbDevice, ShotWriter, capture_scroll_strategy, load_settings, wait_for_scroll_loading_done
from image_similarity import signature_from_path

PAGE_LABEL = "社区发现"
BOTTOM_TAB_ID = "b03"
TOP_TAB_ID = "t02"
PREFIX = "b03_t02"
FOLDER_TAG = "社区发现"
MARKER_NAME = "latest_community_discover_output_dir.txt"


def wait_for_taptap_ready(
    adb: AdbDevice,
    timeout_sec: int = 120,
    *,
    allow_content_fallback: bool = True,
) -> bool:
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
        if allow_content_fallback and page_has_content(adb):
            print("TapTap page content visible (continuing despite splash focus).", flush=True)
            adb.sleep_ms(400)
            return True
        time.sleep(2)
    if allow_content_fallback and page_has_content(adb):
        print("TapTap page content visible after timeout (continuing).", flush=True)
        return True
    print("Warning: TapTap main UI not detected before timeout.", flush=True)
    return False


def page_has_content(adb: AdbDevice, *, top_ratio: float = 0.22, bottom_ratio: float = 0.90, min_std: float = 18.0) -> bool:
    temp = Path(tempfile.gettempdir()) / f"community_discover_probe_{time.time_ns()}.png"
    try:
        adb.screencap(temp)
        img = cv2.imread(str(temp))
        if img is None:
            return False
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        region = gray[int(top_ratio * h) : int(bottom_ratio * h), int(0.08 * w) : int(0.92 * w)]
        return float(np.std(region)) >= min_std
    finally:
        temp.unlink(missing_ok=True)


def wait_for_page_content(adb: AdbDevice, timeout_ms: int = 12000) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if page_has_content(adb):
            print(f"{PAGE_LABEL} page content detected.", flush=True)
            adb.sleep_ms(700)
            return True
        adb.sleep_ms(400)
    print(f"Warning: {PAGE_LABEL} page content not detected before timeout.", flush=True)
    return False


def navigate_to_community_discover(adb: AdbDevice, config: dict) -> None:
    bottom = None
    top = None
    for tab in config["bottom_tabs"]:
        if tab["id"] == BOTTOM_TAB_ID:
            bottom = tab
            for child in tab["top_tabs"]:
                if child["id"] == TOP_TAB_ID:
                    top = child
                    break
            break
    if not bottom or not top:
        raise RuntimeError(f"Could not find {BOTTOM_TAB_ID}/{TOP_TAB_ID} in taptap_tabs.yaml")

    adb.tap_point(bottom["point"])
    adb.sleep_ms(350)
    adb.tap_point(top["point"])
    adb.sleep_ms(500)
    print("Navigated: community -> discover", flush=True)
    wait_for_page_content(adb)


def load_scroll_capture_cfg(adb_config: dict) -> dict:
    return dict(adb_config.get("community_discover_capture") or adb_config.get("sharewall_capture") or {})


def infer_resume_state(shots_dir: Path, prefix: str) -> dict | None:
    files = sorted(shots_dir.glob(f"{prefix}_*.png"))
    if not files:
        return None
    last = files[-1]
    match = re.match(rf"^{re.escape(prefix)}_(\d+)_(.+)\.png$", last.name)
    if not match:
        raise ValueError(f"Cannot parse resume filename: {last.name}")
    seq = int(match.group(1)) + 1
    label = match.group(2)
    scroll_n = 0
    scroll_match = re.search(r"scroll_(\d+)", label)
    if scroll_match:
        scroll_n = int(scroll_match.group(1))
    sig = signature_from_path(last)
    return {
        "seq": seq,
        "scroll_n": scroll_n,
        "last_path": last,
        "last_sig": sig,
        "saved_count": len(files),
    }


def resolve_output_dir(args: argparse.Namespace) -> Path:
    if args.resume_dir:
        path = Path(args.resume_dir)
        if not path.is_absolute():
            path = _ROOT / path
        if not path.is_dir():
            raise SystemExit(f"Resume dir not found: {path}")
        return path
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.until_bottom:
        mode = "bottom"
    elif args.full:
        mode = "full"
    else:
        mode = str(args.shots)
    return _ROOT / "screenshots" / "taptap_lite" / f"pilot_{mode}_{stamp}_{FOLDER_TAG}"


def main() -> int:
    parser = argparse.ArgumentParser(description=f"TapTap {PAGE_LABEL} scroll capture.")
    parser.add_argument("--shots", type=int, default=None, help="Total screenshots (1 start + N-1 swipes)")
    parser.add_argument("--full", action="store_true", help="Scroll until duplicate stop (max scroll_swipes)")
    parser.add_argument(
        "--until-bottom",
        action="store_true",
        help="Keep scrolling until bottom marker, dup frames, or max_scroll_swipes batch",
    )
    parser.add_argument("--prefix", default=PREFIX, help="Filename prefix")
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--skip-nav",
        action="store_true",
        help=f"Already on {PAGE_LABEL} tab (skip navigation and long splash wait)",
    )
    parser.add_argument(
        "--resume-dir",
        default=None,
        help="Continue capture in an existing output folder (append new screenshots)",
    )
    args = parser.parse_args()

    if not args.full and not args.until_bottom and (args.shots is None or args.shots < 1):
        raise SystemExit("Provide --shots N, --full, or --until-bottom")

    tabs, _, timing, _ = load_settings(
        _ROOT / "config" / "taptap_tabs.yaml",
        _ROOT / "config" / "taptap_adb.yaml",
        _ROOT / "config" / "taptap_capture_profiles.yaml",
    )
    adb_cfg = yaml.safe_load((_ROOT / "config" / "taptap_adb.yaml").read_text(encoding="utf-8"))
    scroll_cfg = load_scroll_capture_cfg(adb_cfg)

    output_dir = resolve_output_dir(args)
    shots_dir = output_dir / "adb_raw" / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    resume = infer_resume_state(shots_dir, args.prefix) if args.resume_dir else None

    adb = AdbDevice(args.device, tap_delay_ms=int(timing.get("tap_delay_ms", 150)))
    post_swipe_delay_ms = int(timing.get("post_swipe_delay_ms", 0))

    capture_overrides: dict = {"feed_alignment": False}
    if args.until_bottom or args.full or args.resume_dir:
        capture_overrides["scroll_stop_after_dupes"] = int(
            scroll_cfg.get("scroll_stop_after_dupes", 15 if args.until_bottom else 3)
        )
        capture_overrides["duplicate_threshold"] = float(
            scroll_cfg.get("duplicate_threshold", timing.get("duplicate_threshold", 0.95))
        )
    if scroll_cfg.get("scroll_bottom_markers"):
        capture_overrides["scroll_bottom_markers"] = list(scroll_cfg["scroll_bottom_markers"])
    if scroll_cfg.get("footer_detect"):
        capture_overrides["footer_detect"] = dict(scroll_cfg["footer_detect"])
    if scroll_cfg.get("feed_swipe"):
        capture_overrides["feed_swipe"] = dict(scroll_cfg["feed_swipe"])
    if scroll_cfg.get("scroll_loading_markers"):
        capture_overrides["scroll_loading_markers"] = list(scroll_cfg["scroll_loading_markers"])
    if scroll_cfg.get("loading_wait"):
        capture_overrides["loading_wait"] = dict(scroll_cfg["loading_wait"])
    if scroll_cfg.get("loading_detect"):
        capture_overrides["loading_detect"] = dict(scroll_cfg["loading_detect"])

    swipe_batch = int(scroll_cfg.get("max_scroll_swipes", 500))
    if args.until_bottom:
        dup_threshold = float(capture_overrides.get("duplicate_threshold", 0.992))
        skip_dupes = True
        max_swipes = resume["scroll_n"] + swipe_batch if resume else swipe_batch
    elif args.full:
        dup_threshold = float(capture_overrides.get("duplicate_threshold", timing.get("duplicate_threshold", 0.95)))
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

    start_scroll_index = 1
    if resume:
        writer.seq = resume["seq"]
        writer.last_sig = resume["last_sig"]
        start_scroll_index = resume["scroll_n"] + 1
        print(
            f"Resume: {resume['saved_count']} existing file(s), "
            f"continuing from scroll_{start_scroll_index:02d} (seq {writer.seq:03d})",
            flush=True,
        )
        print(f"  last file: {resume['last_path'].name}", flush=True)

    print(f"Device: {adb.device}, screen: {adb.size[0]}x{adb.size[1]}", flush=True)
    if args.skip_nav or args.resume_dir:
        print("Skip-nav: using screen content check only.", flush=True)
        wait_for_page_content(adb, timeout_ms=8000)
    else:
        wait_for_taptap_ready(adb, timeout_sec=30)
        navigate_to_community_discover(adb, tabs)

    if args.until_bottom:
        mode = (
            f"until bottom (scroll {start_scroll_index}..{max_swipes}, "
            f"stop at 「{scroll_cfg.get('scroll_bottom_markers', ['暂无更多'])[0]}」 "
            f"or {capture_overrides.get('scroll_stop_after_dupes', 15)} dupes)"
        )
    elif args.full:
        mode = f"full scroll (max {max_swipes} swipes)"
    else:
        mode = f"{args.shots} screenshot(s)"
    print(f"Capturing {PAGE_LABEL} {mode}...", flush=True)

    if not resume:
        if scroll_cfg.get("scroll_loading_markers"):
            wait_for_scroll_loading_done(
                adb,
                markers=list(scroll_cfg["scroll_loading_markers"]),
                cfg=scroll_cfg.get("loading_wait") or {},
            )
        writer.capture("00_start")
        if args.shots and not args.full and not args.until_bottom:
            max_swipes = max(0, int(args.shots) - 1)

    if max_swipes and start_scroll_index <= max_swipes:
        capture_scroll_strategy(
            adb=adb,
            config=tabs,
            top={"capture": capture_overrides},
            writer=writer,
            post_swipe_delay_ms=post_swipe_delay_ms,
            timing=timing,
            max_swipes=max_swipes,
            include_intro=False,
            start_scroll_index=start_scroll_index,
        )
    elif resume:
        print(f"Resume: nothing to do (start {start_scroll_index} > max {max_swipes}).", flush=True)

    total = len(list(shots_dir.glob(f"{args.prefix}_*.png")))
    print(f"Saved {len(writer.paths)} new file(s), {total} total -> {shots_dir}", flush=True)
    for path in writer.paths[-5:]:
        print(f"  {path.name}", flush=True)
    if len(writer.paths) > 5:
        print(f"  ... ({len(writer.paths)} new files this run)", flush=True)
    print(f"OUTPUT_DIR={output_dir}", flush=True)
    marker = _ROOT / "screenshots" / "taptap_lite" / MARKER_NAME
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(output_dir), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
