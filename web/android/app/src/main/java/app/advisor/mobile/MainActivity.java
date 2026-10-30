package app.advisor.mobile;

import android.webkit.WebView;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.WebViewListener;

public class MainActivity extends BridgeActivity {
    private boolean safeAreaHooked;

    /**
     * The live site is loaded from the server, so this keeps the status bar clear of the clock
     * even before that site's own safe-area padding is deployed. The rule matches ledger.css.
     */
    private static final String SAFE_AREA =
        "(function(){"
            + "var style=document.getElementById('advisor-safe');"
            + "if(!style){style=document.createElement('style');style.id='advisor-safe';document.head.appendChild(style);}"
            + "style.textContent='.statusbar{padding-top:calc(10px + var(--safe-area-inset-top, 0px)) !important}"
            + ".bottom-tabs{padding-bottom:var(--safe-area-inset-bottom, 0px) !important}';"
            + "})();";

    @Override
    public void onStart() {
        super.onStart();
        if (safeAreaHooked || getBridge() == null) return;
        safeAreaHooked = true;
        getBridge().addWebViewListener(
            new WebViewListener() {
                @Override
                public void onPageLoaded(WebView webView) {
                    webView.post(() -> webView.evaluateJavascript(SAFE_AREA, null));
                }
            }
        );
    }
}
