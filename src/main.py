# -*- coding: utf-8 -*-
"""Tarkov 市场排行生成器 —— 图形界面入口。

界面风格取自 MaiBill（小睦记账）的「褪色薄荷」设计系统：
浅灰绿底 + 白卡片 + 薄荷绿主色，圆角、留白、说话直白。

打包成单文件 exe 时这个文件是启动点。
所有运行时文件都在 exe 所在文件夹**里面**、按类型分目录放
（data 数据库配置 / icon 图标 / reports 报表），
不在 %APPDATA% 之类的系统目录里留东西（整个文件夹拷走就能用）。
目录名的唯一真源在 data.py（DATA_SUBDIR / ICON_SUBDIR / REPORT_SUBDIR）。
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox

import capture
import data
import report
import sync
import theme as theme_module
import widgets

APP_NAME = "Tarkov 市场排行生成器"
# 1.4 = 修两处搜索/排序缺陷：搜配件时配件不再被扣分（wants_part 之前是死变量）；
#       48h涨跌榜的涨栏/跌栏按符号分开过滤，不再互相串
APP_VERSION = "1.4"

# 作者与开源地址，设置窗口的「关于」卡片显示这个
AUTHOR = "OatmeaILL"
GITHUB_URL = "https://github.com/OatmeaILL/tarkov-market-info"

WINDOW_WIDTH = 860
WINDOW_MIN_HEIGHT = 560
WINDOW_MAX_HEIGHT = 980


def resource_path(name):
    """取打包进 exe 的资源路径（图标用）。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def config_path():
    """配置文件放在 data\\ 里，和数据库、收藏、错误日志作伴。"""
    return data.config_path()


def legacy_output_dir():
    """旧版本的默认输出目录（文档下的 TarkovMarketInfo），用来识别"用户没手动选过"。"""
    base = os.path.join(os.path.expanduser("~"), "Documents")
    if not os.path.exists(base):
        base = os.path.expanduser("~")
    return os.path.join(base, "TarkovMarketInfo")


def default_output_dir():
    """报表默认输出到 exe 目录下的 reports\\，不跟 exe 和数据库混在一块。"""
    path = data.reports_dir()
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return data.app_dir()
    return path


def load_config():
    path = config_path()
    if not os.path.exists(path):
        return {}
    try:
        handle = open(path, "r", encoding="utf-8")
        config = json.load(handle)
        handle.close()
        return config
    except Exception:
        return {}


def save_config(config):
    try:
        data.ensure_dirs()
        handle = open(config_path(), "w", encoding="utf-8")
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.close()
    except Exception:
        pass


def write_error_log(text):
    """界面版程序看不到控制台，异常要落到文件里才好排查。"""
    try:
        path = data.error_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = open(path, "a", encoding="utf-8")
        handle.write("[" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "]\n")
        handle.write(text + "\n\n")
        handle.close()
    except Exception:
        pass


def to_file_url(path):
    """转成浏览器能识别的 file:// 地址（正斜杠）。"""
    absolute = os.path.abspath(path).replace("\\", "/")
    return "file:///" + absolute


def open_in_browser(path):
    """用系统默认浏览器打开文件 / 文件夹。"""
    if not path or not os.path.exists(path):
        return False
    try:
        if os.name == "nt":
            os.startfile(path)
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
            return True
        return webbrowser.open(to_file_url(path))
    except Exception:
        write_error_log(traceback.format_exc())
        return False


def work_area(root):
    """返回屏幕可用区域尺寸 (宽, 高)。

    Windows 上会扣掉任务栏（SystemParametersInfo SPI_GETWORKAREA），
    其它平台没有这个概念就退回整屏。窗口按这个来限尺寸，才不会顶出屏幕。
    """
    width = root.winfo_screenwidth()
    height = root.winfo_screenheight()
    if os.name != "nt":
        return width, height
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        rect = RECT()
        # SPI_GETWORKAREA = 0x0030
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x0030, 0, ctypes.byref(rect), 0
        )
        if ok:
            return rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        pass
    return width, height


class SyncProgressWindow:
    """更新数据时单独弹出的小窗：数据和图标各一条进度条。

    主界面底部那条进度条还在（看总进度），这个窗专门用来看两个阶段分别走到哪了。
    """

    def __init__(self, parent, theme, on_cancel):
        self.theme = theme
        self.on_cancel = on_cancel
        self.window = tk.Toplevel(parent)
        self.window.title("正在更新数据")
        self.window.configure(bg=theme["page"])
        self.window.resizable(False, False)
        self.window.transient(parent)
        try:
            self.window.iconbitmap(default=resource_path("app.ico"))
        except Exception:
            pass

        body = tk.Frame(self.window, bg=theme["page"])
        body.pack(fill="both", expand=True, padx=theme.px(20), pady=theme.px(18))

        self.heading = tk.Label(
            body, text="正在从 tarkov.dev 更新数据", bg=theme["page"],
            fg=theme["ink"], font=theme.fonts.heading, anchor="w",
        )
        self.heading.pack(fill="x", pady=(0, theme.px(14)))

        self.rows = {
            sync.PHASE_DATA: self._build_row(body, "数据"),
            sync.PHASE_ICON: self._build_row(body, "图标"),
        }

        self.cancel_button = widgets.Button(
            body, theme, "取消", command=self._cancel, variant="secondary",
            font=theme.fonts.button_small, height=32, radius=10, min_width=88,
        )
        self.cancel_button.pack(anchor="e", pady=(theme.px(6), 0))

        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self._center(parent)

    def _build_row(self, parent, name):
        theme = self.theme
        row = tk.Frame(parent, bg=theme["page"])
        row.pack(fill="x", pady=(0, theme.px(12)))

        top = tk.Frame(row, bg=theme["page"])
        top.pack(fill="x")
        tk.Label(
            top, text=name, bg=theme["page"], fg=theme["ink"],
            font=theme.fonts.subheading, anchor="w",
        ).pack(side="left")
        percent = tk.Label(
            top, text="等待中", bg=theme["page"], fg=theme["ink3"],
            font=theme.fonts.small_bold, anchor="e",
        )
        percent.pack(side="right")

        bar = widgets.ProgressBar(row, theme, width=420, height=8)
        bar.pack(fill="x", pady=(theme.px(6), 0))

        detail = tk.Label(
            row, text="", bg=theme["page"], fg=theme["ink3"],
            font=theme.fonts.small, anchor="w", justify="left",
        )
        detail.pack(fill="x", pady=(theme.px(4), 0))
        return {"bar": bar, "percent": percent, "detail": detail}

    def _center(self, parent):
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 3
        self.window.geometry("%dx%d+%d+%d" % (width, height, max(20, x), max(20, y)))

    def _cancel(self):
        self.cancel_button.set_state("disabled")
        self.cancel_button.set_text("正在取消 ...")
        self.on_cancel()

    def set_progress(self, phase, text, value):
        row = self.rows.get(phase)
        if row is None:
            return
        value = max(0.0, min(1.0, float(value or 0.0)))
        row["bar"].set(value)
        row["percent"].configure(text="%d%%" % int(value * 100))
        if text and text != row["detail"].cget("text"):
            row["detail"].configure(text=text)

    def close(self):
        try:
            self.window.destroy()
        except Exception:
            pass


