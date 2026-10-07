package com.tarkov.marketinfo.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * 配色 —— 逐个搬桌面端 `src/theme.py` 的值，两个端看起来是一套东西。
 *
 * 浅色（桌面端 v1.3 用的这套）：
 *   page #E9ECE5 底色（淡灰绿，比纯白耐看）
 *   主色 #2E9C74 薄荷，对齐 MaiBill v2.4「褪色薄荷」的 MintPrimary
 *   ink  #1B2A21 正文（深墨绿，比纯黑柔和）
 *
 * 深色（桌面端也有一套，两个端一起切）。
 *
 * 涨跌色按 A 股习惯：**涨红跌绿**，和欧美市场相反。桌面端也是这个口径。
 */

// ---------- 浅色 ----------
val PageLight = Color(0xFFE9ECE5)
val BgLight = Color(0xFFF4F6F1)
val SurfaceLight = Color(0xFFFFFFFF)
val Surface2Light = Color(0xFFFBFCFA)
val TrackLight = Color(0xFFEDF0EA)
val TrackbarLight = Color(0xFFE2E8E0)

val InkLight = Color(0xFF1B2A21)
val Ink2Light = Color(0xFF5C6960)
val Ink3Light = Color(0xFF7B867D)
val LineLight = Color(0xFFE8ECE6)

val PrimaryLight = Color(0xFF2E9C74)
val PrimaryDeepLight = Color(0xFF195E49)
val PrimarySoftLight = Color(0xFF6FC9A2)
val PrimaryContainerLight = Color(0xFFDFF2E8)
val OnPrimaryContainerLight = Color(0xFF0C3B27)

val AmberLight = Color(0xFFC08A2E)
val AmberContainerLight = Color(0xFFFAF0DA)

// 涨红跌绿（A 股口径）
val UpLight = Color(0xFFD1443A)
val DownLight = Color(0xFF1E9E6A)
val UpContainerLight = Color(0xFFFBE9E6)
val DownContainerLight = Color(0xFFDFF2E8)

val ShadowLight = Color(0xFFD8DED6)

// ---------- 深色 ----------
// 深色的主色比浅色**更亮**（#4FC08D而不是 #2E9C74）——深底上暗色会糊成一片。
// 桌面端 `theme.DARK` 也是这么配的。
val PageDark = Color(0xFF070907)
val BgDark = Color(0xFF10140F)
val SurfaceDark = Color(0xFF1A211B)
val Surface2Dark = Color(0xFF20281F)
val TrackDark = Color(0xFF263027)
val TrackbarDark = Color(0xFF2F3B31)

val InkDark = Color(0xFFE9EEE9)
val Ink2Dark = Color(0xFF9AA69C)
val Ink3Dark = Color(0xFF68736A)
val LineDark = Color(0xFF242D24)

val PrimaryDark = Color(0xFF4FC08D)
val PrimaryDeepDark = Color(0xFF2E9C74)
val PrimaryContainerDark = Color(0xFF1E3B2D)
val OnPrimaryContainerDark = Color(0xFFB9F0D4)

val AmberDark = Color(0xFFE0B45E)
val AmberContainerDark = Color(0xFF332C1C)

// 涨红跌绿：深底上要比浅色更亮才看得清
val UpDark = Color(0xFFEF7466)
val DownDark = Color(0xFF4FC08D)
val UpContainerDark = Color(0xFF3A211D)
val DownContainerDark = Color(0xFF1E3B2D)
