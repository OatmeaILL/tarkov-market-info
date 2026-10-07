# -*- coding: utf-8 -*-
"""搜索链 —— 从五千多条物品里挑出最可能的 5 个候选。

整条链**全程本地、同步返回**，界面上不等待网络：

    归一化 → 同义词扩展 → 索引召回 → 规则打分 → Top5

规则打分是纯手工加权（不用机器学习）。核心原因是字符串相似度分不开
「M4A1 卡宾枪」和「M4A1 前准星」—— 必须靠武器词 / 配件词人为加分减分。
"""

import re
import unicodedata

# 归一化时要去掉的标点与空白（中英文都算）
_PUNCT_RE = re.compile(r"[\s\-_\.\,\:\;\(\)\[\]\{\}\!\?。，！？、·/\\|]+")

# ---------- 打分权重 ----------
SCORE_EXACT = 30# short_name 完全匹配
SCORE_PREFIX = 14       # short_name 前缀匹配
SCORE_NAME_CONTAINS = 8 # 中文名里直接含查询词
SCORE_EN_CONTAINS = 3   # 只有英文名含查询词（比中文名弱）
SCORE_FIELD_BONUS = 4   # short_name 命中比长名命中更可信
SCORE_WEAPON = 10       # 命中武器词
SCORE_PART = -10        # 命中配件词
SCORE_NAME_MAX = -6     # 名称过长的最大惩罚

# 武器词：压过同名配件
WEAPON_WORDS = (
    "卡宾枪", "突击步枪", "步枪", "冲锋枪", "手枪", "狙击", "霰弹", "机枪",
    "左轮", "霰弹枪", "自动霰弹枪", "手枪",
)

# 配件词：往后排
PART_WORDS = (
    "转接器", "护木", "握把", "枪托", "消音", "瞄准镜", "弹匣", "准星",
    "机匣", "枪管", "枪口", "扳机", "复进簧", "导轨", "侧导轨",
    "消音器", "瞄准镜座", "背带", "握把套", "弹匣套", "消音器基座",
)

# ---------- 同义词（双向）----------
# 官方译名和玩家俗称对不上：玩家打「显卡」，官方叫「显示卡」。
# 每条写成 (俗称, 官方名)；反查也自动成立。
SYNONYMS = [
    ("显卡", "显示卡"),
    ("显卡", "图形卡"),
    ("子弹", "弹药"),
    ("子弹", "子弹头"),
    ("护甲", "防弹衣"),
    ("护甲", "防弹背心"),
    ("急救", "急救包"),
    ("急救", "治疗包"),
    ("药", "止痛药"),
    ("药", "药剂"),
    ("药", "药品"),
    ("镜", "瞄准镜"),
    ("消音器", "消音"),
    ("握把", "手枪握把"),
    ("弹匣", "弹匣"),
    ("头盔", "头盔"),
    ("钥匙", "钥匙"),
    ("容器", "容器"),
    ("背包", "背包"),
    ("胸挂", "胸挂"),
    ("干粮", "食物"),
    ("水", "纯净水"),
    ("面", "罐装六可乐"),
]

# 反查表：官方名 → 俗称集合
_SYNONYM_TO_OFFICIAL = {}
for _alias, _official in SYNONYMS:
    _SYNONYM_TO_OFFICIAL.setdefault(_alias, set()).add(_official)
    _SYNONYM_TO_OFFICIAL.setdefault(_official, set()).add(_alias)


def normalize(text):
    """归一化：全角转半角、转小写、去标点与空格。

    效果：`ak-74m`、`AK 74M`、`ＡＫ７４Ｍ` 归一化后是同一个字符串。
    """
    if not text:
        return ""
    # NFKC 会把全角英数字折叠成半角，兼容全角空格
    folded = unicodedata.normalize("NFKC", str(text))
    lowered = folded.lower()
    # 去标点，得到"紧凑串"，用来做子串匹配
    compact = _PUNCT_RE.sub("", lowered)
    return compact


def expand_synonyms(normalized_query):
    """同义词扩展：返回一个查询串列表（含原串）。"""
    forms = [normalized_query]
    for alias, officials in _SYNONYM_TO_OFFICIAL.items():
        alias_norm = normalize(alias)
        if not alias_norm:
            continue
        if alias_norm in normalized_query or normalized_query in alias_norm:
            for official in officials:
                forms.append(normalize(official))
    # 去重但保持顺序
    seen = set()
    unique = []
    for form in forms:
        if form and form not in seen:
            seen.add(form)
            unique.append(form)
    return unique


def _length_penalty(name, query):
    """名称在查询词之外还拖了多少，拖得越多扣得越多，**最多扣 -6**。

    只算"查询词没覆盖到的那部分尾巴"。比如搜 `消音器`：
        "SureFire SOCOM556-MONSTER 5.56x45 消音器" → 尾巴很长，扣分
        "消音器" → 尾巴为零，不扣
    这样"名字里确实含查询词"这个强信号不会被惩罚吃掉
    （之前是从头算全长，搜"消音器"时整项被扣 -6，召回分 +8 直接归零，
    最后所有消音器都是 0 分，退化成按库顺序乱排）。
    """
    if not query:
        return 0
    # 查询词在名称里的位置：找到就从它的末尾开始算尾巴
    position = name.find(query)
    if position >= 0:
        tail = len(name) - (position + len(query))
    else:
        tail = len(name)
    if tail <= 0:
        return 0
    raw = SCORE_NAME_MAX * (tail / 12.0)
    return int(round(max(SCORE_NAME_MAX, raw)))


