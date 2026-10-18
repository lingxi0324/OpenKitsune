from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from openkitsune.core import spatial_context as sc
from openkitsune.core.spatial_context import (
    SpatialContext,
    bind_spatial_request,
    clear_spatial_cache,
    extract_public_ip,
    format_spatial_hint,
    is_public_ip,
    normalize_ip,
    reset_spatial_request,
    resolve_current_spatial_context,
    resolve_spatial_context,
)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    from openkitsune.config import settings
    from openkitsune.core.wifi_location import clear_wifi_cache

    async def _no_cn_provider(ip, timeout):
        raise sc.SpatialLookupError("disabled_in_tests")

    clear_spatial_cache()
    clear_wifi_cache()
    monkeypatch.setattr(settings, "spatial_awareness_enabled", True, raising=False)
    monkeypatch.setattr(settings, "spatial_wifi_enabled", False, raising=False)
    monkeypatch.setattr(sc, "_lookup_pconline", _no_cn_provider)
    yield
    clear_spatial_cache()
    clear_wifi_cache()


def _fake_provider(**overrides):
    payload = {
        "provider": "fake",
        "city": "Shanghai",
        "region": "Shanghai",
        "country_code": "CN",
        "country_name": "China",
        "latitude": 31.23,
        "longitude": 121.47,
        "timezone": "Asia/Shanghai",
        "isp": "China Telecom",
        "org": "China Telecom",
        "asn": "AS4134",
        "is_mobile": False,
        "is_proxy_or_vpn": False,
    }
    payload.update(overrides)

    async def provider(ip, timeout):
        return dict(payload)

    return provider


def test_normalize_ip_handles_mapped_ipv6_and_invalid():
    assert normalize_ip("::ffff:8.8.8.8") == "8.8.8.8"
    assert normalize_ip("2001:DB8::1") == "2001:db8::1"
    assert normalize_ip("not-an-ip") is None
    assert normalize_ip("") is None
    assert is_public_ip("8.8.8.8") is True
    assert is_public_ip("127.0.0.1") is False
    assert is_public_ip("192.168.1.2") is False


def test_untrusted_peer_ignores_forwarded_header():
    result = extract_public_ip("8.8.4.4", "1.1.1.1", trusted_proxies="")

    assert result.ip == "8.8.4.4"
    assert result.source == "remote"


def test_trusted_proxy_uses_first_public_forwarded_address():
    result = extract_public_ip(
        "10.0.0.5",
        "1.1.1.1, 10.0.0.9",
        trusted_proxies="10.0.0.0/8",
    )

    assert result.ip == "1.1.1.1"
    assert result.source == "x-forwarded-for"


def test_private_peer_without_trust_is_not_geolocated():
    result = extract_public_ip("192.168.1.20", "8.8.8.8", trusted_proxies="")

    assert result.ip is None
    assert result.reason == "private_ip"


async def test_resolve_spatial_context_fuses_time_and_precision(monkeypatch):
    first = _fake_provider()
    second = _fake_provider(latitude=31.24, longitude=121.48, provider="other")
    monkeypatch.setattr(sc, "_PROVIDERS", (("fake", first), ("other", second)))

    context = await resolve_spatial_context("8.8.8.8")

    assert context is not None
    assert context.status == "ok"
    assert context.city == "Shanghai"
    assert context.precision == "city"
    assert context.accuracy_radius_km == 25.0
    assert context.timezone == "Asia/Shanghai"
    assert context.time_of_day in {"late_night", "morning", "work_hours", "evening"}
    assert context.local_hour is not None
    assert context.providers_agree is True
    # Raw IPs must never leak into the context.
    assert "8.8.8.8" not in str(context.to_dict())


async def test_proxy_or_vpn_degrades_and_clears_geography(monkeypatch):
    monkeypatch.setattr(
        sc,
        "_PROVIDERS",
        (("fake", _fake_provider(is_proxy_or_vpn=True, city="Tokyo")),),
    )

    context = await resolve_spatial_context("8.8.8.8")

    assert context is not None
    assert context.status == "degraded"
    assert context.degraded_reason == "proxy_or_vpn"
    assert context.city is None
    assert context.latitude is None
    assert context.timezone is None


