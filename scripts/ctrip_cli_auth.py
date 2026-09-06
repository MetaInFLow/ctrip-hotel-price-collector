#!/usr/bin/env python3
"""Atomic Ctrip login and login-status operations."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ctrip_cli_browser import HOME_URL, focus_page  # noqa: E402
from ctrip_hotel_prices import (  # noqa: E402
    count_ctrip_cookies,
    find_logged_in_page,
    wait_for_login,
)


def login_status(browser: Any, page: Any) -> dict[str, Any]:
    """Inspect one focused page and return a value-only login status payload."""

    page = focus_page(page)
    logged_in_page = find_logged_in_page(browser, page)
    return {
        "logged_in": logged_in_page is not None,
        "cookie_count": count_ctrip_cookies(browser),
        "url": str(getattr(logged_in_page or page, "url", "")),
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
    return wait_for_login(
        browser,
        page,
        timeout_seconds,
        session_probe_seconds=session_probe_seconds,
        has_persisted_cookies=count_ctrip_cookies(browser) > 0,
    )


__all__ = ["ensure_login", "login_status"]
