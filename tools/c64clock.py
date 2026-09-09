#!/usr/bin/env python3
"""Find the six-digit game clock in every C64 Gold Box title's overlays.

The clock is six one-digit counters at `save_load_address + $C6`, and two
routines name it:

* the **tick** -- `INC $ppC6,X / ... / LDA $ppC6,X / CMP <limits>,X /
  BCC out / LDA #$00 / STA $ppC6,X / INX`, which rolls each digit at its own
  limit.  Pool of Radiance's and Curse of the Azure Bonds' are in `DUNGEON`
  and `CAMP`; Secret of the Silver Blades moved it into `LIBRARY`.
* the **status line** -- `LDA $ppC9 / print / LDA #$3A / print / LDA $ppC8 /
  print / LDA $ppC7 / print`, which is the hour, a colon, and the two minute
  digits.  That is why `goldbox.games.CLOCK_OFFSET` is `$C7` and not `$C6`:
  the clock a player reads is the last three of the six digits, and the first
  three of the six are a sub-minute counter the game never shows.

`pp` is the save image's own page, so a hit says which title's save the
routine writes into without anybody having to know the load address first.
The limits Pool of Radiance and Curse both carry are `0A 0A 06 18 1E 0C`:
ten sub-minute ticks to a minute, ten minute units, six minute tens,
twenty-four hours, thirty days, twelve months.

Written for `#470 (Give the project a neutral title beside its neutral
character record, with one port per platform a title shipped on)`, which
could not tell whether `goldbox.games.CLOCK_OFFSET = 0xC7` or
`goldbox.c64_save.Container.clock = 0xC6` was the wrong one.  Both are right
and they are two different fields; this is what says so.

Usage:

    tools/c64clock.py                 # every title tools/gamedisks.toml knows
    tools/c64clock.py pool-of-radiance curse-of-the-azure-bonds
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import d64  # noqa: E402
from tools import gamedisks  # noqa: E402

#: An overlay's PRG header is a family stamp rather than a load address, and
#: the game's `LINKER` puts the payload at `$0800` -- so `file[0]` sits at
#: `$07FE` and every address in a listing based on `file[0] == $0800` is two
#: high (`docs/40-memory-map.md`, `#312`).  `LIBRARY` is the exception and
#: has its own base per title.
OVERLAY_BASE = 0x07FE
LIBRARY_BASE = {"pool-of-radiance": 0x2C46}
LIBRARY_BASE_LATER = 0x2DC6

#: The rollover limits Pool of Radiance and Curse both carry, in digit order.
LIMITS = bytes((0x0A, 0x0A, 0x06, 0x18, 0x1E, 0x0C))

#: `INC $ppC6,X`, then within a dozen bytes `LDA $ppC6,X / CMP <table>,X` on
#: the same page.  The gap is what lets Secret of the Silver Blades match: it
#: counts an extra pair of bytes between the two.
TICK = re.compile(rb"\xFE\xC6(.).{0,12}?\xBD\xC6\1\xDD(..)", re.DOTALL)

#: `LDA $ppC9 / JSR / LDA #$3A / JSR / LDA $ppC8 / JSR / LDA $ppC7`.
STATUS = re.compile(rb"\xAD\xC9(.)\x20..\xA9\x3A\x20..\xAD\xC8\1\x20..\xAD\xC7\1")


def base_for(key: str, name: str) -> int:
    """Where `file[0]` of this file lands in memory."""
    if name.upper().startswith("LIBRARY"):
        return LIBRARY_BASE.get(key, LIBRARY_BASE_LATER)
    return OVERLAY_BASE


def _files(image: d64.D64):
    for entry in image.directory():
        try:
            yield entry.display_name, image.read_file(entry)
        except Exception:                       # a broken chain is not a file
            continue


def scan(key: str) -> list[str]:
    """One line per hit, for every disk side this title has here."""
    where = gamedisks.find(key)
    if where is None:
        return [f"{key}: no disks"]
    out = []
    for path in sorted(pathlib.Path(where).glob("*.[dD]64")):
        try:
            image = d64.D64.open(path)
        except Exception as exc:
            out.append(f"{key} {path.name}: unreadable ({exc})")
            continue
        for name, data in _files(image):
            base = base_for(key, name)
            for m in TICK.finditer(data):
                page = data[m.start() + 2]
                table = int.from_bytes(m.group(2), "little")
                shown = data[table - base:table - base + 6]
                out.append(
                    f"{key} {path.name} {name} tick ${m.start() + base:04X} "
                    f"clock ${page:02X}C6 limits ${table:04X} "
                    f"{' '.join(f'{b:02X}' for b in shown)}"
                    f"{'' if shown == LIMITS else '  <-- not the six known limits'}")
            for m in STATUS.finditer(data):
                page = data[m.start() + 2]
                out.append(
                    f"{key} {path.name} {name} status ${m.start() + base:04X} "
                    f"prints ${page:02X}C9 : ${page:02X}C8 ${page:02X}C7")
            for m in re.finditer(re.escape(LIMITS), data):
                out.append(f"{key} {path.name} {name} limits ${m.start() + base:04X}")
    return out or [f"{key}: no clock signature on any side"]


def main(argv: list[str]) -> int:
    keys = argv[1:] or list(gamedisks.names())
    for key in keys:
        for line in scan(key):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
