"""Buttons of the Micronova device."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .aguaiot import AguaIOTError
from .clock import clock_values, has_clock
from .const import BUTTONS, DOMAIN, translation_key

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = config_entry.runtime_data
    agua = coordinator.agua

    buttons = []
    for device in agua.devices:
        if has_clock(device.registers):
            buttons.append(AguaIOTSyncClockButton(coordinator, device))
        for button in BUTTONS:
            # The enable register depends on the stove state, so it drives
            # availability instead of creation.
            if button.key in device.registers:
                buttons.append(AguaIOTHeatingButton(coordinator, device, button))

    async_add_entities(buttons, True)


def _device_info(device) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, device.id_device)},
        name=device.name,
        manufacturer="Micronova",
        model=device.name_product,
    )


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
        return _device_info(self._device)

    async def async_press(self) -> None:
        try:
            await self._device.set_register_values(
                clock_values(dt_util.now()), limit_value_raw=True
            )
        except (ValueError, AguaIOTError) as err:
            _LOGGER.error("Failed to set the device clock, error: %s", err)
            return
        await self.coordinator.async_request_refresh()


class AguaIOTHeatingButton(CoordinatorEntity, ButtonEntity):
    """Button entity driven by a register (for example the alarm reset)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device, description):
        """Initialize the button."""
        super().__init__(coordinator)
        self._device = device
        self.entity_description = description
        self._attr_translation_key = translation_key(description)

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self._device.id_device}_{self.entity_description.key}"

    @property
    def device_info(self):
        """Return the device info."""
        return _device_info(self._device)

    @property
    def available(self):
        """Only available when the stove accepts the command."""
        key = self.entity_description.key
        # Without a read value the stove state, and so the enable state, is unknown
        return (
            super().available
            and self._device.get_register_value(key) is not None
            and self._device.get_register_enabled(key)
        )

    async def async_press(self):
        """Press the button."""
        try:
            await self._device.set_register_value(self.entity_description.key, 0)
            await self.coordinator.async_request_refresh()
        except AguaIOTError as err:
            _LOGGER.error(
                "Failed to press '%s', error: %s",
                f"{self._device.name} {self.entity_description.name}",
                err,
            )
