"""캐릭터 이미지에서 배경을 지우고 앱용 이미지(아이콘/파비콘/헤더)를 만든다.
원본은 assets/source/ 에 있다. 캐릭터를 바꾸면 원본을 교체하고 `python make_assets.py` 를 실행한다.

 character_small.png (저해상도) → assets/icon.ico (창/작업표시줄/파비콘), assets/icon.png
 character_large.webp (고해상도) → assets/header.png (프로그램 상단), assets/character.png (배경 제거 원본 크기)
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "assets", "source")
OUT = os.path.join(HERE, "assets")
HEADER_H = 104                      # 헤더 이미지 높이(px)
ICON_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def remove_background(img: Image.Image, drop_shadow_below: int | None = None) -> Image.Image:
    """흰 배경(+바닥 그림자)을 투명하게 만든다. 캐릭터 안쪽의 흰 몸통은 외곽선이 막아 주므로 그대로 남는다.
    외곽선 주변의 흐릿한 가장자리는 투명도로 환산해 흰 테두리(헤일로)가 생기지 않게 한다."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    marker = (255, 0, 255)
    work = rgb.copy()
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    for s in seeds:
        if work.getpixel(s) != marker:
            ImageDraw.floodfill(work, s, marker, thresh=14)
    a = np.asarray(work)
    bg = (a[..., 0] == 255) & (a[..., 1] == 0) & (a[..., 2] == 255)

    arr = np.asarray(rgb).astype(np.float32)
    if drop_shadow_below is not None:                     # 바닥 그림자(연보라 타원)
        r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
        shadow = (b - r > 8) & (r > 170) & (r < 246)
        shadow[:drop_shadow_below, :] = False
        # 그림자 가장자리의 반투명 띠까지 지운다 (그림자 마스크만 넓히고, 어두운 외곽선은 보호)
        shadow = np.asarray(Image.fromarray((shadow * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
        shadow[:drop_shadow_below, :] = False
        shadow &= arr.min(axis=2) > 150
        bg |= shadow

    bgi = Image.fromarray((bg * 255).astype(np.uint8))
    band = (np.asarray(bgi.filter(ImageFilter.MaxFilter(5))) > 0) & ~bg      # 배경과 맞닿은 2px 띠
    minc = arr.min(axis=2)
    ink = np.where(bg | band, 255.0, minc)                                    # 띠 바깥(안쪽) 픽셀의 어두운 정도
    ref = np.asarray(Image.fromarray(ink.astype(np.uint8)).filter(ImageFilter.MinFilter(5))).astype(np.float32)
    white = 254.0
    alpha = np.ones(bg.shape, np.float32)
    alpha[bg] = 0.0
    k = band & (ref < white - 30)
    alpha[k] = np.clip((white - minc[k]) / (white - ref[k]), 0.0, 1.0)
    alpha[band & ~k] = 0.0                                                    # 외곽선이 없는 밝은 띠는 배경으로
    out = arr.copy()
    for c in range(3):                                                        # 흰색과 섞인 색을 원래 색으로 되돌림
        ch = out[..., c]
        ch[k] = np.clip((ch[k] - (1 - alpha[k]) * white) / np.maximum(alpha[k], 0.05), 0, 255)
    rgba = np.dstack([out, alpha * 255]).clip(0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def crop_to_content(img: Image.Image, pad: int = 0) -> Image.Image:
    bbox = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        l, t, r, b = bbox
        img = img.crop((max(0, l - pad), max(0, t - pad), min(img.width, r + pad), min(img.height, b + pad)))
    return img


def square(img: Image.Image, size: int, margin: float = 0.04) -> Image.Image:
    """비율을 유지한 채 정사각형 투명 캔버스 중앙에 맞춘다."""
    inner = int(size * (1 - 2 * margin))
    s = min(inner / img.width, inner / img.height)
    r = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(r, ((size - r.width) // 2, (size - r.height) // 2), r)
    return canvas


def main():
    os.makedirs(OUT, exist_ok=True)
    # ---- 저해상도 → 아이콘/파비콘
    small_src = Image.open(os.path.join(SRC, "character_small.png"))
    small = crop_to_content(remove_background(small_src, drop_shadow_below=int(small_src.height * 0.88)), pad=1)
    # ---- 고해상도 → 헤더
    large_src = Image.open(os.path.join(SRC, "character_large.webp"))
    large = crop_to_content(remove_background(large_src, drop_shadow_below=int(large_src.height * 0.84)), pad=2)
    large.save(os.path.join(OUT, "character.png"))
    s = HEADER_H / large.height
    header = large.resize((round(large.width * s), HEADER_H), Image.LANCZOS)
    header.save(os.path.join(OUT, "header.png"))

    # 아이콘: 128px 이하는 저해상도 원본에서, 256px은 고해상도에서 (저해상도를 키우면 흐려지므로)
    frames = []
    for n in ICON_SIZES:
        frames.append(square(small if n <= 128 else large, n))
    frames[-1].save(os.path.join(OUT, "icon.png"))
    square(small, 64).save(os.path.join(OUT, "icon_small.png"))
    frames[-1].save(os.path.join(OUT, "icon.ico"), format="ICO", sizes=[(n, n) for n in ICON_SIZES],
                    append_images=frames[:-1])
    # 파비콘 (웹/바로가기용 작은 크기 묶음)
    fav = [square(small, n, margin=0.02) for n in (16, 32, 48)]
    fav[-1].save(os.path.join(OUT, "favicon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                 append_images=fav[:-1])
    fav[1].save(os.path.join(OUT, "favicon.png"))
    print("만든 파일:", ", ".join(sorted(f for f in os.listdir(OUT) if f != "source")))
    print("header", header.size, "| character", large.size, "| icon source", small.size)


if __name__ == "__main__":
    main()
