"""A fight driven in DOSBox: load, fight, save, and read the records after."""

import pytest

from tools.dos import dosbox, dosfightrun

pytestmark = pytest.mark.xdist_group(name="emulator-pool")


def test_a_driven_fight_raises_experience_in_the_records():
    """Walk into a wandering fight, `fight()` it, and read the files after.

    Experience rising is the assertion because it is the only field that says
    the party did the killing. Hit points are not asserted on in either
    direction: a fight the party wins without being touched moves none of
    them, and a fight it stands through moves plenty.
    """
    if dosbox.missing_tools():
        pytest.skip("needs " + ", ".join(dosbox.missing_tools()))
    try:
        dosbox.find_game()
    except FileNotFoundError as e:
        pytest.skip(str(e))
    out = dosfightrun.fight_run(save="J", rounds=1)
    run = out["runs"][0]
    assert run.get("fight") is True, run
    assert run["fought"] is True, run["diff"]["chars"]
