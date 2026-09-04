---
name: ctrip-hotel-price-collector
description: >-
  FDE特供携程比价技能。适用：在用户自己的携程登录态下，按配置的酒店和日期区间采集房型价格并导出 Excel。
  支持详情页 URL、详情页缓存，或在携程全局搜索框输入模糊酒店名后从候选列表选择具体酒店。
  边界：仅查询和导出，不执行下单、支付、取消或账号管理。
---

# FDE特供携程比价技能

面向 FDE 场景的携程酒店价格采集与比价技能。用户可以提供精确详情页，也可以提供不完整的酒店名称，由脚本展示携程候选后人工确认具体酒店。

## 能力范围

- 登录态校验：复用本地持久化会话，必要时由用户在可见浏览器中手动登录。
- 模糊选店：输入部分酒店名，点击携程搜索按钮，展示酒店候选并由用户选择；候选包含酒店名、区域和详情地址。
- 多日期比价：按连续日期或显式入住区间采集房型、价格和接口原始 JSON。
- 结果交付：生成房型明细、采集汇总、接口概览和 Excel 文件。
- 操作边界：只执行查询、采集和导出，不执行下单、支付、取消或账号管理。

## 输入与输出

- 输入：`ctrip_hotel_config.json` 或用户指定的配置文件。酒店项支持 `name`、可选 `detail_url` 和 `city_id`；日期支持连续区间或显式区间。
- 输出：每个酒店和日期的原始 JSON、房型价格明细、采集汇总、接口概览和 `ctrip_hotel_prices.xlsx`。

## 核心流程

1. 先读取 `ctrip_hotel_config.json` 或用户指定的 JSON 配置。
2. 新机器先完成“新机部署”步骤，确认 Python、CloakBrowser 和 Excel 运行时可用。
3. 运行 `scripts/ctrip_hotel_prices.py`，使用可见的持久化 CloakBrowser profile；启动后从该 Profile 加载携程 Cookie，并只记录 Cookie 数量，不输出 Cookie 值。
4. 首次运行在携程页面点击“登录”，提示用户手动登录自己的账号；持续轮询 `//*[normalize-space()='我的订单']`，确认登录成功后才继续。
5. 已有 Profile 时先复用 Cookie 并检查“我的订单”。只要 `//*[normalize-space()='我的订单']` 可见就视为已登录，即使首页仍保留“登录”入口；登录状态无效时才提示手动登录。
6. 解析酒店详情页，按以下优先级处理：
   - 有 `detail_url`：直接使用配置地址，并刷新详情页缓存。
   - 无配置地址但缓存命中：复用与酒店名称、城市匹配的缓存地址。
   - 两者都没有：执行模糊选店流程。先在 `#_allSearchKeyword` 输入名称，点击 `#search_button_global`，再从 `//*[@class='search_list_hotel']` 读取候选。
7. 模糊选店只保留可见、`type="hotel"`、包含 `word` 且带有效详情 `url` 的候选；使用 `district` 展示区域，按详情 URL 或酒店名去重，剔除地标、历史项、列表页和不完整项。候选按序号打印，用户确认后点击对应 `div`；流程不使用回车，也不猜测未确认的酒店。
8. 如果携程在点击搜索按钮后收起候选下拉，重新触发同一模糊词的输入事件后再读取候选；仍无有效候选时给出明确错误并停止本次酒店解析。
9. 每个日期拼接 `checkIn`、`checkOut`、`crn`、`adult`、`children` 参数，监听 `/restapi/soa2/33278/getHotelRoomListInland` 的非 `OPTIONS` 响应并保存完整 JSON。每个日期结束后立即写入结果文件和进度索引。
10. 酒店切换、日期切换和连续采集操作之间使用配置的随机等待区间，避免连续无间隔请求。
11. 生成原始 JSON、房型价格明细和 Excel。失败日期写入 `.error.json`，其他日期继续执行。

## 浏览器实例生命周期

- 模拟浏览器、Mideng 或其他托管浏览器的 instance 只在当前任务期间有效；任务完成、工具返回、超时或外部清理后，旧的 `browser`、`page` 和候选定位器都不可继续使用。
- 持久化边界只有绝对路径的 `profile_dir`、`detail_url_cache_file` 和 `output_dir`。Cookie 值、页面状态、内存候选和浏览器 tab 不作为后续任务输入。
- 任务状态写入输出目录的 `index.json`：`running` 表示执行中，`ready_for_export` 表示原始结果已落盘，`completed` 表示 Excel 已生成，`failed` 表示任务异常结束。脚本按日期增量保存，实例提前清理后可依据已落盘结果重跑。
- `keep_browser_open` 只控制人工观察时是否等待关闭，不承诺 instance 持续存在。模拟或无人值守运行可设置为 `false`；任务完成以 `index.json` 和 Excel 文件写入成功为准。

