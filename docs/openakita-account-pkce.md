# OpenKitsune Account login integration

OpenKitsune Desktop uses the public OIDC client `openkitsune-desktop`. It never has
a client secret. The backend opens a temporary loopback listener on
`127.0.0.1:1455`, generates a fresh state and S256 PKCE verifier, and returns
the Account authorization URL to Setup Center.

```text
GET  /api/account/capability
POST /api/account/login/start
POST /api/account/login/cancel/{attempt_id}
GET  /api/account/login/status/{attempt_id}
GET  /api/account/status
POST /api/account/entitlements/refresh
POST /api/account/logout
POST /api/account/marketplace/handoff
```

The desktop registered redirect URI is
`http://127.0.0.1:1455/auth/callback`. Refresh tokens are stored only in the OS
credential store through `keyring`; there is no plaintext file fallback.
Access tokens stay in process memory. A successful login fetches `/oauth/userinfo`
and `/api/v1/me/entitlements`, then persists only the identity and entitlement
read model in `~/.openkitsune/account/<provider-scope>/account_identity.db`.
The scope includes the provider URL, client ID and credential namespace,
so changing projects or workspaces does not change the desktop account.

Feature gates must evaluate the cached entitlement status and expiry at read
time. A central `suspended` event revokes Account sessions in that database and
all Account-backed operations fail immediately. The existing local web password
remains a separate break-glass path and is not revoked by Account suspension.

Setup Center's sidebar account menu drives these endpoints, polls the loopback
attempt, shows the cached account/entitlement status, and lets the user refresh
entitlements. Logout revokes the current product grant before clearing the
local OS credential, without opening another browser tab. A revocation outage
is reported as failure rather than successful logout.

## Remote Web sign-in (RFC 8628)

