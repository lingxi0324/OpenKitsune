package com.openkitsune.nativeauth;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/** Public link receiver cannot initialize an authorization session. */
public class RedirectActivity extends Activity {
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        Intent callback = new Intent(this, AuthorizationActivity.class);
        callback.setAction(Intent.ACTION_VIEW);
        callback.setData(getIntent().getData());
        callback.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        startActivity(callback);
        finish();
    }
}
