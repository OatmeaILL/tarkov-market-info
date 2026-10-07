package com.tarkov.marketinfo.ui.home

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import com.tarkov.marketinfo.core.PricePoint
import com.tarkov.marketinfo.ui.theme.Extra
import com.tarkov.marketinfo.ui.theme.Trend
import kotlin.math.abs

/**
 * 迷你走势图。
 *
 * 桌面端是 Canvas 手绘（`home.py` 的 `_draw_curve`），这边也是 Canvas，
 * 但省掉了坐标轴和刻度：手机上那么小一块，画了看不清反而更乱。
 * 只画趋势 + 渐变填充，涨跌一眼能看出来。
 *
 * 画法：把点位按价格映射到 y 坐标，价格高的在上（y 小）。
 * 涨用红、跌用绿（和全app 一致），线下方同色渐变淡出。
 */
@Composable
fun MiniCurve(
    points: List<PricePoint>,
    money: (Int) -> String,
    modifier: Modifier = Modifier,
    heightDp: Int = 72,
) {
    if (points.size < 2) return

    val rising = points.last().price >= points.first().price
    val lineColor = if (rising) Trend.up else Trend.down
    // 采集时的颜色（Trend 是 @Composable，Canvas 的 lambda 里读不到，得先取出来）
    val fillTop = lineColor.copy(alpha = 0.28f)
    val fillBottom = lineColor.copy(alpha = 0.02f)
    val gridColor = Extra.ink3.copy(alpha = 0.18f)
    val density = LocalDensity.current

    val minPrice = points.minOf { it.price }
    val maxPrice = points.maxOf { it.price }
    val span = (maxPrice - minPrice).coerceAtLeast(1)

    Box(modifier = modifier.fillMaxWidth().height(heightDp.dp)) {
        Canvas(modifier = Modifier.fillMaxWidth().height(heightDp.dp)) {
            val w = size.width
            val h = size.height
            // 上下各留 6dp 的余量，线不要顶到边框
            val pad = with(density) { 6.dp.toPx() }
            val usable = h - pad * 2

            fun pointAt(index: Int): Offset {
                val x = w * index / (points.size - 1).toFloat()
                // 归一化到 0..1，价格最高 → 0（顶部）
                val ratio = (points[index].price - minPrice).toFloat() / span
                val y = pad + usable * (1f - ratio)
                return Offset(x, y)
            }

            // 中间一条淡横线，给个"基准"参照，不然曲线悬空看不出高低
            drawLine(
                color = gridColor,
                start = Offset(0f, h / 2f),
                end = Offset(w, h / 2f),
                strokeWidth = 1f,
            )

            val linePath = Path()
            val fillPath = Path()
            for (index in points.indices) {
                val current = pointAt(index)
                if (index == 0) {
                    linePath.moveTo(current.x, current.y)
                    // 填充路径从左下角起，闭合到右下角
                    fillPath.moveTo(current.x, h)
                    fillPath.lineTo(current.x, current.y)
                } else {
                    linePath.lineTo(current.x, current.y)
                    fillPath.lineTo(current.x, current.y)
                }
            }
            fillPath.lineTo(w, h)
            fillPath.close()

            drawPath(
                path = fillPath,
                brush = Brush.verticalGradient(
                    colors = listOf(fillTop, fillBottom),
                    startY = 0f,
                    endY = h,
                ),
            )
            drawPath(
                path = linePath,
                color = lineColor,
                style = Stroke(
                    width = with(density) { 2.dp.toPx() },
                    cap = StrokeCap.Round,
                    join = StrokeJoin.Round,
                ),
            )

            // 末点画个实心圆：当前价所在位置
            val last = pointAt(points.size - 1)
            drawCircle(color = lineColor, radius = with(density) { 3.dp.toPx() }, center = last)
        }
    }
}

/** 首末价差的一句话摘要。空数据显示「暂无均价」。 */
fun priceSummaryText(hasPrice: Boolean, avg: Int, money: (Int) -> String): String =
    if (hasPrice) "均价 ${money(avg)}" else "暂无均价"
