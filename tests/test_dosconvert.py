from __future__ import annotations

"""Turning a DOS Pool of Radiance save into a C64 one, checked field by field.

`tests/test_dossave.py` measures the DOS file; this module checks what
`goldbox/dos.py` does with it.  The two halves of the promise in
`docs/117-save-conversion.md` are what most of these tests are:

* **losslessness** -- a DOS record read and handed back byte for byte, which
  is how a read-only decoder proves it understood the file;
* **nothing dropped silently** -- every field declared in `goldbox/dos_layout.py`
  has a disposition, and every byte of the 580-byte C64 record has a
  provenance.

**The saves are Donald's, not the repository's.**  They live in his unpacked
Steam copy of *Forgotten Realms: The Archives*; set `$FR_ARCHIVES` to point
somewhere else.  With no archives the file-reading tests skip, which is what
CI does -- the table tests above them do not need a save at all.
"""


import pathlib

import gamedata
import pytest
import yaml
from gamedata import needs_disks
from test_dossave import _game_dirs, _save_dir, needs_dos_saves

from goldbox import areas, dos, dos_layout, savegame, spells
from goldbox import dos_savegame as sg
from goldbox.layout import RECORD_SIZE as C64_RECORD_SIZE

# --- the tables, which need no save -----------------------------------------

def test_the_layout_tiles_the_record():
    """Every one of the 285 bytes belongs to exactly one entry, and every one
    of the item record's 63 likewise. `_build` raises on an overlap, so this
    is the other half: nothing falls out of the bottom."""
    assert sum(f.size for f in dos_layout.LAYOUT) == dos_layout.RECORD_SIZE
    assert sum(f.size for f in dos_layout.ITEM_LAYOUT) == dos_layout.ITEM_SIZE
    offsets = [f.offset for f in dos_layout.LAYOUT]
    assert offsets == sorted(offsets)


def test_every_declared_field_has_a_disposition():
    """The rule `docs/117` sets: a DOS field with no C64 home is *reported*.

    A field declared in the layout and named nowhere in `DIRECT`,
    `TRANSFORMED` or `DROPPED` would be one dropped in silence, which is the
    failure this test exists to make impossible.
    """
    declared = {f.name for f in dos_layout.LAYOUT
                if not f.name.startswith("gap_")}
    assert declared - set(dos.field_disposition()) == set()
    assert set(dos.field_disposition()) - declared == set()


def test_the_spell_id_space_is_shared():
    """DOS byte *n* of the spellbook is spell id *n + 1*, and the ids are the
    C64's own -- the DOS array's cleric-1 / mage-1 / cleric-2 / mage-2 /
    cleric-3 / mage-3 runs are `goldbox/spells.py`'s group boundaries exactly."""
    bounds = [(lo, hi) for lo, hi, _, _ in spells.SPELL_GROUPS]
    assert bounds == [(1, 8), (9, 21), (22, 28), (29, 35), (36, 44), (45, 55)]
    # 56 DOS bytes hold ids 1..56; the C64's seven bytes hold bits 1..55.
    assert dos_layout.SPELLBOOK_SPELLS == 56
    assert spells.LAST_SPELLBOOK_SPELL == 55


def test_the_class_level_permutation_covers_every_c64_slot():
    """DOS indexes its eight level slots by class *number*, the C64 by class
    *bit*. Druid and monk have no C64 slot; nothing else is lost."""
    fields = [f for _, _, f in dos.CLASS_LEVEL_SLOTS if f]
    assert set(fields) == {"level_cleric", "level_fighter", "level_paladin",
                           "level_ranger", "level_magic_user", "level_thief"}
    assert [n for n, _, f in dos.CLASS_LEVEL_SLOTS if f is None] == [1, 7]


def test_item_to_c64_is_the_harness_projection():
    """One copy of the projection. `tools/dosbox.py` re-exports this one."""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent
                           / "tools"))
    import dosbox
    assert dosbox.item_to_c64 is dos.item_to_c64


# --- the record, against real files -----------------------------------------

def _records():
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    out = [dos.read_character(p) for p in
           sorted(where.glob("*.SAV")) + sorted(where.glob("*.CHA"))
           if p.stat().st_size == dos_layout.RECORD_SIZE]
    if not out:
        pytest.skip("no DOS Pool of Radiance character records here")
    return out


@needs_dos_saves
def test_a_record_is_handed_back_unchanged():
    """Losslessness, in the form the DOS side can have it.

    The DOS file is read-only in practice -- `wish` never writes one -- but a
    reader has to be able to prove it understood the file, and handing the
    bytes back is that proof.
    """
    where = _save_dir()
    checked = 0
    for path in sorted(where.glob("*.SAV")) + sorted(where.glob("*.CHA")):
        if path.stat().st_size != dos_layout.RECORD_SIZE:
            continue
        assert dos.read_character(path).to_bytes() == path.read_bytes()
        checked += 1
    assert checked >= 24


@needs_dos_saves
def test_the_encumbrance_identity_balances():
    """`encumbrance = money + sum(weight x quantity)`, through the reader.

    The cheapest whole-record check there is: self-contained arithmetic across
    the money block, the item file and one derived field, so it confirms the
    money offsets, the 63-byte stride, the weight offset and the byte order
    at once. Sixteen of the eighteen saved characters balance and all six
    exports do; the two that miss carry a stack of darts whose cached name
    disagrees with the quantity byte.
    """
    exact = total = 0
    for char in _records():
        total += 1
        exact += char.get("encumbrance") == char.expected_encumbrance()
    assert total >= 24
    assert exact >= total - 2, f"{exact} of {total} balanced"


@needs_dos_saves
def test_an_export_carries_no_items():
    """An export zeroes the item count, which is the one systematic
    difference between a save slot and a `.CHA`. A stale `.ITM` sitting beside
    it must not be read as the character's inventory -- and the archives hold
    exactly that."""
    where = _save_dir()
    checked = 0
    for path in sorted(where.glob("*.CHA")):
        char = dos.read_character(path)
        assert char.items == ()
        assert char.get("encumbrance") == char.expected_encumbrance()
        checked += 1
    assert checked >= 6


@needs_dos_saves
def test_every_known_spell_is_one_its_owner_could_cast():
    """The transpose, checked the only way that does not assume it.

    Every byte set in the DOS spellbook falls in a `goldbox/spells.py` group whose
    class the character has, with no crossover in either direction: a level-1
    cleric sets exactly the eight first-level cleric ids, a level-3 magic-user
    sets the thirteen first-level and seven second-level magic-user ids.
    """
    casters = 0
    for char in _records():
        known = char.spells_known
        if not known:
            continue
        casters += 1
        bits = char.get("class_bits")
        for sid in known:
            group = spells.spell_group(sid)
            assert group is not None, (char.name, sid)
            school = group[0]
            assert (school == "cleric" and bits & 2) or \
                   (school == "magic-user" and bits & 1), (char.name, sid,
                                                           school)
    assert casters >= 8


