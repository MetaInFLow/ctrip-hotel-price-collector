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
- 多实例采集：按酒店切分任务，使用独立 CloakBrowser Profile 并行处理多个酒店；默认单实例，避免占用过多本地资源。
- 价格核验：接口模式可在同一页面点击“展示所有房型”并抽查页面价格，将差异写入 JSON。
- 结果交付：生成房型明细、采集汇总、接口概览和 Excel 文件。
- 操作边界：只执行查询、采集和导出，不执行下单、支付、取消或账号管理。

## CLI 原子能力

CLI 统一入口为 `scripts/ctrip_cli.py`；每个命令只负责一个可验证的业务动作，底层实现按脚本模块拆分：

| 命令 | 实现模块 | 原子动作 | 结果 |
| --- | --- | --- | --- |
| `login` | `ctrip_cli_auth.py` | 启动持久化 Profile，复用 Cookie；必要时在可见窗口手动登录，并等待当前页“我的订单”稳定出现且“登录”消失 | 输出登录状态和 Cookie 数量，不输出 Cookie 值 |
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
- 页面导航后的登录信号允许携程完成短暂渲染切换：统一 `require_logged_in` 会持续探测，清晰的登录或登出信号稳定后才放行或失败，默认探测窗口为 15 秒。
- 登录校验只读取本次操作重新打开并聚焦的当前 Page；成功条件是当前页“我的订单”可见且“登录”不可见。Profile 中旧 Tab 的标识不会替当前页面放行，Cookie 数量只作为诊断信息。
- 选定酒店详情页后，脚本会关闭同一会话中的其他 Tab；命令结束时关闭整个浏览器上下文。`keep_browser_open: true` 或 `login --keep-open` 是保留窗口的显式例外；无交互终端收到 EOF 时按正常关闭处理，已保存的会话不受影响。
- `bring_to_front()` 负责标签页前置；操作系统是否允许窗口抢占前台不可由脚本保证。
- 搜索候选和详情页跳转会把选中的 Page 作为后续操作上下文，不依赖“当前活动标签页”的隐式状态。
- 浏览器实例、Page 和 Locator 只在本次 CLI 进程内有效；跨进程只复用绝对 Profile、缓存和落盘结果。
- 同一个绝对 `profile_dir` 同时只能由一个 CloakBrowser 进程使用；若已有窗口占用该 Profile，先关闭该窗口，或给本次命令传入另一个绝对 `--profile-dir`，不要删除原 Profile。
- `max_parallel_instances` 默认是 `1`；多实例模式先用主 Profile 完成登录校验和所有未命中缓存酒店的详情页解析，再关闭主浏览器。
- 主 Profile 关闭后，脚本复制到本次运行专属的 `worker-N/profile`；复制会排除 `Singleton*`、`DevToolsActivePort` 和 Chromium 锁文件。
- 每个 worker 都用自己的浏览器、Page、Profile 和结果分片，并重新执行登录门禁；worker 登录失败会记录失败状态，不会弹出多个手动登录窗口。
- macOS 启动器记录每个实例的独立调试端口；Launch Services 已启动但 CDP、Playwright 或 Context 初始化失败时，会按 Profile 与端口清理对应 Chromium，避免留下停在 `about:blank` 的孤立窗口。
- 所有 worker 完成后，主进程把 JSON 分片合并到最终输出目录，统一写入 `index.json` 并生成 Excel；worker 浏览器关闭后删除本次运行目录。
- 并行模式下 `keep_browser_open` 不保留 worker 窗口，任务结束会自动关闭全部实例。

## 统一登录门禁

