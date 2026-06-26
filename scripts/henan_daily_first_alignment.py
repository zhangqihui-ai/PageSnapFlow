"""Align Henan Daily 新闻-精选 first screenshot: first news text + hero image not clipped."""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from filter_clipped_frames import cut_line_at_top, text_ink_rows


@dataclass
class TextBand:
    top: float
    bottom: float


def first_frame_alignment_cfg(config: dict) -> dict:
    defaults = {
        "enabled": True,
        "list_top_ratio": 0.215,
        "feed_bottom_ratio": 0.90,
        "min_first_text_top_ratio": 0.018,
        "target_first_text_top_ratio": 0.238,
        "top_tolerance_ratio": 0.010,
        "min_block_height_ratio": 0.016,
        "subheader_max_height_ratio": 0.022,
        "clip_band_ratio": 0.035,
        "clip_nudge_ratio": 0.014,
        "image_scan_gap_ratio": 0.012,
        "image_min_std": 28.0,
        "image_top_scan_max_ratio": 0.55,
        "max_nudge_attempts": 5,
        "adjust_wait_ms": 80,
        "scroll_to_top_repeat": 4,
        "scroll_to_top_wait_ms": 60,
        "nudge_swipe": {
            "start_ratio": 0.55,
            "min_end_ratio": 0.24,
            "max_single_ratio": 0.10,
            "duration": 160,
            "pass_wait_ms": 40,
        },
    }
    merged = {**defaults, **config.get("first_frame_alignment", {})}
    merged["nudge_swipe"] = {**defaults["nudge_swipe"], **merged.get("nudge_swipe", {})}
    return merged


def _feed_gray(img: np.ndarray, cfg: dict) -> tuple[np.ndarray, int, int]:
    h = img.shape[0]
    y1 = int(float(cfg["list_top_ratio"]) * h)
    y2 = int(float(cfg["feed_bottom_ratio"]) * h)
    x1 = int(img.shape[1] * 0.05)
    x2 = int(img.shape[1] * 0.95)
    return cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY), y1, y2


