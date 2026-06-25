"""Align TapTap Today Games scroll frames: first game text fully visible at top."""

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


def today_alignment_cfg(config: dict) -> dict:
    defaults = {
        "enabled": True,
        "list_top_ratio": 0.355,
        "feed_bottom_ratio": 0.915,
        "header_skip_ratio": 0.045,
        "min_block_height_ratio": 0.024,
        "subheader_max_height_ratio": 0.028,
        "target_text_top_ratio": 0.375,
        "top_tolerance_ratio": 0.012,
        "card_step_ratio": 0.29,
        "max_nudge_attempts": 4,
        "adjust_wait_ms": 120,
        "clip_band_ratio": 0.04,
        "text_ink_threshold": 8,
        "text_row_gap": 6,
        "clip_nudge_ratio": 0.016,
        "list_ready_wait_ms": 900,
        "list_ready_timeout_ms": 12000,
        "list_ready_min_std": 22.0,
        "list_swipe": {
            "start": "50%, 68%",
            "end": "50%, 42%",
            "duration": 260,
        },
        "nudge_swipe": {
            "start_ratio": 0.58,
            "min_end_ratio": 0.22,
            "max_single_ratio": 0.12,
            "duration": 180,
            "pass_wait_ms": 60,
        },
    }
    merged = {**defaults, **config.get("today_alignment", {})}
    merged["nudge_swipe"] = {**defaults["nudge_swipe"], **merged.get("nudge_swipe", {})}
    merged["list_swipe"] = {**defaults["list_swipe"], **merged.get("list_swipe", {})}
    return merged


def _feed_gray(img: np.ndarray, cfg: dict) -> tuple[np.ndarray, int, int]:
    h = img.shape[0]
    y1 = int(float(cfg["list_top_ratio"]) * h)
    y2 = int(float(cfg["feed_bottom_ratio"]) * h)
    x1 = int(img.shape[1] * 0.06)
    x2 = int(img.shape[1] * 0.94)
    return cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY), y1, y2


