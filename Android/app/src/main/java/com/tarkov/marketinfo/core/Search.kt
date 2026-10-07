package com.tarkov.marketinfo.core

import java.text.Normalizer as JavaNormalizer

/**
 * 搜索链 —— 从五千多条物品里挑出最可能的 5 个候选。
 *
 * 整条链**全程本地、同步返回**，界面上不等待网络：
 *
 *     归一化 → 同义词扩展 → 索引召回 → 规则打分 → Top5
 *
 * 规则打分是纯手工加权（不用机器学习）。核心原因是字符串相似度分不开
 * 「M4A1 卡宾枪」和「M4A1 前准星」—— 必须靠武器词 / 配件词人为加分减分。
 *
 * 本文件是**移植自桌面端 `src/search.py`**（v1.2，打分表与三个规则细节完全对齐），
 * 不是重写。改规则时两边都要改，否则同一个查询在两个端排序会不一样。
 */

/** 归一化时要去掉的标点与空白（中英文都算） */
private val PUNCT_CHARS = setOf(
    ' ', '\t', '\n', '\r', '-', '_', '.', ',', ':', ';', '(', ')', '[', ']', '{', '}',
    '!', '?', '，', '。', '！', '？', '、', '·', '/', '\\', '|',
)

// ---------- 打分权重 ----------
/** short_name 完全匹配 */
const val SCORE_EXACT = 30

/** short_name 前缀匹配 */
const val SCORE_PREFIX = 14

/** 中文名里直接含查询词 */
const val SCORE_NAME_CONTAINS = 8

/** 只有英文名含查询词（比中文名弱） */
const val SCORE_EN_CONTAINS = 3

/** short_name 命中比长名命中更可信 */
const val SCORE_FIELD_BONUS = 4

/** 命中武器词 */
const val SCORE_WEAPON = 10

/** 命中配件词 */
const val SCORE_PART = -10

/** 名称过长的最大惩罚 */
const val SCORE_NAME_MAX = -6

/** 武器词：压过同名配件 */
val WEAPON_WORDS = listOf(
    "卡宾枪", "突击步枪", "步枪", "冲锋枪", "手枪", "狙击", "霰弹", "机枪",
    "左轮", "霰弹枪", "自动霰弹枪", "手枪",
)

/** 配件词：往后排 */
val PART_WORDS = listOf(
    "转接器", "护木", "握把", "枪托", "消音", "瞄准镜", "弹匣", "准星",
    "机匣", "枪管", "枪口", "扳机", "复进簧", "导轨", "侧导轨",
    "消音器", "瞄准镜座", "背带", "握把套", "弹匣套", "消音器基座",
)

/** 同义词（双向）。官方译名和玩家俗称对不上：玩家打「显卡」，官方叫「显示卡」。 */
private val SYNONYMS = listOf(
    "显卡" to "显示卡",
    "显卡" to "图形卡",
    "子弹" to "弹药",
    "子弹" to "子弹头",
    "护甲" to "防弹衣",
    "护甲" to "防弹背心",
    "急救" to "急救包",
    "急救" to "治疗包",
    "药" to "止痛药",
    "药" to "药剂",
    "药" to "药品",
    "镜" to "瞄准镜",
    "消音器" to "消音",
    "握把" to "手枪握把",
    "弹匣" to "弹匣",
    "头盔" to "头盔",
    "钥匙" to "钥匙",
    "容器" to "容器",
    "背包" to "背包",
    "胸挂" to "胸挂",
    "干粮" to "食物",
    "水" to "纯净水",
    "面" to "罐装六可乐",
)

