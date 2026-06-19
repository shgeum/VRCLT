# vrclt

语言: [English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [中文](README.zh.md)

`vrclt` 是面向 VRChat 和 Discord 的 Windows 实时翻译工具。它使用 Gemini
Live API 翻译你的麦克风音频，通过 VB-Audio Virtual Cable 将翻译语音送入目标
应用的麦克风输入，并把其他人的语音显示为翻译字幕。

## 主要功能

- 带有仪表板、设置、日志/关于标签页的 Windows 原生 UI
- 托盘菜单支持打开应用、打开设置、切换翻译/字幕和退出
- 出站翻译: 你的麦克风 -> Gemini Live -> 翻译语音 -> 目标应用麦克风
- 入站字幕: 目标应用音频 -> Gemini Live -> 翻译字幕
- 支持 VRChat OSC 聊天框输出、角色 OSC 控制、SteamVR 字幕和手腕菜单
- VRChat 仅文本模式: 保留原始语音直通，只向 OSC 聊天框追加翻译文本
- Discord 模式: 捕获 Discord 进程音频，并自动禁用 VRChat 专用功能
- 单文件发布构建: `dist\vrclt.exe`
- 用户设置保存位置: `%LOCALAPPDATA%\vrclt\config.yaml`

## 要求

- 推荐 Windows 11
- Google Gemini API 密钥 (获取方式见下方)
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
- 使用 VR 叠加层和手腕 UI 时需要 SteamVR
- 使用 VRChat 聊天框/角色控制功能时需要启用 VRChat OSC
- 从源码运行时需要 Python 3.12

### 获取 Gemini API 密钥

1. 打开 [Google AI Studio](https://aistudio.google.com/) 并使用 Google 账号登录。
   - 如果没有 Google 账号，请先创建。
2. 点击左侧边栏或页面顶部的 **Get API key** 按钮。
   - 也可以直接访问 [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)。
3. 点击 **Create API key**。
4. 选择要关联此密钥的 Google Cloud 项目。
   - 如果没有现有项目，选择 **Create API key in new project** 会自动创建。
5. 复制生成的密钥 (以 `AIza...` 开头)。
   - 完整密钥只会显示一次，请妥善保存。
6. 将复制的密钥粘贴到 `vrclt` 设置标签页中的 **API 密钥** 字段，
   或写入 `config.yaml` 的 `gemini.api_key`。

> **注意**: Gemini API 有带每分钟请求限制的免费层，个人使用通常足够。
> 不要分享你的 API 密钥。它会以明文保存在 `config.yaml` 中，因此不要把该文件提交到公开仓库。

## 快速开始

### 发布版 exe

1. 运行 `vrclt-v<version>-windows-x64.exe`。
2. 打开设置标签页。
3. 设置 Gemini API 密钥、应用模式、麦克风和翻译语音输出设备。
4. 翻译语音输出设备使用 `CABLE Input`。
5. 在 VRChat 或 Discord 中，将麦克风输入设置为 **CABLE Output (VB-Audio Virtual Cable)**。
6. 保存设置。运行时会自动重启。

发布版 exe 会把设置保存到:

```text
%LOCALAPPDATA%\vrclt\config.yaml
```

API 密钥会以明文保存在该文件中。

### 源码检出

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m vrclt run --app vrchat
```

源码检出会读取仓库根目录下的 `config.yaml`。如果想在打开应用前创建本地默认值，
请复制 `config.example.yaml`。

```powershell
Copy-Item config.example.yaml config.yaml
```

开发/调试时可以使用 `VRCLT_CONFIG` 环境变量覆盖配置文件路径。

## 应用模式

| 模式 | 适用对象 | 行为 |
| --- | --- | --- |
| `vrchat` | VRChat | 捕获 `VRChat.exe` 音频，启用 OSC 聊天框、角色 OSC 控制、SteamVR 字幕和手腕 UI |
| `discord` | Discord | 捕获 `Discord.exe` 音频，禁用 VRChat OSC/SteamVR 功能，保留原生应用 UI |

可以在设置中选择模式，也可以只为一次启动传入参数:

```powershell
.\vrclt.exe run --app vrchat
.\vrclt.exe run --app discord
```

若要在 VRChat 中使用仅文本行为，请在仪表板或设置中启用 **仅文本**。
原始麦克风会直通到 VRChat，Gemini 翻译结果只会作为 OSC 聊天框文本发送，
不会输出翻译语音。

如果使用 Discord Canary 或 PTB，请在设置或 `app.profiles.discord.process`
中修改 Discord 进程名。

## 原生 UI

仪表板:

- 运行时状态和连接状态
- VRChat/Discord 模式切换和 VRChat 仅文本切换
- 翻译 ON/OFF
- 字幕 ON/OFF
- 输出语言和字幕语言
- PC 字幕位置移动/重置和字号
- 实时字幕预览

设置:

- API 密钥和模型
- 应用模式和目标进程
- 麦克风、翻译语音输出、监听输出和入站音频设备
- 语言列表
- 音频阈值和 VAD 设置
- OSC、聊天框、SteamVR 叠加层和手腕 UI 选项
- UI 语言和 UI 模式

日志/关于:

- 当前配置路径
- 当前日志文件路径
- 最近日志内容

关闭窗口时，应用会隐藏到托盘。若要停止运行时并完全退出，请使用托盘中的
`Quit` 或 `退出` 操作。

## 音频路由

出站翻译:

```text
microphone -> Gemini Live -> translated voice -> CABLE Input
                                     target app mic <- CABLE Output
```

入站字幕:

```text
target app process audio -> ProcTap -> Gemini Live -> subtitles
```

翻译关闭时，麦克风不会经过 Gemini，而是直接发送到 `CABLE Input`。
在 VRChat **仅文本** 模式中，原始语音始终 passthrough，翻译开关只控制
Gemini 文本翻译和聊天框输出。

## VRChat 功能

VRChat 模式可使用:

- 翻译文本的 OSC 聊天框输出
- `VRCLT_Enabled`、`VRCLT_Lang` 等角色 OSC 参数
- 用于入站字幕的 SteamVR 字幕叠加层
- 可在 VR 内控制的 SteamVR 手腕菜单

使用 `ui.mode: auto` 时，SteamVR 运行后会启用 VR 功能。使用 `ui.mode: vr`
可强制启用 VR 叠加层，使用 `ui.mode: desktop` 可保持禁用。

## 文件和路径

| 项目 | 发布版 exe | 源码检出 |
| --- | --- | --- |
| 配置 | `%LOCALAPPDATA%\vrclt\config.yaml` | 仓库根目录中的 `config.yaml` |
| 配置路径覆盖 | `VRCLT_CONFIG` | `VRCLT_CONFIG` |
| 日志 | `%LOCALAPPDATA%\vrclt\logs\vrclt.log` | `%LOCALAPPDATA%\vrclt\logs\vrclt.log` |
| 构建输出 | `dist\vrclt.exe` | `dist\vrclt.exe` |

不要提交 `config.yaml`、`.venv/`、`build/`、`dist/`、`release/` 或日志文件。

## 配置值说明

所有值都保存在 `config.yaml` 中。发布版使用上面列出的 AppData 路径；
源码检出在未设置 `VRCLT_CONFIG` 时使用仓库根目录的 `config.yaml`。

顶层值和应用配置:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `api_key` | `""` | Gemini API 密钥。留空时可使用 `GEMINI_API_KEY` 环境变量。 |
| `model` | `gemini-3.5-live-translate-preview` | Gemini Live 模型名。 |
| `log_level` | `INFO` | Python 日志级别。 |
| `app.mode` | `vrchat` | 当前配置: `vrchat` 或 `discord`。 |
| `app.profiles.<mode>.process` | `VRChat.exe` / `Discord.exe` | 入站字幕要捕获的进程。 |
| `app.profiles.<mode>.ui_mode` | `auto` / `desktop` | 此配置应用的 UI 模式。 |
| `app.profiles.<mode>.voice_output` | `true` | 启用翻译语音输出。 |
| `app.profiles.<mode>.passthrough_while_translating` | `false` | 翻译过程中也发送原始麦克风音频。 |
| `app.profiles.<mode>.chatbox` | `true` / `false` | 启用 VRChat OSC 聊天框输出。 |
| `app.profiles.<mode>.osc_control` | `true` / `false` | 启用角色 OSC 控制监听器。 |
| `app.profiles.<mode>.vr_overlay` | `true` / `false` | 启用 SteamVR 字幕叠加层。 |
| `app.profiles.<mode>.wrist_ui` | `true` / `false` | 启用 SteamVR 手腕菜单。 |

仪表板状态:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `dashboard.translation_on` | `true` | 上次保存的仪表板翻译开关状态。 |
| `dashboard.subtitles_on` | `true` | 上次保存的仪表板字幕开关状态。 |

出站翻译:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `outbound.enabled` | `true` | 启用出站管线。 |
| `outbound.target_language` | `ja` | 翻译你说话内容的默认目标语言。 |
| `outbound.echo_target_language` | `false` | 对已经是目标语言的输入也进行复述。 |
| `outbound.mic_device` | `""` | 麦克风设备名片段。留空时使用默认输入。 |
| `outbound.tts_device` | `CABLE Input` | 翻译语音和原声直通的输出设备。 |
| `outbound.monitor_device` | `""` | 可选的本地翻译语音监听输出。 |
| `outbound.text_only` | `false` | VRChat 仅文本模式。使用原声直通和翻译聊天框文本。 |
| `outbound.voice_output` | `true` | 启用翻译 TTS 音频输出。 |
| `outbound.passthrough_while_translating` | `false` | 翻译启用时也发送原始麦克风音频。 |
| `outbound.chatbox` | `true` | 将翻译文本发送到 VRChat OSC 聊天框。 |

入站字幕:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `inbound.enabled` | `true` | 启用用于字幕的进程音频捕获。 |
| `inbound.target_language` | `ko` | 默认字幕目标语言。 |
| `inbound.languages` | `[ko, en, ja]` | 手腕菜单中循环的字幕语言列表。 |
| `inbound.process` | `VRChat.exe` | 入站字幕要捕获的进程名。 |
| `inbound.play_audio` | `false` | 将入站翻译语音播放到你的耳机。 |
| `inbound.audio_device` | `""` | 入站翻译语音输出设备。留空时使用默认输出。 |
| `inbound.vad_enabled` | `true` | 使用语音活动检测过滤背景音乐/噪声。 |
| `inbound.vad_threshold` | `0.5` | `0` 到 `1` 的 VAD 严格度。越高越多过滤非语音。 |
| `inbound.vad_hangover_sec` | `0.6` | 说话停止后继续短暂捕获的时间。 |

叠加层和 OSC:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `overlay.enabled` | `true` | 启用 SteamVR 字幕叠加层。 |
| `overlay.width_m` | `0.9` | 字幕叠加层宽度，单位米。 |
| `overlay.distance_m` | `1.2` | 字幕叠加层相对 HMD 的距离，单位米。 |
| `overlay.below_m` | `0.35` | HMD 下方偏移，单位米。 |
| `overlay.tilt_deg` | `-15.0` | 叠加层倾斜角度。 |
| `overlay.transform` | `null` | 在 VR 中重新定位后自动保存的精确 3x4 字幕姿态。 |
| `overlay.font` | `bundled:NotoSansCJKkr-Regular.otf` | 字幕叠加层字体。 |
| `overlay.font_size` | `44` | 字幕字号。 |
| `overlay.display_sec` | `7.0` | 已确认字幕行保留显示的时间。 |
| `overlay.lines` | `3` | 屏幕上保留的最近确认字幕行数。 |
| `overlay.show_source` | `false` | 在字幕中同时显示原文。 |
| `osc.ip` | `127.0.0.1` | VRChat OSC 目标 IP。 |
| `osc.port` | `9000` | VRChat OSC 目标端口。 |
| `osc.throttle_sec` | `1.5` | 聊天框最小发送间隔。 |
| `osc.notification_sfx` | `false` | 请求 VRChat 聊天框提示音。 |
| `osc.show_source` | `true` | 在聊天框中将原文显示在翻译上方。 |
| `osc.chunk_display_sec` | `4.0` | 长聊天框消息分段显示时每段的显示时间。 |

音频、控制、UI、手腕菜单:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `audio.send_interval_ms` | `100` | 将麦克风音频发送到 Gemini 的间隔。 |
| `audio.finalize_silence_sec` | `2.0` | 静音达到此秒数后确认一个片段。 |
| `audio.mic_idle_disconnect_sec` | `15.0` | 麦克风空闲达到此秒数后断开 Gemini 会话。 |
| `audio.voice_rms_threshold` | `90.0` | 麦克风语音检测能量阈值。 |
| `audio.voice_hangover_sec` | `2.5` | 在短暂停顿期间保持麦克风回合的时间。 |
| `audio.echo_guard_multiplier` | `4.0` | 目标应用音频活跃时提高麦克风门限的倍数。`1.0` 表示禁用。 |
| `control.enabled` | `true` | 启用角色 OSC 控制输入。 |
| `control.osc_listen_port` | `9001` | 接收角色控制参数的本地 OSC 端口。 |
| `control.param_enabled` | `VRCLT_Enabled` | 翻译 ON/OFF 用角色 bool 参数。 |
| `control.param_lang` | `VRCLT_Lang` | 语言索引用角色 int 参数。 |
| `control.languages` | `[ja, en, ko, zh-Hans, zh-Hant, yue, es, ru, fr, de]` | 角色和手腕控制使用的输出语言列表。 |
| `control.feedback_chatbox` | `true` | 将控制变更反馈发送到 VRChat 聊天框。 |
| `ui.mode` | `auto` | `auto`、`vr` 或 `desktop`。 |
| `ui.lang` | `""` | UI 显示语言。留空为自动，可用 `en`、`ko`、`ja`、`zh`。 |
| `ui.close_action` | `tray` | 窗口关闭按钮行为: `tray` 或 `exit`。 |
| `wrist_ui.enabled` | `true` | 启用 SteamVR 手腕菜单。 |
| `wrist_ui.hand` | `left` | 佩戴菜单的手: `left` 或 `right`。 |
| `wrist_ui.width_m` | `0.16` | 手腕菜单宽度，单位米。 |
| `wrist_ui.offset` | `[-0.0509, -0.065, 0.0891]` | 控制器坐标系中的 x,y,z 偏移。 |
| `wrist_ui.tilt_deg` | `185.636` | 朝向脸部的额外倾斜。 |
| `wrist_ui.roll_deg` | `-28.633` | 平面内旋转。`null` 时按左右手自动旋转。 |
| `wrist_ui.transform` | saved 3x4 pose | 在 VR 中重新定位后自动保存的精确 3x4 手腕姿态。 |
| `wrist_ui.pointer_tilt_deg` | `50.0` | 指针射线向下倾斜角度。 |
| `wrist_ui.font` | `bundled:NotoSansCJKkr-Bold.otf` | 手腕菜单字体。 |

## 构建

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
```

构建结果:

```text
dist\vrclt.exe
```

创建发布产物:

```powershell
.\scripts\package_release.ps1 -Version 0.1.0
```

发布脚本会生成:

```text
release\vrclt-v0.1.0-windows-x64.exe
release\vrclt-v0.1.0-windows-x64.exe.sha256
```

## 冒烟测试

```powershell
.\.venv\Scripts\python.exe -m compileall vrclt
.\.venv\Scripts\python.exe -m vrclt --help
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
.\scripts\package_release.ps1 -Version 0.1.0 -SkipBuild
```

实际运行时测试流程: 运行 exe，在原生 UI 中保存设置，确认
`%LOCALAPPDATA%\vrclt\config.yaml` 已写入，并验证目标应用能从
`CABLE Output` 接收音频。

## 故障排查

- 目标应用没有收到翻译语音: 确认 `outbound.tts_device` 是 `CABLE Input`，且目标应用麦克风是 `CABLE Output`。
- 入站字幕不显示: 确认目标进程名与正在运行的应用一致，例如 `VRChat.exe` 或 `Discord.exe`。
- 运行时提示需要 API 密钥: 在设置中输入密钥，或设置 `GEMINI_API_KEY`。
- VR 叠加层不显示: 确认 SteamVR 正在运行，且 `overlay.enabled` / `wrist_ui.enabled` 已启用。
- 想重置设置: 关闭应用，将 `%LOCALAPPDATA%\vrclt\config.yaml` 移到其他名称，然后重新启动。

## 致谢

- [Noto Sans CJK](https://github.com/notofonts/noto-cjk) 和 [Pretendard](https://github.com/orioncactus/pretendard): 多语言 UI 字体覆盖。
- [PySide6](https://doc.qt.io/qtforpython-6/): Windows 原生 UI。
- [OpenVR](https://github.com/ValveSoftware/openvr)、GLFW、PyOpenGL: SteamVR 叠加层渲染。
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/): 应用之间的音频路由。

## 发布

发布流程请参考 [docs/RELEASING.md](docs/RELEASING.md)。
