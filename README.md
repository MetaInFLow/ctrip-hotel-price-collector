# FDE特供携程比价技能

用于在用户自己的携程登录会话中采集酒店房型价格，详细使用方法和业务流程统一见 [SKILL.md](SKILL.md)。

## 初始化入口

macOS/Linux：

```bash
bash "/绝对路径/ctrip-hotel-price-collector/scripts/bootstrap_ctrip_hotel_skill.sh"
```

Windows PowerShell：

```powershell
py C:\绝对路径\ctrip-hotel-price-collector\scripts\bootstrap_ctrip_hotel_skill.py
```

初始化脚本会先检测 Python 3.12+。如未检测到，请按脚本提示从 [Python 官方下载页](https://www.python.org/downloads/) 安装后重新运行。
