# FDE特供携程比价技能

在用户自己的携程登录状态下，使用持久化 CloakBrowser 采集指定酒店、指定日期的房型价格，并输出 Excel。所有携程页面操作都由技能脚本完成。

价格默认来自房型接口响应。需要页面口径时，在配置中设置 `price_mode` 为 `page_xpath`，并提供 `show_all_rooms_xpath` 与 `page_price_xpath`；脚本会先点击“展示所有房型”，再读取页面价格。接口模式配置页面价格 XPath 后，会默认抽查 3 条页面价格并把差异写入每日 JSON。

## 使用

1. macOS/Linux 执行 `python3 /绝对路径/ctrip-hotel-price-collector/scripts/bootstrap_ctrip_hotel_skill.py`；Windows PowerShell 执行 `py C:\绝对路径\ctrip-hotel-price-collector\scripts\bootstrap_ctrip_hotel_skill.py`，部署 Python、CloakBrowser 与 openpyxl 依赖。
2. 编辑 `/绝对路径/ctrip-hotel-price-collector/ctrip_hotel_config.json`，配置酒店列表、城市、起始日期和采集天数。默认 `price_mode` 为 `response`；页面模式需要额外配置页面 XPath。
3. 首次执行 `/绝对路径/ctrip-hotel-price-collector/.venv/bin/python /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_hotel_prices.py --login-only`，在可见浏览器中手动登录携程；Windows 将解释器替换为 `C:\绝对路径\ctrip-hotel-price-collector\.venv\Scripts\python.exe`。
4. 使用同一绝对解释器执行采集脚本，并传入绝对配置路径。

结果写入固定的绝对路径。macOS Cookie/Profile 位于 `/Users/<系统用户名>/Library/Application Support/ctrip-hotel-price-collector/.cloakbrowser-profile`；Windows Cookie/Profile 位于 `C:\Users\<系统用户名>\AppData\Local\ctrip-hotel-price-collector\.cloakbrowser-profile`。详情页缓存和 Excel 输出位于同一系统存储根目录下。登录 Profile 中的 Cookie 会由脚本自动复用；所有携程页面操作都必须在该 CloakBrowser 会话中完成。脚本只记录 Cookie 数量，不输出 Cookie 值。自定义路径必须使用绝对路径。

Excel 由 Python `openpyxl` 生成，不需要 Node.js。

完整流程与约束见 [SKILL.md](SKILL.md)。
