"""Wi-Fi BSSID based positioning (opt-in).

Windows desktops can enumerate nearby access points without special hardware
beyond a Wi-Fi adapter. The BSSID set is sent to beaconDB (free, no API key)
to obtain a coordinate fix, then reverse-geocoded with BigDataCloud (free, no
API key) into a city-level name.

This module deliberately stays provider-agnostic: it only returns a raw fix.
Fusion with IP-derived data happens in :mod:`openkitsune.core.spatial_context`.
"""

from __future__ import annotations

import hashlib
import logging
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BSSID_RE = re.compile(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})")
_SIGNAL_RE = re.compile(r"(?:Signal|信号)\s*:\s*(\d+)\s*%")
_MAX_NETWORKS = 12

_SCAN_CACHE_TTL = 60.0
_FIX_CACHE_TTL = 6 * 60 * 60
_FIX_FAILURE_TTL = 10 * 60
_GEO_CACHE_TTL = 24 * 60 * 60

_SCAN_CACHE: tuple[float, list[WifiObservation]] | None = None
_FIX_CACHE: dict[str, tuple[float, WifiFix | None]] = {}
_GEO_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}


class WifiLookupError(RuntimeError):
    """Raised when the Wi-Fi positioning provider cannot answer."""


@dataclass(frozen=True)
class WifiObservation:
    bssid: str
    signal_percent: int | None = None


@dataclass(frozen=True)
class WifiFix:
    latitude: float
    longitude: float
    accuracy_m: float
    provider: str = "beacondb"


