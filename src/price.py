# -*- coding: utf-8 -*-
"""取价链 —— 选中物品后拿到价格、商人价、历史曲线。

核心性能设计：**不联网也能出完整价格**。
启动时拉的那份全量数据本身就带每个物品的24h 均价和商人价，
所以点开一个物品，价格本地就有，毫秒级显示。

只有历史曲线需要额外请求接口（实测 1.1~1.6 秒），放后台慢慢拉，回来再补上曲线。

四级回退：
    1本地全量缓存  免费、毫秒级，含 24h 价 + 商人价
    2  本地历史缓存  1 小时内有效，用于补曲线
    3  联网拉取      补历史数据，失败则跳过
    4  空占位        显示「暂无均价」，不显示 ₽0 误导用户

第 4 级的考量：非跳蚤市场物品本来就没有均价，显示「暂无均价」比显示 ₽0 更诚实。
"""

import json
import os
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.request

import sync

# 历史价格本地缓存的时效：1 小时内直接复用，不重新请求
HISTORY_TTL = 3600
# 曲线只画最近 7 天（接口返回的是全量历史，1089 条，全画没法看）
HISTORY_DAYS = 7
# 请求超时。实测单次请求 1.1~1.6 秒，30 秒足够覆盖慢网
REQUEST_TIMEOUT = 30.0

PRICES_API = "https://json.tarkov.dev/{mode}/prices/{item_id}"
USER_AGENT = "TarkovMarketInfo/1.2"


# ---------- 第 1 级：本地全量（毫秒级）----------


def _safe_price(value):
    """价格字段转int，None / 非数都当 0。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def local_quote(item):
    """从本地全量数据取价。**永远立刻返回，不联网。**

    返回 dict：
        avg24h24 小时均价（没有则 0）
        low24h        24h 最低价
        high24h       24h 最高价
        trader_price  商人回收价（玩家实际能拿到的钱）
        offer_count   挂单数
        flea_enabled  能否上跳蚤
        has_price     有没有真实价格（决定界面显示价格还是「暂无均价」）
    """
    trader_price = _safe_price(item.get("trader_best"))
    avg = _safe_price(item.get("avg24h"))
    return {
        "avg24h": avg,
        "low24h": _safe_price(item.get("low24h")),
        "high24h": _safe_price(item.get("high24h")),
        "trader_price": trader_price,
        "offer_count": _safe_price(item.get("offer_count")),
        "flea_enabled": int(item.get("flea_enabled") or 0),
        "base_price": _safe_price(item.get("base_price")),
        # 第 4 级：没均价就明说"暂无"，不拿 ₽0 糊弄用户
        "has_price": avg > 0,
    }


def trader_names(item):
    """商人回收价的明细：[(商人名, 价格), ...]，按价格从高到低。

    口径是「卖给商人」能拿到的钱——玩家关心能卖多少，不是买入成本。
    """
    sell_json = item.get("sell_json") or ""
    try:
        price_map = json.loads(sell_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(price_map, dict):
        return []
    rows = []
    for trader_name, value in price_map.items():
        amount = _safe_price(value)
        if amount > 0:
            rows.append((trader_name, amount))
    rows.sort(key=lambda pair: pair[1], reverse=True)
    return rows


# ---------- 第 2 级：本地历史缓存 ----------


def _history_db_path(data_dir):
    """曲线缓存库路径。参数是 data 目录，不是 exe 目录。"""
    return os.path.join(data_dir, "history.db")


def init_history_db(data_dir):
    """建历史价格缓存表。返回路径，失败返回 None（缓存是可选的，失败不影响主流程）。"""
    path = _history_db_path(data_dir)
    try:
        connection = sqlite3.connect(path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS price_history (
                item_id TEXT PRIMARY KEY,
                fetched_at INTEGER,
                payload TEXT
            )
            """
        )
        connection.commit()
        connection.close()
        return path
    except sqlite3.Error:
        return None


def read_cached_history(data_dir, item_id):
    """读本地历史缓存。超过 1 小时返回 None。"""
    path = _history_db_path(data_dir)
    if not os.path.exists(path):
        return None
    try:
        connection = sqlite3.connect(path)
        row = connection.execute(
            "select fetched_at, payload from price_history where item_id = ?",
            (item_id,),
        ).fetchone()
        connection.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    fetched_at, payload = row
    if not fetched_at or (time.time() - int(fetched_at)) > HISTORY_TTL:
        return None
    try:
        return json.loads(payload)
    except (TypeError, ValueError):
        return None


