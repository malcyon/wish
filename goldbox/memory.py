"""The game's memory map, as data.

`goldbox/layout.py` is the single source of truth for the 580-byte character record,
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
           note="lags a move on Pool of Radiance, where the status line is "
                "the live copy; Silver Blades is the other way round, so "
                "find which copy is live on a given title by moving and "
                "watching rather than assuming (docs/144-decoding-a-new-title.md)"),
    Region(0x49C1, 1, "party y", OK, saved_in="SAVEDGAME0"),
    Region(0x49C2, 1, "party facing", OK, saved_in="SAVEDGAME0",
           note="0 north, 1 east, 2 south, 3 west"),
    Region(0x49C6, 6, "clock", OK, saved_in="SAVEDGAME0",
           note="six digits, not three: limits 0A 0A 06 18 1E 0C at $A83C. "
                "$49C7 minutes, $49C8 tens of minutes, $49C9 the HOUR -- "
                "DUNGEON $09F7 prints those three -- then $49CA and $49CB "
                "carry the day and the month. Read as plain 'minutes' for a "
                "while, which made PORSAVE11 come out at 27:27"),
    Region(0x49E7, 3, "wall slot pinned", MAYBE, saved_in="SAVEDGAME0",
           note="one flag per wall slot: do not relocate its screen codes"),
    Region(0x49F0, 2, "previous square", MAYBE, saved_in="SAVEDGAME0",
           note="the square occupied before the last move; tracked from the "
                "walk saves, never confirmed against the game's own use"),
    Region(0x49FC, 1, "not the party count", GUESS, saved_in="SAVEDGAME0",
           note="REFUTED as a party count, and named here so the reading is "
                "not made a third time. PORSAVE.D64 with one character and "
                "PORSAVE-6char.D64 with six both read 2; E003-slots.D64 with "
                "two reads 6. No byte of $4900-$4CFF equals the party size in "
                "any of 190 saves -- the C64 does not store one, and the "
                "engine's own DROP CHARACTER instead zeroes the first byte "
                "of the dropped character's name (#104)"),
    Region(0x49FD, 2, "wall colour by roofed bit", MAYBE, saved_in="SAVEDGAME0",
           note="a two-entry table indexed by the roofed bit of the square you "
                "stand on; every ECL writes both"),
    Region(0x4A00, 0x20, "per-script scratch", OK, saved_in="SAVEDGAME0",
           note="zeroed by the NEWECL handler's LDX #$1F / LDA #$00 / "
                "STA $4A00,X / DEX / BPL at DUNGEON $202A-$2032 whenever the "
                "resident ECL changes, so nothing here survives leaving an "
                "area. $4A07 is 'staying at the inn' in ECL00 and something "
                "else in seven other scripts"),
    Region(0x4A20, 0xD9, "persistent quest flags", MAYBE,
           saved_in="SAVEDGAME0",
           note="survives an area change, unlike $4A00-$4A1F. 179 of these "
                "217 bytes are named from the bytecode itself -- 172 by an "
                "ECL operand and 7 more only as the interior of a table a "
                "GETTABLE or SAVETABLE indexes, out of 1415 operand "
                "references across all thirty scripts. The remaining 38 are "
                "gaps between per-area blocks that no script touches. All of "
                "that was regenerated on 2026-09-02 by tools/eclflags.py "
                "into docs/151-quest-flags.md, replacing the lost "
                "work/reports/quest-flags.md, and every figure came back "
                "identical. The one that did not is how many carry a naming "
                "string: the old note said 158 'with a printed string at the "
                "write site', the rule it meant by 'at' was never written "
                "down, and no rule tried reproduces it -- 104 have one in the "
                "same basic block as a write and 150 within sixteen "
                "statements. Take the string count as unreproduced rather "
                "than as 158."),
    Region(0x4AF9, 0x87, "unused", OK, saved_in="SAVEDGAME0",
           note="not flag storage, on four independent grounds: no ECL "
                "operand anywhere above $4AF8, no engine binary references "
                "the range, and it is zero in all 21 specimens. The old "
                "$4A20-$4B7F region was one block only because $4B80 was the "
                "next thing that had a name"),
    Region(0x4B80, 0x40, "effect magnitude", OK, saved_in="SAVEDGAME0",
           note="the fourth of the four parallel effect arrays: how much, for "
                "whatever the id means. ENLARGE on a character with strength "
                "18/98 wrote $E2, which is $80 | 98 -- the strength to put "
                "back. Not zero in every save after all: PORSAVE13 carries 1 "
                "in six slots that nobody had looked at"),
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
           note="resident code and graphics scratch rather than party state -- "
                "but $8400-$8753 is the file ANIMATE00 and loaded-files cache "
                "slot 11 tells the engine it is already in memory, so nothing "
                "reloads it and a save that carries the wrong bytes here is "
                "carrying wrong code (#122). $8754-$8AFF is the bitmap buffer "
                "and is scratch: 940 zeros there loaded, walked, fought and "
                "changed area (#118)"),

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
    Region(0x8C00, 0x5B0, "the combat map", OK,
           note="one byte per square at $8C00 + y*stride + x, 56 x 26 with "
                "stride 56 in the fights seen. Bit 7 means a combatant stands "
                "there; mask & $7F for the terrain, 0 = floor. Outside combat "
                "this is LIBRARY's file staging buffer and holds graphics, so "
                "gate on MODE. Read the shape from $0607/$0612/$0613, not from "
                "constants"),
    Region(0x0400, 0x400, "SQRPACI<nn>", OK,
           note="the combat-map descriptor page: $0580 tile remap, the "
                "parameter block below, and code from $0680. Not a map itself, "
                "which is why scoring it as a GEO gave chance"),
    Region(0x0600, 0x14, "combat-view parameters", OK,
           note="$0600 glyph table (18 bytes a tile: 9 screen codes, 9 "
                "colours), $0602 the map, $0604 the position table, $0606 "
                "combatant count, $0607 row stride, $0610/$0611 maximum camera "
                "origin, $0612/$0613 maximum square x and y. COM.PREP $08C6 "
                "derives the clamps as $0612 - 6, the view being 7 squares "
                "($061A)"),
    Region(0x037E, 2, "camera origin", OK,
           note="top-left square of the 7 x 7 combat window; centred on the "
                "acting combatant"),
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
