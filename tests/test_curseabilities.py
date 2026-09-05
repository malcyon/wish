"""#273 (A C64 Curse record cannot be read and written back, because
abilities_second is read as a list and written as a dict).

`goldbox/c64_codec.py`'s reader built `abilities_second` as `list(...)` --
seven raw bytes with no name attached -- and the writer, at the
`shape.second_abilities` branch, calls `.get(n, 0)` on it expecting the dict
`goldbox/neutral.py`'s vocabulary describes: ability name -> the second copy
of that score. Reading a Curse record and writing it straight back raised
`AttributeError: 'list' object has no attribute 'get'` before it reached a
single byte of output.

None of this needs a save on disk: the record here is built from zeroes with
one field changed, which is what makes it run with no game disks present.
"""

from __future__ import annotations

from goldbox import c64_codec, games, neutral
from goldbox.record import CharacterRecord

CURSE = games.CURSE_OF_THE_AZURE_BONDS

#: Seven distinct bytes, so a scrambled order would fail rather than agree by
#: coincidence with a symmetrical one.
SEVEN_SCORES = bytes((18, 15, 9, 13, 16, 11, 76))


def _curse_record(second: bytes = SEVEN_SCORES) -> CharacterRecord:
    rec = CharacterRecord(bytes(CharacterRecord.SIZE))
    rec.set_raw("abilities_second", second)
    return rec


def test_a_curse_second_ability_array_reads_as_the_neutral_dict():
    """The vocabulary in `goldbox/neutral.py` calls `abilities_second` an
    ability name -> score mapping, keyed in `neutral.ABILITIES` order -- the
    same dict `goldbox/dos.py`'s `to_neutral` builds for Curse."""
    out = c64_codec.read(_curse_record(), game=CURSE)
    assert out.get("abilities_second") == dict(
        zip(neutral.ABILITIES, SEVEN_SCORES))


def test_a_curse_second_ability_array_round_trips():
    """Read a Curse record and write it straight back: the seven bytes at
    0x065-0x06B come back byte for byte. Fails today with `AttributeError:
    'list' object has no attribute 'get'`; passes once the reader keys the
    dict the writer expects."""
    out = c64_codec.read(_curse_record(), game=CURSE)
    written, report = c64_codec.write(out)
    assert written.get_raw("abilities_second") == SEVEN_SCORES
    assert "abilities_second" in report.sources[0x065]
