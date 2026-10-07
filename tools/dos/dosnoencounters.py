#!/usr/bin/env python3
"""The DOS `no_encounters` switch: the running area's encounter gate, written before every move.

The DOS engines run the same area scripts as the C64 ones, and each script
rolls its wandering encounter in its step entry behind a test of a script
variable (`tools/c64/session.py` `ENCOUNTER_GATES`).  `GATES` here lists the
same variables, checked against the DOS script blocks: before each move key the
switch writes the running area's gate values into the live variable array, so
the roll is never reached; fixed square fights roll nothing and still happen.

**Memory is written through the DOSBox-X debugger** (`dosboxx.XSession`):
Alt+Pause halts the machine, `MEMDUMPBIN` reads and `SM` writes, `RUN`
resumes.  No window is drawn and nothing needs a rebuild.  Each title's engine
keeps a far pointer to the variable array and the current area as a byte in
its data segment (`ENGINE`); the data segment is read with `EV DS` at a halt
and believed only when the block it points at passes `LiveVariables.check`.
A DOS variable is one 16-bit word per script address from the title's
`var_base` (`goldbox.dos_savegame`), so a gate is written as a whole word.
The array's own `$49F2` word is not the area: it holds the area the party
came from, and read 0 in the Slums after one step.

`on` arms the switch and touches nothing until the next move.  A gate word the
game changes while the switch holds it keeps the game's value and is not
forced again until the next `on`.  `off` puts back each original value whose
word still holds what the switch wrote, keeps any value the game has changed
since, and leaves the switch off.  A title whose `ENGINE` row is not CONFIRMED
is used only with `speculative=True` and the loaded save.  A game save is
stopped while the switch is on or a written value is still outstanding,
because the gates are saved variables and some are story counters.  The
written values live only in the emulator's memory, so ending the emulator ends
them; nothing is journalled.  Never use it for conversion proof.

**Pools of Darkness has no gate variable** (`SCRIPT_GATES`): its step entry
counts steps and then rolls with `RANDOM`, so the switch changes the loaded
script instead, as the Amiga switch does (`tools/amiga/noencounters.py`).  Each
covered `RANDOM` becomes `SAVE`, which stores the constant (or 0, where the
fight is on the high side) and takes the statement's `EXIT`.  A row is written
only where the bytes at its address hash to its guard, so a reloaded script is
changed again and another area's script is left alone.  `off` puts back each
statement still holding the switch's bytes.  The variables `SAVE` leaves (the
roll variable and an unreset step counter) are not put back; they are values
the game's own roll can leave, and the save stores them, so `off` still comes
before any save.

    dosnoencounters.py gates
    dosnoencounters.py scan
    dosnoencounters.py live --title pool-of-radiance \\
        --folder /mnt/specimens/por-dos/WISH-SPEC-por-amiga-slums-dos-resave --steps 40
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_savegame  # noqa: E402
from tools.dos import dosbox, dosboxx  # noqa: E402
from tools.registry import scratch  # noqa: E402

POOL = "pool-of-radiance"
CURSE = "curse-of-the-azure-bonds"
SILVER = "secret-of-the-silver-blades"
DARKNESS = "pools-of-darkness"

#: Each gate-variable title's saved-game container and its DOS game
#: directory's name.
CONTAINERS = {
    POOL: dos_savegame.SAVE_POOL_OF_RADIANCE,
    CURSE: dos_savegame.SAVE_CURSE_OF_THE_AZURE_BONDS,
    SILVER: dos_savegame.SAVE_SECRET_OF_THE_SILVER_BLADES,
}
STEMS = {POOL: "POOLRAD", CURSE: "CURSE", SILVER: "SECRET", DARKNESS: "DARKNESS"}


@dataclasses.dataclass(frozen=True)
class Engine:
    """Two data-segment offsets in a title's `GAME.OVR`: the far pointer to the
    variable array's word 0, and the current-area byte.  Both come from the
    area start-up copy `les di, [pointer]; mov al, es:[di+0x1E4]; mov [area],
    al` and the `NEWECL` handler's store back, found by those instruction bytes
    in each title."""

    pointer: int
    area: int
    where: str
    grade: str


ENGINE = {
    POOL: Engine(0x49D2, 0x84DC, "GAME.OVR 0x4067 and 0x1926; live, the "
                 "pointer met the block a memory search found and the area "
                 "byte read 20 in the Slums", "CONFIRMED"),
    CURSE: Engine(0x4FB2, 0x8B78, "GAME.OVR 0x40D5 and 0x14FE; live, EV DS "
                  "and a memory search for the pointer gave the same segment "
                  "and the area byte read 2", "CONFIRMED"),
    SILVER: Engine(0x67C6, 0xA4C2, "GAME.OVR 0x189A and 0x1845; not run",
                   "PROBABLE"),
}

#: Word index of the first clock digit (`$49C6` in Pool of Radiance, `$4BC6`
#: in the later two); `check` reads the six digits.
CLOCK_INDEX = 0xC6

#: Words in the first heap block of the variable array, the only one a gate
#: lives in: `$4900`-`$4CFF` in Pool of Radiance, `$4B00`-`$4EFF` after.
BLOCK_WORDS = 0x400

#: With the loaded save in hand, how many bytes of its first block must equal
#: the live one before a data segment is believed.
MATCH_FRACTION = 0.75

#: Halts tried before giving up on finding the game's data segment.
DS_TRIES = 5

CONFIRMED, PROBABLE, SPECULATIVE = "CONFIRMED", "PROBABLE", "SPECULATIVE"


@dataclasses.dataclass(frozen=True)
class Gate:
    """One area's encounter gate: `(address, value)` words to write, in the
    title's own script addresses, with how sure it is and why."""

    grade: str
    source: str
    pokes: tuple[tuple[int, int], ...]


_SAME = "the DOS block is byte-identical to the C64 script"

#: Keyed by `(title, area)`; the area is the script id, the hex in `ECLnn`.
GATES: dict[tuple[str, int], Gate] = {
    (POOL, 0x14): Gate(
        CONFIRMED,
        "Slums ECL14 (ECL2.DAX block 20): $4A80 >= 15 exits before the step "
        "roll at $9B32; the DOS block differs from the C64 script in ten bytes, "
        "none between $9A2E and $9C40; 40 squares walked with it on and no "
        "encounter, against controls that met one within 3 squares",
        ((0x4A80, 15),)),
    **{(POOL, area): Gate(
        PROBABLE,
        f"ECL{area:02X}: the alarm $4A64 >= 1 gates the step roll; {_SAME}",
        ((0x4A64, 0),)) for area in (0x04, 0x05, 0x09)},
    (POOL, 0x06): Gate(
        PROBABLE,
        "ECL06: the alarm $4A64 >= 1 gates the step roll at $99F4-$9A8D; the "
        "DOS block's first difference from the C64 script is at $9BE7",
        ((0x4A64, 0),)),
    (CURSE, 0x03): Gate(
        PROBABLE,
        f"Tilverton sewers ECL03: step roll then $4C02 < 8 at $9A4F; {_SAME}",
        ((0x4C02, 8), (0x4C2A, 1))),
    (CURSE, 0x02): Gate(
        PROBABLE,
        f"ECL02: $4C2C <= 4 at $871E, then 10%; {_SAME}; 37 squares walked "
        "with it on and no wandering encounter before the square-1 fixed "
        "fight, and the control's fight at square 32 was not identified",
        ((0x4C2C, 5),)),
    (CURSE, 0x01): Gate(
        PROBABLE,
        f"Tilverton ECL01: outdoor squares 10% behind $4C0C; {_SAME}",
        ((0x4C0C, 6),)),
    (CURSE, 0x50): Gate(
        PROBABLE, f"world map ECL50: no random encounter; {_SAME}", ()),
    (CURSE, 0x51): Gate(
        PROBABLE, f"world map ECL51 has no RANDOM; {_SAME}", ()),
    (SILVER, 0x10): Gate(
        PROBABLE,
        f"New Verdigris ECL10: the fight arm runs only while $4C2D = 1 "
        f"(at $85AC); {_SAME}",
        ((0x4C2D, 0),)),
}


