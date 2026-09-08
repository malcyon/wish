"""The two ports' thief-skill tables, read off the player's own files.

Everything here reads the game at run time -- the C64's `GEN` off whichever
`POOL*.D64` carries it, the DOS tables out of the EXEPACK-expanded
`START.EXE` -- and skips cleanly when a machine has neither.  No table is
committed; what is asserted is the *relationship* between the two ports,
which is the finding `#431` rests on.
"""

import pathlib
import sys

import pytest
from gamedata import disk_dir

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import thiefskillcensus as census  # noqa: E402

POOL = "pool-of-radiance"
CURSE = "curse-of-the-azure-bonds"

#: `race - 1`, which is what `GEN $2005 LDY $6B72 / DEY` makes the index.
HALFLING = 5 - 1
GNOME = 3 - 1
HALF_ELF = 4 - 1
HALF_ORC = 6 - 1


def _c64(title=POOL):
    if disk_dir() is None and title == POOL:
        pytest.skip("needs the Pool of Radiance disks; set $POR_DISKS")
    try:
        return census.c64_tables(title)
    except SystemExit as e:
        pytest.skip(str(e))


def _dos(title=POOL):
    from tools import dosbox

    if not dosbox.ARCHIVES.is_dir():
        pytest.skip("needs the DOS archives; set FR_ARCHIVES")
    try:
        return census.dos_tables(title)
    except (SystemExit, FileNotFoundError, KeyError) as e:
        pytest.skip(str(e))


def test_the_dos_blocks_are_where_the_geometry_says_they_are():
    """The human row is zeros and dexterity 13, 14 and 15 adjust nothing.

    Both are arithmetic rather than judgement, and either failing means the
    racial block was not found where this thinks it was.
    """
    tables = _dos()
    assert census.check_dos_geometry(tables, POOL) == []
    assert len(tables["level"]) == 9      # Pool of Radiance's thief ceiling


def test_the_two_ports_ship_different_halfling_rows():
    """`#431`: the C64's halfling row is not the DOS build's.

    The DOS row is AD&D 1st edition's published adjustment; the C64's is that
    row from find-traps onward displaced one column to the left.
    """
    c64 = _c64()["race"]
    dostab = _dos()["race"]
    assert dostab[HALFLING] == [5, 5, 5, 10, 15, 5, -15, -5]
    assert c64[HALFLING] == [5, 5, 10, 15, 5, -15, -5, -5]
    assert c64[HALFLING] != dostab[HALFLING]


def test_the_dwarf_and_elf_agree_and_the_other_four_races_do_not():
    """Which races the difference reaches, counted rather than assumed.

    The dwarf is `#431`'s control.  The half-elf was guessed unaffected when
    the issue was filed and is affected.
    """
    c64 = _c64()["race"]
    dostab = _dos()["race"]
    agree = [i for i in range(len(dostab)) if c64[i] == dostab[i]]
    differ = [i for i in range(len(dostab)) if c64[i] != dostab[i]]
    assert agree == [0, 1, 6]                     # dwarf, elf, human
    assert differ == [GNOME, HALF_ELF, HALFLING, HALF_ORC]


def test_the_c64_table_is_the_dos_one_a_byte_short():
    """One byte, not four wrong rows: the streams re-align at a shift of one.

    The two racial blocks agree for 21 bytes; from byte 22 the C64's stream is
    the DOS stream one byte later, to the end of the DOS table.  So the C64
    build is short a byte in the gnome's row and every race after it reads a
    row displaced one column, taking its last column out of the next race.
    """
    c64 = [v for row in _c64()["race"] for v in row]
    dostab = [v for row in _dos()["race"] for v in row]
    shared = 0
    while c64[shared] == dostab[shared]:
        shared += 1
    assert shared == 21
    tail = range(22, len(dostab) - 1)
    assert all(c64[i] == dostab[i + 1] for i in tail)


def test_curse_ships_the_same_racial_table_on_both_ports():
    """Which is what makes Pool of Radiance's C64 build the odd one out."""
    c64 = _c64(CURSE)["race"]
    dostab = _dos(CURSE)["race"]
    assert [row for row in c64[:len(dostab)]] == dostab


def test_pool_of_radiance_on_the_c64_never_reads_dexterity():
    """`GEN $1FEC` adds the level row and the racial row and returns.

    The C64 table set has no dexterity block at all, where every DOS build
    carries eleven rows of five from a dexterity of 9.  A conversion that
    recomputes has to drop the source's dexterity adjustment on the way to
    the C64 and add the destination's on the way to DOS.
    """
    assert _c64()["dex"] is None
    dostab = _dos()["dex"]
    assert len(dostab) == 11 and len(dostab[0]) == 5
    assert dostab[12 - census.DEX_FROM] == [0, 0, 0, -5, 0]


