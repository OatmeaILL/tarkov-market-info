# -*- coding: utf-8 -*-
"""把排行数据画成一张竖版长图（PNG）。

这里**不用无头浏览器**：Windows 上 msedge.exe 只是个转发器，用户开着浏览器时
新进程会被已有实例接走，`--screenshot` 静默失败（返回码还是 0），
截图文件要等好几秒才落盘、还经常干脆不出来。依赖它就会变成"点了生成没反应"。

所以直接用 PIL 自己排版绘制：结果稳定、几秒出图、不依赖任何外部程序，
版式（标题 / 表头 / 排名 / 图标 / 名称 / 价格 / 挂单）和 HTML 报告对得上。
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

# 成图宽度（像素）。1200 宽在手机和电脑上都不会糊
RENDER_WIDTH = 1200
# 所有尺寸都按这个倍率放大一次，方便统一调整疏密
RENDER_SCALE = 1.5

# 配色跟 report.py 里的 HTML 报告保持一致，两个产物看起来是一家人
PALETTE = {
    "bg": (11, 13, 9),
    "card": (20, 23, 15),
    "row": (23, 27, 18),
    "row_alt": (18, 21, 14),
    "gold": (199, 162, 82),
    "gold_bright": (227, 194, 116),
    "text": (217, 214, 203),
    "dim": (141, 139, 128),
    "line": (44, 50, 33),
    "good": (111, 158, 74),
    "bad": (176, 75, 60),
    "rank2": (203, 200, 189),
    "rank3": (185, 139, 94),
}

# 按优先级找能画中文的字体，找不到就退回 PIL 默认位图字体
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\segoeui.ttf",
]

FONT_CANDIDATES_BOLD = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
]

# 卢布符号 ₽（U+20BD）在微软雅黑 / 黑体 / 宋体里都没有字形，直接画会变成豆腐块，
# 所以带金额的那行单独用有该字形的西文字体（数字部分两边都一样）
LATIN_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
]

_font_cache = {}


def _load_first_font(candidates, size):
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return None


def load_font(size, bold=False):
    """找一个能画中文的字体，找不到就退回默认（中文会变方块，但不会崩）。"""
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    candidates = FONT_CANDIDATES_BOLD if bold else FONT_CANDIDATES
    font = _load_first_font(candidates, size)
    if font is None:
        font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def load_latin_font(size):
    """带 ₽ 字形的西文字体，用来单独画金额。"""
    key = ("latin", size)
    if key in _font_cache:
        return _font_cache[key]
    font = _load_first_font(LATIN_FONT_CANDIDATES, size)
    if font is None:
        font = load_font(size, bold=True)
    _font_cache[key] = font
    return font


def find_icon_path(icon_dir, item_id):
    if not icon_dir:
        return ""
    for suffix in (".webp", ".png", ".jpg"):
        path = os.path.join(icon_dir, item_id + suffix)
        if os.path.exists(path):
            return path
    return ""


def load_icon(icon_dir, item_id, height):
    """读物品图标并缩到指定高度，读不到就返回 None（那行就不画图）。"""
    path = find_icon_path(icon_dir, item_id)
    if not path:
        return None
    try:
        icon = Image.open(path).convert("RGBA")
    except Exception:
        return None
    if icon.height <= 0:
        return None
    ratio = height / float(icon.height)
    width = max(1, int(icon.width * ratio))
    return icon.resize((width, height), Image.LANCZOS)


def app_icon_path():
    """拿 exe 图标当长图右上角的装饰，找不到就算了。"""
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(os.path.join(sys._MEIPASS, "app.ico"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(os.path.dirname(here), "app.ico"))
    candidates.append(os.path.join(here, "app.ico"))
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def format_money(value):
    if not value:
        return "0"
    return format(int(value), ",")


def liquidity_tag(offer_count):
    """挂单数 → （标签文字, 颜色）。跟 HTML 报告里的口径一致。"""
    if offer_count >= 10:
        return "流通好", PALETTE["good"]
    if offer_count >= 3:
        return "一般", PALETTE["gold"]
    return "价格失真", PALETTE["bad"]


def sort_field_label(sort_field):
    try:
        from data import sort_label
        return sort_label(sort_field)
    except Exception:
        return sort_field


def fit_text(draw, text, font, max_width):
    """把文字裁到 max_width 像素内，超出部分用省略号。

    HTML 报告那边靠 CSS 的 text-overflow 截断，长图是自己画的，得手动量宽度，
    否则像 "Nightforce MagMount ..." 这种长英文名会直接压到价格列上。
    """
    text = str(text)
    if max_width <= 0:
        return text
    try:
        if draw.textlength(text, font=font) <= max_width:
            return text
    except Exception:
        return text
    ellipsis = "…"
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        try:
            width = draw.textlength(text[:mid] + ellipsis, font=font)
        except Exception:
            return text[:mid]
        if width <= max_width:
            low = mid
        else:
            high = mid - 1
    return text[:low] + ellipsis


def render_long_image(items, output_png, options, context, width=RENDER_WIDTH):
    """把排行画成一张长图并存成 PNG，返回 (宽, 高)。"""
    scale = RENDER_SCALE
    margin = int(32 * scale)
    row_height = int(62 * scale)
    icon_height = int(38 * scale)
    rank_width = int(34 * scale)
    icon_width = int(62 * scale)
    price_width = int(190 * scale)
    offers_width = int(150 * scale)
    header_height = int(118 * scale)
    footer_height = int(96 * scale)

    font_title = load_font(int(25 * scale), bold=True)
    font_sub = load_font(int(12 * scale))
    font_name = load_font(int(14 * scale))
    font_name_en = load_font(int(11 * scale))
    font_price = load_latin_font(int(15 * scale))
    font_rank = load_font(int(16 * scale), bold=True)
    font_tag = load_font(int(11 * scale))

    sort_field = options.get("sort_field", "avg24h")
    label = sort_field_label(sort_field)

    height = header_height + row_height * len(items) + footer_height
    image = Image.new("RGB", (width, height), PALETTE["bg"])
    draw = ImageDraw.Draw(image)

    # ---- 标题区 ----
    draw.text(
        (margin, int(30 * scale)),
        "塔科夫跳蚤市场排行 · " + label,
        font=font_title,
        fill=PALETTE["gold_bright"],
    )
    subtitle = (
        "第 1 ~ " + str(len(items)) + " 名 · "
        + ("从高到低" if options.get("descending", True) else "从低到高")
        + " · 模式 " + str(context.get("game_mode", "PVE"))
        + " · 索引 " + str(context.get("total_items", 0)) + " 项"
        + " · 同步 " + str(context.get("sync_time", "未知"))
    )
    draw.text((margin, int(70 * scale)), subtitle, font=font_sub, fill=PALETTE["dim"])
    line_y = header_height - int(14 * scale)
    draw.line([(margin, line_y), (width - margin, line_y)], fill=PALETTE["line"], width=2)

    # ---- 表头 ----
    price_x = width - margin - offers_width - price_width
    # 名称列的可用宽度：到价格列为止，右侧留一点空隙，超长名字裁掉
    name_max_width = price_x - margin - rank_width - icon_width - int(12 * scale)
    header_y = header_height - int(46 * scale)
    draw.text(
        (margin + (rank_width + icon_width) / 2, header_y),
        "物品",
        font=font_tag,
        fill=PALETTE["dim"],
        anchor="ma",
    )
    draw.text(
        (price_x + price_width, header_y),
        label,
        font=font_tag,
        fill=PALETTE["dim"],
        anchor="ra",
    )
    draw.text(
        (width - margin, header_y),
        "挂单",
        font=font_tag,
        fill=PALETTE["dim"],
        anchor="ra",
    )

    # ---- 每一行物品 ----
    top = header_height
    for index, item in enumerate(items):
        y = top + index * row_height
        row_background = PALETTE["row"] if index % 2 == 0 else PALETTE["row_alt"]
        draw.rectangle([margin, y, width - margin, y + row_height - 2], fill=row_background)

        # 排名（前三名上色）
        if index == 0:
            rank_color = PALETTE["gold_bright"]
        elif index == 1:
            rank_color = PALETTE["rank2"]
        elif index == 2:
            rank_color = PALETTE["rank3"]
        else:
            rank_color = PALETTE["dim"]
        draw.text(
            (margin + rank_width / 2, y + row_height / 2),
            str(index + 1),
            font=font_rank,
            fill=rank_color,
            anchor="mm",
        )

        # 图标
        icon_x = margin + rank_width
        icon = load_icon(context.get("icon_dir", ""), item["id"], icon_height)
        if icon is not None:
            image.paste(
                icon,
                (
                    int(icon_x + (icon_width - icon.width) / 2),
                    int(y + (row_height - icon.height) / 2),
                ),
                icon,
            )

        # 名称（中英文两行，超长截断，别压到价格列）
        text_x = icon_x + icon_width
        draw.text(
            (text_x, y + int(15 * scale)),
            fit_text(draw, item["name_zh"], font_name, name_max_width),
            font=font_name,
            fill=PALETTE["text"],
        )
        draw.text(
            (text_x, y + int(35 * scale)),
            fit_text(draw, item["name_en"], font_name_en, name_max_width),
            font=font_name_en,
            fill=PALETTE["dim"],
        )

        # 价格（排序口径对应的值 + 24h 区间）
        draw.text(
            (price_x + price_width, y + int(14 * scale)),
            "₽ " + format_money(item.get(sort_field, 0)),
            font=font_price,
            fill=PALETTE["gold_bright"],
            anchor="ra",
        )
        low = format_money(item["low24h"]) if item.get("low24h", 0) > 0 else "—"
        high = format_money(item["high24h"]) if item.get("high24h", 0) > 0 else "—"
        draw.text(
            (price_x + price_width, y + int(36 * scale)),
            "区间 " + low + " ~ " + high,
            font=font_tag,
            fill=PALETTE["dim"],
            anchor="ra",
        )

        # 挂单（右上标签 + 右下短名）
        count = item.get("offer_count", 0)
        tag_text, tag_color = liquidity_tag(count)
        draw.text(
            (width - margin, y + int(14 * scale)),
            tag_text + " · " + str(count) + " 条",
            font=font_tag,
            fill=tag_color,
            anchor="ra",
        )
        if item.get("short_name"):
            draw.text(
                (width - margin, y + int(36 * scale)),
                str(item["short_name"]),
                font=font_tag,
                fill=PALETTE["dim"],
                anchor="ra",
            )

    # ---- 页脚 ----
    footer_y = top + row_height * len(items) + int(28 * scale)
    draw.line(
        [(margin, footer_y - int(18 * scale)), (width - margin, footer_y - int(18 * scale))],
        fill=PALETTE["line"],
        width=2,
    )
    draw.text(
        (margin, footer_y),
        "跳蚤均价 = Tarkov.dev 基于跳蚤市场挂单统计的 24 小时均价；挂单少于 3 条时价格参考价值有限。",
        font=font_sub,
        fill=PALETTE["dim"],
    )
    draw.text(
        (margin, footer_y + int(24 * scale)),
        "数据来源：" + str(context.get("db_path", "")),
        font=font_sub,
        fill=PALETTE["dim"],
    )

    # ---- 右上角放个程序图标（纯装饰）----
    logo_path = app_icon_path()
    if logo_path:
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo = logo.resize((int(48 * scale), int(48 * scale)), Image.LANCZOS)
            logo.putalpha(logo.split()[3].point(lambda value: int(value * 0.85)))
            image.paste(logo, (width - margin - logo.width, int(26 * scale)), logo)
        except Exception:
            pass

    image.save(output_png, optimize=True)
    return image.size
