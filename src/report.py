# -*- coding: utf-8 -*-
"""把检索结果渲染成 HTML 报告 / CSV 表格。

HTML 是单文件产物：物品图标读成 base64 内联进去，离线也能看，方便转长图。
"""

import base64
import csv
import html
import os

from data import item_category, liquidity_level, sort_label


def escape(text):
    """物品名里有 & 和引号（比如 B&T、P1X42 "WEAVER"），不转义会把 HTML 结构搞坏。"""
    return html.escape(str(text), quote=True)

CSS = """
:root {
  --bg: #0b0d09;
  --bg-card: #14170f;
  --bg-row: #171b12;
  --bg-row-hover: #1e2317;
  --gold: #c7a252;
  --gold-bright: #e3c274;
  --text: #d9d6cb;
  --text-dim: #8d8b80;
  --border: rgba(199, 162, 82, 0.22);
  --good: #6f9e4a;
  --mid: #c7a252;
  --bad: #b04b3c;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.5;
  padding: 32px 24px 64px;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1080px; margin: 0 auto; }

header { border-bottom: 1px solid var(--border); padding-bottom: 20px; margin-bottom: 24px; }
h1 {
  font-size: 26px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--gold-bright);
}
h1 .accent { color: var(--text-dim); font-weight: 400; letter-spacing: 0.02em; font-size: 16px; }
.sub { color: var(--text-dim); font-size: 13px; margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px 18px; }
.sub b { color: var(--text); font-weight: 500; }

.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 28px; }
.stat { background: var(--bg-card); border: 1px solid var(--border); border-radius: 3px; padding: 14px 16px; }
.stat .label { font-size: 12px; color: var(--text-dim); letter-spacing: 0.04em; }
.stat .value { font-size: 22px; font-weight: 600; color: var(--gold-bright); margin-top: 4px; font-variant-numeric: tabular-nums; }
.stat .value small { font-size: 13px; color: var(--text-dim); font-weight: 400; }

.list-head {
  display: grid;
  grid-template-columns: 44px 68px 1fr 168px 118px 96px;
  gap: 12px;
  padding: 0 16px 8px;
  font-size: 12px;
  color: var(--text-dim);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border-bottom: 1px solid var(--border);
}
.row {
  display: grid;
  grid-template-columns: 44px 68px 1fr 168px 118px 96px;
  gap: 12px;
  align-items: center;
  padding: 10px 16px;
  background: var(--bg-row);
  border-bottom: 1px solid rgba(199, 162, 82, 0.09);
  transition: background 0.12s;
}
.row:hover { background: var(--bg-row-hover); }
.rows .row:nth-child(even) { background: #12150e; }
.rows .row:nth-child(even):hover { background: var(--bg-row-hover); }

.rank { font-size: 17px; font-weight: 600; color: var(--text-dim); font-variant-numeric: tabular-nums; text-align: center; }
.rank.top1 { color: #e3c274; }
.rank.top2 { color: #cbc8bd; }
.rank.top3 { color: #b98b5e; }

.icon { width: 68px; height: 44px; display: flex; align-items: center; justify-content: center; }
.icon img { max-width: 100%; max-height: 44px; object-fit: contain; }

.names { min-width: 0; }
.names .zh { font-size: 14px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.names .en { font-size: 12px; color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.price { text-align: right; font-variant-numeric: tabular-nums; }
.price .avg { font-size: 15px; font-weight: 600; color: var(--gold-bright); }
.price .range { font-size: 11px; color: var(--text-dim); }

.spread { text-align: right; font-variant-numeric: tabular-nums; font-size: 12px; color: var(--text-dim); }
.spread b { color: var(--text); font-weight: 500; }
.spread .dim { color: #6f6d64; }

.offers { text-align: right; }
.tag {
  display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 2px;
  border: 1px solid currentColor; letter-spacing: 0.02em; white-space: nowrap;
}
.tag.good { color: var(--good); }
.tag.mid { color: var(--mid); }
.tag.bad { color: var(--bad); }
.offers .num { display: block; font-size: 12px; color: var(--text-dim); margin-top: 3px; font-variant-numeric: tabular-nums; }

footer { margin-top: 32px; padding-top: 18px; border-top: 1px solid var(--border); color: var(--text-dim); font-size: 12px; line-height: 1.9; }
footer b { color: var(--text); font-weight: 500; }

@media (max-width: 900px) {
  .list-head { display: none; }
  .row { grid-template-columns: 36px 60px 1fr 110px; }
  .spread, .offers { display: none; }
}

/* ---- 48h 涨跌榜浮窗：可拖动、可关闭 ---- */
[hidden] { display: none !important; }
.movers {
  position: fixed; right: 18px; bottom: 18px; width: 432px; z-index: 50;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 4px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, .55); font-size: 12px;
}
.movers-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 10px; cursor: move; user-select: none;
  border-bottom: 1px solid var(--border); color: var(--gold-bright);
  letter-spacing: .06em;
}
.movers-close {
  background: none; border: 0; color: var(--text-dim); font-size: 16px;
  line-height: 1; cursor: pointer; padding: 0 2px;
}
.movers-close:hover { color: var(--bad); }
.movers-body {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px; padding: 8px 10px 10px;
}
.mv-label { font-size: 11px; letter-spacing: .06em; margin-bottom: 4px; }
.mv-label.up { color: var(--good); }
.mv-label.down { color: var(--bad); }
.mv-list { list-style: none; margin: 0; padding: 0; max-height: 300px; overflow: auto; }
.mv-list li {
  display: grid; grid-template-columns: 14px 26px 1fr auto; gap: 5px;
  align-items: center; padding: 3px 0;
  border-bottom: 1px solid rgba(199, 162, 82, .08);
}
.mv-rank { color: var(--text-dim); text-align: right; font-variant-numeric: tabular-nums; }
.mv-list img { width: 26px; height: 18px; object-fit: contain; }
.mv-noimg { width: 26px; height: 18px; }
.mv-name { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mv-pct { font-variant-numeric: tabular-nums; }
.mv-pct.up { color: var(--good); }
.mv-pct.down { color: var(--bad); }
.movers-reopen {
  position: fixed; right: 18px; bottom: 18px; z-index: 50; cursor: pointer;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 4px;
  color: var(--gold-bright); padding: 6px 12px; font-size: 12px;
  letter-spacing: .04em;
}
.movers-reopen:hover { border-color: var(--gold); }

/* ---- 按物品类型切换 ---- */
.type-bar { display: flex; align-items: center; gap: 10px; margin: 20px 0 10px; }
.type-bar-label { color: var(--text-dim); font-size: 12px; letter-spacing: .06em; }
.type-bar select {
  background: var(--bg-card); color: var(--text);
  border: 1px solid var(--border); border-radius: 3px;
  padding: 6px 10px; font-size: 13px; min-width: 220px;
}
.type-bar select:focus { outline: none; border-color: var(--gold); }
/* 窄屏不隐藏、改成压扁显示：直接 display:none 等于把功能入口砍掉了 */
@media (max-width: 900px) {
  .movers { left: 8px; right: 8px; bottom: 8px; width: auto; }
  .mv-list { max-height: 132px; }
}
"""