def test_every_dos_pool_of_radiance_record_reproduces():
    """Level row plus racial row plus dexterity row, clamped at zero.

    57 of 57 `.SAV` records and both archive `.CHA` exports on this machine
    when this was written.  The four `.CHA` files that miss are ours: they are
    the pre-party exports of characters `tools/dosgnome.py` and
    `tools/testparty.py` rolled and then poked, and their own `.SAV` twins
    agree, so the stored bytes are older than the record's race and dexterity.
    """
    tables = _dos()
    seen = misses = 0
    for _s, _n, race, level, dex, stored in census.dos_records(POOL):
        want = census.expected(tables, level, race, dex, True, clamp=True)
        if want is None:
            continue
        seen += 1
        misses += stored != want
    if not seen:
        pytest.skip("no DOS Pool of Radiance records on this machine")
    assert misses <= 4, f"{misses} of {seen} records miss"


#: C64 disks that are **not** the C64 engine's own arithmetic, and why.  Each
#: is a Wish conversion of a record from another port, so its thief skills are
#: whatever our writer put there -- which is `#431` itself.  The two Amiga ones
#: hold two *different* answers for the same character, which is the writer
#: having changed between them rather than the game disagreeing with itself.
#: `WISH-SPEC-por-c64-hall-resave`'s own provenance says it in those words:
#: "NOT EVIDENCE ABOUT THE GAME's arithmetic".
CONVERTED = frozenset(x.upper() for x in (
    "PORSAVEA.D64", "PORSAVEB.D64",
    "WISH-SPEC-por-52-dialog-converted-resave.D64",
    "WISH-SPEC-por-amiga-newphlan-c64-resave.D64",
    "WISH-SPEC-por-amiga-outdoor-c64-resave-walked.D64",
    "WISH-SPEC-por-amiga-slums-c64-resave.D64",
    "WISH-SPEC-por-c64-hall-as-newphlan.d64",
    "WISH-SPEC-por-c64-hall-resave.d64"))


def test_every_engine_written_c64_record_reproduces():
    """Level row plus racial row, and nothing else.

    Wish's own conversions are excluded by name above, because they hold
    whatever the writer of the day put there rather than the C64 engine's
    arithmetic.  What is left includes DAX, a halfling thief carrying the
    displaced row's own `-5` hear noise and `-5` read languages, and NYX, a
    gnome carrying the displaced gnome row.
    """
    tables = _c64()
    seen, misses = 0, []
    for source, name, race, level, dex, stored in census.c64_records(POOL):
        if source.split(":")[0].upper() in CONVERTED:
            continue
        want = census.expected(tables, level, race, dex, False)
        if want is None:
            continue
        seen += 1
        if stored != want:
            misses.append(f"{source} {name} {stored} != {want}")
    if not seen:
        pytest.skip("no C64 records on this machine")
    assert misses == [], f"{len(misses)} of {seen}: {misses}"


def test_a_c64_halfling_thief_holds_the_displaced_row():
    """The stored bytes, not only the table: `-5` hear noise on a real record.

    One record on this machine -- DAX, halfling thief 1 on `PORSAVE10.D64` --
    and its eight bytes are the C64 table's answer exactly, including the two
    negatives stored as `$FB`.  Nobody watched that disk being written, so it
    corroborates `GEN $1FEC` rather than standing on its own.
    """
    tables = _c64()
    found = []
    for source, name, race, level, dex, stored in census.c64_records(POOL):
        if source.split(":")[0].upper() in CONVERTED or race != 5:
            continue
        found.append((source, name, stored,
                      census.expected(tables, level, race, dex, False)))
    if not found:
        pytest.skip("no C64 halfling thief on this machine")
    for source, name, stored, want in found:
        assert stored == want, f"{source} {name}"
        assert stored[5] < 0 and stored[7] < 0, f"{source} {name} {stored}"


def test_the_dos_dexterity_block_holds_two_bytes_the_c64_does_not():
    """`docs/125-bug-notes.md` N22: `-19` at dexterity 10 and `-5` at 16.

    AD&D 1st edition gives -10 and +5, and the C64's own copy of the same
    table in Curse holds -10 and +5 -- so the two odd bytes are the DOS
    build's rather than a misread block here.  All 53 other bytes agree.
    """
    c64 = _c64(CURSE)["dex"]
    dostab = _dos(CURSE)["dex"]
    assert dostab[10 - census.DEX_FROM][0] == -19
    assert c64[10 - census.DEX_FROM][0] == -10
    assert dostab[16 - census.DEX_FROM][1] == -5
    assert c64[16 - census.DEX_FROM][1] == 5
    differ = [9 + i for i in range(len(dostab))
              if c64[i][:census.DEX_COLUMNS] != dostab[i]]
    assert differ == [10, 16]
