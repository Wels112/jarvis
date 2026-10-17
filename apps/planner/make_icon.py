# -*- coding: utf-8 -*-
"""Значок планировщика (planner.ico): лист недели с цветными делами. Рисуется кодом —
без картинок со стороны.  python apps\\planner\\make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).with_name("planner.ico")


def draw(size: int = 256) -> Image.Image:
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([12 * s, 20 * s, 244 * s, 240 * s], radius=34 * s, fill=(255, 255, 255, 255),
                        outline=(214, 209, 199, 255), width=max(1, int(4 * s)))
    d.rounded_rectangle([12 * s, 20 * s, 244 * s, 78 * s], radius=34 * s, fill=(28, 31, 34, 255))
    d.rectangle([12 * s, 50 * s, 244 * s, 78 * s], fill=(28, 31, 34, 255))
    for x in (70, 128, 186):                                   # кольца сверху
        d.rounded_rectangle([(x - 7) * s, 6 * s, (x + 7) * s, 44 * s], radius=7 * s, fill=(160, 166, 172, 255))
    # Дела недели — блоки цветов категорий в трёх колонках
    blocks = [(36, 96, 92, 140, (47, 125, 109)), (100, 96, 156, 176, (63, 98, 196)),
              (164, 120, 220, 160, (169, 100, 15)), (36, 152, 92, 216, (63, 98, 196)),
              (100, 188, 156, 216, (47, 125, 109)), (164, 172, 220, 216, (122, 79, 176))]
    for x1, y1, x2, y2, c in blocks:
        d.rounded_rectangle([x1 * s, y1 * s, x2 * s, y2 * s], radius=9 * s, fill=c + (255,))
    return img


if __name__ == "__main__":
    big = draw(256)
    big.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(OUT)
