"""The NPC window's unnamed bytes cross the neutral record on the later Amiga titles.

`field_83_87` holds the control byte and the treasure share, which are neutral
fields, and bytes no engine reads, which are not: three of five in Curse, two of
four in Silver Blades.  `goldbox.dos_codec.set_window_source` is how a reader
hands those to `goldbox.dos_codec.write`, and `goldbox.amiga_later.
to_neutral_later` must call it or an Amiga Curse or Silver Blades character
arrives, on Amiga or on DOS, with the writer's constant where its own bytes were.

The specimens are the 21 records on the game's own disks and skip without them;
the built records need no disk.
"""

from __future__ import annotations

import pytest
from support.amigarecords import curse_characters, silver_blades_characters

from goldbox import amiga_later, amiga_port, dos_codec

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

SHAPES = (amiga_port.CURSE_DELTAS, amiga_port.SILVER_BLADES_DELTAS)


def _window_at(shape: amiga_port.AmigaDeltas) -> tuple[int, int, list[int]]:
    """The window's Amiga offset, its size, and its indices no neutral field names."""
    f = shape.dos_field("field_83_87")
    control = 1 if f.size == 5 else 0
    return (shape.offset(f.offset), f.size,
            [i for i in range(f.size) if i not in (control, control + 1)])


def _planted(char: amiga_later.AmigaCharacter) -> tuple[amiga_later.AmigaCharacter,
                                                      bytes]:
    """`char` with a non-zero byte in each unnamed window byte, and the window it holds."""
    at, size, unnamed = _window_at(char.deltas)
    raw = bytearray(char.raw)
    for n, i in enumerate(unnamed):
        raw[at + i] = 0x5A + n
    planted = amiga_later.AmigaCharacter.from_bytes(
        bytes(raw), char.deltas, char.source, char.items, char.effects)
    return planted, bytes(raw[at:at + size])


def _built(shape: amiga_port.AmigaDeltas) -> amiga_later.AmigaCharacter:
    raw = bytearray(shape.record_size)
    raw[:6] = b"TESTER"
    return amiga_later.AmigaCharacter.from_bytes(bytes(raw), shape)


def _check(label: str, char: amiga_later.AmigaCharacter) -> None:
    planted, window = _planted(char)
    shape = planted.deltas
    at, size, unnamed = _window_at(shape)
    neutral = amiga_later.to_neutral_later(planted)
    assert dos_codec.window_source(neutral) == window, label

    amiga, _ = amiga_later.write_later(neutral, deltas=shape)
    assert amiga.raw[at:at + size] == window, f"{label}: Amiga to Amiga"

    dos, _itm, _spc, _rep = dos_codec.write(neutral, deltas=shape.dos)
    f = shape.dos_field("field_83_87")
    assert dos[f.offset:f.end] == window, f"{label}: Amiga to DOS"
    assert all(window[i] for i in unnamed), label


@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: s.key)
def test_a_built_record_keeps_its_unnamed_window_bytes(shape):
    _check(shape.key, _built(shape))


def test_every_curse_record_keeps_its_unnamed_window_bytes():
    for n, char in enumerate(curse_characters()):
        _check(f"Curse #{n} {char.name}", char)


def test_every_silver_blades_record_keeps_its_unnamed_window_bytes():
    for n, char in enumerate(silver_blades_characters()):
        _check(f"Silver Blades #{n} {char.name}", char)
