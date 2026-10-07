"""Support for Agua IOT heating devices."""

import copy
import logging
import numbers
import re

import voluptuous as vol
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    UnitOfTemperature,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)
from homeassistant.util import dt

from .aguaiot import AguaIOTError
from .clock import clock_values
from .chrono import (
    CHRONO_DAYS,
    CHRONO_PROGRAMS,
    CHRONO_WEEK_ENABLE_KEY,
    build_program_items,
)
from .const import (
    AIR_VARIANTS,
    CLIMATE_CANALIZATIONS,
    DOMAIN,
    MODE_PELLETS,
    MODE_WOOD,
    STATUS_IDLE,
    STATUS_OFF,
    WATER_VARIANTS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = config_entry.runtime_data
    agua = coordinator.agua

    entities = []
    for device in agua.devices:
        stove = AguaIOTAirDevice(coordinator, device)
        if stove.has_power_levels:
            entities.append(stove)
        else:
            # hydronic stoves without a power-level register (e.g. Polygon): the air thermostat cannot list
            # its fan modes and adding it fails on every start. The water thermostat only needs the object.
            _LOGGER.debug(
                "Skipping the air thermostat of %s: no power register with a range", device.name
            )

        if any(f"temp_{variant}_set" in device.registers for variant in WATER_VARIANTS):
            entities.append(AguaIOTWaterDevice(coordinator, device, stove))

        for canalization in CLIMATE_CANALIZATIONS:
            for c_found in [
                m
                for i in device.registers
                for m in [re.match(canalization.key, i.lower())]
                if m
            ]:
                if (
                    (
                        canalization.key_enable
                        and device.get_register_enabled(
                            canalization.key_enable.format(id=c_found.group(1))
                        )
                    )
                    or (
                        canalization.key2_enable
                        and device.get_register_enabled(
                            canalization.key2_enable.format(id=c_found.group(1))
                        )
                    )
                    or (
                        not canalization.key_enable
                        and device.get_register_enabled(c_found.group(0))
                    )
                ):
                    c_copy = copy.deepcopy(canalization)
                    c_copy.key = c_found.group(0)
                    for key in [
                        "name",
                        "key_temp_set",
                        "key_temp_get",
                        "key_temp2_get",
                        "key_vent_set",
                    ]:
                        if getattr(c_copy, key):
                            setattr(
                                c_copy,
                                key,
                                getattr(c_copy, key).format_map(c_found.groupdict()),
                            )

                    entities.append(
                        AguaIOTCanalizationDevice(coordinator, device, c_copy, stove)
                    )

    async_add_entities(entities, True)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "sync_clock",
        {},
        "sync_clock",
    )
    platform.async_register_entity_service(
        "set_chrono_program",
        {
            vol.Required("program"): vol.All(
                vol.Coerce(int), vol.In(CHRONO_PROGRAMS)
            ),
            vol.Optional("start"): cv.time,
            vol.Optional("stop"): cv.time,
            vol.Optional("days"): vol.All(cv.ensure_list, [vol.In(CHRONO_DAYS)]),
            vol.Optional("water_temperature"): vol.Coerce(float),
            vol.Optional("boiler_temperature"): vol.Coerce(float),
            vol.Optional("acs"): cv.boolean,
            vol.Optional("weekly_enabled"): cv.boolean,
        },
        "set_chrono_program",
    )


