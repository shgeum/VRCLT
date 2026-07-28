"""Generate vrclt/assets/icon.png + icon.ico (app/window/tray/exe icon).

Design matches the existing brand marks (Qt tray icon, VR dashboard
thumbnail): blue rounded square + white V. Drawn supersampled at 1024 px
and downscaled, so the small .ico sizes stay crisp.

Run: .venv/Scripts/python scripts/make_icon.py
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vrclt.ui import theme  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "vrclt" / "assets"
# the V polygon from the 256 px VR dashboard thumbnail (dashboard_panel.py)
V_POINTS_256 = [(70, 84), (108, 84), (128, 156), (148, 84), (186, 84),
                (148, 196), (108, 196)]
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]


def draw_base(s: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = s / 256
    d.rounded_rectangle((24 * k, 24 * k, s - 24 * k, s - 24 * k), 56 * k,
                        fill=theme.QT_TRAY_BLUE)
    d.polygon([(x * k, y * k) for x, y in V_POINTS_256],
              fill=(255, 255, 255, 255))
    return img


def main() -> None:
    base = draw_base()
    png = base.resize((256, 256), Image.LANCZOS)
    png.save(ASSETS / "icon.png")
    ico_frames = [base.resize(size, Image.LANCZOS) for size in ICO_SIZES]
    ico_frames[-1].save(ASSETS / "icon.ico", format="ICO",
                        append_images=ico_frames[:-1],
                        sizes=ICO_SIZES)
    print(f"wrote {ASSETS / 'icon.png'} and {ASSETS / 'icon.ico'}")


if __name__ == "__main__":
    main()
