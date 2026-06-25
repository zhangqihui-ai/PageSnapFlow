#!/usr/bin/env python3
"""Zhiduidui (职堆堆兼职) feed capture via ADB screencap + vertical scroll."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from adb_util import resolve_adb_path
from adb_zcool_capture import (
    AdbDevice,
    ShotWriter,
    confirm_bottom_stuck,
    feed_swipe,
    safe_unlink,
    text_ink_rows,
)


def feed_has_loading_complete_footer(path: Path, margins: dict) -> bool:
    """True when the centered '加载完成' footer band is visible above the nav bar."""
    try:
        with Image.open(path) as img:
            gray = np.asarray(img.convert("L"), dtype=np.float32)
    except OSError:
        return False

    h, w = gray.shape
    top_y = int(h * float(margins.get("footer_top", 0.875)))
    bottom_y = int(h * float(margins.get("footer_bottom", 0.905)))
    if bottom_y <= top_y:
        return False

    band = gray[top_y:bottom_y, :]
    band_mean = float(band.mean())
    if band.size == 0 or band_mean < 235:
        return False

    left = band[:, : int(w * 0.38)]
    center = band[:, int(w * 0.42) : int(w * 0.58)]
    right = band[:, int(w * 0.62) :]

    ink_center = float(255.0 - center.mean())
    ink_left = float(255.0 - left.mean())
    ink_right = float(255.0 - right.mean())

    if ink_center < 16 or ink_center > 50:
        return False
    if ink_center < ink_left * 1.5 or ink_center < ink_right * 1.45:
        return False

    row_ink = text_ink_rows(center)
    if row_ink.size == 0:
        return False
    peak = float(row_ink.max())
    return 20 <= peak <= 75


def reject_loading_complete_footer(
    path: Path,
    writer: ShotWriter,
    margins: dict,
) -> bool:
    """Drop screenshot that includes the list-end footer; return True if rejected."""
    if not feed_has_loading_complete_footer(path, margins):
        return False

    footer_name = path.name
    safe_unlink(path)
    if writer.paths and writer.paths[-1] == path:
        writer.paths.pop()
        writer.seq -= 1
        if writer.paths:
            writer.last_sig = writer._sig(writer.paths[-1])
        else:
            writer.last_sig = None
    print(f"  rejected loading-complete footer: {footer_name}", flush=True)
    return True


def apply_tab_profile(cfg: dict, tab: str) -> tuple[dict, dict, str, str]:
    scroll = dict(cfg.get("scroll", {}))
    margins = dict(cfg.get("feed_margins", {}))
    capture_cfg = cfg["capture"]
    prefix = capture_cfg.get("prefix", "local_jobs")
    flow_name = "home_local_jobs_scroll"

    tabs = cfg.get("tabs", {})
    if tab in tabs:
        profile = tabs[tab]
        prefix = profile.get("prefix", prefix)
        flow_name = profile.get("flow", flow_name)
        scroll.update(profile.get("scroll", {}))
        margins.update(profile.get("feed_margins", {}))

    return scroll, margins, prefix, flow_name


def run_capture(
    output_dir: Path,
    config_path: Path,
    device: str | None,
    skip_nav: bool,
    count: int | None,
    until_bottom: bool = False,
    tab: str = "local_jobs",
) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    nav = cfg.get("navigation", {})
    capture_cfg = cfg["capture"]
    bottom_cfg = capture_cfg.get("until_bottom", {})
    scroll, margins, prefix, flow_name = apply_tab_profile(cfg, tab)

    skip_navigation = skip_nav or bool(capture_cfg.get("skip_navigation", True))
    threshold = float(capture_cfg["duplicate_threshold"])
    stop_after_dupes = int(bottom_cfg.get("stop_after_consecutive_duplicates", 3))
    bottom_extra_swipes = int(bottom_cfg.get("bottom_extra_swipes", 3))
    bottom_threshold = float(bottom_cfg.get("bottom_threshold", 0.985))
    progress_every = int(bottom_cfg.get("progress_every", 25))
    max_until_bottom = int(bottom_cfg.get("max_shots", 5000))

    if until_bottom:
        target = count if count is not None else max_until_bottom
        max_attempts = target * 4
    else:
        target = count if count is not None else int(capture_cfg["target_count"])
        max_attempts = int(capture_cfg.get("max_attempts", target * 4))

    adb_path = resolve_adb_path()
    adb = AdbDevice(
        device=device,
        tap_delay_ms=int(nav.get("tap_delay_ms", 400)),
        adb_path=adb_path,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    probe_dir = output_dir / "_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    attempts = 0
    consecutive_bottom = 0
    footer_rejected = 0
    reached_end = False
    mode = "until_bottom" if until_bottom else "fixed_count"
    started = time.monotonic()

    try:
        initial_delay = int(scroll.get("initial_capture_delay_ms", 0))
        if skip_navigation:
            print("  skip navigation: scroll down, wait, capture until bottom", flush=True)
            if initial_delay > 0:
                adb.sleep_ms(initial_delay)

        writer = ShotWriter(
            adb=adb,
            shots_dir=output_dir,
            prefix=prefix,
            duplicate_threshold=threshold,
            margins=margins,
        )

        while saved < target and attempts < max_attempts:
            if saved > 0:
                feed_swipe(adb, scroll)
                attempts += 1

            label = "overview" if saved == 0 else f"scroll_{saved:05d}"
            path, is_dup = writer.capture(label)

            if path is not None and reject_loading_complete_footer(path, writer, margins):
                footer_rejected += 1
                if saved > 0:
                    reached_end = True
                    print("  reached end: loading-complete footer detected", flush=True)
                    break
                if footer_rejected >= 5:
                    print(
                        "  stopped: footer detected before any save; scroll list to top first",
                        flush=True,
                    )
                    reached_end = True
                    break
                print("  footer on first frames, scrolling...", flush=True)
                feed_swipe(adb, scroll)
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
                            f"  saved {saved} (scroll {attempts}, "
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
                            f"{bottom_extra_swipes} extra swipes",
                            flush=True,
                        )
                        break
                else:
                    attempts += bottom_extra_swipes
                    path, is_dup = writer.capture(label)
                    if path is not None:
                        saved += 1
                        consecutive_bottom = 0
                        if saved == 1 or saved % progress_every == 0:
                            elapsed = time.monotonic() - started
                            rate = saved / elapsed if elapsed > 0 else 0
                            print(
                                f"  saved {saved} (scroll {attempts}, "
                                f"{rate:.1f} shots/s, dup skipped {writer.skipped_duplicates})",
                                flush=True,
                            )

            if saved >= target and not until_bottom:
                break

    finally:
        safe_unlink(probe_dir / "_bottom_probe.png")

    elapsed_sec = round(time.monotonic() - started, 1)
    report = {
        "app": "zhiduidui",
        "tab": tab,
        "flow": flow_name,
        "mode": mode,
        "target_count": target,
        "saved": saved,
        "skipped_duplicates": writer.skipped_duplicates,
        "footer_rejected": footer_rejected,
        "scroll_attempts": attempts,
        "reached_bottom": reached_end or (until_bottom and consecutive_bottom >= stop_after_dupes),
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
    parser = argparse.ArgumentParser(description="Zhiduidui local jobs ADB capture")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--config",
        type=Path,
        default=_ROOT / "config" / "zhiduidui_adb.json",
    )
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--skip-nav",
        action="store_true",
        help="Do not navigate; screenshot current screen (default)",
    )
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument(
        "--tab",
        default="local_jobs",
        choices=["local_jobs"],
        help="Home sub-tab (default: local_jobs)",
    )
    parser.add_argument(
        "--until-bottom",
        action="store_true",
        help="Scroll until list bottom (consecutive duplicate frames)",
    )
    args = parser.parse_args()

    if args.output is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = _ROOT / "screenshots" / "zhiduidui" / stamp

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
        tab=args.tab,
    )

    if report.get("mode") == "until_bottom":
        print(
            f"Done: {report['saved']} screenshots "
            f"({report['duration_seconds']}s), "
            f"bottom={'yes' if report.get('reached_bottom') else 'stopped'}, "
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
