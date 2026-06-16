# vrclt

Languages: [English](README.md) | [Korean](README.ko.md)

`vrclt` is a Windows live translator for VRChat and Discord. It translates your
microphone with the Gemini Live API, plays the translated voice into the target
app through VB-Audio Virtual Cable, and shows translated subtitles for other
people's speech.

The app uses a native PySide6 interface. There is no web UI, no local web
server, and no config file required next to the release executable.

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

## Release Notes

See [docs/RELEASING.md](docs/RELEASING.md) for the release workflow.