/** 反查表：官方名 → 俗称集合。反查也自动成立，所以不用手写反向条目。 */
private val SYNONYM_TO_OFFICIAL: Map<String, Set<String>> = run {
    // 不能用 Map.putMerge：那是 Java 8 的 default 方法，Kotlin 的 buildMap 接收者是
    // MutableMap，编译器不认。手动 accumulate 更直白。
    val acc = HashMap<String, MutableSet<String>>()
    for ((alias, official) in SYNONYMS) {
        // 自环条目（比如 "弹匣" to "弹匣"）会把自己加进自己，
        // 这跟桌面端 setOf(alias) 的行为一致，搜索时会被去重掉，不影响结果。
        acc.getOrPut(alias) { HashSet() }.add(official)
        acc.getOrPut(official) { HashSet() }.add(alias)
    }
    acc
}

/**
 * 归一化：全角转半角、转小写、去标点与空格。
 *
 * 效果：`ak-74m`、`AK 74M`、`ＡＫ７４Ｍ` 归一化后是同一个字符串。
 *
 * 桌面端用 Python 的 NFKC，Android 这边用 java.text.Normalizer 的 NFKC。
 * 两者对全角英数字的折叠结果一致；NFKC 对中文全角标点也会折叠，
 * 所以上面 PUNCT_CHARS 里的中文标点在折叠后基本不会被命中，留着是为了兜底。
 */
fun normalize(text: String?): String {
    if (text.isNullOrEmpty()) return ""
    val folded = JavaNormalizer.normalize(text, JavaNormalizer.Form.NFKC)
    val lowered = folded.lowercase()
    val sb = StringBuilder(lowered.length)
    for (ch in lowered) {
        if (ch !in PUNCT_CHARS) sb.append(ch)
    }
    return sb.toString()
}

/**
 * 同义词扩展：返回一个查询串列表（含原串）。
 *
 * 原串永远在第 0 位，后面是同义词形式。同义词形式在打分时会降权到 0.8。
 */
fun expandSynonyms(normalizedQuery: String): List<String> {
    val forms = mutableListOf(normalizedQuery)
    for ((alias, officials) in SYNONYM_TO_OFFICIAL) {
        val aliasNorm = normalize(alias)
        if (aliasNorm.isEmpty()) continue
        if (normalizedQuery.contains(aliasNorm) || aliasNorm.contains(normalizedQuery)) {
            for (official in officials) forms.add(normalize(official))
        }
    }
    // 去重但保持顺序
    return forms.filter { it.isNotEmpty() }.distinct()
}

/**
 * 名称在查询词之外还拖了多少，拖得越多扣得越多，**最多扣 -6**。
 *
 * 只算"查询词没覆盖到的那部分尾巴"。比如搜 `消音器`：
 *     "SureFire SOCOM556-MONSTER 5.56x45 消音器" → 尾巴很长，扣分
 *     "消音器" → 尾巴为零，不扣
 *
 * 这样"名字里确实含查询词"这个强信号不会被惩罚吃掉。桌面端踩过这个坑：
 * 之前是从头算全长，搜"消音器"时整项被扣 -6，召回分 +8 直接归零，
 * 最后所有消音器都是 0 分，退化成按库顺序乱排。
 */
/**
 * Python `round()` 的四舍六入五成双，不是 Java 的 `Math.round`。
 *
 * 这不是细节洁癖，是**排序错一格**的实测坑：
 * 搜 `m4` 时 M4A1 的长度惩罚是 -5.5，
 * `Math.round(-5.5)` 给 -5（M4A1 拿 31 分，压过 M45A1 的 31 分排到第一），
 * `round(-5.5)` 给 -6（M4A1 拿 30 分，M45A1 的 31 分正常排第一），
 * 跟桌面端结果反了。
 */
private fun pyRound(value: Double): Int {
    val floor = Math.floor(value)
    val diff = value - floor
    return when {
        diff > 0.5 -> (floor + 1).toInt()
        diff < 0.5 -> floor.toInt()
        // 正好 .5：进到偶数的那一边
        else -> {
            val lower = floor.toInt()
            if (lower % 2 == 0) lower else lower + 1
        }
    }
}

