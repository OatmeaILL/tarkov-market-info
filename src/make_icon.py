# -*- coding: utf-8 -*-
"""生成程序图标 app.ico（只在需要换图标时手动跑一次）。"""

import os

from PIL import Image, ImageDraw, ImageFont

SIZE = 512
GOLD = (199, 162, 82, 255)
GOLD_BRIGHT = (227, 194, 116, 255)
DARK = (20, 23, 15, 255)

OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.ico")


def main():
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin = 18
    # 外圈：金色粗环
    draw.ellipse(
        [margin, margin, SIZE - margin, SIZE - margin],
        fill=DARK, outline=GOLD, width=16,
    )
    # 内圈：细装饰线
    inner = margin + 34
    draw.ellipse(
        [inner, inner, SIZE - inner, SIZE - inner],
        outline=(199, 162, 82, 110), width=4,
    )

    # 中间的字母 T
    font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 250)
    box = draw.textbbox((0, 0), "T", font=font)
    text_width = box[2] - box[0]
    text_height = box[3] - box[1]
    pos_x = (SIZE - text_width) / 2 - box[0]
    pos_y = (SIZE - text_height) / 2 - box[1]
    draw.text((pos_x, pos_y), "T", font=font, fill=GOLD_BRIGHT)

    image.save(
        OUTPUT,
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("图标已生成:", OUTPUT, os.path.getsize(OUTPUT), "bytes")


if __name__ == "__main__":
    main()
