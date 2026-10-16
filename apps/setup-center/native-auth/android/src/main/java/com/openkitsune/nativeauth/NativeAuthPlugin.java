package com.openkitsune.nativeauth;

import android.content.Intent;
import android.content.pm.ApplicationInfo;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "NativeAuth")
public class NativeAuthPlugin extends Plugin {
    private volatile JSObject pendingResult = new JSObject();
    private volatile boolean active;

    @PluginMethod
    public void getRedirectUri(PluginCall call) {
        boolean debug = (getContext().getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
        JSObject result = new JSObject();
        result.put("uri", debug ? AuthorizationActivity.SCHEME_REDIRECT : AuthorizationActivity.HTTPS_REDIRECT);
        call.resolve(result);
    }

    @PluginMethod
    public void authorize(PluginCall call) {
        if (active) { call.reject("account_login_in_progress"); return; }
        active = true;
        pendingResult = new JSObject();
        Intent intent = new Intent(getContext(), AuthorizationActivity.class);
        intent.putExtra("url", call.getString("url"));
        intent.putExtra("redirectUri", call.getString("redirectUri"));
        intent.putExtra("state", call.getString("state"));
        startActivityForResult(call, intent, "authorizationFinished");
    }

    @ActivityCallback
    private void authorizationFinished(PluginCall call, ActivityResult result) {
        active = false;
        Intent data = result.getData();
        JSObject dataResult = new JSObject();
        if (data != null) {
            dataResult.put("state", data.getStringExtra("state"));
            if (data.hasExtra("url")) dataResult.put("url", data.getStringExtra("url"));
            if (data.hasExtra("error")) dataResult.put("error", data.getStringExtra("error"));
        } else {
            dataResult.put("error", "account_login_cancelled");
        }
        pendingResult = dataResult;
        if (call != null) call.resolve(dataResult);
        notifyListeners("authorizationResult", dataResult, true);
    }

    @PluginMethod
    public void cancel(PluginCall call) {
        if (active) {
            Intent intent = new Intent(getContext(), AuthorizationActivity.class);
            intent.setAction("com.openkitsune.nativeauth.CANCEL");
            intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            getActivity().startActivity(intent);
        }
        call.resolve();
    }

    @PluginMethod
    public void getPendingResult(PluginCall call) { call.resolve(pendingResult); }

    @PluginMethod
    public void clearPendingResult(PluginCall call) {
        pendingResult = new JSObject();
        call.resolve();
    }
}
