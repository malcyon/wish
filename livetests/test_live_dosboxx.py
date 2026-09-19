"""The DOSBox-X debugger harness, booted for real."""

import pytest

from tools.dos import dosbox, dosboxx

pytestmark = pytest.mark.xdist_group(name="emulator-pool")


def test_the_harness_reproduces_the_clock_tick_docs_142_recorded():
    """Every number here is one `docs/142-dosbox-x-debugger.md` already carries.

    The base address is deliberately not asserted: it is where DOS happened to
    load that build with that config, not a finding.  What is asserted is the
    recipe -- the array is found, the live byte agrees with the save, the
    spurious `00 ->` hit is absorbed, and the real tick is caught.
    """
    if dosboxx.unavailable():
        pytest.skip(dosboxx.unavailable())
    try:
        game = dosbox.find_game("POOLRAD")
    except FileNotFoundError as e:
        pytest.skip(str(e))
    if not (game / "SAVE" / "SAVGAMJ.DAT").is_file():
        pytest.skip("needs the player's slot J")

    out = dosboxx.clock_demo("J")
    assert out["attached"]
    assert out["dumped"] == 0x100000
    assert out["votes"] > 50
    assert out["live"] == out["in_save"]
    assert out["absorbed"].startswith("Break(") and "old=0," in out["absorbed"]
    old, new = out["tick"].split()[1], out["tick"].split()[3]
    assert int(new, 16) == int(old, 16) + 1
    assert out["after_write"] == 9