def read_icon_data_uri(icon_dir, item_id):
    """把物品图标读成 base64 data URI，读不到就返回空串。"""
    if not icon_dir:
        return ""
    # 图标目录以 webp 为主，但也可能混进 png / jpg，都认一下
    for suffix, mime in ((".webp", "webp"), (".png", "png"), (".jpg", "jpeg")):
        path = os.path.join(icon_dir, item_id + suffix)
        if not os.path.exists(path):
            continue
        handle = open(path, "rb")
        raw = handle.read()
        handle.close()
        return "data:image/" + mime + ";base64," + base64.b64encode(raw).decode("ascii")
    return ""


def format_money(value):
    if value is None:
        return "0"
    return format(int(value), ",")


def build_report_title(sort_field, descending, count):
    """根据排序口径拼出报告标题。"""
    if sort_field == "avg24h":
        core = "最贵物品" if descending else "最便宜物品"
    else:
        core = "按「" + sort_label(sort_field) + "」排序"
    direction = "降序" if descending else "升序"
    return core + " TOP " + str(count) + " <span class=\"accent\">/ 跳蚤市场 · " + direction + "</span>"


def build_rows_html(items, sort_field, icon_dir):
    """生成所有物品行的 HTML 片段。"""
    parts = []
    rank = 0
    for item in items:
        rank = rank + 1
        rank_class = ""
        if rank == 1:
            rank_class = " top1"
        elif rank == 2:
            rank_class = " top2"
        elif rank == 3:
            rank_class = " top3"

        data_uri = read_icon_data_uri(icon_dir, item["id"])
        if data_uri:
            image_html = '<img src="' + data_uri + '" alt="' + escape(item["name_zh"]) + '">'
        else:
            image_html = '<span style="color:#555">无图</span>'

        low_text = format_money(item["low24h"]) if item["low24h"] > 0 else "—"
        high_text = format_money(item["high24h"]) if item["high24h"] > 0 else "—"

        size_html = ""
        if item["w"] and item["h"]:
            size_html = '<br><span class="dim">' + str(item["w"]) + "×" + str(item["h"]) + " 格</span>"

        tag_text, tag_class = liquidity_level(item["offer_count"])

        row_html = (
            '<div class="row">'
            '<div class="rank' + rank_class + '">' + str(rank) + "</div>"
            '<div class="icon">' + image_html + "</div>"
            '<div class="names"><div class="zh">' + escape(item["name_zh"]) + "</div>"
            '<div class="en">' + escape(item["name_en"]) + "</div></div>"
            '<div class="price"><div class="avg">₽ ' + format_money(item[sort_field]) + "</div>"
            '<div class="range">区间 ' + low_text + " ~ " + high_text + "</div></div>"
            '<div class="spread"><b>' + escape(item["short_name"]) + "</b>" + size_html + "</div>"
            '<div class="offers"><span class="tag ' + tag_class + '">' + tag_text + "</span>"
            '<span class="num">' + str(item["offer_count"]) + " 条挂单</span></div>"
            "</div>"
        )
        parts.append(row_html)

    return '<div class="rows">\n' + "\n".join(parts) + "\n</div>"


