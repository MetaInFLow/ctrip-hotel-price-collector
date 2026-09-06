---
name: ctrip-hotel-price-collector
description: >-
  FDE特供携程比价技能。适用：在用户自己的携程登录态下，按配置的酒店和日期区间采集房型价格并导出 Excel。
  支持详情页 URL、详情页缓存，或在携程全局搜索框输入模糊酒店名后从候选列表选择具体酒店。
  边界：仅查询和导出，不执行下单、支付、取消或账号管理。
---

# FDE特供携程比价技能

面向 FDE 场景的携程酒店价格采集与比价技能。用户可以提供精确详情页，也可以提供不完整的酒店名称，由脚本展示携程候选后人工确认具体酒店。

## 浏览器唯一入口

- 所有携程页面操作，包括打开页面、登录、输入、点击、候选选择、页面跳转和接口监听，都必须由本 Skill 的脚本通过 CloakBrowser 执行。
- 脚本是唯一执行入口。禁止使用系统默认浏览器、Chrome、Edge、内置浏览器、通用浏览器工具或其他浏览器实例直接操作携程页面。
- 需要人工登录时，只在脚本启动的可见 CloakBrowser 窗口中完成；登录完成后关闭窗口，后续任务继续使用同一个绝对 `profile_dir`。
- 所有运行命令使用技能包自己的 Python 环境；脚本统一调用本 Skill 的持久化启动适配器，底层使用 `cloakbrowser.launch_persistent_context` 的 CloakBrowser 二进制与参数，禁止改用非持久化 `launch`。
- 需要单独打开携程页面时，只运行 `scripts/open_ctrip.py`；该辅助脚本与采集脚本使用同一默认 Profile，关闭窗口后登录状态仍由该 Profile 持久化。

## 能力范围

- 登录态校验：复用本地持久化会话，必要时由用户在可见浏览器中手动登录。
- 模糊选店：输入部分酒店名，点击携程搜索按钮，展示酒店候选并由用户选择；候选包含酒店名、区域和详情地址。
- 多日期比价：按连续日期或显式入住区间采集房型、价格和接口原始 JSON；价格默认来自接口，也支持页面 XPath 模式。
- 价格核验：接口模式可在同一页面点击“展示所有房型”并抽查页面价格，将差异写入 JSON。
- 结果交付：生成房型明细、采集汇总、接口概览和 Excel 文件。
- 操作边界：只执行查询、采集和导出，不执行下单、支付、取消或账号管理。

## CLI 原子能力

CLI 统一入口为 `scripts/ctrip_cli.py`；每个命令只负责一个可验证的业务动作，底层实现按脚本模块拆分：

| 命令 | 实现模块 | 原子动作 | 结果 |
| --- | --- | --- | --- |
| `login` | `ctrip_cli_auth.py` | 启动持久化 Profile，复用 Cookie；必要时在可见窗口手动登录，并等待“我的订单”稳定出现 | 输出登录状态和 Cookie 数量，不输出 Cookie 值 |
| `login-status` | `ctrip_cli_auth.py` | 打开首页并检查当前 Profile 的登录状态 | JSON；已登录退出码为 `0`，未登录退出码为 `2` |
| `search` | `ctrip_cli_search.py` | 输入模糊酒店名，读取有效候选；交互选择后打开详情页 | 候选列表或选中的酒店名、区域、详情 URL |
| `price` | `ctrip_cli_price.py` | 从指定起始日期生成连续入住区间，按日期采集价格 | `response` 模式获取接口 JSON；`page_xpath` 模式读取页面 XPath 价格 |
| `collect` | `ctrip_hotel_prices.py` | 按完整 JSON 配置执行多酒店、多日期采集并导出 Excel | 保留原批量采集能力，支持缓存、随机等待、断点索引和 Excel |

调用示例：

```bash
/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_cli.py login

/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_cli.py login-status

/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_cli.py search \
  --keyword 峨眉山景区智选假日酒店

/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_cli.py price \
  --detail-url 'https://hotels.ctrip.com/hotels/119084256.html?cityid=95' \
  --start-date 2026-09-06 --days 3 --price-mode response
```

页面 XPath 价格示例：

```bash
/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_cli.py price \
  --detail-url 'https://hotels.ctrip.com/hotels/119084256.html?cityid=95' \
  --start-date 2026-09-06 --price-mode page_xpath \
  --show-all-rooms-xpath "//*[@class='你的展开按钮选择器']" \
  --page-price-xpath "//*[@class='你的价格选择器']"
```

