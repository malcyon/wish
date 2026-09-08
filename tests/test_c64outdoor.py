"""`tools/c64outdoor.py`'s `outdoor_request`, offline (#369).

`outdoor_request` builds the shortest DOS buffer that says "outdoors, in
`area`, at `(x, y)`" and hands it to `goldbox.world_state.from_dos`, with no
emulator involved -- this is the whole test surface, since driving VICE is
the rest of the tool's job and not what #369 is about.

The bug: a buffer this short also matches `goldbox.dos.never_adventured`'s
"never set out" signature -- an all-zero staged area script -- so
`world_state.from_dos` substituted Pool of Radiance's own indoor start square
(area 0, `15,1`, indoors) rather than reading the three words the buffer
actually set. `outdoor_request` now stages the script buffer the way
`tests/test_dosconvert.py`'s `_stage_a_script` does, before setting them.
"""

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos  # noqa: E402
from tools import c64outdoor  # noqa: E402


def test_outdoor_request_reads_as_a_party_that_has_set_out():
    state = c64outdoor.outdoor_request(26, 7, 29)
    assert state.set_out is True


def test_outdoor_request_carries_the_requested_travel_window():
    state = c64outdoor.outdoor_request(26, 7, 29)
    assert state.area == 26
    assert state.outdoors is True
    assert state.travel == (7, 29)


def test_outdoor_requests_buffer_does_not_read_as_never_adventured():
    """The mechanism the bug report names directly: `dos.never_adventured`
    on the raw buffer, before `world_state.from_dos` ever substitutes
    anything."""
    import goldbox.dos_savegame as sg

    req = bytearray(sg.SAVGAM_SIZE)
    start, _ = sg.SAVE_POOL_OF_RADIANCE.script_buffer
    req[start] = 0x01
    sg.put_word(req, dos.LATER_BEGUN_WORD, 255)
    sg.put_word(req, sg.SCRIPT, 26)
    sg.put_word(req, sg.INDOORS, 0)
    sg.put_travel_square(req, 7, 29)
    assert not dos.never_adventured(bytes(req))
