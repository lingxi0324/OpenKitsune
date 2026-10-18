"""Spatial awareness from IP addresses.

Produces a *bounded* spatial context instead of a bare coordinate:

* IP extraction with a trusted-proxy allow-list (``X-Forwarded-For`` is only
  honoured when the peer itself is trusted).
* Provider chain (``ipwho.is`` HTTPS primary, ``ip-api`` fallback) behind a
  small in-memory cache.
* City-level precision is the default; the caller receives an explicit
  ``accuracy_radius_km`` and ``precision`` so the model can soften wording.
* Explicit degradation semantics (``ok`` / ``degraded`` / ``unknown``). A
  proxy/VPN signal invalidates the geographic fields rather than reporting the
  exit node's city.
* Privacy: raw IPs are never persisted or logged; cache keys are salted
  hashes and live only in process memory.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import math
import secrets
import time
from collections import OrderedDict
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .temporal_context import day_period

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 24 * 60 * 60
_DEGRADED_TTL_SECONDS = 10 * 60
_WIFI_CONTEXT_TTL_SECONDS = 30 * 60
_STALE_GRACE_SECONDS = 7 * 24 * 60 * 60
_CACHE_MAX_ENTRIES = 256

# Free IP geolocation is city-level at best. The APIs do not return a radius,
# so we publish a conservative heuristic instead of implying GPS precision.
_ACCURACY_RADIUS_KM = {"city": 25.0, "region": 80.0, "country": 300.0}

_CACHE_SALT = secrets.token_bytes(16)

_REQUEST_IP: ContextVar[str | None] = ContextVar("openkitsune_spatial_ip", default=None)
_REQUEST_HOST_FALLBACK: ContextVar[bool] = ContextVar(
    "openkitsune_spatial_host_fallback", default=False
)


class SpatialLookupError(RuntimeError):
    """Raised when a geolocation provider cannot answer."""


@dataclass
class SpatialContext:
    """Bounded spatial facts meant for prompt / tool consumption."""

    # Location facts (city-level)
    city: str | None = None
    region: str | None = None
    country: str | None = None
    country_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy_radius_km: float | None = None
    precision: str | None = None  # "city" / "region" / "country"

    # Time context derived from the timezone
    timezone: str | None = None
    local_time_iso: str | None = None
    local_hour: int | None = None
    time_of_day: str | None = None  # late_night / morning / work_hours / evening
    local_time_label: str | None = None

    # Network environment (a spatial proxy signal)
    isp: str | None = None
    org: str | None = None
    asn: str | None = None
    is_mobile: bool | None = None
    is_proxy_or_vpn: bool | None = None

    # Quality and degradation state
    status: str = "unknown"  # ok / degraded / unknown
    degraded_reason: str | None = None
    is_stale: bool = False
    lookup_provider: str | None = None
    accuracy_source: str | None = None
    # Provenance: manual / request_ip / host_egress
    source: str | None = None
    # Whether the two geolocation providers agree with each other.
    providers_agree: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IpExtraction:
    """Result of resolving the caller address behind proxies."""

    ip: str | None
    source: str  # remote / x-forwarded-for / none
    reason: str | None = None


def normalize_ip(value: Any) -> str | None:
    """Return a canonical IP string (IPv4-mapped IPv6 unwrapped), or None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return str(ip).lower()


def is_public_ip(value: Any) -> bool:
    """True only for globally routable addresses suitable for geolocation."""
    text = normalize_ip(value)
    if text is None:
        return False
    return bool(ipaddress.ip_address(text).is_global)


