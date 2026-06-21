#!/usr/bin/env python3
"""Deduplicate similar app screenshots (for swipe/scroll runs)."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

THUMB_W = 160
THUMB_H = 90


def scene_signature(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    return cv2.resize(gray, (THUMB_W, THUMB_H), interpolation=cv2.INTER_AREA)


def similarity(left: np.ndarray, right: np.ndarray) -> float:
    diff = np.abs(left.astype(np.float32) - right.astype(np.float32))
    return 1.0 - float(np.mean(diff)) / 255.0


def list_user_screenshots(input_dir: Path) -> list[Path]:
    images = []
    for path in sorted(input_dir.glob("*.png")):
        if path.name.startswith("screenshot-"):
            continue
        if "(scroll_" in path.name or "(home_browse" in path.name:
            continue
        images.append(path)
    return images


def dedup_folder(input_dir: Path, output_dir: Path, threshold: float) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    images = list_user_screenshots(input_dir)
    kept: list[tuple[Path, np.ndarray]] = []

    for path in images:
        img = cv2.imread(str(path))
        if img is None:
            print(f"Skip unreadable: {path.name}")
            continue
        sig = scene_signature(img)
        if kept and similarity(sig, kept[-1][1]) >= threshold:
            continue
        kept.append((path, sig))
        shutil.copy2(path, output_dir / path.name)

    manifest_src = input_dir / "run_manifest.json"
    if manifest_src.is_file():
        shutil.copy2(manifest_src, output_dir / "run_manifest.json")

    return len(kept)


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove near-duplicate app screenshots.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--similarity", type=float, default=0.92, help="Keep if similarity < threshold")
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"Input not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    count = dedup_folder(args.input, args.output, args.similarity)
    print(f"Kept {count} unique image(s) in {args.output}")


if __name__ == "__main__":
    main()
