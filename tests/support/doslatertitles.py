"""Helpers `test_doslatertitles` shares with the test files that reuse them."""
from __future__ import annotations

import pathlib

import pytest
from gamedata import specimen_root

from goldbox import c64_codec, dos_codec, dos_port, items
from goldbox.d64 import D64
from goldbox.savegame import load_save


def _mask(shape, original: bytes) -> set[int]:
    """The offsets the writer declares it does not take from the source, plus
    the name bytes past the count byte.

    Built from the writer's own tables and never from the diff, which is what
    `.claude/rules/conversions.md` requires: a new difference has to fail.
    The name padding is masked because the neutral record carries a *name* and
    not the bytes the engine left after it -- Curse's shipped TRAVIS has a
    space at the seventh byte over a count of six.
    """
    table = dos_port.FIELDS_BY_NAME_FOR[shape.key]
    out: set[int] = set()
    named = ([n for n, _ in dos_codec.WRITE_UNSOURCED + dos_codec.WRITE_UNSOURCED_LATER]
             + [n for n, _, _, _ in dos_codec.WRITE_DEFAULTS
                if n != "field_10c_10f"]
             + [n for n, _ in dos_codec.WRITE_DERIVED])
    for name in named:
        if name in table:
            out.update(range(table[name].offset, table[name].end))
    text = table["name_text"]
    out.update(range(text.offset + original[table["name_length"].offset],
                     text.end))
    return out


def _c64_disk(name: str):
    root = specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    found = [p for p in (root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64")]
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]


def _c64_party(path: pathlib.Path):
    disk = D64.open(str(path))
    game, sg0, sg1 = load_save(disk)
    out = []
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        out.append(c64_codec.read(slot.record, roster=block, inventory=inv,
                                  game=game, source=f"slot {slot.index}"))
    return game, out
