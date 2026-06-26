#!/usr/bin/env python3
"""河南日报 新闻-时政: scroll down + screenshot."""

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

from adb_taptap_capture import AdbDevice, ShotWriter, capture_scroll_strategy
from henan_daily_first_alignment import align_first_frame, first_frame_alignment_cfg
from image_similarity import signature_from_path

PAGE_LABEL = "新闻时政"
PREFIX = "hnrb_news_sz"
FOLDER_TAG = "新闻时政"
MARKER_NAME = "latest_henan_news_politics_output_dir.txt"
PACKAGE = "com.hnzx.hnrb"
CAPTURE_KEY = "news_politics_capture"


def page_has_content(adb: AdbDevice, *, top_ratio: float = 0.18, bottom_ratio: float = 0.90, min_std: float = 16.0) -> bool:
    temp = Path(tempfile.gettempdir()) / f"hnrb_probe_{time.time_ns()}.png"
    try:
        adb.screencap(temp)
        img = cv2.imread(str(temp))
        if img is None:
            return False
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        region = gray[int(top_ratio * h) : int(bottom_ratio * h), int(0.06 * w) : int(0.94 * w)]
        return float(np.std(region)) >= min_std
    finally:
        temp.unlink(missing_ok=True)


def wait_for_page_content(adb: AdbDevice, timeout_ms: int = 10000) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if page_has_content(adb):
            print(f"{PAGE_LABEL} page content detected.", flush=True)
            adb.sleep_ms(150)
            return True
        adb.sleep_ms(350)
    print(f"Warning: {PAGE_LABEL} page content not detected before timeout.", flush=True)
    return False


def app_in_foreground(adb: AdbDevice) -> bool:
    proc = subprocess.run(
        ["adb", "-s", adb.device, "shell", "dumpsys", "window"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    focus = proc.stdout or ""
    return PACKAGE in focus


def load_configs() -> tuple[dict, dict, dict, dict, dict]:
    adb_cfg = yaml.safe_load((_ROOT / "config" / "henan_daily_adb.yaml").read_text(encoding="utf-8"))
    timing = dict(adb_cfg.get("adb_capture") or {})
    timing["capture_defaults"] = {"scroll_stop_after_dupes": 3}
    scroll_cfg = dict(adb_cfg.get(CAPTURE_KEY) or {})
    align_source = dict(adb_cfg)
    if scroll_cfg.get("first_frame_alignment") is not None:
        align_source["first_frame_alignment"] = scroll_cfg["first_frame_alignment"]
    align_cfg = first_frame_alignment_cfg(align_source)
    tabs = {
        "feed_swipe": dict(scroll_cfg.get("feed_swipe") or adb_cfg["feed_swipe"]),
        "scroll_to_top": dict(adb_cfg["scroll_to_top"]),
        "scroll_swipes": int(scroll_cfg.get("max_scroll_swipes", 500)),
    }
    return tabs, timing, scroll_cfg, align_cfg, adb_cfg


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
    return {
        "seq": seq,
        "scroll_n": scroll_n,
        "last_path": last,
        "last_sig": signature_from_path(last),
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
    return _ROOT / "screenshots" / "henan_daily" / f"pilot_{mode}_{stamp}_{FOLDER_TAG}"


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Henan Daily {PAGE_LABEL} scroll capture.")
    parser.add_argument("--shots", type=int, default=None)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--until-bottom", action="store_true")
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--device", default=None)
    parser.add_argument("--skip-nav", action="store_true", help="Already on 新闻-时政 page")
    parser.add_argument("--resume-dir", default=None)
    args = parser.parse_args()

    if not args.full and not args.until_bottom and (args.shots is None or args.shots < 1):
        raise SystemExit("Provide --shots N, --full, or --until-bottom")

    tabs, timing, scroll_cfg, align_cfg, _adb_cfg = load_configs()
    output_dir = resolve_output_dir(args)
    shots_dir = output_dir / "adb_raw" / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    resume = infer_resume_state(shots_dir, args.prefix) if args.resume_dir else None

    adb = AdbDevice(args.device, tap_delay_ms=int(timing.get("tap_delay_ms", 150)))
    post_swipe_delay_ms = int(timing.get("post_swipe_delay_ms", 200))

    capture_overrides: dict = {"feed_alignment": False}
    if args.until_bottom or args.full or args.resume_dir:
        capture_overrides["scroll_stop_after_dupes"] = int(scroll_cfg.get("scroll_stop_after_dupes", 15))
        capture_overrides["duplicate_threshold"] = float(scroll_cfg.get("duplicate_threshold", 0.99))
    if scroll_cfg.get("scroll_bottom_markers"):
        capture_overrides["scroll_bottom_markers"] = list(scroll_cfg["scroll_bottom_markers"])
    if scroll_cfg.get("scroll_loading_stall"):
        capture_overrides["scroll_loading_stall"] = dict(scroll_cfg["scroll_loading_stall"])
    if scroll_cfg.get("footer_detect"):
        capture_overrides["footer_detect"] = dict(scroll_cfg["footer_detect"])
    if scroll_cfg.get("scroll_end_uiautomator") is not None:
        capture_overrides["scroll_end_uiautomator"] = bool(scroll_cfg["scroll_end_uiautomator"])
    if scroll_cfg.get("feed_page_guard"):
        capture_overrides["feed_page_guard"] = dict(scroll_cfg["feed_page_guard"])
    if scroll_cfg.get("feed_swipe"):
        capture_overrides["feed_swipe"] = dict(scroll_cfg["feed_swipe"])

    swipe_batch = int(scroll_cfg.get("max_scroll_swipes", 10000))
    if args.until_bottom:
        dup_threshold = float(capture_overrides.get("duplicate_threshold", 0.99))
        skip_dupes = True
        max_swipes = resume["scroll_n"] + swipe_batch if resume else swipe_batch
    elif args.full:
        dup_threshold = float(capture_overrides.get("duplicate_threshold", 0.99))
        skip_dupes = bool(timing.get("skip_duplicate_saves", False))
        max_swipes = swipe_batch
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

    print(f"Device: {adb.device}, screen: {adb.size[0]}x{adb.size[1]}", flush=True)
    if not app_in_foreground(adb):
        print(f"Warning: {PACKAGE} may not be in foreground. Open 新闻-时政 and retry.", flush=True)
    wait_for_page_content(adb)

    if args.until_bottom:
        mode = (
            f"until bottom (scroll {start_scroll_index}..{max_swipes}, "
            f"stop at bottom marker / loading stall "
            f"{capture_overrides.get('scroll_loading_stall', {}).get('stop_after', 3)}x / "
            f"{capture_overrides.get('scroll_stop_after_dupes', 8)} identical frames)"
        )
    elif args.full:
        mode = f"full scroll (max {max_swipes} swipes)"
    else:
        mode = f"{args.shots} screenshot(s)"
    print(f"Capturing {PAGE_LABEL} {mode}...", flush=True)

    if not resume:
        if align_cfg.get("enabled", True):
            align_first_frame(adb, scroll_to_top=tabs["scroll_to_top"], cfg=align_cfg)
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

    total = len(list(shots_dir.glob(f"{args.prefix}_*.png")))
    print(f"Saved {len(writer.paths)} new file(s), {total} total -> {shots_dir}", flush=True)
    for path in writer.paths[-5:]:
        print(f"  {path.name}", flush=True)
    print(f"OUTPUT_DIR={output_dir}", flush=True)
    marker = _ROOT / "screenshots" / "henan_daily" / MARKER_NAME
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(output_dir), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