def _query_wants(query, words):
    """查询词自己是不是就在找这一类东西。

    搜「消音器」时，命中"消音器"的物品是**用户要的**；
    搜「m4a1」时，同名配件是**用户不要的**。
    所以配件词的扣分必须让位给查询词的意图，否则搜「消音器」会把
    真消音器扣下去、反让「消音手枪」（含"手枪"武器词）排到第一。
    """
    for word in words:
        if word in query:
            return True
    return False


def score_item(item, query):
    """给单个物品打分。返回整数分。score_item 只管打分，不做召回。"""
    short_norm = normalize(item.get("short_name", ""))
    name_zh = item.get("name_zh", "") or ""
    name_en = item.get("name_en", "") or ""
    name_zh_norm = normalize(name_zh)
    name_en_norm = normalize(name_en)

    score = 0

    # short_name 完全 / 前缀匹配 —— 最高权重
    if short_norm and short_norm == query:
        score += SCORE_EXACT + SCORE_FIELD_BONUS
    elif short_norm and short_norm.startswith(query):
        score += SCORE_PREFIX + SCORE_FIELD_BONUS

    # 中文名直接含查询词：仅次于 short_name 命中
    if query and query in name_zh_norm:
        score += SCORE_NAME_CONTAINS
    elif query and query in name_en_norm:
        score += SCORE_EN_CONTAINS

    # 武器词 / 配件词：只看中文名和短名，不看英文名
    display = name_zh + " " + (item.get("short_name", "") or "")
    wants_weapon = _query_wants(query, WEAPON_WORDS)
    wants_part = _query_wants(query, PART_WORDS)

    hit_weapon = False
    for word in WEAPON_WORDS:
        if word in display:
            hit_weapon = True
            break
    hit_part = False
    for word in PART_WORDS:
        if word in display:
            hit_part = True
            break

    # 词类调整要看用户的**查询意图**，不能只看命中了什么：
    #   搜「m4a1」  → 用户要枪，命中"消音器"要扣分
    #   搜「消音器」→ 用户要配件，命中"消音器"要加分，命中"手枪"要扣分
    # 之前只判了 wants_weapon，wants_part 算完就扔了（死变量），
    # 于是搜「消音器」时真消音器反被扣 -10，排第一的成了「消音手枪」
    if wants_weapon:
        # 用户在找武器：命中武器词加分、命中配件词扣分
        if hit_weapon:
            score += SCORE_WEAPON
        elif hit_part:
            score += SCORE_PART
    elif wants_part:
        # 用户在找配件：命中配件词加分、命中武器词扣分
        if hit_part:
            score += SCORE_WEAPON
        elif hit_weapon:
            score += SCORE_PART
    else:
        # 用户没指明武器或配件：命中武器词加分、命中配件词扣分
        if hit_weapon and not hit_part:
            score += SCORE_WEAPON
        elif hit_part and not hit_weapon:
            score += SCORE_PART
        # 两类都命中（"消音手枪"之于"消音器"）或都没命中：不动分数，
        # 交给召回分和尾巴惩罚去拉开差距

    # 长度惩罚取中英文名里较短的，避免长英文名拖累
    shorter_name = name_zh_norm if len(name_zh_norm) <= len(name_en_norm) else name_en_norm
    score += _length_penalty(shorter_name, query)

    return score


class SearchIndex:
    """物品搜索索引。

    建索引只为了一次遍历能快速筛出"可能相关"的候选，真正的排序靠规则打分。
    中英文各存一份归一化名，采用模糊子串匹配—— 打错字也能召回。
    """

    def __init__(self, items):
        self.items = items
        self.entries = []
        for item in items:
            short_norm = normalize(item.get("short_name", ""))
            zh_norm = normalize(item.get("name_zh", ""))
            en_norm = normalize(item.get("name_en", ""))
            # 至少有一个字段能匹配才有意义
            self.entries.append((item, short_norm, zh_norm, en_norm))

    def search(self, raw_query, top_n=5):
        """搜索。返回 [(物品, 分数), ...]，按分数从高到低。

        归一化后不足 2 个字符直接返回空——防单字符污染（和历史记录同一条约束）。
        """
        query = normalize(raw_query)
        if len(query) < 2:
            return []

        forms = expand_synonyms(query)
        # 原形排在第一个：同分时原形命中的应当优先（查"护甲"时"防弹衣维修套件"
        # 靠同义词召回，但不该排在真护具前面）
        for form in forms:
            if form != query:
                forms.remove(form)
                forms.insert(0, form)
                break

        matched = {}
        for item, short_norm, zh_norm, en_norm in self.entries:
            best = 0
            hit = False
            for position, form in enumerate(forms):
                if not form:
                    continue
                field_score = self._match(item, short_norm, zh_norm, en_norm, form)
                if field_score is None:
                    continue
                # 同义词形式降权：原形之外的都打八折，
                # 免得"护甲"→"防弹衣"这条扩展把维修套件顶到真护具前面
                weight = 1.0 if position == 0 else 0.8
                weighted = int(field_score * weight)
                if weighted > best:
                    best = weighted
                hit = True
            if hit:
                matched[id(item)] = (item, best)

        ordered = sorted(matched.values(), key=lambda pair: pair[1], reverse=True)
        return ordered[:top_n]

    @staticmethod
    def _match(item, short_norm, zh_norm, en_norm, form):
        """单个查询形式对单个物品的匹配分。没命中返回 None。"""
        if short_norm and (short_norm == form or short_norm in form or form in short_norm):
            return score_item(item, form)
        if zh_norm and (zh_norm == form or zh_norm in form or form in zh_norm):
            return score_item(item, form)
        if en_norm and (en_norm == form or en_norm in form or form in en_norm):
            return score_item(item, form)
        return None


def format_price(value):
    """价格格式化：千分位 +卢布符号。"""
    if not value:
        return "暂无均价"
    return "{:,} ₽".format(int(value))