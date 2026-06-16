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
- `docs/RELEASING.md`
- `config.example.yaml`
- `requirements.txt`
- `vrclt.spec`
- `scripts/package_release.ps1`

## 2. Validation

Run the lightweight checks first:

```powershell
.\.venv\Scripts\python.exe -m compileall vrclt
.\.venv\Scripts\python.exe -m vrclt --help
```

Confirm that the public CLI only exposes `run` plus the optional app override:

```text
vrclt [{run}] [--app {vrchat,vrc_text,discord}]
```

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

```powershell
.\scripts\package_release.ps1 -Version 0.1.0
```

If `dist\vrclt.exe` has already been built and only the release copy needs to be
refreshed:

```powershell
.\scripts\package_release.ps1 -Version 0.1.0 -SkipBuild
```

Expected output:

```text
release\vrclt-v0.1.0-windows-x64.exe
release\vrclt-v0.1.0-windows-x64.exe.sha256
```

## 5. Smoke Test The Executable

Start the built exe directly:

```powershell
.\dist\vrclt.exe
```

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
.\dist\vrclt.exe run --app vrc_text
.\dist\vrclt.exe run --app discord
```

In `vrchat` mode, confirm OSC/chatbox, SteamVR subtitles, and wrist UI behavior
on a VR-capable machine. In `vrc_text` mode, confirm translated OSC chatbox text
is sent, translated voice is not played, and the original microphone still
passes through to `CABLE Input`. In `discord` mode, confirm VRChat-only
OSC/SteamVR features stay disabled while the native UI remains available.

## 6. Audio And Runtime Checks

On a release candidate machine, verify the expected audio routing:

```text
microphone -> Gemini Live -> CABLE Input -> target app microphone input from CABLE Output
target app process audio -> ProcTap -> Gemini Live -> native/VR subtitles
```

Minimum manual checks:

- Gemini API key can be saved in Settings.
- `CABLE Input` can be selected as translated voice output.
- The target app is configured to use `CABLE Output` as its microphone input.
- Translation ON sends translated voice to the target app.
- Translation OFF passes the original microphone through to `CABLE Input`.
- In `vrc_text`, original microphone audio always passes through to
  `CABLE Input`; Translation ON/OFF controls only OSC chatbox translation.
- Inbound subtitles appear for the selected process.
- Language changes from Dashboard apply immediately.
- Settings that require a rebuild restart the runtime without duplicate pipelines.

## 7. Commit And Tag

After validation, commit only source changes:

```powershell
git status
git add README.md README.ko.md README.en.md docs/RELEASING.md config.example.yaml requirements.txt vrclt.spec scripts/package_release.ps1 vrclt
git status
git commit -m "chore: prepare v0.1.0 release"
```

Create and push the tag:

```powershell
git tag v0.1.0
git push origin main --tags
```

Use a new version number if the tag already exists.

## 8. Publish

Upload these files to a GitHub Release:

```text
release\vrclt-v0.1.0-windows-x64.exe
release\vrclt-v0.1.0-windows-x64.exe.sha256
```

With GitHub CLI:

```powershell
gh release create v0.1.0 `
  .\release\vrclt-v0.1.0-windows-x64.exe `
  .\release\vrclt-v0.1.0-windows-x64.exe.sha256 `
  --title "vrclt v0.1.0" `
  --notes "Native UI release. Settings are stored in %LOCALAPPDATA%\vrclt\config.yaml."
```

## 9. Release Notes Checklist

Include these points in the release body:

- Windows-only single executable.
- VB-Audio Virtual Cable is required.
- Gemini API key is configured in the Settings tab.
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
