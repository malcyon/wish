"""The disk Wish builds from nothing, read back the way the game reads it.

`tests/test_dosconvert.py` checks what `goldbox/dos.py` writes into the two
payloads.  This module goes one step further out, to the thing a player is
handed: a `.d64` image built by `goldbox.dos.save_disk`, serialised, reopened
from its bytes, and read back through `goldbox.savegame` and
`goldbox.c64_codec` -- the same path `editor/` takes when it opens a save.

**It is the part of #119 that can be pinned without an emulator, and no
more.**  Whether the game's own `LOAD SAVED GAME` accepts the disk, what the
status line says and what the combat floor draws are all questions only a
running C64 answers, and `docs/122-release-testing.md` §9 is where the recipe
for asking them lives.  What a file *can* prove is that every number a person
would read off the character sheet is the DOS party's own -- and that is
worth pinning, because three of the faults this project has shipped were a
sheet reading wrong over bytes that checked out: an AC of 9 displayed as 51,
a dropped combat tail, and a garbage weapon line.

The saves are the player's, in their unpacked *Forgotten Realms: The
Archives*; with no archives and no game disks every test here skips.
"""
from __future__ import annotations

import gamedata
import pytest
from conftest import load_tools_module
from test_dossave import _save_dir, needs_dos_saves

from goldbox import c64_codec, dos, items, savegame
from goldbox import dos_savegame as sg
from goldbox import portraits as portraits_mod
from goldbox.d64 import D64

#: `60 - value` is the family's encoding for armour class and THAC0 alike --
#: `goldbox/dos_layout.py` 0x110 and 0x111, where SILAS' 63 is AC -3.  Both
#: ports store the biased byte and both display the difference, so a test that
#: compared the displayed numbers would prove less than one that compares the
#: bytes: an off-by-fifty is exactly the fault that shipped.
DISPLAY_BIAS = 60

#: The fields a person reads off the `VIEW` sheet, in both ports' own names.
#: Every one of them has to survive the crossing, and a field that quietly
#: became zero would pass every provenance check in the repository -- the
#: bytes would still be "written by the conversion".
SHEET_FIELDS = (
    "strength", "intelligence", "wisdom", "dexterity", "constitution",
    "charisma", "age", "experience", "hp_current", "hp_max",
    "armour_class", "thac0_current",
    "copper", "silver", "electrum", "gold", "platinum", "gems", "jewelry",
)


def _game_files():
    """The composed icon and `ANIMATE00` off the player's own disks, or skip.

    The same pair `editor/window.py` reads before it opens the import dialog;
    neither may be stored here, so both are read at run time.
    """
    import gamedata

    from goldbox.d64 import load_payload
    from goldbox.iconparts import IconParts

    where = gamedata.disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    icon = animate = None
    for disk in sorted(where.glob("POOL*.[dD]64")):
        try:
            icon = icon if icon is not None else \
                IconParts.load(str(disk)).default_icon()
        except Exception:
            pass
        try:
            animate = animate if animate is not None else \
                load_payload(str(disk), dos.ANIMATE_FILE)
        except Exception:
            pass
    if icon is None or animate is None:
        pytest.skip("no POOL disk here carries SPELLE64 or ANIMATE00")
    return icon, animate


def _built(slot: str, tmp_path):
    """A `.d64` written to disk and reopened from its own bytes.

    Going out through a file and back is the point: `save_disk` hands back a
    live `D64`, and reading the party off *that* would never notice a BAM, a
    directory entry or a sector chain that the image cannot be reconstructed
    from.  The game reads the file.
    """
    icon, animate = _game_files()
    save0, save1, report = dos.new_save(_save_dir(), slot, icon, animate)
    path = tmp_path / f"NEW{slot}.D64"
    path.write_bytes(bytes(dos.save_disk(bytes(save0), bytes(save1)).data))
    return D64.open(path), report


def _read_back(disk):
    """Every character the game would list, as neutral records.

    Keyed by name rather than by slot, because reading the expected slot back
    through `marching_slot` would make the test agree with the code by
    construction -- the same reason
    `test_the_converted_inventory_follows_its_owner_to_the_reversed_slot`
    keys on the name.
    """
    _game, sg0, sg1 = savegame.load_save(disk)
    payload = sg0.to_bytes()
    out = {}
    for slot in sg0.slots:
        if not slot.occupied:
            continue
        carried = [bytes(i.raw) for i in items.items_for_slot(payload, slot.index)]
        out[slot.record.name] = (slot.index, c64_codec.read(
            slot.record, roster=sg1.roster(slot.index), inventory=carried))
    return sg0, out


