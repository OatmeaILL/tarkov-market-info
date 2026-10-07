# -*- coding: utf-8 -*-
"""查价主窗口 —— 程序启动后的第一屏。

结构（自上而下）：
    Hero 区标题 + 数据状态+ 突出按钮（打开排行报表）/ 次级按钮（数据与设置）
    搜索框        —— 输入≥2 个字自动检索（防抖 180ms），纯本地同步
    候选列表      —— Top5，上下键/ 点击切换 = 记录历史 + 取价
    详情面板      —— 24h 均价 / 商人回收价 / 区间 / 曲线

三条设计原则（来自 TarkovScout 逻辑框架）：
    界面永不等待网络：搜索同步返回、价格本地秒显、曲线后台补
    状态显式：加载中/ 已就绪 / 网络失败 / 暂无均价 / 跳蚤不可售，各有各的说法
    记录锚定在「点击」：打字不记历史，点开候选才记

数据更新从报表窗口挪到这里（报表窗口不再管同步），统一在「数据与设置」里做。
"""

import os
import queue
import time
import tkinter as tk

import data
import price
import prefs
import search
import widgets
from theme import blend

APP_TITLE = "塔科夫查价"

WINDOW_WIDTH = 720
WINDOW_HEIGHT = 720

# 归一化后输入够几个字就自动检索。2 是底线：一个字搜出来的东西基本没法看，
# 而且和prefs.record_visit 的"≥2 字符才记历史"是同一个口径，别让两处标准不一样。
MIN_SEARCH_CHARS = 2

# 自动检索的防抖毫秒。中文输入法下打字很快，不防抖会一串一串地搜，
# 每次都重新排候选、拉曲线。180ms 是"手停下来就开始搜"的手感。
SEARCH_DEBOUNCE_MS = 180

# 详情面板的状态文案 —— 每个环节都明确表达当前状态，不假装成功
STATE_IDLE = "idle"
STATE_READY = "ready"
STATE_LOADING = "loading"
STATE_NO_DATA = "nodata"
STATE_NO_FLEA = "noflea"


class CandidateRow(tk.Frame):
    """候选列表里的一行。

    整行都是点击区（不是只有文字），所以用 bind 绑到自身而不是某个 Label。
    """

    def __init__(self, parent, theme, on_click):
        tk.Frame.__init__(self, parent, bg=theme["surface"], bd=0, highlightthickness=0)
        self.theme = theme
        self.on_click = on_click
        self.item = None
        self._hover = False

        self._height = theme.px(46)
        self.canvas = tk.Canvas(
            self, height=self._height, bg=theme["surface"],
            bd=0, highlightthickness=0, cursor="hand2",
        )
        self.canvas.pack(fill="x")

        self.canvas.bind("<Configure>", lambda event: self._draw())
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self._on_click)

    def _on_enter(self, event=None):
        self._hover = True
        self._draw()

    def _on_leave(self, event=None):
        self._hover = False
        self._draw()

    def _on_click(self, event=None):
        if self.item is not None:
            self.on_click(self.item)

    def set_item(self, item, selected=False):
        self.item = item
        self.selected = selected
        self._draw()

    def _draw(self):
        theme = self.theme
        self.canvas.delete("all")
        width = self.canvas.winfo_width() or theme.px(WINDOW_WIDTH - 60)
        height = self._height
        if width <= 1:
            return

        if self.item is None:
            return

        # 选中项用浅主色底，悬停用更浅的一档
        if getattr(self, "selected", False):
            background = theme["pcont"]
        elif self._hover:
            background = blend(theme["surface"], theme["track"], 0.6)
        else:
            background = theme["surface"]

        pad = theme.px(8)
        widgets.rounded_rect(
            self.canvas, 0, 0, width - 1, height - 1, theme.px(10),
            fill=background, outline="",
        )

        item = self.item
        name = item.get("name_zh") or item.get("name_en") or item.get("short_name") or ""
        quote = price.local_quote(item)
        if quote["has_price"]:
            price_text = price.format_money(quote["avg24h"])
            price_color = theme["ink"]
        else:
            # 第 4 级：明说"暂无"，不显示 ₽0
            price_text = "暂无均价"
            price_color = theme["ink3"]

        text_left = pad + theme.px(2)
        price_right = width - pad - theme.px(2)
        center_y = height / 2

        self.canvas.create_text(
            text_left, center_y - theme.px(7),
            text=name[:34], anchor="w",
            font=theme.fonts.body_bold, fill=theme["ink"],
        )

        # 副标题：短名 + 类型
        sub_parts = []
        if item.get("short_name"):
            sub_parts.append(item["short_name"])
        category = data.item_category(item)
        if category and category != data.OTHER_CATEGORY:
            sub_parts.append(category)
        subtitle = " · ".join(sub_parts)
        if subtitle:
            self.canvas.create_text(
                text_left, center_y + theme.px(9),
                text=subtitle[:44], anchor="w",
                font=theme.fonts.tiny, fill=theme["ink3"],
            )

        self.canvas.create_text(
            price_right, center_y,
            text=price_text, anchor="e",
            font=theme.fonts.body_bold, fill=price_color,
        )


