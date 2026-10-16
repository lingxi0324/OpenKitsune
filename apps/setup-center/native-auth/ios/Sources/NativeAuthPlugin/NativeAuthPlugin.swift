import AuthenticationServices
import Capacitor

@objc(NativeAuthPlugin)
public class NativeAuthPlugin: CAPPlugin, CAPBridgedPlugin, ASWebAuthenticationPresentationContextProviding {
    public let identifier = "NativeAuthPlugin"
    public let jsName = "NativeAuth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getRedirectUri", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "authorize", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "cancel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getPendingResult", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "clearPendingResult", returnType: CAPPluginReturnPromise)
    ]
    private let redirect = "com.openkitsune.mobile:/oauth/callback"
    private var session: ASWebAuthenticationSession?
    private var pendingResult: [String: Any] = [:]
    private var pendingCall: CAPPluginCall?
    private var pendingState: String?

    @objc func getRedirectUri(_ call: CAPPluginCall) { call.resolve(["uri": redirect]) }

    @objc func authorize(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard self.session == nil else { call.reject("account_login_in_progress"); return }
            guard let raw = call.getString("url"), let url = URL(string: raw), url.scheme == "https",
                  let state = call.getString("state"), !state.isEmpty,
                  call.getString("redirectUri") == self.redirect,
                  let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
                  parts.queryItems?.first(where: { $0.name == "state" })?.value == state,
                  parts.queryItems?.first(where: { $0.name == "redirect_uri" })?.value == self.redirect
            else { call.reject("account_native_invalid_request"); return }
            self.pendingResult = [:]
            self.pendingCall = call
            self.pendingState = state
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: "com.openkitsune.mobile") { callback, error in
                DispatchQueue.main.async {
                    var result: [String: Any] = ["state": state]
                    if let callback = callback {
                        result["url"] = callback.absoluteString
                    } else {
                        result["error"] = (error as? ASWebAuthenticationSessionError)?.code == .canceledLogin
                            ? "account_login_cancelled" : "account_native_unavailable"
                    }
                    self.finish(result)
                }
            }
            session.presentationContextProvider = self
            self.session = session
            if !session.start() { self.finish(["state": state, "error": "account_native_unavailable"]) }
        }
    }

    private func finish(_ result: [String: Any]) {
        guard let call = pendingCall, pendingState == result["state"] as? String else { return }
        pendingCall = nil
        pendingState = nil
        session = nil
        pendingResult = result
        call.resolve(result)
        notifyListeners("authorizationResult", data: result, retainUntilConsumed: true)
    }

    @objc func cancel(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            self.session?.cancel()
            self.finish(["state": self.pendingState ?? "", "error": "account_login_cancelled"])
            call.resolve()
        }
    }
    @objc func getPendingResult(_ call: CAPPluginCall) {
        DispatchQueue.main.async { call.resolve(self.pendingResult) }
    }
    @objc func clearPendingResult(_ call: CAPPluginCall) {
        DispatchQueue.main.async { self.pendingResult = [:]; call.resolve() }
    }

    public func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        return bridge?.viewController?.view.window ?? ASPresentationAnchor()
    }
}
