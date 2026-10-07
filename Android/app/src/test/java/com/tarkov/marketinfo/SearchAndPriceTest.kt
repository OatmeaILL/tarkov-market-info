package com.tarkov.marketinfo.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 搜索 / 取价 / 筛选 的行为验证。
 *
 * 这些断言**逐条对照桌面端 `src/search.py` 和 `src/price.py` 的实际行为**，
 * 目的是保证同一个查询在两个端结果一致。桌面端改规则时，这里要跟着改。
 *
 * 用的样本物品名和真实库里的写法一致（含英文名里的连字符、带引号的名字）。
 */
class SearchAndPriceTest {

    // ---------- 测试样本 ----------

    private fun item(
        id: String = "id1",
        short: String = "",
        zh: String = "",
        en: String = "",
        avg: Int = 0,
        low: Int = 0,
        high: Int = 0,
        offers: Int = 0,
        flea: Boolean = true,
        base: Int = 0,
        sell: String = "",
        change: Int = 0,
        pct: Double = 0.0,
        types: String = "",
    ) = Item(
        id = id, shortName = short, nameZh = zh, nameEn = en,
        avg24h = avg, low24h = low, high24h = high, offerCount = offers,
        fleaEnabled = flea, minLevelFlea = 0, basePrice = base, sellJson = sell,
        change48h = change, change48hPct = pct, typesJson = types,
    )

    /** 真实库里存在的一组样本，排序预期来自桌面端实测结果 */
    private val samples = listOf(
        item("1", "M4A1", "柯尔特 M4A1 5.56x45 卡宾枪", "Colt M4A1 5.56x45 carbine", 61328, 4000, 123456, 42, base = 45000, types = """["gun","wearable"]"""),
        item("2", "M45A1", "柯尔特 M45A1 .45 ACP 手枪", "Colt M45A1 .45 ACP pistol", 30000, 2000, 90000, 12, base = 30000, types = """["gun"]"""),
        item("3", "M4A1 2k17 NY", "柯尔特 M4A1 5.56x45 卡宾枪 2k17 NY", "Colt M4A1 5.56x45 2k17 NY carbine", 120000, 90000, 150000, 5, base = 90000, types = """["gun","wearable"]"""),
        // 短名照抄真实库：库里是 "MONSTER" / "PB"，不是 "Suppressor SOCOM556"
        item("4", "MONSTER", "SureFire SOCOM556-MONSTER 5.56x45 消音器", "surefire-socom556-monster-556x45-sound-suppressor", 25000, 20000, 30000, 8, types = """["mods","suppressor"]"""),
        item("5", "SR1MP消基", "SR1MP消音器基座", "sr-1mp-sound-suppressor-mount", 8000, 6000, 9000, 2, types = """["mods"]"""),
        // 桌面端注释里点名的反例：两类词都命中（"消音" + "手枪"）
        item("6", "PB", "PB 9x18PM消音手枪", "pb-9x18pm-silenced-pistol", 26000, 22000, 31000, 15, types = """["gun","suppressor"]"""),
        item("7", "GPU", "显示卡", "Graphics card", 40000, 35000, 50000, 20, types = """["mod"]"""),
        item("8", "Ammo 7.62x51", "7.62x51 弹药包", "7.62x51 ammo pack", 5000, 4500, 6000, 100, types = """["ammo","ammoBox"]"""),
    )

    private val index = SearchIndex(samples)

    // ==================== normalize ====================

    @Test
    fun `归一化折叠全角与连字符`() {
        assertEquals("ak74m", normalize("ＡＫ－７４Ｍ"))
        assertEquals("ak74m", normalize("AK-74M"))
        assertEquals("ak74m", normalize("AK 74M"))
        assertEquals("m4a1", normalize("M4A1"))
    }

