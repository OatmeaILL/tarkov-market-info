# -*- coding: utf-8 -*-
"""从 tarkov.dev 联网拉取物品索引与图标。

数据源是 json.tarkov.dev 的公开 REST 接口（不需要 key）：
    GET /{mode}/items      全量物品 + 24h 价格 + 商人买卖价（名称字段是占位符）+ iconLink
    GET /{mode}/items_zh   中文名映射表
    GET /{mode}/traders    商人 id → 显示名

写库沿用查价 MCP 的扁平 schema（data.py 的读端直接读这些列），**不要改表结构**。

下载逻辑移植自 TarkovEco（core/network.py、core/image_cache.py），两处改动：

1. httpx 换成标准库 urllib。原实现只是 `Client(timeout=)` + `.get()`，没有用到
   连接池复用 / 自动重试 / 代理 / 流式下载，换成 urllib 不会丢能力；而带上 httpx
   会让单文件 exe 再多几 MB（httpcore / anyio / sniffio / idna / certifi）。
   HTTPS 证书走 Windows 系统证书库，不需要 certifi。
2. 取消时先把队列排空再 join。原实现在取消后 worker 直接 return、队列里剩下的
   任务永远不会 task_done，`q.join()` 会把线程挂死。
"""

import concurrent.futures
import json
import os
import queue
import re
import shutil
import sqlite3
import ssl
import tempfile
import threading
import time
import unicodedata
import urllib.request
import zipfile

import data

API_BASE = "https://json.tarkov.dev"
USER_AGENT = "TarkovMarketInfo/1.2"

NETWORK_TIMEOUT = 30.0
# 正常图床 0.5 秒左右就回了，10 秒足够；定小一点，被限流时才能快点收手
ICON_TIMEOUT = 10.0
ICON_WORKERS = 4
# 连续这么多张都下不下来就整个收手。图床限流时每个请求都要等满超时，
# 几千个挨个等下去界面看着就像卡死；早点停下来让用户过会儿再点一次续传。
ICON_FAIL_LIMIT = 25

# 图标包：一次请求拿全量图标，比逐个下 5000 多次稳得多，也不容易被图床限流。
# 换新包时把同名资产替换掉即可，程序里这个地址不用动。
ICON_PACK_URL = (
    "https://github.com/OatmeaILL/tarkov-mcp/releases/download/icons/icon.zip"
)
# 下载顺序：镜像优先，镜像都失败再回原始 release（前缀式加速站）。
# 注意 github.com 在部分网络下直连不通（实测 8 秒超时），所以镜像必须排前面。
# 前两个是常用的加速站；后两个是备用，实测也能拉到。
ICON_PACK_MIRRORS = [
    "https://gh-proxy.org/",
    "https://v4.gh-proxy.org/",
    "https://ghproxy.net/",
    "https://gh-proxy.com/",
]
_PACK_MARKER = ".iconpack"
_PACK_TEMP = ".iconpack.tmp.zip"

# （界面/报告里显示的名字, 接口用的 gameMode）
GAME_MODES = [
    ("PVE", "pve"),
    ("PVP", "regular"),
]

# 物品表：和查价 MCP 的库完全一致，读端 load_all_items 直接读这些列
SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    short_name TEXT,
    name_zh TEXT,
    name_en TEXT,
    norm_zh TEXT,
    norm_en TEXT,
    avg24h INTEGER DEFAULT 0,
    low24h INTEGER DEFAULT 0,
    high24h INTEGER DEFAULT 0,
    offer_count INTEGER DEFAULT 0,
    base_price INTEGER DEFAULT 0,
    flea_enabled INTEGER DEFAULT 0,
    min_level_flea INTEGER DEFAULT 0,
    sell_json TEXT DEFAULT '{}',
    updated_at INTEGER DEFAULT 0,
    w INTEGER DEFAULT 0,
    h INTEGER DEFAULT 0,
    change48h INTEGER DEFAULT 0,
    change48h_pct REAL DEFAULT 0,
    types_json TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# 归一化用（移植自 TarkovEco core/matcher.py）
_PUNCT_RE = re.compile(r"[\s\-_\.\,\:\;\(\)\[\]\{\}\!\?。，！？、]+")

# 各阶段进度（0~1），图标包和逐个补齐占最后一段
_STAGE_LIST = 0.05
_STAGE_ZH = 0.25
_STAGE_TRADERS = 0.35
_STAGE_MERGE = 0.45
_STAGE_DB = 0.50
_STAGE_PACK = 0.62
_STAGE_ICON_TOP = 1.0