class MarketApp:
    def __init__(self, root, force_dark=None, force_scale=None):
        self.root = root
        self.log_queue = queue.Queue()
        self.config = load_config()
        self.ui_queue = queue.Queue()
        self.force_dark = force_dark
        self.force_scale = force_scale

        # 数据更新已挪到主窗口的「数据与设置」。报表窗口只负责生成报告，
        # 这里留个开关：False 时不画同步那一块、也不自动更新。
        self.sync_enabled = True

        self.db_path_var = tk.StringVar()
        self.icon_dir_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.sort_label_var = tk.StringVar()
        self.order_var = tk.IntVar()
        self.limit_var = tk.StringVar()
        self.min_price_var = tk.StringVar()
        self.keyword_var = tk.StringVar()
        self.flea_only_var = tk.IntVar()
        self.skip_zero_var = tk.IntVar()
        # 报告右下角那个涨跌榜浮窗，勾哪个就出哪一列
        self.movers_up_var = tk.IntVar()
        self.movers_down_var = tk.IntVar()
        self.export_html_var = tk.IntVar()
        self.export_png_var = tk.IntVar()
        self.export_csv_var = tk.IntVar()
        self.open_after_var = tk.IntVar()
        self.with_icons_var = tk.IntVar()
        self.mode_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.footer_status_var = tk.StringVar()
        self.sync_state_var = tk.StringVar()

        self.label_to_field = {}
        self.sort_labels = []
        for label, field in data.SORT_OPTIONS:
            self.label_to_field[label] = field
            self.sort_labels.append(label)

        self.last_html_path = ""
        self.summary = None
        self.busy = False
        self.sync_cancel = [False]
        self.sync_window = None
        self.sync_auto = False
        self.folded = {}

        self.build_ui()
        self.apply_config()
        self.watch_filter_vars()
        self.update_filter_summary()
        self.refresh_header_status()
        self.refresh_db_status_async()

        self.root.after(100, self.poll_queues)
        if self.sync_enabled:
            # 等主窗口显示出来了再看要不要自动更新，免得进度窗抢在空白窗口前面弹
            self.root.after(600, self.auto_sync_if_needed)

    # ---------- 界面搭建 ----------

    def _on_callback_error(self, exc_type, exc_value, exc_tb):
        """界面回调里未捕获的异常：写 error.log 并在运行记录里说一声。"""
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        write_error_log(detail)
        try:
            self.append_log("界面回调出错：" + str(exc_value) + "（详见 error.log）", "bad")
        except Exception:
            pass

    def build_ui(self):
        root = self.root
        root.title(APP_NAME + " v" + APP_VERSION)
        root.resizable(True, True)

        # 先让窗口完全透明，等尺寸量完、布局排好再显形。
        # 不做这一步的话：place_window 里第一次 update() 会先把窗口按最小尺寸
        # （616x413）画出来，紧接着 set geometry 又整屏重排重画一次 —— 看上去就是
        # 先弹个小窗 → 所有组件抖一下 → 突然变成大窗。
        self.alpha_supported = True
        try:
            root.attributes("-alpha", 0.0)
        except Exception:
            self.alpha_supported = False

        # 固定浅色（白底为主）。原来跟随系统深色主题，系统一开深色整屏就变黑；
        # 想要深色只是开发 / 截图时用 --dark。
        dark = bool(self.force_dark)
        if self.force_scale is None:
            scale = theme_module.detect_scale(root)
        else:
            scale = float(self.force_scale)
        self.theme = theme_module.Theme(dark=dark, scale=scale)
        self.colors = self.theme.colors
        widgets.style_combobox(root, self.theme)

        # 最小尺寸也跟着缩放走，否则窄屏下内容会被硬挤
        root.minsize(self.theme.px(700), self.theme.px(470))

        root.configure(bg=self.colors["page"])
        root.grid_rowconfigure(1, weight=1)
        root.grid_columnconfigure(0, weight=1)
        # Tkinter 默认把回调里的异常打到 stderr，窗口程序根本看不到 —— 落进 error.log 才好查
        root.report_callback_exception = self._on_callback_error

        try:
            root.iconbitmap(default=resource_path("app.ico"))
        except Exception:
            pass

        self.build_header(root)
        self.build_body(root)
        self.build_footer(root)

        self.place_window()

    def place_window(self):
        """先按内容量出合适高度，再按屏幕可用区收一遍，最后居中。

        这里必须用 update()：只 update_idletasks() 的话嵌套卡片的高度还没算出来，
        量到的内容高度会偏小，窗口一开就带滚动条。
        """
        root = self.root
        root.update()

        pad_top, pad_bottom = self.scroll.padding[1], self.scroll.padding[3]
        body_height = self.scroll.content.winfo_reqheight() + pad_top + pad_bottom
        wanted_width = self.theme.px(WINDOW_WIDTH)
        # 头部 / 底部的 grid 外边距也算进去，不然量出来的高度会比实际少一截，
        # 一开窗就带滚动条、底下那行被藏住
        header_height = self.header.winfo_reqheight() + self.theme.px(18 + 10)
        footer_height = self.footer.winfo_reqheight() + self.theme.px(8 + 18)
        wanted_height = header_height + body_height + footer_height + self.theme.px(30)

        # 屏幕可用区（Windows 会扣掉任务栏），窗口不许超出它
        area_width, area_height = work_area(root)
        margin = self.theme.px(24)
        max_width = max(self.theme.px(620), area_width - margin)
        # 高度只占工作区的一部分，别一开就把屏幕吃掉
        max_height = max(self.theme.px(420), int(area_height * 0.86) - margin)

        width = min(wanted_width, max_width)
        height = max(
            self.theme.px(WINDOW_MIN_HEIGHT),
            min(wanted_height, self.theme.px(WINDOW_MAX_HEIGHT), max_height),
        )

        pos_x = max(12, (area_width - width) // 2)
        pos_y = max(12, (area_height - height) // 3)
        root.geometry(
            str(width) + "x" + str(height) + "+" + str(pos_x) + "+" + str(pos_y)
        )
        root.update()
        self.scroll.refresh()

        # 布局和尺寸都落地了，这时显形，用户只会看到最终状态
        if self.alpha_supported:
            root.attributes("-alpha", 1.0)
            root.update_idletasks()

    # --- 顶部 ---

    def build_header(self, root):
        header = tk.Frame(root, bg=self.colors["page"], bd=0, highlightthickness=0)
        header.grid(
            row=0, column=0, sticky="ew",
            padx=self.theme.px(24), pady=(self.theme.px(18), self.theme.px(10)),
        )
        self.header = header

        left = tk.Frame(header, bg=self.colors["page"])
        left.pack(side="left", anchor="w")

        title = tk.Label(
            left,
            text="塔科夫市场排行生成器",
            bg=self.colors["page"],
            fg=self.colors["ink"],
            font=self.theme.fonts.title,
            anchor="w",
        )
        title.pack(anchor="w")

        subtitle = tk.Label(
            left,
            text="选好条件点一下，就能拿到一份带图的价格排行",
            bg=self.colors["page"],
            fg=self.colors["ink2"],
            font=self.theme.fonts.small,
            anchor="w",
        )
        subtitle.pack(anchor="w", pady=(self.theme.px(4), 0))

        right = tk.Frame(header, bg=self.colors["page"])
        right.pack(side="right", anchor="e")
        self.status_pill = widgets.Pill(right, self.theme, "正在检查数据 ...", "idle")
        self.status_pill.pack(anchor="e")

    # --- 中间滚动区 ---

    def build_body(self, root):
        self.scroll = widgets.ScrollArea(root, self.theme, padding=(24, 4, 24, 24))
        self.scroll.grid(row=1, column=0, sticky="nsew")
        body = self.scroll.body()

        self.build_action_card(body)
        self.build_options_card(body)
        self.build_data_card(body)
        self.build_log_card(body)

    def build_action_card(self, body):
        card = widgets.RoundCard(
            body,
            self.theme,
            padding=(20, 18, 20, 18),
            title="生成排行报告",
            subtitle=(
                "导出目录已经填好；物品数据在主窗口的「数据与设置」里管。"
                if not self.sync_enabled
                else "导出目录已经填好；第一次用先去下面「数据来源」点「更新数据」。"
            ),
        )
        self.scroll.add(card, pady=(0, 14))

        self.generate_button = widgets.Button(
            card.body,
            self.theme,
            "开始生成",
            command=self.on_generate,
            variant="primary",
            icon="▶",
            font=self.theme.fonts.big_button,
            height=46,
            radius=14,
        )
        self.generate_button.pack(fill="x", pady=(0, self.theme.px(6)))

        hint = tk.Label(
            card.body,
            text="生成后会自动用浏览器打开报告；文件同时存到下面的目录里。",
            bg=self.colors["surface"],
            fg=self.colors["ink3"],
            font=self.theme.fonts.small,
            anchor="center",
        )
        hint.pack(fill="x", pady=(0, self.theme.px(14)))

        card.divider(pady=(0, 12))

        title = tk.Label(
            card.body,
            text="要输出哪些文件",
            bg=self.colors["surface"],
            fg=self.colors["ink"],
            font=self.theme.fonts.subheading,
            anchor="w",
        )
        title.pack(fill="x", pady=(0, self.theme.px(8)))

        options = [
            ("网页报告", self.export_html_var, "推荐：双击就能看，也能直接发群里"),
            ("长图 PNG", self.export_png_var, "一整张竖图，适合发帖、存手机"),
            ("表格 CSV", self.export_csv_var, "拉进 Excel 自己算"),
            ("生成后自动打开", self.open_after_var, "生成完用默认浏览器打开这份报告"),
        ]
        # 两列排布：四条竖着排会把卡片撑得很高，窗口就得跟着变高
        option_grid = tk.Frame(card.body, bg=self.colors["surface"])
        option_grid.pack(fill="x", pady=(0, self.theme.px(4)))
        option_grid.grid_columnconfigure(0, weight=1, uniform="outfile")
        option_grid.grid_columnconfigure(1, weight=1, uniform="outfile")
        for index, (text, variable, note) in enumerate(options):
            box = widgets.CheckBox(
                option_grid, self.theme, text, variable, note=note, wraplength=300
            )
            box.grid(
                row=index // 2, column=index % 2, sticky="w",
                pady=(0, self.theme.px(8)),
            )

        card.divider(pady=(12, 12))

        folder_title = tk.Label(
            card.body,
            text="保存到哪个文件夹",
            bg=self.colors["surface"],
            fg=self.colors["ink"],
            font=self.theme.fonts.subheading,
            anchor="w",
        )
        folder_title.pack(fill="x", pady=(0, self.theme.px(8)))

        folder_row = tk.Frame(card.body, bg=self.colors["surface"])
        folder_row.pack(fill="x")
        self.make_path_entry(folder_row, self.output_dir_var).pack(
            side="left", fill="x", expand=True
        )
        widgets.Button(
            folder_row, self.theme, "选择", command=self.on_pick_output, variant="secondary",
            font=self.theme.fonts.button_small, height=34, radius=10,
        ).pack(side="left", padx=(self.theme.px(8), 0))
        widgets.Button(
            folder_row, self.theme, "打开文件夹", command=self.on_open_output, variant="ghost",
            font=self.theme.fonts.button_small, height=34, radius=10,
        ).pack(side="left", padx=(self.theme.px(8), 0))

        self.result_row = tk.Frame(card.body, bg=self.colors["surface"])
        self.result_label = tk.Label(
            self.result_row,
            text="",
            bg=self.colors["surface"],
            fg=self.colors["primary"],
            font=self.theme.fonts.small_bold,
            anchor="w",
        )
        self.result_label.pack(side="left")
        self.open_report_button = widgets.Button(
            self.result_row,
            self.theme,
            "打开报告",
            command=self.on_open_report,
            variant="link",
            font=self.theme.fonts.small_bold,
            height=26,
            radius=8,
        )
        self.open_report_button.pack(side="left", padx=(self.theme.px(10), 0))
        self.open_report_button.set_state("disabled")

        self.action_card = card

    def build_options_card(self, body):
        card = widgets.RoundCard(
            body,
            self.theme,
            padding=(20, 16, 20, 16),
            title="筛选条件",
            subtitle=None,
        )
        self.scroll.add(card, pady=(0, 14))
        self.options_card = card

        toggle_row = tk.Frame(card.body, bg=self.colors["surface"])
        toggle_row.pack(fill="x")

        summary = tk.Label(
            toggle_row,
            textvariable=self.status_var,
            bg=self.colors["surface"],
            fg=self.colors["ink2"],
            font=self.theme.fonts.small,
            anchor="w",
        )
        summary.pack(side="left")

        self.options_toggle = widgets.Button(
            toggle_row,
            self.theme,
            "展开 ▾",
            command=lambda: self.toggle_section("options"),
            variant="link",
            font=self.theme.fonts.small_bold,
            height=24,
            radius=8,
        )
        self.options_toggle.pack(side="right")

        content = tk.Frame(card.body, bg=self.colors["surface"])
        self.folded["options"] = {"content": content, "button": self.options_toggle,
                                  "card": card, "open": False, "open_text": "收起 ▴",
                                  "closed_text": "展开 ▾"}

        rows = tk.Frame(content, bg=self.colors["surface"])
        rows.pack(fill="x")
        rows.grid_columnconfigure(0, weight=3)
        rows.grid_columnconfigure(1, weight=2)

        sort_box = tk.Frame(rows, bg=self.colors["surface"])
        sort_box.grid(row=0, column=0, sticky="w", pady=(0, self.theme.px(10)))
        widgets.small_label(sort_box, self.theme, "按什么排序", "dim").pack(anchor="w", pady=(0, self.theme.px(5)))
        widgets.make_combo(
            sort_box, self.theme, self.sort_label_var, self.sort_labels, width=18
        ).pack(anchor="w")

        order_box = tk.Frame(rows, bg=self.colors["surface"])
        order_box.grid(row=0, column=1, sticky="w", pady=(0, self.theme.px(10)))
        widgets.small_label(order_box, self.theme, "顺序", "dim").pack(anchor="w", pady=(0, self.theme.px(5)))
        widgets.Segmented(
            order_box,
            self.theme,
            [("贵的在前", 1), ("便宜的在前", 0)],
            self.order_var,
            height=32,
        ).pack(anchor="w")

        count_box = tk.Frame(rows, bg=self.colors["surface"])
        count_box.grid(row=1, column=0, sticky="w", pady=(0, self.theme.px(10)))
        widgets.small_label(count_box, self.theme, "显示多少条", "dim").pack(
            anchor="w", pady=(0, self.theme.px(5))
        )
        widgets.make_entry(count_box, self.theme, self.limit_var, width=10).pack(anchor="w")

        gate_box = tk.Frame(rows, bg=self.colors["surface"])
        gate_box.grid(row=1, column=1, sticky="w", pady=(0, self.theme.px(10)))
        widgets.small_label(
            gate_box, self.theme, "低于这个价就不显示（0 = 不限）", "dim"
        ).pack(anchor="w", pady=(0, self.theme.px(5)))
        widgets.make_entry(gate_box, self.theme, self.min_price_var, width=16).pack(anchor="w")

        keyword_box = tk.Frame(content, bg=self.colors["surface"])
        keyword_box.pack(fill="x", pady=(0, self.theme.px(10)))
        widgets.small_label(
            keyword_box, self.theme, "只看名字里带这些字的（中英文都行，留空 = 全部）", "dim"
        ).pack(anchor="w", pady=(0, self.theme.px(5)))
        widgets.make_entry(keyword_box, self.theme, self.keyword_var, width=32).pack(
            anchor="w", fill="x"
        )

        check_row = tk.Frame(content, bg=self.colors["surface"])
        check_row.pack(fill="x")
        widgets.CheckBox(
            check_row, self.theme, "只要能在跳蚤市场买卖的", self.flea_only_var
        ).pack(side="left", padx=(0, self.theme.px(22)))
        widgets.CheckBox(
            check_row, self.theme, "跳过价格为 0 的条目", self.skip_zero_var
        ).pack(side="left")

        # 涨跌榜不是一种排序口径，是报告里额外的浮窗，所以单独做成勾选项
        mover_box = tk.Frame(content, bg=self.colors["surface"])
        mover_box.pack(fill="x", pady=(self.theme.px(12), 0))
        widgets.small_label(
            mover_box,
            self.theme,
            "报告右下角的「48h 涨跌榜」浮窗（可拖动、可关闭）",
            "dim",
        ).pack(anchor="w", pady=(0, self.theme.px(6)))
        mover_row = tk.Frame(mover_box, bg=self.colors["surface"])
        mover_row.pack(fill="x")
        widgets.CheckBox(
            mover_row, self.theme,
            "涨得最多 TOP " + str(data.MOVERS_COUNT), self.movers_up_var,
        ).pack(side="left", padx=(0, self.theme.px(22)))
        widgets.CheckBox(
            mover_row, self.theme,
            "跌得最多 TOP " + str(data.MOVERS_COUNT), self.movers_down_var,
        ).pack(side="left")

    def build_data_card(self, body):
        # 数据更新已挪到主窗口的「数据与设置」，这里只留"用哪个文件"的开关，
        # 并且不再放模式 / 更新按钮——避免两个地方都能改数据、状态互相打架。
        subtitle = (
            "数据在主窗口的「数据与设置」里更新"
            if not self.sync_enabled
            else "点「更新数据」让程序自己联网获取；也可以点「选择」手动指一个已有的文件。"
        )
        card = widgets.RoundCard(
            body,
            self.theme,
            padding=(20, 16, 20, 16),
            title="数据来源",
            subtitle=subtitle,
        )
        self.scroll.add(card, pady=(0, 14))
        self.data_card = card

        toggle_row = tk.Frame(card.body, bg=self.colors["surface"])
        toggle_row.pack(fill="x")

        self.db_state_label = tk.Label(
            toggle_row,
            text="正在检查 ...",
            bg=self.colors["surface"],
            fg=self.colors["ink2"],
            font=self.theme.fonts.small,
            anchor="w",
        )
        self.db_state_label.pack(side="left")

        self.data_toggle = widgets.Button(
            toggle_row,
            self.theme,
            "展开 ▾",
            command=lambda: self.toggle_section("data"),
            variant="link",
            font=self.theme.fonts.small_bold,
            height=24,
            radius=8,
        )
        self.data_toggle.pack(side="right")

        content = tk.Frame(card.body, bg=self.colors["surface"])
        self.folded["data"] = {"content": content, "button": self.data_toggle,
                               "card": card, "open": False, "open_text": "收起 ▴",
                               "closed_text": "展开 ▾"}

        db_box = tk.Frame(content, bg=self.colors["surface"])
        db_box.pack(fill="x", pady=(0, self.theme.px(12)))
        widgets.small_label(db_box, self.theme, "查价数据（tarkov.db）", "dim").pack(
            anchor="w", pady=(0, self.theme.px(5))
        )
        db_row = tk.Frame(db_box, bg=self.colors["surface"])
        db_row.pack(fill="x")
        self.make_path_entry(db_row, self.db_path_var).pack(side="left", fill="x", expand=True)
        widgets.Button(
            db_row, self.theme, "选择", command=self.on_pick_db, variant="secondary",
            font=self.theme.fonts.button_small, height=34, radius=10,
        ).pack(side="left", padx=(self.theme.px(8), 0))

        icon_box = tk.Frame(content, bg=self.colors["surface"])
        icon_box.pack(fill="x", pady=(0, self.theme.px(12)))
        widgets.small_label(icon_box, self.theme, "物品图标目录", "dim").pack(
            anchor="w", pady=(0, self.theme.px(5))
        )
        icon_row = tk.Frame(icon_box, bg=self.colors["surface"])
        icon_row.pack(fill="x")
        self.make_path_entry(icon_row, self.icon_dir_var).pack(
            side="left", fill="x", expand=True
        )
        widgets.Button(
            icon_row, self.theme, "选择", command=self.on_pick_icon, variant="secondary",
            font=self.theme.fonts.button_small, height=34, radius=10,
        ).pack(side="left", padx=(self.theme.px(8), 0))

        if not self.sync_enabled:
            # 同步区已移交主窗口，这里留一句指路
            tk.Frame(content, bg=self.colors["line"], height=1).pack(
                fill="x", pady=(0, self.theme.px(14))
            )
            note = tk.Label(
                content,
                text="要更新物品数据和图标，请回到主窗口点「数据与设置」。",
                bg=self.colors["surface"],
                fg=self.colors["ink3"],
                font=self.theme.fonts.small,
                anchor="w",
                justify="left",
            )
            note.pack(fill="x")
            return

        tk.Frame(content, bg=self.colors["line"], height=1).pack(
            fill="x", pady=(0, self.theme.px(14))
        )

        sync_row = tk.Frame(content, bg=self.colors["surface"])
        sync_row.pack(fill="x", pady=(0, self.theme.px(8)))

        mode_box = tk.Frame(sync_row, bg=self.colors["surface"])
        mode_box.pack(side="left", anchor="w")
        widgets.small_label(mode_box, self.theme, "游戏模式", "dim").pack(
            anchor="w", pady=(0, self.theme.px(5))
        )
        widgets.Segmented(
            mode_box,
            self.theme,
            [(label, label) for label, _ in sync.GAME_MODES],
            self.mode_var,
            height=32,
        ).pack(anchor="w")

        action_box = tk.Frame(sync_row, bg=self.colors["surface"])
        action_box.pack(side="left", anchor="w", padx=(self.theme.px(26), 0))
        widgets.small_label(action_box, self.theme, "从 tarkov.dev 联网更新", "dim").pack(
            anchor="w", pady=(0, self.theme.px(5))
        )
        action_row = tk.Frame(action_box, bg=self.colors["surface"])
        action_row.pack(anchor="w")
        self.sync_button = widgets.Button(
            action_row, self.theme, "更新数据", command=self.on_sync,
            variant="secondary", font=self.theme.fonts.button_small,
            height=32, radius=10, min_width=96,
        )
        self.sync_button.pack(side="left")
        widgets.CheckBox(
            action_row, self.theme, "同时下载图标", self.with_icons_var
        ).pack(side="left", padx=(self.theme.px(12), 0))

        self.sync_state_label = tk.Label(
            content,
            textvariable=self.sync_state_var,
            bg=self.colors["surface"],
            fg=self.colors["ink3"],
            font=self.theme.fonts.small,
            anchor="w",
            justify="left",
        )
        self.sync_state_label.pack(fill="x", pady=(0, self.theme.px(10)))

        note = tk.Label(
            content,
            text="数据可以自己联网更新（下载到 exe 同目录），也可以继续用查价 MCP 的本地缓存。",
            bg=self.colors["surface"],
            fg=self.colors["ink3"],
            font=self.theme.fonts.small,
            anchor="w",
            justify="left",
        )
        note.pack(fill="x")

    def build_log_card(self, body):
        card = widgets.RoundCard(
            body,
            self.theme,
            padding=(20, 16, 20, 16),
            title="运行记录",
            subtitle=None,
        )
        self.log_slot = card
        self.log_card_packed = False
        self.log_card = card

        toggle_row = tk.Frame(card.body, bg=self.colors["surface"])
        toggle_row.pack(fill="x")
        widgets.small_label(
            toggle_row, self.theme, "出问题时把这里的内容发出来，方便排查", "muted"
        ).pack(side="left")
        self.log_toggle = widgets.Button(
            toggle_row,
            self.theme,
            "收起 ▴",
            command=self.hide_log_card,
            variant="link",
            font=self.theme.fonts.small_bold,
            height=24,
            radius=8,
        )
        self.log_toggle.pack(side="right")

        content = tk.Frame(card.body, bg=self.colors["surface"])
        self.folded["log"] = {"content": content, "button": self.log_toggle,
                              "card": card, "open": True, "open_text": "收起 ▴",
                              "closed_text": "展开 ▾"}

        holder = tk.Frame(content, bg=self.colors["track"], bd=0, highlightthickness=0)
        holder.pack(fill="x", pady=(self.theme.px(10), 0))
        self.log_text = tk.Text(
            holder,
            height=10,
            bg=self.colors["track"],
            fg=self.colors["ink"],
            font=self.theme.fonts.mono,
            relief="flat",
            bd=0,
            wrap="word",
            padx=self.theme.px(10),
            pady=self.theme.px(8),
            insertbackground=self.colors["primary"],
            highlightthickness=0,
        )
        scrollbar = tk.Scrollbar(
            holder, command=self.log_text.yview, bd=0, highlightthickness=0,
            troughcolor=self.colors["track"], bg=self.colors["trackbar"],
            activebackground=self.colors["primary_soft"], width=self.theme.px(10),
        )
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(
            side="left", fill="both", expand=True,
            padx=(self.theme.px(1), 0), pady=self.theme.px(1),
        )
        self.log_text.configure(state="disabled")
        self.log_text.tag_configure("ok", foreground=self.colors["primary"])
        self.log_text.tag_configure("warn", foreground=self.colors["amber"])
        self.log_text.tag_configure("bad", foreground=self.colors["danger"])
        self.log_text.tag_configure("dim", foreground=self.colors["ink3"])

        self.append_log("准备就绪。点「开始生成」即可。", "dim")

    def show_log_card(self):
        """运行记录平时收起来（小白看着一屏日志会慌），需要排查时再放出来。"""
        if self.log_card_packed:
            self.scroll.scroll_to_bottom()
            return
        self.scroll.add(self.log_slot, pady=(0, 14))
        self.log_card_packed = True
        self.refresh_layout()
        self.scroll.scroll_to_bottom()

    def hide_log_card(self):
        if not self.log_card_packed:
            return
        self.log_slot.pack_forget()
        self.log_card_packed = False
        self.refresh_layout()

    def make_path_entry(self, parent, variable):
        wrapper = tk.Frame(parent, bg=self.colors["track"], bd=0, highlightthickness=0)
        entry = widgets.make_entry(wrapper, self.theme, variable, width=40)
        entry.pack(fill="x", padx=1, pady=1, ipady=self.theme.px(6))
        return wrapper

    # --- 底部 ---

    def build_footer(self, root):
        footer = tk.Frame(root, bg=self.colors["page"], bd=0, highlightthickness=0)
        footer.grid(
            row=2, column=0, sticky="ew",
            padx=self.theme.px(24), pady=(self.theme.px(8), self.theme.px(18)),
        )
        self.footer = footer

        self.progress = widgets.ProgressBar(footer, self.theme, width=120, height=7)
        self.progress.pack(side="left", padx=(0, self.theme.px(12)))

        status = tk.Label(
            footer,
            textvariable=self.footer_status_var,
            bg=self.colors["page"],
            fg=self.colors["ink2"],
            font=self.theme.fonts.small,
            anchor="w",
        )
        status.pack(side="left")

        self.footer_generate = widgets.Button(
            footer,
            self.theme,
            "开始生成",
            command=self.on_generate,
            variant="primary",
            icon="▶",
            font=self.theme.fonts.button,
            height=40,
            radius=12,
            min_width=140,
        )
        self.footer_generate.pack(side="right")

        self.footer_log_button = widgets.Button(
            footer,
            self.theme,
            "运行记录",
            command=self.show_log_card,
            variant="link",
            font=self.theme.fonts.small_bold,
            height=26,
            radius=8,
        )
        self.footer_log_button.pack(side="right", padx=(0, self.theme.px(14)))

    # ---------- 折叠 ----------

    def toggle_section(self, key):
        info = self.folded.get(key)
        if info is None:
            return
        if info["open"]:
            info["content"].pack_forget()
            info["button"].set_text(info["closed_text"])
            info["open"] = False
        else:
            info["content"].pack(fill="x", pady=(self.theme.px(12), 0))
            info["button"].set_text(info["open_text"])
            info["open"] = True
        self.refresh_layout()

    def refresh_layout(self):
        """内容变了以后重新量一遍卡片高度和滚动范围。

        先把堆积的几何算完（update_idletasks），量一次就准了；再补一轮 after_idle
        兜底。原来连着跑 4 轮（立即 / idle / +40ms / +140ms），等于把整棵树反复重排
        重画好几遍，点一下面板要卡 100 多毫秒。
        """
        self.root.update_idletasks()
        self._refresh_layout_now()
        self.root.after_idle(self._refresh_layout_now)

    def _refresh_layout_now(self):
        for info in self.folded.values():
            info["card"].refresh()
        self.scroll.refresh()

    def set_section(self, key, open_state):
        info = self.folded.get(key)
        if info is None or info["open"] == open_state:
            return
        self.toggle_section(key)

    # ---------- 配置读写 ----------

    def apply_config(self):
        config = self.config

        # 库和图标由程序自己管，但**不预填**：
        # 自己目录下已经有就显示（程序自己下回来的），否则留空等「更新数据」去获取，
        # 或者由用户点「选择」手动指一个。新用户打开时这两栏就该是空的。
        own_db = sync.default_db_path()
        if os.path.exists(own_db):
            db_path = own_db
        else:
            db_path = config.get("db_path", "").strip()
        self.db_path_var.set(db_path)

        own_icon = sync.default_icon_dir()
        try:
            has_own_icon = os.path.isdir(own_icon) and bool(os.listdir(own_icon))
        except OSError:
            has_own_icon = False
        if has_own_icon:
            icon_dir = own_icon
        else:
            icon_dir = config.get("icon_dir", "").strip()
        self.icon_dir_var.set(icon_dir)

        output_dir = config.get("output_dir", "")
        if not output_dir or output_dir == legacy_output_dir():
            # 旧版本的默认值是「文档\TarkovMarketInfo」，那不算用户手动选过，切到新默认
            output_dir = default_output_dir()
        self.output_dir_var.set(output_dir)

        sort_label = config.get("sort_label", "跳蚤均价")
        if sort_label not in self.label_to_field:
            sort_label = "跳蚤均价"
        self.sort_label_var.set(sort_label)

        self.order_var.set(int(config.get("descending", 1)))
        self.limit_var.set(str(config.get("limit", 50)))
        self.min_price_var.set(str(config.get("min_price", 0)))
        self.keyword_var.set(config.get("keyword", ""))
        self.flea_only_var.set(int(config.get("flea_only", 1)))
        self.skip_zero_var.set(int(config.get("skip_zero", 1)))
        self.movers_up_var.set(int(config.get("movers_up", 1)))
        self.movers_down_var.set(int(config.get("movers_down", 1)))
        self.export_html_var.set(int(config.get("export_html", 1)))
        self.export_png_var.set(int(config.get("export_png", 1)))
        self.export_csv_var.set(int(config.get("export_csv", 0)))
        self.open_after_var.set(int(config.get("open_after", 1)))
        self.with_icons_var.set(int(config.get("with_icons", 1)))

        mode = config.get("game_mode", "PVE")
        if mode not in [label for label, _ in sync.GAME_MODES]:
            mode = "PVE"
        self.mode_var.set(mode)
        if self.sync_enabled:
            self.sync_state_var.set("还没联网更新过，点「更新数据」从网上拉一份")
        else:
            self.sync_state_var.set("数据更新在主窗口的「数据与设置」里")

        self.footer_status_var.set("准备好啦，随时可以生成")

    def collect_config(self):
        config = {
            "db_path": self.db_path_var.get().strip(),
            "icon_dir": self.icon_dir_var.get().strip(),
            "output_dir": self.output_dir_var.get().strip(),
            "sort_label": self.sort_label_var.get(),
            "descending": self.order_var.get(),
            "limit": self.limit_var.get().strip(),
            "min_price": self.min_price_var.get().strip(),
            "keyword": self.keyword_var.get().strip(),
            "flea_only": self.flea_only_var.get(),
            "skip_zero": self.skip_zero_var.get(),
            "movers_up": self.movers_up_var.get(),
            "movers_down": self.movers_down_var.get(),
            "export_html": self.export_html_var.get(),
            "export_png": self.export_png_var.get(),
            "export_csv": self.export_csv_var.get(),
            "open_after": self.open_after_var.get(),
            "with_icons": self.with_icons_var.get(),
            "game_mode": self.mode_var.get() or "PVE",
        }
        return config

    # ---------- 状态显示 ----------

    def refresh_header_status(self):
        if self.summary is None:
            # 同步已移交主窗口，指路要去对地方
            tip = "去主窗口「数据与设置」下载数据" if not self.sync_enabled else "还没找到查价数据"
            self.status_pill.set(tip, "bad")
            return
        if not self.summary.get("total"):
            self.status_pill.set("索引里没有物品", "warn")
            return
        self.status_pill.set(str(self.summary["total"]) + " 项物品已就绪", "ok")

    def refresh_db_status_async(self):
        """读数据库概要可能要几百毫秒，放后台，别卡住窗口。"""
        path = self.db_path_var.get().strip()

        def work():
            try:
                summary = data.load_db_summary(path)
            except Exception:
                summary = None
            self.ui_queue.put(("summary", summary))

        worker = threading.Thread(target=work)
        worker.daemon = True
        worker.start()

    def on_summary_ready(self, summary):
        self.summary = summary
        self.refresh_header_status()
        if summary is None:
            self.db_state_label.configure(
                text="还没有数据，点「更新数据」联网拉一份", fg=self.colors["danger"]
            )
            self.status_var.set("数据还没接上 · 先在下面点「更新数据」")
            return
        time_text = datetime.fromtimestamp(summary["mtime"]).strftime("%Y-%m-%d %H:%M")
        self.db_state_label.configure(
            text="共 " + str(summary["total"]) + " 项物品 · 数据更新于 " + time_text,
            fg=self.colors["ink2"],
        )
        sync_time = datetime.fromtimestamp(summary["last_sync"]).strftime("%Y-%m-%d %H:%M")
        self.sync_state_var.set(
            "上次同步 " + sync_time + " · " + str(summary["total"]) + " 项物品"
        )
        self.update_filter_summary()

    def update_filter_summary(self):
        """把筛选条件说成一句人话，放在折叠标题旁边。"""
        sort_label = self.sort_label_var.get() or "跳蚤均价"
        direction = "从高到低" if self.order_var.get() == 1 else "从低到高"
        parts = ["按「" + sort_label + "」" + direction]

        limit = self.limit_var.get().strip()
        if limit.isdigit() and int(limit) > 0:
            parts.append("取前 " + limit + " 条")

        keyword = self.keyword_var.get().strip()
        if keyword:
            parts.append("名字含「" + keyword + "」")

        min_price = self.min_price_var.get().strip()
        if min_price.isdigit() and int(min_price) > 0:
            parts.append("低于 " + format(int(min_price), ",") + " 不要")

        boards = []
        if self.movers_up_var.get():
            boards.append("涨")
        if self.movers_down_var.get():
            boards.append("跌")
        if boards:
            parts.append("浮窗出「48h " + "／".join(boards) + "榜」")
        else:
            parts.append("不要涨跌榜浮窗")

        self.status_var.set(" · ".join(parts))

    def watch_filter_vars(self):
        """筛选条件变了就把那句人话刷新一下，用户不用点开也知道现在是啥设定。"""
        for variable in (
            self.sort_label_var,
            self.order_var,
            self.limit_var,
            self.min_price_var,
            self.keyword_var,
            self.movers_up_var,
            self.movers_down_var,
        ):
            variable.trace_add("write", lambda *args: self.update_filter_summary())

    def append_log(self, message, tag=None):
        self.log_queue.put((message, tag))

    # ---------- 交互回调 ----------

    def on_pick_db(self):
        path = filedialog.askopenfilename(
            title="找到 tarkov.db（查价数据的索引文件）",
            filetypes=[("SQLite 数据库", "*.db"), ("所有文件", "*.*")],
        )
        if path:
            self.db_path_var.set(path)
            guessed = data.guess_icon_dir(path)
            if guessed:
                self.icon_dir_var.set(guessed)
            self.refresh_db_status_async()

    def on_pick_icon(self):
        path = filedialog.askdirectory(title="选择物品图标目录")
        if path:
            self.icon_dir_var.set(path)

    def on_pick_output(self):
        path = filedialog.askdirectory(title="选择保存报告的文件夹")
        if path:
            self.output_dir_var.set(path)

    def on_open_output(self):
        path = self.output_dir_var.get().strip()
        if not path:
            return
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except Exception:
                messagebox.showerror(APP_NAME, "这个文件夹建不出来，换一个位置试试")
                return
        open_in_browser(path)

    def on_open_report(self):
        if self.last_html_path and os.path.exists(self.last_html_path):
            open_in_browser(self.last_html_path)
        else:
            messagebox.showinfo(APP_NAME, "这次还没有生成可以打开的报告")

    # ---------- 生成主流程 ----------

    def on_generate(self):
        if self.busy:
            return
        config = self.collect_config()

        if not config["db_path"] or not os.path.exists(config["db_path"]):
            messagebox.showerror(
                APP_NAME,
                "还没有找到查价数据（tarkov.db）。\n\n"
                "到「数据来源」里点「更新数据」联网拉一份；"
                "或者点「选择」手动指定一个已有的 tarkov.db。",
            )
            self.set_section("data", True)
            return

        try:
            limit = int(config["limit"])
            if limit < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "「显示多少条」要填一个不小于 0 的整数")
            self.set_section("options", True)
            return

        try:
            min_price = int(config["min_price"])
            if min_price < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "「低于这个价就不显示」要填一个不小于 0 的整数")
            self.set_section("options", True)
            return

        if not config["export_html"] and not config["export_png"] and not config["export_csv"]:
            messagebox.showerror(APP_NAME, "至少要选一种输出文件（建议留着「网页报告」）")
            return

        save_config(config)
        self.set_busy(True)
        self.update_filter_summary()

        worker = threading.Thread(target=self.run_generate, args=(config, limit, min_price))
        worker.daemon = True
        worker.start()

    def set_busy(self, busy, action="生成"):
        """统一开关忙碌态。生成和更新互斥，跑一个的时候另一个也点不了。

        action="更新" 时「更新数据」按钮会变成「取消更新」，可以中途停下。
        """
        self.busy = busy
        # sync_enabled=False 时同步那一块没建，sync_button 不存在。
        # 用 getattr 拿成None，底下判一下就不碰它。
        sync_button = getattr(self, "sync_button", None)
        if busy:
            self.generate_button.set_state("disabled")
            self.footer_generate.set_state("disabled")
            if action == "更新":
                self.generate_button.set_text("开始生成")
                self.footer_generate.set_text("开始生成")
                if sync_button is not None:
                    sync_button.set_text("取消更新")
                    sync_button.command = self.on_cancel_sync
                    sync_button.set_state("normal")
                self.footer_status_var.set("正在联网更新数据 ...")
            else:
                self.generate_button.set_text("生成中 ...")
                self.footer_generate.set_text("生成中 ...")
                if sync_button is not None:
                    sync_button.set_state("disabled")
                self.footer_status_var.set("正在读取数据 ...")
            self.progress.set(0.1)
        else:
            self.generate_button.set_state("normal")
            self.footer_generate.set_state("normal")
            self.generate_button.set_text("开始生成")
            self.footer_generate.set_text("开始生成")
            if sync_button is not None:
                sync_button.set_text("更新数据")
                sync_button.command = self.on_sync
                sync_button.set_state("normal")

    # ---------- 联网更新 ----------

    def on_sync(self):
        self.start_sync()

    def start_sync(self, auto=False):
        """开始联网更新。auto=True 是启动时自动触发（失败不弹窗打扰）。"""
        if self.busy:
            return
        config = self.collect_config()
        save_config(config)
        self.sync_cancel[0] = False
        self.sync_auto = auto
        self.set_busy(True, "更新")
        if not auto:
            self.set_section("data", True)
        if self.sync_window is None:
            self.sync_window = SyncProgressWindow(self.root, self.theme, self.on_cancel_sync)

        worker = threading.Thread(
            target=self.run_sync,
            args=(config["game_mode"], config["with_icons"] == 1),
        )
        worker.daemon = True
        worker.start()

    def icon_dir_ready(self, icon_dir):
        """图标目录有没有内容（至少一张 webp）。"""
        try:
            return os.path.isdir(icon_dir) and any(
                name.endswith(".webp") for name in os.listdir(icon_dir)
            )
        except OSError:
            return False

    def auto_sync_if_needed(self):
        """启动后如果还没有数据库或图标，就自己联网拉一份，不用用户手动点。"""
        if self.busy:
            return
        db_path = self.db_path_var.get().strip()
        if not db_path or not os.path.exists(db_path):
            missing = "数据"
        elif not self.icon_dir_ready(self.icon_dir_var.get().strip()):
            missing = "图标"
        else:
            return
        self.append_log("还没" + missing + "，自动开始联网更新 ...", "dim")
        self.start_sync(auto=True)

    def on_cancel_sync(self):
        self.sync_cancel[0] = True
        self.append_log("收到取消，正在停下 ...", "warn")
        self.footer_status_var.set("正在取消 ...")

    def run_sync(self, mode_label, with_icons):
        """后台线程：拉数据 → 建库 →（可选）下图标。"""
        try:
            self.append_log("─" * 46, "dim")
            self.append_log(
                "开始更新数据（" + mode_label + "）"
                + datetime.now().strftime("%H:%M:%S")
            )
            if with_icons:
                self.append_log("会一并下载图标，首次可能要几分钟", "dim")

            result = sync.sync_all(
                sync.mode_slug(mode_label),
                with_icons=with_icons,
                progress_cb=self.post_sync_progress,
                cancel_flag=self.sync_cancel,
            )

            self.append_log("数据库已写入：" + result["db_path"], "ok")
            self.append_log("共 " + str(result["items"]) + " 项物品", "dim")
            if with_icons:
                if result["icon_pack"]:
                    self.append_log(
                        "图标包解出 " + str(result["icon_pack"]) + " 张", "dim"
                    )
                self.append_log(
                    "图标已就绪 " + str(result["icons"]) + " 张 → " + result["icon_dir"],
                    "ok",
                )
                if result["icon_aborted"]:
                    self.append_log(
                        "图床限流，剩下的 " + str(result["icon_failed"])
                        + " 张没补上；过一会儿再点一次「更新数据」会接着补",
                        "warn",
                    )
                elif result["icon_failed"]:
                    self.append_log(
                        "有 " + str(result["icon_failed"]) + " 张图标没下下来", "warn"
                    )
            if result["cancelled"]:
                self.append_log("已取消，数据已更新但图标可能没下完", "warn")

            self.ui_queue.put(("sync_finish", (result, None)))
        except Exception as error:
            detail = traceback.format_exc()
            write_error_log(detail)
            self.append_log("更新失败：" + str(error), "bad")
            self.append_log("详细堆栈已写入 error.log", "dim")
            self.ui_queue.put(("sync_finish", (None, str(error))))

    def on_sync_finish(self, result, error):
        self.set_busy(False)
        if self.sync_window is not None:
            self.sync_window.close()
            self.sync_window = None

        if error or result is None:
            self.progress.set(0)
            self.footer_status_var.set("更新失败，旧的数据库没有被破坏")
            self.sync_state_var.set("更新失败：" + str(error))
            self.refresh_layout()
            if self.sync_auto:
                # 启动时自动拉的，失败别弹窗堵着；日志和状态栏已经写了原因
                self.append_log("自动更新失败，可稍后手动点「更新数据」重试", "warn")
            else:
                messagebox.showerror(
                    APP_NAME,
                    "更新数据失败：\n\n" + str(error)
                    + "\n\n可能是网络不通，或者 exe 所在目录不可写。",
                )
            return

        # 切到刚下载下来的库和图标目录
        self.db_path_var.set(result["db_path"])
        self.icon_dir_var.set(result["icon_dir"])
        self.progress.set(1.0)
        if result["icon_aborted"]:
            self.footer_status_var.set(
                "数据已更新；图标被限流还差 "
                + str(result["icon_failed"]) + " 张，过会儿再点「更新数据」接着补"
            )
        else:
            self.footer_status_var.set("数据已更新，共 " + str(result["items"]) + " 项")
        self.refresh_db_status_async()
        self.refresh_layout()

    def run_generate(self, config, limit, min_price):
        """在后台线程里干活，界面不会卡住。"""
        try:
            self.post_progress("正在读取数据 ...", 0.2)
            self.append_log("─" * 46, "dim")
            self.append_log("开始生成 " + datetime.now().strftime("%H:%M:%S"))

            all_items = data.load_all_items(config["db_path"])
            self.append_log("索引共 " + str(len(all_items)) + " 项物品", "dim")

            sort_field = self.label_to_field[config["sort_label"]]
            options = {
                "sort_field": sort_field,
                "descending": config["descending"] == 1,
                "limit": limit,
                "keyword": config["keyword"],
                "flea_only": config["flea_only"] == 1,
                "skip_zero": config["skip_zero"] == 1,
                "min_price": min_price,
            }

            items = data.search_items(all_items, options)
            self.append_log(
                "命中 " + str(len(items)) + " 项 · 排序：" + config["sort_label"]
                + " · " + ("降序" if options["descending"] else "升序")
            )

            if not items:
                self.append_log("没有任何物品符合条件，检查一下关键词和门槛", "warn")
                self.post_finish(None, 0, False, "没有符合条件的物品，把条件放宽一点再试")
                return

            output_dir = config["output_dir"]
            if not output_dir:
                output_dir = default_output_dir()
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = "Tarkov排行_" + config["sort_label"] + "_" + stamp

            db_summary = data.load_db_summary(config["db_path"])
            if db_summary:
                sync_time = datetime.fromtimestamp(db_summary["mtime"]).strftime("%Y-%m-%d %H:%M")
                total_items = db_summary["total"]
            else:
                sync_time = "未知"
                total_items = 0

            context = {
                "db_path": config["db_path"],
                "icon_dir": config["icon_dir"],
                "sync_time": sync_time,
                "total_items": total_items,
                "game_mode": config.get("game_mode", "PVE"),
                # 涨跌榜浮窗：从整个索引里取，不受当前筛选/条数影响
                "movers": data.top_movers(
                    all_items,
                    config["movers_up"] == 1,
                    config["movers_down"] == 1,
                ),
            }

            # 分类表：先按同一套条件过滤（不截断），再按类型各取前 limit 条 ——
            # 每张分类表跟总表口径一致，只是范围换成那一类
            pool = data.search_items(all_items, dict(options, limit=0))
            context["type_groups"] = data.group_by_type(pool, options["limit"])
            if context["type_groups"]:
                self.append_log(
                    "按类型分了 " + str(len(context["type_groups"])) + " 张分类表"
                    "（连总表共 " + str(len(context["type_groups"]) + 1)
                    + " 张，报告顶部可切换）", "dim"
                )

            produced = []
            html_path = ""

            if config["export_html"] or config["export_png"]:
                self.post_progress("正在排版报告 ...", 0.4)
                html_path = os.path.join(output_dir, base_name + ".html")
                report.write_html(items, options, context, html_path)
                if config["export_html"]:
                    produced.append(html_path)
                    self.append_log("网页报告已生成", "ok")

            png_failed = False
            if config["export_png"]:
                self.post_progress("正在画长图 ...", 0.6)
                self.append_log("正在画长图 ...")
                png_path = os.path.join(output_dir, base_name + ".png")
                try:
                    png_width, png_height = capture.render_long_image(
                        items, png_path, options, context
                    )
                    produced.append(png_path)
                    self.append_log(
                        "长图已生成：" + str(png_width) + " × " + str(png_height), "ok"
                    )
                except Exception as error:
                    # 长图失败不能把已经做好的 HTML 一起废掉，记下来继续往下走
                    png_failed = True
                    write_error_log(traceback.format_exc())
                    self.append_log("长图生成失败", "bad")
                    self.append_log(str(error), "dim")
                    if os.path.exists(png_path):
                        os.remove(png_path)

            if config["export_csv"]:
                self.post_progress("正在导出表格 ...", 0.8)
                csv_path = os.path.join(output_dir, base_name + ".csv")
                report.write_csv(items, options, csv_path)
                produced.append(csv_path)
                self.append_log("CSV 表格已生成", "ok")

            # 只勾了长图的话，中间那个 HTML 正常情况下没必要留着
            if html_path and not config["export_html"] and os.path.exists(html_path):
                if png_failed:
                    produced.append(html_path)
                    self.append_log("长图没出来，网页报告已保留备用", "warn")
                else:
                    os.remove(html_path)

            self.append_log("全部完成，输出目录：" + output_dir, "ok")
            for path in produced:
                self.append_log("  · " + os.path.basename(path), "dim")

            self.post_finish(output_dir, len(produced), png_failed, "", produced)

        except Exception as error:
            detail = traceback.format_exc()
            write_error_log(detail)
            self.append_log("出错了：" + str(error), "bad")
            self.append_log("详细堆栈已写入 error.log", "dim")
            self.post_finish(None, 0, False, "出错了：" + str(error))

    # ---------- 线程 → 界面 ----------

    def post_progress(self, text, value):
        self.ui_queue.put(("progress", (text, value)))

    def post_sync_progress(self, phase, text, value):
        """同步线程的进度回调：phase 区分「数据」和「图标」，窗口里分成两条。"""
        self.ui_queue.put(("sync_progress", (phase, text, value)))

    def on_sync_progress(self, phase, text, value):
        if self.sync_window is not None:
            self.sync_window.set_progress(phase, text, value)
        self.footer_status_var.set(text)
        self.progress.set(value)

    def post_finish(self, output_dir, count, png_failed, message, produced=None):
        self.ui_queue.put(
            ("finish", (output_dir, count, png_failed, message, produced or []))
        )

    def poll_queues(self):
        # 日志
        while True:
            try:
                message, tag = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state="normal")
            if tag:
                self.log_text.insert("end", message + "\n", tag)
            else:
                self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        # 界面动作
        while True:
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "summary":
                self.on_summary_ready(payload)
            elif kind == "progress":
                text, value = payload
                self.footer_status_var.set(text)
                self.progress.set(value)
            elif kind == "finish":
                self.on_finish(*payload)
            elif kind == "sync_progress":
                self.on_sync_progress(*payload)
            elif kind == "sync_finish":
                self.on_sync_finish(*payload)

        self.root.after(100, self.poll_queues)

    def on_finish(self, output_dir, count, png_failed, message, produced):
        self.set_busy(False)

        html_path = ""
        for path in produced:
            if path.lower().endswith(".html"):
                html_path = path
                break
        self.last_html_path = html_path

        if count <= 0:
            self.progress.set(0)
            self.footer_status_var.set(message or "这次没有生成文件")
            self.result_label.configure(text=message or "这次没有生成文件", fg=self.colors["amber"])
            self.result_row.pack(fill="x", pady=(self.theme.px(12), 0))
            self.open_report_button.set_state("disabled")
            self.refresh_layout()
            if message and "出错" in message:
                messagebox.showerror(APP_NAME, message)
            return

        self.progress.set(1.0)
        self.footer_status_var.set("完成，共 " + str(count) + " 个文件")

        if html_path:
            self.result_label.configure(
                text="已生成 " + str(count) + " 个文件：" + os.path.basename(html_path),
                fg=self.colors["primary"],
            )
            self.open_report_button.set_state("normal")
        else:
            self.result_label.configure(
                text="已生成 " + str(count) + " 个文件，就在：" + output_dir,
                fg=self.colors["primary"],
            )
            self.open_report_button.set_state("disabled")
        self.result_row.pack(fill="x", pady=(self.theme.px(12), 0))
        self.refresh_layout()

        open_target = html_path if html_path else output_dir
        auto_open = bool(self.open_after_var.get())
        if auto_open and open_target:
            open_in_browser(open_target)
            self.footer_status_var.set("完成，已经帮你打开了：" + os.path.basename(open_target))

        if png_failed:
            messagebox.showwarning(
                APP_NAME,
                "长图没生成出来（详情见运行记录），网页报告已经保留。\n"
                "可以用浏览器打开它，再按 Ctrl+P 或截图工具导出。\n\n"
                "文件位置：\n" + output_dir,
            )
            return

        messagebox.showinfo(
            APP_NAME,
            "搞定，共 " + str(count) + " 个文件。\n\n"
            "文件位置：\n" + output_dir
            + ("\n\n已经用浏览器打开这份报告。" if auto_open and html_path else ""),
        )


