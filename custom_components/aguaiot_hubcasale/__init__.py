"""Support for Micronova Agua IOT heating devices."""

import asyncio
import json
import re

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .coordinator import AguaIOTDataUpdateCoordinator

MAX_PROBE_OFFSETS = 800

READ_OFFSETS_SCHEMA = vol.Schema(
    {
        vol.Optional("start", default=0): vol.All(int, vol.Range(min=0, max=65535)),
        vol.Optional("stop", default=0): vol.All(int, vol.Range(min=0, max=65535)),
        vol.Optional("step", default=2): vol.All(int, vol.Range(min=1, max=64)),
        vol.Optional("word", default=True): bool,
        vol.Optional("offsets"): [vol.All(int, vol.Range(min=0, max=65535))],
        # the result is also saved as <config>/aguaiot_probe_<label>.json
        vol.Optional("label", default="probe"): str,
    }
)


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1)


async def _async_read_offsets(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Read arbitrary offsets over Bluetooth (read-only probe)."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise ServiceValidationError("Micronova Agua IOT is not loaded")
    agua = entries[0].runtime_data.agua
    if not hasattr(agua, "read_offsets") or not agua.devices:
        raise ServiceValidationError(
            "Reading offsets needs the Bluetooth connection mode"
        )
    offsets = call.data.get("offsets") or list(
        range(call.data["start"], call.data["stop"] + 1, call.data["step"])
    )
    if not offsets or len(offsets) > MAX_PROBE_OFFSETS:
        raise ServiceValidationError(f"Ask for 1 to {MAX_PROBE_OFFSETS} offsets")
    device = agua.devices[0]
    values, errors = await agua.read_offsets(device, offsets, call.data["word"])
    result = {
        "device": device.name,
        "word": call.data["word"],
        "asked": len(offsets),
        "values": {str(o): v for o, v in sorted(values.items())},
        "errors": errors,
    }
    label = re.sub(r"[^A-Za-z0-9_-]+", "_", call.data["label"]) or "probe"
    path = hass.config.path(f"aguaiot_probe_{label}.json")
    await hass.async_add_executor_job(_write_json, path, result)
    return result


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the AguaIOT integration."""

    async def read_offsets(call: ServiceCall) -> ServiceResponse:
        return await _async_read_offsets(hass, call)

    hass.services.async_register(
        DOMAIN,
        "read_offsets",
        read_offsets,
        schema=READ_OFFSETS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    if DOMAIN in config:
        for entry_config in config[DOMAIN]:
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_IMPORT}, data=entry_config
                )
            )

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up AguaIOT entry."""
    coordinator = AguaIOTDataUpdateCoordinator(
        hass=hass,
        config_entry=config_entry,
    )
    config_entry.runtime_data = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    except (Exception, asyncio.CancelledError):
        # HA may retry setup with a new coordinator. Release this attempt's client.
        if hasattr(coordinator.agua, "close"):
            await coordinator.agua.close()
        raise

    # Services
    async def async_close_connection(event: Event) -> None:
        """Close AguaIOT connection on HA Stop."""
        if hasattr(coordinator.agua, "close"):
            await coordinator.agua.close()

    config_entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_close_connection)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    if unload_ok:
        coordinator: AguaIOTDataUpdateCoordinator = config_entry.runtime_data
        if hasattr(coordinator.agua, "close"):
            await coordinator.agua.close()
    return unload_ok
