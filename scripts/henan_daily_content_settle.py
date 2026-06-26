"""Wait for Henan Daily feed list thumbnails to finish loading before capture."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from image_similarity import imread_unicode


def content_settle_cfg(config: dict) -> dict:
    defaults = {
        "enabled": True,
        "max_wait_ms": 3000,
        "poll_ms": 200,
        "min_settle_ms": 400,
        "max_retries": 2,
        "feed_top_ratio": 0.20,
        "feed_bottom_ratio": 0.88,
        "row_height_ratio": 0.14,
        "row_step_ratio": 0.16,
        "thumb_left_ratio": 0.05,
        "thumb_right_ratio": 0.32,
        "placeholder_std_max": 18.0,
        "placeholder_blue_red_min": 18.0,
        "min_placeholder_rows": 1,
    }
    return {**defaults, **config}


def _scan_thumbnail_rows(img: np.ndarray, cfg: dict) -> list[tuple[float, float, float]]:
    h, w = img.shape[:2]
    top = float(cfg.get("feed_top_ratio", 0.20))
    bottom = float(cfg.get("feed_bottom_ratio", 0.88))
    row_h = float(cfg.get("row_height_ratio", 0.14))
    step = float(cfg.get("row_step_ratio", 0.16))
    left = int(float(cfg.get("thumb_left_ratio", 0.05)) * w)
    right = int(float(cfg.get("thumb_right_ratio", 0.32)) * w)
    rows: list[tuple[float, float, float]] = []
    y = top
    while y + row_h <= bottom:
        band = img[int(y * h) : int((y + row_h) * h), left:right]
        if band.size == 0:
            break
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        blue = band[:, :, 0].astype(np.float32)
        red = band[:, :, 2].astype(np.float32)
        rows.append((float(gray.std()), float(blue.mean() - red.mean()), float(gray.mean())))
        y += step
    return rows


def feed_has_placeholder_thumbnails(img: np.ndarray, cfg: dict) -> bool:
    std_max = float(cfg.get("placeholder_std_max", 18.0))
    blue_min = float(cfg.get("placeholder_blue_red_min", 18.0))
    need = int(cfg.get("min_placeholder_rows", 1))
    hits = 0
    for std, blue_red, _mean in _scan_thumbnail_rows(img, cfg):
        if std <= std_max and blue_red >= blue_min:
            hits += 1
    return hits >= need


def wait_for_feed_content_ready(adb: Any, cfg: dict) -> bool:
    cfg = content_settle_cfg(cfg)
    if not cfg.get("enabled", True):
        return True
    min_settle = int(cfg.get("min_settle_ms", 400))
    if min_settle > 0:
        adb.sleep_ms(min_settle)
    max_wait_ms = int(cfg.get("max_wait_ms", 3000))
    poll_ms = int(cfg.get("poll_ms", 200))
    deadline = time.time() + max_wait_ms / 1000.0
    while time.time() < deadline:
        temp = Path(tempfile.gettempdir()) / f"hnrb_settle_{time.time_ns()}.png"
        try:
            adb.screencap(temp)
            img = imread_unicode(temp)
            if img is None or not feed_has_placeholder_thumbnails(img, cfg):
                return True
        finally:
            temp.unlink(missing_ok=True)
        adb.sleep_ms(poll_ms)
    return False


def ensure_feed_content_ready_for_capture(
    adb: Any,
    cfg: dict,
    *,
    image_path: Path | None = None,
) -> bool:
    cfg = content_settle_cfg(cfg)
    if not cfg.get("enabled", True):
        return True
    if image_path is not None and image_path.is_file():
        img = imread_unicode(image_path)
        if img is not None and not feed_has_placeholder_thumbnails(img, cfg):
            return True
    ok = wait_for_feed_content_ready(adb, cfg)
    if not ok:
        print("  warning: feed thumbnails may still be loading", flush=True)
    return ok
