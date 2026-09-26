import java.util.Properties

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing comes from android/key.properties, which is gitignored and never
// checked in. Missing it fails a release build loudly instead of falling back to debug signing.
val keyPropertiesFile = rootProject.file("key.properties")
val keyProperties = Properties()
val hasKeyProperties = keyPropertiesFile.exists()
if (hasKeyProperties) {
    keyPropertiesFile.inputStream().use { keyProperties.load(it) }
}
// checked on the task graph, so "assemble" or "build" can't slip out an unsigned release either
gradle.taskGraph.whenReady {
    if (!hasKeyProperties && allTasks.any { it.name.contains("Release") }) {
        throw GradleException(
            "Missing android/key.properties (storeFile, storePassword, keyAlias, keyPassword). Required for a release build."
        )
    }
}

android {
    namespace = "com.pocketdrs.pocket_drs"
    // camera_android is built against 36
    compileSdk = 36
    // Plugins used by PocketDRS currently require NDK 27.x.
    // This avoids build failures due to mismatched NDK versions.
    ndkVersion = "27.0.12077973"

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.pocketdrs.pocket_drs"
        // the server's certificate chains to ISRG Root X1, which Android only trusts from 7.1.1
        minSdk = 25
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasKeyProperties) {
            create("release") {
                storeFile = file(keyProperties.getProperty("storeFile"))
                storePassword = keyProperties.getProperty("storePassword")
                keyAlias = keyProperties.getProperty("keyAlias")
                keyPassword = keyProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (hasKeyProperties) signingConfigs.getByName("release") else null
        }
    }
}

flutter {
    source = "../.."
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}
