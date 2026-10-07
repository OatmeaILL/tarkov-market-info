package com.tarkov.marketinfo.ui.report

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.tarkov.marketinfo.core.Item
import com.tarkov.marketinfo.core.Liquidity
import com.tarkov.marketinfo.core.ReportOptions
import com.tarkov.marketinfo.core.SortField
import com.tarkov.marketinfo.core.itemCategory
import com.tarkov.marketinfo.core.sortValue
import com.tarkov.marketinfo.ui.HomeViewModel
import com.tarkov.marketinfo.ui.components.FlatCard
import com.tarkov.marketinfo.ui.components.PriceRow
import com.tarkov.marketinfo.ui.components.SectionTitle
import com.tarkov.marketinfo.ui.components.Tag
import com.tarkov.marketinfo.ui.components.ThinDivider
import com.tarkov.marketinfo.ui.components.formatPct
import com.tarkov.marketinfo.ui.components.trendColor
import com.tarkov.marketinfo.ui.theme.Extra
import com.tarkov.marketinfo.ui.theme.Spacing

/**
 * 报表页。
 *
 * 筛选口径和桌面端 `report.py` 一致：排序字段 + 升降序 + 条数 + 关键词 +
 * 只要跳蚤可交易 + 跳过零值 + 最低价门槛。桌面端能导出 HTML/PNG/CSV，
 * 移动端**不做导出**（手机上没那个需求，文件也没地方放）。
 */
@Composable
fun ReportScreen(
    viewModel: HomeViewModel,
    onClose: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val options = state.reportOptions
    val report by viewModel.report.collectAsStateWithLifecycle()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
    ) {
        // 顶栏
        Surface(color = MaterialTheme.colorScheme.surface) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = Spacing.lg, end = Spacing.sm, top = Spacing.md, bottom = Spacing.md),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "排行报表",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = "共 ${report.total} 项符合条件",
                        style = MaterialTheme.typography.labelSmall,
                        color = Extra.ink3,
                    )
                }
                IconButton(onClick = onClose) {
                    Icon(Icons.Filled.Close, contentDescription = "关闭")
                }
            }
        }
        ThinDivider()

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = Spacing.lg, end = Spacing.lg,
                top = Spacing.md, bottom = Spacing.xl,
            ),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            item { FilterPanel(options, viewModel) }

            if (report.upItems.isNotEmpty() || report.downItems.isNotEmpty()) {
                item { Spacer(Modifier.height(Spacing.sm)) }
                item { SectionTitle("48 小时涨跌榜") }
                if (report.upItems.isNotEmpty()) {
                    item {
                        MoverStrip(
                            title = "涨得最多",
                            items = report.upItems,
                            money = viewModel::money,
                        )
                    }
                }
                if (report.downItems.isNotEmpty()) {
                    item {
                        MoverStrip(
                            title = "跌得最多",
                            items = report.downItems,
                            money = viewModel::money,
                        )
                    }
                }
            }

            item { Spacer(Modifier.height(Spacing.sm)) }
            item {
                SectionTitle(
                    text = if (options.groupByCategory) "分类明细" else "明细",
                    trailing = "${report.rows.size} 条",
                )
            }

            if (report.byCategory) {
                report.groups.forEach { group ->
                    item(key = "g-${group.name}") {
                        Text(
                            text = group.name,
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onSurface,
                            modifier = Modifier.padding(top = Spacing.sm),
                        )
                    }
                    items(group.items, key = { "i-${it.id}" }) { item ->
                        ReportRow(item, options, viewModel)
                    }
                }
            } else {
                items(report.rows, key = { it.id }) { item ->
                    ReportRow(item, options, viewModel)
                }
            }

            if (report.rows.isEmpty()) {
                item {
                    Text(
                        text = "没有符合条件的物品，放宽筛选试试",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Extra.ink3,
                        modifier = Modifier.padding(vertical = Spacing.xl),
                    )
                }
            }
        }
    }
}