@needs_dos_saves
def test_a_first_level_cleric_knows_the_eight_first_level_cleric_spells():
    """The sharpest single check on the ordering: eight bytes, in a row, at
    the start, and `goldbox/spells.py` says ids 1-8 are cleric level 1."""
    seen = 0
    for char in _records():
        levels = char.class_levels
        if levels != {"cleric": 1}:
            continue
        assert char.spells_known == list(range(1, 9)), char.name
        seen += 1
    assert seen >= 2


@needs_dos_saves
def test_conversion_accounts_for_every_byte():
    """`docs/117` makes this the test that replaces a round trip: for any
    offset in the output, say where that byte came from."""
    for char in _records():
        rec, report = dos.to_c64_record(char)
        assert len(rec.to_bytes()) == C64_RECORD_SIZE
        assert report.unaccounted == [], (char.name, report.unaccounted[:8])
        assert report.dropped


@needs_dos_saves
def test_the_converted_record_says_what_the_dos_one_said():
    """Field for field, on everything the two ports encode the same way."""
    for char in _records():
        rec, _ = dos.to_c64_record(char)
        assert rec.name == char.name
        assert rec.strength == char.get("strength")
        assert rec.exceptional_strength == char.get("exceptional_strength")
        assert rec.race == char.get("race")
        # The class byte copies because the two ports share one 18-entry
        # table; the bitmask copies because they share the bit order.
        assert rec.char_class == char.get("char_class")
        assert rec.class_bits == char.get("class_bits")
        assert rec.age == char.get("age")
        assert rec.hp_max == char.get("hp_max")
        assert rec.get("hp_current") == char.get("hp_current")
        assert rec.level == char.get("level")
        assert rec.thac0_base == char.get("thac0_base")
        assert rec.get("experience") == char.get("experience")
        assert spells.spells_known(rec.to_bytes()) == char.spells_known
        # Memorised spells: DOS fills from the end, the C64 from the start.
        assert [b for b in rec.get_raw("spells_memorised") if b] \
            == char.spells_memorised
        # The per-class levels, permuted.
        for _, name, field in dos.CLASS_LEVEL_SLOTS:
            if field:
                assert rec.get(field) == char.class_levels.get(name, 0)


@needs_dos_saves
def test_the_converted_items_are_the_dos_items():
    """Sixteen fixed C64 slots against a DOS chain of 63-byte records."""
    from goldbox.items import ITEM_SIZE as C64_ITEM_SIZE

    carried = 0
    for char in _records():
        rec, _ = dos.to_c64_record(char)
        inv = rec.get_raw("inventory")
        for n, item in enumerate(char.items[:16]):
            assert inv[n * C64_ITEM_SIZE:(n + 1) * C64_ITEM_SIZE] \
                == item.to_c64()
            carried += 1
        # Nothing past the last item.
        rest = inv[len(char.items[:16]) * C64_ITEM_SIZE:]
        assert rest == bytes(len(rest))
    assert carried >= 50


@needs_dos_saves
def test_a_character_with_no_thief_level_carries_no_thief_skills():
    """A cheap sanity check on the eight-byte block, and on the permutation
    that puts the thief level where the C64 keeps it."""
    for char in _records():
        rec, _ = dos.to_c64_record(char)
        if rec.get("level_thief"):
            continue
        assert all(rec.get(f) == 0 for f in
                   ("thief_pick_pockets", "thief_open_locks",
                    "thief_find_traps", "thief_climb_walls"))


@needs_dos_saves
def test_innate_effects_survive_and_running_ones_do_not():
    """The `.SPC` file splits in two, and the two ports share the id space.

    Curse's own importer keeps exactly the innate racial ids out of a Pool of
    Radiance `.spc`; `goldbox/traits.py` names the same numbers the same way --
    107 is elf sleep resistance and 124 is the half-elf's on both sides.
    Everything else is a running spell and must not reach the trait slots: a
    Bless with four rounds left on it would arrive as a permanent racial
    bonus, which is a defect a player can see.

    **The running ones used to be reported as dropped as well, and are not
    any more.**  Donald, 2026-08-27: *"For running effects, that would expire
    after a certain period of time, we do not need to report those. The user
    will not expect this to carry over, so reporting it is unnecessary."*  An
    innate effect that cannot be carried is the opposite case and is still
    reported -- `write`'s gnome line is the one specimen of it.  So what this
    asserts moved from "it is reported" to "it is not written", which is the
    thing a player would meet.
    """
    innate = running = 0
    for char in _records():
        rec, report = dos.to_c64_record(char)
        slots = [b for b in rec.get_raw("item_effects") if b]
        for e in char.effect_ids:
            if e in dos.INNATE_EFFECTS:
                assert e in slots, (char.name, e)
                innate += 1
            else:
                running += 1
                assert e not in slots, (char.name, e)
        assert not [d for d in report.dropped if d.startswith(".SPC effect")], \
            char.name
    assert innate >= 5
    assert running >= 2


@needs_dos_saves
def test_the_dropped_list_names_the_losses_a_player_would_notice():
    """What the import's report pane shows, which is not everything the
    conversion knows (#118, Donald's four corrections of 2026-08-27).

    Three kinds of line came off it: a field the C64 derives for itself, a
    running spell effect, and the three DOS icon fields, which became one
    sentence.  None of the three is a loss a player can see, and a pane of
    lines nobody can act on is what made him ask.

    **Nothing measured left the code.**  Every suppressed name is still in
    `DROPPED`, so `field_disposition` still accounts for it and
    `test_every_declared_field_has_a_disposition` still holds; every one
    still has its field note in `goldbox/dos_layout.py`.  This asserts both
    halves, because the failure worth catching is a fact being deleted rather
    than a line being hidden.
    """
    quiet = dos.UNREPORTED_DROPS | dos.ICON_DROPS
    declared = dict(dos.DROPPED)
    assert quiet <= set(declared), "a suppressed drop must still be declared"
    disposition = dos.field_disposition()
    for name in quiet:
        assert disposition[name].startswith("dropped:"), name

    seen = 0
    for char in _records():
        _rec, report = dos.to_c64_record(char)
        for name in quiet:
            assert not [d for d in report.dropped
                        if d.startswith(f"DOS {name} @")], (char.name, name)
        assert report.dropped.count(dos.COMBAT_ICON_DROP) == 1, char.name
        seen += 1
    assert seen >= 6, "needs a party to check against"


# --- the saved game ----------------------------------------------------------

def _savgam(slot: str) -> bytes:
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    path = where / f"SAVGAM{slot}.DAT"
    if not path.exists():
        pytest.skip(f"no SAVGAM{slot}.DAT here")
    return path.read_bytes()


@needs_dos_saves
def test_the_quest_flags_narrow_to_bytes():
    """A copy with a stride change: read the DOS word, write the C64 byte.

    Every nonzero word in the 217-entry window fits in a byte, so nothing is
    lost by narrowing. The counter counts: `$4AC1`, the commissions counter
    with ten `ADD 1` sites, reads 0, 1 and 2 across slots J, B and A, in the
    order the parties progressed.
    """
    counts = {}
    for slot in "JBA":
        save = _savgam(slot)
        flags = dos.quest_flags(save)
        assert len(flags) == dos.FLAGS_LAST - dos.FLAGS_FIRST + 1
        for addr in range(dos.FLAGS_FIRST, dos.FLAGS_LAST + 1):
            word = sg.word(save, addr)
            assert word <= 0xFF, (slot, hex(addr), word)
        counts[slot] = flags[0x4AC1 - dos.FLAGS_FIRST]
    assert counts["J"] < counts["B"] < counts["A"]


