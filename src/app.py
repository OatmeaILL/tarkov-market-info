# -*- coding: utf-8 -*-
"""程序启动流程的接线层。

    建Tk 根窗口
        ↓
    资源检测（缺库全量 / 缺图标补图标）
        ↓
    查价主窗口（home.HomeWindow）
        ↓点「打开排行报表」
    报表窗口（main.MarketApp挂成 Toplevel）

数据更新统一在这里管（原报表窗口里那套同步代码已移除）：
    启动时缺什么补什么
    之后要改模式 / 重下数据，走主窗口的「数据与设置」
"""

import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime

import data
import home
import main
import price
import sync
import theme as theme_module
import widgets


class BootChecker:
    """启动资源检测。判断缺什么，然后后台去补。

    触发条件（缺了才下，不多下）：
        库不存在 / 库损坏      → 全量数据
        图标目录空/ 没webp     → 图标
    都在就不联网，启动直接可用。
    """

    def __init__(self, data_dir, theme, status_widget=None, progress_widget=None):
        self.data_dir = data_dir
        self.theme = theme
        self.status_widget = status_widget
        self.progress_widget = progress_widget
        self.cancel_flag = [False]

    @staticmethod
    def icon_dir_has_icons(icon_dir):
        try:
            return os.path.isdir(icon_dir) and any(
                name.endswith(".webp") for name in os.listdir(icon_dir)
            )
        except OSError:
            return False

    def detect(self):
        """返回 (需要全量数据?, 需要图标?, 人类可读的原因)。"""
        db_path = data.find_default_db()
        icon_dir = data.icon_root()

        need_data = False
        reason = ""
        if not db_path:
            need_data = True
            reason = "没有本地物品数据"
        else:
            summary = data.load_db_summary(db_path)
            if not summary or not summary.get("total"):
                need_data = True
                reason = "本地数据是空的"

        need_icons = not self.icon_dir_has_icons(icon_dir)
        if not need_data and need_icons:
            reason = "没有物品图标"

        return need_data, need_icons, reason

    def set_status(self, text):
        if self.status_widget is not None:
            try:
                self.status_widget.configure(text=text)
            except tk.TclError:
                pass

    def set_progress(self, value):
        if self.progress_widget is not None:
            try:
                self.progress_widget.set(value)
            except tk.TclError:
                pass

    def run_async(self, mode_label, on_done, with_icons=True):
        """后台补数据。完成时回调 on_done(success, message)。

        进度回调直接把 phase 映射到一条进度条上（数据 + 图标各占一段）。
        """
        self.cancel_flag[0] = False
        self.set_progress(0)

        def progress(phase, text, value):
            self.set_progress(value)
            self.set_status(text)

        def worker():
            ok = False
            message = ""
            try:
                result = sync.sync_all(
                    sync.mode_slug(mode_label),
                    with_icons=with_icons,
                    progress_cb=progress,
                    cancel_flag=self.cancel_flag,
                )
                ok = bool(result and result.get("ok"))
                message = (result or {}).get("message", "")
            except Exception as exc:  # 断网 / 磁盘满 / 权限等，一律降级不崩
                message = "更新失败：" + str(exc)
            on_done(ok, message)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread

    def cancel(self):
        self.cancel_flag[0] = True


