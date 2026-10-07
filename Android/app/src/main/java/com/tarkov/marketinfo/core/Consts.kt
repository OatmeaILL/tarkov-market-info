package com.tarkov.marketinfo.core

/**
 * 全局常量与接口地址 —— 移植自桌面端的 `sync.py` / `price.py` / `search.py`。
 *
 * 接口完全一致，这样同一个物品在两个端查到的价格、排序也一致。
 */

/** 版本号。桌面端 1.2 / 1.3，移动端独立计数但接口行为要对齐。 */
const val APP_VERSION = "1.3"

/** 请求 UA。桌面端是 `TarkovMarketInfo/1.2`，这边标明移动端便于服务端区分。 */
const val USER_AGENT = "TarkovMarketInfo-Android/1.3"

/** 游戏模式：PVE / PVP */
enum class GameMode(val label: String, val slug: String) {
    PVE("PVE", "pve"),
    PVP("PVP", "regular");

    companion object {
        fun fromLabel(label: String): GameMode =
            entries.firstOrNull { it.label == label } ?: PVE
    }
}

/**
 * ⚠️ 接口路径**大小写敏感**：`/PVE/prices/` 会404。
 * 桌面端踩过这个坑（`price.fetch_history` 里改用 `sync.mode_slug`）。
 */
fun pricesUrl(mode: GameMode, itemId: String): String =
    "https://json.tarkov.dev/${mode.slug}/prices/$itemId"

/** 全量物品（带 24h 价格、商人买卖价、涨跌、types、iconLink） */
fun itemsUrl(mode: GameMode): String = "https://json.tarkov.dev/${mode.slug}/items"

/** 中文名映射表 */
fun itemsZhUrl(mode: GameMode): String = "https://json.tarkov.dev/${mode.slug}/items_zh"

/** 商人 id → 显示名 */
fun tradersUrl(mode: GameMode): String = "https://json.tarkov.dev/${mode.slug}/traders"

/**
 * 图标策略：**不下 16MB 的 icon.zip**（桌面端那套），改成按需拉单张。
 *
 * 桌面端把约 5300 张 webp 解到本地 `icon/`，移动端塞不进 APK、首下也要 16MB 流量。
 * 移动端只存接口给的 `iconLink`，界面滚到才拉单张，缓存在 `cacheDir/icons`。
 * 代价是首次看某个物品要等几百毫秒，好处是安装包小得多。
 *
 * 下面的镜像列表是为「整包下载」准备的 fallback，移动端当前走不到，
 * 留着是万一以后要下整包时不用重新查一遍可用镜像。
 */
const val ICON_PACK_URL = "https://github.com/OatmeaILL/tarkov-mcp/releases/download/icons/icon.zip"

// 注意：这里不能用 const —— Kotlin 的 const 只允许原始类型和 String，不允许 List。
private val GITHUB_MIRRORS = listOf(
    "https://gh-proxy.org/https://github.com",
    "https://v4.gh-proxy.org/https://github.com",
    "https://ghproxy.net/https://github.com",
    "https://gh-proxy.com/https://github.com",
)

/** 图标包候选地址，镜像优先、原始 release 兜底。 */
fun iconPackUrls(): List<String> =
    GITHUB_MIRRORS.map { "$it/OatmeaILL/tarkov-mcp/releases/download/icons/icon.zip" } + ICON_PACK_URL

/** 图床：接口的 `iconLink` 是相对路径，拼上这个前缀就是完整地址。 */
const val ICON_CDN = "https://assets.tarkov.dev"

/**
 * 图床连续失败到多少张就主动收手。
 * 被限流时挨个重试只会拖死整个同步流程。
 */
const val ICON_MAX_FAILURES = 25

/** 兼容别名：同步层用的名字，语义一样。 */
const val ITEM_MAX_FAILURES = ICON_MAX_FAILURES

/** 请求超时。实测单次请求 1.1~1.6 秒，30 秒足够覆盖慢网。 */
const val REQUEST_TIMEOUT_MS = 30_000

/** 兼容别名：同步层用的名字，语义一样。 */
const val ITEM_TIMEOUT_MS = REQUEST_TIMEOUT_MS

/**
 * 自动检索的字符门槛（归一化后）。
 *
 * 和桌面端 `home.MIN_SEARCH_CHARS = 2`、以及历史记录「≥2 字符才记」是同一个口径，
 * 三处别改成不一样的值。
 */
const val MIN_SEARCH_CHARS = 2

/** 候选条数上限 */
const val TOP_N = 5

/** 归一化后输入够几个字就自动检索。桌面端 180ms，移动端也用 180ms。 */
const val SEARCH_DEBOUNCE_MS = 180L

/** 最近查看保留条数，和桌面端 `prefs.MAX_RECENT` 一致 */
const val MAX_RECENT = 12