private fun lengthPenalty(name: String, query: String): Int {
    if (query.isEmpty()) return 0
    val position = name.indexOf(query)
    // 查询词在名称里的位置：找到就从它的末尾开始算尾巴
    val tail = if (position >= 0) name.length - (position + query.length) else name.length
    if (tail <= 0) return 0
    val raw = SCORE_NAME_MAX * (tail / 12.0)
    return pyRound(maxOf(SCORE_NAME_MAX.toDouble(), raw))
}

/**
 * 查询词自己是不是就在找这一类东西。
 *
 * 搜「消音器」时，命中"消音器"的物品是**用户要的**；
 * 搜「m4a1」时，同名配件是**用户不要的**。
 *
 * 所以配件词的扣分必须让位给查询词的意图，否则搜「消音器」会把真消音器扣下去、
 * 反让「消音手枪」（含"手枪"武器词）排到第一。这是桌面端修过的三个坑之一。
 */
private fun queryWants(query: String, words: List<String>): Boolean =
    words.any { query.contains(it) }

/** 给单个物品打分。返回整数分。只管打分，不做召回。 */
fun scoreItem(item: Item, query: String): Int {
    val shortNorm = normalize(item.shortName)
    val nameZh = item.nameZh
    val nameEn = item.nameEn
    val nameZhNorm = normalize(nameZh)
    val nameEnNorm = normalize(nameEn)

    var score = 0

    // short_name 完全 / 前缀匹配 —— 最高权重
    if (shortNorm.isNotEmpty() && shortNorm == query) {
        score += SCORE_EXACT + SCORE_FIELD_BONUS
    } else if (shortNorm.isNotEmpty() && shortNorm.startsWith(query)) {
        score += SCORE_PREFIX + SCORE_FIELD_BONUS
    }

    // 中文名直接含查询词：仅次于 short_name 命中
    if (query.isNotEmpty() && nameZhNorm.contains(query)) {
        score += SCORE_NAME_CONTAINS
    } else if (query.isNotEmpty() && nameEnNorm.contains(query)) {
        score += SCORE_EN_CONTAINS
    }

    // 武器词 / 配件词：只看中文名和短名，不看英文名
    val display = nameZh + " " + item.shortName
    val wantsWeapon = queryWants(query, WEAPON_WORDS)
    val wantsPart = queryWants(query, PART_WORDS)

    val hitWeapon = WEAPON_WORDS.any { display.contains(it) }
    val hitPart = PART_WORDS.any { display.contains(it) }

    // 词类调整要让位给查询词的意图：用户敲「消音器」就是要配件，敲「m4a1」是要枪。
    //
    // ⚠️ 这里和桌面端 v1.2 **有意不同**：桌面端算了个 wants_part 但从来没参与判断
    // （`src/search.py` 第 175 行赋值后全文再无引用，是死变量），
    // 于是搜「消音器」时真消音器反被扣 -10：
    //   Bramit莫辛步枪消音器   8 分  ← 排第一，但它其实把消音器当步枪名字的一部分
    //   PB 9x18PM消音手枪      -6 分
    //   SureFire SOCOM556 消音器 -8 分  ← 真·消音器排到第 6 位，用户还得往下翻
    // 移动端把 wants_part 接上，搜「消音器」时真消音器回到第一。
    // 桌面端要不要跟着修，等用户拍板，这里先不互相改。
    if (wantsWeapon) {
        // 用户在找武器：命中武器词加分、命中配件词扣分
        if (hitWeapon) score += SCORE_WEAPON else if (hitPart) score += SCORE_PART
    } else if (wantsPart) {
        // 用户在找配件：命中配件词加分、命中武器词扣分
        if (hitPart) score += SCORE_WEAPON else if (hitWeapon) score += SCORE_PART
    } else {
        // 用户没指明武器或配件
        if (hitWeapon && !hitPart) {
            score += SCORE_WEAPON
        } else if (hitPart && !hitWeapon) {
            score += SCORE_PART
        }
        // 两类都命中（"消音手枪"之于"消音器"）或都没命中：不动分数，
        // 交给召回分和尾巴惩罚去拉开差距
    }

    // 长度惩罚取中英文名里较短的，避免长英文名拖累
    val shorterName = if (nameZhNorm.length <= nameEnNorm.length) nameZhNorm else nameEnNorm
    score += lengthPenalty(shorterName, query)

    return score
}

