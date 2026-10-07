# -*- coding: utf-8 -*-
"""从一张照片生成程序图标（换头像时手动跑一次）。

    python src/make_icon.py                      用 avatar.jpg
    python src/make_icon.py "D:/ pics/me.jpg"    指定别的图

一次生成两份：
    app.ico                                          Windows exe / 任务栏 / 资源管理器
    Android/.../mipmap-*/ic_launcher_fg.png         Android 自适应图标前景层

处理链（原图是白边贴纸风格，直接当图标会显脏）：
    裁方 -> 椭圆柔边遮罩 -> 贴到薄荷深色圆底

为什么不能把原图直接塞进 ico：
    ico 是方形画布，照片常常不是方形，直接塞会被拉伸变形。
    为什么不用纯色底：
    这张图四边是白边不规则的（左深灰右白），纯色底会露出白角。
    底色取薄荷深色 #195E49，和桌面端主题的 MintDeep 同一个值。
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFilter

SIZE = 512
# 底色 =桌面端主题的 MintDeep
MINT_DEEP = (25, 94, 73, 255)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICO_PATH = os.path.join(HERE, "app.ico")
ANDROID_RES = os.path.join(HERE, "Android", "app", "src", "main", "res")
DEFAULT_SOURCE = "avatar.jpg"

# 各密度档的图标边长（自适应图标是 108dp）
DENSITIES = {
    "mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432,
}
# 自适应图标 108 里只有中心 72 是安全区，四周会被各家桌面裁掉，
# 前景内容必须缩进这 72 里面，不然脸会被切
SAFE_RATIO = 72.0 / 108.0

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def load_square(path):
    """读图并裁成正方形。人物脸和帽子都在画面上部，所以往上偏得多一些。"""
    image = Image.open(path).convert("RGB")
    width, height = image.size
    if width != height:
        short = min(width, height)
        left = (width - short) // 2
        top = int((height - short) * 0.02)
        image = image.crop((left, top, left + short, top + short))
    return image.resize((SIZE, SIZE), Image.LANCZOS)


def make_face(square):
    """椭圆柔边遮罩，把人物从白边里摘出来。返回带 alpha 的人物层。"""
    mask = Image.new("L", (SIZE, SIZE), 0)
    # 遮罩画到超出画布：椭圆比画布大，帽子这种顶到边的内容才不会被削掉
    ImageDraw.Draw(mask).ellipse([-30, -30, SIZE + 29, SIZE + 29], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    face = square.convert("RGBA")
    face.putalpha(mask)
    return face


def build_ico(face):
    """Windows 图标：薄荷深色底 + 人物。多尺寸一起写，各档缩放算法不一样。"""
    canvas = Image.new("RGBA", (SIZE, SIZE), MINT_DEEP)
    canvas.alpha_composite(face)
    canvas.save(ICO_PATH, sizes=ICO_SIZES)
    return canvas


def build_android(face):
    """Android 自适应图标前景层：人物缩进中心安全区，底色交给 @color。"""
    for name, size in DENSITIES.items():
        inner = int(size * SAFE_RATIO)
        small = face.resize((inner, inner), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        offset = (size - inner) // 2
        canvas.paste(small, (offset, offset), small)
        folder = os.path.join(ANDROID_RES, "mipmap-" + name)
        os.makedirs(folder, exist_ok=True)
        canvas.save(os.path.join(folder, "ic_launcher_fg.png"))
    return len(DENSITIES)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, DEFAULT_SOURCE)
    if not os.path.exists(source):
        print("找不到图片:", source)
        print("用法: python src/make_icon.py [图片路径]")
        sys.exit(1)

    face = make_face(load_square(source))
    build_ico(face)
    tiers = build_android(face)

    print("原图:", source)
    print("app.ico:", os.path.getsize(ICO_PATH), "bytes  尺寸",
          ", ".join(str(w) + "x" + str(h) for w, h in ICO_SIZES))
    print("Android 前景层: " + str(tiers) + " 个密度档 -> mipmap-*/ic_launcher_fg.png")
    print("旧图标 drawable/ic_launcher_fg.xml 已被 PNG 取代，可删")


if __name__ == "__main__":
    main()
