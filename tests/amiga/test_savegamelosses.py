"""#619: a name a writer narrows must reach `report.losses`, all the way up
to the save-level report `new_savegame` hands back.

Before this fix, `new_savegame` copied `dropped` and `warnings` off each
character's own report and never `losses`, so a save's report always came
back with `losses == []` even when a character's name was cut, and
`editor.saveplan.losses` -- the guard `File > Convert...` reads -- saw
nothing to refuse.
"""

from __future__ import annotations

from support.amigarecords import sample

from editor import saveplan
from goldbox import amiga_savegame, areas, c64_save, dos_codec, world_state


def _bare_silver_blades_state() -> world_state.WorldState:
    """A minimal Secret of the Silver Blades state, built rather than read.

    Area 4 is Silver Blades' own `SILVER-{}`
    (`goldbox/areas.py::areas_for("Secret of the Silver Blades")`), and the
    title has no `ECL.GLB` to stage, so `new_savegame` takes no
    `ecl_glb` argument for it.
    """
    later_first, later_size = dos_codec.LATER_HEADER_COPIED
    header = {dos_codec.SAVE0_BASE + later_first + i: 0
              for i in range(later_size)}
    flags_width = c64_save.container_for(
        "secret-of-the-silver-blades").quest_flags[1]
    return world_state.WorldState(
        title="Secret of the Silver Blades", area=4,
        geo=areas.geo_number("GEO10"), x=0, y=0,
        facing=0, clock=(0,) * 6, wallset=(0, 0, 0),
        flags=(0,) * flags_width,
        scratch={addr: 0 for addr in dos_codec.SHARED_SCRATCH},
        outdoors=False, travel=(0, 0), set_out=True, header=header)


def test_a_name_cut_to_the_amiga_width_reaches_the_saves_own_losses():
    """A name past the destination's field width is a loss `new_savegame`
    must not drop on the way from a character's report to the save's."""
    state = _bare_silver_blades_state()
    party = [sample(name="A" * 20)]

    _built, report = amiga_savegame.new_savegame(state, party, "B")

    assert report.losses != []
    assert saveplan.losses(report) != []


def test_area_4_is_the_silver_blades_area_this_test_relies_on():
    """Pins the fixture's own premise, so a change to `areas.py` fails here
    rather than as a mystifying `AmigaSaveError` in the test above."""
    assert areas.area_in(4, "Secret of the Silver Blades") is not None