## 页面聚焦与操作原子性

- CloakBrowser 的 `launch_persistent_context` 没有启动级的“聚焦某个页面”参数。
- macOS 上 Playwright 直接派生 Chromium 会触发系统 Launch Services 注册崩溃；本 Skill 通过 `open -na` 经 Launch Services 启动 Cloak Chromium，再通过本机 CDP 连接回持久化 Context。Windows/Linux 继续使用 CloakBrowser 原生持久化启动。
- CLI 通过 `--page-index` 或 `--page-url-contains` 明确选择页面；默认使用第 `0` 个页面。
- 每次输入、点击、跳转或监听前，脚本先对目标 Page 调用 Playwright 的 `bring_to_front()`，再尽力执行 `window.focus()`。
- 登录校验只读取本次操作重新打开并聚焦的当前 Page；Profile 中旧 Tab 的“我的订单”不会再替当前页面放行。
- 选定酒店详情页后，脚本会关闭同一会话中的其他 Tab；命令结束时关闭整个浏览器上下文。`keep_browser_open: true` 或 `login --keep-open` 是保留窗口的显式例外。
- `bring_to_front()` 负责标签页前置；操作系统是否允许窗口抢占前台不可由脚本保证。
- 搜索候选和详情页跳转会把选中的 Page 作为后续操作上下文，不依赖“当前活动标签页”的隐式状态。
- 浏览器实例、Page 和 Locator 只在本次 CLI 进程内有效；跨进程只复用绝对 Profile、缓存和落盘结果。
- 同一个绝对 `profile_dir` 同时只能由一个 CloakBrowser 进程使用；若已有窗口占用该 Profile，先关闭该窗口，或给本次命令传入另一个绝对 `--profile-dir`，不要删除原 Profile。

## 输入与输出

- 输入：`ctrip_hotel_config.json` 或用户指定的配置文件。酒店项支持 `name`、可选 `detail_url` 和 `city_id`；日期支持连续区间或显式区间；`price_mode` 支持 `response`（默认）和 `page_xpath`。
- 页面价格配置：`page_price_xpath` 是页面价格元素 XPath；`show_all_rooms_xpath` 是“展示所有房型”按钮 XPath，缺省使用按按钮文字匹配的通用 XPath；`page_room_name_xpath` 可选，用于按房型名匹配接口行；`page_price_sample_size` 默认为 3，设为 0 可关闭接口模式抽查。
- 输出：每个酒店和日期的原始 JSON、房型价格明细、采集汇总、接口概览和 `ctrip_hotel_prices.xlsx`。房型价格表包含 `价格来源`、`接口价格`、`页面价格文本`、`页面价格XPath` 和页面匹配方式。

## 核心流程

1. 先读取 `ctrip_hotel_config.json` 或用户指定的 JSON 配置。
2. 新机器先完成“新机部署”步骤，确认 Python、CloakBrowser 和 Excel 运行时可用。
3. 运行 `scripts/ctrip_hotel_prices.py`，使用可见的持久化 CloakBrowser Profile；启动后从该 Profile 加载携程 Cookie，并只记录 Cookie 数量，不输出 Cookie 值。
4. 已有 Cookie 时，脚本先在同一 Profile 内持续探测登录状态，等待 `//*[normalize-space()='我的订单']` 稳定出现；探测失败后才点击登录入口。
5. 首次登录只在脚本启动的 CloakBrowser 窗口中由用户手动完成；脚本持续轮询 `//*[normalize-space()='我的订单']`，确认登录标识稳定后才继续。
6. 解析酒店详情页，按以下优先级处理：
   - 有 `detail_url`：直接使用配置地址，并刷新详情页缓存。
   - 无配置地址但缓存命中：复用与酒店名称、城市匹配的缓存地址。
   - 两者都没有：执行模糊选店流程。先在 `#_allSearchKeyword` 输入名称，点击 `#search_button_global`，再从 `//*[@class='search_list_hotel']` 读取候选。
