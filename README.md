# PageSnapFlow

Android 原生 APP 自动截图工具：基于 [Maestro](https://maestro.mobile.dev/) 低代码 YAML 流程，自动执行滑动、点击、翻页，并在每步操作后截图。

## 支持的 APP

| App | Flow 目录 | 包名（需设备上验证） |
|-----|-----------|---------------------|
| Breaking News US | `flows/breaking_news_us/` | `com.breakingnews.us` |
| TapTap Lite | `flows/taptap_lite/` | `com.taptap.global.lite` |
| McDonald's | `flows/mcdonalds/` | `com.mcdonalds.mobileapp` |
| Booking.com | `flows/booking/` | `com.booking` |
| 站酷 | `flows/zcool/` | `com.zcool.community` |
| PlayStation App | `flows/playstation/` | `com.scee.psxandroid` |
| YouTube TV | `flows/youtube_tv/` | `com.google.android.apps.youtube.unplugged` |

完整注册表见 [`config/apps.yaml`](config/apps.yaml)。

## 环境要求

- Windows 10+
- Python 3.8+
- [Maestro CLI](https://maestro.mobile.dev/docs/getting-started/installing-maestro)
- [Android Platform Tools (ADB)](https://developer.android.com/tools/releases/platform-tools)
- Android 真机（USB 调试）或 Android 模拟器

## 快速开始

### 0. Windows 脚本执行策略

若直接运行 `.ps1` 报「禁止运行脚本」，请用项目根目录的 `.bat` 启动器（已自动 Bypass 执行策略）：

```cmd
setup.bat
verify.bat
run.bat -App breaking_news_us -Flow home_browse
run_all.bat
```

或在 PowerShell 中显式 Bypass：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1
```

### 1. 安装依赖

```powershell
cd D:\code\zqh\PageSnapFlow

# 推荐：用 bat 启动器（无需改系统执行策略）
setup.bat

# 或 PowerShell Bypass
powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1

# Python 依赖（截图整理、去重）
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# 验证环境
verify.bat
```

### 2. 连接 Android 设备

```powershell
adb devices
adb shell wm size
```

### 3. 安装目标 APP 并确认包名

```powershell
adb shell pm list packages | findstr -i taptap
adb shell pm list packages | findstr -i booking
```

若包名与 `config/apps.yaml` 不一致，修改对应 flow 文件顶部的 `appId`。

### 4. 探路与录制（推荐）

```powershell
maestro studio
```

在 Studio 中手动操作 APP，Maestro 会生成命令。将流程导出为 YAML，放入 `flows/<app>/`，并在关键步骤插入 `takeScreenshot`。

### 5. 运行单个 flow

```powershell
.\scripts\run_flow.ps1 -App breaking_news_us -Flow home_browse
```

截图输出：

```
screenshots/breaking_news_us/20260619_143022/
├── 01_home.png
├── 02_feed_swipe_1.png
├── ...
└── run_manifest.json
```

### 6. 批量运行所有 APP

```powershell
.\scripts\run_all.ps1

# 指定部分 APP
.\scripts\run_all.ps1 -Apps taptap_lite,booking

# 某 APP 失败后继续
.\scripts\run_all.ps1 -ContinueOnError
```

### 7. 去重（滑动产生的相似帧）

```powershell
.\scripts\dedup_screenshots.ps1 -InputDir screenshots\taptap_lite\20260619_143022 -Similarity 0.92
```

## 项目结构

```
PageSnapFlow/
├── config/
│   ├── apps.yaml          # APP 注册表
│   └── devices.yaml       # 设备配置
├── flows/
│   ├── common/            # 弹窗/权限 dismiss 子 flow
│   ├── breaking_news_us/
│   ├── taptap_lite/
│   └── ...
├── scripts/
│   ├── setup_env.ps1      # 环境安装
│   ├── verify_env.ps1     # 环境检查
│   ├── run_flow.ps1       # 单 APP 运行
│   ├── run_all.ps1        # 批量运行
│   ├── collect_screenshots.py
│   └── dedup_screenshots.py
└── screenshots/           # 输出目录（gitignore）
```

## Flow 编写示例

```yaml
appId: com.taptap.global.lite

---
- launchApp
- runFlow: ../common/dismiss_permissions.yaml
- runFlow: ../common/dismiss_dialogs.yaml
- takeScreenshot: 01_home

- swipe:
    start: 50%, 80%
    end: 50%, 20%
- takeScreenshot: 02_after_swipe

- tapOn:
    text: "发现"
    optional: true
- takeScreenshot: 03_discover
```

## 常见问题

**Maestro 找不到设备**  
确认 `adb devices` 显示 `device` 状态，非 `unauthorized`。

**tapOn 找不到元素**  
用 `maestro studio` 重新录制；或改用 `point: "50%,50%"` 百分比坐标。

**包名不对**  
`adb shell pm list packages | findstr -i <keyword>` 查实际包名，更新 flow 的 `appId`。

**登录/验证码**  
首次手动登录后 Maestro 可复用 session；或在 flow 开头增加登录子 flow。

## 与 image-filtering 衔接

同目录下的 [`image-filtering`](../image-filtering) 项目可用于游戏截图血条筛选。PageSnapFlow 内置了通用的 `dedup_screenshots.py`，更适合 APP 滑动截图去重。