    @Test
    fun `归一化去中文标点`() {
        assertEquals("柯尔特m4a1卡宾枪", normalize("柯尔特 M4A1，卡宾枪"))
        assertEquals("", normalize(null))
        assertEquals("", normalize(""))
    }

    // ==================== 门槛 ====================

    @Test
    fun `少于两个字符不搜索`() {
        assertEquals(0, index.search("m").size)
        assertEquals(0, index.search("卡").size)
        assertEquals(0, index.search("").size)
        // 单个英文字母也不行
        assertEquals(0, index.search("G").size)
    }

    @Test
    fun `两个字符开始搜索`() {
        assertTrue(index.search("m4").isNotEmpty())
        assertTrue(index.search("消音").isNotEmpty())
    }

    // ==================== 排序 ====================

    @Test
    fun `m4a1 精确命中排第一`() {
        val found = index.search("m4a1")
        assertTrue(found.isNotEmpty())
        assertEquals("柯尔特 M4A1 5.56x45 卡宾枪", found[0].item.nameZh)
    }

    @Test
    fun `m4 前缀匹配 M45A1 排最前 因为名字更短`() {
        // 桌面端实测：搜 m4 时 M45A1(31分) 在 M4A1(30分) 之前，
        // 因为 M45A1 的 short_name 更短、尾巴惩罚更小。这是有意为之。
        val found = index.search("m4")
        assertTrue(found.isNotEmpty())
        assertEquals("柯尔特 M45A1 .45 ACP 手枪", found[0].item.nameZh)
    }

    @Test
    fun `同义词把俗称映射到官方名`() {
        // 库里有"显示卡"没有"显卡"，同义词表显卡→显示卡
        val found = index.search("显卡")
        assertTrue(found.isNotEmpty())
        assertEquals("显示卡", found[0].item.nameZh)
    }

    @Test
    fun `消音器 不被配件词扣分`() {
        // ⚠️ 这一条**和桌面端 v1.2 结果不同**，是移动端有意修的。
        //
        // 桌面端 `src/search.py` 第 175 行算了 `wants_part` 却从没在判断里用它（死变量），
        // 所以搜「消音器」时反让"消音手枪"（两类词都命中）排到第一：
        //   桌面端实测：7 分PB 9x18PM消音手枪 / 0 分 SOCOM556 消音器 / 0 分 SR1MP消音器基座
        // 这恰好是桌面端自己注释里说要避免的情况（"反让「消音手枪」排到第一"）。
        // 移动端把 wants_part 接进判断：用户在找配件就别扣配件，
        // 真·消音器回到第一，消音手枪（它本身是枪不是消音器）排后面。
        val found = index.search("消音器")
        assertTrue(found.isNotEmpty())
        assertTrue(
            "真消音器应排第一，实际首位=" + found[0].item.nameZh,
            found[0].item.nameZh.contains("SOCOM556"),
        )
    }

    @Test
    fun `搜索不区分大小写`() {
        assertEquals(index.search("消音器").size, index.search("消音器").size)
        assertTrue(index.search("SOCOM").isNotEmpty())
        assertTrue(index.search("socom").isNotEmpty())
    }

    @Test
    fun `候选条数不超过上限`() {
        assertTrue(index.search("卡宾枪", topN = 5).size <= 5)
        assertTrue(index.search("卡宾枪", topN = 2).size <= 2)
    }

    @Test
    fun `同分时顺序稳定`() {
        // 两次调用应得完全一样的顺序（同分多，不加 tiebreak 会乱跳）
        val a = index.search("M4A1").map { it.item.id }
        val b = index.search("M4A1").map { it.item.id }
        assertEquals(a, b)
    }

    // ==================== 打分细节 ====================

    @Test
    fun `长度惩罚不超过负六`() {
        // 名字超长也不会扣超过 -6，否则召回分 +8 被吃掉就归零了
        val longName = "非常非常非常长的名字".repeat(10)
        val it = item(short = "x", zh = longName)
        val penalty = scoreItem(it, normalize("x"))
        assertTrue("扣分应 >= -6，实际=$penalty", penalty >= -6)
    }