Web browsers (including mobile browsers) and desktop connections to a remote backend use the standard
[OAuth Device Authorization Grant](https://www.rfc-editor.org/rfc/rfc8628).
Local desktop connections retain Authorization Code + S256 PKCE. All Web builds
use device authorization, including localhost URLs that might be SSH tunnels.

1. OpenKitsune requests a short-lived grant from `POST /oauth/device_authorization`
   using the public `openkitsune-desktop` client. No client secret or redirect URI
   is sent.
2. The Web UI first displays the user code in a confirmation panel (a bottom
   sheet on mobile). Only clicking **Continue to account center** opens
   `verification_uri_complete` in a new tab; preparation never opens a blank tab.
   The panel keeps the same code and request when reopening or retrying a blocked
   popup. Expired requests must be restarted. The code is already filled in at
   the account center. The user signs
   in, checks that both codes match, and explicitly confirms the requesting app,
   account and scopes. Visiting the link alone never approves a request.
3. The OpenKitsune backend polls `POST /oauth/token` with grant type
   `urn:ietf:params:oauth:grant-type:device_code`. The original UI polls only its
   own backend and updates automatically when authorization succeeds.

After the user confirms, the account page attempts to close its own login tab.
Browsers that prohibit automatic closing keep a return button and instructions
for returning manually. When OpenKitsune regains visibility/focus or is restored
from browser history, it immediately checks the pending attempt. These checks
are serialized and still honor the backend's provider polling interval. The
account page reports authorization completion; OpenKitsune reports successful
sign-in only after it has received and stored the credentials.

The account center returns a ten-minute expiry and an initial five-second poll
interval. OpenKitsune honors `authorization_pending`, increases the interval by
five seconds on `slow_down`, and uses exponential backoff for network timeouts
and temporary server errors. Denial, expiry and consumed grants are terminal.
Cancelling closes the tab and stops backend polling; unused account-center
grants expire automatically. Backend restarts require starting a new attempt.

The device code stays in backend memory. Only the user code, verification URLs
and attempt status reach the OpenKitsune browser. Access tokens stay in memory;
refresh tokens use the existing OS credential store. Starting, polling and
cancelling login remain behind normal OpenKitsune Web access authentication.
There is no public callback route, callback proxy or per-deployment redirect
registration. The backend needs outbound access to the account center; the
account center does not need inbound access to the self-hosted deployment.

Deploy the updated **openkitsune-account first**, then OpenKitsune. Account schema
migration 7 adds the short-lived device authorization table without modifying
existing clients, sessions or credentials. The account center currently permits
device grants only for active public first-party platform clients (including the
seeded `openkitsune-desktop`), and preserves scope policy, refresh rotation, reuse
detection and browser-session revocation. Custom providers must implement the
same RFC 8628 endpoints. Older providers show an upgrade-required error instead
of falling back to the unreachable loopback callback.

If login cannot start, check account-service availability/version and popup
permissions. If authorization succeeds but local sign-in fails, check backend
connectivity and OS credential-store availability. The existing `keyring`
requirement also applies to server deployments; there is no plaintext fallback.

## Native mobile sign-in (Authorization Code + S256 PKCE)

Capacitor builds use `flow: native`, not the browser device-code dialog. The
instance creates the state/verifier and an expiring attempt; the App opens the
authorization URL through the local `@openkitsune/native-auth` plugin. Android
uses AndroidX Auth Tab with automatic Custom Tabs compatibility. iOS uses
`ASWebAuthenticationSession`. Account pages are never loaded in the App WebView.

The existing public `openkitsune-desktop` client remains the **instance's** client
identity, preserving existing refresh-token storage, rotation, and product
integrations. Its display name is now OpenKitsune and its registered redirect
allowlist includes these project-owned mobile callbacks:

- Android release: `https://account.openkitsune.cn/oauth/mobile/callback`.
- Android debug and iOS: `com.openkitsune.mobile:/oauth/callback`.

The account center publishes `/.well-known/assetlinks.json` with the production
APK signing certificate, verified against the official v1.27.38 APK. During
signing-key rotation, publish both old and new SHA-256 fingerprints. Never add
debug signing keys to the production association. iOS uses a system-session
callback scheme to support iOS 15+ without requiring Universal Links setup.

The App validates the exact callback URI, state and unambiguous code/error,
then POSTs those fields to the **original instance** at
`/api/account/login/native/callback/{attempt_id}` using its existing instance
authentication. This endpoint is protected; it is not a public OAuth redirect.
The backend verifies its own state and PKCE, redeems the code once, persists
the refresh token in its existing OS vault, and returns only status. Repeated
delivery of a successful native callback is idempotent. Server switching aborts
delivery and prevents account-status publication into a different server view.

Only attempt routing metadata is stored in App localStorage, never the verifier,
authorization code, or account-center tokens. Native activity/session callbacks
retain results until acknowledged; a transient delivery failure can retry the
same attempt. Android activity restoration handles a returned browser result
after process recreation. If the OS discards the entire session, or the backend
restarts/expires the attempt, start a new login. Closing system auth cancels the
pending backend attempt. A callback page fallback explains how to enable App
Links when the OS does not deliver a verified HTTPS link.

Build/sync with `npm run build:cap` and `npx cap sync android` (or `ios`). The
local plugin includes both Android and iOS implementations; the existing iOS
workflow creates the Xcode project and discovers the plugin during Capacitor
sync. Publish the updated account center before distributing the updated App.
Custom account providers must allow the same exact mobile redirects on their
configured public client; mobile authorization URLs must use HTTPS.

## Distribution configuration

Account integration is a distribution-level capability with three modes:

```text
@@OPENKITSUNE_ACCOUNT_MODE@@=openkitsune  # official hosted service (default)
@@OPENKITSUNE_ACCOUNT_MODE@@=custom     # OEM identity service
@@OPENKITSUNE_ACCOUNT_MODE@@=disabled   # no account routes, credentials, or account UI
```

The official mode uses the hosted service by default:

```text
OPENKITSUNE_ACCOUNT_BASE_URL=https://account.openkitsune.cn
OPENKITSUNE_ACCOUNT_CLIENT_ID=openkitsune-desktop
```

Override `OPENKITSUNE_ACCOUNT_BASE_URL` only when testing against a local Account
service. Custom mode requires an explicit `OPENKITSUNE_ACCOUNT_BASE_URL` and
`OPENKITSUNE_ACCOUNT_CLIENT_ID`; `OPENKITSUNE_ACCOUNT_DISPLAY_NAME` and
`OPENKITSUNE_ACCOUNT_PROVIDER` customize the provider identity shown to users.
Provider credentials use separate OS-vault slots, so an OEM token is never sent
to the official service or another custom provider.

When account mode is disabled, only `GET /api/account/capability` remains
mounted so the frontend can render an account-free application menu. OAuth,
status, entitlement, logout, and status-propagation routes are absent, and
startup clears locally stored account refresh tokens. Core local OpenKitsune
features continue to work without an account.

An account-enabled always-on server may additionally expose the signed status receiver at
`POST /api/internal/openkitsune/users/status`. Desktop-only processes must not be
configured as Account Outbox targets because they have no stable ingress.

## Independent product sessions

Desktop, the Account website and Marketplace have independent sessions.
Opening Marketplace may offer identity continuation; it does not silently
replace the browser account. Ordinary logout affects the current product.

## Marketplace session contract

- Desktop identity is scoped to the OS user and account provider/client, not a project or workspace. Its profile database lives under `~/.openkitsune/account/`; the refresh token remains in the OS credential vault.
- A cached identity is usable only when its stored credential hash matches the current vault credential. Legacy credentials are recovered through refresh and userinfo, never by copying an unverified workspace profile. An unavailable recovery is shown as unconfirmed and cannot issue Marketplace handoffs or installation proofs.
- Credential rotation, identity recovery and logout share an OS file lock across desktop backends. UI focus/periodic refresh and handoff responses synchronize the visible identity.
- Account owns identity and validates live desktop credentials. Marketplace owns its HttpOnly browser session and keeps all long-lived credentials server-side.
- POST /oauth/desktop-handoff accepts JSON {client_id, refresh_token, target_client_id, target_origin}; returns {ticket, expires_in}. Tickets live for 120 seconds, are stored hashed, restricted to a registered first-party target origin, and invalidated by source grant revocation.
- POST /oauth/desktop-handoff/inspect accepts JSON {client_id, client_secret, ticket}; returns {sub, name, email, iss}. Only the target confidential client can inspect.
- POST /oauth/desktop-handoff/redeem accepts JSON {client_id, client_secret, ticket, redirect_uri, code_challenge}; atomically consumes the ticket and creates a normal S256 authorization code, returning {code}. Marketplace exchanges it using its existing token endpoint. No Account browser cookie is replaced.
- GET /auth/desktop?ticket=...&next=... on Marketplace stores a browser-bound pending transaction and immediately redirects to a clean confirmation URL. Same-account arrivals keep the existing session. Different-account arrivals offer switch or keep. Anonymous arrivals explicitly confirm the named account, preventing untrusted links from silently logging a browser in.
- Marketplace browser writes require X-Marketplace-Context, a non-credential identifier supplied by /api/v1/me (including anonymous context). It is compared to the current cookie-derived context. Missing/mismatched context cannot authorize writes. Machine routes are excluded and retain their own authentication.
- Every tab captures its own context. A shared fetch wrapper never replaces stale context with the latest identity to make a write succeed. Broadcast/focus/pageshow signals trigger a blocking account-changed view; old requests cannot repopulate a new identity.
- Local desktop handoff is enabled only for the official account distribution on local desktop UI; remote/web consumers cannot receive a server owner's credentials. A signed-out desktop opens Marketplace without disturbing its existing session.
- Ordinary logout revokes the current refresh-token family. Refresh rotation is atomic and serialized on the desktop. Login attempts have a generation, and delayed callbacks cannot undo logout or replace a newer login.
- Marketplace checks upstream session validity, with bounded caching for reads and fresh checks for writes, so global security revocation reaches independent sessions.
- Account-required installs must validate the consuming client's identity server-side before releasing download URLs; same personal subject initially, with an explicit boundary for future organization authorization.

## Observable behavior

| Desktop | Marketplace browser | Opening Marketplace |
| --- | --- | --- |
| Signed out | Signed out | Browse anonymously; no forced login |
| Signed out | Account A | Keep A |
| Account A | Signed out | Confirm the named account A, then create a Marketplace session |
| Account A | Account A | Keep the current Marketplace session |
| Account B | Account A | Explicitly choose B or keep A |
| Account B after switching | Old A tabs remain open | A pages block on session change; stale writes and identity responses are rejected |

Ordinary logout in any product does not sign out the others. An unfinished
handoff/proof remains dependent on the source desktop grant; a completed
Marketplace login has its own grant. Explicit security revocation still reaches
affected sessions. A switch or logout after an installation preview requires a
fresh identity proof before confirmation. An already authorized running local
installation retains its fixed authorization and is not reassigned to a new user.

The Marketplace document can reload to accept the current session or explicitly
restart sign-in if its cookies are stale. Browser generation checks cover delayed
Set-Cookie responses as well as ordinary shared-cookie changes. An unavailable
identity provider never authorizes a write using cached permissions.

## Deployment and compatibility

Deploy Account with migration 6 first. Deploy Marketplace API, web and Nginx
routes together, then publish the desktop. The registered Marketplace callback
origin must equal the externally opened origin. Local development sets
`OPENKITSUNE_MARKETPLACE_URL` on the desktop backend and `VITE_MARKETPLACE_URL`
on its frontend; the Account client registration and Marketplace frontend and
callback settings must use that same visible origin.

Existing open Marketplace pages reload to obtain the context contract. Old
desktop versions cannot consume install instructions without account proofs;
there is deliberately no token-only compatibility bypass. Historical Account
refresh tokens have no recorded rotation lineage: migration 6 groups them by
user/client, preserving the previous revocation boundary, while each new login
gets an independent family. Existing OAuth product logins also gain independence
from ordinary Account website logout.

The implementation uses existing PostgreSQL, Redis and native credential storage;
there is no additional service or required user setting. Organizational access
can extend the installation authorization boundary later without sharing user
sessions or passing long-lived tokens to the browser.

The local native access boundary must also support an independently started
backend and a desktop reopening while its backend survives. It therefore uses
a same-OS-user native credential, created through Tauri IPC at
`~/.openkitsune/.desktop-account-token`, rather than requiring matching process
launch environments. Windows protects the file with user-scoped DPAPI; Unix
requires owner-only file permissions. The backend only reads this credential;
no HTTP endpoint publishes it. Direct loopback and no-proxy checks still apply.
The inherited launch token remains accepted for compatibility with managed
backends. This local credential authenticates the caller, not an Account user.

See the sibling repositories' `docs/product-sessions.md` (Account) and
`docs/OPENKITSUNE-CLIENT-CONTEXT.md` (Marketplace) for exact endpoint and deployment
contracts. Do not record ticket-bearing URLs in outer proxy/CDN access logs.

## Marketplace installation behavior

Installation authorization is rechecked after preview. Local installed
identity comes from the actual manifest, not job history. The same version
is not downloaded again; upgrades require confirmation, older versions do
not overwrite newer installs, and unknown same-name resources require
explicit replacement confirmation. Local state is rechecked before writes.

First-time Skill installs are enabled; upgrades preserve the user's
enable/disable choice and category edits. Install and uninstall share the
workspace path, and successful installation refreshes the Skill list.

See [the testing guide](testing.md#账号与市场回归测试) for focused regression suites.

## Identity freshness

`GET /api/account/status` rechecks Account userinfo after 20 seconds; `?refresh=true`
bypasses the cache. The sidebar forces a refresh when returning to the app and
while visible on its existing 30-second timer. Profile writes are bound to the
current refresh grant and serialized with native credential rotation. Increasing
`identity_version` values prevent older responses from reverting email state.
Account outages return `status=unavailable` while retaining the last profile and
credential for retry. Local status events and entitlements remain separate.

Deploy Account's versioned userinfo first, then distribute the updated client.