def _slots():
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    found = dos.slots_available(where)
    if not found:
        pytest.skip("no DOS Pool of Radiance slot here")
    return found


@needs_dos_saves
def test_every_sheet_number_on_the_built_disk_is_the_dos_partys_own(tmp_path):
    """The character sheet, field for field, through the whole `.d64`.

    This is #119 step 3 -- *"read the party off the sheet against the DOS
    sheet: names, classes, levels, hit points, experience, money"* -- reduced
    to what a file can answer.  It is deliberately a comparison of two
    independently read records rather than of the conversion against itself:
    the DOS side comes from `dos.to_neutral` off `CHRDAT<slot><n>.SAV`, the
    C64 side from `c64_codec.read` off the built image, and the two meet only
    in the neutral record.

    Sample: every slot the player's DOS folder holds, every character in each.
    """
    checked = 0
    for slot in _slots():
        party = dos.read_party(_save_dir(), slot)
        disk, _report = _built(slot, tmp_path)
        _sg0, back = _read_back(disk)
        assert sorted(back) == sorted(c.name for c in party), slot
        for source in party:
            want = dos.to_neutral(source).fields
            _place, got = back[source.name]
            for field in SHEET_FIELDS:
                if field not in want:
                    continue
                assert field in got.fields, (slot, source.name, field)
                assert got.fields[field].value == want[field].value, \
                    (slot, source.name, field)
            # The two the sheet shows as a difference rather than as the byte,
            # which is where an AC of 9 once reached a player as 51.
            assert DISPLAY_BIAS - got.fields["armour_class"].value \
                == DISPLAY_BIAS - want["armour_class"].value
            # Levels on the classes both ports have.  DOS numbers druid and
            # monk and the C64 does not, and the C64 numbers knight and DOS
            # does not -- `dos.CLASS_LEVEL_SLOTS`.  A druid or a monk would
            # be a real loss and no DOS Pool of Radiance character can be
            # one, so the two absent slots are asserted empty rather than
            # skipped.
            here, there = got.fields["levels"].value, want["levels"].value
            shared = set(here) & set(there)
            assert {k: here[k] for k in shared} == {k: there[k] for k in shared}, \
                (slot, source.name)
            assert not any(there[k] for k in set(there) - shared), \
                (slot, source.name, "a class the C64 has no slot for")
            # And the items, which are not on the sheet as a number but are
            # on it as a readied weapon and a readied armour. A character
            # whose inventory came apart from its record shows somebody
            # else's -- the garbage weapon line this project shipped once.
            assert len(got.fields["inventory"].value) == \
                len(want["inventory"].value), (slot, source.name)
            checked += 1
    assert checked >= len(_slots()), "no character was compared"


@needs_dos_saves
def test_the_built_disk_lists_the_dos_party_and_nobody_else(tmp_path):
    """Six characters in, six out, in the C64's own marching order.

    A seventh name in the party panel is what #104 was: the C64 holds eight
    slots and a DOS save six, so the two above the party are somebody else's
    unless something empties them.

    **The empty half of this is weaker than it looks and says so on purpose.**
    From a zeroed buffer slots 6 and 7 are empty by construction, so removing
    the zeroing would not turn it red; what it catches is something *writing*
    into a slot the party does not fill. The half that can fail is the
    order -- making `marching_slot` the identity puts the DOS party's
    front-rank fighter at the back and this goes red, which was checked by
    breaking it.
    """
    for slot in _slots():
        party = [c.name for c in dos.read_party(_save_dir(), slot)]
        disk, _report = _built(slot, tmp_path)
        _game, sg0, sg1 = savegame.load_save(disk)
        listed = [s.record.name for s in sg0.slots if s.occupied]
        # Highest slot first is the C64's marching order (#101).
        assert list(reversed(listed)) == party, slot
        for place in range(len(party), savegame.SLOT_COUNT):
            assert not sg0.slots[place].occupied, (slot, place)
            assert not sg1.roster(place).occupied, (slot, place)


