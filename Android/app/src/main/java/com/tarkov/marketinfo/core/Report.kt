package com.tarkov.marketinfo.core

/**
 * 排行报表的筛选、排序、分类 —— 移植自桌面端 `src/data.py`。
 *
 * 桌面端把 `trader_best`（商人最高收购价）作为**派生字段预先算好**放进 item dict，
 * 排序时直接用它；这边不存派生字段，排序取价时现算（[sortValue]）。
 * 结果完全一致，但少一份可能不一致的冗余数据。
 */

/** 排序口径。label 是界面显示名，key 是 [sortValue] 认识的字段名。 */
enum class SortField(val label: String) {
    AVG24H("跳蚤均价"),
    LOW24H("24h 最低价"),
    HIGH24H("24h 最高价"),
    OFFER_COUNT("挂单数量"),
    TRADER_BEST("商人最高收购价"),
    BASE_PRICE("物品基准价"),
}

/** 报表筛选条件 */
data class ReportOptions(
    val sortField: SortField = SortField.AVG24H,
    val descending: Boolean = true,
    /** 取前多少条，0 表示不限制 */
    val limit: Int = 50,
    /** 名称关键词，空字符串表示不过滤 */
    val keyword: String = "",
    /** 是否只要能在跳蚤市场交易的 */
    val fleaOnly: Boolean = true,
    /** 是否跳过排序字段为 0 的条目 */
    val skipZero: Boolean = true,
    /** 排序字段的最小值门槛 */
    val minPrice: Int = 0,
    /** 按大类归并展示（否则平铺列表）。桌面端是「分类」下拉框。 */
    val groupByCategory: Boolean = false,
    /** 涨跌幅榜：是否要「涨得最多」那一栏 */
    val showGainers: Boolean = true,
    /** 涨跌幅榜：是否要「跌得最多」那一栏 */
    val showLosers: Boolean = true,
)

/** 取排序用的值。商人最高收购价是现算的（桌面对应 `trader_best` 派生字段）。 */
fun sortValue(item: Item, field: SortField): Int = when (field) {
    SortField.AVG24H -> item.avg24h
    SortField.LOW24H -> item.low24h
    SortField.HIGH24H -> item.high24h
    SortField.OFFER_COUNT -> item.offerCount
    SortField.TRADER_BEST -> bestTraderPrice(item.sellJson)
    SortField.BASE_PRICE -> item.basePrice
}

/**
 * 按条件过滤 + 排序 + 截断。
 *
 * 和桌面端 `data.search_items` 行为一致，包括关键词匹配是
 * 「中文名 + 英文名 + 短名 拼起来取小写后判断包含」这种粗粒度做法。
 */
fun searchItems(items: List<Item>, options: ReportOptions): List<Item> {
    val keyword = options.keyword.trim().lowercase()
    val matched = ArrayList<Item>()

    for (item in items) {
        if (options.fleaOnly && !item.fleaEnabled) continue

        val value = sortValue(item, options.sortField)
        if (options.skipZero && value <= 0) continue
        if (value < options.minPrice) continue

        if (keyword.isNotEmpty()) {
            val haystack = (item.nameZh + " " + item.nameEn + " " + item.shortName).lowercase()
            if (!haystack.contains(keyword)) continue
        }

        matched.add(item)
    }

    // 稳定排序：分数相同时保持原顺序（同分太多，不加 tiebreak 会让行序乱跳）
    matched.sortWith(
        if (options.descending) {
            compareByDescending { sortValue(it, options.sortField) }
        } else {
            compareBy { sortValue(it, options.sortField) }
        }
    )

    return if (options.limit > 0) matched.take(options.limit) else matched
}

/**
 * 48h涨跌榜：从能上跳蚤、且有价格的物品里取涨跌幅前后各 [count] 名。
 *
 * 涨跌两侧**各自按符号过滤**，没勾的一侧给空列表。
 *
 * ⚠️ 这里和桌面端 v1.2 **有意不同**：桌面端 `data.top_movers` 的 `pool` 只过滤了
 * "非零涨跌"，没按正负分开，只靠排序后取前N / 后N。真实数据里涨的物品数远多于
 * `count`，所以看不出来；但只勾"涨"时，pool 前N 里混进了跌 40% 的物品
 * （实测：只勾涨，count=5，返回 `['u1', 'd1']`）。移动端按符号切干净。
 */
fun topMovers(
    items: List<Item>,
    wantedUp: Boolean,
    wantedDown: Boolean,
    count: Int = 10,
): Pair<List<Item>, List<Item>> {
    // 涨跌幅为零表示"接口没给涨跌"，不是"没涨没跌"，两端都排除
    val pool = items.filter { it.fleaEnabled && it.avg24h > 0 && it.change48hPct != 0.0 }
    val up = if (wantedUp) {
        pool.filter { it.change48hPct > 0.0 }
            .sortedByDescending { it.change48hPct }
            .take(count)
    } else {
        emptyList()
    }
    val down = if (wantedDown) {
        pool.filter { it.change48hPct < 0.0 }
            .sortedBy { it.change48hPct }
            .take(count)
    } else {
        emptyList()
    }
    return up to down
}

// ---------- 分类归并 ----------

/**
 * 接口的 types 是 26 个 slug，里面混着「能装备」「不能上跳蚤」这类纯标记，
 * 直接摆出来用户看不懂，所以按顺序归成直觉大类；**一个物品只落到第一个命中的类**。
 *
 * 顺序即优先级，也决定下拉框的排列。桌面端是 `data.CATEGORY_ORDER`。
 */
