# -*- coding: utf-8 -*-
"""查价业务的用户偏好：收藏 + 最近搜索。

两个反直觉但重要的约定：

1. **触发搜索不记历史，只有「点击候选查看价格」才记。**
   随手打两个字看看有没有结果，这句话没有留存价值；只有真的点进去看了某个物品，
   说明用户关心它。所以历史记录锚定在「点击」这个动作上，而非「输入」。

2. **归一化后长度不足 2 个字符的查询不记录**，防止单字符污染历史列表。

都存在 exe 目录下的 data/preferences.json 里，跟着程序走，不进 %APPDATA%。

注意：本模块的函数收的是 **data 目录**（`data.data_dir()`），不是 exe 目录，
调用时别传 `data.app_dir()`。
"""

import json
import os
import re
import threading

MAX_RECENT = 12

_PUNCT_RE = re.compile(r"[\s\-_\.\,\:\;\(\)\[\]\{\}\!\?。，！？、·/\\|]+")

# 收藏 / 历史是后台线程也会碰的，锁一下避免写坏文件
_lock = threading.Lock()
_cache = None
_cache_path = None


def preferences_path(data_dir):
    """收藏文件路径。参数是 data 目录，不是 exe 目录。"""
    return os.path.join(data_dir, "preferences.json")


def _normalize_key(text):
    """和search.normalize 同样口径：全角转半角、小写、去标点。"""
    import unicodedata

    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", str(text))
    return _PUNCT_RE.sub("", folded.lower())


def load(data_dir):
    """读偏好。读不了就用空结构，不因为配置坏掉而报错。"""
    global _cache, _cache_path
    with _lock:
        _cache_path = preferences_path(data_dir)
        if _cache is not None:
            return _cache
        data = {"favorites": [], "recent": []}
        try:
            with open(_cache_path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                if isinstance(loaded.get("favorites"), list):
                    data["favorites"] = loaded["favorites"]
                if isinstance(loaded.get("recent"), list):
                    data["recent"] = loaded["recent"]
        except (OSError, ValueError):
            pass
        _cache = data
        return _cache


def _save_locked(data_dir):
    if _cache is None:
        return
    try:
        with open(preferences_path(data_dir), "w", encoding="utf-8") as handle:
            json.dump(_cache, handle, ensure_ascii=False, indent=2)
    except OSError:
        pass


def reset_cache():
    """换目录 / 测试时用。"""
    global _cache, _cache_path
    with _lock:
        _cache = None
        _cache_path = None


# ---------- 收藏 ----------


def favorite_ids(data_dir):
    return list(load(data_dir).get("favorites") or [])


def is_favorite(data_dir, item_id):
    return item_id in (load(data_dir).get("favorites") or [])


def toggle_favorite(data_dir, item_id):
    """收藏 / 取消收藏，返回切换后的状态。"""
    data = load(data_dir)
    with _lock:
        favorites = data.setdefault("favorites", [])
        if item_id in favorites:
            favorites.remove(item_id)
            state = False
        else:
            favorites.append(item_id)
            state = True
        _save_locked(data_dir)
    return state


# ---------- 最近搜索 ----------


def recent_entries(data_dir):
    """返回 [(物品id, 物品名, 查询词), ...]，最近的在前。"""
    return list(load(data_dir).get("recent") or [])


def record_visit(data_dir, item, raw_query):
    """记录一次「点开查看」。**只在点击候选时调，不在输入时调。**

    同一个物品重复查看会置顶（用户又回来看它了），而不是堆多条。
    """
    key = _normalize_key(raw_query)
    if len(key) < 2:
        # 归一化后不足 2 个字符不记录，防单字符污染历史列表
        return
    item_id = item.get("id", "")
    if not item_id:
        return
    name = item.get("name_zh") or item.get("name_en") or item.get("short_name") or ""

    data = load(data_dir)
    with _lock:
        recent = data.setdefault("recent", [])
        # 先移除同 id 的旧记录，再插到最前
        for entry in list(recent):
            if entry and entry[0] == item_id:
                recent.remove(entry)
        recent.insert(0, [item_id, name, raw_query])
        del recent[MAX_RECENT:]
        _save_locked(data_dir)


def clear_recent(data_dir):
    data = load(data_dir)
    with _lock:
        data["recent"] = []
        _save_locked(data_dir)