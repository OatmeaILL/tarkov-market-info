# -*- coding: utf-8 -*-
"""界面配色与字体 —— 风格取自 MaiBill（小睦记账）的「褪色薄荷」设计系统。

配色说明（浅色主题的实际取值）：
    page        #E9ECE5   窗口底色（淡灰绿），比纯白耐看，不刺眼
    bg/surface  #F4F6F1 / #FFFFFF  外层底 / 卡片底
    track       #EDF0EA   输入框 / 轨道
    ink         #1B2A21   正文（深墨绿，比纯黑柔和）
    primary     #1E7A57   主色薄荷（按钮、选中态）
    amber       #8A5D14   警示琥珀

顺带管"分辨率适配"：DENSITY 做整体收紧，enable_dpi_awareness() 让窗口在高 DPI
下不被系统拉伸，Theme.px() 把设计稿像素换算成当前设备的真实像素。
"""

import os

import tkinter.font as tkfont

# 整体收紧系数：< 1 让界面更紧凑。
# 窗口尺寸、卡片内边距、控件高度这些"设计稿像素"都会乘上它，字号不动。
DENSITY = 0.88

# ---------- 浅色（默认）----------

LIGHT = {
    "page": "#E9ECE5",
    "bg": "#F4F6F1",
    "surface": "#FFFFFF",
    "surface2": "#FBFCFA",
    "track": "#EDF0EA",
    "trackbar": "#E2E8E0",
    # 正文 / 次要 / 最浅说明文字。这套值是在 MaiBill 原配色上压深过的：
    # 原稿的 #79857C / #A9B3AB 放在白卡片上对比度只有 3.8 / 2.2，
    # 中文小字看起来很虚 —— 桌面程序里要按 WCAG 补一下。
    "ink": "#1B2A21",
    "ink2": "#5C6960",
    "ink3": "#7B867D",
    "line": "#E8ECE6",
    # 主色对齐 MaiBill v2.4「褪色薄荷」的 MintPrimary（#2E9C74），
    # 之前用的是更暗的 #1E7A57，Hero 区和主按钮都偏闷
    "primary": "#2E9C74",
    "primary_deep": "#195E49",
    "primary_soft": "#6FC9A2",
    "pcont": "#DFF2E8",
    "pon": "#0C3B27",
    "amber": "#C08A2E",
    "amber_c": "#FAF0DA",
    "danger": "#E0574A",
    "danger_c": "#FBE9E6",
    "shadowy": "#D8DED6",
    "on_primary": "#FFFFFF",
}

# ---------- 深色（配色跟随系统时用）----------

DARK = {
    "page": "#070907",
    "bg": "#10140F",
    "surface": "#1A211B",
    "surface2": "#20281F",
    "track": "#263027",
    "trackbar": "#2F3B31",
    "ink": "#E9EEE9",
    "ink2": "#9AA69C",
    "ink3": "#68736A",
    "line": "#242D24",
    "primary": "#4FC08D",
    "primary_deep": "#2E9C74",
    "primary_soft": "#6FC9A2",
    "pcont": "#1E3B2D",
    "pon": "#B9F0D4",
    "amber": "#E0B45E",
    "amber_c": "#332C1C",
    "danger": "#EF7466",
    "danger_c": "#3A211D",
    "shadowy": "#050705",
    "on_primary": "#08160F",
}


def blend(color_a, color_b, ratio):
    """把两个 #rrggbb 颜色按比例混合，ratio=0 返回 a，1 返回 b。

    用来做「悬停」「按下」这类只差一点点的状态色，省得手写一堆色值。
    """
    a = _rgb(color_a)
    b = _rgb(color_b)
    mixed = []
    for index in range(3):
        value = int(round(a[index] + (b[index] - a[index]) * ratio))
        mixed.append(max(0, min(255, value)))
    return "#%02x%02x%02x" % (mixed[0], mixed[1], mixed[2])


def _rgb(color):
    text = color.lstrip("#")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def with_alpha(color, background, ratio):
    """在背景色上叠一层半透明色，tkinter 没有 alpha，只能这样模拟。"""
    return blend(background, color, ratio)


