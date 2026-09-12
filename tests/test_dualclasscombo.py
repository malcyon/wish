"""The Class combo and a conversion, for a dual-classed Curse character.

`#393 (A dual-classed Curse character may show one class in the editor and
convert as another, and no specimen exists to tell)`.  Two parts of Wish
answer "what class is this character" and they ask it differently:

* `editor/window.py`'s `_char_class_shown`, behind the Class combo, calls
  `goldbox.classcode.repair(raw, class_bits, game=...)` -- the mask alone;
* `goldbox.c64_codec.read`, which a conversion goes through, calls the same
  function with `levels` and `former_levels` as well, and those send a
  **dual-classed** character down `classcode.code_for`'s other branch, where
  the answer comes off the level array instead of off the mask.

They agree, and the reason is the engine rather than the two calls being the
same: Curse's `GEN $20A3` writes the old class's level back into the level
array and ORs its bit into `class_bits` in the same routine, under one test,
so a C64 record is never caught with one done and not the other.
`test_the_two_call_shapes_really_can_disagree` is what stops the rest of this
file passing for the empty reason -- it hands the two calls a mask and a level
array that contradict each other and watches them part company.

The specimens are `WISH-SPEC-curse-dualclass-trained` (PHILIPPE, a human
magic-user 6 who took `HUMAN CHANGE CLASSES` to fighter and was then trained
to fighter 8 at Curse's own hall, which is past the level she left the old
class at, so the engine has given it back) and `WISH-SPEC-curse-dual-classed`
(the same character at fighter 1, one action after the change).
"""

import os
import pathlib

import pytest
from gamedata import specimen_root

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from goldbox import c64_codec, c64_port, classcode, items
from goldbox.d64 import D64
from goldbox.savegame import load_save

CURSE = c64_port.by_key("curse-of-the-azure-bonds")

#: Class name -> its bit in the neutral order, the same table
#: `tools/classcombocheck.py` and `tools/classcodecensus.py` carry.  The
#: bitmask a level array implies is not a field any record stores.
BIT_FOR_CLASS = {"magic-user": 0x01, "cleric": 0x02, "thief": 0x04,
                 "fighter": 0x08, "knight": 0x10, "paladin": 0x40,
                 "ranger": 0x80}

#: Curse's own class table gives fighter/magic-user code 13 and fighter 2
#: (`goldbox/classcode.py`, `GEN $1951`).
FIGHTER_MAGIC_USER, FIGHTER = 13, 2