- 登录判断的唯一实现是 `scripts/ctrip_login_guard.py`。它只检查当前聚焦页面，要求 `//*[normalize-space()='我的订单']` 可见且 `//span[normalize-space()='登录']` 不可见；公共导航中的“我的订单”不能单独证明已登录。
- `check_login(browser, page)` 可独立返回登录状态、两个页面信号、Cookie 数量和当前 URL，不返回 Cookie 值。
- `require_logged_in(browser, page, operation=...)` 是搜索、候选选择、详情解析和房价采集的强制门禁。任何门禁失败都抛出 `LoginRequiredError`，当前操作停止。
- `ctrip_cli_auth.py` 的 `login-status` 通过 `check_login` 持续轮询，要求明确的已登录或已登出信号稳定后再返回；`login` 完成等待后再次调用 `require_logged_in`。`ctrip_cli_search.py`、`ctrip_cli_price.py` 和 `ctrip_hotel_prices.py` 的原子操作均保留代码驱动的门禁调用，不提供跳过登录的参数。
- `capture_room_data` 和 `collect_one_stay` 必须接收同一浏览器上下文；调用方无法通过省略上下文绕过登录检查。

## 输入与输出

- 输入：`ctrip_hotel_config.json` 或用户指定的配置文件。酒店项支持 `name`、可选 `detail_url` 和 `city_id`；日期支持连续区间或显式区间；`price_mode` 支持 `response`（默认）和 `page_xpath`；`max_parallel_instances` 控制并行实例数，默认 `1`。
- 页面价格配置：`page_price_xpath` 是页面价格元素 XPath；`show_all_rooms_xpath` 是“展示所有房型”按钮 XPath，缺省使用按按钮文字匹配的通用 XPath；`page_room_name_xpath` 可选，用于按房型名匹配接口行；`page_price_sample_size` 默认为 3，设为 0 可关闭接口模式抽查。
- 输出：每个酒店和日期的原始 JSON、房型价格明细、采集汇总、接口概览和 `ctrip_hotel_prices.xlsx`。房型价格表包含 `价格来源`、`接口价格`、`页面价格文本`、`页面价格XPath` 和页面匹配方式。

## 核心流程

1. 先读取 `ctrip_hotel_config.json` 或用户指定的 JSON 配置。
2. 新机器先完成“新机部署”步骤，确认 Python、CloakBrowser 和 Excel 运行时可用。
3. 运行 `scripts/ctrip_hotel_prices.py`，使用可见的持久化 CloakBrowser Profile；启动后从该 Profile 加载携程 Cookie，并只记录 Cookie 数量，不输出 Cookie 值。
4. 已有 Cookie 时，脚本先在同一 Profile 的当前 Page 内持续探测登录状态，要求 `//*[normalize-space()='我的订单']` 稳定出现且 `//span[normalize-space()='登录']` 不可见；探测失败后才点击登录入口。公共 Cookie 不会直接放行。
5. 首次登录只在脚本启动的 CloakBrowser 窗口中由用户手动完成；脚本持续轮询当前 Page 的两个登录信号，确认登录标识稳定后才继续。
6. `max_parallel_instances` 大于 `1` 时，主会话先按以下优先级解析全部酒店详情页，确保人工候选选择不会在多个窗口之间冲突：
   - 有 `detail_url`：直接使用配置地址，并刷新详情页缓存。
   - 无配置地址但缓存命中：复用与酒店名称、城市匹配的缓存地址。
   - 两者都没有：执行模糊选店流程。先在 `#_allSearchKeyword` 输入名称，点击 `#search_button_global`，再从 `//*[@class='search_list_hotel']` 读取候选。
7. 模糊选店只保留可见、`type="hotel"`、包含 `word` 且带有效详情 `url` 的候选；使用 `district` 展示区域，按详情 URL 或酒店名去重，剔除地标、历史项、列表页和不完整项。候选按序号打印，用户确认后点击对应 `div`；流程不使用回车，也不猜测未确认的酒店。
8. 如果携程在点击搜索按钮后收起候选下拉，重新触发同一模糊词的输入事件后再读取候选；仍无有效候选时给出明确错误并停止本次酒店解析。
9. 多实例模式关闭主浏览器后，按酒店分组复制独立 Profile，worker 各自执行登录门禁并按配置的随机等待采集自己的全部日期。
10. 每个日期拼接 `checkIn`、`checkOut`、`crn`、`adult`、`children` 参数，监听 `/restapi/soa2/33278/getHotelRoomListInland` 的非 `OPTIONS` 响应并保存完整 JSON。
11. `price_mode=response` 时使用接口 `priceInfo.price` 作为最终价格；配置了 `page_price_xpath` 且抽查数量大于 0 时，在同一响应监听期间先点击 `show_all_rooms_xpath`，读取页面价格并记录接口与页面差异，抽查失败继续保留接口结果。
12. `price_mode=page_xpath` 时必须提供 `page_price_xpath`；脚本先点击 `show_all_rooms_xpath`，读取页面价格作为最终价格，同时保留接口价格、页面原文和匹配方式。页面 XPath 命中但没有可解析数字价格时，本日期失败。
13. 每个日期结束后立即写入结果文件和进度索引；酒店切换、日期切换和连续采集操作之间使用配置的随机等待区间。
14. 生成原始 JSON、房型价格明细和 Excel。失败日期写入 `.error.json`，其他日期继续执行。

