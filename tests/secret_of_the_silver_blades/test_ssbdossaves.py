"""A C64 Silver Blades party converted to DOS gets the saving throws DOS
Silver Blades itself rebuilds the first time it loads the party.

DOS Silver Blades' own save rebuild is `GAME.OVR:0x3C644` (overlay entry
`164:34`), reached from the character loader on every path. It is Curse's
`0x3B45B` with two differences, both read off the routine:

* **No race test.** Column 0 takes the 4-6 +1 ... 18 +5 constitution step
  only for a readied constitution-booster item; a dwarf gets nothing for
  being a dwarf. Curse also gives it to its dwarf and halfling.
* **A trailing thief comparison.** After the class loop the loop variable is
  left on its last slot, and one more comparison reads that slot: when the
  current level there beats the former level, the column is lowered to the
  table cell at the *former* level. Curse's last slot is the monk, which no
  character holds; Silver Blades has no monk, so its last slot is the thief,
  and a thief who never left the class reads "thief level 0" -- which, the
  table being 18 levels to a class starting at level 0, is magic-user level
  18's row, `10 7 5 9 6`. That is why MALACHITE, a fighter 7 / thief 8, is
  stored with a magic-user's saves.

Everything below that reads a DOS or C64 record reads the player's own
specimens at run time and skips cleanly on a machine that has none. No game
bytes are committed.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import c64_codec, dos_codec, items, levels
from goldbox.d64 import D64
from goldbox.dos_codec import _ability_pair
from goldbox.savegame import load_save

SSB = "secret-of-the-silver-blades"
_SAVES = ("save_paralysis", "save_petrification", "save_wands", "save_breath",
          "save_spell")

# --- the rule itself, no game data needed -----------------------------------


@pytest.mark.parametrize("class_levels, former, race, constitution, "
                         "bonus_item, want", [
    # MALACHITE: the fighter 7 row, lowered by the thief-level-0 cell.
    ({"fighter": 7, "thief": 8}, {}, 3, 17, False, (10, 7, 5, 9, 6)),
    # A thief alone reads the same cell.
    ({"thief": 1}, {}, 6, 10, False, (10, 7, 5, 9, 6)),
    # No thief level, no trailing comparison: the plain fighter 7 row.
    ({"fighter": 7}, {}, 6, 16, False, (10, 11, 12, 12, 13)),
    # A dwarf (race 3 in this title) takes no constitution step at all.
    ({"fighter": 7}, {}, 3, 17, False, (10, 11, 12, 12, 13)),
    # Neither does an elf (1) or a halfling (5), whom DOS Curse's race
    # numbers would have given one.
    ({"fighter": 7}, {}, 1, 16, False, (10, 11, 12, 12, 13)),
    ({"fighter": 7}, {}, 5, 16, False, (10, 11, 12, 12, 13)),
    # A readied constitution booster does: +4 at 16.
    ({"fighter": 7}, {}, 6, 16, True, (14, 11, 12, 12, 13)),
    # The high step every race takes: +1 at 19.
    ({"fighter": 7}, {}, 6, 19, False, (11, 11, 12, 12, 13)),
    # A thief who left the class and came back: current thief 0 is not above
    # former thief 9, so the trailing comparison never fires.
    ({"fighter": 7}, {"thief": 9}, 6, 10, False, (10, 11, 12, 12, 13)),
    # The table's own paladin 5 cell, `9 9 11 11 12`, not the C64's.
    ({"paladin": 5}, {}, 6, 10, False, (9, 9, 11, 11, 12)),
])
def test_the_silver_blades_rule_matches_the_read_routine(
        class_levels, former, race, constitution, bonus_item, want):
    assert levels.dos_engine_saving_throws(
        class_levels, race, constitution, bonus_item, SSB,
        former_levels=former) == want


@pytest.mark.parametrize("game, race, constitution, bonus_item, step", [
    # The racial step's last test is `cmp al, 0x12 / jne` in both routines
    # (Curse `0x3B6BE`, Silver Blades `0x3C885`): exactly 18 takes +5, and
    # 19 takes only the high step's +1.
    ("curse-of-the-azure-bonds", 1, 18, False, 5),
    ("curse-of-the-azure-bonds", 1, 19, False, 1),
    ("curse-of-the-azure-bonds", 5, 25, False, 4),
    (SSB, 6, 18, True, 5),
    (SSB, 6, 19, True, 1),
    # The high step's last test is `cmp al, 0x19 / jne`: nothing above 25.
    (SSB, 6, 26, True, 0),
])
def test_the_constitution_steps_are_the_routines_equality_tests(
        game, race, constitution, bonus_item, step):
    fighter_7 = levels.at_level("fighter", 7, game).saves[0]
    got = levels.dos_engine_saving_throws(
        {"fighter": 7}, race, constitution, bonus_item, game)
    assert got[0] == fighter_7 + step


def test_curse_keeps_its_race_step_and_has_no_trailing_thief():
    """The two differences are Silver Blades' alone: a Curse dwarf (race 1)
    still takes the step, and a Curse thief reads his own row."""
    curse = "curse-of-the-azure-bonds"
    assert levels.dos_engine_saving_throws(
        {"fighter": 7}, 1, 16, False, curse) == (14, 11, 12, 12, 13)
    thief = levels.at_level("thief", 8, curse).saves
    assert levels.dos_engine_saving_throws(
        {"thief": 8}, 7, 10, False, curse) == tuple(thief)


# --- the specimen sweep ------------------------------------------------------
#: Our own writer's output, not DOS Silver Blades' rebuild -- excluded. Every
#: other Silver Blades directory is a slot the engine itself saved over.
_OUR_OWN_OUTPUT = {
    "por-dos/WISH-SPEC-ssb-299-built-from-nothing",
    "por-dos/WISH-SPEC-ssb-299-converted-and-resaved",
}


def _specimen_root() -> pathlib.Path | None:
    from tools.registry import specimens
    root = specimens.tree_root()
    return root if root.is_dir() else None


def _ssb_dos_records():
    """Every engine-written DOS Silver Blades record under `$WISH_SPECIMENS`,
    or an empty list when the tree is not on this machine."""
    root = _specimen_root()
    if root is None:
        return []
    out = []
    for path in sorted(root.glob("*/*/CHRDAT*.SAV")):
        specimen_dir = f"{path.parent.parent.name}/{path.parent.name}"
        if specimen_dir in _OUR_OWN_OUTPUT:
            continue
        try:
            char = dos_codec.read_character(path)
        except Exception:
            continue
        if getattr(char.deltas, "key", None) != SSB:
            continue
        out.append((specimen_dir, path.name, char))
    return out


def _former_levels(char) -> dict[str, int]:
    """Class name -> level for the record's `former_class_levels` array, in
    the slot order `class_levels` uses."""
    raw = char.raw("former_class_levels")
    return {name: raw[n] for n, name, _ in dos_codec.CLASS_LEVEL_SLOTS
            if n < len(raw) and raw[n]}


def test_the_rule_reproduces_every_engine_written_dos_silver_blades_record():
    """Written by the engine itself, 45 or more, none of them ours: 56
    records of six characters where this was measured, every one agreeing,
    including all nine of MALACHITE's, which only the trailing thief
    comparison explains."""
    records = _ssb_dos_records()
    if not records:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    checked = 0
    mismatched = []
    for specimen_dir, name, char in records:
        want = tuple(char.get(n) for n in _SAVES)
        constitution = _ability_pair(char, "constitution")[0]
        got = levels.dos_engine_saving_throws(
            char.class_levels, char.get("race"), constitution, False, SSB,
            former_levels=_former_levels(char))
        checked += 1
        if got != want:
            mismatched.append((specimen_dir, name, char.class_levels, want, got))
    assert checked >= 45, checked
    assert mismatched == []


# --- the table, re-read off the player's own START.EXE -----------------------

#: `GAME.OVR:0x3C644`'s class-slot order; Silver Blades has no monk.
_DOS_CLASS_ORDER = ("cleric", "druid", "fighter", "paladin", "ranger",
                    "magic-user", "thief")


def test_the_dos_save_table_is_the_c64s_own_except_the_overrides():
    """The 7x90 bytes at `DS:0x5592`, indexed `slot * 90 + level * 5`, are
    the C64's own rows for every class and level both have -- except the
    cells `goldbox.levels.SECRET_OF_THE_SILVER_BLADES.dos_save_overrides`
    names: Curse's three paladin cells, and the thief's level-0 cell the
    trailing comparison reads."""
    dosspellslots = pytest.importorskip("tools.dos.dosspellslots")
    from tools.dos import dosbox

    try:
        game = dosbox.find_game("SECRET")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the player's DOS Silver Blades archives: {exc}")
    image = dosspellslots.image_of(game, None)
    base = dosspellslots.data_segment(image) * 16 + 0x5592
    overrides = dict(levels.SECRET_OF_THE_SILVER_BLADES.dos_save_overrides)
    checked = 0
    for slot, name in enumerate(_DOS_CLASS_ORDER):
        for level in range(0, 19):
            at = base + slot * 90 + level * 5
            entry = tuple(image[at:at + 5])
            if (name, level) in overrides:
                assert entry == overrides[name, level], (name, level)
                continue
            row = levels.at_level(name, level, SSB) if level else None
            if row is None:
                continue
            checked += 1
            assert entry == tuple(row.saves), (name, level)
    assert checked >= 60, checked
    assert ("thief", 0) in overrides


# --- the conversion, against DOS Silver Blades' own resave -------------------

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


def _c64_party():
    """The six characters of `por-c64/WISH-SPEC-ssb-52-dialog-converted-
    resave.D64`, the C64 engine's own save, read into neutral records."""
    disk = _checked_specimen(
        "por-c64/WISH-SPEC-ssb-52-dialog-converted-resave.D64")
    game, sg0, sg1 = load_save(D64.open(str(disk)))
    out = []
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        out.append(c64_codec.read(slot.record, roster=block, inventory=inv,
                                  game=game, source=disk.name))
    return out


