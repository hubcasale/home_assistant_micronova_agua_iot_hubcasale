"""Clock of Micronova devices (hour, minute and calendar date registers).

The device keeps its own clock, used by the weekly chrono programs. The registers
``clock_hour_set``, ``clock_minute_set``, ``calendar_day_set``, ``calendar_month_set``
and ``calendar_year_set`` hold the clock as the device reports it, so the drift against
Home Assistant's time can be measured and corrected.

This module has no Home Assistant dependency so it can be unit tested alone.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

CLOCK_KEYS = (
    "clock_hour_set",
    "clock_minute_set",
    "calendar_day_set",
    "calendar_month_set",
    "calendar_year_set",
)


def has_clock(registers) -> bool:
    """True when the device exposes all clock registers."""
    return all(key in registers for key in CLOCK_KEYS)


def read_device_clock(get_value: Callable[[str], object], tzinfo) -> datetime | None:
    """Device clock as an aware datetime in ``tzinfo`` (None if unreadable or invalid).

    ``get_value`` returns the value of a register by key (``Device.get_register_value``).
    The device stores local time, so it is interpreted in the given time zone.
    """
    try:
        hour, minute, day, month, year = (int(get_value(key)) for key in CLOCK_KEYS)
        return datetime(year, month, day, hour, minute, tzinfo=tzinfo)
    except (TypeError, ValueError):
        return None


def clock_offset_minutes(device_clock: datetime | None, now: datetime) -> int | None:
    """Minutes the device clock is ahead of ``now`` (negative = behind), None if unknown."""
    if device_clock is None:
        return None
    return round((device_clock - now).total_seconds() / 60)


def clock_values(now: datetime) -> dict[str, int]:
    """Register values that set the device clock to ``now``."""
    return {
        "clock_hour_set": now.hour,
        "clock_minute_set": now.minute,
        "calendar_day_set": now.day,
        "calendar_month_set": now.month,
        "calendar_year_set": now.year,
    }