# --------------------------------------------------------------------------
# Pools of Darkness: the rolls in the loaded script
# --------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class ScriptEngine:
    """Two data-segment offsets in a title's `GAME.OVR`: far pointers to its
    byte-wide variable 1 and to the loaded script's ECL address `$8000`."""

    variables: int
    script: int
    where: str
    grade: str


SCRIPT_ENGINE = {
    DARKNESS: ScriptEngine(
        0x87F8, 0x87FC,
        "GAME.OVR GetVar/SetVar: `les di, [0x87F8]` for a variable and "
        "`les di, [0x87FC]; add di, ax; add di, 0x8000` for a script address "
        "(0x6EF7, 0x7054); live, area 16 loaded, the script pointer held the "
        "ECL1.DAX block byte for byte and the variable pointer 1022 of the "
        "save's 1024 bytes", CONFIRMED),
}

#: The ECL address of a script buffer's first byte.
SCRIPT_BASE = 0x8000

#: The roll's opcode, and the one it becomes: `SAVE` takes the same operands
#: and stores the constant instead of a roll.
RANDOM, SAVE = 0x08, 0x09

#: The bytes a row's guard hashes: `RANDOM` and `COMPARE` (six each), the
#: condition and the `EXIT` it guards.
GUARD_BYTES = 14

#: The variable index the engine writes the running area to after an entry
#: script (`tools/dos/acceptance.py` `POD_AREA_VAR`); it read the loaded
#: script's area once live.
DARKNESS_AREA_VAR = 0x16

#: Each clock digit's radix, from variable 5 (`dos_savegame.POD_CLOCK`); a
#: real variable block has every digit below its radix.
POD_CLOCK = dos_savegame.POD_CLOCK
POD_CLOCK_RADIX = dos_savegame.POD_CLOCK_RADIX


@dataclasses.dataclass(frozen=True)
class ScriptGate:
    """One encounter roll: the area whose script holds it, the ECL address of
    its `RANDOM`, the short hash of the `GUARD_BYTES` it starts, and the
    `(offset, value)` bytes written over it."""

    area: int
    address: int
    guard: str
    changes: tuple[tuple[int, int], ...]
    grade: str
    source: str


#: `RANDOM` becomes `SAVE`, which stores the roll's limit.
_TO_SAVE = ((0, SAVE),)
#: `SAVE 0`, where the limit would land on the fight side.
_TO_ZERO = ((0, SAVE), (2, 0))


def _row(area: int, address: int, guard: str, source: str,
         changes: tuple[tuple[int, int], ...] = _TO_SAVE,
         grade: str = PROBABLE) -> ScriptGate:
    return ScriptGate(area, address, guard, changes, grade,
                      f"area {area} step entry, after its step counter: {source}")


#: Every `RANDOM`/`COMPARE`/`IF`/`EXIT` roll the step entry (entry 1) of a
#: `ECL1.DAX` area script reaches whose other side leads to `COMBAT`
#: (`dosnoencounters.py scan`), keyed by title.  Rolls of that kind whose
#: other side is only text or a `NEWECL` are left alone: area 16 `$8E8C`,
#: `$8EC8`; 22 `$8567`; 24 `$8AF0`, `$956F`, `$95AB`; 39 `$8B5C`, `$909C`;
#: 53 `$9903`; 54 `$8868`.  Rolls compared with a variable rather than a
#: constant (53 `$9313`, 69 `$9CE3`) are not covered.  PROBABLE: read from the
#: script; area 33's is CONFIRMED live.
SCRIPT_GATES: dict[str, tuple[ScriptGate, ...]] = {DARKNESS: (
    _row(16, 0x89A3, "0074b0e9", "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $8A15"),
    _row(17, 0x8BC7, "ab3e8354", "RANDOM 99 [191]; COMPARE 20, [191]; IF<= EXIT: 20 of 100 fight, COMBAT at $9470"),
    _row(19, 0x825E, "e5b5ee32", "RANDOM 99 [191]; COMPARE [191], 10; IF>= EXIT: 10 of 100 fight, COMBAT at $82DE"),
    _row(21, 0x8603, "0074b0e9", "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $9D7C"),
    _row(21, 0x86BE, "5137e3df", "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $9D7C"),
    _row(21, 0x9737, "f60fea4c", "RANDOM 99 [191]; COMPARE [191], 70; IF> $23: 71 of 100 fight, COMBAT at $96D5"),
    _row(22, 0x9B3E, "7dc31bbd", "RANDOM 99 [173]; COMPARE 3, [173]; IF<= EXIT: 3 of 100 fight, COMBAT at $9D54"),
    _row(25, 0x8371, "5aa8a7ca", "RANDOM 99 [191]; COMPARE 5, [191]; IF<= EXIT: 5 of 100 fight, COMBAT at $8A2A"),
    _row(26, 0x81EE, "e5b5ee32", "RANDOM 99 [191]; COMPARE [191], 10; IF>= EXIT: 10 of 100 fight, COMBAT at $826A"),
    _row(32, 0x82EA, "294a21bf", "RANDOM 99 [192]; COMPARE [192], 5; IF> EXIT: 6 of 100 fight, COMBAT at $835A"),
    _row(33, 0x830A, "6872c50c", "RANDOM 99 [160]; COMPARE [160], 5; IF> EXIT: 6 of 100 fight, COMBAT at $8405; "
         "live, step counter [159] staged to 24: 40 steps with it on and no encounter, against a "
         "control that met one on its 13th step", grade=CONFIRMED),
    _row(34, 0x8286, "5137e3df", "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $82D0"),
    _row(37, 0x8345, "5137e3df", "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $83E4"),
    _row(39, 0x8631, "5137e3df", "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $8699"),
    _row(40, 0x8178, "5137e3df", "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $81DF"),
    _row(50, 0x9C39, "4bf5e551", "RANDOM 99 [191]; COMPARE [191], 1; IF> EXIT: 2 of 100 fight, COMBAT at $9D33"),
    _row(51, 0x81D6, "ab3e8354", "RANDOM 99 [191]; COMPARE 20, [191]; IF<= EXIT: 20 of 100 fight, COMBAT at $843B"),
    _row(52, 0x87CA, "0074b0e9", "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $8820"),
    _row(54, 0x998C, "4bf5e551", "RANDOM 99 [191]; COMPARE [191], 1; IF> EXIT: 2 of 100 fight, COMBAT at $9A7D"),
    _row(64, 0x8724, "ab937717", "RANDOM 99 [191]; COMPARE 10, [191]; IF< EXIT: 11 of 100 fight, COMBAT at $9D8D"),
    _row(65, 0x912D, "e4a1c84c", "RANDOM 5 [192]; COMPARE [192], 0; IF!= EXIT: 1 of 6 fight, COMBAT at $8C24"),
    _row(66, 0x8B78, "0074b0e9", "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $8BD9"),
    _row(67, 0x83C5, "f939acc4", "RANDOM 20 [191]; COMPARE [191], 1; IF> EXIT: 2 of 21 fight, COMBAT at $844B"),
    _row(68, 0x84A5, "de9d6f13", "RANDOM 99 [191]; COMPARE 15, [191]; IF> EXIT: 85 of 100 fight, COMBAT at $8526", _TO_ZERO),
    _row(69, 0x8DDB, "2311e021", "RANDOM 99 [191]; COMPARE 10, [191]; IF<= EXIT: 10 of 100 fight, COMBAT at $8EB9"),
    _row(69, 0x8E62, "9e8efd2e", "RANDOM 50 [192]; COMPARE 10, [192]; IF<= EXIT: 10 of 51 fight, COMBAT at $8EB9"),
    _row(69, 0x8ED7, "2311e021", "RANDOM 99 [191]; COMPARE 10, [191]; IF<= EXIT: 10 of 100 fight, COMBAT at $8FB4"),
    _row(69, 0x8F5B, "d16971bd", "RANDOM 50 [192]; COMPARE 10, [192]; IF<= $23: 10 of 51 fight, COMBAT at $8FB4"),
    _row(71, 0x80E7, "de9d6f13", "RANDOM 99 [191]; COMPARE 15, [191]; IF> EXIT: 85 of 100 fight, COMBAT at $8145", _TO_ZERO),
    _row(80, 0x82C0, "ab3e8354", "RANDOM 99 [191]; COMPARE 20, [191]; IF<= EXIT: 20 of 100 fight, COMBAT at $8552"),
    _row(81, 0x9B9D, "22d64801", "RANDOM 99 [191]; COMPARE 5, [191]; IF< $23: 6 of 100 fight, COMBAT at $9C1B"),
    _row(82, 0x9BD3, "ac1a1459", "RANDOM 99 [192]; COMPARE 5, [192]; IF<= EXIT: 5 of 100 fight, COMBAT at $9CA4"),
)}


