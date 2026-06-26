#!/usr/bin/env python3
"""Lightweight screenshot similarity helpers (shared by capture + dedup)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

THUMB_W = 160
THUMB_H = 90


def imread_unicode(path: Path | str) -> np.ndarray | None:
    """Read images on Windows paths that may contain non-ASCII characters."""
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def scene_signature(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    return cv2.resize(gray, (THUMB_W, THUMB_H), interpolation=cv2.INTER_AREA)


def signature_from_path(path: Path) -> np.ndarray | None:
    img = imread_unicode(path)
    if img is None:
        return None
    return scene_signature(img)


def previous_saved_path(paths: list[Path], *, exclude: Path | None = None) -> Path | None:
    for candidate in reversed(paths):
        if exclude is not None and candidate == exclude:
            continue
        if candidate.is_file():
            return candidate
    return None


def similarity(left: np.ndarray, right: np.ndarray) -> float:
    diff = np.abs(left.astype(np.float32) - right.astype(np.float32))
    return 1.0 - float(np.mean(diff)) / 255.0


def count_unique_images(paths: list[Path], threshold: float) -> tuple[int, int, float]:
    """Return (total, unique, duplicate_rate)."""
    kept_sig: np.ndarray | None = None
    unique = 0
    for path in paths:
        sig = signature_from_path(path)
        if sig is None:
            continue
        if kept_sig is not None and similarity(sig, kept_sig) >= threshold:
            continue
        kept_sig = sig
        unique += 1
    total = len([p for p in paths if signature_from_path(p) is not None])
    dup_rate = 0.0 if total == 0 else 1.0 - (unique / total)
    return total, unique, dup_rate
