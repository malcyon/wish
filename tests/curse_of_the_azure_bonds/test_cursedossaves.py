"""A C64 Curse party converted to DOS gets saving throws and THAC0 that DOS
Curse itself replaces the first time it loads the party (#632).

DOS Curse's own character loader rebuilds a character's five saving throws
and unarmed `thac0_current` before the party ever appears on screen --
`GAME.OVR:0x1D9D1`, which calls the save routine at `0x3B45B` and the combat
rebuild at `0x382C5`. Wish's writer used to copy the C64's own numbers
straight across, so a converted party's saved file and Character Editor
disagreed with what the game itself computes, until the player's first
`ENCAMP > SAVE`. `goldbox.levels.LevelTables.dos_engine_saving_throws` and
`goldbox.derive.dos_strength_hit_bonus` reproduce that rebuild.

Everything below that reads a DOS or C64 record reads the player's own
specimens at run time and skips cleanly on a machine that has none. No game
bytes are committed.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import c64_codec, derive, dos_codec, items, levels
from goldbox.d64 import D64
from goldbox.dos_codec import _ability_pair
from goldbox.savegame import load_save

CURSE = "curse-of-the-azure-bonds"

# --- the rule itself, no game data needed -----------------------------------


@pytest.mark.parametrize("class_levels, race, constitution, bonus_item, want", [
    ({"fighter": 7}, 7, 17, False, (10, 11, 12, 12, 13)),
    ({"cleric": 6}, 0, 0, False, (9, 12, 13, 15, 14)),
    ({"fighter": 5, "thief": 6}, 1, 16, False, (15, 11, 12, 13, 13)),
    ({"paladin": 5}, 0, 0, False, (9, 9, 11, 11, 12)),
    # A gnome (race 3) takes neither constitution step DOS Curse's dwarf and
    # halfling get, so the fighter row is unadjusted.
    ({"fighter": 7}, 3, 16, False, (10, 11, 12, 12, 13)),
    # A human (race 7) at constitution 19 takes only the high-constitution
    # step every race gets, +1 on column 0.
    ({"fighter": 7}, 7, 19, False, (11, 11, 12, 12, 13)),
    # A bonus item makes a human take the racial step too: +4 at constitution
    # 16, and no high step since 16 is under 19.
    ({"fighter": 7}, 7, 16, True, (14, 11, 12, 12, 13)),
])
def test_dos_engine_saving_throws_matches_the_read_rule(
        class_levels, race, constitution, bonus_item, want):
    assert levels.dos_engine_saving_throws(
        class_levels, race, constitution, bonus_item, CURSE) == want


def test_dos_engine_saving_throws_answers_none_for_an_unread_title():
    """Pool of Radiance's `dos_save_rule_read` is False -- nobody has read
    its DOS load-time rebuild, so the method says "cannot answer" rather than
    guessing the C64's rows apply unchanged."""
    assert levels.dos_engine_saving_throws(
        {"fighter": 5}, 0, 0, False, "pool-of-radiance") is None


def test_dos_engine_saving_throws_answers_none_with_no_class():
    assert levels.dos_engine_saving_throws({}, 7, 16, False, CURSE) is None


def test_dos_strength_hit_bonus_agrees_with_strength_bonuses_8_to_18():
    for strength in range(8, 19):
        for pct in (0, 25, 50, 60, 75, 80, 90, 95, 99, 100):
            want, _damage = derive.strength_bonuses(strength, pct)
            assert derive.dos_strength_hit_bonus(strength, pct) == want


# --- the specimen sweep ------------------------------------------------------
#: Our own writer's output, not DOS Curse's own rebuild -- excluded from the
#: sweep below.  Slot A of the last one is Wish's conversion of
#: `coab-c64/WISH-SPEC-curse-409-regained-paladin`; slot B is the engine's own
#: resave and stays in the sweep.
_OUR_OWN_OUTPUT = {
    "coab-dos/WISH-SPEC-curse-551-party-as-converted",
    "por-dos/WISH-SPEC-curse-299-built-from-nothing",
    "por-dos/WISH-SPEC-curse-234-converted-party",
}
_OUR_OWN_SLOT = ("coab-dos/WISH-SPEC-curse-632-wish-converted-resave", "A")