@needs_dos_saves
def test_the_built_disk_shows_the_dos_saves_own_clock_and_square(tmp_path):
    """The status line: `S 10:56 14,5` for slot J, and its own for each other.

    #103 was found by a person noticing a clock reading 21:15 when the source
    save said 10:15, so the clock is checked against the DOS container rather
    than against a number written down here.  The square goes with it because
    both are read off the same one line of the game's screen.
    """
    for slot in _slots():
        savgam = (_save_dir() / f"SAVGAM{slot}.DAT").read_bytes()
        if sg.outdoors(savgam):
            continue                     # the travel pair, not this square
        x, y, facing = sg.position(savgam)
        hour, minute, _day, _month = sg.clock(savgam)
        disk, _report = _built(slot, tmp_path)
        _game, sg0, _sg1 = savegame.load_save(disk)
        assert (sg0.party.x, sg0.party.y, sg0.party.facing) == (x, y, facing), slot
        assert sg0.party.clock == (hour, minute), slot


@needs_dos_saves
def test_no_character_on_the_built_disk_would_draw_as_black_hooks(tmp_path):
    """An icon of all zeros is not "no icon" (#57).

    Screen code 0 in `CHARPIC00` is a real glyph, so a zeroed 36-byte icon
    draws as a 3x3 block of black hooks on the combat floor -- which is why
    the conversion composes the icon the game's own character creation
    writes.  The failure this catches is a conversion that stops supplying
    one: `new_save` demands an `icon`, but nothing else asserts that what
    reaches the disk is a figure rather than a hole.

    The 216 bytes of the six party icons were the last entry on #118's list,
    and this is their file-level half; the other half is a fight, and only
    the running game can hold that.
    """
    from goldbox import icons

    icon, _animate = _game_files()
    for slot in _slots():
        party = dos.read_party(_save_dir(), slot)
        disk, _report = _built(slot, tmp_path)
        _game, sg0, _sg1 = savegame.load_save(disk)
        payload = sg0.to_bytes()
        for place in range(savegame.SLOT_COUNT):
            drawn = icons.icon_for_slot(payload, place).raw
            if place < len(party):
                assert drawn == icon, (slot, place)
                assert any(drawn), f"{slot} slot {place} draws as black hooks"
            else:
                assert drawn == bytes(len(icon)), (slot, place)


@needs_dos_saves
def test_build_wires_the_creation_menu_into_the_disk_it_writes(tmp_path):
    """`tools/dosdisk.py`'s `build()` reads the creation menu (#57) off the
    same disks directory it already reads the icon and `ANIMATE00` from, and
    passes it on to `dos.new_save` -- so a party wholly inside the menu
    arrives on the disk with the sheet portrait switched on rather than with
    every face silently dropped.

    This is the wiring, not the conversion: `tests/test_dosconvert.py`
    already proves `new_save(..., portraits=tables)` sets the switch. What
    was missing is `build()` ever calling `tables_from_disks` at all --
    before this it always passed `portraits=None`, so `$49FF` came out
    `dos.PORTRAIT_OFF` for every party, however complete its faces were.
    """
    dosdisk = load_tools_module("dosdisk")

    where = gamedata.disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    try:
        tables = portraits_mod.tables_from_disks(where)
    except portraits_mod.PortraitError:
        pytest.skip("no side here carries the creation menu")

    save_dir = _save_dir()
    slot = None
    for candidate in dos.slots_available(save_dir):
        party = dos.read_party(save_dir, candidate)
        neutral = [dos.to_neutral(c, portraits=tables) for c in party]
        if all("portrait_head" in n and "portrait_body" in n
               for n in neutral):
            slot = candidate
            break
    if slot is None:
        pytest.skip("no DOS slot here has every character in the menu")

    out = tmp_path / f"NEW{slot}.D64"
    dosdisk.build(save_dir, slot, where, out)
    _game, sg0, _sg1 = savegame.load_save(D64.open(out))
    payload = sg0.to_bytes()
    at = dos.PORTRAIT_SWITCH - dos.SAVE0_BASE
    assert payload[at] == dos.PORTRAIT_ON


@needs_dos_saves
def test_a_disk_built_from_nothing_leaves_no_byte_to_the_payload(tmp_path):
    """`Report.unwritten` empty, for every slot, all the way to the image.

    `tests/test_dosconvert.py` asserts this of `new_save`'s payloads; this
    asserts it of the disk, so a `save_disk` that ever grew a region of its
    own would have to account for it too.
    """
    for slot in _slots():
        disk, report = _built(slot, tmp_path)
        assert report.unwritten == [], slot
        assert report.unaccounted == [], slot
        assert [bytes(e.name) for e in disk.directory()] == \
            [b"SAVEDGAME1", b"SAVEDGAME0"], slot
