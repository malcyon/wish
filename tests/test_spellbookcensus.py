"""What `tools/spellbookcensus.py` asked, and the answer read off the disks.

`#411 (Nobody knows whether a converted cleric loses Restoration, because the
spellbook field is one bit short of the game's own spell list)` asks whether a
character can carry Pool of Radiance's spell id 56, which the DOS record has a
byte for and the C64 record has no bit for.  The census answers it over 840
records; these are the parts of that answer a change to this repository could
break, plus the reading of the engine that says the id is unreachable.

The corpus counts themselves are on the issue rather than asserted here: they
move whenever somebody adds a save disk, and a test that pins them would fail
for the wrong reason.  What is pinned is the geometry the question rests on and
the three sites in the player's own `GEN` that decide it.
"""

from __future__ import annotations

import pytest

from goldbox import dos_port as dl
from goldbox import spells
from tests import gamedata
from tools import spellbookcensus as census


def test_the_dos_array_can_say_something_the_c64_mask_cannot():
    """The premise of the ticket, from the two layouts rather than from it.

    DOS spends 56 bytes at `0x033` for ids 1..56; the C64 spends 7 bytes at
    `0x078` for a mask whose top usable bit is id 55.  If either width ever
    changes, the question the census answers stops being the question.
    """
    book = dl.FIELDS_BY_NAME_FOR["pool-of-radiance"]["spellbook"]
    assert (book.offset, book.size) == (0x033, 56)
    table = spells.POOL_OF_RADIANCE
    assert table.last_spell == 56
    assert table.spellbook_size == 7
    assert table.last_spellbook_spell == 55
    assert not table.in_spellbook(56)


def test_the_mask_reader_agrees_with_the_module_the_rest_of_the_code_uses():
    """`_ids_from_mask` must index bits the way `spells.spells_known` does.

    A census that read the mask its own way could report a whole port's worth
    of spells at the wrong ids and look entirely plausible doing it.
    """
    record = bytearray(0x100)
    wanted = (1, 8, 9, 55)
    for i in wanted:
        record[0x078 + (i >> 3)] |= 1 << (i & 7)
    assert spells.spells_known(bytes(record)) == list(wanted)
    book = bytes(record[0x078:0x078 + census.C64_BOOK_BYTES])
    assert census._ids_from_mask(book, first_id=1) == wanted


def test_a_record_is_graded_by_where_it_was_found():
    """The played DOS directory is the one whose records were all edited."""
    assert census._grade("/home/x/dos_por_play/SAVE/CHRDATA1.SAV") == "edited"
    assert census._grade("/home/x/wish-specimens/por-dos/a.sav") == "spec"
    assert census._grade("/x/wish/work/issue1/a.sav") == "work"
    assert census._grade("/x/fr-archives/games/POOLRAD/a.sav") == "found"


def test_the_row_reports_only_ids_past_the_titles_own_mask():
    row = census.Row(port="dos", title="pool-of-radiance", where="x", who="y",
                     klass="cleric", known=(1, 44, 56), reach=55, last_spell=56)
    assert row.beyond == (56,)
    assert row.is_cleric


def test_a_title_with_no_spell_table_is_not_measured_against_pool_of_radiance():
    """`spells.for_game` answers Pool of Radiance for a key it does not know.

    Three of Wish's six C64 titles have no table here, and their disks sit
    beside the registered ones, so the sweep reads them. Measured against a
    55-spell ceiling, a Death Knights of Krynn book reports ids "past the
    mask" that are simply spells in a list nobody has read.
    """
    assert "death-knights-of-krynn" not in spells.BY_KEY
    assert spells.for_game("death-knights-of-krynn") is spells.POOL_OF_RADIANCE
    row = census.Row(port="c64", title="death-knights-of-krynn", where="x",
                     who="y", klass="cleric", known=(70,), reach=55,
                     last_spell=56, has_table=False)
    assert row.beyond == ()


def test_a_deduplicated_record_is_graded_over_every_path_it_was_found_at():
    """The specimen tree decides, whichever path the finder happened to sort
    first -- `tools/carryceiling.py` mis-graded THRENDER GRONE this way."""
    assert census._grade_over(["/x/work/issue1/a.sav",
                               "/home/x/wish-specimens/por-dos/a.sav"]) == "spec"
    assert census._grade_over(["/x/work/issue1/a.sav",
                               "/home/x/dos_por_play/SAVE/a.sav"]) == "edited"
    assert census._grade_over(["/x/work/issue1/a.sav"]) == "work"


