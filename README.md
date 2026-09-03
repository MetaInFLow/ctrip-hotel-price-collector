# Ctrip Hotel Price Collector

在用户自己的携程登录状态下，使用 CloakBrowser 采集指定酒店、指定日期的房型价格，并输出 Excel。

## 使用

1. 执行 `scripts/bootstrap_ctrip_hotel_skill.sh` 部署 Python 与 CloakBrowser 依赖。
2. 编辑 `ctrip_hotel_config.json`，配置酒店列表、城市、起始日期和采集天数。
3. 首次执行 `scripts/ctrip_hotel_prices.py --login-only`，在可见浏览器中手动登录携程。
4. 执行 `scripts/ctrip_hotel_prices.py --config ctrip_hotel_config.json`。

结果写入配置中的 `output_dir`，详情页 URL 会缓存到 `.ctrip-hotel-detail-cache.json`。登录 Profile、Cookie、缓存和采集结果均只保存在本机，不应提交到仓库。

完整流程与约束见 [SKILL.md](SKILL.md)。
