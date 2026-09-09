# FDE特供携程比价技能

在用户自己的携程本地会话中，采集指定酒店与日期区间的房型价格，输出 JSON 和 Excel 比价结果。

## 安装前确认

- 安装包名称与当前电脑的系统和芯片匹配，例如 `macos-arm64` 或 `windows-x64`。
- 将整个文件夹解压到本机可写目录，保持目录结构完整。
- 建议保留至少 2 GB 可用空间。安装与环境验证不需要访问外部下载服务。

## 首次安装

客户电脑无需预装 Python，无需管理员权限。

macOS/Linux：

```bash
bash "/绝对路径/ctrip-hotel-price-collector/install.sh"
```

Windows：双击 `install.cmd`。

客户包已内置 CloakBrowser 浏览器组件。安装程序会验证运行程序、浏览器驱动、Excel 导出和浏览器组件；出现“环境验证通过”后才算安装完成。

## 配置与采集

编辑技能包根目录的 `ctrip_hotel_config.json`，填写酒店、城市、入住日期和采集天数。样例配置不包含账号、密码或 Cookie。

macOS/Linux：

```bash
"/绝对路径/ctrip-hotel-price-collector/bin/ctrip-agent" collect \
  --config "/绝对路径/ctrip-hotel-price-collector/ctrip_hotel_config.json"
```

Windows：

```powershell
& "C:\绝对路径\ctrip-hotel-price-collector\bin\ctrip-agent.exe" collect `
  --config "C:\绝对路径\ctrip-hotel-price-collector\ctrip_hotel_config.json"
```

首次采集需要登录时，程序会打开可见的携程窗口。请在该窗口内完成登录和必要验证，程序会继续执行。登录信息和采集结果仅保存在当前电脑。

## 故障处理

重新检查环境：

```bash
"/绝对路径/ctrip-hotel-price-collector/bin/ctrip-agent" setup
```

常见原因包括：安装包平台不匹配、安装包未完整解压、安全软件隔离了组件、解压目录不可写。