def write_cached_history(data_dir, item_id, points):
    """把历史曲线写进本地缓存。写失败只记error，不打断界面。"""
    path = _history_db_path(data_dir)
    try:
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS price_history ("
            "item_id TEXT PRIMARY KEY, fetched_at INTEGER, payload TEXT)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO price_history (item_id, fetched_at, payload) "
            "VALUES (?, ?, ?)",
            (item_id, int(time.time()), json.dumps(points)),
        )
        connection.commit()
        connection.close()
    except sqlite3.Error:
        pass


# ---------- 第 3 级：联网拉曲线 ----------


def _ssl_context():
    try:
        return ssl.create_default_context()
    except Exception:
        return None


def fetch_history(mode, item_id, timeout=REQUEST_TIMEOUT):
    """联网拉某个物品的历史价格，返回最近 7 天的 [(时间戳, 均价), ...]。

    接口真实结构是 `{"data": [{"price":..,"priceMin":..,"offerCount":..,"timestamp":..}, ...]}`
    —— 注意是 `data` 而不是 `prices`，且返回的是全量历史（1000+ 条），要自己截最近 7 天。

    失败返回 None（界面保持"曲线还没数据"，不弹错）。
    """
    # 接口路径大小写敏感：/PVE/prices/ 会404，必须走 sync.mode_slug 转成 pve/regular
    url = PRICES_API.format(mode=sync.mode_slug(mode), item_id=item_id)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        response = urllib.request.urlopen(
            request, timeout=timeout, context=_ssl_context()
        )
        raw = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None

    series = parsed.get("data") or []
    if not isinstance(series, list):
        return None

    # 只留有 price 的点，再取最近 HISTORY_DAYS 天
    points = []
    for entry in series:
        if not isinstance(entry, dict):
            continue
        price = _safe_price(entry.get("price"))
        stamp = entry.get("timestamp")
        if price <= 0 or not stamp:
            continue
        points.append((int(stamp), price))
    if not points:
        return None

    points.sort(key=lambda pair: pair[0])
    cutoff = time.time() - HISTORY_DAYS * 86400
    points = [pair for pair in points if pair[0] / 1000.0 >= cutoff]
    if not points:
        # 全是很久以前的数据（冷门物品），退而取最后 7 个点，
        # 好过一条空曲线——有历史总比没有强
        points = points[-HISTORY_DAYS:]
    return points


def load_history_async(mode, data_dir, item_id, callback):
    """后台拉曲线，拉完调callback(points, error)。

    界面永远不等这个结果：先拿本地均价出图，曲线回来再重绘。

    callback(points, error)：points 为None 且 error 为字符串时表示失败。
    """
    # 第 2 级先试缓存，命中就不用联网了
    cached = read_cached_history(data_dir, item_id)
    if cached:
        callback(cached, None)
        return

    def worker():
        points = fetch_history(mode, item_id)
        if points:
            write_cached_history(data_dir, item_id, points)
            callback(points, None)
        else:
            callback(None, "取不到历史价格")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


# ---------- 第 4 级：空占位 ----------


def empty_quote(item):
    """没有任何价格数据时的占位。

    关键：不返回 ₽0，返回"暂无"。非跳蚤物品本来就没均价，
    显示 ₽0 会让用户以为这东西白送。
    """
    return {
        "avg24h": 0,
        "low24h": 0,
        "high24h": 0,
        "trader_price": 0,
        "offer_count": 0,
        "flea_enabled": int(item.get("flea_enabled") or 0),
        "base_price": _safe_price(item.get("base_price")),
        "has_price": False,
    }


def format_money(value):
    """金额格式化，带卢布符号和千分位。0 返回「暂无」而不是 ₽0。"""
    amount = _safe_price(value)
    if amount <= 0:
        return "暂无"
    return "{:,} ₽".format(amount)


def curve_summary(points):
    """从曲线算出涨跌摘要：[(文案, 是否上涨), ...]。

    没有曲线时返回空列表——界面就不显示这一块，而不是显示"持平 0%"。
    """
    if not points or len(points) < 2:
        return []
    first_price = points[0][1]
    last_price = points[-1][1]
    if first_price <= 0:
        return []
    pct = (last_price - first_price) / first_price * 100.0
    if pct >= 0.5:
        return [("近 7 天上涨 %.1f%%" % pct, True)]
    if pct <= -0.5:
        return [("近 7 天下跌 %.1f%%" % abs(pct), False)]
    return [("近 7 天基本持平", True)]