def digest(span: bytes) -> str:
    """The short hash a `ScriptGate` names its bytes by, so the table
    describes the script without holding it."""
    return hashlib.sha256(span).hexdigest()[:8]


class SaveBlocked(RuntimeError):
    """A game save was asked for while the switch could still be in the game."""


class SwitchError(RuntimeError):
    """A written word did not read back, or the array could not be found."""


def word_index(title: str, address: int) -> int:
    """The word index of one of `title`'s own script addresses."""
    index = address - CONTAINERS[title].var_base
    if not 0 <= index < BLOCK_WORDS:
        raise ValueError(f"${address:04X} is outside {title}'s first variable "
                         f"block")
    return index


class EncounterSwitch:
    """The switch's logic, over `peek(address) -> int` and `poke(address,
    value)` on the title's own script addresses and `area() -> int`.

    The caller brackets `apply` and `off` with whatever halts the machine.
    `log` takes one line of text.
    """

    def __init__(self, title: str, peek: Callable[[int], int],
                 poke: Callable[[int, int], None], area: Callable[[], int],
                 log: Callable[[str], None] = print):
        if title not in CONTAINERS:
            raise ValueError(f"no DOS variable array is known for {title!r}")
        self.title = title
        self.peek, self.poke, self.area, self.log = peek, poke, area, log
        self.active = False
        #: address -> (value before the first write, value written)
        self.held: dict[int, tuple[int, int]] = {}
        #: Gate words the game changed while held; not forced again until
        #: the next `on`.
        self.yielded: set[int] = set()
        #: Moves made in an area with no known gate.
        self.unsuppressed_moves = 0
        self._unsuppressed: set[int] = set()

    def on(self) -> None:
        self.active = True
        self.yielded = set()

    @property
    def pending(self) -> bool:
        """Whether a written value is still waiting to be put back."""
        return bool(self.held)

    def check_save(self) -> None:
        """Raise `SaveBlocked` while on, or while a write is outstanding."""
        if self.active or self.pending:
            raise SaveBlocked(
                "no_encounters is on or a value it wrote is still in the game; "
                "the gates are saved variables, so turn it off before saving")

    def _put(self, address: int, value: int) -> None:
        self.poke(address, value)
        got = self.peek(address)
        if got != value:
            raise SwitchError(f"${address:04X} read back {got:#06x} after "
                              f"writing {value:#06x}")

    def apply(self) -> list[dict]:
        """Write the running area's gate; what was written comes back."""
        if not self.active:
            return []
        area = self.area()
        gate = GATES.get((self.title, area))
        if gate is None:
            self.unsuppressed_moves += 1
            if area not in self._unsuppressed:
                self._unsuppressed.add(area)
                self.log(f"encounters are not suppressed in area ${area:02X}: "
                         "no gate is known for it")
            return []
        done = []
        for address, value in gate.pokes:
            if address in self.yielded:
                continue
            now = self.peek(address)
            if address not in self.held:
                self.held[address] = (now, value)
            elif now != self.held[address][1]:
                # The game wrote this word since the switch did: its value
                # is the one to keep, so the gate is no longer forced.
                self.held[address] = (now, now)
                self.yielded.add(address)
                self.log(f"the game changed ${address:04X} to {now} while "
                         "no_encounters held it; that value is kept and the "
                         "gate is no longer forced")
                done.append({"area": area, "address": f"${address:04X}",
                             "was": now, "yielded": True})
                continue
            if now == value:
                continue
            self._put(address, value)
            done.append({"area": area, "address": f"${address:04X}",
                         "was": now, "wrote": value})
        return done

    def off(self) -> list[dict]:
        """Put back every original the game has not changed since; the switch
        stays off.  A write that does not read back raises and stays pending."""
        self.active = False
        done = []
        for address, (original, written) in list(self.held.items()):
            now = self.peek(address)
            row = {"address": f"${address:04X}", "original": original,
                   "written": written, "now": now}
            if now == written and now != original:
                self._put(address, original)
                row["action"] = "restored"
            elif now == original:
                row["action"] = "already original"
            else:
                row["action"] = "kept the game's value"
            del self.held[address]
            done.append(row)
        return done


