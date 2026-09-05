"""`tools/iconswing.py`: the icon's second pose, counted and compared.

`#184 (A converted combat icon's colours are proven in the game and its
shapes are not)` was answered for nine of an icon's eighteen screen codes by
reading the combat floor.  The other nine are never on the floor when the
game stops to ask for a command, so the tool these tests cover counts the
engine's own reads instead -- and reads the table `COM.PREP` expands both
poses into, which is where the second nine end up.

No emulator: the monitor is a fake and the charset is built here.
"""

import struct

from conftest import load_tools_module

iconswing = load_tools_module("iconswing")


def charpic(mapping: dict[int, bytes]) -> bytes:
    """A `CHARPIC00`-shaped charset with `mapping`'s codes filled in."""
    out = bytearray(2030)
    for code, bits in mapping.items():
        out[code * 8:code * 8 + 8] = bits
    return bytes(out)


class FakeMonitor:
    def __init__(self, blob=b"", checkpoint_hits=0):
        self.blob = blob
        self.checkpoint_hits = checkpoint_hits

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr, length, bank=0, side_effects=0):
        start = addr - iconswing.EXPANDED
        return bytes(self.blob[start:start + length])

    def command(self, cmd, body=b""):
        # `MON_RESPONSE_CHECKPOINT_INFO`: number, hit, start, end, four flag
        # bytes, then the hit count at offset 13.
        return (struct.pack("<I", 7) + bytes([1]) + struct.pack("<HH", 0, 0)
                + bytes([1, 1, 1, 0])
                + struct.pack("<II", self.checkpoint_hits, 0) + bytes([0, 0]))


class FakeSession:
    def __init__(self, mon):
        self._mon = mon

    def mon(self, timeout=5):
        return self._mon


def test_a_watch_is_set_on_both_poses_of_every_occupied_slot():
    """The addresses are the ticket's arithmetic, written out.

    An icon is 36 bytes at `$4BE0 + slot * 36`, eighteen codes then eighteen
    colours, so the second pose's codes start nine bytes in.  Getting this
    wrong by nine would count the first pose's reads and report them as the
    second's, which is the failure the whole measurement exists to avoid.
    """
    slots = [{"slot": n, "occupied": n < 2} for n in range(8)]
    watch = iconswing.windows(slots, control=0)
    icons = [w for w in watch if w["kind"] == "icon"]
    assert [(w["slot"], w["pose"], w["start"], w["end"]) for w in icons] == [
        (0, 0, 0x4BE0, 0x4BE8), (0, 1, 0x4BE9, 0x4BF1),
        (1, 0, 0x4C04, 0x4C0C), (1, 1, 0x4C0D, 0x4C15)]


def test_only_the_named_slot_gets_its_first_pose_bitmaps_watched():
    """Watching all six would stop the machine on every redraw.

    The second pose is watched for everybody, because that is the question;
    the first is watched once, as the control that proves the instrument
    fires at all.
    """
    slots = [{"slot": n, "occupied": True} for n in range(6)]
    watch = [w for w in iconswing.windows(slots, control=3)
             if w["kind"] == "glyphs"]
    assert sorted((w["slot"], w["pose"]) for w in watch) == [
        (0, 1), (1, 1), (2, 1), (3, 0), (3, 1), (4, 1), (5, 1)]
    first = next(w for w in watch if w == watch[0])
    assert first["end"] - first["start"] == 71     # nine glyphs of eight


def test_the_expanded_blocks_are_162_bytes_apart():
    """`COM.PREP` writes 18 glyphs of 8 bytes then 18 colour bytes a slot."""
    slots = [{"slot": n, "occupied": True} for n in range(3)]
    watch = [w for w in iconswing.windows(slots, control=99)
             if w["kind"] == "glyphs"]
    starts = [w["start"] for w in watch]
    assert starts == [iconswing.EXPANDED + n * 162 + 72 for n in range(3)]


def test_a_checkpoint_reports_its_hit_count():
    hits = iconswing.checkpoint_hits(FakeMonitor(checkpoint_hits=768), 7)
    assert hits == 768


def test_the_expanded_table_is_scored_against_both_poses_separately():
    """A slot whose second nine were built from the wrong codes scores low.

    Slot 0's table is built correctly.  Slot 1's second nine are filled with
    the *first* nine's bitmaps, which is exactly what a conversion writing
    eighteen codes and the engine reading nine would look like -- and the
    reading has to say so rather than averaging it away.
    """
    charset = charpic({code: bytes([code]) * 8 for code in range(1, 40)})
    slots = [
        {"slot": 0, "occupied": True,
         "shape": bytes(range(1, 19)).hex(), "colours": bytes(range(18)).hex()},
        {"slot": 1, "occupied": True,
         "shape": bytes(range(21, 39)).hex(), "colours": bytes(range(18)).hex()},
    ]
    blob = bytearray(162 * 8)
    for entry, wrong_second_pose in ((slots[0], False), (slots[1], True)):
        shape = bytes.fromhex(entry["shape"])
        base = entry["slot"] * 162
        for n in range(18):
            code = shape[n - 9] if wrong_second_pose and n >= 9 else shape[n]
            blob[base + n * 8:base + n * 8 + 8] = bytes([code]) * 8
        blob[base + 144:base + 162] = bytes.fromhex(entry["colours"])
    read = iconswing.expanded_reading(FakeSession(FakeMonitor(bytes(blob))),
                                      slots, charset)
    assert read["slots"][0] == {
        "slot": 0, "occupied": True, "pose0": 9, "pose1": 9, "colours": True,
        "first": (bytes([1]) * 8).hex(), "tenth": (bytes([10]) * 8).hex()}
    assert read["slots"][1]["pose0"] == 9
    assert read["slots"][1]["pose1"] == 0


def test_a_renumbered_icon_is_found_by_its_run_of_nine():
    """The editor hands out sequential codes exactly as a fight does.

    So the block to score is nine **consecutive** codes laid out three by
    three, and a 3x3 patch of anything else is not one.  Searching the screen
    for the icon's own codes instead finds nothing, which is what the first
    run of `--camp` reported.
    """
    rows = [bytearray([0x20] * 40) for _ in range(25)]
    for dr in range(3):
        for dc in range(3):
            rows[3 + dr][4 + dc] = 0x60 + dr * 3 + dc
    # A block of the same code repeated is not a run, and must not be found.
    for dr in range(3):
        for dc in range(3):
            rows[10 + dr][4 + dc] = 0x60
    found = iconswing.blocks_on([bytes(r) for r in rows])
    assert [(r, c) for r, c, _ in found] == [(3, 4)]
