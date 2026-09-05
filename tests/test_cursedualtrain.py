"""What Curse's trainer does to a character who has dual-classed, replayed.

`#18 (Measure Curse's trainer so Level Up works there)`. Four routines in
Curse's `GEN` behave differently for a non-zero `dual_class_level` at `0x0BA`,
and until 2026-09-05 `goldbox/levelup.py` refused such a character outright
because none of the four had been seen running. All four have now been watched,
over eight `TRAIN CHARACTER` presses on one character in a pooled VICE session:

* `$15E7` -- no hit die at all until the new class passes the old level;
* `$20A3` -- the old class's level and class bit come back at the level after;
* `$124F` -- the old class keeps its own hit-point term, once;
* `$1321` and `$1470` -- its slot is out of eligibility and out of the clamp.

The pair is two disks in the specimen tree. `WISH-SPEC-curse-dual-classed` is
PHILIPPE one `HUMAN CHANGE CLASS` after being a magic-user 6 -- fighter 1, no
experience -- and `WISH-SPEC-curse-dualclass-trained` is the engine's own
`SAVE CURRENT GAME` after seven trainings took her to fighter 8.

**One input was written between presses and it is named here**: her experience,
poked back to `TRAINING_EXPERIENCE` in the roster slot each time, because the
clamp at `$2086` lowers it after every level. Editing an input and watching the
game compute from it is the experiment; nothing read back was written by us
(`.claude/rules/testing.md`).

**The two dice are handed in and everything else is derived.** Presses 1 to 5
are handed *nothing*, so this module has to produce a roll of zero on its own,
which is the whole of `$15E7`; presses 6 and 7 are handed the 4 and the 8 the
engine rolled, because a die leaves no trace a test could re-derive.

Everything skips without the specimen tree, and none of the game's bytes is
committed.
"""

from __future__ import annotations

import pytest

from goldbox import games, levels, levelup
from goldbox.d64 import D64
from goldbox.record import CharacterRecord
from goldbox.savegame import load_save
from tests import gamedata

CURSE = games.CURSE_OF_THE_AZURE_BONDS

#: What was poked into `0x0E8` before each press. Enough for the fighter's
#: seventh level (125,001) and short of its ninth (250,001), so the seven
#: presses raise one level each and the eighth is refused.
TRAINING_EXPERIENCE = 150_000

#: The die the engine rolled, per press. The first five are `None` because the
#: engine rolled none -- `hp_rolled` held 21 from fighter 2 to fighter 6 -- and
#: `plan` has to work that out from `dual_class_level` rather than be told.
DICE = (None, None, None, None, None, 4, 8)

#: What the clamp wrote after each press, watched. The seventh is absent
#: because 150,000 is already below `clamp_threshold("fighter", 8) - 1`.
CLAMPED = (4_000, 8_000, 18_000, 35_000, 70_000, 125_000, 150_000)

#: Every field the trained slot differs in, plus the ones that must *not* move.
COMPARED = ("thac0_base", "hp_max", "attack_level", "save_paralysis",
            "save_petrification", "save_wands", "save_breath", "save_spell",
            "level", "turn_power", "attack_forms", "level_magic_user",
            "level_cleric", "level_thief", "level_fighter", "level_paladin",
            "level_ranger", "class_bits", "experience", "hp_rolled",
            "dual_class_slot", "dual_class_level")


def _disk(name: str):
    """One C64 specimen, checked against its own recorded hash."""
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs specimen WISH-SPEC-{name}")
    path = found[0]
    recorded = specimens.read_provenance(
        path.with_suffix(".provenance.toml")).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail(f"WISH-SPEC-{name}: {path.name} has changed since it was "
                    f"recorded; run tools/specimens.py check")
    return path


def _philippe(name: str) -> CharacterRecord:
    disk = D64.open(str(_disk(name)))
    _game, saved, _roster = load_save(disk)
    slot = saved.slots[0]
    assert str(slot.record.name) == "PHILIPPE", "slot 0 is not the specimen's"
    return slot.record