async def test_resolve_without_client_ip_or_fallback_returns_unknown(monkeypatch):
    calls = 0

    async def provider(ip, timeout):
        nonlocal calls
        calls += 1
        return await _fake_provider()(ip, timeout)

    monkeypatch.setattr(sc, "_PROVIDERS", (("fake", provider),))

    context = await resolve_spatial_context("192.168.0.10", allow_host_fallback=False)

    assert context is not None
    assert context.status == "unknown"
    assert context.degraded_reason == "private_ip"
    assert calls == 0


async def test_provider_chain_falls_back_to_second_provider(monkeypatch):
    async def broken(ip, timeout):
        raise sc.SpatialLookupError("boom")

    monkeypatch.setattr(
        sc,
        "_PROVIDERS",
        (("broken", broken), ("fake", _fake_provider(city="Beijing"))),
    )

    context = await resolve_spatial_context("8.8.8.8")

    assert context is not None
    # One surviving provider cannot be cross-checked: city is dropped.
    assert context.status == "degraded"
    assert context.degraded_reason == "single_provider"
    assert context.precision == "country"
    assert context.city is None
    assert context.country == "CN"
    assert context.lookup_provider == "fake"


async def test_cache_avoids_repeated_provider_calls(monkeypatch):
    calls = 0

    async def provider(ip, timeout):
        nonlocal calls
        calls += 1
        return await _fake_provider()(ip, timeout)

    monkeypatch.setattr(sc, "_PROVIDERS", (("fake", provider),))

    first = await resolve_spatial_context("8.8.8.8")
    second = await resolve_spatial_context("8.8.8.8")

    assert first is not None and second is not None
    assert calls == 1
    assert second.status == "degraded"
    assert second.timezone == "Asia/Shanghai"


async def test_failed_lookup_is_cached_as_degraded(monkeypatch):
    calls = 0

    async def broken(ip, timeout):
        nonlocal calls
        calls += 1
        raise sc.SpatialLookupError("timeout")

    monkeypatch.setattr(sc, "_PROVIDERS", (("broken", broken),))

    first = await resolve_spatial_context("8.8.8.8")
    second = await resolve_spatial_context("8.8.8.8")

    assert first is not None and first.status == "degraded"
    assert first.degraded_reason == "lookup_failed"
    assert second is not None and second.status == "degraded"
    assert calls == 1


async def test_context_binding_is_used_by_current_resolver(monkeypatch):
    monkeypatch.setattr(
        sc,
        "_PROVIDERS",
        (("fake", _fake_provider()), ("other", _fake_provider(provider="other"))),
    )
    token = bind_spatial_request("8.8.8.8", allow_host_fallback=False)
    try:
        context = await resolve_current_spatial_context()
    finally:
        reset_spatial_request(token)

    assert context is not None
    assert context.city == "Shanghai"
    assert context.source == "request_ip"


def test_format_spatial_hint_softens_wording():
    context = SpatialContext(
        city="Shanghai",
        region="Shanghai",
        country="CN",
        country_name="China",
        precision="city",
        accuracy_radius_km=25.0,
        timezone="Asia/Shanghai",
        local_time_iso="2026-10-18T20:10:00+08:00",
        local_time_label="夜晚",
        isp="China Telecom",
        status="ok",
    )

    hint = format_spatial_hint(context.to_dict())

    assert "## 空间感知" in hint
    assert "大概" in hint or "附近" in hint
    assert "Shanghai" in hint
    assert "20:10" in hint


def test_format_spatial_hint_omits_untrusted_context():
    assert format_spatial_hint({"status": "degraded", "city": "Tokyo"}) == ""
    assert format_spatial_hint({"status": "unknown"}) == ""


