#!/usr/bin/env python3
"""Estimate total screenshots for a TapTap ADB capture plan."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def resolve_top(top: dict, profiles: dict) -> dict:
    resolved = dict(top)
    profile_name = top.get("profile")
    if profile_name:
        profile = profiles.get(profile_name, {})
        if "strategy" in profile:
            resolved["strategy"] = profile["strategy"]
        if "capture" in profile:
            resolved["capture"] = profile["capture"]
        if "scroll_swipes" in profile:
            resolved["scroll_swipes"] = profile["scroll_swipes"]
    if "strategy" not in resolved:
        resolved["strategy"] = "scroll"
    return resolved


def estimate_segment(resolved: dict, global_scroll_swipes: int, estimates: dict) -> int:
    profile_name = resolved.get("profile", "feed_scroll" if resolved.get("strategy") == "scroll" else "hybrid")
    if profile_name in estimates:
        return int(estimates[profile_name])
    if resolved.get("strategy") == "scroll":
        swipes = int(resolved.get("scroll_swipes", global_scroll_swipes))
        return swipes + 1
    return int(estimates.get("hybrid_community", 60))


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Estimate TapTap ADB capture volume.")
    parser.add_argument("--tabs-config", type=Path, default=root / "config" / "taptap_tabs.yaml")
    parser.add_argument("--profiles-config", type=Path, default=root / "config" / "taptap_capture_profiles.yaml")
    parser.add_argument(
        "--bottom-tab",
        default="all",
        help="Estimate only one bottom tab (b01, b02, find_games, all, ...). Default: all",
    )
    args = parser.parse_args()

    tabs = load_yaml(args.tabs_config)
    prof_cfg = load_yaml(args.profiles_config)
    profiles = prof_cfg.get("profiles", {})
    estimates = prof_cfg.get("profile_estimates", {})
    global_swipes = int(tabs.get("scroll_swipes", 99))

    bottom_filter: str | None = None
    if args.bottom_tab and args.bottom_tab.lower() not in ("all", "*"):
        from adb_taptap_capture import resolve_bottom_tab_spec

        bottom_filter = resolve_bottom_tab_spec(tabs, args.bottom_tab)

    total = 0
    rows: list[tuple[str, str, str, int]] = []
    for bottom in tabs["bottom_tabs"]:
        if bottom_filter and bottom["id"] != bottom_filter:
            continue
        for top in bottom["top_tabs"]:
            resolved = resolve_top(top, profiles)
            key = f"{bottom['id']}_{top['id']}"
            est = estimate_segment(resolved, global_swipes, estimates)
            total += est
            rows.append((key, bottom["label"], top.get("label", top["id"]), est))

    scope = bottom_filter or "all"
    print(f"Bottom tab scope: {scope}")
    print(f"Segments: {len(rows)}")
    print(f"Estimated saved screenshots: ~{total}")
    print(f"Target range: {tabs.get('target_total_min', '?')}-{tabs.get('target_total_max', '?')}")
    print()
    for key, bottom, top, est in rows:
        print(f"  {key:10} {bottom:12} / {top:16} ~{est}")


if __name__ == "__main__":
    main()