    @Test
    fun `长度惩罚按Python 的四舍六入五成双`() {
        // 回归测试：`Math.round` 会把m4 的排序弄反。
        //
        // 「柯尔特 M4A1 5.56x45 卡宾枪」归一化后尾巴长 11，
        // 惩罚 = -6 * 11/12 = -5.5，正好一半。
        //   Math.round(-5.5) = -5  → M4A1 得 31 分，压过 M45A1 的 31 分排到第一（错）
        //   Python round(-5.5) = -6 → M4A1 得 30 分，M45A1 的 31 分正常第一（对）
        //
        // 桌面端实测就是 M45A1 在前，所以这里必须跟 Python 而不是跟 Java。
        //
        // 注意：中英文名都得给。长度惩罚取**较短**的那个名字算，
        // 英文名留空的话 shorter 变成空串、惩罚直接归 0，就测不到 .5 这个点了。
        val m4a1 = item(
            short = "M4A1", zh = "柯尔特 M4A1 5.56x45 卡宾枪",
            en = "Colt M4A1 5.56x45 carbine",
        )
        val m45a1 = item(
            short = "M45A1", zh = "柯尔特 M45A1 .45 ACP 手枪",
            en = "Colt M45A1 .45 ACP pistol",
        )
        val q = normalize("m4")
        val a = scoreItem(m4a1, q)
        val b = scoreItem(m45a1, q)
        assertEquals("M4A1 应拿 30 分", 30, a)
        assertEquals("M45A1 应拿 31 分", 31, b)
        assertTrue("M45A1 应高于 M4A1", b > a)
    }

    @Test
    fun `查询词本身就是配件词时不扣分`() {
        // 桌面端这里给 -2（wants_part 是死变量）；移动端给正分。
        // 语义：搜「消音器」时命中"消音器"的物品是用户要的，不该被扣。
        val suppressor = item(short = "Suppressor", zh = "5.56x45 消音器")
        val score = scoreItem(suppressor, normalize("消音器"))
        assertTrue("不该被配件词扣成负数，实际=$score", score > 0)
    }

    @Test
    fun `短名完全匹配比仅中文名包含分高`() {
        val byShort = item(short = "M4A1", zh = "柯尔特 卡宾枪")
        val byZh = item(short = "别的", zh = "柯尔特 M4A1 卡宾枪")
        val q = normalize("m4a1")
        assertTrue(
            "短名命中应分更高：short=${scoreItem(byShort, q)} zh=${scoreItem(byZh, q)}",
            scoreItem(byShort, q) > scoreItem(byZh, q),
        )
    }

    // ==================== 取价 ====================

    @Test
    fun `本地取价不联网且字段完整`() {
        val it = item("x", avg = 61328, low = 4000, high = 123456, offers = 42, flea = true, base = 45000)
        val q = localQuote(it)
        assertEquals(61328, q.avg24h)
        assertEquals(4000, q.low24h)
        assertEquals(123456, q.high24h)
        assertEquals(42, q.offerCount)
        assertTrue(q.hasPrice)
    }

    @Test
    fun `没有价格时 hasPrice 为 false 而不是报 0`() {
        // 第 4 级空占位：不拿 ₽0 糊弄用户
        val q = localQuote(item(avg = 0, flea = false))
        assertFalse(q.hasPrice)
        assertFalse(q.fleaEnabled)
        assertEquals("暂无", formatMoney(q.avg24h))
    }

    @Test
    fun `商人回收价按从高到低排序`() {
        val it = item(sell = """{"普什金":50000,"Therapist":82000,"USHIN":30000}""")
        val rows = traderNames(it)
        assertEquals(3, rows.size)
        assertEquals(82000, rows[0].price)
        assertEquals("Therapist", rows[0].name)
        assertEquals(30000, rows[2].price)
    }

