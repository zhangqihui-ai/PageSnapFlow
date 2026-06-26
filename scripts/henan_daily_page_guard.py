"""Detect Henan Daily 新闻-精选 feed vs article detail; recover with BACK."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from image_similarity import imread_unicode, signature_from_path


def feed_page_guard_cfg(config: dict) -> dict:
    defaults = {
        "enabled": True,
        "max_back_attempts": 3,
        "recover_back_wait_ms": 450,
        "header_red_min": 12.0,
        "selected_tab_blue_min": 0.85,
        "feed_tabs_mean_min": 215.0,
        "feed_tabs_std_min": 30.0,
        "comment_mean_min": 248.0,
        "comment_std_max": 12.0,
        "detail_action_std_min": 22.0,
    }
    merged = {**defaults, **config.get("feed_page_guard", {})}
    return merged


def _header_red_margin(img: np.ndarray) -> float:
    h, w = img.shape[:2]
    header = img[int(0.055 * h) : int(0.11 * h), int(0.04 * w) : int(0.42 * w)]
    if header.size == 0:
        return 0.0
    red = header[:, :, 2].astype(np.float32)
    blue = header[:, :, 0].astype(np.float32)
    return float(red.mean() - blue.mean())


def _tab_band_blue_ratio(img: np.ndarray, band: dict) -> float:
    h, w = img.shape[:2]
    left = int(float(band.get("left_ratio", 0.06)) * w)
    right = int(float(band.get("right_ratio", 0.22)) * w)
    tab_band = img[int(0.158 * h) : int(0.178 * h), left:right]
    if tab_band.size == 0:
        return 0.0
    return float(
        ((tab_band[:, :, 0] > 150) & (tab_band[:, :, 0] > tab_band[:, :, 2] + 20)).mean()
    )


def _selected_tab_blue_ratio(img: np.ndarray) -> float:
    return _tab_band_blue_ratio(img, {"left_ratio": 0.06, "right_ratio": 0.22})


def _feed_tabs_band_stats(img: np.ndarray) -> tuple[float, float]:
    h, w = img.shape[:2]
    tabs = img[int(0.155 * h) : int(0.180 * h), int(0.05 * w) : int(0.95 * w)]
    if tabs.size == 0:
        return 0.0, 0.0
    gray = cv2.cvtColor(tabs, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()), float(gray.std())


def _comment_input_band(img: np.ndarray) -> tuple[float, float]:
    h, w = img.shape[:2]
    comment = img[int(0.855 * h) : int(0.892 * h), int(0.04 * w) : int(0.42 * w)]
    if comment.size == 0:
        return 0.0, 999.0
    gray = cv2.cvtColor(comment, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()), float(gray.std())


def has_feed_header_logo(img: np.ndarray, cfg: dict) -> bool:
    return _header_red_margin(img) >= float(cfg.get("header_red_min", 12.0))


def has_sticky_category_tabs(img: np.ndarray, cfg: dict) -> bool:
    mean, std = _feed_tabs_band_stats(img)
    return mean >= float(cfg.get("feed_tabs_mean_min", 215.0)) and std >= float(
        cfg.get("feed_tabs_std_min", 30.0)
    )


def has_detail_comment_input(img: np.ndarray, cfg: dict) -> bool:
    if has_feed_header_logo(img, cfg):
        return False
    mean, std = _comment_input_band(img)
    return mean >= float(cfg.get("comment_mean_min", 248.0)) and std <= float(
        cfg.get("comment_std_max", 12.0)
    )


def has_detail_action_bar(img: np.ndarray, cfg: dict) -> bool:
    if has_feed_header_logo(img, cfg):
        return False
    h, w = img.shape[:2]
    action = img[int(0.862 * h) : int(0.888 * h), int(0.55 * w) : int(0.98 * w)]
    if action.size == 0:
        return False
    std = float(action.reshape(-1, 3).astype(float).std())
    return std >= float(cfg.get("detail_action_std_min", 22.0))


def has_exit_app_toast(img: np.ndarray, cfg: dict | None = None) -> bool:
    cfg = cfg or {}
    if has_detail_comment_input(img, cfg):
        return False
    if has_feed_header_logo(img, cfg):
        mean, std = _comment_input_band(img)
        if mean >= float(cfg.get("comment_mean_min", 248.0)) and std <= float(
            cfg.get("toast_comment_std_max", 10.0)
        ):
            return True
    h, w = img.shape[:2]
    toast = img[int(0.80 * h) : int(0.88 * h), int(0.30 * w) : int(0.70 * w)]
    if toast.size == 0:
        return False
    gray = cv2.cvtColor(toast, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()) >= 210 and float(gray.std()) <= 35


def is_feed_list_page(img: np.ndarray, cfg: dict) -> bool:
    if not has_feed_header_logo(img, cfg):
        return False
    tab_mode = str(cfg.get("feed_tab_mode", "selected_blue"))
    if tab_mode == "sticky_tabs":
        return has_sticky_category_tabs(img, cfg)
    if tab_mode == "tab_band":
        band = cfg.get("active_tab_band") or {"left_ratio": 0.06, "right_ratio": 0.22}
        return _tab_band_blue_ratio(img, band) >= float(cfg.get("selected_tab_blue_min", 0.85))
    if _selected_tab_blue_ratio(img) < float(cfg.get("selected_tab_blue_min", 0.85)):
        return False
    return True


def is_on_feed_shell_no_back(img: np.ndarray, cfg: dict) -> bool:
    """Root 新闻-精选 shell — pressing BACK here triggers the exit toast."""
    if has_feed_header_logo(img, cfg):
        return True
    if is_feed_list_page(img, cfg):
        return True
    if has_sticky_category_tabs(img, cfg):
        return True
    if has_exit_app_toast(img, cfg):
        return True
    return False


def is_article_detail_page(img: np.ndarray, cfg: dict) -> bool:
    if is_on_feed_shell_no_back(img, cfg):
        return False
    if has_detail_comment_input(img, cfg):
        return True
    if has_detail_action_bar(img, cfg):
        return True
    return False


def image_has_pull_loading_footer(img: np.ndarray, cfg: dict) -> bool:
    """Detect 正在加载... row: bright, low-variance band above bottom nav."""
    h, w = img.shape[:2]
    top = int(float(cfg.get("pull_top_ratio", 0.80)) * h)
    bottom = int(float(cfg.get("pull_bottom_ratio", 0.915)) * h)
    left = int(float(cfg.get("pull_left_ratio", 0.25)) * w)
    right = int(float(cfg.get("pull_right_ratio", 0.75)) * w)
    if bottom <= top or right <= left:
        return False
    gray = cv2.cvtColor(img[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    std = float(gray.std())
    return mean >= float(cfg.get("pull_mean_min", 247.0)) and std <= float(
        cfg.get("pull_std_max", 12.0)
    )


def feed_loading_footer_visible(img: np.ndarray, bright_band_cfg: dict) -> bool:
    if image_has_pull_loading_footer(img, bright_band_cfg):
        return True
    from adb_taptap_capture import image_has_bright_loading_band

    path = Path(tempfile.gettempdir()) / f"hnrb_loading_probe_{time.time_ns()}.png"
    try:
        cv2.imencode(".png", img)[1].tofile(str(path))
        return image_has_bright_loading_band(path, bright_band_cfg)
    finally:
        path.unlink(missing_ok=True)


def choose_feed_swipe(
    feed: dict,
    img: np.ndarray | None,
    *,
    bright_band_cfg: dict | None = None,
) -> tuple[str, str, int, int]:
    if (
        img is not None
        and bright_band_cfg
        and feed_loading_footer_visible(img, bright_band_cfg)
    ):
        return (
            str(feed.get("loading_safe_start", "58%, 52%")),
            str(feed.get("loading_safe_end", "58%, 26%")),
            int(feed.get("loading_safe_duration", 480)),
            int(feed.get("loading_safe_min_duration", 420)),
        )
    start = str(feed["start"])
    end = str(feed["end"])
    duration = int(feed["duration"])
    min_duration = int(feed.get("min_duration", 0))
    return start, end, duration, min_duration


def wait_for_loading_footer_clear(
    adb: Any,
    bright_band_cfg: dict,
    *,
    max_wait_ms: int | None = None,
    poll_ms: int | None = None,
) -> bool:
    max_wait_ms = int(max_wait_ms or bright_band_cfg.get("pull_max_wait_ms", 12000))
    poll_ms = int(poll_ms or bright_band_cfg.get("pull_poll_ms", 350))
    clear_streak_need = int(bright_band_cfg.get("pull_clear_streak", 2))
    settle_ms = int(bright_band_cfg.get("pull_settle_ms", 450))
    deadline = time.time() + max_wait_ms / 1000.0
    clear_streak = 0
    while time.time() < deadline:
        temp = Path(tempfile.gettempdir()) / f"hnrb_loading_wait_{time.time_ns()}.png"
        try:
            adb.screencap(temp)
            img = imread_unicode(temp)
            if img is None or not feed_loading_footer_visible(img, bright_band_cfg):
                clear_streak += 1
                if clear_streak >= clear_streak_need:
                    adb.sleep_ms(settle_ms)
                    return True
            else:
                clear_streak = 0
        finally:
            temp.unlink(missing_ok=True)
        adb.sleep_ms(poll_ms)
    return False


def nudge_feed_after_detail_recovery(adb: Any, cfg: dict) -> None:
    """Scroll past the row that was accidentally opened so the next swipe does not re-enter it."""
    nudge = dict(cfg.get("recovery_nudge") or {})
    settle_ms = int(cfg.get("recover_settle_ms", 500))
    wait_ms = int(cfg.get("recover_nudge_wait_ms", 280))
    adb.sleep_ms(settle_ms)
    adb.swipe_points(
        str(nudge.get("start", "58%, 70%")),
        str(nudge.get("end", "58%, 57%")),
        int(nudge.get("duration", 320)),
        min_duration_ms=int(nudge.get("min_duration", 300)),
    )
    adb.sleep_ms(wait_ms)


def _load_screen(adb: Any, image_path: Path | None) -> tuple[np.ndarray | None, Path | None]:
    if image_path is not None and image_path.is_file():
        img = imread_unicode(image_path)
        return img, None
    temp = Path(tempfile.gettempdir()) / f"hnrb_guard_{time.time_ns()}.png"
    adb.screencap(temp)
    img = imread_unicode(temp)
    return img, temp


def ensure_feed_list_page(adb: Any, cfg: dict, *, image_path: Path | None = None) -> bool:
    if not cfg.get("enabled", True):
        return True
    max_tries = int(cfg.get("max_back_attempts", 3))
    wait_ms = int(cfg.get("recover_back_wait_ms", 450))
    temp_path: Path | None = None
    backs = 0
    for attempt in range(max_tries):
        img, temp_path = _load_screen(adb, image_path)
        if temp_path is not None:
            image_path = None
        if img is None:
            break
        if is_feed_list_page(img, cfg):
            if attempt > 0:
                print("  back on 新闻-精选 feed", flush=True)
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            if backs > 0:
                nudge_feed_after_detail_recovery(adb, cfg)
            return True
        if is_on_feed_shell_no_back(img, cfg):
            if backs > 0:
                print("  on 新闻-精选 shell (skip BACK to avoid exit toast)", flush=True)
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            if backs > 0:
                nudge_feed_after_detail_recovery(adb, cfg)
            return True
        if not is_article_detail_page(img, cfg):
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            return False
        print(f"  article page, BACK ({attempt + 1}/{max_tries})", flush=True)
        adb.press_back()
        backs += 1
        adb.sleep_ms(wait_ms)
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
            temp_path = None
    img, temp_path = _load_screen(adb, None)
    if temp_path is not None:
        temp_path.unlink(missing_ok=True)
    ok = img is not None and (
        is_feed_list_page(img, cfg) or is_on_feed_shell_no_back(img, cfg)
    )
    if not ok:
        print("  warning: could not confirm 新闻-精选 feed after BACK", flush=True)
    elif backs > 0:
        nudge_feed_after_detail_recovery(adb, cfg)
    return ok


def revert_last_capture(writer: Any, path: Path | None) -> None:
    if path is None:
        return
    from adb_taptap_capture import safe_unlink

    if path.is_file():
        safe_unlink(path)
    if writer.paths and writer.paths[-1] == path:
        writer.paths.pop()
    writer.seq = max(0, writer.seq - 1)
    while writer.paths and not writer.paths[-1].is_file():
        writer.paths.pop()
        writer.seq = max(0, writer.seq - 1)
    if writer.paths:
        last = writer.paths[-1]
        writer.last_sig = signature_from_path(last) if last.is_file() else None
    else:
        writer.last_sig = None
