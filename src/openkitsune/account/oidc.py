"""PKCE and RFC 8628 device authorization with OpenKitsune Account."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from filelock import FileLock, Timeout

from openkitsune.account.config import (
    DEFAULT_ACCOUNT_BASE_URL,
    DEFAULT_ACCOUNT_CLIENT_ID,
    disabled_credential_usernames,
)
from openkitsune.account.status_store import AccountStatusStore

logger = logging.getLogger(__name__)

CLIENT_ID = DEFAULT_ACCOUNT_CLIENT_ID
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 1455
CALLBACK_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}/auth/callback"
NATIVE_CALLBACK_URIS = frozenset(
    {
        "https://account.openkitsune.cn/oauth/mobile/callback",
        "com.openkitsune.mobile:/oauth/callback",
    }
)
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
LOGIN_TTL = 180


class AccountOIDCError(Exception):
    pass


class TokenStore(Protocol):
    async def load_refresh_token(self) -> str | None: ...

    async def save_refresh_token(self, token: str) -> None: ...

    async def clear(self) -> None: ...


class KeyringTokenStore:
    """OS-keyring-backed credential store with a local file fallback.

    整改（2026-10-07）：keyring 在部分 Windows/CI/无桌面环境不可用（模块缺失
    或无可用后端），此前 ``import keyring`` 失败会直接抛 ``AccountOIDCError``，
    导致 ``/api/account/status`` 每次轮询 500。现在 keyring 可用则用，
    不可用/操作异常时自动回退到 ``~/.openkitsune/account/<hash>.refresh_token``
    文件存储，保证账号状态接口永不因凭证存储 500。
    """

    service = "OpenKitsune Account"
    username = "openkitsune-desktop-refresh-token"

    def __init__(
        self,
        *,
        username: str | None = None,
        fallback_dir: str | os.PathLike | None = None,
    ) -> None:
        self.username = username or type(self).username
        base = Path(fallback_dir or (Path.home() / ".openkitsune" / "account"))
        digest = hashlib.sha256(self.username.encode()).hexdigest()[:24]
        self._fallback_path = base / f"{digest}.refresh_token"
        self._keyring_unavailable_reason: str | None = None
        # 探测结果缓存字段必须在 __init__ 中初始化：此前只在 _keyring() 内赋值，
        # 首次调用读取 _keyring_probe_done 会抛 AttributeError，导致
        # /api/account/status 每次轮询 500（WSL headless 实测）。
        self._keyring_probe_done: bool = False
        self._keyring_module = None

    def _keyring(self):
        """Return the keyring module when usable, else None (idempotent probe).

        [fix 2026-10-18] 探测结果按进程缓存一次；后续调用不再重复 import /
        get_keyring()。探测成功但实际操作抛 NoKeyringError（WSL headless 下
        默认 fail 后端）时，由调用方把本缓存清空并置“不可用”，从此静默走文件。
        """
        if self._keyring_probe_done:
            return self._keyring_module
        self._keyring_probe_done = True
        self._keyring_module = None
        try:
            import keyring

            # 触发一次后端探测：无可用后端时 keyring 会抛 RuntimeError。
            keyring.get_keyring()
            self._keyring_module = keyring
            return keyring
        except Exception as exc:
            if self._keyring_unavailable_reason is None:
                self._keyring_unavailable_reason = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "OS keyring unavailable (%s); falling back to file credential "
                    "store at %s",
                    self._keyring_unavailable_reason,
                    self._fallback_path,
                )
            return None

    def _disable_keyring(self, exc: Exception) -> None:
        """探测成功但实际操作失败（如 headless NoKeyringError）时永久降级到文件。"""
        self._keyring_module = None
        self._keyring_probe_done = True
        if self._keyring_unavailable_reason is None:
            self._keyring_unavailable_reason = f"{type(exc).__name__}: {exc}"

    async def load_refresh_token(self) -> str | None:
        def _load() -> str | None:
            kr = self._keyring()
            if kr is not None:
                try:
                    token = kr.get_password(self.service, self.username)
                    if token:
                        return token
                except Exception as exc:
                    self._disable_keyring(exc)
                    logger.warning(
                        "keyring read failed (%s); using file fallback",
                        type(exc).__name__,
                    )
            return self._read_file()

        return await asyncio.to_thread(_load)

    async def save_refresh_token(self, token: str) -> None:
        def _save() -> None:
            kr = self._keyring()
            if kr is not None:
                try:
                    kr.set_password(self.service, self.username, token)
                    return
                except Exception as exc:
                    self._disable_keyring(exc)
                    logger.warning(
                        "keyring write failed (%s); using file fallback",
                        type(exc).__name__,
                    )
            self._write_file(token)

        await asyncio.to_thread(_save)

    async def clear(self) -> None:
        def _clear() -> None:
            kr = self._keyring()
            if kr is not None:
                try:
                    kr.delete_password(self.service, self.username)
                except Exception as exc:
                    self._disable_keyring(exc)

            try:
                self._fallback_path.unlink(missing_ok=True)
            except Exception:
                pass

        await asyncio.to_thread(_clear)

    def _read_file(self) -> str | None:
        try:
            if self._fallback_path.exists():
                token = self._fallback_path.read_text(encoding="utf-8").strip()
                return token or None
        except Exception as exc:
            logger.warning("credential file read failed: %s", exc)
        return None

    def _write_file(self, token: str) -> None:
        try:
            self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
            self._fallback_path.write_text(token, encoding="utf-8")
        except Exception as exc:
            # 真正无法持久化凭证时才报错（与登录流程语义一致）。
            raise AccountOIDCError(f"credential persistence failed: {exc}") from exc


async def clear_disabled_account_credentials() -> None:
    """Remove every locally known account credential slot without reading it."""

    await asyncio.gather(
        *(
            KeyringTokenStore(username=username).clear()
            for username in disabled_credential_usernames()
        )
    )


@dataclass
class LoginAttempt:
    attempt_id: str
    state: str
    verifier: str
    authorization_url: str
    redirect_uri: str = CALLBACK_URI
    flow: str = "loopback"
    user_code: str = ""
    verification_uri: str = ""
    device_code: str = field(default="", repr=False)
    expires_in: int = LOGIN_TTL
    poll_interval: float = 5
    next_poll_at: float = 0
    status: str = "pending"
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    generation: int = 0


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _preferred_callback_language(accept_language: str) -> str:
    """Choose a supported callback language from an HTTP Accept-Language value."""
    preferences: list[tuple[float, int, str]] = []
    for index, item in enumerate(accept_language.split(",")):
        parts = [part.strip() for part in item.split(";")]
        tag = parts[0].lower()
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.lower().startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0
        if quality > 0:
            preferences.append((quality, -index, tag))
    for _quality, _index, tag in sorted(preferences, reverse=True):
        if tag == "zh" or tag.startswith("zh-"):
            return "zh"
        if tag == "en" or tag.startswith("en-"):
            return "en"
    return "en"


def _callback_page_html(*, success: bool, language: str) -> bytes:
    copy = {
        "zh": {
            "page_title": "登录成功" if success else "登录失败",
            "eyebrow": "OpenKitsune",
            "title": "登录成功" if success else "登录失败",
            "message": (
                "你已成功登录 OpenKitsune。"
                if success
                else "登录过程中遇到问题，请返回 OpenKitsune 重新登录。"
            ),
            "hint": "现在可以关闭此页面。",
        },
        "en": {
            "page_title": "Signed in successfully" if success else "Sign-in failed",
            "eyebrow": "OpenKitsune",
            "title": "Signed in successfully" if success else "Sign-in failed",
            "message": (
                "You’re now signed in to OpenKitsune."
                if success
                else "Something went wrong. Return to OpenKitsune and try signing in again."
            ),
            "hint": "You can close this tab now.",
        },
    }
    lang = "zh" if language == "zh" else "en"
    text = copy[lang]
    document_language = "zh-CN" if lang == "zh" else "en"
    state_class = "success" if success else "error"
    state_icon = "&#10003;" if success else "!"
    status_role = "status" if success else "alert"
    html = f"""<!doctype html>