@pytest.fixture
def measured(monkeypatch):
    """Reach past `TRAINER_MEASURED` for the length of one test.

    `plan` refuses Curse outright, and rightly -- switching the title on is a
    change to `goldbox/levels.py`. Everything here is about whether this module
    *would* reproduce the trainer, which is the question that has to be
    answered before the key is added, so it is asked the way
    `tools/cursetrain.py diff` asks it: in this process only.
    """
    monkeypatch.setattr(levels, "TRAINER_MEASURED",
                        frozenset(set(levels.TRAINER_MEASURED) | {CURSE.key}))


def _replay(record):
    """The seven presses, chained the way one visit to the hall chains them."""
    out = [record]
    for die in DICE:
        stepped = CharacterRecord.from_bytes(bytes(out[-1]))
        stepped.set("experience", TRAINING_EXPERIENCE)
        kw = {"game": CURSE}
        if die is not None:
            kw["rolled"] = die
        plan = levelup.plan(stepped, "fighter", **kw)
        out.append(levelup.apply_to(stepped, plan))
    return out


def test_the_specimen_is_the_pair_this_replay_expects():
    """Before: fighter 1, no experience, magic-user 6 left behind. After:
    fighter 8 with the magic-user back. If either disk is not that, nothing
    below means anything."""
    before, after = _philippe("curse-dual-classed"), \
        _philippe("curse-dualclass-trained")
    assert (before.get("level_fighter"), before.get("level_magic_user")) == (1, 0)
    assert (before.get("dual_class_slot"), before.get("dual_class_level")) == (0, 6)
    assert before.get("experience") == 0
    assert before.get("class_bits") == 0x08
    assert (after.get("level_fighter"), after.get("level_magic_user")) == (8, 6)
    assert after.get("class_bits") == 0x09


def test_no_hit_die_until_the_new_class_passes_the_old_level(measured):
    """`GEN $15E7`. Five levels with no die and no hit points, then a die.

    This is the one field the replay is *not* handed: presses 1 to 5 pass no
    `rolled`, so a `plan` that rolled a die anyway would show up here as a
    non-zero `hit_points_rolled` and as `hp_rolled` climbing above 21.
    """
    record = _philippe("curse-dual-classed")
    states = _replay(record)
    rolled = [s.get("hp_rolled") for s in states]
    assert rolled == [21, 21, 21, 21, 21, 21, 25, 33], rolled


def test_the_old_class_comes_back_at_the_level_above_it(measured):
    """`GEN $20A3`. Not at fighter 6, and at fighter 7."""
    states = _replay(_philippe("curse-dual-classed"))
    got = [(s.get("level_fighter"), s.get("level_magic_user"),
            s.get("class_bits")) for s in states]
    assert got == [(1, 0, 0x08), (2, 0, 0x08), (3, 0, 0x08), (4, 0, 0x08),
                   (5, 0, 0x08), (6, 0, 0x08), (7, 6, 0x09), (8, 6, 0x09)], got


def test_the_clamp_writes_what_the_engine_wrote_after_every_press(measured):
    """`GEN $2086`, six lowerings and one no-op. Nothing had ever seen this
    clamp actually lower a Curse character's experience before: all five of
    the trainings driven earlier kept what they arrived with."""
    states = _replay(_philippe("curse-dual-classed"))
    assert [s.get("experience") for s in states[1:]] == list(CLAMPED)


def test_the_old_class_is_never_ready_however_much_experience_it_has(measured):
    """`GEN $1321`. The eighth press was refused with `UNABLE TO ADVANCE`
    while she held 150,000 experience and a magic-user 6 that wants 135,001."""
    final = _replay(_philippe("curse-dual-classed"))[-1]
    final.set("experience", TRAINING_EXPERIENCE)
    assert final.get("level_magic_user") == 6
    assert final.get("class_bits") & 0x01, "the magic-user's bit is back"
    assert levels.next_threshold("magic-user", 6, CURSE) < TRAINING_EXPERIENCE
    assert levelup.ready_classes(final, CURSE) == []
    with pytest.raises(levelup.CannotLevel):
        levelup.plan(final, "magic-user", game=CURSE)


