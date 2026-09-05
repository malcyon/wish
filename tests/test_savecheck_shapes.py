"""`--icon` compares a figure's glyphs against `CHARPIC00`, not against `$FF`.

`#184 (A converted combat icon's colours are proven in the game and its
shapes are not)` proposed checking the top row of every party figure for
eight zero bytes and eight `$FF`s, on the grounds that `$20` and `$A0` are
the space and the reversed space.  That is true of the C64's ROM character
set and false of `CHARPIC00`, which is the charset a combat icon's screen
codes index: `$A0` there is the top of a figure's head.  So the comparison
these tests cover is against the bitmaps the icon's own codes name.

No emulator: the monitor is a fake, and the charset is built here rather than
read off a disk.
"""

import struct

import pytest
from conftest import load_tools_module

savecheck = load_tools_module("savecheck")


def banks_response(pairs):
    body = b""
    for name, bid in pairs:
        raw = name.encode("latin1")
        body += bytes([3 + len(raw)]) + struct.pack("<H", bid) \
            + bytes([len(raw)]) + raw
    return struct.pack("<H", len(pairs)) + body


class FakeScreen:
    def __init__(self, codes):
        self.codes = codes


class FakeMonitor:
    """Answers glyph reads out of `charset_at`, keyed by screen code."""

    def __init__(self, charset_at, colours):
        self.charset_at = charset_at
        self.colours = colours

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def command(self, cmd, body=b""):
        return banks_response([("default", 0), ("ram", 1)])

    def read(self, addr, length, bank=0, side_effects=0):
        # The registers a real fight shows: VIC bank 3 and character base
        # `$1000` within it, which is the `$D000` the ticket names.
        if addr == 0xD018:
            return bytes([0x04])
        if addr == 0xDD00:
            return bytes([0x00])
        if addr == 0xD800:
            return bytes(self.colours[:length])
        return self.charset_at.get(addr // 8, bytes(length))


class FakeSession:
    def __init__(self, codes, mon):
        self._screen = FakeScreen(codes)
        self._mon = mon

    def screen(self):
        return self._screen

    def mon(self, timeout=5):
        return self._mon


def charpic(mapping: dict[int, bytes]) -> bytes:
    """A `CHARPIC00`-shaped charset with `mapping`'s codes filled in."""
    out = bytearray(2030)
    for code, bits in mapping.items():
        out[code * 8:code * 8 + 8] = bits
    return bytes(out)


def floor_codes(blocks):
    codes = [0] * 1000
    for row, col, start in blocks:
        for dr in range(3):
            for dc in range(3):
                codes[(row + dr) * 40 + col + dc] = start + dr * 3 + dc
    return codes


def test_the_window_puts_a_square_where_the_run_saw_it():
    """The one geometry in here, and it is measured rather than derived.

    Six party members at `(26,11) (25,11) (27,12) (26,12) (24,12) (29,12)`
    with the camera at `23,8` drew at these rows and columns in the `#265`
    run's own log.  A wrong origin or a wrong step would attribute every
    figure to the character standing next to it, which is worse than not
    attributing them at all.
    """
    camera = (23, 8)
    seen = {(26, 11): (10, 10), (25, 11): (10, 7), (27, 12): (13, 13),
            (26, 12): (13, 10), (24, 12): (13, 4), (29, 12): (13, 19)}
    for (x, y), cell in seen.items():
        assert savecheck.where_drawn(x, y, camera) == cell


def test_a_figure_is_matched_to_the_slot_whose_codes_it_was_drawn_from():
    """Two characters, two different icons, one figure each.

    The engine hands each combatant its own run of nine sequential screen
    codes, so the codes on the floor are never the icon's; the bitmaps behind
    them are.  What proves the shape converted is that all nine agree with
    `CHARPIC00[code * 8]` for the nine codes that character's own slot holds.
    """
    charset = charpic({code: bytes([code]) * 8 for code in range(1, 60)})
    slots = [
        {"slot": 0, "occupied": True,
         "shape": bytes(range(1, 19)).hex(), "colours": bytes(18).hex()},
        {"slot": 1, "occupied": True,
         "shape": bytes(range(21, 39)).hex(), "colours": bytes(18).hex()},
    ]
    # The combat charset: slot 0's first pose copied to codes $5E-$66 and
    # slot 1's second pose to $70-$78, which is the renumbering the engine
    # does and the reason an icon's own codes appear nowhere on the floor.
    charset_at = {}
    for n, code in enumerate(range(1, 10)):
        charset_at[0xD000 // 8 + 0x5E + n] = bytes([code]) * 8
    for n, code in enumerate(range(30, 39)):
        charset_at[0xD000 // 8 + 0x70 + n] = bytes([code]) * 8

    sess = FakeSession(floor_codes([(1, 1, 0x5E), (4, 4, 0x70)]),
                       FakeMonitor(charset_at, bytes(1000)))
    found = savecheck.icon_evidence(
        sess, bytes(36), slots=slots, charset=charset,
        roll={"camera": [10, 10],
              "party": [{"index": 0, "name": "ONE", "x": 10, "y": 10,
                         "on_map": True, "slot": 0, "pose": 0},
                        {"index": 1, "name": "TWO", "x": 11, "y": 11,
                         "on_map": True, "slot": 1, "pose": 1}]})

    assert found["distinct_figures"] == 2
    first, second = found["figures"]
    assert (first["who"], first["best"], first["exact"]) \
        == ("ONE", 9, [(0, 0, "plain")])
    assert (second["who"], second["best"], second["exact"]) \
        == ("TWO", 9, [(1, 1, "plain")])


def test_a_figure_drawn_from_the_wrong_bitmaps_matches_nothing():
    """The failure this exists to catch: right colours, wrong shape.

    One byte of one glyph is changed, which is what "the engine drew a
    different figure" looks like from here -- and the whole point of `#184`
    is that the colour half cannot see it.
    """
    charset = charpic({code: bytes([code]) * 8 for code in range(1, 60)})
    slots = [{"slot": 0, "occupied": True,
              "shape": bytes(range(1, 19)).hex(), "colours": bytes(18).hex()}]
    charset_at = {0xD000 // 8 + 0x5E + n: bytes([code]) * 8
                  for n, code in enumerate(range(1, 10))}
    charset_at[0xD000 // 8 + 0x62] = bytes([0xEE]) * 8

    sess = FakeSession(floor_codes([(1, 1, 0x5E)]),
                       FakeMonitor(charset_at, bytes(1000)))
    found = savecheck.icon_evidence(sess, bytes(36), slots=slots,
                                    charset=charset)

    figure = found["figures"][0]
    assert figure["exact"] == []
    assert figure["best"] == 8


def test_the_charset_read_still_refuses_a_vice_with_no_ram_bank():
    """The `#265` guard survives the new arguments."""

    class NoRam(FakeMonitor):
        def command(self, cmd, body=b""):
            return banks_response([("default", 0), ("io", 3)])

    sess = FakeSession(floor_codes([(1, 1, 0x5E)]), NoRam({}, bytes(1000)))
    with pytest.raises(SystemExit) as refused:
        savecheck.icon_evidence(sess, bytes(36))
    assert "ram" in str(refused.value)


def test_a_figure_facing_the_other_way_is_the_same_nine_bitmaps_turned_over():
    """Pose byte 2 is a mirror of pose 0, not the icon's second nine codes.

    45 of 405 party-figure readings across one 80-turn fight had the position
    table's pose byte at 2, and all 45 were this transform of that
    character's own first pose, 9 of 9 cells. The width of a pixel is the
    part that is easy to get wrong: a cell whose colour byte has bit 3 set is
    multicolour and reverses in pairs, and one without it is hi-res and
    reverses bit by bit. Scoring every cell as multicolour reported 8 of 9
    for the one character whose icon has a hi-res cell -- which reads like a
    fault in the game and is a fault in the reader.
    """
    charset = charpic({code: bytes([code]) * 8 for code in range(1, 60)})
    # Cell 0 is hi-res (colour 0), the other eight multicolour (bit 3 set).
    colours = bytes([0x00] + [0x0E] * 8) + bytes(9)
    slots = [{"slot": 0, "occupied": True,
              "shape": bytes(range(1, 19)).hex(), "colours": colours.hex()}]
    want = [savecheck.glyph_of(charset, code) for code in range(1, 10)]
    turned = savecheck.mirrored(want, colours[:9])
    charset_at = {0xD000 // 8 + 0x5E + n: bits
                  for n, bits in enumerate(turned)}

    sess = FakeSession(floor_codes([(1, 1, 0x5E)]),
                       FakeMonitor(charset_at, bytes(1000)))
    found = savecheck.icon_evidence(sess, bytes(36), slots=slots,
                                    charset=charset)

    figure = found["figures"][0]
    assert figure["best"] == 9
    assert figure["exact"] == [(0, 0, "mirrored")]


def test_a_hi_res_cell_is_not_turned_over_in_pairs():
    """The reader's own bug, kept out by a test that names the two widths.

    `0x81` reversed bit by bit is `0x81`, and reversed in pixel pairs is
    `0x42`; a cell that is hi-res has to take the first.
    """
    hires = savecheck.mirrored([bytes([0x81]) * 8] + [bytes(8)] * 8,
                               bytes([0x00] + [0x0E] * 8))
    multi = savecheck.mirrored([bytes([0x81]) * 8] + [bytes(8)] * 8,
                               bytes([0x0E] * 9))
    assert hires[2] == bytes([0x81]) * 8
    assert multi[2] == bytes([0x42]) * 8
