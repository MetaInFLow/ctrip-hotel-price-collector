#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  printf '%s\n' "未检测到 Python 3。请先安装 Python 3.12 或更高版本：" >&2
  printf '%s\n' "macOS/Linux：https://www.python.org/downloads/" >&2
  printf '%s\n' "Windows：https://www.python.org/downloads/windows/" >&2
  printf '%s\n' "安装完成后重新运行本脚本。" >&2
  exit 2
fi

PYTHON_VERSION="$($PYTHON_BIN --version 2>&1 || true)"
PYTHON_MAJOR="$(printf '%s\n' "$PYTHON_VERSION" | awk '{split($2, v, "."); print v[1]}')"
PYTHON_MINOR="$(printf '%s\n' "$PYTHON_VERSION" | awk '{split($2, v, "."); print v[2]}')"
if [ "${PYTHON_MAJOR:-0}" -lt 3 ] || { [ "${PYTHON_MAJOR:-0}" -eq 3 ] && [ "${PYTHON_MINOR:-0}" -lt 12 ]; }; then
  printf '%s\n' "检测到的 Python 版本低于 3.12。请升级后重新运行本脚本：" >&2
  printf '%s\n' "https://www.python.org/downloads/" >&2
  exit 2
fi

exec "$PYTHON_BIN" "$SKILL_DIR/scripts/bootstrap_ctrip_hotel_skill.py" "$@"