class CurvePanel(tk.Frame):
    """历史价格曲线。用 Canvas 手绘折线。

    没有数据时显示占位文案，而不是画一条 0 线——后者会被误读成"价格一直是 0"。
    """

    def __init__(self, parent, theme, height=88):
        tk.Frame.__init__(self, parent, bg=theme["track"], bd=0, highlightthickness=0)
        self.theme = theme
        self.points = None
        self._height = theme.px(height)
        self.canvas = tk.Canvas(
            self, height=self._height, bg=theme["track"],
            bd=0, highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self._draw())

    def set_points(self, points):
        self.points = points or None
        self._draw()

    def set_placeholder(self, text):
        self.points = None
        self.placeholder = text
        self._draw()

    def _draw(self):
        theme = self.theme
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 1 or height <= 1:
            return

        if not self.points:
            text = getattr(self, "placeholder", "近 7 天价格走势")
            self.canvas.create_text(
                width / 2, height / 2, text=text,
                font=theme.fonts.tiny, fill=theme["ink3"],
            )
            return

        points = self.points
        prices = [value for _stamp, value in points]
        low = min(prices)
        high = max(prices)
        if high <= low:
            # 全程一个价：画一条水平线，别除以零
            high = low + 1

        pad_x = theme.px(10)
        pad_y = theme.px(12)
        draw_width = width - pad_x * 2
        draw_height = height - pad_y * 2
        span = len(points) - 1
        if span <= 0:
            span = 1

        coords = []
        for index, value in enumerate(prices):
            x = pad_x + draw_width * index / span
            ratio = (value - low) / (high - low)
            y = pad_y + draw_height * (1 - ratio)
            coords.extend((x, y))

        # 面积填充 + 折线。折线画两遍：亮色主线 + 深色描边，浅色背景下更清楚
        fill_coords = [coords[0], coords[1]] + coords + [coords[-2], coords[-1]]
        self.canvas.create_polygon(
            fill_coords, fill=blend(theme["track"], theme["primary"], 0.18), outline="",
        )
        self.canvas.create_line(
            coords, fill=theme["primary"], width=theme.px(1.8),
            smooth=True, capstyle=tk.ROUND, joinstyle=tk.ROUND,
        )
        # 末点标一个圆点
        self.canvas.create_oval(
            coords[-2] - theme.px(3), coords[-1] - theme.px(3),
            coords[-2] + theme.px(3), coords[-1] + theme.px(3),
            fill=theme["primary"], outline="",
        )

        # 最低 / 最高标注
        self.canvas.create_text(
            pad_x, height - theme.px(2),
            text="低 " + price.format_money(low), anchor="sw",
            font=theme.fonts.tiny, fill=theme["ink3"],
        )
        self.canvas.create_text(
            width - pad_x, theme.px(2),
            text="高 " + price.format_money(high), anchor="ne",
            font=theme.fonts.tiny, fill=theme["ink3"],
        )