class LiveVariables:
    """The first variable block of a running DOS game and its current area,
    read and written through the DOSBox-X debugger.  Use it as a context
    manager: entering halts the machine and reads the block, leaving resumes
    it.

    The data segment is taken from `EV DS` at a halt and kept once the block
    it points at passes `check` (and, given the loaded save, agrees with its
    first block in `MATCH_FRACTION` of the bytes).  A halt that lands outside
    the game's code shows another `DS`; the machine is run and halted again,
    `DS_TRIES` times in all.
    """

    def __init__(self, session, title: str, save: bytes | None = None,
                 speculative: bool = False):
        self.s = session
        self.title = title
        self.engine = ENGINE[title]
        if self.engine.grade != CONFIRMED:
            if not speculative:
                raise SwitchError(
                    f"The {title} data-segment offsets have not been read in a "
                    "running game, so the switch needs speculative=True to "
                    "use them.")
            if save is None:
                raise SwitchError(
                    f"The {title} data-segment offsets have not been read in a "
                    "running game, so the switch needs the loaded save to "
                    "check the variable block against.")
        off = CONTAINERS[title].var_offset
        self.saved = save[off:off + 2 * BLOCK_WORDS] if save else None
        self.ds: int | None = None
        self.base: int | None = None
        self.found: dict = {}
        #: The array pointer as `SEG:OFF`, from the latest read.
        self.pointer: str | None = None
        self.block = b""
        self.area_byte = 0

    def __enter__(self):
        tried = []
        for _ in range(DS_TRIES):
            # The machine always runs between moves, so no probe comes first.
            # Any way out of this body but a return runs the machine again,
            # so an error never leaves the game halted in the debugger.
            try:
                if not self.s.attach():
                    raise SwitchError("The debugger did not halt the machine.")
                ds = self.ds if self.ds is not None else self.s.regs("DS")["DS"]
                why = self._read(ds)
            except BaseException:
                self.s.run()
                raise
            if why is None:
                if self.ds is None:
                    self.found = {"ds": f"{ds:04X}", "base": f"{self.base:#x}",
                                  "tries": len(tried) + 1,
                                  "pointer": self.pointer,
                                  "area": self.area_byte}
                self.ds = ds
                return self
            tried.append(f"DS {ds:04X}: {why}")
            self.ds = None
            self.s.run()
        raise SwitchError("no halt showed the game's data segment: "
                          + "; ".join(tried))

    def __exit__(self, *exc):
        self.s.run()
        return False

    def _read(self, ds: int) -> str | None:
        """Read the block and the area through `ds`; why not, or None."""
        ptr = self.s.read((ds, self.engine.pointer), 4)
        off, seg = int.from_bytes(ptr[:2], "little"), int.from_bytes(ptr[2:], "little")
        base = dosboxx.linear((seg, off))
        if seg == 0 or base + 2 * BLOCK_WORDS > 0x100000:
            return f"the array pointer reads {seg:04X}:{off:04X}"
        self.base = base
        self.pointer = f"{seg:04X}:{off:04X}"
        self.block = self.s.read(base, 2 * BLOCK_WORDS)
        why = self.check()
        if why is None and not any(self.block):
            why = "the variable block is all zeros"
        if why is None and self.saved is not None:
            same = sum(a == b for a, b in zip(self.block, self.saved))
            if same < MATCH_FRACTION * len(self.saved):
                why = f"{same} of {len(self.saved)} bytes match the save"
        if why is None:
            self.area_byte = self.s.read((ds, self.engine.area), 1)[0]
        return why

    def check(self) -> str | None:
        """The six clock digits are small numbers in a real array, with high
        bytes of zero; why not, or None."""
        words = [self._word(i) for i in range(CLOCK_INDEX, CLOCK_INDEX + 6)]
        if any(w >= 60 for w in words):
            return f"the clock digits read {words}"
        return None

    def _word(self, index: int) -> int:
        return int.from_bytes(self.block[2 * index:2 * index + 2], "little")

    def area(self) -> int:
        return self.area_byte

    def peek(self, address: int) -> int:
        return self._word(word_index(self.title, address))

    def poke(self, address: int, value: int) -> None:
        index = word_index(self.title, address)
        at = self.base + 2 * index
        self.s.write(at, value.to_bytes(2, "little"))
        got = self.s.read(at, 2)
        block = bytearray(self.block)
        block[2 * index:2 * index + 2] = got
        self.block = bytes(block)


class ScriptSwitch:
    """The Pools of Darkness switch's logic, over `read(address, n) -> bytes`
    and `write(address, data)` on the loaded script's ECL addresses and
    `area() -> int`.  `EncounterSwitch`'s interface: the caller brackets
    `apply` and `off` with whatever halts the machine."""

    def __init__(self, title: str, read: Callable[[int, int], bytes],
                 write: Callable[[int, bytes], None], area: Callable[[], int],
                 log: Callable[[str], None] = print):
        if title not in SCRIPT_GATES:
            raise ValueError(f"no script gates are known for {title!r}")
        self.title = title
        self.rows = SCRIPT_GATES[title]
        self.read, self.write, self.area, self.log = read, write, area, log
        self.active = False
        #: address -> (bytes before the change, bytes written)
        self.held: dict[int, tuple[bytes, bytes]] = {}
        #: Never filled: the switch writes the script, which the game never
        #: changes, so nothing yields.  `NoEncounters` reads it.
        self.yielded: set[int] = set()
        #: Moves made with no row's roll in the loaded script.
        self.unsuppressed_moves = 0
        self._unsuppressed: set[int] = set()
        self.low = min(r.address for r in self.rows)
        self.high = max(r.address for r in self.rows) + GUARD_BYTES

    def on(self) -> None:
        self.active = True

    @property
    def pending(self) -> bool:
        return bool(self.held)

    def check_save(self) -> None:
        if self.active or self.pending:
            raise SaveBlocked(
                "no_encounters is on or a script byte it wrote is still in the "
                "game; turn it off before saving")

    def _put(self, address: int, data: bytes, original: bytes) -> None:
        self.write(address, data)
        got = self.read(address, len(data))
        if got != data:
            self.write(address, original[:len(data)])
            raise SwitchError(f"${address:04X} read back {got.hex()} after "
                              f"writing {data.hex()}")

    def apply(self) -> list[dict]:
        """Change every row whose roll is in the loaded script; what was
        written comes back."""
        if not self.active:
            return []
        script = self.read(self.low, self.high - self.low)
        done, loaded = [], False
        area = self.area()
        for row in self.rows:
            if row.area != area:
                # Rows can share a guard; only the running area's own row
                # is the roll that script holds.
                self.held.pop(row.address, None)
                continue
            at = row.address - self.low
            now = script[at:at + GUARD_BYTES]
            held = self.held.get(row.address)
            if held is not None and now == held[1]:
                loaded = True
                continue
            if digest(now) != row.guard:
                # Another script is loaded: nothing of this row is there.
                self.held.pop(row.address, None)
                continue
            loaded = True
            new = bytearray(now)
            for offset, value in row.changes:
                new[offset] = value
            new = bytes(new)
            self._put(row.address, new[:3], now)
            self.held[row.address] = (now, new)
            done.append({"area": row.area, "address": f"${row.address:04X}",
                         "was": now[:3].hex(), "wrote": new[:3].hex()})
        if not loaded:
            self.unsuppressed_moves += 1
            if area not in self._unsuppressed:
                self._unsuppressed.add(area)
                self.log(f"encounters are not suppressed in area {area}: no "
                         "known roll is in its script")
        return done

    def off(self) -> list[dict]:
        """Put back every statement still holding the switch's bytes; the
        switch stays off."""
        self.active = False
        done = []
        for address, (original, written) in list(self.held.items()):
            now = self.read(address, GUARD_BYTES)
            row = {"address": f"${address:04X}", "original": original[:3].hex(),
                   "written": written[:3].hex(), "now": now[:3].hex()}
            if now == written:
                self._put(address, original[:3], written)
                row["action"] = "restored"
            elif now == original:
                row["action"] = "already original"
            else:
                row["action"] = "another script is loaded"
            del self.held[address]
            done.append(row)
        return done