async def test_pconline_cn_result_is_authoritative(monkeypatch):
    async def fake_cn(ip, timeout):
        return {
            "provider": "pconline",
            "city": "泸州市",
            "region": "四川省",
            "country_code": "CN",
            "country_name": "中国",
            "latitude": None,
            "longitude": None,
            "timezone": "Asia/Shanghai",
            "isp": None,
            "org": None,
            "asn": None,
            "is_mobile": None,
            "is_proxy_or_vpn": None,
        }

    async def should_not_run(ip, timeout):
        raise AssertionError("international providers must not override CN result")

    monkeypatch.setattr(sc, "_lookup_pconline", fake_cn)
    monkeypatch.setattr(sc, "_PROVIDERS", (("boom", should_not_run),))

    context = await resolve_spatial_context("117.177.82.15")

    assert context is not None
    assert context.status == "ok"
    assert context.precision == "city"
    assert context.region == "四川省"
    assert context.city == "泸州市"
    assert context.accuracy_source == "cn_specific_database"
    assert context.timezone == "Asia/Shanghai"

    hint = format_spatial_hint(context)
    assert "四川省" in hint
    assert "泸州市" in hint


async def test_pconline_is_skipped_for_ipv6(monkeypatch):
    calls = 0

    async def fake_cn(ip, timeout):
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(sc, "_lookup_pconline", fake_cn)
    monkeypatch.setattr(
        sc,
        "_PROVIDERS",
        (("fake", _fake_provider()), ("other", _fake_provider(provider="other"))),
    )

    context = await resolve_spatial_context("2409:8a62:2013:c0d0::1")

    assert calls == 0
    assert context is not None
    assert context.city == "Shanghai"


async def test_wifi_fix_is_preferred_and_cross_checked(monkeypatch):
    from openkitsune.config import settings
    from openkitsune.core import wifi_location
    from openkitsune.core.wifi_location import WifiFix

    async def fake_cn(ip, timeout):
        return {
            "provider": "pconline",
            "city": "泸州市",
            "region": "四川省",
            "country_code": "CN",
            "country_name": "中国",
            "timezone": "Asia/Shanghai",
        }

    async def fake_fix(timeout):
        return WifiFix(latitude=28.8717, longitude=105.4433, accuracy_m=35.0)

    async def fake_geo(lat, lon, timeout):
        return {"city": "泸州市", "region": "四川省", "country": "CN", "country_name": "中国"}

    monkeypatch.setattr(settings, "spatial_wifi_enabled", True)
    monkeypatch.setattr(sc, "_lookup_pconline", fake_cn)
    monkeypatch.setattr(wifi_location, "resolve_wifi_fix", fake_fix)
    monkeypatch.setattr(wifi_location, "reverse_geocode", fake_geo)

    context = await resolve_spatial_context("117.177.82.15")

    assert context is not None
    assert context.source == "wifi_bssid"
    assert context.precision == "wifi"
    assert context.city == "泸州市"
    assert context.accuracy_radius_km == 0.035
    assert context.providers_agree is True

    hint = format_spatial_hint(context)
    assert "Wi-Fi 指纹定位" in hint
    assert "35 米" in hint
    assert "与 IP 推断一致" in hint


async def test_wifi_conflict_prefers_wifi_over_ip(monkeypatch):
    from openkitsune.config import settings
    from openkitsune.core import wifi_location
    from openkitsune.core.wifi_location import WifiFix

    async def fake_cn(ip, timeout):
        return {
            "provider": "pconline",
            "city": "广州市",
            "region": "广东省",
            "country_code": "CN",
            "country_name": "中国",
            "timezone": "Asia/Shanghai",
        }

    async def fake_fix(timeout):
        return WifiFix(latitude=28.8717, longitude=105.4433, accuracy_m=35.0)

    async def fake_geo(lat, lon, timeout):
        return {"city": "泸州市", "region": "四川省", "country": "CN", "country_name": "中国"}

    monkeypatch.setattr(settings, "spatial_wifi_enabled", True)
    monkeypatch.setattr(sc, "_lookup_pconline", fake_cn)
    monkeypatch.setattr(wifi_location, "resolve_wifi_fix", fake_fix)
    monkeypatch.setattr(wifi_location, "reverse_geocode", fake_geo)

    context = await resolve_spatial_context("8.8.8.8")

    assert context is not None
    assert context.source == "wifi_bssid"
    assert context.city == "泸州市"
    assert context.providers_agree is False
    assert context.degraded_reason == "wifi_ip_conflict"

    hint = format_spatial_hint(context)
    assert "与 IP 推断不一致，已采用 Wi-Fi 结果" in hint


