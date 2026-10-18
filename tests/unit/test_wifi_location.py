from openkitsune.core.wifi_location import (
    WifiObservation,
    _parse_netsh_output,
    build_beacondb_payload,
    parse_beacondb_response,
    parse_reverse_geocode_response,
)


def test_netsh_command_uses_windows_binary_in_wsl(monkeypatch):
    import openkitsune.core.wifi_location as wl

    monkeypatch.setattr(wl.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wl.Path, "exists", lambda self: "netsh.exe" in str(self).lower())

    command = wl._netsh_command()

    assert command is not None
    assert command[0].endswith("netsh.exe")


def test_netsh_command_none_without_windows_interop(monkeypatch):
    import openkitsune.core.wifi_location as wl

    monkeypatch.setattr(wl.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wl.Path, "exists", lambda self: False)

    assert wl._netsh_command() is None


def test_parse_netsh_output_english():
    output = """
SSID 1 : HomeWiFi
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    BSSID 1                 : AA:BB:CC:DD:EE:01
         Signal             : 78%
    BSSID 2                 : aa:bb:cc:dd:ee:02
         Signal             : 42%
SSID 2 : Neighbor
    BSSID 1                 : aa:bb:cc:dd:ee:03
         Signal             : 91%
"""

    observations = _parse_netsh_output(output)

    assert [item.bssid for item in observations] == [
        "aa:bb:cc:dd:ee:03",
        "aa:bb:cc:dd:ee:01",
        "aa:bb:cc:dd:ee:02",
    ]
    assert observations[1].signal_percent == 78


def test_parse_netsh_output_chinese():
    output = """
SSID 1 : 家里
    BSSID 1                 : aa:bb:cc:dd:ee:11
         信号             : 65%
"""

    observations = _parse_netsh_output(output)

    assert len(observations) == 1
    assert observations[0].bssid == "aa:bb:cc:dd:ee:11"
    assert observations[0].signal_percent == 65


def test_parse_netsh_output_deduplicates_bssid():
    output = """
    BSSID 1                 : aa:bb:cc:dd:ee:01
         Signal             : 20%
    BSSID 1                 : aa:bb:cc:dd:ee:01
         Signal             : 80%
"""

    observations = _parse_netsh_output(output)

    assert len(observations) == 1
    assert observations[0].signal_percent == 80


def test_beacondb_payload_converts_signal_percent():
    payload = build_beacondb_payload(
        [
            WifiObservation("aa:bb:cc:dd:ee:01", 100),
            WifiObservation("aa:bb:cc:dd:ee:02", 50),
            WifiObservation("aa:bb:cc:dd:ee:03", None),
        ]
    )

    points = payload["wifiAccessPoints"]
    assert payload["considerIp"] is False
    assert points[0]["signalStrength"] == -50
    assert points[1]["signalStrength"] == -75
    assert "signalStrength" not in points[2]


def test_parse_beacondb_response():
    fix = parse_beacondb_response({"location": {"lat": 28.8717, "lng": 105.4433}, "accuracy": 35.0})

    assert fix is not None
    assert fix.latitude == 28.8717
    assert fix.longitude == 105.4433
    assert fix.accuracy_m == 35.0


def test_parse_beacondb_error_payload():
    assert parse_beacondb_response({"error": {"code": 404}}) is None


def test_parse_reverse_geocode_response():
    geo = parse_reverse_geocode_response(
        {
            "city": "泸州市",
            "locality": "江阳区",
            "principalSubdivision": "四川省",
            "countryCode": "CN",
            "countryName": "中华人民共和国",
        }
    )

    assert geo == {
        "city": "泸州市",
        "region": "四川省",
        "country": "CN",
        "country_name": "中华人民共和国",
    }


def test_parse_reverse_geocode_requires_city_or_region():
    assert parse_reverse_geocode_response({"countryCode": "CN"}) is None