class AguaIOTClimateDevice(CoordinatorEntity, ClimateEntity):
    @property
    def device_info(self):
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.id_device)},
            name=self._device.name,
            manufacturer="Micronova",
            model=self._device.name_product,
        )

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def precision(self):
        """Return the precision of the system."""
        return PRECISION_HALVES

    async def set_chrono_program(
        self,
        program,
        start=None,
        stop=None,
        days=None,
        water_temperature=None,
        boiler_temperature=None,
        acs=None,
        weekly_enabled=None,
    ):
        """Program one weekly chrono program (all values in a single request)."""
        items = build_program_items(
            program,
            start=start,
            stop=stop,
            days=days,
            water_temperature=water_temperature,
            boiler_temperature=boiler_temperature,
            acs=acs,
        )
        if weekly_enabled is not None:
            items[CHRONO_WEEK_ENABLE_KEY] = 1 if weekly_enabled else 0

        if not items:
            raise ServiceValidationError("No value to set")

        missing = [key for key in items if key not in self._device.registers]
        if missing:
            raise ServiceValidationError(
                f"This device does not support: {', '.join(sorted(missing))}"
            )

        try:
            await self._device.set_register_values(items)
            await self.coordinator.async_request_refresh()
        except (ValueError, AguaIOTError) as err:
            raise ServiceValidationError(
                f"Failed to set chrono program {program}: {err}"
            ) from err


