"""The DOS training ladder: its routing, and the records the trainer wrote.

`tools/dosladder.py` walks DOS Pool of Radiance's training hall and presses
`TRAIN CHARACTER`.  Two halves are worth testing and they fail for different
reasons.

**The routing** is arithmetic over the player's own `GEO00`, and it can be
checked without an emulator: the hall's thirteen squares, the turns that face
the party the right way, and a walk to each of the four schools that
`goldbox.geo` agrees is legal.  A wrong route sends a run into a wall and
costs a boot to find out.

**The records** are the specimens the tool made -- `WISH-SPEC-por-party-l*`,
levelled through the game's own schools -- and what is asserted about them is
what the *engine* computed, never what we staged.  `.claude/rules/testing.md`
draws that line: experience and gold went in as inputs and prove nothing,
while the level, the hit points and the experience the trainer left behind are
the game's own answer.  These skip where the specimen tree is absent, which is
every CI runner.
"""

from __future__ import annotations

import types

import gamedata
import pytest

from goldbox import geo as geolib
from goldbox import levels
from tools import dosladder


def _character(name, **classes):
    """A stand-in with the one attribute `plan` reads."""
    return types.SimpleNamespace(name=name, class_levels=classes)


# -- the routing, which needs no emulator ------------------------------------


def test_turns_takes_the_short_way_round():
    assert dosladder.turns(0, 0) == []
    assert dosladder.turns(0, 1) == ["Right"]
    assert dosladder.turns(0, 3) == ["Left"]
    assert dosladder.turns(3, 0) == ["Right"]
    assert dosladder.turns(0, 2) == ["Right", "Right"]


def test_direction_names_the_neighbour_it_steps_to():
    assert dosladder.direction((6, 1), (6, 0)) == 0
    assert dosladder.direction((6, 1), (7, 1)) == 1
    assert dosladder.direction((6, 1), (6, 2)) == 2
    assert dosladder.direction((6, 1), (5, 1)) == 3
    with pytest.raises(ValueError):
        dosladder.direction((6, 1), (8, 1))


def test_a_single_class_character_goes_to_its_own_school():
    party = [_character("A", fighter=1), _character("B", cleric=2),
             _character("C", **{"magic-user": 1}), _character("D", thief=1)]
    assert dosladder.plan(party) == {
        "fighter": [1], "cleric": [2], "magic-user": [3], "thief": [4]}


def test_a_multi_class_character_trains_the_class_it_is_furthest_behind_in():
    """Otherwise one class of a three-class character runs away with every
    rung and the other two never move."""
    party = [_character("HEL", cleric=3, fighter=1, **{"magic-user": 2})]
    assert dosladder.plan(party) == {"fighter": [1]}
    party = [_character("HEL", cleric=3, fighter=3, **{"magic-user": 2})]
    assert dosladder.plan(party) == {"magic-user": [1]}


def test_a_character_with_no_class_is_left_alone():
    assert dosladder.plan([_character("X")]) == {}


def test_source_letter_is_read_off_the_container(tmp_path):
    """A party is installed under the letter it already uses, because
    `SAVGAM<letter>.DAT` names its own six character files."""
    (tmp_path / "SAVGAMF.DAT").write_bytes(b"")
    (tmp_path / "CHRDATF1.SAV").write_bytes(b"")
    assert dosladder.source_letter(tmp_path) == "F"
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        dosladder.source_letter(empty)


def test_extract_takes_one_slot_out_of_a_snapshot(tmp_path):
    """A snapshot of `SAVE/` after a rung holds several parties -- the slot
    the rung loaded and one per school it saved at -- and handing all of them
    to the next rung installs one on top of another."""
    snap = tmp_path / "snap"
    snap.mkdir()
    for name in ("SAVGAMA.DAT", "CHRDATA1.SAV", "CHRDATA1.SPC",
                 "SAVGAMB.DAT", "CHRDATB1.SAV", "EXPLORED.DAT"):
        (snap / name).write_bytes(b"x")
    out = dosladder.extract(snap, "B", tmp_path / "party")
    assert sorted(p.name for p in out.iterdir()) == ["CHRDATB1.SAV",
                                                     "SAVGAMB.DAT"]


# -- the routing against the player's own map --------------------------------


@pytest.fixture(scope="module")
def new_phlan():
    """`GEO00`, which area 11 borrows: the training hall has no map."""
    if gamedata.disk_dir() is None:
        pytest.skip("needs the player's Pool of Radiance disks")
    return geolib.Geo(gamedata.game_file("GEO00"))


def test_the_hall_squares_agree_with_the_players_own_map(new_phlan):
    """`docs/50-experiments.md` P18 read the schools out of `ECL0B` on the
    C64.  Every one of the thirteen is where the DOS map says it is, so the
    route this tool computes is over the right squares."""
    assert dosladder.check_hall(new_phlan) == []