@gamedata.needs_disks
def test_the_games_own_table_names_56_restoration_and_57_a_message():
    """Read off the player's `SPELLN00`, not taken from the ticket."""
    names = spells.load_spell_names(str(gamedata.game_disk("POOL1")))
    assert names[56] == "RESTORATION"
    assert names[55] == "SLOW"
    # 57 onwards is the combat-message tail, so 56 really is the last spell.
    assert not names[57].startswith(("CURE", "PROTECTION", "RESTOR"))


@gamedata.needs_disks
def test_the_cleric_grant_stops_two_bytes_below_the_one_that_would_hold_56():
    """`GEN`'s cleric grant writes `0x07A`-`0x07D` and nothing higher.

    The whole routine is four `ORA` stores gated on the cleric level at
    `0x0CA`: `CPX #$03` grants ids 22-28 (`$C0` into `0x07A`, `$1F` into
    `0x07B`) and `CPX #$05` grants ids 36-44 (`$F0` into `0x07C`, `$1F` into
    `0x07D`).  There is no third gate, so no cleric of any level is granted a
    spell above id 44 -- which is why the byte holding id 56 cannot be reached
    from the cleric side.
    """
    gen = gamedata.game_file("GEN")
    grant = bytes.fromhex("AD7A6B09C08D7A6BAD7B6B091F8D7B6B")
    assert gen.count(grant) == 1, "the cleric level-2 grant moved"
    third = bytes.fromhex("AD7C6B09F08D7C6BAD7D6B091F8D7D6B")
    assert gen.count(third) == 1, "the cleric level-3 grant moved"
    # Nothing ORs into the byte that would carry id 56.
    assert bytes.fromhex("AD7F6B09") not in gen


@gamedata.needs_disks
def test_the_learn_menu_refuses_every_id_from_56_up():
    """`CPX #$38 / BCS` in `GEN`'s magic-user menu builder.

    The builder walks a 32-byte copy of the mask, so it *could* offer ids far
    past the game's own list; the compare is the engine saying which ids are
    spells.  Its two lookup tables end at id 55 as well -- the byte after each
    is the next routine's first opcode -- so an id of 56 has no spell level
    and no class in this game at all.
    """
    gen = gamedata.game_file("GEN")
    at = gen.find(bytes.fromhex("E038B0"))          # CPX #$38 / BCS
    assert at > 0, "the learn menu's id ceiling moved"
    base = 0x800
    levels = gen[0x268E - base:0x268E - base + 56]
    flags = gen[0x226B - base:0x226B - base + 56]
    # Ids 1-21 are spell level 1, 22-35 level 2, 36-55 level 3 -- the six
    # groups `goldbox/spells.py` names, in the game's own hand.
    assert set(levels[1:22]) == {1}
    assert set(levels[22:36]) == {2}
    assert set(levels[36:56]) == {3}
    assert set(flags[1:9]) == {1} and set(flags[9:22]) == {0}
    assert set(flags[22:29]) == {1} and set(flags[29:36]) == {0}
    assert set(flags[36:45]) == {1} and set(flags[45:56]) == {0}
    # Index 56 is not a table entry: it is the first byte of the code that
    # follows each table.
    assert gen[0x268E - base + 56] == 0xA9         # LDA #
    assert gen[0x226B - base + 56] == 0x20         # JSR


@gamedata.needs_disks
def test_no_pool_of_radiance_record_on_the_c64_disks_sets_the_missing_id():
    """The census's own answer, over whatever C64 saves this machine holds.

    Asserted as "none", not as a count: the count is the issue's business and
    a new save disk would move it, while a single record setting id 56 is the
    finding that would reopen the ticket.
    """
    rows = [r for r in census.c64_rows() if r.title == "pool-of-radiance"]
    # The finder takes the parent of each registered disk directory as well,
    # so the three C64 titles with no `gamedisks.toml` entry are read too;
    # `has_table` keeps their books from being measured against Pool of
    # Radiance's 55-spell ceiling, which is what `beyond` would otherwise do.
    assert all(r.has_table for r in rows)
    if not rows:
        pytest.skip("no C64 Pool of Radiance save on this machine")
    assert [r.who for r in rows if r.beyond] == []
    assert [r.who for r in rows if any(r.raw_tail)] == []
    # And the field is not the magic-user's alone: every cleric here has one.
    clerics = [r for r in rows if r.is_cleric]
    assert clerics, "no cleric among the C64 records"
    assert [r.who for r in clerics if not r.known] == []
    # A cleric at the top of the game's grant holds exactly what `GEN $20C6`
    # ORs in and nothing above id 44 -- ids 1-8, 22-28, 36-44.
    top = [r for r in clerics if len(r.known) >= 24]
    for row in top:
        assert max(row.known) == 44, (row.who, row.known)