class AguaIOTAirDevice(AguaIOTClimateDevice):
    """Representation of an Agua IOT heating device."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator, device):
        """Initialize the thermostat."""
        super().__init__(coordinator)
        self._enable_turn_on_off_backwards_compatibility = False
        self._device = device
        self._hybrid = "power_wood_set" in device.registers

        self._temperature_get_key = None
        for variant in AIR_VARIANTS:
            if (
                f"temp_{variant}_get" in self._device.registers
                and self._device.get_register_enabled(f"temp_{variant}_get")
                and self._device.get_register_value(f"temp_{variant}_get")
            ):
                self._temperature_get_key = f"temp_{variant}_get"
                break

        self._temperature_set_key = None
        for variant in AIR_VARIANTS:
            if (
                f"temp_{variant}_set" in self._device.registers
                and self._device.get_register_enabled(f"temp_{variant}_set")
                and self._device.get_register_value(f"temp_{variant}_set")
            ):
                self._temperature_set_key = f"temp_{variant}_set"
                break

    def _status_description_upper(self):
        """Return the current status description in a normalized uppercase form."""
        status_value = self._device.get_register_value("status_get")
        if status_value is None:
            return None

        description = self._device.get_register_value_description(
            key="status_get", language="ENG"
        )
        if description is None:
            return None

        return str(description).strip().upper()

    def _is_alarm_like_status(self):
        """Return True for Micronova alarm/manual-alarm style states."""
        description = self._status_description_upper()
        if description is None:
            return False

        return "ALARM" in description or "ALLARM" in description

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._device.id_device

    @property
    def supported_features(self):
        """Return the list of supported features."""
        features = (
            ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
        )
        if self._hybrid:
            features = features | ClimateEntityFeature.PRESET_MODE
        return features

    @property
    def hvac_action(self):
        """Return the current running hvac operation."""
        status_value = self._device.get_register_value("status_get")
        if status_value is not None:
            description = self._status_description_upper()
            if self._is_alarm_like_status():
                return HVACAction.OFF
            if description in STATUS_IDLE:
                return HVACAction.IDLE
            elif status_value == 0 or description in STATUS_OFF:
                return HVACAction.OFF
            return HVACAction.HEATING

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes."""
        return [HVACMode.HEAT, HVACMode.OFF]

    @property
    def hvac_mode(self):
        """Return hvac operation ie. heat, cool mode."""
        status_value = self._device.get_register_value("status_get")
        if status_value is not None:
            description = self._status_description_upper()
            if (
                self._is_alarm_like_status()
                or status_value == 0
                or description in STATUS_OFF
            ):
                return HVACMode.OFF
            return HVACMode.HEAT

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        elif hvac_mode == HVACMode.HEAT:
            await self.async_turn_on()

    @property
    def hybrid_mode(self):
        return (
            MODE_WOOD
            if self._hybrid and self._device.get_register_enabled("real_power_wood_get")
            else MODE_PELLETS
        )

    @property
    def fan_mode(self):
        """Return fan mode."""
        power_register = (
            "power_wood_set" if self.hybrid_mode == MODE_WOOD else "power_set"
        )
        return str(self._device.get_register_value_description(power_register))

    @property
    def has_power_levels(self):
        """True if the power register has a range, so fan modes can be listed."""
        power_register = (
            "power_wood_set" if self.hybrid_mode == MODE_WOOD else "power_set"
        )
        return self._device.has_register_range(power_register)

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        if not self.has_power_levels:
            return []
        fan_modes = []
        power_register = (
            "power_wood_set" if self.hybrid_mode == MODE_WOOD else "power_set"
        )
        for x in range(
            self._device.get_register_value_min(power_register),
            (self._device.get_register_value_max(power_register) + 1),
        ):
            fan_modes.append(
                str(self._device.get_register_value_options(power_register).get(x, x))
            )
        return fan_modes

    @property
    def preset_modes(self):
        return [self.hybrid_mode]

    @property
    def preset_mode(self):
        return self.hybrid_mode

    async def async_set_preset_mode(self, preset_mode):
        # The stove will pick the correct mode.
        pass

    async def async_turn_off(self):
        """Turn device off."""
        try:
            await self._device.set_register_value_description(
                key="status_managed_get",
                value_description="OFF",
                value_fallback=170,
                language="ENG",
            )
            await self.coordinator.async_request_refresh()
        except AguaIOTError as err:
            _LOGGER.error("Failed to turn off device, error: %s", err)

    async def async_turn_on(self):
        """Turn device on."""
        try:
            await self._device.set_register_value_description(
                key="status_managed_get",
                value_description="ON",
                value_fallback=85,
                language="ENG",
            )
            await self.coordinator.async_request_refresh()
        except AguaIOTError as err:
            _LOGGER.error("Failed to turn on device, error: %s", err)

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        power_register = (
            "power_wood_set" if self.hybrid_mode == MODE_WOOD else "power_set"
        )
        try:
            await self._device.set_register_value_description(power_register, fan_mode)
            await self.coordinator.async_request_refresh()
        except AguaIOTError as err:
            _LOGGER.error("Failed to set fan mode, error: %s", err)

    @property
    def min_temp(self):
        """Return the minimum temperature to set."""
        return self._device.get_register_value_min(self._temperature_set_key)

    @property
    def max_temp(self):
        """Return the maximum temperature to set."""
        return self._device.get_register_value_max(self._temperature_set_key)

    @property
    def current_temperature(self):
        """Return the current temperature."""
        if self._temperature_get_key:
            value = self._device.get_register_value_description(
                self._temperature_get_key
            )
            if isinstance(value, numbers.Number):
                return value

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        if self.current_temperature:
            return self._device.get_register_value(self._temperature_set_key)

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        try:
            await self._device.set_register_value(
                self._temperature_set_key, temperature
            )
            await self.coordinator.async_request_refresh()
        except (ValueError, AguaIOTError) as err:
            _LOGGER.error("Failed to set temperature, error: %s", err)

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return self._device.get_register(self._temperature_set_key).get("step", 1)

    async def sync_clock(self):
        try:
            await self._device.set_register_values(
                clock_values(dt.now()),
                limit_value_raw=True,
            )
        except (ValueError, AguaIOTError) as err:
            _LOGGER.error("Failed to set value, error: %s", err)


