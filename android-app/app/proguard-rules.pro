-keepattributes *Annotation*
# Keep JavaScript bridge methods
-keepclassmembers class com.autocop.quickcheckout.CheckoutBridge {
    @android.webkit.JavascriptInterface <methods>;
}
