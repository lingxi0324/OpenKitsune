# Installing Marketplace resources from the mobile app

The Android app opens the existing Marketplace in a system browser tab. After
acquisition or purchase, Marketplace returns an installation instruction to the
app. The app shows the selected server, resource, version, permissions and
dependencies. Only explicit confirmation starts installation on that server.

## Target and identity

Opening Marketplace records the active server ID, URL, display name and a random
state locally. Only the state, backend version and return mode reach Marketplace;
server addresses and connection credentials are not sent to the website.
Marketplace stores this context per browser tab, with an eight-hour lifetime.
The app reads the selected backend's health/version when opening Marketplace,
independently of the startup version check. Failed connections can be retried,
and switching servers during this request cancels opening the stale context.

An installation return must match an unexpired local context and the trusted
Marketplace origin. Switching servers does not retarget an installation. The app
offers connection management so the user can reconnect to the original server.
Each request binds the original server credential and rejects redirects. A late
response after a server switch cannot update the current installation UI.
Installation routes accept either the local desktop credential or a validated
explicit instance Bearer token. The desktop browser handoff route still requires
the local desktop credential and cannot be used with the mobile instance token.

Desktop and mobile use the same installation progress and plugin permission
components. Download percentages reflect measured bytes; dependency operations
show the active stage, package and elapsed time with indeterminate progress.

The backend requests `/oauth/desktop-install-proof` from Account, using its stored
refresh token. Despite its historical name, this existing protocol also supports
the instance account logged in from mobile. The short-lived proof is bound to the
instruction, Marketplace client and backend device ID. Marketplace checks that
its subject owns the resource. Confirmation obtains a fresh proof and rechecks
authorization, so changing accounts after preview does not authorize installation.
Account access and refresh tokens never enter the installation link or app UI.

## Android return links

- Signed release: `https://marketplace.openkitsune.cn/openkitsune/install#...`.
  Marketplace publishes `/.well-known/assetlinks.json` for the official APK
  signing certificate. Keep the certificate synchronized during key rotation.
- Debug/browser fallback: `com.openkitsune.marketplace://marketplace/install#...`.
  The installation receiver is separate from the OAuth callback receiver.
- The fragment contains the short-lived installation ticket, state and trusted
  Marketplace origin. It is not sent in HTTP requests. The fallback page clears
  the fragment from the address bar and offers an explicit return button.
- Both `appUrlOpen` and `getLaunchUrl` are handled, covering running and cold apps.

If the browser stays on the return page, tap **Open OpenKitsune** and permit the
browser to open the app. No clipboard or manually pasted callback is required.
The app needs an existing valid Marketplace context; an unrelated external link
cannot silently choose a server.

## Remote Web installation

The desktop's Web Access action issues a one-use, 60-second browser handoff
authorized by the native desktop credential. The browser consumes the fragment
ticket before mounting the application and receives a normal instance access
token and refresh cookie. Loopback Web requests retain and send explicit tokens
even though basic page access is exempt from password authentication. The native
credential and account refresh token never enter the browser. Account display
state alone, a cookie alone or a loopback IP still cannot authorize installation.
Missing instance authorization has its own error instead of suggesting that the
OpenKitsune account is signed out.

The Web interface opens Marketplace with `client=web`. Mobile browsers navigate
in the same tab. Desktop browsers open a new tab, keeping the original OpenKitsune
page available. Desktop market tabs retain their opener and advertise
`channel=post-message`. Resource details, the library and version history send
instructions directly to that window, leaving the Marketplace page and scroll
position intact. The recipient checks the exact market window, origin, session
state, expiry and current backend before persisting and acknowledging delivery.
Only then does Marketplace report receipt and try to focus the source tab.
If popups or local storage are unavailable, opening Marketplace retains the
existing same-tab flow.

If the opener has closed, refreshed or been isolated by browser policy, or no
acknowledgment arrives, Marketplace offers an explicit “Open OpenKitsune to continue
installing” action. It opens the same instruction in a new tab and preserves the
details page. The fallback can initialize only from an unexpired session issued
locally by OpenKitsune, stored under its random state in localStorage. These
records contain no account credentials or installation tokens and are pruned
when opening Marketplace. The instruction remains in the fragment.

