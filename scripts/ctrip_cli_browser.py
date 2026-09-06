#!/usr/bin/env python3
"""Atomic persistent CloakBrowser session and page-focus primitives."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ctrip_hotel_prices import (  # noqa: E402
    DEFAULT_PROFILE_NAME,
    close_browser_safely,
    default_session_root,
    require_absolute_path,
)
from ctrip_page import browser_pages, focus_page  # noqa: E402


HOME_URL = "https://www.ctrip.com/"


def select_page(
    browser: Any,
    *,
    page_index: int = 0,
    url_contains: str = "",
) -> Any:
    """Select one page deterministically and fail on an invalid explicit index."""

    pages = browser_pages(browser)
    if url_contains:
        for page in pages:
            if url_contains in str(getattr(page, "url", "")):
                return focus_page(page)

    if not pages:
        return focus_page(browser.new_page())
    if page_index < 0 or page_index >= len(pages):
        urls = ", ".join(str(getattr(page, "url", "")) for page in pages)
        raise IndexError(
            f"page_index 超出范围：{page_index}；当前页面数量 {len(pages)}；URL：{urls}"
        )
    return focus_page(pages[page_index])


class CtripBrowserSession:
    """One visible persistent browser session with an explicit focused page."""

    def __init__(
        self,
        profile_dir: Path | str | None = None,
        *,
        page_index: int = 0,
        url_contains: str = "",
        launcher: Callable[..., Any] | None = None,
    ) -> None:
        default_path = default_session_root() / DEFAULT_PROFILE_NAME
        self.profile_dir = require_absolute_path(
            profile_dir or default_path,
            "profile_dir",
        )
        self.page_index = page_index
        self.url_contains = url_contains
        self.launcher = launcher
        self.browser: Any | None = None
        self.page: Any | None = None

    def open(self) -> "CtripBrowserSession":
        if self.browser is not None:
            return self
        launcher = self.launcher
        if launcher is None:
            try:
                from ctrip_cloak_launcher import launch_persistent_context
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "缺少 CloakBrowser 依赖，请先执行新机部署脚本。"
                ) from exc
            launcher = launch_persistent_context
        try:
            self.browser = launcher(str(self.profile_dir), headless=False)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "缺少 CloakBrowser 依赖，请先执行新机部署脚本。"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                "CloakBrowser 启动失败，持久化 Profile 可能正被另一个浏览器实例占用："
                f"{self.profile_dir}。请先关闭使用该 Profile 的浏览器窗口，"
                "或传入另一个绝对路径的 --profile-dir；不要删除原 Profile。"
            ) from exc
        self.page = select_page(
            self.browser,
            page_index=self.page_index,
            url_contains=self.url_contains,
        )
        return self

    def focus(self, page: Any | None = None) -> Any:
        if self.browser is None:
            self.open()
        selected = page or self.page
        if selected is None:
            raise RuntimeError("浏览器已启动但没有可用页面")
        self.page = focus_page(selected)
        return self.page

    def goto(self, url: str, *, wait_until: str = "domcontentloaded", timeout: int = 60_000) -> Any:
        page = self.focus()
        page.goto(url, wait_until=wait_until, timeout=timeout)
        return page

    def close(self) -> None:
        if self.browser is not None:
            close_browser_safely(self.browser)
            self.browser = None
            self.page = None

    def __enter__(self) -> "CtripBrowserSession":
        return self.open()

    def __exit__(self, _exc_type: Any, _exc_value: Any, _traceback: Any) -> None:
        self.close()


__all__ = [
    "CtripBrowserSession",
    "HOME_URL",
    "browser_pages",
    "focus_page",
    "select_page",
]