def _decode_output(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "cp936"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_netsh_output(text: str) -> list[WifiObservation]:
    """Parse ``netsh wlan show networks mode=bssid`` output (EN/zh)."""
    observations: list[WifiObservation] = []
    current: WifiObservation | None = None

    for line in text.splitlines():
        bssid_match = _BSSID_RE.search(line)
        if bssid_match:
            if current is not None:
                observations.append(current)
            current = WifiObservation(bssid_match.group(1).lower(), None)
            continue
        if current is None:
            continue
        signal_match = _SIGNAL_RE.search(line)
        if signal_match:
            try:
                current = WifiObservation(current.bssid, int(signal_match.group(1)))
            except ValueError:
                pass

    if current is not None:
        observations.append(current)

    # Deduplicate, keeping the strongest observation per BSSID.
    best: dict[str, WifiObservation] = {}
    for observation in observations:
        previous = best.get(observation.bssid)
        if previous is None or (observation.signal_percent or -1) > (previous.signal_percent or -1):
            best[observation.bssid] = observation

    return sorted(
        best.values(),
        key=lambda item: item.signal_percent if item.signal_percent is not None else -1,
        reverse=True,
    )


def _netsh_command() -> list[str] | None:
    """Return a netsh invocation for native Windows or WSL interop."""
    if platform.system() == "Windows":
        return ["netsh", "wlan", "show", "networks", "mode=bssid"]
    if platform.system() == "Linux":
        # The production deployment runs inside WSL; use Windows interop.
        for candidate in (
            "/mnt/c/Windows/System32/netsh.exe",
            "/c/Windows/System32/netsh.exe",
        ):
            if Path(candidate).exists():
                return [candidate, "wlan", "show", "networks", "mode=bssid"]
    return None


def scan_wifi_observations() -> list[WifiObservation]:
    """Enumerate nearby BSSIDs. Returns an empty list when unavailable."""
    global _SCAN_CACHE

    now = time.monotonic()
    if _SCAN_CACHE is not None and now - _SCAN_CACHE[0] < _SCAN_CACHE_TTL:
        return _SCAN_CACHE[1]

    command = _netsh_command()
    if command is None:
        _SCAN_CACHE = (now, [])
        return []

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        logger.debug("[WiFi] scan failed: %s", type(exc).__name__)
        _SCAN_CACHE = (now, [])
        return []

    observations = _parse_netsh_output(_decode_output(completed.stdout or b""))
    _SCAN_CACHE = (now, observations)
    return observations


def build_beacondb_payload(observations: list[WifiObservation]) -> dict[str, Any]:
    access_points = []
    for observation in observations[:_MAX_NETWORKS]:
        entry: dict[str, Any] = {"macAddress": observation.bssid}
        if observation.signal_percent is not None:
            # Percent -> approximate dBm: 100% ~= -50 dBm, 0% ~= -100 dBm.
            entry["signalStrength"] = -100 + int(observation.signal_percent / 2)
        access_points.append(entry)
    return {"wifiAccessPoints": access_points, "considerIp": False}


def parse_beacondb_response(data: dict[str, Any]) -> WifiFix | None:
    location = data.get("location")
    if not isinstance(location, dict):
        return None
    try:
        latitude = float(location["lat"])
        longitude = float(location["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        accuracy = float(data.get("accuracy") or 100.0)
    except (TypeError, ValueError):
        accuracy = 100.0
    return WifiFix(latitude=latitude, longitude=longitude, accuracy_m=accuracy)


async def locate_wifi(observations: list[WifiObservation], timeout: float) -> WifiFix | None:
    """Resolve a coordinate fix from the BSSID set via beaconDB."""
    if len(observations) < 1:
        return None

    payload = build_beacondb_payload(observations)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={"User-Agent": "OpenKitsune/1.0 (spatial-awareness)"},
        ) as client:
            response = await client.post("https://api.beacondb.net/v1/geolocate", json=payload)
    except Exception as exc:
        logger.debug("[WiFi] beaconDB request failed: %s", type(exc).__name__)
        return None

    if response.status_code != 200:
        logger.debug("[WiFi] beaconDB returned %s", response.status_code)
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return parse_beacondb_response(data) if isinstance(data, dict) else None


def parse_reverse_geocode_response(data: dict[str, Any]) -> dict[str, Any] | None:
    city = data.get("city") or data.get("locality")
    region = data.get("principalSubdivision")
    if not city and not region:
        return None
    return {
        "city": city,
        "region": region,
        "country": data.get("countryCode"),
        "country_name": data.get("countryName"),
    }


async def reverse_geocode(
    latitude: float, longitude: float, timeout: float
) -> dict[str, Any] | None:
    """Reverse-geocode a Wi-Fi fix via BigDataCloud (free, no key)."""
    key = f"{latitude:.3f},{longitude:.3f}"
    now = time.monotonic()
    cached = _GEO_CACHE.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={"User-Agent": "OpenKitsune/1.0 (spatial-awareness)"},
        ) as client:
            response = await client.get(
                "https://api.bigdatacloud.net/data/reverse-geocode-client",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "localityLanguage": "zh",
                },
            )
    except Exception as exc:
        logger.debug("[WiFi] reverse geocode failed: %s", type(exc).__name__)
        _GEO_CACHE[key] = (now + 10 * 60, None)
        return None

    if response.status_code != 200:
        _GEO_CACHE[key] = (now + 10 * 60, None)
        return None

    try:
        data = response.json()
    except ValueError:
        _GEO_CACHE[key] = (now + 10 * 60, None)
        return None

    parsed = parse_reverse_geocode_response(data) if isinstance(data, dict) else None
    _GEO_CACHE[key] = (now + _GEO_CACHE_TTL if parsed else now + 10 * 60, parsed)
    return parsed


async def resolve_wifi_fix(timeout: float) -> WifiFix | None:
    """Scan + locate, with short-lived caching so repeated turns stay cheap."""
    observations = scan_wifi_observations()
    if not observations:
        return None

    cache_key = hashlib.sha256(
        "|".join(sorted(observation.bssid for observation in observations)).encode()
    ).hexdigest()
    now = time.monotonic()
    cached = _FIX_CACHE.get(cache_key)
    if cached is not None and now < cached[0]:
        return cached[1]

    fix = await locate_wifi(observations, timeout)
    _FIX_CACHE[cache_key] = (
        now + (_FIX_CACHE_TTL if fix is not None else _FIX_FAILURE_TTL),
        fix,
    )
    if len(_FIX_CACHE) > 8:
        oldest = min(_FIX_CACHE, key=lambda key: _FIX_CACHE[key][0])
        _FIX_CACHE.pop(oldest, None)
    return fix


def clear_wifi_cache() -> None:
    """Drop cached scans/fixes/geocodes (tests and privacy resets)."""
    global _SCAN_CACHE
    _SCAN_CACHE = None
    _FIX_CACHE.clear()
    _GEO_CACHE.clear()