def _c64_specimen(name: str) -> pathlib.Path:
    """A named C64 specimen disk, verified against its own manifest.

    The C64 half of the tree is flat files rather than directories, so
    `gamedata.specimen` does not reach it; this is the same rule
    `tests/test_editor.py`'s `_curse_trained_party_specimen` applies, which
    is that a specimen whose bytes have moved is no longer evidence and the
    test says so rather than skipping.
    """
    from tools import specimens

    root = specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted(root.glob(f"*-c64/WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs specimen WISH-SPEC-{name}")
    path = found[0]
    prov = path.with_suffix(".provenance.toml")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail(f"WISH-SPEC-{name}: {path.name} has changed since it was "
                    f"recorded; run tools/specimens.py check")
    return path


def _member(path: pathlib.Path, who: str):
    """`(record, neutral)` for one named character on a C64 save disk."""
    game, sg0, sg1 = load_save(D64.open(str(path)))
    for slot in sg0.characters:
        if slot.record.name.strip() != who:
            continue
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        neutral = c64_codec.read(slot.record, roster=block, inventory=inv,
                                 game=game, source=path.name)
        return slot.record, neutral
    pytest.fail(f"{path.name} has no {who}")


def _bits_from_levels(levels) -> int:
    out = 0
    for name, level in (levels or {}).items():
        if level:
            out |= BIT_FOR_CLASS.get(name, 0)
    return out


def test_the_two_call_shapes_really_can_disagree():
    """The guard on everything else here.

    Hand `classcode.repair` a mask that says fighter and a level array that
    says fighter **and** magic-user, with a former class, and the two call
    shapes give different codes -- 2 against 13.  So the agreement the rest of
    this file measures is a fact about what Curse's engine leaves on disk, and
    not two identical calls agreeing with themselves.  No record has this
    shape; it is built here to make the branch discriminate.
    """
    mask_only = classcode.repair(0, 0x08, game=CURSE)
    with_levels = classcode.repair(
        0, 0x08, {"fighter": 8, "magic-user": 6}, {"magic-user": 6},
        game=CURSE)
    assert mask_only == FIGHTER
    assert with_levels == FIGHTER_MAGIC_USER
    assert mask_only != with_levels


def test_the_combo_and_a_conversion_agree_on_a_regained_dual_class():
    """#393's question, on the only record anywhere that asks it.

    PHILIPPE is a human magic-user 6 who changed class to fighter and was
    trained to fighter 8, past the 6 she left the old class at, so `GEN $20A3`
    has put `level_magic_user` back to 6 and ORed magic-user's bit into
    `class_bits`.  The Class combo would draw fighter/magic-user; a conversion
    writes fighter/magic-user.  The stored byte is neither -- Curse's trainer
    left it at 6, which the table calls a thief.
    """
    from editor.window import _char_class_shown

    path = _c64_specimen("curse-dualclass-trained")
    record, neutral = _member(path, "PHILIPPE")

    assert record.get("char_class") == 6            # the stale byte, #310
    assert record.get("class_bits") == 0x09
    assert neutral.get("former_levels") == {"magic-user": 6}
    assert {k: v for k, v in neutral.get("levels").items() if v} == {
        "magic-user": 6, "fighter": 8}

    shown = _char_class_shown(record.get("char_class"), record, CURSE)
    assert shown == FIGHTER_MAGIC_USER
    assert neutral.get("char_class") == FIGHTER_MAGIC_USER
    assert shown == neutral.get("char_class")


def test_the_combo_and_a_conversion_agree_one_action_after_the_change():
    """The same character before the old class comes back.

    At fighter 1 the mask carries the new class alone and the old class's
    level slot is zero, so both answers are fighter.  This is the state every
    other dual-classed record in the corpus is in, on both ports.
    """
    from editor.window import _char_class_shown

    path = _c64_specimen("curse-dual-classed")
    record, neutral = _member(path, "PHILIPPE")

    assert record.get("class_bits") == 0x08
    assert neutral.get("former_levels") == {"magic-user": 6}
    assert {k: v for k, v in neutral.get("levels").items() if v} == {
        "fighter": 1}

    shown = _char_class_shown(record.get("char_class"), record, CURSE)
    assert shown == FIGHTER
    assert neutral.get("char_class") == FIGHTER


def test_the_window_draws_the_class_the_conversion_would_write():
    """The same reading through the window the player actually opens, rather
    than through the function behind it -- the combo's own current item."""
    from test_editor import make_root

    from editor.window import EditorBinding

    path = _c64_specimen("curse-dualclass-trained")
    _record, neutral = _member(path, "PHILIPPE")

    editor = EditorBinding(make_root(), str(path))
    row = next(i for i, m in enumerate(editor.party.members)
               if m.name.strip() == "PHILIPPE")
    editor.roster.selectRow(row)
    combo = editor._widgets["char_class"]

    assert combo.currentData() == neutral.get("char_class")
    shown = combo.currentText().lower()
    assert "fighter" in shown and "magic-user" in shown


@pytest.mark.parametrize("name", ["curse-dualclass-trained",
                                  "curse-dual-classed",
                                  "curse-trained-party"])
def test_the_mask_and_the_level_array_never_disagree_on_a_curse_disk(name):
    """The mechanism, and the thing that would break the answer if it moved.

    Every writer of either field on the six Curse sides keeps them in step:
    creation derives the level array from the mask (`GEN $0B40`), `GEN $20A3`
    writes both under one test, `GEN $18A4` only rewrites slots that are
    already set, and `SPELLE20 $0C5A` derives the mask from the array.  So a
    record whose stored mask differs from the one its level array implies
    would be a state nothing on the disks can produce -- and it is exactly the
    state in which the Class combo and a conversion would part company.
    """
    path = _c64_specimen(name)
    game, sg0, sg1 = load_save(D64.open(str(path)))
    checked = 0
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        neutral = c64_codec.read(slot.record, roster=block, inventory=inv,
                                 game=game, source=path.name)
        stored = slot.record.get("class_bits") or 0
        assert stored == _bits_from_levels(neutral.get("levels")), (
            f"{path.name} {slot.record.name.strip()}: class_bits "
            f"{stored:#04x} against the level array's "
            f"{_bits_from_levels(neutral.get('levels')):#04x}")
        checked += 1
    assert checked == 6
