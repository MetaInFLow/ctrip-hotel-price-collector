#!/usr/bin/env python3
"""Atomic Ctrip login and login-status operations."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ctrip_cli_browser import HOME_URL, focus_page  # noqa: E402
from ctrip_login_guard import (  # noqa: E402
    check_login,
    count_ctrip_cookies,
    require_logged_in,
    wait_for_login,
)


def login_status(
    browser: Any,
    page: Any,
    *,
    timeout_seconds: float = 0,
) -> dict[str, Any]:
    """Inspect one focused page and return a value-only login status payload."""

    page = focus_page(page)
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    status = check_login(browser, page)
    while (
        not status["logged_in"]
        and not status["login_visible"]
        and time.monotonic() < deadline
    ):
        page.wait_for_timeout(250)
        status = check_login(browser, page)
    return {
        "logged_in": status["logged_in"],
        "orders_visible": status["orders_visible"],
        "login_visible": status["login_visible"],
        "signals_readable": status["signals_readable"],
        "cookie_count": status["cookie_count"],
        "url": status["url"],
    }


def ensure_login(
    browser: Any,
    page: Any,
    *,
    timeout_seconds: float = 600,
    session_probe_seconds: float = 30,
) -> Any:
    """Navigate to Ctrip, reuse the session, or wait for manual login."""

    page = focus_page(page)
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    page = wait_for_login(
        browser,
        page,
        timeout_seconds,
        session_probe_seconds=session_probe_seconds,
        has_persisted_cookies=count_ctrip_cookies(browser) > 0,
    )
    return require_logged_in(browser, page, operation="登录后的后续操作")


__all__ = ["ensure_login", "login_status"]
