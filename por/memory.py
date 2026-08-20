"""The game's memory map, as data.

`por/layout.py` is the single source of truth for the 580-byte character record,
and it works: every field carries a confidence, the docs are generated from it,
and nothing drifts. Nothing played that role for **everything outside a record**
-- the party header, the loader's caches, the combat tables -- so those addresses
lived scattered across constants in `savegame.py`, prose in `docs/`, and
experiment write-ups. Finding out what `$4BC2` was meant grepping.

This is that table. It is deliberately *descriptive*: nothing here is used to
decode anything, because the decoders already have their own constants. It
exists so a person or an agent can ask "what is at this address" and "how sure
are we" in one place, and so `docs/40-memory-map.md` can be generated rather than
maintained.

**Addresses are live addresses.** `SAVEDGAME0` is a verbatim image of
`$4900`-`$64FF` and `SAVEDGAME1` of `$8300`-`$8AFF`, so anything in those ranges
is also a save-file offset once you subtract the base. Everything else is only
meaningful while the overlay that owns it is resident -- the game is heavily
overlaid and an address means what we think only in the right moment.
"""

from __future__ import annotations

from dataclasses import dataclass

from .layout import Confidence

OK = Confidence.CONFIRMED
MAYBE = Confidence.PROBABLE
GUESS = Confidence.GUESS
UNKNOWN = Confidence.UNKNOWN


@dataclass(frozen=True)
class Region:
    """One named span of the machine's memory."""

    start: int
    size: int
    name: str
    confidence: Confidence
    note: str = ""
    #: Which file, if any, carries these bytes verbatim.
    saved_in: str | None = None

    @property
    def end(self) -> int:
        return self.start + self.size

    def __str__(self) -> str:
        span = (f"${self.start:04X}" if self.size == 1
                else f"${self.start:04X}-${self.end - 1:04X}")
        return f"{span} {self.name}"


