"""Neutral characters whose packs the C64 cannot hold, composed from the item
format, and the `PackOverflow` the writer reports for them (#432).

Nothing here is read from a game file: an item is sixteen bytes in the C64
layout, a scroll's spells are bytes 13-15, and a joined scroll is a
`ScrollBundle` over a run of scrolls in the inventory.
"""
from __future__ import annotations

import pathlib

from goldbox import c64_codec, c64_port, dos_codec, dos_port
from goldbox.layout import Confidence
from goldbox.neutral import NeutralCharacter, ScrollBundle
from support.neutralrecords import _filled

GAME = c64_port.SECRET_OF_THE_SILVER_BLADES
SCROLL = dos_codec.SCROLL_TYPES[0]


def plain(n: int) -> bytes:
    """A 16-byte item that is not a scroll; `n` picks its type."""
    return bytes([10 + n, 0, 0, 1, 0, 0, 0, 0, 5, 0, 0, 0, 0, 0, 0, 0])


def scroll(*spells: int) -> bytes:
    """A 16-byte scroll of `spells` (up to three ids, in bytes 13-15)."""
    ids = (list(spells) + [0, 0, 0])[:3]
    return bytes([SCROLL, 0, 2, 3, 0, 0, 0, 0, 10, 0, 0, 0, 0, *ids])


def head(count: int) -> bytes:
    """The item a JOIN of `count` scrolls makes."""
    return bytes([dos_codec.SCROLL_BUNDLE_TYPE, 0x27, count, 0x4D, 0, 0, 0, 0,
                  count, 0, count, 0, 0, 0, 0, 0])


def member(name: str, plain_items: int, *scrolls: bytes,
           loose: int = 0) -> NeutralCharacter:
    """`plain_items` items, then a joined scroll of `scrolls` (if any), then
    `loose` more items, as the neutral record holds them."""
    char = NeutralCharacter("test", source="made up", game=GAME)
    char.set("name", name, "made up")
    inventory = ([plain(n) for n in range(plain_items)] + list(scrolls)
                 + [plain(50 + n) for n in range(loose)])
    char.set("inventory", inventory, "made up")
    bundles = ((ScrollBundle(plain_items, len(scrolls), head(len(scrolls))),)
               if scrolls else ())
    char.set("scroll_bundles", bundles, "made up")
    return char


def party() -> list[NeutralCharacter]:
    """Member 0 needs 17 slots, member 1 fits in 16, member 2 needs 18."""
    return [
        member("ALPHA", 15, scroll(5), scroll(6, 7)),
        member("BETA", 14, scroll(5), scroll(6)),
        member("GAMMA", 14, scroll(5), scroll(6), scroll(7), scroll(5)),
    ]


def overflow(chars=None):
    """What `write_c64_save` reports for `chars` (the party above by
    default): one entry for each member who does not fit."""
    return dos_codec.pack_overflow(chars or party())


def crowd_dos_member(folder, number: int, plain_items: int, *scrolls: bytes,
                     name: str = "CROWDED", loose: int = 0) -> None:
    """Replace `CHRDATA<number>` in a DOS Silver Blades save folder (slot A)
    with a character holding `member`'s pack, so the party opened from it
    overflows the C64's sixteen slots the same way."""
    deltas = dos_port.SECRET_OF_THE_SILVER_BLADES
    pack = member(name, plain_items, *scrolls, loose=loose)
    char = _filled(GAME)
    char.set("name", name, "made up", Confidence.CONFIRMED,
             c64_codec.Provenance.RESHAPED)
    char.set("inventory", pack.get("inventory"), "made up")
    char.set("scroll_bundles", pack.get("scroll_bundles"), "made up")
    record, itm, spc, _report = dos_codec.write(char, deltas=deltas)
    folder = pathlib.Path(folder)
    (folder / f"CHRDATA{number}.SAV").write_bytes(record)
    (folder / f"CHRDATA{number}{deltas.item_suffix}").write_bytes(itm)
    (folder / f"CHRDATA{number}{deltas.effect_suffix}").write_bytes(spc)
