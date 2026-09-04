#!/usr/bin/env python3
"""Collect Ctrip room-list API JSON for configured hotels and dates."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


HOME_URL = "https://www.ctrip.com/"
CTRIP_SESSION_URLS = ["https://www.ctrip.com/", "https://hotels.ctrip.com/"]
SESSION_APP_NAME = "ctrip-hotel-price-collector"
DEFAULT_PROFILE_NAME = ".cloakbrowser-profile"
DEFAULT_DETAIL_CACHE_NAME = ".ctrip-hotel-detail-cache.json"
ROOM_LIST_API_PATH = "/restapi/soa2/33278/getHotelRoomListInland"
LOGIN_XPATH = "xpath=//span[normalize-space()='登录']"
ORDERS_XPATH = "xpath=//*[normalize-space()='我的订单']"
HOTEL_SEARCH_INPUT_XPATH = "xpath=//input[@id='_allSearchKeyword']"
HOTEL_SEARCH_BUTTON_XPATH = "xpath=//*[@id='search_button_global']"
HOTEL_CANDIDATE_XPATH = "xpath=//*[@class='search_list_hotel']"
HOTEL_CANDIDATE_NAME_XPATH = "xpath=.//p"
HOTEL_CANDIDATE_TYPE_XPATH = "xpath=.//*[@type]"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "ctrip_hotel_config.json"


def session_root_for_platform(
    *,
    os_name: str,
    platform: str,
    home: Path,
    environ: Mapping[str, str],
) -> Path:
    home = home.expanduser().resolve()
    if platform == "darwin":
        base = home / "Library" / "Application Support"
    elif os_name == "nt":
        base = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    else:
        base = Path(environ.get("XDG_STATE_HOME") or home / ".local" / "state")
    return (base / SESSION_APP_NAME).expanduser().resolve()


def default_session_root() -> Path:
    return session_root_for_platform(
        os_name=os.name,
        platform=sys.platform,
        home=Path.home(),
        environ=os.environ,
    )


def require_absolute_path(value: Any, field_name: str) -> Path:
    path = Path(str(value).strip()).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{field_name} 必须使用绝对路径：{path}")
    return path


def parse_iso_date(value: Any, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是 YYYY-MM-DD 日期字符串")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} 不是有效的 YYYY-MM-DD 日期：{value}") from exc


def build_stays(config: dict[str, Any]) -> list[tuple[date, date]]:
    explicit_dates = config.get("dates")
    if explicit_dates is not None:
        if not isinstance(explicit_dates, list) or not explicit_dates:
            raise ValueError("dates 必须是非空数组")

        stays: list[tuple[date, date]] = []
        for index, item in enumerate(explicit_dates, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"dates[{index}] 必须包含 check_in 和 check_out")
            check_in = parse_iso_date(item.get("check_in"), f"dates[{index}].check_in")
            check_out = parse_iso_date(item.get("check_out"), f"dates[{index}].check_out")
            if check_out <= check_in:
                raise ValueError(f"dates[{index}] 的 check_out 必须晚于 check_in")
            stays.append((check_in, check_out))
        return stays

    start_date = parse_iso_date(config.get("start_date"), "start_date")
    try:
        days = int(config.get("days", 1))
        nights = int(config.get("nights", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("days 和 nights 必须是正整数") from exc
    if days < 1 or nights < 1:
        raise ValueError("days 和 nights 必须是正整数")

    return [
        (
            start_date + timedelta(days=offset),
            start_date + timedelta(days=offset + nights),
        )
        for offset in range(days)
    ]


def build_detail_url(
    base_url: str,
    check_in: date,
    check_out: date,
    *,
    adults: int,
    children: int,
    rooms: int,
    city_id: int | str | None = None,
) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"无效的酒店详情页 URL：{base_url}")

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if city_id is not None:
        query["cityid"] = str(city_id)
    query.update(
        {
            "checkIn": check_in.isoformat(),
            "checkOut": check_out.isoformat(),
            "crn": str(rooms),
            "adult": str(adults),
            "children": str(children),
        }
    )
    return urlunsplit(parsed._replace(query=urlencode(query)))


def is_room_list_api_url(url: str) -> bool:
    return urlsplit(url).path.rstrip("/") == ROOM_LIST_API_PATH


def sleep_random_interval(
    minimum_seconds: float,
    maximum_seconds: float,
    *,
    rng: Any = random.uniform,
    sleeper: Any = time.sleep,
) -> float:
    minimum = float(minimum_seconds)
    maximum = float(maximum_seconds)
    if minimum < 0 or maximum < minimum:
        raise ValueError("随机等待区间必须满足 0 <= min <= max")
    delay = float(rng(minimum, maximum))
    sleeper(delay)
    return delay


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value, flags=re.UNICODE)
    return cleaned.strip("._") or "hotel"


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"找不到配置文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件 JSON 格式错误：第 {exc.lineno} 行") from exc

    if not isinstance(config, dict):
        raise ValueError("配置文件根节点必须是对象")
    hotels = config.get("hotels")
    if not isinstance(hotels, list) or not hotels:
        raise ValueError("hotels 必须是非空数组")

    normalized_hotels: list[dict[str, Any]] = []
    for index, item in enumerate(hotels, start=1):
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            raise ValueError(f"hotels[{index}] 必须包含非空 name")
        normalized_hotels.append(dict(item))

    normalized = dict(config)
    normalized["hotels"] = normalized_hotels
    normalized.setdefault("city_id", 95)
    normalized.setdefault("adults", 2)
    normalized.setdefault("children", 0)
    normalized.setdefault("rooms", 1)
    session_root = default_session_root()
    normalized.setdefault(
        "output_dir",
        str(session_root / "output" / "ctrip_hotel_prices"),
    )
    normalized.setdefault("profile_dir", str(session_root / DEFAULT_PROFILE_NAME))
    normalized.setdefault(
        "detail_url_cache_file",
        str(session_root / DEFAULT_DETAIL_CACHE_NAME),
    )
    for field_name in ("output_dir", "profile_dir", "detail_url_cache_file"):
        normalized[field_name] = str(
            require_absolute_path(normalized[field_name], field_name)
        )
    normalized.setdefault("session_probe_seconds", 30)
    normalized.setdefault("random_sleep_min_seconds", 2)
    normalized.setdefault("random_sleep_max_seconds", 5)
    normalized.setdefault("login_timeout_seconds", 600)
    normalized.setdefault("search_timeout_seconds", 45)
    normalized.setdefault("api_timeout_seconds", 45)
    normalized.setdefault("settle_ms", 1500)
    normalized.setdefault("keep_browser_open", True)
    sleep_random_interval(
        normalized["random_sleep_min_seconds"],
        normalized["random_sleep_max_seconds"],
        sleeper=lambda _delay: None,
    )
    build_stays(normalized)
    return normalized


def resolve_profile_dir(config: dict[str, Any], config_dir: Path) -> Path:
    del config_dir
    return require_absolute_path(
        config.get("profile_dir", default_session_root() / DEFAULT_PROFILE_NAME),
        "profile_dir",
    )


def resolve_detail_url_cache_path(config: dict[str, Any], config_dir: Path) -> Path:
    del config_dir
    return require_absolute_path(
        config.get(
            "detail_url_cache_file",
            default_session_root() / DEFAULT_DETAIL_CACHE_NAME,
        ),
        "detail_url_cache_file",
    )


def _first_visible(locator: Any) -> Any | None:
    try:
        count = locator.count()
    except Exception:
        try:
            return locator if locator.is_visible() else None
        except Exception:
            return None
    for index in range(count):
        candidate = locator.nth(index)
        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None


def wait_for_visible(page: Any, selector: str, timeout_seconds: float, label: str) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        candidate = _first_visible(page.locator(selector))
        if candidate is not None:
            return candidate
        page.wait_for_timeout(250)
    raise TimeoutError(f"等待{label}超时（{timeout_seconds:g} 秒）")


def browser_pages(browser: Any, fallback_page: Any) -> list[Any]:
    pages: list[Any] = []
    try:
        contexts = getattr(browser, "contexts", None)
        if contexts:
            for context in contexts:
                pages.extend(context.pages)
        else:
            pages.extend(getattr(browser, "pages", []))
    except Exception:
        pass
    if fallback_page not in pages:
        pages.append(fallback_page)
    return pages


def count_ctrip_cookies(browser: Any) -> int:
    cookie_reader = getattr(browser, "cookies", None)
    if not callable(cookie_reader):
        return 0
    try:
        return len(cookie_reader(CTRIP_SESSION_URLS))
    except Exception:
        return 0


def find_logged_in_page(browser: Any, fallback_page: Any) -> Any | None:
    for page in browser_pages(browser, fallback_page):
        try:
            has_orders = _first_visible(page.locator(ORDERS_XPATH)) is not None
            if has_orders:
                return page
        except Exception:
            continue
    return None


def wait_for_login(
    browser: Any,
    page: Any,
    timeout_seconds: float,
    *,
    session_probe_seconds: float = 15,
    has_persisted_cookies: bool = False,
) -> Any:
    probe_deadline = time.monotonic() + min(timeout_seconds, session_probe_seconds)
    logged_in_since: float | None = None
    login_visible_since: float | None = None
    while time.monotonic() < probe_deadline:
        logged_in_page = find_logged_in_page(browser, page)
        now = time.monotonic()
        if logged_in_page is not None:
            logged_in_since = logged_in_since or now
            if now - logged_in_since >= 1:
                print("已通过本地会话检测到“我的订单”，直接使用已登录状态。", flush=True)
                return logged_in_page
        else:
            logged_in_since = None

        if _first_visible(page.locator(LOGIN_XPATH)) is not None:
            login_visible_since = login_visible_since or now
            if not has_persisted_cookies and now - login_visible_since >= 2:
                break
        else:
            login_visible_since = None
        page.wait_for_timeout(500)

    login_button = _first_visible(page.locator(LOGIN_XPATH))
    if login_button is not None:
        login_button.click()
        print("请在 CloakBrowser 窗口中手动登录你自己的携程账号，脚本会自动等待。", flush=True)
    else:
        logged_in_page = find_logged_in_page(browser, page)
        if logged_in_page is not None:
            print("已检测到“我的订单”，当前账号已登录。", flush=True)
            return logged_in_page
        raise TimeoutError("找不到登录入口，也未检测到已登录状态")

    deadline = time.monotonic() + timeout_seconds
    next_notice = time.monotonic() + 10
    logged_in_since = None
    while time.monotonic() < deadline:
        logged_in_page = find_logged_in_page(browser, page)
        now = time.monotonic()
        if logged_in_page is not None:
            logged_in_since = logged_in_since or now
            if now - logged_in_since >= 1:
                print("已检测到“我的订单”，登录成功。", flush=True)
                return logged_in_page
        else:
            logged_in_since = None
        if time.monotonic() >= next_notice:
            remaining = max(0, int(deadline - time.monotonic()))
            print(f"仍在等待登录完成，剩余约 {remaining} 秒。", flush=True)
            next_notice = time.monotonic() + 10
        page.wait_for_timeout(1000)

    raise TimeoutError(f"等待登录超时（{timeout_seconds:g} 秒），未发现“我的订单”")


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def normalized_city_id(city_id: int | str | None) -> str:
    if city_id is None:
        return ""
    return normalized_text(str(city_id).strip())


def hotel_cache_key(
    hotel_name: str,
    city_id: int | str | None = None,
) -> str:
    name_key = normalized_text(str(hotel_name).strip())
    city_key = normalized_city_id(city_id)
    return f"{name_key}::city={city_key}" if city_key else name_key


def is_valid_detail_url(url: str) -> bool:
    parsed = urlsplit(str(url).strip())
    path = parsed.path.lower()
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and re.search(
            r"/hotels?/(?!list(?:/|$)|search(?:/|$))[^/]+$",
            path,
        )
        is not None
    )


def _cache_record_timestamp(record: dict[str, Any]) -> str:
    return str(record.get("updated_at") or "").strip()


def _prefer_cache_record(
    current: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    if current is None:
        return incoming

    current_timestamp = _cache_record_timestamp(current)
    incoming_timestamp = _cache_record_timestamp(incoming)
    if incoming_timestamp and current_timestamp:
        return incoming if incoming_timestamp >= current_timestamp else current
    if incoming_timestamp:
        return incoming
    return current


def _normalize_detail_url_cache(
    cache: dict[str, dict[str, Any]] | Any,
) -> dict[str, dict[str, Any]]:
    if not isinstance(cache, dict):
        return {}

    normalized_cache: dict[str, dict[str, Any]] = {}
    for stored_key, record in cache.items():
        if not isinstance(record, dict):
            continue
        hotel_name = str(record.get("hotel_name") or stored_key).strip()
        detail_url = str(record.get("detail_url", "")).strip()
        city_id = record.get("city_id")
        key = hotel_cache_key(hotel_name, city_id)
        if not normalized_text(hotel_name) or not is_valid_detail_url(detail_url):
            continue
        normalized_record = {
            "hotel_name": hotel_name,
            "detail_url": detail_url,
            "city_id": city_id,
            "updated_at": record.get("updated_at", ""),
        }
        normalized_cache[key] = _prefer_cache_record(
            normalized_cache.get(key),
            normalized_record,
        )
    return normalized_cache


def load_detail_url_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"详情页缓存不可读取，将重新搜索：{path}（{exc}）", file=sys.stderr)
        return {}

    items = payload.get("items") if isinstance(payload, dict) else None
    return _normalize_detail_url_cache(items)


def get_cached_detail_url(
    cache: dict[str, dict[str, Any]],
    hotel_name: str,
    *,
    city_id: int | str | None = None,
) -> str | None:
    exact_key = hotel_cache_key(hotel_name, city_id)
    record = cache.get(exact_key)
    if not isinstance(record, dict) and city_id is not None:
        # Read caches written before city_id became part of the key.
        record = cache.get(hotel_cache_key(hotel_name))
    if not isinstance(record, dict):
        return None

    stored_city_id = normalized_city_id(record.get("city_id"))
    requested_city_id = normalized_city_id(city_id)
    if requested_city_id and stored_city_id and stored_city_id != requested_city_id:
        return None

    detail_url = str(record.get("detail_url", "")).strip()
    return detail_url if is_valid_detail_url(detail_url) else None


def cache_detail_url(
    cache: dict[str, dict[str, Any]],
    hotel_name: str,
    detail_url: str,
    *,
    city_id: int | str | None = None,
) -> None:
    normalized_name = str(hotel_name).strip()
    if not normalized_text(normalized_name):
        raise ValueError("酒店名称不能为空")
    normalized_url = str(detail_url).strip()
    if not is_valid_detail_url(normalized_url):
        raise ValueError(f"无效的酒店详情页 URL：{detail_url}")
    cache[hotel_cache_key(normalized_name, city_id)] = {
        "hotel_name": normalized_name,
        "detail_url": normalized_url,
        "city_id": city_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@contextmanager
def detail_url_cache_lock(path: Path):
    """Serialize cache read/merge/write operations across collector processes."""
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            lock_file.write(b"0")
            lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def save_detail_url_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    with detail_url_cache_lock(path):
        disk_cache = load_detail_url_cache(path)
        incoming_cache = _normalize_detail_url_cache(cache)
        merged_cache = dict(disk_cache)
        for key, record in incoming_cache.items():
            merged_cache[key] = _prefer_cache_record(
                merged_cache.get(key),
                record,
            )

        cache.clear()
        cache.update(merged_cache)
        write_json(
            path,
            {
                "version": 2,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "items": merged_cache,
            },
        )


def find_hotel_detail_href(page: Any, hotel_name: str) -> str | None:
    target = normalized_text(hotel_name)
    anchors = page.locator("a")
    try:
        count = min(anchors.count(), 1500)
    except Exception:
        return None

    for index in range(count):
        anchor = anchors.nth(index)
        try:
            href = anchor.get_attribute("href") or ""
            if not href or "hotel" not in href.lower():
                continue
            text = " ".join(
                value
                for value in (
                    anchor.inner_text(timeout=500),
                    anchor.get_attribute("title") or "",
                    anchor.get_attribute("aria-label") or "",
                )
                if value
            )
            if target in normalized_text(text):
                absolute_href = urljoin(page.url, href)
                if is_valid_detail_url(absolute_href):
                    return absolute_href
        except Exception:
            continue
    return None


def _get_attribute(locator: Any, name: str) -> str:
    try:
        value = locator.get_attribute(name)
    except Exception:
        return ""
    return str(value or "").strip()


def extract_hotel_candidates(page: Any) -> list[dict[str, Any]]:
    """Read usable hotel candidates from Ctrip's global search result list."""
    candidates_locator = page.locator(HOTEL_CANDIDATE_XPATH)
    try:
        count = candidates_locator.count()
    except Exception:
        return []

    candidates: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index in range(count):
        candidate_locator = candidates_locator.nth(index)
        try:
            if not candidate_locator.is_visible():
                continue

            candidate_type = _get_attribute(candidate_locator, "type")
            if not candidate_type:
                try:
                    candidate_type = candidate_locator.locator(
                        HOTEL_CANDIDATE_TYPE_XPATH
                    ).inner_text(timeout=1_000).strip()
                except Exception:
                    candidate_type = ""
            if candidate_type.lower() not in {"hotel", "酒店"}:
                continue

            candidate_name = _get_attribute(candidate_locator, "word")
            if not candidate_name:
                try:
                    candidate_name = candidate_locator.locator(
                        HOTEL_CANDIDATE_NAME_XPATH
                    ).inner_text(timeout=1_000).strip()
                except Exception:
                    candidate_name = ""
            if not candidate_name:
                continue

            candidate_url = _get_attribute(candidate_locator, "url")
            candidate_district = _get_attribute(candidate_locator, "district")
            has_attribute_api = callable(getattr(candidate_locator, "get_attribute", None))
            if has_attribute_api and (
                not candidate_url or not is_valid_detail_url(candidate_url)
            ):
                continue
            dedupe_key = candidate_url or candidate_name
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            candidates.append(
                {
                    "name": candidate_name,
                    "type": candidate_type,
                    "district": candidate_district,
                    "url": candidate_url,
                    "page": page,
                    "locator": candidate_locator,
                }
            )
        except Exception:
            continue
    return candidates