class LiveScript:
    """Pools of Darkness' loaded script and variables in a running game,
    through the DOSBox-X debugger: `LiveVariables`' context manager, over the
    two far pointers of `SCRIPT_ENGINE`.

    A data segment is believed when its script pointer leads to a block that
    opens with the five entry `GOTO`s and its variable pointer to a block
    whose clock digits are each below their radix (and, given the loaded
    save, which agrees with it in `MATCH_FRACTION` of its bytes).
    """

    def __init__(self, session, title: str, save: bytes | None = None):
        self.s = session
        self.title = title
        self.engine = SCRIPT_ENGINE[title]
        self.saved = save[:dos_savegame.POD_VAR_COUNT] if save else None
        self.ds: int | None = None
        self.found: dict = {}
        self.script_base: int | None = None
        self.var_base: int | None = None
        self.block = b""

    def __enter__(self):
        tried = []
        for n in range(DS_TRIES):
            # As `LiveVariables`: any way out but a return runs the machine.
            try:
                if not self.s.attach():
                    raise SwitchError("The debugger did not halt the machine.")
                ds = self.ds if self.ds is not None else self.s.regs("DS")["DS"]
                why = self._read(ds)
            except BaseException:
                self.s.run()
                raise
            if why is None:
                if self.ds is None:
                    self.found["tries"] = n + 1
                self.ds = ds
                return self
            tried.append(f"DS {ds:04X}: {why}")
            self.ds = None
            self.s.run()
        raise SwitchError("no halt showed the game's data segment: "
                          + "; ".join(tried))

    def __exit__(self, *exc):
        self.s.run()
        return False

    def _pointer(self, ds: int, offset: int) -> tuple[int, str] | None:
        raw = self.s.read((ds, offset), 4)
        off, seg = int.from_bytes(raw[:2], "little"), int.from_bytes(raw[2:], "little")
        base = dosboxx.linear((seg, off))
        if seg == 0 or base + 0x2000 > 0x100000:
            return None
        return base, f"{seg:04X}:{off:04X}"

    def _read(self, ds: int) -> str | None:
        """Read the variable block through `ds`; why not, or None."""
        script = self._pointer(ds, self.engine.script)
        variables = self._pointer(ds, self.engine.variables)
        if script is None or variables is None:
            return "a far pointer reads 0 or past the first megabyte"
        head = self.s.read(script[0], 20)
        if any(head[4 * n] != 0x01 or head[4 * n + 3] < SCRIPT_BASE >> 8
               for n in range(5)):
            return f"the script pointer {script[1]} leads to {head.hex()}"
        self.block = self.s.read(variables[0], dos_savegame.POD_VAR_COUNT)
        why = self.check()
        if why is None and self.saved is not None:
            same = sum(a == b for a, b in zip(self.block, self.saved))
            if same < MATCH_FRACTION * len(self.saved):
                why = f"{same} of {len(self.saved)} bytes match the save"
        if why is None:
            self.script_base, self.var_base = script[0], variables[0]
            if self.ds is None:
                self.found = {"ds": f"{ds:04X}", "pointer": script[1],
                              "variables": variables[1], "area": self.area(),
                              "base": f"{script[0]:#x}"}
        return why

    def check(self) -> str | None:
        digits = self.block[POD_CLOCK - 1:POD_CLOCK - 1 + len(POD_CLOCK_RADIX)]
        if any(d >= r for d, r in zip(digits, POD_CLOCK_RADIX)):
            return f"the clock digits read {list(digits)}"
        return None

    def area(self) -> int:
        return self.block[DARKNESS_AREA_VAR - 1]

    def read(self, address: int, n: int) -> bytes:
        return self.s.read(self.script_base + address - SCRIPT_BASE, n)

    def write(self, address: int, data: bytes) -> None:
        self.s.write(self.script_base + address - SCRIPT_BASE, data)


def find_data_segments(image: bytes, base: int, pointer: int) -> list[int]:
    """Every data segment whose `pointer` offset holds a far pointer to
    `base` in a memory image: a check of `ENGINE` that needs no halt in the
    game's own code."""
    out = []
    for seg in range(max(0, (base - 0xFFFF + 15) >> 4), min(0xFFFF, base >> 4) + 1):
        off = base - (seg << 4)
        needle = off.to_bytes(2, "little") + seg.to_bytes(2, "little")
        at = image.find(needle)
        while at >= 0:
            if (at - pointer) % 16 == 0 and at >= pointer:
                out.append((at - pointer) >> 4)
            at = image.find(needle, at + 1)
    return sorted(set(out))


