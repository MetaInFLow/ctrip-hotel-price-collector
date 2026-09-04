# FDE特供携程比价技能

在用户自己的携程登录状态下，使用 CloakBrowser 采集指定酒店、指定日期的房型价格，并输出 Excel。

## 使用

1. macOS/Linux 执行 `python3 /绝对路径/ctrip-hotel-price-collector/scripts/bootstrap_ctrip_hotel_skill.py`；Windows PowerShell 执行 `py C:\绝对路径\ctrip-hotel-price-collector\scripts\bootstrap_ctrip_hotel_skill.py`，部署 Python、CloakBrowser 与 openpyxl 依赖。
2. 编辑 `/绝对路径/ctrip-hotel-price-collector/ctrip_hotel_config.json`，配置酒店列表、城市、起始日期和采集天数。
3. 首次执行 `/绝对路径/ctrip-hotel-price-collector/.venv/bin/python /绝对路径/ctrip-hotel-price-collector/scripts/ctrip_hotel_prices.py --login-only`，在可见浏览器中手动登录携程；Windows 将解释器替换为 `C:\绝对路径\ctrip-hotel-price-collector\.venv\Scripts\python.exe`。
4. 使用同一绝对解释器执行采集脚本，并传入绝对配置路径。

结果写入固定的绝对路径。macOS Cookie/Profile 位于 `/Users/<系统用户名>/Library/Application Support/ctrip-hotel-price-collector/.cloakbrowser-profile`；Windows Cookie/Profile 位于 `C:\Users\<系统用户名>\AppData\Local\ctrip-hotel-price-collector\.cloakbrowser-profile`。详情页缓存和 Excel 输出位于同一系统存储根目录下。登录 Profile 中的 Cookie 会自动复用；脚本只记录 Cookie 数量，不输出 Cookie 值。自定义路径必须使用绝对路径。

Excel 由 Python `openpyxl` 生成，不需要 Node.js。

完整流程与约束见 [SKILL.md](SKILL.md)。
