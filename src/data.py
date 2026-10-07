# -*- coding: utf-8 -*-
"""物品索引数据库的读取与检索。

只管一件事：从 Tarkov 索引库（sqlite）里，按条件取出物品列表。
数据库由本程序自己联网更新并维护（见 sync.py），都放在 exe 所在目录下的
data 子目录里，不再默认去翻别的程序的缓存。本模块只读不写。

目录布局（v1.3）—— 所有运行时文件都在 exe 所在文件夹内，但按类型分开放：

    TarkovMarketInfo.exe
    data/          数据库、配置、收藏、错误日志
      tarkov.db          物品索引
      history.db         曲线本地缓存
      config.json        界面配置
      preferences.json   查价收藏与最近查看
      error.log          错误日志
    icon/          物品图标（5470 张 webp）
    reports/       生成的报表：HTML / PNG 长图 / CSV
"""

import json
import operator
import os
import sqlite3
import sys

# 界面下拉框的选项 -> 数据库字段名
# "商人最高收购价" 不是真实字段，由 sell_json 现场算出来
SORT_OPTIONS = [
    ("跳蚤均价", "avg24h"),
    ("24h 最低价", "low24h"),
    ("24h 最高价", "high24h"),
    ("挂单数量", "offer_count"),
    ("商人最高收购价", "trader_best"),
    ("物品基准价", "base_price"),
]

# 报告右下角那个涨跌榜浮窗，每列显示多少条
MOVERS_COUNT = 10

# ---------- 目录布局 ----------
# 这三个名字是唯一的真源，其它模块一律调函数，别自己拼路径
DATA_SUBDIR = "data"
ICON_SUBDIR = "icon"
REPORT_SUBDIR = "reports"

DB_NAME = "tarkov.db"
HISTORY_NAME = "history.db"
CONFIG_NAME = "config.json"
PREFERENCES_NAME = "preferences.json"
ERROR_LOG_NAME = "error.log"


def top_movers(items, wanted_up, wanted_down, count=MOVERS_COUNT):
    """48h 涨跌榜：从能上跳蚤、且有价格的物品里取涨跌幅前后各 count 名。

    返回 (涨得最多, 跌得最多)；没勾选的那一侧给 None。
    """
    if not wanted_up and not wanted_down:
        return None, None

    pool = [
        item for item in items
        if item["flea_enabled"] == 1 and item["avg24h"] > 0 and item["change48h_pct"]
    ]
    pool.sort(key=operator.itemgetter("change48h_pct"), reverse=True)
    up = pool[:count] if wanted_up else None
    down = pool[-count:][::-1] if wanted_down else None
    return up, down


# 接口的 types 是 26 个 slug，里面混着「能装备」「不能上跳蚤」这类纯标记，
# 直接摆出来用户看不懂，所以按顺序归成直觉大类；一个物品只落到第一个命中的类。
CATEGORY_ORDER = [
    ("枪械", ("gun",)),
    ("弹药", ("ammo", "ammoBox")),
    ("护甲与头盔", ("armor", "armorPlate", "helmet")),
    ("面具眼镜", ("glasses",)),
    ("耳机", ("headphones",)),
    ("背包胸挂", ("backpack", "rig")),
    ("医疗", ("meds", "injectors")),
    ("食品", ("provisions",)),
    ("钥匙", ("keys",)),
    ("手雷", ("grenade",)),
    ("容器", ("container",)),
    ("配件", ("mods", "pistolGrip", "suppressor")),
    ("海报", ("poster",)),
    ("武器预设", ("preset",)),
    ("交换用物品", ("barter",)),
]
OTHER_CATEGORY = "其他"

CATEGORY_BY_TAG = {}
for _rank, (_category_name, _category_tags) in enumerate(CATEGORY_ORDER):
    for _tag in _category_tags:
        CATEGORY_BY_TAG[_tag] = (_rank, _category_name)


def item_category(item):
    """把一个物品归到某个大类的名字上（按 CATEGORY_ORDER 的先后定优先级）。"""
    best = None
    for tag in item.get("types") or ():
        found = CATEGORY_BY_TAG.get(tag)
        if found and (best is None or found[0] < best[0]):
            best = found
    return best[1] if best else OTHER_CATEGORY