@needs_dos_saves
def test_the_sokal_keep_flags_are_set_together_or_not_at_all():
    """`work/reports/quest-flags.md` names six ECL15 flags that a party which
    has taken the keep sets to 255. A base off by one would straddle them."""
    addresses = (0x4A21, 0x4A26, 0x4A27, 0x4A28, 0x4A29, 0x4AD7)
    states = set()
    for slot in "JBA":
        save = _savgam(slot)
        values = {sg.word(save, a) for a in addresses}
        assert values in ({0}, {255}), (slot, values)
        states.add(frozenset(values))
    assert len(states) == 2, "no save differs, so this proves nothing"


@needs_dos_saves
def test_the_party_square_and_area_read_out():
    """Four reads and a halving. Facing is the C64's value doubled on DOS."""
    for slot in "JBA":
        save = _savgam(slot)
        x, y, facing = sg.position(save)
        assert 0 <= x < 32 and 0 <= y < 32
        assert facing in (0, 1, 2, 3)
        assert save[sg.POS_FACING] in (0, 2, 4, 6)
        assert 0 <= sg.area_id(save) < 32
        assert 1 <= sg.dax_number(save) <= 8
        # The engine keeps the same area id twice, at $49C5 and $49F2.
        assert sg.word(save, sg.SCRIPT) == sg.area_id(save)


@needs_dos_saves
def test_the_flags_and_the_square_land_where_a_c64_save_keeps_them():
    """Steps 5 and 6 against a blank `SAVEDGAME0` window: the flags go to
    `$4A20` and the square to `$49C0`, both as offsets from `$4900`."""
    save = _savgam("A")
    payload = bytearray(0x1C00)
    changed = dos.apply_quest_flags(payload, save)
    assert changed == sum(1 for b in dos.quest_flags(save) if b)
    dos.apply_position(payload, save)
    x, y, facing = sg.position(save)
    assert payload[0x49C0 - 0x4900] == x
    assert payload[0x49C1 - 0x4900] == y
    assert payload[0x49C2 - 0x4900] == facing
    # The area is not written here: `$4BC2` is slot 2 of the loaded-files
    # cache, so it belongs to `apply_file_cache` with the other twenty-four.
    payload[0x4BC2 - 0x4900] = 0xFF
    dos.apply_position(payload, save)
    assert payload[0x4BC2 - 0x4900] == 0xFF
    dos.apply_file_cache(payload, save)
    assert payload[0x4BC2 - 0x4900] == sg.area_id(save)
    # Nothing outside the two regions was touched.
    assert payload[:0x49C0 - 0x4900] == bytes(0xC0)


# --- the YAML view -----------------------------------------------------------

@needs_dos_saves
def test_a_dos_party_exports_as_the_same_yaml_a_c64_party_does():
    """Step 2, and the reason it is worth having on its own: one shape, one
    set of field names, one renderer."""
    from goldbox.yaml_io import to_yaml

    data = dos.export_party(_save_dir(), "A")
    assert data["port"] == "dos"
    assert len(data["party"]) == 6
    text = to_yaml(data)
    back = yaml.safe_load(text)
    assert [e["name"] for e in back["party"]] == \
           [e["name"] for e in data["party"]]
    first = data["party"][0]
    assert first["_dos_encumbrance"] == first["_dos_encumbrance_expected"]
    assert first["classes"]
    assert first["levels"]


# --- the whole save ----------------------------------------------------------

@needs_dos_saves
def test_convert_save_accounts_for_the_whole_payload():
    """Every one of the 9216 bytes of **both** files has a provenance,
    including "carried through from the template save", which is why a
    template is required at all.

    `SAVEDGAME1` used to be absent from the report entirely (#120): its 194
    written bytes had no provenance line and its 1854 carried ones were not
    counted, so `3833/7168 bytes accounted for` was a statement about half
    the output.
    """
    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    report = dos.convert_save(_save_dir(), "A", save0, save1)
    assert report.total == len(save0) + len(save1)
    assert report.unaccounted == []
    assert any("quest-flag" in w for w in report.warnings)
    # The six roster blocks the conversion writes are named, and named as
    # being in the other file -- `0x0100` means two different things now.
    for place in range(6):
        at = len(save0) + place * dos.ROSTER_STRIDE
        assert "SAVEDGAME1" in report.sources[at]
        assert "roster" in report.sources[at]


@needs_dos_saves
def test_convert_save_accounts_for_save0_alone_when_there_is_no_save1():
    """`save1` is optional, and with none given the report covers exactly the
    one file it was handed."""
    save0 = bytearray(0x1C00)
    report = dos.convert_save(_save_dir(), "A", save0)
    assert report.total == len(save0)
    assert report.unaccounted == []


@needs_dos_saves
def test_a_template_from_another_area_is_retargeted_not_refused():
    """`$FF` in all twenty-five slots, then slot 2 = the `GEO`, slot 8 = the
    area id and slot 11 = `ANIMATE00`. The arriving script's entry 4 refills
    the rest, CONFIRMED twice in the running game
    (`docs/140-loaded-files-cache.md`). Slot 11 is the third because the save
    *carries* `ANIMATE00` in `SAVEDGAME1`'s tail, and a save that leaves the
    slot empty cannot complete a transition into an area (#102). The three
    bytes outside the cache go with it, `$49EA` above all -- without the disk
    hint the loader sits on `INSERT SIDE # N` hunting a file that is not on
    the side it asked for.
    """
    savgam = _savgam("A")
    there = sg.area_id(savgam)
    where = areas.area(there)
    save0 = bytearray(0x1C00)
    save0[0x4BC2 - dos.SAVE0_BASE] = (there + 1) & 0x7F
    dos.convert_save(_save_dir(), "A", save0)
    at = dos.FILE_CACHE[0] - dos.SAVE0_BASE
    cache = bytes(save0[at:at + dos.FILE_CACHE[1]])
    want = bytearray(b"\xFF" * dos.FILE_CACHE[1])
    want[dos.CACHE_GEO] = areas.geo_number(where.geos[0])
    want[dos.CACHE_ECL] = there
    want[11] = 0                 # ANIMATE00, and see below
    assert cache == bytes(want)
    assert save0[dos.DISK_HINT - dos.SAVE0_BASE] == where.disk
    assert save0[dos.CURRENT_GEO - dos.SAVE0_BASE] == want[dos.CACHE_GEO]
    assert save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE] == there
    assert save0[dos.INDOORS - dos.SAVE0_BASE] == 1