    @Test
    fun `商人明细过滤掉零价`() {
        val rows = traderNames(item(sell = """{"A":0,"B":100,"C":0}"""))
        assertEquals(1, rows.size)
        assertEquals(100, rows[0].price)
    }

    @Test
    fun `商人明细遇到坏JSON不崩`() {
        // 桌面端 isinstance(dict) 检查的等价物：数组 / null / 坏串都当没有
        assertEquals(0, traderNames(item(sell = "[1,2,3]")).size)
        assertEquals(0, traderNames(item(sell = "null")).size)
        assertEquals(0, traderNames(item(sell = "")).size)
        assertEquals(0, traderNames(item(sell = "{broken")).size)
        assertEquals(0, traderNames(item(sell = "{\"a\":")).size)
    }

    @Test
    fun `商人名里的转义引号能正确解析`() {
        // 真实库里真有这种名字：VOMZ P1X42 "WEAVER"
        val rows = traderNames(item(sell = """{"VOMZ \"WEAVER\" P1X42":12345}"""))
        assertEquals(1, rows.size)
        assertEquals("VOMZ \"WEAVER\" P1X42", rows[0].name)
        assertEquals(12345, rows[0].price)
    }

    @Test
    fun `商人最高收购价取最大值`() {
        assertEquals(82000, bestTraderPrice("""{"a":50000,"b":82000,"c":30000}"""))
        assertEquals(0, bestTraderPrice(""))
        assertEquals(0, bestTraderPrice("[1,2]"))
    }

    @Test
    fun `金额格式化带千分位和卢布`() {
        assertEquals("61,328 ₽", formatMoney(61328))
        assertEquals("999 ₽", formatMoney(999))
        assertEquals("暂无", formatMoney(0))
        assertEquals("暂无", formatMoney(-5))
    }

    // ==================== 曲线摘要 ====================

    @Test
    fun `曲线上涨摘要`() {
        val points = listOf(PricePoint(100, 1000), PricePoint(200, 1100))
        val (text, up) = curveSummary(points)!!
        assertTrue(up)
        assertEquals("近 7 天上涨 10.0%", text)
    }

    @Test
    fun `曲线下跌摘要不带负号`() {
        val points = listOf(PricePoint(100, 1000), PricePoint(200, 950))
        val (text, up) = curveSummary(points)!!
        assertFalse(up)
        assertEquals("近 7 天下跌 5.0%", text)
    }

    @Test
    fun `曲线持平用专门文案`() {
        val points = listOf(PricePoint(100, 1000), PricePoint(200, 1001))
        val (text, _) = curveSummary(points)!!
        assertEquals("近 7 天基本持平", text)
    }

    @Test
    fun `曲线点数不足时没有摘要`() {
        // 不显示"持平 0%"，直接不显示这一块
        assertNull(curveSummary(emptyList()))
        assertNull(curveSummary(listOf(PricePoint(100, 1000))))
    }

    // ==================== 筛选排序 ====================

    @Test
    fun `按均价降序取前N`() {
        val r = searchItems(samples, ReportOptions(sortField = SortField.AVG24H, descending = true, limit = 3, fleaOnly = true))
        assertEquals(3, r.size)
        assertEquals(120000, r[0].avg24h)
        assertEquals(61328, r[1].avg24h)
    }

    @Test
    fun `按均价升序`() {
        val r = searchItems(samples, ReportOptions(sortField = SortField.AVG24H, descending = false, limit = 1))
        assertEquals(5000, r[0].avg24h)
    }

    @Test
    fun `skipZero 过滤掉没价格的`() {
        val withZero = samples + item("9", "零价物", zh = "零价物品", avg = 0)
        val r = searchItems(withZero, ReportOptions(sortField = SortField.AVG24H, skipZero = true, limit = 0))
        assertFalse(r.any { it.id == "9" })
    }

