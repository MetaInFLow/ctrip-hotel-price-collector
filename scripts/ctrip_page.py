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


__all__ = ["browser_pages", "focus_page"]
