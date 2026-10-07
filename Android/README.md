# TarkovMarketInfo · Android

逃离塔科夫查价工具的 Android 版。查价 + 排行报表两个功能，配色和桌面版一套。

数据来自 [json.tarkov.dev](https://json.tarkov.dev)，首次启动联网拉一次全量（5400+ 项），之后可以离线查价。

## 和桌面版的差别

两个端是**独立源码**（Android 在 `Android/`，桌面端在 `src/`），不共享代码，只共享接口和口径。

| | 桌面版 | Android |
|---|---|---|
| 技术栈 | Python 3.14 + tkinter | Kotlin + Jetpack Compose |
| 图标 | 本地 5300 张 webp（16MB 包） | 按需拉单张，缓存在 cacheDir |
| 排序选择 | 键盘上下键 | 点候选 + 上一/下一按钮 |
| 报表导出 | HTML / PNG / CSV | 不导出（手机上没地方放） |
| 数据存储 | SQLite `data/tarkov.db` | Room `tarkov.db` |

**同样的地方**：搜索打分表（8 个权重）、同义词表、取价四级回退、
分类归并顺序、商人回收价口径、48 小时涨跌口径 —— 两个端结果一致。

## 有意做得不一样的三处

移植时发现桌面版 `src/search.py` / `data.py` 有三个缺陷，Android 侧**没有照抄**：

1. **`wants_part` 是死变量**
   桌面版算了却从没参与判断，于是搜「消音器」时真消音器反被扣 -10 分，
   排第一的是「消音手枪」。Android 把 `wants_part` 接进判断，真消音器回到第一。

2. **`top_movers` 没按符号过滤**
   桌面版的 pool 只过掉零值，没分正负；只勾「涨」时会把跌 40% 的也列进来
   （真实数据里涨的远多于 count，所以一直没暴露）。Android 按符号切干净。

3. **`Math.round` 和 Python `round` 的 .5 处理不同**
   搜 `m4` 时长度惩罚是 -5.5，`Math.round(-5.5)` 给 -5、`round(-5.5)` 给 -6，
   结果 M4A1 抢在 M45A1 前面。Android 写了 `pyRound` 对齐 Python 的「四舍六入五成双」。

这三条都写在对应代码的注释里，也都写了回归测试。**桌面版要不要跟着修，等确认。**

## 构建

依赖的 SDK / Gradle / JDK 复用同目录下的 MaiBill 项目环境：

```bash
# 第一次构建：先从模板拷一份 SDK 路径配置，改成你自己的路径
cp Android/local.properties.example Android/local.properties

source "E:/Programming/xioamaipian/MaiBill/build-env/env.sh"
cd Android
gradle testDebugUnitTest assembleDebug
```

产物：`app/build/outputs/apk/debug/app-debug.apk`

> ⚠️ `local.properties` 是机器相关的，**不进仓库**（模板是 `local.properties.example`）。
> 如果 MaiBill 那个目录被清理了，需要自己准备：JDK 17 + Android SDK（platform 35）+ Gradle 8.9。

## 工程结构

```
app/src/main/java/com/tarkov/marketinfo/
├── core/            纯逻辑，零 Android 依赖，能在 JVM 上单测
│   ├── Consts.kt      接口地址、常量
│   ├── Search.kt      搜索打分链（移植自桌面 search.py）
│   ├── Price.kt       取价 / 曲线 / 格式化
│   └── Report.kt      报表筛选排序 + 分类归并
├── data/            Room + 联网
│   ├── Entity.kt      5 张表
│   ├── Daos.kt        DAO
│   ├── AppDatabase.kt 单例
│   ├── SyncService.kt 拉全量 + 手写 JSON 解析
│   └── Repository.kt  取价四级回退、曲线缓存、收藏、最近
└── ui/
    ├── theme/         配色（搬桌面 theme.py）
    ├── components/    通用控件
    ├── home/          查价页 + 走势图
    ├── report/        报表页
    └── HomeViewModel.kt 唯一的状态源
```

`core` 层刻意不引 Android 依赖：搜索、取价、筛选这些纯逻辑能在普通 JVM
单元测试里跑（71 个测试，秒级出结果），不用起模拟器。

## 测试

```bash
gradle testDebugUnitTest
```

覆盖：搜索归一化 / 门槛 / 排序 / 打分细节、取价口径、曲线摘要、
筛选排序、分类归并、涨跌榜、接口地址大小写、JSON 解析容错、曲线序列化往返。

## 作者

OatmeaILL · https://github.com/OatmeaILL

## 说明

数据接口和图标来自 [tarkov.dev](https://tarkov.dev) 的公开服务，
本工具只做查询展示，与 Battlestate Games 无关。
