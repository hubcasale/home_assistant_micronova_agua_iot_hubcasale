"""Registers that local transports can read but cloud register maps lack.

The cloud register map of a stove only lists the registers the vendor app
uses. Some stoves expose more useful values in RAM, such as the state of the
pellet level sensor. The local transports (MQTT and Bluetooth) read the
offsets listed in the register map, so adding a register to the map is enough
to read it. Cloud reads use a server defined buffer and never return these
offsets, so the overrides are only applied by the local transports.

Overrides are keyed by the id of the cloud register map and are only added
when the map does not already define the register.
"""

from __future__ import annotations

import copy
from typing import Any

REGISTER_OVERRIDES: dict[str, dict[str, dict[str, Any]]] = {
    # Bronpi "BRONPI PLUS RADIO" (tested on a Neva insert with a Navel 2.0
    # module). RAM offset 159 holds the capacitive pellet level sensor state:
    # around 220 while pellets cover the sensor, 8 once the level drops below
    # it. The remote then shows "DEPOSITO VAZIO" ("tank empty") while the
    # stove keeps burning the reserve.
    "B89772DB-3E76-4A4F-B03C-A1626EA1B49E": {
        "ris_pellet_ris_get": {
            "reg_key": "ris_pellet_ris_get",
            "reg_type": "GET",
            "offset": 159,
            "mask": 255,
            "formula": "IF(#<37,1,0)",
            "formula_inverse": "#",
            "is_hex": False,
            "is_word": False,
            "set_min": 0,
            "set_max": 255,
        },
    },
    # Nobis Polygon (Navel 2.0 module, map B2C8...). EEPROM byte 33130 holds the
    # season chosen on the stove display: 1 = summer, 0 = winter. Found by
    # reading the EEPROM over Bluetooth in summer, winter and summer again: it
    # is the only byte that follows the season (the three-way valve register
    # follows it too, but it is only an effect). Writable only through the Season select.
    "B2C86BA3-3747-4E71-A1F5-10D1D6390788": {
        "season_get": {
            "reg_key": "season_get",
            "reg_type": "GET",
            "offset": 33130,
            "mask": 255,
            "formula": "#",
            "formula_inverse": "#",
            "is_hex": False,
            "is_word": False,
            "set_min": 0,
            "set_max": 1,
            # Lowercase slugs on purpose: Home Assistant translates the state of
            # an enum sensor / select through entity.<platform>.season.state.<slug>.
            "enc_val": [
                {"value": 1, "lang": "ENG", "description": "summer"},
                {"value": 0, "lang": "ENG", "description": "winter"},
                {"value": 1, "lang": "ITA", "description": "summer"},
                {"value": 0, "lang": "ITA", "description": "winter"},
            ],
        },
        # The same byte as a writable register (the Season select). Writing
        # goes through the EEPROM write budget like every other offset >= 32768.
        "season_set": {
            "reg_key": "season_set",
            "reg_type": "SET",
            "offset": 33130,
            "mask": 255,
            "formula": "#",
            "formula_inverse": "#",
            "is_hex": False,
            "is_word": False,
            "set_min": 0,
            "set_max": 1,
            # Lowercase slugs on purpose: Home Assistant translates the state of
            # an enum sensor / select through entity.<platform>.season.state.<slug>.
            "enc_val": [
                {"value": 1, "lang": "ENG", "description": "summer"},
                {"value": 0, "lang": "ENG", "description": "winter"},
                {"value": 1, "lang": "ITA", "description": "summer"},
                {"value": 0, "lang": "ITA", "description": "winter"},
            ],
        },
    },
}


def override_offsets(id_registers_map: Any) -> list[int]:
    """Offsets of the overrides of a map, to read apart from the stove buffers.

    The Bluetooth buffers only hold the offsets of the vendor app, so the
    override offsets they do not contain are read with an explicit request.
    """
    overrides = REGISTER_OVERRIDES.get(str(id_registers_map).upper(), {})
    return sorted({int(register["offset"]) for register in overrides.values()})


def apply_register_overrides(
    id_registers_map: Any, register_map: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Return the register map with the overrides for its map id added.

    Registers already present in the map are never replaced.
    """
    overrides = REGISTER_OVERRIDES.get(str(id_registers_map).upper())
    if not overrides or register_map is None:
        return register_map

    merged = dict(register_map)
    for key, register in overrides.items():
        if key not in merged:
            merged[key] = copy.deepcopy(register)
    return merged
