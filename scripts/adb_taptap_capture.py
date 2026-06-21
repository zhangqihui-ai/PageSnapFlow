#!/usr/bin/env python3
"""TapTap scroll capture via ADB (no Maestro takeScreenshot / UI settle wait)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from image_similarity import count_unique_images, signature_from_path, similarity


def safe_unlink(path: Path, retries: int = 5, delay_ms: int = 80) -> bool:
    for attempt in range(retries):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError:
            if attempt + 1 >= retries:
                return False
            time.sleep(delay_ms / 1000.0)
    return False


def progress_file_path(output_dir: Path) -> Path:
    return output_dir / "capture_progress.json"


def load_progress(output_dir: Path) -> dict:
    path = progress_file_path(output_dir)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"completed_segments": [], "flow": None}


def save_progress(output_dir: Path, progress: dict) -> None:
    progress_file_path(output_dir).write_text(
        json.dumps(progress, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def clear_segment_shots(shots_dir: Path, prefix: str) -> int:
    removed = 0
    for path in shots_dir.glob(f"{prefix}_*.png"):
        if safe_unlink(path):
            removed += 1
    return removed


def segment_shot_count(shots_dir: Path, prefix: str) -> int:
    return len(list(shots_dir.glob(f"{prefix}_*.png")))


def infer_resume_index(
    plans: list[SegmentPlan],
    shots_dir: Path,
    progress: dict,
    config: dict,
    resume_from: str | None,
) -> int:
    if resume_from:
        for index, plan in enumerate(plans):
            if plan.key == resume_from:
                cleared = clear_segment_shots(shots_dir, plan.prefix)
                if cleared:
                    print(f"Resume: cleared {cleared} partial file(s) for {plan.key}", flush=True)
                return index
        raise ValueError(f"Unknown segment key for --resume-from: {resume_from!r}")

    completed = progress.get("completed_segments") or []
    if completed:
        completed_set = set(completed)
        for index, plan in enumerate(plans):
            if plan.key not in completed_set:
                file_count = segment_shot_count(shots_dir, plan.prefix)
                if file_count > 0:
                    strategy = plan.top.get("strategy", "scroll")
                    if strategy == "scroll":
                        expected = int(plan.top.get("scroll_swipes", config.get("scroll_swipes", 99))) + 1
                        if file_count < max(20, int(expected * 0.25)):
                            cleared = clear_segment_shots(shots_dir, plan.prefix)
                            print(
                                f"Resume: inferred partial segment {plan.key} ({file_count} files), "
                                f"cleared {cleared}, restarting it",
                                flush=True,
                            )
                            return index
                    print(
                        f"Resume: continuing partial segment {plan.key} ({file_count} files kept)",
                        flush=True,
                    )
                    return index
                return index
        return len(plans)

    last_idx = -1
    for index, plan in enumerate(plans):
        if segment_shot_count(shots_dir, plan.prefix) > 0:
            last_idx = index
        else:
            break

    if last_idx < 0:
        return 0

    plan = plans[last_idx]
    file_count = segment_shot_count(shots_dir, plan.prefix)
    strategy = plan.top.get("strategy", "scroll")
    if strategy == "scroll":
        expected = int(plan.top.get("scroll_swipes", config.get("scroll_swipes", 99))) + 1
        if file_count < max(20, int(expected * 0.25)):
            cleared = clear_segment_shots(shots_dir, plan.prefix)
            print(
                f"Resume: inferred partial segment {plan.key} ({file_count} files), "
                f"cleared {cleared}, restarting it",
                flush=True,
            )
            return last_idx

    next_index = last_idx + 1
    if next_index < len(plans):
        next_plan = plans[next_index]
        if segment_shot_count(shots_dir, next_plan.prefix) > 0:
            cleared = clear_segment_shots(shots_dir, next_plan.prefix)
            print(
                f"Resume: cleared {cleared} partial file(s) for {next_plan.key}, continuing",
                flush=True,
            )
        print(f"Resume: continuing from segment {next_index + 1}/{len(plans)} ({plans[next_index].key})", flush=True)
        return next_index

    return len(plans)


@dataclass
class SegmentPlan:
    key: str
    prefix: str
    bottom: dict
    top: dict


class AdbDevice:
    def __init__(self, device: str | None, tap_delay_ms: int) -> None:
        self.device = device or self._default_device()
        self.tap_delay_ms = tap_delay_ms
        self._size: tuple[int, int] | None = None

    @staticmethod
    def _default_device() -> str:
        out = subprocess.check_output(["adb", "devices"], text=True, encoding="utf-8", errors="replace")
        for line in out.splitlines()[1:]:
            if "\tdevice" in line:
                return line.split("\t")[0].strip()
        raise RuntimeError("No adb device connected (adb devices).")

    def _adb(self, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        cmd = ["adb", "-s", self.device, *args]
        return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)

    def _adb_shell(self, *args: str, timeout: int = 60) -> None:
        self._adb("shell", *args, timeout=timeout)

    def sleep_ms(self, ms: int) -> None:
        if ms > 0:
            time.sleep(ms / 1000.0)

    @property
    def size(self) -> tuple[int, int]:
        if self._size is None:
            self._size = self._read_screen_size()
        return self._size

    def _read_screen_size(self) -> tuple[int, int]:
        proc = self._adb("shell", "wm", "size")
        text = proc.stdout or proc.stderr or ""
        for line in text.splitlines():
            lower = line.lower()
            if "size:" in lower:
                part = line.split(":")[-1].strip()
                if "x" in part:
                    w_str, h_str = part.split("x", 1)
                    return int(w_str), int(h_str)
        raise RuntimeError(f"Could not parse screen size from: {text!r}")

    @staticmethod
    def parse_point(point: str, width: int, height: int) -> tuple[int, int]:
        x_part, y_part = [p.strip() for p in point.split(",", 1)]
        x = int(float(x_part.rstrip("%")) / 100.0 * width)
        y = int(float(y_part.rstrip("%")) / 100.0 * height)
        return x, y

    def tap_point(self, point: str) -> None:
        x, y = self.parse_point(point, *self.size)
        self._adb_shell("input", "tap", str(x), str(y))
        self.sleep_ms(self.tap_delay_ms)

    def swipe_points(self, start: str, end: str, duration_ms: int) -> None:
        w, h = self.size
        x1, y1 = self.parse_point(start, w, h)
        x2, y2 = self.parse_point(end, w, h)
        self._adb_shell(
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        )

    def press_back(self) -> None:
        self._adb_shell("input", "keyevent", "4")
        self.sleep_ms(self.tap_delay_ms)

    def tap_back(self, point: str, wait_ms: int = 450) -> None:
        """TapTap game detail uses top-left arrow; system BACK often does nothing."""
        self.tap_point(point)
        self.sleep_ms(wait_ms)

    def screencap(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["adb", "-s", self.device, "exec-out", "screencap", "-p"]
        with dest.open("wb") as fp:
            subprocess.run(cmd, check=True, stdout=fp, timeout=30)


@dataclass
class ShotWriter:
    adb: AdbDevice
    shots_dir: Path
    prefix: str
    post_swipe_delay_ms: int
    duplicate_threshold: float | None
    skip_duplicate_saves: bool = True
    seq: int = 0
    skipped_duplicates: int = 0
    last_sig: Any = field(default=None, repr=False)
    paths: list[Path] = field(default_factory=list)

    def capture(self, label: str) -> tuple[Path | None, bool]:
        safe_label = re.sub(r"[^\w\-]+", "_", label).strip("_") or "shot"
        filename = f"{self.prefix}_{self.seq:03d}_{safe_label}.png"
        dest = self.shots_dir / filename
        self.adb.screencap(dest)

        sig = signature_from_path(dest)
        is_duplicate = False
        if sig is not None and self.last_sig is not None and self.duplicate_threshold is not None:
            is_duplicate = similarity(sig, self.last_sig) >= self.duplicate_threshold

        if is_duplicate and self.skip_duplicate_saves:
            if not safe_unlink(dest):
                print(f"  warning: duplicate kept (file locked): {dest.name}", flush=True)
                self.paths.append(dest)
                self.seq += 1
                if sig is not None:
                    self.last_sig = sig
                return dest, True
            self.skipped_duplicates += 1
            return None, True

        self.paths.append(dest)
        self.seq += 1
        if sig is not None:
            self.last_sig = sig
        return dest, is_duplicate


def load_settings(
    tabs_config_path: Path,
    adb_config_path: Path,
    profiles_config_path: Path,
) -> tuple[dict, dict, dict, dict]:
    tabs = yaml.safe_load(tabs_config_path.read_text(encoding="utf-8"))
    adb_cfg = yaml.safe_load(adb_config_path.read_text(encoding="utf-8"))
    prof_cfg = yaml.safe_load(profiles_config_path.read_text(encoding="utf-8"))
    timing = dict(adb_cfg.get("adb_capture", {}))
    timing["capture_defaults"] = adb_cfg.get("capture_defaults", {})
    capture_profiles = prof_cfg.get("profiles", {})
    return tabs, adb_cfg.get("flow_profiles", {}), timing, capture_profiles


def resolve_top_tab(top: dict, capture_profiles: dict) -> dict:
    resolved = dict(top)
    profile_name = top.get("profile")
    if profile_name:
        profile = capture_profiles.get(profile_name)
        if profile is None:
            raise KeyError(f"Unknown capture profile: {profile_name!r}")
        if "strategy" in profile:
            resolved["strategy"] = profile["strategy"]
        if "capture" in profile:
            resolved["capture"] = profile["capture"]
        if "scroll_swipes" in profile:
            resolved["scroll_swipes"] = profile["scroll_swipes"]
    if "strategy" not in resolved:
        resolved["strategy"] = "scroll"
    return resolved


def find_bottom(config: dict, bottom_id: str) -> dict:
    for bottom in config["bottom_tabs"]:
        if bottom["id"] == bottom_id:
            return bottom
    raise KeyError(f"Unknown bottom tab id: {bottom_id}")


BOTTOM_TAB_ALIASES: dict[str, str] = {
    "all": "all",
    "*": "all",
    "b01": "b01",
    "1": "b01",
    "find_games": "b01",
    "找游戏": "b01",
    "b02": "b02",
    "2": "b02",
    "ranking": "b02",
    "排行榜": "b02",
    "b03": "b03",
    "3": "b03",
    "community": "b03",
    "社区": "b03",
    "b04": "b04",
    "4": "b04",
    "messages": "b04",
    "消息": "b04",
    "b05": "b05",
    "5": "b05",
    "my_games": "b05",
    "我的游戏": "b05",
}


def resolve_bottom_tab_spec(config: dict, spec: str) -> str:
    raw = spec.strip()
    lowered = raw.lower()
    if lowered in BOTTOM_TAB_ALIASES:
        return BOTTOM_TAB_ALIASES[lowered]
    if raw in BOTTOM_TAB_ALIASES:
        return BOTTOM_TAB_ALIASES[raw]
    for bottom in config["bottom_tabs"]:
        if bottom["id"] == raw:
            return bottom["id"]
        if bottom.get("label", "").lower() == lowered:
            return bottom["id"]
    options = "all, b01/find_games, b02/ranking, b03/community, b04/messages, b05/my_games"
    raise ValueError(f"Unknown bottom tab {spec!r}. Use one of: {options}")


def filter_plans_by_bottom_tab(plans: list[SegmentPlan], bottom_id: str) -> list[SegmentPlan]:
    return [plan for plan in plans if plan.bottom["id"] == bottom_id]


def bottom_tab_display(config: dict, bottom_id: str) -> str:
    bottom = find_bottom(config, bottom_id)
    label = bottom.get("label", bottom_id)
    text = bottom.get("text")
    if text:
        return f"{text} ({label}, {bottom_id})"
    return f"{label} ({bottom_id})"


def find_top(bottom: dict, top_id: str) -> dict:
    for top in bottom["top_tabs"]:
        if top["id"] == top_id:
            return top
    raise KeyError(f"Unknown top tab id: {top_id} in {bottom['id']}")


def build_segment_plans(
    config: dict,
    flow: str,
    flow_profiles: dict,
    capture_profiles: dict,
) -> list[SegmentPlan]:
    profile = flow_profiles.get(flow)
    if profile is None:
        supported = ", ".join(sorted(flow_profiles))
        raise ValueError(f"Flow {flow!r} has no ADB profile. Supported: {supported}")

    prefix_map: dict[str, str] = profile.get("prefix_map", {})
    segments_spec = profile["segments"]
    plans: list[SegmentPlan] = []

    if segments_spec == "all":
        for bottom in config["bottom_tabs"]:
            for top in bottom["top_tabs"]:
                key = f"{bottom['id']}_{top['id']}"
                prefix = prefix_map.get(key, key)
                resolved = resolve_top_tab(top, capture_profiles)
                plans.append(SegmentPlan(key=key, prefix=prefix, bottom=bottom, top=resolved))
        return plans

    for key in segments_spec:
        bottom_id, top_id = key.split("_", 1)
        bottom = find_bottom(config, bottom_id)
        top = resolve_top_tab(find_top(bottom, top_id), capture_profiles)
        prefix = prefix_map.get(key, key)
        plans.append(SegmentPlan(key=key, prefix=prefix, bottom=bottom, top=top))
    return plans


def maybe_top_bar_swipe(adb: AdbDevice, config: dict, top: dict) -> None:
    swipe_key = top.get("top_bar_swipe")
    if not swipe_key:
        return
    swipe = config["top_bar_swipes"][swipe_key]
    adb.swipe_points(swipe["start"], swipe["end"], int(swipe["duration"]))


def reset_top_bar(adb: AdbDevice, config: dict, top: dict) -> None:
    if not top.get("top_bar_swipe"):
        return
    reset = config["top_bar_swipes"]["reset"]
    adb.swipe_points(reset["start"], reset["end"], int(reset["duration"]))


def tap_top_tab(adb: AdbDevice, top: dict) -> None:
    if top.get("point"):
        adb.tap_point(top["point"])


def navigate_to_segment(
    adb: AdbDevice,
    config: dict,
    plan: SegmentPlan,
    skip_bottom_tap: bool,
) -> None:
    if not skip_bottom_tap:
        adb.tap_point(plan.bottom["point"])
    maybe_top_bar_swipe(adb, config, plan.top)
    tap_top_tab(adb, plan.top)


def capture_scroll_strategy(
    *,
    adb: AdbDevice,
    config: dict,
    top: dict,
    writer: ShotWriter,
    post_swipe_delay_ms: int,
    timing: dict,
    max_swipes: int | None = None,
    include_intro: bool = True,
    name_prefix: str = "scroll",
) -> None:
    scroll_swipes = int(max_swipes if max_swipes is not None else top.get("scroll_swipes", config["scroll_swipes"]))
    feed = config["feed_swipe"]
    scroll_to_top = config["scroll_to_top"]
    defaults = timing.get("capture_defaults", {})
    overrides = top.get("capture", {})
    capture_cfg = {**defaults, **overrides}
    stop_after_dupes = int(capture_cfg.get("scroll_stop_after_dupes", 3))

    if include_intro:
        adb.swipe_points(scroll_to_top["start"], scroll_to_top["end"], int(scroll_to_top["duration"]))
        writer.capture("overview")

    consecutive_dupes = 0
    for n in range(1, scroll_swipes + 1):
        adb.swipe_points(feed["start"], feed["end"], int(feed["duration"]))
        adb.sleep_ms(post_swipe_delay_ms)
        _, is_dup = writer.capture(f"{name_prefix}_{n:02d}")
        if is_dup:
            consecutive_dupes += 1
            if consecutive_dupes >= stop_after_dupes:
                print(f"  scroll: stopped early at {n} ({stop_after_dupes} consecutive duplicates)", flush=True)
                break
        else:
            consecutive_dupes = 0


def capture_horizontal_dates(
    *,
    adb: AdbDevice,
    writer: ShotWriter,
    step: dict,
) -> None:
    swipe = step["swipe"]
    count = int(step.get("count", 7))
    for i in range(count):
        writer.capture(step.get("name_prefix", "date") + f"_{i:02d}")
        if i < count - 1:
            adb.swipe_points(swipe["start"], swipe["end"], int(swipe.get("duration", 250)))
            adb.sleep_ms(int(step.get("wait_ms", 200)))

    reset = step.get("reset_swipe")
    if reset:
        adb.swipe_points(reset["start"], reset["end"], int(reset.get("duration", 350)))


def capture_vertical_scroll(
    *,
    adb: AdbDevice,
    config: dict,
    writer: ShotWriter,
    name_prefix: str,
    post_swipe_delay_ms: int,
    max_swipes: int,
    stop_after_dupes: int,
) -> None:
    feed = config["feed_swipe"]
    consecutive_dupes = 0
    for n in range(1, max_swipes + 1):
        adb.swipe_points(feed["start"], feed["end"], int(feed["duration"]))
        adb.sleep_ms(post_swipe_delay_ms)
        _, is_dup = writer.capture(f"{name_prefix}_{n:02d}")
        if is_dup:
            consecutive_dupes += 1
            if consecutive_dupes >= stop_after_dupes:
                print(
                    f"    scroll: stopped at {name_prefix} #{n} "
                    f"({stop_after_dupes} consecutive duplicates)",
                    flush=True,
                )
                break
        else:
            consecutive_dupes = 0


def scroll_list_feed(
    adb: AdbDevice,
    config: dict,
    swipes: int,
    post_swipe_delay_ms: int,
) -> None:
    if swipes <= 0:
        return
    feed = config["feed_swipe"]
    for _ in range(swipes):
        adb.swipe_points(feed["start"], feed["end"], int(feed["duration"]))
        adb.sleep_ms(post_swipe_delay_ms)


def navigate_back_from_detail(adb: AdbDevice, config: dict, opts: dict | None = None) -> bool:
    """Tap top-left back; retry until page changes or max attempts."""
    ui = config.get("ui_points", {})
    merged = {**ui, **(opts or {})}
    point = merged.get("back", "6%, 13%")
    wait_ms = int(merged.get("after_back_ms", 500))
    use_keyevent = bool(merged.get("back_keyevent_fallback", False))
    max_attempts = int(merged.get("back_max_attempts", 3))
    threshold = float(merged.get("back_verify_threshold", 0.90))

    for attempt in range(1, max_attempts + 1):
        before = screencap_signature(adb)
        print(f"    back: tap {point} (attempt {attempt}/{max_attempts})", flush=True)
        adb.tap_back(point, wait_ms=wait_ms)
        if use_keyevent:
            adb.press_back()
            adb.sleep_ms(wait_ms)
        after = screencap_signature(adb)
        if before is None or after is None or similarity(before, after) < threshold:
            print("    back: left page", flush=True)
            return True
    print("    back: warning — page unchanged after back taps", flush=True)
    return False


def screencap_signature(adb: AdbDevice) -> Any:
    tmp = Path(tempfile.gettempdir()) / f"taptap_cap_{time.time_ns()}.png"
    try:
        adb.screencap(tmp)
        return signature_from_path(tmp)
    finally:
        safe_unlink(tmp)


def detect_active_detail_tab(
    adb: AdbDevice,
    tab_points: list[tuple[str, str]],
    nav_ms: int,
    threshold: float = 0.97,
) -> str | None:
    """Tap each tab header; the active one will not change page content."""
    ref = screencap_signature(adb)
    for name, point in tab_points:
        adb.tap_point(point)
        adb.sleep_ms(nav_ms)
        sig = screencap_signature(adb)
        if ref is not None and sig is not None and similarity(ref, sig) >= threshold:
            return name
        ref = sig
    return None


def build_layout_tab_points(
    layouts: dict,
    layout_name: str,
    landing: dict,
    tab_defaults: dict,
) -> list[tuple[str, str]]:
    detail_point = tab_defaults.get("detail_tab_point", landing.get("detail_point", "38%, 13%"))
    if layout_name == "full":
        points: list[tuple[str, str]] = [
            ("stats", tab_defaults.get("probe_point", "20%, 13%")),
            ("detail", detail_point),
        ]
        for tab in layouts.get("full", []):
            if tab["name"] not in ("stats", "detail"):
                points.append((tab["name"], tab["point"]))
        return points
    points = [("detail", detail_point)]
    for tab in layouts.get("minimal", []):
        points.append((tab["name"], tab["point"]))
    return points


def detect_game_detail_location(
    adb: AdbDevice,
    tab_defaults: dict,
    layouts: dict,
    landing: dict,
    nav_ms: int,
) -> dict:
    """Return surface=list|game_detail|forum_nested plus optional layout/active_tab."""
    probe_threshold = float(tab_defaults.get("probe_threshold", 0.94))
    detail_point = tab_defaults.get("detail_tab_point", landing.get("detail_point", "38%, 13%"))
    forum_nested_tab = tab_defaults.get("forum_nested_tab", "8%, 18%")

    ref = screencap_signature(adb)
    if tab_page_changed(adb, detail_point, ref, nav_ms, probe_threshold):
        stats_point = tab_defaults.get("probe_point", "20%, 13%")
        ref2 = screencap_signature(adb)
        if layouts.get("full") and tab_page_changed(adb, stats_point, ref2, nav_ms, probe_threshold):
            layout = "full"
        elif layouts.get("minimal"):
            layout = "minimal"
        else:
            layout = "full"
        probe_points = build_layout_tab_points(layouts, layout, landing, tab_defaults)
        active = detect_active_detail_tab(adb, probe_points, nav_ms)
        return {"surface": "game_detail", "layout": layout, "active_tab": active}

    ref = screencap_signature(adb)
    if not tab_page_changed(adb, forum_nested_tab, ref, nav_ms, 0.97):
        nested_points = [
            ("forum_all", forum_nested_tab),
            ("forum_guides", tab_defaults.get("forum_nested_guides", "22%, 18%")),
            ("forum_official", tab_defaults.get("forum_nested_official", "36%, 18%")),
        ]
        active = detect_active_detail_tab(adb, nested_points, nav_ms)
        return {
            "surface": "forum_nested",
            "layout": None,
            "active_tab": active or "forum_all",
        }

    return {"surface": "list", "layout": None, "active_tab": None}


def print_detail_location(loc: dict, prefix: str = "locate") -> None:
    parts = [f"surface={loc['surface']}"]
    if loc.get("layout"):
        parts.append(f"layout={loc['layout']}")
    if loc.get("active_tab"):
        parts.append(f"tab={loc['active_tab']}")
    print(f"    {prefix}: {', '.join(parts)}", flush=True)


def ensure_exit_forum_nested(
    adb: AdbDevice,
    config: dict,
    tab_defaults: dict,
    layouts: dict,
    landing: dict,
    nav_ms: int,
) -> dict:
    """Leave full-screen forum feed (截图2) if present; report where we landed."""
    max_backs = int(tab_defaults.get("forum_nested_max_backs", 2))
    loc = detect_game_detail_location(adb, tab_defaults, layouts, landing, nav_ms)
    print_detail_location(loc)
    for _ in range(max_backs):
        if loc["surface"] != "forum_nested":
            return loc
        print("    back: exit forum feed view", flush=True)
        navigate_back_from_detail(adb, config, tab_defaults)
        loc = detect_game_detail_location(adb, tab_defaults, layouts, landing, nav_ms)
        print_detail_location(loc)
    return loc


def tab_page_changed(
    adb: AdbDevice,
    point: str,
    ref_sig: Any,
    navigation_delay_ms: int,
    threshold: float = 0.94,
) -> bool:
    """Tap a tab header and check whether page content changed."""
    adb.tap_point(point)
    adb.sleep_ms(navigation_delay_ms)
    tmp = Path(tempfile.gettempdir()) / f"taptap_probe_{time.time_ns()}.png"
    try:
        adb.screencap(tmp)
        sig = signature_from_path(tmp)
        if ref_sig is None or sig is None:
            return True
        return similarity(sig, ref_sig) < threshold
    finally:
        safe_unlink(tmp)


def capture_vertical_scroll_with_transition(
    *,
    adb: AdbDevice,
    config: dict,
    writer: ShotWriter,
    name_prefix: str,
    post_swipe_delay_ms: int,
    max_swipes: int,
    stop_after_dupes: int,
    transition_threshold: float = 0.88,
    transition_min_swipe: int = 1,
) -> bool:
    """Scroll and capture; return True if UI jumped into another surface mid-scroll."""
    feed = config["feed_swipe"]
    consecutive_dupes = 0
    entered_nested = False
    prev_sig = writer.last_sig
    for n in range(1, max_swipes + 1):
        adb.swipe_points(feed["start"], feed["end"], int(feed["duration"]))
        adb.sleep_ms(post_swipe_delay_ms)
        _, is_dup = writer.capture(f"{name_prefix}_{n:02d}")
        if (
            not entered_nested
            and n >= transition_min_swipe
            and prev_sig is not None
            and writer.last_sig is not None
            and similarity(prev_sig, writer.last_sig) < transition_threshold
        ):
            entered_nested = True
            print(f"    forum: entered full feed view at swipe #{n}", flush=True)
        prev_sig = writer.last_sig
        if is_dup:
            consecutive_dupes += 1
            if consecutive_dupes >= stop_after_dupes:
                print(
                    f"    scroll: stopped at {name_prefix} #{n} "
                    f"({stop_after_dupes} consecutive duplicates)",
                    flush=True,
                )
                break
        else:
            consecutive_dupes = 0
    return entered_nested


def capture_detail_tab(
    *,
    adb: AdbDevice,
    config: dict,
    writer: ShotWriter,
    label: str,
    tab: dict,
    navigation_delay_ms: int,
    post_swipe_delay_ms: int,
    stop_after_dupes: int,
    tap: bool,
    tab_defaults: dict | None = None,
    layouts: dict | None = None,
    landing: dict | None = None,
) -> None:
    tab_name = tab.get("name", "tab")
    text = tab.get("text", tab_name)
    if tap:
        print(f"    game tab: {text}", flush=True)
        adb.tap_point(tab["point"])
        adb.sleep_ms(int(tab.get("wait_ms", navigation_delay_ms)))
    else:
        print(f"    game tab: {text} (default)", flush=True)
    writer.capture(f"{label}_{tab_name}_00")
    max_swipes = int(tab.get("max_swipes", 8))
    tab_stop = int(tab.get("scroll_stop_after_dupes", stop_after_dupes))
    defaults = tab_defaults or {}

    if tab.get("forum_nested") and layouts is not None and landing is not None:
        transition_threshold = float(
            tab.get("transition_threshold", defaults.get("forum_transition_threshold", 0.88))
        )
        entered = capture_vertical_scroll_with_transition(
            adb=adb,
            config=config,
            writer=writer,
            name_prefix=f"{label}_{tab_name}",
            post_swipe_delay_ms=post_swipe_delay_ms,
            max_swipes=max_swipes,
            stop_after_dupes=tab_stop,
            transition_threshold=transition_threshold,
        )
        loc = detect_game_detail_location(adb, defaults, layouts, landing, navigation_delay_ms)
        if entered or loc["surface"] == "forum_nested":
            nested_max = int(
                tab.get("nested_max_swipes", defaults.get("forum_nested_max_swipes", 12))
            )
            nested_stop = int(
                tab.get("nested_scroll_stop_after_dupes", defaults.get("forum_nested_scroll_stop_after_dupes", tab_stop))
            )
            print(f"    forum: capture feed view ({nested_max} swipes max)", flush=True)
            capture_vertical_scroll(
                adb=adb,
                config=config,
                writer=writer,
                name_prefix=f"{label}_{tab_name}_feed",
                post_swipe_delay_ms=post_swipe_delay_ms,
                max_swipes=nested_max,
                stop_after_dupes=nested_stop,
            )
        ensure_exit_forum_nested(
            adb, config, defaults, layouts, landing, navigation_delay_ms
        )
        return

    capture_vertical_scroll(
        adb=adb,
        config=config,
        writer=writer,
        name_prefix=f"{label}_{tab_name}",
        post_swipe_delay_ms=post_swipe_delay_ms,
        max_swipes=max_swipes,
        stop_after_dupes=tab_stop,
    )


def capture_game_detail_deep(
    *,
    adb: AdbDevice,
    config: dict,
    writer: ShotWriter,
    entry: dict,
    detail_profile: dict,
    navigation_delay_ms: int,
    post_swipe_delay_ms: int,
) -> None:
    label = entry.get("label", "game")
    tab_defaults = detail_profile.get("capture", {})
    adb.tap_point(entry["point"])
    adb.sleep_ms(navigation_delay_ms)

    stop_after_dupes = int(tab_defaults.get("scroll_stop_after_dupes", 3))
    dup_threshold = tab_defaults.get("duplicate_threshold")
    prev_threshold = writer.duplicate_threshold
    if dup_threshold is not None:
        writer.duplicate_threshold = float(dup_threshold)

    landing = detail_profile.get(
        "landing",
        {"name": "detail", "text": "详情", "max_swipes": 8},
    )
    layouts = detail_profile.get("layouts", {})
    legacy_tabs = detail_profile.get("tabs")
    probe_point = tab_defaults.get("probe_point", "20%, 13%")
    probe_threshold = float(tab_defaults.get("probe_threshold", 0.94))
    nav_ms = int(tab_defaults.get("navigation_delay_ms", navigation_delay_ms))
    ctx = {
        "tab_defaults": tab_defaults,
        "layouts": layouts,
        "landing": landing,
    }

    try:
        if layouts:
            capture_detail_tab(
                adb=adb,
                config=config,
                writer=writer,
                label=label,
                tab=landing,
                navigation_delay_ms=nav_ms,
                post_swipe_delay_ms=post_swipe_delay_ms,
                stop_after_dupes=stop_after_dupes,
                tap=False,
                **ctx,
            )
            detail_sig = writer.last_sig
            full_tabs = layouts.get("full", [])
            minimal_tabs = layouts.get("minimal", [])

            if full_tabs and tab_page_changed(
                adb, probe_point, detail_sig, nav_ms, probe_threshold
            ):
                print("    layout: full (统计/详情/评价/攻略/论坛)", flush=True)
                capture_detail_tab(
                    adb=adb,
                    config=config,
                    writer=writer,
                    label=label,
                    tab=full_tabs[0],
                    navigation_delay_ms=nav_ms,
                    post_swipe_delay_ms=post_swipe_delay_ms,
                    stop_after_dupes=stop_after_dupes,
                    tap=False,
                    **ctx,
                )
                for tab in full_tabs[1:]:
                    if tab.get("optional"):
                        sig = screencap_signature(adb)
                        if not tab_page_changed(
                            adb, tab["point"], sig, nav_ms, probe_threshold
                        ):
                            print(f"    skip optional tab {tab.get('text', tab['name'])}", flush=True)
                            continue
                        if tab.get("name") == "new_ver" and detail_sig is not None:
                            probe_sig = screencap_signature(adb)
                            if (
                                probe_sig is not None
                                and similarity(detail_sig, probe_sig) >= 0.92
                            ):
                                print("    skip 新版本 (5-tab layout)", flush=True)
                                continue
                        capture_detail_tab(
                            adb=adb,
                            config=config,
                            writer=writer,
                            label=label,
                            tab=tab,
                            navigation_delay_ms=nav_ms,
                            post_swipe_delay_ms=post_swipe_delay_ms,
                            stop_after_dupes=stop_after_dupes,
                            tap=False,
                            **ctx,
                        )
                        continue
                    capture_detail_tab(
                        adb=adb,
                        config=config,
                        writer=writer,
                        label=label,
                        tab=tab,
                        navigation_delay_ms=nav_ms,
                        post_swipe_delay_ms=post_swipe_delay_ms,
                        stop_after_dupes=stop_after_dupes,
                        tap=True,
                        **ctx,
                    )
            elif minimal_tabs:
                print("    layout: minimal (详情/评价/论坛)", flush=True)
                for tab in minimal_tabs:
                    capture_detail_tab(
                        adb=adb,
                        config=config,
                        writer=writer,
                        label=label,
                        tab=tab,
                        navigation_delay_ms=nav_ms,
                        post_swipe_delay_ms=post_swipe_delay_ms,
                        stop_after_dupes=stop_after_dupes,
                        tap=True,
                        **ctx,
                    )
        elif legacy_tabs:
            for tab in legacy_tabs:
                tab_name = tab.get("name", "tab")
                text = tab.get("text", tab_name)
                if tab.get("landing"):
                    print(f"    game tab: {text} (default)", flush=True)
                else:
                    print(f"    game tab: {text}", flush=True)
                    adb.tap_point(tab["point"])
                    adb.sleep_ms(int(tab.get("wait_ms", nav_ms)))
                _, is_dup = writer.capture(f"{label}_{tab_name}_00")
                if tab.get("optional") and is_dup and not tab.get("landing"):
                    print(f"    game tab: {text} skipped (not present)", flush=True)
                    continue
                max_swipes = int(tab.get("max_swipes", tab_defaults.get("max_swipes", 8)))
                tab_stop = int(tab.get("scroll_stop_after_dupes", stop_after_dupes))
                capture_vertical_scroll(
                    adb=adb,
                    config=config,
                    writer=writer,
                    name_prefix=f"{label}_{tab_name}",
                    post_swipe_delay_ms=post_swipe_delay_ms,
                    max_swipes=max_swipes,
                    stop_after_dupes=tab_stop,
                )
    finally:
        writer.duplicate_threshold = prev_threshold

    loc = ensure_exit_forum_nested(adb, config, tab_defaults, layouts, landing, nav_ms)
    if loc["surface"] == "game_detail":
        navigate_back_from_detail(adb, config, tab_defaults)
        loc = detect_game_detail_location(adb, tab_defaults, layouts, landing, nav_ms)
        print_detail_location(loc, prefix="locate after exit")
    elif loc["surface"] == "forum_nested":
        print("    warning: still in forum feed after back attempts", flush=True)
    else:
        print_detail_location(loc, prefix="locate after exit")


def capture_drill_down_entry(
    *,
    adb: AdbDevice,
    config: dict,
    writer: ShotWriter,
    entry: dict,
    navigation_delay_ms: int,
    post_swipe_delay_ms: int,
    step: dict | None = None,
    capture_profiles: dict | None = None,
) -> None:
    detail_profile_name = (step or {}).get("game_detail_profile")
    if detail_profile_name and capture_profiles:
        detail_profile = capture_profiles.get(detail_profile_name, {})
        if not detail_profile.get("layouts") and not detail_profile.get("tabs"):
            raise ValueError(f"game_detail_profile {detail_profile_name!r} has no layouts/tabs")
        nav_ms = int(detail_profile.get("capture", {}).get("navigation_delay_ms", navigation_delay_ms))
        capture_game_detail_deep(
            adb=adb,
            config=config,
            writer=writer,
            entry=entry,
            detail_profile=detail_profile,
            navigation_delay_ms=nav_ms,
            post_swipe_delay_ms=post_swipe_delay_ms,
        )
        return

    label = entry.get("label", "card")
    adb.tap_point(entry["point"])
    adb.sleep_ms(navigation_delay_ms)
    writer.capture(f"{label}_detail_00")

    max_swipes = int(entry.get("scroll_swipes", entry.get("max_swipes", 0)))
    if max_swipes > 0:
        step_opts = step or {}
        stop_dupes = int(
            entry.get(
                "scroll_stop_after_dupes",
                step_opts.get("scroll_stop_after_dupes", 4),
            )
        )
        capture_vertical_scroll(
            adb=adb,
            config=config,
            writer=writer,
            name_prefix=f"{label}_detail",
            post_swipe_delay_ms=post_swipe_delay_ms,
            max_swipes=max_swipes,
            stop_after_dupes=stop_dupes,
        )
        print(f"    detail: scroll done for {label}, returning to list", flush=True)

    back_opts = {**(step or {}), **entry}
    navigate_back_from_detail(adb, config, back_opts)


def capture_tap_then_scroll(
    *,
    adb: AdbDevice,
    config: dict,
    writer: ShotWriter,
    step: dict,
    post_swipe_delay_ms: int,
) -> None:
    adb.tap_point(step["point"])
    adb.sleep_ms(int(step.get("wait_ms", 350)))
    writer.capture(step.get("name", "expanded"))

    scroll_count = int(step.get("scroll_swipes", 0))
    if scroll_count <= 0:
        return
    feed = config["feed_swipe"]
    for n in range(1, scroll_count + 1):
        adb.swipe_points(feed["start"], feed["end"], int(feed["duration"]))
        adb.sleep_ms(post_swipe_delay_ms)
        writer.capture(f"{step.get('name', 'expanded')}_scroll_{n:02d}")


def capture_hybrid_strategy(
    *,
    adb: AdbDevice,
    config: dict,
    top: dict,
    writer: ShotWriter,
    post_swipe_delay_ms: int,
    timing: dict,
    capture_profiles: dict | None = None,
) -> None:
    capture_cfg = top.get("capture", {})
    navigation_delay_ms = int(capture_cfg.get("navigation_delay_ms", 450))
    steps = capture_cfg.get("steps", [])
    profiles = capture_profiles or {}

    for step in steps:
        step_type = step["type"]
        print(f"  step: {step_type} ({step.get('name', step_type)})", flush=True)

        if step_type == "capture":
            writer.capture(step.get("name", "overview"))

        elif step_type == "horizontal":
            capture_horizontal_dates(adb=adb, writer=writer, step=step)

        elif step_type == "tap_scroll":
            capture_tap_then_scroll(
                adb=adb,
                config=config,
                writer=writer,
                step=step,
                post_swipe_delay_ms=post_swipe_delay_ms,
            )

        elif step_type == "scroll_to_top":
            scroll_to_top = config["scroll_to_top"]
            repeat = int(step.get("repeat", 1))
            for i in range(repeat):
                adb.swipe_points(
                    scroll_to_top["start"],
                    scroll_to_top["end"],
                    int(scroll_to_top["duration"]),
                )
                adb.sleep_ms(int(step.get("wait_ms", 180)))
            if repeat > 1:
                print(f"  scroll_to_top: {repeat} swipe(s) to return list to top", flush=True)

        elif step_type == "tap":
            adb.tap_point(step["point"])
            adb.sleep_ms(int(step.get("wait_ms", 400)))

        elif step_type == "retap_top":
            tap_top_tab(adb, top)
            adb.sleep_ms(int(step.get("wait_ms", 400)))

        elif step_type == "scroll_limited":
            scroll_ctx = dict(top)
            if step.get("capture"):
                scroll_ctx["capture"] = {**top.get("capture", {}), **step["capture"]}
            capture_scroll_strategy(
                adb=adb,
                config=config,
                top=scroll_ctx,
                writer=writer,
                post_swipe_delay_ms=post_swipe_delay_ms,
                timing=timing,
                max_swipes=int(step.get("max_swipes", 30)),
                include_intro=bool(step.get("include_intro", False)),
                name_prefix=step.get("name", "feed"),
            )

        elif step_type == "drill_down":
            entries = step.get("entries", [])
            scroll_between = int(step.get("pre_scroll_between", 5))
            settle_ms = int(step.get("after_back_settle_ms", 450))
            for idx, entry in enumerate(entries):
                if "list_scroll" in entry:
                    pre = int(entry["list_scroll"])
                elif idx > 0:
                    pre = int(entry.get("pre_scroll_swipes", scroll_between))
                else:
                    pre = 0
                if pre > 0:
                    label = entry.get("label", f"item_{idx + 1}")
                    print(
                        f"  list scroll: {pre} swipe(s) on list before {label}",
                        flush=True,
                    )
                    scroll_list_feed(adb, config, pre, post_swipe_delay_ms)
                    adb.sleep_ms(settle_ms)
                capture_drill_down_entry(
                    adb=adb,
                    config=config,
                    writer=writer,
                    entry=entry,
                    navigation_delay_ms=navigation_delay_ms,
                    post_swipe_delay_ms=post_swipe_delay_ms,
                    step=step,
                    capture_profiles=profiles,
                )

        else:
            raise ValueError(f"Unknown hybrid step type: {step_type}")


def capture_segment(
    *,
    adb: AdbDevice,
    config: dict,
    plan: SegmentPlan,
    shots_dir: Path,
    post_swipe_delay_ms: int,
    skip_bottom_tap: bool,
    timing: dict,
    capture_profiles: dict | None = None,
) -> tuple[int, dict | None]:
    top = plan.top
    strategy = top.get("strategy", "scroll")
    capture_cfg = top.get("capture", {})
    dup_threshold = capture_cfg.get("duplicate_threshold", timing.get("duplicate_threshold"))

    navigate_to_segment(adb, config, plan, skip_bottom_tap)

    writer = ShotWriter(
        adb=adb,
        shots_dir=shots_dir,
        prefix=plan.prefix,
        post_swipe_delay_ms=post_swipe_delay_ms,
        duplicate_threshold=float(dup_threshold) if dup_threshold is not None else None,
        skip_duplicate_saves=bool(capture_cfg.get("skip_duplicate_saves", timing.get("skip_duplicate_saves", True))),
    )

    print(f"  strategy: {strategy} ({top.get('profile', 'default')})", flush=True)

    if strategy == "scroll":
        capture_scroll_strategy(
            adb=adb,
            config=config,
            top=top,
            writer=writer,
            post_swipe_delay_ms=post_swipe_delay_ms,
            timing=timing,
        )
    elif strategy == "hybrid":
        capture_hybrid_strategy(
            adb=adb,
            config=config,
            top=top,
            writer=writer,
            post_swipe_delay_ms=post_swipe_delay_ms,
            timing=timing,
            capture_profiles=capture_profiles,
        )
    else:
        raise ValueError(f"Unsupported capture strategy {strategy!r} for {plan.key}")

    reset_top_bar(adb, config, top)

    dup_report = None
    if writer.paths or writer.skipped_duplicates:
        saved = len(writer.paths)
        attempted = saved + writer.skipped_duplicates
        dup_rate = 0.0 if attempted == 0 else writer.skipped_duplicates / attempted
        if writer.paths:
            _, unique_check, _ = count_unique_images(
                writer.paths,
                float(dup_threshold or timing.get("duplicate_threshold", 0.95)),
            )
        else:
            unique_check = 0
        dup_report = {
            "segment": plan.key,
            "strategy": strategy,
            "total_attempts": attempted,
            "saved": saved,
            "unique": unique_check,
            "skipped_duplicates": writer.skipped_duplicates,
            "duplicate_rate": round(dup_rate, 4),
        }
        print(
            f"  duplicate rate: {saved} saved, {writer.skipped_duplicates} skipped "
            f"({dup_rate * 100:.1f}% dupes of {attempted} attempts)",
            flush=True,
        )

    return len(writer.paths), dup_report


def run_capture(
    *,
    output_dir: Path,
    flow: str,
    tabs_config_path: Path,
    adb_config_path: Path,
    profiles_config_path: Path,
    device: str | None,
    tap_delay_ms: int | None,
    post_swipe_delay_ms: int | None,
    resume: bool = False,
    resume_from: str | None = None,
    bottom_tab: str = "b01",
) -> dict:
    config, flow_profiles, timing, capture_profiles = load_settings(
        tabs_config_path, adb_config_path, profiles_config_path
    )
    effective_tap_delay = int(tap_delay_ms if tap_delay_ms is not None else timing.get("tap_delay_ms", 150))
    effective_post_delay = int(
        post_swipe_delay_ms if post_swipe_delay_ms is not None else timing.get("post_swipe_delay_ms", 0)
    )

    plans = build_segment_plans(config, flow, flow_profiles, capture_profiles)
    bottom_tab_scope = resolve_bottom_tab_spec(config, bottom_tab)
    if bottom_tab_scope != "all":
        plans = filter_plans_by_bottom_tab(plans, bottom_tab_scope)
        if not plans:
            raise ValueError(f"No segments for bottom tab {bottom_tab!r} ({bottom_tab_scope})")
        print(
            f"Bottom tab scope: {bottom_tab_display(config, bottom_tab_scope)} — "
            f"{len(plans)} segment(s)",
            flush=True,
        )
    adb = AdbDevice(device, tap_delay_ms=effective_tap_delay)

    shots_dir = output_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    progress = load_progress(output_dir)
    progress["flow"] = flow
    progress["bottom_tab"] = bottom_tab_scope
    start_index = 0
    if resume:
        start_index = infer_resume_index(plans, shots_dir, progress, config, resume_from)
        existing = sum(segment_shot_count(shots_dir, p.prefix) for p in plans[:start_index])
        print(
            f"Resume mode: skipping first {start_index} segment(s), "
            f"~{existing} existing screenshot(s) kept",
            flush=True,
        )
        if start_index >= len(plans):
            print("Resume: all segments already completed.", flush=True)
            total_existing = sum(segment_shot_count(shots_dir, p.prefix) for p in plans)
            return {
                "capture_mode": "adb",
                "flow": flow,
                "device": adb.device,
                "segments": len(plans),
                "screenshot_count": total_existing,
                "output_dir": str(output_dir),
                "screen_size": f"{adb.size[0]}x{adb.size[1]}",
                "resumed": True,
                "already_complete": True,
            }
        if not progress.get("completed_segments"):
            progress["completed_segments"] = [plans[i].key for i in range(start_index)]

    session_total = 0
    segment_reports: list[dict] = []
    current_bottom_id: str | None = None

    for index, plan in enumerate(plans):
        if index < start_index:
            continue

        skip_bottom = plan.bottom["id"] == current_bottom_id
        current_bottom_id = plan.bottom["id"]

        print(
            f"[ADB {index + 1}/{len(plans)}] {plan.key} ({plan.prefix}) "
            f"bottom={plan.bottom['label']} top={plan.top.get('label', plan.top['id'])}",
            flush=True,
        )
        count, dup_report = capture_segment(
            adb=adb,
            config=config,
            plan=plan,
            shots_dir=shots_dir,
            post_swipe_delay_ms=effective_post_delay,
            skip_bottom_tap=skip_bottom,
            timing=timing,
            capture_profiles=capture_profiles,
        )
        session_total += count
        if dup_report:
            segment_reports.append(dup_report)

        completed = progress.setdefault("completed_segments", [])
        if plan.key not in completed:
            completed.append(plan.key)
        save_progress(output_dir, progress)

    total_existing = sum(segment_shot_count(shots_dir, p.prefix) for p in plans)

    stats: dict[str, Any] = {
        "capture_mode": "adb",
        "flow": flow,
        "bottom_tab": bottom_tab_scope,
        "device": adb.device,
        "segments": len(plans),
        "screenshot_count": total_existing,
        "session_screenshot_count": session_total,
        "output_dir": str(output_dir),
        "screen_size": f"{adb.size[0]}x{adb.size[1]}",
        "segment_duplicate_reports": segment_reports,
        "resumed": resume,
        "resume_from_index": start_index + 1 if resume else 1,
    }

    if segment_reports:
        all_attempts = sum(r["total_attempts"] for r in segment_reports)
        all_saved = sum(r["saved"] for r in segment_reports)
        all_skipped = sum(r["skipped_duplicates"] for r in segment_reports)
        stats["duplicate_summary"] = {
            "total_attempts": all_attempts,
            "saved": all_saved,
            "skipped_duplicates": all_skipped,
            "duplicate_rate": round(0.0 if all_attempts == 0 else all_skipped / all_attempts, 4),
        }
        report_path = output_dir / "duplicate_report.json"
        report_path.write_text(json.dumps(stats["duplicate_summary"], indent=2), encoding="utf-8")

    return stats


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="TapTap ADB fast scroll capture (no Maestro screenshots).")
    parser.add_argument("--output", type=Path, required=True, help="Capture output dir (adb_raw)")
    parser.add_argument("--flow", required=True, help="Flow name, e.g. scroll_bottom1_top1_fast")
    parser.add_argument("--tabs-config", type=Path, default=root / "config" / "taptap_tabs.yaml")
    parser.add_argument("--adb-config", type=Path, default=root / "config" / "taptap_adb.yaml")
    parser.add_argument(
        "--profiles-config",
        type=Path,
        default=root / "config" / "taptap_capture_profiles.yaml",
    )
    parser.add_argument("--device", default=None, help="ADB device serial")
    parser.add_argument("--tap-delay-ms", type=int, default=None)
    parser.add_argument("--post-swipe-delay-ms", type=int, default=None)
    parser.add_argument("--resume", action="store_true", help="Continue an interrupted run in --output dir")
    parser.add_argument(
        "--resume-from",
        default=None,
        help="Segment key to restart from (e.g. b02_t01). Clears partial files for that segment.",
    )
    parser.add_argument(
        "--bottom-tab",
        default="b01",
        help=(
            "Run only one bottom tab, then stop. "
            "Default b01 (找游戏). Use all for every tab, or b02/ranking, b03/community, etc."
        ),
    )
    args = parser.parse_args()

    try:
        stats = run_capture(
            output_dir=args.output,
            flow=args.flow,
            tabs_config_path=args.tabs_config,
            adb_config_path=args.adb_config,
            profiles_config_path=args.profiles_config,
            device=args.device,
            tap_delay_ms=args.tap_delay_ms,
            post_swipe_delay_ms=args.post_swipe_delay_ms,
            resume=args.resume,
            resume_from=args.resume_from,
            bottom_tab=args.bottom_tab,
        )
    except subprocess.CalledProcessError as exc:
        print(f"ADB command failed: {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"ADB capture done: {stats['screenshot_count']} screenshot(s) total in output dir, "
        f"{stats.get('session_screenshot_count', stats['screenshot_count'])} this session, "
        f"{stats['segments']} segment(s), device={stats['device']}, screen={stats['screen_size']}",
        flush=True,
    )
    if stats.get("duplicate_summary"):
        ds = stats["duplicate_summary"]
        print(
            f"Duplicate summary: {ds['saved']} saved, {ds['skipped_duplicates']} skipped "
            f"({ds['duplicate_rate'] * 100:.1f}% of {ds['total_attempts']} attempts)",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
