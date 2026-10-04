"""Buttons of the Micronova device."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .aguaiot import AguaIOTError
from .clock import clock_values, has_clock
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = config_entry.runtime_data
    agua = coordinator.agua

    buttons = [
        AguaIOTSyncClockButton(coordinator, device)
        for device in agua.devices
        if has_clock(device.registers)
    ]
    async_add_entities(buttons, True)


class AguaIOTSyncClockButton(CoordinatorEntity, ButtonEntity):
    """Set the device clock to Home Assistant's time."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync_clock"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator, device):
        super().__init__(coordinator)
        self._device = device

    @property
    def unique_id(self):
        return f"{self._device.id_device}_sync_clock"

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.id_device)},
            name=self._device.name,
            manufacturer="Micronova",
            model=self._device.name_product,
        )

    async def async_press(self) -> None:
        try:
            await self._device.set_register_values(
                clock_values(dt_util.now()), limit_value_raw=True
            )
        except (ValueError, AguaIOTError) as err:
            _LOGGER.error("Failed to set the device clock, error: %s", err)
            return
        await self.coordinator.async_request_refresh()
