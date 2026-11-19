#!/usr/bin/env python3
"""Find the offset of a stove setting that the register map does not list (for example the season).

Download the Home Assistant diagnostics of the integration three times, changing only that setting on the display:

    A: setting in state 1 (for example summer)
    B: setting in state 2 (for example winter)   -> wait 1-2 minutes after the change, then download
    C: setting back in state 1                   -> wait 1-2 minutes, then download

Usage:  python3 tools/diff_raw_offsets.py A.json B.json C.json

It prints the offsets that changed from A to B and came back in C (candidates), the ones that changed A to B and also
differ in C (changing anyway: temperatures, counters, clock), and which register of the map, if any, uses each offset.
"""

import json
import sys


def load(path):
    with open(path) as f:
        data = json.load(f)
    # Home Assistant wraps the integration diagnostics in a "data" key
    data = data.get("data", data)
    raw = data.get("raw_offsets")
    if not raw:
        sys.exit(
            f"{path}: no 'raw_offsets' in the diagnostics (install the fork version that exports them)"
        )
    name = next(iter(raw))
    offsets = {int(k): v for k, v in raw[name].items()}
    devices = data.get("devices", {}).get(name, {})
    owners = {}
    for key, reg in devices.items():
        if isinstance(reg, dict) and "offset" in reg:
            owners.setdefault(int(reg["offset"]), []).append(key)
    return offsets, owners


def main(argv):
    if len(argv) != 4:
        sys.exit(__doc__)
    a, owners = load(argv[1])
    b, _ = load(argv[2])
    c, _ = load(argv[3])
    keys = sorted(set(a) | set(b) | set(c))
    candidates, noisy = [], []
    for k in keys:
        va, vb, vc = a.get(k), b.get(k), c.get(k)
        if va != vb and va == vc:
            candidates.append((k, va, vb, vc))
        elif va != vb or va != vc:
            noisy.append((k, va, vb, vc))
    print(f"offsets read: A {len(a)}, B {len(b)}, C {len(c)}")
    print("\nCANDIDATES (A != B, C == A): the setting is probably one of these")
    for k, va, vb, vc in candidates:
        print(
            f"  offset {k:>6}  A={va:<6} B={vb:<6} C={vc:<6}  mapped: {', '.join(owners.get(k, [])) or '-'}"
        )
    if not candidates:
        print(
            "  none: the setting is not in the values read, or it changed together with other values"
        )
    print(f"\nCHANGING ANYWAY ({len(noisy)}): ignore unless the candidates are empty")
    for k, va, vb, vc in noisy[:60]:
        print(
            f"  offset {k:>6}  A={va} B={vb} C={vc}  mapped: {', '.join(owners.get(k, [])) or '-'}"
        )
    if len(noisy) > 60:
        print(f"  ... and {len(noisy) - 60} more")


if __name__ == "__main__":
    main(sys.argv)
