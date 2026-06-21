#!/usr/bin/env python3
"""Report duplicate rate for a screenshot run folder."""

from __future__ import annotations

import argparse
import json
import sys
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from image_similarity import count_unique_images


def list_run_pngs(run_dir: Path) -> list[Path]:
    pngs = sorted(run_dir.glob("*.png"))
    if pngs:
        return pngs
    nested = sorted((run_dir / "screenshots").glob("*.png")) if (run_dir / "screenshots").is_dir() else []
    return nested


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze duplicate screenshot rate in a run folder.")
    parser.add_argument("--input", type=Path, required=True, help="Run output dir with numbered pngs")
    parser.add_argument("--similarity", type=float, default=0.95, help="Duplicate if similarity >= threshold")
    parser.add_argument("--report", type=Path, default=None, help="Write JSON report path")
    args = parser.parse_args()

    pngs = list_run_pngs(args.input)
    if not pngs:
        print(f"No PNG files under {args.input}", file=sys.stderr)
        return 1

    total, unique, dup_rate = count_unique_images(pngs, args.similarity)
    report = {
        "input": str(args.input),
        "total_screenshots": total,
        "unique_screenshots": unique,
        "duplicate_count": total - unique,
        "duplicate_rate": round(dup_rate, 4),
        "similarity_threshold": args.similarity,
    }

    print(
        f"Duplicate analysis: {unique}/{total} unique "
        f"({dup_rate * 100:.1f}% duplicates at similarity>={args.similarity})"
    )

    report_path = args.report or (args.input / "duplicate_report.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
