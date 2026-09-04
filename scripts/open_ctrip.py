#!/usr/bin/env python3
"""Open Ctrip in a visible persistent CloakBrowser window."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ctrip_hotel_prices import (  # noqa: E402
    DEFAULT_PROFILE_NAME,
    close_browser_safely,
    default_session_root,
    require_absolute_path,
)


URL = "https://www.ctrip.com/"


def default_profile_dir() -> Path:
    return default_session_root() / DEFAULT_PROFILE_NAME


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="在共享的持久化 CloakBrowser Profile 中打开携程",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=default_profile_dir(),
        help="CloakBrowser 持久化 Profile 的绝对路径",
    )
    return parser.parse_args(argv)


def main(argv=None, *, launcher=None, input_fn=input) -> int:
    args = parse_args(argv)
    profile_dir = require_absolute_path(args.profile_dir, "profile_dir")
    if launcher is None:
        try:
            from cloakbrowser import launch_persistent_context
        except ModuleNotFoundError:
            print(
                "缺少 CloakBrowser 依赖，请先执行："
                " python3 -m pip install -r requirements-cloak.txt",
                file=sys.stderr,
            )
            return 1
        launcher = launch_persistent_context

    browser = None
    try:
        print(f"正在启动 CloakBrowser 持久化会话：{profile_dir}", flush=True)
        browser = launcher(str(profile_dir), headless=False)
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        print(f"已打开：{page.url}", flush=True)
        print(f"页面标题：{page.title()}", flush=True)
        input_fn("携程已打开。按 Enter 关闭浏览器：")
    except EOFError:
        pass
    except Exception as exc:
        print(f"打开携程失败：{exc}", file=sys.stderr)
        return 1
    finally:
        if browser is not None:
            close_browser_safely(browser)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