<html lang="{document_language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>{text["page_title"]} · OpenKitsune</title>
  <style>
    :root {{ color-scheme: light dark; font-family: Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{
      min-height: 100vh; margin: 0; display: grid; place-items: center; padding: 24px;
      color: #182033; background:
        radial-gradient(circle at 50% 0%, rgba(59, 130, 246, .13), transparent 38%),
        linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
    }}
    .card {{
      width: min(100%, 440px); padding: 42px 38px 30px; text-align: center;
      border: 1px solid rgba(148, 163, 184, .28); border-radius: 22px;
      background: rgba(255, 255, 255, .92); box-shadow: 0 24px 70px rgba(15, 23, 42, .12);
    }}
    .mark {{
      width: 64px; height: 64px; margin: 0 auto 24px; display: grid; place-items: center;
      border-radius: 20px; font-size: 32px; font-weight: 700;
    }}
    .success .mark {{ color: #047857; background: #d1fae5; box-shadow: 0 0 0 8px rgba(16, 185, 129, .08); }}
    .error .mark {{ color: #b91c1c; background: #fee2e2; box-shadow: 0 0 0 8px rgba(239, 68, 68, .07); }}
    .eyebrow {{ margin: 0 0 8px; color: #2563eb; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }}
    h1 {{ margin: 0; font-size: 28px; line-height: 1.25; letter-spacing: -.02em; }}
    .message {{ margin: 14px auto 0; max-width: 340px; color: #64748b; font-size: 15px; line-height: 1.65; }}
    .hint {{ margin: 26px 0 0; padding: 12px 14px; border-radius: 12px; color: #475569; background: #f1f5f9; font-size: 13px; }}
    @media (prefers-color-scheme: dark) {{
      body {{ color: #e5e7eb; background: radial-gradient(circle at 50% 0%, rgba(59, 130, 246, .18), transparent 38%), #0f172a; }}
      .card {{ border-color: rgba(148, 163, 184, .2); background: rgba(17, 24, 39, .94); box-shadow: 0 24px 70px rgba(0, 0, 0, .35); }}
      .message {{ color: #94a3b8; }}
      .hint {{ color: #cbd5e1; background: rgba(51, 65, 85, .65); }}
      .success .mark {{ color: #6ee7b7; background: rgba(6, 78, 59, .72); }}
      .error .mark {{ color: #fca5a5; background: rgba(127, 29, 29, .62); }}
    }}
  </style>
</head>
<body>
  <main class="card {state_class}" role="{status_role}" aria-labelledby="callback-title">
    <div class="mark" aria-hidden="true">{state_icon}</div>
    <p class="eyebrow">{text["eyebrow"]}</p>
    <h1 id="callback-title">{text["title"]}</h1>
    <p class="message">{text["message"]}</p>
    <p class="hint">{text["hint"]}</p>
  </main>
</body>
</html>"""
    return html.encode("utf-8")


class AccountOIDCManager:
    def __init__(
        self,
        *,
        store: AccountStatusStore,
        token_store: TokenStore | None = None,
        account_base_url: str | None = None,
        client_id: str | None = None,
    ) -> None:
        self._store = store
        self._tokens = token_store or KeyringTokenStore()
        self._base_url = (
            account_base_url
            or os.environ.get("OPENKITSUNE_ACCOUNT_BASE_URL", DEFAULT_ACCOUNT_BASE_URL)
        ).rstrip("/")
        self._client_id = (
            client_id or os.environ.get("OPENKITSUNE_ACCOUNT_CLIENT_ID", DEFAULT_ACCOUNT_CLIENT_ID)
        ).strip()
        if not self._client_id:
            raise ValueError("account client ID must not be empty")
        self._attempts: dict[str, LoginAttempt] = {}
        self._server: asyncio.Server | None = None
        self._listener_attempt: LoginAttempt | None = None
        self._login_lock = asyncio.Lock()
        self._access_token: str | None = None
        self._session_id: str | None = None
        self._account_user_id: str | None = None
        self._credential_lock = asyncio.Lock()
        self._generation = 0
        self._access_expires_at = 0.0
        self._identity_checked_at = 0.0
        self._identity_checked_subject: str | None = None
        self._access_credential_hash: str | None = None
        self._vault_lock = None
        if isinstance(self._tokens, KeyringTokenStore):
            namespace = hashlib.sha256(self._tokens.username.encode()).hexdigest()[:24]
            self._vault_lock = FileLock(
                str(Path.home() / ".openkitsune" / "account" / f"{namespace}.lock"),
                thread_local=False,
            )

    @asynccontextmanager
    async def _credentials(self):
        # Separate desktop backends share the same OS credential. Serialize
        # refresh rotation, logout and identity publication across processes.
        async with self._credential_lock:
            if self._vault_lock is None:
                yield
                return
            await asyncio.to_thread(
                Path(self._vault_lock.lock_file).parent.mkdir, parents=True, exist_ok=True
            )
            while True:
                acquisition = asyncio.create_task(
                    asyncio.to_thread(
                        self._vault_lock.acquire,
                        timeout=0,
                    )
                )
                try:
                    await asyncio.shield(acquisition)
                    break
                except Timeout:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    try:
                        await acquisition
                    except Timeout:
                        pass
                    else:
                        await asyncio.to_thread(self._vault_lock.release)
                    raise
            try:
                yield
            finally:
                await asyncio.to_thread(self._vault_lock.release)

    async def start(
        self, *, flow: str = "loopback", redirect_uri: str | None = None
    ) -> LoginAttempt:
        if flow not in {"loopback", "device", "native"}:
            raise AccountOIDCError("unsupported login flow")
        if flow == "native" and redirect_uri not in NATIVE_CALLBACK_URIS:
            raise AccountOIDCError("invalid native redirect URI")
        self._generation += 1
        generation = self._generation
        async with self._credentials():
            return await self._start_locked(generation, flow=flow, redirect_uri=redirect_uri)

    async def _start_locked(
        self, generation: int, *, flow: str, redirect_uri: str | None
    ) -> LoginAttempt:
        if generation != self._generation:
            raise AccountOIDCError("login attempt was superseded")
        for old in self._attempts.values():
            if old.status in {"pending", "exchanging"}:
                old.status = "expired"
                old.device_code = ""
        if self._listener_attempt is not None:
            await self._close_listener(self._listener_attempt)
        self._attempts = {
            key: value
            for key, value in self._attempts.items()
            if time.time() - value.created_at < value.expires_in + 60
        }
        if len(self._attempts) >= 32:
            raise AccountOIDCError("too many login attempts")
        if flow == "device":
            return await self._start_device(generation)
        if flow == "loopback" and self._listener_attempt is not None:
            await self.cancel(self._listener_attempt.attempt_id)
        redirect_uri = redirect_uri if flow == "native" else CALLBACK_URI
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        attempt_id = secrets.token_urlsafe(18)
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "prompt": "select_account",
                "scope": "openid profile email offline_access entitlements organizations",
                "state": state,
                "code_challenge": pkce_challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
        attempt = LoginAttempt(
            attempt_id=attempt_id,
            generation=generation,
            state=state,
            verifier=verifier,
            authorization_url=f"{self._base_url}/oauth/authorize?{query}",
            redirect_uri=redirect_uri,
            flow=flow,
            expires_in=600 if flow == "native" else LOGIN_TTL,
        )
        self._attempts[attempt_id] = attempt
        if flow == "native":
            asyncio.get_running_loop().call_later(attempt.expires_in, self._expire_attempt, attempt)
            return attempt
        try:
            self._server = await asyncio.start_server(
                lambda reader, writer: self._callback(reader, writer, attempt),
                CALLBACK_HOST,
                CALLBACK_PORT,
            )
        except OSError:
            self._attempts.pop(attempt_id, None)
            raise
        self._listener_attempt = attempt
        asyncio.get_running_loop().call_later(LOGIN_TTL, self._expire_attempt, attempt)
        return attempt

    async def _start_device(self, generation: int) -> LoginAttempt:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._base_url}/oauth/device_authorization",
                    data={
                        "client_id": self._client_id,
                        "scope": "openid profile email offline_access entitlements organizations",
                    },
                )
            if response.status_code in {404, 405, 501}:
                raise AccountOIDCError("account_device_not_supported")
            if response.status_code != 200:
                raise AccountOIDCError("account_device_start_failed")
            payload = response.json()
            device_code = payload["device_code"]
            user_code = payload["user_code"]
            verification_uri = payload["verification_uri"]
            authorization_url = payload.get("verification_uri_complete") or verification_uri
            expires_in = payload["expires_in"]
            interval = payload.get("interval", 5)
            if (
                not all(
                    isinstance(value, str) and 0 < len(value) <= 8192
                    for value in (device_code, user_code, verification_uri, authorization_url)
                )
                or type(expires_in) is not int
                or not 0 < expires_in <= 3600
                or type(interval) is not int
                or not 0 < interval <= expires_in
            ):
                raise ValueError("invalid device authorization response")
            for uri in (verification_uri, authorization_url):
                parsed = urlsplit(uri)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError("invalid verification URI")
        except AccountOIDCError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise AccountOIDCError("account_device_start_failed") from exc
        attempt = LoginAttempt(
            attempt_id=secrets.token_urlsafe(18),
            generation=generation,
            state="",
            verifier="",
            authorization_url=authorization_url,
            flow="device",
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            expires_in=expires_in,
            poll_interval=interval,
            next_poll_at=time.monotonic() + interval,
        )
        self._attempts[attempt.attempt_id] = attempt
        asyncio.get_running_loop().call_later(expires_in, self._expire_attempt, attempt)
        return attempt

    async def attempt_status(self, attempt_id: str) -> dict:
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            raise AccountOIDCError("unknown login attempt")
        if attempt.flow == "device" and attempt.status == "pending":
            await self._poll_device(attempt)
        return {"status": attempt.status, "error": attempt.error}

    async def _poll_device(self, attempt: LoginAttempt) -> None:
        async with self._login_lock:
            if attempt.generation != self._generation:
                attempt.status = "expired"
            if attempt.status != "pending":
                return
            if time.time() - attempt.created_at >= attempt.expires_in:
                self._expire_attempt(attempt)
                return
            if time.monotonic() < attempt.next_poll_at:
                return
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    response = await client.post(
                        f"{self._base_url}/oauth/token",
                        data={
                            "grant_type": DEVICE_GRANT_TYPE,
                            "client_id": self._client_id,
                            "device_code": attempt.device_code,
                        },
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    attempt.poll_interval *= 2
                    return
                if attempt.generation != self._generation:
                    attempt.status = "expired"
                if attempt.status != "pending":
                    if response.status_code == 200:
                        refresh = response.json().get("refresh_token")
                        if isinstance(refresh, str) and refresh:
                            await self._revoke_refresh(refresh)
                    return
                payload = response.json()
                if response.status_code != 200:
                    error = payload.get("error")
                    if error == "authorization_pending":
                        return
                    if error == "slow_down":
                        attempt.poll_interval += 5
                        return
                    attempt.status = "expired" if error == "expired_token" else "failed"
                    attempt.error = (
                        "account_authorization_denied"
                        if error == "access_denied"
                        else "account_login_expired"
                        if error == "expired_token"
                        else "account_token_exchange_failed"
                    )
                    return
                # Once tokens have been issued, do not poll the one-time grant
                # again even if userinfo or local credential persistence fails.
                attempt.status = "exchanging"
                await self._accept_tokens(payload, attempt.generation)
                attempt.status = "complete"
            except asyncio.CancelledError:
                # A disconnected request may have consumed the one-time grant.
                # Never leave an attempt stuck in exchanging or retry it blindly.
                attempt.status = "failed"
                attempt.error = "account_token_exchange_failed"
                raise
            except httpx.HTTPError:
                if attempt.status == "exchanging":
                    attempt.status = "failed"
                    attempt.error = "account_token_exchange_failed"
                else:
                    attempt.poll_interval *= 2
            except Exception as exc:
                logger.warning("Device login failed: %s", type(exc).__name__)
                attempt.status = "failed"
                attempt.error = "account_token_exchange_failed"
            finally:
                attempt.next_poll_at = time.monotonic() + attempt.poll_interval
                if attempt.status != "pending":
                    attempt.device_code = ""

    async def complete_callback(
        self,
        attempt: LoginAttempt,
        *,
        state: str,
        code: str = "",
        error: str = "",
    ) -> bool:
        async with self._login_lock:
            if not secrets.compare_digest(attempt.state.encode(), state.encode()):
                raise AccountOIDCError("invalid OAuth state")
            if attempt.generation != self._generation:
                attempt.status = "expired"
            if attempt.flow == "native" and attempt.status == "complete":
                return True
            if attempt.status != "pending":
                raise AccountOIDCError("login attempt is no longer pending")
            if time.time() - attempt.created_at >= attempt.expires_in:
                attempt.status = "expired"
                raise AccountOIDCError("account_login_expired")
            if error:
                attempt.status = "failed"
                attempt.error = "account_authorization_denied"
                return False
            if not code:
                raise AccountOIDCError("missing OAuth code")
            attempt.status = "exchanging"
            try:
                await self._complete(
                    code=code,
                    verifier=attempt.verifier,
                    redirect_uri=attempt.redirect_uri,
                    generation=attempt.generation,
                )
            except asyncio.CancelledError:
                attempt.status = "failed"
                attempt.error = "account_token_exchange_failed"
                raise
            except Exception as exc:
                # HTTP exceptions can include token request URLs. Do not expose
                # provider payloads, authorization codes or tokens in logs/UI.
                logger.warning(
                    "OpenKitsune Account login failed: %s",
                    str(exc) if isinstance(exc, AccountOIDCError) else type(exc).__name__,
                )
                attempt.status = "failed"
                attempt.error = "account_token_exchange_failed"
                return False
            finally:
                attempt.verifier = ""
            attempt.status = "complete"
            return True

    async def complete_native_callback(
        self, attempt_id: str, *, state: str, code: str = "", error: str = ""
    ) -> dict:
        attempt = self._attempts.get(attempt_id)
        if attempt is None or attempt.flow != "native":
            raise AccountOIDCError("unknown native login attempt")
        # A retry after a lost response must not redeem the one-time code again.
        if not secrets.compare_digest(attempt.state.encode(), state.encode()):
            raise AccountOIDCError("invalid OAuth state")
        if code and error:
            raise AccountOIDCError("ambiguous OAuth response")
        if attempt.status == "complete":
            return {"status": "complete", "error": None}
        if attempt.status in {"failed", "expired", "cancelled"}:
            return {"status": attempt.status, "error": attempt.error or "account_login_expired"}
        try:
            await self.complete_callback(attempt, state=state, code=code, error=error)
        except AccountOIDCError:
            if attempt.status not in {"expired", "cancelled"}:
                raise
            return {"status": attempt.status, "error": "account_login_expired"}
        return {"status": attempt.status, "error": attempt.error}

    async def _close_listener(self, attempt: LoginAttempt) -> None:
        if self._listener_attempt is attempt and self._server is not None:
            server = self._server
            self._server = None
            self._listener_attempt = None
            server.close()
            await server.wait_closed()

    async def cancel(self, attempt_id: str) -> None:
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            raise AccountOIDCError("unknown login attempt")
        async with self._login_lock:
            if attempt.status == "pending":
                attempt.status = "cancelled"
                attempt.device_code = ""
            await self._close_listener(attempt)

    async def snapshot(self, *, force: bool = False) -> dict:
        # The identity snapshot is intentionally retained for offline cache and
        # audit purposes. Its presence alone must not make the UI appear signed
        # in after the OS-vault refresh token has been cleared on logout.
        async with self._credentials():
            try:
                snapshot = await self._identity_locked()
                subject = snapshot.get("account_user_id")
                if not subject or snapshot.get("status") != "active":
                    return snapshot
                checked_at = snapshot.get("profile_checked_at")
                if (
                    not force
                    and checked_at
                    and 0
                    <= (datetime.now(UTC) - datetime.fromisoformat(checked_at)).total_seconds()
                    < 20
                ):
                    return snapshot
                if (
                    not force
                    and self._identity_checked_subject == subject
                    and time.monotonic() - self._identity_checked_at < 20
                ):
                    return snapshot
                generation = self._generation
                access = await self._valid_access_token_locked()
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        f"{self._base_url}/oauth/userinfo",
                        headers={"Authorization": f"Bearer {access}"},
                    )
                if response.status_code != 200:
                    raise AccountOIDCError("account identity is temporarily unavailable")
                profile = response.json()
                if (
                    not isinstance(profile, dict)
                    or profile.get("sub") != subject
                    or generation != self._generation
                ):
                    raise AccountOIDCError("account changed during identity refresh")
                refresh = await self._tokens.load_refresh_token()
                if not refresh:
                    return {"status": "signed_out"}
                credential_hash = hashlib.sha256(refresh.encode()).hexdigest()
                if not await self._store.refresh_profile(
                    credential_hash=credential_hash, profile=profile
                ):
                    raise AccountOIDCError("account changed during identity refresh")
                self._identity_checked_at = time.monotonic()
                self._identity_checked_subject = subject
                return await self._store.snapshot(credential_hash=credential_hash)
            except (AccountOIDCError, httpx.HTTPError, ValueError):
                # A network outage is not a logout, and must not expose an
                # unrelated cached profile as the owner of the saved token.
                refresh = await self._tokens.load_refresh_token()
                if not refresh:
                    return {"status": "signed_out"}
                cached = await self._store.snapshot(
                    credential_hash=hashlib.sha256(refresh.encode()).hexdigest()
                )
                return {
                    **(cached or {}),
                    "status": "unavailable",
                    "status_reason": "account_identity_unavailable",
                }

    async def _identity_locked(self) -> dict:
        refresh = await self._tokens.load_refresh_token()
        if not refresh:
            return {"status": "signed_out"}
        credential_hash = hashlib.sha256(refresh.encode()).hexdigest()
        snapshot = await self._store.snapshot(credential_hash=credential_hash)
        if snapshot:
            return snapshot
        # Legacy credentials may have no local profile, or an old workspace's
        # profile may belong to another account. Recover only via this grant.
        generation = self._generation
        access = await self._valid_access_token_locked()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self._base_url}/oauth/userinfo",
                headers={"Authorization": f"Bearer {access}"},
            )
        if response.status_code != 200:
            raise AccountOIDCError("account identity is temporarily unavailable")
        profile = response.json()
        if (
            not isinstance(profile, dict)
            or not isinstance(profile.get("sub"), str)
            or not profile["sub"]
        ):
            raise AccountOIDCError("userinfo is missing sub")
        if generation != self._generation:
            raise AccountOIDCError("account changed during identity recovery")
        refresh = await self._tokens.load_refresh_token()
        if not refresh:
            return {"status": "signed_out"}
        session_id = secrets.token_urlsafe(18)
        await self._store.save_authenticated(
            account_user_id=profile["sub"],
            profile_json=json.dumps(profile),
            session_id=session_id,
            credential_hash=hashlib.sha256(refresh.encode()).hexdigest(),
        )
        self._session_id, self._account_user_id = session_id, profile["sub"]
        self._identity_checked_at = time.monotonic()
        self._identity_checked_subject = profile["sub"]
        return await self._store.snapshot(
            credential_hash=hashlib.sha256(refresh.encode()).hexdigest()
        )

    async def refresh_entitlements(self) -> dict:
        async with self._credentials():
            return await self._refresh_entitlements_locked()

    async def _refresh_entitlements_locked(self) -> dict:
        identity = await self._identity_locked()
        if identity["status"] != "active":
            raise AccountOIDCError("not signed in")
        access_token = await self._valid_access_token_locked()
        self._account_user_id = identity["account_user_id"]
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self._base_url}/api/v1/me/entitlements",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code != 200:
            raise AccountOIDCError(f"entitlement refresh failed with HTTP {response.status_code}")
        payload = response.json()
        if not self._account_user_id:
            raise AccountOIDCError("account identity is unavailable")
        await self._store.save_entitlements(
            account_user_id=self._account_user_id,
            entitlements_json=json.dumps(payload, separators=(",", ":")),
        )
        return payload

    async def logout(self) -> str:
        # Invalidate in-flight callbacks before waiting for credential I/O.
        self._generation += 1
        async with self._credentials():
            for attempt in self._attempts.values():
                if attempt.status in {"pending", "exchanging"}:
                    attempt.status = "expired"
                    attempt.device_code = ""
                    attempt.verifier = ""
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
                self._server = None
            refresh = await self._tokens.load_refresh_token()
            if refresh:
                await self._revoke_refresh(refresh)
            if self._session_id:
                await self._store.revoke_session(self._session_id)
            await self._tokens.clear()
            self._access_token = None
            self._access_expires_at = 0
            self._session_id = None
            self._account_user_id = None
        return ""

    async def _revoke_refresh(self, refresh: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._base_url}/oauth/revoke",
                    data={"token": refresh, "client_id": self._client_id},
                )
        except httpx.HTTPError as exc:
            raise AccountOIDCError("account revocation is temporarily unavailable") from exc
        if response.status_code >= 300:
            raise AccountOIDCError("account revocation is temporarily unavailable")

    async def marketplace_handoff(self, target_origin: str) -> str | None:
        async with self._credentials():
            identity = await self._identity_locked()
            if identity["status"] == "signed_out":
                return None
            if identity["status"] != "active":
                raise AccountOIDCError("marketplace_account_required")
            refresh = await self._tokens.load_refresh_token()
            if not refresh:
                return None
            return await self._marketplace_proof_locked(
                "/oauth/desktop-handoff",
                refresh,
                {"target_origin": target_origin},
                "ticket",
            )

    async def marketplace_install_proof(self, token: str, device_id: str) -> str:
        async with self._credentials():
            if (await self._identity_locked())["status"] != "active":
                raise AccountOIDCError("marketplace_account_required")
            refresh = await self._tokens.load_refresh_token()
            if not refresh:
                raise AccountOIDCError("marketplace_account_required")
            return await self._marketplace_proof_locked(
                "/oauth/desktop-install-proof",
                refresh,
                {"installation_token": token, "device_id": device_id},
                "proof",
            )

    async def _marketplace_proof_locked(
        self,
        path: str,
        refresh: str,
        values: dict[str, str],
        field_name: str,
    ) -> str:
        generation = self._generation
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._base_url}{path}",
                    json={
                        "client_id": self._client_id,
                        "refresh_token": refresh,
                        "target_client_id": "marketplace",
                        **values,
                    },
                )
            if generation != self._generation:
                raise AccountOIDCError("account changed during request")
            if response.status_code != 200:
                raise AccountOIDCError("marketplace account authorization failed")
            value = response.json().get(field_name)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,512}", value):
                raise AccountOIDCError("invalid marketplace account authorization")
            return value
        except (httpx.HTTPError, ValueError) as exc:
            raise AccountOIDCError("marketplace account authorization unavailable") from exc

    async def _callback(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        attempt: LoginAttempt,
    ) -> None:
        language = "en"
        try:
            request_line = (await asyncio.wait_for(reader.readline(), timeout=5)).decode(
                "ascii", errors="replace"
            )
            parts = request_line.strip().split(" ")
            if len(parts) != 3 or parts[0] != "GET":
                raise AccountOIDCError("invalid loopback callback")
            accept_language = ""
            for _ in range(64):
                raw_header = await asyncio.wait_for(reader.readline(), timeout=5)
                if raw_header in {b"", b"\r\n", b"\n"}:
                    break
                if len(raw_header) > 8_192:
                    raise AccountOIDCError("loopback callback header is too large")
                header = raw_header.decode("latin-1", errors="replace")
                name, separator, value = header.partition(":")
                if separator and name.strip().lower() == "accept-language":
                    accept_language = value.strip()
            language = _preferred_callback_language(accept_language)
            target = urlsplit(parts[1])
            if target.path != "/auth/callback":
                raise AccountOIDCError("invalid loopback callback path")
            query = parse_qs(target.query, max_num_fields=20)
            if any(len(query.get(key, [])) > 1 for key in ("state", "code", "error")):
                raise AccountOIDCError("duplicate OAuth parameters")
            state = query.get("state", [""])[0]
            code = query.get("code", [""])[0]
            success = await self.complete_callback(
                attempt, state=state, code=code, error=query.get("error", [""])[0]
            )
            body = _callback_page_html(success=success, language=language)
            status = b"200 OK" if success else b"400 Bad Request"
        except Exception:
            body = _callback_page_html(success=False, language=language)
            status = b"400 Bad Request"
        writer.write(
            b"HTTP/1.1 "
            + status
            + b"\r\nContent-Type: text/html; charset=utf-8\r\n"
            + f"Content-Language: {'zh-CN' if language == 'zh' else 'en'}\r\n".encode()
            + b"Cache-Control: no-store\r\n"
            + b"X-Content-Type-Options: nosniff\r\n"
            + b"Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        if attempt.status != "pending":
            await self._close_listener(attempt)

    async def _complete(
        self,
        *,
        code: str,
        verifier: str,
        redirect_uri: str = CALLBACK_URI,
        generation: int | None = None,
    ) -> None:
        if generation is None:
            generation = self._generation
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_response = await client.post(
                f"{self._base_url}/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self._client_id,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                },
            )
            if token_response.status_code != 200:
                raise AccountOIDCError(
                    f"token exchange failed with HTTP {token_response.status_code}"
                )
            tokens = token_response.json()
        await self._accept_tokens(tokens, generation)

    async def _accept_tokens(self, tokens: dict, generation: int) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            access_token = str(tokens.get("access_token", ""))
            refresh_token = str(tokens.get("refresh_token", ""))
            try:
                if not access_token or not refresh_token:
                    raise AccountOIDCError("token response is incomplete")
                expires_in = max(0, int(tokens.get("expires_in", 0)))
                userinfo_response = await client.get(
                    f"{self._base_url}/oauth/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if userinfo_response.status_code != 200:
                    raise AccountOIDCError("userinfo request failed")
                profile = userinfo_response.json()
                account_user_id = str(profile.get("sub", ""))
                if not account_user_id:
                    raise AccountOIDCError("userinfo is missing sub")
            except Exception:
                # Exchange already minted a grant; a failed profile lookup must not orphan it.
                if refresh_token:
                    await self._revoke_refresh(refresh_token)
                raise
        async with self._credentials():
            if generation != self._generation:
                await self._revoke_refresh(refresh_token)
                raise AccountOIDCError("login attempt was superseded")
            previous = await self._tokens.load_refresh_token()
            session_id = secrets.token_urlsafe(18)
            try:
                # Revoke the old product grant before accepting the new identity.
                if previous and previous != refresh_token:
                    await self._revoke_refresh(previous)
                if generation != self._generation:
                    raise AccountOIDCError("login attempt was superseded")
                await self._tokens.save_refresh_token(refresh_token)
                await self._store.save_authenticated(
                    account_user_id=account_user_id,
                    profile_json=json.dumps(profile, separators=(",", ":")),
                    session_id=session_id,
                    credential_hash=hashlib.sha256(refresh_token.encode()).hexdigest(),
                )
                if generation != self._generation:
                    raise AccountOIDCError("login attempt was superseded")
            except Exception:
                if previous and await self._tokens.load_refresh_token() == previous:
                    pass  # Revocation failed: retain the existing local credential.
                else:
                    await self._tokens.clear()
                    self._access_token = None
                await self._revoke_refresh(refresh_token)
                raise
            self._access_token = access_token
            self._access_credential_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            self._access_expires_at = time.monotonic() + expires_in
            self._session_id = session_id
            self._account_user_id = account_user_id
            self._identity_checked_at = time.monotonic()
            self._identity_checked_subject = account_user_id
            # A temporary entitlement outage must not turn a committed login into failure.
            try:
                await self._refresh_entitlements_locked()
            except (AccountOIDCError, httpx.HTTPError):
                logger.warning("Account signed in; entitlement refresh is temporarily unavailable")

    async def _valid_access_token(self) -> str:
        async with self._credentials():
            return await self._valid_access_token_locked()

    async def _valid_access_token_locked(self) -> str:
        refresh_token = await self._tokens.load_refresh_token()
        if not refresh_token:
            self._access_token = None
            raise AccountOIDCError("not signed in")
        credential_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        if self._access_credential_hash != credential_hash:
            self._access_token = None
            self._session_id = None
            self._account_user_id = None
        if self._session_id and not await self._store.session_is_active(self._session_id):
            self._access_token = None
            raise AccountOIDCError("account is suspended or session was revoked")
        if self._access_token and self._access_expires_at > time.monotonic() + 30:
            return self._access_token
        snapshot = await self._store.snapshot(credential_hash=credential_hash)
        if snapshot and snapshot.get("status") != "active":
            raise AccountOIDCError("account is suspended")
        refresh_token = await self._tokens.load_refresh_token()
        if not refresh_token:
            raise AccountOIDCError("not signed in")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self._base_url}/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                },
            )
        if response.status_code != 200:
            if response.status_code in {400, 401, 403}:
                await self._tokens.clear()
                self._access_token = None
                raise AccountOIDCError("refresh token is no longer valid")
            raise AccountOIDCError("account refresh is temporarily unavailable")
        tokens = response.json()
        self._access_token = str(tokens.get("access_token", ""))
        rotated = str(tokens.get("refresh_token", ""))
        if rotated:
            await self._tokens.save_refresh_token(rotated)
            await self._store.rotate_credential(
                credential_hash,
                hashlib.sha256(rotated.encode()).hexdigest(),
            )
        self._access_credential_hash = hashlib.sha256(
            (rotated or refresh_token).encode()
        ).hexdigest()
        if not self._access_token:
            raise AccountOIDCError("refresh response is incomplete")
        self._access_expires_at = time.monotonic() + max(0, int(tokens.get("expires_in", 0)))
        return self._access_token

    def _expire_attempt(self, attempt: LoginAttempt) -> None:
        if attempt.status == "pending":
            attempt.status = "expired"
            attempt.device_code = ""
            if self._listener_attempt is attempt and self._server is not None:
                self._server.close()
                self._server = None
                self._listener_attempt = None
