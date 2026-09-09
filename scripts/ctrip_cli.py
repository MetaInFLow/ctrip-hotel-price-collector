#!/usr/bin/env python3
"""Ctrip CLI with atomic login, search, status, and price commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ctrip_cli_auth import ensure_login, login_status  # noqa: E402
from ctrip_cli_browser import (  # noqa: E402
    CtripBrowserSession,
    HOME_URL,
    close_other_pages,
)
from ctrip_cli_price import collect_one_stay  # noqa: E402
from ctrip_cli_search import (  # noqa: E402
    fuzzy_search_hotel,
    public_candidate,
    search_candidates,
)
from ctrip_hotel_prices import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    DEFAULT_DETAIL_CACHE_NAME,
    DEFAULT_PROFILE_NAME,
    DEFAULT_SHOW_ALL_ROOMS_XPATH,
    build_stays,
    default_session_root,
    is_valid_detail_url,
    load_config,
    load_detail_url_cache,
    resolve_hotel_detail,
    safe_filename,
    save_detail_url_cache,
    validate_price_config,
    write_json,
)
from ctrip_runtime_setup import setup_runtime  # noqa: E402


def default_profile_dir() -> Path:
    return default_session_root() / DEFAULT_PROFILE_NAME


def command_names(parser: argparse.ArgumentParser) -> list[str]:
    subparsers = getattr(parser, "_subparsers", None)
    if subparsers is None or subparsers._group_actions == []:
        return []
    action = subparsers._group_actions[0]
    return list(action.choices)


def _add_session_options(
    parser: argparse.ArgumentParser,
    *,
    suppress_defaults: bool = False,
) -> None:
    profile_default: Any = argparse.SUPPRESS if suppress_defaults else default_profile_dir()
    page_index_default: Any = argparse.SUPPRESS if suppress_defaults else 0
    page_url_default: Any = argparse.SUPPRESS if suppress_defaults else ""
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=profile_default,
        help="CloakBrowser 持久化 Profile 的绝对路径",
    )
    parser.add_argument(
        "--page-index",
        type=int,
        default=page_index_default,
        help="默认聚焦的浏览器页面序号，从 0 开始",
    )
    parser.add_argument(
        "--page-url-contains",
        default=page_url_default,
        help="优先聚焦 URL 包含此文本的页面",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctrip",
        description="FDE特供携程比价 CLI：登录、登录状态、模糊选店和日期价格采集",
    )
    _add_session_options(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="打开携程并完成手动登录，保存本地会话")
    login.add_argument("--timeout", type=float, default=600)
    login.add_argument("--session-probe-seconds", type=float, default=30)
    login.add_argument("--keep-open", action="store_true", help="登录成功后保持浏览器打开")

    status = subparsers.add_parser("login-status", help="检查当前 Profile 的携程登录状态")
    status.add_argument("--timeout", type=float, default=30)

    search = subparsers.add_parser("search", help="模糊搜索酒店并选择详情页")
    search.add_argument("--keyword", required=True, help="酒店模糊名称")
    search.add_argument("--timeout", type=float, default=45)
    search.add_argument("--select-index", type=int, help="直接选择候选序号，从 1 开始")
    search.add_argument("--list-only", action="store_true", help="只输出候选，不打开详情页")

    price = subparsers.add_parser("price", help="获取指定起始日期的房型价格 JSON")
    price.add_argument("--hotel", help="酒店名称或模糊名称，可与 --detail-url 一起提供")
    price.add_argument("--detail-url", help="酒店详情页 URL；至少提供 --hotel 或 --detail-url")
    price.add_argument("--start-date", required=True, help="入住起始日期 YYYY-MM-DD")
    price.add_argument("--days", type=int, default=1, help="连续采集天数")
    price.add_argument("--nights", type=int, default=1, help="每个入住区间的晚数")
    price.add_argument("--city-id", default=95)
    price.add_argument("--adults", type=int, default=2)
    price.add_argument("--children", type=int, default=0)
    price.add_argument("--rooms", type=int, default=1)
    price.add_argument("--price-mode", choices=("response", "page_xpath"), default="response")
    price.add_argument("--show-all-rooms-xpath", default=DEFAULT_SHOW_ALL_ROOMS_XPATH)
    price.add_argument("--page-price-xpath", default="")
    price.add_argument("--page-room-name-xpath", default="")
    price.add_argument("--page-price-sample-size", type=int, default=0)
    price.add_argument("--page-price-timeout-seconds", type=float, default=15)
    price.add_argument("--api-timeout-seconds", type=float, default=45)
    price.add_argument("--settle-ms", type=int, default=1500)
    price.add_argument("--search-timeout-seconds", type=float, default=45)
    price.add_argument("--output-dir", type=Path, help="可选的绝对 JSON 输出目录")

    collect = subparsers.add_parser("collect", help="按 JSON 配置执行完整批量采集")
    collect.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    collect.add_argument("--login-only", action="store_true")

    subparsers.add_parser("setup", help="验证浏览器组件和当前运行程序")

    for command_parser in (login, status, search, price, collect):
        _add_session_options(command_parser, suppress_defaults=True)

    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.page_index < 0:
        raise SystemExit("--page-index 必须是大于等于 0 的整数")
    if args.command == "search" and args.select_index is not None and args.select_index < 1:
        raise SystemExit("--select-index 必须从 1 开始")
    if args.command != "price":
        return
    if not args.hotel and not args.detail_url:
        raise SystemExit("price 至少需要提供 --hotel 或 --detail-url")
    if args.days < 1 or args.nights < 1:
        raise SystemExit("--days 和 --nights 必须是正整数")
    if args.price_mode == "page_xpath" and not str(args.page_price_xpath).strip():
        raise SystemExit("page_xpath 模式必须提供 --page-price-xpath")
    if args.output_dir is not None and not args.output_dir.expanduser().is_absolute():
        raise SystemExit("--output-dir 必须使用绝对路径")


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str), flush=True)


def run_login(args: argparse.Namespace) -> int:
    with CtripBrowserSession(
        args.profile_dir,
        page_index=args.page_index,
        url_contains=args.page_url_contains,
    ) as session:
        page = ensure_login(
            session.browser,
            session.focus(),
            timeout_seconds=args.timeout,
            session_probe_seconds=args.session_probe_seconds,
        )
        session.focus(page)
        result = login_status(
            session.browser,
            page,
            timeout_seconds=args.timeout,
        )
        result["profile_dir"] = str(session.profile_dir)
        _json_print(result)
        if args.keep_open:
            try:
                input("登录状态已保存。按 Enter 关闭浏览器：")
            except EOFError:
                print(
                    "当前终端没有可等待的输入，登录会话已保存，浏览器正常关闭。",
                    file=sys.stderr,
                    flush=True,
                )
        else:
            print(
                "登录会话已保存，命令正常结束；浏览器将关闭，后续命令会复用本地会话。",
                flush=True,
            )
    return 0


def run_login_status(args: argparse.Namespace) -> int:
    with CtripBrowserSession(
        args.profile_dir,
        page_index=args.page_index,
        url_contains=args.page_url_contains,
    ) as session:
        page = session.goto(HOME_URL)
        result = login_status(
            session.browser,
            page,
            timeout_seconds=args.timeout,
        )
        result["profile_dir"] = str(session.profile_dir)
        _json_print(result)
        return 0 if result["logged_in"] else 2


def run_search(args: argparse.Namespace) -> int:
    with CtripBrowserSession(
        args.profile_dir,
        page_index=args.page_index,
        url_contains=args.page_url_contains,
    ) as session:
        page = ensure_login(session.browser, session.focus())
        if args.list_only:
            _, candidates = search_candidates(
                session.browser,
                page,
                args.keyword,
                timeout_seconds=args.timeout,
            )
            _json_print([public_candidate(candidate) for candidate in candidates])
            return 0

        detail_page, selected, candidates = fuzzy_search_hotel(
            session.browser,
            page,
            args.keyword,
            timeout_seconds=args.timeout,
            index=args.select_index,
        )
        close_other_pages(session.browser, detail_page)
        session.focus(detail_page)
        _json_print(
            {
                "selected": selected,
                "candidates": [public_candidate(candidate) for candidate in candidates],
            }
        )
    return 0


def _price_config(args: argparse.Namespace, hotel_name: str) -> dict[str, Any]:
    config = {
        "hotel_name": hotel_name,
        "city_id": args.city_id,
        "adults": args.adults,
        "children": args.children,
        "rooms": args.rooms,
        "price_mode": args.price_mode,
        "show_all_rooms_xpath": args.show_all_rooms_xpath,
        "page_price_xpath": args.page_price_xpath,
        "page_room_name_xpath": args.page_room_name_xpath,
        "page_price_sample_size": args.page_price_sample_size,
        "page_price_timeout_seconds": args.page_price_timeout_seconds,
        "api_timeout_seconds": args.api_timeout_seconds,
        "settle_ms": args.settle_ms,
    }
    validate_price_config(config)
    return config


def run_price(args: argparse.Namespace) -> int:
    with CtripBrowserSession(
        args.profile_dir,
        page_index=args.page_index,
        url_contains=args.page_url_contains,
    ) as session:
        page = ensure_login(session.browser, session.focus())
        detail_url = args.detail_url
        hotel_name = args.hotel or "hotel"
        if detail_url:
            if not is_valid_detail_url(detail_url):
                raise SystemExit(f"无效的酒店详情页 URL：{detail_url}")
        else:
            cache_path = default_session_root() / DEFAULT_DETAIL_CACHE_NAME
            detail_cache = load_detail_url_cache(cache_path)
            hotel = {"name": args.hotel, "city_id": args.city_id}

            def search_fn(browser: Any, current_page: Any, name: str, *, timeout_seconds: float):
                searched_page, selected, _ = fuzzy_search_hotel(
                    browser,
                    current_page,
                    name,
                    timeout_seconds=timeout_seconds,
                )
                return searched_page, selected["url"]

            page, detail_url, _source = resolve_hotel_detail(
                browser=session.browser,
                page=page,
                hotel=hotel,
                config={"city_id": args.city_id},
                detail_url_cache=detail_cache,
                timeout_seconds=args.search_timeout_seconds,
                search_hotel_fn=search_fn,
            )
            close_other_pages(session.browser, page)
            save_detail_url_cache(cache_path, detail_cache)
            hotel_name = args.hotel

        config = _price_config(args, hotel_name)
        stays = build_stays(
            {
                "start_date": args.start_date,
                "days": args.days,
                "nights": args.nights,
            }
        )
        payloads = [
            collect_one_stay(
                session.focus(page),
                detail_url,
                check_in,
                check_out,
                browser=session.browser,
                config=config,
            )
            for check_in, check_out in stays
        ]

        if args.output_dir is not None:
            output_dir = args.output_dir.expanduser().resolve()
            for payload in payloads:
                output_path = (
                    output_dir
                    / safe_filename(payload["hotel_name"] or "hotel")
                    / f"{payload['check_in']}_{payload['check_out']}.json"
                )
                write_json(output_path, payload)
            print(f"已写入 {len(payloads)} 个日期结果：{output_dir}", flush=True)
        else:
            _json_print(payloads)
    return 0


def run_collect(args: argparse.Namespace) -> int:
    from ctrip_hotel_prices import collect_prices

    config_path = args.config.expanduser().resolve()
    try:
        config = load_config(config_path)
    except ValueError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1
    config["profile_dir"] = str(args.profile_dir.expanduser().resolve())
    return collect_prices(
        config,
        config_dir=config_path.parent,
        login_only=args.login_only,
    )


def run_setup(_args: argparse.Namespace) -> int:
    print("正在准备 CloakBrowser 浏览器组件…", flush=True)
    browser_binary = setup_runtime()
    print(f"环境验证通过：{browser_binary}", flush=True)
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args)
    try:
        if args.command == "login":
            return run_login(args)
        if args.command == "login-status":
            return run_login_status(args)
        if args.command == "search":
            return run_search(args)
        if args.command == "price":
            return run_price(args)
        if args.command == "setup":
            return run_setup(args)
        return run_collect(args)
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