async def test_provider_agreement_keeps_city(monkeypatch):
    first = _fake_provider(city="Shanghai", region="Shanghai")
    second = _fake_provider(
        city="Shanghai",
        region="Shanghai",
        latitude=31.24,
        longitude=121.48,
        provider="other",
    )
    monkeypatch.setattr(sc, "_PROVIDERS", (("a", first), ("b", second)))

    context = await resolve_spatial_context("8.8.8.8")

    assert context is not None
    assert context.status == "ok"
    assert context.precision == "city"
    assert context.city == "Shanghai"
    assert context.providers_agree is True
    assert context.accuracy_source == "cross_checked_city"


async def test_provider_disagreement_downgrades_to_country(monkeypatch):
    beijing = _fake_provider(
        city="Beijing",
        region="Beijing",
        latitude=39.9075,
        longitude=116.3972,
    )
    guangzhou = _fake_provider(
        city="Guangzhou",
        region="Guangdong",
        latitude=23.1317,
        longitude=113.266,
        provider="other",
    )
    monkeypatch.setattr(sc, "_PROVIDERS", (("a", beijing), ("b", guangzhou)))

    context = await resolve_spatial_context("8.8.8.8")

    assert context is not None
    assert context.status == "degraded"
    assert context.degraded_reason == "providers_disagree"
    assert context.precision == "country"
    assert context.city is None
    assert context.region is None
    assert context.providers_agree is False

    hint = format_spatial_hint(context)
    assert "仅能确定到国家" in hint
    assert "Beijing" not in hint
    assert "Guangzhou" not in hint


async def test_manual_location_overrides_ip_lookup(monkeypatch):
    from openkitsune.config import settings

    async def should_not_run(ip, timeout):
        raise AssertionError("manual location must not trigger IP lookup")

    monkeypatch.setattr(settings, "spatial_manual_location", "四川泸州")
    monkeypatch.setattr(sc, "_PROVIDERS", (("boom", should_not_run),))

    context = await resolve_spatial_context("8.8.8.8")

    assert context is not None
    assert context.status == "ok"
    assert context.precision == "manual"
    assert context.city == "四川泸州"
    assert context.source == "manual"

    hint = format_spatial_hint(context)
    assert "用户手动设置" in hint
    assert "可直接使用" in hint
    assert "仅供参考" not in hint


def test_format_spatial_hint_for_country_only_disagreement():
    context = SpatialContext(
        country="CN",
        country_name="China",
        precision="country",
        status="degraded",
        degraded_reason="providers_disagree",
        providers_agree=False,
        timezone="Asia/Shanghai",
        local_time_iso="2026-10-18T20:10:00+08:00",
        local_time_label="夜晚",
    )

    hint = format_spatial_hint(context)

    assert "仅能确定到国家" in hint
    assert "当地时间" in hint
    assert "不要推断省份或城市" in hint


def test_local_time_is_derived_from_reported_timezone():
    before = datetime.now(ZoneInfo("Asia/Shanghai")).hour
    context = sc._build_context(_fake_provider_payload())
    after = datetime.now(ZoneInfo("Asia/Shanghai")).hour

    assert context.timezone == "Asia/Shanghai"
    assert context.local_hour in {before, after}


def _fake_provider_payload():
    return {
        "provider": "fake",
        "city": "Shanghai",
        "region": "Shanghai",
        "country_code": "CN",
        "country_name": "China",
        "latitude": 31.23,
        "longitude": 121.47,
        "timezone": "Asia/Shanghai",
        "isp": "China Telecom",
        "org": "China Telecom",
        "asn": "AS4134",
        "is_mobile": False,
        "is_proxy_or_vpn": False,
    }
