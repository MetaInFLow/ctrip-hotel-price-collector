#!/usr/bin/env python3
"""Cross-platform persistent CloakBrowser launcher for Ctrip scripts."""

from __future__ import annotations

import json
import platform
import socket
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen


MACOS_CDP_TIMEOUT_SECONDS = 30.0
MACOS_CDP_CONNECT_TIMEOUT_MS = 15_000


def _set_argument(arguments: list[str], key: str, value: str) -> list[str]:
    """Replace one Chromium flag by key, preserving unrelated flags."""

    filtered = [argument for argument in arguments if argument.split("=", 1)[0] != key]
    filtered.append(value)
    return filtered


def build_macos_open_command(
    app_path: str | Path,
    profile_dir: str | Path,
    cdp_port: int,
    *,
    headless: bool,
    chrome_args: list[str] | None = None,
) -> list[str]:
    """Build an ``open -na`` command that starts one isolated CDP instance."""

    arguments = list(chrome_args or [])
    arguments = _set_argument(
        arguments,
        "--user-data-dir",
        f"--user-data-dir={Path(profile_dir)}",
    )
    arguments = _set_argument(
        arguments,
        "--remote-debugging-port",
        f"--remote-debugging-port={cdp_port}",
    )
    for flag in ("--no-first-run", "--no-default-browser-check"):
        if flag not in arguments:
            arguments.append(flag)
    if headless and not any(argument.startswith("--headless") for argument in arguments):
        arguments.append("--headless=new")
    arguments.append("about:blank")
    return ["open", "-na", str(app_path), "--args", *arguments]


def _find_app_bundle(binary_path: str | Path) -> Path:
    path = Path(binary_path).expanduser().resolve()
    for parent in (path, *path.parents):
        if parent.suffix == ".app":
            return parent
    raise RuntimeError(f"CloakBrowser 二进制不在 macOS .app 包内：{path}")


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _cdp_version(port: int) -> dict[str, Any] | None:
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _wait_for_cdp(port: int, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = _cdp_version(port)
        if payload and payload.get("webSocketDebuggerUrl"):
            return payload
        time.sleep(0.2)
    raise RuntimeError(
        "macOS Launch Services 已发起 Chromium，但 CDP 端口未就绪；"
        "请检查 Chromium 崩溃报告或关闭占用同一 Profile 的浏览器窗口。"
    )


class _ConnectedPersistentContext:
    """Expose a BrowserContext while owning the CDP browser connection."""

    def __init__(self, browser: Any, context: Any, playwright: Any) -> None:
        self._browser = browser
        self._context = context
        self._playwright = playwright
        self._closed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)

    def close(self, *args: Any, **kwargs: Any) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            try:
                browser_cdp = self._browser.new_browser_cdp_session()
                browser_cdp.send("Browser.close")
            except Exception:
                try:
                    self._browser.close()
                except Exception:
                    pass
        finally:
            self._playwright.stop()


def _build_cloak_args(
    *,
    headless: bool,
    args: list[str] | None,
    stealth_args: bool,
    timezone: str | None,
    locale: str | None,
    extension_paths: list[str] | None,
    start_maximized: bool,
) -> list[str]:
    try:
        from cloakbrowser.browser import build_args
    except (ImportError, ModuleNotFoundError):
        return list(args or [])
    return build_args(
        stealth_args,
        list(args or []),
        timezone=timezone,
        locale=locale,
        headless=headless,
        extension_paths=extension_paths,
        start_maximized=start_maximized,
    )


def _launch_macos(
    user_data_dir: str | Path,
    *,
    headless: bool,
    args: list[str] | None,
    stealth_args: bool,
    timezone: str | None,
    locale: str | None,
    extension_paths: list[str] | None,
    start_maximized: bool,
    license_key: str | None,
    browser_version: str | None,
    release_channel: str | None,
) -> _ConnectedPersistentContext:
    from cloakbrowser.download import ensure_binary
    from playwright.sync_api import sync_playwright

    binary_path = ensure_binary(
        license_key=license_key,
        browser_version=browser_version,
        release_channel=release_channel,
    )
    app_path = _find_app_bundle(binary_path)
    profile_path = Path(user_data_dir).expanduser().resolve()
    port = _free_local_port()
    chrome_args = _build_cloak_args(
        headless=headless,
        args=args,
        stealth_args=stealth_args,
        timezone=timezone,
        locale=locale,
        extension_paths=extension_paths,
        start_maximized=start_maximized,
    )
    command = build_macos_open_command(
        app_path,
        profile_path,
        port,
        headless=headless,
        chrome_args=chrome_args,
    )
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"无法通过 macOS Launch Services 启动 Chromium：{exc}") from exc

    _wait_for_cdp(port, MACOS_CDP_TIMEOUT_SECONDS)
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{port}",
            timeout=MACOS_CDP_CONNECT_TIMEOUT_MS,
        )
        contexts = browser.contexts
        if not contexts:
            raise RuntimeError("Chromium 已启动，但没有可用的持久化 BrowserContext")
        return _ConnectedPersistentContext(browser, contexts[0], playwright)
    except Exception:
        playwright.stop()
        raise


def launch_persistent_context(
    user_data_dir: str | Path,
    *,
    headless: bool = True,
    **kwargs: Any,
) -> Any:
    """Launch CloakBrowser persistently, using Launch Services on macOS."""

    if platform.system() != "Darwin":
        from cloakbrowser import launch_persistent_context as cloak_launch

        return cloak_launch(user_data_dir, headless=headless, **kwargs)

    supported = {
        "args",
        "stealth_args",
        "timezone",
        "locale",
        "extension_paths",
        "start_maximized",
        "license_key",
        "browser_version",
        "release_channel",
    }
    unsupported = sorted(set(kwargs) - supported)
    if unsupported:
        raise TypeError(
            "macOS Launch Services 启动器暂不支持参数：" + ", ".join(unsupported)
        )
    return _launch_macos(
        user_data_dir,
        headless=headless,
        args=kwargs.get("args"),
        stealth_args=bool(kwargs.get("stealth_args", True)),
        timezone=kwargs.get("timezone"),
        locale=kwargs.get("locale"),
        extension_paths=kwargs.get("extension_paths"),
        start_maximized=bool(kwargs.get("start_maximized", False)),
        license_key=kwargs.get("license_key"),
        browser_version=kwargs.get("browser_version"),
        release_channel=kwargs.get("release_channel"),
    )


__all__ = ["build_macos_open_command", "launch_persistent_context"]
