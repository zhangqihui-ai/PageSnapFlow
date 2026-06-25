#!/usr/bin/env python3
"""Booking.com hotel list scroll capture via ADB."""

from __future__ import annotations

import argparse
import re
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from adb_taptap_capture import AdbDevice, ShotWriter, safe_unlink
from image_similarity import scene_signature, signature_from_path, similarity


_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
_SR_NODE_RE = re.compile(r'<node\b[^>]*content-desc="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def swipe(adb: AdbDevice, spec: dict) -> None:
    repeat = max(1, int(spec.get("repeat", 1)))
    wait_ms = int(spec.get("wait_ms", 0))
    for idx in range(repeat):
        adb.swipe_points(spec["start"], spec["end"], int(spec["duration"]))
        if wait_ms > 0 and idx + 1 < repeat:
            adb.sleep_ms(wait_ms)


def screencap_temp(adb: AdbDevice) -> Path:
    tmp = Path(tempfile.gettempdir()) / f"booking_align_{time.time_ns()}.png"
    adb.screencap(tmp)
    return tmp


def align_top_card_by_ui(adb: AdbDevice, config: dict, *, adjust_wait_ms: int) -> None:
    """Use Android bounds to remove a clipped hotel card tail at the top."""
    ui_cfg = config.get("ui_alignment", {})
    if not bool(ui_cfg.get("enabled", True)):
        return
    try:
        cmd = ["adb", "-s", adb.device, "exec-out", "uiautomator", "dump", "/dev/tty"]
        proc = subprocess.run(cmd, check=True, capture_output=True, timeout=12)
    except Exception as exc:
        print(f"    ui-align: skipped ({exc})", flush=True)
        return
    text = (proc.stdout or b"").decode("utf-8", errors="replace")
    sr_pos = text.find('resource-id="sr_list"')
    if sr_pos < 0:
        return
    nodes: list[tuple[int, int, int, int, str]] = []
    for match in _SR_NODE_RE.finditer(text[sr_pos:]):
        desc = match.group(1)
        if not desc or "CNY" not in desc and "无需预付" not in desc:
            continue
        x1, y1, x2, y2 = (int(match.group(i)) for i in range(2, 6))
        if y2 <= y1:
            continue
        nodes.append((x1, y1, x2, y2, desc))
    if len(nodes) < 2:
        return
    nodes.sort(key=lambda item: item[1])
    first = nodes[0]
    second = nodes[1]
    _, y1, _, y2, desc = first
    first_h = y2 - y1
    screen_h = adb.size[1]
    min_full_h = int(float(ui_cfg.get("min_full_card_ratio", 0.22)) * screen_h)
    max_top_gap = int(float(ui_cfg.get("max_top_gap_ratio", 0.035)) * screen_h)
    list_top_px = int(float(ui_cfg.get("list_top_ratio", list_top_for_frame(False, config))) * screen_h)
    if first_h >= min_full_h or y1 > list_top_px + max_top_gap:
        return
    gap = max(0, second[1] - y2)
    padding = int(float(ui_cfg.get("top_padding_ratio", 0.012)) * screen_h)
    fix_px = max(0, first_h + gap - padding)
    if fix_px <= 0:
        return
    title = desc.split("&#10;", 1)[0].strip()
    print(
        f"    ui-align: clipped first card {first_h}px, advance {fix_px}px ({title})",
        flush=True,
    )
    swipe_pixels(adb, config, fix_px)
    adb.sleep_ms(adjust_wait_ms)


def _visible_hotel_nodes(adb: AdbDevice) -> list[tuple[int, int, int, int, str]]:
    try:
        cmd = ["adb", "-s", adb.device, "exec-out", "uiautomator", "dump", "/dev/tty"]
        proc = subprocess.run(cmd, check=True, capture_output=True, timeout=12)
    except Exception as exc:
        print(f"    ui-align: skipped ({exc})", flush=True)
        return []
    text = (proc.stdout or b"").decode("utf-8", errors="replace")
    sr_pos = text.find('resource-id="sr_list"')
    if sr_pos < 0:
        return []
    nodes: list[tuple[int, int, int, int, str]] = []
    for match in _SR_NODE_RE.finditer(text[sr_pos:]):
        desc = match.group(1)
        if not desc or "CNY" not in desc:
            continue
        x1, y1, x2, y2 = (int(match.group(i)) for i in range(2, 6))
        if y2 <= y1:
            continue
        nodes.append((x1, y1, x2, y2, desc))
    return sorted(nodes, key=lambda item: item[1])


def align_top_card_by_ui2(adb: AdbDevice, config: dict, *, adjust_wait_ms: int) -> None:
    """Make the first hotel card start cleanly below the sticky toolbar."""
    ui_cfg = config.get("ui_alignment", {})
    if not bool(ui_cfg.get("enabled", True)):
        return
    screen_h = adb.size[1]
    min_full_h = int(float(ui_cfg.get("min_full_card_ratio", 0.22)) * screen_h)
    max_top_gap = int(float(ui_cfg.get("max_top_gap_ratio", 0.035)) * screen_h)
    list_top_px = int(float(ui_cfg.get("list_top_ratio", list_top_for_frame(False, config))) * screen_h)
    desired_top = list_top_px + int(float(ui_cfg.get("desired_top_padding_ratio", 0.012)) * screen_h)
    top_tolerance = int(float(ui_cfg.get("top_tolerance_ratio", 0.010)) * screen_h)

    for _ in range(int(ui_cfg.get("max_passes", 2))):
        nodes = _visible_hotel_nodes(adb)
        if len(nodes) < 2:
            return
        _, y1, _, y2, desc = nodes[0]
        first_h = y2 - y1
        title = desc.split("&#10;", 1)[0].strip()

        if first_h < min_full_h and y1 <= list_top_px + max_top_gap:
            gap = max(0, nodes[1][1] - y2)
            padding = int(float(ui_cfg.get("top_padding_ratio", 0.012)) * screen_h)
            fix_px = max(0, first_h + gap - padding)
            if fix_px <= 0:
                return
            print(
                f"    ui-align: clipped first card {first_h}px, advance {fix_px}px ({title})",
                flush=True,
            )
            swipe_pixels(adb, config, fix_px)
            adb.sleep_ms(adjust_wait_ms)
            continue

        if y1 < desired_top - top_tolerance:
            fix_px = y1 - desired_top
            print(
                f"    ui-align: title too high, pull down {-fix_px}px "
                f"(top={y1}, desired={desired_top})",
                flush=True,
            )
            swipe_pixels(adb, config, fix_px)
            adb.sleep_ms(adjust_wait_ms)
            continue

        return


def card_region(img: np.ndarray, card_index: int, list_top: float, card_h: float) -> np.ndarray | None:
    h = img.shape[0]
    y1 = int((list_top + card_index * card_h) * h)
    y2 = int((list_top + (card_index + 1) * card_h) * h)
    y2 = min(y2, h)
    if y2 <= y1 + 4:
        return None
    return img[y1:y2, :]


def card_half_sig(
    img: np.ndarray, card_index: int, list_top: float, card_h: float, half: str,
):
    region = card_region(img, card_index, list_top, card_h)
    if region is None or region.size == 0:
        return None
    mid = max(1, region.shape[0] // 2)
    crop = region[:mid, :] if half == "top" else region[mid:, :]
    return scene_signature(crop)


def list_top_for_frame(is_overview: bool, config: dict) -> float:
    if is_overview:
        return float(config.get("list_top_ratio", 0.30))
    return float(config.get("scroll_list_top_ratio", 0.215))


def measure_alignment(
    prev_path: Path,
    curr_path: Path,
    config: dict,
    *,
    prev_is_overview: bool,
) -> dict | None:
    card_h = float(config.get("card_height_ratio", 0.304))
    list_top_prev = list_top_for_frame(prev_is_overview, config)
    list_top_curr = list_top_for_frame(False, config)
    prev = cv2.imread(str(prev_path))
    curr = cv2.imread(str(curr_path))
    if prev is None or curr is None:
        return None

    c3_bot = card_half_sig(prev, 2, list_top_prev, card_h, "bottom")
    n1_top = card_half_sig(curr, 0, list_top_curr, card_h, "top")

    if c3_bot is None or n1_top is None:
        return None

    return {"c3b_c1t": similarity(c3_bot, n1_top)}


def is_list_loading(path: Path, config: dict) -> bool:
    """Skeleton placeholders while results load."""
    img = cv2.imread(str(path))
    if img is None:
        return True
    h, w = img.shape[:2]
    list_top = float(config.get("list_top_ratio", 0.30))
    card_h = float(config.get("card_height_ratio", 0.304))
    region = card_region(img, 0, list_top, card_h)
    if region is None or region.size == 0:
        return True
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    std = float(np.std(gray))
    mean = float(np.mean(gray))
    return std < 28 and 165 < mean < 228


def swipe_pixels(adb: AdbDevice, config: dict, dist_px: int) -> None:
    """Scroll list by exact pixel distance (positive = finger up / content up)."""
    if dist_px == 0:
        return
    w, h = adb.size
    swipe_cfg = config.get("list_swipe", {})
    start_ratio = float(swipe_cfg.get("start_ratio", 0.72))
    min_end_ratio = float(swipe_cfg.get("min_end_ratio", 0.10))
    max_single_ratio = float(swipe_cfg.get("max_single_ratio", 0.50))
    duration = int(swipe_cfg.get("duration", 350))
    pass_wait = int(swipe_cfg.get("pass_wait_ms", 120))
    cx = w // 2
    remaining = abs(dist_px)
    direction = 1 if dist_px > 0 else -1
    while remaining > 0:
        chunk = min(remaining, int(max_single_ratio * h))
        start_y = int(start_ratio * h)
        if direction > 0:
            end_y = max(int(min_end_ratio * h), start_y - chunk)
            actual = start_y - end_y
        else:
            end_y = min(int(0.88 * h), start_y + chunk)
            actual = end_y - start_y
        adb._adb_shell("input", "swipe", str(cx), str(start_y), str(cx), str(end_y), str(duration))
        remaining -= actual
        if remaining > 0:
            adb.sleep_ms(pass_wait)


def _divider_cfg(config: dict) -> dict:
    return config.get("divider_alignment", {})


def detect_card_dividers(
    img: np.ndarray,
    config: dict,
    *,
    is_overview: bool,
) -> list[float]:
    """Detect horizontal separator lines between hotel cards (white/gray bands)."""
    div_cfg = _divider_cfg(config)
    h, w = img.shape[:2]
    list_top = list_top_for_frame(is_overview, config)
    min_y = list_top + float(div_cfg.get("min_below_list_top", 0.06))
    min_gap = float(div_cfg.get("min_card_gap", 0.24))
    ys = int(min_y * h)
    ye = int(float(div_cfg.get("scan_y_max", 0.97)) * h)
    x1 = int(float(div_cfg.get("scan_x1", 0.35)) * w)
    x2 = int(float(div_cfg.get("scan_x2", 0.98)) * w)
    gray = cv2.cvtColor(img[ys:ye, x1:x2], cv2.COLOR_BGR2GRAY)
    rm = gray.mean(axis=1)
    rs = gray.std(axis=1)

    hits: list[float] = []
    for i in range(len(rm)):
        is_white = rs[i] < 4.0 and rm[i] > 252.0
        is_gray = rs[i] < 14.0 and 228.0 < rm[i] < 252.0
        if is_white or is_gray:
            hits.append((ys + i) / h)

    if not hits:
        return []

    clusters: list[float] = []
    start = hits[0]
    prev = hits[0]
    for y in hits[1:]:
        if y - prev < 0.004:
            prev = y
            continue
        clusters.append((start + prev) / 2.0)
        start = y
        prev = y
    clusters.append((start + prev) / 2.0)

    first_gap = float(div_cfg.get("min_first_divider_gap", min_gap * 0.82))
    filtered: list[float] = []
    for y in clusters:
        if y < list_top + first_gap:
            continue
        if filtered and y - filtered[-1] < min_gap:
            continue
        filtered.append(y)
    return filtered


def estimate_card_height(dividers: list[float], config: dict) -> float:
    div_cfg = _divider_cfg(config)
    if len(dividers) >= 2:
        gaps = [dividers[i + 1] - dividers[i] for i in range(len(dividers) - 1)]
        return float(np.median(gaps))
    return float(div_cfg.get("fallback_card_height", config.get("card_height_ratio", 0.304)))


def scroll_target_ratio(
    dividers: list[float],
    list_top: float,
    cards_per_step: float,
    card_h: float,
) -> float:
    idx = int(cards_per_step) - 1
    if len(dividers) > idx:
        return dividers[idx]
    if dividers:
        return dividers[-1]
    return list_top + card_h * cards_per_step


def measure_divider_alignment(path: Path, config: dict, card_h: float) -> dict | None:
    img = cv2.imread(str(path))
    if img is None:
        return None
    list_top = list_top_for_frame(False, config)
    dividers = detect_card_dividers(img, config, is_overview=False)
    if not dividers:
        return {"first_div": None, "error": None, "dividers": []}
    expected = list_top + card_h
    error = dividers[0] - expected
    return {"first_div": dividers[0], "error": error, "dividers": dividers}


def fix_top_partial_card(
    adb: AdbDevice,
    config: dict,
    temp: Path,
    *,
    adjust_wait_ms: int,
) -> Path:
    """If a previous card tail is visible at the top, advance to the next divider."""
    div_cfg = _divider_cfg(config)
    threshold = float(div_cfg.get("top_partial_divider_threshold", 0.0))
    if threshold <= 0:
        return temp
    img = cv2.imread(str(temp))
    if img is None:
        return temp
    dividers = detect_card_dividers(img, config, is_overview=False)
    if not dividers:
        return temp
    first_div = dividers[0]
    if first_div >= threshold:
        return temp
    target = float(div_cfg.get("top_divider_target", list_top_for_frame(False, config)))
    fix_px = max(0, int((first_div - target) * adb.size[1]))
    if fix_px <= 0:
        return temp
    print(
        f"    align: top partial card, advance {fix_px}px "
        f"(first_div={first_div:.3f} -> target={target:.3f})",
        flush=True,
    )
    swipe_pixels(adb, config, fix_px)
    adb.sleep_ms(adjust_wait_ms)
    safe_unlink(temp)
    return screencap_temp(adb)


def is_first_card_divider_aligned(path: Path, config: dict) -> bool:
    """Reject frames where the first hotel card is clipped under the sticky bar."""
    div_cfg = _divider_cfg(config)
    if not bool(div_cfg.get("require_first_card_aligned", True)):
        return True
    img = cv2.imread(str(path))
    if img is None:
        return False
    dividers = detect_card_dividers(img, config, is_overview=False)
    if not dividers:
        return False
    list_top = list_top_for_frame(False, config)
    card_h = estimate_card_height(dividers, config)
    expected = list_top + card_h
    tol = float(div_cfg.get("first_divider_tolerance", 0.075))
    return abs(dividers[0] - expected) <= tol


def compute_scroll_distance_px(
    prev_path: Path,
    config: dict,
    *,
    prev_is_overview: bool,
) -> tuple[int, dict]:
    """Pixels to scroll so prev hotel #3 divider lands at scroll list top."""
    img = cv2.imread(str(prev_path))
    cards = float(config.get("cards_per_step", 2))
    list_top = list_top_for_frame(prev_is_overview, config)
    dest_top = list_top_for_frame(False, config)
    card_h = float(config.get("card_height_ratio", 0.304))
    if img is None:
        target = list_top + card_h * cards
        return int((target - dest_top) * 2400), {"mode": "fallback_no_img"}
    h = img.shape[0]
    dividers = detect_card_dividers(img, config, is_overview=prev_is_overview)
    card_h = estimate_card_height(dividers, config)
    target = scroll_target_ratio(dividers, list_top, cards, card_h)
    extra_step = float(_divider_cfg(config).get("step_extra_ratio", 0.0))
    dist = int((target - dest_top + extra_step) * h)
    meta = {
        "mode": "divider",
        "dividers": [round(d, 3) for d in dividers],
        "target_y": round(target, 3),
        "extra_step": round(extra_step, 3),
        "card_h": round(card_h, 3),
        "dist_px": dist,
    }
    return dist, meta


def swipe_card_steps(adb: AdbDevice, config: dict, cards: float) -> None:
    """Fallback swipe by estimated card heights."""
    w, h = adb.size
    card_h = float(config.get("card_height_ratio", 0.304))
    swipe_pixels(adb, config, int(cards * card_h * h))


def _strip_stats(img: np.ndarray, y1: float, y2: float, x1: float, x2: float) -> tuple[float, float, float]:
    h, w = img.shape[:2]
    strip = img[int(y1 * h): int(y2 * h), int(x1 * w): int(x2 * w)]
    if strip.size == 0:
        return 0.0, 255.0, 0.0
    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    std = float(np.std(gray))
    mean = float(np.mean(gray))
    dark = float(np.mean(gray < 105))
    return std, mean, dark


def has_filter_chips(path: Path) -> bool:
    """Filter pill row: 酒店(578) / 含早餐 / 8分以上 …"""
    img = cv2.imread(str(path))
    if img is None:
        return False
    std, mean, _ = _strip_stats(img, 0.198, 0.252, 0.04, 0.96)
    return std > 22 and mean < 242


def has_results_count(path: Path) -> bool:
    """Row like '602家住宿' / '623家住宿' below filter chips."""
    img = cv2.imread(str(path))
    if img is None:
        return False
    # Scan a few bands — chip/count spacing varies slightly by locale and DPI.
    bands = (
        (0.283, 0.315),
        (0.288, 0.318),
        (0.275, 0.305),
    )
    for y1, y2 in bands:
        std, mean, dark = _strip_stats(img, y1, y2, 0.04, 0.55)
        if std > 12 and mean < 246 and dark > 0.024:
            return True
    return False


def _peak_title_stats(
    img: np.ndarray, y1: float, y2: float, x1: float, x2: float,
) -> tuple[float, float]:
    best_dark = 0.0
    best_std = 0.0
    y = y1
    while y + 0.022 <= y2:
        std, _, dark = _strip_stats(img, y, y + 0.022, x1, x2)
        if dark > best_dark:
            best_dark = dark
            best_std = std
        y += 0.012
    return best_std, best_dark


def is_first_hotel_name_visible(path: Path, config: dict, *, is_overview: bool) -> bool:
    """First hotel title text on the right must not be hidden under sticky header."""
    img = cv2.imread(str(path))
    if img is None:
        return False
    h, w = img.shape[:2]
    list_top = list_top_for_frame(is_overview, config)
    card_h = float(config.get("card_height_ratio", 0.304))
    if is_overview:
        y1 = list_top
        y2 = list_top + card_h * 0.16
        std, mean, dark = _strip_stats(img, y1, y2, 0.40, 0.93)
        if dark < 0.055 or std < 22:
            return False
        title_std, title_dark = std, dark
        photo_y2 = list_top + card_h * 0.22
        min_photo_std = 28.0
    else:
        title_y1 = max(0.0, list_top - 0.005)
        title_y2 = list_top + 0.058
        title_std, title_dark = _peak_title_stats(img, title_y1, title_y2, 0.40, 0.93)
        _, mean, _ = _strip_stats(img, title_y1, title_y2, 0.40, 0.93)
        if title_dark < 0.075 or title_std < 45:
            return False
        _, body_dark = _peak_title_stats(
            img, list_top + 0.050, list_top + 0.110, 0.40, 0.93,
        )
        if body_dark > title_dark + 0.055 and title_dark < 0.11:
            return False
        y1, y2 = title_y1, title_y2
        photo_y2 = list_top + 0.12
        min_photo_std = 35.0

    if mean > 248:
        return False

    lstd, _, _ = _strip_stats(img, list_top, photo_y2, 0.04, 0.36)
    if lstd < min_photo_std:
        return False

    name_area = img[int(y1 * h): int(y2 * h), int(0.40 * w): int(0.93 * w)]
    b, g, r = cv2.split(name_area)
    yellow = (r.astype(np.float32) > 165) & (g.astype(np.float32) > 130) & (b.astype(np.float32) < 120)
    yellow_ratio = float(np.mean(yellow))
    if yellow_ratio >= 0.22 and title_dark < 0.13:
        return False
    return True


def overview_ready(path: Path, config: dict) -> bool:
    """Full overview header + first hotel name fully visible."""
    if is_list_loading(path, config):
        return False
    if not has_filter_chips(path):
        return False
    if not has_results_count(path):
        return False
    if not is_first_hotel_name_visible(path, config, is_overview=True):
        return False
    return True


def overview_status(path: Path, config: dict) -> dict[str, bool]:
    return {
        "loading": is_list_loading(path, config),
        "chips": has_filter_chips(path),
        "count": has_results_count(path),
        "name": is_first_hotel_name_visible(path, config, is_overview=True),
    }


def frame_ready(path: Path, config: dict, *, is_overview: bool) -> bool:
    if is_overview:
        return overview_ready(path, config)
    if is_list_loading(path, config):
        return False
    if not is_first_hotel_name_visible(path, config, is_overview=False):
        return False
    return is_first_card_divider_aligned(path, config)


def reveal_hotel_name(adb: AdbDevice, config: dict, *, scrolled: bool = False) -> None:
    if scrolled:
        spec = config.get("scroll_reveal_hotel_name", config.get("reveal_hotel_name"))
    else:
        spec = config.get("reveal_hotel_name", config.get("unclip_swipe"))
    swipe(adb, spec)


def settle_overview_position(adb: AdbDevice, config: dict) -> None:
    """Scroll to true list top; adjust until filter chips + count row + hotel name visible."""
    align = config.get("alignment", {})
    timing = config.get("adb_capture", {})
    wait_ms = int(timing.get("list_ready_wait_ms", 1200))
    max_attempts = int(align.get("overview_max_attempts", 8))
    adjust_wait = int(align.get("adjust_wait_ms", 300))
    to_top = config.get("scroll_to_top", {})

    print("  settle: force scroll to list top...", flush=True)
    swipe(adb, to_top)
    adb.sleep_ms(wait_ms)

    print("  settle: verify full header...", flush=True)
    for attempt in range(max_attempts):
        temp = screencap_temp(adb)
        try:
            status = overview_status(temp, config)
            if status["chips"] and overview_ready(temp, config):
                print(f"  settle: overview ready (attempt {attempt + 1})", flush=True)
                return

            if status["chips"]:
                if not status["name"] or not status["count"]:
                    print("  settle: header ok, reveal hotel name", flush=True)
                    reveal_hotel_name(adb, config)
                else:
                    return
            else:
                print("  settle: scroll to top", flush=True)
                swipe(adb, to_top)
        finally:
            safe_unlink(temp)
        adb.sleep_ms(adjust_wait if attempt else wait_ms)

    raise RuntimeError(
        "Could not reach overview top: need filter chips + N家住宿 row + visible hotel name"
    )


def align_after_step(
    *,
    adb: AdbDevice,
    config: dict,
    prev_path: Path,
    prev_is_overview: bool,
    post_swipe_delay_ms: int,
) -> Path:
    """Scroll by hotel-card divider on prev frame; one quick nudge if needed."""
    align_cfg = config.get("alignment", {})
    div_cfg = _divider_cfg(config)
    max_nudge = int(div_cfg.get("max_nudge_attempts", 2))
    adjust_wait = int(align_cfg.get("adjust_wait_ms", 160))
    nudge_tol = float(div_cfg.get("nudge_tolerance", 0.012))

    dist_px, meta = compute_scroll_distance_px(
        prev_path, config, prev_is_overview=prev_is_overview,
    )
    print(
        f"    scroll: divider dist={dist_px}px "
        f"target_y={meta.get('target_y')} dividers={meta.get('dividers')}",
        flush=True,
    )
    swipe_pixels(adb, config, dist_px)
    adb.sleep_ms(post_swipe_delay_ms)
    align_top_card_by_ui2(adb, config, adjust_wait_ms=adjust_wait)

    temp = screencap_temp(adb)
    try:
        card_h = float(meta.get("card_h") or config.get("card_height_ratio", 0.304))
        temp = fix_top_partial_card(
            adb,
            config,
            temp,
            adjust_wait_ms=adjust_wait,
        )
        for nudge in range(max_nudge + 1):
            name_ok = is_first_hotel_name_visible(temp, config, is_overview=False)
            ready = name_ok and is_first_card_divider_aligned(temp, config)
            div_info = measure_divider_alignment(temp, config, card_h)
            err = div_info["error"] if div_info else None
            if div_info and err is not None and div_info.get("first_div") is not None:
                print(
                    f"    align: first_div={div_info['first_div']:.3f} "
                    f"err={err:+.3f} name_ok={name_ok}",
                    flush=True,
                )
            elif div_info:
                print(f"    align: name_ok={name_ok} dividers={div_info.get('dividers')}", flush=True)
            if ready and (err is None or abs(err) <= nudge_tol):
                return temp
            if nudge >= max_nudge:
                break
            if err is not None and abs(err) > nudge_tol:
                fix_px = int(err * adb.size[1])
                print(f"    align: divider nudge {fix_px}px", flush=True)
                swipe_pixels(adb, config, fix_px)
            elif not name_ok:
                print("    align: name clipped, reveal once", flush=True)
                reveal_hotel_name(adb, config, scrolled=True)
            else:
                break
            adb.sleep_ms(adjust_wait)
            safe_unlink(temp)
            temp = screencap_temp(adb)
        return temp
    except Exception:
        safe_unlink(temp)
        raise


def capture_aligned_frame(
    *,
    adb: AdbDevice,
    writer: ShotWriter,
    config: dict,
    prev_path: Path,
    prev_is_overview: bool,
    label: str,
    post_swipe_delay_ms: int,
    max_dup_retries: int,
) -> Path | None:
    align_cfg = config.get("alignment", {})
    adjust_wait = int(align_cfg.get("adjust_wait_ms", 280))
    local_quality_retries = int(align_cfg.get("local_quality_retries", 2))

    def save_temp(temp_path: Path) -> Path:
        safe_label = label.replace(" ", "_")
        filename = f"{writer.prefix}_{writer.seq:03d}_{safe_label}.png"
        dest = writer.shots_dir / filename
        dest.write_bytes(temp_path.read_bytes())
        writer.paths.append(dest)
        writer.seq += 1
        sig_now = signature_from_path(dest)
        if sig_now is not None:
            writer.last_sig = sig_now
        return dest

    for attempt in range(1, max_dup_retries + 1):
        temp = align_after_step(
            adb=adb,
            config=config,
            prev_path=prev_path,
            prev_is_overview=prev_is_overview,
            post_swipe_delay_ms=post_swipe_delay_ms,
        )
        try:
            sig = signature_from_path(temp)
            is_dup = False
            if sig is not None and writer.last_sig is not None and writer.duplicate_threshold is not None:
                is_dup = similarity(sig, writer.last_sig) >= writer.duplicate_threshold

            if is_dup and writer.skip_duplicate_saves and attempt < max_dup_retries:
                print(f"    duplicate frame, retry scroll ({attempt}/{max_dup_retries})", flush=True)
                safe_unlink(temp)
                swipe_card_steps(adb, config, 1.0)
                adb.sleep_ms(adjust_wait)
                temp = screencap_temp(adb)
                sig = signature_from_path(temp)
                if sig is None or writer.last_sig is None or writer.duplicate_threshold is None:
                    is_dup = False
                else:
                    is_dup = similarity(sig, writer.last_sig) >= writer.duplicate_threshold
                if is_dup:
                    continue

            if not frame_ready(temp, config, is_overview=False):
                print(f"    reject: hotel name not visible for {label}", flush=True)
                for local_attempt in range(local_quality_retries):
                    reveal_hotel_name(adb, config, scrolled=True)
                    adb.sleep_ms(adjust_wait)
                    safe_unlink(temp)
                    temp = screencap_temp(adb)
                    if frame_ready(temp, config, is_overview=False):
                        return save_temp(temp)
                if is_first_card_divider_aligned(temp, config):
                    print("    warning: title detector uncertain; saved divider-aligned frame", flush=True)
                    return save_temp(temp)
                print("    warning: quality detector uncertain; saved best-effort frame", flush=True)
                return save_temp(temp)

            return save_temp(temp)
        finally:
            safe_unlink(temp)

    print(f"  warning: could not get unique frame for {label}", flush=True)
    return None


def capture_overview(
    adb: AdbDevice,
    writer: ShotWriter,
    config: dict,
    post_swipe_delay_ms: int,
    *,
    skip_scroll_to_top: bool = False,
) -> Path:
    align = config.get("alignment", {})
    max_attempts = int(align.get("overview_max_attempts", 8))
    adjust_wait = int(align.get("adjust_wait_ms", 300))
    timing = config.get("adb_capture", {})
    wait_ms = int(timing.get("list_ready_wait_ms", 1200))

    if not skip_scroll_to_top:
        settle_overview_position(adb, config)

    for attempt in range(max_attempts):
        adb.sleep_ms(post_swipe_delay_ms)
        temp = screencap_temp(adb)
        try:
            if not overview_ready(temp, config):
                st = overview_status(temp, config)
                print(
                    f"  overview: quality check failed ({attempt + 1}/{max_attempts}) "
                    f"chips={st['chips']} count={st['count']} name={st['name']}",
                    flush=True,
                )
                if skip_scroll_to_top:
                    adb.sleep_ms(wait_ms)
                    continue
                reveal_hotel_name(adb, config)
                adb.sleep_ms(adjust_wait)
                continue

            safe_label = "overview"
            filename = f"{writer.prefix}_{writer.seq:03d}_{safe_label}.png"
            dest = writer.shots_dir / filename
            dest.write_bytes(temp.read_bytes())
            writer.paths.append(dest)
            writer.seq += 1
            sig = signature_from_path(dest)
            if sig is not None:
                writer.last_sig = sig
            print("  overview: captured with full header + hotel name", flush=True)
            return dest
        finally:
            safe_unlink(temp)

    raise RuntimeError("Overview capture failed: first hotel name or header not valid")


def run_capture(
    *,
    output_dir: Path,
    config_path: Path,
    device: str | None,
    max_shots: int | None,
    skip_scroll_to_top: bool = False,
) -> dict:
    config = load_config(config_path)
    timing = config.get("adb_capture", {})
    pilot = config.get("pilot", {})
    shot_count = int(max_shots if max_shots is not None else pilot.get("max_shots", 10))
    max_dup_retries = int(pilot.get("max_dup_retries", 4))
    post_swipe_delay_ms = int(timing.get("post_swipe_delay_ms", 400))
    dup_threshold = float(timing.get("duplicate_threshold", 0.90))

    shots_dir = output_dir / "adb_raw" / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    adb = AdbDevice(device, int(timing.get("tap_delay_ms", 150)))
    writer = ShotWriter(
        adb=adb,
        shots_dir=shots_dir,
        prefix="booking",
        post_swipe_delay_ms=post_swipe_delay_ms,
        duplicate_threshold=dup_threshold,
        skip_duplicate_saves=bool(timing.get("skip_duplicate_saves", True)),
    )

    print(
        f"Booking list capture: {shot_count} shots, screen={adb.size}, "
        f"card step={config.get('cards_per_step', 2)}",
        flush=True,
    )

    overview_path = capture_overview(
        adb, writer, config, post_swipe_delay_ms,
        skip_scroll_to_top=skip_scroll_to_top,
    )
    prev_path = overview_path

    for n in range(1, shot_count):
        print(f"  scroll {n}/{shot_count - 1}", flush=True)
        saved = capture_aligned_frame(
            adb=adb,
            writer=writer,
            config=config,
            prev_path=prev_path,
            prev_is_overview=(n == 1),
            label=f"scroll_{n:02d}",
            post_swipe_delay_ms=post_swipe_delay_ms,
            max_dup_retries=max_dup_retries,
        )
        if saved is not None:
            prev_path = saved
        else:
            print("  warning: skipped one frame that could not be aligned", flush=True)

    manifest = {
        "app": "booking",
        "package": config.get("package", "com.booking"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "device": adb.device,
        "screen_size": f"{adb.size[0]}x{adb.size[1]}",
        "requested_shots": shot_count,
        "saved_shots": len(writer.paths),
        "skipped_duplicates": writer.skipped_duplicates,
        "alignment": {
            "list_top_ratio": config.get("list_top_ratio"),
            "card_height_ratio": config.get("card_height_ratio"),
            "cards_per_step": config.get("cards_per_step"),
        },
        "files": [str(p.relative_to(output_dir)) for p in writer.paths],
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Booking.com hotel list ADB scroll capture")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "config" / "booking_adb.yaml",
    )
    parser.add_argument("--device", default=None)
    parser.add_argument("--max-shots", type=int, default=None)
    parser.add_argument(
        "--skip-scroll-to-top",
        action="store_true",
        help="Do not scroll list to top before first capture",
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    try:
        stats = run_capture(
            output_dir=args.output,
            config_path=args.config,
            device=args.device,
            max_shots=args.max_shots,
            skip_scroll_to_top=args.skip_scroll_to_top,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Done: saved {stats['saved_shots']}/{stats['requested_shots']} "
        f"(skipped {stats['skipped_duplicates']} duplicates)",
        flush=True,
    )
    print(f"Output: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