@needs_dos_saves
def test_a_template_already_in_the_area_is_retargeted_like_any_other():
    """A template standing where the DOS party stands used to keep its own
    cache, on the reasoning that the game wrote it and it names more files
    than a converted save needs. That was the one path in the conversion
    that preferred an inherited value to a computed one, and #121 removed it.

    The recipe is confirmed twice in the running game
    (`docs/140-loaded-files-cache.md`), and **one of those two tests is
    itself a same-area case** -- PORSAVE13 standing in the Slums with a
    Slums save converted onto it -- so the branch this replaces is the one
    already proven unnecessary. What it cost was 29 bytes of somebody
    else's save on #118's inherited list, for no gain.
    """
    savgam = _savgam("A")
    there = sg.area_id(savgam)
    where = areas.area(there)
    save0 = bytearray(0x1C00)
    at = dos.FILE_CACHE[0] - dos.SAVE0_BASE
    save0[at:at + dos.FILE_CACHE[1]] = bytes(range(0x20, 0x39))
    save0[at + dos.CACHE_GEO] = there | dos.FILE_CACHE_RELOAD
    dos.convert_save(_save_dir(), "A", save0)
    want = bytearray(b"\xFF" * dos.FILE_CACHE[1])
    want[dos.CACHE_GEO] = areas.geo_number(where.geos[0])
    want[dos.CACHE_ECL] = there
    want[11] = 0                 # ANIMATE00, as in the other-area case
    assert bytes(save0[at:at + dos.FILE_CACHE[1]]) == bytes(want)
    # The four bytes outside the cache are written too. They used to be
    # skipped on this branch, which is how $49EA -- the side the loader asks
    # for -- kept the template's value.
    assert save0[dos.DISK_HINT - dos.SAVE0_BASE] == where.disk
    assert save0[dos.CURRENT_GEO - dos.SAVE0_BASE] == want[dos.CACHE_GEO]
    assert save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE] == there
    assert save0[dos.INDOORS - dos.SAVE0_BASE] == 1


@needs_dos_saves
def test_an_area_whose_map_we_cannot_name_is_refused():
    """Six of the thirty areas: the four that load no map and the two whose
    script picks one at run time. Guessing there is what wrote a save that
    loads and hangs.  The travel-grid windows used to be refused here too;
    #50 lifted that once #59's outdoor saves settled their fields.
    """
    savgam = bytearray(_savgam("A"))
    save0 = bytearray(0x1C00)
    for id in (3, 8):
        sg.put_word(savgam, sg.AREA, id)
        assert sg.area_id(bytes(savgam)) == id
        with pytest.raises(dos.DosRecordError):
            dos.apply_file_cache(save0, bytes(savgam))


def _outdoor_savgam(script: int = 26) -> bytes:
    """An overland save in the measured shape of `work/p59-outdoor`'s three:
    `$49E6` = 0, `$49C5` = 0, the area id in `$49F2` alone, the square in
    `$49C3`/`$49C4`, and the stale indoor square left in 12801-12803.

    `script` picks which of the three measured windows (#59: areas 25, 26 and
    27) -- 26 by default, unchanged from before this took a parameter."""
    savgam = bytearray(_savgam("A"))
    sg.put_word(savgam, sg.INDOORS, 0)
    sg.put_word(savgam, sg.AREA, 0)
    sg.put_word(savgam, sg.SCRIPT, script)
    sg.put_travel_square(savgam, 7, 29)
    return bytes(savgam)


# script, SQRDATA number, disk hint -- `goldbox/areas.py`'s entries for 25-27.
OUTDOOR_WINDOWS = [(25, 4, 6), (26, 5, 7), (27, 6, 8)]


@needs_dos_saves
@pytest.mark.parametrize("script,sqrdata,disk", OUTDOOR_WINDOWS)
def test_an_overland_save_writes_the_outdoor_cache_recipe(script, sqrdata, disk):
    """#47's outdoor form: slot 4 = the SQRDATA number where slot 2 would
    hold the GEO, slot 2 left `$FF`, `$49E6` = 0, `$49C5` = the SQRDATA
    number, and the disk hint naming the side that carries the area's `ECL`.

    Parametrized over all three measured windows (#59: 3 of 3 specimens),
    not only 26 -- #99 named this the coverage gap between "measured" and
    "unit-tested"."""
    savgam = _outdoor_savgam(script)
    save0 = bytearray(0x1C00)
    line = dos.apply_file_cache(save0, savgam)
    assert f"SQRDATA0{sqrdata}" in line
    at = dos.FILE_CACHE[0] - dos.SAVE0_BASE
    assert save0[at + dos.CACHE_SQRDATA] == sqrdata
    assert save0[at + dos.CACHE_ECL] == script
    assert save0[at + dos.CACHE_GEO] == dos.FILE_CACHE_EMPTY
    # Slot 11 goes with them: `SAVEDGAME1`'s tail *is* `ANIMATE00`, and a save
    # that leaves the slot empty cannot walk into an area (#102). Written as
    # the literal 11 and 0 rather than through the module's own names, so a
    # constant renumbered by hand fails here instead of following the change:
    # `ANIMATE00` is the only `ANIMATE` file in the game, on all eight sides.
    assert save0[at + 11] == 0
    assert save0[dos.INDOORS - dos.SAVE0_BASE] == 0
    assert save0[dos.CURRENT_GEO - dos.SAVE0_BASE] == sqrdata
    assert save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE] == script
    assert save0[dos.DISK_HINT - dos.SAVE0_BASE] == disk


@needs_dos_saves
@pytest.mark.parametrize("script", [25, 26, 27])
def test_an_overland_save_places_the_party_on_the_travel_pair(script):
    """Outdoors the square goes to `$49C3`/`$49C4` and `$49C0`-`$49C2` is
    left the template's -- the DOS file's own 12801/12802 are the stale
    square the party left the grid on, not where it stands."""
    savgam = _outdoor_savgam(script)
    save0 = bytearray(0x1C00)
    save0[0x49C0 - 0x4900:0x49C3 - 0x4900] = b"\x11\x22\x33"
    notes = dos.apply_position(save0, savgam)
    assert save0[0x49C3 - 0x4900] == 7
    assert save0[0x49C4 - 0x4900] == 29
    assert bytes(save0[0x49C0 - 0x4900:0x49C3 - 0x4900]) == b"\x11\x22\x33"
    assert {a for a, _ in notes} == {0x49C3, 0x49C4}


@needs_dos_saves
@pytest.mark.parametrize("script", [25, 26, 27])
def test_an_outdoor_area_id_is_read_from_the_script_word(script):
    """`$49C5` is 0 on the travel grid (3 of 3 outdoor specimens), so a
    reader keying on it would take an overland party for one in New Phlan."""
    savgam = _outdoor_savgam(script)
    assert sg.area_id(savgam) == 0
    assert sg.current_area(savgam) == script
    indoor = _savgam("A")
    assert sg.current_area(indoor) == sg.area_id(indoor)


# --- #99: the two outdoor signals checked against each other ----------------

def _mismatched_savgam(indoors_word: int, area: int, script: int) -> bytes:
    """A `SAVGAM` whose own `$49E6` disagrees with what `goldbox/areas.py` says
    about its script id -- never seen on a real disk (#59 is 3 of 3
    agreeing), but reachable by a corrupt or hand-edited save now that #50 no
    longer refuses all outdoor input.  Built from nothing rather than a real
    specimen, because the whole point is a save no real disk has ever held."""
    savgam = bytearray(sg.SAVGAM_SIZE)
    sg.put_word(savgam, sg.INDOORS, indoors_word)
    sg.put_word(savgam, sg.AREA, area)
    sg.put_word(savgam, sg.SCRIPT, script)
    return bytes(savgam)


