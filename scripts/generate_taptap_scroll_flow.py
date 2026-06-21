#!/usr/bin/env python3
"""Generate flows/taptap_lite/scroll_all_tabs.yaml from config/taptap_tabs.yaml."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def indent_block(lines: list[str], spaces: int = 4) -> list[str]:
    pad = " " * spaces
    return [f"{pad}{line}" if line else line for line in lines]


def yaml_quote(value: str) -> str:
    escaped = str(value).replace('"', '\\"')
    return f'"{escaped}"'


def emit_tap(top: dict) -> list[str]:
    lines: list[str] = []
    optional = top.get("optional", False)
    if top.get("text"):
        if optional:
            lines.append(f'- tapOn: {{ text: {yaml_quote(top["text"])}, optional: true }}')
        else:
            lines.append(f'- tapOn: {{ text: {yaml_quote(top["text"])} }}')
    if top.get("point"):
        if optional:
            lines.append(f'- tapOn: {{ point: {yaml_quote(top["point"])}, optional: true }}')
        else:
            lines.append(f'- tapOn: {{ point: {yaml_quote(top["point"])} }}')
    return lines


def emit_segment(
    *,
    prefix: str,
    scroll_swipes: int,
    feed_swipe: dict,
    scroll_to_top: dict,
) -> list[str]:
    fs = feed_swipe
    st = scroll_to_top
    return [
        f'- evalScript: ${{output.prefix = "{prefix}"}}',
        "- evalScript: ${output.n = 0}",
        f'- swipe:\n    start: {st["start"]}\n    end: {st["end"]}\n    duration: {st["duration"]}',
        '- takeScreenshot: ${output.prefix + "_00_start"}',
        "- repeat:",
        f"    times: {scroll_swipes}",
        "    commands:",
        f'      - swipe:\n          start: {fs["start"]}\n          end: {fs["end"]}\n          duration: {fs["duration"]}',
        "      - evalScript: ${output.n = output.n + 1}",
        '      - takeScreenshot: ${output.prefix + "_" + output.n}',
        "",
    ]


def generate(config_path: Path, output_path: Path) -> dict:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    scroll_swipes = int(config["scroll_swipes"])
    feed_swipe = config["feed_swipe"]
    scroll_to_top = config["scroll_to_top"]
    top_bar_swipes = config["top_bar_swipes"]
    bottom_tabs = config["bottom_tabs"]

    lines: list[str] = [
        "# AUTO-GENERATED — do not edit by hand.",
        f"# Source: {config_path.as_posix()}",
        f"# Regenerate: python scripts/generate_taptap_scroll_flow.py",
        f"# Segments: scroll_swipes={scroll_swipes} (+1 start => {scroll_swipes + 1} shots each)",
        "",
        "appId: com.taptap",
        "",
        "---",
        "- runFlow: ../common/ensure_taptap_ready.yaml",
        "",
        "- runFlow:",
        "    label: Dismiss dialogs if shown",
        "    commands:",
        '      - tapOn: { text: "允许", optional: true }',
        '      - tapOn: { text: "跳过", optional: true }',
        '      - tapOn: { text: "关闭", optional: true }',
        '      - tapOn: { text: "以后再说", optional: true }',
        "",
    ]

    segment_count = 0
    for bottom in bottom_tabs:
        b_id = bottom["id"]
        b_label = bottom["label"]
        lines.extend(
            [
                f"# --- Bottom: {b_label} ({b_id}) ---",
                f'- tapOn:\n    point: {yaml_quote(bottom["point"])}',
                "- waitForAnimationToEnd:",
                "    timeout: 300",
                "",
            ]
        )

        for top in bottom["top_tabs"]:
            t_id = top["id"]
            prefix = f"{b_id}_{t_id}"
            segment_count += 1
            lines.append(f"# Segment {segment_count}: {b_label} / {top.get('label', t_id)}")

            swipe_key = top.get("top_bar_swipe")
            if swipe_key:
                swipe = top_bar_swipes[swipe_key]
                lines.extend(
                    [
                        "- swipe:",
                        f'    start: {swipe["start"]}',
                        f'    end: {swipe["end"]}',
                        f'    duration: {swipe["duration"]}',
                    ]
                )

            lines.extend(emit_tap(top))
            lines.extend(
                [
                    "- waitForAnimationToEnd:",
                    "    timeout: 250",
                    "",
                ]
            )
            lines.extend(
                emit_segment(
                    prefix=prefix,
                    scroll_swipes=scroll_swipes,
                    feed_swipe=feed_swipe,
                    scroll_to_top=scroll_to_top,
                )
            )

            if swipe_key:
                reset = top_bar_swipes["reset"]
                lines.extend(
                    [
                        "- swipe:",
                        f'    start: {reset["start"]}',
                        f'    end: {reset["end"]}',
                        f'    duration: {reset["duration"]}',
                        "",
                    ]
                )

    shots_per_segment = scroll_swipes + 1
    total_shots = segment_count * shots_per_segment
    header_stats = (
        f"# Planned segments: {segment_count}, ~{total_shots} screenshots "
        f"({shots_per_segment} per segment)"
    )
    lines.insert(4, header_stats)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "segments": segment_count,
        "shots_per_segment": shots_per_segment,
        "total_shots_est": total_shots,
        "output": str(output_path),
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Generate TapTap scroll_all_tabs Maestro flow.")
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "config" / "taptap_tabs.yaml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "flows" / "taptap_lite" / "scroll_all_tabs.yaml",
    )
    args = parser.parse_args()

    stats = generate(args.config, args.output)
    print(
        f"Generated {stats['output']}: "
        f"{stats['segments']} segments x {stats['shots_per_segment']} shots "
        f"≈ {stats['total_shots_est']} screenshots"
    )


if __name__ == "__main__":
    main()
