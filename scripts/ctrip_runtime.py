#!/usr/bin/env python3
"""Resolve paths shared by source runs and compiled customer releases."""

from __future__ import annotations

import os
import platform
import sys
from collections.abc import Mapping
from pathlib import Path


SKILL_DIR_ENV = "CTRIP_SKILL_DIR"
COMPILED_BINARY_NAMES = {"ctrip-agent", "ctrip-agent.exe"}
BUNDLED_BROWSER_PATHS = {
    "darwin": Path("browser/Chromium.app/Contents/MacOS/Chromium"),
    "linux": Path("browser/chrome"),
    "windows": Path("browser/chrome.exe"),
}


def resolve_skill_dir(
    *,
    environ: Mapping[str, str] | None = None,
    executable_path: str | Path | None = None,
    module_path: str | Path | None = None,
) -> Path:
    """Return the customer package root without relying on extracted onefile paths."""

    environment = os.environ if environ is None else environ
    configured = str(environment.get(SKILL_DIR_ENV, "")).strip()
    if configured:
        return Path(configured).expanduser().resolve()

    executable = Path(executable_path or sys.argv[0]).expanduser().resolve()
    if executable.name.lower() in COMPILED_BINARY_NAMES and executable.parent.name == "bin":
        return executable.parent.parent

    source_file = Path(module_path or __file__).expanduser().resolve()
    return source_file.parents[1]


SKILL_DIR = resolve_skill_dir()


def bundled_browser_binary(
    *,
    skill_dir: str | Path | None = None,
    system: str | None = None,
) -> Path | None:
    """Return the browser shipped with a customer package, when present."""

    system_name = (system or platform.system()).lower()
    relative_path = BUNDLED_BROWSER_PATHS.get(system_name)
    if relative_path is None:
        return None
    candidate = Path(skill_dir or SKILL_DIR).expanduser().resolve() / relative_path
    return candidate.resolve() if candidate.is_file() else None


def runtime_dir() -> Path:
    configured = os.environ.get("CTRIP_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return SKILL_DIR / ".runtime"


def cloakbrowser_cache_dir() -> Path:
    configured = os.environ.get("CTRIP_CLOAK_CACHE_DIR") or os.environ.get(
        "CLOAKBROWSER_CACHE_DIR"
    )
    if configured:
        return Path(configured).expanduser().resolve()
    return runtime_dir() / "cloakbrowser"


def default_config_path() -> Path:
    return SKILL_DIR / "ctrip_hotel_config.json"
