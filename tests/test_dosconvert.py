"""Turning a DOS Pool of Radiance save into a C64 one, checked field by field.

`tests/test_dossave.py` measures the DOS file; this module checks what
`por/dos.py` does with it.  The two halves of the promise in
`docs/117-save-conversion.md` are what most of these tests are:

* **losslessness** -- a DOS record read and handed back byte for byte, which
  is how a read-only decoder proves it understood the file;
* **nothing dropped silently** -- every field declared in `por/dos_layout.py`
  has a disposition, and every byte of the 580-byte C64 record has a
  provenance.

**The saves are Donald's, not the repository's.**  They live in his unpacked
Steam copy of *Forgotten Realms: The Archives*; set `$FR_ARCHIVES` to point
somewhere else.  With no archives the file-reading tests skip, which is what
CI does -- the table tests above them do not need a save at all.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml
from test_dossave import _save_dir, needs_dos_saves

from por import areas, dos, dos_layout, spells
from por import dos_savegame as sg
from por.layout import RECORD_SIZE as C64_RECORD_SIZE

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
    cleric-3 / mage-3 runs are `por/spells.py`'s group boundaries exactly."""
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

    Every byte set in the DOS spellbook falls in a `por/spells.py` group whose
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
    the start, and `por/spells.py` says ids 1-8 are cleric level 1."""
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
    from por.items import ITEM_SIZE as C64_ITEM_SIZE

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
def test_innate_effects_survive_and_running_ones_are_reported():
    """The `.SPC` file splits in two, and the two ports share the id space.

    Curse's own importer keeps exactly the innate racial ids out of a Pool of
    Radiance `.spc`; `por/traits.py` names the same numbers the same way --
    107 is elf sleep resistance and 124 is the half-elf's on both sides.
    Everything else is a running spell and is dropped, out loud.
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
                assert any(str(e) in d for d in report.dropped)
    assert innate >= 5
    assert running >= 2


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
    from por.yaml_io import to_yaml

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
    """Every one of `SAVEDGAME0`'s 7168 bytes has a provenance, including
    "carried through from the template save", which is why a template is
    required at all."""
    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    report = dos.convert_save(_save_dir(), "A", save0, save1)
    assert report.total == 0x1C00
    assert report.unaccounted == []
    assert any("quest-flag" in w for w in report.warnings)


@needs_dos_saves
def test_a_template_from_another_area_is_retargeted_not_refused():
    """`$FF` in all twenty-five slots, then slot 2 = the `GEO` and slot 8 =
    the area id. That is the whole cache a save needs: the arriving script's
    entry 4 refills the rest, CONFIRMED twice in the running game
    (`docs/140-loaded-files-cache.md`). The three bytes outside the cache go
    with it, `$49EA` above all -- without the disk hint the loader sits on
    `INSERT SIDE # N` hunting a file that is not on the side it asked for.
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
    assert cache == bytes(want)
    assert save0[dos.DISK_HINT - dos.SAVE0_BASE] == where.disk
    assert save0[dos.CURRENT_GEO - dos.SAVE0_BASE] == want[dos.CACHE_GEO]
    assert save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE] == there
    assert save0[dos.INDOORS - dos.SAVE0_BASE] == 1


@needs_dos_saves
def test_a_template_already_in_the_area_keeps_its_own_cache():
    """A template standing where the DOS party stands carries a real cache the
    game itself wrote, naming every file it had resident. That is strictly
    more than the two slots a converted save needs, so it is kept."""
    savgam = _savgam("A")
    there = sg.area_id(savgam)
    save0 = bytearray(0x1C00)
    at = dos.FILE_CACHE[0] - dos.SAVE0_BASE
    save0[at:at + dos.FILE_CACHE[1]] = bytes(range(0x20, 0x39))
    save0[at + dos.CACHE_GEO] = there | dos.FILE_CACHE_RELOAD
    before = bytes(save0[at:at + dos.FILE_CACHE[1]])
    dos.convert_save(_save_dir(), "A", save0)
    assert bytes(save0[at:at + dos.FILE_CACHE[1]]) == before


@needs_dos_saves
def test_an_area_whose_map_we_cannot_name_is_refused():
    """Nine of the thirty areas: the four that load no map, the two whose
    script picks one at run time, and the three travel-grid windows, where the
    cache names a `SQRDATA` in slot 4 instead of a `GEO` in slot 2 and nothing
    has tested it. Guessing there is what wrote a save that loads and hangs.
    """
    savgam = bytearray(_savgam("A"))
    save0 = bytearray(0x1C00)
    for id in (3, 8, 25):
        sg.put_word(savgam, sg.AREA, id)
        assert sg.area_id(bytes(savgam)) == id
        with pytest.raises(dos.DosRecordError):
            dos.apply_file_cache(save0, bytes(savgam))


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
