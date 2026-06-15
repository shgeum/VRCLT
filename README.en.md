# vrclt — VRChat / Discord Live Translator

Languages: [Korean](README.md) | [English](README.en.md)

`vrclt` is a Windows live voice translation tool powered by the Gemini Live API
(`gemini-3.5-live-translate-preview`). It translates your microphone into spoken
voice output and shows translated subtitles for other people. It supports both
VRChat and Discord, using VB-Audio Virtual Cable to route translated voice into
the target app's microphone input.

## Features

- Translate your microphone through Gemini Live and output the translated voice to `CABLE Input`
- Passthrough mode: when translation is OFF, your original microphone is routed directly
- VRChat mode: OSC chatbox output, SteamVR subtitle overlay, wrist menu, avatar OSC parameter controls
- Discord mode: Discord process audio capture, PC subtitle window, automatic disabling of VRChat-only features
- Per-app inbound audio capture through ProcTap process loopback
- Web settings/control UI at `http://127.0.0.1:8765`
- Local settings and API keys are kept out of Git

## Requirements

- Windows 11 recommended
- Python 3.12 recommended, 3.10-3.13 supported
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
- [Gemini API key](https://aistudio.google.com/apikey)
- SteamVR for VR mode
- VRChat OSC enabled for VRChat subtitles/chatbox features

## Installation

1. Prepare the repository.

```powershell
git clone <repository-url>
Set-Location VRCLT
```

If you already have the source folder, start from that folder and continue with the next step.

1. Create a Python virtual environment and install dependencies.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

1. Create your local config file.

```powershell
Copy-Item config.example.yaml config.yaml
```

`config.yaml` contains your API key, device names, and language preferences. Do not commit it to Git.
Edit [config.example.yaml](config.example.yaml) only for shareable defaults.

1. Set your Gemini API key.

```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
```

This only applies to the current PowerShell session. For persistent use, register `GEMINI_API_KEY`
as a Windows environment variable, or put the key in your local [config.yaml](config.yaml).

1. Verify audio devices and Gemini access.

```powershell
.\.venv\Scripts\python.exe -m vrclt devices
.\.venv\Scripts\python.exe -m vrclt sinetest "CABLE Input"
.\.venv\Scripts\python.exe -m vrclt miccheck
.\.venv\Scripts\python.exe -m vrclt livetest
```

`devices` should show `VB-Cable: FOUND`. `sinetest` helps confirm that the target app's
microphone test reacts when audio is sent to `CABLE Input`.

## Quick Start

### VRChat

1. Set the VRChat microphone input device to **CABLE Output (VB-Audio Virtual Cable)**.
2. In VRChat, enable Options -> OSC from the action menu.
3. Set `outbound.mic_device` in [config.yaml](config.yaml) to match your real microphone.
   Leave it empty to use the Windows default input device.
4. Run VRCLT.

```powershell
.\.venv\Scripts\python.exe -m vrclt run --app vrchat
```

`--app vrchat` is optional. The default comes from `app.mode` in [config.yaml](config.yaml),
and the example config starts with `vrchat`.

### Discord

1. Set the Discord input device to **CABLE Output (VB-Audio Virtual Cable)**.
2. Make sure `outbound.tts_device` in [config.yaml](config.yaml) is `CABLE Input`.
3. Set `outbound.mic_device` to part of your real microphone name, or leave it empty.
4. Run Discord mode.

```powershell
.\.venv\Scripts\python.exe -m vrclt run --app discord
```

Discord mode uses the desktop subtitle/control windows and automatically disables VRChat OSC chatbox,
avatar OSC controls, and SteamVR UI. If you use Discord Canary or PTB, set
`app.profiles.discord.process` in [config.yaml](config.yaml) to `DiscordCanary.exe` or `DiscordPTB.exe`.

## How To Use

### Runtime Controls

- **Translation ON/OFF**: ON sends Gemini translated voice to the target app. OFF sends your original microphone through passthrough.
- **Output language**: The language your voice is translated into. Choose from `control.languages`.
- **Subtitles ON/OFF**: Enables or disables the inbound subtitle pipeline.
- **Subtitle language**: The language used for other people's translated subtitles. Choose from `inbound.languages`.
- **Web UI**: While running, open `http://127.0.0.1:8765` to edit settings, change languages, and view live subtitles.
- **Tray icon**: When `web.tray: true`, provides quick controls and a quit menu.

### PC / Desktop Mode

When SteamVR is not running, or when `ui.mode: desktop`, VRCLT shows two always-on-top desktop windows.

- Subtitle window: displays translated subtitles for other people. It auto-hides when empty.
- Control bar: translation toggle, output language, subtitle toggle, subtitle language, connection status, and quit button.
- Window positions are saved to `%LOCALAPPDATA%\vrclt\desktop_layout.json`.

To preview the desktop UI without an API key, run:

```powershell
.\.venv\Scripts\python.exe -m vrclt desktoptest
```

### VR Mode

With `ui.mode: auto`, VRCLT enters VR mode when SteamVR is running. To force VR mode,
set `ui.mode` in [config.yaml](config.yaml) to `vr`.

VR mode provides:

- SteamVR subtitle overlay: shows translated inbound subtitles in front of the HMD.
- Wrist menu: attaches to the left wrist by default. Point with the other controller and click.
- Avatar OSC parameters: `VRCLT_Enabled` and `VRCLT_Lang` can toggle translation and change languages.

To test only the wrist menu, run:

```powershell
.\.venv\Scripts\python.exe -m vrclt wristtest
```

To reset saved overlay positions, run:

```powershell
.\.venv\Scripts\python.exe -m vrclt resetpos
```

## App Modes

Choose the app mode with `app.mode` in [config.yaml](config.yaml) or with the `--app` runtime option.
The runtime option takes priority for that launch.

| Mode | Command | Main behavior |
| --- | --- | --- |
| `vrchat` | `python -m vrclt run --app vrchat` | Captures VRChat process audio, uses OSC chatbox and VR UI |
| `discord` | `python -m vrclt run --app discord` | Captures Discord process audio, uses desktop UI, disables VRChat-only features |

Mode defaults can be changed under `app.profiles`.

| Setting | Description |
| --- | --- |
| `process` | Target process name for inbound audio capture |
| `ui_mode` | Runtime UI mode: `auto`, `vr`, or `desktop` |
| `chatbox` | Whether to send translated text to the VRChat OSC chatbox |
| `osc_control` | Whether to listen for VRChat avatar OSC controls |
| `vr_overlay` | Whether to use the SteamVR subtitle overlay |
| `wrist_ui` | Whether to use the SteamVR wrist menu |

## Configuration

Main settings live in [config.yaml](config.yaml). Device names vary per machine, so start with
`python -m vrclt devices` to inspect available input and output devices.

| Setting | Description |
| --- | --- |
| `api_key` | If empty, VRCLT uses the `GEMINI_API_KEY` environment variable. |
| `model` | Gemini Live model name |
| `app.mode` | Default app target: `vrchat` or `discord` |
| `outbound.target_language` | Output language for your translated voice |
| `outbound.mic_device` | Part of your real microphone device name. `""` means default input |
| `outbound.tts_device` | Output device for translated voice, usually `CABLE Input` |
| `outbound.monitor_device` | Optional output device for hearing translated voice yourself. `""` disables it |
| `outbound.chatbox` | Whether to send translated text to the VRChat OSC chatbox |
| `inbound.enabled` | Enables the inbound subtitle pipeline |
| `inbound.process` | Process to capture. Automatically set by the selected app profile |
| `inbound.target_language` | Default subtitle language for other people's voices |
| `inbound.play_audio` | Whether to play inbound translated voice to your output device |
| `audio.voice_rms_threshold` | Microphone speech threshold. Lower it if speech is clipped; raise it if noise opens sessions |
| `audio.echo_guard_multiplier` | Boosts microphone gating while target-app audio is active |
| `web.port` | Web UI port. Default: `8765` |
| `ui.mode` | `auto`, `vr`, or `desktop` |

Language codes use BCP-47 style values such as `ja`, `en`, `ko`, `zh-Hans`, `zh-Hant`, `es`, `fr`, and `de`.

## CLI Reference

| Command | Description |
| --- | --- |
| `python -m vrclt devices` | Lists WASAPI devices and VB-Cable detection status |
| `python -m vrclt sinetest [name]` | Plays a test tone to an output device. Default: `CABLE Input` |
| `python -m vrclt miccheck [name]` | Captures the microphone for about 4 seconds and prints RMS levels plus a suggested threshold |
| `python -m vrclt livetest [--app vrchat\|discord]` | Tests Gemini Live connection and model access |
| `python -m vrclt desktoptest [--app vrchat\|discord]` | Previews the PC subtitle/control UI without an API key |
| `python -m vrclt wristtest [--app vrchat\|discord]` | Tests the SteamVR wrist menu without an API key |
| `python -m vrclt overlaytest [--app vrchat\|discord]` | Tests the SteamVR subtitle overlay |
| `python -m vrclt resetpos` | Resets saved VR overlay and wrist menu positions |
| `python -m vrclt run [--app vrchat\|discord]` | Runs live translation |

## Audio Routing

The default routing is:

```text
Your microphone -> Gemini Live -> translated voice -> CABLE Input -> target app microphone input (CABLE Output)
                -> translated text -> VRChat chatbox or subtitle/web UI

Target app process audio -> ProcTap -> Gemini Live -> translated subtitles -> PC/VR/web UI
```

When translation is OFF, your microphone bypasses Gemini and is routed directly to `CABLE Input`.
Discord mode uses the same audio routing but does not use OSC chatbox output.

## Troubleshooting

### `VB-Cable: NOT INSTALLED`

Install VB-Audio Virtual Cable, then restart Windows or refresh the audio device list.
Run `python -m vrclt devices` again afterward.

### The target app does not receive microphone audio

Make sure the target app input device is **CABLE Output**. When you run `sinetest "CABLE Input"`,
the target app microphone test should react.

### My speech is not translated or gets cut off

Run `python -m vrclt miccheck` and adjust `audio.voice_rms_threshold` based on the suggested value.
Lower it if your voice is missed; raise it if background noise keeps opening sessions.

### Other people's subtitles do not appear

Make sure the target app is running. VRChat defaults to `VRChat.exe`; Discord defaults to `Discord.exe`.
If you use Canary/PTB or another executable name, update `app.profiles.discord.process`.

### The web UI does not open

The default URL is `http://127.0.0.1:8765`. If the port conflicts with another app, change `web.port`
in [config.yaml](config.yaml), then restart VRCLT.

### Gemini connection test fails

Check the `GEMINI_API_KEY` environment variable or the `api_key` value in [config.yaml](config.yaml).
Also confirm that your account has access to the model in [Google AI Studio](https://aistudio.google.com/apikey).

## Logs

Logs are written to:

```text
%LOCALAPPDATA%\vrclt\logs\vrclt.log
```

When troubleshooting, check this file first for device selection, process capture, and Gemini connection logs.

## Development

For development, activate the virtual environment and run the CLI directly.

```powershell
.\.venv\Scripts\Activate.ps1
python -m vrclt devices
python -m vrclt run --app vrchat
```

Packaging uses the PyInstaller spec file.

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
```

The build output is generated in `dist/vrclt/`.

## Git / Distribution

- [config.example.yaml](config.example.yaml) is the shareable configuration example.
- Do not commit `config.yaml`, `.venv/`, `build/`, `dist/`, or log files.
- Create the release zip with `scripts/package_release.ps1`.
- Publish executables or zip archives as release attachments, not as regular Git commits.
- See [docs/RELEASING.md](docs/RELEASING.md) for the release workflow.
