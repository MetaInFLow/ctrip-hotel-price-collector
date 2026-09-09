#!/usr/bin/env bash
set -Eeuo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_VERSION="3.12.6"
UV_VERSION="0.12.11"
RUNTIME_DIR="${CTRIP_RUNTIME_DIR:-$SKILL_DIR/.runtime}"
VENV_DIR="${CTRIP_VENV_DIR:-$SKILL_DIR/.venv}"
UV_BIN_DIR="$RUNTIME_DIR/bin"
LOCAL_UV_BIN="$UV_BIN_DIR/uv"
UV_BIN="${CTRIP_UV_BIN:-$LOCAL_UV_BIN}"
PYTHON_INSTALL_DIR="$RUNTIME_DIR/python"
VENV_PYTHON="$VENV_DIR/bin/python"
UV_CACHE_DIR="${CTRIP_UV_CACHE_DIR:-$RUNTIME_DIR/uv-cache}"
CLOAK_CACHE_DIR="${CTRIP_CLOAK_CACHE_DIR:-$RUNTIME_DIR/cloakbrowser}"
LOCK_FILE="$SKILL_DIR/requirements-cloak.lock"
PREFLIGHT_SCRIPT="$SKILL_DIR/scripts/verify_ctrip_hotel_environment.py"
UV_INSTALLER_URL="https://astral.sh/uv/$UV_VERSION/install.sh"
CURRENT_STAGE="初始化"

log() {
  printf '%s\n' "$*"
}

fail_with_guidance() {
  local exit_code=$?
  log ""
  log "安装未完成：${CURRENT_STAGE}。"
  log "请确认网络可访问 PyPI、Astral 和 CloakBrowser 下载地址，并且技能包目录可写、磁盘至少保留 2 GB。"
  log "若公司网络需要代理，请先配置系统代理后重新运行此脚本。"
  exit "$exit_code"
}

install_local_uv() {
  local installer
  mkdir -p "$UV_BIN_DIR"
  installer="$(mktemp "${TMPDIR:-/tmp}/ctrip-uv-installer.XXXXXX")"

  # Keep cleanup in this function. An EXIT trap would outlive the local variable
  # under `set -u` and can turn a successful installation into a false failure.
  if command -v curl >/dev/null 2>&1; then
    if ! curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
      --output "$installer" "$UV_INSTALLER_URL"; then
      rm -f "$installer"
      return 1
    fi
  elif command -v wget >/dev/null 2>&1; then
    if ! wget --https-only --output-document="$installer" "$UV_INSTALLER_URL"; then
      rm -f "$installer"
      return 1
    fi
  else
    rm -f "$installer"
    log "找不到 curl 或 wget，无法下载安装运行时。"
    return 1
  fi

  if ! UV_UNMANAGED_INSTALL="$UV_BIN_DIR" UV_NO_MODIFY_PATH=1 sh "$installer"; then
    rm -f "$installer"
    return 1
  fi
  if ! test -x "$LOCAL_UV_BIN"; then
    rm -f "$installer"
    return 1
  fi
  rm -f "$installer"
}

show_dry_run() {
  cat <<EOF
安装预检（不会修改文件）
- 本地 uv：$UV_BIN
- 本地 Python 3.12：$PYTHON_INSTALL_DIR/$PYTHON_VERSION
- 本地虚拟环境：$VENV_DIR
- 依赖清单：$LOCK_FILE
- CloakBrowser 浏览器运行时：$CLOAK_CACHE_DIR
EOF
}

run_legacy_python_bootstrap() {
  local python_bin="${PYTHON_BIN:-python3}"
  exec "$python_bin" "$SKILL_DIR/scripts/bootstrap_ctrip_hotel_skill.py" "${@:2}"
}

case "${1:-}" in
  --dry-run)
    show_dry_run
    exit 0
    ;;
  --legacy-python)
    run_legacy_python_bootstrap "$@"
    ;;
  --help|-h)
    log "直接运行此脚本即可部署本地运行环境，无需预装 Python。"
    log "可选参数：--dry-run（仅查看计划）；--legacy-python（使用已有 Python）。"
    exit 0
    ;;
esac

trap fail_with_guidance ERR
mkdir -p "$RUNTIME_DIR" "$UV_CACHE_DIR" "$CLOAK_CACHE_DIR"
export UV_PYTHON_INSTALL_DIR="$PYTHON_INSTALL_DIR"
export UV_CACHE_DIR
export CLOAKBROWSER_CACHE_DIR="$CLOAK_CACHE_DIR"
export CLOAKBROWSER_AUTO_UPDATE="${CLOAKBROWSER_AUTO_UPDATE:-false}"

if [[ ! -x "$UV_BIN" ]]; then
  CURRENT_STAGE="下载本地 uv 运行时"
  log "[1/4] 下载本地运行时管理器"
  install_local_uv
  UV_BIN="$LOCAL_UV_BIN"
fi

CURRENT_STAGE="安装本地 Python $PYTHON_VERSION"
log "[2/4] 安装本地 Python $PYTHON_VERSION"
"$UV_BIN" python install --no-bin "$PYTHON_VERSION"

CURRENT_STAGE="创建并同步虚拟环境"
log "[3/4] 创建虚拟环境并安装已锁定依赖"
"$UV_BIN" venv --clear --managed-python --python "$PYTHON_VERSION" "$VENV_DIR"
test -x "$VENV_PYTHON"
"$UV_BIN" pip sync --strict --require-hashes --python "$VENV_PYTHON" "$LOCK_FILE"

CURRENT_STAGE="验证 CloakBrowser 浏览器运行时"
log "[4/4] 下载并验证 CloakBrowser 浏览器运行时"
"$VENV_PYTHON" "$PREFLIGHT_SCRIPT" \
  --skill-dir "$SKILL_DIR" \
  --cache-dir "$CLOAK_CACHE_DIR"

trap - ERR
log ""
log "部署完成。运行采集：$VENV_PYTHON $SKILL_DIR/scripts/ctrip_cli.py collect --config <绝对配置路径>"
