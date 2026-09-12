# FDE特供携程比价技能

在用户自己的携程登录状态下，采集酒店在指定日期的房型价格，输出每日 JSON 和 Excel 比价结果。所有携程页面操作都由 Skill 脚本通过 CloakBrowser 完成。

## 业务主流程

1. **接收需求**：提取酒店名称、城市 ID、入住起始日和连续采集天数。成人数默认2 人，儿童数默认0，房间数默认1，晚数默认1。
2. **准备环境**：执行初始化脚本。脚本先检测 Python 3.12+，虚拟环境固定创建在 `<skill目录>/.runtime/python-3.12/`。
3. **启动会话**：脚本启动持久化 CloakBrowser Profile，复用本机会话。
4. **登录门禁**：同时检查“我的订单”可见且“登录”不可见。未登录时打开窗口等待用户完成登录。
5. **解析酒店**：优先使用详情页地址，其次使用本地缓存，否则在携程全局搜索框输入酒店名，候选不唯一时由用户确认。
6. **逐日采集**：按日期生成入住/离店参数，监听房型接口，获取各房型价格，每个日期完成后立即落盘。
7. **导出结果**：生成 `ctrip_hotel_prices.xlsx`；失败日期保留 `.error.json`。

## 初始化

macOS/Linux：

```bash
bash "/绝对路径/ctrip-hotel-price-collector/scripts/bootstrap_ctrip_hotel_skill.sh"
```

Windows PowerShell：

```powershell
py C:\绝对路径\ctrip-hotel-price-collector\scripts\bootstrap_ctrip_hotel_skill.py
```

如未检测到 Python 3.12+，请按脚本提示从 [Python 官方下载页](https://www.python.org/downloads/) 安装后重新运行。

## 快速采集

源码态直接执行 Skill 运行时 Python 与 CLI：

```bash
"/绝对路径/ctrip-hotel-price-collector/.runtime/python-3.12/bin/python" \
  "/绝对路径/ctrip-hotel-price-collector/scripts/ctrip_cli.py" collect \
  --hotel "酒店名称" --city-id 30 --start-date 2026-09-10 --days 7
```

多家酒店重复传入 `--hotel`。高级用户可使用 `--config` 读取既有 JSON 配置。

## 运行时与登录

- 默认 Profile 和结果保存在操作系统的绝对应用数据目录。
- 每次采集开始时先做登录门禁；每个日期抓取前和日期页面导航后再检查。
- 登录状态由 `scripts/ctrip_login_guard.py` 代码判定，不靠 README 或 Skill 文字判断。

## 边界

本技能只执行登录、搜索、价格采集和导出，不执行下单、支付、取消或账号管理。