def _curse_dos_records():
    """Every DOS Curse character record under `$WISH_SPECIMENS`, or an empty
    list when the tree is not on this machine."""
    from tools.registry import specimens

    root = specimens.tree_root()
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*/*/CHRDAT*.SAV")):
        specimen_dir = f"{path.parent.parent.name}/{path.parent.name}"
        if specimen_dir in _OUR_OWN_OUTPUT:
            continue
        dirname, slot_letter = _OUR_OWN_SLOT
        if specimen_dir == dirname and len(path.stem) > 6 \
                and path.stem[6] == slot_letter:
            continue
        try:
            char = dos_codec.read_character(path)
        except Exception:
            continue
        if getattr(char.deltas, "key", None) != CURSE:
            continue
        out.append((specimen_dir, path.name, char))
    return out


def test_the_rule_reproduces_every_engine_written_dos_curse_record():
    """Written by the engine itself, sixty or more, none of them ours.

    `#632`'s re-check comment measured 98 records on this machine, 9
    mismatches, and all 9 in files this project's own writer produced --
    `_OUR_OWN_OUTPUT` and the one slot in `_OUR_OWN_SLOT`. 89 engine-written
    records remain and every one of them agrees.
    """
    records = _curse_dos_records()
    if not records:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    checked = 0
    mismatched = []
    for specimen_dir, name, char in records:
        want = tuple(char.get(n) for n in
                     ("save_paralysis", "save_petrification", "save_wands",
                      "save_breath", "save_spell"))
        constitution = _ability_pair(char, "constitution")[0]
        got = levels.dos_engine_saving_throws(
            char.class_levels, char.get("race"), constitution, False, CURSE)
        checked += 1
        if got != want:
            mismatched.append((specimen_dir, name, char.class_levels, want, got))
    assert checked >= 60, checked
    assert mismatched == []


# --- the table, re-read off the player's own START.EXE -----------------------

def _curse_image():
    dosspellslots = pytest.importorskip("tools.dos.dosspellslots")
    from tools.dos import dosbox

    try:
        game = dosbox.find_game("CURSE")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the player's DOS Curse archives: {exc}")
    return dosspellslots, dosspellslots.image_of(game, None)


#: `GAME.OVR:0x3B45B`'s class-slot order, the same as the DOS THAC0 tables'
#: (`goldbox.levels._DOS_THAC0_CURSE`).
_DOS_CLASS_ORDER = ("cleric", "druid", "fighter", "paladin", "ranger",
                    "magic-user", "thief", "monk")


def test_the_dos_save_table_is_the_c64s_own_except_the_three_overrides():
    """The 8x60 bytes at `DS:0x45BE + 5` are the C64's own rows, level by
    level, for every class and level both have -- except the three cells
    `goldbox.levels.CURSE_OF_THE_AZURE_BONDS.dos_save_overrides` names."""
    dosspellslots, image = _curse_image()
    seg = dosspellslots.data_segment(image)
    base = seg * 16 + 0x45BE + 5
    data = image[base:base + 8 * 60]
    overrides = dict(levels.CURSE_OF_THE_AZURE_BONDS.dos_save_overrides)
    checked = 0
    for slot, name in enumerate(_DOS_CLASS_ORDER):
        row = data[slot * 60:(slot + 1) * 60]
        for level in range(1, 13):
            entry = tuple(row[(level - 1) * 5:(level - 1) * 5 + 5])
            c64_row = levels.at_level(name, level, CURSE)
            if c64_row is None:
                continue
            checked += 1
            want = overrides.get((name, level), c64_row.saves)
            assert entry == want, (name, level)
    assert checked >= 60, checked


# --- the conversion, against DOS Curse's own resave --------------------------

def _specimen_root() -> pathlib.Path | None:
    from tools.registry import specimens
    root = specimens.tree_root()
    return root if root.is_dir() else None


def _checked_specimen(rel: str) -> pathlib.Path:
    """One `coab-*` specimen file or directory, checked against its own
    recorded hash -- the pattern `tests/convert/test_dosregainedclass.py` uses
    for the same reason: a specimen is only evidence once we know it has not
    moved since it was recorded."""
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


def _regained_paladin_party():
    """The six characters of `coab-c64/WISH-SPEC-curse-409-regained-paladin`,
    read into neutral records the way `c64_codec.read` reads any C64 save."""
    disk = _checked_specimen(
        "coab-c64/WISH-SPEC-curse-409-regained-paladin.d64")
    game, sg0, sg1 = load_save(D64.open(str(disk)))
    out = []
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        out.append(c64_codec.read(slot.record, roster=block, inventory=inv,
                                  game=game, source=disk.name))
    return out


def _engine_resave_slot_b():
    """`name -> DosCharacter` for slot B of `coab-dos/WISH-SPEC-curse-632-
    wish-converted-resave`, DOS Curse's own `ENCAMP > SAVE` after loading
    Wish's conversion of the same party (#632's own evidence)."""
    root = _specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    specimen_dir = root / "coab-dos/WISH-SPEC-curse-632-wish-converted-resave"
    if not specimen_dir.is_dir():
        pytest.skip(
            "needs specimen coab-dos/WISH-SPEC-curse-632-wish-converted-resave")
    out = {}
    for n in range(1, 7):
        char = dos_codec.read_character(specimen_dir / f"CHRDATB{n}.SAV")
        out[char.name] = char
    return out


def test_a_regained_paladins_party_converts_to_dos_curses_own_resave():
    """MATHEW and MARK are dual-classed-out-of paladins whose regained level
    the C64 counts and DOS Curse's loader does not (`#633`); TRAVIS is a
    dwarf, whose column-0 constitution step DOS computes the other way round
    from the C64's. All three change under this fix; the other three do not.

    Compared against DOS Curse's own resave rather than typed-in numbers, so
    a change to the game's own table would be caught here too. Before the
    fix this fails on MATHEW: `8` where slot B holds `10`.
    """
    party = _regained_paladin_party()
    resave = _engine_resave_slot_b()
    checked = 0
    for neutral in party:
        rec, _itm, _spc, _rep = dos_codec.write(
            neutral, deltas=dos_codec.CURSE_OF_THE_AZURE_BONDS)
        char = dos_codec.DosCharacter(rec, deltas=dos_codec.CURSE_OF_THE_AZURE_BONDS)
        want = resave.get(char.name)
        if want is None:
            continue
        checked += 1
        got = tuple(char.get(n) for n in
                   ("save_paralysis", "save_petrification", "save_wands",
                    "save_breath", "save_spell"))
        want_saves = tuple(want.get(n) for n in
                          ("save_paralysis", "save_petrification",
                           "save_wands", "save_breath", "save_spell"))
        assert got == want_saves, char.name
        assert char.get("thac0_current") == want.get("thac0_current"), char.name
    assert checked == 6