def _staged(record, **fields) -> CharacterRecord:
    """A copy of the specimen's record with named fields written into it.

    The same thing the session did from the monitor: an **input** is edited and
    the engine's answer is what gets read. Here there is no engine, so what is
    being checked is that this module answers what the engine answered.
    """
    out = CharacterRecord.from_bytes(bytes(record))
    for name, value in fields.items():
        out.set(name, value)
    return out


def test_the_clamp_leaves_the_class_the_character_left_out_of_its_maximum(
        measured):
    """`GEN $1470`, in two arrangements.

    **The first is the one that was watched.** A character carrying a
    magic-user 10 as its old class and a fighter 1 as its new one, staged into
    the roster slot from the monitor with 400,000 experience, was trained once
    and the engine wrote **4,000** -- the fighter's
    `clamp_threshold(2) - 1`, not the magic-user's 375,000.

    **The second is a constructed record, and it is here because the first
    does not discriminate this module.** `_experience` walks the classes in
    `class_bits`, and a dual-classed character's old class is out of that mask
    until `$20A3` puts it back -- so in the watched arrangement the right
    answer falls out whether the skip is there or not. The branch only bites
    after the restore, and this is a case where the old class's clamp is the
    larger: a thief 10 who used to be a cleric 10 crosses into thief 11, the
    cleric comes back, and 675,000 would be written instead of 440,000. That
    character may not be one `GEN $23FC`'s own list would offer -- what is
    tested is the routine, which was read rather than reasoned about.
    """
    record = _philippe("curse-dual-classed")

    watched = _staged(record, level_magic_user=10, level_fighter=1,
                      dual_class_slot=0, dual_class_level=10,
                      class_bits=0x08, experience=400_000)
    assert levelup.plan(watched, "fighter",
                        game=CURSE).fields["experience"] == 4_000

    constructed = _staged(record, level_magic_user=0, level_cleric=0,
                          level_thief=10, level_fighter=0,
                          dual_class_slot=1, dual_class_level=10,
                          class_bits=0x04, experience=700_000)
    plan = levelup.plan(constructed, "thief", game=CURSE)
    assert plan.fields["level_cleric"] == 10, "the cleric should be back"
    assert plan.fields["experience"] == 440_000


def test_every_field_of_the_trained_slot_comes_out_of_this_module(measured):
    """The whole point: chain the seven presses and compare the result with
    what the engine wrote, field by field.

    The two dice are given and everything else is derived -- saving throws,
    THAC0, `attack_level`, `attack_forms`, `hp_max`, `level`, the experience
    clamp, the class array and the class mask.
    """
    got = _replay(_philippe("curse-dual-classed"))[-1]
    want = _philippe("curse-dualclass-trained")
    mismatches = {name: (got.get(name), want.get(name))
                  for name in COMPARED if got.get(name) != want.get(name)}
    assert not mismatches, mismatches


def test_the_rest_of_the_party_is_the_control():
    """Only PHILIPPE was trained, so the other five slots must be identical
    across the pair. Five of five, byte for byte over the whole slot."""
    pairs = []
    for name in ("curse-dual-classed", "curse-dualclass-trained"):
        disk = D64.open(str(_disk(name)))
        _game, saved, _roster = load_save(disk)
        pairs.append([bytes(s.record) if s.record is not None else None
                      for s in saved.slots])
    before, after = pairs
    named = [n for n in range(1, min(len(before), len(after)))
             if before[n] is not None]
    assert len(named) == 5, named
    moved = [n for n in named if before[n] != after[n]]
    assert moved == [], moved
