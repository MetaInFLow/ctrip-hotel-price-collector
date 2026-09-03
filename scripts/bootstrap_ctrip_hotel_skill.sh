#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$SKILL_DIR/scripts"
VENV_DIR="${CTRIP_VENV_DIR:-$PWD/.venv}"
NODE_MODULES_DIR="${CTRIP_NODE_MODULES:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
NODE_BIN="${CTRIP_NODE:-node}"

usage() {
  cat <<'EOF'
用法：
  bootstrap_ctrip_hotel_skill.sh [选项]

选项：
  --venv-dir PATH       Python 虚拟环境目录，默认是当前目录/.venv
  --node-modules PATH   包含 @oai/artifact-tool 的 Node.js node_modules 目录（可选，旧 Excel 运行时）
  --python PATH         Python 可执行文件，默认使用 python3
  --node PATH            Node.js 可执行文件，默认使用 node
  -h, --help            显示帮助

也可以使用环境变量：CTRIP_VENV_DIR、CTRIP_NODE_MODULES、PYTHON_BIN、CTRIP_NODE。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv-dir)
      [[ $# -ge 2 ]] || { echo "--venv-dir 缺少参数" >&2; exit 2; }
      VENV_DIR="$2"
      shift 2
      ;;
    --node-modules)
      [[ $# -ge 2 ]] || { echo "--node-modules 缺少参数" >&2; exit 2; }
      NODE_MODULES_DIR="$2"
      shift 2
      ;;
    --python)
      [[ $# -ge 2 ]] || { echo "--python 缺少参数" >&2; exit 2; }
      PYTHON_BIN="$2"
      shift 2
      ;;
    --node)
      [[ $# -ge 2 ]] || { echo "--node 缺少参数" >&2; exit 2; }
      NODE_BIN="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "找不到 Python：$PYTHON_BIN。请先安装 Python 3。" >&2
  exit 1
fi

echo "创建或复用 Python 虚拟环境：$VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
VENV_PYTHON="$VENV_DIR/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "虚拟环境创建失败，找不到：$VENV_PYTHON" >&2
  exit 1
fi

echo "安装 CloakBrowser 依赖"
"$VENV_PYTHON" -m pip install -r "$SKILL_DIR/requirements-cloak.txt"

LINK_PATH="$SCRIPT_DIR/node_modules"
if [[ -n "$NODE_MODULES_DIR" ]]; then
  if ! command -v "$NODE_BIN" >/dev/null 2>&1; then
    echo "找不到 Node.js：$NODE_BIN。请先安装 Node.js 或省略 --node-modules。" >&2
    exit 1
  fi
  if [[ ! -d "$NODE_MODULES_DIR/@oai/artifact-tool" ]]; then
    echo "--node-modules 目录中缺少 @oai/artifact-tool：$NODE_MODULES_DIR" >&2
    exit 1
  fi
  if [[ -e "$LINK_PATH" && ! -L "$LINK_PATH" ]]; then
    echo "目标已存在且不是符号链接，无法安全替换：$LINK_PATH" >&2
    exit 1
  fi
  ln -sfn "$NODE_MODULES_DIR" "$LINK_PATH"

  echo "检查旧 Excel 运行时（@oai/artifact-tool，可选）"
  (
    cd "$SCRIPT_DIR"
    "$NODE_BIN" --input-type=module -e 'import "@oai/artifact-tool"; console.log("artifact-tool-ok")'
  )
fi

echo "检查 Excel 运行时（openpyxl，默认）"
"$VENV_PYTHON" -c 'import openpyxl; print("openpyxl-ok", openpyxl.__version__)'

echo "部署完成。"
echo "运行检查：$VENV_PYTHON $SCRIPT_DIR/ctrip_hotel_prices.py --help"
