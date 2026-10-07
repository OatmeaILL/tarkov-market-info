package com.tarkov.marketinfo.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 应用主题。
 *
 * 色板不用 Material3 的默认色，全用桌面端 `theme.py` 的值——
 * Material3 默认的紫青色跟"褪色薄荷"完全不是一回事。
 * 组件库只借它的**行为**（焦点、点击态、无障碍），颜色和字体自己定。
 */

/** 涨跌色单独拎出来：Material3 的 colorScheme 没有"涨/跌"这种语义位。 */
data class TrendColors(
    val up: Color,
    val down: Color,
    val upContainer: Color,
    val downContainer: Color,
)

/** 桌面端 theme.py 里那些 Material3 语义位放不下的颜色。 */
data class ExtraColors(
    val ink2: Color,
    val ink3: Color,
    val track: Color,
    val trackbar: Color,
    val surface2: Color,
    val amber: Color,
    val amberContainer: Color,
    val primaryDeep: Color,
)

val LocalTrend = staticCompositionLocalOf {
    TrendColors(
        UpLight, DownLight, UpContainerLight, DownContainerLight,
    )
}

val LocalExtra = staticCompositionLocalOf {
    ExtraColors(
        Ink2Light, Ink3Light, TrackLight, TrackbarLight, Surface2Light,
        AmberLight, AmberContainerLight, PrimaryDeepLight,
    )
}

private val LightScheme = lightColorScheme(
    primary = PrimaryLight,
    onPrimary = Color.White,
    primaryContainer = PrimaryContainerLight,
    onPrimaryContainer = OnPrimaryContainerLight,
    secondary = PrimaryDeepLight,
    onSecondary = Color.White,
    background = BgLight,
    onBackground = InkLight,
    surface = SurfaceLight,
    onSurface = InkLight,
    surfaceVariant = Surface2Light,
    onSurfaceVariant = Ink2Light,
    outline = LineLight,
    outlineVariant = TrackLight,
    error = UpLight,
    onError = Color.White,
    errorContainer = UpContainerLight,
    onErrorContainer = OnPrimaryContainerLight,
    scrim = Color(0x99000000),
)

private val DarkScheme = darkColorScheme(
    primary = PrimaryDark,
    onPrimary = Color(0xFF08160F),
    primaryContainer = PrimaryContainerDark,
    onPrimaryContainer = OnPrimaryContainerDark,
    secondary = PrimaryDeepDark,
    onSecondary = Color.White,
    background = BgDark,
    onBackground = InkDark,
    surface = SurfaceDark,
    onSurface = InkDark,
    surfaceVariant = Surface2Dark,
    onSurfaceVariant = Ink2Dark,
    outline = LineDark,
    outlineVariant = TrackDark,
    error = UpDark,
    onError = Color(0xFF3A0F0B),
    errorContainer = UpContainerDark,
    onErrorContainer = UpDark,
    scrim = Color(0xB3000000),
)

/**
 * 字号。
 *
 * 移动端比桌面端整体大一号：桌面端窗口 720px 宽、手机屏360~430dp 宽，
 * 同样的物理尺寸下手机上字要更大才看得清。
 */
private val AppTypography = Typography(
    displaySmall = TextStyle(fontSize = 28.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.4).sp),
    headlineSmall = TextStyle(fontSize = 22.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.2).sp),
    titleLarge = TextStyle(fontSize = 19.sp, fontWeight = FontWeight.SemiBold),
    titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold),
    titleSmall = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.SemiBold),
    bodyLarge = TextStyle(fontSize = 15.sp, lineHeight = 21.sp),
    bodyMedium = TextStyle(fontSize = 13.5.sp, lineHeight = 19.sp),
    bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 17.sp),
    labelLarge = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.SemiBold),
    labelMedium = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Medium),
    labelSmall = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Medium),
)

@Composable
fun TarkovTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    // 涨跌色和桌面端的 danger 色不同语义：涨跌是红绿，danger 是警示红，
    // 混用会让"跌了 20%"被看成报错。所以单独一组。
    val trend = if (darkTheme) {
        TrendColors(UpDark, DownDark, UpContainerDark, DownContainerDark)
    } else {
        TrendColors(UpLight, DownLight, UpContainerLight, DownContainerLight)
    }
    val extra = if (darkTheme) {
        ExtraColors(
            Ink2Dark, Ink3Dark, TrackDark, TrackbarDark, Surface2Dark,
            AmberDark, AmberContainerDark, PrimaryDeepDark,
        )
    } else {
        ExtraColors(
            Ink2Light, Ink3Light, TrackLight, TrackbarLight, Surface2Light,
            AmberLight, AmberContainerLight, PrimaryDeepLight,
        )
    }

    CompositionLocalProvider(LocalTrend provides trend, LocalExtra provides extra) {
        MaterialTheme(
            colorScheme = if (darkTheme) DarkScheme else LightScheme,
            typography = AppTypography,
            content = content,
        )
    }
}

/** 便捷取色：涨跌 */
object Trend {
    val up: Color
        @Composable get() = LocalTrend.current.up
    val down: Color
        @Composable get() = LocalTrend.current.down
    val flat: Color
        @Composable get() = LocalExtra.current.ink3
}

/** 便捷取色：Material3 放不下的那些 */
object Extra {
    val ink2: Color
        @Composable get() = LocalExtra.current.ink2
    val ink3: Color
        @Composable get() = LocalExtra.current.ink3
    val track: Color
        @Composable get() = LocalExtra.current.track
    val surface2: Color
        @Composable get() = LocalExtra.current.surface2
    val amber: Color
        @Composable get() = LocalExtra.current.amber
    val primaryDeep: Color
        @Composable get() = LocalExtra.current.primaryDeep
}

/** 统一间距。桌面端是 8 / 12 / 16 / 20，移动端照搬。 */
object Spacing {
    val xs = 4.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 20.dp
}
