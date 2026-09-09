#!/usr/bin/env sh
set -eu

SKILL_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
RUNNER="$SKILL_DIR/bin/ctrip-agent"
BROWSER_DIR="$SKILL_DIR/browser"

if [ ! -f "$RUNNER" ]; then
  printf '%s\n' "安装失败：当前安装包与操作系统不匹配，或运行程序不完整。" >&2
  exit 1
fi
if [ ! -d "$BROWSER_DIR" ]; then
  printf '%s\n' "安装失败：客户包缺少内置浏览器组件，请重新解压完整安装包。" >&2
  exit 1
fi

chmod +x "$RUNNER"
if command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "$RUNNER" "$BROWSER_DIR" 2>/dev/null || true
fi

"$RUNNER" setup
printf '\n%s\n' "部署完成。请在 Codex 中启用 FDE特供携程比价技能。"