class AguaIOTWaterDevice(AguaIOTClimateDevice):
    """Representation of an Agua IOT heating device."""

    _attr_has_entity_name = True
    _attr_translation_key = "water"
    _attr_icon = "mdi:water"

    def __init__(self, coordinator, device, parent):
        """Initialize the thermostat."""
        super().__init__(coordinator)
        self._enable_turn_on_off_backwards_compatibility = False
        self._device = device
        self._parent = parent

        # Le chiavi dei registri si risolvono quando servono (e si memorizzano appena un registro ha un valore):
        # leggerle una sola volta all'avvio le lasciava vuote se la caldaia era spenta o il cloud non rispondeva,
        # e allora min_temp/max_temp tornavano None e climate.set_temperature falliva.
        self._temperature_get_key_cache = None
        self._temperature_set_key_cache = None

    def _resolve_water_key(self, kind):
        """Registro 'temp_<variante>_<kind>': quello con un valore (memorizzato), altrimenti il primo abilitato."""
        cached = getattr(self, f"_temperature_{kind}_key_cache")
        if cached:
            return cached
        key, has_value = self._device.find_variant_register(
            WATER_VARIANTS, f"temp_{{}}_{kind}"
        )
        if has_value:
            setattr(self, f"_temperature_{kind}_key_cache", key)
        return key

    @property
    def _temperature_get_key(self):
        return self._resolve_water_key("get")

    @property
    def _temperature_set_key(self):
        return self._resolve_water_key("set")

    @property
    def unique_id(self):
        return f"{self._device.id_device}_water"

    @property
    def supported_features(self):
        """Return the list of supported features."""
        features = (
            ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TARGET_TEMPERATURE
        )
        return features

    @property
    def hvac_action(self):
        return self._parent.hvac_action

    @property
    def hvac_modes(self):
        return self._parent.hvac_modes

    @property
    def hvac_mode(self):
        return self._parent.hvac_mode

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        elif hvac_mode == HVACMode.HEAT:
            await self.async_turn_on()

    async def async_turn_off(self):
        """Turn device off."""
        try:
            await self._device.set_register_value_description(
                key="status_managed_get",
                value_description="OFF",
                value_fallback=170,
                language="ENG",
            )
            await self.coordinator.async_request_refresh()
        except AguaIOTError as err:
            _LOGGER.error("Failed to turn off device, error: %s", err)

    async def async_turn_on(self):
        """Turn device on."""
        try:
            await self._device.set_register_value_description(
                key="status_managed_get",
                value_description="ON",
                value_fallback=85,
                language="ENG",
            )
            await self.coordinator.async_request_refresh()
        except AguaIOTError as err:
            _LOGGER.error("Failed to turn on device, error: %s", err)

    @property
    def min_temp(self):
        """Return the minimum temperature to set."""
        key = self._temperature_set_key
        value = self._device.get_register_value_min(key) if key else None
        return value if value is not None else 30

    @property
    def max_temp(self):
        """Return the maximum temperature to set."""
        key = self._temperature_set_key
        value = self._device.get_register_value_max(key) if key else None
        return value if value is not None else 90

    @property
    def current_temperature(self):
        """Return the current temperature."""
        if self._temperature_get_key:
            value = self._device.get_register_value_description(
                self._temperature_get_key
            )
            if isinstance(value, numbers.Number):
                return value

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        key = self._temperature_set_key
        if key:
            return self._device.get_register_value(key) or None

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        key = self._temperature_set_key
        if not key:
            _LOGGER.error("Failed to set temperature: no water setpoint register found")
            return
        try:
            await self._device.set_register_value(key, temperature)
            await self.coordinator.async_request_refresh()
        except (ValueError, AguaIOTError) as err:
            _LOGGER.error("Failed to set temperature, error: %s", err)

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        key = self._temperature_set_key
        return self._device.get_register(key).get("step", 1) if key else 1