## 浏览器实例生命周期

- 模拟浏览器、Mideng 或其他托管浏览器的 instance 只在当前任务期间有效；任务完成、工具返回、超时或外部清理后，旧的 `browser`、`page` 和候选定位器都不可继续使用。
- 持久化边界只有绝对路径的 `profile_dir`、`detail_url_cache_file` 和 `output_dir`。Cookie 值、页面状态、内存候选和浏览器 tab 不作为后续任务输入。
- 任务状态写入输出目录的 `index.json`：`running` 表示执行中，`ready_for_export` 表示原始结果已落盘，`completed` 表示 Excel 已生成，`failed` 表示任务异常结束。脚本按日期增量保存，实例提前清理后可依据已落盘结果重跑。
- `keep_browser_open` 默认是 `false`，采集完成后自动关闭浏览器；需要人工观察时显式设置为 `true`。该配置只控制是否等待关闭，不承诺 instance 持续存在；任务完成以 `index.json` 和 Excel 文件写入成功为准。
- `max_parallel_instances` 默认是 `1`，实际 worker 数量不会超过酒店数量。并行模式下主 Profile 只负责登录和详情页解析，worker 关闭后临时 Profile 自动删除；`keep_browser_open` 在并行模式下忽略。

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

直接覆盖本次运行的并行实例数：

```bash
/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_hotel_prices.py \
  --config /绝对路径/ctrip-hotel-price-collector/ctrip_hotel_config.json \
  --max-parallel-instances 2
```

CLI 统一入口也支持同名覆盖：

```bash
/绝对路径/ctrip-hotel-price-collector/.venv/bin/python \
  /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_cli.py collect \
  --config /绝对路径/ctrip-hotel-price-collector/ctrip_hotel_config.json \
  --max-parallel-instances 2
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

酒店可以是名称字符串，也可以是带 `name`、`detail_url`、`city_id` 的对象。公共参数包括 `city_id`、`adults`、`children`、`rooms`、`price_mode`、`show_all_rooms_xpath`、`page_price_xpath`、`page_room_name_xpath`、`page_price_sample_size`、`detail_url_cache_file`、`random_sleep_min_seconds`、`random_sleep_max_seconds` 和 `max_parallel_instances`。

`max_parallel_instances` 示例：

```json
{
  "max_parallel_instances": 2
}
```

设置为 `2` 时，两家酒店可以同时运行两个独立 CloakBrowser；每个 worker 处理一组酒店及其全部日期。未命中详情页缓存的酒店仍由主会话按顺序搜索并缓存，避免多个 worker 同时要求人工选择。

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

并行运行期间的临时目录位于主 Profile 同级的绝对路径：

```text
<profile_dir 的上级目录>/.ctrip-parallel-runs/<run-id>/worker-1/profile
<profile_dir 的上级目录>/.ctrip-parallel-runs/<run-id>/worker-2/profile
```

临时 Profile 只用于当前运行，worker 全部退出后自动删除；主 Profile、Cookie、详情页缓存和最终 Excel 会保留。

## 约束

- 所有酒店搜索和价格采集都必须通过登录状态检查；不要添加跳过登录的参数或调用路径。
- 登录、验证码和风控校验由用户在可见浏览器中手动完成，脚本不代填账号密码，也不绕过验证码。
- 只保留用户明确配置的酒店和日期范围；不要扩大采集范围。
- 修改脚本后先运行技能包测试，再使用真实登录会话做小范围采集回归。
