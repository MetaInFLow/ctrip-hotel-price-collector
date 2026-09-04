#!/usr/bin/env python3
"""Collect Ctrip room-list API JSON for configured hotels and dates."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


HOME_URL = "https://www.ctrip.com/"
CTRIP_SESSION_URLS = ["https://www.ctrip.com/", "https://hotels.ctrip.com/"]
ROOM_LIST_API_PATH = "/restapi/soa2/33278/getHotelRoomListInland"
LOGIN_XPATH = "xpath=//span[normalize-space()='登录']"
ORDERS_XPATH = "xpath=//*[normalize-space()='我的订单']"
SEARCH_INPUT_XPATH = "xpath=//input[@id='_allSearchKeyword']"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "ctrip_hotel_config.json"


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
    normalized.setdefault("output_dir", "output/ctrip_hotel_prices")
    normalized.setdefault("profile_dir", ".cloakbrowser-profile")
    normalized.setdefault("detail_url_cache_file", ".ctrip-hotel-detail-cache.json")
    normalized.setdefault("session_probe_seconds", 15)
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
    profile_dir = Path(str(config.get("profile_dir", ".cloakbrowser-profile")).strip())
    profile_dir = profile_dir.expanduser()
    if profile_dir.is_absolute():
        return profile_dir
    return config_dir / profile_dir


def resolve_detail_url_cache_path(config: dict[str, Any], config_dir: Path) -> Path:
    cache_file = str(
        config.get("detail_url_cache_file", ".ctrip-hotel-detail-cache.json")
    ).strip() or ".ctrip-hotel-detail-cache.json"
    cache_path = Path(cache_file).expanduser()
    if cache_path.is_absolute():
        return cache_path
    return config_dir / cache_path


def _first_visible(locator: Any) -> Any | None:
    try:
        count = locator.count()
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
            if now - login_visible_since >= 2:
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
    while time.monotonic() < deadline:
        logged_in_page = find_logged_in_page(browser, page)
        if logged_in_page is not None:
            print("已检测到“我的订单”，登录成功。", flush=True)
            return logged_in_page
        if time.monotonic() >= next_notice:
            remaining = max(0, int(deadline - time.monotonic()))
            print(f"仍在等待登录完成，剩余约 {remaining} 秒。", flush=True)
            next_notice = time.monotonic() + 10
        page.wait_for_timeout(1000)

    raise TimeoutError(f"等待登录超时（{timeout_seconds:g} 秒），未发现“我的订单”")


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def hotel_cache_key(hotel_name: str) -> str:
    return normalized_text(str(hotel_name).strip())


def is_valid_detail_url(url: str) -> bool:
    parsed = urlsplit(str(url).strip())
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and "/hotels/" in parsed.path.lower()
    )


def load_detail_url_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"详情页缓存不可读取，将重新搜索：{path}（{exc}）", file=sys.stderr)
        return {}

    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, dict):
        return {}

    cache: dict[str, dict[str, Any]] = {}
    for stored_key, record in items.items():
        if not isinstance(record, dict):
            continue
        hotel_name = str(record.get("hotel_name") or stored_key).strip()
        detail_url = str(record.get("detail_url", "")).strip()
        key = hotel_cache_key(hotel_name)
        if key and is_valid_detail_url(detail_url):
            cache[key] = {
                "hotel_name": hotel_name,
                "detail_url": detail_url,
                "city_id": record.get("city_id"),
                "updated_at": record.get("updated_at", ""),
            }
    return cache


def get_cached_detail_url(
    cache: dict[str, dict[str, Any]],
    hotel_name: str,
    *,
    city_id: int | str | None = None,
) -> str | None:
    record = cache.get(hotel_cache_key(hotel_name))
    if not isinstance(record, dict):
        return None

    stored_city_id = record.get("city_id")
    if (
        city_id is not None
        and stored_city_id not in (None, "", city_id, str(city_id))
    ):
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
    if not hotel_cache_key(normalized_name):
        raise ValueError("酒店名称不能为空")
    normalized_url = str(detail_url).strip()
    if not is_valid_detail_url(normalized_url):
        raise ValueError(f"无效的酒店详情页 URL：{detail_url}")
    cache[hotel_cache_key(normalized_name)] = {
        "hotel_name": normalized_name,
        "detail_url": normalized_url,
        "city_id": city_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_detail_url_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    write_json(
        path,
        {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": cache,
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
                return urljoin(page.url, href)
        except Exception:
            continue
    return None


def search_hotel(
    browser: Any,
    page: Any,
    hotel_name: str,
    *,
    timeout_seconds: float,
) -> tuple[Any, str]:
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    search_input = wait_for_visible(page, SEARCH_INPUT_XPATH, 60, "酒店搜索框")
    search_input.fill(hotel_name)
    search_input.press("Enter")

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pages = browser_pages(browser, page)
        for candidate in pages:
            try:
                if "/hotels/" in candidate.url.lower():
                    return candidate, candidate.url
                href = find_hotel_detail_href(candidate, hotel_name)
                if href:
                    return candidate, href
            except Exception:
                continue

        for candidate in pages:
            try:
                text_match = _first_visible(candidate.get_by_text(hotel_name, exact=True))
                if text_match is not None:
                    text_match.click(timeout=5_000)
                    candidate.wait_for_timeout(1000)
                    for opened_page in browser_pages(browser, candidate):
                        if "/hotels/" in opened_page.url.lower():
                            return opened_page, opened_page.url
            except Exception:
                continue
        page.wait_for_timeout(1000)

    raise TimeoutError(f"搜索酒店超时，未找到详情页：{hotel_name}")


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
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def export_excel(input_dir: Path, output_path: Path) -> bool:
    script_dir = Path(__file__).parent
    py_builder = script_dir / "ctrip_hotel_excel_builder.py"
    mjs_builder = script_dir / "ctrip_hotel_excel_builder.mjs"

    # 优先使用 Python + openpyxl 生成器，不依赖 @oai/artifact-tool。
    if py_builder.is_file():
        result = subprocess.run(
            [sys.executable, str(py_builder), "--input-dir", str(input_dir), "--output", str(output_path)],
            cwd=str(script_dir),
            text=True,
            capture_output=True,
            check=False,
        )
        if result.stdout.strip():
            print(result.stdout.strip(), flush=True)
        if result.returncode == 0:
            return True
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        print("openpyxl 生成器失败，尝试回退到 Node.js 生成器。", file=sys.stderr)

    # 回退：Node.js + @oai/artifact-tool 生成器（旧路径，可选）。
    if not mjs_builder.is_file():
        print(f"找不到 Excel 生成器：{py_builder} 或 {mjs_builder}", file=sys.stderr)
        return False

    node_bin = os.environ.get("CTRIP_NODE") or shutil.which("node")
    if not node_bin:
        print("找不到 Node.js，无法生成 Excel。可设置 CTRIP_NODE 指向 Node.js。", file=sys.stderr)
        return False

    result = subprocess.run(
        [node_bin, str(mjs_builder), "--input-dir", str(input_dir), "--output", str(output_path)],
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

    output_dir = Path(config["output_dir"])
    if not output_dir.is_absolute():
        output_dir = config_dir / output_dir
    profile_dir = resolve_profile_dir(config, config_dir)
    detail_url_cache_path = resolve_detail_url_cache_path(config, config_dir)
    detail_url_cache = load_detail_url_cache(detail_url_cache_path)
    profile_exists = profile_dir.exists()
    stays = build_stays(config)
    browser = None
    summary: list[dict[str, Any]] = []
    operation_started = False

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
        )

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

        index_path = output_dir / "index.json"
        write_json(
            index_path,
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "items": summary,
            },
        )
        ok_count = sum(item["status"] == "ok" for item in summary)
        print(f"\n处理完成：{ok_count}/{len(summary)} 个日期成功。", flush=True)
        print(f"汇总文件：{index_path}", flush=True)
        excel_path = output_dir / "ctrip_hotel_prices.xlsx"
        excel_exported = export_excel(output_dir, excel_path)
        if excel_exported:
            print(f"Excel 文件：{excel_path}", flush=True)
        else:
            print("Excel 生成失败，原始 JSON 仍已保存。", file=sys.stderr)
        if config.get("keep_browser_open", True):
            try:
                input("浏览器仍保持打开。按 Enter 关闭：")
            except EOFError:
                pass
        return 0 if ok_count == len(summary) and excel_exported else 2
    except Exception as exc:
        print(f"采集失败：{exc}", file=sys.stderr)
        return 1
    finally:
        if browser is not None:
            browser.close()


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