## 新机部署

首次运行前执行一次跨平台部署脚本。它会创建或更新 Python 虚拟环境，安装 CloakBrowser 与 openpyxl 依赖。Excel 只由 Python 版生成器 `scripts/ctrip_hotel_excel_builder.py` 生成。

macOS/Linux：
```bash
python3 /绝对路径/ctrip-hotel-price-collector/scripts/bootstrap_ctrip_hotel_skill.py \
  --venv-dir /绝对路径/ctrip-hotel-price-collector/.venv
```

Windows PowerShell：
```powershell
py C:\绝对路径\ctrip-hotel-price-collector\scripts\bootstrap_ctrip_hotel_skill.py `
  --venv-dir C:\绝对路径\ctrip-hotel-price-collector\.venv
```

macOS/Linux 也可以执行同目录下的 `bootstrap_ctrip_hotel_skill.sh`，它只是上述 Python 部署脚本的便捷包装。

部署完成后先检查：

```bash
/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_hotel_prices.py --help
```

Windows 检查命令使用 `C:\绝对路径\ctrip-hotel-price-collector\.venv\Scripts\python.exe`。

## 运行

首次只保存登录会话：

```bash
/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_hotel_prices.py --login-only
```

执行采集：

```bash
/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_hotel_prices.py \
  --config /绝对路径/ctrip-hotel-price-collector/ctrip_hotel_config.json
```

配置支持两种日期方式：

- `start_date + days + nights`：从起始日期连续生成入住区间。
- `dates`：显式提供多个 `check_in` / `check_out` 区间；存在 `dates` 时优先使用它。

酒店可以是名称字符串，也可以是带 `name`、`detail_url`、`city_id` 的对象。公共参数包括 `city_id`、`adults`、`children`、`rooms`、`detail_url_cache_file`、`random_sleep_min_seconds` 和 `random_sleep_max_seconds`。

详情页缓存使用固定绝对路径。缓存记录酒店名称、城市和详情页 URL；每次保存都会读取磁盘最新内容并增量合并当前新增或更新的记录，再以原子方式写回，历史记录会继续保留。酒店名称与 `city_id` 共同组成缓存键，同名酒店在不同城市可以分别命中；旧版按酒店名称保存的缓存仍可读取。删除该绝对路径文件即可强制重新搜索全部未显式配置详情页的酒店。

## 输出与会话

默认存储根目录始终由脚本解析为绝对路径：

- macOS Cookie/Profile：`/Users/<系统用户名>/Library/Application Support/ctrip-hotel-price-collector/.cloakbrowser-profile`
- macOS 详情页缓存：`/Users/<系统用户名>/Library/Application Support/ctrip-hotel-price-collector/.ctrip-hotel-detail-cache.json`
- macOS 采集输出：`/Users/<系统用户名>/Library/Application Support/ctrip-hotel-price-collector/output/ctrip_hotel_prices`
- Windows Cookie/Profile：`C:\Users\<系统用户名>\AppData\Local\ctrip-hotel-price-collector\.cloakbrowser-profile`
- Windows 详情页缓存：`C:\Users\<系统用户名>\AppData\Local\ctrip-hotel-price-collector\.ctrip-hotel-detail-cache.json`
- Windows 采集输出：`C:\Users\<系统用户名>\AppData\Local\ctrip-hotel-price-collector\output\ctrip_hotel_prices`
- Linux Cookie/Profile：`/home/<系统用户名>/.local/state/ctrip-hotel-price-collector/.cloakbrowser-profile`
- Linux 详情页缓存：`/home/<系统用户名>/.local/state/ctrip-hotel-price-collector/.ctrip-hotel-detail-cache.json`
- Linux 采集输出：`/home/<系统用户名>/.local/state/ctrip-hotel-price-collector/output/ctrip_hotel_prices`

Excel 文件位于对应系统的采集输出目录下的 `ctrip_hotel_prices.xlsx`，包含“房型价格”“采集汇总”“接口概览”“说明”四个工作表。CloakBrowser 会从绝对 Profile 路径自动恢复 Cookie；该目录包含敏感信息，只保存在本机，不要提交、同步或分享。

如果在配置中自定义 `profile_dir`、`detail_url_cache_file` 或 `output_dir`，必须填写绝对路径；脚本会拒绝相对路径。

## 约束

- 所有酒店搜索和价格采集都必须通过登录状态检查；不要添加跳过登录的参数或调用路径。
- 登录、验证码和风控校验由用户在可见浏览器中手动完成，脚本不代填账号密码，也不绕过验证码。
- 只保留用户明确配置的酒店和日期范围；不要扩大采集范围。
- 修改脚本后先运行技能包测试，再使用真实登录会话做小范围采集回归。
