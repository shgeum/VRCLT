# Release Workflow

This project keeps source code in Git and distributes Windows builds as release
attachments. Do not commit local settings, virtual environments, logs, or build
outputs.

The release artifact is a single executable:

```text
release\vrclt-v<version>-windows-x64.exe
```

User settings are created at runtime in:

```text
%LOCALAPPDATA%\vrclt\config.yaml
```

Do not ship a `config.yaml` or `config.example.yaml` next to the exe.

## 1. Pre-Release Checks

Inspect the working tree before building:

```powershell
git status --short --ignored
```

These paths must not be staged or committed:

- `config.yaml`
- `.venv/`
- `build/`
- `dist/`
- `release/`
- `build_log.txt`
- `%LOCALAPPDATA%\vrclt\logs\*`
- any local API key or personal device config

Expected release-related source files include:

- `README.md`
- `README.ko.md`
- `README.ja.md`
- `README.zh.md`
- `CHANGELOG.md`
- `docs/RELEASING.md`
- `docs/releases/v0.19.0.md`
- `config.example.yaml`
- `requirements.txt`
- `vrclt.spec`
- `scripts/package_release.ps1`

## 2. Validation

Run the lightweight checks first:

```powershell
.\.venv\Scripts\python.exe -m compileall vrclt
.\.venv\Scripts\python.exe tests\smoke_cli.py
.\.venv\Scripts\python.exe -m vrclt --help
```

For v0.19.0, also run the regression scripts for Soniox, speaker displays,
settings navigation, logs, reconnect waits, audio passthrough, and startup:

```powershell
$releaseChecks = @(
  'smoke_soniox_session.py', 'smoke_subtitle_speakers.py',
  'smoke_speaker_ui.py', 'smoke_vr_speakers.py',
  'smoke_settings_navigation.py', 'smoke_logpanel.py',
  'smoke_session_wait.py', 'smoke_audio_passthrough.py',
  'smoke_pipeline_startup.py'
)
foreach ($releaseCheck in $releaseChecks) {
  & .\.venv\Scripts\python.exe (Join-Path 'tests' $releaseCheck)
  if ($LASTEXITCODE -ne 0) { throw "Failed: $releaseCheck" }
}
```

Record local test results separately from live-provider and physical-device
checks. Mock Soniox sessions and rendered VR images do not establish live
speaker-recognition accuracy or behavior on a headset.

Confirm that the public CLI only exposes `run` plus the optional app override:

```text
vrclt [-h] [--app {vrchat,discord,custom}] [{run}]
```

Help must exit successfully without opening the GUI or starting microphone capture.

Check source files for stale web stack references before tagging:

```powershell
rg -n "FastAPI|uvicorn|pystray|localhost:8765|vrclt.web|_start_web" README.md README.ko.md vrclt requirements.txt
```

No matches are expected, except unrelated dependency names such as
`websockets`.

## 3. Build

Build the one-file, windowed executable:

```powershell
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
```

Expected output:

```text
dist\vrclt.exe
```

The spec must remain a onefile/windowed build. It should not use `COLLECT`, and
it should not copy web static files or an external config into the distribution.

Some optional PyInstaller warnings from OpenGL, onnxruntime, or test modules can
appear during analysis. Treat the build as failed only if PyInstaller exits with
a non-zero status or `dist\vrclt.exe` is missing.

## 4. Package Release Artifact

Create the release executable and checksum:

The script defaults to `vrclt.__version__`. An explicit `-Version` must match it.
Build failures stop packaging, and `-SkipBuild` checks the version inside the
executable before copying it. Windows file and product versions also use the
application version from the spec.

```powershell
.\scripts\package_release.ps1 -Version 0.19.0
```

If `dist\vrclt.exe` has already been built and only the release copy needs to be
refreshed:

```powershell
.\scripts\package_release.ps1 -Version 0.19.0 -SkipBuild
```

Use `-SkipBuild` only when that executable was built from the exact source being
released. Confirm `vrclt/__init__.py`, the changelog, and the artifact name all
use `0.19.0`.

Expected output:

```text
release\vrclt-v0.19.0-windows-x64.exe
release\vrclt-v0.19.0-windows-x64.exe.sha256
```

## 5. Smoke Test The Executable

Start the built exe directly:

```powershell
.\dist\vrclt.exe
```

Repeat the launch check with the packaged release executable, which is the file
users download:

```powershell
.\release\vrclt-v0.19.0-windows-x64.exe
Get-FileHash .\release\vrclt-v0.19.0-windows-x64.exe -Algorithm SHA256
Get-Content .\release\vrclt-v0.19.0-windows-x64.exe.sha256
```

The computed hash must match the checksum file. An existing process or a
successful build alone does not prove that the application window appeared.

Then verify:

- The native PySide6 window appears.
- No console window is required for normal use.
- Closing the window hides the app to the tray.
- The tray menu can reopen the app and quit it.
- The Dashboard shows runtime status.
- The Settings tab can save settings.
- `%LOCALAPPDATA%\vrclt\config.yaml` is created after saving.
- `%LOCALAPPDATA%\vrclt\logs\vrclt.log` is created.

For app-mode smoke tests:

```powershell
.\dist\vrclt.exe run --app vrchat
.\dist\vrclt.exe run --app discord
.\dist\vrclt.exe run --app custom
```

In `vrchat` mode, confirm OSC/chatbox, SteamVR subtitles, and wrist UI behavior
on a VR-capable machine. With the VRChat **Text only** toggle enabled, confirm
translated OSC chatbox text is sent, translated voice is not played, and the
original microphone still passes through to `CABLE Input`. In `discord` mode,
confirm VRChat-only OSC/SteamVR features stay disabled while the native UI
remains available.

## 6. Audio And Runtime Checks

On a release candidate machine, verify the expected audio routing:

```text
microphone -> selected translation engine -> CABLE Input -> target app microphone input from CABLE Output
target app process audio -> ProcTap -> selected translation engine -> native/VR subtitles
```

Minimum manual checks:

- The selected engine's API key can be saved in Settings.
- `CABLE Input` can be selected as translated voice output.
- The target app is configured to use `CABLE Output` as its microphone input.
- Translation ON sends translated voice to the target app.
- Translation OFF passes the original microphone through to `CABLE Input`.
- With VRChat **Text only** enabled, original microphone audio always passes
  through to `CABLE Input`; Translation ON/OFF controls only OSC chatbox
  translation.
- Inbound subtitles appear for the selected process.
- Language changes from Dashboard apply immediately.
- Settings that require a rebuild restart the runtime without duplicate pipelines.

Soniox release checks:

- Set the engine to `soniox` and configure its API key in Settings, or supply
  `SONIOX_API_KEY` in the environment.
- Use two speakers and confirm speaker numbers/colors, original/translated text
  association, and turn order in the Dashboard, desktop overlay, and VR overlay.
- Confirm **Keep speaker context** is enabled by default and the billing note is
  visible. Active recognition connections stay billable during silence, including
  text-only use; see [Soniox keepalive billing](https://soniox.com/docs/stt/rt/connection-keepalive).
- With context retention off, verify idle disconnect and a new speaker context
  after reconnecting. Speaker numbers are session-local, not persistent identities.
- Verify text-only use and optional translated voice separately. Translated voice
  uses the selected TTS voice; speaker labels do not imply automatic voice cloning.

If these live checks or headset checks have not been performed, leave that limit
explicit in the release notes.

## 7. Commit And Tag

After validation, commit only source changes:

```powershell
git status
git add README.md README.ko.md README.en.md README.ja.md README.zh.md CHANGELOG.md docs/RELEASING.md docs/releases/v0.19.0.md config.example.yaml requirements.txt vrclt.spec scripts/package_release.ps1 vrclt tests
git status
git commit -m "chore: prepare v0.19.0 release"
```

Create and push the tag:

```powershell
git tag v0.19.0
git push origin main
git push origin v0.19.0
```

Use a new version number if the tag already exists.

## 8. Publish

Upload these files to a GitHub Release:

```text
release\vrclt-v0.19.0-windows-x64.exe
release\vrclt-v0.19.0-windows-x64.exe.sha256
```

With GitHub CLI:

```powershell
gh release create v0.19.0 `
  .\release\vrclt-v0.19.0-windows-x64.exe `
  .\release\vrclt-v0.19.0-windows-x64.exe.sha256 `
  --title "vrclt v0.19.0" `
  --notes-file .\docs\releases\v0.19.0.md
```

## 9. Release Notes Checklist

Include these points in the release body:

- Windows-only single executable.
- VB-Audio Virtual Cable is required.
- The selected engine's API key is configured in the Settings tab.
- Soniox speaker labels preserve turn order and are local to the current session.
- Soniox keeps speaker context by default; the full connected recognition stream
  is billable, including silence. The option can be disabled in Settings.
- State whether live Soniox calls, packaged-window launch, and physical VR/audio
  checks were completed; do not equate local mock tests with those checks.
- User settings are stored in `%LOCALAPPDATA%\vrclt\config.yaml`.
- The app uses a native PySide6 UI and tray menu.
- There is no web UI or local web server.
- VRChat mode supports OSC chatbox, avatar OSC control, SteamVR subtitles, and wrist UI.
- VRC Text Only mode passes original voice through and sends translated OSC
  chatbox text without translated voice output.
- Discord mode captures Discord process audio and disables VRChat-only features.
- Target app microphone should be set to `CABLE Output`.

## 10. Rollback

If a release needs to be pulled:

1. Delete or mark the GitHub Release as pre-release.
2. Leave the Git tag in place unless the artifact was never meant to be public.
3. Create a patch release with a new version number.
4. Note whether users should delete or keep `%LOCALAPPDATA%\vrclt\config.yaml`.
