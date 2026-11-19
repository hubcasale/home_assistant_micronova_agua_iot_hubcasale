from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

TO_REDACT = {
    CONF_PASSWORD,
    CONF_EMAIL,
    "mqtt_settings",
    "reg_code",
    "security_code",
    "assistance_code",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = config_entry.runtime_data
    agua = coordinator.agua

    devices = {}
    for device in agua.devices:
        devices[device.name] = {}
        for reg in device.registers:
            devices[device.name][reg] = device.get_register(reg)

    # Every offset the stove returned in the last read, mapped or not (compare two downloads to find the offset of a
    # setting the register map does not list, see tools/diff_raw_offsets.py).
    raw_offsets = {
        device.name: {
            str(offset): value for offset, value in sorted(device.raw_data.items())
        }
        for device in agua.devices
    }

    return {
        "entry": async_redact_data(config_entry.as_dict(), TO_REDACT),
        "devices": devices,
        "raw_offsets": raw_offsets,
    }
