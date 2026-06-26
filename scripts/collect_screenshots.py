#!/usr/bin/env python3
"""Collect Maestro test screenshots and generate run_manifest.json."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


def find_png_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.png"))


def is_failure_screenshot(path: Path) -> bool:
    name = path.name
    if name.startswith("screenshot-"):
        return True
    if "\u274c" in name or "\u26a0" in name or "\u2757" in name:
        return True
    return False


def is_valid_output_name(path: Path) -> bool:
    """Only keep deliberate takeScreenshot outputs (e.g. b1t1_*, 01_launch)."""
    if is_failure_screenshot(path):
        return False
    stem = path.stem
    if stem.startswith("b1t1_"):
        return True
    if re.match(r"^b\d{2}_t\d{2}_", stem):
        return True
    if re.match(r"^hnrb_", stem):
        return True
    if re.match(r"^\d+_(launch|find_games|swipe|ranking|community|home|feed)", stem):
        return True
    if re.match(r"^\d{2}_", stem) and "screenshot" not in stem.lower():
        return True
    return not name_looks_like_maestro_debug(path.name)


def name_looks_like_maestro_debug(name: str) -> bool:
    return name.startswith("screenshot-") or "(scroll_" in name or "(home_browse" in name


def natural_screenshot_sort_key(path: Path) -> tuple:
    """Order b01_t02_001_overview, b1t1_1, b01_t01_00_start, etc."""
    stem = path.stem
    numbered = re.match(r"^(b\d{2}_t\d{2}|b1t1|hnrb_[\w]+)_(\d{3})_(.+)$", stem)
    if numbered:
        return (numbered.group(1), int(numbered.group(2)), numbered.group(3))

    legacy = re.match(r"^(b\d{2}_t\d{2}|b1t1)_(.+)$", stem)
    if not legacy:
        return (stem, 0)
    prefix, suffix = legacy.group(1), legacy.group(2)
    if suffix == "00_start":
        return (prefix, 0, suffix)
    if suffix.isdigit():
        return (prefix, int(suffix), "")
    return (prefix, 9999, suffix)


def prefer_flow_screenshots(root: Path) -> list[Path]:
    """Prefer Maestro takeScreenshot outputs over failure/debug captures."""
    named_dir = root / "screenshots"
    if named_dir.is_dir():
        named = list(named_dir.glob("*.png"))
        if named:
            return sorted(named, key=natural_screenshot_sort_key)

    all_pngs = find_png_files(root)
    flow_shots = [p for p in all_pngs if is_valid_output_name(p)]
    if flow_shots:
        return sorted(flow_shots, key=natural_screenshot_sort_key)
    return []


def find_maestro_output_dirs(project_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for pattern in (".maestro/tests", ".maestro"):
        candidates.extend(project_root.glob(f"{pattern}/**"))
    home = Path.home() / ".maestro" / "tests"
    if home.exists():
        candidates.extend(home.iterdir())
    return [p for p in candidates if p.is_dir()]


def newest_png_dir(dirs: list[Path]) -> Path | None:
    best: Path | None = None
    best_mtime = 0.0
    for d in dirs:
        for png in find_png_files(d):
            mtime = png.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best = png.parent
    return best


def step_name_from_file(path: Path) -> str:
    stem = path.stem
    match = re.match(r"^\d+_(.+)$", stem)
    if match:
        return match.group(1)
    return stem


def collect(
    *,
    input_dir: Path | None,
    output_dir: Path,
    app: str,
    flow: str,
    device: str | None,
    project_root: Path,
) -> dict:
    source_dir = input_dir
    if source_dir is None or not source_dir.exists():
        maestro_dirs = find_maestro_output_dirs(project_root)
        source_dir = newest_png_dir(maestro_dirs)

    output_dir.mkdir(parents=True, exist_ok=True)
    screenshots: list[dict] = []

    png_files = prefer_flow_screenshots(source_dir) if source_dir else []
    if not png_files and input_dir and input_dir.exists():
        png_files = prefer_flow_screenshots(input_dir)
        source_dir = input_dir

    for index, src in enumerate(png_files, start=1):
        step = step_name_from_file(src)
        dest_name = f"{index:05d}_{step}.png"
        dest = output_dir / dest_name
        shutil.copy2(src, dest)
        screenshots.append(
            {
                "step": step,
                "file": str(dest.relative_to(project_root)).replace("\\", "/"),
                "source": str(src),
            }
        )

    manifest = {
        "app": app,
        "flow": flow,
        "device": device,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(source_dir) if source_dir else None,
        "screenshot_count": len(screenshots),
        "screenshots": screenshots,
    }

    manifest_path = output_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Maestro screenshots into run folder.")
    parser.add_argument("--input", type=Path, default=None, help="Maestro test output directory")
    parser.add_argument("--output", type=Path, required=True, help="Destination run directory")
    parser.add_argument("--app", required=True, help="App key (e.g. taptap_lite)")
    parser.add_argument("--flow", default="home_browse", help="Flow name")
    parser.add_argument("--device", default=None, help="Device id or name")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="PageSnapFlow project root",
    )
    args = parser.parse_args()

    manifest = collect(
        input_dir=args.input,
        output_dir=args.output,
        app=args.app,
        flow=args.flow,
        device=args.device,
        project_root=args.project_root,
    )
    print(f"Collected {manifest['screenshot_count']} screenshot(s) -> {args.output}")
    print(f"Manifest: {args.output / 'run_manifest.json'}")


if __name__ == "__main__":
    main()