@Composable
private fun FilterPanel(options: ReportOptions, viewModel: HomeViewModel) {
    FlatCard {
        Column(modifier = Modifier.padding(Spacing.lg)) {
            Text(
                text = "排序口径",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(Spacing.sm))
            LazyRow(horizontalArrangement = Arrangement.spacedBy(Spacing.xs)) {
                items(SortField.entries.toList()) { field ->
                    val selected = options.sortField == field
                    Tag(
                        text = field.label,
                        color = if (selected) {
                            MaterialTheme.colorScheme.onPrimaryContainer
                        } else {
                            Extra.ink2
                        },
                        container = if (selected) {
                            MaterialTheme.colorScheme.primaryContainer
                        } else {
                            Extra.track
                        },
                        modifier = Modifier.clickable {
                            viewModel.updateReportOptions(options.copy(sortField = field))
                        },
                    )
                }
            }

            Spacer(Modifier.height(Spacing.md))
            SwitchRow(
                label = "从高到低",
                checked = options.descending,
                onChange = { viewModel.updateReportOptions(options.copy(descending = it)) },
            )
            SwitchRow(
                label = "只要能在跳蚤市场交易",
                checked = options.fleaOnly,
                onChange = { viewModel.updateReportOptions(options.copy(fleaOnly = it)) },
            )
            SwitchRow(
                label = "跳过零值",
                checked = options.skipZero,
                onChange = { viewModel.updateReportOptions(options.copy(skipZero = it)) },
            )
            SwitchRow(
                label = "按大类归并",
                checked = options.groupByCategory,
                onChange = { viewModel.updateReportOptions(options.copy(groupByCategory = it)) },
            )
            SwitchRow(
                label = "涨跌幅榜 · 涨",
                checked = options.showGainers,
                onChange = { viewModel.updateReportOptions(options.copy(showGainers = it)) },
            )
            SwitchRow(
                label = "涨跌幅榜 · 跌",
                checked = options.showLosers,
                onChange = { viewModel.updateReportOptions(options.copy(showLosers = it)) },
            )

            Spacer(Modifier.height(Spacing.md))
            OutlinedTextField(
                value = options.keyword,
                onValueChange = { viewModel.updateReportOptions(options.copy(keyword = it)) },
                label = { Text("名称关键词") },
                singleLine = true,
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(Spacing.md))
            Text(
                text = "显示条数：${if (options.limit == 0) "不限" else options.limit}",
                style = MaterialTheme.typography.bodyMedium,
                color = Extra.ink2,
            )
            // 五档吸附而不是连续滑块：手指粗，连续值很难拖到想要的数
            LazyRow(horizontalArrangement = Arrangement.spacedBy(Spacing.xs)) {
                items(LIMIT_STEPS) { step ->
                    val selected = options.limit == step
                    Tag(
                        text = if (step == 0) "不限" else "$step",
                        color = if (selected) {
                            MaterialTheme.colorScheme.onPrimaryContainer
                        } else {
                            Extra.ink2
                        },
                        container = if (selected) {
                            MaterialTheme.colorScheme.primaryContainer
                        } else {
                            Extra.track
                        },
                        modifier = Modifier.clickable {
                            viewModel.updateReportOptions(options.copy(limit = step))
                        },
                    )
                }
            }

            if (options.minPrice > 0) {
                Text(
                    text = "最低价门槛：${viewModel.money(options.minPrice)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = Extra.ink3,
                )
            }
        }
    }
}

@Composable
private fun SwitchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onChange(!checked) }
            .padding(vertical = Spacing.xs),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
private fun MoverStrip(title: String, items: List<Item>, money: (Int) -> String) {
    Column(modifier = Modifier.padding(vertical = Spacing.xs)) {
        Text(
            text = title,
            style = MaterialTheme.typography.labelMedium,
            color = Extra.ink2,
        )
        Spacer(Modifier.height(Spacing.xs))
        LazyRow(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            items(items, key = { it.id }) { item ->
                val name = item.nameZh.ifEmpty { item.nameEn.ifEmpty { item.shortName } }
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = MaterialTheme.colorScheme.surface,
                    border = androidx.compose.foundation.BorderStroke(
                        1.dp,
                        trendColor(item.change48hPct).copy(alpha = 0.35f),
                    ),
                ) {
                    Column(modifier = Modifier.width(132.dp).padding(Spacing.md)) {
                        Text(
                            text = name,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurface,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Spacer(Modifier.height(2.dp))
                        Text(
                            text = formatPct(item.change48hPct),
                            style = MaterialTheme.typography.titleSmall,
                            color = trendColor(item.change48hPct),
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            text = money(item.avg24h),
                            style = MaterialTheme.typography.labelSmall,
                            color = Extra.ink3,
                            maxLines = 1,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ReportRow(item: Item, options: ReportOptions, viewModel: HomeViewModel) {
    val name = item.nameZh.ifEmpty { item.nameEn.ifEmpty { item.shortName } }
    FlatCard {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.md, vertical = Spacing.md),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = name,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(3.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.xs)) {
                    Tag(itemCategory(item), container = Extra.track, color = Extra.ink2)
                    Tag(
                        Liquidity.of(item.offerCount).label,
                        container = Extra.track,
                        color = Extra.ink3,
                    )
                }
            }
            Spacer(Modifier.width(Spacing.sm))
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = viewModel.money(sortValue(item, options.sortField)),
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = formatPct(item.change48hPct).ifEmpty { "持平" },
                    style = MaterialTheme.typography.labelSmall,
                    color = trendColor(item.change48hPct),
                )
            }
        }
    }
}

/** 显示条数的档位。0 = 不限。 */
private val LIMIT_STEPS = listOf(0, 25, 50, 100, 200)
