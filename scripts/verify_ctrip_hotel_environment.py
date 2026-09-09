#!/usr/bin/env python3
"""Verify the managed runtime before handing the collector to a customer."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlparse


SKILL_DIR = Path(__file__).resolve().parents[1]
PROXY_ENVIRONMENT_VARIABLES = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)


def invalid_proxy_environment_variable() -> str | None:
    """Return the name of a malformed proxy variable without exposing its value."""

    for name in PROXY_ENVIRONMENT_VARIABLES:
        value = os.environ.get(name)
        if not value:
            continue
        try:
            parsed = urlparse(value)
            _ = parsed.port
        except ValueError:
            return name
        if parsed.scheme not in {"http", "https", "socks5", "socks5h"}:
            return name
        if not parsed.hostname:
            return name

    try:
        import httpx

        client = httpx.Client()
        client.close()
    except Exception:
        if os.environ.get("no_proxy"):
            return "no_proxy"
        if os.environ.get("NO_PROXY"):
            return "NO_PROXY"
        return "代理配置"
    return None


def verify_environment(
    skill_dir: Path,
    cache_dir: Path,
    *,
    ensure_binary_fn: Callable[[], str] | None = None,
    run_command: Callable[..., object] = subprocess.run,
) -> Path:
    """Download and validate the browser binary and the collector command."""

    skill_dir = Path(skill_dir).expanduser().resolve()
    cache_dir = Path(cache_dir).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CLOAKBROWSER_CACHE_DIR"] = str(cache_dir)
    os.environ.setdefault("CLOAKBROWSER_AUTO_UPDATE", "false")

    invalid_proxy = invalid_proxy_environment_variable()
    if invalid_proxy:
        raise RuntimeError(
            f"代理环境变量 {invalid_proxy} 的地址格式无效。"
            "请修正系统代理，或清除该变量后重新运行安装。"
        )

    try:
        import cloakbrowser  # noqa: F401
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(f"缺少已锁定的运行依赖：{exc.name}") from exc

    if ensure_binary_fn is None:
        from cloakbrowser.download import ensure_binary

        ensure_binary_fn = ensure_binary

    browser_binary = Path(ensure_binary_fn()).expanduser().resolve()
    if not browser_binary.is_file():
        raise RuntimeError(f"CloakBrowser 浏览器文件不存在：{browser_binary}")

    run_command(
        [sys.executable, "-m", "cloakbrowser", "doctor", "--quick"],
        check=True,
    )

    cli_script = skill_dir / "scripts" / "ctrip_cli.py"
    if not cli_script.is_file():
        raise RuntimeError(f"找不到携程采集入口：{cli_script}")
    run_command([sys.executable, str(cli_script), "--help"], check=True)
    return browser_binary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证携程采集 Skill 的本地运行环境")
    parser.add_argument("--skill-dir", type=Path, default=SKILL_DIR)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=SKILL_DIR / ".runtime" / "cloakbrowser",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        browser_binary = verify_environment(args.skill_dir, args.cache_dir)
    except Exception as exc:
        print(f"运行时检查未通过：{exc}", file=sys.stderr)
        return 1

    print(f"运行时检查通过：{browser_binary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