@pytest.mark.parametrize("school,through", [
    ((5, 0), (6, 0)),
    ((7, 0), (6, 0)),
    ((8, 0), (8, 1)),
    ((9, 0), (9, 1)),
])
def test_every_school_can_be_walked_to_from_the_lobby(new_phlan, school,
                                                      through):
    """From the lobby at `(6,2)`, where the door puts a party that walks in.

    `walkable_route` is `goldbox.geo`'s own check and knows nothing about this
    tool, so a route that satisfies both is not the search agreeing with
    itself.  The fighters' and thieves' schools are reached through their own
    signposted squares -- an earlier run looked for them off the `(6,0)`
    corridor and found a wall.
    """
    path = dosladder.route(new_phlan, (6, 2), school)
    assert path[0] == (6, 2) and path[-1] == school
    assert through in path
    assert new_phlan.walkable_route(path)
    assert all(square in dosladder.HALL for square in path)


def test_a_route_never_leaves_the_hall(new_phlan):
    """Every square of every route is one `ECL0B` has a script for.  A route
    that stepped outside would leave the training hall mid-walk."""
    for school in dosladder.SCHOOLS:
        for start in dosladder.HALL:
            path = dosladder.route(new_phlan, start, school)
            assert set(path) <= dosladder.HALL


# -- what the trainer wrote --------------------------------------------------
#
# The party is `#249 (Build a DOS party from creation and level it ourselves,
# so DOS measurements rest on records we watched being written)`'s: six
# characters rolled in the game's own creation screens and levelled through
# its own schools. Nothing here asserts a number we wrote.

LADDER = "por-party-ladder"
#: Every rung of the ladder that is in the tree, so the sample is the whole
#: climb rather than its last step.  The last one is `LADDER` itself, and by
#: then four of the six characters are at a Pool of Radiance ceiling -- where
#: there is no next threshold and nothing to be one short of.
RUNGS = [f"por-party-ladder-rung{n}" for n in range(9)] + [LADDER]


def _ladder_records():
    """Every single-class record across every rung, as (specimen, path)."""
    from goldbox import dos

    out = []
    for name in RUNGS:
        if not gamedata.have_specimen(name):
            continue
        where = gamedata.specimen(name)
        for path in sorted(where.glob("CHRDAT*.SAV")):
            record = dos.read_character(path)
            if len(record.class_levels) == 1:
                out.append((name, path.name, record))
    return out


@pytest.mark.skipif(not gamedata.have_specimen(LADDER),
                    reason=f"needs specimen WISH-SPEC-{LADDER}")
def test_every_trained_record_stops_one_short_of_its_next_level():
    """**The trainer leaves a character one experience point short**, so it
    cannot be trained twice on one staging -- measured in `#249 (Build a DOS
    party from creation and level it ourselves, so DOS measurements rest on
    records we watched being written)`, and the reason a ladder needs a boot
    per level.

    Two exceptions, both named rather than rounded away.  A character at its
    class's **ceiling** has no next threshold and keeps whatever it went in
    with.  A **multi-class** character is counted against the largest of its
    classes' caps, which is a rule `tools/dosladder.clamp_cap` states and this
    does not re-test.
    """
    checked = 0
    for specimen, filename, record in _ladder_records():
        (name, level), = record.class_levels.items()
        want = levels.next_threshold(name, level)
        if want is None:
            continue
        experience = record.get("experience")
        if experience > want:
            continue          # never trained on that rung; still our staging
        assert experience == want - 1, f"{specimen}/{filename} {name} {level}"
        checked += 1
    assert checked >= 10, f"only {checked} records to check"


@pytest.mark.skipif(not gamedata.have_specimen(LADDER),
                    reason=f"needs specimen WISH-SPEC-{LADDER}")
def test_no_character_rolled_more_hit_points_than_its_dice_allow():
    """`hp_rolled` is the sum of the trainer's own dice, so it lies between one
    per level and the whole die per level -- `goldbox/levels.py`'s `hit_dice`
    says which die.  `hp_max` is that plus a constitution bonus, so it is only
    checked for being at least the rolled total.

    Single-class characters only: a multi-class character's dice are averaged
    between its classes, which is a different sum.
    """
    checked = 0
    for specimen, filename, record in _ladder_records():
        (name, level), = record.class_levels.items()
        faces = int(levels.at_level(name, level).hit_dice.split("d")[1])
        rolled, most = record.get("hp_rolled"), record.get("hp_max")
        where = f"{specimen}/{filename} {name} {level}"
        assert level <= rolled <= level * faces, f"{where} rolled {rolled}"
        assert most >= rolled, f"{where} hp_max {most} < rolled {rolled}"
        checked += 1
    assert checked >= 20, f"only {checked} records to check"