def test_an_outdoor_bit_with_an_indoor_script_id_is_refused():
    """`$49E6` = 0 (outdoors) but the script id names an indoor area."""
    savgam = _mismatched_savgam(indoors_word=0, area=0, script=1)
    assert sg.outdoors(savgam) is True
    assert areas.area(sg.current_area(savgam)).outdoors is False
    save0 = bytearray(0x1C00)
    with pytest.raises(dos.DosRecordError):
        dos.apply_file_cache(save0, savgam)


def test_an_indoor_bit_with_an_outdoor_script_id_is_refused():
    """`$49E6` != 0 (indoors) but the area id (`$49C5`, read since the save
    is not outdoors) is one of the three overland windows."""
    savgam = _mismatched_savgam(indoors_word=1, area=26, script=0)
    assert sg.outdoors(savgam) is False
    assert areas.area(sg.current_area(savgam)).outdoors is True
    save0 = bytearray(0x1C00)
    with pytest.raises(dos.DosRecordError):
        dos.apply_file_cache(save0, savgam)


@needs_dos_saves
def test_the_roster_tail_comes_from_the_dos_combat_tail():
    """DOS `0x110`-`0x11C` is the C64's roster block `0x10E`-`0x11B` at a
    displacement of -2: THAC0, armour class, the armour bonus and the eight
    running attack-form bytes, then hit points widening by one."""
    for char in _records():
        rec, _ = dos.to_c64_record(char)
        assert rec.get("thac0") == char.get("thac0_current")
        assert rec.get("armour_class") == char.get("armour_class")
        assert rec.get_raw("roster_tail") == char.raw("roster_tail")
        assert rec.get("roster_movement") == char.get("movement_current")


@needs_dos_saves
def test_the_converted_clock_is_the_dos_partys_and_not_the_templates():
    """The time of day is carried, not inherited (#103).

    Three DOS saves, three different clocks -- 10:02, 1:22 and 10:56 -- each
    converted onto a template whose own six clock bytes are a sentinel no
    real save holds.  Before the fix all three arrived reading the sentinel,
    which is what a player saw as 21:15 on a party whose save said 10:15.
    """
    sentinel = bytes([9, 9, 9, 21, 28, 11])   # 21:99 on day 28 of month 11
    seen = set()
    for slot in "JBA":
        savgam = _savgam(slot)
        save0 = bytearray(0x1C00)
        at = sg.CLOCK - dos.SAVE0_BASE
        save0[at:at + sg.CLOCK_DIGITS] = sentinel
        dos.convert_save(_save_dir(), slot, save0)
        want = bytes(sg.word(savgam, sg.CLOCK + i)
                     for i in range(sg.CLOCK_DIGITS))
        assert bytes(save0[at:at + sg.CLOCK_DIGITS]) == want, slot
        # And it reads back as the same time through the C64's own accessor,
        # so the six digits are in the order the status line prints.
        hour, minute, day, month = sg.clock(savgam)
        c64 = savegame.SaveGame0.from_bytes(bytes(save0))
        assert c64.party.clock == (hour, minute)
        seen.add((hour, minute, day, month))
    assert len(seen) == 3, "the three saves must differ or this proves nothing"


@needs_dos_saves
def test_a_clock_digit_too_large_for_its_field_is_reported():
    """A digit above what its field holds means the six words are not the
    clock, so it is a warning rather than a silent narrowing."""
    savgam = bytearray(_savgam("A"))
    sg.put_word(savgam, sg.CLOCK + 3, 300)      # the hour digit, limit 24
    save0 = bytearray(0x1C00)
    note, complaints = dos.apply_clock(save0, bytes(savgam))
    assert "the clock" in note
    assert len(complaints) == 1 and "clock digit 3" in complaints[0]
    assert save0[sg.CLOCK + 3 - dos.SAVE0_BASE] == 300 & 0xFF


@needs_dos_saves
def test_the_converted_party_marches_in_the_dos_order():
    """The C64 lists the party from the highest slot down (#101).

    `ENCAMP > ALTER > ORDER` in `work/p3/W1.D64` -- an engine-written save
    whose slots 0-5 are MALCYON, LADY KATHERINE, ROLAND, SILAS, MAGNUS,
    BRUTUS -- asks `WHO TAKES POSITION #1?` over a list headed by BRUTUS, and
    the main panel lists the same six in the same order (`work/p102/order2.log`).
    So DOS position 0 belongs in the highest slot, and writing it into slot 0
    put the DOS party's front-rank fighter at the back.
    """
    for slot in "JBA":
        party = [c.name for c in dos.read_party(_save_dir(), slot)]
        assert len(party) == 6
        save0 = bytearray(0x1C00)
        save1 = bytearray(0x0800)
        dos.convert_save(_save_dir(), slot, save0, save1)
        sg0 = savegame.SaveGame0.from_bytes(bytes(save0))
        by_slot = {s.index: s.record.name for s in sg0.slots if s.occupied}
        # Highest slot first is the C64's marching order; it must be the DOS
        # party's own order, not its reverse.
        assert [by_slot[i] for i in sorted(by_slot, reverse=True)] == party
        # And the roster block travels with the record: +0x0D is the record's
        # slot index, identity in every engine-written save read.
        stride = savegame.ROSTER_STRIDE
        for i in sorted(by_slot):
            assert save1[i * stride + 0x0D] == i, (slot, i)


@needs_dos_saves
def test_the_converted_inventory_follows_its_owner_to_the_reversed_slot():
    """The item page and the slot record must not come apart when the party is
    reversed: page `n` at `$5900` belongs to the character in slot `n`."""
    from goldbox import items

    slot = "A"
    # Keyed by name, not by index: reading the expected count back through
    # `marching_slot` would make the test agree with the code by construction.
    want = {c.name: c.get("item_count")
            for c in dos.read_party(_save_dir(), slot)}
    assert len(want) == 6 and any(want.values())
    save0 = bytearray(0x1C00)
    dos.convert_save(_save_dir(), slot, save0)
    sg0 = savegame.SaveGame0.from_bytes(bytes(save0))
    for place in [s.index for s in sg0.slots if s.occupied]:
        who = sg0.slots[place].record.name
        carried = list(items.items_for_slot(bytes(save0), place))
        assert len(carried) == want[who], (who, place)


# --- the other three titles (#53) -------------------------------------------
#
# Reading is per title and the title is the record's own length.  These tests
# are the evidence that `goldbox/dos_layout.py`'s four shapes are right: a shape
# one byte out fails several of them at once, because each check is a fact
# about the *content* of a field rather than about the table that names it.

#: The archive folder name for each shape, so a test can find that title's
#: shipped party.
_TITLE_FOLDER = {
    "pool-of-radiance": "POOLRAD",
    "curse-of-the-azure-bonds": "CURSE",
    "secret-of-the-silver-blades": "SECRET",
    "pools-of-darkness": "Pools of Darkness",
}


