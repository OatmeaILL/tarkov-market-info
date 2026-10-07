package com.tarkov.marketinfo

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tarkov.marketinfo.ui.HomeViewModel
import com.tarkov.marketinfo.ui.home.HomeScreen
import com.tarkov.marketinfo.ui.report.ReportScreen
import com.tarkov.marketinfo.ui.theme.TarkovTheme

/**
 * 唯一Activity。
 *
 * 报表不是新Activity 而是**同页切换**（`showReport` 一个布尔）：
 * 手机上返回键直接能回到查价页，不用处理 Activity 栈。
 * 桌面端是开新窗口，移动端这样更顺。
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            TarkovTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                    // 状态栏那一条留出安全区，否则顶栏会被刘海盖住
                    contentColor = MaterialTheme.colorScheme.onBackground,
                ) {
                    AppRoot()
                }
            }
        }
    }
}

@Composable
private fun AppRoot() {
    val viewModel: HomeViewModel = viewModel()
    val state by viewModel.state.collectAsState()

    Box(
        modifier = Modifier
            .fillMaxSize()
            .systemBarsPadding(),
    ) {
        if (state.showReport) {
            ReportScreen(
                viewModel = viewModel,
                onClose = viewModel::closeReport,
            )
        } else {
            HomeScreen(
                viewModel = viewModel,
                onOpenReport = viewModel::openReport,
            )
        }
    }
}