Fallback handoff uses a same-origin BroadcastChannel and a registry of sessions
in the originating tab's sessionStorage. Each page runtime has a fresh random
instance ID: the live originating instance takes precedence over a duplicated
tab, while a refreshed source can offer its persisted session. The return page
selects exactly one responder. IndexedDB serializes receipt claims, including
fallback claims, so a delayed direct delivery cannot race a local installation.
Direct instructions use the unique ticket as their receipt key, allowing
multiple resources to be installed from the same market session. A
missing acknowledgment after a claim prompts retry instead of silently installing
in another tab. Accepted requests are persisted and queued in the source tab;
closing the current dialog advances to the next confirmation. Preparation and
installation still require the normal authentication and explicit confirmation.

If no eligible source responds (closed, suspended or connected elsewhere), the
returning page continues the existing local confirmation flow. Unsupported
BroadcastChannel/IndexedDB environments use that same local flow. After receipt
is acknowledged, the source tries to focus and the return page tries to close;
browser restrictions leave a clear instruction to switch to the original tab.
Only the temporary fallback page may close after successful handoff; Marketplace
never navigates away or closes during direct delivery.
Its per-tab context lasts 30 minutes and contains a random state, the original
Web page and the target API base. Web targets always use the page's origin,
independently of native desktop connection state. Marketplace receives only the clean Web return
address (origin and path), state and version. The original query/hash and instance
credentials stay in OpenKitsune's origin. State generation uses `getRandomValues`,
which is available on LAN HTTP pages as well as HTTPS pages.

For same-tab flows and explicit fallbacks, Marketplace returns to that
Web address with a one-use instruction in the URL fragment. OpenKitsune captures
and clears the fragment before routing or login. It validates the state, expiry,
page, Marketplace origin and current API target, then uses the existing
authenticated prepare/confirm APIs. Preparation never confirms installation.
After preparation, reload recovery uses the job ID; failed preparation keeps the
ticket for retry. Progress, background tasks and plugin authorization share the
desktop/App components. The Marketplace page never fetches a private backend or
receives its login credentials.

This Web path requires the existing remote instance login and matching instance
and Marketplace account identities. It does not grant browser cookies or local-IP
exemptions access to native desktop credentials. Expired, unrelated or replayed
returns require reopening Marketplace from OpenKitsune. Entering Marketplace from
a desktop client clears a previous Web/App context in that browser tab.

Web returns use the dedicated `/web/marketplace-return` shell. The backend serves
this shell, the normal Web entry and the service worker with `Cache-Control:
no-store`, so a return navigation cannot reuse an older cached entry document.
The original page path, query and fragment are restored locally after capture.
Hashed static assets retain their normal caching behavior. Reverse proxies must
forward this callback path to OpenKitsune and honor the entry's cache policy.

Ship the updated OpenKitsune backend together with the rebuilt Web assets and
restart the backend to enable this entry. Deploy the updated Marketplace Web
alongside OpenKitsune Web to enable direct messaging. No Account or APK update is
required. Existing mobile and desktop native protocol flows are unchanged.
Verify an HTTP LAN address and HTTPS reverse proxy, refresh before
confirmation, background completion/permission recovery and an expired link.

## App task recovery

The floating installation entry and its list use the same working set and total
count. Running installations sort first; mixed states use a neutral installation
label. The entry can minimize without hiding access to tasks. There is no
installation shortcut in the account/application menu.

Failure notices remain only in the current page session. Upgrading the task store
drops historical failures, and reloads retain live work and pending plugin setup.
Failed rows can be removed; closing a failed detail dialog also removes its
notice and clears the matching recovery pointer. Removal does not delete plugin
files or server logs, and discovery never re-imports completed failed jobs.

The app persists the target and returned job ID. A response lost during preparation
can be retried with the same instruction. After preparation, subsequent operations
use the saved job ID instead of consuming the ticket again. Closing the progress view lets the
backend continue; tapping Marketplace reopens the pending task. Reopening the app
queries the job without confirming installation again. Backend restart failures
remain explicit and require a new installation attempt.

## Shipping and verification

Ship the Marketplace web changes, updated OpenKitsune backend and new APK together.
This feature requires no Account deployment or database migration. It does not
export a remote instance owner's account into a Marketplace browser session;
the two account identities must agree to install acquired resources.

`app-debug.apk` uses the development signing key; `app-release-unsigned.apk`
must be signed with the official key before installing or distributing it.
Browser/unit tests cannot establish OS App Links verification on a real phone.
Check cold start, background return, cancelled authorization, multiple servers,
offline/reconnect and installation completion on a signed release device.

There is no generated iOS host project in this checkout. The shared Capacitor
installation UI and browser fallback can be reused there, but the iOS host must
register `com.openkitsune.marketplace` in `CFBundleURLTypes` and forward open-URL
events to Capacitor before it can be shipped. No iOS binary is produced here.
