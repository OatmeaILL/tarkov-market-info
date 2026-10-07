package com.tarkov.marketinfo.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.tarkov.marketinfo.core.GameMode
import com.tarkov.marketinfo.core.HISTORY_DAYS
import com.tarkov.marketinfo.ui.HomeViewModel
import com.tarkov.marketinfo.ui.components.EmptyHint
import com.tarkov.marketinfo.ui.components.FlatCard
import com.tarkov.marketinfo.ui.components.PriceRow
import com.tarkov.marketinfo.ui.components.SectionTitle
import com.tarkov.marketinfo.ui.components.Tag
import com.tarkov.marketinfo.ui.components.ThinDivider
import com.tarkov.marketinfo.ui.theme.Extra
import com.tarkov.marketinfo.ui.theme.Spacing
import com.tarkov.marketinfo.ui.theme.Trend

/**
 * 查价页。
 *
 * 布局照桌面端主窗口的顺序：搜索框 → 候选列表 → 详情 → 最近 / 收藏。
 * 移动端改成单列纵向滚动（桌面端是左右分栏），因为手机屏幕窄。
 */
@Composable
fun HomeScreen(
    viewModel: HomeViewModel,
    onOpenReport: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val keyboard = LocalSoftwareKeyboardController.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
    ) {
        SearchBar(
            query = state.query,
            onQueryChange = viewModel::onQueryChange,
            onSubmit = {
                viewModel.onSubmit()
                keyboard?.hide()
            },
            onClear = viewModel::clearQuery,
            onPrev = { viewModel.moveSelection(-1) },
            onNext = { viewModel.moveSelection(1) },
            onReport = onOpenReport,
        )

        if (state.syncing) {
            SyncBanner(state.syncText, state.syncProgress)
        }

        if (state.itemCount == 0 && !state.syncing) {
            EmptyLibrary(onSync = viewModel::syncNow)
            return@Column
        }

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(
                start = Spacing.lg,
                end = Spacing.lg,
                top = Spacing.sm,
                bottom = Spacing.xl,
            ),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            item {
                StatusLine(
                    text = state.status,
                    isError = state.statusIsError,
                    mode = state.mode,
                    onModeChange = viewModel::switchMode,
                    itemCount = state.itemCount,
                    lastSync = state.lastSync,
                )
            }

            if (state.candidates.isEmpty()) {
                if (state.detail.isEmpty) {
                    item { EmptyHint("输入物品名就会自动查", Icons.Filled.Search) }
                }
            } else {
                item {
                    SectionTitle(
                        text = "候选",
                        trailing = if (state.selectedIndex >= 0) {
                            "${state.selectedIndex + 1} / ${state.candidates.size}"
                        } else {
                            "${state.candidates.size} 条"
                        },
                    )
                }
                itemsIndexed(state.candidates, key = { _, hit -> hit.item.id }) { position, hit ->
                    CandidateRow(
                        name = hit.item.nameZh.ifEmpty {
                            hit.item.nameEn.ifEmpty { hit.item.shortName }
                        },
                        shortName = hit.item.shortName,
                        price = hit.item.avg24h,
                        changePct = hit.item.change48hPct,
                        score = hit.score,
                        selected = position == state.selectedIndex,
                        money = viewModel::money,
                        onClick = { viewModel.select(position) },
                    )
                }
            }

            if (!state.detail.isEmpty) {
                item { Spacer(Modifier.height(Spacing.sm)) }
                item { SectionTitle("详情") }
                item { DetailCard(viewModel) }
            }

            if (state.recent.isNotEmpty()) {
                item { Spacer(Modifier.height(Spacing.sm)) }
                item {
                    SectionTitle(
                        text = "最近查看",
                        trailing = "${state.recent.size} 条",
                    )
                }
                item {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                        items(state.recent, key = { it.itemId }) { entry ->
                            RecentChip(
                                name = entry.nameZh,
                                query = entry.query,
                                onClick = { viewModel.openById(entry.itemId) },
                            )
                        }
                    }
                }
            }

            if (state.favorites.isNotEmpty()) {
                item { Spacer(Modifier.height(Spacing.sm)) }
                item { SectionTitle("收藏", trailing = "${state.favorites.size} 项") }
                item {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                        items(state.favorites, key = { it.itemId }) { entry ->
                            RecentChip(
                                name = entry.nameZh,
                                query = "",
                                onClick = { viewModel.openById(entry.itemId) },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SearchBar(
    query: String,
    onQueryChange: (String) -> Unit,
    onSubmit: () -> Unit,
    onClear: () -> Unit,
    onPrev: () -> Unit,
    onNext: () -> Unit,
    onReport: () -> Unit,
) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.lg, vertical = Spacing.md),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                OutlinedTextField(
                    value = query,
                    onValueChange = onQueryChange,
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("输入物品名", style = MaterialTheme.typography.bodyLarge) },
                    leadingIcon = {
                        Icon(Icons.Filled.Search, contentDescription = null)
                    },
                    trailingIcon = {
                        if (query.isNotEmpty()) {
                            IconButton(onClick = onClear) {
                                Icon(Icons.Filled.Clear, contentDescription = "清空")
                            }
                        }
                    },
                    singleLine = true,
                    shape = RoundedCornerShape(10.dp),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    keyboardActions = KeyboardActions(onSearch = { onSubmit() }),
                )
                IconButton(onClick = onReport) {
                    Icon(Icons.Filled.Refresh, contentDescription = "报表")
                }
            }

            Spacer(Modifier.height(Spacing.sm))

            // 桌面端是键盘上下键；手机上没有小键盘，给两个按钮 +
            // 候选行可点。同一套 select/moveSelection 逻辑。
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = "输入 2 个字自动查 · 点候选看价格",
                    style = MaterialTheme.typography.labelSmall,
                    color = Extra.ink3,
                )
                Row {
                    IconButton(onClick = onPrev, modifier = Modifier.size(36.dp)) {
                        Icon(
                            Icons.Filled.Search,
                            contentDescription = "上一个",
                            modifier = Modifier.size(18.dp),
                            tint = Extra.ink2,
                        )
                    }
                    IconButton(onClick = onNext, modifier = Modifier.size(36.dp)) {
                        Icon(
                            Icons.Filled.Search,
                            contentDescription = "下一个",
                            modifier = Modifier.size(18.dp),
                            tint = Extra.ink2,
                        )
                    }
                }
            }
        }
    }
    ThinDivider()
}

