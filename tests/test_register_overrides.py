"""Test the register overrides applied by the local transports."""

from tests.helpers import load_component_module

overrides_module = load_component_module("register_overrides")
apply_register_overrides = overrides_module.apply_register_overrides

BRONPI_MAP_ID = "B89772DB-3E76-4A4F-B03C-A1626EA1B49E"


class TestApplyRegisterOverrides:
    def test_adds_pellet_sensor_for_bronpi_map(self):
        register_map = {"status_get": {"offset": 33}}

        result = apply_register_overrides(BRONPI_MAP_ID, register_map)

        assert result["status_get"] == {"offset": 33}
        assert result["ris_pellet_ris_get"]["offset"] == 159
        assert result["ris_pellet_ris_get"]["formula"] == "IF(#<37,1,0)"

    def test_map_id_match_is_case_insensitive(self):
        result = apply_register_overrides(BRONPI_MAP_ID.lower(), {})

        assert "ris_pellet_ris_get" in result

    def test_does_not_modify_input_map(self):
        register_map = {"status_get": {"offset": 33}}

        apply_register_overrides(BRONPI_MAP_ID, register_map)

        assert register_map == {"status_get": {"offset": 33}}

    def test_keeps_register_already_in_map(self):
        existing = {"offset": 42, "formula": "#"}
        register_map = {"ris_pellet_ris_get": existing}

        result = apply_register_overrides(BRONPI_MAP_ID, register_map)

        assert result["ris_pellet_ris_get"] is existing

    def test_other_map_is_unchanged(self):
        register_map = {"status_get": {"offset": 33}}

        assert apply_register_overrides(5, register_map) is register_map

    def test_missing_map_is_unchanged(self):
        assert apply_register_overrides(BRONPI_MAP_ID, None) is None

    def test_returned_registers_are_copies(self):
        first = apply_register_overrides(BRONPI_MAP_ID, {})
        first["ris_pellet_ris_get"]["offset"] = 1

        second = apply_register_overrides(BRONPI_MAP_ID, {})

        assert second["ris_pellet_ris_get"]["offset"] == 159


NOBIS_MAP_ID = "B2C86BA3-3747-4E71-A1F5-10D1D6390788"


class TestSeasonRegister:
    def test_adds_season_register_for_nobis_map(self):
        result = apply_register_overrides(NOBIS_MAP_ID, {"status_get": {"offset": 33}})

        season = result["season_get"]
        assert season["offset"] == 33130
        assert season["mask"] == 255
        assert {(e["lang"], e["value"]): e["description"] for e in season["enc_val"]} == {
            ("ENG", 1): "Summer",
            ("ENG", 0): "Winter",
            ("ITA", 1): "Estate",
            ("ITA", 0): "Inverno",
        }

    def test_override_offsets_lists_the_extra_offsets(self):
        assert overrides_module.override_offsets(NOBIS_MAP_ID.lower()) == [33130]
        assert overrides_module.override_offsets("unknown") == []

    def test_season_value_description(self, devices_from_fixtures):
        device = devices_from_fixtures["go_heat"]
        register_map = apply_register_overrides(NOBIS_MAP_ID, {})
        device._Device__register_map_dict = register_map
        device.apply_raw_data({33130: 1})
        assert device.get_register_value_description("season_get", "ENG") == "Summer"
        device.apply_raw_data({33130: 0})
        assert device.get_register_value_description("season_get", "ITA") == "Inverno"

    def test_season_set_is_a_writable_register_on_the_same_offset(self):
        result = apply_register_overrides(NOBIS_MAP_ID, {})

        assert result["season_set"]["reg_type"] == "SET"
        assert result["season_set"]["offset"] == result["season_get"]["offset"]
        assert (result["season_set"]["set_min"], result["season_set"]["set_max"]) == (0, 1)