/** 一条索引项：物品本体 + 三份归一化名，避免每次打分都重新归一化 */
private data class Entry(
    val item: Item,
    val shortNorm: String,
    val zhNorm: String,
    val enNorm: String,
)

/**
 * 物品搜索索引。
 *
 * 建索引只为了一次遍历能快速筛出"可能相关"的候选，真正的排序靠规则打分。
 * 中英文各存一份归一化名，采用模糊子串匹配 —— 打错字也能召回。
 *
 * 全量放内存：5476 项约 1MB，构建一次几毫秒，查一次也是几毫秒。
 * 桌面端是同样的做法（`search.SearchIndex`）。
 */
class SearchIndex(items: List<Item>) {

    private val entries: List<Entry> = items.map { item ->
        Entry(
            item = item,
            shortNorm = normalize(item.shortName),
            zhNorm = normalize(item.nameZh),
            enNorm = normalize(item.nameEn),
        )
    }

    /**
     * 搜索。返回 [(物品, 分数)] 按分数从高到低。
     *
     * 归一化后不足 [MIN_SEARCH_CHARS] 个字符直接返回空 —— 防单字符污染
     * （和历史记录同一条约束）。
     */
    fun search(rawQuery: String, topN: Int = 5): List<ScoredItem> {
        val query = normalize(rawQuery)
        if (query.length < MIN_SEARCH_CHARS) return emptyList()

        // 原形必须排第一：同分时原形命中的应当优先（查"护甲"时"防弹衣维修套件"
        // 靠同义词召回，但不该排在真护具前面）。
        // 桌面端这里是 list.remove + list.insert 边遍历边改，
        // 换到 Kotlin 必须先算出原形下标再重排，否则会漏元素。
        val expanded = expandSynonyms(query)
        val forms = mutableListOf<String>()
        forms.add(query)
        for (form in expanded) {
            if (form != query) forms.add(form)
        }

        // 物品 id → (物品, 最好分数)。同一物品可能被多个查询形式召回，取最高分
        val best = HashMap<String, ScoredItem>(entries.size)
        for (entry in entries) {
            var topScore = 0
            var hit = false
            for ((position, form) in forms.withIndex()) {
                if (form.isEmpty()) continue
                val fieldScore = match(entry, form) ?: continue
                // 同义词形式降权：原形之外的都打八折，
                // 免得"护甲"→"防弹衣"这条扩展把维修套件顶到真护具前面
                val weight = if (position == 0) 1.0 else 0.8
                val weighted = pyRound(fieldScore * weight)
                if (weighted > topScore) topScore = weighted
                hit = true
            }
            if (hit) {
                val previous = best[entry.item.id]
                if (previous == null || topScore > previous.score) {
                    best[entry.item.id] = ScoredItem(entry.item, topScore)
                }
            }
        }

        // 同分时保持原顺序（用 id 做稳定 tiebreak，避免每次搜索顺序乱跳）
        return best.values
            .sortedWith(compareByDescending<ScoredItem> { it.score }.thenBy { it.item.id })
            .take(topN)
    }

    /** 单个查询形式对单个物品的匹配分。没命中返回 null。 */
    private fun match(entry: Entry, form: String): Int? {
        val s = entry.shortNorm
        val z = entry.zhNorm
        val e = entry.enNorm
        if (s.isNotEmpty() && (s == form || s.contains(form) || form.contains(s))) {
            return scoreItem(entry.item, form)
        }
        if (z.isNotEmpty() && (z == form || z.contains(form) || form.contains(z))) {
            return scoreItem(entry.item, form)
        }
        if (e.isNotEmpty() && (e == form || e.contains(form) || form.contains(e))) {
            return scoreItem(entry.item, form)
        }
        return null
    }
}

/** 打分后的物品 */
data class ScoredItem(val item: Item, val score: Int)