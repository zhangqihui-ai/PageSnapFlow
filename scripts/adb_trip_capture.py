#!/usr/bin/env python3
"""Trip.com discovery feed scroll capture via ADB — one page per step."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from adb_taptap_capture import AdbDevice, ShotWriter, safe_unlink
from image_similarity import imread_unicode, signature_from_path

PREFIX = "trip"
_FILENAME_RE = re.compile(rf"^{PREFIX}_(\d+)_(.+)\.png$")


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def swipe_spec(adb: AdbDevice, spec: dict) -> None:
    repeat = max(1, int(spec.get("repeat", 1)))
    wait_ms = int(spec.get("wait_ms", 0))
    for idx in range(repeat):
        adb.swipe_points(spec["start"], spec["end"], int(spec["duration"]))
        if wait_ms > 0 and idx + 1 < repeat:
            adb.sleep_ms(wait_ms)


def scroll_to_top(adb: AdbDevice, config: dict) -> None:
    spec = config.get("scroll_to_top")
    if not spec:
        return
    repeat = int(spec.get("repeat", 1))
    print(f"  scroll_to_top: {repeat} swipe(s)", flush=True)
    swipe_spec(adb, spec)


def content_settle_cfg(config: dict) -> dict:
    timing = config.get("adb_capture", {})
    defaults = {
        "enabled": True,
        "min_settle_ms": 700,
        "max_wait_ms": 4500,
        "poll_ms": 300,
        "feed_top_ratio": config.get("feed_top_ratio", 0.185),
        "feed_bottom_ratio": config.get("feed_bottom_ratio", 0.895),
        "columns": [
            {"x1": 0.03, "x2": 0.49},
            {"x1": 0.51, "x2": 0.97},
        ],
        "card_height_ratio": 0.22,
        "card_step_ratio": 0.18,
        "placeholder_std_max": 18.0,
        "placeholder_mean_min": 175.0,
        "min_placeholder_cards": 1,
    }
    return {**defaults, **config.get("content_settle", {})}


def feed_has_loading_placeholders(img: np.ndarray, cfg: dict) -> bool:
    h, w = img.shape[:2]
    top = float(cfg.get("feed_top_ratio", 0.185))
    bottom = float(cfg.get("feed_bottom_ratio", 0.895))
    card_h = float(cfg.get("card_height_ratio", 0.22))
    step = float(cfg.get("card_step_ratio", 0.18))
    std_max = float(cfg.get("placeholder_std_max", 18.0))
    mean_min = float(cfg.get("placeholder_mean_min", 175.0))
    need = int(cfg.get("min_placeholder_cards", 1))
    hits = 0
    for col in cfg.get("columns", []):
        x1 = int(float(col["x1"]) * w)
        x2 = int(float(col["x2"]) * w)
        y = top
        while y + card_h <= bottom:
            band = img[int(y * h) : int((y + card_h) * h), x1:x2]
            if band.size == 0:
                break
            gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
            std = float(gray.std())
            mean = float(gray.mean())
            if std <= std_max and mean >= mean_min:
                hits += 1
            y += step
    return hits >= need


def wait_for_feed_ready(adb: AdbDevice, cfg: dict) -> None:
    if not cfg.get("enabled", True):
        adb.sleep_ms(int(cfg.get("min_settle_ms", 700)))
        return
    min_settle = int(cfg.get("min_settle_ms", 700))
    if min_settle > 0:
        adb.sleep_ms(min_settle)
    max_wait_ms = int(cfg.get("max_wait_ms", 4500))
    poll_ms = int(cfg.get("poll_ms", 300))
    deadline = time.time() + max_wait_ms / 1000.0
    while time.time() < deadline:
        temp = Path(tempfile.gettempdir()) / f"trip_settle_{time.time_ns()}.png"
        try:
            adb.screencap(temp)
            img = imread_unicode(temp)
            if img is None or not feed_has_loading_placeholders(img, cfg):
                return
        finally:
            safe_unlink(temp)
        adb.sleep_ms(poll_ms)
    print("  warning: feed may still be loading placeholders", flush=True)


def page_swipe(adb: AdbDevice, config: dict) -> None:
    spec = config["page_swipe"]
    adb.swipe_points(spec["start"], spec["end"], int(spec["duration"]))


def list_saved_shots(shots_dir: Path) -> list[Path]:
    return sorted(shots_dir.glob(f"{PREFIX}_*.png"))


def infer_resume_state(shots_dir: Path) -> dict | None:
    files = list_saved_shots(shots_dir)
    if not files:
        return None
    last = files[-1]
    match = _FILENAME_RE.match(last.name)
    if not match:
        raise ValueError(f"Cannot parse resume filename: {last.name}")
    return {
        "seq": int(match.group(1)) + 1,
        "last_path": last,
        "last_sig": signature_from_path(last),
        "saved_count": len(files),
    }


def write_manifest(
    *,
    output_dir: Path,
    config: dict,
    adb: AdbDevice,
    shots_dir: Path,
    target_shots: int,
    writer: ShotWriter,
    completed: bool,
) -> dict:
    feed_top = config.get("feed_top_ratio", 0.185)
    feed_bottom = config.get("feed_bottom_ratio", 0.895)
    saved = list_saved_shots(shots_dir)
    manifest = {
        "app": "trip",
        "tab": config.get("tab_name"),
        "package": config.get("package", "ctrip.android.view"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "device": adb.device,
        "screen_size": f"{adb.size[0]}x{adb.size[1]}",
        "target_shots": target_shots,
        "saved_shots": len(saved),
        "skipped_duplicates": writer.skipped_duplicates,
        "completed": completed,
        "feed_geometry": {
            "feed_top_ratio": feed_top,
            "feed_bottom_ratio": feed_bottom,
            "page_swipe": config.get("page_swipe"),
        },
        "files": [str(p.relative_to(output_dir)) for p in saved[-20:]],
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    progress = {
        "target_shots": target_shots,
        "saved_shots": len(saved),
        "last_file": saved[-1].name if saved else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed": completed,
    }
    (output_dir / "capture_progress.json").write_text(
        json.dumps(progress, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def run_capture(
    *,
    output_dir: Path,
    config_path: Path,
    device: str | None,
    max_shots: int | None,
    skip_scroll_to_top: bool = False,
    progress_every: int = 50,
) -> dict:
    config = load_config(config_path)
    timing = config.get("adb_capture", {})
    pilot = config.get("pilot", {})
    full_run = config.get("full_run", {})
    target_shots = int(
        max_shots
        if max_shots is not None
        else full_run.get("max_shots", pilot.get("max_shots", 10))
    )
    post_swipe_delay_ms = int(timing.get("post_swipe_delay_ms", 900))
    dup_threshold = float(timing.get("duplicate_threshold", 0.94))
    settle_cfg = content_settle_cfg(config)
    scroll_first = bool(pilot.get("scroll_to_top_first", True)) and not skip_scroll_to_top
    progress_every = max(1, int(progress_every))

    shots_dir = output_dir / "adb_raw" / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    existing = len(list_saved_shots(shots_dir))
    if existing >= target_shots:
        print(
            f"Trip feed capture: already have {existing}/{target_shots} shots in {output_dir}",
            flush=True,
        )
        adb = AdbDevice(device, int(timing.get("tap_delay_ms", 100)))
        writer = ShotWriter(
            adb=adb,
            shots_dir=shots_dir,
            prefix=PREFIX,
            post_swipe_delay_ms=post_swipe_delay_ms,
            duplicate_threshold=dup_threshold,
            skip_duplicate_saves=bool(timing.get("skip_duplicate_saves", False)),
        )
        return write_manifest(
            output_dir=output_dir,
            config=config,
            adb=adb,
            shots_dir=shots_dir,
            target_shots=target_shots,
            writer=writer,
            completed=True,
        )

    adb = AdbDevice(device, int(timing.get("tap_delay_ms", 100)))
    writer = ShotWriter(
        adb=adb,
        shots_dir=shots_dir,
        prefix=PREFIX,
        post_swipe_delay_ms=post_swipe_delay_ms,
        duplicate_threshold=dup_threshold,
        skip_duplicate_saves=bool(timing.get("skip_duplicate_saves", False)),
    )

    feed_top = config.get("feed_top_ratio", 0.185)
    feed_bottom = config.get("feed_bottom_ratio", 0.895)
    print(
        f"Trip feed capture: target {target_shots} shots, existing {existing}, "
        f"screen={adb.size[0]}x{adb.size[1]}, feed={feed_top:.0%}–{feed_bottom:.0%}, "
        f"post_swipe={post_swipe_delay_ms}ms",
        flush=True,
    )
    print(f"Output: {output_dir}", flush=True)

    resume = infer_resume_state(shots_dir) if existing else None
    if resume:
        writer.seq = resume["seq"]
        writer.last_sig = resume["last_sig"]
        writer.paths = list_saved_shots(shots_dir)
        print(
            f"  resume: {resume['saved_count']} existing file(s), next seq {writer.seq:03d}, "
            f"last={resume['last_path'].name}",
            flush=True,
        )
    elif scroll_first:
        scroll_to_top(adb, config)
        wait_for_feed_ready(adb, settle_cfg)
        writer.capture("00_start")
        existing = len(list_saved_shots(shots_dir))
        print(f"  start capture: {existing}/{target_shots}", flush=True)
    elif existing == 0:
        wait_for_feed_ready(adb, settle_cfg)
        writer.capture("00_start")
        existing = len(list_saved_shots(shots_dir))
        print(f"  start capture: {existing}/{target_shots}", flush=True)

    while existing < target_shots:
        page_swipe(adb, config)
        adb.sleep_ms(post_swipe_delay_ms)
        wait_for_feed_ready(adb, settle_cfg)
        path, is_dup = writer.capture(f"page_{existing:05d}")
        if is_dup:
            print(f"  warning: frame {existing} looks similar to previous", flush=True)
        existing = len(list_saved_shots(shots_dir))
        if existing % progress_every == 0 or existing >= target_shots:
            print(f"  progress: {existing}/{target_shots}", flush=True)
            write_manifest(
                output_dir=output_dir,
                config=config,
                adb=adb,
                shots_dir=shots_dir,
                target_shots=target_shots,
                writer=writer,
                completed=existing >= target_shots,
            )

    return write_manifest(
        output_dir=output_dir,
        config=config,
        adb=adb,
        shots_dir=shots_dir,
        target_shots=target_shots,
        writer=writer,
        completed=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Trip.com discovery feed ADB scroll capture")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=_ROOT / "config" / "trip_adb.yaml",
    )
    parser.add_argument("--device", default=None)
    parser.add_argument("--max-shots", type=int, default=None)
    parser.add_argument(
        "--skip-scroll-to-top",
        action="store_true",
        help="Capture from current scroll position without scrolling to top first",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=50,
        help="Print and save progress every N shots (default: 50)",
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    try:
        stats = run_capture(
            output_dir=args.output,
            config_path=args.config,
            device=args.device,
            max_shots=args.max_shots,
            skip_scroll_to_top=args.skip_scroll_to_top,
            progress_every=args.progress_every,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Done: {stats['saved_shots']}/{stats['target_shots']} shots -> {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
