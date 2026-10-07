# -*- coding: utf-8 -*-
"""界面小组件 —— 用 Canvas 手绘，做出 MaiBill 那种圆角卡片 + 薄荷绿按钮的观感。

tkinter 原生控件是方的、颜色也压不住，所以关键部件都自己在 Canvas 上画：

    RoundCard   圆角卡片，自动跟着内容长高
    ScrollArea  可滚动的页面容器（窗口矮的时候也不会切掉内容）
    Button      圆角按钮（主要 / 次要 / 描边 / 文字链）
    CheckBox    圆角勾选框
    Segmented   分段选择器（贵的在前 / 便宜的在前）
    ProgressBar 进度条
    Pill        状态胶囊标签
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from theme import blend


# ---------- 绘图基础 ----------


def rounded_rect(canvas, x1, y1, x2, y2, radius, **options):
    """在 Canvas 上画一个圆角矩形（用多边形 + 平滑近似，不依赖外部库）。"""
    radius = max(0, min(radius, abs(x2 - x1) // 2, abs(y2 - y1) // 2))
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=12, **options)


def measure_text(spec, text):
    """算文字宽度（像素），控件自己定尺寸时要用。"""
    return tkfont.Font(font=spec).measure(text)


# ---------- 圆角卡片 ----------


class RoundCard(tk.Frame):
    """圆角卡片。

    做法：外层 Canvas 画圆角底 + 一条分隔线，内容用 place 铺在上面。
    高度不写死，由内容自己撑开——所以卡片会跟着里面控件长高。
    """

    def __init__(
        self,
        parent,
        theme,
        padding=(18, 16, 18, 16),
        radius=18,
        title=None,
        subtitle=None,
        accent=None,
    ):
        tk.Frame.__init__(self, parent, bg=theme["bg"], bd=0, highlightthickness=0)
        self.theme = theme
        # 设计稿像素换算成设备像素，高 DPI 下卡片才不会和字号脱节
        self.pad = tuple(theme.px(value) for value in padding)
        self.radius = theme.px(radius)
        self.accent = accent

        self.canvas = tk.Canvas(
            self, bg=theme["bg"], bd=0, highlightthickness=0, takefocus=0
        )
        self.canvas.pack(fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=theme["surface"], bd=0, highlightthickness=0)
        self.canvas.create_window(
            self.pad[0],
            self.pad[1],
            window=self.inner,
            anchor="nw",
            tags="inner",
        )

        self.body = self.inner
        self.header = None
        if title:
            self.header = self._build_header(title, subtitle)

        self._bg_shape = None
        self._line_shape = None
        self._last_width = -1
        self._last_size = None
        self.canvas.bind("<Configure>", self._on_resize)

    def _build_header(self, title, subtitle):
        theme = self.theme
        header = tk.Frame(self.inner, bg=theme["surface"])
        header.pack(fill="x", pady=(0, theme.px(12)))

        left = tk.Frame(header, bg=theme["surface"])
        left.pack(side="left", fill="x", expand=True)

        top = tk.Frame(left, bg=theme["surface"])
        top.pack(fill="x")
        bar_color = self.accent or theme["primary"]
        accent = tk.Frame(top, bg=bar_color, width=theme.px(4), height=theme.px(15))
        accent.pack(side="left", pady=theme.px(1))
        accent.pack_propagate(False)

        self.header_label = tk.Label(
            top,
            text=title,
            bg=theme["surface"],
            fg=theme["ink"],
            font=theme.fonts.heading,
            anchor="w",
        )
        self.header_label.pack(side="left", padx=(theme.px(9), 0))

        self.header_hint = tk.Label(
            header,
            text="",
            bg=theme["surface"],
            fg=theme["ink3"],
            font=theme.fonts.small,
            anchor="e",
        )
        self.header_hint.pack(side="right", padx=(theme.px(10), 0))

        if subtitle:
            self.subtitle_label = tk.Label(
                left,
                text=subtitle,
                bg=theme["surface"],
                fg=theme["ink2"],
                font=theme.fonts.small,
                anchor="w",
                justify="left",
                wraplength=theme.px(520),
            )
            self.subtitle_label.pack(
                fill="x", padx=(theme.px(13), 0), pady=(theme.px(5), 0)
            )
        return header

    def set_hint(self, text):
        if self.header is not None:
            self.header_hint.configure(text=text)

    # --- 尺寸同步 ---

    def _on_resize(self, event=None):
        width = self.canvas.winfo_width()
        if width <= 1:
            return
        if width != self._last_width:
            self._last_width = width
            inner_width = max(self.theme.px(80), width - self.pad[0] - self.pad[2])
            self.canvas.itemconfigure("inner", width=inner_width)
        self.refresh()

    def refresh(self):
        """重画底色和分隔线，并让卡片高度跟上内容的实际高度。

        尺寸没变就直接返回：拖窗口 / 展开面板时会连着触发好几次 Configure，
        每次都 delete + 重画整个圆角底纯属白费。
        """
        width = self.canvas.winfo_width()
        if width <= 1:
            return

        inner_height = self.inner.winfo_reqheight()
        height = inner_height + self.pad[1] + self.pad[3]
        size_key = (width, height)
        if size_key == self._last_size:
            return
        self._last_size = size_key

        self.canvas.configure(height=height)

        self.canvas.delete("cardbg")
        self._bg_shape = rounded_rect(
            self.canvas,
            0,
            0,
            width - 1,
            height - 1,
            self.radius,
            fill=self.theme["surface"],
            outline=self.theme["line"],
            width=1,
            tags="cardbg",
        )
        self.canvas.tag_lower("cardbg")

        if self.header is not None:
            y = self.pad[1] + self.header.winfo_reqheight() + 3
            self.canvas.delete("cardline")
            self._line_shape = self.canvas.create_line(
                self.pad[0] - 2,
                y,
                width - self.pad[2] + 2,
                y,
                fill=self.theme["line"],
                tags="cardline",
            )

    # --- 内容构建小工具 ---

    def row(self, pady=(0, 8), fill="x"):
        frame = tk.Frame(self.body, bg=self.theme["surface"])
        frame.pack(fill=fill, pady=pady)
        return frame

    def note(self, parent, text, kind="dim"):
        colors = {
            "dim": self.theme["ink2"],
            "muted": self.theme["ink3"],
            "primary": self.theme["primary"],
            "amber": self.theme["amber"],
            "danger": self.theme["danger"],
        }
        label = tk.Label(
            parent,
            text=text,
            bg=self.theme["surface"],
            fg=colors.get(kind, self.theme["ink2"]),
            font=self.theme.fonts.small,
            anchor="w",
            justify="left",
            wraplength=self.theme.px(680),
        )
        return label

    def divider(self, pady=(4, 12)):
        line = tk.Frame(self.body, bg=self.theme["line"], height=1)
        line.pack(fill="x", pady=tuple(self.theme.px(value) for value in pady))
        return line


# ---------- 页面滚动容器 ----------


class ScrollArea(tk.Frame):
    """竖着排的页面放到 Canvas 里，窗口不够高时可以滚。

    滚动条只在内容真的超出时出现，平时看不见，界面干净。
    """

    def __init__(self, parent, theme, padding=(22, 20, 22, 24)):
        tk.Frame.__init__(self, parent, bg=theme["bg"], bd=0, highlightthickness=0)
        self.theme = theme
        self.padding = tuple(theme.px(value) for value in padding)

        self.canvas = tk.Canvas(
            self, bg=theme["bg"], bd=0, highlightthickness=0, takefocus=0
        )
        # 带上主题样式，否则 clam 默认的灰色滚动条在深色模式下很突兀
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            style="Card.Vertical.TScrollbar",
        )
        self.canvas.configure(yscrollcommand=self._on_scrollbar_set)
        # yscrollincrement=0 时一个 "unit" 是视口高度的 1/10，滚轮一次滚 3 个 unit
        # 就等于跳掉 30% 屏，滚起来一卡一卡的。定死成像素后一次滚轮约 55px。
        self.canvas.configure(yscrollincrement=theme.px(20))

        self.canvas.pack(side="left", fill="both", expand=True)
        # 滚动条不用 pack，改成 place 浮在右侧内边距上：pack 一出现/消失会改变画布
        # 宽度，导致所有卡片重新换行、整屏重画一遍，展开面板就会卡一下。
        self.scrollbar_width = theme.px(11)

        self.content = tk.Frame(self.canvas, bg=theme["bg"], bd=0, highlightthickness=0)
        self._window = self.canvas.create_window(
            self.padding[0],
            self.padding[1],
            window=self.content,
            anchor="nw",
        )

        self._width = 0
        self._last_scrollregion = None
        self._busy = False
        self._pending = False

        self.content.bind("<Configure>", lambda event: self.refresh())
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self._bind_wheel()

    # --- 布局 ---

    def _on_canvas_resize(self, event):
        if event.width == self._width:
            return
        self._width = event.width
        inner = max(self.theme.px(120), event.width - self.padding[0] - self.padding[2])
        self.canvas.itemconfigure(self._window, width=inner)
        self.refresh()

    def refresh(self):
        """把滚动范围同步成内容的真实高度。"""
        if self._busy:
            self._pending = True
            return
        self._busy = True
        try:
            height = self.content.winfo_reqheight() + self.padding[1] + self.padding[3]
            width = self.canvas.winfo_width()
            region = (0, 0, width, max(height, self.canvas.winfo_height()))
            if region != self._last_scrollregion:
                self._last_scrollregion = region
                self.canvas.configure(scrollregion=region)
            self._sync_scrollbar()
        finally:
            self._busy = False
            if self._pending:
                self._pending = False
                self.after_idle(self.refresh)

    def _sync_scrollbar(self):
        first, last = self.canvas.yview()
        needed = not (first <= 0.0 and last >= 1.0)
        mapped = bool(self.scrollbar.winfo_manager())
        if needed and not mapped:
            # 浮在画布右侧：不参与布局，出现 / 消失不会改变画布宽度
            self.scrollbar.place(
                relx=1.0, rely=0.0, anchor="ne", relheight=1.0,
                width=self.scrollbar_width,
            )
        elif not needed and mapped:
            self.scrollbar.place_forget()
            self.canvas.yview_moveto(0.0)

    def _on_scrollbar_set(self, first, last):
        self.scrollbar.set(first, last)
        self.after_idle(self._sync_scrollbar)

    def body(self):
        return self.content

    def add(self, widget, pady=(0, 14)):
        widget.pack(fill="x", pady=tuple(self.theme.px(value) for value in pady))
        return widget

    def scroll_to_bottom(self):
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)

    # --- 滚轮 ---

    def _in_this_area(self, event):
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return False
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def handles_wheel(self, event):
        """给内部需要自己滚的控件（比如日志框）判断要不要让位。"""
        return self._in_this_area(event)

    def _bind_wheel(self):
        def on_wheel(event):
            try:
                widget = self.winfo_containing(event.x_root, event.y_root)
            except Exception:
                return None
            # 挂在别的可滚动区域下面时，交给那个区域处理
            if widget is not None and not self._in_this_area(event):
                return None
            if isinstance(widget, tk.Text):
                return None
            first, last = self.canvas.yview()
            if first <= 0.0 and last >= 1.0:
                return "break"
            delta = 0
            if getattr(event, "num", None) == 4:
                delta = -3
            elif getattr(event, "num", None) == 5:
                delta = 3
            elif getattr(event, "delta", 0):
                delta = int(-event.delta / 120 * 3) or (-3 if event.delta > 0 else 3)
            if delta:
                self.canvas.yview_scroll(delta, "units")
            return "break"

        def on_shift_wheel(event):
            delta = 0
            if getattr(event, "num", None) == 4:
                delta = -3
            elif getattr(event, "num", None) == 5:
                delta = 3
            elif getattr(event, "delta", 0):
                delta = int(-event.delta / 120 * 3) or (-3 if event.delta > 0 else 3)
            if delta:
                self.canvas.yview_scroll(delta, "units")
            return "break"

        root = self.winfo_toplevel()
        root.bind("<MouseWheel>", on_wheel, add="+")
        root.bind("<Button-4>", on_wheel, add="+")
        root.bind("<Button-5>", on_wheel, add="+")
        root.bind("<Shift-MouseWheel>", on_shift_wheel, add="+")


# ---------- 按钮 ----------


class Button(tk.Canvas):
    """圆角按钮。variant: primary / secondary / ghost / danger / link"""

    def __init__(
        self,
        parent,
        theme,
        text,
        command=None,
        variant="secondary",
        icon="",
        min_width=0,
        font=None,
        height=38,
        radius=12,
    ):
        self.theme = theme
        self.variant = variant
        self.text = text
        self.icon = icon
        self.command = command
        self.font = font or theme.fonts.body_bold
        self.radius = theme.px(radius)
        self._min_width = theme.px(min_width) if min_width else 0
        self._height = theme.px(height)
        self._width = max(self._min_width, self._measure())
        self._state = "normal"
        self._hover = False
        self._pressed = False

        tk.Canvas.__init__(
            self,
            parent,
            width=self._width,
            height=self._height,
            bg=parent["bg"],
            bd=0,
            highlightthickness=0,
            takefocus=1,
            cursor="hand2",
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Return>", lambda event: self.invoke())
        self.bind("<space>", lambda event: self.invoke())
        self.bind("<Configure>", lambda event: self._draw())
        self.bind("<FocusIn>", lambda event: self._draw())
        self.bind("<FocusOut>", lambda event: self._draw())
        self._draw()

    # --- 尺寸 ---

    def _measure(self):
        label = (self.icon + " " + self.text).strip() if self.icon else self.text
        return measure_text(self.font, label) + self.theme.px(34)

    def set_text(self, text):
        self.text = text
        # 按新文案重新量宽度：只增不减的话，忙碌态过去后按钮会留着一截空档
        self._width = max(self._min_width, self._measure())
        self.configure(width=self._width)
        self._draw()

    def set_min_width(self, width):
        width = self.theme.px(width)
        if width > self._width:
            self._width = width
            self.configure(width=self._width)
            self._draw()

    # --- 状态 ---

    def set_state(self, state):
        self._state = state
        self._hover = False
        self._pressed = False
        if state == "disabled":
            self.configure(cursor="")
        else:
            self.configure(cursor="hand2")
        self._draw()

    def invoke(self):
        if self._state == "disabled":
            return
        if self.command:
            self.command()

    # --- 事件 ---

    def _on_enter(self, event):
        if self._state == "disabled":
            return
        self._hover = True
        self._draw()

    def _on_leave(self, event):
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, event):
        if self._state == "disabled":
            return
        self._pressed = True
        self.focus_set()
        self._draw()

    def _on_release(self, event):
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and self._state != "disabled":
            self.invoke()

    # --- 绘制 ---

    def _palette(self):
        theme = self.theme
        disabled = self._state == "disabled"

        if self.variant == "primary":
            fill = theme["primary"]
            fg = theme["on_primary"]
            outline = ""
            if self._hover:
                fill = theme.hover("primary")
            if self._pressed:
                fill = theme.pressed("primary")
            if disabled:
                fill = theme["trackbar"]
                fg = theme["ink3"]
        elif self.variant == "ghost":
            fill = ""
            fg = theme["ink2"]
            outline = theme["line"]
            if self._hover:
                fill = theme["track"]
                fg = theme["ink"]
            if disabled:
                fg = theme["ink3"]
                outline = theme["line"]
        elif self.variant == "link":
            fill = ""
            outline = ""
            fg = theme["primary"]
            if self._hover:
                fg = theme.hover("primary")
            if disabled:
                fg = theme["ink3"]
        elif self.variant == "danger":
            fill = theme["danger_c"]
            fg = theme["danger"]
            outline = ""
            if self._hover:
                fill = theme.pressed("danger_c")
            if disabled:
                fg = theme["ink3"]
        else:  # secondary
            fill = theme["track"]
            fg = theme["ink"]
            outline = ""
            if self._hover:
                fill = theme.hover("track")
            if self._pressed:
                fill = theme.pressed("track")
            if disabled:
                fill = theme["surface2"]
                fg = theme["ink3"]

        return fill, fg, outline

    def _draw(self):
        self.delete("all")
        width = self.winfo_width() or self._width
        height = self.winfo_height() or self._height
        fill, fg, outline = self._palette()

        if fill or outline:
            rounded_rect(
                self,
                1,
                1,
                width - 2,
                height - 2,
                self.radius,
                fill=fill if fill else self["bg"],
                outline=outline if outline else (fill if fill else self["bg"]),
                width=1,
            )

        if self.focus_get() is self and self._state != "disabled":
            rounded_rect(
                self,
                1,
                1,
                width - 2,
                height - 2,
                self.radius,
                fill="",
                outline=self.theme["primary_soft"],
                width=1,
            )

        label = (self.icon + " " + self.text).strip() if self.icon else self.text
        self.create_text(
            width / 2,
            height / 2 + 1,
            text=label,
            fill=fg,
            font=self.font,
            anchor="center",
        )


# ---------- 勾选框 / 分段选择 ----------


class CheckBox(tk.Frame):
    """圆角勾选框 + 文案，点击整行都能切换。"""

    DESIGN_SIZE = 18

    def __init__(self, parent, theme, text, variable, command=None, note="", wraplength=None):
        self.theme = theme
        self.variable = variable
        self.command = command
        self.wraplength = wraplength
        self.size = theme.px(self.DESIGN_SIZE)
        tk.Frame.__init__(self, parent, bg=parent["bg"], bd=0, highlightthickness=0)

        self.canvas = tk.Canvas(
            self,
            width=self.size,
            height=self.size,
            bg=parent["bg"],
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.canvas.pack(side="left", pady=(theme.px(1), 0))

        holder = tk.Frame(self, bg=parent["bg"])
        holder.pack(side="left", padx=(theme.px(9), 0))

        self.label = tk.Label(
            holder,
            text=text,
            bg=parent["bg"],
            fg=theme["ink"],
            font=theme.fonts.body,
            anchor="w",
            justify="left",
            cursor="hand2",
        )
        if wraplength:
            self.label.configure(wraplength=theme.px(wraplength))
        self.label.pack(anchor="w")

        self.note_label = None
        if note:
            self.note_label = tk.Label(
                holder,
                text=note,
                bg=parent["bg"],
                fg=theme["ink3"],
                font=theme.fonts.small,
                anchor="w",
                justify="left",
            )
            if wraplength:
                # 缩进对齐上面那行文字，看起来是一组的
                self.note_label.configure(wraplength=theme.px(wraplength + 2))
            self.note_label.pack(anchor="w", pady=(theme.px(1), 0))

        for widget in (self.canvas, self.label):
            widget.bind("<Button-1>", lambda event: self.toggle())
        if self.note_label is not None:
            self.note_label.bind("<Button-1>", lambda event: self.toggle())

        self.canvas.bind("<space>", lambda event: self.toggle())
        self.canvas.configure(takefocus=1)
        self._trace = self.variable.trace_add("write", lambda *args: self._draw())
        self._draw()

    def toggle(self):
        self.variable.set(0 if self.variable.get() else 1)
        if self.command:
            self.command()

    def _draw(self):
        self.canvas.delete("all")
        on = bool(self.variable.get())
        theme = self.theme
        size = self.size
        radius = theme.px(6)
        mid = size / 2
        if on:
            fill = theme["primary"]
            rounded_rect(self.canvas, 1, 1, size - 1, size - 1, radius, fill=fill, outline=fill)
            step = theme.px(3)
            self.canvas.create_line(
                theme.px(5),
                mid,
                theme.px(8),
                mid + step,
                theme.px(13),
                mid - step,
                fill="#FFFFFF",
                width=theme.px(2),
                capstyle="round",
                joinstyle="round",
            )
        else:
            rounded_rect(
                self.canvas,
                1,
                1,
                size - 1,
                size - 1,
                radius,
                fill=theme["surface"],
                outline=theme["trackbar"],
                width=theme.px(1.4),
            )


class Segmented(tk.Canvas):
    """分段选择器：一段灰底里挑一个，比两个单选钮清楚。"""

    def __init__(self, parent, theme, options, variable, command=None, height=34):
        """options: [(显示文案, 值), ...]"""
        self.theme = theme
        self.options = options
        self.variable = variable
        self.command = command
        self._height = theme.px(height)

        self.font = theme.fonts.small_bold
        widths = [measure_text(self.font, text) + theme.px(30) for text, _ in options]
        self._segments = widths
        total = sum(widths) + theme.px(8)

        tk.Canvas.__init__(
            self,
            parent,
            width=total,
            height=self._height,
            bg=parent["bg"],
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", lambda event: self._draw())
        self._trace = self.variable.trace_add("write", lambda *args: self._draw())
        self._draw()

    def _on_click(self, event):
        x = event.x - self.theme.px(4)
        cursor = 0
        for index, width in enumerate(self._segments):
            if cursor <= x <= cursor + width:
                self.variable.set(self.options[index][1])
                if self.command:
                    self.command()
                return
            cursor += width

    def _draw(self):
        self.delete("all")
        theme = self.theme
        inset = theme.px(4)
        width = self.winfo_width() or (sum(self._segments) + theme.px(8))
        height = self.winfo_height() or self._height
        current = self.variable.get()

        rounded_rect(
            self,
            0,
            0,
            width - 1,
            height - 1,
            (height - 2) / 2,
            fill=theme["track"],
            outline=theme["track"],
        )

        cursor = inset
        for index, (text, value) in enumerate(self.options):
            seg_width = self._segments[index]
            selected = value == current
            if selected:
                rounded_rect(
                    self,
                    cursor,
                    inset,
                    cursor + seg_width,
                    height - inset,
                    (height - inset * 2) / 2,
                    fill=theme["surface"],
                    outline=theme["line"],
                )
            self.create_text(
                cursor + seg_width / 2,
                height / 2,
                text=text,
                fill=theme["ink"] if selected else theme["ink2"],
                font=self.font,
            )
            cursor += seg_width


# ---------- 进度条 / 胶囊 ----------


class ProgressBar(tk.Canvas):
    """细长的进度条，生成时给个「在跑」的感觉。"""

    def __init__(self, parent, theme, width=150, height=7):
        self.theme = theme
        width = theme.px(width)
        height = theme.px(height)
        tk.Canvas.__init__(
            self,
            parent,
            width=width,
            height=height,
            bg=parent["bg"],
            bd=0,
            highlightthickness=0,
        )
        self._value = 0
        self._width = width
        self._height = height
        self.bind("<Configure>", lambda event: self._draw())
        self._draw()

    def set(self, value):
        self._value = max(0, min(1.0, float(value)))
        self._draw()

    def _draw(self):
        self.delete("all")
        width = self.winfo_width() or self._width
        height = self.winfo_height() or self._height
        radius = height / 2
        rounded_rect(self, 0, 0, width, height, radius, fill=self.theme["trackbar"], outline="")
        filled = int(width * self._value)
        if filled > height:
            rounded_rect(
                self, 0, 0, filled, height, radius, fill=self.theme["primary"], outline=""
            )
        elif filled > 0:
            rounded_rect(
                self, 0, 0, max(height, filled), height, radius,
                fill=self.theme["primary"], outline="",
            )


class Pill(tk.Canvas):
    """状态胶囊：一个小圆点 + 一句话。"""

    def __init__(self, parent, theme, text="", kind="idle", font=None):
        self.theme = theme
        self.text = text
        self.kind = kind
        self.font = font or theme.fonts.small_bold
        self._height = theme.px(28)
        width = self._measure()
        tk.Canvas.__init__(
            self,
            parent,
            width=width,
            height=self._height,
            bg=parent["bg"],
            bd=0,
            highlightthickness=0,
        )
        self.bind("<Configure>", lambda event: self._draw())
        self._draw()

    def _colors(self):
        table = {
            "ok": (self.theme["pcont"], self.theme["pon"], self.theme["primary"]),
            "warn": (self.theme["amber_c"], self.theme["amber"], self.theme["amber"]),
            "bad": (self.theme["danger_c"], self.theme["danger"], self.theme["danger"]),
            "idle": (self.theme["track"], self.theme["ink2"], self.theme["ink3"]),
        }
        return table.get(self.kind, table["idle"])

    def _measure(self):
        return measure_text(self.font, self.text) + self.theme.px(36)

    def set(self, text, kind="idle"):
        self.text = text
        self.kind = kind
        self.configure(width=self._measure())
        self._draw()

    def _draw(self):
        self.delete("all")
        theme = self.theme
        width = self.winfo_width() or self._measure()
        height = self.winfo_height() or self._height
        background, foreground, dot = self._colors()
        rounded_rect(
            self, 0, 0, width - 1, height - 1, (height - 2) / 2,
            fill=background, outline=background,
        )
        radius = theme.px(3.5)
        dot_x = theme.px(12)
        center_y = height / 2
        self.create_oval(
            dot_x, center_y - radius, dot_x + radius * 2, center_y + radius,
            fill=dot, outline=dot,
        )
        self.create_text(
            dot_x + radius * 2 + theme.px(7),
            center_y,
            text=self.text,
            fill=foreground,
            font=self.font,
            anchor="w",
        )


# ---------- 表单零件 ----------


def make_entry(parent, theme, textvariable, width=20, font=None):
    """统一样式的输入框（tkinter 原生 Entry，只能改颜色）。"""
    entry = tk.Entry(
        parent,
        textvariable=textvariable,
        width=width,
        bg=theme["track"],
        fg=theme["ink"],
        insertbackground=theme["primary"],
        disabledbackground=theme["track"],
        disabledforeground=theme["ink3"],
        relief="flat",
        bd=0,
        font=font or theme.fonts.body,
        highlightthickness=1,
        highlightbackground=theme["line"],
        highlightcolor=theme["primary_soft"],
    )
    return entry


def make_combo(parent, theme, variable, values, width=14, font=None):
    """统一样式的下拉框（ttk 样式需要 style，外面用 style_combobox 注册过）。"""
    combo = ttk.Combobox(
        parent,
        textvariable=variable,
        values=values,
        width=width,
        font=font or theme.fonts.body,
        state="readonly",
        style="Card.TCombobox",
    )
    return combo


def style_combobox(root, theme):
    """把 Combobox 的下拉列表也刷成卡片色，否则会露出系统灰。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(
        "Card.TCombobox",
        fieldbackground=theme["track"],
        background=theme["track"],
        foreground=theme["ink"],
        arrowcolor=theme["ink2"],
        bordercolor=theme["line"],
        lightcolor=theme["track"],
        darkcolor=theme["track"],
        padding=(theme.px(9), theme.px(5)),
        relief="flat",
    )
    style.map(
        "Card.TCombobox",
        fieldbackground=[("readonly", theme["track"])],
        foreground=[("readonly", theme["ink"])],
        bordercolor=[("focus", theme["primary_soft"])],
        arrowcolor=[("active", theme["primary"])],
    )
    root.option_add("*TCombobox*Listbox.background", theme["surface"])
    root.option_add("*TCombobox*Listbox.foreground", theme["ink"])
    root.option_add("*TCombobox*Listbox.selectBackground", theme["pcont"])
    root.option_add("*TCombobox*Listbox.selectForeground", theme["pon"])
    root.option_add("*TCombobox*Listbox.font", theme.fonts.body)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    style.configure(
        "Card.Vertical.TScrollbar",
        background=theme["trackbar"],
        troughcolor=theme["bg"],
        bordercolor=theme["bg"],
        arrowcolor=theme["ink2"],
        relief="flat",
    )
    style.map(
        "Card.Vertical.TScrollbar",
        background=[("active", theme["primary_soft"])],
    )
    return style


def small_label(parent, theme, text, kind="body"):
    colors = {
        "body": (theme["ink"], theme.fonts.body),
        "dim": (theme["ink2"], theme.fonts.small),
        "muted": (theme["ink3"], theme.fonts.small),
        "strong": (theme["ink"], theme.fonts.body_bold),
        "primary": (theme["primary"], theme.fonts.small_bold),
        "amber": (theme["amber"], theme.fonts.small),
        "danger": (theme["danger"], theme.fonts.small),
    }
    fg, font = colors.get(kind, colors["body"])
    return tk.Label(
        parent, text=text, bg=parent["bg"], fg=fg, font=font, anchor="w", justify="left"
    )