class SettingsWindow:
    """数据与设置。

    数据更新从报表窗口挪到这里统一管理：模式选择、立即更新、数据位置、进度。
    """

    def __init__(self, parent, theme, data_dir, on_data_ready):
        self.data_dir = data_dir
        self.theme = theme
        self.colors = theme.colors
        self.on_data_ready = on_data_ready

        self.mode_var = tk.StringVar(value=self._current_mode())
        self.status_var = tk.StringVar(value="")
        self.db_path_var = tk.StringVar(value=data.find_default_db() or "")
        self.icon_dir_var = tk.StringVar(value=data.icon_root())

        self.window = tk.Toplevel(parent)
        self.window.title("数据与设置")
        self.window.configure(bg=self.colors["page"])
        self.window.transient(parent)
        self.window.minsize(theme.px(520), theme.px(420))

        self.checker = BootChecker(data_dir, theme)
        self.busy = False

        self.build_ui()
        self.place_window(parent)

    def _current_mode(self):
        try:
            import json

            with open(data.config_path(), "r", encoding="utf-8") as handle:
                return json.load(handle).get("game_mode", "PVE")
        except (OSError, ValueError):
            return "PVE"

    def _save_mode(self, mode):
        try:
            import json

            path = data.config_path()
            data.ensure_dirs()
            config = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    config = json.load(handle)
            config["game_mode"] = mode
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(config, handle, ensure_ascii=False, indent=2)
        except (OSError, ValueError):
            pass

    def build_ui(self):
        theme = self.theme
        colors = self.colors
        window = self.window

        window.grid_rowconfigure(1, weight=1)
        window.grid_columnconfigure(0, weight=1)

        head = tk.Frame(window, bg=colors["page"])
        head.grid(row=0, column=0, sticky="ew", padx=theme.px(20), pady=(theme.px(18), theme.px(4)))
        # place_window 要量它的高度，别只当局部变量
        self.header = head
        tk.Label(
            head, text="数据与设置", bg=colors["page"], fg=colors["ink"],
            font=theme.fonts.title, anchor="w",
        ).pack(anchor="w")
        tk.Label(
            head, text="物品数据和图标都在程序目录，换电脑时整个文件夹一起拷走",
            bg=colors["page"], fg=colors["ink3"], font=theme.fonts.small, anchor="w",
        ).pack(anchor="w", pady=(theme.px(3), 0))

        scroll = widgets.ScrollArea(window, theme, padding=(20, 12, 20, 20))
        scroll.grid(row=1, column=0, sticky="nsew")
        # 存成实例属性：place_window 还要用它量内容高度
        self.scroll = scroll
        body = scroll.content
        # place_window 要按卡片逐张算高度，body 得留成实例属性
        self.body = body

        # --- 数据来源 ---
        source_card = widgets.RoundCard(
            body, theme, padding=(16, 14, 16, 14), radius=14,
            title="数据来源", subtitle="切换游戏模式后需要重新更新数据",
        )
        source_card.pack(fill="x")
        inner = source_card.body

        mode_row = tk.Frame(inner, bg=colors["surface"])
        mode_row.pack(fill="x")
        tk.Label(
            mode_row, text="游戏模式", bg=colors["surface"], fg=colors["ink2"],
            font=theme.fonts.body, anchor="w",
        ).pack(side="left")
        mode_picker = widgets.Segmented(
            mode_row, theme,
            [(label, label) for label, _ in sync.GAME_MODES],
            self.mode_var,
            command=self._on_mode_change, height=30,
        )
        mode_picker.pack(side="right")

        # --- 本地数据位置 ---
        path_card = widgets.RoundCard(
            body, theme, padding=(16, 14, 16, 14), radius=14,
            title="本地数据", subtitle="程序自己维护，一般不用改",
        )
        path_card.pack(fill="x", pady=(theme.px(12), 0))
        pinner = path_card.body

        self._path_row(pinner, "物品数据库", self.db_path_var, self._pick_db)
        self._path_row(pinner, "图标目录", self.icon_dir_var, self._pick_icon)

        size_label = tk.Label(
            pinner, text="", bg=colors["surface"], fg=colors["ink3"],
            font=theme.fonts.tiny, anchor="w", justify="left",
        )
        size_label.pack(fill="x", pady=(theme.px(8), 0))
        self.size_label = size_label
        self._refresh_sizes()

        # --- 更新 ---
        update_card = widgets.RoundCard(
            body, theme, padding=(16, 14, 16, 14), radius=14,
            title="更新数据", subtitle="物品索引与图标会全量覆盖更新",
        )
        update_card.pack(fill="x", pady=(theme.px(12), 0))
        uinner = update_card.body

        progress_row = tk.Frame(uinner, bg=colors["surface"])
        progress_row.pack(fill="x")
        self.progress = widgets.ProgressBar(progress_row, theme, width=200, height=7)
        self.progress.pack(side="left")
        tk.Label(
            progress_row, textvariable=self.status_var, bg=colors["surface"],
            fg=colors["ink2"], font=theme.fonts.small, anchor="w",
        ).pack(side="left", padx=(theme.px(10), 0))

        buttons = tk.Frame(uinner, bg=colors["surface"])
        buttons.pack(fill="x", pady=(theme.px(12), 0))
        self.update_button = widgets.Button(
            buttons, theme, "立即更新", command=self.on_update,
            variant="primary", min_width=110, height=36,
        )
        self.update_button.pack(side="left")
        self.cancel_button = widgets.Button(
            buttons, theme, "取消", command=self.on_cancel,
            variant="secondary", min_width=80, height=36,
            font=theme.fonts.body,
        )
        # 平时不占位，只在真的在跑的时候才出现
        self.cancel_button.pack_forget()
        self.cancel_slot = buttons

        # --- 关于 ---
        about_card = widgets.RoundCard(
            body, theme, padding=(16, 14, 16, 14), radius=14,
            title="关于", subtitle="开源地址与作者",
        )
        about_card.pack(fill="x", pady=(theme.px(12), 0))
        ainner = about_card.body

        about_row = tk.Frame(ainner, bg=colors["surface"])
        about_row.pack(fill="x")
        tk.Label(
            about_row, text="TarkovMarketInfo  v" + main.APP_VERSION,
            bg=colors["surface"], fg=colors["ink"],
            font=theme.fonts.body, anchor="w",
        ).pack(side="left")
        tk.Label(
            about_row, text="作者 " + main.AUTHOR,
            bg=colors["surface"], fg=colors["ink3"],
            font=theme.fonts.small, anchor="e",
        ).pack(side="right")

        # 链接用 Label + 手型光标 + 点击打开浏览器。
        # 不用 Button：链接长得像按钮在设置页里太抢眼。
        link = tk.Label(
            ainner, text=main.GITHUB_URL,
            bg=colors["surface"], fg=colors["primary"],
            font=theme.fonts.small, anchor="w", cursor="hand2",
        )
        link.pack(fill="x", pady=(theme.px(6), 0))
        link.bind("<Button-1>", lambda event: self._open_github())

        tk.Label(
            ainner,
            text="数据与图标来自 tarkov.dev 的公开接口，"
                 "本工具只做查询展示，与 Battlestate Games 无关。",
            bg=colors["surface"], fg=colors["ink3"],
            font=theme.fonts.tiny, anchor="w", justify="left",
            wraplength=theme.px(320),
        ).pack(fill="x", pady=(theme.px(8), 0))

    def _open_github(self):
        """打开项目主页。打不开只提示，不弹错误框打断。"""
        try:
            webbrowser.open(main.GITHUB_URL)
        except Exception:
            self.status_var.set("打不开浏览器，地址：" + main.GITHUB_URL)

    def _path_row(self, parent, caption, variable, command):
        theme = self.theme
        colors = self.colors
        row = tk.Frame(parent, bg=colors["surface"])
        row.pack(fill="x", pady=(theme.px(4), 0))
        tk.Label(
            row, text=caption, bg=colors["surface"], fg=colors["ink2"],
            font=theme.fonts.small, anchor="w",
        ).pack(side="left")
        widgets.Button(
            row, theme, "选择", command=command, variant="secondary",
            min_width=64, height=28,
        ).pack(side="right")
        entry = widgets.make_entry(row, theme, variable, width=30)
        entry.pack(side="right", fill="x", expand=True, padx=(theme.px(8), theme.px(8)))
        # 路径通常很长，聚焦时把光标推到末尾，才看得到文件名而不是开头
        entry.bind("<FocusIn>", lambda event: entry.icursor("end"))
        row._entry = entry

    def _refresh_sizes(self):
        """显示本地数据占用，让用户知道文件夹要多大。"""
        parts = []
        db_path = self.db_path_var.get().strip()
        if db_path and os.path.exists(db_path):
            parts.append("数据库 %.1f MB" % (os.path.getsize(db_path) / 1024 / 1024))
        icon_dir = self.icon_dir_var.get().strip()
        if icon_dir and os.path.isdir(icon_dir):
            count = 0
            total = 0
            try:
                for name in os.listdir(icon_dir):
                    if name.endswith(".webp"):
                        count += 1
                        total += os.path.getsize(os.path.join(icon_dir, name))
            except OSError:
                pass
            if count:
                parts.append("图标 %d 张 / %.1f MB" % (count, total / 1024 / 1024))
        self.size_label.configure(text="　".join(parts) if parts else "还没有本地数据")

    def _pick_db(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="选择 tarkov.db", initialdir=self.data_dir,
            filetypes=[("数据库", "*.db"), ("所有文件", "*.*")],
        )
        if path:
            self.db_path_var.set(path)
            self._refresh_sizes()

    def _pick_icon(self):
        from tkinter import filedialog

        path = filedialog.askdirectory(
            title="选择图标目录", initialdir=data.app_dir()
        )
        if path:
            self.icon_dir_var.set(path)
            self._refresh_sizes()

    def _on_mode_change(self, value=None):
        mode = self.mode_var.get()
        self._save_mode(mode)
        self.status_var.set("模式已切到 %s，点「立即更新」拉取新数据" % mode)

    def on_update(self):
        if self.busy:
            return
        self.busy = True
        self.update_button.set_state("disabled")
        self.cancel_button.pack(side="left", padx=(self.theme.px(8), 0))
        self.status_var.set("开始更新 ...")
        self.checker.progress_widget = self.progress

        mode = self.mode_var.get()
        self.checker.run_async(mode, self._on_done, with_icons=True)

    def on_cancel(self):
        self.checker.cancel()
        self.status_var.set("正在取消 ...")

    def _on_done(self, ok, message):
        """后台线程回调 —— 必须切回主线程才能碰界面。"""
        self.window.after(0, lambda: self._finish(ok, message))

    def _finish(self, ok, message):
        self.busy = False
        self.update_button.set_state("normal")
        self.cancel_button.pack_forget()
        if ok:
            self.status_var.set("更新完成 " + datetime.now().strftime("%H:%M:%S"))
        else:
            self.status_var.set(message or "更新失败")
        self._refresh_sizes()
        if ok:
            self.on_data_ready()

    def place_window(self, parent):
        # 路径那一列要放得下完整路径，否则只剩前缀看不出是哪个文件
        width = max(self.theme.px(620), 620)
        # 先给一个初值再建布局：ScrollArea 的 canvas 是按父容器高度算的，
        # 不先摆一个尺寸，量出来的 reqheight 会被父容器的默认值污染。
        self.window.geometry("%dx%d" % (width, 520))
        self.window.update_idletasks()
        self.scroll.refresh()

        # ScrollArea 的 content / inner 都会被 grid 拉伸到"当前可视高度"，
        # 量它们的 reqheight 等于量窗口现在多高，不是内容多高。
        # 只有每张卡片自己的 reqheight 才是它真实要占的位置，逐张加起来才是内容高度。
        content_height = 0
        for card in self.body.winfo_children():
            card.update_idletasks()
            content_height += card.winfo_reqheight()
        content_height += self.scroll.padding[1] + self.scroll.padding[3]
        # 卡片之间还有 pady 间距
        content_height += self.theme.px(12) * max(0, len(self.body.winfo_children()) - 1)
        header_height = self.header.winfo_reqheight() + self.theme.px(28)
        wanted_height = content_height + header_height

        area_height = self.window.winfo_screenheight()
        height = min(wanted_height, int(area_height * 0.86))
        height = max(height, self.theme.px(460))

        try:
            parent.update_idletasks()
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        except tk.TclError:
            x = y = 200
        self.window.geometry("%dx%d+%d+%d" % (width, height, x, y))
        self.window.update_idletasks()

        # 建窗口时卡片还没映射，reqheight 量不准（会把窗口撑到"最大"那档）。
        # 窗口显形后再量一次，那时才知道内容真实多高。
        self.window.after(60, self._refit_height)

    def _refit_height(self):
        """窗口显形后按真实卡片高度收一次口。"""
        if not self.body.winfo_children():
            return
        self.body.update_idletasks()
        total = 0
        for card in self.body.winfo_children():
            card.update_idletasks()
            total += card.winfo_reqheight()
        total += self.scroll.padding[1] + self.scroll.padding[3]
        total += self.theme.px(12) * max(0, len(self.body.winfo_children()) - 1)
        total += self.header.winfo_reqheight() + self.theme.px(28)

        area_height = self.window.winfo_screenheight()
        height = min(total, int(area_height * 0.86))
        height = max(height, self.theme.px(460))
        current = self.window.winfo_height()
        # 只在差得明显时调，避免反复触发布局抖动
        if abs(current - height) > 12:
            self.window.geometry("%dx%d" % (self.window.winfo_width(), height))


