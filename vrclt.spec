# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for vrclt onefile build.

Build: pyinstaller vrclt.spec --noconfirm
Output: dist/vrclt.exe
"""
from pathlib import Path
import ast

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo,
)

version_tree = ast.parse(Path("vrclt/__init__.py").read_text(encoding="utf-8"))
app_version = next(
    ast.literal_eval(node.value) for node in version_tree.body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets)
)
version_tuple = tuple(int(part) for part in app_version.split("-")[0].split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple,
                     mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", "VRCLT Live Translator"),
            StringStruct("FileVersion", app_version),
            StringStruct("ProductName", "VRCLT"),
            StringStruct("ProductVersion", app_version),
            StringStruct("OriginalFilename", "vrclt.exe"),
        ])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

datas = []
binaries = []
hiddenimports = ["vrclt"]

font_dir = Path("vrclt") / "assets" / "fonts"
if font_dir.exists():
    for path in font_dir.iterdir():
        if path.is_file():
            datas.append((str(path), "vrclt/assets/fonts"))

for icon_name in ("icon.ico", "icon.png"):
    icon_file = Path("vrclt") / "assets" / icon_name
    if icon_file.exists():
        datas.append((str(icon_file), "vrclt/assets"))

# native / data-heavy packages PyInstaller can't fully trace on its own
for pkg in [
    "onnxruntime", "soxr", "proctap", "openvr", "sounddevice",
    "glfw", "OpenGL", "PIL", "google.genai", "pythonosc", "yaml",
    "psutil", "websockets", "certifi",
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
    version=version_info,
    icon="vrclt/assets/icon.ico",
    strip=False,
    upx=False,
)
