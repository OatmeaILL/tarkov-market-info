package com.tarkov.marketinfo.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tarkov.marketinfo.ui.theme.Extra
import com.tarkov.marketinfo.ui.theme.Spacing
import com.tarkov.marketinfo.ui.theme.Trend

/**
 * 通用组件。
 *
 * 视觉口径全部对齐桌面端（`widgets.py` + `theme.py`）：
 * 卡片纯色不透明 + 1px 描边、圆角 12、主色薄荷、涨跌红绿。
 * 不加阴影 —— 桌面端靠描边分层，加了阴影在手机上会显得脏。
 */

/** 卡片：白底 + 细描边，代替阴影分层。 */
@Composable
fun FlatCard(
    modifier: Modifier = Modifier,
    selected: Boolean = false,
    onClick: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    val border = if (selected) {
        BorderStroke(2.dp, MaterialTheme.colorScheme.primary)
    } else {
        BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)
    }
    val base = modifier
        .clip(RoundedCornerShape(12.dp))
        .background(
            if (selected) {
                MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.35f)
            } else {
                MaterialTheme.colorScheme.surface
            }
        )
    Card(
        modifier = if (onClick != null) base.clickable { onClick() } else base,
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = Color.Transparent,
        ),
        border = border,
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        content()
    }
}

/** 小标签：分类、流动性那种。 */
@Composable
fun Tag(
    text: String,
    color: Color = MaterialTheme.colorScheme.onSurfaceVariant,
    container: Color = Extra.track,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(6.dp),
        color = container,
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
            maxLines = 1,
        )
    }
}

/**
 * 价格 + 涨跌。
 *
 * 涨红跌绿（A 股口径，和桌面端一致）。
 * 涨跌为 0 时用中性灰，别显示成绿色——"没跌"不等于"涨"。
 */
@Composable
fun PriceRow(
    price: Int,
    changePct: Double,
    money: (Int) -> String,
    modifier: Modifier = Modifier,
    priceStyle: androidx.compose.ui.text.TextStyle = MaterialTheme.typography.titleLarge,
) {
    val color = when {
        changePct > 0.0 -> Trend.up
        changePct < 0.0 -> Trend.down
        else -> Extra.ink3
    }
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = money(price),
            style = priceStyle,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.width(Spacing.sm))
        if (changePct != 0.0) {
            val arrow = if (changePct > 0) "▲" else "▼"
            val sign = if (changePct > 0) "+" else ""
            Text(
                text = "$arrow$sign${formatPct(changePct)}",
                style = MaterialTheme.typography.labelMedium,
                color = color,
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
}

/** 百分比格式化：1 位小数，带正负号。0.0 返回空串（不占位）。 */
fun formatPct(value: Double): String {
    if (value == 0.0) return ""
    val rounded = Math.round(value * 10.0) / 10.0
    return if (rounded > 0) "+$rounded%" else "$rounded%"
}

/** 涨跌颜色的统一出口。 */
@Composable
fun trendColor(changePct: Double): Color = when {
    changePct > 0.0 -> Trend.up
    changePct < 0.0 -> Trend.down
    else -> Extra.ink3
}

/** 一行「标签 : 值」，详情面板里用得最多。 */
@Composable
fun LabeledValue(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    valueColor: Color = MaterialTheme.colorScheme.onSurface,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = Extra.ink2,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            color = valueColor,
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/** 空状态占位。 */
@Composable
fun EmptyHint(
    text: String,
    icon: ImageVector? = null,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth().padding(vertical = Spacing.xl),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (icon != null) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = Extra.ink3,
                modifier = Modifier.size(36.dp),
            )
            Spacer(Modifier.height(Spacing.md))
        }
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            color = Extra.ink3,
        )
    }
}

/** 分区标题（带一条细线）。 */
@Composable
fun SectionTitle(
    text: String,
    modifier: Modifier = Modifier,
    trailing: String = "",
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onSurface,
        )
        if (trailing.isNotEmpty()) {
            Spacer(Modifier.width(Spacing.sm))
            Text(
                text = trailing,
                style = MaterialTheme.typography.labelSmall,
                color = Extra.ink3,
            )
        }
    }
}

/** 竖排细线分隔。 */
@Composable
fun ThinDivider(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(MaterialTheme.colorScheme.outlineVariant),
    )
}
