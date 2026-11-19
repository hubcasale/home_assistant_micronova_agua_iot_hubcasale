# Fixture mode (development)

The integration can run against JSON register fixtures in
`custom_components/aguaiot_hubcasale/fixtures` instead of a live Agua IOT account. This
loads every fixture as its own device and never contacts the Agua IOT servers.

Enable it with the `AGUAIOT_FIXTURES` environment variable before starting
Home Assistant:

```bash
# Load every fixture from the default fixtures/ directory
AGUAIOT_FIXTURES=1 hass

# Relative paths are resolved against the current directory, the Home
# Assistant configuration directory and the integration directory
AGUAIOT_FIXTURES=fixtures hass

# Or load a specific directory or single fixture file
AGUAIOT_FIXTURES=/path/to/fixtures hass
AGUAIOT_FIXTURES=/path/to/fixtures/ravelli.json hass
```

Any existing config entry is used for the integration settings, but the
devices and register values come from the fixtures. Writes are simulated in
memory: values change after the next refresh, but nothing is written to the
fixture file or sent to a stove. Set `AGUAIOT_FIXTURES=0` (or unset it) to
return to live data.

## Finding a setting the register map does not list

The local transports read every offset the stove returns, not only the ones in the register map. The diagnostics of the
integration export that raw read as `raw_offsets` (offset to value). To find the offset of a setting that has no register
(for example the season), download the diagnostics three times changing only that setting on the display (A: state 1,
B: state 2, C: state 1 again, waiting 1-2 minutes after each change) and run
`python3 tools/diff_raw_offsets.py A.json B.json C.json`: the offsets that change from A to B and come back in C are the
candidates. Offsets from 32768 up are EEPROM: do not write to an offset you have not confirmed.