def wait_for_hotel_candidates(
    page: Any,
    timeout_seconds: float,
    *,
    browser: Any | None = None,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for candidate_page in browser_pages(browser, page) if browser else [page]:
            candidates = extract_hotel_candidates(candidate_page)
            if candidates:
                return candidates
        page.wait_for_timeout(250)
    raise TimeoutError(f"等待酒店候选下拉超时（{timeout_seconds:g} 秒）")


def choose_hotel_candidate(
    candidates: list[dict[str, Any]],
    *,
    input_fn: Any = input,
) -> dict[str, Any]:
    if not candidates:
        raise ValueError("没有可选择的酒店候选")
    if len(candidates) == 1:
        selected_index = 0
    else:
        print("找到多个酒店候选，请选择：", flush=True)
        for index, candidate in enumerate(candidates, start=1):
            district = str(candidate.get("district") or "").strip()
            suffix = f"（{district}）" if district else ""
            print(f"  {index}. {candidate['name']}{suffix}", flush=True)
        while True:
            try:
                value = input_fn("请选择酒店序号：").strip()
            except EOFError as exc:
                raise RuntimeError(
                    "当前终端无法接收酒店选择，请在交互式终端中重新运行。"
                ) from exc
            try:
                selected_index = int(value) - 1
            except ValueError:
                selected_index = -1
            if 0 <= selected_index < len(candidates):
                break
            print(f"请输入 1 到 {len(candidates)} 之间的序号。", flush=True)
    return candidates[selected_index]


def search_hotel(
    browser: Any,
    page: Any,
    hotel_name: str,
    *,
    timeout_seconds: float,
    input_fn: Any = input,
) -> tuple[Any, str]:
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    search_input = wait_for_visible(
        page, HOTEL_SEARCH_INPUT_XPATH, 60, "酒店模糊搜索框"
    )
    search_input.fill(hotel_name)
    search_button = wait_for_visible(
        page,
        HOTEL_SEARCH_BUTTON_XPATH,
        60,
        "携程搜索按钮",
    )
    search_button.click(timeout=5_000)
    page.wait_for_timeout(250)
    candidates: list[dict[str, Any]] = []
    for candidate_page in browser_pages(browser, page):
        candidates = extract_hotel_candidates(candidate_page)
        if candidates:
            break
    if not candidates:
        # Ctrip may close the global result list after the button click. Re-fire
        # the input event so the same fuzzy query renders the candidate list.
        search_input.fill(hotel_name)
        candidates = wait_for_hotel_candidates(
            page,
            timeout_seconds,
            browser=browser,
        )
    selected_candidate = choose_hotel_candidate(candidates, input_fn=input_fn)
    selected_hotel_name = str(selected_candidate["name"])
    selected_page = selected_candidate.get("page", page)
    selected_candidate["locator"].click(timeout=5_000)

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pages = browser_pages(browser, page)
        for candidate in pages:
            try:
                if is_valid_detail_url(candidate.url):
                    return candidate, candidate.url
                href = find_hotel_detail_href(candidate, selected_hotel_name)
                if href:
                    return candidate, href
            except Exception:
                continue

        for candidate in pages:
            try:
                text_match = _first_visible(
                    candidate.get_by_text(selected_hotel_name, exact=True)
                )
                if text_match is not None:
                    text_match.click(timeout=5_000)
                    candidate.wait_for_timeout(1000)
                    for opened_page in browser_pages(browser, candidate):
                        if is_valid_detail_url(opened_page.url):
                            return opened_page, opened_page.url
            except Exception:
                continue

        selected_url = str(selected_candidate.get("url") or "").strip()
        if selected_url and is_valid_detail_url(selected_url):
            return selected_page, urljoin(selected_page.url, selected_url)
        page.wait_for_timeout(1000)

    raise TimeoutError(f"搜索酒店超时，未找到详情页：{selected_hotel_name}")


def resolve_hotel_detail(
    *,
    browser: Any,
    page: Any,
    hotel: dict[str, Any],
    config: dict[str, Any],
    detail_url_cache: dict[str, dict[str, Any]],
    timeout_seconds: float,
    search_hotel_fn: Any = search_hotel,
) -> tuple[Any, str, str]:
    hotel_name = str(hotel["name"]).strip()
    city_id = hotel.get("city_id", config.get("city_id"))
    configured_url = str(hotel.get("detail_url", "")).strip()
    if configured_url:
        if not is_valid_detail_url(configured_url):
            raise ValueError(f"无效的酒店详情页 URL：{configured_url}")
        cache_detail_url(
            detail_url_cache,
            hotel_name,
            configured_url,
            city_id=city_id,
        )
        return page, configured_url, "configured"

    cached_url = get_cached_detail_url(
        detail_url_cache,
        hotel_name,
        city_id=city_id,
    )
    if cached_url:
        print(f"使用详情页缓存：{cached_url}", flush=True)
        return page, cached_url, "cache"

    detail_page, detail_url = search_hotel_fn(
        browser,
        page,
        hotel_name,
        timeout_seconds=timeout_seconds,
    )
    cache_detail_url(
        detail_url_cache,
        hotel_name,
        detail_url,
        city_id=city_id,
    )
    print(f"详情页搜索完成并已缓存：{detail_url}", flush=True)
    return detail_page, detail_url, "search"


def capture_room_list_responses(
    page: Any,
    detail_url: str,
    *,
    api_timeout_seconds: float,
    settle_ms: int,
) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []

    # The API can be requested more than once during a detail-page refresh.
    def handle_response(response: Any) -> None:
        if not is_room_list_api_url(response.url):
            return
        try:
            if response.request.method.upper() == "OPTIONS":
                return
            data = response.json()
            responses.append(
                {
                    "url": response.url,
                    "status": response.status,
                    "method": response.request.method,
                    "request_post_data": response.request.post_data,
                    "data": data,
                }
            )
        except Exception:
            return

    page.on("response", handle_response)
    try:
        page.goto(detail_url, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.monotonic() + api_timeout_seconds
        while not responses and time.monotonic() < deadline:
            page.wait_for_timeout(250)
        if not responses:
            raise TimeoutError(
                f"等待房型接口超时（{api_timeout_seconds:g} 秒）：{detail_url}"
            )
        page.wait_for_timeout(max(0, settle_ms))
        return responses
    finally:
        try:
            page.remove_listener("response", handle_response)
        except Exception:
            pass


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _category_titles(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return "；".join(
        str(item.get("title", "")).strip()
        for item in value
        if isinstance(item, dict) and str(item.get("title", "")).strip()
    )


def flatten_room_rows(
    *,
    hotel_name: str,
    check_in: str,
    check_out: str,
    detail_url: str,
    captured_at: str,
    source_file: str,
    responses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten the API's physical-room and sale-room maps for Excel output."""
    latest_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for response in responses:
        response_data = _as_dict(response.get("data"))
        data = _as_dict(response_data.get("data"))
        physical_map = _as_dict(data.get("physicRoomMap"))
        sale_map = _as_dict(data.get("saleRoomMap"))
        for sale_key, sale in sale_map.items():
            sale = _as_dict(sale)
            physical_id = str(sale.get("physicalRoomId", ""))
            physical = _as_dict(physical_map.get(physical_id))
            if not physical and physical_id.isdigit():
                physical = _as_dict(physical_map.get(int(physical_id)))

            price_info = _as_dict(sale.get("priceInfo"))
            total_info = _as_dict(sale.get("totalPriceInfo"))
            total = _as_dict(total_info.get("total"))
            booking = _as_dict(sale.get("bookingStatusInfo"))
            cancel_info = _as_dict(sale.get("cancelInfo"))
            bed_info = _as_dict(physical.get("bedInfo"))
            room_name = (
                str(physical.get("name", "")).strip()
                or str(sale.get("name", "")).strip()
                or f"房型 {physical_id or sale_key}"
            )
            row = {
                "酒店名称": hotel_name,
                "入住日期": check_in,
                "离店日期": check_out,
                "房型": room_name,
                "房型ID": physical_id,
                "销售方案": str(sale.get("name", "")).strip(),
                "销售方案ID": sale.get("id"),
                "价格": price_info.get("price"),
                "原价": price_info.get("deletePricewithOutCurrency"),
                "货币": price_info.get("currency", ""),
                "显示价格": price_info.get("displayPrice", ""),
                "总价展示": total.get("content", ""),
                "床型": bed_info.get("title", ""),
                "早餐及权益": _category_titles(sale.get("saleRoomCategoryList")),
                "取消政策": cancel_info.get("simpleDesc") or cancel_info.get("title", ""),
                "预订状态": booking.get("buttonText", ""),
                "可预订": booking.get("isBooking"),
                "余房": booking.get("remainRoomQuantity"),
                "销售方案Key": str(sale_key),
                "接口状态": response.get("status"),
                "接口URL": response.get("url", ""),
                "JSON文件": source_file,
                "采集时间": captured_at,
                "详情页URL": detail_url,
            }
            latest_rows[(str(sale_key), check_in, check_out)] = row

    return sorted(
        latest_rows.values(),
        key=lambda row: (
            str(row["酒店名称"]),
            str(row["入住日期"]),
            str(row["房型"]),
            str(row["销售方案Key"]),
        ),
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def write_run_index(
    path: Path,
    items: list[dict[str, Any]],
    *,
    status: str,
    error: str | None = None,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "version": 1,
        "status": status,
        "generated_at": timestamp,
        "updated_at": timestamp,
        "items": items,
    }
    if error:
        payload["error"] = error
    write_json(path, payload)


def close_browser_safely(browser: Any) -> None:
    try:
        browser.close()
    except Exception:
        print("浏览器实例可能已由托管环境清理，跳过重复关闭。", file=sys.stderr)


def export_excel(input_dir: Path, output_path: Path) -> bool:
    script_dir = Path(__file__).resolve().parent
    py_builder = script_dir / "ctrip_hotel_excel_builder.py"
    if not py_builder.is_file():
        print(f"找不到 Python Excel 生成器：{py_builder}", file=sys.stderr)
        return False

    result = subprocess.run(
        [
            sys.executable,
            str(py_builder),
            "--input-dir",
            str(input_dir),
            "--output",
            str(output_path),
        ],
        cwd=str(script_dir),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.stdout.strip():
        print(result.stdout.strip(), flush=True)
    if result.returncode != 0:
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        print("Python Excel 生成器执行失败，请确认已安装 requirements-cloak.txt。", file=sys.stderr)
        return False
    return True


def collect_prices(
    config: dict[str, Any],
    *,
    config_dir: Path,
    login_only: bool = False,
) -> int:
    try:
        from cloakbrowser import launch_persistent_context
    except ModuleNotFoundError:
        print(
            "缺少 CloakBrowser 依赖，请先执行技能包的"
            " scripts/bootstrap_ctrip_hotel_skill.sh",
            file=sys.stderr,
        )
        return 1

    output_dir = require_absolute_path(config["output_dir"], "output_dir")
    profile_dir = resolve_profile_dir(config, config_dir)
    detail_url_cache_path = resolve_detail_url_cache_path(config, config_dir)
    detail_url_cache = load_detail_url_cache(detail_url_cache_path)
    profile_exists = profile_dir.exists()
    stays = build_stays(config)
    browser = None
    summary: list[dict[str, Any]] = []
    index_path = output_dir / "index.json"
    operation_started = False

    def checkpoint(status: str, error: str | None = None) -> None:
        try:
            write_run_index(index_path, summary, status=status, error=error)
        except Exception as exc:
            print(f"采集进度无法保存：{exc}", file=sys.stderr)

    def wait_between_operations(label: str) -> None:
        nonlocal operation_started
        if operation_started:
            delay = sleep_random_interval(
                config["random_sleep_min_seconds"],
                config["random_sleep_max_seconds"],
            )
            print(f"{label}前随机等待 {delay:.2f} 秒。", flush=True)
        operation_started = True

    try:
        print("正在启动带本地会话的 CloakBrowser...", flush=True)
        if profile_exists:
            print(f"发现本地会话目录，先校验登录状态：{profile_dir}", flush=True)
        else:
            print(f"未发现本地会话目录，将在首次登录后保存：{profile_dir}", flush=True)
        browser = launch_persistent_context(str(profile_dir), headless=False)
        cookie_count = count_ctrip_cookies(browser)
        if cookie_count:
            print(f"已加载本地携程 Cookie（{cookie_count} 个），正在验证登录状态。", flush=True)
        else:
            print("本地未加载到携程 Cookie，等待手动登录。", flush=True)
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        page = wait_for_login(
            browser,
            page,
            float(config["login_timeout_seconds"]),
            session_probe_seconds=float(config["session_probe_seconds"]),
            has_persisted_cookies=cookie_count > 0,
        )
        checkpoint("running")

        if login_only:
            print(f"登录会话已保存到：{profile_dir}", flush=True)
            if config.get("keep_browser_open", True):
                try:
                    input("登录状态已保存。按 Enter 关闭浏览器：")
                except EOFError:
                    pass
            return 0

        for hotel in config["hotels"]:
            hotel_name = str(hotel["name"]).strip()
            print(f"\n开始处理：{hotel_name}", flush=True)
            wait_between_operations(f"处理酒店 {hotel_name}")
            city_id = hotel.get("city_id", config.get("city_id"))
            detail_page, detail_url, detail_source = resolve_hotel_detail(
                browser=browser,
                page=page,
                hotel=hotel,
                config=config,
                detail_url_cache=detail_url_cache,
                timeout_seconds=float(config["search_timeout_seconds"]),
            )
            page = detail_page
            if detail_source == "configured":
                print(f"使用配置中的详情页：{detail_url}", flush=True)
            save_detail_url_cache(detail_url_cache_path, detail_url_cache)
            checkpoint("running")

            for check_in, check_out in stays:
                wait_between_operations(f"抓取日期 {check_in.isoformat()}")
                target_url = build_detail_url(
                    detail_url,
                    check_in,
                    check_out,
                    adults=int(config["adults"]),
                    children=int(config["children"]),
                    rooms=int(config["rooms"]),
                    city_id=city_id,
                )
                file_path = (
                    output_dir
                    / safe_filename(hotel_name)
                    / f"{check_in.isoformat()}_{check_out.isoformat()}.json"
                )
                print(
                    f"抓取 {check_in.isoformat()} 至 {check_out.isoformat()}...",
                    flush=True,
                )
                try:
                    responses = capture_room_list_responses(
                        detail_page,
                        target_url,
                        api_timeout_seconds=float(config["api_timeout_seconds"]),
                        settle_ms=int(config["settle_ms"]),
                    )
                    room_rows = flatten_room_rows(
                        hotel_name=hotel_name,
                        check_in=check_in.isoformat(),
                        check_out=check_out.isoformat(),
                        detail_url=target_url,
                        captured_at=datetime.now(timezone.utc).isoformat(),
                        source_file=str(file_path),
                        responses=responses,
                    )
                    payload = {
                        "hotel_name": hotel_name,
                        "check_in": check_in.isoformat(),
                        "check_out": check_out.isoformat(),
                        "detail_url": target_url,
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "responses": responses,
                        "room_rows": room_rows,
                    }
                    write_json(file_path, payload)
                    summary.append(
                        {
                            "hotel_name": hotel_name,
                            "check_in": check_in.isoformat(),
                            "check_out": check_out.isoformat(),
                            "status": "ok",
                            "response_count": len(responses),
                            "room_row_count": len(room_rows),
                            "file": str(file_path),
                        }
                    )
                    print(f"已保存：{file_path}", flush=True)
                    checkpoint("running")
                except Exception as exc:
                    error_payload = {
                        "hotel_name": hotel_name,
                        "check_in": check_in.isoformat(),
                        "check_out": check_out.isoformat(),
                        "detail_url": target_url,
                        "status": "error",
                        "error": str(exc),
                    }
                    error_path = file_path.with_suffix(".error.json")
                    write_json(error_path, error_payload)
                    summary.append(
                        {
                            "hotel_name": hotel_name,
                            "check_in": check_in.isoformat(),
                            "check_out": check_out.isoformat(),
                            "status": "error",
                            "room_row_count": 0,
                            "error": str(exc),
                            "file": str(error_path),
                        }
                    )
                    print(f"本日期失败，已记录：{error_path}", file=sys.stderr)
                    checkpoint("running")

        checkpoint("ready_for_export")
        ok_count = sum(item["status"] == "ok" for item in summary)
        print(f"\n处理完成：{ok_count}/{len(summary)} 个日期成功。", flush=True)
        print(f"汇总文件：{index_path}", flush=True)
        excel_path = output_dir / "ctrip_hotel_prices.xlsx"
        excel_exported = export_excel(output_dir, excel_path)
        if excel_exported:
            print(f"Excel 文件：{excel_path}", flush=True)
            checkpoint("completed")
        else:
            print("Excel 生成失败，原始 JSON 仍已保存。", file=sys.stderr)
            checkpoint("failed", "Excel 生成失败")
        if config.get("keep_browser_open", True):
            try:
                input("浏览器仍保持打开。按 Enter 关闭：")
            except EOFError:
                pass
        return 0 if ok_count == len(summary) and excel_exported else 2
    except Exception as exc:
        checkpoint("failed", str(exc))
        if summary:
            partial_excel_path = output_dir / "ctrip_hotel_prices.xlsx"
            if export_excel(output_dir, partial_excel_path):
                print(f"已根据已落盘结果生成部分 Excel：{partial_excel_path}", flush=True)
        print(f"采集失败：{exc}", file=sys.stderr)
        return 1
    finally:
        if browser is not None:
            close_browser_safely(browser)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集携程酒店房型价格接口 JSON")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="JSON 配置文件路径",
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="只打开并保存登录会话，不执行酒店采集",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    try:
        config = load_config(config_path)
    except ValueError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1
    return collect_prices(
        config,
        config_dir=config_path.parent,
        login_only=args.login_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