def group_by_type(items, limit):
    """按大类分堆，每堆取前 limit 条（limit <= 0 表示不截断）。

    items 得是已经排好序的列表，分堆时保持这个顺序。
    返回 [(类名, [物品...]), ...]；空类不出现，顺序固定。
    """
    buckets = {}
    for item in items:
        buckets.setdefault(item_category(item), []).append(item)

    groups = []
    for name, _tags in CATEGORY_ORDER:
        rows = buckets.get(name)
        if rows:
            groups.append((name, rows[:limit] if limit > 0 else rows))
    others = buckets.get(OTHER_CATEGORY)
    if others:
        groups.append((OTHER_CATEGORY, others[:limit] if limit > 0 else others))
    return groups


# 不是所有物品都能上跳蚤市场，这两个字段用来判断流动性
LIQUIDITY_GOOD = 10
LIQUIDITY_MID = 3


def app_dir():
    """程序运行目录：打包后 = exe 所在目录，源码运行 = 项目根。

    数据库、图标、报表都放这个文件夹**里面**（按类型再分 data / icon / reports），
    整个文件夹搬走就能用。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    """数据目录 = exe 目录下的 data\。存数据库、配置、收藏、错误日志。"""
    return os.path.join(app_dir(), DATA_SUBDIR)


def icon_root():
    """图标目录 = exe 目录下的 icon\\。"""
    return os.path.join(app_dir(), ICON_SUBDIR)


def reports_dir():
    """报表目录 = exe 目录下的 reports\\。存 HTML / PNG / CSV。"""
    return os.path.join(app_dir(), REPORT_SUBDIR)


def config_path():
    """配置文件路径（data\\config.json）。"""
    return os.path.join(data_dir(), CONFIG_NAME)


def history_db_path():
    """曲线缓存库路径（data\\history.db）。"""
    return os.path.join(data_dir(), HISTORY_NAME)


def error_log_path():
    """错误日志路径（data\\error.log）。"""
    return os.path.join(data_dir(), ERROR_LOG_NAME)


def ensure_dirs():
    """把 data\\ 和 reports\\ 建出来（只建目录，不动里面的东西）。

    放在每次启动时调用，这样只拷exe 到新机器、第一次跑也能自动建好。
    icon\\ 不在这里建 —— 它由联网更新创建，空的 icon\\ 会让「有没有图标」的判断变麻烦。
    """
    for path in (data_dir(), reports_dir()):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass


def db_candidates():
    """数据库候选位置，按优先级排列（第一个存在的就是它）。

    新的 data\\tarkov.db 在前；后面几个是 v1.2 之前的老位置，
    为了让老用户的文件夹升级后还能直接用（读得到就不重下）。
    """
    return [
        os.path.join(data_dir(), DB_NAME),
        os.path.join(app_dir(), DB_NAME),
        os.path.join(app_dir(), "cache", "db", DB_NAME),
    ]


def find_default_db():
    """在候选路径里找第一个存在的数据库。"""
    for path in db_candidates():
        if os.path.exists(path):
            return path
    return ""


def icon_dir_candidates(db_path):
    """图标目录候选位置，按优先级排列。

    优先程序目录下的 icon\\（联网更新的落点），再考虑查价 MCP 的图标目录。
    """
    out = [icon_root(), os.path.join(app_dir(), "tarkov_mcp", ICON_SUBDIR)]
    if db_path:
        # 数据库在 <MCP根>/cache/db/tarkov.db，图标在 <MCP根>/tarkov_mcp/icon
        db_dir = os.path.dirname(os.path.abspath(db_path))
        cache_dir = os.path.dirname(db_dir)
        mcp_root = os.path.dirname(cache_dir)
        out.append(os.path.join(mcp_root, "tarkov_mcp", ICON_SUBDIR))
    return out


def guess_icon_dir(db_path):
    """挑第一个存在且里面有文件的图标目录。

    都没有就返回程序目录下的 icon\\ —— 联网更新会往那里放。
    """
    for path in icon_dir_candidates(db_path):
        try:
            if os.path.isdir(path) and os.listdir(path):
                return path
        except OSError:
            continue
    return icon_root()


def best_trader_price(sell_json_text):
    """从 sell_json 里取出商人收购价的最大值。"""
    if not sell_json_text:
        return 0
    try:
        price_map = json.loads(sell_json_text)
    except (ValueError, TypeError):
        return 0
    # 正常是 {"商人名": 价格} 的字典；万一存成数组 / null，直接当没有
    if not isinstance(price_map, dict):
        return 0

    best = 0
    for trader_name in price_map:
        value = price_map[trader_name]
        if isinstance(value, (int, float)) and value > best:
            best = int(value)
    return best


def load_db_summary(db_path):
    """读出物品总数、最后同步时间，用于界面上的状态显示。"""
    if not os.path.exists(db_path):
        return None

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute("select count(*) from items").fetchone()
        try:
            meta = connection.execute(
                "select value from meta where key = 'last_sync'"
            ).fetchone()
        except sqlite3.Error:
            # 老库没有 meta 表也算正常，退回按文件时间显示
            meta = None
    finally:
        connection.close()

    total = row[0] if row else 0
    last_sync = 0
    if meta and meta[0]:
        try:
            last_sync = int(meta[0])
        except (TypeError, ValueError):
            last_sync = 0
    if not last_sync:
        last_sync = int(os.path.getmtime(db_path))
    return {"total": total, "mtime": os.path.getmtime(db_path), "last_sync": last_sync}


def load_all_items(db_path):
    """把整个物品表读进内存。

    一共五千多条，全读进来比拼复杂 SQL 直观，排序和过滤都在 Python 里做。
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError("找不到数据库文件：" + db_path)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    # 老库（或别人给的库）可能没有后来加的涨跌幅列，缺的按 0 处理，
    # 别让整个报告因为一个列名就挂掉
    columns = {row[1] for row in connection.execute("PRAGMA table_info(items)")}
    wanted = [
        "id", "name_zh", "name_en", "short_name", "avg24h", "low24h", "high24h",
        "offer_count", "base_price", "flea_enabled", "sell_json", "w", "h",
        "change48h", "change48h_pct", "types_json",
    ]
    rows = connection.execute(
        "select " + ", ".join(c for c in wanted if c in columns) + " from items"
    ).fetchall()
    connection.close()

    def read(row, name, default=0):
        try:
            value = row[name]
        except (IndexError, KeyError):
            return default
        return default if value is None else value

    def read_types(raw):
        try:
            value = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        return [str(tag) for tag in value] if isinstance(value, list) else []

    items = []
    for row in rows:
        item = {
            "id": row["id"],
            "name_zh": row["name_zh"] or "",
            "name_en": row["name_en"] or "",
            "short_name": row["short_name"] or "",
            "avg24h": int(row["avg24h"] or 0),
            "low24h": int(row["low24h"] or 0),
            "high24h": int(row["high24h"] or 0),
            "offer_count": int(row["offer_count"] or 0),
            "base_price": int(row["base_price"] or 0),
            "flea_enabled": int(row["flea_enabled"] or 0),
            "w": int(row["w"] or 0),
            "h": int(row["h"] or 0),
            "change48h": int(read(row, "change48h", 0) or 0),
            "change48h_pct": float(read(row, "change48h_pct", 0.0) or 0.0),
            "types": read_types(read(row, "types_json", "[]")),
            # sell_json 原样留着：查价界面要列出每个商人的回收价明细，
            # 只给一个 trader_best 最大值是不够的
            "sell_json": row["sell_json"] if "sell_json" in columns else "",
        }
        # 商人价单独算，界面上可以按它排序
        item["trader_best"] = best_trader_price(row["sell_json"])
        items.append(item)

    return items


