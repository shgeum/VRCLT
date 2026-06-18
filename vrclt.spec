# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for vrclt onefile build.

Build: pyinstaller vrclt.spec --noconfirm
Output: dist/vrclt.exe
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ["vrclt"]

font_dir = Path("vrclt") / "assets" / "fonts"
if font_dir.exists():
    for path in font_dir.iterdir():
        if path.is_file():
            datas.append((str(path), "vrclt/assets/fonts"))

# native / data-heavy packages PyInstaller can't fully trace on its own
for pkg in [
    "onnxruntime", "soxr", "proctap", "openvr", "sounddevice",
    "glfw", "OpenGL", "PIL", "google.genai", "pythonosc", "yaml",
    "psutil", "soundfile",
]:
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
    excludes=["torch", "matplotlib", "tkinter", "tkinter.test", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="vrclt",
    console=False,
    icon=None,
    strip=False,
    upx=False,
)
