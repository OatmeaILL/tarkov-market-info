package com.tarkov.marketinfo

import android.app.Application
import com.tarkov.marketinfo.data.Graph

/**
 * 应用入口。
 *
 * 只做一件事：初始化 Room 单例。
 * 桌面端的 `app.AppShell.__init__` 还要建目录、查资源、初始化历史库，
 * 移动端这些 Room / Context 都自己管，不用手动建目录。
 */
class TarkovApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Graph.init(this)
    }
}
