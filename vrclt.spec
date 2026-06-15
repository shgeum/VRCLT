# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for vrclt (onedir). Build: pyinstaller vrclt.spec --noconfirm"""
from PyInstaller.utils.hooks import collect_all

datas = [("vrclt/web/static/index.html", "vrclt/web/static")]
binaries = []
hiddenimports = ["vrclt"]

# native / data-heavy packages PyInstaller can't fully trace on its own
for pkg in ["onnxruntime", "soxr", "proctap", "openvr", "sounddevice", "glfw",
            "OpenGL", "pystray", "PIL", "uvicorn", "fastapi", "starlette",
            "google.genai", "pythonosc", "yaml", "psutil", "soundfile"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec] collect_all skipped {pkg}: {e}")

a = Analysis(
    ["run_vrclt.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "matplotlib", "tkinter.test", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="vrclt",
    console=True,        # keep the log console; set False for a silent tray app
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="vrclt")
