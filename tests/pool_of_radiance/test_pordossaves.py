"""A C64 Pool of Radiance party converted to DOS gets the saving throws DOS
Pool of Radiance itself rebuilds the first time it loads the party.

DOS Pool of Radiance's save rebuild is `GAME.OVR:0x2ACDC` (overlay entry
`AC:2F`). `AC:25` (`0x2AA87`) calls it unconditionally, and the party loader
reaches `AC:25` through `7C:52` (`0x1F42C`) for every character file it
reads (`0x1F9BD` reads, `0x1F9C9` appends). The routine is simpler than
Curse's or Silver Blades':

* each column starts at 20 and is lowered to `DS:0x426E + slot * 45 +
  level * 5` for every class slot whose level byte at `0x096` is above zero;
* **there is no constitution step at all**, for any race. A C64 dwarf's
  saves carry his constitution bonus inside the five bytes; DOS keeps the
  plain row and the bonus in `.SPC` effects 90 and 97 instead;
* the table is the C64's rows except fighter 4, which holds the fighter 3
  row -- breath 16 where the C64 has 15 -- and the cleric and magic-user
  cells at levels 7 and 8, which the C64's rows do not reach.

Everything below that reads a DOS or C64 record reads the player's own
specimens at run time and skips cleanly on a machine that has none. No game
bytes are committed.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import c64_codec, dos_codec, items, levels
from goldbox.d64 import D64
from goldbox.savegame import load_save

POR = "pool-of-radiance"
_SAVES = ("save_paralysis", "save_petrification", "save_wands", "save_breath",
          "save_spell")

# --- the rule itself, no game data needed -----------------------------------


@pytest.mark.parametrize("class_levels, race, constitution, want", [
    # Fighter 4 is the fighter 3 row in the DOS table: breath 16, not 15.
    ({"fighter": 4}, 7, 10, (13, 14, 15, 16, 16)),
    # A dwarf (race 1) with constitution 13 takes nothing for either: the
    # plain fighter 1 row, where the C64 stores it three lower.
    ({"fighter": 1}, 1, 13, (14, 15, 16, 17, 17)),
    # Nor does constitution 19, which Curse's high step would count.
    ({"fighter": 1}, 7, 19, (14, 15, 16, 17, 17)),
    # A multi-class character takes the column-wise best.
    ({"fighter": 1, "thief": 1}, 1, 16, (13, 12, 14, 16, 15)),
    # Magic-user 7, past the C64's own rows, reads the DOS table's cell.
    ({"magic-user": 7}, 7, 10, (13, 11, 9, 13, 10)),
    # Thief 9 is the one level past 8 a Pool of Radiance class reaches; its
    # cell is the monk's level-0 slot, which holds the C64's thief 9 row.
    ({"thief": 9}, 7, 10, (11, 10, 10, 14, 11)),
])
def test_the_pool_of_radiance_rule_matches_the_read_routine(
        class_levels, race, constitution, want):
    assert levels.dos_engine_saving_throws(
        class_levels, race, constitution, False, POR) == want


def test_a_constitution_booster_adds_nothing_in_pool_of_radiance():
    """`0x2ACDC` scans no items, so the booster flag Curse reads changes
    nothing here."""
    assert levels.dos_engine_saving_throws(
        {"fighter": 1}, 7, 16, True, POR) == (14, 15, 16, 17, 17)


# --- the specimen sweep ------------------------------------------------------
#: Our own writer's output, not DOS Pool of Radiance's rebuild -- excluded.
#: Each specimen's `provenance.toml` says which files are ours: all six
#: `CHRDATA` records of the first, and slot C of the second, whose slot D
#: is the engine's resave and stays in.
_OUR_OWN_OUTPUT = {
    ("por-dos/WISH-SPEC-por-276-hall-converted-resave", "A"),
    ("por-dos/WISH-SPEC-por-gnome-converted", "C"),
}

#: The one engine-written record the rule does not reproduce: MAD MAN, a
#: fighter 8 companion from `npc_party.d64`, who holds the fighter 1-2 row
#: his C64 record was authored with. `AC:25` would also have set his
#: `0x0A1` to 3 (fighter above 6) and he holds 2, so the rebuild never ran on
#: the record that was saved -- which the loader read does not explain. The
#: same run left GENHEERIS's magic-user spell slots at the C64's 4/2/2 where
#: `AC:25` writes the table's 0/0/0 for level 7 (#634).
_UNEXPLAINED = {
    ("por-dos/WISH-SPEC-issue641-dirten-seven-resave", "CHRDATB4.SAV"),
}


def _specimen_root() -> pathlib.Path | None:
    from tools.registry import specimens
    root = specimens.tree_root()
    return root if root.is_dir() else None


def _por_dos_records():
    """Every engine-written DOS Pool of Radiance record under
    `$WISH_SPECIMENS` -- saved-game slots and the `.CHA` files the game's own
    character creation wrote -- or an empty list when the tree is not on this
    machine."""
    root = _specimen_root()
    if root is None:
        return []
    out = []
    for path in sorted(root.glob("*/*/CHRDAT*.SAV")) + sorted(
            root.glob("*/*/*.CHA")):
        specimen_dir = f"{path.parent.parent.name}/{path.parent.name}"
        if (specimen_dir, path.stem[6:7]) in _OUR_OWN_OUTPUT:
            continue
        try:
            char = dos_codec.read_character(path)
        except Exception:
            continue
        if getattr(char.deltas, "key", None) != POR:
            continue
        out.append((specimen_dir, path.name, char))
    return out


def test_the_rule_reproduces_every_engine_written_dos_pool_record():
    """Written by the engine itself, 150 or more, none of them ours: 190
    records where this was measured, 189 agreeing and MAD MAN the one named
    exception. Among the 189 are five fighter-4 records holding breath 16
    (WISHFTR, WISHDWF twice, SKULLCRUSHER, PRINCESS FATIMA), which only the
    DOS table's own fighter 4 cell explains, and the dwarf and halfling
    records, which only the missing constitution step does."""
    records = _por_dos_records()
    if not records:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    checked = 0
    mismatched = set()
    for specimen_dir, name, char in records:
        want = tuple(char.get(n) for n in _SAVES)
        got = levels.dos_engine_saving_throws(
            char.class_levels, char.get("race"), char.get("constitution"),
            False, POR)
        checked += 1
        if got != want:
            mismatched.add((specimen_dir, name))
    assert checked >= 150, checked
    assert mismatched == _UNEXPLAINED


# --- the table, re-read off the player's own START.EXE -----------------------

def test_the_dos_save_table_is_the_c64s_own_except_the_overrides():
    """The 8x45 bytes at `DS:0x426E`, indexed `slot * 45 + level * 5` in
    class-number order, are the C64's own rows for every Pool of Radiance
    class at levels 1-8 -- except the cells `goldbox.levels.POOL_OF_RADIANCE.
    dos_save_overrides` names, which are the DOS table's own. A thief 9
    indexes one cell past his slot, into the monk's level-0 cell, which holds
    the C64's thief 9 row."""
    dosspellslots = pytest.importorskip("tools.dos.dosspellslots")
    from tools.dos import dosbox

    try:
        game = dosbox.find_game("POOLRAD")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the player's DOS Pool of Radiance archives: {exc}")
    image = dosspellslots.image_of(game, None)
    base = dosspellslots.data_segment(image) * 16 + 0x426E
    slot_of = {name: n for n, name, _ in dos_codec.CLASS_LEVEL_SLOTS}
    overrides = dict(levels.POOL_OF_RADIANCE.dos_save_overrides)
    checked = 0
    for name in ("cleric", "fighter", "magic-user", "thief"):
        for level in range(1, 10 if name == "thief" else 9):
            at = base + slot_of[name] * 45 + level * 5
            entry = tuple(image[at:at + 5])
            if (name, level) in overrides:
                assert entry == overrides[name, level], (name, level)
                assert levels.at_level(name, level, POR) is None \
                    or tuple(levels.at_level(name, level, POR).saves) != entry
                continue
            row = levels.at_level(name, level, POR)
            assert row is not None, (name, level)
            checked += 1
            assert entry == tuple(row.saves), (name, level)
    assert checked == 28, checked