class NoEncounters:
    """What a driver holds: the switch over a running game's variables.
    `save` is the loaded saved game's bytes, which `LiveVariables` checks the
    live block against; without it only a title whose `ENGINE` row is
    CONFIRMED is accepted, and the clock check decides.  `speculative` allows
    a title whose row is not, which then needs `save`.  A title in
    `SCRIPT_GATES` gets `LiveScript` and `ScriptSwitch` instead."""

    def __init__(self, session, title: str, save: bytes | None = None,
                 log: Callable[[str], None] = print, speculative: bool = False):
        if title in SCRIPT_GATES:
            self.live = LiveScript(session, title, save)
            self.switch = ScriptSwitch(title, self.live.read, self.live.write,
                                       self.live.area, log)
        else:
            self.live = LiveVariables(session, title, save, speculative)
            self.switch = EncounterSwitch(title, self.live.peek, self.live.poke,
                                          self.live.area, log)
        self.writes: list[dict] = []
        #: How many moves found the party in each area.
        self.areas: dict[int, int] = {}
        #: How many times a restore re-armed the switch.
        self.resets = 0
        #: Which arming the switch is in: 1 from the start, plus one per reset.
        self.arming = 1
        #: Every gate word the game took back, across resets, with the arming
        #: it happened in; `EncounterSwitch.yielded` is cleared by each one.
        self.yield_history: list[dict] = []

    def on(self) -> None:
        self.switch.on()

    def reset(self) -> None:
        """Forget what was written and re-arm.  For a restored machine, whose
        memory holds the originals again: a gate word read back as its original
        would otherwise look like a change by the game."""
        self.switch.held.clear()
        self.switch.on()
        self.resets += 1
        self.arming += 1

    def before_move(self) -> list[dict]:
        """Write the gate; a no-op while the switch is off."""
        if not self.switch.active:
            return []
        with self.live:
            done = self.switch.apply()
            area = self.live.area()
        self.areas[area] = self.areas.get(area, 0) + 1
        self.writes += done
        self.yield_history += [
            {"arming": self.arming, "area": row["area"],
             "address": row["address"], "value": row["was"]}
            for row in done if row.get("yielded")]
        return done

    def off(self) -> list[dict]:
        if not self.switch.pending:
            return self.switch.off()
        with self.live:
            return self.switch.off()

    def check_save(self) -> None:
        self.switch.check_save()

    def report(self) -> dict:
        """What the switch read and wrote, for a run's `summary.json`: the
        pointer and area read on load, each gate write, the areas the moves
        were made in, and what yielded or was left unsuppressed."""
        found = self.live.found
        return {
            "pointer": found.get("pointer"),
            "area_on_load": found.get("area"),
            "data_segment": found.get("ds"),
            "writes": [{"area": w["area"], "address": w["address"],
                        "before": w["was"], "after": w["wrote"]}
                       for w in self.writes if "wrote" in w],
            "areas": {f"${a:02X}": n for a, n in sorted(self.areas.items())},
            "unsuppressed_moves": self.switch.unsuppressed_moves,
            "yielded": list(self.yield_history),
            "resets": self.resets,
        }


class SuppressedPool(dosbox.PoolOfRadiance):
    """`dosbox.PoolOfRadiance` with the switch written before every move key
    and checked before every save."""

    def __init__(self, session, encounters: NoEncounters):
        super().__init__(session)
        self.encounters = encounters

    def move(self, key: str, timeout: float = 20.0) -> bool:
        self.encounters.before_move()
        return super().move(key, timeout)

    def save_game(self, letter: str, timeout: float = 60.0) -> bytes:
        self.encounters.check_save()
        return super().save_game(letter, timeout)


# --------------------------------------------------------------------------
# The live check: one boot, a walk with the switch on, a restore, a control
# --------------------------------------------------------------------------

def pool_answer(por: dosbox.PoolOfRadiance) -> tuple[str, str | None]:
    """Pool of Radiance's bars after a move that did not come back: `met` at
    an encounter's or, after answering a `PRESS RETURN`, a combat bar's,
    `cleared` after answering a locked door or a `YES NO`, and `stuck` at
    anything else."""
    from tools.dos import dosfightwatch as fw

    kind, resolved = fw._await_bar(por, 90.0)
    if not resolved:
        return "stuck", kind
    if kind in fw.FIGHT_BARS:
        return "met", kind
    key = fw.LOCKED_EXIT_KEY if kind == "locked" else por.COMBAT_KEYS.get(kind or "")
    if key is None:
        return "stuck", kind
    por.s.key(key)
    # A `PRESS RETURN` that opens a fight leads to its command bar, not to the
    # map: a combat bar after the key is a fight, and the walk stops there.
    deadline = time.time() + 20.0
    while time.time() < deadline:
        screen, bar = fw._grab(por)
        if screen is not None:
            if screen.ink(dosbox.BAR) == (por.world_bar or ""):
                return "cleared", kind
            if bar in fw.FIGHT_BARS:
                return "met", "fight"
        time.sleep(0.25)
    return "stuck", kind


def later_load(por: dosbox.PoolOfRadiance, letter: str) -> None:
    """Curse's load: `LOAD SAVED GAME`, the slot, the party menu, `BEGIN
    ADVENTURING`, and Return past its continue screens to the map, as
    `acceptance.Driver.load` and `begin` do."""
    from tools.dos import acceptance as acc

    s = por.s
    por.to_main_menu()
    s.settle(quiet=0.6, timeout=20.0)
    s.key(acc.PARTY_LOAD)
    s.settle(quiet=0.6, timeout=20.0)
    s.key(letter.lower())
    screen = s.settle(quiet=1.0, timeout=90.0)
    if acc.bar_signature(screen) != acc.CURSE_PARTY_BAR:
        raise RuntimeError(f"slot {letter} did not reach the party menu: "
                           f"{acc.bar_signature(screen)}")
    s.key(acc.PARTY_BEGIN)
    screen = s.settle(quiet=1.0, timeout=60.0)
    for _ in range(acc.CONTINUE_ROUNDS):
        if screen.glyphs(dosbox.BAR) != acc.CURSE_CONTINUE_BAR:
            break
        s.key(acc.POD_CONTINUE)
        screen = s.settle(quiet=1.0, timeout=60.0)
    por.record_map(screen)


def install_slot(folder: Path, save_dir: Path, source: str | None) -> str:
    """Install the slot `source` of `folder` (the only one, when None) into
    `save_dir`, as `acceptance.run` does, and return its letter."""
    from tools.dos import staging

    slot = staging.source_slot(folder, source)
    return staging.install(folder, save_dir, slot, source)["as_slot"]


def load_title(title: str, s, por: dosbox.PoolOfRadiance, enc: NoEncounters,
               letter: str) -> None:
    """Load slot `letter` and reach the map, by the title's own path: Pool's
    `load_game`, Silver Blades' `acceptance.Driver` load and begin, and
    Curse's `later_load`."""
    if title == POOL:
        por.to_main_menu()
        por.load_game(letter)
    elif title == SILVER:
        from tools.dos import acceptance as acc

        d = acc.Driver(s, lambda **kw: None, letter, "ssb", encounters=enc)
        d.load()
        d.begin()
    else:
        later_load(por, letter)


def later_answer(por: dosbox.PoolOfRadiance,
                 patience: float = 60.0) -> tuple[str, str | None]:
    """Curse's and Silver Blades' bars after a move that did not come back:
    `met` at an encounter or combat bar, `cleared` once the map is back after
    answering `YES NO`, a locked door, a continue or a treasure bar by
    `acceptance.FIGHT_KEYS`, and `stuck` at anything else."""
    from tools.dos import acceptance as acc

    kind = None
    deadline = time.time() + patience
    while time.time() < deadline:
        try:
            screen = por.s.capture()
        except dosboxx.NotLineDoubled:
            time.sleep(0.25)
            continue
        if por.on_map(screen):
            return "cleared", kind
        kind = acc.fight_bar_kind(screen)
        if kind in ("encounter", "command"):
            return "met", kind
        if kind in ("yes_no", "locked", "continue", "treasure", "treasure_left"):
            por.s.key(acc.FIGHT_KEYS[kind])
            por.s.settle(quiet=0.6, timeout=20.0)
            continue
        time.sleep(0.5)
    return "stuck", kind