val CATEGORY_ORDER: List<Pair<String, List<String>>> = listOf(
    "枪械" to listOf("gun"),
    "弹药" to listOf("ammo", "ammoBox"),
    "护甲与头盔" to listOf("armor", "armorPlate", "helmet"),
    "面具眼镜" to listOf("glasses"),
    "耳机" to listOf("headphones"),
    "背包胸挂" to listOf("backpack", "rig"),
    "医疗" to listOf("meds", "injectors"),
    "食品" to listOf("provisions"),
    "钥匙" to listOf("keys"),
    "手雷" to listOf("grenade"),
    "容器" to listOf("container"),
    "配件" to listOf("mods", "pistolGrip", "suppressor"),
    "海报" to listOf("poster"),
    "武器预设" to listOf("preset"),
    "交换用物品" to listOf("barter"),
)

const val OTHER_CATEGORY = "其他"

/** 类型标签 → (优先级, 类名) */
private val CATEGORY_BY_TAG: Map<String, Pair<Int, String>> = buildMap {
    CATEGORY_ORDER.forEachIndexed { rank, (_, tags) ->
        for (tag in tags) put(tag, rank to CATEGORY_ORDER[rank].first)
    }
}

/** 把一个物品归到某个大类的名字上（按 CATEGORY_ORDER 的先后定优先级） */
fun itemCategory(item: Item): String {
    var best: Pair<Int, String>? = null
    for (tag in itemTags(item)) {
        val found = CATEGORY_BY_TAG[tag] ?: continue
        if (best == null || found.first < best.first) best = found
    }
    return best?.second ?: OTHER_CATEGORY
}

/** 解析 types_json 字符串成标签列表。坏数据当空，不抛异常。 */
fun itemTags(item: Item): List<String> {
    if (item.typesJson.isBlank()) return emptyList()
    return parseStringArray(item.typesJson)
}

/** 一个分类下的一堆物品 */
data class CategoryGroup(val name: String, val items: List<Item>)

/**
 * 按大类分堆，每堆取前 [limit] 条（limit <= 0 表示不截断）。
 *
 * items 得是已经排好序的列表，分堆时保持这个顺序。
 * 返回 [(类名, 物品列表)]；空类不出现，顺序固定。
 *
 * **不变量**：同一件物品不会出现在两个分类里（按 CATEGORY_ORDER 优先级只落第一个）。
 */
fun groupByType(items: List<Item>, limit: Int): List<CategoryGroup> {
    val buckets = LinkedHashMap<String, MutableList<Item>>()
    for (item in items) {
        val name = itemCategory(item)
        buckets.getOrPut(name) { ArrayList() }.add(item)
    }

    val groups = ArrayList<CategoryGroup>()
    for ((name, categoryItems) in buckets) {
        val picked = if (limit > 0) categoryItems.take(limit) else categoryItems
        groups.add(CategoryGroup(name, picked))
    }

    // 固定成 CATEGORY_ORDER 的顺序，「其他」永远在最后
    val order = CATEGORY_ORDER.map { it.first }
    groups.sortWith(
        compareBy(
            { g -> order.indexOf(g.name).let { if (it < 0) Int.MAX_VALUE else it } },
            { g -> if (g.name == OTHER_CATEGORY) 1 else 0 }
        )
    )
    return groups
}

/**
 * 极简 JSON 字符串数组解析：`["gun","wearable"]`。坏数据当空。
 *
 * 只认引号里的内容，引号外的逗号和空格全是分隔噪声。
 * 别用 org.json：core 层要能在纯 JVM 单元测试里跑，org.json 在 Android 上是 stub。
 */
internal fun parseStringArray(json: String): List<String> {
    val trimmed = json.trim()
    if (!trimmed.startsWith("[") || !trimmed.endsWith("]")) return emptyList()
    val body = trimmed.substring(1, trimmed.length - 1)
    val out = ArrayList<String>()
    val sb = StringBuilder()
    var inQuote = false
    var i = 0
    while (i < body.length) {
        val ch = body[i]
        when {
            // 引号内的反斜杠转义：把下一个字符原样收进来
            ch == '\\' && inQuote && i + 1 < body.length -> {
                sb.append(body[i + 1]); i += 2
            }
            ch == '"' -> {
                // 只在**闭合**引号时收一个元素。
                // 开启引号时也收一次的话，`["gun","wearable"]` 会变成
                // ["", "gun", ",", ",", "wearable"]（实测踩过）。
                if (inQuote) {
                    if (sb.isNotEmpty()) out.add(sb.toString())
                    sb.setLength(0)
                }
                inQuote = !inQuote
                i++
            }
            inQuote -> {
                sb.append(ch); i++
            }
            else -> {
                // 引号外：逗号、空格、[、] 都直接跳过
                i++
            }
        }
    }
    return out
}

/** 不是所有物品都能上跳蚤市场，这两个阈值用来判断流动性 */
const val LIQUIDITY_GOOD = 10
const val LIQUIDITY_MID = 3

/** 按挂单数给出流动性等级。 */
enum class Liquidity(val label: String) {
    GOOD("流通好"),
    MID("流通一般"),
    LOW("几乎无挂单");

    companion object {
        fun of(offerCount: Int): Liquidity = when {
            offerCount >= LIQUIDITY_GOOD -> GOOD
            offerCount >= LIQUIDITY_MID -> MID
            else -> LOW
        }
    }
}