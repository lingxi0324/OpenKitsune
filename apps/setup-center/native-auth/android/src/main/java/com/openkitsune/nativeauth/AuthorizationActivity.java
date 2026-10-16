package com.openkitsune.nativeauth;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import androidx.activity.result.ActivityResultLauncher;
import androidx.appcompat.app.AppCompatActivity;
import androidx.browser.auth.AuthTabIntent;

/** Owns the browser activity result, including when Android recreates the process. */
public class AuthorizationActivity extends AppCompatActivity {
    static final String HTTPS_REDIRECT = "https://account.openkitsune.cn/oauth/mobile/callback";
    static final String SCHEME_REDIRECT = "com.openkitsune.mobile:/oauth/callback";
    private String state;
    private String redirect;
    private boolean finished;
    private final ActivityResultLauncher<Intent> launcher =
        AuthTabIntent.registerActivityResultLauncher(this, result -> {
            if (result.resultCode == AuthTabIntent.RESULT_OK && result.resultUri != null) {
                accept(result.resultUri);
            } else {
                finishWith(null, result.resultCode == AuthTabIntent.RESULT_CANCELED
                    ? "account_login_cancelled" : "account_native_verification_failed");
            }
        });

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        // Never accept initialization parameters from a public deep link.
        if (saved != null) {
            state = saved.getString("state");
            redirect = saved.getString("redirect");
            return;
        }
        if (Intent.ACTION_VIEW.equals(getIntent().getAction())) {
            finish(); return;
        }
        state = getIntent().getStringExtra("state");
        redirect = getIntent().getStringExtra("redirectUri");
        String url = getIntent().getStringExtra("url");
        if (state == null || state.isEmpty() || url == null
            || !(HTTPS_REDIRECT.equals(redirect) || SCHEME_REDIRECT.equals(redirect))) {
            finishWith(null, "account_native_invalid_request"); return;
        }
        Uri authorization = Uri.parse(url);
        if (!"https".equals(authorization.getScheme())
            || !state.equals(authorization.getQueryParameter("state"))
            || !redirect.equals(authorization.getQueryParameter("redirect_uri"))) {
            finishWith(null, "account_native_invalid_request"); return;
        }
        try {
            AuthTabIntent tab = new AuthTabIntent.Builder().build();
            if (HTTPS_REDIRECT.equals(redirect)) {
                tab.launch(launcher, authorization, "account.openkitsune.cn", "/oauth/mobile/callback");
            } else {
                tab.launch(launcher, authorization, "com.openkitsune.mobile");
            }
        } catch (RuntimeException error) {
            finishWith(null, "account_native_unavailable");
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle saved) {
        saved.putString("state", state);
        saved.putString("redirect", redirect);
        super.onSaveInstanceState(saved);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (Intent.ACTION_VIEW.equals(intent.getAction()) && intent.getData() != null) {
            accept(intent.getData());
        } else if ("com.openkitsune.nativeauth.CANCEL".equals(intent.getAction())) {
            finishWith(null, "account_login_cancelled");
        }
    }

    private void accept(Uri uri) {
        if (state == null || redirect == null) return;
        String base = uri.buildUpon().clearQuery().fragment(null).build().toString();
        if (!redirect.equals(base) || uri.getFragment() != null
            || uri.getQueryParameters("state").size() != 1
            || !state.equals(uri.getQueryParameter("state"))) return;
        finishWith(uri.toString(), null);
    }

    private void finishWith(String url, String error) {
        if (finished) return;
        finished = true;
        Intent result = new Intent();
        result.putExtra("state", state);
        if (url != null) result.putExtra("url", url);
        if (error != null) result.putExtra("error", error);
        setResult(RESULT_OK, result);
        finish();
    }
}
