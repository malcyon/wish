#!/usr/bin/env python3
"""Which monitor bank a read needs, for RAM that sits under I/O (#184).

`#184 (A converted combat icon's colours are proven in the game and its
shapes are not)` turns on one detail of the binary monitor: the combat
character set computes to `$D000`, and `$D000` is RAM **under** the I/O
registers.  A monitor read there answers whichever of the two the bank asks
for, and the bank is a number this project mostly leaves at its default.

So this measures it rather than arguing it.  On a pooled instance it

* asks VICE for the banks it offers (`MON_CMD_BANKS_AVAILABLE`, the same
  request `tools/wallpins.py`'s `bank_ids` makes);
* writes a marker byte into `$D000` through the bank called `ram`;
* reads `$D000` back through **every** bank, and says which ones show it.

A bank that shows the marker is reading RAM.  A bank that does not is reading
the registers, and any charset read through it is not character data however
plausible the bytes look.

Nothing about the game is involved: the answer is VICE's, so the emulator is
booted and left at the title.  Output is a table and an exit status -- 0 when
the default bank reads RAM, 1 when it does not, so a run can be a check.

    POR_HEADLESS=1 tools/vicebankcheck.py
    POR_HEADLESS=1 tools/vicebankcheck.py --address 0xD000,0xD100,0xD500

Several addresses in one run because the interesting reading is not only
whether the default bank misses RAM but **what it answers instead**: a check
that expects eight zero bytes at one glyph and eight `$FF`s at another can
pass on register mirrors and open bus without ever seeing character data.
`--bytes` widens each reading from one byte to a glyph.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap.paths import find_disks  # noqa: E402
from tools import instance  # noqa: E402
from tools.session import Session  # noqa: E402

#: `MON_CMD_BANKS_AVAILABLE`.  `tools/wallpins.py` carries the same constant
#: and the same unpacking; this is the tool that says what the answer means.
CMD_BANKS = 0x82

#: Where the question is asked.  `$D000` is the VIC's registers to the CPU
#: with I/O banked in, and RAM to the VIC in bank 3 -- which is where the
#: engine puts the combat character set.
DEFAULT_ADDRESS = 0xD000
DEFAULT_MARKER = 0xA5


def bank_ids(mon) -> dict[str, int]:
    """Every bank VICE offers this machine, by name."""
    resp = mon.command(CMD_BANKS, b"")
    count = struct.unpack("<H", resp[:2])[0]
    off, out = 2, {}
    for _ in range(count):
        size = resp[off]
        bid = struct.unpack("<H", resp[off + 1:off + 3])[0]
        length = resp[off + 3]
        out[resp[off + 4:off + 4 + length].decode("latin1")] = bid
        off += size + 1
    return out


def probe(sess, addresses: list[int], marker: int,
          width: int) -> tuple[dict[str, int], dict[int, dict[str, bytes]]]:
    """`(banks, {address: {bank name: what it read}})`, marker written first."""
    with sess.mon(8) as m:
        banks = bank_ids(m)
        if "ram" not in banks:
            raise SystemExit(f"this VICE offers no bank called ram: "
                             f"{sorted(banks)}")
        order = sorted(banks.items(), key=lambda kv: kv[1])
        seen = {}
        for address in addresses:
            before = m.read(address, width, bank=banks["ram"])
            m.write(address, bytes([marker]) * width, bank=banks["ram"])
            seen[address] = {name: m.read(address, width, bank=bid)
                             for name, bid in order}
            m.write(address, before, bank=banks["ram"])
    return banks, seen


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--address", default=hex(DEFAULT_ADDRESS),
                    help="one address or several, comma separated")
    ap.add_argument("--bytes", type=int, default=1, dest="width",
                    help="how many bytes to read at each (default 1)")
    ap.add_argument("--marker", type=lambda s: int(s, 0), default=DEFAULT_MARKER)
    ap.add_argument("--disk", help="any bootable image; the game is not used")
    args = ap.parse_args(argv)

    addresses = [int(part, 0) for part in args.address.split(",")]
    disk = args.disk
    if not disk:
        where = os.environ.get("POR_DISKS") or find_disks()
        if not where:
            raise SystemExit("no disks; pass --disk")
        disk = str(pathlib.Path(where) / "POOLBOOT.D64")

    slot = instance.claim(game="por", note="vicebankcheck")
    sess = Session(disk, slot=slot)
    try:
        sess.launch()
        banks, seen = probe(sess, addresses, args.marker, args.width)
    finally:
        sess.close()
        slot.teardown()
        slot.release()

    want = bytes([args.marker]) * args.width
    missed = []
    for address, readings in seen.items():
        print(f"${address:04X}, marker ${args.marker:02X} x {args.width}")
        print("  bank            id  reads                     RAM?")
        for name, value in readings.items():
            print(f"    {name:<12} {banks[name]:3}   {value.hex(' '):<24}  "
                  f"{'yes' if value == want else 'no'}")
        print()
        if readings.get("default") != want:
            missed.append(address)
    if "default" not in next(iter(seen.values())):
        print("this VICE offers no bank called default")
        return 1
    if not missed:
        print("the default bank reads RAM at every address asked about")
        return 0
    print("the default bank does NOT read RAM at "
          + ", ".join(f"${a:04X}" for a in missed)
          + f": a read there needs bank {banks['ram']} (ram)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
