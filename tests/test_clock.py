"""Tests of the device clock helpers (no Home Assistant needed)."""

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

from tests.helpers import build_device_from_fixture

_CLOCK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "aguaiot_hubcasale", "clock.py"
)
_spec = importlib.util.spec_from_file_location("aguaiot_clock", _CLOCK_PATH)
clock = importlib.util.module_from_spec(_spec)
sys.modules["aguaiot_clock"] = clock
_spec.loader.exec_module(clock)

CLOCK_KEYS = clock.CLOCK_KEYS
clock_offset_minutes = clock.clock_offset_minutes
clock_values = clock.clock_values
has_clock = clock.has_clock
read_device_clock = clock.read_device_clock

TZ = timezone(timedelta(hours=2))


def getter(values):
    return lambda key: values[key]


def values(hour, minute, day=4, month=10, year=2026):
    return {
        "clock_hour_set": hour,
        "clock_minute_set": minute,
        "calendar_day_set": day,
        "calendar_month_set": month,
        "calendar_year_set": year,
    }


def test_read_clock():
    dev = read_device_clock(getter(values(12, 13)), TZ)
    assert dev == datetime(2026, 10, 4, 12, 13, tzinfo=TZ)


def test_read_clock_invalid_date_is_none():
    assert read_device_clock(getter(values(12, 13, day=31, month=2)), TZ) is None


def test_read_clock_missing_value_is_none():
    bad = values(12, 13)
    bad["clock_minute_set"] = None
    assert read_device_clock(getter(bad), TZ) is None


def test_offset_ahead_and_behind():
    now = datetime(2026, 10, 4, 12, 0, tzinfo=TZ)
    assert clock_offset_minutes(datetime(2026, 10, 4, 12, 13, tzinfo=TZ), now) == 13
    assert clock_offset_minutes(datetime(2026, 10, 4, 11, 55, tzinfo=TZ), now) == -5
    assert clock_offset_minutes(now, now) == 0
    assert clock_offset_minutes(None, now) is None


def test_offset_across_midnight():
    now = datetime(2026, 10, 5, 0, 5, tzinfo=TZ)
    assert clock_offset_minutes(datetime(2026, 10, 4, 23, 58, tzinfo=TZ), now) == -7


def test_clock_values_cover_all_registers():
    now = datetime(2026, 10, 4, 12, 7, tzinfo=TZ)
    vals = clock_values(now)
    assert set(vals) == set(CLOCK_KEYS)
    assert vals == values(12, 7)


def test_has_clock():
    assert has_clock({k: {} for k in CLOCK_KEYS}) is True
    assert has_clock({"clock_hour_set": {}}) is False


def test_fixture_nobis_polygon_has_a_readable_clock(fixture_data, aguaiot_mock):
    reg_map = fixture_data["nobis_polygon"]
    assert has_clock(reg_map)
    device = build_device_from_fixture(aguaiot_mock, "nobis_polygon", reg_map)
    dev = read_device_clock(device.get_register_value, TZ)
    assert dev is not None
    assert dev.year == 2026 and dev.month == 10
