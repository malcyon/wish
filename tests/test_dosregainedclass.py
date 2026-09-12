"""A regained dual-classed character crossing to DOS (#408).

Curse's `GEN $20A3` restores a dual-classed character's old class level once
his new class passes the level he left the old one at, and OR's the old
class's bit back into `class_bits` -- so the C64's own `levels` for a
character in that state names *both* classes.  DOS never stores that:
`GAME.OVR:0x3B119` derives `class_bits` from `class_levels` and
`former_class_levels` on every recompute, and the trainer at `0x254B3` never
raises a slot that reads zero, so the old class's `class_levels` slot has to
stay zero and `char_class` has to stay the code for the class he is now,
alone, or a converted character's DOS sheet reads as multi-classed and every
later training halves his hit points.

Two C64 specimens carry PHILIPPE, a human magic-user 6 who took `HUMAN CHANGE
CLASSES` to fighter: `WISH-SPEC-curse-dual-classed` one action later, fighter
1, the old slot still zero; `WISH-SPEC-curse-dualclass-trained`, the engine's
own `SAVE CURRENT GAME` after seven trainings took her to fighter 8, past the
6 she left, so `class_levels {magic-user: 6, fighter: 8}` and `class_bits
0x09` -- both classes, and `docs/209-the-regained-dual-class-on-dos.md`'s
target shape for this fix.

`WISH-SPEC-curse-408-regained-paladin`'s `CHRDATJ1.SAV` (MATHEW) is the DOS
engine's own record in that same regained state -- watched under DOSBox,
`GAME.OVR:0x3B119` read out of the overlay before any of it ran -- and is the
shape a converted record is compared against: `class_levels {magic-user: 6}`
alone, `former_class_levels {paladin: 5}`, `char_class 5` (magic-user alone),
`class_bits 0x41` (both bits).

Every test skips without the specimen tree.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import c64_codec, dos_codec, items
from goldbox.d64 import D64
from goldbox.savegame import load_save


def _specimen_root() -> pathlib.Path | None:
    from gamedata import specimen_root
    return specimen_root()


def _c64_disk(name: str) -> pathlib.Path:
    """One flat C64 specimen disk, checked against its own recorded hash."""
    from tools import specimens

    root = _specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted(root.glob(f"*-c64/WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs specimen WISH-SPEC-{name}")
    path = found[0]
    recorded = specimens.read_provenance(
        path.with_suffix(".provenance.toml")).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail(f"WISH-SPEC-{name}: {path.name} has changed since it "
                    f"was recorded; run tools/specimens.py check")
    return path


def _philippe(name: str) -> "dos_codec.NeutralCharacter":  # type: ignore[name-defined]
    """PHILIPPE, read into the neutral record, off one named C64 disk."""
    disk = _c64_disk(name)
    game, sg0, sg1 = load_save(D64.open(str(disk)))
    for slot in sg0.characters:
        if slot.record.name.strip() != "PHILIPPE":
            continue
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        return c64_codec.read(slot.record, roster=block, inventory=inv,
                              game=game, source=disk.name)
    pytest.fail(f"{disk.name} has no PHILIPPE")


def _mathew() -> dos_codec.DosCharacter:
    """MATHEW, the DOS engine's own regained dual-classed record."""
    root = _specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted(root.glob(
        "coab-dos/WISH-SPEC-curse-408-regained-paladin/CHRDATJ1.SAV"))
    if not found:
        pytest.skip("needs specimen WISH-SPEC-curse-408-regained-paladin")
    return dos_codec.read_character(found[0])


def test_the_engine_written_specimen_has_the_target_shape():
    """`docs/209-the-regained-dual-class-on-dos.md`'s reading, off the bytes
    rather than the disassembly: the old class's `class_levels` slot is
    zero, the former array and `char_class` alone name it, `class_bits`
    carries both."""
    mathew = _mathew()
    assert mathew.class_levels == {"magic-user": 6}
    assert dict(zip(
        (n for _, n, _ in dos_codec.CLASS_LEVEL_SLOTS),
        mathew.raw("former_class_levels")))["paladin"] == 5
    assert mathew.get("char_class") == 5
    assert mathew.get("class_bits") == 0x41


def test_a_regained_character_converts_to_dos_in_the_engines_own_shape():
    """PHILIPPE, trained past the level she left magic-user at, converts to
    a Curse DOS record shaped like MATHEW's: the old class's `class_levels`
    slot zero, `char_class` the new class alone, `class_bits` both bits.

    This is the case #408 exists for: before the fix, `class_levels` carried
    fighter 8 **and** magic-user 6, and `char_class` came back 13
    (fighter/magic-user), which is a DOS multi-class code and not the
    dual-classed shape DOS itself ever writes.
    """
    neutral = _philippe("curse-dualclass-trained")
    rec, _itm, _spc, rep = dos_codec.write(neutral, deltas=dos_codec.CURSE_OF_THE_AZURE_BONDS)
    char = dos_codec.DosCharacter(rec, deltas=dos_codec.CURSE_OF_THE_AZURE_BONDS)

    assert char.class_levels == {"fighter": 8}
    assert list(char.raw("class_levels")) == [0, 0, 8, 0, 0, 0, 0, 0]
    assert list(char.raw("former_class_levels")) == [0, 0, 0, 0, 0, 6, 0, 0]
    assert char.get("char_class") == 2   # fighter alone, not 13
    assert char.get("class_bits") == 0x09
    assert dos_codec.class_bits_for(char) == char.get("class_bits")

    lines = "\n".join(set(rep.sources.values()))
    assert "magic-user zeroed here" in lines
    assert "#408" in lines


def test_an_unregained_dual_classed_character_is_unchanged():
    """PHILIPPE one action after the change, fighter 1, has not passed the
    magic-user 6 she left -- the ordinary case this fix must not touch.
    `class_levels` carries the new class alone before conversion as well as
    after, so nothing here has anything to zero."""
    neutral = _philippe("curse-dual-classed")
    rec, _itm, _spc, rep = dos_codec.write(neutral, deltas=dos_codec.CURSE_OF_THE_AZURE_BONDS)
    char = dos_codec.DosCharacter(rec, deltas=dos_codec.CURSE_OF_THE_AZURE_BONDS)

    assert char.class_levels == {"fighter": 1}
    assert list(char.raw("former_class_levels")) == [0, 0, 0, 0, 0, 6, 0, 0]
    assert char.get("char_class") == 2
    assert char.get("class_bits") == 0x08
    assert dos_codec.class_bits_for(char) == char.get("class_bits")

    lines = "\n".join(set(rep.sources.values()))
    assert "zeroed here" not in lines