class AppShell:
    """整个程序的外壳：持有根窗口、管报表窗口的开关、管资源检测。"""

    def __init__(self, root, force_dark=None, force_scale=None):
        self.root = root
        self.force_dark = force_dark
        self.force_scale = force_scale
        self.app_dir = data.app_dir()
        self.data_dir = data.data_dir()
        # data\ 和 reports\ 先建出来：只拷 exe 到新机器时第一次跑也不会因为目录不存在而失败
        data.ensure_dirs()

        self.report_window = None
        self.report_app = None
        self.settings_window = None

        # 历史价格缓存表（曲线用），失败不影响主流程
        price.init_history_db(self.data_dir)

        if self.force_scale is None:
            scale = theme_module.detect_scale(root)
        else:
            scale = float(self.force_scale)
        self.theme = theme_module.Theme(dark=bool(force_dark), scale=scale)
        widgets.style_combobox(root, self.theme)

        # Tkinter 默认把回调异常打到 stderr，窗口程序看不到 —— 挂上去落error.log
        root.report_callback_exception = self._on_callback_error

        # 主窗口先建好：它一出现用户就有东西看，同步在后面跑
        self.home = home.HomeWindow(
            root, self.theme,
            open_report=self.open_report,
            open_settings=self.open_settings,
            app_dir=self.app_dir,
        )

        # 资源检测等主窗口显形后再做，免得进度抢在空白窗口前面
        root.after(400, self.check_resources)

    def _on_callback_error(self, exc_type, exc_value, exc_tb):
        import traceback

        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            main.write_error_log(detail)
        except Exception:
            pass

    # ---------- 资源检测 ----------

    def check_resources(self):
        """启动时缺什么补什么。都在就不联网，直接可用。"""
        checker = BootChecker(self.data_dir, self.theme)
        need_data, need_icons, reason = checker.detect()
        if not need_data and not need_icons:
            return

        # 有资源缺口才弹进度提示，且不阻塞界面
        self._open_boot_progress(reason)
        checker.progress_widget = self.boot_progress
        checker.status_widget = self.boot_status
        checker.run_async(
            "PVE", self._on_boot_done, with_icons=need_icons or not need_data
        )

    def _open_boot_progress(self, reason):
        colors = self.theme.colors
        top = tk.Toplevel(self.root)
        top.title("准备数据")
        top.configure(bg=colors["page"])
        top.transient(self.root)
        # 不给关闭按钮：这一步很短，关掉反而留半份数据
        top.resizable(False, False)

        frame = tk.Frame(top, bg=colors["surface"], padx=28, pady=22)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame, text="首次使用，正在准备物品数据",
            bg=colors["surface"], fg=colors["ink"],
            font=self.theme.fonts.heading,
        ).pack(anchor="w")
        self.boot_status = tk.Label(
            frame, text=reason + "，正在下载（首次约 18 秒）",
            bg=colors["surface"], fg=colors["ink3"],
            font=self.theme.fonts.small, anchor="w",
        )
        self.boot_status.pack(anchor="w", pady=(6, 12))
        self.boot_progress = widgets.ProgressBar(frame, self.theme, width=340, height=8)
        self.boot_progress.pack(fill="x")

        self.boot_window = top
        try:
            top.grab_set()
        except tk.TclError:
            pass

    def _on_boot_done(self, ok, message):
        self.root.after(0, lambda: self._finish_boot(ok, message))

    def _finish_boot(self, ok, message):
        window = getattr(self, "boot_window", None)
        if window is not None:
            try:
                window.grab_release()
                window.destroy()
            except tk.TclError:
                pass
            self.boot_window = None

        if ok:
            self.home.refresh_data()
            self.home.set_state("数据就绪", "ok")
        else:
            # 网络失败也要能开出一个可用的界面，只是明确说没数据
            self.home.set_state("数据没下下来：%s" % (message or "网络不通"), "bad")
            self.home.status_var.set("本地无数据，请到「数据与设置」重试")

    # ---------- 窗口切换 ----------

    def open_report(self):
        """打开排行报表窗口。已开着就提到最前，不重复建。"""
        if self.report_window is not None and self.report_window.winfo_exists():
            self.report_window.deiconify()
            self.report_window.lift()
            self.report_window.focus_force()
            return

        top = tk.Toplevel(self.root)
        top.transient(self.root)
        # 报表窗口自己管关闭：关掉只销毁这个窗口，主窗口留着
        self.report_window = top
        self.report_app = main.MarketApp(
            top, force_dark=self.force_dark, force_scale=self.force_scale,
        )
        # 报表窗口不再管数据同步 —— 统一在主窗口的「数据与设置」里做
        self.report_app.sync_enabled = False

    def open_settings(self):
        if self.settings_window is not None:
            try:
                if self.settings_window.window.winfo_exists():
                    self.settings_window.window.lift()
                    return
            except tk.TclError:
                pass
        self.settings_window = SettingsWindow(
            self.root, self.theme, self.data_dir, self.home.refresh_data,
        )

    def run(self):
        self.root.mainloop()