@Composable
private fun StatusLine(
    text: String,
    isError: Boolean,
    mode: GameMode,
    onModeChange: (GameMode) -> Unit,
    itemCount: Int,
    lastSync: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            if (text.isNotEmpty()) {
                Text(
                    text = text,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (isError) Trend.up else Extra.ink2,
                )
            } else {
                Text(
                    text = "已同步 $itemCount 项 · $lastSync",
                    style = MaterialTheme.typography.bodySmall,
                    color = Extra.ink3,
                )
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.xs)) {
            GameMode.entries.forEach { entry ->
                Tag(
                    text = entry.label,
                    color = if (entry == mode) {
                        MaterialTheme.colorScheme.onPrimaryContainer
                    } else {
                        Extra.ink2
                    },
                    container = if (entry == mode) {
                        MaterialTheme.colorScheme.primaryContainer
                    } else {
                        Extra.track
                    },
                    modifier = Modifier.clickable { onModeChange(entry) },
                )
            }
        }
    }
}

@Composable
private fun SyncBanner(text: String, progress: Float) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f))
            .padding(horizontal = Spacing.lg, vertical = Spacing.sm),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(
                modifier = Modifier.size(14.dp),
                strokeWidth = 2.dp,
                color = MaterialTheme.colorScheme.primary,
            )
            Spacer(Modifier.width(Spacing.sm))
            Text(
                text = text,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
        }
        Spacer(Modifier.height(Spacing.xs))
        LinearProgressIndicator(
            progress = { progress },
            modifier = Modifier.fillMaxWidth().height(3.dp),
            color = MaterialTheme.colorScheme.primary,
        )
    }
}

@Composable
private fun EmptyLibrary(onSync: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(Spacing.xl),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = "还没有物品数据",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(Spacing.sm))
        Text(
            text = "首次使用需要联网拉一次全量物品（5400+ 项），之后就能离线查价",
            style = MaterialTheme.typography.bodyMedium,
            color = Extra.ink2,
        )
        Spacer(Modifier.height(Spacing.lg))
        FlatCard(onClick = onSync) {
            Row(
                modifier = Modifier.padding(horizontal = Spacing.xl, vertical = Spacing.md),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    Icons.Filled.Refresh,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                )
                Spacer(Modifier.width(Spacing.sm))
                Text(
                    text = "开始同步",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
private fun CandidateRow(
    name: String,
    shortName: String,
    price: Int,
    changePct: Double,
    score: Int,
    selected: Boolean,
    money: (Int) -> String,
    onClick: () -> Unit,
) {
    FlatCard(selected = selected, onClick = onClick) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.md, vertical = Spacing.md),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = name,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (shortName.isNotEmpty() && shortName != name) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        text = shortName,
                        style = MaterialTheme.typography.labelSmall,
                        color = Extra.ink3,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Spacer(Modifier.width(Spacing.md))
            Column(horizontalAlignment = Alignment.End) {
                PriceRow(
                    price = price,
                    changePct = changePct,
                    money = money,
                    priceStyle = MaterialTheme.typography.titleMedium,
                )
            }
        }
    }
}

