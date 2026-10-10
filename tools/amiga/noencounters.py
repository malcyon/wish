"""The Amiga `no_encounters` switch: which script bytes to change, and keeping them changed.

Every Amiga title decides a random encounter in the loaded area script, with a
`RANDOM` statement (opcode `$08`) whose result is compared and branched on.
Changing the opcode to `SAVE` (`$09`) stores the constant instead of a roll, so
the comparison always goes the common way and fixed square fights, which roll
nothing, are untouched.  A script is reloaded on an area change, a crossing and a
saved-game load, so a roll is recognised by a short hash of its statement at the roll
address and changed again whenever a reload brings it back.

The saved game carries the loaded script for Pool and Curse, so
`no_encounters off` comes before any save; it stays off until turned on again.
The Pools of Darkness save holds no script, but `off` still comes first there:
with the switch on, each patched `SAVE` leaves its constant (mostly 99) in the
roll's variable and skips resetting the step counter, and that save stores
those variables.  `off` restores the script, not them.  Its SPECULATIVE rest
row also writes variable `$2C`, which the save stores.

A row applies only while its area's script is loaded, so `on` reports every
row of an area that is not loaded as stopped and writes nothing for it; `keys`
applies the rows again before each key press and changes the row once its
area loads.  A gate that names its `area` is also checked against the loaded
script's entry table, because Silver Blades does not clear the buffer before a
load: a short script leaves an earlier area's roll in place past its end.
A `none` row names a script that makes no random-encounter roll, recognised by
its entry table, so that while it is loaded the reply names the script as
having no random roll, beside the stopped rows instead of leaving them to read
as a failure.

The class does no I/O of its own: the driver hands it `resolve`, `read` and
`write`, so it runs against a fake, and a `journal` callback that is given
every change still to be put back, before each write and after each restore,
so a driver killed outright leaves a record a later run can repair from.

`WinuaeEncounters` is the same switch under WinUAE, through the debugger pipe,
and `main` is its command line:

    tools/amiga/noencounters.py --holder H --title pool-of-radiance on
    tools/amiga/noencounters.py --holder H keys NP8 NP8 NP2
    tools/amiga/noencounters.py --holder H off
"""

import dataclasses
import hashlib
import json
import os
import pathlib
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import amiga  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: How sure a row is.  CONFIRMED has been run live; PROBABLE was read from the
#: script or the engine and matches a confirmed case; SPECULATIVE is an address
#: nobody has seen hold the value yet.
CONFIRMED, PROBABLE, SPECULATIVE = "CONFIRMED", "PROBABLE", "SPECULATIVE"

GATE, REST, NONE = "gate", "rest", "none"


#: The opcode a roll starts with, and what it is changed to: `SAVE` takes the
#: same operands and stores the constant instead of a roll.
RANDOM, SAVE = 0x08, 0x09

#: A roll statement is six bytes: the opcode, its constant and its variable.
STATEMENT = 6

#: A script starts with its five entry `GOTO`s, four bytes each; their targets
#: tell one area's script from another's.
ENTRY_TABLE = 20


def digest(statement: bytes) -> str:
    """The short hash a row names its roll by, so the table describes the
    statement without holding it."""
    return hashlib.sha256(statement).hexdigest()[:8]


@dataclasses.dataclass(frozen=True)
class Row:
    """One place to change.

    `spec` is a `peek` spec for the first byte.  A gate is recognised as loaded
    when the `STATEMENT` bytes there hash to `digest`; `changes` are `(offset, value)` pairs written
    over the bytes read there, whose originals the switch keeps itself.  A rest
    row has no `changes`: it holds the bytes of `new` where the game writes a
    chance, and puts back what it read.  A none row's `spec` is the script's
    first byte and `digest` the hash of its `ENTRY_TABLE` bytes; it writes
    nothing.  A gate's `area`, when set, is that hash for the script the roll
    belongs to, and the gate applies only while that script is loaded.
    """

    title: str
    kind: str
    spec: str
    digest: str
    changes: tuple[tuple[int, int], ...]
    new: bytes
    grade: str
    source: str
    area: str = ""


_TO_SAVE = ((0, SAVE),)


def _gate(title, spec, digest, grade, source, changes=_TO_SAVE, area=""):
    return Row(title, GATE, spec, digest, changes, b"", grade, source, area)


def _rest(title, spec, new, grade, source):
    return Row(title, REST, spec, "", (), bytes.fromhex(new), grade, source)


def _none(title, spec, digest, grade, source):
    return Row(title, NONE, spec, digest, (), b"", grade, source)


def length(row: Row) -> int:
    """How many bytes the switch reads at a row's address."""
    return {GATE: STATEMENT, NONE: ENTRY_TABLE}.get(row.kind, len(row.new))


#: Where a script starts in the buffer a spec's pointer gives: Pool's
#: `ecl.dax` at its first byte, the other titles' at ECL address `$8000`.
SCRIPT_START = {"pool-of-radiance": 0}


def script_spec(row: Row) -> str:
    """The spec of the first byte of the script a row's spec reads into."""
    pointer, _offset = parse_spec(row.spec)
    return f"*{pointer:#x}+{SCRIPT_START.get(row.title, 0x8000):#x}"


#: `SAVE 0`, where the limit would land on the fight side.
_TO_ZERO = ((0, SAVE), (2, 0))
#: `SAVE 255`: a byte constant above any byte counter it is compared with.
_TO_SAVE_255 = ((0, SAVE), (2, 255))
#: A roll whose limit is a variable, `RANDOM [v], [w]`, is seven bytes; it
#: becomes `SAVE 99, [w]` with the first operand's kind changed from `$01`
#: (byte variable) to `$02` (immediate word), so its length stays the same.
_TO_SAVE_WORD = ((0, SAVE), (1, 0x02), (2, 99), (3, 0))
#: `ADD 1, [v], [v]` becomes `ADD 0`.
_ADD_NOTHING = ((2, 0),)

DARKNESS = "pools-of-darkness"

#: The two Pools of Darkness `Disk3/ECL.GLB` releases, by sha256 prefix.
_LIBRARY = {"becddc": "becddc5926af library", "adb9af": "adb9afbd3eca library",
            "both": "both libraries"}