# 进度回调的 phase 值，界面上据此分两条进度条（数据 / 图标）
PHASE_DATA = "data"
PHASE_ICON = "icons"


def _report(progress_cb, phase, text, value):
    """进度回报：progress_cb(phase, text, value)。"""
    if progress_cb:
        progress_cb(phase, text, value)


def mode_slug(value):
    """界面上的「PVE / PVP」→ 接口用的 gameMode。"""
    text = str(value or "").strip().lower()
    for label, slug in GAME_MODES:
        if text in (label.lower(), slug):
            return slug
    return "pve"


def normalize(text):
    """去标点 / NFKC / 小写 / 去空白。"""
    if not text:
        return ""
    return _PUNCT_RE.sub("", unicodedata.normalize("NFKC", str(text)).lower())


def default_db_path():
    """数据库落点 = data\\tarkov.db。老位置的库不搬，读的时候由 data.db_candidates 兜。"""
    return os.path.join(data.data_dir(), data.DB_NAME)


def default_icon_dir():
    return data.icon_root()


# ---------- 网络 ----------


def _get(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(
        request, timeout=timeout, context=ssl.create_default_context()
    )


def _get_json(url, timeout=NETWORK_TIMEOUT):
    with _get(url, timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _fetch_trader_names(base_url):
    """商人 id → 显示名（用 normalizedName，name 字段是占位符）。"""
    try:
        payload = _get_json(base_url + "/traders").get("data") or {}
    except Exception:
        return {}
    names = {}
    for trader_id, trader in payload.items():
        if isinstance(trader, dict):
            name = trader.get("normalizedName") or trader_id
            names[trader_id] = name[:1].upper() + name[1:] if name else trader_id
    return names


def _map_sell_prices(entries, trader_names):
    """sellToTrader 是 [{trader, price}]，库里存的是 {商人名: 最高收购价} 的字典。

    读端 best_trader_price() 按字典遍历，写成数组会让「商人最高收购价」全变 0。
    """
    best = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        trader_id = entry.get("trader")
        name = trader_names.get(trader_id, trader_id)
        price = int(entry.get("price") or 0)
        if name and price > best.get(name, 0):
            best[name] = price
    return best


def fetch_items(mode="pve", progress_cb=None):
    """拉全量物品并与中文名合并，返回可直接写库的条目列表。"""
    base_url = API_BASE + "/" + mode

    _report(progress_cb, PHASE_DATA, "正在获取物品列表 ...", _STAGE_LIST)
    payload = _get_json(base_url + "/items")
    raw_items = (payload.get("data") or {}).get("items") or {}

    _report(
        progress_cb, PHASE_DATA,
        "物品列表完成（%d 项），正在获取中文翻译 ..." % len(raw_items), _STAGE_ZH,
    )
    translations = _get_json(base_url + "/items_zh").get("data") or {}

    _report(
        progress_cb, PHASE_DATA,
        "中文翻译完成（%d 条），正在获取商人列表 ..." % len(translations), _STAGE_TRADERS,
    )
    trader_names = _fetch_trader_names(base_url)

    _report(progress_cb, PHASE_DATA, "正在合并物品数据 ...", _STAGE_MERGE)

    items = []
    for item_id, raw in raw_items.items():
        name_key = raw.get("name", "")
        short_key = raw.get("shortName", "")
        name_zh = translations.get(name_key) or name_key.replace(" Name", "").strip()
        short_zh = translations.get(short_key) or name_zh
        offer_count = int(raw.get("lastOfferCount") or 0)
        items.append({
            "id": item_id,
            "name_zh": name_zh,
            "short_name": short_zh,
            "name_en": raw.get("normalizedName") or "",
            "avg24h": int(raw.get("avg24hPrice") or 0),
            "low24h": int(raw.get("low24hPrice") or 0),
            "high24h": int(raw.get("high24hPrice") or 0),
            "base_price": int(raw.get("basePrice") or 0),
            "offer_count": offer_count,
            "flea_enabled": 1 if offer_count > 0 else 0,
            "min_level_flea": int(raw.get("minLevelForFlea") or 0),
            "w": int(raw.get("width") or 0),
            "h": int(raw.get("height") or 0),
            "sell": _map_sell_prices(raw.get("sellToTrader"), trader_names),
            "icon_url": raw.get("iconLink") or "",
            # 涨跌口径：Tarkov.dev 只给「最近 48 小时」，没有 24 小时的
            "change48h": int(raw.get("changeLast48h") or 0),
            "change48h_pct": float(raw.get("changeLast48hPercent") or 0.0),
            # 物品类型标签（gun / ammo / meds ...），报告里按它分类
            "types": [str(t) for t in (raw.get("types") or [])],
        })
    return items


# ---------- 写库 ----------


def build_db(items, db_path, mode="pve"):
    """全量重建索引库，返回写入条数。

    先写同目录下的临时库再原子替换：中途失败不会把已有的可用库写坏。
    """
    folder = os.path.dirname(os.path.abspath(db_path)) or "."
    os.makedirs(folder, exist_ok=True)
    temp_path = os.path.join(folder, ".tarkov_sync_tmp.db")
    if os.path.exists(temp_path):
        os.remove(temp_path)

    now = int(time.time())
    rows = [
        (
            item["id"], item["short_name"], item["name_zh"], item["name_en"],
            normalize(item["name_zh"]), normalize(item["name_en"]),
            item["avg24h"], item["low24h"], item["high24h"], item["offer_count"],
            item["base_price"], item["flea_enabled"], item["min_level_flea"],
            json.dumps(item["sell"], ensure_ascii=False), now,
            item["w"], item["h"], item["change48h"], item["change48h_pct"],
            json.dumps(item["types"], ensure_ascii=False),
        )
        for item in items
    ]

    connection = sqlite3.connect(temp_path)
    try:
        connection.executescript(SCHEMA)
        with connection:
            connection.executemany(
                "INSERT OR REPLACE INTO items(id, short_name, name_zh, name_en,"
                " norm_zh, norm_en, avg24h, low24h, high24h, offer_count,"
                " base_price, flea_enabled, min_level_flea, sell_json,"
                " updated_at, w, h, change48h, change48h_pct, types_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('last_sync', ?)",
                (str(now),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('game_mode', ?)",
                (mode,),
            )
    finally:
        connection.close()

    os.replace(temp_path, db_path)
    return len(rows)


# ---------- 图标 ----------


def _atomic_write(path, blob):
    temp_path = path + ".tmp"
    with open(temp_path, "wb") as handle:
        handle.write(blob)
    os.replace(temp_path, path)


# ---------- 图标包 ----------


def icon_pack_urls():
    """图标包下载地址：镜像在前，原始 release 兜底。"""
    return [mirror + ICON_PACK_URL for mirror in ICON_PACK_MIRRORS] + [ICON_PACK_URL]


def _download_to(url, dest_path, progress_cb=None, cancel_flag=None,
                 base=0.0, span=1.0, label="正在下载"):
    """把 url 下载到 dest_path，按字节回报进度。返回写入的字节数（0 = 被取消）。"""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(
        request, timeout=NETWORK_TIMEOUT, context=ssl.create_default_context()
    ) as response:
        total = int(response.headers.get("Content-Length") or 0)
        got = 0
        last_percent = -1
        with open(dest_path, "wb") as handle:
            while True:
                if cancel_flag and cancel_flag[0]:
                    return 0
                chunk = response.read(65536)
                if not chunk:
                    break
                handle.write(chunk)
                got += len(chunk)
                if progress_cb and total:
                    percent = int(got * 100 / total)
                    # 每 1% 报一次就够了，不然每读一块都回调，日志会被刷爆
                    if percent != last_percent:
                        last_percent = percent
                        _report(
                            progress_cb, PHASE_ICON,
                            "%s %d%%（%.1f / %.1f MB）" % (
                                label, percent, got / 1048576, total / 1048576
                            ),
                            base + span * (got / float(total)),
                        )
    return got


def _remote_pack_size():
    """问出线上图标包的大小（只请求第 1 个字节）。全失败返回 0。

    用来判断"包有没有换过"：地址不变、把资产替换成新包时，光看 URL 是发现不了的。
    """
    for url in icon_pack_urls():
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"}
        )
        try:
            with urllib.request.urlopen(
                request, timeout=NETWORK_TIMEOUT, context=ssl.create_default_context()
            ) as response:
                content_range = response.headers.get("Content-Range") or ""
                if "/" in content_range:
                    tail = content_range.rsplit("/", 1)[1].strip()
                    if tail.isdigit():
                        return int(tail)
                size = int(response.headers.get("Content-Length") or 0)
                if size:
                    return size
        except Exception:
            continue
    return 0


def _read_pack_marker(marker):
    """读标记：返回 (url, size)。文件不存在或格式不对都算没下过。"""
    try:
        with open(marker, "r", encoding="utf-8") as handle:
            parts = handle.read().strip().split("\n")
    except OSError:
        return "", 0
    if not parts or parts[0] != ICON_PACK_URL:
        return "", 0
    size = 0
    if len(parts) > 1 and parts[1].strip().isdigit():
        size = int(parts[1].strip())
    return parts[0], size


def _extract_icons(zip_path, icon_dir):
    """把压缩包里的 .webp 解到 icon_dir，已有的跳过。返回新解出的数量。"""
    written = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename
            if info.is_dir() or not name.lower().endswith(".webp"):
                continue
            # 只取文件名，防止压缩包里有 ../ 之类的路径
            target = os.path.join(icon_dir, os.path.basename(name))
            if os.path.exists(target):
                continue
            with archive.open(info) as source, open(target, "wb") as handle:
                shutil.copyfileobj(source, handle)
            written += 1
    return written


def ensure_icon_pack(icon_dir, progress_cb=None, cancel_flag=None):
    """拉一次图标包并解压。先试镜像，失败再回原始 release。

    解压过的会在 icon_dir/.iconpack 留标记（地址 + 大小）；线上包大小没变就不重复下。
    返回 {"done": bool, "extracted": int, "source": str}。
    """
    os.makedirs(icon_dir, exist_ok=True)
    marker = os.path.join(icon_dir, _PACK_MARKER)
    recorded_url, recorded_size = _read_pack_marker(marker)
    if recorded_url:
        # 地址没变还要比一下大小：换新包时资产名是同一个，光看 URL 发现不了。
        # 问不到大小（网络问题）就先按没换处理，缺的图后面会走补齐。
        remote_size = _remote_pack_size()
        if not remote_size or remote_size == recorded_size:
            return {"done": True, "extracted": 0, "source": "cached"}

    urls = icon_pack_urls()
    last_error = ""
    temp_path = os.path.join(icon_dir, _PACK_TEMP)

    for index, url in enumerate(urls):
        if cancel_flag and cancel_flag[0]:
            return {"done": False, "extracted": 0, "source": ""}
        label = "正在下载图标包（镜像）" if index < len(ICON_PACK_MIRRORS) else "正在下载图标包（原始地址）"
        try:
            _report(progress_cb, PHASE_ICON, label + " ...", _STAGE_DB)
            size = _download_to(
                url, temp_path, progress_cb, cancel_flag,
                _STAGE_DB, _STAGE_PACK - _STAGE_DB, label,
            )
            if not size:
                return {"done": False, "extracted": 0, "source": ""}
        except Exception as error:
            last_error = "%s: %s" % (type(error).__name__, error)
            _report(
                progress_cb, PHASE_ICON,
                label.replace("正在下载", "").replace("（", "").replace("）", "")
                + "下载失败，换下一个地址",
                _STAGE_PACK,
            )
            continue

        try:
            extracted = _extract_icons(temp_path, icon_dir)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("%s\n%d" % (ICON_PACK_URL, size))
        _report(progress_cb, PHASE_ICON, "图标包解压完成，新解出 %d 张" % extracted, _STAGE_PACK)
        return {"done": True, "extracted": extracted, "source": url}

    _report(
        progress_cb, PHASE_ICON,
        "图标包没下下来（%s），改为逐个补齐" % (last_error or "全部地址失败"),
        _STAGE_PACK,
    )
    return {"done": False, "extracted": 0, "source": "", "error": last_error}


def _drain(tasks):
    """把队列里还没人认领的任务排空，否则 join() 会一直等。"""
    while True:
        try:
            tasks.get_nowait()
            tasks.task_done()
        except queue.Empty:
            return


def download_icons(items, icon_dir, progress_cb=None, cancel_flag=None):
    """批量下载小图标，返回 {"cached", "failed", "aborted"}。

    已有的跳过（可打断续传）；图标约 2KB/张，4 线程并发。
    """
    os.makedirs(icon_dir, exist_ok=True)
    todo = []
    for item in items:
        url = item.get("icon_url") or ""
        if not url:
            continue
        if os.path.exists(os.path.join(icon_dir, item["id"] + ".webp")):
            continue
        todo.append((item["id"], url))

    total = len(todo)
    if total == 0:
        _report(progress_cb, PHASE_ICON, "图标无需更新", _STAGE_ICON_TOP)
        return {"cached": 0, "failed": 0, "aborted": False}

    tasks = queue.Queue()
    for pair in todo:
        tasks.put(pair)

    lock = threading.Lock()
    state = {"ok": 0, "failed": 0, "streak": 0, "stop": False}

    def worker():
        while True:
            with lock:
                if state["stop"]:
                    return
            if cancel_flag and cancel_flag[0]:
                return
            try:
                item_id, url = tasks.get_nowait()
            except queue.Empty:
                return
            ok = False
            try:
                with _get(url, ICON_TIMEOUT) as response:
                    blob = response.read()
                _atomic_write(os.path.join(icon_dir, item_id + ".webp"), blob)
                ok = True
            except Exception:
                ok = False
            with lock:
                if ok:
                    state["ok"] += 1
                    state["streak"] = 0
                else:
                    state["failed"] += 1
                    state["streak"] += 1
                    if state["streak"] >= ICON_FAIL_LIMIT:
                        state["stop"] = True
            tasks.task_done()

    cancelled = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=ICON_WORKERS) as pool:
        futures = [pool.submit(worker) for _ in range(ICON_WORKERS)]
        while not tasks.empty():
            if cancel_flag and cancel_flag[0]:
                cancelled = True
                break
            if state["stop"]:
                break
            if progress_cb:
                # 用「已经落盘」的数量报进度，而不是「已经发出去的请求」，
                # 否则失败一堆时进度会虚高、收尾时又往回跳
                done = state["ok"]
                _report(
                    progress_cb, PHASE_ICON,
                    "正在补齐缺失图标 %d / %d" % (done, total),
                    _STAGE_PACK + (done / float(total)) * (_STAGE_ICON_TOP - _STAGE_PACK),
                )
            time.sleep(0.15)
        if cancelled or state["stop"]:
            _drain(tasks)
        tasks.join()
        for future in futures:
            future.cancel()

    cached = sum(
        1 for item_id, _ in todo
        if os.path.exists(os.path.join(icon_dir, item_id + ".webp"))
    )
    failed = state["failed"]
    aborted = state["stop"]
    # 进度按真正落盘的数量算；被中断时就停在对应位置，别谎报 100%
    value = _STAGE_PACK + (cached / float(total)) * (_STAGE_ICON_TOP - _STAGE_PACK)
    if aborted:
        _report(progress_cb, PHASE_ICON, "缺失图标被限流中断，已补 %d / %d" % (cached, total), value)
    else:
        _report(progress_cb, PHASE_ICON, "缺失图标补齐 %d / %d" % (cached, total), value)
    return {"cached": cached, "failed": failed, "aborted": aborted}


# ---------- 编排 ----------


def sync_all(mode="pve", with_icons=True, progress_cb=None, cancel_flag=None,
             db_path=None, icon_dir=None):
    """拉数据 → 建库 →（可选）下图标。返回汇总信息。"""
    db_path = db_path or default_db_path()
    icon_dir = icon_dir or default_icon_dir()

    items = fetch_items(mode, progress_cb)

    _report(progress_cb, PHASE_DATA, "正在写入数据库 ...", _STAGE_DB)
    count = build_db(items, db_path, mode)

    pack = {"done": False, "extracted": 0, "source": ""}
    icon_stats = {"cached": 0, "failed": 0, "aborted": False}
    if with_icons:
        # 先一次性拉图标包（镜像优先，失败回原始 release），
        # 包里已经有的会被跳过，剩下的少量缺图再联网补齐
        pack = ensure_icon_pack(icon_dir, progress_cb, cancel_flag)
        if not (cancel_flag and cancel_flag[0]):
            icon_stats = download_icons(items, icon_dir, progress_cb, cancel_flag)

    have = sum(
        1 for item in items
        if os.path.exists(os.path.join(icon_dir, item["id"] + ".webp"))
    )
    return {
        "db_path": db_path,
        "icon_dir": icon_dir,
        "items": count,
        "icons": have,
        "icon_pack": pack.get("extracted", 0),
        "icon_pack_source": pack.get("source", ""),
        "icon_failed": icon_stats["failed"],
        "icon_aborted": icon_stats["aborted"],
        "cancelled": bool(cancel_flag and cancel_flag[0]),
    }
