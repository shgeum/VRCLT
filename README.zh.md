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
- 两种翻译引擎: Google Gemini Live（默认），以及面向无法访问 Google 的地区（如中国大陆）的 Alibaba Qwen3.5 LiveTranslate
- 支持 VRChat OSC 聊天框输出、角色 OSC 控制、SteamVR 字幕和手腕菜单
- 支持 SteamVR 仪表板设置面板和随 SteamVR 自动启动（注册到启动/叠加层应用）
- VRChat 仅文本模式: 保留原始语音直通，只向 OSC 聊天框追加翻译文本
- Discord 模式: 捕获 Discord 进程音频，并自动禁用 VRChat 专用功能
- 自定义模式: 捕获任意其他应用，从当前正在播放音频的进程中直接选择
- 原声直通直接使用 48 kHz 原始麦克风流，Gemini 翻译流单独重采样
- GitHub Releases 更新提醒，以及保留 API 密钥、已保存语言列表、UI 语言、窗口关闭行为和已选择音频设备的安全配置重置
- 可从 [VRCLT Releases](https://github.com/shgeum/VRCLT/releases) 下载的 Windows exe
- 用户设置保存位置: `%LOCALAPPDATA%\vrclt\config.yaml`

## 安装

### 要求

- 推荐 Windows 11
- Google Gemini API 密钥 — 或用于 Qwen 引擎的阿里云百炼 (Model Studio / DashScope) API 密钥 (获取方式见下方)
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
- 使用 VR 叠加层和手腕 UI 时需要 SteamVR
- 使用 VRChat 聊天框/角色控制功能时需要启用 VRChat OSC
- 从源码运行时需要 Python 3.12

### 1. 下载 vrclt

最新 Windows 可执行文件可在 [VRCLT Releases](https://github.com/shgeum/VRCLT/releases) 下载。

请下载类似下面名称的文件。

```text
vrclt-v<version>-windows-x64.exe
```

发布版 exe 会把设置保存到:

```text
%LOCALAPPDATA%\vrclt\config.yaml
```

API 密钥会以明文保存在该文件中。

### 2. 安装 VB-Audio Virtual Cable

如果想让 VRChat 或 Discord 把翻译语音当作麦克风输入，需要安装 VB-Audio Virtual Cable。

1. 从 [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) 下载 **VB-CABLE**。
2. 解压下载的 ZIP 文件。
3. 右键点击 `VBCABLE_Setup_x64.exe`，选择 **以管理员身份运行**。
4. 点击 **Install Driver**。
5. 如果看不到 `CABLE Input` / `CABLE Output`，请重启 Windows。

安装后，Windows 会出现两个重要设备:

| 设备 | 含义 | 在哪里选择 |
| --- | --- | --- |
| `CABLE Input` | 虚拟线缆的播放/输出侧 | 在 vrclt 中选择为翻译语音输出 |
| `CABLE Output` | 虚拟线缆的录音/麦克风侧 | 在 VRChat 或 Discord 中选择为麦克风 |

真实麦克风应在 vrclt 中选择。若要让对方听到翻译语音，VRChat/Discord 的麦克风不要选真实麦克风，而要选 `CABLE Output`。

### 3. 获取 Gemini API 密钥

> **中国大陆用户**: 无法访问 Google 服务时，请跳过本节，直接使用 Qwen 引擎 — 见下文 **3b** 节。

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

### 3b. 备选: Qwen API 密钥（无法访问 Gemini 的地区）

如果所在地区无法访问 Google 服务（例如中国大陆），vrclt 可以使用
**Alibaba Qwen3.5 LiveTranslate** 代替 Gemini:

1. 创建阿里云账号并开通 **百炼 (Model Studio)**:
   - 中国大陆: [bailian.console.aliyun.com](https://bailian.console.aliyun.com/)
   - 国际版（新加坡）: [Alibaba Cloud Model Studio](https://www.alibabacloud.com/en/product/modelstudio)
2. 创建 API 密钥（DashScope 密钥，以 `sk-...` 开头）。
   **密钥与地域绑定**: 大陆（北京）密钥只能配合 `beijing` 端点使用，
   国际版密钥只能配合 `intl` 使用。
3. 在 vrclt 设置中将 **翻译引擎** 设为 `qwen`，把密钥粘贴到
   **Qwen API 密钥 (DashScope)**，并选择与密钥匹配的 **Qwen 服务器**
   （中国大陆选 `beijing`，其他地区选 `intl`）。密钥也可以通过
   `DASHSCOPE_API_KEY` 环境变量提供。
4. **Qwen 工作空间 ID — `intl` 必填**: 国际版（新加坡）端点只通过工作空间
   专属域名提供服务。在百炼控制台首页点击左下角图标，打开
   **业务空间详情 (Workspace Details)**，复制 ID（形如 `llm-7c72iiw36kd8****`）
   填入 **Qwen 工作空间 ID** 字段。`beijing` 端点可以留空（经典共享
   `dashscope` 域名）。
   参见 [Obtain the workspace ID](https://www.alibabacloud.com/help/en/model-studio/obtain-api-key-app-id-and-workspace-id)。
5. 设置 **我的语音语言** 和 **对方语音语言** — Qwen 无法自动检测语音语言
   （见下文"翻译引擎"一节）。

### 4. 首次启动设置

1. 运行 `vrclt-v<version>-windows-x64.exe`。
2. 打开设置标签页，配置要使用的翻译引擎:

   **使用 Qwen（中国大陆推荐）**
   1. 将 **翻译引擎** 设为 `qwen`。
   2. 把 DashScope 密钥粘贴到 **Qwen API 密钥 (DashScope)**（见 3b 节），
      并选择与密钥地域匹配的 **Qwen 服务器**（中国大陆选 `beijing`，
      其他地区选 `intl`）。
   3. 使用 `intl` 时: 填写 **Qwen 工作空间 ID**（见 3b 节）。
   4. 设置 **我的语音语言**（你说的语言）和 **对方语音语言**（游戏里
      对方说的语言）。Qwen 无法自动检测，留空会按英语处理。这两项之后
      也可以在仪表盘标签页或 SteamVR 仪表盘面板上修改。

   **使用 Gemini（默认，需要能访问 Google 服务）**
   1. 把 Gemini API 密钥粘贴到 **Gemini API 密钥**（见第 3 节）。引擎设置
      到此为止 — Gemini 会自动检测语音语言。

3. 选择应用模式: `vrchat`、`discord` 或 `custom`（选 `custom` 后在设置中选择要捕获的应用）。
4. **麦克风输入**选择你的真实麦克风。
5. **语音输出**或翻译语音输出设备选择 `CABLE Input`。
6. 在 VRChat 或 Discord 中，将麦克风输入设置为 **CABLE Output (VB-Audio Virtual Cable)**。
7. 保存设置。运行时会自动重启。

## 故障排查

- 目标应用没有收到翻译语音: 确认 `outbound.tts_device` 是 `CABLE Input`，且目标应用麦克风是 `CABLE Output`。
- 入站字幕不显示: 确认目标进程名与正在运行的应用一致，例如 `VRChat.exe` 或 `Discord.exe`。
- 运行时提示需要 API 密钥: 在设置中输入密钥，或设置 `GEMINI_API_KEY`（Qwen 引擎为 `DASHSCOPE_API_KEY`）。
- Qwen 密钥被拒绝或连接立即失败: 检查 `qwen.endpoint` 是否与密钥的地域匹配 — `beijing` 密钥和 `intl` 密钥不能混用 — 并确认使用 `intl` 时已设置工作空间 ID。
- Qwen 报错 `Voice '...' is not supported`: 字面值音色 `default` 只在声音复刻启用时可用。请保持 `qwen.voice_clone` 开启，或将 **Qwen 语音 ID** 留空以使用模型默认音色。
- Qwen 从错误的语言进行翻译: 设置 **我的语音语言** / **对方语音语言**（在设置、仪表板或 SteamVR 面板中均可）。Qwen 无法自动检测；留空按英语处理。
- VR 叠加层不显示: 确认 SteamVR 正在运行，且 `overlay.enabled` / `wrist_ui.enabled` 已启用。
- passthrough 或字幕延迟较大: 先使用本 README 中的默认值；如果连接稳定，再谨慎降低 `audio.turn_end_silence_sec`、`audio.inbound_turn_end_silence_sec` 或 `audio.subtitle_finalize_silence_sec`。
- 想重置设置: 使用设置标签页中的 **恢复默认设置**。它会保留 API 密钥、输出语言列表、字幕语言列表、UI 语言、窗口关闭行为和已选择音频设备，并将其他设置恢复默认。应用更新后，vrclt 也会就此重置询问一次。

## 翻译引擎

vrclt 支持两种实时翻译引擎，通过 **翻译引擎** 设置（`config.yaml` 中的
`provider`）选择。该选择同时作用于两个方向: 你的语音和入站字幕。

| | Gemini Live（默认） | Qwen3.5 LiveTranslate |
| --- | --- | --- |
| 提供方 / 密钥 | Google AI Studio (`GEMINI_API_KEY`) | 阿里云百炼 / DashScope (`DASHSCOPE_API_KEY`) |
| 必要设置 | 仅需 API 密钥 | 引擎设为 `qwen`、API 密钥 + 服务器（`intl` 还需工作空间 ID）、**我的/对方语音语言** |
| 中国大陆可用性 | 需要能访问 Google 服务 | 可直连 `beijing` 端点 |
| 语音语言检测 | 自动检测 | **手动** — 需设置"我的/对方语音语言" |
| 支持语言 | 70+ 种 BCP-47 目标语言，含 `zh-Hans`/`zh-Hant` | 29 种带语音 + 另外 31 种仅文本；中文只有 `zh`（不区分简体/繁体）；粤语（`yue`）仅文本 |
| 翻译语音 | 复刻说话者音色 | 通过服务端声音复刻还原说话者音色（`qwen.voice_clone`，默认 `once`）；关闭复刻时使用固定音色 |
| 抢话打断（barge-in） | 支持 | 不支持 — 同时说话时音频可能排队播放 |

Qwen 注意事项:

- **必须设置语音语言。** 可在设置标签页、仪表板标签页或 SteamVR 仪表板面板的
  底部一行设置。留空按英语处理。
- `zh-Hans`/`zh-Hant` 目标语言发送给 Qwen 时都会作为 `zh`。
- 如果所选目标语言没有 Qwen 语音支持，vrclt 会自动以仅文本方式运行会话
  （聊天框/字幕仍正常工作）。
- 端点: `intl`（新加坡）或 `beijing`。`intl` **必须**设置百炼工作空间 ID；
  `beijing` 无需设置（见上文 3b 节）。
- 声音复刻: `qwen.voice_clone: once`（默认）在会话开始时复刻说话者音色 —
  适合你自己的麦克风，且音频延迟低。`always` 对每次回复重新复刻（适合多人
  说话的音频，但合成开始会明显变慢）；`off` 使用模型默认音色，或使用
  `qwen.voice` 中预先复刻的语音 ID（`qwen-translate-vc-...`）。

## 应用模式

| 模式 | 适用对象 | 行为 |
| --- | --- | --- |
| `vrchat` | VRChat | 捕获 `VRChat.exe` 音频，启用 OSC 聊天框、角色 OSC 控制、SteamVR 字幕和手腕 UI |
| `discord` | Discord | 捕获根 `Discord.exe` 进程树音频，禁用 VRChat OSC/SteamVR 功能，保留 PC UI 和桌面字幕 |
| `custom` | 任意其他应用 | 捕获在设置中选定的进程，保留 SteamVR 字幕和手腕菜单，禁用 VRChat OSC 功能 |

可以在设置中选择模式，也可以只为一次启动传入参数:

```powershell
.\vrclt.exe run --app vrchat
.\vrclt.exe run --app discord
.\vrclt.exe run --app custom
```

若要在 VRChat 中使用仅文本行为，请在仪表板或设置中启用 **仅文本**。
原始麦克风会直通到 VRChat，Gemini 翻译结果只会作为 OSC 聊天框文本发送，
不会输出翻译语音。

如果使用 Discord Canary 或 PTB，请在设置或 `app.profiles.discord.process`
中修改 Discord 进程名。

若要为其他应用（浏览器、媒体播放器、别的游戏）生成字幕，请切换到 **自定义**
模式，并在设置中指定 **自定义捕获进程**。打开该下拉列表会列出持有 Windows
音频会话的进程，当前正在播放声音的会带标记并排在最前，因此无需事先知道 exe
名称。**捕获进程** 使用同一个选择器，显示此刻实际捕获的目标。

## 原生 UI

仪表板:

- 运行时状态和连接状态
- VRChat/Discord/自定义 模式切换和 VRChat 仅文本切换
- 翻译 ON/OFF
- 字幕 ON/OFF
- 使用 PC 全局热键切换翻译/字幕
- 输出语言和字幕语言，并可搜索添加 Gemini Live Translation 支持的 70+ 种语言
- 麦克风输入和翻译语音输出设备选择，附输出测试音按钮；刷新设备会重启运行时并识别后插入的设备
- 翻译语音音量滑块和带检测阈值标记的实时麦克风电平表
- Qwen 引擎的我的/对方语音语言选择器（Gemini 下禁用，因其自动检测）
- PC 字幕位置移动/重置、字幕框大小和字号
- 实时字幕预览

设置:

- 翻译引擎（Gemini / Qwen）、API 密钥、模型，以及 Qwen 端点/工作空间
- 应用模式和目标进程
- 麦克风、翻译语音输出、监听输出和入站音频设备
- 默认目标语言和已保存语言列表
- PC 全局热键设置
- 音频阈值和 VAD 设置
- 保留 API 密钥、输出语言列表、字幕语言列表、UI 语言、窗口关闭行为和已选择音频设备的恢复默认设置按钮
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

原声 passthrough 直接使用捕获到的 48 kHz 麦克风流，Gemini 翻译流会单独重采样。
因此 passthrough 不需要等待翻译会话，也能减少不必要的音质损失。

## VRChat 功能

VRChat 模式可使用:

- 翻译文本的 OSC 聊天框输出
- `VRCLT_Enabled`、`VRCLT_Lang` 等角色 OSC 参数
- 用于入站字幕的 SteamVR 字幕叠加层
- 可在 VR 内控制的 SteamVR 手腕菜单 — 含运行时重启、字幕字号和连接/错误状态显示
- SteamVR 仪表板设置面板（打开 SteamVR 菜单并选择 vrclt 图标）；包含麦克风和语音输出设备选择 — 最后一次点击稍后会随运行时重启一起生效 — 以及翻译语音音量和错误状态显示（正在重连、配额用尽、API 密钥无效），还有 Qwen 引擎的语音语言一行
- 随 SteamVR 自动启动: 发布版 exe 会自动注册到 SteamVR 设置 > 启动/叠加层应用，可在 SteamVR 设置或 vrclt 设置中开关自动启动
- 更新到新版本后请先运行一次新 exe。注册本身会保留，但自动启动指向的 exe 路径需要首次运行时才会更新为新文件
- VR 字幕编辑 laser/cursor 显示和角落尺寸调整手柄

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
| `provider` | `gemini` | 同时作用于两条管线的翻译引擎: `gemini` 或 `qwen`。 |
| `api_key` | `""` | Gemini API 密钥。留空时可使用 `GEMINI_API_KEY` 环境变量。 |
| `model` | `gemini-3.5-live-translate-preview` | Gemini Live 模型名。 |
| `qwen.api_key` | `""` | DashScope API 密钥。留空时可使用 `DASHSCOPE_API_KEY` 环境变量。 |
| `qwen.model` | `qwen3.5-livetranslate-flash-realtime` | Qwen 实时翻译模型名。 |
| `qwen.endpoint` | `intl` | `intl`（新加坡）或 `beijing`（中国大陆）。密钥与地域绑定。 |
| `qwen.workspace_id` | `""` | 百炼工作空间 ID（`maas.aliyuncs.com` 域名）。`intl` 必填；`beijing` 可留空。 |
| `qwen.base_url` | `""` | 高级: 覆盖完整 `wss://` URL。 |
| `qwen.voice_clone` | `once` | 服务端说话者声音复刻: `once`（会话开始时，低延迟）、`always`（每次回复，较慢）或 `off`。 |
| `qwen.voice` | `""` | 复刻为 `off` 时: 留空 = 模型默认音色，或预先复刻的语音 ID（`qwen-translate-vc-...`）。 |
| `log_level` | `INFO` | Python 日志级别。 |
| `meta.last_version` | `""` | 当前配置已确认的最后应用版本。用于更新后的一次性重置确认。 |
| `app.mode` | `vrchat` | 当前配置: `vrchat`、`discord` 或 `custom`。 |
| `app.profiles.<mode>.process` | `VRChat.exe` / `Discord.exe` / 留空 | 入站字幕要捕获的进程。留空（自定义配置的默认值）表示沿用当前捕获目标。 |
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

PC 热键:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `hotkeys.enabled` | `true` | 启用 Windows 全局热键。 |
| `hotkeys.translation_toggle` | `Ctrl+Alt+T` | 翻译 ON/OFF 切换热键。留空会禁用该热键。 |
| `hotkeys.subtitles_toggle` | `Ctrl+Alt+S` | 字幕 ON/OFF 切换热键。留空会禁用该热键。 |
| `hotkeys.enabled_in_vr` | `true` | SteamVR 运行时保持全局热键有效。 |
| `hotkeys.translation_hold` | `""` | 按住期间暂停翻译（原声直通）的热键。留空会禁用。 |

出站翻译:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `outbound.enabled` | `true` | 启用出站管线。 |
| `outbound.target_language` | `ja` | 翻译你说话内容的默认 BCP-47 语言代码。可在 UI 中搜索并选择 Gemini Live Translation 支持的 70+ 种语言。 |
| `outbound.source_language` | `""` | 我的语音语言。Qwen 必填（无自动检测；留空按英语处理）。Gemini 会忽略。 |
| `outbound.echo_target_language` | `false` | 对已经是目标语言的输入也进行复述。 |
| `outbound.mic_device` | `""` | 麦克风设备名片段。留空时使用默认输入。 |
| `outbound.tts_device` | `CABLE Input` | 翻译语音和原声直通的输出设备。 |
| `outbound.tts_gain` | `1.0` | 翻译语音音量 `0.0`–`2.0`（也应用于监听输出；原声直通保持不变）。 |
| `outbound.monitor_device` | `""` | 可选的本地翻译语音监听输出。 |
| `outbound.text_only` | `false` | VRChat 仅文本模式。使用原声直通和翻译聊天框文本。 |
| `outbound.voice_output` | `true` | 启用翻译 TTS 音频输出。 |
| `outbound.passthrough_while_translating` | `false` | 翻译启用时也发送原始麦克风音频。 |
| `outbound.chatbox` | `true` | 将翻译文本发送到 VRChat OSC 聊天框。 |
| `outbound.glossary` | `""` | 翻译词汇表。每行 `原文=译文`，用于固定名字/术语的译法。 |

入站字幕:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `inbound.enabled` | `true` | 启用用于字幕的进程音频捕获。 |
| `inbound.target_language` | `ko` | 默认字幕 BCP-47 语言代码。可在 UI 中搜索并选择 Gemini Live Translation 支持的 70+ 种语言。 |
| `inbound.source_language` | `""` | 对方语音语言（仅 Qwen，规则与 `outbound.source_language` 相同）。 |
| `inbound.languages` | `[ko, en, ja]` | 仪表板和手腕菜单使用的已保存字幕语言列表。只从 UI 选择器中添加需要的语言。 |
| `inbound.process` | `VRChat.exe` | 入站字幕要捕获的进程名。 |
| `inbound.play_audio` | `false` | 将入站翻译语音播放到你的耳机。 |
| `inbound.audio_device` | `""` | 入站翻译语音输出设备。留空时使用默认输出。 |
| `inbound.vad_enabled` | `true` | 使用语音活动检测过滤背景音乐/噪声。 |
| `inbound.vad_threshold` | `0.5` | `0` 到 `1` 的 VAD 严格度。越高越多过滤非语音。 |
| `inbound.vad_hangover_sec` | `0.35` | 说话停止后继续短暂捕获的时间。数值越低，字幕尾部延迟越小。 |

叠加层和 OSC:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `overlay.enabled` | `true` | 启用 SteamVR 字幕叠加层。 |
| `overlay.width_m` | `0.9` | 字幕叠加层宽度，单位米。 |
| `overlay.height_m` | `0.225` | 字幕叠加层高度，单位米。 |
| `overlay.distance_m` | `1.2` | 字幕叠加层相对 HMD 的距离，单位米。 |
| `overlay.below_m` | `0.35` | HMD 下方偏移，单位米。 |
| `overlay.tilt_deg` | `-15.0` | 叠加层倾斜角度。 |
| `overlay.transform` | `null` | 在 VR 中重新定位后自动保存的精确 3x4 字幕姿态。 |
| `overlay.font` | `bundled:NotoSansCJKkr-Regular.otf` | 字幕叠加层字体。 |
| `overlay.font_size` | `27` | 字幕字号。 |
| `overlay.display_sec` | `7.0` | 已确认字幕行保留显示的时间。 |
| `overlay.lines` | `3` | 屏幕上保留的最近确认字幕行数。 |
| `overlay.show_source` | `false` | 在字幕中同时显示原文。 |
| `osc.ip` | `127.0.0.1` | VRChat OSC 目标 IP。 |
| `osc.port` | `9000` | VRChat OSC 目标端口。 |
| `osc.throttle_sec` | `1.5` | 聊天框最小发送间隔，包括实时 partial 更新。 |
| `osc.notification_sfx` | `false` | 请求 VRChat 聊天框提示音。 |
| `osc.show_source` | `true` | 在聊天框中将原文显示在翻译上方。 |
| `osc.stream_sentences` | `true` | 每说完一句立即发送到聊天框，并在同一个气泡内滚动显示最近的句子。`false` 恢复旧行为（长片段按 `chunk_display_sec` 间隔分段重放）。 |
| `osc.chunk_display_sec` | `4.0` | 长聊天框消息分段显示时每段的显示时间。 |

音频、控制、UI、手腕菜单:

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `audio.send_interval_ms` | `50` | 将麦克风音频发送到 Gemini 的间隔。数值越低翻译延迟越小，但网络发送量会略增。 |
| `audio.finalize_silence_sec` | `2.0` | 静音达到此秒数后确认一个片段。 |
| `audio.mic_idle_disconnect_sec` | `15.0` | 麦克风空闲达到此秒数后断开 Gemini 会话。 |
| `audio.voice_rms_threshold` | `90.0` | 麦克风语音检测能量阈值。 |
| `audio.voice_hangover_sec` | `2.5` | 在短暂停顿期间保持麦克风回合的时间。 |
| `audio.turn_end_silence_sec` | `0.55` | 实际麦克风静音达到此秒数后，补回被门限裁掉的静音，让服务端语音检测结束回合、模型把句子说完。降低它可能减少翻译语音延迟。 |
| `audio.inbound_turn_end_silence_sec` | `0.35` | 入站字幕会话使用的更快回合结束。 |
| `audio.subtitle_partial_interval_sec` | `0.15` | 字幕行确认前的实时刷新间隔。 |
| `audio.subtitle_finalize_silence_sec` | `0.8` | 确认入站字幕行前所需的静音时间。 |
| `audio.echo_guard_multiplier` | `4.0` | 目标应用音频活跃时提高麦克风门限的倍数。`1.0` 表示禁用。 |
| `audio.echo_guard_hold_sec` | `1.2` | 目标应用语音活跃时阻断 outbound 麦克风输入的保持时间。 |
| `audio.echo_guard_barge_in_multiplier` | `3.0` | 回声防护期间仍允许更大的本地语音通过。数值越低，同时说话越容易通过。 |
| `control.enabled` | `true` | 启用角色 OSC 控制输入。 |
| `control.osc_listen_port` | `9001` | 接收角色控制参数的本地 OSC 端口。 |
| `control.param_enabled` | `VRCLT_Enabled` | 翻译 ON/OFF 用角色 bool 参数。 |
| `control.param_lang` | `VRCLT_Lang` | 语言索引用角色 int 参数。 |
| `control.languages` | `[ja, en, ko, zh-Hans, zh-Hant, yue, es, ru, fr, de]` | 仪表板、角色和手腕控制使用的已保存输出语言列表。只从 UI 选择器中添加需要的语言。 |
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

## 从源码运行

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

## 致谢

- [Noto Sans CJK](https://github.com/notofonts/noto-cjk) 和 [Pretendard](https://github.com/orioncactus/pretendard): 多语言 UI 字体覆盖。
- [PySide6](https://doc.qt.io/qtforpython-6/): Windows 原生 UI。
- [OpenVR](https://github.com/ValveSoftware/openvr)、GLFW、PyOpenGL: SteamVR 叠加层渲染。
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/): 应用之间的音频路由。

## 发布

发布流程请参考 [docs/RELEASING.md](docs/RELEASING.md)。
