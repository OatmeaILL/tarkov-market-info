plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")
}

android {
    namespace = "com.tarkov.marketinfo"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.tarkov.marketinfo"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.3"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            // 桌面端用 debug 签名当兜底，保证新克隆的仓库能直接构建。
            // 手机上装不了debug 包以外的包之前，先用 debug 签名。
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources {
            excludes += setOf("/META-INF/{AL2.0,LGPL2.1}")
        }
    }
}

dependencies {
    // Compose（版本与 MaiBill 对齐，少踩一份兼容坑）
    implementation(platform("androidx.compose:compose-bom:2024.09.03"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")

    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.6")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")

    // Room：物品索引、收藏、历史曲线、设置都走这里
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")

    // 查价搜索是纯本地同步计算，索引放内存里查（5476项约几毫秒）
    // 不引入协程库，Kotlin 协程已随lifecycle-viewmodel 传递进来

    testImplementation("junit:junit:4.13.2")
    testImplementation(platform("androidx.compose:compose-bom:2024.09.03"))
}