#: Every Pools of Darkness roll that decides whether a step starts a fight:
#: `(ECL address, statement hash, entry-table hash, changes, area, library,
#: what the script does)`.  Each is reached from the step entry (entry 1),
#: most after a step counter passes its limit; its change takes the `EXIT`.
#: Rolls the step entry reaches only past one of these, rolls in the camp
#: entries, and rolls inside a fixed event (after a `WHO`, a once-only flag or
#: an `APPROACH`) are not here.
_DARKNESS_GATES = (
    (0x89A2, "b0469054", "f219fc88", _TO_SAVE, 16, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $8A18"),
    (0x89A3, "b0469054", "7afab110", _TO_SAVE, 16, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $8A15"),
    (0x8B88, "b0469054", "afb581b9", _TO_SAVE, 17, "adb9af",
     "RANDOM 99 [191]; COMPARE 20, [191]; IF<= EXIT: 20 of 100 fight, COMBAT at $9435"),
    (0x8BC7, "b0469054", "f90bb419", _TO_SAVE, 17, "becddc",
     "RANDOM 99 [191]; COMPARE 20, [191]; IF<= EXIT: 20 of 100 fight, COMBAT at $9470"),
    (0x8248, "b0469054", "1a87c6e7", _TO_SAVE, 19, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 10; IF>= EXIT: 10 of 100 fight, COMBAT at $82CB"),
    (0x825E, "b0469054", "ed590f7d", _TO_SAVE, 19, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 10; IF>= EXIT: 10 of 100 fight, COMBAT at $82DE"),
    (0x85E4, "b0469054", "7b88e1b9", _TO_SAVE, 21, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $9D56"),
    (0x8603, "b0469054", "68fa88b9", _TO_SAVE, 21, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $9D7C"),
    (0x869F, "b0469054", "7b88e1b9", _TO_SAVE, 21, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $9D56"),
    (0x86BE, "b0469054", "68fa88b9", _TO_SAVE, 21, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $9D7C"),
    (0x9709, "b0469054", "7b88e1b9", _TO_SAVE, 21, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 70; IF> $23: 71 of 100 fight, COMBAT at $96A7"),
    (0x9737, "b0469054", "68fa88b9", _TO_SAVE, 21, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 70; IF> $23: 71 of 100 fight, COMBAT at $96D5"),
    (0x9B3E, "ada9bdc3", "38d311f7", _TO_SAVE, 22, "becddc",
     "RANDOM 99 [173]; COMPARE 3, [173]; IF<= EXIT: 3 of 100 fight, COMBAT at $9D54"),
    (0x9B66, "ada9bdc3", "33adf784", _TO_SAVE, 22, "adb9af",
     "RANDOM 99 [173]; COMPARE 3, [173]; IF<= EXIT: 3 of 100 fight, COMBAT at $9D79"),
    (0x8371, "b0469054", "3e2ccabc", _TO_SAVE, 25, "becddc",
     "RANDOM 99 [191]; COMPARE 5, [191]; IF<= EXIT: 5 of 100 fight, COMBAT at $8A2A"),
    (0x838E, "b0469054", "3e2ccabc", _TO_SAVE, 25, "adb9af",
     "RANDOM 99 [191]; COMPARE 5, [191]; IF<= EXIT: 5 of 100 fight, COMBAT at $8A97"),
    (0x81EE, "b0469054", "3dff99c5", _TO_SAVE, 26, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 10; IF>= EXIT: 10 of 100 fight, COMBAT at $826A"),
    (0x81FD, "b0469054", "908f1b94", _TO_SAVE, 26, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 10; IF>= EXIT: 10 of 100 fight, COMBAT at $827C"),
    (0x82EA, "e43dac29", "637295c6", _TO_SAVE, 32, "both",
     "RANDOM 99 [192]; COMPARE [192], 5; IF> EXIT: 6 of 100 fight, COMBAT at $835A"),
    (0x82FD, "570b9230", "bbcfd12e", _TO_SAVE, 33, "adb9af",
     "RANDOM 99 [160]; COMPARE [160], 5; IF> EXIT: 6 of 100 fight, COMBAT at $83F7"),
    (0x8302, "570b9230", "796119d3", _TO_SAVE, 33, "becddc",
     "RANDOM 99 [160]; COMPARE [160], 5; IF> EXIT: 6 of 100 fight, COMBAT at $83FD"),
    (0x827A, "b0469054", "2632d2ab", _TO_SAVE, 34, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $82C1"),
    (0x8286, "b0469054", "eeacfd0b", _TO_SAVE, 34, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $82D0"),
    (0x887C, "93204a53", "5137aec2", _TO_SAVE_WORD, 35, "becddc",
     "RANDOM [351] [191] after a step counter; COMPARE [191], 1; IF>= EXIT, else the monster tables and COMBAT"),
    (0x88C5, "93204a53", "3d47504b", _TO_SAVE_WORD, 35, "adb9af",
     "RANDOM [351] [191] after a step counter; COMPARE [191], 1; IF>= EXIT, else the monster tables and COMBAT"),
    (0x8472, "52c253aa", "e97376fc", _TO_SAVE_WORD, 36, "becddc",
     "RANDOM [417] [191] after a step counter; COMPARE [191], 1; IF>= EXIT, else the monster tables and COMBAT"),
    (0x849F, "52c253aa", "bdf570fe", _TO_SAVE_WORD, 36, "adb9af",
     "RANDOM [417] [191] after a step counter; COMPARE [191], 1; IF>= EXIT, else the monster tables and COMBAT"),
    (0x833D, "b0469054", "6fe8210f", _TO_SAVE, 37, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $83DA"),
    (0x8345, "b0469054", "0a27efc0", _TO_SAVE, 37, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $83E4"),
    (0x8631, "b0469054", "3c13761f", _TO_SAVE, 39, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $8699"),
    (0x868F, "b0469054", "8e6f6178", _TO_SAVE, 39, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $86FC"),
    (0x8178, "b0469054", "8de718f2", _TO_SAVE, 40, "both",
     "RANDOM 99 [191]; COMPARE [191], 5; IF> EXIT: 6 of 100 fight, COMBAT at $81DF"),
    (0x856A, "93204a53", "e61534bf", _TO_SAVE_WORD, 48, "becddc",
     "RANDOM [351] [191] after a step counter; COMPARE [191], 1; IF>= EXIT, else the monster tables and COMBAT"),
    (0x8586, "93204a53", "861c1c80", _TO_SAVE_WORD, 48, "adb9af",
     "RANDOM [351] [191] after a step counter; COMPARE [191], 1; IF>= EXIT, else the monster tables and COMBAT"),
    (0x9030, "eea428e6", "e61534bf", _TO_SAVE_WORD, 48, "becddc",
     "RANDOM [362] [193], [362] counting moves since the last fight square; COMPARE [193], 0; IF!= EXIT, else SETUPMON and COMBAT"),
    (0x9098, "eea428e6", "861c1c80", _TO_SAVE_WORD, 48, "adb9af",
     "RANDOM [362] [193], [362] counting moves since the last fight square; COMPARE [193], 0; IF!= EXIT, else SETUPMON and COMBAT"),
    (0x9AB6, "b0469054", "8d2f1fb3", _TO_SAVE, 50, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 1; IF> EXIT: 2 of 100 fight, COMBAT at $9B96"),
    (0x9C39, "b0469054", "92432309", _TO_SAVE, 50, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 1; IF> EXIT: 2 of 100 fight, COMBAT at $9D33"),
    (0x81D6, "b0469054", "8741c491", _TO_SAVE, 51, "both",
     "RANDOM 99 [191]; COMPARE 20, [191]; IF<= EXIT: 20 of 100 fight, COMBAT at $843B"),
    (0x87A9, "b0469054", "b70d73e6", _TO_SAVE, 52, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $87FB"),
    (0x87CA, "b0469054", "ade77ad6", _TO_SAVE, 52, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $8820"),
    (0x9313, "b0469054", "3daa5cf8", _TO_SAVE, 53, "becddc",
     "RANDOM 99 [191]; COMPARE [192], [191], [192] set to 5 or 10 just before; IF< EXIT, else the event table"),
    (0x9341, "b0469054", "0f284d7a", _TO_SAVE, 53, "adb9af",
     "RANDOM 99 [191]; COMPARE [192], [191], [192] set to 5 or 10 just before; IF< EXIT, else the event table"),
    (0x964B, "b0469054", "4b6a014b", _TO_SAVE, 54, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 1; IF> EXIT: 2 of 100 fight, COMBAT at $9731"),
    (0x998C, "b0469054", "a10e2cb1", _TO_SAVE, 54, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 1; IF> EXIT: 2 of 100 fight, COMBAT at $9A7D"),
    (0x8700, "b0469054", "a355d97d", _TO_SAVE, 64, "adb9af",
     "RANDOM 99 [191]; COMPARE 10, [191]; IF< EXIT: 11 of 100 fight, COMBAT at $9D99"),
    (0x8724, "b0469054", "18349f46", _TO_SAVE, 64, "becddc",
     "RANDOM 99 [191]; COMPARE 10, [191]; IF< EXIT: 11 of 100 fight, COMBAT at $9D8D"),
    (0x8B20, "03bea0b8", "204207f4", _TO_SAVE_WORD, 65, "adb9af",
     "RANDOM [156] [191] after a step counter; COMPARE [191], 1; IF>= EXIT, else the monster tables and COMBAT"),
    (0x8B56, "03bea0b8", "9e68e602", _TO_SAVE_WORD, 65, "becddc",
     "RANDOM [156] [191] after a step counter; COMPARE [191], 1; IF>= EXIT, else the monster tables and COMBAT"),
    (0x90A8, "38811a45", "204207f4", _TO_SAVE, 65, "adb9af",
     "RANDOM 5 [192]; COMPARE [192], 0; IF!= EXIT: 1 of 6 fight, COMBAT at $8BE8"),
    (0x912D, "38811a45", "9e68e602", _TO_SAVE, 65, "becddc",
     "RANDOM 5 [192]; COMPARE [192], 0; IF!= EXIT: 1 of 6 fight, COMBAT at $8C24"),
    (0x8A98, "b0469054", "08f9aa28", _TO_SAVE, 66, "adb9af",
     "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $8AEF"),
    (0x8B78, "b0469054", "c4c3178d", _TO_SAVE, 66, "becddc",
     "RANDOM 99 [191]; COMPARE [191], 10; IF> EXIT: 11 of 100 fight, COMBAT at $8BD9"),
    (0x83C5, "4010ca26", "ad7ad6cc", _TO_SAVE, 67, "becddc",
     "RANDOM 20 [191]; COMPARE [191], 1; IF> EXIT: 2 of 21 fight, COMBAT at $844B"),
    (0x83D4, "4010ca26", "ae6a331f", _TO_SAVE, 67, "adb9af",
     "RANDOM 20 [191]; COMPARE [191], 1; IF> EXIT: 2 of 21 fight, COMBAT at $845A"),
    (0x8559, "4010ca26", "ad7ad6cc", _TO_SAVE_255, 67, "becddc",
     "RANDOM 20 [191]; COMPARE [191], [163]; ADD 1 [163]; IF> EXIT, else [163] guards and COMBAT"),
    (0x8566, "96f6c8f8", "ad7ad6cc", _ADD_NOTHING, 67, "becddc",
     "ADD 1 [163] after the roll; ADD 0 keeps the counter the roll is compared with"),
    (0x8566, "4010ca26", "ae6a331f", _TO_SAVE_255, 67, "adb9af",
     "RANDOM 20 [191]; COMPARE [191], [163]; ADD 1 [163]; IF> EXIT, else [163] guards and COMBAT"),
    (0x8573, "96f6c8f8", "ae6a331f", _ADD_NOTHING, 67, "adb9af",
     "ADD 1 [163] after the roll; ADD 0 keeps the counter the roll is compared with"),
    (0x84A5, "b0469054", "6119e551", _TO_ZERO, 68, "becddc",
     "RANDOM 99 [191]; COMPARE 15, [191]; IF> EXIT: 85 of 100 fight, COMBAT at $8526"),
    (0x84E9, "b0469054", "7c3d1e77", _TO_ZERO, 68, "adb9af",
     "RANDOM 99 [191]; COMPARE 15, [191]; IF> EXIT: 85 of 100 fight, COMBAT at $8570"),
    (0x8D31, "b0469054", "76d88dbd", _TO_SAVE, 69, "adb9af",
     "RANDOM 99 [191]; COMPARE 10, [191]; IF<= EXIT: 10 of 100 fight, COMBAT at $8E08"),
    (0x8DA8, "b0123001", "76d88dbd", _TO_SAVE, 69, "adb9af",
     "RANDOM 50 [192]; COMPARE 10, [192]; IF<= EXIT: 10 of 51 fight, COMBAT at $8E08"),
    (0x8DDB, "b0469054", "cd4dcd8d", _TO_SAVE, 69, "becddc",
     "RANDOM 99 [191]; COMPARE 10, [191]; IF<= EXIT: 10 of 100 fight, COMBAT at $8EB9"),
    (0x8E26, "b0469054", "76d88dbd", _TO_SAVE, 69, "adb9af",
     "RANDOM 99 [191]; COMPARE 10, [191]; IF<= EXIT: 10 of 100 fight, COMBAT at $8F0B"),
    (0x8E62, "b0123001", "cd4dcd8d", _TO_SAVE, 69, "becddc",
     "RANDOM 50 [192]; COMPARE 10, [192]; IF<= EXIT: 10 of 51 fight, COMBAT at $8EB9"),
    (0x8EA2, "b0123001", "76d88dbd", _TO_SAVE, 69, "adb9af",
     "RANDOM 50 [192]; COMPARE 10, [192]; IF<= $23: 10 of 51 fight, COMBAT at $8F0B"),
    (0x8ED7, "b0469054", "cd4dcd8d", _TO_SAVE, 69, "becddc",
     "RANDOM 99 [191]; COMPARE 10, [191]; IF<= EXIT: 10 of 100 fight, COMBAT at $8FB4"),
    (0x8F5B, "b0123001", "cd4dcd8d", _TO_SAVE, 69, "becddc",
     "RANDOM 50 [192]; COMPARE 10, [192]; IF<= $23: 10 of 51 fight, COMBAT at $8FB4"),
    (0x9CE3, "b0469054", "cd4dcd8d", _TO_SAVE, 69, "becddc",
     "RANDOM 99 [191]; COMPARE [193], [191], [193] set to 7 or 13 just before; IF< EXIT, else SETUPMON and COMBAT"),
    (0x9CFA, "b0469054", "76d88dbd", _TO_SAVE, 69, "adb9af",
     "RANDOM 99 [191]; COMPARE [193], [191], [193] set to 7 or 13 just before; IF< EXIT, else SETUPMON and COMBAT"),
    (0x853F, "66750d9e", "a2ec60b1", _TO_SAVE_WORD, 70, "becddc",
     "RANDOM [368] [191] after a step counter; COMPARE [191], [194], [194] set to 1 just before; IF> EXIT, else the monster tables and COMBAT"),
    (0x8543, "66750d9e", "499c9d38", _TO_SAVE_WORD, 70, "adb9af",
     "RANDOM [368] [191] after a step counter; COMPARE [191], [194], [194] set to 1 just before; IF> EXIT, else the monster tables and COMBAT"),
    (0x80E7, "b0469054", "5d99e4dc", _TO_ZERO, 71, "both",
     "RANDOM 99 [191]; COMPARE 15, [191]; IF> EXIT: 85 of 100 fight, COMBAT at $8145"),
    (0x87A8, "03bea0b8", "d6c42656", _TO_SAVE_WORD, 74, "becddc",
     "RANDOM [156] [191] after a step counter; COMPARE [191], 2; IF< another event, IF> EXIT, else the monster tables and COMBAT"),
    (0x87F9, "03bea0b8", "2e7611b3", _TO_SAVE_WORD, 74, "adb9af",
     "RANDOM [156] [191] after a step counter; COMPARE [191], 2; IF< another event, IF> EXIT, else the monster tables and COMBAT"),
    (0x82A3, "b0469054", "397d3b27", _TO_SAVE, 80, "adb9af",
     "RANDOM 99 [191]; COMPARE 20, [191]; IF<= EXIT: 20 of 100 fight, COMBAT at $853D"),
    (0x82C0, "b0469054", "397d3b27", _TO_SAVE, 80, "becddc",
     "RANDOM 99 [191]; COMPARE 20, [191]; IF<= EXIT: 20 of 100 fight, COMBAT at $8552"),
    (0x9B9D, "b0469054", "76d88a00", _TO_SAVE, 81, "becddc",
     "RANDOM 99 [191]; COMPARE 5, [191]; IF< $23: 6 of 100 fight, COMBAT at $9C1B"),
    (0x9BC6, "b0469054", "618c819e", _TO_SAVE, 81, "adb9af",
     "RANDOM 99 [191]; COMPARE 5, [191]; IF< $23: 6 of 100 fight, COMBAT at $9C44"),
    (0x9BCB, "e43dac29", "884fdcd9", _TO_SAVE, 82, "adb9af",
     "RANDOM 99 [192]; COMPARE 5, [192]; IF<= EXIT: 5 of 100 fight, COMBAT at $9C9D"),
    (0x9BD3, "e43dac29", "42eb97bd", _TO_SAVE, 82, "becddc",
     "RANDOM 99 [192]; COMPARE 5, [192]; IF<= EXIT: 5 of 100 fight, COMBAT at $9CA4"),
)

#: Every Pools of Darkness area script that makes no such roll:
#: `(entry-table hash, area, library, whether it has no RANDOM at all)`.
_DARKNESS_NONE = (
    ("8a8ad741", 1, "becddc", True),
    ("8fbf813a", 1, "adb9af", True),
    ("f16ebadc", 2, "both", True),
    ("44ad59e8", 3, "both", True),
    ("7ab30909", 4, "becddc", True),
    ("7dac702f", 4, "adb9af", True),
    ("f25013ea", 18, "becddc", True),
    ("52c17257", 18, "adb9af", True),
    ("1aeb3802", 20, "becddc", True),
    ("6916a7ae", 20, "adb9af", True),
    ("916184f4", 23, "becddc", True),
    ("2657dd9c", 23, "adb9af", True),
    ("0fb407b2", 24, "becddc", False),
    ("50e74057", 24, "adb9af", False),
    ("149bd555", 27, "becddc", True),
    ("4cef5eab", 27, "adb9af", True),
    ("380063e4", 38, "becddc", False),
    ("0965b9b1", 38, "adb9af", False),
    ("2c5a28f5", 41, "becddc", False),
    ("0e4f4046", 41, "adb9af", False),
    ("4d922233", 42, "becddc", True),
    ("abcd9c23", 42, "adb9af", True),
    ("c5ef44ff", 49, "becddc", True),
    ("d438ad54", 49, "adb9af", True),
    ("ec1ba714", 55, "becddc", False),
    ("f6c5488f", 55, "adb9af", False),
    ("09d0cf78", 72, "becddc", False),
    ("bb43b658", 72, "adb9af", False),
    ("2db3e1ec", 73, "becddc", False),
    ("7e6034b8", 73, "adb9af", False),
    ("69e3bb4d", 75, "becddc", False),
    ("6c4af453", 75, "adb9af", False),
    ("c5a16e7c", 76, "becddc", True),
    ("b0548a95", 76, "adb9af", True),
    ("bec73726", 77, "becddc", True),
    ("3a26be0e", 77, "adb9af", True),
    ("42d1340f", 83, "becddc", False),
    ("0f039f51", 83, "adb9af", False),
    ("8b5809f7", 84, "becddc", True),
    ("1c8e21aa", 84, "adb9af", True),
    ("66441a6c", 85, "becddc", False),
    ("d849daec", 85, "adb9af", False),
    ("72015941", 86, "becddc", True),
    ("e93f946c", 86, "adb9af", True),
)

_DARKNESS_ROWS = tuple(
    _gate(DARKNESS, f"*0x6EA6+0x{at:04X}", statement, PROBABLE,
          f"area {area} ({_LIBRARY[library]}) at ${at:04X}: {what}",
          changes=changes, area=entries)
    for at, statement, entries, changes, area, library, what in _DARKNESS_GATES
) + tuple(
    _none(DARKNESS, "*0x6EA6+0x8000", entries, PROBABLE,
          f"area {area} ({_LIBRARY[library]}): "
          + ("no RANDOM statement" if bare else
             "none of its rolls decides whether a step starts a fight"))
    for entries, area, library, bare in _DARKNESS_NONE
)


#: Pool's buffer is `ecl.dax` at `[data+0xA4] + (A - $9900)`; the other titles'
#: is `[data+pointer] + A`.  The Slums roll (`$9B3A`) has its encounter on the
#: high side, so its constant, two bytes on, is zeroed as well.
#:
#: Pools of Darkness has two `Disk3/ECL.GLB` releases (sha256 `becddc5926af`
#: and `adb9afbd3eca`) whose rolls mostly sit at different addresses, so each
#: has its own rows (`_DARKNESS_GATES`), and every row names its area's entry
#: table; with both hashes, each row matches its own area of its own release
#: and nothing else.  The `SAVE` leaves its constant, mostly 99, a value the
#: roll can produce, in the roll's variable (191, save offset `0xBE`, for
#: most), and a step counter unreset.  Area 67's chase roll stores 255 instead,
#: and its `ADD 1` to the counter the roll is compared with becomes `ADD 0`,
#: because that counter also sets how many guards the fight brings.
ROWS = (
    _gate("pool-of-radiance", "*0xA4+0x7B3", "59ff65e6", PROBABLE,
          "ECL25 wilderness roll at $A0B3, same statement as area 26"),
    _gate("pool-of-radiance", "*0xA4+0x7E7", "59ff65e6", CONFIRMED,
          "area 26 roll at $A0E7, 103 steps in 29.7 minutes live"),
    _gate("pool-of-radiance", "*0xA4+0x5A7", "59ff65e6", PROBABLE,
          "ECL27 wilderness roll at $9EA7, same statement as area 26"),
    _gate("pool-of-radiance", "*0xA4+0x23A", "a57ba371", PROBABLE,
          "Slums roll at $9B3A, ECL14: IF<= 12 EXIT, so the constant is 0",
          changes=((0, SAVE), (2, 0))),
    _gate("pool-of-radiance", "*0xA4+0x10E", "59ff65e6", PROBABLE,
          "area 0 step roll at $9A0E: RANDOM 19, COMPARE 19, IF= looks for "
          "the MAD MAN in the party, whose attack brings the city watch, so "
          "the constant is 0",
          changes=((0, SAVE), (2, 0))),
    _gate("pool-of-radiance", "*0xA4+0xB40", "8bb105ac", PROBABLE,
          "area 0 tavern roll at $A440 after a tale: RANDOM 3, COMPARE 1, "
          "IF= GOTO the drunken brawl at $A693"),
    _gate("curse-of-the-azure-bonds", "*0x5006+0x8739", "9afc9873", PROBABLE,
          "ECL02 roll at $8739: IF> EXIT"),
    _none("curse-of-the-azure-bonds", "*0x5006+0x8000", "0da02140", PROBABLE,
          "world map area $50: its rolls pick the PATROL FOREST monsters the "
          "player asked to fight ($84DE, $84F8, $8508) and whether a journey "
          "leg shows a note ($9A1A); each leg's fight is the leg's own"),
    _none("curse-of-the-azure-bonds", "*0x5006+0x8000", "c27b304a", PROBABLE,
          "world map area $51: no RANDOM statement; each leg's fight is the "
          "leg's own"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x859D", "dc6e4e48", PROBABLE,
          "ECL10 roll at $859D: IF> EXIT", area="793f0cfc"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x89F6", "dc6e4e48", PROBABLE,
          "The Ruins (area $20, disk 2 ECL block 3) roll at $89F6, reached on an "
          "ordinary square when the [$4C1B] wait is 0: IF> 5 EXIT",
          area="0a16c6d8"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x834F", "dc6e4e48", PROBABLE,
          "area 33 ($21) roll at $834F, reached from the step entry on an "
          "ordinary square when the [$4C1B] wait is 0: IF> 5 EXIT, else one of "
          "two monster sets and COMBAT", area="5bee2f53"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x83ED", "dc6e4e48", PROBABLE,
          "area 65 ($41) roll at $83ED, reached from the step entry on an "
          "ordinary square when [$4CD9] is not 0 and the [$4C1B] wait is 0: "
          "IF> 3 EXIT, else COMBAT at $845A", area="6a55442a"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x9827", "dc6e4e48", PROBABLE,
          "area 81 ($51) roll at $9827, reached from the step entry on an "
          "ordinary square once step counter [$4C02] passes 10: COMPARE 15, "
          "roll, IF<= GOTO $9ACA (EXIT), else the monster tables and the "
          "encounter menu", area="bfb373ae"),
    _none("secret-of-the-silver-blades", "*0x6956+0x8000", "9a483961", PROBABLE,
          "area 48 ($30): no RANDOM statement"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x9074", "dc6e4e48", PROBABLE,
          "area 51 ($33) roll at $9074, reached from the step entry on an "
          "ordinary square once step counter [$4C02] passes 20: COMPARE 35, "
          "roll, IF<= GOTO $97FC (EXIT), else the monster tables and SETUPMON; "
          "while [$4CD9] is 1 the step entry takes the $9761 roll instead, "
          "which only prints a message", area="bf712cb6"),
    _none("secret-of-the-silver-blades", "*0x6956+0x8000", "57e281fe", PROBABLE,
          "area 52 ($34): no RANDOM statement"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x84B3", "761f6670", PROBABLE,
          "area 82 ($52) roll at $84B3 into [$4C06], reached from the step "
          "entry off a type-31 square when [$4CBE] is 255, [$7ECA] is 1 and "
          "the try counter [$4CBD] is at most 10: IF> 50 GOTO the square "
          "dispatch, else TREASURE and COMBAT at $84F2", area="3dff39b8"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x85B0", "dc6e4e48", PROBABLE,
          "area 82 ($52) roll at $85B0 on an ordinary square when the "
          "[$4C07] wait is 0: IF> 50, 20 or 10 GOTO $8943 (EXIT), by [$4CBE] "
          "and [$7ECA], else the monster tables and SETUPMON or the $86E6 "
          "event table", area="3dff39b8"),
    _gate("secret-of-the-silver-blades", "*0x6956+0x86D5", "dc6e4e48", PROBABLE,
          "area 82 ($52) roll at $86D5 on an ordinary square while the "
          "[$4C07] wait counts down after a fight: IF> 5 GOTO $8938 (EXIT), "
          "else the $86E6 event table, two of whose ten events are COMBAT",
          area="3dff39b8"),
    *_DARKNESS_ROWS,
    _rest("pool-of-radiance", "*0x9C+0x5A6", "0000", SPECULATIVE,
          "$6DD3 chance word, confirmed on DOS, not run on the Amiga"),
    _rest("curse-of-the-azure-bonds", "*0x3DBE+0xFDA6", "0000", SPECULATIVE,
          "$7ED3 chance word in the $7C00 block"),
    _rest("secret-of-the-silver-blades", "*0x52B4+0xFDA6", "0000", SPECULATIVE,
          "$7ED3 chance word in the $7C00 block"),
    _rest("pools-of-darkness", "*0x57AC+0x2C", "00", SPECULATIVE,
          "variable $2C, the chance byte"),
)


def rows_for(title: str) -> list[Row]:
    return [row for row in ROWS if row.title == title]


class EncounterSwitch:
    """Holds one title's rows changed while the switch is on.

    `resolve(spec)` gives an address or None for a null pointer, `read(address,
    n)` bytes, and `write(address, data)` a dict with an `error` key when the
    write did not stick.  `inside(address, n)` says whether a rest row's
    resolved address may be written.  `speculative` holds the SPECULATIVE rest
    rows too.  The original bytes are read from memory before the first change
    and kept here, so nothing of the script is stored in the repository.

    Every write is read back: bytes that are neither the change nor the
    original are put back to the original and reported.
    """

    def __init__(self, title, resolve, read, write, speculative=False,
                 inside=lambda address, n: True, journal=lambda rows: None):
        self.rows = [r for r in rows_for(title)
                     if speculative or r.grade != SPECULATIVE]
        if not self.rows:
            raise ValueError(f"no encounter rows for {title!r}")
        self.title = title
        self.resolve, self.read, self.write = resolve, read, write
        self.inside = inside
        #: Gates this switch changed: address -> (original bytes, changed bytes).
        self.patched: dict[int, tuple[bytes, bytes]] = {}
        #: Rest values this switch overwrote: address -> what was there.
        self.held: dict[int, bytes] = {}
        #: What is already reported stopped: the address of a gate whose
        #: statement did not match or of a rest row outside memory, and
        #: `(address, area)` of a gate whose area is not loaded.
        self.blocked: set[int | tuple[int, str]] = set()
        #: `(address, digest)` of each none row already reported loaded.
        self.noted: set[tuple[int, str]] = set()
        #: How many bytes each change covers: address -> span.
        self.spans: dict[int, int] = {}
        #: What each rest row holds: address -> the bytes written.
        self.holding: dict[int, bytes] = {}
        #: The row each changed address belongs to, for the journal.
        self.row_at: dict[int, Row] = {}
        self.journal = journal
        self.active = True

    def outstanding(self) -> list[dict]:
        """Every change still to be put back: `kind`, `spec`, `address`,
        `original` and `changed` bytes in hex, and for a gate the `digest` its
        whole statement had, so a later repair can check it is the same one."""
        rows = [{"kind": GATE, "spec": self.row_at[a].spec, "address": a,
                 "digest": self.row_at[a].digest,
                 "original": o[:self.spans[a]].hex(),
                 "changed": c[:self.spans[a]].hex()}
                for a, (o, c) in self.patched.items()]
        rows += [{"kind": REST, "spec": self.row_at[a].spec, "address": a,
                  "original": o.hex(), "changed": self.holding[a].hex()}
                 for a, o in self.held.items()]
        return rows

    def _record(self) -> None:
        self.journal(self.outstanding())

    def _checked_write(self, address, original, ours) -> dict:
        """Write `ours`, read it back, and put `original` back if it is neither."""
        result = self.write(address, ours)
        got = self.read(address, len(ours))
        if got not in (ours, original[:len(ours)]):
            self.write(address, original[:len(ours)])
            return {**result, "error": f"read back {got.hex()}, neither the "
                                       "change nor the original; original "
                                       "put back"}
        return result

    def apply(self) -> list[dict]:
        """Change every row that is currently loaded; return what was written
        or blocked (a block is reported once until the bytes match), and each
        loaded script that makes no roll (reported once until it unloads)."""
        done = []
        for row in self.rows:
            address = self.resolve(row.spec)
            if address is None:
                continue
            if row.kind == NONE:
                key = (address, row.digest)
                if digest(self.read(address, ENTRY_TABLE)) != row.digest:
                    self.noted.discard(key)
                elif key not in self.noted:
                    self.noted.add(key)
                    done.append({"row": row.spec, "grade": row.grade,
                                 "none": "the loaded script makes no "
                                         f"random-encounter roll: {row.source}"})
                continue
            if row.kind == GATE:
                # Rows of two areas can share an address, so a row stopped
                # for its area is remembered by both.
                elsewhere = self._other_area(row)
                if elsewhere is not None:
                    if (address, row.area) not in self.blocked:
                        self.blocked.add((address, row.area))
                        done.append({"row": row.spec, "grade": row.grade,
                                     "stopped": elsewhere})
                    continue
                self.blocked.discard((address, row.area))
                now = self.read(address, STATEMENT)
                if address in self.patched and now == self.patched[address][1]:
                    continue
                if digest(now) != row.digest:
                    if address not in self.blocked:
                        self.blocked.add(address)
                        done.append({"row": row.spec, "grade": row.grade,
                                     "stopped": f"the {STATEMENT} bytes at "
                                                "the row's address do not match "
                                                f"its expected hash ({digest(now)}"
                                                f", not {row.digest}), for "
                                                "example because its area is "
                                                "not loaded"})
                    continue
                self.blocked.discard(address)
                changed = bytearray(now)
                for offset, value in row.changes:
                    changed[offset] = value
                span = max(offset for offset, _ in row.changes) + 1
                # Recorded first, here and in the journal: a transport error
                # or a kill mid-write leaves the address restorable.
                self.patched[address] = (now, bytes(changed))
                self.spans[address] = span
                self.row_at[address] = row
                self._record()
                result = self._checked_write(address, now, bytes(changed[:span]))
                if "error" in result:
                    del self.patched[address]
                    self._record()
            else:
                if not self.inside(address, len(row.new)):
                    if address not in self.blocked:
                        self.blocked.add(address)
                        done.append({"row": row.spec, "grade": row.grade,
                                     "stopped": f"{address:#x} is outside the "
                                                "expected memory"})
                    continue
                now = self.read(address, len(row.new))
                if now == row.new:
                    continue
                # Whatever the game last wrote is what to put back.
                self.held[address] = now
                self.holding[address] = row.new
                self.row_at[address] = row
                self._record()
                result = self._checked_write(address, now, row.new)
            done.append({"row": row.spec, "grade": row.grade, **result})
        return done

    def _other_area(self, row: Row) -> str | None:
        """None when `row` names no area or its area's script is loaded, else
        why the gate is stopped."""
        if not row.area:
            return None
        head = self.resolve(script_spec(row))
        seen = None if head is None else digest(self.read(head, ENTRY_TABLE))
        if seen == row.area:
            return None
        if seen is None:
            return ("the entry-table address is unresolved, so the row's area "
                    "cannot be checked")
        return (f"the loaded script's {ENTRY_TABLE}-byte entry table does not "
                f"match the row's area ({seen}, not {row.area}), so its area "
                "is not loaded")

    def release(self) -> list[dict]:
        """Put every changed byte back, without turning the switch off.

        A row that fails to read or write is reported and the rest still go
        back.
        """
        done = []
        for row in self.rows:
            try:
                address = self.resolve(row.spec)
                if address is None:
                    continue
                if row.kind == GATE:
                    if address not in self.patched:
                        continue
                    original, changed = self.patched[address]
                    if self.read(address, len(changed)) != changed:
                        del self.patched[address]
                        self._record()
                        continue        # the script was reloaded already
                    result = self.write(address, original[:self.spans[address]])
                    if "error" not in result:
                        del self.patched[address]
                        self._record()
                elif row.kind == REST:
                    if (address not in self.held
                            or self.read(address, len(row.new)) != row.new):
                        continue
                    result = self.write(address, self.held[address])
                    if "error" not in result:
                        del self.held[address]
                        self._record()
                else:
                    continue
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
            done.append({"row": row.spec, "grade": row.grade, **result})
        return done

    def adopt(self, rows: list[dict]) -> list[dict]:
        """Take over changes an earlier process recorded, where the bytes are
        still that change; give back every row it did not take.

        A row is taken when its spec is one of this switch's rows of the same
        kind and still resolves to its address, and the bytes there read as the
        recorded change (for a gate, with the original put back, as the
        recorded statement).  A row given back is either gone already, put
        back by a reload, or for `restore_row` to judge.
        """
        left = []
        by_spec = {}
        for row in self.rows:
            if row.kind != NONE:
                by_spec.setdefault(row.spec, []).append(row)
        for entry in rows:
            # Rows of two areas can share a spec; the recorded digest picks one.
            found = by_spec.get(entry.get("spec"), [])
            row = next((r for r in found if r.kind != GATE
                        or r.digest == entry.get("digest")),
                       found[0] if found else None)
            try:
                address = int(entry["address"])
                original = bytes.fromhex(entry["original"])
                changed = bytes.fromhex(entry["changed"])
            except (KeyError, TypeError, ValueError):
                left.append(entry)
                continue
            if (row is None or row.kind != entry.get("kind", GATE)
                    or len(original) != len(changed) or not changed
                    or self.resolve(row.spec) != address):
                left.append(entry)
                continue
            if row.kind == GATE:
                span = max(offset for offset, _ in row.changes) + 1
                now = self.read(address, STATEMENT)
                if (span != len(changed) or now[:span] != changed
                        or entry.get("digest") != row.digest
                        or digest(original + now[span:]) != row.digest):
                    left.append(entry)
                    continue
                self.patched[address] = (original + now[span:], now)
                self.spans[address] = span
            else:
                if changed != row.new or self.read(address, len(changed)) != changed:
                    left.append(entry)
                    continue
                self.held[address] = original
                self.holding[address] = changed
            self.row_at[address] = row
        self._record()
        return left

    @property
    def pending(self) -> bool:
        """Whether a changed byte is still waiting to be put back."""
        return bool(self.patched or self.held)

    def off(self) -> list[dict]:
        """`release`, and the switch stays off.  The `write` it was given must
        read its bytes back, so a row counts as restored only when it is."""
        done = self.release()
        self.active = False
        return done


#: A key line is a save key when it presses the letter that opens the Save
#: picker in the camp and party menus.  **This net is not complete**: a save
#: can start from keys that contain no `s`, and a line of keysyms does not say
#: which menu is up.  The rule is `no_encounters off` before any save, because
#: the saved game carries the loaded script.
SAVE_KEYS = frozenset("sS")


def is_save_key(keys: str) -> bool:
    return any(k in SAVE_KEYS for k in keys.split())


# -- WinUAE ---------------------------------------------------------------
#
# Under WinUAE the switch reads and writes through the debugger pipe
# (`automap.amiga.WinuaePipe`), with `S` dumps and `W` lines inside an
# `AmigaTarget`, and it lives across processes: `amigadrive.py` presses a key a
# call, so `on` leaves the switch on and every later `keys` takes it over from
# the state file until `off`.

#: A row's spec: `*POINTER+OFFSET` reads the big-endian pointer at the
#: data-hunk offset POINTER and adds OFFSET; `+OFFSET` is a data-hunk offset.
SPEC = re.compile(r"^(?:\+(?P<at>\w+)|\*(?P<ptr>\w+)\+(?P<off>\w+))$")

#: What a failed read, write or key press under WinUAE raises.
WINUAE_ERRORS = (ValueError, OSError, TimeoutError, SystemExit, amiga.GuestError)


def parse_spec(spec: str) -> tuple[int | None, int]:
    """`(pointer offset or None, offset)` for a row's spec."""
    found = SPEC.match(spec.strip())
    if found is None:
        raise ValueError(f"{spec!r} is neither +OFFSET nor *POINTER+OFFSET")
    if found["at"] is not None:
        return None, int(found["at"], 0)
    return int(found["ptr"], 0), int(found["off"], 0)


def inside_memory(address: int, n: int) -> bool:
    return any(base <= address and address + n <= base + size
               for base, size in amiga.MEMORY)


def restore_row(read, write, resolve, row: dict) -> dict:
    """Put one recorded change back where it is certainly still there.

    A gate is written only when its bytes read as the recorded change and the
    statement with the original put back hashes to the recorded digest; a rest
    row only when its bytes read as the change and its spec still resolves to
    its address.  Anything else was reloaded or restored since and is left,
    with no write.  A result with an `error` key was not put back.
    """
    address = int(row["address"])
    original = bytes.fromhex(row["original"])
    changed = bytes.fromhex(row["changed"])
    if len(original) != len(changed) or not changed:
        raise ValueError("its original and changed bytes differ in length")
    if row.get("kind", GATE) == GATE:
        statement = read(address, STATEMENT)
        if statement[:len(changed)] != changed:
            return {"address": address, "left": statement.hex()}
        if digest(original + statement[len(original):]) != row.get("digest"):
            return {"address": address, "left": statement.hex(),
                    "why": "another statement is there now"}
    else:
        now = read(address, len(changed))
        if now != changed:
            return {"address": address, "left": now.hex()}
        if resolve(row["spec"]) != address:
            return {"address": address, "left": now.hex(),
                    "why": f"{row['spec']} no longer points here"}
    result = write(address, original)
    if "error" not in result and read(address, len(original)) != original:
        result = {**result, "error": "the original did not read back"}
    return {"address": address, "repaired": "error" not in result, **result}


#: A lane holder's name, as `winuae.ps1` and `automap.amiga` accept it; it names a file here.
_HOLDER = re.compile(r"[A-Za-z0-9._-]{1,64}")


def winuae_state_path(holder: str) -> pathlib.Path:
    """Where the WinUAE switch keeps `holder`'s state: one file per lane holder,
    because each lane runs its own WinUAE and every run by that holder must find
    what an earlier one left."""
    if not _HOLDER.fullmatch(holder) or holder.strip(".") == "":
        raise ValueError(f"the lane holder {holder!r} is not a lane holder name")
    return scratch.cache_dir("noencounters", f"winuae-{holder}.json")


class StateError(ValueError):
    """The WinUAE state file exists and cannot be read."""


class WinuaeState:
    """The WinUAE switch's record on disk.

    `on`, the `title` and `speculative` choice it was turned on with, the
    `anchor_base` and `data_base` where that title was last found, and `rows`:
    every change still to be put back, as `EncounterSwitch.outstanding` gives
    it plus its `title`.  Rewritten before every change and after every
    restore, so a process killed outright leaves the originals for the next.
    """

    EMPTY = {"on": False, "title": None, "speculative": False,
             "anchor_base": None, "data_base": None, "rows": []}

    def __init__(self, path: pathlib.Path):
        self.path = pathlib.Path(path)

    def load(self) -> dict:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return dict(self.EMPTY, rows=[])
        except OSError as exc:
            raise StateError(self._unreadable(exc)) from exc
        try:
            state = json.loads(text)
            if not isinstance(state, dict):
                raise ValueError("it is not a record")
            state = {**self.EMPTY, **state}
            rows = state["rows"]
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                raise ValueError("its rows are not a list of records")
            if not isinstance(state["on"], bool):
                raise ValueError("`on` is not true or false")
        except (ValueError, TypeError) as exc:
            raise StateError(self._unreadable(exc)) from exc
        return state

    def _unreadable(self, exc) -> str:
        return (f"the encounter state {self.path} cannot be read ({exc}), so a "
                "change may still be in the game: check the game, then delete "
                "the file")

    def save(self, state: dict) -> None:
        """Replace the file whole.  One name for the temporary copy, because the
        WinUAE lane lets one writer run at a time: a copy a killed save left is
        overwritten by the next one, and a failed save removes its own."""
        scratch.ensure(self.path.parent)
        temp = self.path.with_name(self.path.name + ".tmp")
        try:
            temp.write_text(json.dumps(state), encoding="utf-8")
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)


class PipeMemory:
    """The switch's `resolve`, `read` and `write` over an `AmigaTarget` on
    WinUAE's pipe, with each pass's reads gathered into one round trip.

    `prefetch(rows)` reads, in one batch, every pointer the rows go through and
    each row's bytes at the address that pointer gave last time; a pointer that
    moved costs a second batch.  Reads are served from what was fetched where
    it covers them; a write drops every fetched block it overlaps, so its
    read-back goes to the machine.  `clear()` ends the pass.
    """

    def __init__(self, target):
        self.target = target
        self.blocks: dict[tuple[int, int], bytes] = {}
        #: The value each pointer offset held when last read.
        self.pointers: dict[int, int] = {}
        #: Pointer offsets read in this pass.
        self.fresh: set[int] = set()

    def _address(self, spec: str, pointers: dict[int, int]) -> int | None:
        pointer, offset = parse_spec(spec)
        if pointer is None:
            return self.target.data_base + offset
        value = pointers.get(pointer)
        return None if not value else value + offset

    def fetch(self, blocks: list[tuple[int, int]]) -> None:
        """Read `blocks` in one round trip and keep them for this pass."""
        blocks = [b for b in dict.fromkeys(blocks) if inside_memory(*b)]
        if blocks:
            self.blocks.update(zip(blocks, self.target.read_blocks(blocks), strict=True))

    def prefetch(self, rows: list[Row]) -> None:
        pointers = sorted({p for p, _ in (parse_spec(r.spec) for r in rows)
                           if p is not None})
        heads = [(self.target.data_base + p, 4) for p in pointers]
        # Each row's bytes, and the entry table of a gate that names its area.
        reads = [(r.spec, length(r)) for r in rows]
        reads += [(script_spec(r), ENTRY_TABLE) for r in rows if r.area]
        guesses = [(a, n) for spec, n in reads
                   if (a := self._address(spec, self.pointers)) is not None]
        self.fetch(heads + guesses)
        before = dict(self.pointers)
        for p, head in zip(pointers, heads, strict=True):
            if head in self.blocks:
                self.pointers[p] = int.from_bytes(self.blocks[head], "big")
                self.fresh.add(p)
        self.fetch([(a, n) for spec, n in reads
                    if (a := self._address(spec, self.pointers))
                    != self._address(spec, before) and a is not None])

    def clear(self) -> None:
        self.blocks.clear()
        self.fresh.clear()

    def resolve(self, spec: str) -> int | None:
        pointer, offset = parse_spec(spec)
        if pointer is None:
            return self.target.data_base + offset
        if pointer not in self.fresh:
            self.pointers[pointer] = int.from_bytes(
                self.read(self.target.data_base + pointer, 4), "big")
            self.fresh.add(pointer)
        value = self.pointers[pointer]
        return None if value == 0 else value + offset

    def read(self, address: int, n: int) -> bytes:
        for (start, length), blob in self.blocks.items():
            if start <= address and address + n <= start + length:
                return blob[address - start:address - start + n]
        return self.target.read(address, n)

    def write(self, address: int, data: bytes) -> dict:
        end = address + len(data)
        for start, length in list(self.blocks):
            if start < end and address < start + length:
                del self.blocks[(start, length)]
        try:
            self.target.write(address, bytes(data))
        except WINUAE_ERRORS as exc:
            return {"address": address, "error": f"{type(exc).__name__}: {exc}"}
        return {"address": address, "new": bytes(data).hex()}


class WinuaeEncounters:
    """`no_encounters` for a game under WinUAE: `on`, `off`, and `keys`.

    `target` is an `AmigaTarget` over `WinuaePipe` for `title`'s layout, not yet
    located; `lane_check()` proves this run holds the lane and runs once,
    before the first read; `press(name)` presses one `amigadrive` key.
    `state` is the `WinuaeState`.

    `on` puts back whatever an earlier run left, then changes every loaded row
    and records the switch as on.  `keys` presses keys, blocking the whole line
    when one is a save key while the switch is on or a change may be in the
    game, and while the switch is on takes it over and applies it again before
    each key.  `off` puts every recorded change back.  The switch stays on
    across processes until `off`, so an interrupted `keys` leaves it on and
    recorded; an interrupted `on` or `off` leaves every change recorded, and
    the next command takes it over or puts it back.
    """

    def __init__(self, title: str, target, *, state: WinuaeState,
                 lane_check=lambda: None, press=lambda name: None):
        if not rows_for(title):
            raise ValueError(f"no encounter rows for {title!r}")
        self.title = title
        self.target = target
        self.state = state
        self.lane_check = lane_check
        self.press = press
        self.memory = PipeMemory(target)
        self.switch: EncounterSwitch | None = None
        self.checked = False
        #: Rows of another title, kept in the file and left alone.
        self.foreign: list[dict] = []
        #: This title's rows that could not be put back, still recorded.
        self.stuck: list[dict] = []
        self.speculative = False
        #: `(anchor_base, data_base)` as the state file last had them.
        self.bases: tuple[int | None, int | None] = (None, None)

    def _load(self) -> dict:
        saved = self.state.load()
        if saved.get("title") == self.title:
            self.bases = (saved.get("anchor_base"), saved.get("data_base"))
        return saved

    # -- the state file --------------------------------------------------

    def _save(self, on: bool, rows: list[dict]) -> None:
        located = self.target.data_base is not None
        self.state.save({
            "on": on, "title": self.title, "speculative": self.speculative,
            "anchor_base": self.target.anchor_base if located else self.bases[0],
            "data_base": self.target.data_base if located else self.bases[1],
            "rows": self.foreign + [{**r, "title": self.title} for r in rows + self.stuck]})

    def _journal(self, rows: list[dict]) -> None:
        self._save(True, rows)

    # -- reaching the game -----------------------------------------------

    def _lane(self) -> None:
        """Prove this run holds the lane, once, before its first read or write."""
        if not self.checked:
            self.lane_check()
            self.checked = True

    def _ready(self, saved: dict) -> None:
        """Check the lane, and find the game: where `saved` says if its anchor
        is still there, otherwise by a sweep."""
        self._lane()
        if self.target.data_base is not None:
            return
        layout = self.target.layout
        anchor, data = saved.get("anchor_base"), saved.get("data_base")
        if saved.get("title") == self.title and isinstance(anchor, int) \
                and isinstance(data, int):
            at = anchor + layout.anchor_offset
            blocks = [(at, len(layout.anchor)), (anchor - 8, 4), (anchor - 4, 4),
                      (data - 8, 4)]
            self.memory.fetch(blocks)
            try:
                if (self.memory.read(at, len(layout.anchor)) == layout.anchor
                        and amiga.data_base_for(self.memory.read, layout,
                                                anchor) == data):
                    self.target.anchor_base, self.target.data_base = anchor, data
                    return
            except amiga.PipeError:
                raise
            except amiga.GuestError:
                pass    # moved: a new boot, found again below
            finally:
                self.memory.clear()
        self.target.locate()

    def _split(self, saved: dict) -> list[dict]:
        """This title's recorded rows; the others are kept as `foreign`."""
        self.foreign = [r for r in saved["rows"] if r.get("title") != self.title]
        return [r for r in saved["rows"] if r.get("title") == self.title]

    def _new_switch(self) -> EncounterSwitch:
        return EncounterSwitch(
            self.title, self.memory.resolve, self.memory.read, self.memory.write,
            speculative=self.speculative, inside=inside_memory,
            journal=self._journal)

    def _restore(self, rows: list[dict]) -> list[dict]:
        """`restore_row` for each row; the rows that failed stay in `stuck`."""
        self.memory.fetch([(int(r["address"]),
                            STATEMENT if r.get("kind", GATE) == GATE
                            else len(bytes.fromhex(r["changed"])))
                           for r in rows if isinstance(r.get("address"), int)
                           and isinstance(r.get("changed"), str)])
        done, self.stuck = [], []
        try:
            for row in rows:
                try:
                    result = restore_row(self.memory.read, self.memory.write,
                                         self.memory.resolve, row)
                except (*WINUAE_ERRORS, KeyError, TypeError) as exc:
                    result = {"row": row, "error": f"{type(exc).__name__}: {exc}"}
                if "error" in result:
                    self.stuck.append(row)
                done.append(result)
        finally:
            self.memory.clear()
        return done

    def _take_over(self, saved: dict) -> list[dict]:
        """Build the switch from a state that is on, adopting its rows; the
        rows it cannot adopt are put back."""
        self.speculative = bool(saved.get("speculative"))
        self.switch = self._new_switch()
        self.memory.prefetch(self.switch.rows)
        try:
            left = self.switch.adopt(self._split(saved))
        finally:
            self.memory.clear()
        done = self._restore(left) if left else []
        self._save(True, self.switch.outstanding())
        return done

    def _apply(self) -> list[dict]:
        self.memory.prefetch(self.switch.rows)
        try:
            return self.switch.apply()
        finally:
            self.memory.clear()

    # -- the commands ----------------------------------------------------

    def on(self, speculative: bool = False) -> dict:
        """Put back what an earlier run left, change every loaded row, and
        record the switch as on."""
        saved = self._load()
        if saved.get("title") not in (None, self.title) and saved["on"]:
            raise ValueError(f"no_encounters is on for {saved['title']}; "
                             "`off` first")
        others = sorted({str(r.get("title")) for r in saved["rows"]
                         if r.get("title") != self.title})
        if others:
            raise ValueError(
                f"{self.state.path} still records changes to {', '.join(others)}, "
                "which this switch cannot put back: run `noencounters.py --holder "
                f"H --title {others[0]} off` with that game running, or delete the "
                "file once it is not")
        self._ready(saved)
        repaired = self._restore(self._split(saved))
        if self.stuck:
            self._save(False, [])
            raise ValueError("a recorded change is still in the game and was "
                             "not put back; `off` tries again")
        self.speculative = speculative
        self.switch = self._new_switch()
        self._save(True, [])
        try:
            done = self._apply()
        except WINUAE_ERRORS:
            # Whatever did not go back stays recorded, so a save is blocked
            # and the next `on` or `off` tries again.
            self.switch.off()
            self._save(False, self.switch.outstanding())
            self.switch = None
            raise
        return {"action": "on", "repaired": repaired, "rows": done,
                "held": [r.spec for r in self.switch.rows if r.kind != NONE]}

    def off(self) -> dict:
        """Put every recorded change back and record the switch as off."""
        saved = self._load()
        if saved["on"] and saved.get("title") != self.title:
            raise ValueError(f"no_encounters is on for {saved['title']}, not "
                             f"{self.title}")
        own = self._split(saved)
        if self.switch is not None:
            own = self.switch.outstanding()
            self.switch = None
        self._lane()
        if not own:
            self._save(False, [])
            return {"action": "off", "rows": []}
        self._ready(saved)
        done = self._restore(own)
        self._save(False, [])
        result = {"action": "off", "rows": done}
        if self.stuck:
            result["error"] = ("no_encounters off did not restore every row; "
                               "the script is still changed")
        return result

    def keys(self, names: list[str]) -> dict:
        """Press `names` in order, applying the switch again before each while it
        is on; block the whole line, pressing nothing, when one is a save key
        while the switch is on or a change of any title may still be in the
        game.  A key that cannot be pressed ends the line: the result's `error`
        says why and `pressed` holds the keys that went in."""
        try:
            saved = self._load()
        except StateError as exc:
            if is_save_key(" ".join(names)):
                return {"action": "keys", "stopped": str(exc), "pressed": []}
            raise
        if is_save_key(" ".join(names)) and (saved["on"] or saved["rows"]):
            titles = sorted({str(r.get("title")) for r in saved["rows"]}
                            | ({str(saved.get("title"))} if saved["on"] else set()))
            return {"action": "keys", "pressed": [],
                    "stopped": ("no_encounters is on or a change it made is "
                                f"still in the game ({', '.join(titles)}), and a "
                                "save carries the changed script: turn it off "
                                "first")}
        if saved["on"] and saved.get("title") != self.title:
            raise ValueError(f"no_encounters is on for {saved['title']}, not "
                             f"{self.title}")
        result = {"action": "keys", "pressed": [], "applied": []}
        try:
            if saved["on"] and self.switch is None:
                self._ready(saved)
                result["repaired"] = self._take_over(saved)
            for name in names:
                if self.switch is not None:
                    done = self._apply()
                    if done:
                        result["applied"].append({"before": name, "rows": done})
                self.press(name)
                result["pressed"].append(name)
        except WINUAE_ERRORS as exc:
            # The keys already pressed are in the game; the caller needs them.
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result


def main(argv: list[str] | None = None) -> int:
    """`no_encounters` against WinUAE, from Linux through `winvm`."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="Switch an Amiga Gold Box title's random encounters off and "
                    "on under WinUAE, and press keys while it is off.  Never for "
                    "conversion proof; `off` before any save.")
    parser.add_argument("--holder", help="the winuae.ps1 lane claim this run holds")
    parser.add_argument("--title", choices=sorted(amiga.MACHINES),
                        help="the running title (for keys and off, the state's)")
    parser.add_argument("--settle", type=float, default=1.5,
                        help="seconds to wait after each key (default 1.5)")
    sub = parser.add_subparsers(dest="command", required=True)
    on = sub.add_parser("on", help="change every loaded roll, and keep it changed")
    on.add_argument("--speculative", action="store_true",
                    help="hold the SPECULATIVE rest rows too")
    sub.add_parser("off", help="put every changed byte back")
    keys = sub.add_parser("keys", help="press amigadrive keys, applying the switch "
                                       "before each while it is on")
    keys.add_argument("names", nargs="+")
    sub.add_parser("status", help="print the state file")
    args = parser.parse_args(argv)

    if args.holder is None:
        parser.error("--holder is needed")
    try:
        state = WinuaeState(winuae_state_path(args.holder))
    except ValueError as exc:
        parser.error(str(exc))
    old = state.path.parent / "winuae.json"
    if old.exists():
        print(f"{old} holds encounter state from before per-holder files; "
              "restore it with the old holder or delete it.")
        return 1
    try:
        saved = state.load()
    except StateError as exc:
        if args.command != "keys":
            print(json.dumps({"action": args.command, "error": str(exc)}))
            return 1
        saved = dict(WinuaeState.EMPTY)
    if args.command == "status":
        print(json.dumps(saved, indent=1))
        return 0
    title = args.title or saved.get("title")
    if title is None:
        parser.error("--title is needed: the state names no title")
    from tools.amiga import amigadrive  # noqa: PLC0415

    pipe = amiga.WinuaePipe(holder=args.holder)
    enc = WinuaeEncounters(
        title, amiga.AmigaTarget(pipe, amiga.MACHINES[title]), state=state,
        lane_check=lambda: pipe.drives(args.holder),
        press=lambda name: amigadrive.press(args.holder, name, args.settle))
    try:
        if args.command == "on":
            result = enc.on(args.speculative)
        elif args.command == "off":
            result = enc.off()
        else:
            result = enc.keys(args.names)
    except WINUAE_ERRORS as exc:
        print(json.dumps({"action": args.command,
                          "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(result))
    return 1 if "error" in result or "stopped" in result else 0


if __name__ == "__main__":
    sys.exit(main())
