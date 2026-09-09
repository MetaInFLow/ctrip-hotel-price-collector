#!/usr/bin/env python3
"""清理携程酒店价格采集技能的本机运行环境。

默认只预览待删除路径。实际执行必须显式传入 --yes。
脚本保留技能源码、说明、依赖清单和测试文件，不触碰 ~/.codex 或其他工作台。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


SKILL_NAME = "ctrip-hotel-price-collector"
SKILL_DIR = Path(__file__).resolve().parents[1]
SKILLS_ROOT = SKILL_DIR.parent


def default_runtime_paths() -> list[Path]:
    """返回不同平台下该技能可能使用的运行状态目录。"""
    home = Path.home()
    paths = [
        SKILL_DIR / ".runtime",
        SKILL_DIR / ".venv",
        SKILL_DIR / ".pytest_cache",
        SKILL_DIR / "__pycache__",
        SKILL_DIR / "scripts" / "__pycache__",
        SKILL_DIR / "tests" / "__pycache__",
        home / "Library" / "Application Support" / SKILL_NAME,
        home / "Library" / "Caches" / SKILL_NAME,
        home / ".local" / "state" / SKILL_NAME,
        home / ".cache" / SKILL_NAME,
    ]

    if os.name == "nt":
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")
        )
        paths.extend(
            [
                local_app_data / SKILL_NAME,
                home / "AppData" / "Local" / SKILL_NAME,
            ]
        )
    return _deduplicate(paths)


def backup_paths() -> list[Path]:
    return sorted(
        path
        for path in SKILLS_ROOT.glob(f"{SKILL_NAME}.backup-*")
        if path.is_dir() or path.is_symlink()
    )


def _deduplicate(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        resolved = path.expanduser()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def _is_allowed_target(path: Path) -> bool:
    """限制删除范围，避免参数或环境变量导致越界删除。"""
    path = path.expanduser()
    if path in set(default_runtime_paths()):
        return True
    return (
        path.parent == SKILLS_ROOT
        and path.name.startswith(f"{SKILL_NAME}.backup-")
    )


def _describe(path: Path) -> str:
    if path.is_symlink():
        return "符号链接"
    if path.is_dir():
        try:
            size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
            return f"目录，约 {size / 1024 / 1024:.1f} MB"
        except OSError:
            return "目录"
    if path.is_file():
        try:
            return f"文件，{path.stat().st_size} 字节"
        except OSError:
            return "文件"
    return "不存在"


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="清理携程酒店价格采集技能的本机运行环境，默认仅预览。",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行删除；不传时只显示待删除路径。",
    )
    parser.add_argument(
        "--include-backups",
        action="store_true",
        help="同时删除技能目录旁的历史备份目录。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets = default_runtime_paths()
    if args.include_backups:
        targets.extend(backup_paths())
    targets = _deduplicate(targets)

    invalid = [path for path in targets if not _is_allowed_target(path)]
    if invalid:
        print("拒绝执行：发现不在白名单内的删除目标：", file=sys.stderr)
        for path in invalid:
            print(f"  {path}", file=sys.stderr)
        return 2

    existing = [path for path in targets if path.exists() or path.is_symlink()]
    print(f"技能目录：{SKILL_DIR}")
    if not existing:
        print("未发现需要清理的本地运行状态。")
        return 0

    print("待清理路径：")
    for path in existing:
        print(f"  - {path}（{_describe(path)}）")

    if not args.yes:
        print("\n当前为预览模式；确认删除请追加 --yes。")
        return 0

    failures: list[tuple[Path, Exception]] = []
    for path in existing:
        try:
            remove_path(path)
            print(f"已删除：{path}")
        except OSError as exc:
            failures.append((path, exc))

    if failures:
        print("\n以下路径删除失败：", file=sys.stderr)
        for path, exc in failures:
            print(f"  {path}: {exc}", file=sys.stderr)
        return 1

    print("\n清理完成：技能源码已保留，运行环境和本地状态已清除。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