    @Test
    fun `最低价门槛过滤`() {
        val r = searchItems(samples, ReportOptions(sortField = SortField.AVG24H, minPrice = 40000, limit = 0))
        assertTrue(r.all { it.avg24h >= 40000 })
        // id=1 是 M4A1（61328），id=7 是显示卡（40000，刚好卡在门槛上应保留）
        assertTrue(r.any { it.id == "1" })
        assertTrue(r.any { it.id == "7" })
        // id=2 是 M45A1（30000）、id=8 是弹药包（5000），都该被挡掉
        assertFalse(r.any { it.id == "2" })
        assertFalse(r.any { it.id == "8" })
    }

    @Test
    fun `关键词同时匹配中英文名`() {
        val zh = searchItems(samples, ReportOptions(keyword = "卡宾枪", limit = 0))
        assertTrue(zh.any { it.id == "1" })
        val en = searchItems(samples, ReportOptions(keyword = "colt", limit = 0))
        assertTrue(en.any { it.id == "1" })
        val sh = searchItems(samples, ReportOptions(keyword = "m4a1", limit = 0))
        assertTrue(sh.isNotEmpty())
    }

    @Test
    fun `关键词忽略大小写`() {
        val upper = searchItems(samples, ReportOptions(keyword = "COLT", limit = 0))
        val lower = searchItems(samples, ReportOptions(keyword = "colt", limit = 0))
        assertEquals(upper.size, lower.size)
    }

    @Test
    fun `fleaOnly 过滤不可跳蚤物品`() {
        val mixed = samples + item("9", "不可售", zh = "不可售物品", avg = 99999, flea = false)
        val r = searchItems(mixed, ReportOptions(fleaOnly = true, limit = 0))
        assertFalse(r.any { it.id == "9" })
        val r2 = searchItems(mixed, ReportOptions(fleaOnly = false, limit = 0))
        assertTrue(r2.any { it.id == "9" })
    }

    @Test
    fun `按商人回收价排序现算派生值`() {
        val withTraders = listOf(
            item("a", avg = 1000, sell = """{"A":5000}"""),
            item("b", avg = 2000, sell = """{"B":9000}"""),
            item("c", avg = 3000, sell = """{"C":100}"""),
        )
        val r = searchItems(withTraders, ReportOptions(sortField = SortField.TRADER_BEST, descending = true, limit = 3))
        assertEquals(listOf("b", "a", "c"), r.map { it.id })
    }

    @Test
    fun `limit 为 0 表示不限制`() {
        val r = searchItems(samples, ReportOptions(limit = 0))
        assertEquals(samples.size, r.size)
    }

    // ==================== 分类归并 ====================

    @Test
    fun `一个物品只落一个分类`() {
        // M4A1 带 gun,wearable 两个标签，只能落「枪械」
        val gun = item("1", zh = "卡宾枪", types = """["gun","wearable"]""")
        assertEquals("枪械", itemCategory(gun))
    }

    @Test
    fun `多标签按优先级归并`() {
        // 弹药 + barter：弹药排在 barter 前面，落「弹药」
        val ammo = item("2", zh = "VOG-25", types = """["ammo","barter"]""")
        assertEquals("弹药", itemCategory(ammo))
    }

    @Test
    fun `没命中任何类落到其他`() {
        assertEquals(OTHER_CATEGORY, itemCategory(item(types = """["unknownTag"]""")))
        assertEquals(OTHER_CATEGORY, itemCategory(item(types = "")))
    }

    @Test
    fun `分类不变量：一个物品只出现在一个分类里`() {
        val groups = groupByType(samples, limit = 10)
        val allIds = groups.flatMap { g -> g.items.map { it.id } }
        assertEquals("不该有重复物品", allIds.size, allIds.toSet().size)
    }

