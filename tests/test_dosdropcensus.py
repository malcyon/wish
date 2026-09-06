"""`tools/dosdropcensus.py`'s `0x0E6` column (#284).

`goldbox/dos_layout.py` renamed that byte from `gap_0e6` to `former_level` as
part of `#256 (The neutral record has nowhere to put a dual-classed
character's former levels)`, and `tools/dosdropcensus.py` kept the old name in
its lookup, so the column silently degraded to `-` for every record.
"""

from __future__ import annotations

import pathlib

from goldbox import dos_layout
from tools import dosdropcensus, dostailcensus

CURSE = dos_layout.CURSE_OF_THE_AZURE_BONDS
POR = dos_layout.POOL_OF_RADIANCE


def record(shape, **values) -> bytes:
    """A record in `shape` with the named fields set, built from the table
    rather than sliced out of anybody's save."""
    rec = bytearray(shape.record_size)
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
    for name, value in values.items():
        f = table[name]
        raw = bytes([value] * f.size) if isinstance(value, int) else value
        assert len(raw) == f.size, name
        rec[f.span] = raw
    return bytes(rec)


def specimen(shape, **values) -> dostailcensus.Specimen:
    data = record(shape, **values)
    return dostailcensus.Specimen(pathlib.Path("synthetic-record"), data)


def test_the_0x0e6_column_reports_a_non_zero_former_level():
    spec = specimen(CURSE, former_level=7)
    assert dosdropcensus.columns(spec)["0x0E6"] == "07"


def test_the_0x0e6_column_reports_a_dash_when_the_shape_has_no_such_field():
    """Pool of Radiance has no `former_level` field at all."""
    assert "former_level" not in dos_layout.FIELDS_BY_NAME_FOR[POR.key]
    spec = specimen(POR)
    assert dosdropcensus.columns(spec)["0x0E6"] == "-"
