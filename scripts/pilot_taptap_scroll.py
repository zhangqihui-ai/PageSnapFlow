#!/usr/bin/env python3
"""Quick pilot: scroll + capture N screenshots on current TapTap screen (no navigation)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from adb_taptap_capture import AdbDevice, ShotWriter, capture_scroll_strategy, load_settings
from taptap_feed_alignment import align_frame, alignment_cfg


def save_aligned_frame(
    *,
    adb: AdbDevice,
    writer: ShotWriter,
    config: dict,
    label: str,
    post_swipe_delay_ms: int,
) -> None:
    cfg = alignment_cfg(config)
    if cfg.get("enabled", False):
        temp, _report = align_frame(
            adb,
            config,
            post_swipe_delay_ms=post_swipe_delay_ms,
            overrides=cfg,
        )
        if temp is not None:
            writer.capture_from_path(temp, label)
            return
    writer.capture(label)


def main() -> int:
    parser = argparse.ArgumentParser(description="TapTap scroll pilot (current screen only).")
    parser.add_argument(
        "--shots",
        type=int,
        default=None,
        help="Fixed screenshot count (1 start + N-1 swipes). Omit with --full.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Scroll until bottom (uses config scroll_swipes max + duplicate stop).",
    )
    parser.add_argument("--prefix", default="b1t1", help="Filename prefix")
    parser.add_argument("--device", default=None)
    args = parser.parse_args()

    if not args.full and (args.shots is None or args.shots < 1):
        raise SystemExit("Provide --shots N or --full")

    tabs, _, timing, _ = load_settings(
        _ROOT / "config" / "taptap_tabs.yaml",
        _ROOT / "config" / "taptap_adb.yaml",
        _ROOT / "config" / "taptap_capture_profiles.yaml",
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "full" if args.full else str(args.shots)
    output_dir = _ROOT / "screenshots" / "taptap_lite" / f"pilot_{label}_{stamp}"
    shots_dir = output_dir / "adb_raw" / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    adb = AdbDevice(args.device, tap_delay_ms=int(timing.get("tap_delay_ms", 150)))
    post_swipe_delay_ms = int(timing.get("post_swipe_delay_ms", 0))
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
    mode = f"full scroll (max {max_swipes} swipes)" if args.full else f"{args.shots} screenshot(s)"
    print(f"Capturing {mode} on current screen (no navigation)...", flush=True)

    save_aligned_frame(
        adb=adb,
        writer=writer,
        config=tabs,
        label="00_start",
        post_swipe_delay_ms=post_swipe_delay_ms,
    )
    if max_swipes:
        capture_scroll_strategy(
            adb=adb,
            config=tabs,
            top={},
            writer=writer,
            post_swipe_delay_ms=post_swipe_delay_ms,
            timing=timing,
            max_swipes=max_swipes,
            include_intro=False,
        )

    print(f"Saved {len(writer.paths)} file(s) -> {shots_dir}", flush=True)
    for path in writer.paths:
        print(f"  {path.name}", flush=True)
    print(f"OUTPUT_DIR={output_dir}", flush=True)
    latest_marker = _ROOT / "screenshots" / "taptap_lite" / "latest_output_dir.txt"
    latest_marker.parent.mkdir(parents=True, exist_ok=True)
    latest_marker.write_text(str(output_dir), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