MOVERS_SCRIPT = """
(function () {
  var panel = document.getElementById('movers');
  if (!panel) { return; }
  var head = document.getElementById('moversHead');
  var closeBtn = document.getElementById('moversClose');
  var reopen = document.getElementById('moversReopen');
  var dragging = false, offsetX = 0, offsetY = 0;

  head.addEventListener('mousedown', function (event) {
    if (event.target === closeBtn) { return; }
    var box = panel.getBoundingClientRect();
    dragging = true;
    offsetX = event.clientX - box.left;
    offsetY = event.clientY - box.top;
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
    // 把当前宽度钉死，否则清掉 right 之后（窄屏 width:auto）浮窗会按内容缩一下
    panel.style.width = box.width + 'px';
    panel.style.left = box.left + 'px';
    panel.style.top = box.top + 'px';
    document.body.style.userSelect = 'none';
    event.preventDefault();
  });
  document.addEventListener('mousemove', function (event) {
    if (!dragging) { return; }
    var left = Math.min(Math.max(0, event.clientX - offsetX), window.innerWidth - 80);
    var top = Math.min(Math.max(0, event.clientY - offsetY), window.innerHeight - 40);
    panel.style.left = left + 'px';
    panel.style.top = top + 'px';
  });
  document.addEventListener('mouseup', function () {
    if (!dragging) { return; }
    dragging = false;
    document.body.style.userSelect = '';
  });
  closeBtn.addEventListener('click', function () {
    panel.hidden = true;
    reopen.hidden = false;
  });
  reopen.addEventListener('click', function () {
    panel.hidden = false;
    reopen.hidden = true;
  });
}());
"""