class HomeWindow:
    """查价主窗口。"""

    def __init__(self, root, theme, open_report, open_settings, app_dir):
        self.root = root
        self.theme = theme
        self.colors = theme.colors
        self.app_dir = app_dir
        # 收藏 / 曲线缓存都在 data\ 下，和 exe 目录不是一回事
        self.data_dir = data.data_dir()

        # 回调由外部注入：打开报表窗口 / 打开设置窗口
        self.open_report = open_report
        self.open_settings = open_settings

        self.items = []
        self.index = None
        self.current_item = None
        self.current_query = ""
        self.candidates = []
        self.rows = []
        self.selected_row = -1

        # 曲线请求的返回队列：后台线程塞进来，主线程after 里取
        self.curve_queue = queue.Queue()
        # 防止快速连点物品时，旧曲线的返回覆盖新物品的
        self.curve_token = 0
        # 待执行的自动检索计时器（None = 没有待执行的）。每次打字重置。
        self.search_timer = None

        self.query_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.state_var = tk.StringVar()

        self.build_ui()
        self.load_items()
        self.root.after(120, self.poll_curve_queue)

    # ---------- 界面 ----------

    def build_ui(self):
        root = self.root
        theme = self.theme
        colors = self.colors

        root.title(APP_TITLE)
        root.configure(bg=colors["page"])
        root.resizable(True, True)
        root.minsize(theme.px(600), theme.px(600))

        root.grid_rowconfigure(1, weight=1)
        root.grid_columnconfigure(0, weight=1)

        self.build_hero(root)

        # 主体放在滚动区里，窗口矮的时候不会切掉内容
        self.scroll = widgets.ScrollArea(root, theme, padding=(20, 4, 20, 20))
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.build_search(self.scroll.content)
        self.build_candidates(self.scroll.content)
        self.build_detail(self.scroll.content)

        self.place_window()

    def build_hero(self, root):
        """顶部Hero 区：标题 + 数据状态 + 突出的报表按钮。"""
        theme = self.theme
        colors = self.colors

        hero = tk.Frame(root, bg=colors["page"], bd=0, highlightthickness=0)
        hero.grid(row=0, column=0, sticky="ew",
                  padx=theme.px(20), pady=(theme.px(18), theme.px(6)))
        self.hero = hero

        # 左侧：标题 + 状态
        left = tk.Frame(hero, bg=colors["page"])
        left.pack(side="left", anchor="w")

        title = tk.Label(
            left, text=APP_TITLE, bg=colors["page"], fg=colors["ink"],
            font=theme.fonts.title, anchor="w",
        )
        title.pack(anchor="w")

        self.status_label = tk.Label(
            left, textvariable=self.status_var, bg=colors["page"],
            fg=colors["ink3"], font=theme.fonts.small, anchor="w",
        )
        self.status_label.pack(anchor="w", pady=(theme.px(3), 0))

        # 右侧：主按钮（打开报表）+ 次按钮（数据与设置）
        # 主按钮用 widgets.Button 的 primary 变体，是整个窗口颜色最突出的地方
        right = tk.Frame(hero, bg=colors["page"])
        right.pack(side="right", anchor="e")

        self.report_button = widgets.Button(
            right, theme, "打开排行报表",
            command=self.on_open_report,
            variant="primary", min_width=140, height=40,
        )
        self.report_button.pack(side="left", padx=(0, theme.px(8)))

        self.settings_button = widgets.Button(
            right, theme, "数据与设置",
            command=self.on_open_settings,
            variant="secondary", min_width=110, height=40,
        )
        self.settings_button.pack(side="left")

    def build_search(self, parent):
        theme = self.theme
        colors = self.colors

        self.search_card = widgets.RoundCard(
            parent, theme, padding=(14, 12, 14, 12), radius=14,
        )
        self.search_card.pack(fill="x")
        body = self.search_card.body

        row = tk.Frame(body, bg=colors["surface"])
        row.pack(fill="x")

        entry = widgets.make_entry(row, theme, self.query_var, width=28)
        entry.pack(side="left", fill="x", expand=True, ipady=theme.px(4))
        entry.bind("<Return>", self.on_search)
        entry.bind("<KP_Enter>", self.on_search)
        # 上下键（小键盘和主键区都算）切候选。bind 到输入框上，
        # 这样打字时方向键就在这里走；bind 到窗口上会被滚动容器抢走。
        entry.bind("<Up>", lambda event: self.on_move_selection(-1))
        entry.bind("<Down>", lambda event: self.on_move_selection(1))
        entry.bind("<KP_Up>", lambda event: self.on_move_selection(-1))
        entry.bind("<KP_Down>", lambda event: self.on_move_selection(1))
        self.search_entry = entry

        # 输入 ≥ MIN_SEARCH_CHARS 个字符就自动检索，不用回车也不用点按钮。
        # 用 StringVar 的 trace 而不是 <KeyRelease>：后者漏掉鼠标粘贴，
        # 而且中文输入法上 <KeyRelease> 会在拼音字母阶段就触发，搜到错误的东西。
        self.query_var.trace_add("write", self.on_query_changed)

        self.search_button = widgets.Button(
            row, theme, "查价", command=self.on_search,
            variant="primary", min_width=84, height=36,
        )
        self.search_button.pack(side="left", padx=(theme.px(8), 0))

        # 状态行：加载中 / 就绪 / 网络失败 / 暂无均价，各有各的说法
        state_row = tk.Frame(body, bg=colors["surface"])
        state_row.pack(fill="x", pady=(theme.px(8), 0))
        self.state_pill = widgets.Pill(state_row, theme, "输入物品名开始查价", "idle")
        self.state_pill.pack(side="left")

        hint = tk.Label(
            state_row, text="输入 2 个字自动查 · 上下键选候选 · 回车直接看第一个",
            bg=colors["surface"], fg=colors["ink3"],
            font=theme.fonts.tiny, anchor="w",
        )
        hint.pack(side="right")

    def build_candidates(self, parent):
        theme = self.theme
        colors = self.colors

        card = widgets.RoundCard(
            parent, theme, padding=(14, 12, 14, 12), radius=14,
            title="候选物品", subtitle="规则打分排序，最多 5 条",
        )
        card.pack(fill="x", pady=(theme.px(12), 0))
        self.candidates_card = card

        self.candidates_box = tk.Frame(card.body, bg=colors["surface"])
        self.candidates_box.pack(fill="x")

        self.rows = []
        for _ in range(5):
            row = CandidateRow(self.candidates_box, theme, self.on_pick_candidate)
            row.pack(fill="x", pady=theme.px(2))
            self.rows.append(row)

        self.empty_label = tk.Label(
            card.body, text="还没有查询。输入物品名就会自动查。",
            bg=colors["surface"], fg=colors["ink3"],
            font=theme.fonts.small, anchor="w",
        )

        # 收藏 + 最近搜索两个入口
        tools = tk.Frame(card.body, bg=colors["surface"])
        tools.pack(fill="x", pady=(theme.px(8), 0))
        self.favorites_button = widgets.Button(
            tools, theme, "我的收藏", command=self.on_show_favorites,
            variant="link", min_width=80, height=26,
        )
        self.favorites_button.pack(side="left")
        self.recent_button = widgets.Button(
            tools, theme, "最近查看", command=self.on_show_recent,
            variant="link", min_width=80, height=26,
        )
        self.recent_button.pack(side="left", padx=(theme.px(8), 0))

    def build_detail(self, parent):
        theme = self.theme
        colors = self.colors

        card = widgets.RoundCard(
            parent, theme, padding=(16, 14, 16, 14), radius=14,
            title="价格详情",
        )
        card.pack(fill="x", pady=(theme.px(12), 0))
        self.detail_card = card
        body = card.body

        # 物品名 + 收藏按钮
        head = tk.Frame(body, bg=colors["surface"])
        head.pack(fill="x")
        self.detail_name = tk.Label(
            head, text="用上下键选一个候选", bg=colors["surface"], fg=colors["ink"],
            font=theme.fonts.heading, anchor="w",
        )
        self.detail_name.pack(side="left")
        self.favorite_button = widgets.Button(
            head, theme, "收藏", command=self.on_toggle_favorite,
            variant="secondary", min_width=64, height=28,
        )
        self.favorite_button.pack(side="right")

        # 三个价格块
        grid = tk.Frame(body, bg=colors["surface"])
        grid.pack(fill="x", pady=(theme.px(12), 0))
        grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="price")
        self.price_labels = {}
        for column, (key, caption) in enumerate([
            ("avg24h", "24 小时均价"),
            ("trader", "商人回收价"),
            ("range", "24 小时区间"),
        ]):
            cell = tk.Frame(grid, bg=colors["bg"], bd=0, highlightthickness=0)
            cell.grid(row=0, column=column, sticky="ew",
                      padx=(0, theme.px(8)) if column < 2 else 0)
            pad = theme.px(12)
            tk.Label(
                cell, text=caption, bg=colors["bg"], fg=colors["ink2"],
                font=theme.fonts.tiny, anchor="w",
            ).pack(anchor="w", padx=pad, pady=(pad, 0))
            value_label = tk.Label(
                cell, text="—", bg=colors["bg"], fg=colors["ink"],
                font=theme.fonts.body_bold, anchor="w",
            )
            value_label.pack(anchor="w", padx=pad, pady=(theme.px(2), pad))
            self.price_labels[key] = value_label

        # 商人明细
        self.trader_label = tk.Label(
            body, text="", bg=colors["surface"], fg=colors["ink2"],
            font=theme.fonts.tiny, anchor="w", justify="left",
        )
        self.trader_label.pack(fill="x", pady=(theme.px(8), 0))

        # 曲线
        self.curve_panel = CurvePanel(body, theme, height=96)
        self.curve_panel.pack(fill="x", pady=(theme.px(12), 0))
        self.curve_panel.set_placeholder("近 7 天价格走势")

        self.curve_note = tk.Label(
            body, text="", bg=colors["surface"], fg=colors["ink3"],
            font=theme.fonts.tiny, anchor="w",
        )
        self.curve_note.pack(fill="x", pady=(theme.px(6), 0))

    def place_window(self):
        """小窗口：按屏幕可用区收口后居中。

        高度要能一次看全"候选 + 详情"——查价窗口的意义就在这儿，
        让人一直往下滚才看到价格是失败的。所以先量内容高度，再决定要不要缩。
        """
        root = self.root
        root.update_idletasks()
        self.scroll.refresh()

        area_width = root.winfo_screenwidth()
        area_height = root.winfo_screenheight()

        # 内容要占多高：头部 + 搜索 + 候选 + 详情 + 一点余量
        # 窗口宽度不走 theme.px：DENSITY 是给"设计稿像素"做整体收紧的，
        # 但窗口本身就该是那个尺寸——再乘 0.88 会窄到内容换行、价格被挤掉。
        wanted_width = min(WINDOW_WIDTH, area_width - 40)
        header_height = self.hero.winfo_reqheight() + self.theme.px(24)
        content_height = self.scroll.content.winfo_reqheight() + self.theme.px(48)

        width = min(wanted_width, area_width - self.theme.px(40))
        # 优先给足高度装下内容；装不下才按屏幕可用区的85% 收口
        height = min(content_height, int(area_height * 0.85))
        height = max(height, self.theme.px(560))
        height = min(height, area_height - self.theme.px(40))

        pos_x = max(0, (area_width - width) // 2)
        pos_y = max(0, (area_height - height) // 2)
        root.geometry("%dx%d+%d+%d" % (width, height, pos_x, pos_y))
        root.update_idletasks()

    # ---------- 数据 ----------

    def load_items(self):
        """读本地库建索引。读不到就明说，不假装有数据。"""
        db_path = data.find_default_db()
        if not db_path:
            self.set_state("找不到本地数据，点「数据与设置」下载", "bad")
            self.status_var.set("未下载物品数据")
            return
        try:
            self.items = data.load_all_items(db_path)
        except (FileNotFoundError, Exception) as exc:
            self.set_state("数据读取失败：" + str(exc), "bad")
            self.status_var.set("数据读取失败")
            return

        self.index = search.SearchIndex(self.items)
        summary = data.load_db_summary(db_path)
        total = summary["total"] if summary else len(self.items)
        stamp = summary["last_sync"] if summary else 0
        when = time.strftime("%m-%d %H:%M", time.localtime(stamp)) if stamp else "未知"
        self.status_var.set("%s 项本地索引 · 更新于 %s" % (total, when))

    def refresh_data(self):
        """设置页更新完数据后回调，重新读库。"""
        self.load_items()
        self.scroll.refresh()
        if self.current_item is not None:
            # 当前物品的价格可能变了，重画一次
            self.show_detail(self.current_item)

    # ---------- 搜索 ----------

    def on_query_changed(self, *_args):
        """输入框内容变了。够2 个字就自动检索。

        只在真正变化时重置防抖计时器；不够 2 个字立刻清空候选，
        这样用户删字的时候界面马上回到干净状态，不用等计时器。
        """
        raw = self.query_var.get().strip()
        if not search.normalize(raw):
            self.clear_candidates()
            self.set_state("输入物品名开始查价", "idle")
            return
        if len(search.normalize(raw)) < MIN_SEARCH_CHARS:
            self.clear_candidates()
            self.set_state("再输入 %d 个字就自动查" % (MIN_SEARCH_CHARS - len(search.normalize(raw))), "idle")
            return

        # 连续打字时重置计时器，最后一次停下才开始搜
        if self.search_timer is not None:
            try:
                self.root.after_cancel(self.search_timer)
            except (tk.TclError, ValueError):
                pass
            self.search_timer = None
        self.search_timer = self.root.after(SEARCH_DEBOUNCE_MS, self.on_search)

    def clear_candidates(self):
        """清空候选和详情，回到"还没查"的状态。"""
        self.candidates = []
        self.render_candidates()
        self.reset_detail()

    def reset_detail(self):
        """把详情面板清回初始态（价格占位 + 曲线占位 + 收藏按钮复位）。"""
        self.current_item = None
        self.detail_name.configure(text="点候选看价格")
        labels = self.price_labels
        labels["avg24h"].configure(text="暂无均价")
        labels["trader"].configure(text="—")
        labels["range"].configure(text="—")
        self.trader_label.configure(text="")
        self.curve_panel.set_placeholder("选一个候选看走势")
        self.curve_note.configure(text="")

    def on_search(self, event=None):
        """真正的检索。搜索是纯本地同步的，几毫秒就返回，不卡界面。"""
        # 手动触发（回车/点按钮）时取消待执行的自动检索，免得搜两遍
        if self.search_timer is not None:
            try:
                self.root.after_cancel(self.search_timer)
            except (tk.TclError, ValueError):
                pass
            self.search_timer = None

        raw = self.query_var.get().strip()
        if not raw:
            self.clear_candidates()
            self.set_state("输入物品名开始查价", "idle")
            return
        if self.index is None:
            self.set_state("物品数据还没准备好", "bad")
            return

        self.current_query = raw
        self.candidates = self.index.search(raw, top_n=5)
        self.render_candidates()

        if not self.candidates:
            self.reset_detail()
            self.set_state("没找到「%s」相关的物品，换个说法试试" % raw, "warn")
            return

        # 自动检索时只停在"找到几行"，不替用户选第一行——
        # 直接选中会让人打字打到一半就被换掉详情，曲线也白拉一次。
        # 回车/点按钮是"明确要看"，才默认选中第一个。
        if event is not None:
            self.select_candidate(0)
            self.set_state("找到 %d 个候选，已选中第一个" % len(self.candidates), "ok")
        else:
            self.set_state("找到 %d 个候选，按上下键选" % len(self.candidates), "ok")

    def on_move_selection(self, step):
        """上下键切候选。到边界就停住，不循环。

        切过去会立即显示详情并拉曲线，和鼠标点一行是同一套逻辑。
        """
        if not self.candidates:
            return
        # 一个都没选过时，第一下不管按上还是下都落到第 0 行
        if self.selected_row < 0:
            target = 0
        else:
            target = self.selected_row + step
        target = max(0, min(target, len(self.candidates) - 1))
        if target == self.selected_row:
            return
        self.select_candidate(target)

    def render_candidates(self):
        for index, row in enumerate(self.rows):
            if index < len(self.candidates):
                row.pack(fill="x", pady=self.theme.px(2))
                row.set_item(self.candidates[index][0], selected=False)
            else:
                row.set_item(None)
                row.pack_forget()
        self.selected_row = -1
        if not self.candidates:
            self.empty_label.configure(text="没有匹配的物品。换个说法试试。")
            self.empty_label.pack(fill="x", pady=(self.theme.px(6), 0))
        else:
            self.empty_label.pack_forget()
        self.candidates_box.update_idletasks()

    def on_pick_candidate(self, item):
        """点候选 = 查看 = 记录历史。

        历史锚定在这个动作上，而不是打字时——随手打两个字没有留存价值。
        """
        prefs.record_visit(self.data_dir, item, self.current_query or item.get("name_zh", ""))
        for index, (candidate, _score) in enumerate(self.candidates):
            if candidate is item:
                self.select_candidate(index)
                return
        self.show_detail(item)

    def select_candidate(self, index):
        if index < 0 or index >= len(self.candidates):
            return
        for position, row in enumerate(self.rows):
            row.set_item(
                self.candidates[position][0] if position < len(self.candidates) else None,
                selected=position == index,
            )
        self.selected_row = index
        self.show_detail(self.candidates[index][0])

    # ---------- 详情 ----------

    def show_detail(self, item):
        """显示详情。价格本地秒显，曲线后台慢慢补。"""
        self.current_item = item
        name = item.get("name_zh") or item.get("name_en") or item.get("short_name") or ""
        self.detail_name.configure(text=name[:40])

        quote = price.local_quote(item)
        labels = self.price_labels
        if quote["has_price"]:
            labels["avg24h"].configure(text=price.format_money(quote["avg24h"]))
            labels["range"].configure(
                text="%s – %s" % (
                    price.format_money(quote["low24h"]),
                    price.format_money(quote["high24h"]),
                )
            )
        else:
            # 第 4 级空占位：明说没有，不显示 ₽0
            labels["avg24h"].configure(text="暂无均价")
            labels["range"].configure(text="暂无")

        if quote["trader_price"] > 0:
            labels["trader"].configure(text=price.format_money(quote["trader_price"]))
        else:
            labels["trader"].configure(text="无人收购")

        # 商人明细
        traders = price.trader_names(item)[:3]
        if traders:
            text = "商人收购：" + "· ".join(
                "%s %s" % (name_text, price.format_money(amount))
                for name_text, amount in traders
            )
            self.trader_label.configure(text=text)
        else:
            self.trader_label.configure(text="")

        # 收藏状态两处同步：候选行高亮 + 详情按钮
        self.refresh_favorite_button(item)

        # 跳蚤不可售要明说——用户可能想拿去卖
        if not quote["flea_enabled"]:
            self.set_state("跳蚤市场不可售", "warn")
        elif quote["offer_count"] > 0:
            self.set_state("挂单 %d 条 · 商人收购价已算出" % quote["offer_count"], "ok")
        else:
            self.set_state("当前无挂单", "warn")

        self.load_curve(item)

    def refresh_favorite_button(self, item=None):
        target = item or self.current_item
        if target is None:
            return
        if prefs.is_favorite(self.data_dir, target.get("id", "")):
            self.favorite_button.set_text("已收藏")
            self.favorite_button.variant = "primary"
        else:
            self.favorite_button.set_text("收藏")
            self.favorite_button.variant = "secondary"

    def load_curve(self, item):
        """曲线：先出占位，后台拉回来再重绘。

        token 用来丢弃过期返回——用户快速连点时，
        上一个物品的曲线回来得晚，不能盖掉当前物品的。
        """
        self.curve_token += 1
        token = self.curve_token
        self.curve_panel.set_placeholder("正在取近 7 天走势…")
        self.curve_note.configure(text="")

        item_id = item.get("id", "")
        mode = self.get_mode()

        def callback(points, error):
            self.curve_queue.put((token, item_id, points, error))

        price.load_history_async(mode, self.data_dir, item_id, callback)

    def poll_curve_queue(self):
        """取后台返回的曲线。曲线失败不影响其他内容。"""
        try:
            while True:
                token, item_id, points, error = self.curve_queue.get_nowait()
                # token 过期 = 用户已经切到别的物品了，丢弃
                if token != self.curve_token:
                    continue
                if points:
                    self.curve_panel.set_points(points)
                    summary = price.curve_summary(points)
                    if summary:
                        text, up = summary[0]
                        color = self.colors["primary"] if up else self.colors["danger"]
                        self.curve_note.configure(text=text, fg=color)
                    else:
                        self.curve_note.configure(text="")
                else:
                    # 明确说"没取到"，不装作成功，也不画一条 0 线
                    self.curve_panel.set_placeholder("取不到历史价格")
                    self.curve_note.configure(
                        text="曲线需要联网，不影响上面的价格", fg=self.colors["ink3"],
                    )
        except queue.Empty:
            pass
        self.root.after(150, self.poll_curve_queue)

    # ---------- 收藏 / 历史 ----------

    def on_toggle_favorite(self):
        if self.current_item is None:
            self.set_state("先点一个候选物品", "idle")
            return
        state = prefs.toggle_favorite(self.data_dir, self.current_item.get("id", ""))
        self.refresh_favorite_button()
        self.set_state("已加入收藏" if state else "已取消收藏", "ok")

    def on_show_favorites(self):
        entries = prefs.favorite_ids(self.data_dir)
        self.show_id_list("我的收藏", entries, empty_text="还没有收藏。看到有用的物品点「收藏」。")

    def on_show_recent(self):
        recent = prefs.recent_entries(self.data_dir)
        ids = [entry[0] for entry in recent if entry]
        self.show_id_list("最近查看", ids, empty_text="还没有查看记录。点候选看价格才会记。")

    def show_id_list(self, title, item_ids, empty_text):
        """按 id 列表展示。id 失效（换了数据源）就跳过，不报错。"""
        by_id = {item["id"]: item for item in self.items}
        found = [by_id[item_id] for item_id in item_ids if item_id in by_id]
        if not found:
            self.set_state(empty_text, "idle")
            return
        # 这里的候选不是搜索来的，清掉 current_query，
        # 免得之后点候选记历史时把id 列表当成查询词记下来
        self.current_query = ""
        self.candidates = [(item, 0) for item in found[:5]]
        self.render_candidates()
        self.set_state("%s：%d 项" % (title, len(found[:5])), "ok")
        self.select_candidate(0)

    # ---------- 回调 ----------

    def set_state(self, text, kind="idle"):
        self.state_pill.set(text, kind)
        self.state_var.set(text)

    def on_open_report(self):
        self.open_report()

    def on_open_settings(self):
        self.open_settings()

    def focus_search(self):
        try:
            self.search_entry.focus_set()
        except tk.TclError:
            pass

    def get_mode(self):
        """当前游戏模式。设置页可能改过，这里读配置。"""
        try:
            import json

            with open(data.config_path(), "r", encoding="utf-8") as handle:
                return json.load(handle).get("game_mode", "PVE")
        except (OSError, ValueError):
            return "PVE"