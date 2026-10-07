package com.tarkov.marketinfo.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.tarkov.marketinfo.core.GameMode
import com.tarkov.marketinfo.core.MIN_SEARCH_CHARS
import com.tarkov.marketinfo.core.CategoryGroup
import com.tarkov.marketinfo.core.Item
import com.tarkov.marketinfo.core.Liquidity
import com.tarkov.marketinfo.core.PricePoint
import com.tarkov.marketinfo.core.Quote
import com.tarkov.marketinfo.core.ReportOptions
import com.tarkov.marketinfo.core.SEARCH_DEBOUNCE_MS
import com.tarkov.marketinfo.core.ScoredItem
import com.tarkov.marketinfo.core.SortField
import com.tarkov.marketinfo.core.TraderRow
import com.tarkov.marketinfo.core.bestTraderPrice
import com.tarkov.marketinfo.core.curveSummary
import com.tarkov.marketinfo.core.formatMoney
import com.tarkov.marketinfo.core.groupByType
import com.tarkov.marketinfo.core.itemCategory
import com.tarkov.marketinfo.core.localQuote
import com.tarkov.marketinfo.core.normalize
import com.tarkov.marketinfo.core.searchItems
import com.tarkov.marketinfo.core.topMovers
import com.tarkov.marketinfo.core.traderNames
import com.tarkov.marketinfo.data.FavoriteEntity
import com.tarkov.marketinfo.data.Graph
import com.tarkov.marketinfo.data.RecentEntity
import com.tarkov.marketinfo.data.Repository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 界面状态。
 *
 * 整个界面只有这一个状态对象：Compose 靠数据变化自动重组，
 * 不用像 tkinter 那样手动 `update()` 每一个控件（桌面端 `home.py` 里全是那种代码）。
 */
data class HomeState(
    val query: String = "",
    val candidates: List<ScoredItem> = emptyList(),
    val selectedIndex: Int = -1,
    val detail: DetailState = DetailState(),
    val recent: List<RecentEntity> = emptyList(),
    val favorites: List<FavoriteEntity> = emptyList(),
    val favoriteIds: Set<String> = emptySet(),
    val status: String = "",
    val statusIsError: Boolean = false,
    val mode: GameMode = GameMode.PVE,
    val itemCount: Int = 0,
    val lastSync: String = "从未同步",
    val showReport: Boolean = false,
    val reportOptions: ReportOptions = ReportOptions(),
    val syncing: Boolean = false,
    val syncText: String = "",
    val syncProgress: Float = 0f,
) {
    val selected: ScoredItem?
        get() = candidates.getOrNull(selectedIndex)
}

/** 详情面板。价格先出本地值，曲线后补——跟桌面端一个节奏。 */
data class DetailState(
    val itemId: String = "",
    val nameZh: String = "",
    val shortName: String = "",
    val nameEn: String = "",
    val quote: Quote? = null,
    /** 48 小时涨跌（百分比）。在 Item 上而不在 Quote 里，core 层就这么分的。 */
    val changePct: Double = 0.0,
    val traders: List<TraderRow> = emptyList(),
    val bestTrader: Int = 0,
    val category: String = "",
    val liquidity: Liquidity = Liquidity.MID,
    val curve: List<PricePoint> = emptyList(),
    val curveText: String = "",
    val curveEmpty: Boolean = false,
    val isFavorite: Boolean = false,
    val iconUrl: String = "",
    val loading: Boolean = false,
) {
    val isEmpty: Boolean get() = itemId.isEmpty()
}

/** 报表状态。 */
data class ReportState(
    val rows: List<Item> = emptyList(),
    val groups: List<CategoryGroup> = emptyList(),
    val groupNames: List<String> = emptyList(),
    val total: Int = 0,
    val upItems: List<Item> = emptyList(),
    val downItems: List<Item> = emptyList(),
    val byCategory: Boolean = false,
)

