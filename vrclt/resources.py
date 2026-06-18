"""Bundled data asset helpers."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

ASSET_ROOT = Path(__file__).resolve().parent / "assets"
_BUNDLED_PREFIX = "bundled:"
_LEGACY_DEFAULT_FONTS = {
    "c:/windows/fonts/malgun.ttf",
    "c:/windows/fonts/malgunbd.ttf",
}


def bundled_font(name: str) -> str:
    """Return a stable config token for a font shipped with the app."""
    return f"{_BUNDLED_PREFIX}{name}"


def font_path(name: str) -> Path:
    return ASSET_ROOT / "fonts" / name


def resolve_font_path(value: str | None, default_name: str) -> str:
    """Resolve user config font paths, including bundled font tokens.

    Config files may outlive a onefile PyInstaller extraction directory, so
    bundled fonts are stored as stable ``bundled:Name.otf`` tokens instead of
    absolute temporary paths.
    """
    ref = (value or "").strip()
    if ref.startswith(_BUNDLED_PREFIX):
        path = font_path(ref[len(_BUNDLED_PREFIX):])
        if path.exists():
            return str(path)
        log.warning("bundled font not found: %s", path)

    if ref:
        if ref.replace("\\", "/").lower() in _LEGACY_DEFAULT_FONTS:
            fallback = font_path(default_name)
            if fallback.exists():
                return str(fallback)
        path = Path(ref).expanduser()
        if path.exists():
            return str(path)
        log.warning("configured font not found: %s; using bundled fallback", ref)

    fallback = font_path(default_name)
    return str(fallback) if fallback.exists() else ref
