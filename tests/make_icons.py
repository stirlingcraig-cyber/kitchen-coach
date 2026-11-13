"""Render web/icons/logo.svg into the PNG icons and the Windows .ico (dev tool; needs playwright + Pillow)."""
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "web" / "icons"
svg = (ICONS / "logo.svg").read_text()
square = svg.replace('rx="112"', 'rx="0"')                        # iOS / maskable: full-bleed square
maskable = square.replace('<rect x="226"', '<g transform="translate(51 51) scale(.8)"><rect x="226"', 1) \
                 .replace("</svg>", "</g></svg>")
maskable = maskable.replace('<rect width="512" height="512" rx="0" fill="url(#bg)"/>\n  <g transform="translate(51 51) scale(.8)">',
                            '<rect width="512" height="512" fill="url(#bg)"/>\n  <g transform="translate(51 51) scale(.8)">')

def shot(page, markup, size, out, transparent=True):
    page.set_viewport_size({"width": size, "height": size})
    page.set_content(f"<html><body style='margin:0;background:transparent'>"
                     f"<div style='width:{size}px;height:{size}px'>{markup.replace('<svg ', f'<svg width=\"{size}\" height=\"{size}\" ', 1)}</div></body></html>")
    page.screenshot(path=str(out), omit_background=transparent, clip={"x": 0, "y": 0, "width": size, "height": size})

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    shot(page, svg, 192, ICONS / "icon-192.png")
    shot(page, svg, 512, ICONS / "icon-512.png")
    shot(page, maskable, 512, ICONS / "icon-maskable-512.png", transparent=False)
    shot(page, square, 180, ICONS / "apple-touch-icon.png", transparent=False)
    shot(page, svg, 1024, ROOT / "assets" / "icon-1024.png")
    b.close()

big = Image.open(ROOT / "assets" / "icon-1024.png").convert("RGBA")
big.save(ROOT / "assets" / "kitchen_coach.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
print("icons written")
