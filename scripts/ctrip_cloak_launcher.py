#!/usr/bin/env python3
"""Cross-platform persistent CloakBrowser launcher for Ctrip scripts."""

from __future__ import annotations

import json
import os
import platform
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ctrip_runtime import bundled_browser_binary, cloakbrowser_cache_dir  # noqa: E402

MACOS_CDP_TIMEOUT_SECONDS = 30.0
MACOS_CDP_CONNECT_TIMEOUT_MS = 15_000
PROCESS_CLEANUP_TIMEOUT_SECONDS = 3.0
MACOS_CDP_HOST = "localhost"
def configure_cloakbrowser_cache() -> Path:
    """Use the package-local browser cache unless an operator overrides it."""

    configured = os.environ.get("CLOAKBROWSER_CACHE_DIR")
    cache_dir = (
        Path(configured).expanduser().resolve()
        if configured
        else cloakbrowser_cache_dir()
    )
    os.environ["CLOAKBROWSER_CACHE_DIR"] = str(cache_dir)
    os.environ.setdefault("CLOAKBROWSER_AUTO_UPDATE", "false")
    packaged_browser = bundled_browser_binary()
    if packaged_browser is not None:
        os.environ.setdefault("CLOAKBROWSER_BINARY_PATH", str(packaged_browser))
    return cache_dir


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
        with urlopen(
            f"http://{MACOS_CDP_HOST}:{port}/json/version",
            timeout=1,
        ) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _posix_instance_pids(profile_path: Path, cdp_port: int) -> set[int]:
    """Find Chromium processes that belong to one isolated macOS/Linux run."""

    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return set()

    profile_marker = f"--user-data-dir={profile_path}"
    port_marker = f"--remote-debugging-port={cdp_port}"
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        pid_text, command = fields
        if profile_marker not in command or port_marker not in command:
            continue
        try:
            pids.add(int(pid_text))
        except ValueError:
            continue
    return pids


def _windows_instance_pids(cdp_port: int) -> set[int]:
    """Find the Chromium process listening on one isolated Windows port."""

    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return set()

    port_suffix = f":{cdp_port}"
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP":
            continue
        if not fields[1].endswith(port_suffix):
            continue
        if fields[3].upper() != "LISTENING":
            continue
        try:
            pids.add(int(fields[4]))
        except ValueError:
            continue
    return pids


def _instance_pids(profile_path: Path, cdp_port: int) -> set[int]:
    if os.name == "nt":
        return _windows_instance_pids(cdp_port)
    return _posix_instance_pids(profile_path, cdp_port)


def _cleanup_macos_process(profile_path: Path, cdp_port: int) -> None:
    """Terminate the Chromium tree detached by macOS Launch Services."""

    deadline = time.monotonic() + PROCESS_CLEANUP_TIMEOUT_SECONDS
    pids = _instance_pids(profile_path, cdp_port)
    if os.name == "nt":
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except (OSError, subprocess.SubprocessError):
                continue
        return

    for pid in pids:
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            continue

    while pids and time.monotonic() < deadline:
        time.sleep(0.1)
        pids = _instance_pids(profile_path, cdp_port)

    for pid in pids:
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            continue


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

    def __init__(
        self,
        browser: Any,
        context: Any,
        playwright: Any,
        *,
        profile_path: Path | None = None,
        cdp_port: int | None = None,
    ) -> None:
        self._browser = browser
        self._context = context
        self._playwright = playwright
        self._profile_path = profile_path
        self._cdp_port = cdp_port
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
            try:
                self._playwright.stop()
            finally:
                if self._profile_path is not None and self._cdp_port is not None:
                    _cleanup_macos_process(self._profile_path, self._cdp_port)


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

    playwright = None
    try:
        _wait_for_cdp(port, MACOS_CDP_TIMEOUT_SECONDS)
        playwright = sync_playwright().start()
        browser = playwright.chromium.connect_over_cdp(
            f"http://{MACOS_CDP_HOST}:{port}",
            timeout=MACOS_CDP_CONNECT_TIMEOUT_MS,
        )
        contexts = browser.contexts
        if not contexts:
            raise RuntimeError("Chromium 已启动，但没有可用的持久化 BrowserContext")
        return _ConnectedPersistentContext(
            browser,
            contexts[0],
            playwright,
            profile_path=profile_path,
            cdp_port=port,
        )
    except Exception:
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        _cleanup_macos_process(profile_path, port)
        raise


def launch_persistent_context(
    user_data_dir: str | Path,
    *,
    headless: bool = True,
    **kwargs: Any,
) -> Any:
    """Launch CloakBrowser persistently, using Launch Services on macOS."""

    configure_cloakbrowser_cache()

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


__all__ = [
    "build_macos_open_command",
    "configure_cloakbrowser_cache",
    "launch_persistent_context",
]
