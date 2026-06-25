"""Align TapTap feed scroll frames so card text metadata sits fully above the bottom bar."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from filter_clipped_frames import cut_line_at_bottom, text_ink_rows


def alignment_cfg(config: dict) -> dict:
    defaults = {
        "enabled": False,
        "feed_top_ratio": 0.145,
        "feed_bottom_ratio": 0.915,
        "target_text_bottom_ratio": 0.875,
        "bottom_tolerance_ratio": 0.015,
        "card_step_ratio": 0.34,
        "max_nudge_attempts": 4,
        "adjust_wait_ms": 120,
        "clip_band_ratio": 0.055,
        "min_text_block_rows": 10,
        "text_scan_band_ratio": 0.52,
        "text_ink_threshold": 8,
        "text_row_gap": 6,
        "clip_nudge_ratio": 0.018,
        "nudge_swipe": {
            "start_ratio": 0.58,
            "min_end_ratio": 0.20,
            "max_single_ratio": 0.14,
            "duration": 180,
            "pass_wait_ms": 60,
        },
    }
    merged = {**defaults, **config.get("feed_alignment", {})}
    merged["nudge_swipe"] = {**defaults["nudge_swipe"], **merged.get("nudge_swipe", {})}
    return merged


def _feed_slice(img: np.ndarray, cfg: dict) -> tuple[np.ndarray, int, int]:
    h = img.shape[0]
    y1 = int(float(cfg["feed_top_ratio"]) * h)
    y2 = int(float(cfg["feed_bottom_ratio"]) * h)
    x1 = int(img.shape[1] * 0.06)
    x2 = int(img.shape[1] * 0.94)
    return img[y1:y2, x1:x2], y1, y2


def find_bottom_text_edge(img: np.ndarray, cfg: dict) -> float | None:
    """Return screen-height ratio of the last ink row in the bottom text block."""
    feed, y1, _y2 = _feed_slice(img, cfg)
    if feed.size == 0:
        return None

    gray = cv2.cvtColor(feed, cv2.COLOR_BGR2GRAY)
    band_h = max(32, int(feed.shape[0] * float(cfg["text_scan_band_ratio"])))
    region = gray[max(0, gray.shape[0] - band_h) :, :]
    offset = gray.shape[0] - region.shape[0]

    blur = cv2.GaussianBlur(region, (5, 5), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = binary.mean(axis=1)
    text_thresh = float(cfg["text_ink_threshold"])
    text_rows = np.where(ink > text_thresh)[0]
    if text_rows.size == 0:
        return None

    gap = int(cfg["text_row_gap"])
    blocks: list[tuple[int, int]] = []
    start = int(text_rows[0])
    prev = int(text_rows[0])
    for row in text_rows[1:]:
        row = int(row)
        if row - prev > gap:
            blocks.append((start, prev))
            start = row
        prev = row
    blocks.append((start, prev))

    min_rows = int(cfg["min_text_block_rows"])
    block_start, block_end = blocks[-1]
    if block_end - block_start + 1 < min_rows and len(blocks) >= 2:
        block_start, block_end = blocks[-2]

    abs_row = y1 + offset + block_end
    return abs_row / img.shape[0]


def bottom_text_clipped(img: np.ndarray, cfg: dict) -> bool:
    """True when the feed bottom band cuts through a text line."""
    feed, _y1, y2 = _feed_slice(img, cfg)
    if feed.size == 0:
        return False

    h = img.shape[0]
    band_h = max(32, int(h * float(cfg["clip_band_ratio"])))
    bottom_y = int(float(cfg["feed_bottom_ratio"]) * h)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bottom_band = gray[bottom_y - band_h : bottom_y, :]
    return cut_line_at_bottom(text_ink_rows(bottom_band))


def compute_nudge_px(img: np.ndarray, cfg: dict, screen_h: int) -> tuple[int, dict[str, Any]]:
    """Positive nudge scrolls content up (reveals lower pixels)."""
    meta: dict[str, Any] = {}
    if bottom_text_clipped(img, cfg):
        nudge = int(float(cfg.get("clip_nudge_ratio", 0.018)) * screen_h)
        meta["reason"] = "bottom_text_clipped"
        meta["nudge_px"] = nudge
        return nudge, meta

    edge = find_bottom_text_edge(img, cfg)
    if edge is None:
        meta["reason"] = "no_text_edge"
        meta["nudge_px"] = 0
        return 0, meta

    target = float(cfg["target_text_bottom_ratio"])
    tol = float(cfg["bottom_tolerance_ratio"])
    feed_bottom = float(cfg["feed_bottom_ratio"])
    min_gap = float(cfg.get("min_bottom_gap_ratio", 0.004))
    error = target - edge
    meta["text_bottom"] = round(edge, 4)
    meta["target"] = target
    meta["error"] = round(error, 4)

    if abs(error) <= tol:
        meta["reason"] = "aligned"
        meta["nudge_px"] = 0
        return 0, meta

    if edge > feed_bottom - min_gap:
        meta["reason"] = "too_low"
        meta["nudge_px"] = int((target - edge) * screen_h)
        return meta["nudge_px"], meta

    meta["reason"] = "position"
    meta["nudge_px"] = int(error * screen_h)
    return meta["nudge_px"], meta


def swipe_pixels(adb: Any, cfg: dict, dist_px: int) -> None:
    if dist_px == 0:
        return
    swipe_cfg = cfg.get("nudge_swipe", {})
    w, h = adb.size
    start_ratio = float(swipe_cfg.get("start_ratio", 0.58))
    min_end_ratio = float(swipe_cfg.get("min_end_ratio", 0.20))
    max_single_ratio = float(swipe_cfg.get("max_single_ratio", 0.14))
    duration = int(swipe_cfg.get("duration", 180))
    pass_wait = int(swipe_cfg.get("pass_wait_ms", 60))
    cx = w // 2
    remaining = abs(dist_px)
    direction = 1 if dist_px > 0 else -1
    while remaining > 0:
        chunk = min(remaining, int(max_single_ratio * h))
        start_y = int(start_ratio * h)
        if direction > 0:
            end_y = max(int(min_end_ratio * h), start_y - chunk)
            actual = start_y - end_y
        else:
            end_y = min(int(0.86 * h), start_y + chunk)
            actual = end_y - start_y
        adb._adb_shell("input", "swipe", str(cx), str(start_y), str(cx), str(end_y), str(duration))
        remaining -= actual
        if remaining > 0:
            adb.sleep_ms(pass_wait)


def screencap_temp(adb: Any) -> Path:
    path = Path(tempfile.gettempdir()) / f"taptap_align_{time.time_ns()}.png"
    adb.screencap(path)
    return path


def align_frame(
    adb: Any,
    config: dict,
    *,
    post_swipe_delay_ms: int,
    overrides: dict | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    """Capture, nudge until card text bottom is fully visible, return temp screenshot path."""
    cfg = alignment_cfg(config)
    if overrides:
        cfg = {**cfg, **overrides}
    if not cfg.get("enabled", False):
        return None, {"enabled": False}

    adjust_wait = int(cfg.get("adjust_wait_ms", 120))
    max_attempts = int(cfg.get("max_nudge_attempts", 4))
    screen_h = adb.size[1]

    temp = screencap_temp(adb)
    report: dict[str, Any] = {"enabled": True, "attempts": []}

    try:
        img = cv2.imread(str(temp))
        if img is None:
            report["error"] = "unreadable_frame"
            return temp, report

        for attempt in range(max_attempts + 1):
            nudge, meta = compute_nudge_px(img, cfg, screen_h)
            meta["attempt"] = attempt
            report["attempts"].append(meta)
            if nudge == 0:
                report["aligned"] = True
                return temp, report

            if attempt >= max_attempts:
                report["aligned"] = False
                report["warning"] = "max_nudge_attempts"
                return temp, report

            print(
                f"    align: {meta.get('reason')} nudge={nudge}px "
                f"text_bottom={meta.get('text_bottom')} target={meta.get('target')}",
                flush=True,
            )
            swipe_pixels(adb, cfg, nudge)
            adb.sleep_ms(max(post_swipe_delay_ms, adjust_wait))
            safe_unlink = temp
            temp = screencap_temp(adb)
            if safe_unlink.exists():
                safe_unlink.unlink(missing_ok=True)
            img = cv2.imread(str(temp))
            if img is None:
                report["error"] = "unreadable_frame"
                return temp, report

        return temp, report
    except Exception:
        if temp.exists():
            temp.unlink(missing_ok=True)
        raise


def card_step_px(config: dict, screen_h: int) -> int:
    cfg = alignment_cfg(config)
    return int(float(cfg.get("card_step_ratio", 0.34)) * screen_h)
