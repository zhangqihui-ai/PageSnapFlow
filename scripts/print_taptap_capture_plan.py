#!/usr/bin/env python3
"""Print TapTap capture navigation plan from config (human-readable checklist)."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

MODE_LABELS = {
    "feed_scroll": "A 纯下滑",
    "ranking_scroll": "A' 榜单下滑(~top150)",
    "ranking_list_detail": "A'' 榜单+游戏详情深截",
    "hybrid_today": "C 今日游戏",
    "hybrid_category": "D 游戏分类",
    "hybrid_card_feed": "B 下滑+点卡片",
    "hybrid_community": "B 下滑+点帖子",
    "hybrid_forum": "B 下滑+点论坛帖",
    "hybrid_messages": "B 下滑+点消息",
    "hybrid_my_games": "B 下滑+点游戏",
    "hybrid_explore": "B 探索+点条目",
    "light_tab": "E 轻量(overview+短滚)",
}

BOTTOM_CN = {
    "find_games": "找游戏",
    "ranking": "排行榜",
    "community": "社区",
    "messages": "消息",
    "my_games": "我的游戏",
}


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def profile_steps_summary(profile: dict) -> str:
    cap = profile.get("capture", {})
    steps = cap.get("steps", [])
    parts: list[str] = []
    for step in steps:
        t = step["type"]
        if t == "capture":
            parts.append("overview")
        elif t == "horizontal":
            parts.append(f"横滑×{step.get('count', '?')}")
        elif t == "scroll_limited":
            parts.append(f"下滑≤{step.get('max_swipes', '?')}")
        elif t == "tap_scroll":
            parts.append(f"点击展开+滚{step.get('scroll_swipes', '?')}")
        elif t == "drill_down":
            n = len(step.get("entries", []))
            if step.get("game_detail_profile"):
                parts.append(f"点进{n}游戏+6子tab深截")
            else:
                parts.append(f"点进{n}项+BACK")
        elif t == "scroll_to_top":
            parts.append("滑回列表顶部")
    return " → ".join(parts) if parts else "滑到顶+连续下滑(遇重复停)"


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Print TapTap capture plan.")
    parser.add_argument("--tabs-config", type=Path, default=root / "config" / "taptap_tabs.yaml")
    parser.add_argument("--profiles-config", type=Path, default=root / "config" / "taptap_capture_profiles.yaml")
    args = parser.parse_args()

    tabs = load(args.tabs_config)
    prof_cfg = load(args.profiles_config)
    profiles = prof_cfg.get("profiles", {})
    estimates = prof_cfg.get("profile_estimates", {})

    print("=" * 72)
    print("TapTap 截图导航清单（按执行顺序）")
    print("=" * 72)
    print()
    print("每段导航: [底部tab?] → [左滑顶栏?] → 点顶栏子tab → 截图策略 → [顶栏复位]")
    print()

    seq = 0
    prev_bottom: str | None = None
    total_est = 0

    for bottom in tabs["bottom_tabs"]:
        b_id = bottom["id"]
        b_label = bottom["label"]
        b_cn = BOTTOM_CN.get(b_label, b_label)
        b_point = bottom["point"]

        print(f"## {b_cn} ({b_id}) @ {b_point}")
        print("-" * 72)

        for top in bottom["top_tabs"]:
            seq += 1
            key = f"{b_id}_{top['id']}"
            profile_name = top.get("profile", "feed_scroll")
            mode = MODE_LABELS.get(profile_name, profile_name)
            est = int(estimates.get(profile_name, 151))
            total_est += est

            swipe = top.get("top_bar_swipe")
            swipe_note = {"left": "左滑顶栏×1", "left2": "左滑顶栏×2"}.get(swipe or "", "顶栏首屏")
            bottom_note = "同底部" if prev_bottom == b_id else f"点底部→{b_cn}"
            prev_bottom = b_id

            name = top.get("text") or top.get("label", top["id"])
            point = top.get("point", "?")
            prof = profiles.get(profile_name, {})
            flow = profile_steps_summary(prof)

            print(f"  {seq:2}. [{key}] {name}")
            print(f"      导航: {bottom_note} | {swipe_note} | 点子tab {point}")
            print(f"      模式: {mode} (~{est}张)")
            print(f"      步骤: {flow}")
            print()

        print()

    print("=" * 72)
    print(f"合计: {seq} 段, 预计 ~{total_est} 张")
    print("=" * 72)


if __name__ == "__main__":
    main()
