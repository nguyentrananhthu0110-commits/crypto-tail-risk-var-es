"""Tạo bộ favicon / app icon cho CRI từ ảnh logo gốc.

Cách dùng:
    python assets/brand/build_icons.py [đường_dẫn_ảnh_gốc]

Mặc định đọc assets/brand/cri-icon-1024.png và ghi ra app/static/icons/.

Hai biến thể được sinh ra:
  1. "full"  — nguyên ô icon có viền neon (dùng cho icon lớn, apple-touch, PWA).
  2. "safe"  — crop zoom sát chữ R hơn (dùng cho favicon 16-48px) để ký tự
               còn đọc được ở kích thước rất nhỏ.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "app" / "static" / "icons"
DEFAULT_SRC = Path(__file__).resolve().parent / "cri-icon-1024.png"


def rounded(img: Image.Image, radius_frac: float = 0.21) -> Image.Image:
    """Bo góc theo tỉ lệ cạnh, khớp với tile gốc."""
    s = img.size[0]
    r = int(s * radius_frac)
    mask = Image.new("L", (s * 4, s * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s * 4 - 1, s * 4 - 1], radius=r * 4, fill=255)
    mask = mask.resize((s, s), Image.LANCZOS)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def safe_crop(src: Image.Image, zoom_margin: float = 0.10) -> Image.Image:
    """Cắt sát phần chữ R (bỏ viền) để favicon nhỏ vẫn rõ."""
    w, h = src.size
    pad = int(min(w, h) * 0.13)          # bỏ viền neon quanh tile
    core = src.crop((pad, pad, w - pad, h - pad))
    inner = int(min(core.size) * zoom_margin)
    core = core.crop((inner, inner, core.size[0] - inner, core.size[1] - inner))
    side = max(core.size)
    sq = Image.new("RGB", (side, side), core.getpixel((2, 2)))
    sq.paste(core, ((side - core.size[0]) // 2, (side - core.size[1]) // 2))
    return sq


def main() -> None:
    src_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src_path.exists():
        raise SystemExit(f"Không tìm thấy ảnh gốc: {src_path}")

    OUT.mkdir(parents=True, exist_ok=True)
    full = rounded(Image.open(src_path).convert("RGB"))
    safe = rounded(safe_crop(Image.open(src_path).convert("RGB")))

    # Icon lớn — giữ nguyên viền neon
    full.resize((512, 512), Image.LANCZOS).save(OUT / "cri-icon-512.png")
    full.resize((256, 256), Image.LANCZOS).save(OUT / "cri-icon.png")
    full.resize((192, 192), Image.LANCZOS).save(OUT / "cri-icon-192.png")
    full.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")

    # Favicon nhỏ — bản zoom sát chữ R
    safe.resize((48, 48), Image.LANCZOS).save(OUT / "favicon-48.png")
    safe.resize((32, 32), Image.LANCZOS).save(OUT / "favicon-32.png")
    safe.resize((16, 16), Image.LANCZOS).save(OUT / "favicon-16.png")
    safe.save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

    for f in sorted(OUT.iterdir()):
        print(f"  {f.name:24} {f.stat().st_size / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
