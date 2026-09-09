# FDE特供携程比价技能

在用户自己的携程本地会话中，采集指定酒店与日期区间的房型价格，并输出 JSON 和 Excel 比价结果。

## 部署

macOS/Linux：

```bash
python3 /绝对路径/ctrip-hotel-price-collector/scripts/bootstrap_ctrip_hotel_skill.py
```

Windows PowerShell：

```powershell
py C:\绝对路径\ctrip-hotel-price-collector\scripts\bootstrap_ctrip_hotel_skill.py
```

部署脚本始终把运行环境创建在技能包目录的 `.venv`，并安装 CloakBrowser 与 `openpyxl`。

## 采集

编辑 `ctrip_hotel_config.json` 后，使用该技能包的 Python 运行批量采集：

```bash
/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_cli.py collect \
  --config /绝对路径/ctrip-hotel-price-collector/ctrip_hotel_config.json
```

Windows 使用 `C:\绝对路径\ctrip-hotel-price-collector\.venv\Scripts\python.exe`。脚本会自动检查本地会话；需要登录时会打开可见窗口并等待用户完成登录，然后继续采集。零价结果会触发一次登录状态复核；会话失效时脚本完成重新登录后只重试一次。

运行日志以 `CTRIP_EVENT {JSON}` 输出，可用于监控登录、搜索、零价复核和重试状态。日志不包含 Cookie 值、账号或密码。

## 清空本机运行环境

如需模拟刚安装技能、重新部署和登录，可先执行清理脚本。默认仅预览：

```bash
python3 /绝对路径/ctrip-hotel-price-collector/scripts/clean_ctrip_hotel_environment.py
```

确认删除运行环境和本地状态：

```bash
python3 /绝对路径/ctrip-hotel-price-collector/scripts/clean_ctrip_hotel_environment.py --yes
```

如需同时删除技能目录旁的历史备份，加上 `--include-backups`。脚本保留技能源码，不触碰 `~/.codex` 或其他工作台。

本机持久化目录保存登录 Profile、详情页缓存和输出文件。该目录包含敏感会话数据，只保存在当前设备。完整业务约定见 [SKILL.md](SKILL.md)。