def _parse_trusted_proxies(
    value: str | None,
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for token in str(value or "").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            networks.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            logger.debug("[Spatial] ignoring invalid trusted proxy CIDR entry")
    return networks


def extract_public_ip(
    remote_addr: Any,
    forwarded_for: str | None = "",
    trusted_proxies: str | None = "",
) -> IpExtraction:
    """Resolve the caller's public IP using a trusted-upstream policy.

    ``X-Forwarded-For`` is only read when the direct peer is loopback or listed
    in ``trusted_proxies``; the left-most public address wins.
    """
    remote = normalize_ip(remote_addr)
    if remote is None:
        return IpExtraction(None, "none", "invalid_remote_addr")

    remote_ip = ipaddress.ip_address(remote)
    peer_trusted = remote_ip.is_loopback or any(
        remote_ip in network for network in _parse_trusted_proxies(trusted_proxies)
    )

    if peer_trusted and forwarded_for:
        for token in str(forwarded_for).split(","):
            candidate = normalize_ip(token)
            if candidate is not None and is_public_ip(candidate):
                return IpExtraction(candidate, "x-forwarded-for")

    if is_public_ip(remote):
        return IpExtraction(remote, "remote")

    reason = "loopback" if remote_ip.is_loopback else "private_ip"
    return IpExtraction(None, "none", reason)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


async def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": "OpenKitsune spatial-awareness"})
        response.raise_for_status()
        try:
            data = response.json()
        except (ValueError, UnicodeDecodeError):
            # Some Chinese endpoints (e.g. pconline) return GBK-encoded JSON
            # without a usable charset header.
            data = json.loads(response.content.decode("gb18030", errors="replace"))
    if not isinstance(data, dict):
        raise SpatialLookupError("invalid payload")
    return data


async def _lookup_pconline(ip: str | None, timeout: float) -> dict[str, Any]:
    """PConline (太平洋电脑网) China-specific IP database.

    Much more accurate than international databases for Chinese carrier /
    CGNAT addresses. It only understands IPv4 and China; anything else raises
    so the international cross-check path can take over.
    """
    normalized = normalize_ip(ip)
    if normalized is not None and ipaddress.ip_address(normalized).version == 6:
        raise SpatialLookupError("pconline_ipv6_unsupported")

    url = "https://whois.pconline.com.cn/ipJson.jsp?json=true"
    if normalized is not None:
        url += f"&ip={normalized}"
    data = await _fetch_json(url, timeout)

    region = str(data.get("pro") or "").strip()
    city = str(data.get("city") or "").strip()
    if data.get("err") or not region:
        raise SpatialLookupError("pconline_not_cn")

    timezone = "Asia/Shanghai"
    if "香港" in region:
        timezone = "Asia/Hong_Kong"
    elif "澳门" in region:
        timezone = "Asia/Macau"
    elif "台湾" in region:
        timezone = "Asia/Taipei"

    return {
        "provider": "pconline",
        "city": city or None,
        "region": region,
        "country_code": "CN",
        "country_name": "中国",
        "latitude": None,
        "longitude": None,
        "timezone": timezone,
        "isp": None,
        "org": None,
        "asn": None,
        "is_mobile": None,
        "is_proxy_or_vpn": None,
    }


async def _lookup_ipwhois(ip: str | None, timeout: float) -> dict[str, Any]:
    """ipwho.is — HTTPS, no API key required."""
    url = f"https://ipwho.is/{ip}" if ip else "https://ipwho.is/"
    data = await _fetch_json(url, timeout)
    if data.get("success") is False:
        raise SpatialLookupError(str(data.get("message") or "lookup failed"))
    connection = data.get("connection") or {}
    timezone_info = data.get("timezone") or {}
    return {
        "provider": "ipwho.is",
        "city": data.get("city"),
        "region": data.get("region"),
        "country_code": data.get("country_code"),
        "country_name": data.get("country"),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "timezone": timezone_info.get("id"),
        "isp": connection.get("isp"),
        "org": connection.get("org"),
        "asn": str(connection["asn"]) if connection.get("asn") else None,
        "is_mobile": None,
        "is_proxy_or_vpn": None,
    }


async def _lookup_ipapi(ip: str | None, timeout: float) -> dict[str, Any]:
    """ip-api.com — free tier is HTTP-only, includes proxy/mobile flags."""
    base = f"http://ip-api.com/json/{ip}" if ip else "http://ip-api.com/json/"
    fields = (
        "status,message,country,countryCode,regionName,city,lat,lon,timezone,"
        "isp,org,as,mobile,proxy,hosting"
    )
    data = await _fetch_json(f"{base}?lang=zh-CN&fields={fields}", timeout)
    if data.get("status") != "success":
        raise SpatialLookupError(str(data.get("message") or "lookup failed"))
    proxy = bool(data.get("proxy") or data.get("hosting"))
    return {
        "provider": "ip-api",
        "city": data.get("city"),
        "region": data.get("regionName"),
        "country_code": data.get("countryCode"),
        "country_name": data.get("country"),
        "latitude": data.get("lat"),
        "longitude": data.get("lon"),
        "timezone": data.get("timezone"),
        "isp": data.get("isp"),
        "org": data.get("org"),
        "asn": data.get("as"),
        "is_mobile": data.get("mobile"),
        "is_proxy_or_vpn": proxy,
    }


_PROVIDERS = (
    ("ipwho.is", _lookup_ipwhois),
    ("ip-api", _lookup_ipapi),
)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    expires_at: float
    stale_until: float
    context: SpatialContext


_CACHE: OrderedDict[str, _CacheEntry] = OrderedDict()


def _cache_key(ip: str | None) -> str:
    material = f"{ip or 'self'}:".encode() + _CACHE_SALT
    return hashlib.sha256(material).hexdigest()


def _cache_get(key: str) -> _CacheEntry | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    if entry.stale_until <= time.monotonic():
        _CACHE.pop(key, None)
        return None
    _CACHE.move_to_end(key)
    return entry


def _cache_put(key: str, context: SpatialContext) -> None:
    now = time.monotonic()
    ttl = _CACHE_TTL_SECONDS if context.status == "ok" else _DEGRADED_TTL_SECONDS
    if context.source == "wifi_bssid":
        # Wi-Fi fingerprints change when the user moves; keep this short.
        ttl = min(ttl, _WIFI_CONTEXT_TTL_SECONDS)
    _CACHE[key] = _CacheEntry(
        expires_at=now + ttl,
        stale_until=now + max(ttl, _STALE_GRACE_SECONDS),
        context=context,
    )
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.popitem(last=False)


def clear_spatial_cache() -> None:
    """Drop all cached contexts (useful for tests and privacy resets)."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


def _time_of_day(hour: int) -> str:
    if hour < 6:
        return "late_night"
    if hour < 9:
        return "morning"
    if hour < 18:
        return "work_hours"
    return "evening"


def _apply_timezone(context: SpatialContext, timezone_name: str | None) -> None:
    if not timezone_name:
        return
    try:
        local = datetime.now(ZoneInfo(timezone_name))
    except Exception:
        context.timezone = None
        return
    context.timezone = timezone_name
    context.local_time_iso = local.isoformat(timespec="seconds")
    context.local_hour = local.hour
    context.time_of_day = _time_of_day(local.hour)
    context.local_time_label = day_period(local.hour)[0]


def _build_context(
    raw: dict[str, Any],
    *,
    is_stale: bool = False,
    source: str | None = None,
) -> SpatialContext:
    context = SpatialContext(
        city=raw.get("city"),
        region=raw.get("region"),
        country=raw.get("country_code"),
        country_name=raw.get("country_name"),
        latitude=raw.get("latitude"),
        longitude=raw.get("longitude"),
        timezone=raw.get("timezone"),
        isp=raw.get("isp"),
        org=raw.get("org"),
        asn=raw.get("asn"),
        is_mobile=raw.get("is_mobile"),
        is_proxy_or_vpn=raw.get("is_proxy_or_vpn"),
        is_stale=is_stale,
        lookup_provider=raw.get("provider"),
        source=source,
    )

    # A proxy/VPN makes the reported city the exit node's city. Drop the
    # geographic fields instead of inviting the model to assert a wrong place.
    if context.is_proxy_or_vpn:
        return SpatialContext(
            status="degraded",
            degraded_reason="proxy_or_vpn",
            is_proxy_or_vpn=True,
            isp=context.isp,
            lookup_provider=context.lookup_provider,
            source=source,
            is_stale=is_stale,
        )

    if context.city:
        context.precision = "city"
    elif context.region:
        context.precision = "region"
    elif context.country:
        context.precision = "country"

    if context.precision:
        context.accuracy_radius_km = _ACCURACY_RADIUS_KM[context.precision]
        context.accuracy_source = "heuristic_city_level"

    _apply_timezone(context, context.timezone)

    if context.precision or context.timezone:
        context.status = "ok"
    else:
        context.status = "unknown"
        context.degraded_reason = "insufficient_fields"
    return context


def _same_text(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return str(left).strip().casefold() == str(right).strip().casefold()


def _distance_km(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    """Great-circle distance between two provider payloads, if both have coords."""
    try:
        lat1 = float(left["latitude"])
        lon1 = float(left["longitude"])
        lat2 = float(right["latitude"])
        lon2 = float(right["longitude"])
    except (KeyError, TypeError, ValueError):
        return None

    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _merge_provider_results(
    results: list[dict[str, Any]],
    *,
    source: str | None,
    is_stale: bool = False,
) -> SpatialContext:
    """Cross-check providers and downgrade to the precision they agree on.

    Provider databases disagree often — especially for carrier NAT / CGNAT
    addresses. Claiming one provider's city in that case is exactly the
    over-confident behaviour this module is meant to prevent.
    """
    if not results:
        return SpatialContext(
            status="degraded",
            degraded_reason="lookup_failed",
            source=source,
            is_stale=is_stale,
        )

    if any(result.get("is_proxy_or_vpn") for result in results):
        return SpatialContext(
            status="degraded",
            degraded_reason="proxy_or_vpn",
            is_proxy_or_vpn=True,
            source=source,
            is_stale=is_stale,
        )

    primary = results[0]
    context = _build_context(primary, is_stale=is_stale, source=source)

    if len(results) == 1:
        # A single database is not enough to trust a city/province claim:
        # providers demonstrably disagree for the same address. Keep the
        # country and timezone, drop the unverifiable local fields.
        context.providers_agree = None
        context.accuracy_source = "single_provider"
        if context.precision in ("city", "region"):
            context.city = None
            context.region = None
            context.latitude = None
            context.longitude = None
            context.precision = "country"
            context.accuracy_radius_km = _ACCURACY_RADIUS_KM["country"]
            context.status = "degraded"
            context.degraded_reason = "single_provider"
        return context

    secondary = results[1]
    if not _same_text(context.country, secondary.get("country_code")):
        return SpatialContext(
            status="degraded",
            degraded_reason="providers_disagree_country",
            providers_agree=False,
            source=source,
            is_stale=is_stale,
            lookup_provider=context.lookup_provider,
            accuracy_source="cross_checked_country_mismatch",
        )

    distance = _distance_km(primary, secondary)
    if distance is not None:
        if distance <= 50:
            level = "city"
        elif distance <= 200:
            level = "region"
        else:
            level = "country"
    elif _same_text(context.city, secondary.get("city")):
        level = "city"
    elif _same_text(context.region, secondary.get("region")):
        level = "region"
    else:
        level = "country"

    context.providers_agree = level != "country"
    if level == "city":
        context.accuracy_radius_km = _ACCURACY_RADIUS_KM["city"]
        context.accuracy_source = "cross_checked_city"
    elif level == "region":
        context.city = None
        context.precision = "region"
        context.accuracy_radius_km = _ACCURACY_RADIUS_KM["region"]
        context.accuracy_source = "cross_checked_region"
    else:
        context.city = None
        context.region = None
        context.latitude = None
        context.longitude = None
        context.precision = "country"
        context.accuracy_radius_km = _ACCURACY_RADIUS_KM["country"]
        context.accuracy_source = "cross_checked_country_only"
        context.status = "degraded"
        context.degraded_reason = "providers_disagree"
    return context


def _manual_context(location: str, timezone_name: str | None) -> SpatialContext:
    """User-configured location, treated as the trustworthy baseline."""
    context = SpatialContext(
        city=location,
        precision="manual",
        status="ok",
        source="manual",
        accuracy_source="user_configured",
        accuracy_radius_km=0.0,
    )
    _apply_timezone(context, timezone_name)
    return context


def _build_wifi_context(
    fix: Any,
    geo: dict[str, Any] | None,
    fallback_timezone: str | None,
) -> SpatialContext:
    context = SpatialContext(
        city=(geo or {}).get("city"),
        region=(geo or {}).get("region"),
        country=(geo or {}).get("country"),
        country_name=(geo or {}).get("country_name"),
        latitude=fix.latitude,
        longitude=fix.longitude,
        accuracy_radius_km=max(fix.accuracy_m / 1000.0, 0.01),
        precision="wifi",
        status="ok",
        source="wifi_bssid",
        accuracy_source="beacondb_wifi",
    )
    _apply_timezone(context, fallback_timezone)
    return context


def _merge_wifi_context(
    wifi: SpatialContext,
    ip_context: SpatialContext | None,
) -> SpatialContext:
    """Cross-check the Wi-Fi fix against the IP-derived context.

    The Wi-Fi fix wins on precision. When the two disagree, we keep the Wi-Fi
    result but flag the conflict so the prompt can say so instead of silently
    picking a side.
    """
    if ip_context is None:
        return wifi

    if not wifi.city and not wifi.region:
        # Reverse geocoding failed; borrow names from IP, keep Wi-Fi coords.
        if ip_context.city or ip_context.region:
            wifi.city = ip_context.city
            wifi.region = ip_context.region
            wifi.country = wifi.country or ip_context.country
            wifi.country_name = wifi.country_name or ip_context.country_name
            wifi.accuracy_source = "wifi_coords_ip_names"
        wifi.providers_agree = None
    elif ip_context.city or ip_context.region:
        if _same_text(wifi.city, ip_context.city) or _same_text(wifi.region, ip_context.region):
            wifi.providers_agree = True
            wifi.accuracy_source = "wifi_cross_checked"
        else:
            wifi.providers_agree = False
            wifi.degraded_reason = "wifi_ip_conflict"
            wifi.accuracy_source = "wifi_conflict_with_ip"
    else:
        wifi.providers_agree = None
        wifi.accuracy_source = "wifi_only"

    if not wifi.timezone:
        _apply_timezone(wifi, ip_context.timezone)
    if not wifi.isp:
        wifi.isp = ip_context.isp
        wifi.org = ip_context.org
    if not wifi.country:
        wifi.country = ip_context.country
        wifi.country_name = ip_context.country_name
    return wifi


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def _resolve_ip_context(
    query_ip: str | None,
    *,
    source: str,
    entry: _CacheEntry | None,
    timeout: float,
) -> SpatialContext:
    # China-specific database first. International databases routinely place
    # Chinese carrier / CGNAT addresses in Beijing, Shanghai or Guangdong even
    # when the user is nowhere near those cities.
    if query_ip is None or ipaddress.ip_address(query_ip).version == 4:
        try:
            cn_raw = await _lookup_pconline(query_ip, timeout)
        except Exception as exc:
            logger.debug("[Spatial] pconline unavailable: %s", type(exc).__name__)
        else:
            context = _build_context(cn_raw, source=source)
            context.accuracy_source = "cn_specific_database"
            context.providers_agree = None
            return context

    async def _call(provider_name: str, provider: Any) -> dict[str, Any] | None:
        try:
            return await provider(query_ip, timeout)
        except Exception as exc:
            logger.debug("[Spatial] provider %s failed: %s", provider_name, type(exc).__name__)
            return None

    results: list[dict[str, Any]] = []
    tasks = [asyncio.create_task(_call(name, fn)) for name, fn in _PROVIDERS]
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    # Preserve provider order so the primary result stays primary.
    for task in tasks:
        if task in done and not task.cancelled():
            try:
                result = task.result()
            except Exception:
                result = None
            if result:
                results.append(result)
    if results:
        return _merge_provider_results(results, source=source)

    if entry is not None and entry.stale_until > time.monotonic():
        return replace(entry.context, is_stale=True, degraded_reason="lookup_failed_stale")

    return SpatialContext(status="degraded", degraded_reason="lookup_failed", source=source)


async def _resolve_with_wifi(
    wifi_task: asyncio.Task[Any] | None,
    ip_context: SpatialContext,
    *,
    timeout: float,
    fallback_timezone: str | None,
) -> SpatialContext:
    if wifi_task is None:
        return ip_context
    try:
        fix = await wifi_task
    except Exception:
        fix = None
    if fix is None:
        return ip_context

    from .wifi_location import reverse_geocode

    geo = await reverse_geocode(fix.latitude, fix.longitude, min(timeout, 2.0))
    wifi_context = _build_wifi_context(fix, geo, fallback_timezone)
    return _merge_wifi_context(wifi_context, ip_context)


async def resolve_spatial_context(
    ip: str | None = None,
    *,
    allow_host_fallback: bool = False,
) -> SpatialContext | None:
    """Resolve a spatial context for ``ip``.

    When ``ip`` is missing/private and ``allow_host_fallback`` is true, the
    provider is asked about the caller's own egress address — the right answer
    for a locally running desktop app. When fallback is disabled (IM channels,
    where the user's IP is unknown), an honest ``unknown`` is returned instead
    of reporting the server's datacenter.
    """
    from ..config import settings

    if not getattr(settings, "spatial_awareness_enabled", True):
        return None

    manual_location = str(getattr(settings, "spatial_manual_location", "") or "").strip()
    if manual_location:
        return _manual_context(
            manual_location,
            getattr(settings, "scheduler_timezone", "Asia/Shanghai"),
        )

    candidate = normalize_ip(ip)
    if candidate is not None and is_public_ip(candidate):
        query_ip: str | None = candidate
        source = "request_ip"
    elif allow_host_fallback:
        query_ip = None
        source = "host_egress"
    else:
        reason = "no_client_ip" if not ip else "private_ip"
        return SpatialContext(status="unknown", degraded_reason=reason)

    key = _cache_key(query_ip)
    entry = _cache_get(key)
    now = time.monotonic()
    if entry is not None and entry.expires_at > now:
        return entry.context

    timeout = float(getattr(settings, "spatial_lookup_timeout_seconds", 1.5) or 1.5)

    wifi_task: asyncio.Task[Any] | None = None
    if getattr(settings, "spatial_wifi_enabled", False):
        from .wifi_location import resolve_wifi_fix

        wifi_timeout = float(getattr(settings, "spatial_wifi_timeout_seconds", 2.5) or 2.5)
        wifi_task = asyncio.create_task(resolve_wifi_fix(wifi_timeout))

    try:
        ip_context = await _resolve_ip_context(
            query_ip,
            source=source,
            entry=entry,
            timeout=timeout,
        )
        final_context = await _resolve_with_wifi(
            wifi_task,
            ip_context,
            timeout=timeout,
            fallback_timezone=getattr(settings, "scheduler_timezone", "Asia/Shanghai"),
        )
    finally:
        if wifi_task is not None and not wifi_task.done():
            wifi_task.cancel()
            await asyncio.gather(wifi_task, return_exceptions=True)

    _cache_put(key, final_context)
    return final_context


def bind_spatial_request(
    ip: str | None,
    *,
    allow_host_fallback: bool = True,
) -> tuple[Token[str | None], Token[bool]]:
    """Bind the current request's IP for prompt/tool resolution (context-local)."""
    return (
        _REQUEST_IP.set(normalize_ip(ip)),
        _REQUEST_HOST_FALLBACK.set(bool(allow_host_fallback)),
    )


def reset_spatial_request(token: tuple[Token[str | None], Token[bool]]) -> None:
    ip_token, fallback_token = token
    _REQUEST_HOST_FALLBACK.reset(fallback_token)
    _REQUEST_IP.reset(ip_token)


async def resolve_current_spatial_context() -> SpatialContext | None:
    """Resolve using the request-bound IP, if any."""
    return await resolve_spatial_context(
        _REQUEST_IP.get(),
        allow_host_fallback=_REQUEST_HOST_FALLBACK.get(),
    )


def _coerce_context(value: SpatialContext | dict[str, Any]) -> SpatialContext:
    if isinstance(value, SpatialContext):
        return value
    allowed = {field.name for field in fields(SpatialContext)}
    return SpatialContext(**{key: val for key, val in value.items() if key in allowed})


def format_spatial_hint(value: SpatialContext | dict[str, Any]) -> str:
    """Render a compact prompt block; empty string when nothing is trustworthy."""
    context = _coerce_context(value)
    if context.is_proxy_or_vpn:
        return ""
    if context.status not in ("ok", "degraded"):
        return ""
    if context.status == "degraded" and context.precision != "country" and not context.timezone:
        return ""
    if not (context.city or context.region or context.country or context.timezone):
        return ""

    manual = context.precision == "manual"
    wifi_source = context.source == "wifi_bssid"
    lines = ["## 空间感知", ""]

    if manual and context.city:
        lines.append(f"- 位置：{context.city}（用户手动设置，可视为可靠）")
    elif wifi_source:
        location_parts: list[str] = []
        for part in (context.country_name or context.country, context.region, context.city):
            if part and part not in location_parts:
                location_parts.append(part)
        location = " · ".join(location_parts) or "本机附近"
        if context.accuracy_radius_km and context.accuracy_radius_km < 1:
            accuracy_text = f"误差约 {context.accuracy_radius_km * 1000:.0f} 米"
        elif context.accuracy_radius_km:
            accuracy_text = f"误差约 {context.accuracy_radius_km:.0f} 公里"
        else:
            accuracy_text = "精度未知"
        if context.providers_agree is False:
            agreement = "；与 IP 推断不一致，已采用 Wi-Fi 结果"
        elif context.providers_agree is True:
            agreement = "；与 IP 推断一致"
        else:
            agreement = ""
        lines.append(f"- 位置：{location}（Wi-Fi 指纹定位，{accuracy_text}{agreement}）")
    elif context.status == "ok":
        location_parts: list[str] = []
        for part in (context.country_name or context.country, context.region, context.city):
            if part and part not in location_parts:
                location_parts.append(part)
        location = " · ".join(location_parts)
        precision_label = {
            "city": "城市级",
            "region": "省级",
            "country": "国家级",
        }.get(context.precision or "", "粗略")
        radius = (
            f"，误差约 {context.accuracy_radius_km:.0f} 公里" if context.accuracy_radius_km else ""
        )
        source_note = "；单一数据源" if context.accuracy_source == "single_provider" else ""
        lines.append(f"- 位置：{location}（{precision_label}近似{radius}{source_note}，仅供参考）")
    elif context.precision == "country" and context.country:
        country = context.country_name or context.country
        reason = (
            "仅一个数据源响应，无法交叉验证"
            if context.degraded_reason == "single_provider"
            else "IP 数据源给出的城市互相矛盾"
        )
        lines.append(f"- 位置：{country}（仅能确定到国家；{reason}，不要推断省份或城市）")
    elif context.timezone:
        lines.append("- 位置：不可用（IP 数据源无法一致判断），仅当地时间可参考")

    if context.local_time_iso and context.timezone:
        local_time = context.local_time_iso[:16].replace("T", " ")
        suffix = f" · {context.local_time_label}" if context.local_time_label else ""
        lines.append(f"- 当地时间：{local_time}（{context.timezone}）{suffix}")
    network = context.isp or context.org
    if network:
        network_type = "移动网络" if context.is_mobile else ""
        lines.append(f"- 网络：{network}{f'（{network_type}）' if network_type else ''}")
    if context.is_stale:
        lines.append("- 数据状态：来自较早的缓存，位置与时间可能已经变化，请谨慎使用。")
    if manual:
        lines.append(
            "- 提示：位置由用户手动设置，可直接使用，不要再加「大概 / 附近」等不确定措辞。"
        )
    elif wifi_source:
        lines.append(
            "- 提示：位置来自附近 Wi-Fi 指纹，通常比 IP 更可靠；仍可能有室内误差，"
            "不要精确到门牌号。"
        )
    else:
        lines.append(
            "- 提示：位置来自 IP 推断，只能使用「大概 / 附近」这类近似措辞，"
            "不要断言区县、街道或具体地点；用户自述的位置优先于此推断。"
        )
    return "\n".join(lines)