def search_items(items, options):
    """按条件过滤 + 排序 + 截断。

    options 里用到的键：
        sort_field    排序用的字段名
        descending    True 从大到小，False 从小到大
        limit         取前多少条，0 表示不限制
        keyword       名称关键词，空字符串表示不过滤
        flea_only     是否只要能在跳蚤市场交易的
        skip_zero     是否跳过排序字段为 0 的条目
        min_price     排序字段的最小值门槛
    """
    sort_field = options["sort_field"]
    keyword = options["keyword"].strip().lower()
    limit = options["limit"]

    matched = []
    for item in items:
        if options["flea_only"] and item["flea_enabled"] != 1:
            continue

        value = item[sort_field]
        if options["skip_zero"] and value <= 0:
            continue
        if value < options["min_price"]:
            continue

        if keyword:
            haystack = item["name_zh"] + " " + item["name_en"] + " " + item["short_name"]
            if keyword not in haystack.lower():
                continue

        matched.append(item)

    matched.sort(key=operator.itemgetter(sort_field), reverse=options["descending"])

    if limit > 0:
        matched = matched[:limit]
    return matched


def liquidity_level(offer_count):
    """按挂单数给出流动性标签，返回 (文案, 样式名)。"""
    if offer_count >= LIQUIDITY_GOOD:
        return ("流通好", "good")
    if offer_count >= LIQUIDITY_MID:
        return ("流通一般", "mid")
    return ("挂单稀少", "bad")


def sort_label(sort_field):
    """字段名反查界面上的中文名。"""
    for label, field in SORT_OPTIONS:
        if field == sort_field:
            return label
    return sort_field
