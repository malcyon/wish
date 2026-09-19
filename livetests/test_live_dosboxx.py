"""The DOSBox-X debugger harness, booted for real."""

import shutil
from pathlib import Path

import pytest
from needs import fail_if_save_missing, find_game_or_fail

from tools.dos import dosboxx

pytestmark = pytest.mark.xdist_group(name="emulator-pool")


def test_the_harness_reproduces_the_clock_tick_docs_142_recorded():
    """Every number here is one `docs/142-dosbox-x-debugger.md` already carries.

    The base address is deliberately not asserted: it is where DOS happened to
    load that build with that config, not a finding.  What is asserted is the
    recipe -- the array is found, the live byte agrees with the save, the
    spurious `00 ->` hit is absorbed, and the real tick is caught.
    """
    if not Path(dosboxx.DOSBOXX).is_file() and shutil.which(dosboxx.DOSBOXX) is None:
        pytest.fail(f"the DOSBox-X executable {dosboxx.DOSBOXX} is not installed")
    reason = dosboxx.unavailable()
    if reason:
        pytest.fail(f"DOSBox-X with the debugger is not usable: {reason}")
    fail_if_save_missing(find_game_or_fail("POOLRAD"), "J")

    out = dosboxx.clock_demo("J")
    assert out["attached"]
    assert out["dumped"] == 0x100000
    assert out["votes"] > 50
    assert out["live"] == out["in_save"]
    assert out["absorbed"].startswith("Break(") and "old=0," in out["absorbed"]
    old, new = out["tick"].split()[1], out["tick"].split()[3]
    assert int(new, 16) == int(old, 16) + 1
    assert out["after_write"] == 9
