package com.tarkov.marketinfo.core

/**
 * 物品数据模型。
 *
 * 字段与桌面端 `tarkov.db` 的 `items` 表一一对应，
 * 少了 `sell_json` 的解析结果（`traderBest`）在 [traderNames] 里现场算。
 *
 * 这个类放在 core 而不是 data 包，因为它被搜索和取价两个纯逻辑共用，
 * 不该依赖 Room 或任何 Android 类型（这样单元测试不需要 Robolectric）。
 */
data class Item(
    val id: String,
    val shortName: String,
    val nameZh: String,
    val nameEn: String,
    /** 24 小时均价。没有价格数据的物品是 0。 */
    val avg24h: Int,
    val low24h: Int,
    val high24h: Int,
    val offerCount: Int,
    /** 能否上跳蚤市场 */
    val fleaEnabled: Boolean,
    /** 能否上跳蚤的解锁等级 */
    val minLevelFlea: Int,
    val basePrice: Int,
    /** 商人回收价明细，JSON 串：{"商人名": 最高收购价}。解析失败当空。 */
    val sellJson: String,
    /** 48 小时涨跌额与涨跌幅（百分比，可能是极大值——没有做阈值过滤） */
    val change48h: Int,
    val change48hPct: Double,
    /** 物品类型标签数组的 JSON 串，如 ["gun","wearable"] */
    val typesJson: String,
)

/** 价格快照：界面上要显示的那几个数字 */
data class Quote(
    val avg24h: Int,
    val low24h: Int,
    val high24h: Int,
    /** 商人回收价：玩家「卖给商人」能拿到的钱，不是买入成本 */
    val traderPrice: Int,
    val offerCount: Int,
    val fleaEnabled: Boolean,
    val basePrice: Int,
    /** 有没有真实价格。false 时界面显示「暂无均价」而不是 ₽0 */
    val hasPrice: Boolean,
)

/** 商人明细的一行 */
data class TraderRow(val name: String, val price: Int)

/** 曲线上的一点：Unix 秒 + 均价 */
data class PricePoint(val timestamp: Long, val price: Int)

/**
 * 取价链 —— 选中物品后拿到价格、商人价、历史曲线。
 *
 * 核心性能设计：**不联网也能出完整价格**。
 * 启动时拉的那份全量数据本身就带每个物品的 24h 均价和商人价，
 * 所以点开一个物品，价格本地就有，毫秒级显示。
 *
 * 只有历史曲线需要额外请求接口（实测 1.1~1.6 秒），放后台慢慢拉，回来再补上曲线。
 *
 * 四级回退（与桌面端 `src/price.py` 一致）：
 *     1 本地全量缓存  免费、毫秒级，含 24h 价 + 商人价
 *     2 本地历史缓存  1 小时内有效，用于补曲线
 *     3 联网拉取      补历史数据，失败则跳过
 *     4 空占位        显示「暂无均价」，不显示 ₽0 误导用户
 *
 * 第 4 级的考量：非跳蚤市场物品本来就没有均价，显示「暂无均价」比显示 ₽0 更诚实。
 *
 * **与桌面端的差异**：桌面端存`trader_best`（load_all_items 现场从 sell_json 算的
 * 一个数），Android 端不存这个派生字段，由 [localQuote] 每次从 sellJson 算。
 * 理由是它可由原始字段推导，存两份就有不一致的风险。
 */

/** 历史价格本地缓存的时效：1 小时内直接复用，不重新请求 */
const val HISTORY_TTL_SECONDS = 3600L

/** 曲线只画最近 7 天（接口返回的是全量历史，1000+ 条，全画没法看） */
const val HISTORY_DAYS = 7

/**
 * 从本地全量数据取价。**永远立刻返回，不联网。**
 *
 * 和桌面端 [local_quote] 行为一致，包括"没有价格就返回 hasPrice=false"。
 */
fun localQuote(item: Item): Quote {
    val avg = item.avg24h
    return Quote(
        avg24h = avg,
        low24h = item.low24h,
        high24h = item.high24h,
        traderPrice = traderNames(item).firstOrNull()?.price ?: 0,
        offerCount = item.offerCount,
        fleaEnabled = item.fleaEnabled,
        basePrice = item.basePrice,
        hasPrice = avg > 0,
    )
}