def _title_records(shape):
    """Every shipped record of one title, or a skip."""
    where = _game_dirs().get(_TITLE_FOLDER[shape.key])
    if where is None:
        pytest.skip(f"no DOS {shape.title} here; set FR_ARCHIVES")
    out = [dos.read_character(p) for p in sorted(where.glob("CHRDAT*.SAV"))
           if p.stat().st_size == shape.record_size]
    if not out:
        pytest.skip(f"no DOS {shape.title} records here")
    return out


def _all_titles():
    return pytest.mark.parametrize(
        "shape", dos_layout.SHAPES, ids=[s.key for s in dos_layout.SHAPES])


def test_each_shape_tiles_its_own_record():
    """Every byte of all four records belongs to exactly one entry, and the
    widths add up to the size the file actually is.  `layout_for` raises on a
    shape that does not, so this is the other half."""
    for shape in dos_layout.SHAPES:
        table = dos_layout.layout_for(shape)
        assert sum(f.size for f in table) == shape.record_size, shape.key
        assert [f.offset for f in table] == sorted(f.offset for f in table)
    # No two titles are the same length, which is what lets a record name its
    # own title with nothing else to go on.
    assert len(dos_layout.SHAPES_BY_SIZE) == len(dos_layout.SHAPES)


def test_the_pool_of_radiance_shape_is_the_table_it_was_read_from():
    """The generator must reproduce the hand-written table exactly -- offsets,
    widths, kinds and notes.  Without this the other three shapes would be
    free to drift the one that is measured against 24 specimens."""
    assert dos_layout.layout_for(dos_layout.POOL_OF_RADIANCE) \
        == dos_layout.LAYOUT


def test_a_record_of_an_unknown_length_is_refused():
    """A file that is not one of the four sizes names no title, and guessing
    is how a reader hands back rubbish that looks like a character."""
    with pytest.raises(dos.DosRecordError):
        dos.DosCharacter(bytes(300))


@_all_titles()
def test_every_record_of_every_title_rebuilds_byte_for_byte(shape):
    """Decode every field through the title's table, encode it back, compare.

    This is the round trip a read-only decoder can make, and it is not the
    trivial one: `to_bytes` hands the bytes back untouched, where this goes
    through `_decode`/`_encode` for every entry.  A field declared one byte
    wide that is really two comes back with its second byte zeroed.
    """
    records = _title_records(shape)
    for char in records:
        assert char.rebuild() == bytes(char), (shape.key, char.name)
    assert len(records) >= 6, shape.key


@_all_titles()
def test_the_encumbrance_identity_balances_in_every_title(shape):
    """`money + sum(item weight x quantity)` against the stored encumbrance.

    Self-contained arithmetic across three structures, so it confirms the
    money block, the 63-byte item stride, the weight offset and the byte
    order together -- and it is what says Pools of Darkness really does keep
    **three** coin slots where every earlier title keeps seven.
    """
    for char in _title_records(shape):
        assert char.expected_encumbrance() == char.get("encumbrance"), \
            (shape.key, char.name)


@_all_titles()
def test_the_level_array_is_indexed_by_class_number_in_every_title(shape):
    """DOS indexes its per-class levels by the class *number*, and the class
    byte says which slots may be set.  A spellbook or a memorised region one
    byte out moves this array and the check fails."""
    for char in _title_records(shape):
        number = char.get("char_class")
        assert number in dos.CLASS_SLOTS_FOR_CLASS, (shape.key, char.name,
                                                    number)
        levels = char.raw("class_levels")
        want = {n for n in dos.CLASS_SLOTS_FOR_CLASS[number]
                if n < len(levels)}
        assert {n for n, v in enumerate(levels) if v} == want, \
            (shape.key, char.name, char.get("char_class"), list(levels))
        assert char.get("level") == max(levels), (shape.key, char.name)


@_all_titles()
def test_no_title_converts_but_pool_of_radiance(shape):
    """Reading is per title; converting is not.  Handing a Curse record to
    the C64 writer would read Pool of Radiance's offsets out of a 422-byte
    record, so it raises instead."""
    char = _title_records(shape)[0]
    if shape is dos_layout.POOL_OF_RADIANCE:
        dos.to_neutral(char)
        return
    with pytest.raises(dos.WrongTitleError):
        dos.to_neutral(char)


@_all_titles()
def test_the_class_bitmask_is_what_the_level_arrays_imply(shape):
    """`class_bits` against the classes the level arrays actually name.

    The check that bites hardest on a wrong shape, because the two sit at
    opposite ends of the undecoded middle: move either and they disagree.
    54 of 54 shipped records across the four titles.
    """
    for char in _title_records(shape):
        assert char.get("class_bits") == dos.class_bits_for(char), \
            (shape.key, char.name, hex(char.get("class_bits")))


@_all_titles()
def test_the_shipped_party_reads_as_characters(shape):
    """The cheap sanity of a record that decoded: abilities in range, a
    printable name, hit points inside their maximum, five saving throws that
    are d20 rolls, a size that is small or medium, a party slot."""
    for char in _title_records(shape):
        who = (shape.key, char.name)
        assert char.name.isprintable() and char.name, who
        for stat in ("strength", "intelligence", "wisdom", "dexterity",
                     "constitution", "charisma"):
            assert all(3 <= b <= 25 for b in char.raw(stat)), (who, stat)
        assert 0 < char.get("hp_current") <= char.get("hp_max"), who
        saves = [char.get(n) for n in ("save_paralysis", "save_petrification",
                                       "save_wands", "save_breath",
                                       "save_spell")]
        assert all(1 <= v <= 20 for v in saves), (who, saves)
        assert char.get("size") in (1, 2), who
        assert 0 <= char.get("party_order") <= 7, who
        assert char.get("movement") in (6, 9, 12), who


def test_a_dual_classed_character_carries_the_class_it_was():
    """Pools of Darkness keeps a second level array for the class a
    dual-classed character left behind, indexed the same way: ABAGAIL is a
    magic-user 12 who was a cleric 11, and her class bitmask carries both."""
    shape = dos_layout.SHAPES_BY_SIZE[510]
    by_name = {c.name: c for c in _title_records(shape)}
    abagail = by_name.get("ABAGAIL")
    if abagail is None:
        pytest.skip("this Pools of Darkness party has no ABAGAIL")
    assert abagail.get("char_class") == 5                    # magic-user
    assert list(abagail.raw("class_levels"))[5] == 12
    assert list(abagail.raw("former_class_levels"))[0] == 11  # cleric
    assert abagail.get("class_bits") == 0x03                 # both


def test_the_silver_blades_rangers_hold_the_c64_grant_list_exactly():
    """The strongest single check on a shape this project did not measure
    itself: `goldbox/spells.py`'s ranger grant table was read mechanically out of
    the **C64** `GEN` file, and DOS Silver Blades' three shipped rangers hold
    its level-8 row -- 77, 78, 79, 80 -- and nothing else.

    Three of three, on a 117-byte spellbook 0x071 bytes into a 439-byte
    record neither port's table knew about the other.
    """
    shape = dos_layout.SHAPES_BY_SIZE[439]
    want = set(dict(spells._RANGER_GRANT_SILVER_BLADES)[8])
    rangers = [c for c in _title_records(shape) if c.get("char_class") == 4]
    assert len(rangers) == 3
    for char in rangers:
        assert set(char.spells_known) == want, char.name


