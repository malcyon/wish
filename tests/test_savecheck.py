"""Counting the figures a fight draws, against the fight the engine is running.

Nothing here needs an emulator or a display: the battle is built by hand from
`automap.combat`'s own dataclasses, which is what `read_battle` hands back out
of the running machine.

The reason these are tests is
`#185 (Two of six party members were not drawn on the combat floor at Sokol
Keep)`.  `savecheck --icon` counted the party figures it found on the floor and
never said what it should have found, so a converted party of six that drew
four was reported as a pass and the shortfall was noticed by a person reading
the log.

**What the count is compared against is not the party size.**  The game draws a
seven-square window (`automap.combat.VIEW`) onto a battlefield that has been
56 x 26 in every fight read here, so a party member six squares away is off the
drawn portion and there is nothing whatever wrong with them.  Comparing against
the party size would fail on those, which is the assertion that would have been
wrong.  What is compared is the position table: how many combatants the engine
puts *inside* the window.
"""

from conftest import load_tools_module

savecheck = load_tools_module("savecheck")
roll_call = savecheck.roll_call
undrawn = savecheck.undrawn

from automap.combat import VIEW, Battle, Combatant, Shape  # noqa: E402

SHAPE = Shape(map_base=0x8C00, stride=56, width=56, height=26,
              positions=0x8B00, count=16)


def who(index: int, x: int, y: int, on_map: bool = True) -> Combatant:
    return Combatant(index=index, x=x, y=y, slot=0, pose=0, on_map=on_map,
                     initiative=0, hp=10, hp_max=10)


def fight(*people: Combatant, camera=(24, 10)) -> Battle:
    return Battle(shape=SHAPE, terrain=bytes(SHAPE.length),
                  combatants=tuple(people), camera=camera)


class FakeSession:
    """Only what `roll_call` asks of a session."""

    def __init__(self, battle):
        self._battle = battle

    def battle(self):
        return self._battle


def party_of_six(spread: int = 0) -> Battle:
    """Six party members in a row from the camera's corner, plus two enemies.

    `spread` pushes the last two past the window's right edge, which is the
    ordinary state this must not complain about.
    """
    x0, y0 = 24, 10
    people = [who(i, x0 + i, y0) for i in range(4)]
    people += [who(4, x0 + 4 + spread, y0), who(5, x0 + 5 + spread, y0)]
    people += [who(8, x0 + 1, y0 + 1), who(9, x0 + 2, y0 + 1)]
    return fight(*people, camera=(x0, y0))


def test_the_window_is_measured_from_the_camera_and_not_from_the_party():
    roll = roll_call(FakeSession(party_of_six()))
    assert roll["party_size"] == 6
    assert roll["party_in_window"] == 6
    assert roll["camera"] == [24, 10]
    assert roll["view"] == VIEW
    assert roll["map"] == [56, 26]


def test_a_party_member_outside_the_drawn_window_is_not_a_missing_figure():
    # Sokol Keep's shape: six on the map, two of them further than the seven
    # squares the game draws, and a floor that therefore shows four.
    roll = roll_call(FakeSession(party_of_six(spread=6)))
    assert roll["party_size"] == 6
    assert roll["party_on_map"] == 6
    assert roll["party_in_window"] == 4
    assert undrawn(roll, blocks=4 + roll["enemies_in_window"]) == []


def test_a_figure_the_engine_puts_in_the_window_and_the_floor_omits_is_reported():
    # All six inside the window and only four drawn.  This is the state
    # `--icon` used to report as a pass.
    roll = roll_call(FakeSession(party_of_six()))
    said = undrawn(roll, blocks=6)
    assert said, "eight combatants in the window and six figures drawn"
    assert "only 6 figures" in said[0] and "8 inside" in said[0]


def test_a_screen_still_holding_the_frame_before_a_scroll_is_not_a_complaint():
    # The camera moves between one combatant's turn and the next, and the
    # screen read and the memory read are milliseconds apart, so the floor can
    # carry figures from before the scroll.  Measured on the engine-written
    # Sokol Keep control: 27 turns of 30 matched exactly and three drew two
    # **more** than the table put in the window, never fewer.  Reporting that
    # would make the check cry wolf on a tenth of every fight.
    roll = roll_call(FakeSession(party_of_six()))
    assert undrawn(roll, blocks=roll["party_in_window"]
                   + roll["enemies_in_window"] + 2) == []


def test_a_party_member_off_the_map_is_named_even_when_the_count_agrees():
    x0, y0 = 24, 10
    people = [who(i, x0 + i, y0) for i in range(5)]
    people.append(who(5, 0xFF, 0xFF, on_map=False))
    roll = roll_call(FakeSession(fight(*people, camera=(x0, y0))))
    assert roll["party_on_map"] == 5
    # The floor draws exactly what the table puts in the window, so the count
    # is silent -- and the missing sixth still has to be said out loud.
    said = undrawn(roll, blocks=5)
    assert said == ["Off the map altogether: #5"]


def test_a_fight_that_cannot_be_read_is_said_so_rather_than_passing():
    assert roll_call(FakeSession(None)) == {}
    assert "could not be read" in undrawn({}, blocks=0)[0]
