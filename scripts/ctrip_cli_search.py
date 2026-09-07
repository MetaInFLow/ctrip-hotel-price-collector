#!/usr/bin/env python3
"""Atomic fuzzy hotel search and candidate selection operations."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ctrip_cli_browser import HOME_URL, browser_pages, focus_page  # noqa: E402
from ctrip_login_guard import require_logged_in  # noqa: E402
from ctrip_hotel_prices import (  # noqa: E402
    HOTEL_SEARCH_BUTTON_XPATH,
    HOTEL_SEARCH_INPUT_XPATH,
    choose_hotel_candidate,
    extract_hotel_candidates,
    is_valid_detail_url,
    wait_for_hotel_candidates,
    wait_for_visible,
)


def search_candidates(
    browser: Any,
    page: Any,
    keyword: str,
    *,
    timeout_seconds: float = 45,
) -> tuple[Any, list[dict[str, Any]]]:
    """Submit one fuzzy keyword and return visible, validated hotel candidates."""

    if not str(keyword).strip():
        raise ValueError("酒店模糊搜索词不能为空")
    page = require_logged_in(browser, page, operation="酒店模糊搜索")
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    page = require_logged_in(browser, page, operation="酒店模糊搜索")
    search_input = wait_for_visible(
        page,
        HOTEL_SEARCH_INPUT_XPATH,
        60,
        "酒店模糊搜索框",
    )
    search_input.fill(keyword)
    search_button = wait_for_visible(
        page,
        HOTEL_SEARCH_BUTTON_XPATH,
        60,
        "携程搜索按钮",
    )
    focus_page(page)
    search_button.click(timeout=5_000)
    page.wait_for_timeout(250)

    for candidate_page in browser_pages(browser):
        candidates = extract_hotel_candidates(candidate_page)
        if candidates:
            return focus_page(candidate_page), candidates

    # Ctrip sometimes closes the result list after a button click. Re-filling
    # the same input reopens the list without changing the query semantics.
    search_input.fill(keyword)
    candidates = wait_for_hotel_candidates(
        page,
        timeout_seconds,
        browser=browser,
    )
    return focus_page(page), candidates


def select_candidate(
    browser: Any,
    page: Any,
    candidates: list[dict[str, Any]],
    *,
    index: int | None = None,
    input_fn: Any = input,
    timeout_seconds: float = 45,
) -> tuple[Any, dict[str, Any]]:
    """Select one 1-based candidate and wait for its detail page."""

    page = require_logged_in(browser, page, operation="酒店候选选择")
    if index is None:
        selected = choose_hotel_candidate(candidates, input_fn=input_fn)
    else:
        if index < 1 or index > len(candidates):
            raise ValueError(f"酒店序号必须在 1 到 {len(candidates)} 之间")
        selected = candidates[index - 1]

    selected_page = focus_page(selected.get("page", page))
    selected["locator"].click(timeout=5_000)
    selected_name = str(selected.get("name", "")).strip()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for candidate_page in browser_pages(browser):
            candidate_page = focus_page(candidate_page)
            candidate_url = str(getattr(candidate_page, "url", ""))
            if is_valid_detail_url(candidate_url):
                return candidate_page, {
                    "name": selected_name,
                    "district": selected.get("district", ""),
                    "url": candidate_url,
                }
        selected_url = str(selected.get("url", "")).strip()
        if selected_url and is_valid_detail_url(selected_url):
            return selected_page, {
                "name": selected_name,
                "district": selected.get("district", ""),
                "url": urljoin(str(getattr(selected_page, "url", "")), selected_url),
            }
        page.wait_for_timeout(500)
    raise TimeoutError(f"等待酒店详情页超时：{selected_name}")


def fuzzy_search_hotel(
    browser: Any,
    page: Any,
    keyword: str,
    *,
    timeout_seconds: float = 45,
    index: int | None = None,
    input_fn: Any = input,
) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    """Search, list, select and open one hotel detail page."""

    result_page, candidates = search_candidates(
        browser,
        page,
        keyword,
        timeout_seconds=timeout_seconds,
    )
    detail_page, selected = select_candidate(
        browser,
        result_page,
        candidates,
        index=index,
        input_fn=input_fn,
        timeout_seconds=timeout_seconds,
    )
    return detail_page, selected, candidates


def public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Remove Playwright handles before a candidate is serialized as JSON."""

    return {
        "name": str(candidate.get("name", "")),
        "type": str(candidate.get("type", "")),
        "district": str(candidate.get("district", "")),
        "url": str(candidate.get("url", "")),
    }


__all__ = [
    "fuzzy_search_hotel",
    "public_candidate",
    "search_candidates",
    "select_candidate",
]