# --- the conversion, against DOS Pool of Radiance's own records --------------

def _checked_specimen(rel: str) -> pathlib.Path:
    """One specimen file, checked against its own recorded hash."""
    from tools.registry import specimens

    root = _specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    path = root / rel
    if not path.is_file():
        pytest.skip(f"needs specimen {rel}")
    prov = path.with_suffix(".provenance.toml")
    if prov.is_file():
        recorded = specimens.read_provenance(prov).get("sha256", {})
        actual = specimens.sha256_file(path)
        if recorded.get(path.name) not in (None, actual):
            pytest.fail(f"{rel} has changed since it was recorded; "
                        f"run tools/registry/specimens.py check")
    return path


def _c64_character(rel: str, name: str):
    disk = _checked_specimen(rel)
    game, sg0, sg1 = load_save(D64.open(str(disk)))
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        char = c64_codec.read(slot.record, roster=block, inventory=inv,
                              game=game, source=disk.name)
        if str(char.get("name")).strip().upper() == name:
            return char
    pytest.fail(f"no {name} in {rel}")


def _engine_record(rel: str):
    root = _specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    path = root / rel
    if not path.is_file():
        pytest.skip(f"needs specimen {rel}")
    return dos_codec.read_character(path)


def test_a_c64_dwarf_converts_to_the_saves_dos_pool_stores_for_a_dwarf():
    """MAGNUS, a dwarf fighter 1 with constitution 13, stores
    `11 12 13 14 14` on the C64 -- the fighter 1 row less his constitution
    bonus of 3. The DOS engine stores the plain row for a dwarf fighter 1:
    MAGNUS himself in the engine's resave of an Amiga-sourced conversion
    (`por-amiga-slums-dos-resave`, slot D) and THRENDER GRONE, a dwarf the
    DOS game made (`por-item-granted`). No C64-to-DOS resave on this machine
    has the engine rebuild a C64 dwarf, so these two engine records stand in
    for it; `docs/117-save-conversion.md` records the same five numbers from
    the run that did. Before the fix the writer copied the C64's bytes."""
    magnus = _c64_character("por-c64/WISH-SPEC-por-hall-2npc-recruit.D64",
                            "MAGNUS")
    rec, _itm, _spc, _rep = dos_codec.write(magnus)
    got = tuple(dos_codec.DosCharacter(rec).get(n) for n in _SAVES)
    for rel in ("por-dos/WISH-SPEC-por-amiga-slums-dos-resave/CHRDATD5.SAV",
                "por-dos/WISH-SPEC-por-item-granted/CHRDATD1.SAV"):
        engine = _engine_record(rel)
        assert engine.get("race") == 1 and engine.class_levels == {
            "fighter": 1}, rel
        assert got == tuple(engine.get(n) for n in _SAVES), rel