7. 模糊选店只保留可见、`type="hotel"`、包含 `word` 且带有效详情 `url` 的候选；使用 `district` 展示区域，按详情 URL 或酒店名去重，剔除地标、历史项、列表页和不完整项。候选按序号打印，用户确认后点击对应 `div`；流程不使用回车，也不猜测未确认的酒店。
8. 如果携程在点击搜索按钮后收起候选下拉，重新触发同一模糊词的输入事件后再读取候选；仍无有效候选时给出明确错误并停止本次酒店解析。
9. 每个日期拼接 `checkIn`、`checkOut`、`crn`、`adult`、`children` 参数，监听 `/restapi/soa2/33278/getHotelRoomListInland` 的非 `OPTIONS` 响应并保存完整 JSON。
10. `price_mode=response` 时使用接口 `priceInfo.price` 作为最终价格；配置了 `page_price_xpath` 且抽查数量大于 0 时，在同一响应监听期间先点击 `show_all_rooms_xpath`，读取页面价格并记录接口与页面差异，抽查失败继续保留接口结果。
11. `price_mode=page_xpath` 时必须提供 `page_price_xpath`；脚本先点击 `show_all_rooms_xpath`，读取页面价格作为最终价格，同时保留接口价格、页面原文和匹配方式。页面 XPath 命中但没有可解析数字价格时，本日期失败。
12. 每个日期结束后立即写入结果文件和进度索引；酒店切换、日期切换和连续采集操作之间使用配置的随机等待区间。
13. 生成原始 JSON、房型价格明细和 Excel。失败日期写入 `.error.json`，其他日期继续执行。

## 浏览器实例生命周期

- 模拟浏览器、Mideng 或其他托管浏览器的 instance 只在当前任务期间有效；任务完成、工具返回、超时或外部清理后，旧的 `browser`、`page` 和候选定位器都不可继续使用。
- 持久化边界只有绝对路径的 `profile_dir`、`detail_url_cache_file` 和 `output_dir`。Cookie 值、页面状态、内存候选和浏览器 tab 不作为后续任务输入。
- 任务状态写入输出目录的 `index.json`：`running` 表示执行中，`ready_for_export` 表示原始结果已落盘，`completed` 表示 Excel 已生成，`failed` 表示任务异常结束。脚本按日期增量保存，实例提前清理后可依据已落盘结果重跑。
- `keep_browser_open` 默认是 `false`，采集完成后自动关闭浏览器；需要人工观察时显式设置为 `true`。该配置只控制是否等待关闭，不承诺 instance 持续存在；任务完成以 `index.json` 和 Excel 文件写入成功为准。

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

使用页面 XPath 作为价格来源：

```bash
/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_hotel_prices.py \
  --config /绝对路径/ctrip-hotel-price-collector/ctrip_hotel_config.json \
  --price-mode page_xpath \
  --show-all-rooms-xpath "//*[@class='你的展开按钮选择器']" \
  --page-price-xpath "//*[@class='你的价格选择器']" \
  --page-room-name-xpath "//*[@class='你的房型名称选择器']"
```

页面 XPath 参数也可以直接写入 JSON 配置。原始 XPath 和带 `xpath=` 前缀的选择器都支持；页面模式需要提供真实的价格 XPath，示例中的选择器只表示参数位置。

配置支持两种日期方式：

- `start_date + days + nights`：从起始日期连续生成入住区间。
- `dates`：显式提供多个 `check_in` / `check_out` 区间；存在 `dates` 时优先使用它。

酒店可以是名称字符串，也可以是带 `name`、`detail_url`、`city_id` 的对象。公共参数包括 `city_id`、`adults`、`children`、`rooms`、`price_mode`、`show_all_rooms_xpath`、`page_price_xpath`、`page_room_name_xpath`、`page_price_sample_size`、`detail_url_cache_file`、`random_sleep_min_seconds` 和 `random_sleep_max_seconds`。

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

Excel 文件位于对应系统的采集输出目录下的 `ctrip_hotel_prices.xlsx`，包含“房型价格”“采集汇总”“接口概览”“说明”四个工作表。房型价格表会标明价格来源、接口价格、页面价格原文、页面 XPath 和匹配方式；页面抽查明细保存在每日 JSON 的 `page_price_checks` 中。CloakBrowser 会从绝对 Profile 路径自动恢复 Cookie；该目录包含敏感信息，只保存在本机，不要提交、同步或分享。

如果在配置中自定义 `profile_dir`、`detail_url_cache_file` 或 `output_dir`，必须填写绝对路径；脚本会拒绝相对路径。

## 约束

- 所有酒店搜索和价格采集都必须通过登录状态检查；不要添加跳过登录的参数或调用路径。
- 登录、验证码和风控校验由用户在可见浏览器中手动完成，脚本不代填账号密码，也不绕过验证码。
- 只保留用户明确配置的酒店和日期范围；不要扩大采集范围。
- 修改脚本后先运行技能包测试，再使用真实登录会话做小范围采集回归。
