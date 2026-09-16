from config_flow import _parse_devices


def test_parse_devices_normalizes_valid_entries():
    devices, invalid = _parse_devices(
        "aa-bb-cc-dd-ee-ff=Desk\n11:22:33:44:55:66=NAS\n"
    )

    assert devices == {
        "AA:BB:CC:DD:EE:FF": "Desk",
        "11:22:33:44:55:66": "NAS",
    }
    assert invalid == []


def test_parse_devices_rejects_invalid_and_duplicate_macs():
    devices, invalid = _parse_devices(
        "AA:BB:CC:DD:EE:FF=Desk\n"
        "AA:BB:CC:DD:EE:FF=Other\n"
        "bad-line\n"
        "12:34:56=Broken\n"
    )

    assert devices == {"AA:BB:CC:DD:EE:FF": "Desk"}
    assert invalid == [
        "AA:BB:CC:DD:EE:FF=Other",
        "bad-line",
        "12:34:56=Broken",
    ]
