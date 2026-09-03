#!/usr/bin/env python3
"""Open Ctrip in a visible CloakBrowser window."""

from __future__ import annotations

import sys


URL = "https://www.ctrip.com/"


def main() -> int:
    try:
        from cloakbrowser import launch
    except ModuleNotFoundError:
        print(
            "缺少 CloakBrowser 依赖，请先执行："
            " python3 -m pip install -r requirements-cloak.txt",
            file=sys.stderr,
        )
        return 1

    browser = None
    try:
        print("正在启动 CloakBrowser...", flush=True)
        browser = launch(headless=False)
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        print(f"已打开：{page.url}", flush=True)
        print(f"页面标题：{page.title()}", flush=True)
        input("携程已打开。按 Enter 关闭浏览器：")
    except EOFError:
        pass
    except Exception as exc:
        print(f"打开携程失败：{exc}", file=sys.stderr)
        return 1
    finally:
        if browser is not None:
            browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