@Composable
private fun DetailCard(viewModel: HomeViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val detail = state.detail
    if (detail.isEmpty) return

    FlatCard {
        Column(modifier = Modifier.padding(Spacing.lg)) {
            Row(verticalAlignment = Alignment.Top) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = detail.nameZh,
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    if (detail.shortName.isNotEmpty()) {
                        Spacer(Modifier.height(2.dp))
                        Text(
                            text = detail.shortName,
                            style = MaterialTheme.typography.labelMedium,
                            color = Extra.ink3,
                        )
                    }
                }
                IconButton(onClick = viewModel::toggleFavorite) {
                    Icon(
                        imageVector = if (detail.isFavorite) {
                            Icons.Filled.Star
                        } else {
                            Icons.Outlined.StarBorder
                        },
                        contentDescription = if (detail.isFavorite) "取消收藏" else "收藏",
                        tint = if (detail.isFavorite) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            Extra.ink3
                        },
                    )
                }
            }

            Spacer(Modifier.height(Spacing.md))

            val quote = detail.quote
            // 「暂无均价」而不是 ₽0：接口没给价格时显示 0 会被当成"白送"，
            // 桌面端 `localQuote` 也是靠 hasPrice 区分的。
            if (quote != null && quote.hasPrice) {
                PriceRow(
                    price = quote.avg24h,
                    changePct = detail.changePct,
                    money = viewModel::money,
                    priceStyle = MaterialTheme.typography.displaySmall,
                )
            } else {
                Text(
                    text = "暂无均价",
                    style = MaterialTheme.typography.displaySmall,
                    color = Extra.ink3,
                )
            }
            Text(
                text = "跳蚤市场 24 小时均价 · 涨跌为 48 小时口径",
                style = MaterialTheme.typography.labelSmall,
                color = Extra.ink3,
            )

            Spacer(Modifier.height(Spacing.md))
            ThinDivider()
            Spacer(Modifier.height(Spacing.md))

            Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                Tag(detail.category, container = MaterialTheme.colorScheme.primaryContainer)
                Tag(
                    detail.liquidity.label,
                    color = Extra.ink2,
                    container = Extra.track,
                )
            }

            Spacer(Modifier.height(Spacing.md))

            ValueLine("24h 最低", viewModel.money(quote?.low24h ?: 0))
            ValueLine("24h 最高", viewModel.money(quote?.high24h ?: 0))
            ValueLine("挂单数量", "${quote?.offerCount ?: 0}")
            ValueLine(
                label = "商人最高收购价",
                value = if (detail.bestTrader > 0) {
                    viewModel.money(detail.bestTrader)
                } else {
                    "暂无"
                },
                valueColor = if (detail.bestTrader > 0) {
                    MaterialTheme.colorScheme.onSurface
                } else {
                    Extra.ink3
                },
            )
            ValueLine("物品基准价", viewModel.money(quote?.basePrice ?: 0))

            if (detail.traders.isNotEmpty()) {
                Spacer(Modifier.height(Spacing.md))
                SectionTitle("商人回收价", trailing = "卖给商人")
                Spacer(Modifier.height(Spacing.xs))
                detail.traders.forEach { row ->
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(
                            text = row.name,
                            style = MaterialTheme.typography.bodyMedium,
                            color = Extra.ink2,
                        )
                        Text(
                            text = viewModel.money(row.price),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                            fontWeight = FontWeight.Medium,
                        )
                    }
                }
            }

            Spacer(Modifier.height(Spacing.md))
            SectionTitle("价格走势", trailing = "最近 $HISTORY_DAYS 天")
            Spacer(Modifier.height(Spacing.xs))
            when {
                detail.loading -> Text(
                    text = "正在拉曲线 ...",
                    style = MaterialTheme.typography.bodySmall,
                    color = Extra.ink3,
                )
                detail.curveEmpty -> Text(
                    text = "这个物品没有历史曲线",
                    style = MaterialTheme.typography.bodySmall,
                    color = Extra.ink3,
                )
                detail.curveText.isEmpty() -> Text(
                    text = "正在拉曲线 ...",
                    style = MaterialTheme.typography.bodySmall,
                    color = Extra.ink3,
                )
                else -> {
                    MiniCurve(detail.curve, viewModel::money)
                    Spacer(Modifier.height(Spacing.xs))
                    Text(
                        text = detail.curveText,
                        style = MaterialTheme.typography.bodySmall,
                        color = Extra.ink2,
                    )
                }
            }
        }
    }
}

@Composable
private fun ValueLine(label: String, value: String, valueColor: androidx.compose.ui.graphics.Color? = null) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = Extra.ink2,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            color = valueColor ?: MaterialTheme.colorScheme.onSurface,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
private fun RecentChip(name: String, query: String, onClick: () -> Unit) {
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surface,
        border = androidx.compose.foundation.BorderStroke(
            1.dp,
            MaterialTheme.colorScheme.outlineVariant,
        ),
        modifier = Modifier
            .heightIn(min = 36.dp)
            .clickable { onClick() },
    ) {
        Row(
            modifier = Modifier.padding(horizontal = Spacing.md, vertical = Spacing.sm),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = name,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
            )
            if (query.isNotEmpty()) {
                Spacer(Modifier.width(Spacing.xs))
                Text(
                    text = "· $query",
                    style = MaterialTheme.typography.labelSmall,
                    color = Extra.ink3,
                    maxLines = 1,
                )
            }
        }
    }
}