/**
 * 商人回收价的明细：[(商人名, 价格)]，按价格从高到低。
 *
 * 口径是「卖给商人」能拿到的钱 —— 玩家关心能卖多少，不是买入成本。
 *
 * 桌面端 `trader_names` 里的 `isinstance(price_map, dict)` 判断，
 * Kotlin 侧靠 try/catch + 逐项类型检查达到同样效果：
 * sell_json 是数组 / null / 坏 JSON 时都当没有，不让整次查询崩掉。
 */
fun traderNames(item: Item): List<TraderRow> {
    if (item.sellJson.isBlank()) return emptyList()
    // org.json 在 Android 上可用，但单元测试跑在 JVM 上没有它。
    // 所以这里用手写的极简解析，只认 "名字": 数字 这种形态——
    // sell_json 本身就是程序自己写出来的，格式可控。
    val out = ArrayList<TraderRow>()
    parsePriceMap(item.sellJson) { name, price ->
        if (price > 0) out.add(TraderRow(name, price))
    }
    return out.sortedByDescending { it.price }
}

/** 商人回收价的最大值，没有就是 0 */
fun bestTraderPrice(sellJson: String): Int {
    var best = 0
    parsePriceMap(sellJson) { _, price -> if (price > best) best = price }
    return best
}

/**
 * 极简 JSON 对象解析：只处理 `{"名字": 数字, ...}`。
 *
 * 不引org.json 是为了让 core 层能在纯 JVM 单元测试里跑（org.json 需要 Robolectric）。
 * 名字里可能有转义引号（库里真有这种：`VOMZ P1X42 "WEAVER"`），
 * 所以名字部分要支持 \" 转义。
 */
private fun parsePriceMap(json: String, onEntry: (String, Int) -> Unit) {
    var i = 0
    val n = json.length

    fun skipWs() {
        while (i < n && (json[i] == ' ' || json[i] == '\n' || json[i] == '\r' || json[i] == '\t')) i++
    }

    fun readString(): String? {
        if (i >= n || json[i] != '"') return null
        i++ // 跳过起始引号
        val sb = StringBuilder()
        while (i < n) {
            val ch = json[i]
            when {
                ch == '\\' && i + 1 < n -> {
                    // 支持 \" \\ \/ \n \t，其余转义原样保留字符
                    val next = json[i + 1]
                    sb.append(
                        when (next) {
                            'n' -> '\n'
                            't' -> '\t'
                            'r' -> '\r'
                            else -> next
                        }
                    )
                    i += 2
                }
                ch == '"' -> {
                    i++
                    return sb.toString()
                }
                else -> {
                    sb.append(ch)
                    i++
                }
            }
        }
        return null // 没闭合，坏数据
    }

    skipWs()
    if (i >= n || json[i] != '{') return
    i++
    skipWs()

    while (i < n) {
        if (json[i] == '}') return
        val name = readString() ?: return
        skipWs()
        if (i >= n || json[i] != ':') return
        i++
        skipWs()
        // 读数字（整数；价格不会是浮点，也不该是）
        val start = i
        if (i < n && (json[i] == '-' || json[i] == '+')) i++
        while (i < n && json[i].isDigit()) i++
        if (i == start) return // 不是数字，当坏数据处理
        val value = json.substring(start, i).trim().toIntOrNull() ?: return
        onEntry(name, value)

        skipWs()
        if (i < n && json[i] == ',') {
            i++
            skipWs()
        }
    }
}

/** 金额格式化，带卢布符号和千分位。0 返回「暂无」而不是 ₽0 */
fun formatMoney(value: Int): String {
    if (value <= 0) return "暂无"
    return "%,d ₽".format(value)
}

/**
 * 从曲线算出涨跌摘要： (文案, 是否上涨)。
 *
 * 没有曲线时返回空列表 —— 界面就不显示这一块，而不是显示"持平 0%"。
 *
 * 和桌面端 `curve_summary` 阈值一致：|涨跌| < 0.5% 视为持平。
 */
fun curveSummary(points: List<PricePoint>): Pair<String, Boolean>? {
    if (points.size < 2) return null
    val firstPrice = points.first().price
    val lastPrice = points.last().price
    if (firstPrice <= 0) return null
    val pct = (lastPrice - firstPrice).toDouble() / firstPrice * 100.0
    return when {
        pct >= 0.5 -> "近 7 天上涨 %.1f%%".format(pct) to true
        pct <= -0.5 -> "近 7 天下跌 %.1f%%".format(-pct) to false
        else -> "近 7 天基本持平" to true
    }
}