def _text_blocks(gray_feed: np.ndarray, cfg: dict, screen_h: int) -> list[TextBand]:
    blur = cv2.GaussianBlur(gray_feed, (5, 5), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = binary.mean(axis=1)
    text_rows = np.where(ink > 8)[0]
    if text_rows.size == 0:
        return []

    gap = 6
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

    min_h = int(float(cfg["min_block_height_ratio"]) * screen_h)
    subheader_max = int(float(cfg["subheader_max_height_ratio"]) * screen_h)
    bands: list[TextBand] = []
    for start_row, end_row in blocks:
        if end_row - start_row + 1 < min_h:
            continue
        if end_row - start_row + 1 <= subheader_max and start_row < int(0.04 * gray_feed.shape[0]):
            continue
        bands.append(TextBand(top=start_row, bottom=end_row))
    return bands


def find_first_news_text(img: np.ndarray, cfg: dict) -> TextBand | None:
    gray_feed, y1, _y2 = _feed_gray(img, cfg)
    if gray_feed.size == 0:
        return None
    h = img.shape[0]
    list_top = float(cfg["list_top_ratio"])
    scan_max = list_top + float(cfg.get("image_top_scan_max_ratio", 0.55))
    blocks = _text_blocks(gray_feed, cfg, h)
    for block in blocks:
        top = (y1 + block.top) / h
        bottom = (y1 + block.bottom) / h
        if top < list_top + float(cfg.get("min_first_text_top_ratio", 0.018)):
            continue
        if top > scan_max:
            continue
        return TextBand(top=top, bottom=bottom)
    return None


def top_text_clipped(img: np.ndarray, cfg: dict, band: TextBand) -> bool:
    h = img.shape[0]
    clip_h = max(20, int(h * float(cfg["clip_band_ratio"])))
    top_y = int(band.top * h)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    top_slice = gray[max(0, top_y - clip_h // 2) : top_y + clip_h // 2, :]
    if top_slice.size == 0:
        return False
    return cut_line_at_top(text_ink_rows(top_slice))


def find_hero_image_top(img: np.ndarray, cfg: dict, text: TextBand) -> float | None:
    h, w = img.shape[:2]
    y1 = int((text.bottom + float(cfg.get("image_scan_gap_ratio", 0.012))) * h)
    y2 = min(h - 1, y1 + int(0.42 * h))
    if y2 <= y1:
        return None
    roi = img[y1:y2, int(0.05 * w) : int(0.95 * w)]
    if roi.size == 0:
        return None
    std_rows = roi.reshape(roi.shape[0], -1, 3).astype(np.float32).std(axis=(1, 2))
    min_std = float(cfg.get("image_min_std", 28.0))
    for idx, std in enumerate(std_rows):
        if std >= min_std:
            return (y1 + idx) / h
    return None


def hero_image_top_clipped(img: np.ndarray, cfg: dict, image_top: float) -> bool:
    h = img.shape[0]
    clip_h = max(20, int(h * float(cfg["clip_band_ratio"])))
    top_y = int(image_top * h)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    band = gray[max(0, top_y - clip_h // 2) : top_y + clip_h // 2, :]
    if band.size == 0:
        return False
    return cut_line_at_top(text_ink_rows(band))


def compute_nudge_px(img: np.ndarray, cfg: dict, screen_h: int) -> tuple[int, dict[str, Any]]:
    meta: dict[str, Any] = {}
    text = find_first_news_text(img, cfg)
    if text is None:
        meta["reason"] = "no_text"
        meta["nudge_px"] = 0
        return 0, meta

    meta["text_top"] = round(text.top, 4)
    meta["text_bottom"] = round(text.bottom, 4)
    list_top = float(cfg["list_top_ratio"])
    target_top = float(cfg.get("target_first_text_top_ratio", list_top + 0.02))
    tolerance = float(cfg.get("top_tolerance_ratio", 0.010))
    min_clear = list_top + float(cfg.get("min_first_text_top_ratio", 0.018))

    if top_text_clipped(img, cfg, text):
        nudge = -int(float(cfg.get("clip_nudge_ratio", 0.014)) * screen_h)
        meta["reason"] = "text_clipped"
        meta["nudge_px"] = nudge
        return nudge, meta

    if text.top < min_clear:
        nudge = int((text.top - min_clear) * screen_h)
        meta["reason"] = "text_under_header"
        meta["nudge_px"] = nudge
        return nudge, meta

    if text.top < target_top - tolerance:
        nudge = int((text.top - target_top) * screen_h)
        meta["reason"] = "text_too_high"
        meta["nudge_px"] = nudge
        return nudge, meta

    image_top = find_hero_image_top(img, cfg, text)
    if image_top is not None:
        meta["image_top"] = round(image_top, 4)
        if hero_image_top_clipped(img, cfg, image_top):
            nudge = -int(float(cfg.get("clip_nudge_ratio", 0.014)) * screen_h)
            meta["reason"] = "image_clipped"
            meta["nudge_px"] = nudge
            return nudge, meta

    meta["reason"] = "aligned"
    meta["nudge_px"] = 0
    return 0, meta


def swipe_pixels(adb: Any, cfg: dict, dist_px: int) -> None:
    if dist_px == 0:
        return
    swipe_cfg = cfg.get("nudge_swipe", {})
    w, h = adb.size
    start_ratio = float(swipe_cfg.get("start_ratio", 0.55))
    min_end_ratio = float(swipe_cfg.get("min_end_ratio", 0.24))
    max_single_ratio = float(swipe_cfg.get("max_single_ratio", 0.10))
    duration = max(int(swipe_cfg.get("duration", 160)), int(swipe_cfg.get("min_duration", 250)))
    pass_wait = int(swipe_cfg.get("pass_wait_ms", 40))
    cx = int(float(swipe_cfg.get("x_ratio", 0.92)) * w)
    remaining = abs(dist_px)
    direction = 1 if dist_px > 0 else -1
    while remaining > 0:
        chunk = min(remaining, int(max_single_ratio * h))
        start_y = int(start_ratio * h)
        if direction > 0:
            end_y = max(int(min_end_ratio * h), start_y - chunk)
            actual = start_y - end_y
        else:
            end_y = min(int(0.88 * h), start_y + chunk)
            actual = end_y - start_y
        adb._adb_shell("input", "swipe", str(cx), str(start_y), str(cx), str(end_y), str(duration))
        remaining -= actual
        if remaining > 0:
            adb.sleep_ms(pass_wait)


def scroll_feed_to_top(adb: Any, scroll_to_top: dict, *, repeat: int, wait_ms: int) -> None:
    min_duration = int(scroll_to_top.get("min_duration", 0))
    for _ in range(repeat):
        adb.swipe_points(
            scroll_to_top["start"],
            scroll_to_top["end"],
            int(scroll_to_top["duration"]),
            min_duration_ms=min_duration,
        )
        if wait_ms > 0:
            adb.sleep_ms(wait_ms)


def align_first_frame(adb: Any, *, scroll_to_top: dict, cfg: dict | None = None) -> dict[str, Any]:
    raw = cfg or {}
    if "first_frame_alignment" in raw:
        align_cfg = first_frame_alignment_cfg(raw)
    else:
        align_cfg = first_frame_alignment_cfg({"first_frame_alignment": raw}) if raw.get("list_top_ratio") is None else raw
    if not align_cfg.get("enabled", True):
        return {"aligned": True, "skipped": True}

    scroll_feed_to_top(
        adb,
        scroll_to_top,
        repeat=int(align_cfg.get("scroll_to_top_repeat", 4)),
        wait_ms=int(align_cfg.get("scroll_to_top_wait_ms", 60)),
    )

    report: dict[str, Any] = {"attempts": []}
    screen_h = adb.size[1]
    wait_ms = int(align_cfg.get("adjust_wait_ms", 80))
    max_attempts = int(align_cfg.get("max_nudge_attempts", 5))

    for attempt in range(max_attempts):
        temp = Path(tempfile.gettempdir()) / f"hnrb_align_{time.time_ns()}.png"
        adb.screencap(temp)
        img = cv2.imread(str(temp))
        temp.unlink(missing_ok=True)
        if img is None:
            break
        nudge_px, meta = compute_nudge_px(img, align_cfg, screen_h)
        meta["attempt"] = attempt + 1
        report["attempts"].append(meta)
        if nudge_px == 0:
            report["aligned"] = True
            print(f"  first frame aligned ({meta.get('reason', 'ok')})", flush=True)
            return report
        swipe_pixels(adb, align_cfg, nudge_px)
        adb.sleep_ms(wait_ms)

    report["aligned"] = False
    print("  warning: first frame alignment did not fully converge", flush=True)
    return report
