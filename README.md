# vrclt

Languages: [English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [中文](README.zh.md)

`vrclt` is a Windows live translator for VRChat and Discord. It translates your
microphone with the Gemini Live API, plays the translated voice into the target
app through VB-Audio Virtual Cable, and shows translated subtitles for other
people's speech.

## Highlights

- Native Windows UI with Dashboard, Settings, and Logs/About tabs
- Tray menu for opening the app, opening settings, toggling translation/subtitles, and quitting
- Outbound translation: your microphone -> Gemini Live -> translated voice -> target app mic
- Inbound subtitles: target app audio -> Gemini Live -> translated subtitles
- VRChat support for OSC chatbox output, avatar OSC controls, SteamVR subtitles, and the wrist menu
- VRC Text Only mode for sending translated chatbox text while passing your original voice through
- Discord mode with Discord process audio capture and VRChat-only features disabled
- Single-file release build: `dist\vrclt.exe`
- User settings stored in `%LOCALAPPDATA%\vrclt\config.yaml`

## Requirements

- Windows 11 recommended
- Google Gemini API key (see instructions below)
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
- SteamVR for VR overlays and wrist UI
- VRChat OSC enabled for chatbox/avatar-control features
- Python 3.12 only if running from source

### How to Get a Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/) and sign in with your Google account.
   - If you do not have a Google account, create one first.
2. Click the **Get API key** button in the left sidebar (or at the top of the page).
   - You can also navigate directly to [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey).
3. Click **Create API key**.
4. Select a Google Cloud project to associate with the key.
   - If you have no existing projects, choose **Create API key in new project** and one will be created automatically.
5. Copy the generated key (it starts with `AIza...`).
   - Store it somewhere safe — it is only shown in full once.
6. Paste the key into the **API Key** field in the vrclt Settings tab,
   or set it as `gemini.api_key` in `config.yaml`.

> **Note**: The Gemini API has a free tier with per-minute request limits that is sufficient for personal use.
> Do not share your API key. It is stored as plain text in `config.yaml`, so do not commit that file to a public repository.

## Quick Start

### Release Executable

1. Run `vrclt-v<version>-windows-x64.exe`.
2. Open the Settings tab.
3. Set the Gemini API key, app mode, microphone, and translated voice output device.
4. Use `CABLE Input` as the translated voice output device.
5. In VRChat or Discord, set the microphone input to **CABLE Output (VB-Audio Virtual Cable)**.
6. Save settings. The runtime restarts automatically.

The release executable stores settings in:

```text
%LOCALAPPDATA%\vrclt\config.yaml
```

The API key is stored as plain text in that file.

### Source Checkout

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m vrclt run --app vrchat
```

Source checkouts read `config.yaml` from the repository root. Copy
`config.example.yaml` to `config.yaml` if you want local defaults before opening
the app:

```powershell
Copy-Item config.example.yaml config.yaml
```

`VRCLT_CONFIG` can override the config path for development and debugging.

## App Modes

| Mode | Use for | Behavior |
| --- | --- | --- |
| `vrchat` | VRChat | Captures `VRChat.exe`, enables OSC chatbox, avatar OSC control, SteamVR subtitles, and wrist UI |
| `discord` | Discord | Captures `Discord.exe`, disables VRChat OSC/SteamVR features, keeps the native app UI active |

Choose a mode in Settings or pass it for one launch:

```powershell
.\vrclt.exe run --app vrchat
.\vrclt.exe run --app discord
```

For VRChat text-only behavior, enable **Text only** in the Dashboard or
Settings. Your original microphone passes through to VRChat while Gemini sends
translated text to the OSC chatbox without translated voice output.

For Discord Canary or PTB, change the Discord process name in Settings or in
`app.profiles.discord.process`.

## Native UI

Dashboard:

- Runtime status and connection state
- VRChat/Discord mode toggle and VRChat text-only toggle
- Translation ON/OFF
- Subtitles ON/OFF
- Output language and subtitle language
- PC subtitle position controls and font size
- Live subtitle preview

Settings:

- API key and model
- App mode and target processes
- Microphone, translated voice output, monitor output, and inbound audio device
- Language lists
- Audio thresholds and VAD settings
- OSC, chatbox, SteamVR overlay, and wrist UI options
- UI language and UI mode

Logs/About:

- Current config path
- Current log file path
- Recent log tail

Closing the window hides it to the tray. Use the tray `Quit` action to stop the
runtime and exit.

## Audio Routing

Outbound translation:

```text
microphone -> Gemini Live -> translated voice -> CABLE Input
                                     target app mic <- CABLE Output
```

Inbound subtitles:

```text
target app process audio -> ProcTap -> Gemini Live -> subtitles
```

When translation is OFF, the microphone bypasses Gemini and is sent directly to
`CABLE Input`. In VRChat **Text only**, the original microphone is always passed
through; the translation toggle controls Gemini text translation and chatbox
output.

## VRChat Features

VRChat mode can use:

- OSC chatbox output for translated text
- Avatar OSC parameters such as `VRCLT_Enabled` and `VRCLT_Lang`
- SteamVR subtitle overlay for inbound subtitles
- SteamVR wrist menu for in-VR controls

With `ui.mode: auto`, SteamVR features activate when SteamVR is running. Use
`ui.mode: vr` to force VR overlays or `ui.mode: desktop` to keep them disabled.

## Files And Paths

| Item | Release exe | Source checkout |
| --- | --- | --- |
| Config | `%LOCALAPPDATA%\vrclt\config.yaml` | `config.yaml` in the repo root |
| Config override | `VRCLT_CONFIG` | `VRCLT_CONFIG` |
| Logs | `%LOCALAPPDATA%\vrclt\logs\vrclt.log` | `%LOCALAPPDATA%\vrclt\logs\vrclt.log` |
| Build output | `dist\vrclt.exe` | `dist\vrclt.exe` |

Do not commit `config.yaml`, `.venv/`, `build/`, `dist/`, `release/`, or log
files.

## Configuration Reference

All values are stored in `config.yaml`. Release builds use the AppData path
shown above; source checkouts use the repository-root `config.yaml` unless
`VRCLT_CONFIG` is set.

Top-level and app profile settings:

| Key | Default | Description |
| --- | --- | --- |
| `api_key` | `""` | Gemini API key. Empty means `GEMINI_API_KEY` can be used. |
| `model` | `gemini-3.5-live-translate-preview` | Gemini Live model name. |
| `log_level` | `INFO` | Python logging level. |
| `app.mode` | `vrchat` | Active profile: `vrchat` or `discord`. |
| `app.profiles.<mode>.process` | `VRChat.exe` / `Discord.exe` | Process captured for inbound subtitles. |
| `app.profiles.<mode>.ui_mode` | `auto` / `desktop` | UI mode applied by the profile. |
| `app.profiles.<mode>.voice_output` | `true` | Enables translated voice output. |
| `app.profiles.<mode>.passthrough_while_translating` | `false` | Sends raw microphone audio while translation is active. |
| `app.profiles.<mode>.chatbox` | `true` / `false` | Enables VRChat OSC chatbox output. |
| `app.profiles.<mode>.osc_control` | `true` / `false` | Enables avatar OSC control listener. |
| `app.profiles.<mode>.vr_overlay` | `true` / `false` | Enables SteamVR subtitle overlay. |
| `app.profiles.<mode>.wrist_ui` | `true` / `false` | Enables SteamVR wrist menu. |

Dashboard state:

| Key | Default | Description |
| --- | --- | --- |
| `dashboard.translation_on` | `true` | Last saved Dashboard translation toggle state. |
| `dashboard.subtitles_on` | `true` | Last saved Dashboard subtitles toggle state. |

Outbound translation:

| Key | Default | Description |
| --- | --- | --- |
| `outbound.enabled` | `true` | Enables the outbound pipeline. |
| `outbound.target_language` | `ja` | Default language for translating your speech. |
| `outbound.echo_target_language` | `false` | Also repeats source audio that is already in the target language. |
| `outbound.mic_device` | `""` | Microphone device name substring. Empty uses the default input. |
| `outbound.tts_device` | `CABLE Input` | Output device for translated voice and passthrough audio. |
| `outbound.monitor_device` | `""` | Optional local monitor output for translated voice. |
| `outbound.text_only` | `false` | VRChat text-only mode: raw mic passthrough plus translated chatbox text. |
| `outbound.voice_output` | `true` | Enables translated TTS audio output. |
| `outbound.passthrough_while_translating` | `false` | Sends raw mic audio even while translation is active. |
| `outbound.chatbox` | `true` | Sends translated text to the VRChat OSC chatbox. |

Inbound subtitles:

| Key | Default | Description |
| --- | --- | --- |
| `inbound.enabled` | `true` | Enables process-audio capture for subtitles. |
| `inbound.target_language` | `ko` | Default subtitle target language. |
| `inbound.languages` | `[ko, en, ja]` | Subtitle language list used by the wrist menu. |
| `inbound.process` | `VRChat.exe` | Process name captured for inbound subtitles. |
| `inbound.play_audio` | `false` | Plays translated inbound speech to your headphones. |
| `inbound.audio_device` | `""` | Output device for inbound translated speech. Empty uses default output. |
| `inbound.vad_enabled` | `true` | Uses voice activity detection to gate background music/noise. |
| `inbound.vad_threshold` | `0.5` | VAD strictness from `0` to `1`; higher rejects more non-speech. |
| `inbound.vad_hangover_sec` | `0.6` | Keeps capturing briefly after speech stops. |

Overlay and OSC:

| Key | Default | Description |
| --- | --- | --- |
| `overlay.enabled` | `true` | Enables the SteamVR subtitle overlay. |
| `overlay.width_m` | `0.9` | Subtitle overlay width in meters. |
| `overlay.distance_m` | `1.2` | Subtitle overlay distance from the HMD. |
| `overlay.below_m` | `0.35` | Vertical offset below the HMD. |
| `overlay.tilt_deg` | `-15.0` | Overlay tilt angle. |
| `overlay.font` | `bundled:NotoSansCJKsc-Regular.otf` | Subtitle overlay font. |
| `overlay.font_size` | `44` | Subtitle font size. |
| `overlay.display_sec` | `7.0` | Time finalized subtitle lines stay visible. |
| `overlay.lines` | `3` | Number of recent finalized lines kept on screen. |
| `overlay.show_source` | `false` | Also shows original source text in subtitles. |
| `osc.ip` | `127.0.0.1` | VRChat OSC destination IP. |
| `osc.port` | `9000` | VRChat OSC destination port. |
| `osc.throttle_sec` | `1.5` | Minimum chatbox send interval. |
| `osc.notification_sfx` | `false` | Requests VRChat chatbox notification sound. |
| `osc.show_source` | `true` | Shows source text above translation in the chatbox. |
| `osc.chunk_display_sec` | `4.0` | Display time per chunk for long chatbox messages. |

Audio, control, UI, and wrist menu:

| Key | Default | Description |
| --- | --- | --- |
| `audio.send_interval_ms` | `100` | Microphone audio flush interval to Gemini. |
| `audio.finalize_silence_sec` | `2.0` | Silence duration before a segment is finalized. |
| `audio.mic_idle_disconnect_sec` | `15.0` | Disconnects idle Gemini mic sessions after this many seconds. |
| `audio.voice_rms_threshold` | `90.0` | Microphone energy gate threshold. |
| `audio.voice_hangover_sec` | `2.5` | Keeps the mic turn open through short pauses. |
| `audio.echo_guard_multiplier` | `4.0` | Raises mic gate while target-app audio is active. `1.0` disables it. |
| `control.enabled` | `true` | Enables avatar OSC control input. |
| `control.osc_listen_port` | `9001` | Local OSC port for avatar control parameters. |
| `control.param_enabled` | `VRCLT_Enabled` | Avatar bool parameter for translation on/off. |
| `control.param_lang` | `VRCLT_Lang` | Avatar int parameter for language index. |
| `control.languages` | `[ja, en, ko, zh-Hans, zh-Hant, yue, es, ru, fr, de]` | Output language list for avatar and wrist controls. |
| `control.feedback_chatbox` | `true` | Sends control-change feedback to the VRChat chatbox. |
| `ui.mode` | `auto` | `auto`, `vr`, or `desktop`. |
| `ui.lang` | `""` | UI display language. Empty means auto; valid values are `en`, `ko`, `ja`, `zh`. |
| `ui.close_action` | `tray` | Window close button behavior: `tray` or `exit`. |
| `wrist_ui.enabled` | `true` | Enables the SteamVR wrist menu. |
| `wrist_ui.hand` | `left` | Wrist that wears the menu: `left` or `right`. |
| `wrist_ui.width_m` | `0.16` | Wrist menu width in meters. |
| `wrist_ui.offset` | `[0.0, 0.02, 0.12]` | Wrist menu x,y,z offset in controller space. |
| `wrist_ui.tilt_deg` | `0.0` | Extra tilt toward the face. |
| `wrist_ui.roll_deg` | `null` | In-plane rotation. `null` uses automatic per-hand rotation. |
| `wrist_ui.pointer_tilt_deg` | `50.0` | Pointer ray downward tilt angle. |
| `wrist_ui.font` | `bundled:NotoSansCJKsc-Bold.otf` | Wrist menu font. |

## Build

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
```

The build creates:

```text
dist\vrclt.exe
```

Create release artifacts:

```powershell
.\scripts\package_release.ps1 -Version 0.1.0
```

The release script creates:

```text
release\vrclt-v0.1.0-windows-x64.exe
release\vrclt-v0.1.0-windows-x64.exe.sha256
```

## Smoke Tests

```powershell
.\.venv\Scripts\python.exe -m compileall vrclt
.\.venv\Scripts\python.exe -m vrclt --help
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
.\scripts\package_release.ps1 -Version 0.1.0 -SkipBuild
```

For a real runtime test, run the exe, save settings in the native UI, confirm
that `%LOCALAPPDATA%\vrclt\config.yaml` is written, and verify that the target
app receives audio from `CABLE Output`.

## Troubleshooting

- No translated voice in the target app: confirm `outbound.tts_device` is `CABLE Input` and the target app microphone is `CABLE Output`.
- No inbound subtitles: confirm the target process name matches the running app, for example `VRChat.exe` or `Discord.exe`.
- Runtime says API key is required: enter the key in Settings or set `GEMINI_API_KEY`.
- VR overlays do not appear: confirm SteamVR is running and `overlay.enabled` / `wrist_ui.enabled` are enabled.
- Need a clean config: close the app, move `%LOCALAPPDATA%\vrclt\config.yaml`, then start the app again.

## Thanks To

- [Noto Sans CJK](https://github.com/notofonts/noto-cjk) and [Pretendard](https://github.com/orioncactus/pretendard) for multilingual UI font coverage.
- [PySide6](https://doc.qt.io/qtforpython-6/) for the native Windows interface.
- [OpenVR](https://github.com/ValveSoftware/openvr), GLFW, and PyOpenGL for SteamVR overlay rendering.
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) for practical app-to-app audio routing.

## Release Notes

See [docs/RELEASING.md](docs/RELEASING.md) for the release workflow.
