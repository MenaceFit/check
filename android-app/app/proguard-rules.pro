-keepattributes *Annotation*

# Keep all @JavascriptInterface methods in the bridge
-keepclassmembers class com.autocop.quickcheckout.CheckoutBridge {
    @android.webkit.JavascriptInterface <methods>;
}

# Keep all public members of the bridge so MainActivity can call them
-keep class com.autocop.quickcheckout.CheckoutBridge { *; }
-keep class com.autocop.quickcheckout.SettingsDialog  { *; }
-keep class com.autocop.quickcheckout.MainActivity    { *; }
