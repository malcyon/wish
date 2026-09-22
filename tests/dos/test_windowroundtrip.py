"""`field_83_87`'s whole run survives a DOS render's own round trip (#614).

`goldbox.dos_codec.to_neutral` hangs a DOS source's own window on the neutral
record (`set_window_source`) and `write` puts it back unchanged
(`window_source(char) is not None`) rather than the writer's constant --
except for the control byte and the treasure share, which `write` always
re-derives from the neutral `npc`/`npc_control_byte`/`treasure_share` fields.
So a round trip that starts from a record whose control byte and share agree
with those fields proves every byte of the window comes back, not only the
fourth one `tests/records/test_windowfourthclass.py` already covers.

Built from `goldbox/dos_port.py`'s own field table, exactly as
`tests/records/test_dualclass_dos.py`'s `dos_record` does: no game data, runs
everywhere.
"""
from __future__ import annotations

import pytest

from goldbox import dos_codec, dos_port

POOL_OF_RADIANCE = dos_port.POOL_OF_RADIANCE
CURSE = dos_port.CURSE_OF_THE_AZURE_BONDS
SILVER_BLADES = dos_port.SECRET_OF_THE_SILVER_BLADES


def _dos_record(shape: dos_port.DosDeltas, **values) -> bytes:
    """A record of the given shape with the named fields set."""
    rec = bytearray(shape.record_size)
    table = dos_port.FIELDS_BY_NAME_FOR[shape.key]
    for name, value in values.items():
        f = table[name]
        raw = bytes([value] * f.size) if isinstance(value, int) else value
        assert len(raw) == f.size, name
        rec[f.span] = raw
    return bytes(rec)


@pytest.mark.parametrize("shape,window", (
    (POOL_OF_RADIANCE, b"\x11\x80\x03\x22\x33"),
    (CURSE, b"\x11\x80\x03\x22\x33"),
    (SILVER_BLADES, b"\x80\x03\x22\x33"),
))
def test_the_whole_window_survives_a_dos_round_trip(shape, window):
    """The control byte (index 0 or 1) is `0x80` -- npc, no morale bits set
    -- and the share (the byte after it) is `3`, so the neutral fields
    `write` re-derives them from agree with what the window itself holds and
    do not mask a mismatch elsewhere in the run."""
    f83 = dos_port.FIELDS_BY_NAME_FOR[shape.key]["field_83_87"]
    rec = bytearray(_dos_record(shape))
    rec[f83.span] = window
    char = dos_codec.to_neutral(
        dos_codec.DosCharacter(bytes(rec), deltas=shape))
    assert dos_codec.window_source(char) == window

    out, _itm, _spc, _rep = dos_codec.write(char, deltas=shape)
    assert out[f83.span] == window
