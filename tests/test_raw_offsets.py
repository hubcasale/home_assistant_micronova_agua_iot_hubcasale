"""The raw read of the stove (every offset, mapped or not) is kept and exported in the diagnostics."""

from unittest.mock import MagicMock

import pytest

from tests.helpers import build_device_from_fixture, load_component_module

REGISTER_MAP = {
    "temp_get": {
        "reg_key": "temp_get",
        "reg_type": "GET",
        "offset": 10,
        "mask": 255,
        "formula": "#",
        "set_min": 0,
        "set_max": 100,
    }
}


def test_device_keeps_a_copy_of_the_raw_read(aguaiot_mock):
    device = build_device_from_fixture(aguaiot_mock, "test", REGISTER_MAP)
    raw = {10: 55, 129: 1, 33134: 0}
    device.apply_raw_data(raw)
    assert device.raw_data == raw
    raw[10] = 0
    assert device.raw_data[10] == 55  # copy of the input
    device.raw_data[10] = 1
    assert device.raw_data[10] == 55  # and the property returns a copy too


@pytest.mark.asyncio
async def test_diagnostics_export_raw_offsets_with_string_keys(aguaiot_mock):
    diagnostics = load_component_module("diagnostics")
    device = build_device_from_fixture(aguaiot_mock, "test", REGISTER_MAP)
    device.apply_raw_data({33134: 0, 10: 55, 129: 1})
    entry = MagicMock()
    entry.runtime_data.agua.devices = [device]
    entry.as_dict.return_value = {"data": {}, "options": {}}
    result = await diagnostics.async_get_config_entry_diagnostics(MagicMock(), entry)
    raw = result["raw_offsets"][device.name]
    assert raw == {"10": 55, "129": 1, "33134": 0}
    assert list(raw) == ["10", "129", "33134"]  # in offset order
