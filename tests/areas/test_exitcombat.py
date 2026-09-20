"""Which exits can start a fight, in the checked-in table and as the game's own
scripts say.

`automap.fasttravel.choose_door` skips a route marked `combat`, so a stale flag
would send a party through a fight or refuse a door that is safe.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from gamedata import needs_disks  # noqa: E402

from automap import fasttravel as F  # noqa: E402
from tools.generate import genexits as G  # noqa: E402


def test_render_marks_only_the_combat_rows():
    text = G.render({(7, 0): (1, (3, 8)), (7, 5): (0, (5, 7))},
                    combat={(7, 0)})
    assert "(7, 0): ExitRoute(1, (3, 8), combat=True)," in text
    assert "(7, 5): ExitRoute(0, (5, 7))," in text


@needs_disks
def test_the_committed_combat_flags_match_a_fresh_generation():
    rows, _skipped, combat = G.build_with_combat()
    committed = {key for key, route in F.EXIT_ROUTES.items() if route.combat}
    assert committed == {key for key in combat if key in rows}, (
        "automap/fasttravel.py's combat flags are stale -- rerun "
        "tools/generate/genexits.py and paste its output in")
    assert (7, 0) in committed          # the endgame fight