MAP: tuple[Region, ...] = (
    # --- SAVEDGAME0: a verbatim image of $4900-$64FF ----------------------
    Region(0x4900, 0x40, "effect ids", MAYBE, saved_in="SAVEDGAME0",
           note="64 timed effects; 0 means the slot is free. Expiry clears "
                "only the id, so filter on it or you will show effects that "
                "have already ended"),
    Region(0x4940, 0x40, "effect owner", MAYBE, saved_in="SAVEDGAME0",
           note="0-7 a party member by slot, 8+ a monster, $FF the whole "
                "party. This encoding is what led to the combatant table"),
    Region(0x4980, 0x40, "effect duration", MAYBE, saved_in="SAVEDGAME0",
           note="bits 6-7 select the time unit"),
    Region(0x49C0, 1, "party x", OK, saved_in="SAVEDGAME0",
           note="lags a move; the game's own status line is authoritative"),
    Region(0x49C1, 1, "party y", OK, saved_in="SAVEDGAME0"),
    Region(0x49C2, 1, "party facing", OK, saved_in="SAVEDGAME0",
           note="0 north, 1 east, 2 south, 3 west"),
    Region(0x49C7, 3, "clock", OK, saved_in="SAVEDGAME0",
           note="units of a minute, tens, then the HOUR. DUNGEON $09F7 prints "
                "$49C9 : $49C8 $49C7. Read as 'minutes' for a while, which "
                "made PORSAVE11 come out at 27:27"),
    Region(0x49E7, 3, "wall slot pinned", MAYBE, saved_in="SAVEDGAME0",
           note="one flag per wall slot: do not relocate its screen codes"),
    Region(0x49F0, 2, "previous square", MAYBE, saved_in="SAVEDGAME0",
           note="the square occupied before the last move; tracked from the "
                "walk saves, never confirmed against the game's own use"),
    Region(0x49FC, 1, "party count", MAYBE, saved_in="SAVEDGAME0",
           note="CAMP increments and decrements it"),
    Region(0x49FD, 2, "wall colour by roofed bit", MAYBE, saved_in="SAVEDGAME0",
           note="a two-entry table indexed by the roofed bit of the square you "
                "stand on; every ECL writes both"),
    Region(0x4A00, 0x20, "per-script scratch", MAYBE, saved_in="SAVEDGAME0",
           note="zeroed by DUNGEON $202A whenever the resident ECL changes, so "
                "nothing here survives leaving an area. $4A07 is 'staying at "
                "the inn' in ECL00 and something else in seven other scripts"),
    Region(0x4A20, 0x160, "persistent flags", UNKNOWN, saved_in="SAVEDGAME0",
           note="survives an area change, unlike $4A00-$4A1F. Largely unread"),
    Region(0x4B80, 0x40, "effect magnitude", MAYBE, saved_in="SAVEDGAME0",
           note="the fourth of the four parallel effect arrays; how much, "
                "for whatever the id means. Zero in every save we hold, "
                "because none was taken mid-effect"),
    Region(0x4BC0, 25, "loaded-files cache", OK, saved_in="SAVEDGAME0",
           note="one entry per data-file type, mirroring $6E13 in a running "
                "game. Bit 7 is a reload marker, not data -- mask it"),
    Region(0x4BC2, 1, "current GEO", OK, saved_in="SAVEDGAME0",
           note="the map the party is on, and the answer to the question that "
                "stood open longest. All ten New Phlan saves read $00; "
                "PORSAVE13, in the slums, reads $14"),
    Region(0x4BE0, 8 * 36, "combat icon table", OK, saved_in="SAVEDGAME0",
           note="8 entries of 36 bytes, ending exactly at $4D00. Record offset "
                "0x220 for each character"),
    Region(0x4D00, 12 * 0x100, "character slots", OK, saved_in="SAVEDGAME0",
           note="TWELVE slots of $100, not eight: 0-7 the party, 8-11 combat. "
                "A slot holds only the first 256 bytes of a 580-byte record"),
    Region(0x5900, 12 * 0x100, "item area", OK, saved_in="SAVEDGAME0",
           note="one $100 block per slot, 16 items of 16 bytes. Ends exactly "
                "at $6500, which is where SAVEDGAME0 ends -- the arithmetic "
                "only closes at twelve slots. A live poke here is reverted: "
                "this is a copy fed from a master elsewhere"),

    # --- SAVEDGAME1: a verbatim image of $8300-$8AFF ----------------------
    Region(0x8300, 8 * 32, "party roster", OK, saved_in="SAVEDGAME1",
           note="eight 32-byte blocks of derived combat values. These same "
                "bytes are record offsets 0x100-0x11F -- an export and the "
                "roster agree in 31 of 32, differing only at 0x10D"),
    Region(0x8400, 0x700, "ANIMATE00 and a bitmap buffer", OK,
           saved_in="SAVEDGAME1",
           note="not save data at all: resident code and graphics scratch that "
                "happened to be in memory when the range was dumped"),

    # --- live only --------------------------------------------------------
    Region(0x03DE, 3, "SETNAM arguments", OK,
           note="length, then the filename's address in $03DF/$03E0"),
    Region(0x2B80, 136, "LINKER", OK,
           note="the outer loop: read $6E11, load that overlay at $0800, call "
                "it, repeat"),
    Region(0x2C48, 0, "LIBRARY", OK,
           note="resident base. Its declared $1000 is a lie, as every "
                "overlay's is; the rest load at $0800"),
    Region(0x40EA, 0x60, "data-file name stems", OK,
           note="GDRIVE00, SQRPACI00, GEO00 at $40FC... templates copied "
                "elsewhere to build a filename, never patched in place"),
    Region(0x3243, 0x39, "race names", OK,
           note="NUL-separated, 1-based: DWARF=1 ... HUMAN=7 MONSTER=8. "
                "Reasoning in docs/40-memory-map.md"),
    Region(0x327C, 0x0C, "gender names", OK, note="MALE, FEMALE"),
    Region(0x3288, 0x2B, "class names", OK,
           note="0-based: CLERIC=0 DRUID=1 FIGHTER=2 ... Entries 13, 14 and 15 "
                "all point at MAGIC-USER, which is why a paladin displays as "
                "one"),
    Region(0x32B3, 0x78, "alignment names", OK,
           note="the record's 0x0D8 is a 0-based index into exactly this list"),
    Region(0x332B, 0x1C, "ability labels", OK, note="AGE STR INT WIS DEX CON CHR"),
    Region(0x3347, 0x30, "money labels", OK),
    Region(0x3E0B, 0, "party-list print routine", OK,
           note="prints name, AC and hit points and nothing else, which is why "
                "there is no stored status field"),
    Region(0x6B00, 580, "the resident character record", OK,
           note="a fixed base, which is why absolute operands name record "
                "offsets directly and why disassembly cracked so much"),
    Region(0x6C00, 32, "the resident roster block", OK),
    Region(0x6D7C, 16, "the resident item", OK,
           note="its ITEMS type record at $6D8C"),
    Region(0x6E11, 1, "MODE", OK,
           note="which overlay is running: 0 GEN, 1 DUNGEON, 2 COMBAT, "
                "3 INIT, 4 COM.PREP, 5 POST.COM, 8 FINAL, 9 CAMP. This is the "
                "flag to gate on, not the screen"),
    Region(0x6E13, 25, "loaded-files cache, live", OK,
           note="what $4BC0 is a copy of"),
    Region(0x0400, 1024, "the resident GEO", OK,
           note="the map the game is drawing, unrelocated -- the file loads at "
                "$0400 and in the world the screen has moved to $CC00"),
    Region(0x8B00, 64 * 4, "combatant positions", MAYBE,
           note="x, y, index*4|pose, 0 per combatant; $FF $FF means off the "
                "map. Reads all ZERO outside combat, not $FF, so gate on MODE "
                "or you will draw 64 combatants at (0,0)"),
    Region(0xA380, 64, "initiative", MAYBE,
           note="scanned for the maximum with ties broken randomly; the round "
                "ends when all 64 are zero"),
    Region(0xCC00, 1000, "screen", OK,
           note="in the world. Recompute it from $D018 and $DD00 every read -- "
                "it is $0400 at boot"),
)

BY_NAME = {r.name: r for r in MAP}


def at(address: int) -> list[Region]:
    """Every region covering `address`. More than one is normal -- `$4BC2` sits
    inside the loaded-files cache, and both entries are worth seeing."""
    return [r for r in MAP if r.start <= address < r.end or
            (r.size == 0 and r.start == address)]


def describe(address: int) -> str:
    hits = at(address)
    if not hits:
        return f"${address:04X} is not in the map"
    return "; ".join(str(r) for r in hits)


def saved_regions(save_file: str) -> list[Region]:
    return [r for r in MAP if r.saved_in == save_file]