def test_the_silver_blades_clerics_hold_the_cleric_grant_levels():
    """The level-8 clerics know cleric levels 1-4 and nothing else, which is
    `goldbox/spells.py`'s Silver Blades groups 1-8, 22-28, 37-44, {58, 66-70}."""
    shape = dos_layout.SHAPES_BY_SIZE[439]
    want = (set(range(1, 9)) | set(range(22, 29)) | set(range(37, 45))
            | {58} | set(range(66, 71)))
    clerics = [c for c in _title_records(shape) if c.get("char_class") == 0]
    assert len(clerics) == 2
    for char in clerics:
        assert set(char.spells_known) == want, char.name


# --- the template's spare characters (#104) ---------------------------------

def _plant(save0: bytearray, save1: bytearray, place: int, name: bytes) -> None:
    """Put something in a slot that `looks_occupied` agrees is a character.

    A synthetic template rather than a real save, because what is being tested
    is a rule -- no slot the converted party did not fill may still read as
    occupied -- and a synthetic one can hold **eight**, which is the case a
    six-character DOS party cannot cover and no engine-written save on this
    machine happens to be.
    """
    at = savegame.SLOT_AREA_BASE - savegame.SAVE0_LOAD_ADDRESS \
        + place * savegame.SLOT_STRIDE
    save0[at:at + len(name)] = name
    save0[at + 0x14:at + 0x1A] = bytes([12] * 6)   # six abilities, 3..25
    save1[place * savegame.ROSTER_STRIDE] = 1      # roster_in_use


@needs_dos_saves
def test_no_spare_character_survives_a_conversion():
    """A DOS save holds six characters and a C64 save eight, so a conversion
    always leaves at least two of the template's slots unwritten. They must
    not still read as characters: the party would arrive with strangers in it,
    carrying items that are not theirs and sharing the experience.

    **The whole slot goes**, not the one byte the engine's own `DROP` writes
    (#118). `ZSLOT8` wiped 555 non-zero bytes of an eight-character save this
    way and the party in it walked five squares and won a fight, so a slot
    that is nobody's carries none of the previous owner's abilities, hit
    points or items either.
    """
    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    # Names no DOS party can be carrying, so the assertion below cannot pass
    # or fail by coincidence -- the shipped party has a BRUTUS and a MAGNUS.
    for place, name in ((6, b"XYZZY"), (7, b"PLUGH")):
        _plant(save0, save1, place, name)
    planted = savegame.SaveGame0.from_bytes(bytes(save0))
    assert [s.index for s in planted.slots if s.occupied] == [6, 7], \
        "the synthetic template must start out holding those two"

    party = dos.read_party(_save_dir(), "A")
    report = dos.convert_save(_save_dir(), "A", save0, save1)
    sg0 = savegame.SaveGame0.from_bytes(bytes(save0))
    filled = {s.index for s in sg0.slots if s.occupied}
    assert filled == set(range(len(party))), sorted(filled)
    names = {s.record.name for s in sg0.slots if s.occupied}
    assert "XYZZY" not in names and "PLUGH" not in names, sorted(names)
    # The roster block says the same thing, and both have to agree or the
    # engine reads one structure as full and the other as empty.
    for place in range(len(party), 8):
        assert save1[place * savegame.ROSTER_STRIDE] == 0, place
    assert report.unaccounted == []
    # And nothing of XYZZY is left behind it: not the name, not the abilities
    # `_plant` wrote at +0x14, not the item block, not the icon.
    for place in range(len(party), dos.SLOT_TOTAL):
        for base in (savegame.SLOT_AREA_BASE, dos.ITEM_AREA):
            at = base - savegame.SAVE0_LOAD_ADDRESS + place * dos.SLOT_STRIDE
            assert bytes(save0[at:at + dos.SLOT_STRIDE]) == \
                bytes(dos.SLOT_STRIDE), f"slot {place} at ${base:04X}"
    for place in range(len(party), savegame.SLOT_COUNT):
        at = dos.ICON_TABLE - savegame.SAVE0_LOAD_ADDRESS \
            + place * dos.ICON_SIZE
        assert bytes(save0[at:at + dos.ICON_SIZE]) == bytes(dos.ICON_SIZE)
        at = place * savegame.ROSTER_STRIDE
        assert bytes(save1[at:at + savegame.ROSTER_STRIDE]) == \
            bytes(savegame.ROSTER_STRIDE)


# --- a save built from nothing (#118) ---------------------------------------
#
# The regions below are what a template used to supply. Each has a run behind
# it in the emulator, on this issue's comments; what these assert is that the
# writer puts the measured value there rather than leaving the buffer's.

