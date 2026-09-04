---
name: ctrip-hotel-price-collector
description: "Use when collecting logged-in Ctrip hotel room prices for configured hotels and dates in a visible CloakBrowser session, intercepting the room-list JSON and exporting Excel."
---

# 携程酒店价格采集

用于在用户自己的携程登录状态下采集酒店房型价格。技能只执行查询和导出，不执行下单、支付、取消或账号管理。

## 核心流程

1. 先读取 `ctrip_hotel_config.json` 或用户指定的 JSON 配置。
2. 新机器先完成“新机部署”步骤，确认 Python、CloakBrowser 和 Excel 运行时可用。
3. 运行 `scripts/ctrip_hotel_prices.py`，使用可见的持久化 CloakBrowser profile；启动后从该 Profile 加载携程 Cookie，并只记录 Cookie 数量，不输出 Cookie 值。
4. 首次运行在携程页面点击“登录”，提示用户手动登录自己的账号；持续轮询 `//*[normalize-space()='我的订单']`，确认登录成功后才继续。
5. 已有 Profile 时先复用 Cookie 并检查“我的订单”。只要 `//*[normalize-space()='我的订单']` 可见就视为已登录，即使首页仍保留“登录”入口；登录状态无效时才提示手动登录。
6. 有 `detail_url` 的酒店直接使用详情页并刷新详情页缓存；没有详情页时先读取缓存，命中后直接使用缓存 URL，未命中才通过 `#_allSearchKeyword` 搜索酒店并进入详情页。
7. 每个日期拼接 `checkIn`、`checkOut`、`crn`、`adult`、`children` 参数，监听 `/restapi/soa2/33278/getHotelRoomListInland` 的非 `OPTIONS` 响应并保存完整 JSON。
8. 酒店切换、日期切换和连续采集操作之间使用配置的随机等待区间，避免连续无间隔请求。
9. 生成原始 JSON、房型价格明细和 Excel。失败日期写入 `.error.json`，其他日期继续执行。

## 新机部署

部署脚本针对 macOS/Linux，必须在首次运行前执行。它会创建或更新 Python 虚拟环境，安装 CloakBrowser 与 openpyxl 依赖。Excel 默认由 Python 版生成器 `scripts/ctrip_hotel_excel_builder.py` 生成，无需 Node.js。

```bash
cd /path/to/ctrip-hotel-price-collector
./scripts/bootstrap_ctrip_hotel_skill.sh --venv-dir /path/to/.venv
```

`--node-modules` 为可选参数，仅在需要回退到旧的 `@oai/artifact-tool` 生成器时使用，指向包含该包的 Node.js node_modules 目录。

部署完成后先检查：

```bash
/path/to/.venv/bin/python scripts/ctrip_hotel_prices.py --help
```

## 运行

首次只保存登录会话：

```bash
/path/to/.venv/bin/python scripts/ctrip_hotel_prices.py --login-only
```

执行采集：

```bash
/path/to/.venv/bin/python scripts/ctrip_hotel_prices.py \
  --config ctrip_hotel_config.json
```

配置支持两种日期方式：

- `start_date + days + nights`：从起始日期连续生成入住区间。
- `dates`：显式提供多个 `check_in` / `check_out` 区间；存在 `dates` 时优先使用它。

酒店可以是名称字符串，也可以是带 `name`、`detail_url`、`city_id` 的对象。公共参数包括 `city_id`、`adults`、`children`、`rooms`、`detail_url_cache_file`、`random_sleep_min_seconds` 和 `random_sleep_max_seconds`。

详情页缓存默认写入 `.ctrip-hotel-detail-cache.json`，位置与配置文件相同。缓存记录酒店名称、城市和详情页 URL；修改酒店名称或城市后会按新键重新搜索。删除该文件即可强制重新搜索全部未显式配置详情页的酒店。

## 输出与会话

- 原始响应和房型明细：配置的 `output_dir`，默认是 `output/ctrip_hotel_prices`。
- Excel：`output_dir/ctrip_hotel_prices.xlsx`，包含“房型价格”“采集汇总”“接口概览”“说明”四个工作表。
- 详情页缓存：配置的 `detail_url_cache_file`，默认是 `.ctrip-hotel-detail-cache.json`。
- 登录会话与 Cookie：配置的 `profile_dir`，默认是 `.cloakbrowser-profile`。CloakBrowser 会从该持久化 Profile 自动恢复 Cookie；当默认安装目录没有 Profile 时，脚本会复用当前项目目录下已有的 `.cloakbrowser-profile`。该目录包含敏感信息，只保存在本机，不要提交、同步或分享。

## 约束

- 所有酒店搜索和价格采集都必须通过登录状态检查；不要添加跳过登录的参数或调用路径。
- 登录、验证码和风控校验由用户在可见浏览器中手动完成，脚本不代填账号密码，也不绕过验证码。
- 只保留用户明确配置的酒店和日期范围；不要扩大采集范围。
- 修改脚本后先运行技能包测试，再使用真实登录会话做小范围采集回归。
