# FDE特供携程比价技能

在用户自己的携程本地会话中，采集指定酒店与日期区间的房型价格，并输出 JSON 和 Excel 比价结果。

## 首次部署

将整个技能包解压到本机一个可写目录后，按系统执行一次安装。无需预装 Python，也不需要管理员权限。

macOS/Linux：

```bash
bash "/绝对路径/ctrip-hotel-price-collector/scripts/bootstrap_ctrip_hotel_skill.sh"
```

Windows：双击 `scripts\bootstrap_ctrip_hotel_skill.cmd`。

也可以在 PowerShell 中执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\绝对路径\ctrip-hotel-price-collector\scripts\bootstrap_ctrip_hotel_skill.ps1"
```

安装程序会在技能包目录内准备 Python、依赖和 CloakBrowser 浏览器运行时，不修改系统 Python 或系统环境变量。看到“部署完成”或 “Deployment complete”后，才表示安装可用。

安装失败时，先检查以下条件后重新运行：网络可访问 PyPI、Astral 和 CloakBrowser 下载服务；技能包目录可写；磁盘至少有 2 GB 可用空间。如公司网络使用代理，请先连接公司代理。

如提示“代理环境变量”的地址格式无效，请由网络管理员修正该变量后重新运行。安装程序不会输出代理地址、账号或其他敏感信息。

需要在现场排查安装计划时，可运行：

```bash
bash "/绝对路径/ctrip-hotel-price-collector/scripts/bootstrap_ctrip_hotel_skill.sh" --dry-run
```

## 配置与采集

编辑技能包根目录的 `ctrip_hotel_config.json`，填写酒店、城市、入住日期和采集天数。样例配置不包含账号、密码或 Cookie。

macOS/Linux 运行采集：

```bash
"/绝对路径/ctrip-hotel-price-collector/.venv/bin/python" \
  "/绝对路径/ctrip-hotel-price-collector/scripts/ctrip_cli.py" collect \
  --config "/绝对路径/ctrip-hotel-price-collector/ctrip_hotel_config.json"
```

Windows 运行采集：

```powershell
& "C:\绝对路径\ctrip-hotel-price-collector\.venv\Scripts\python.exe" `
  "C:\绝对路径\ctrip-hotel-price-collector\scripts\ctrip_cli.py" collect `
  --config "C:\绝对路径\ctrip-hotel-price-collector\ctrip_hotel_config.json"
```

首次采集需要登录时，脚本会打开可见的携程窗口。请在该窗口内完成登录和必要验证，脚本会继续执行。日志以 `CTRIP_EVENT {JSON}` 输出，不包含 Cookie 值、账号或密码。

## 重置本机环境

需要重新部署或重新登录时，先预览将被清理的本地运行状态：

```bash
"/绝对路径/ctrip-hotel-price-collector/.venv/bin/python" \
  "/绝对路径/ctrip-hotel-price-collector/scripts/clean_ctrip_hotel_environment.py"
```

确认清理后追加 `--yes`。脚本保留技能源码；本机登录 Profile、浏览器运行时和采集输出会被清除。完整业务约定见 [SKILL.md](SKILL.md)。