def _game_files():
    """The icon and `ANIMATE00` off the player's own disks, or skip.

    Read at run time, never stored: both are the game's own data and
    `CLAUDE.md` forbids a fixture that is a slice of a game file.
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


@needs_dos_saves
def test_a_save_built_from_nothing_accounts_for_every_byte():
    """`new_save` returns a report whose `unwritten` is empty, for every slot
    the DOS folder holds.

    That is the whole of #118 stated as a test: a byte with no source is a
    byte inherited from somebody else's save, and there is no longer a save to
    inherit one from. Without the zeroing tables and the two game files this
    goes red with 5405 entries.
    """
    icon, animate = _game_files()
    slots = dos.slots_available(_save_dir())
    assert slots, "the DOS save folder has to hold at least one slot"
    for slot in slots:
        save0, save1, report = dos.new_save(_save_dir(), slot, icon, animate)
        assert report.unwritten == [], slot
        assert report.unaccounted == [], slot
        assert len(save0) + len(save1) == report.total == 9216


@needs_dos_saves
def test_the_combat_icons_of_the_party_are_the_ones_creation_writes():
    """Zero is refused here (#57): screen code 0 in `CHARPIC00` is a real
    glyph, so a zeroed 36-byte icon draws as a 3x3 block of black hooks on the
    combat floor rather than as nothing.

    So every occupied slot carries the icon the game's own character creation
    writes, and every empty one carries zero -- nothing draws an icon for a
    slot with no character in it.
    """
    icon, animate = _game_files()
    party = dos.read_party(_save_dir(), "A")
    save0, _save1, _report = dos.new_save(_save_dir(), "A", icon, animate)
    for place in range(savegame.SLOT_COUNT):
        at = dos.ICON_TABLE - dos.SAVE0_BASE + place * dos.ICON_SIZE
        got = bytes(save0[at:at + dos.ICON_SIZE])
        want = icon if place < len(party) else bytes(dos.ICON_SIZE)
        assert got == want, place
        if place < len(party):
            assert any(got), f"slot {place} would draw as black hooks"


@needs_disks
def test_the_default_icon_is_what_the_engine_seeded_the_table_with():
    """Composed from the option tables, and checked against the player's own
    save disks rather than against a number written down here.

    Slots 6 and 7 are the NPC-only slots nobody has ever edited, so they still
    hold what the table was seeded with. **28 of 28** -- every save disk, both
    slots -- and **0 of 84** in slots 0-5, which is what says the match is the
    creation default rather than a shape any character happens to carry.
    """
    from goldbox import icons
    from goldbox.d64 import D64
    from goldbox.iconparts import IconParts

    #: Slots 6 and 7 are the two a DOS party can never fill, so the engine's
    #: seeding is still in them on every save the player has ever made.
    NPC_SLOTS = (6, 7)

    want = IconParts.load(str(gamedata.game_disk("POOL3"))).default_icon()
    checked = seeded = nudged = 0
    for path in gamedata.save_disks():
        try:
            _game, sg0, _sg1 = savegame.load_save(D64.open(path))
        except Exception:
            continue                      # a roster disk with no save on it
        checked += 1
        payload = sg0.to_bytes()
        for place in range(savegame.SLOT_COUNT):
            same = icons.icon_for_slot(payload, place).raw == want
            if place in NPC_SLOTS:
                seeded += same
            else:
                nudged += same
    assert checked, "needs at least one save disk to check against"
    assert seeded == checked * len(NPC_SLOTS), \
        f"{seeded} of {checked * len(NPC_SLOTS)} NPC slots carry it"
    assert nudged == 0, "a slot the player edited matches the default"


@needs_dos_saves
def test_animate00_is_written_where_the_cache_says_it_is():
    """`$8400`-`$8753` is `ANIMATE00` as the loader leaves it, off the
    player's own disk.

    It is not scratch: the loaded-files cache slot 11 says the file is
    resident, so the engine does not reload it and calls into whatever the
    save carried (#102). The bounds are the file's own -- `$8400 + 852 - 1` is
    `$8753`, exactly where the bitmap buffer begins -- and the buffer after it
    is zero, which is what makes the split checkable rather than asserted.
    """
    icon, animate = _game_files()
    assert len(animate) == dos.ANIMATE_SIZE
    _save0, save1, _report = dos.new_save(_save_dir(), "A", icon, animate)
    at = dos.ANIMATE_AT - dos.SAVE1_BASE
    assert bytes(save1[at:at + len(animate)]) == animate
    end = at + len(animate)
    assert dos.SAVE1_BASE + end == dos.BITMAP_BUFFER[0]
    assert bytes(save1[end:]) == bytes(len(save1) - end)


@needs_dos_saves
def test_a_wrong_sized_animate_is_refused_rather_than_written():
    """852 bytes on all eight `POOL` sides. Something else is not the file,
    and writing it would put the wrong bytes under a cache entry that says
    they are the right ones.

    **The long case is the one that needs the check.** A short payload leaves
    a byte with no source and `new_save` catches it anyway; a long one runs
    past `$8753` into the bitmap buffer, and every byte of it is accounted
    for, so nothing else would notice.
    """
    icon, animate = _game_files()
    for wrong in (animate[:-1], animate + b"\x00"):
        with pytest.raises(dos.DosRecordError):
            dos.new_save(_save_dir(), "A", icon, wrong)


@needs_dos_saves
def test_the_built_disk_is_the_two_files_a_save_disk_needs():
    """Thirteen of the player's fifteen save disks hold `SAVEDGAME1` and
    `SAVEDGAME0` in that directory order and nothing else, so a disk built
    from nothing is those two files and no others."""
    from goldbox.savegame import load_save

    icon, animate = _game_files()
    save0, save1, _report = dos.new_save(_save_dir(), "A", icon, animate)
    disk = dos.save_disk(bytes(save0), bytes(save1))
    assert [bytes(e.name) for e in disk.directory()] == \
        [b"SAVEDGAME1", b"SAVEDGAME0"]
    _game, sg0, sg1 = load_save(disk)
    assert sg0.to_bytes() == bytes(save0)
    assert sg1.to_bytes() == bytes(save1)


def _outdoor_folder(tmp_path, slot: str = "A", script: int = 26):
    """A DOS save folder holding one slot, patched to stand on the travel grid.

    All three of Donald's own DOS saves are indoors, so an outdoor
    `new_save` cannot be reached from the archives as they stand -- and
    `_outdoor_savgam` alone cannot reach it either, because `convert_save`
    reads `SAVGAM<slot>.DAT` off the disk rather than taking bytes.  So the
    slot's files are copied into `tmp_path` and the copy of the `SAVGAM` is
    the one that is patched; nothing under `$FR_ARCHIVES` is written.
    """
    import shutil

    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    for path in sorted(where.glob(f"CHRDAT{slot}?.*")):
        shutil.copy(path, tmp_path / path.name)
    if not list(tmp_path.glob(f"CHRDAT{slot}?.SAV")):
        pytest.skip(f"no CHRDAT{slot}?.SAV here")
    (tmp_path / f"SAVGAM{slot}.DAT").write_bytes(_outdoor_savgam(script))
    return tmp_path


@needs_dos_saves
def test_an_outdoor_dos_save_builds_a_whole_c64_save(tmp_path):
    """An outdoor DOS party converts at all, which it did not (#118).

    `apply_position` writes `$49C0`-`$49C2` on its **indoor** branch only:
    outdoors the square is the travel pair `$49C3`/`$49C4` and those three
    bytes are nobody's.  With a template underneath that was "left alone";
    from nothing it is three bytes with no source, so `new_save` refused
    every outdoor save there is -- `3 bytes of the save have no source ...
    the first is SAVEDGAME0 $49C0`.

    Zero is what the game's own ENCAMP > SAVE writes there outdoors
    (`work/p3/W4.D64`-`W7.D64`), which is what `DUNGEON_SQUARE` records.
    """
    icon, animate = _game_files()
    folder = _outdoor_folder(tmp_path)
    save0, save1, report = dos.new_save(folder, "A", icon, animate)
    assert report.unwritten == []
    assert report.unaccounted == []
    assert len(save0) + len(save1) == report.total == 9216
    at = dos.DUNGEON_SQUARE[0] - dos.SAVE0_BASE
    assert bytes(save0[at:at + dos.DUNGEON_SQUARE[1]]) == bytes(3)
    # The travel pair is the square the party is actually standing on, and it
    # is the one thing that would be lost by zeroing the whole run at once.
    assert [save0[sg.TRAVEL_X - dos.SAVE0_BASE],
            save0[sg.TRAVEL_Y - dos.SAVE0_BASE]] == [7, 29]
    assert save0[dos.INDOORS - dos.SAVE0_BASE] == 0


@needs_dos_saves
def test_an_indoor_dos_save_still_carries_its_own_dungeon_square():
    """The other half of the zero, and what stops it being written always.

    Indoors `apply_position` writes all three over the zero, so a conversion
    that zeroed `$49C0`-`$49C2` unconditionally would put every imported
    indoor party on square 0,0 facing north.  Checked against the DOS save's
    own bytes rather than against a square written down here.
    """
    icon, animate = _game_files()
    slot = dos.slots_available(_save_dir())[0]
    save0, _save1, _report = dos.new_save(_save_dir(), slot, icon, animate)
    at = dos.DUNGEON_SQUARE[0] - dos.SAVE0_BASE
    want = sg.position(_savgam(slot))
    assert not sg.outdoors(_savgam(slot)), \
        "this test needs an indoor slot; all three archives saves are indoors"
    assert tuple(save0[at:at + 3]) == want