def build_movers_html(movers, icon_dir):
    """48h 涨 / 跌榜浮窗（标题栏可拖动、可关闭，关掉后右下角留个按钮能再打开）。

    movers 是 (涨, 跌) 两列数据，用户没勾选的那一侧是 None —— 只勾一个就只显示一列。
    """
    if not movers:
        return ""
    boards = [
        (title, kind, rows) for title, kind, rows in (
            ("涨得最多", "up", movers[0]),
            ("跌得最多", "down", movers[1]),
        ) if rows
    ]
    if not boards:
        return ""

    def column(title, kind, rows):
        parts = []
        for index, item in enumerate(rows, 1):
            data_uri = read_icon_data_uri(icon_dir, item["id"])
            if data_uri:
                image = '<img src="' + data_uri + '" alt="">'
            else:
                image = '<span class="mv-noimg"></span>'
            parts.append(
                "<li>"
                '<span class="mv-rank">' + str(index) + "</span>"
                + image
                + '<span class="mv-name" title="' + escape(item["name_zh"]) + '">'
                + escape(item["name_zh"]) + "</span>"
                '<span class="mv-pct ' + kind + '">'
                + ("%+.1f%%" % float(item["change48h_pct"])) + "</span>"
                "</li>"
            )
        return (
            '<div class="mv-col">'
            '<div class="mv-label ' + kind + '">' + title + "</div>"
            '<ol class="mv-list">' + "".join(parts) + "</ol>"
            "</div>"
        )

    shown = max(len(rows) for _, _, rows in boards)
    return (
        '<div class="movers" id="movers">'
        '<div class="movers-head" id="moversHead">'
        "<span>48h 涨跌榜 · TOP " + str(shown) + "</span>"
        '<button type="button" class="movers-close" id="moversClose" title="关闭">×</button>'
        "</div>"
        '<div class="movers-body">'
        + "".join(column(title, kind, rows) for title, kind, rows in boards)
        + "</div></div>"
        '<button type="button" class="movers-reopen" id="moversReopen" hidden>涨跌榜</button>'
    )


def build_type_bar_html(groups, total_count):
    """物品类型选择框。没有分类就不出这一条。"""
    if not groups:
        return ""
    options = ['<option value="all">全部（总表）· ' + str(total_count) + " 条</option>"]
    for index, (name, rows) in enumerate(groups, 1):
        options.append(
            '<option value="t' + str(index) + '">' + escape(name)
            + " · " + str(len(rows)) + " 条</option>"
        )
    return (
        '<div class="type-bar">'
        '<span class="type-bar-label">物品类型</span>'
        '<select id="typeSelect">' + "".join(options) + "</select>"
        "</div>"
    )


def build_type_blocks_html(items, sort_field, icon_dir, groups):
    """总表 + 各分类表一次性全渲染出来，用选择框切换显示哪一块。"""
    blocks = [
        '<section class="type-block" data-key="all">'
        + build_rows_html(items, sort_field, icon_dir) + "</section>"
    ]
    for index, (name, rows) in enumerate(groups, 1):
        blocks.append(
            '<section class="type-block" data-key="t' + str(index) + '" hidden>'
            + build_rows_html(rows, sort_field, icon_dir) + "</section>"
        )
    return "\n".join(blocks)


TYPE_SCRIPT = """
(function () {
  var select = document.getElementById('typeSelect');
  if (!select) { return; }
  var blocks = document.querySelectorAll('.type-block');
  var stats = document.getElementById('statsBlock');
  function show(key) {
    for (var i = 0; i < blocks.length; i++) {
      blocks[i].hidden = blocks[i].getAttribute('data-key') !== key;
    }
    // 顶上那排统计说的是总表，切到分类表时收起来免得对不上
    if (stats) { stats.hidden = key !== 'all'; }
  }
  select.addEventListener('change', function () { show(select.value); });
  show('all');
}());
"""