def self_test(limit=10):
    """自检模式：不弹窗口，把完整链路跑一遍，结果写到临时文件。

    打包后用来确认 exe 在目标机器上能不能干活：
        TarkovMarketInfo.exe --selftest
        TarkovMarketInfo.exe --selftest 100     （指定渲染条数，用来压测长图）
    """
    lines = []
    result_path = os.path.join(tempfile.gettempdir(), "tarkov_selftest.txt")
    passed = True
    temp_dir = ""

    lines.append("Tarkov 市场排行生成器 自检")
    lines.append("时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("打包运行：" + ("是" if getattr(sys, "frozen", False) else "否"))
    # 打包后程序目录 = exe 所在目录；源码运行时 exe 是 python.exe，
    # 直接报 sys.executable 会指向 C:\Python314，得用 app_dir()
    lines.append("程序目录：" + data.app_dir())
    lines.append("配置目录：" + os.path.dirname(config_path()))
    lines.append("数据目录：" + data.data_dir())
    lines.append("图标目录：" + data.icon_root())
    lines.append("报表目录：" + data.reports_dir())
    lines.append("渲染条数：" + str(limit))
    lines.append("-" * 50)

    try:
        # 目录布局：data\ 和 reports\ 必须已经建出来，缺一个后面写文件就会失败
        missing_dirs = [
            name for name, path in (("data", data.data_dir()), ("reports", data.reports_dir()))
            if not os.path.isdir(path)
        ]
        if missing_dirs:
            raise RuntimeError("缺少目录：" + "、".join(missing_dirs))
        lines.append("[0/9] 目录布局：data\\ / reports\\ 均已建立")

        db_path = data.find_default_db()
        lines.append("[1/9] 数据库：" + (db_path if db_path else "未找到"))
        if not db_path:
            raise RuntimeError("没有找到 tarkov.db 索引文件")
        summary = data.load_db_summary(db_path)
        lines.append("      物品总数：" + str(summary["total"]))

        items = data.load_all_items(db_path)
        lines.append("[2/9] 索引读取成功：" + str(len(items)) + " 项")

        base_options = {
            "sort_field": "avg24h",
            "descending": True,
            "limit": limit,
            "keyword": "",
            "flea_only": True,
            "skip_zero": True,
            "min_price": 0,
        }
        top_items = data.search_items(items, base_options)
        lines.append("[3/9] 降序检索：" + str(len(top_items)) + " 项，第一名 " + top_items[0]["name_zh"])

        asc_options = dict(base_options)
        asc_options["descending"] = False
        cheap_items = data.search_items(items, asc_options)
        lines.append("      升序检索：第一名 " + cheap_items[0]["name_zh"])

        context = {
            "db_path": db_path,
            "icon_dir": data.guess_icon_dir(db_path),
            "sync_time": "selftest",
            "total_items": summary["total"],
            "game_mode": "PVE",
            "movers": data.top_movers(items, True, True),
            "type_groups": data.group_by_type(
                data.search_items(items, dict(base_options, limit=0)), base_options["limit"]
            ),
        }
        temp_dir = tempfile.mkdtemp(prefix="tarkov_selftest_")
        html_path = os.path.join(temp_dir, "selftest.html")
        report.write_html(top_items, base_options, context, html_path)
        lines.append("[4/9] HTML 生成：" + str(os.path.getsize(html_path) // 1024) + " KB")

        png_path = os.path.join(temp_dir, "selftest.png")
        size_w, size_h = capture.render_long_image(top_items, png_path, base_options, context)
        lines.append("[5/9] 长图渲染：" + str(size_w) + " × " + str(size_h))
        lines.append("      PNG 大小：" + str(os.path.getsize(png_path) // 1024) + " KB")

        # --- 查价链路：搜索 + 取价，纯本地就能验完，不用联网 ---
        import price as price_module
        import search as search_module

        index = search_module.SearchIndex(items)
        lines.append("[6/9] 查价链路：")
        for probe in ("m4a1", "消音器", "显卡"):
            found = index.search(probe, top_n=5)
            first = found[0][0]["name_zh"][:24] if found else "（无结果）"
            lines.append("      查 " + probe + " → " + str(len(found)) + " 个候选，首位 " + first)
        probe_item = index.search("m4a1", top_n=1)
        if probe_item:
            quote = price_module.local_quote(probe_item[0][0])
            lines.append("      取价：均价 " + price_module.format_money(quote["avg24h"])
                         + " · 商人回收价 " + price_module.format_money(quote["trader_price"]))
            if not quote["has_price"]:
                raise RuntimeError("有价格数据的物品取价却返回 has_price=False")
            merchants = price_module.trader_names(probe_item[0][0])
            lines.append("      商人明细：" + str(len(merchants)) + " 个商人")

        # --- 界面：查价主窗口 + 报表窗口都构建一遍 ---
        import app as app_module

        ui_root = tk.Tk()
        ui_root.withdraw()
        theme_module.enable_dpi_awareness()
        shell = app_module.AppShell(ui_root)
        ui_root.update_idletasks()
        lines.append("[7/9] 查价主窗口：tkinter " + str(tk.TkVersion))
        lines.append("      主题：" + ("深色" if shell.theme.dark else "浅色")
                     + " · 字体：" + shell.theme.fonts.family)
        lines.append("      主色：" + shell.theme["primary"])
        lines.append("      索引状态：" + shell.home.status_var.get())

        # 走一遍真实搜索：输入 → 候选 → 详情
        # 自动检索不替用户选行，所以这里要显式回车触发才会填详情
        shell.home.query_var.set("m4a1")
        shell.home.on_search(event="selftest")
        ui_root.update_idletasks()
        lines.append("      搜索 m4a1：" + str(len(shell.home.candidates)) + " 个候选")
        lines.append("      详情均价：" + shell.home.price_labels["avg24h"].cget("text"))
        lines.append("      详情区间：" + shell.home.price_labels["range"].cget("text"))
        if len(shell.home.candidates) == 0:
            raise RuntimeError("查价搜索 m4a1 没有任何候选")
        if "暂无" in shell.home.price_labels["avg24h"].cget("text"):
            raise RuntimeError("M4A1 明明有价格，详情却显示「暂无」")

        # 自动检索：输入够 2 个字就该排上候选，且要挂防抖计时器
        home = shell.home
        home.query_var.set("m")
        ui_root.update_idletasks()
        if len(home.candidates) != 0:
            raise RuntimeError("只输入 1 个字就出候选了，自动检索门槛失效")
        if home.current_item is not None:
            raise RuntimeError("删到 1 个字详情没复位")
        home.query_var.set("m4a1")
        ui_root.update_idletasks()
        if home.search_timer is None:
            raise RuntimeError("输入变化后没有挂防抖计时器，自动检索没生效")
        lines.append("      自动检索：1 字不搜 / 2 字起挂防抖")

        # 手动触发（回车）应该立刻搜掉待执行的自动检索，不搜两遍
        home.on_search(event="selftest")
        ui_root.update_idletasks()
        if home.search_timer is not None:
            raise RuntimeError("手动检索后还留着待执行的自动检索，会重复搜索")
        if home.selected_row != 0:
            raise RuntimeError("回车检索应默认选中第一个候选，实际 selected_row="
                             + str(home.selected_row))
        lines.append("      回车检索：清防抖 + 默认选中第一个")

        # 上下键切候选：到边界停住，不循环、不越界
        home.selected_row = -1
        home.on_move_selection(1)
        if home.selected_row != 0:
            raise RuntimeError("第一次按方向键应选中第 0 行")
        home.on_move_selection(1)
        if home.selected_row != 1:
            raise RuntimeError("第二次按方向键应选中第 1 行")
        home.on_move_selection(-1)
        if home.selected_row != 0:
            raise RuntimeError("按上键应回到第 0 行")
        for _ in range(len(home.candidates) + 3):
            home.on_move_selection(1)
        if home.selected_row != len(home.candidates) - 1:
            raise RuntimeError("到下边界应停住，实际 " + str(home.selected_row))
        lines.append("      上下键：逐行切换 + 边界停住")

        # 空查询不能崩，且要明说
        home.query_var.set("")
        home.on_search()
        home.query_var.set("zzzz查无此物")
        home.on_search()
        ui_root.update_idletasks()
        if home.current_item is not None:
            raise RuntimeError("无结果时详情没复位")
        lines.append("      空查询 / 无结果：正常")

        # --- 报表窗口挂在 Toplevel 上能不能活 ---
        ui_root.update_idletasks()
        shell.open_report()
        ui_root.update_idletasks()
        report_app = shell.report_app
        lines.append("[8/9] 报表窗口：")
        lines.append("      同步已移交主窗口：" + str(not report_app.sync_enabled))
        lines.append("      卡片数量：" + str(len(report_app.scroll.content.winfo_children())))
        enabled = []
        for name, var in (
            ("HTML", report_app.export_html_var),
            ("PNG", report_app.export_png_var),
            ("CSV", report_app.export_csv_var),
            ("自动打开", report_app.open_after_var),
        ):
            if var.get():
                enabled.append(name)
        lines.append("      默认输出：" + " / ".join(enabled))

        # 折叠 / 展开走一遍，确认布局刷新不会抛异常
        for key in ("options", "data", "log"):
            report_app.toggle_section(key)
            ui_root.update_idletasks()
            report_app.toggle_section(key)
            ui_root.update_idletasks()
        lines.append("      折叠面板：正常")

        # 默认输出目录必须是 reports\，不能是 exe 目录（不然报表又跟程序文件混一起）
        default_out = default_output_dir()
        in_reports = os.path.abspath(default_out) == os.path.abspath(data.reports_dir())
        lines.append("[9/9] 默认输出目录：" + default_out)
        if not in_reports:
            raise RuntimeError("默认输出目录不是 reports\\：" + default_out)
        lines.append("      位于 reports\\ 内：正常")

        # 按钮状态切换也不能炸（同步按钮不存在时也要安全）
        report_app.set_busy(True)
        ui_root.update_idletasks()
        report_app.set_busy(False)
        ui_root.update_idletasks()
        lines.append("      按钮状态：正常")

        # 设置窗口：数据更新已经挪到这里，必须能构建
        shell.open_settings()
        ui_root.update_idletasks()
        settings = shell.settings_window
        lines.append("      数据与设置窗口：" + str(settings.window.winfo_width())
                     + " × " + str(settings.window.winfo_height()))
        lines.append("      当前模式：" + settings.mode_var.get())
        lines.append("      数据占用：" + settings.size_label.cget("text"))

        # 资源检测：本地有数据时不该触发同步
        checker = app_module.BootChecker(shell.data_dir, shell.theme)
        need_data, need_icons, reason = checker.detect()
        lines.append("      资源检测：缺数据=" + str(need_data)
                     + " 缺图标=" + str(need_icons) + "（" + (reason or "无缺口") + "）")
        settings.window.destroy()
        ui_root.destroy()

        lines.append("-" * 50)
        lines.append("全部通过")
    except Exception as error:
        passed = False
        lines.append("失败：" + str(error))
        lines.append(traceback.format_exc())

    text = "\n".join(lines)
    handle = open(result_path, "w", encoding="utf-8")
    handle.write(text)
    handle.close()

    # 自检只是为了验证链路，产物没必要堆在临时目录里
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # 窗口程序没有控制台，这里只是从命令行启动时方便看
    try:
        print(text)
    except Exception:
        pass

    return 0 if passed else 1


def parse_selftest_limit(argv):
    if "--selftest" not in argv:
        return None
    position = argv.index("--selftest")
    limit = 10
    if position + 1 < len(argv):
        try:
            limit = int(argv[position + 1])
        except ValueError:
            limit = 10
    return limit


def parse_theme_flag(argv):
    if "--dark" in argv:
        return True
    if "--light" in argv:
        return False
    return None


def parse_sync_mode(argv):
    """--sync [pve|regular]：命令行同步，主要用来验证打包后的联网能力。"""
    if "--sync" not in argv:
        return None
    position = argv.index("--sync")
    if position + 1 < len(argv) and not argv[position + 1].startswith("--"):
        return argv[position + 1]
    return "pve"


def run_sync_cli(mode):
    """不弹窗口同步一遍数据，结果写 %TEMP%\\tarkov_sync.txt。

    打包后想确认"冻结环境里 HTTPS 能不能用"就跑这个：
        TarkovMarketInfo.exe --sync pve
    """
    lines = []
    result_path = os.path.join(tempfile.gettempdir(), "tarkov_sync.txt")
    passed = True

    lines.append("Tarkov 市场排行生成器 命令行同步")
    lines.append("时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("打包运行：" + ("是" if getattr(sys, "frozen", False) else "否"))
    lines.append("模式：" + mode)
    lines.append("-" * 50)

    last_line = [""]

    def progress(phase, text, value):
        # 进度回调很密集，文案没变就不重复记，免得日志刷屏
        tag = "数据" if phase == sync.PHASE_DATA else "图标"
        line = "  [%s] %3d%%  %s" % (tag, int((value or 0) * 100), text)
        if line != last_line[0]:
            last_line[0] = line
            lines.append(line)

    try:
        result = sync.sync_all(
            sync.mode_slug(mode), with_icons=True, progress_cb=progress
        )
        lines.append("-" * 50)
        lines.append("数据库：" + result["db_path"])
        lines.append("图标目录：" + result["icon_dir"])
        lines.append("写入物品：" + str(result["items"]))
        lines.append("图标包解出：" + str(result["icon_pack"]))
        lines.append("图标已就绪：" + str(result["icons"]) + " 张（本次失败 " + str(result["icon_failed"]) + "）")
        if result["icon_aborted"]:
            lines.append("缺失图标被图床限流中断（再跑一次会接着续传）")
        lines.append("成功")
    except Exception as error:
        passed = False
        lines.append("失败：" + str(error))
        lines.append(traceback.format_exc())

    text = "\n".join(lines)
    handle = open(result_path, "w", encoding="utf-8")
    handle.write(text)
    handle.close()
    try:
        print(text)
    except Exception:
        pass
    return 0 if passed else 1


def audit_layout(root, tolerance=6, verbose=True, skip_scroll=True):
    """开发用：走一遍控件树，找出被挤出父容器的控件。

    tkinter 的 pack 不会把太宽的控件缩回去，只会让它溢出 —— 溢出在界面上
    看起来就是"文案被切掉"或者"右边多出来一截"，很难靠肉眼在截图里发现。

    滚动容器本身是故意"内容比视口高"的，往下走一层就不再报它。
    """
    problems = []
    scroll_cls = globals().get("widgets").ScrollArea if "widgets" in globals() else None

    def walk(widget, path, inside_scroll=False):
        try:
            parent_width = widget.winfo_width()
            parent_height = widget.winfo_height()
        except Exception:
            return
        for child in widget.winfo_children():
            # 没被 pack/grid/place 管的控件还留着上一次的坐标，别拿来判断
            try:
                if not child.winfo_manager():
                    continue
            except Exception:
                continue
            label = path + "/" + child.winfo_class()
            text = ""
            try:
                text = str(child.cget("text"))[:20]
            except Exception:
                pass
            if text:
                label += "(" + text + ")"

            if inside_scroll:
                # 滚动区里内容高出视口是设计如此，只查横向溢出
                if parent_width > 1 and child.winfo_x() + child.winfo_width() > parent_width + tolerance:
                    problems.append(
                        "溢出右侧：%s（子右 %d > 父 %d）"
                        % (label, child.winfo_x() + child.winfo_width(), parent_width)
                    )
            else:
                if parent_width > 1 and child.winfo_x() + child.winfo_width() > parent_width + tolerance:
                    problems.append(
                        "溢出右侧 %dpx：%s（子 %d > 父 %d）"
                        % (child.winfo_x() + child.winfo_width() - parent_width, label,
                           child.winfo_x() + child.winfo_width(), parent_width)
                    )
                if parent_height > 1 and child.winfo_height() > parent_height + tolerance:
                    problems.append(
                        "溢出底部 %dpx：%s（子 %d > 父 %d）"
                        % (child.winfo_height() - parent_height, label,
                           child.winfo_height(), parent_height)
                    )

            next_inside = inside_scroll
            if scroll_cls is not None and isinstance(child, scroll_cls):
                next_inside = True
            walk(child, label, next_inside)

    walk(root, root.winfo_class())
    if verbose:
        if problems:
            print("布局检查：发现 " + str(len(problems)) + " 个问题")
            for line in problems:
                print("  - " + line)
        else:
            print("布局检查：没有溢出 / 被切掉的控件")
    return problems


def grab_window_image(root):
    """按窗口句柄截图，别的窗口压在上面也不影响（开发调试用）。"""
    from PIL import Image

    if os.name != "nt":
        from PIL import ImageGrab

        box = (
            root.winfo_rootx(),
            root.winfo_rooty(),
            root.winfo_rootx() + root.winfo_width(),
            root.winfo_rooty() + root.winfo_height(),
        )
        return ImageGrab.grab(bbox=box)

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = int(root.frame(), 16) if isinstance(root.frame(), str) else int(root.frame())

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top

    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(memory_dc, bitmap)

    # 2 = PW_RENDERFULLCONTENT，能抓到 DirectComposition 渲染的内容
    user32.PrintWindow(hwnd, memory_dc, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth = width
    info.biHeight = -height  # 负号 = 从上到下的行序
    info.biPlanes = 1
    info.biBitCount = 32
    info.biCompression = 0

    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0)

    image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
    image = image.convert("RGB")

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(hwnd, window_dc)
    return image


def take_ui_screenshot(path, force_dark=None):
    """开发用：把窗口截下来存成 PNG，方便看界面到底长什么样。

        python main.py --shot out.png [--dark | --light]
    """
    root = tk.Tk()
    app = MarketApp(root, force_dark=force_dark)
    root.lift()

    def shoot():
        try:
            root.update_idletasks()
            root.update()
        except Exception:
            pass
        time.sleep(0.5)
        try:
            image = grab_window_image(root)
            image.save(path)
            print("截图已保存：" + path + " " + str(image.size))
        except Exception as error:
            print("截图失败：" + str(error))
        root.destroy()

    root.after(1500, shoot)
    root.mainloop()
    return 0


def main():
    # 必须在建 Tk 根窗口之前声明，否则高 DPI 屏幕上窗口会被系统拉伸变糊
    theme_module.enable_dpi_awareness()

    sync_mode = parse_sync_mode(sys.argv)
    if sync_mode is not None:
        sys.exit(run_sync_cli(sync_mode))

    if "--shot" in sys.argv:
        position = sys.argv.index("--shot")
        path = "ui_shot.png"
        if position + 1 < len(sys.argv) and not sys.argv[position + 1].startswith("--"):
            path = sys.argv[position + 1]
        sys.exit(take_ui_screenshot(path, parse_theme_flag(sys.argv)))

    limit = parse_selftest_limit(sys.argv)
    if limit is not None:
        sys.exit(self_test(limit))

    root = tk.Tk()

    # 延迟导入 app：app 要用 main.MarketApp（报表窗口），
    # 而 app 又是从这里启动的，直接 import 会绕成环。
    import app as app_module

    shell = app_module.AppShell(root, force_dark=parse_theme_flag(sys.argv))

    def on_close():
        # 报表窗口开着的话，把它的配置也存了，别丢用户的筛选条件
        if shell.report_app is not None:
            try:
                save_config(shell.report_app.collect_config())
            except Exception:
                pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