def _text_blocks(gray_feed: np.ndarray, cfg: dict, screen_h: int) -> list[TextBand]:
    blur = cv2.GaussianBlur(gray_feed, (5, 5), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = binary.mean(axis=1)
    text_thresh = float(cfg["text_ink_threshold"])
    text_rows = np.where(ink > text_thresh)[0]
    if text_rows.size == 0:
        return []

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

    min_h = int(float(cfg["min_block_height_ratio"]) * screen_h)
    subheader_max = int(float(cfg["subheader_max_height_ratio"]) * screen_h)
    header_skip = int(float(cfg.get("header_skip_ratio", 0.045)) * screen_h)

    bands: list[TextBand] = []
    for start_row, end_row in blocks:
        if end_row - start_row + 1 < min_h:
            continue
        if start_row < header_skip and end_row - start_row + 1 <= subheader_max:
            continue
        bands.append(TextBand(top=start_row, bottom=end_row))
    return bands


def find_first_game_text_band(img: np.ndarray, cfg: dict) -> TextBand | None:
    gray_feed, y1, _y2 = _feed_gray(img, cfg)
    if gray_feed.size == 0:
        return None

    h = img.shape[0]
    list_top = float(cfg["list_top_ratio"])
    blocks = _text_blocks(gray_feed, cfg, h)
    if not blocks:
        return None

    abs_blocks: list[TextBand] = [
        TextBand(top=(y1 + block.top) / h, bottom=(y1 + block.bottom) / h) for block in blocks
    ]
    min_game_h = float(cfg.get("min_game_text_height_ratio", 0.042))
    subheader_top_max = list_top + float(cfg.get("subheader_top_slack_ratio", 0.018))
    subheader_max_h = float(cfg.get("subheader_max_height_ratio", 0.028))

    candidates: list[TextBand] = []
    for band in abs_blocks:
        height = band.bottom - band.top
        if height < min_game_h:
            continue
        if band.top <= subheader_top_max and height <= subheader_max_h + 0.01:
            continue
        if band.top < list_top + float(cfg.get("min_game_text_top_ratio", 0.025)):
            continue
        if band.top > list_top + float(cfg.get("first_card_scan_max_ratio", 0.58)):
            continue
        candidates.append(band)

    if not candidates:
        return None

    return candidates[0]


def top_text_clipped(img: np.ndarray, cfg: dict, band: TextBand) -> bool:
    h = img.shape[0]
    clip_h = max(24, int(h * float(cfg["clip_band_ratio"])))
    top_y = int(band.top * h)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    top_slice = gray[max(0, top_y - clip_h // 2) : top_y + clip_h // 2, :]
    if top_slice.size == 0:
        return False
    return cut_line_at_top(text_ink_rows(top_slice))


def compute_nudge_px(img: np.ndarray, cfg: dict, screen_h: int) -> tuple[int, dict[str, Any]]:
    meta: dict[str, Any] = {}
    band = find_first_game_text_band(img, cfg)
    if band is None:
        meta["reason"] = "no_text_band"
        meta["nudge_px"] = 0
        return 0, meta

    meta["text_top"] = round(band.top, 4)
    meta["text_bottom"] = round(band.bottom, 4)
    list_top = float(cfg["list_top_ratio"])
    min_clear_top = list_top + float(cfg.get("min_game_text_top_ratio", 0.025))
    meta["min_clear_top"] = round(min_clear_top, 4)

    if top_text_clipped(img, cfg, band):
        nudge = -int(float(cfg.get("clip_nudge_ratio", 0.016)) * screen_h)
        meta["reason"] = "top_text_clipped"
        meta["nudge_px"] = nudge
        return nudge, meta

    if band.top < min_clear_top:
        nudge = int((band.top - min_clear_top) * screen_h)
        meta["reason"] = "under_header"
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
    start_ratio = float(swipe_cfg.get("start_ratio", 0.58))
    min_end_ratio = float(swipe_cfg.get("min_end_ratio", 0.22))
    max_single_ratio = float(swipe_cfg.get("max_single_ratio", 0.12))
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
    path = Path(tempfile.gettempdir()) / f"taptap_today_align_{time.time_ns()}.png"
    adb.screencap(path)
    return path


def align_frame(
    adb: Any,
    config: dict,
    *,
    post_swipe_delay_ms: int,
    overrides: dict | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    cfg = today_alignment_cfg(config)
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
                f"text_top={meta.get('text_top')} min_clear={meta.get('min_clear_top')}",
                flush=True,
            )
            swipe_pixels(adb, cfg, nudge)
            adb.sleep_ms(max(post_swipe_delay_ms, adjust_wait))
            prev = temp
            temp = screencap_temp(adb)
            if prev.exists():
                prev.unlink(missing_ok=True)
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
    cfg = today_alignment_cfg(config)
    return int(float(cfg.get("card_step_ratio", 0.29)) * screen_h)


def list_has_content(img: np.ndarray, cfg: dict) -> bool:
    h = img.shape[0]
    y1 = int(float(cfg["list_top_ratio"]) * h)
    y2 = int(float(cfg.get("list_ready_scan_bottom_ratio", 0.72)) * h)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    region = gray[y1:y2, int(img.shape[1] * 0.08) : int(img.shape[1] * 0.92)]
    if region.size == 0:
        return False
    return float(np.std(region)) >= float(cfg.get("list_ready_min_std", 22.0))


def wait_for_today_list(adb: Any, config: dict) -> bool:
    cfg = today_alignment_cfg(config)
    timeout_ms = int(cfg.get("list_ready_timeout_ms", 12000))
    wait_ms = int(cfg.get("list_ready_wait_ms", 900))
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        temp = screencap_temp(adb)
        img = cv2.imread(str(temp))
        temp.unlink(missing_ok=True)
        if img is not None and list_has_content(img, cfg):
            print("Today Games list content detected.", flush=True)
            adb.sleep_ms(wait_ms)
            return True
        adb.sleep_ms(400)
    print("Warning: Today Games list did not finish loading before timeout.", flush=True)
    return False


def swipe_today_list(adb: Any, config: dict) -> None:
    cfg = today_alignment_cfg(config)
    swipe = cfg["list_swipe"]
    adb.swipe_points(swipe["start"], swipe["end"], int(swipe.get("duration", 260)))