/**
 * 主 ViewModel。
 *
 * ## 移植时和桌面端不一样的地方
 *
 * - 桌面端是 tkinter，状态存在 widget 属性里、靠 `update()` 刷；
 *   这边是 Compose + StateFlow，改 state 就自动重组。
 * - 桌面端后台线程更新 UI 必须 `after(0, ...)` 切主线程（`home.py` 里到处是这个坑）；
 *   这边用协程的 `withContext(Dispatchers.Main)`，语义一样但不靠记得调用。
 * - 自动检索的防抖：桌面端用 `after(180, ...)` + `after_cancel`；
 *   这边用 `Job` + `delay`，切物品时把旧 Job 取消掉，语义一样。
 */
class HomeViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = Repository(app)

    private val _state = MutableStateFlow(HomeState())
    val state: StateFlow<HomeState> = _state.asStateFlow()

    private val _report = MutableStateFlow(ReportState())
    val report: StateFlow<ReportState> = _report.asStateFlow()

    /** 防抖任务。每次输入都取消上一个，保证只搜最后一次。 */
    private var debounceJob: Job? = null

    /** 曲线请求标识。快速切物品时旧响应直接丢。 */
    private var curveJob: Job? = null

    init {
        viewModelScope.launch {
            val mode = repo.gameMode()
            val count = repo.itemCount()
            _state.update {
                it.copy(
                    mode = mode,
                    itemCount = count,
                    lastSync = repo.lastSyncText(),
                    // 没数据就直说，别让用户对着空列表发呆
                    status = if (count == 0) "还没有数据，点右下角同步" else "",
                )
            }
            refreshRecent()
            refreshFavorites()
            if (count > 0) rebuildReport()
        }
    }

    // ---------- 搜索 ----------

    /**
     * 输入变化。**输入满2 个字自动开始搜**，不用点按钮也不用按回车。
     *
     * 防抖 180ms：手停下来就开始搜，同时避免打字过程中每个键都触发一次全量搜索。
     */
    fun onQueryChange(text: String) {
        _state.update { it.copy(query = text) }
        debounceJob?.cancel()
        // 归一化后不足 2 个字符不搜（和历史记录同一条约束）
        if (normalize(text).length < MIN_SEARCH_CHARS) {
            debounceJob = null
            _state.update {
                it.copy(
                    candidates = emptyList(),
                    selectedIndex = -1,
                    detail = DetailState(),
                )
            }
            return
        }
        debounceJob = viewModelScope.launch {
            delay(SEARCH_DEBOUNCE_MS)
            runSearch(text, auto = true)
        }
    }

    /**
     * 回车 / 点搜索。
     *
     * 手动搜索和自动搜索的区别只在**要不要自动选中**：
     * 自动搜完只给候选让用户选（手还在打字），
     * 手动敲回车说明用户已经想好了，直接看第一个。
     */
    fun onSubmit() {
        debounceJob?.cancel()
        debounceJob = null
        val text = _state.value.query
        if (normalize(text).length < MIN_SEARCH_CHARS) {
            setStatus("至少输入 2 个字", error = true)
            return
        }
        viewModelScope.launch { runSearch(text, auto = false) }
    }

    private suspend fun runSearch(text: String, auto: Boolean) {
        val found = withContext(Dispatchers.Default) { repo.search(text) }
        if (found.isEmpty()) {
            _state.update {
                it.copy(
                    candidates = emptyList(),
                    selectedIndex = -1,
                    detail = DetailState(),
                    status = "没找到「$text」",
                    statusIsError = true,
                )
            }
            return
        }
        _state.update {
            it.copy(
                candidates = found,
                status = if (auto) {
                    "找到 ${found.size} 个候选"
                } else {
                    "找到 ${found.size} 个候选，已选中第一个"
                },
                statusIsError = false,
            )
        }
        if (auto) {
            // 自动检索不自动选中：用户可能还在改关键词
            _state.update { it.copy(selectedIndex = -1, detail = DetailState()) }
        } else {
            select(0, text)
        }
    }

    /**
     * 上下键切候选。**边界停住不循环**：
     * 在第一项按上键停住、最后一项按下键停住，
     * 循环跳转容易让用户按过头、找不着刚才看的那条。
     */
    fun moveSelection(delta: Int) {
        val current = _state.value
        if (current.candidates.isEmpty()) return
        val target = when {
            current.selectedIndex < 0 -> if (delta > 0) 0 else current.candidates.lastIndex
            else -> (current.selectedIndex + delta).coerceIn(0, current.candidates.lastIndex)
        }
        select(target, current.query)
    }

    fun select(index: Int, query: String = _state.value.query) {
        val current = _state.value
        val hit = current.candidates.getOrNull(index) ?: return
        _state.update { it.copy(selectedIndex = index) }
        loadDetail(hit.item, query)
    }

    fun clearQuery() {
        debounceJob?.cancel()
        curveJob?.cancel()
        _state.update {
            it.copy(
                query = "",
                candidates = emptyList(),
                selectedIndex = -1,
                detail = DetailState(),
                status = "",
                statusIsError = false,
            )
        }
    }

    // ---------- 详情 ----------

    private fun loadDetail(item: Item, query: String) {
        // 取消上一条曲线请求：快速切物品时别让旧响应覆盖新物品的曲线
        curveJob?.cancel()

        val quote = localQuote(item)
        val traders = traderNames(item)
        _state.update {
            it.copy(
                detail = DetailState(
                    itemId = item.id,
                    nameZh = item.nameZh,
                    shortName = item.shortName,
                    nameEn = item.nameEn,
                    quote = quote,
                    changePct = item.change48hPct,
                    traders = traders,
                    bestTrader = bestTraderPrice(item.sellJson),
                    category = itemCategory(item),
                    liquidity = Liquidity.of(item.offerCount),
                    isFavorite = it.favoriteIds.contains(item.id),
                    iconUrl = repo.iconUrlOf(item),
                    loading = true,
                )
            )
        }
        // 记录查看：锚定「点开候选」，不是「输入」
        repo.recordVisit(item, query)
        refreshRecent()

        curveJob = viewModelScope.launch {
            repo.loadCurve(item.id, _state.value.mode) { result ->
                when (result) {
                    is Repository.CurveResult.Ready -> {
                        repo.cacheCurve(item.id, result.points)
                        val summary = curveSummary(result.points)
                        _state.update { current ->
                            // 物品已经切走了就别写回来
                            if (current.detail.itemId != item.id) return@update current
                            current.copy(
                                detail = current.detail.copy(
                                    curve = result.points,
                                    curveText = summary?.first ?: "",
                                    curveEmpty = false,
                                    loading = false,
                                )
                            )
                        }
                    }
                    Repository.CurveResult.Empty -> {
                        _state.update { current ->
                            if (current.detail.itemId != item.id) return@update current
                            current.copy(
                                detail = current.detail.copy(
                                    curveEmpty = true,
                                    loading = false,
                                )
                            )
                        }
                    }
                }
            }
        }
    }

    fun resetDetail() {
        curveJob?.cancel()
        _state.update { it.copy(detail = DetailState(), selectedIndex = -1) }
    }

    // ---------- 收藏 / 最近 ----------

    fun toggleFavorite() {
        val detail = _state.value.detail
        if (detail.itemId.isEmpty()) return
        val now = repo.toggleFavorite(detail.itemId, detail.nameZh)
        _state.update {
            it.copy(
                detail = it.detail.copy(isFavorite = now),
                favoriteIds = if (now) it.favoriteIds + detail.itemId else it.favoriteIds - detail.itemId,
                status = if (now) "已收藏" else "已取消收藏",
            )
        }
        refreshFavorites()
    }

    private fun refreshFavorites() {
        viewModelScope.launch {
            val list = withContext(Dispatchers.IO) { repo.favoriteEntries() }
            _state.update { it.copy(favorites = list, favoriteIds = list.map { f -> f.itemId }.toSet()) }
        }
    }

    private fun refreshRecent() {
        viewModelScope.launch {
            val list = withContext(Dispatchers.IO) { repo.recentItems() }
            _state.update { it.copy(recent = list) }
        }
    }

    fun clearRecent() {
        repo.clearRecent()
        refreshRecent()
        setStatus("已清空最近")
    }

    /** 点最近/收藏里的某条：直接看详情，不走搜索。 */
    fun openById(itemId: String) {
        viewModelScope.launch {
            val item = withContext(Dispatchers.IO) { repo.findItem(itemId) }
            if (item == null) {
                setStatus("这个物品不在当前库里了", error = true)
                return@launch
            }
            // 塞成单条候选，这样上下键逻辑和搜索路径是同一套
            _state.update {
                it.copy(
                    query = "",
                    candidates = listOf(ScoredItem(item, 0)),
                    selectedIndex = 0,
                    status = "",
                )
            }
            loadDetail(item, "")
        }
    }

    // ---------- 同步 ----------

    fun syncNow() {
        if (_state.value.syncing) return
        _state.update { it.copy(syncing = true, syncText = "准备同步 ...", syncProgress = 0f) }
        viewModelScope.launch {
            val mode = _state.value.mode
            val result = withContext(Dispatchers.IO) {
                repo.sync(mode) { progress ->
                    // 进度从 IO 线程回来，StateFlow 的 update 是线程安全的
                    _state.update {
                        it.copy(syncText = progress.text, syncProgress = progress.value)
                    }
                }
            }
            if (result.error.isEmpty()) {
                _state.update {
                    it.copy(
                        syncing = false,
                        syncText = "",
                        syncProgress = 0f,
                        itemCount = result.count,
                        lastSync = repo.lastSyncText(),
                        status = "同步完成，共 ${result.count} 项",
                        statusIsError = false,
                    )
                }
                rebuildReport()
            } else {
                _state.update {
                    it.copy(
                        syncing = false,
                        syncText = "",
                        syncProgress = 0f,
                        status = "同步失败：${result.error}",
                        statusIsError = true,
                    )
                }
            }
        }
    }

    /** 切游戏模式。切完要重新同步——两个模式的物品集合不一样。 */
    fun switchMode(mode: GameMode) {
        if (mode == _state.value.mode) return
        repo.setGameMode(mode)
        _state.update { it.copy(mode = mode) }
        setStatus("已切到 ${mode.label}，正在重新同步")
        syncNow()
    }

    // ---------- 报表 ----------

    fun openReport() {
        _state.update { it.copy(showReport = true) }
        rebuildReport()
    }

    fun closeReport() {
        _state.update { it.copy(showReport = false) }
    }

    fun updateReportOptions(options: ReportOptions) {
        _state.update { it.copy(reportOptions = options) }
        rebuildReport()
    }

    private fun rebuildReport() {
        viewModelScope.launch {
            val options = _state.value.reportOptions
            val all = withContext(Dispatchers.IO) { repo.allItems() }
            val result = withContext(Dispatchers.Default) {
                val rows = searchItems(all, options)
                val groups = if (options.groupByCategory) {
                    groupByType(rows, options.limit)
                } else {
                    emptyList()
                }
                val movers = topMovers(
                    all, options.showGainers, options.showLosers, 10
                )
                ReportState(
                    rows = rows,
                    groups = groups,
                    groupNames = groups.map { it.name },
                    total = rows.size,
                    upItems = movers.first,
                    downItems = movers.second,
                    byCategory = options.groupByCategory,
                )
            }
            _report.value = result
        }
    }

    // ---------- 工具 ----------

    private fun setStatus(text: String, error: Boolean = false) {
        _state.update { it.copy(status = text, statusIsError = error) }
    }

    /** 物品名：中文名优先，空了退英文、再退短名。 */
    fun displayName(item: Item): String =
        item.nameZh.ifEmpty { item.nameEn.ifEmpty { item.shortName } }

    fun money(value: Int): String = formatMoney(value)
}