class AguaIOTCanalizationDevice(AguaIOTClimateDevice):
    """Canalization device"""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device, description, parent):
        super().__init__(coordinator)
        self._enable_turn_on_off_backwards_compatibility = False
        self._device = device
        self._parent = parent
        self.entity_description = description
        self._fan_register = self.entity_description.key

        if (
            self.entity_description.key_vent_set
            and self.entity_description.key_vent_set in self._device.registers
        ):
            self._fan_register = self.entity_description.key_vent_set

    @property
    def unique_id(self):
        return f"{self._device.id_device}_{self.entity_description.key}"

    @property
    def name(self):
        return self.entity_description.name

    @property
    def supported_features(self):
        features = ClimateEntityFeature.FAN_MODE
        if (
            self.entity_description.key_temp_set
            and self.entity_description.key_temp_set in self._device.registers
            and self._device.get_register_enabled(self.entity_description.key_temp_set)
        ):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if (
            self.entity_description.key_vent_set
            and self.entity_description.key_vent_set in self._device.registers
        ):
            features |= ClimateEntityFeature.PRESET_MODE

        return features

    @property
    def fan_mode(self):
        """Return fan mode."""
        return str(self._device.get_register_value_description(self._fan_register))

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        fan_modes = []
        for x in range(
            self._device.get_register_value_min(self._fan_register),
            (self._device.get_register_value_max(self._fan_register) + 1),
        ):
            fan_modes.append(
                str(
                    self._device.get_register_value_options(self._fan_register).get(
                        x, x
                    )
                )
            )
        return fan_modes

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        try:
            await self._device.set_register_value_description(
                self._fan_register, fan_mode
            )
            await self.coordinator.async_request_refresh()
        except AguaIOTError as err:
            _LOGGER.error("Failed to set fan mode, error: %s", err)

    @property
    def preset_modes(self):
        return list(
            self._device.get_register_value_options(
                self.entity_description.key
            ).values()
        )

    @property
    def preset_mode(self):
        return self._device.get_register_value_description(self.entity_description.key)

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode."""
        try:
            await self._device.set_register_value_description(
                self.entity_description.key, preset_mode
            )
            await self.coordinator.async_request_refresh()
        except AguaIOTError as err:
            _LOGGER.error("Failed to set preset mode, error: %s", err)

    @property
    def hvac_action(self):
        if self._device.get_register_value(self.entity_description.key):
            return self._parent.hvac_action
        return HVACAction.OFF

    @property
    def hvac_modes(self):
        if self._device.get_register_value(self.entity_description.key):
            return [self._parent.hvac_mode]
        return [HVACMode.OFF]

    @property
    def hvac_mode(self):
        if self._device.get_register_value(self.entity_description.key):
            return self._parent.hvac_mode
        return HVACMode.OFF

    async def async_set_hvac_mode(self, hvac_mode):
        pass

    @property
    def min_temp(self):
        """Return the minimum temperature to set."""
        if self.entity_description.key_temp_set in self._device.registers:
            return self._device.get_register_value_min(
                self.entity_description.key_temp_set
            )

    @property
    def max_temp(self):
        """Return the maximum temperature to set."""
        if self.entity_description.key_temp_set in self._device.registers:
            return self._device.get_register_value_max(
                self.entity_description.key_temp_set
            )

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        if (
            self.entity_description.key_temp_set in self._device.registers
            and self.current_temperature
        ):
            return self._device.get_register_value(self.entity_description.key_temp_set)

    @property
    def current_temperature(self):
        """Return the current temperature."""
        if (
            self.entity_description.key_temp_get in self._device.registers
            and self._device.get_register_enabled(self.entity_description.key_temp_get)
        ):
            value = self._device.get_register_value_description(
                self.entity_description.key_temp_get
            )
            if isinstance(value, numbers.Number):
                return value
        elif (
            self.entity_description.key_temp2_get
            and self.entity_description.key_temp2_get in self._device.registers
            and self._device.get_register_enabled(self.entity_description.key_temp2_get)
        ):
            value = self._device.get_register_value_description(
                self.entity_description.key_temp2_get
            )
            if isinstance(value, numbers.Number):
                return value

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        try:
            await self._device.set_register_value(
                self.entity_description.key_temp_set, temperature
            )
            await self.coordinator.async_request_refresh()
        except (ValueError, AguaIOTError) as err:
            _LOGGER.error("Failed to set temperature, error: %s", err)

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        if self.entity_description.key_temp_set in self._device.registers:
            return self._device.get_register(self.entity_description.key_temp_set).get(
                "step", 1
            )
