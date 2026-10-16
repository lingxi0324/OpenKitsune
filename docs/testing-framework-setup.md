# 自动化测试框架配置指南

## 1. 依赖配置 (app/build.gradle.kts)

```kotlin
dependencies {
    // JUnit 5
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.2")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
    
    // Mockito
    testImplementation("org.mockito:mockito-core:5.10.0")
    testImplementation("org.mockito.kotlin:mockito-kotlin:5.2.1")
    
    // Kotlin Coroutines Test
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.0")
    
    // Truth for assertions
    testImplementation("com.google.truth:truth:1.4.2")
    
    // AndroidX Test (for instrumented tests)
    androidTestImplementation("androidx.test:core:1.5.0")
    androidTestImplementation("androidx.test:runner:1.5.2")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
}

android {
    testOptions {
        unitTests.all {
            it.useJUnitPlatform()
        }
    }
}
```

## 2. JaCoCo 覆盖率配置 (app/build.gradle.kts)

```kotlin
plugins {
    id("jacoco")
}

jacoco {
    toolVersion = "0.8.11"
}

tasks.withType<Test> {
    configure<JacocoTaskExtension> {
        isIncludeNoLocationClasses = true
        excludes = listOf("jdk.internal.*")
    }
}

tasks.register<JacocoReport>("jacocoTestReport") {
    dependsOn("testDebugUnitTest", "createDebugCoverageReport")
    
    reports {
        xml.required.set(true)
        html.required.set(true)
        csv.required.set(false)
    }
    
    val fileFilter = listOf(
        "**/R.class",
        "**/R$*.class",
        "**/BuildConfig.*",
        "**/Manifest*.*",
        "**/*Test*.*",
        "android/**/*.*",
        "**/di/**",
        "**/model/**",
        "**/view/**"
    )
    
    val debugTree = fileTree("${buildDir}/tmp/kotlin-classes/debug") {
        exclude(fileFilter)
    }
    
    val mainSrc = "${project.projectDir}/src/main/java"
    
    sourceDirectories.setFrom(files(mainSrc))
    classDirectories.setFrom(files(debugTree))
    executionData.setFrom(fileTree("${buildDir}") {
        include("outputs/unit_test_code_coverage/debugUnitTest/testDebugUnitTest.exec")
        include("jacoco/testDebugUnitTest.exec")
    })
    
    doLast {
        val htmlReport = reports.html.outputLocation.get().asFile
        println("✅ Jacoco 报告生成成功: ${htmlReport.absolutePath}")
    }
}
```

## 3. 测试覆盖率目标

- **整体覆盖率目标**: ≥70%
- **核心业务逻辑**: ≥85%
- **ViewModel**: ≥80%
- **UseCase**: ≥90%
- **Repository**: ≥75%

## 4. 示例测试用例结构

```
src/
├── test/
│   └── java/
│       └── com/openkitsune/app/
│           ├── data/
│           │   └── repository/
│           │       └── UserRepositoryTest.kt
│           ├── domain/
│           │   └── usecase/
│           │       └── GetUserProfileUseCaseTest.kt
│           └── presentation/
│               └── viewmodel/
│                   └── ProfileViewModelTest.kt
└── androidTest/
    └── java/
        └── com/openkitsune/app/
            └── ui/
                └── MainActivityTest.kt
```

## 5. 运行测试命令

```bash
# 运行所有单元测试
./gradlew test

# 运行带覆盖率的测试并生成报告
./gradlew jacocoTestReport

# 运行特定模块测试
./gradlew :app:testDebugUnitTest

# 查看覆盖率报告 (HTML)
open app/build/reports/jacoco/jacocoTestReport/html/index.html
```

## 6. CI/CD 集成

GitHub Actions 将自动执行：
1. `./gradlew test` - 运行所有单元测试
2. `./gradlew jacocoTestReport` - 生成覆盖率报告
3. 上传覆盖率报告到 Codecov (可选)
4. 覆盖率低于 70% 时构建失败

---
*最后更新: 2026-04-07 | CTO 技术部*