def _engine_resave_slot_a():
    """`name -> DosCharacter` for slot A of `ssb-dos/WISH-SPEC-c64todos-ssb-
    resave`: DOS Silver Blades' own `ENCAMP > SAVE` after loading Wish's
    conversion of the same C64 save."""
    root = _specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    specimen_dir = root / "ssb-dos/WISH-SPEC-c64todos-ssb-resave"
    if not specimen_dir.is_dir():
        pytest.skip("needs specimen ssb-dos/WISH-SPEC-c64todos-ssb-resave")
    out = {}
    for n in range(1, 7):
        char = dos_codec.read_character(specimen_dir / f"CHRDATA{n}.SAV")
        out[char.name.strip().upper()] = char
    return out


def test_a_c64_party_converts_to_dos_silver_blades_own_resave():
    """Compared against the engine's own resave rather than typed-in numbers.
    A straight copy of the C64's saves differs on five of the six;
    MALACHITE's would be `6 11 7 12 8` where the engine keeps
    `10 7 5 9 6`."""
    party = _c64_party()
    resave = _engine_resave_slot_a()
    checked = 0
    for neutral in party:
        rec, _itm, _spc, _rep = dos_codec.write(
            neutral, deltas=dos_codec.SECRET_OF_THE_SILVER_BLADES)
        char = dos_codec.DosCharacter(
            rec, deltas=dos_codec.SECRET_OF_THE_SILVER_BLADES)
        want = resave.get(char.name.strip().upper())
        if want is None:
            continue
        checked += 1
        got = tuple(char.get(n) for n in _SAVES)
        assert got == tuple(want.get(n) for n in _SAVES), char.name
    assert checked == 6
