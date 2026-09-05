"""`tools/exitroute.py`'s route printing, on statements built here and on the
two exits `#207 (Run an exit's own handler before Fast Travel warps out)`
turns on.

The classifier is `marker()`, which is deliberately thin: it re-uses
`eclexitkinds.py`'s own opcode sets so the two tools cannot drift into
disagreeing about what a player would notice. So the tests worth having are
that each set is actually consulted, that a `SAVE` is read for its
*destination* rather than its value, and -- disk-backed -- that the two
routes the issue's argument rests on still come out with the markers the
issue quotes.

`ECL07 $A904` is the one that would cost somebody a day if it silently
stopped saying `COMBAT`: its last block is six `SAVE`s and a `NEWECL 0`, and
the whole reason Fast Travel cannot run every handler blindly is what sits
above them.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tests.gamedata import needs_disks  # noqa: E402
from tools import eclwalk as W  # noqa: E402
from tools import exitroute as R  # noqa: E402


def statement(op, operands=()):
    return W.Statement(0, 1, op, list(operands))


IMMEDIATE, ADDRESS = 0x00, 0x02


# ---------------------------------------------------------------------------
# marker() -- what a player would notice, one opcode at a time
# ---------------------------------------------------------------------------

def test_a_menu_opcode_is_marked_menu():
    for op in sorted(R.K.MENUS):
        assert R.marker(statement(op)) == "menu", f"opcode ${op:02X}"


def test_a_text_opcode_is_marked_text():
    for op in sorted(R.K.TEXT):
        assert R.marker(statement(op)) == "text", f"opcode ${op:02X}"


def test_loadchar_and_combat_and_the_exit_itself_are_marked():
    assert R.marker(statement(R.K.LOADCHAR)) == "loadchar"
    assert R.marker(statement(0x24)) == "COMBAT"
    assert R.marker(statement(W.NEWECL, [(IMMEDIATE, 27)])) == "exit"


def test_a_save_is_read_for_its_destination_not_its_value():
    # SAVE 1, [$C04B] writes the party's x; SAVE 0xC04B, [$4A00] does not.
    position = statement(R.K.SAVE, [(IMMEDIATE, 1), (ADDRESS, 0xC04B)])
    assert R.marker(position) == "position"
    value = statement(R.K.SAVE, [(IMMEDIATE, 0xC04B), (ADDRESS, 0x4A00)])
    assert R.marker(value) == ""


def test_a_quest_flag_and_a_membership_write_are_told_apart():
    flag = statement(R.K.SAVE, [(IMMEDIATE, 1), (ADDRESS, 0x4AC6)])
    assert R.marker(flag) == "flag"
    member = statement(R.K.SAVE, [(IMMEDIATE, 0), (ADDRESS, 0x6B00)])
    assert R.marker(member) == "membership"


def test_a_save_whose_destination_is_an_immediate_is_not_a_write_we_can_name():
    # Both operands immediate: there is no address to classify.
    assert R.marker(statement(R.K.SAVE, [(IMMEDIATE, 0), (IMMEDIATE, 3)])) == ""


def test_an_unremarkable_opcode_gets_no_marker():
    assert R.marker(statement(W.GOTO, [(ADDRESS, 0x9900)])) == ""


# ---------------------------------------------------------------------------
# The two routes the issue's argument rests on
# ---------------------------------------------------------------------------

@needs_disks
def test_the_kobold_caves_exit_still_drops_a_character_on_its_route(capsys):
    assert R.report(W.Machine(), "ECL0D", "9A9D") == 0
    out = capsys.readouterr().out
    assert "membership" in out, "the SAVE 0, [$6B00] is what takes Fatima out"
    assert "loadchar" in out, "and the LOADCHAR is what writes the slot back"
    assert "$9A9D  NEWECL 27" in out


@needs_disks
def test_the_inner_tower_exit_still_fights_tyranthraxus_on_its_route(capsys):
    assert R.report(W.Machine(), "ECL07", "A904") == 0
    out = capsys.readouterr().out
    # The statement's own name is COMBAT and so is its marker, so the line
    # carries the word twice.  Asserting only that COMBAT appears somewhere
    # passed with `marker()` gutted, which is the failure this checks for.
    marked = [ln for ln in out.splitlines() if ln.count("COMBAT") == 2]
    assert marked, \
        "running this handler would put the party in the endgame battle"


@needs_disks
def test_an_address_that_is_not_an_exit_is_refused(capsys):
    assert R.report(W.Machine(), "ECL0D", "1234") == 1
    assert "no NEWECL" in capsys.readouterr().err


@needs_disks
def test_a_script_that_is_not_on_the_disks_is_refused(capsys):
    assert R.report(W.Machine(), "ECL99", None) == 1
    assert "not on the disks" in capsys.readouterr().err
