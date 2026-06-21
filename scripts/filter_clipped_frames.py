#!/usr/bin/env python3
"""Drop scroll screenshots where a text line is visibly cut in half at feed edges."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class FeedMargins:
    top: float = 0.155
    bottom: float = 0.865
    band_ratio: float = 0.055


def text_ink_rows(gray_band: np.ndarray) -> np.ndarray:
    if gray_band.size == 0:
        return np.array([])
    blur = cv2.GaussianBlur(gray_band, (5, 5), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary.mean(axis=1)


def cut_line_at_top(ink: np.ndarray) -> bool:
    """True when top rows show ink, a gap, then more ink (half line clipped)."""
    if ink.size < 18:
        return False
    top = ink[:3].mean()
    gap = ink[3:7].mean()
    body = ink[7:16].mean()
    if top < 24 or body < 18:
        return False
    return gap < top * 0.32 and gap < body * 0.32 and top > body * 0.85


def cut_line_at_bottom(ink: np.ndarray) -> bool:
    if ink.size < 18:
        return False
    bottom = ink[-3:].mean()
    gap = ink[-7:-3].mean()
    body = ink[-16:-7].mean()
    if bottom < 24 or body < 18:
        return False
    return gap < bottom * 0.32 and gap < body * 0.32 and bottom > body * 0.85


def feed_clipped(img: np.ndarray, margins: FeedMargins) -> tuple[bool, str]:
    h, _w = img.shape[:2]
    band_h = max(32, int(h * margins.band_ratio))
    top_y = int(h * margins.top)
    bottom_y = int(h * margins.bottom)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    top_band = gray[top_y : top_y + band_h, :]
    bottom_band = gray[bottom_y - band_h : bottom_y, :]

    top_ink = text_ink_rows(top_band)
    bottom_ink = text_ink_rows(bottom_band)

    if cut_line_at_top(top_ink):
        return True, "top_text_clipped"
    if cut_line_at_bottom(bottom_ink):
        return True, "bottom_text_clipped"
    return False, ""


def filter_folder(input_dir: Path, output_dir: Path, margins: FeedMargins) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(input_dir.glob("*.png"))
    kept: list[dict] = []
    dropped: list[dict] = []

    for path in images:
        img = cv2.imread(str(path))
        if img is None:
            dropped.append({"file": path.name, "reason": "unreadable"})
            continue
        clipped, reason = feed_clipped(img, margins)
        if clipped:
            dropped.append({"file": path.name, "reason": reason})
            continue
        shutil.copy2(path, output_dir / path.name)
        kept.append({"file": path.name})

    report = {
        "input": str(input_dir),
        "output": str(output_dir),
        "kept_count": len(kept),
        "dropped_count": len(dropped),
        "kept": kept,
        "dropped": dropped,
    }
    (output_dir / "filter_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove scroll frames with half-cut text lines.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-margin", type=float, default=0.155)
    parser.add_argument("--bottom-margin", type=float, default=0.865)
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"Input not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    margins = FeedMargins(top=args.top_margin, bottom=args.bottom_margin)
    report = filter_folder(args.input, args.output, margins)
    print(
        f"Kept {report['kept_count']} clean frame(s), "
        f"dropped {report['dropped_count']} clipped frame(s) -> {args.output}"
    )


if __name__ == "__main__":
    main()
