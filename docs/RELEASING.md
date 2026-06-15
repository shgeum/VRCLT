# Releasing vrclt with Git

This project keeps source code in Git and keeps local secrets, virtual environments,
logs, and PyInstaller output outside Git.

## First-time repository setup

```powershell
git init
git status
git add .
git commit -m "chore: prepare source release"
```

Before the first commit, check that `config.yaml`, `.venv/`, `build/`, and `dist/`
do not appear under `git status` as staged files.

## Local setup from a fresh clone

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml
$env:GEMINI_API_KEY = "your-gemini-api-key"
.\.venv\Scripts\python.exe -m vrclt devices
.\.venv\Scripts\python.exe -m vrclt run
```

You can also put the API key in `config.yaml`, but that file is intentionally ignored
by Git.

## Building a distributable folder

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\pyinstaller.exe vrclt.spec --noconfirm
```

The generated app folder is written to `dist/vrclt/`. Publish that folder or a zipped
copy through GitHub Releases instead of committing it to Git.

## Tagging a release

```powershell
git tag v0.1.0
git push origin main --tags
```

Use a new tag for each published build so users can find the exact source that created
the release artifact.