def explore_walk(por: dosbox.PoolOfRadiance, steps: int, shot,
                 answer=None) -> dict:
    """Walk until the square under the party has changed `steps` times,
    preferring squares not yet stood on (`acceptance.Explorer`).  A move that
    does not come back to the map bar is given to `answer`, which says `met`,
    `cleared` or `stuck`; with no `answer` the walk stops there."""
    from tools.dos import screens
    from tools.dos.acceptance import Explorer

    ex = Explorer()
    started = time.time()

    def square() -> str | None:
        return screens.status_square(por.s.settle())

    def result(**more) -> dict:
        return {"steps": ex.steps, "bumps": ex.bumps, "moves": moves,
                "squares": len(ex.visits),
                "seconds": round(time.time() - started, 1), **more}

    def stopped(at: str) -> dict | None:
        kind = None
        verdict = "stuck"
        if answer is not None:
            verdict, kind = answer(por)
        if verdict == "cleared":
            ex.at(square())
            return None
        return result(met=verdict == "met", stop=verdict, bar=kind,
                      shot=shot(f"{at}-{moves}"))

    ex.at(square())
    moves = 0
    while ex.steps < steps and moves < steps * 6:
        try:
            d = ex.choose()
        except Exception as e:
            return result(met=False, stop=str(e))
        for k in ex.turn_keys(d):
            moves += 1
            if not por.move(k):
                done = stopped("turn")
                if done:
                    return done
            ex.turned(k)
        ex.stepping()
        moves += 1
        if por.step():
            ex.stepped(square())
            continue
        done = stopped("step")
        if done:
            return done
    return result(met=False, stop="walked")


def live(title: str, folder: Path, steps: int, out: Path,
         source: str | None = None, stage: list[tuple[int, int]] = (),
         speculative: bool = False) -> dict:
    """One boot: load, snapshot, a walk with the switch on, `off`, restore the
    snapshot, and a control walk with it off.  Evidence goes under `out`."""
    from tools.dos import dossnapshot, staging

    out = scratch.ensure(out)
    report: dict = {"title": title, "folder": str(folder), "steps": steps}

    def checkpoint() -> None:
        (out / "report.json").write_text(json.dumps(report, indent=1,
                                                    default=str))

    game = dosbox.find_game(STEMS[title])
    answer = pool_answer if title == POOL else later_answer
    with dosboxx.claim(f"dosnoencounters {title}") as slot:
        s = dossnapshot.SnapshotSession(
            slot, game, snapshot_dir=out / "snapshots")
        try:
            def shot(name: str) -> str:
                dest = out / f"{name}.png"
                shutil.copyfile(s.shot(name, allow_blank=True), dest)
                return str(dest)

            s.stage(fresh=True)
            letter = install_slot(folder, s.save_dir, source)
            report["staged"] = [staging.stage_var(s.save_dir, letter, a, v)
                                for a, v in stage]
            save = s.save_file(letter).read_bytes()
            report["saved_area"] = dosbox.current_area(save)
            gate = GATES.get((title, report["saved_area"]))
            report["gate"] = dataclasses.asdict(gate) if gate else None
            addresses = [a for a, _ in gate.pokes] if gate else []
            lines: list[str] = []
            enc = NoEncounters(s, title, save, log=lines.append,
                               speculative=speculative)
            por = SuppressedPool(s, enc)

            def gates_now() -> dict:
                with enc.live:
                    return {"area": enc.live.area(),
                            **{f"${a:04X}": enc.live.peek(a) for a in addresses}}

            started = time.time()
            s.boot(fresh=False)
            load_title(title, s, por, enc, letter)
            report["boot_seconds"] = round(time.time() - started, 1)
            shot("loaded")
            # The engine's pointer, found from the memory image and the save,
            # beside what `EV DS` at a halt gave.
            if not s.attach():
                raise SwitchError("the debugger did not halt the machine")
            image = s.read(0, 0x100000)
            s.run()
            off = CONTAINERS[title].var_offset
            found = dosboxx.locate(image, save[off:off + 2 * BLOCK_WORDS])
            report["image"] = None if found is None else {
                "base": f"{found[0]:#x}", "votes": found[1],
                "matching": f"{found[2]}/{2 * BLOCK_WORDS}",
                "data_segments": [f"{d:04X}" for d in find_data_segments(
                    image, found[0], ENGINE[title].pointer)]}
            checkpoint()
            try:
                report["at_load"] = gates_now()
            except SwitchError as e:
                report["at_load"] = f"EV DS: {e}"
                segments = find_data_segments(image, found[0], ENGINE[title].pointer) \
                    if found else []
                if not segments:
                    raise
                enc.live.ds = segments[0]
                report["at_load_from_image"] = gates_now()
            report["data_segment"] = enc.live.found or {"ds": f"{enc.live.ds:04X}"}
            s.snapshot("start")

            enc.on()
            try:
                por.save_game(letter)
                report["save_while_on"] = "not stopped"
            except SaveBlocked as e:
                report["save_while_on"] = f"stopped: {e}"
            checkpoint()

            report["on_walk"] = explore_walk(por, steps, shot, answer)
            report["on_writes"] = enc.writes
            report["on_areas"] = {f"${a:02X}": n for a, n in enc.areas.items()}
            report["unsuppressed"] = lines
            report["on_unsuppressed_moves"] = enc.switch.unsuppressed_moves
            report["on_yielded"] = sorted(f"${a:04X}" for a in enc.switch.yielded)
            shot("on-end")
            checkpoint()
            report["on_end"] = gates_now()
            report["off"] = enc.off()
            report["after_off"] = gates_now()
            checkpoint()

            report["changed_saves"] = s.restore("start")
            s.settle()
            report["after_restore"] = gates_now()
            report["control_walk"] = explore_walk(por, steps, shot, answer)
            shot("control-end")
            s.discard_snapshot("start")
        finally:
            if s.log.is_file():
                shutil.copyfile(s.log, out / "dbg.log")
            s.close()
    checkpoint()
    return report


#: `IF` opcodes and what each tests of `COMPARE a, b`: "a c b".
CONDITIONS = {0x16: lambda a, b: a == b, 0x17: lambda a, b: a != b,
              0x18: lambda a, b: a < b, 0x19: lambda a, b: a > b,
              0x1A: lambda a, b: a <= b, 0x1B: lambda a, b: a >= b}
#: Opcodes nothing runs after: `EXIT`, `GOTO`, `RETURN`, `NEWECL`, and Pools
#: of Darkness' `$23`, which clears the text window and exits.
SCRIPT_STOPS = {0x00, 0x01, 0x13, 0x20, 0x23}
COMBAT = 0x24


def darkness_scripts(game: Path | None = None) -> dict[int, bytes]:
    """Every area script of DOS Pools of Darkness' `ECL1.DAX`, by area, as
    the buffer holds it: the block without its two-byte header."""
    from tools.dos import dospod

    game = game or dospod.find_game(STEMS[DARKNESS])
    dax = (game / "ECL1.DAX").read_bytes()
    return {area: body[2:] for area, body in dos_savegame.dax_blocks(dax, "ECL1.DAX")}