# ---------- 字体 ----------

# 按优先级找系统里最好看的中文字体，找不到就退回 Tk 默认
FAMILY_CANDIDATES = [
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "HarmonyOS Sans SC",
    "PingFang SC",
    "Source Han Sans SC",
    "Noto Sans CJK SC",
    "SimHei",
]


class Fonts:
    """字体表。必须在创建 Tk 根窗口之后再实例化。"""

    def __init__(self):
        self.family = self._pick_family()
        self.mono_family = self._pick_mono()
        self.title = (self.family, 16, "bold")
        self.heading = (self.family, 11, "bold")
        self.subheading = (self.family, 10, "bold")
        self.body = (self.family, 10)
        self.body_bold = (self.family, 10, "bold")
        self.small = (self.family, 9)
        self.small_bold = (self.family, 9, "bold")
        self.tiny = (self.family, 8)
        self.button = (self.family, 11, "bold")
        self.button_small = (self.family, 9, "bold")
        self.big_button = (self.family, 13, "bold")
        self.number = (self.family, 19, "bold")
        self.mono = (self.mono_family, 9)

    def _pick_family(self):
        try:
            available = set(tkfont.families())
        except Exception:
            return "TkDefaultFont"
        for name in FAMILY_CANDIDATES:
            if name in available:
                return name
        return "TkDefaultFont"

    def _pick_mono(self):
        try:
            available = set(tkfont.families())
        except Exception:
            return "Courier New"
        for name in ("Consolas", "Cascadia Mono", "JetBrains Mono", "Courier New"):
            if name in available:
                return name
        return "Courier New"


def enable_dpi_awareness():
    """在创建 Tk 根窗口之前声明 DPI 感知。

    不声明的话，Windows 会把整个窗口按系统缩放做位图拉伸：125% / 150% 下又大又糊，
    而且真实尺寸不受程序控制。Per-Monitor V2 → shcore → 老接口逐级回退，
    全失败也不影响使用（顶多还是被拉伸）。必须在 Tk() 之前调用，返回是否成功。
    """
    if os.name != "nt":
        return False
    import ctypes
    try:
        # -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return True
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return True
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


def detect_scale(root):
    """按真实 DPI 算出设备缩放系数（96dpi = 1.0）。

    必须在声明了 DPI 感知之后、且 Tk 根窗口已建好时调用，才拿得到真实 DPI。
    """
    try:
        dpi = float(root.winfo_fpixels("1i"))
    except Exception:
        return 1.0
    if dpi <= 0:
        return 1.0
    # 夹一下，异常 DPI 不至于把界面撑爆或缩没
    return max(0.75, min(3.0, dpi / 96.0))


class Theme:
    """一套配色 + 字体 + 缩放，界面里所有颜色和尺寸都从这里取。"""

    def __init__(self, dark=False, scale=1.0):
        self.dark = bool(dark)
        self.scale = float(scale) if scale else 1.0
        # 设计稿像素 -> 设备像素：DPI 缩放 × 整体收紧
        self.k = self.scale * DENSITY
        self.colors = dict(DARK if self.dark else LIGHT)
        self.fonts = Fonts()

    def px(self, value):
        """把设计稿里的像素值换算成当前设备的真实像素。"""
        return max(1, int(round(value * self.k)))

    def __getitem__(self, name):
        return self.colors[name]

    def get(self, name, fallback="#000000"):
        return self.colors.get(name, fallback)

    def hover(self, name):
        """悬停态：浅色主题往深处压一点，深色主题往亮处提一点。"""
        base = self.colors[name]
        target = "#000000" if not self.dark else "#FFFFFF"
        return blend(base, target, 0.10 if not self.dark else 0.08)

    def pressed(self, name):
        base = self.colors[name]
        target = "#000000" if not self.dark else "#FFFFFF"
        return blend(base, target, 0.20 if not self.dark else 0.16)

    def mix(self, name, other_name, ratio):
        return blend(self.colors[name], self.colors[other_name], ratio)
