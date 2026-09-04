#!/usr/bin/env python3
"""Create the collector virtual environment on macOS, Windows, or Linux."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REQUIREMENTS_FILE = SKILL_DIR / "requirements-cloak.txt"


def venv_python(venv_dir: Path, *, os_name: str | None = None) -> Path:
    os_name = os_name or os.name
    executable_dir = "Scripts" if os_name == "nt" else "bin"
    executable_name = "python.exe" if os_name == "nt" else "python"
    return venv_dir / executable_dir / executable_name


def resolve_python(value: str) -> str:
    resolved = shutil.which(value)
    if resolved:
        return resolved
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    raise FileNotFoundError(f"找不到 Python：{value}")


def run(command: list[str]) -> None:
    print("执行：" + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="为携程酒店价格采集 Skill 创建跨平台 Python 环境",
    )
    parser.add_argument(
        "--venv-dir",
        type=Path,
        default=Path(os.environ.get("CTRIP_VENV_DIR") or Path.cwd() / ".venv"),
        help="虚拟环境目录，默认为当前目录下的 .venv",
    )
    parser.add_argument(
        "--python",
        default=os.environ.get("PYTHON_BIN") or sys.executable,
        help="创建虚拟环境所用的 Python，可传可执行文件名或绝对路径",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        python_bin = resolve_python(args.python)
        venv_dir = args.venv_dir.expanduser().resolve()
        print(f"使用 Python：{python_bin}", flush=True)
        print(f"创建或复用虚拟环境：{venv_dir}", flush=True)
        run([python_bin, "-m", "venv", str(venv_dir)])

        python_in_venv = venv_python(venv_dir)
        if not python_in_venv.is_file():
            raise RuntimeError(f"虚拟环境创建失败，找不到：{python_in_venv}")

        print("安装 CloakBrowser 与 Excel 依赖", flush=True)
        run(
            [
                str(python_in_venv),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(REQUIREMENTS_FILE),
            ]
        )
        run(
            [
                str(python_in_venv),
                "-c",
                "import cloakbrowser, openpyxl; print('运行时检查通过', openpyxl.__version__)",
            ]
        )
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"部署失败：{exc}", file=sys.stderr)
        return 1

    print("部署完成。", flush=True)
    print(f"运行检查：{python_in_venv} {SKILL_DIR / 'scripts' / 'ctrip_hotel_prices.py'} --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