def roll_exit(model, body: bytes, at: int):
    """The roll at `at` if it is `RANDOM n, [v]`, `COMPARE` of `[v]` with a
    constant, an `IF` and an `EXIT` (or `$23`): `(limit, exits, end)`, where
    `exits(r)` says whether a roll of `r` takes the `EXIT`; else None."""
    from tools.amiga import tripspace as ts

    roll = ts.decode(model, body, at)
    if roll is None or roll.op != RANDOM or roll.operands[0][0] != 0:
        return None
    compare = ts.decode(model, body, roll.end)
    if compare is None or compare.op != 0x03 or roll.operands[1] not in compare.operands:
        return None
    condition = ts.decode(model, body, compare.end)
    if condition is None or condition.op not in CONDITIONS:
        return None
    exit_ = ts.decode(model, body, condition.end)
    if exit_ is None or exit_.op not in (0x00, 0x23):
        return None
    (ka, va), (kb, vb) = compare.operands
    variable = roll.operands[1]
    if (kb, vb) != variable and kb != 0 or (ka, va) != variable and ka != 0:
        return None

    def exits(r: int) -> bool:
        a = r if (ka, va) == variable else va
        b = r if (kb, vb) == variable else vb
        return CONDITIONS[condition.op](a, b)
    return roll.operands[0][1], exits, exit_.end


def scan_darkness(game: Path | None = None) -> list[dict]:
    """Every roll of `roll_exit`'s kind that a Pools of Darkness area's step
    entry reaches, with the `SAVE` constant that takes its `EXIT`, how many
    rolls fight, and the first `COMBAT` a walk of its other side meets.

    The scripts are walked with the operand counts of the Amiga Pools of
    Darkness executable's skip switch (`tools/amiga/tripspace.py`), since the
    DOS scripts are the same language."""
    from tools.amiga import amigasaves
    from tools.amiga import tripspace as ts
    from tools.amiga.amiga68k import Executable

    models = set()
    for _t, _label, _path, body in ts.disk_files(
            amigasaves.images(), {ts.DARKNESS: ts.EXECUTABLE[ts.DARKNESS]}):
        try:
            model = ts.skip_model(Executable.parse(body).data)
        except Exception:                       # a packed or foreign file
            model = None
        if model:
            models.add(model)
    if len(models) != 1:
        raise SwitchError(f"{len(models)} Amiga Pools of Darkness operand "
                          "models found; the scan needs exactly one")
    skip = next(iter(models))
    model = tuple(skip)
    listed = {(r.area, r.address) for r in SCRIPT_GATES[DARKNESS]}
    out = []
    for area, body in sorted(darkness_scripts(game).items()):
        found, _bad = ts.walk(ts.DARKNESS, model, skip, body, entries=[1])
        for at in sorted(found):
            got = roll_exit(model, body, at)
            if got is None:
                continue
            limit, exits, end = got
            save = limit if exits(limit) else 0 if exits(0) else None
            out.append({"area": area, "address": SCRIPT_BASE + at,
                        "guard": digest(body[at:at + GUARD_BYTES]),
                        "save": save,
                        "fights": f"{sum(not exits(r) for r in range(limit + 1))}"
                                  f"/{limit + 1}",
                        "combat": _first_combat(model, skip, body, end),
                        "listed": (area, SCRIPT_BASE + at) in listed})
    return out


def _first_combat(model, skip, body: bytes, start: int, limit: int = 2000) -> int | None:
    """The ECL address of the first `COMBAT` a breadth-first walk from
    `start` meets, or None."""
    from tools.amiga import tripspace as ts

    seen, work = set(), [start]
    while work and len(seen) < limit:
        i = work.pop(0)
        if i in seen:
            continue
        s = ts.decode(model, body, i)
        if s is None:
            continue
        seen.add(i)
        if s.op == COMBAT:
            return SCRIPT_BASE + i
        if s.op in (0x01, 0x02) and s.address(0) is not None:
            work.append(s.address(0) - SCRIPT_BASE)
        if s.op in (ts.ONGOTO, ts.ONGOSUB):
            work += [s.address(k) - SCRIPT_BASE for k in range(2, len(s.operands))
                     if s.address(k) is not None]
        if s.op not in SCRIPT_STOPS:
            work.append(s.end)
        if s.op in CONDITIONS:
            skipped = ts.decode(skip, body, s.end)
            if skipped is not None:
                work.append(skipped.end)
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("gates", help="print the gate table")
    sub.add_parser("scan", help="list every Pools of Darkness step-entry "
                   "roll in ECL1.DAX and whether a fight is on its other side")
    run = sub.add_parser("live", help="one boot: a walk with the switch on, "
                         "then a control walk with it off")
    run.add_argument("--title", choices=sorted(CONTAINERS), default=POOL)
    run.add_argument("--folder", type=Path, required=True,
                     help="a DOS save folder standing in an encounter area")
    run.add_argument("--from-slot", help="the slot to install, if several")
    run.add_argument("--steps", type=int, default=40,
                     help="squares to walk in each of the two walks")
    run.add_argument("--stage-var", action="append", default=[],
                     metavar="ADDRESS=VALUE", help="a script word written into "
                     "the save before the boot, hex address and decimal value")
    run.add_argument("--speculative", action="store_true",
                     help="use a title whose data-segment offsets have not "
                     "been read in a running game")
    run.add_argument("--out", type=Path, help="evidence directory (default "
                     "~/.cache/wish/noencounters/dos-<title>)")
    args = ap.parse_args(argv)

    if args.command == "gates":
        for (title, area), gate in sorted(GATES.items()):
            pokes = ", ".join(f"${a:04X}={v}" for a, v in gate.pokes) or "none"
            print(f"{title:28} ${area:02X}  {gate.grade:9} {pokes:24} {gate.source}")
        for title, rows in SCRIPT_GATES.items():
            for row in rows:
                change = " ".join(f"+{o}={v:02X}" for o, v in row.changes)
                print(f"{title:28} {row.area:3} ${row.address:04X} {row.grade:9} "
                      f"{row.guard} {change:12} {row.source}")
        return 0
    if args.command == "scan":
        for found in scan_darkness():
            print(f"area {found['area']:3} ${found['address']:04X} {found['guard']} "
                  f"SAVE {found['save']} {found['fights']} "
                  f"{'COMBAT at $%04X' % found['combat'] if found['combat'] else 'no COMBAT'}"
                  f"{'  (in SCRIPT_GATES)' if found['listed'] else ''}")
        return 0

    stage = []
    for text in args.stage_var:
        address, value = text.split("=")
        stage.append((int(address, 16), int(value)))
    out = args.out or scratch.cache_dir("noencounters", f"dos-{args.title}")
    report = live(args.title, args.folder, args.steps, out,
                  args.from_slot, stage, args.speculative)
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
