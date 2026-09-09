#!/usr/bin/env python3
"""Shared page-selection primitives for all Ctrip script entrypoints."""

from __future__ import annotations

from typing import Any


def focus_page(page: Any) -> Any:
    """Activate one tab and request DOM focus without requiring OS focus."""

    bring_to_front = getattr(page, "bring_to_front", None)
    if callable(bring_to_front):
        try:
            bring_to_front()
        except Exception:
            pass

    evaluate = getattr(page, "evaluate", None)
    if callable(evaluate):
        try:
            evaluate("window.focus()")
        except Exception:
            pass
    return page


def browser_pages(browser: Any) -> list[Any]:
    """Return pages from either a BrowserContext or a Browser handle."""

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
    return pages


def close_other_pages(browser: Any, selected_page: Any) -> int:
    """Close all open tabs except the page that owns the next operation."""

    closed_count = 0
    for page in browser_pages(browser):
        if page is selected_page:
            continue
        try:
            page.close()
        except Exception:
            continue
        closed_count += 1
    return closed_count


__all__ = ["browser_pages", "close_other_pages", "focus_page"]