def build_html(items, options, context):
    """渲染完整的 HTML 报告字符串。

    context 里放数据来源信息：数据库路径、同步时间、物品总数、游戏模式、图标目录。
    """
    sort_field = options["sort_field"]
    type_groups = context.get("type_groups") or []
    item_count = len(items)

    prices = []
    rare_count = 0
    total_value = 0
    for item in items:
        value = item[sort_field]
        prices.append(value)
        total_value = total_value + item["avg24h"]
        if item["offer_count"] < 3:
            rare_count = rare_count + 1

    top_value = prices[0] if prices else 0
    last_value = prices[-1] if prices else 0

    if total_value >= 100000000:
        total_html = format(round(total_value / 100000000.0, 2), ",") + " <small>亿</small>"
    else:
        total_html = format(round(total_value / 10000.0, 1), ",") + " <small>万</small>"

    status_note = ""
    if rare_count > 0:
        status_note = " <small>项 / 价格失真</small>"

    html = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"UTF-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>塔科夫跳蚤市场排行</title>\n<style>{css}</style>\n</head>\n<body>\n"
        '<div class="wrap">\n'
        "<header>\n<h1>" + build_report_title(sort_field, options["descending"], item_count) + "</h1>\n"
        '<div class="sub">'
        "<span>排序口径：<b>" + escape(sort_label(sort_field)) + "</b></span>"
        "<span>模式：<b>" + escape(context["game_mode"]) + "</b></span>"
        "<span>索引物品：<b>" + str(context["total_items"]) + " 项</b></span>"
        "<span>同步时间：<b>" + escape(context["sync_time"]) + "</b></span>"
        "<span>单位：<b>₽ 卢布</b></span>"
        "<span>涨跌口径：<b>最近 48 小时</b></span>"
        "</div>\n</header>\n"
        '<div class="stats" id="statsBlock">\n'
        '<div class="stat"><div class="label">第 1 名 ' + sort_label(sort_field) + "</div>"
        '<div class="value">₽ ' + format_money(top_value) + "</div></div>\n"
        '<div class="stat"><div class="label">第 ' + str(item_count) + " 名 " + sort_label(sort_field) + "</div>"
        '<div class="value">₽ ' + format_money(last_value) + "</div></div>\n"
        '<div class="stat"><div class="label">这些物品的跳蚤总价值</div>'
        '<div class="value">₽ ' + total_html + "</div></div>\n"
        '<div class="stat"><div class="label">挂单 &lt;3 条的</div>'
        '<div class="value">' + str(rare_count) + status_note + "</div></div>\n"
        "</div>\n"
        + build_type_bar_html(type_groups, item_count) + "\n"
        '<div class="list-head">'
        "<div>#</div><div>图标</div><div>物品</div>"
        "<div>" + sort_label(sort_field) + "</div><div>短名</div><div>挂单</div>"
        "</div>\n"
        + build_type_blocks_html(items, sort_field, context["icon_dir"], type_groups) + "\n"
        "<footer>"
        "<div><b>口径说明</b>：跳蚤均价 = Tarkov.dev 基于跳蚤市场挂单统计的 24 小时均价；"
        "区间 = 24h 最低（急卖地板价）~ 24h 最高。</div>"
        "<div><b>可信度</b>：挂单数小于 3 条时，均价极易被单笔天价挂单拉高，参考价值有限；"
        "挂单数大于等于 10 条的价格才接近真实成交。</div>"
        "<div><b>物品类型</b>：按 tarkov.dev 的 types 标签归并成大类；一个物品可能带多个标签"
        "（例如 M4A1 既是 gun 又是 wearable），这里只取优先级最高的那一个。"
        "各分类表用的是和总表一样的筛选条件。</div>"
        "<div><b>数据来源</b>：" + escape(context["db_path"]) + "</div>"
        "</footer>\n</div>\n"
        "{movers}\n<script>{script}{type_script}</script>\n</body>\n</html>\n"
    ).format(
        css=CSS,
        # 浮窗和脚本里带 JS 花括号，走 format 参数传进来，别让 .format() 去解析它们
        movers=build_movers_html(context.get("movers"), context["icon_dir"]),
        script=MOVERS_SCRIPT,
        type_script=TYPE_SCRIPT,
    )

    return html


def write_html(items, options, context, output_path):
    html = build_html(items, options, context)
    handle = open(output_path, "w", encoding="utf-8")
    handle.write(html)
    handle.close()
    return output_path


def write_csv(items, options, output_path):
    """导出纯数据表格，方便拉到 Excel 里自己分析。"""
    handle = open(output_path, "w", encoding="utf-8-sig", newline="")
    writer = csv.writer(handle)
    writer.writerow([
        "排名", "物品名", "英文名", "短名", "物品类型", "跳蚤均价", "24h最低", "24h最高",
        "挂单数", "商人最高收购价", "基准价", "48h涨跌额", "48h涨跌幅%", "占格", "可上跳蚤",
    ])

    rank = 0
    for item in items:
        rank = rank + 1
        writer.writerow([
            rank,
            item["name_zh"],
            item["name_en"],
            item["short_name"],
            item_category(item),
            item["avg24h"],
            item["low24h"],
            item["high24h"],
            item["offer_count"],
            item["trader_best"],
            item["base_price"],
            item["change48h"],
            round(item["change48h_pct"], 2),
            str(item["w"]) + "x" + str(item["h"]),
            "是" if item["flea_enabled"] == 1 else "否",
        ])
    handle.close()
    return output_path
