plugins {
    id("com.android.application")
}

android {
    namespace = "io.github.webby888.sunburstnavy"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.webby888.sunburstnavy"
        // Watch Face Format v2 needs Wear OS 5 (API 34); the Galaxy Watch Ultra shipped with it.
        minSdk = 34
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Sideload-only build: reuse the debug key. Use a real upload key before publishing to Play.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}
