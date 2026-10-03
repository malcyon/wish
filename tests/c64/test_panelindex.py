"""`route_pool.panel_index` and `Run.panel_index` choose a party line by number
or by the name column, never by text in the AC and HP columns."""

import pytest
from conftest import load_tools_module

S = load_tools_module("session")
from tools.c64 import route_pool  # noqa: E402

#: Names with the AC and HP columns the panel draws after them.  BROTHER SEAN
#: has a 2 in both, so a digit searched for in the whole row finds him.
PANEL = [("BAKSHI", "5 31"), ("BROTHER SEAN", "2 22"),
         ("BRUTUS", "7 40"), ("BRUTUS THE LESS", "3 12")]
HEADER = "NAME            AC HP"


class Screen:
    def __init__(self, panel):
        self.lines = {2: " " * S.PARTY_COLUMN + HEADER}
        for i, (name, stats) in enumerate(panel):
            self.lines[4 + i] = " " * S.PARTY_COLUMN + f"{name[:16]:<16}{stats}"

    def row(self, r):
        return self.lines.get(r, "").ljust(40)


class Sess:
    def __init__(self, panel=PANEL):
        self.s = Screen(panel)

    def screen(self):
        return self.s

    def party_rows(self, s):
        return [r for r in sorted(s.lines) if r > 2]


def names_of(sess):
    s = sess.screen()
    return route_pool.panel_names(s, sess.party_rows(s))


def test_a_number_picks_the_line_not_a_stat_column():
    sess = Sess()
    assert route_pool.panel_index(sess, "2") == 1
    assert route_pool.panel_index(sess, "1") == 0
    assert route_pool.panel_index(sess, "4") == 3


def test_a_name_matches_only_its_own_row():
    sess = Sess()
    assert route_pool.panel_index(sess, "BAKSHI") == 0
    assert route_pool.panel_index(sess, "BROTHER SEAN") == 1


def test_a_part_of_a_name_is_not_a_match():
    with pytest.raises(route_pool.PanelError, match="is not on the party panel"):
        route_pool.panel_index(Sess(), "SEAN")


def test_a_prefix_of_two_names_is_not_a_match():
    with pytest.raises(route_pool.PanelError, match="not on the party panel"):
        route_pool.panel_index(Sess(), "BRO")


def test_an_exact_name_that_is_also_a_prefix_picks_itself():
    assert route_pool.panel_index(Sess(), "BRUTUS") == 2


def test_a_name_the_panel_cut_still_matches():
    sess = Sess([("MALCYON THE VERY LONG", "5 31"), ("MALCYON THE VERY SHORT", "5 31")])
    # Both cut to the same 16 characters: ambiguous, said in a sentence.
    with pytest.raises(route_pool.PanelError, match="more than one party line"):
        route_pool.panel_index(sess, "MALCYON THE VERY LONG")
    sess = Sess([("MALCYON THE VERY LONG", "5 31"), ("BAKSHI", "5 31")])
    assert route_pool.panel_index(sess, "MALCYON THE VERY LONG") == 0


def test_the_acceptance_driver_picks_by_the_name_column_too():
    from tools.c64 import acceptance as A

    class Fake(Sess):
        def stable_party_rows(self):
            return self.party_rows(self.s)

    run = A.PoolRun.__new__(A.PoolRun)
    run.sess = Fake()
    run.fail = lambda tag, why: A.StepFailed(why)
    assert run.panel_index("4") == 3
    assert run.panel_index("BRUTUS") == 2
    with pytest.raises(A.StepFailed, match="not on the party panel"):
        run.panel_index("BRO")