    @Test
    fun `每类取前N且顺序与分类顺序一致`() {
        val many = (1..30).map { item("g$it", zh = "枪$it", avg = it * 100, types = """["gun"]""") }
        val ammo = (1..5).map { item("a$it", zh = "弹$it", avg = it * 100, types = """["ammo"]""") }
        val groups = groupByType(many + ammo, limit = 10)
        assertEquals("枪械" to 10, groups.first().name to groups.first().items.size)
        // 枪械在 CATEGORY_ORDER 里排第一，弹药第二
        assertEquals("枪械", groups[0].name)
        assertEquals("弹药", groups[1].name)
    }

    @Test
    fun `空类不出现`() {
        val groups = groupByType(listOf(item("1", types = """["gun"]""")), limit = 10)
        assertEquals(1, groups.size)
    }

    @Test
    fun `typesJson 解析容错`() {
        assertEquals(listOf("gun", "wearable"), itemTags(item(types = """["gun","wearable"]""")))
        assertEquals(listOf("gun"), itemTags(item(types = """["gun",]""")))
        assertEquals(emptyList<String>(), itemTags(item(types = "坏数据")))
        assertEquals(emptyList<String>(), itemTags(item(types = "")))
    }

    // ==================== 涨跌榜 ====================

    @Test
    fun `涨跌榜取前后各N且过滤掉无涨跌的`() {
        val movers = listOf(
            item("u1", avg = 100, pct = 50.0),
            item("u2", avg = 100, pct = 30.0),
            item("d1", avg = 100, pct = -40.0),
            item("d2", avg = 100, pct = -20.0),
            item("flat", avg = 100, pct = 0.0),
            item("noPrice", avg = 0, pct = 99.0),
            item("noFlea", avg = 100, pct = 99.0, flea = false),
        )
        val (up, down) = topMovers(movers, true, true, count = 2)
        assertEquals(listOf("u1", "u2"), up.map { it.id })
        assertEquals(listOf("d1", "d2"), down.map { it.id })
    }

    @Test
    fun `只勾一边时另一边为空`() {
        // 桌面端这里返回 2（把跌 40% 的 d1 也算进"涨"列表），因为它的 pool 没按符号过滤。
        // 移动端按正负切干净：只勾涨就只有涨的。
        val movers = listOf(item("u1", avg = 100, pct = 50.0), item("d1", avg = 100, pct = -40.0))
        val (up, down) = topMovers(movers, true, false, count = 5)
        assertEquals(listOf("u1"), up.map { it.id })
        assertEquals(0, down.size)

        val (up2, down2) = topMovers(movers, false, true, count = 5)
        assertEquals(0, up2.size)
        assertEquals(listOf("d1"), down2.map { it.id })
    }

    @Test
    fun `涨跌百分比为零不算涨跌`() {
        val zero = listOf(item("z", avg = 100, pct = 0.0))
        assertEquals(0, topMovers(zero, true, true).first.size)
    }

    // ==================== 接口地址 ====================

    @Test
    fun `接口路径小写才对`() {
        // /PVE/prices/ 会 404，这是桌面端踩过的坑
        assertEquals("https://json.tarkov.dev/pve/prices/abc", pricesUrl(GameMode.PVE, "abc"))
        assertEquals("https://json.tarkov.dev/regular/prices/abc", pricesUrl(GameMode.PVP, "abc"))
    }

    @Test
    fun ` pvp 模式的 slug 是 regular`() {
        assertEquals("regular", GameMode.PVP.slug)
        assertEquals("pve", GameMode.PVE.slug)
        assertEquals(GameMode.PVP, GameMode.fromLabel("PVP"))
        assertEquals(GameMode.PVE, GameMode.fromLabel("不存在"))
    }

    @Test
    fun `图标包镜像优先原始地址兜底`() {
        val urls = iconPackUrls()
        assertTrue("镜像应排在前面", urls[0].contains("gh-proxy"))
        assertEquals(ICON_PACK_URL, urls.last())
        assertTrue(urls.size >= 4)
    }
}