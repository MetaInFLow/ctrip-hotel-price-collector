#!/usr/bin/env python3
"""Compile and assemble a source-free customer release."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_NAME = "ctrip-hotel-price-collector"
FORBIDDEN_SUFFIXES = {".py", ".pyc", ".pyo", ".whl"}
FORBIDDEN_PARTS = {".git", "tests", "tools", "__pycache__", ".venv", ".runtime"}
CUSTOMER_FILES = (
    "README.md",
    "SKILL.md",
    "ctrip_hotel_config.json",
    "THIRD_PARTY_NOTICES.txt",
    "agents/openai.yaml",
)
RUNTIME_DISTRIBUTIONS = ("cloakbrowser", "playwright", "openpyxl", "socksio")


def target_id(system: str | None = None, machine: str | None = None) -> str:
    system_name = (system or platform.system()).lower()
    architecture = (machine or platform.machine()).lower()
    architecture_aliases = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
    }
    architecture = architecture_aliases.get(architecture, architecture)
    operating_systems = {"darwin": "macos", "windows": "windows", "linux": "linux"}
    if system_name not in operating_systems or architecture not in {"arm64", "x64"}:
        raise RuntimeError(f"不支持的构建平台：{system_name}/{architecture}")
    return f"{operating_systems[system_name]}-{architecture}"


def executable_name(target: str) -> str:
    return "ctrip-agent.exe" if target.startswith("windows-") else "ctrip-agent"


def browser_binary_relative_path(target: str) -> PurePosixPath:
    if target.startswith("macos-"):
        return PurePosixPath("browser/Chromium.app/Contents/MacOS/Chromium")
    if target.startswith("windows-"):
        return PurePosixPath("browser/chrome.exe")
    if target.startswith("linux-"):
        return PurePosixPath("browser/chrome")
    raise RuntimeError(f"不支持的客户包目标：{target}")


def _package_dir(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    if spec is None or spec.origin is None:
        raise RuntimeError(f"构建环境缺少依赖：{package}")
    return Path(spec.origin).resolve().parent


def nuitka_command(output_dir: Path, target: str) -> list[str]:
    _package_dir("playwright")
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--mode=onefile",
        "--assume-yes-for-downloads",
        "--remove-output",
        "--python-flag=-OO",
        f"--output-dir={output_dir}",
        f"--output-filename={executable_name(target)}",
        "--include-package=cloakbrowser",
        "--include-package=playwright.sync_api",
        "--include-package=playwright._impl",
        "--include-package=openpyxl",
        "--include-package=socksio",
        str(PROJECT_ROOT / "scripts" / "ctrip_cli.py"),
    ]
    return command


def compile_runner(output_dir: Path, target: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(nuitka_command(output_dir, target), cwd=PROJECT_ROOT, check=True)
    binary = output_dir / executable_name(target)
    if not binary.is_file():
        raise RuntimeError(f"构建完成后未找到运行程序：{binary}")
    return binary


def resolve_official_browser_bundle(target: str) -> Path:
    """Return a verified CloakBrowser cache directory for this build target."""

    current_target = target_id()
    if target != current_target:
        raise RuntimeError(f"浏览器组件只能在目标平台构建：{target} != {current_target}")
    inherited_overrides = [
        name
        for name in ("CLOAKBROWSER_BINARY_PATH", "CLOAKBROWSER_LICENSE_KEY")
        if os.environ.get(name)
    ]
    if inherited_overrides:
        raise RuntimeError(
            "构建客户包前请清除环境变量：" + ", ".join(inherited_overrides)
        )

    from cloakbrowser.config import (
        get_binary_dir,
        get_binary_path,
        get_chromium_version,
    )
    from cloakbrowser.download import ensure_binary

    version = get_chromium_version()
    expected_binary = Path(get_binary_path(version)).expanduser().resolve()
    actual_binary = Path(
        ensure_binary(browser_version=version)
    ).expanduser().resolve()
    if actual_binary != expected_binary:
        raise RuntimeError("构建获取到了非官方缓存的浏览器组件")
    if not actual_binary.is_file() or not os.access(actual_binary, os.X_OK):
        raise RuntimeError(f"浏览器组件不完整或不可执行：{actual_binary}")

    source_root = Path(get_binary_dir(version)).expanduser().resolve()
    expected_relative = Path(*browser_binary_relative_path(target).parts[1:])
    if actual_binary.relative_to(source_root) != expected_relative:
        raise RuntimeError(f"浏览器组件目录结构不符合预期：{source_root}")
    return source_root


def _copy_customer_files(stage_root: Path) -> None:
    for relative_name in CUSTOMER_FILES:
        source = PROJECT_ROOT / relative_name
        destination = stage_root / relative_name
        if not source.is_file():
            raise RuntimeError(f"发行文件缺失：{source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _copy_runtime_licenses(stage_root: Path) -> None:
    license_root = stage_root / "licenses"
    for distribution_name in RUNTIME_DISTRIBUTIONS:
        distribution = importlib.metadata.distribution(distribution_name)
        candidates = [
            item
            for item in distribution.files or []
            if item.name.lower() in {"license", "licence", "license.rst", "licence.rst"}
        ]
        if not candidates:
            raise RuntimeError(f"未找到第三方许可证：{distribution_name}")
        source = Path(distribution.locate_file(candidates[0]))
        license_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, license_root / f"{distribution_name}-{source.name}")


def _copy_browser_bundle(browser_bundle: Path, stage_root: Path) -> None:
    source = browser_bundle.expanduser().resolve()
    if not source.is_dir():
        raise RuntimeError(f"浏览器组件目录不存在：{source}")
    shutil.copytree(source, stage_root / "browser", symlinks=True)


def stage_release(
    binary: Path,
    stage_root: Path,
    target: str,
    *,
    browser_bundle: Path | None = None,
) -> Path:
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True)
    _copy_customer_files(stage_root)
    _copy_runtime_licenses(stage_root)
    _copy_browser_bundle(
        browser_bundle or resolve_official_browser_bundle(target),
        stage_root,
    )

    destination_binary = stage_root / "bin" / executable_name(target)
    destination_binary.parent.mkdir(parents=True)
    shutil.copy2(binary, destination_binary)
    destination_binary.chmod(destination_binary.stat().st_mode | stat.S_IXUSR)

    installer_name = "install.cmd" if target.startswith("windows-") else "install.sh"
    installer = stage_root / installer_name
    shutil.copy2(PROJECT_ROOT / "packaging" / installer_name, installer)
    if installer.suffix == ".sh":
        installer.chmod(installer.stat().st_mode | stat.S_IXUSR)
    validate_release_tree(stage_root, target)
    return stage_root


def validate_release_members(members: Sequence[str], target: str) -> None:
    normalized = [PurePosixPath(member) for member in members if not member.endswith("/")]
    for member in normalized:
        if member.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise RuntimeError(f"客户包含有源码或 Python 中间文件：{member}")
        if FORBIDDEN_PARTS.intersection(member.parts):
            raise RuntimeError(f"客户包含有开发目录：{member}")
        if member.name.startswith("requirements-"):
            raise RuntimeError(f"客户包含有开发依赖清单：{member}")

    required = {
        PurePosixPath("README.md"),
        PurePosixPath("SKILL.md"),
        PurePosixPath("ctrip_hotel_config.json"),
        PurePosixPath("bin") / executable_name(target),
        browser_binary_relative_path(target),
        PurePosixPath("install.cmd" if target.startswith("windows-") else "install.sh"),
    }
    missing = required.difference(normalized)
    if missing:
        raise RuntimeError(f"客户包缺少必需文件：{sorted(map(str, missing))}")


def validate_release_tree(stage_root: Path, target: str) -> None:
    members = [
        path.relative_to(stage_root).as_posix()
        for path in stage_root.rglob("*")
        if path.is_file() or path.is_symlink()
    ]
    validate_release_members(members, target)


def _write_zip_entry(
    archive: zipfile.ZipFile,
    path: Path,
    archive_name: str,
) -> None:
    if not path.is_symlink():
        archive.write(path, archive_name)
        return

    info = zipfile.ZipInfo(archive_name)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive.writestr(info, os.readlink(path))


def create_zip(stage_root: Path, archive_path: Path, target: str) -> Path:
    validate_release_tree(stage_root, target)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path.unlink()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage_root.rglob("*")):
            if path.is_file() or path.is_symlink():
                archive_name = (
                    Path(PRODUCT_NAME) / path.relative_to(stage_root)
                ).as_posix()
                _write_zip_entry(archive, path, archive_name)

    with zipfile.ZipFile(archive_path) as archive:
        prefix = f"{PRODUCT_NAME}/"
        members = [name.removeprefix(prefix) for name in archive.namelist() if name.startswith(prefix)]
        validate_release_members(members, target)
        bad_entry = archive.testzip()
        if bad_entry:
            raise RuntimeError(f"ZIP 校验失败：{bad_entry}")
    return archive_path


def git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建不含 Python 源码的客户发行包")
    parser.add_argument("--binary", type=Path, help="跳过编译，封装已有的本平台运行程序")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "release")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    target = target_id()
    build_root = PROJECT_ROOT / "build" / target
    binary = args.binary.resolve() if args.binary else compile_runner(build_root, target)
    if not binary.is_file():
        raise SystemExit(f"找不到待封装的运行程序：{binary}")

    release_root = args.output_dir.resolve()
    stage_root = release_root / f"{PRODUCT_NAME}-{target}"
    browser_bundle = resolve_official_browser_bundle(target)
    stage_release(binary, stage_root, target, browser_bundle=browser_bundle)
    archive_name = (
        f"{PRODUCT_NAME}-beta-{date.today():%Y%m%d}-{git_revision()}-{target}.zip"
    )
    archive_path = create_zip(stage_root, release_root / archive_name, target)
    result = {
        "target": target,
        "archive": str(archive_path),
        "binary": str(stage_root / "bin" / executable_name(target)),
        "browser": str(stage_root / browser_binary_relative_path(target)),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
