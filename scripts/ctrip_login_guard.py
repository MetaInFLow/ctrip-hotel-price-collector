#!/usr/bin/env python3
"""Shared, fail-closed login checks for every Ctrip page operation."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ctrip_page import focus_page  # noqa: E402


HOME_URL = "https://www.ctrip.com/"
CTRIP_SESSION_URLS = ["https://www.ctrip.com/", "https://hotels.ctrip.com/"]
LOGIN_XPATH = "xpath=//span[normalize-space()='登录']"
ORDERS_XPATH = "xpath=//*[normalize-space()='我的订单']"


class LoginRequiredError(RuntimeError):
    """Raised when a Ctrip operation is attempted without a verified session."""


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


def _read_visibility(page: Any, selector: str) -> tuple[bool, bool]:
    """Return ``(visible, readable)`` for one login signal."""

    try:
        locator = page.locator(selector)
        count = locator.count()
    except Exception:
        return False, False

    for index in range(count):
        try:
            if locator.nth(index).is_visible():
                return True, True
        except Exception:
            return False, False
    return False, True


def count_ctrip_cookies(browser: Any) -> int:
    """Return only the number of Ctrip cookies; never expose cookie values."""

    cookie_reader = getattr(browser, "cookies", None)
    if not callable(cookie_reader):
        return 0
    try:
        return len(cookie_reader(CTRIP_SESSION_URLS))
    except Exception:
        return 0


def check_login(browser: Any, page: Any) -> dict[str, Any]:
    """Check login markers on this focused page and return diagnostic metadata.

    Ctrip renders a public “我的订单” navigation item even when logged out, so
    that marker is accepted only when the visible “登录” trigger is absent.
    Other tabs are deliberately ignored.
    """

    page = focus_page(page)
    orders_visible, orders_readable = _read_visibility(page, ORDERS_XPATH)
    login_visible, login_readable = _read_visibility(page, LOGIN_XPATH)
    signals_readable = orders_readable and login_readable

    return {
        "logged_in": signals_readable and orders_visible and not login_visible,
        "orders_visible": orders_visible,
        "login_visible": login_visible,
        "signals_readable": signals_readable,
        "cookie_count": count_ctrip_cookies(browser),
        "url": str(getattr(page, "url", "")),
    }


def find_logged_in_page(browser: Any, page: Any) -> Any | None:
    """Return the supplied page only when that page passes ``check_login``."""

    return page if check_login(browser, page)["logged_in"] else None


def require_logged_in(
    browser: Any,
    page: Any,
    *,
    operation: str = "携程操作",
    navigate_to_home: bool = False,
    home_url: str = HOME_URL,
) -> Any:
    """Fail closed unless the operation's page has a verified login state.

    ``navigate_to_home`` is available for callers whose current page does not
    contain the shared navigation markers. It returns the navigated page after
    checking it, so callers must use the returned value when opting in.
    """

    page = focus_page(page)
    status = check_login(browser, page)
    if not status["logged_in"] and navigate_to_home:
        page.goto(home_url, wait_until="domcontentloaded", timeout=60_000)
        page = focus_page(page)
        status = check_login(browser, page)

    if not status["logged_in"]:
        raise LoginRequiredError(
            f"{operation}必须在登录状态下执行，请先运行 login 完成携程登录。"
        )
    return page


def wait_for_login(
    browser: Any,
    page: Any,
    timeout_seconds: float,
    *,
    session_probe_seconds: float = 15,
    has_persisted_cookies: bool = False,
) -> Any:
    """Reuse a verified session or wait for the user to finish manual login."""

    del has_persisted_cookies
    page = focus_page(page)
    timeout_seconds = float(timeout_seconds)
    session_probe_seconds = max(0.0, float(session_probe_seconds))
    probe_deadline = time.monotonic() + min(timeout_seconds, session_probe_seconds)
    logged_in_since: float | None = None
    login_visible_since: float | None = None

    while time.monotonic() < probe_deadline:
        now = time.monotonic()
        status = check_login(browser, page)
        if status["logged_in"]:
            logged_in_since = logged_in_since or now
            if now - logged_in_since >= 1:
                print(
                    "已通过本地会话检测到“我的订单”且“登录”已消失，直接使用已登录状态。",
                    flush=True,
                )
                return page
        else:
            logged_in_since = None

        if status["login_visible"]:
            login_visible_since = login_visible_since or now
            if now - login_visible_since >= 2:
                break
        else:
            login_visible_since = None
        page.wait_for_timeout(500)

    status = check_login(browser, page)
    if status["logged_in"]:
        print("已检测到已登录状态。", flush=True)
        return page

    login_button = _first_visible(page.locator(LOGIN_XPATH))
    if login_button is None:
        raise LoginRequiredError("找不到登录入口，也未检测到已登录状态。")

    page = focus_page(page)
    login_button.click()
    print(
        "请在 CloakBrowser 窗口中手动登录你自己的携程账号，脚本会自动等待。",
        flush=True,
    )

    deadline = time.monotonic() + timeout_seconds
    next_notice = time.monotonic() + 10
    logged_in_since = None
    while time.monotonic() < deadline:
        now = time.monotonic()
        status = check_login(browser, page)
        if status["logged_in"]:
            logged_in_since = logged_in_since or now
            if now - logged_in_since >= 1:
                print("已检测到“我的订单”且“登录”已消失，登录成功。", flush=True)
                return page
        else:
            logged_in_since = None

        if now >= next_notice:
            remaining = max(0, int(deadline - now))
            print(f"仍在等待登录完成，剩余约 {remaining} 秒。", flush=True)
            next_notice = now + 10
        page.wait_for_timeout(1000)

    raise LoginRequiredError(
        f"等待登录超时（{timeout_seconds:g} 秒），未发现有效的已登录状态。"
    )


__all__ = [
    "CTRIP_SESSION_URLS",
    "HOME_URL",
    "LOGIN_XPATH",
    "LoginRequiredError",
    "ORDERS_XPATH",
    "check_login",
    "count_ctrip_cookies",
    "find_logged_in_page",
    "require_logged_in",
    "wait_for_login",
]
