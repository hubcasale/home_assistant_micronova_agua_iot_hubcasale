"""The raw read of the stove (every offset, mapped or not) is kept and exported in the diagnostics."""

from unittest.mock import MagicMock

import pytest

from tests.helpers import build_device_from_fixture, load_component_module
from tests.test_write_guard import real_ble_class


def read_offsets_with_session():
    """The probe function of the Bluetooth module, loaded without the host Bluetooth stack."""
    return real_ble_class().read_offsets.__globals__["read_offsets_with_session"]


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


class FakeSession:
    """Answers RequestReading like the stove: Items and Values, or an error for some chunks."""

    def __init__(self, fail_from=None, bad_answer=False):
        self.commands = []
        self.fail_from = fail_from
        self.bad_answer = bad_answer

    async def exchange(self, command):
        self.commands.append(command)
        items = command["pl"]["Items"]
        if self.fail_from is not None and items[0] >= self.fail_from:
            raise TimeoutError("no answer")
        if self.bad_answer:
            return {"pl": {"Items": items}}
        return {"pl": {"Items": items, "Values": [i % 7 for i in items]}}


@pytest.mark.asyncio
async def test_read_offsets_chunks_and_collects_values():
    probe = read_offsets_with_session()
    session = FakeSession()
    make = lambda payload: {"pl": payload}
    offsets = list(
        range(33100, 33100 + 2 * 60, 2)
    )  # 60 offsets: 3 requests of 24, 24, 12
    values, errors = await probe(session, make, offsets, True)
    assert errors == []
    assert len(session.commands) == 3
    first = session.commands[0]["pl"]
    assert first["Cmd"] == "RequestReading"
    assert (
        first["BitData"] == [16] * 24
        and first["Masks"] == [65535] * 24
        and first["Endianess"] == ["L"] * 24
    )
    assert values[33100] == 33100 % 7 and len(values) == 60


@pytest.mark.asyncio
async def test_read_offsets_single_bytes_use_8_bit_data():
    probe = read_offsets_with_session()
    session = FakeSession()
    await probe(session, lambda p: {"pl": p}, [10, 11], False)
    assert session.commands[0]["pl"]["BitData"] == [8, 8]


@pytest.mark.asyncio
async def test_read_offsets_reports_failed_chunks_and_keeps_going():
    probe = read_offsets_with_session()
    session = FakeSession(fail_from=124)
    offsets = list(range(100, 100 + 48))  # two chunks: 100-123 ok, 124-147 times out
    values, errors = await probe(session, lambda p: {"pl": p}, offsets, True)
    assert sorted(values) == list(range(100, 124))
    assert (
        len(errors) == 1
        and "TimeoutError" in errors[0]
        and errors[0].startswith("124-147")
    )


@pytest.mark.asyncio
async def test_read_offsets_unexpected_answer_is_an_error():
    probe = read_offsets_with_session()
    values, errors = await probe(
        FakeSession(bad_answer=True), lambda p: {"pl": p}, [10, 12], True
    )
    assert values == {}
    assert len(errors) == 1 and "unexpected answer" in errors[0]
