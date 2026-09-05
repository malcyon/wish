"""`--icon`'s glyph read wants the RAM bank, not the default one (#265).

`icon_evidence` computes the combat character set's address as `$D000`, which
is RAM **under** the VIC's I/O registers -- so a read there through the
monitor's default bank answers the registers rather than the character data.
Two figures with genuinely different bitmaps read back as the same eighteen
bytes when the read goes through the wrong bank, which is exactly the
six-identical-figures symptom of `#130 (A converted DOS party arrives with six
identical combat figures, not its own)` whether or not the icons differ.

Nothing here needs an emulator: the monitor is a fake that hands back real
bitmaps on the bank named ``ram`` and register-mirror zeroes on every other
bank, the way VICE itself does at `$D000` (measured with
`tools/vicebankcheck.py`).
"""

import struct

import pytest
from conftest import load_tools_module

savecheck = load_tools_module("savecheck")
icon_evidence = savecheck.icon_evidence
CMD_BANKS = savecheck.CMD_BANKS


def banks_response(pairs: list[tuple[str, int]]) -> bytes:
    """The `MON_CMD_BANKS_AVAILABLE` wire format `bank_ids` parses."""
    body = b""
    for name, bid in pairs:
        raw = name.encode("latin1")
        n = len(raw)
        size = 3 + n
        body += bytes([size]) + struct.pack("<H", bid) + bytes([n]) + raw
    return struct.pack("<H", len(pairs)) + body


class FakeScreen:
    def __init__(self, codes):
        self.codes = codes


class FakeMonitor:
    """Answers `$D000`-based glyph reads differently by bank, like VICE does.

    `real` is what the bank named ``ram`` reads back; `wrong` is what every
    other bank reads -- the registers, mirrored here as the zero bytes VICE
    actually returns for both `$20` and `$A0` at `$D000` (`#265`'s own
    measurement: the space check passes by coincidence, the reversed-space
    check fails).
    """

    def __init__(self, ram_bank: int, real: dict, wrong: dict,
                 offer_ram: bool = True):
        self.ram_bank = ram_bank
        self.real = real
        self.wrong = wrong
        # An older VICE, or a build that names its banks differently. The
        # point of the flag is that `icon_evidence` must refuse rather than
        # read the registers again (#265).
        self.offer_ram = offer_ram

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def command(self, cmd, body=b""):
        assert cmd == CMD_BANKS
        pairs = [("default", 0), ("cpu", 0), ("io", 3), ("cart", 4)]
        if self.offer_ram:
            pairs.insert(2, ("ram", self.ram_bank))
        return banks_response(pairs)

    def read(self, addr, length, bank=0, side_effects=0):
        if addr == 0xD018:
            return bytes([0x00])
        if addr == 0xDD00:
            return bytes([0x03])
        if addr == 0xD800:
            return bytes(length)
        code = addr // 8
        source = self.real if bank == self.ram_bank else self.wrong
        return source.get(code, bytes(length))


class FakeSession:
    def __init__(self, codes, mon):
        self._screen = FakeScreen(codes)
        self._mon = mon

    def screen(self):
        return self._screen

    def mon(self, timeout=5):
        return self._mon


def floor_codes(blocks: list[tuple[int, int, int]]) -> list[int]:
    """A 1000-code floor with each figure placed as nine consecutive codes."""
    codes = [0] * 1000
    for row, col, start in blocks:
        for dr in range(3):
            for dc in range(3):
                codes[(row + dr) * 40 + col + dc] = start + dr * 3 + dc
    return codes


def figure(base: int) -> dict:
    """Nine distinct 8-byte bitmaps starting at screen code `base`.

    The composed icon's own top row is `$20 $A0 $20` -- blank, solid, blank --
    so the first two bitmaps are what the engine actually copies there.
    """
    return {
        base: bytes(8),
        base + 1: bytes([0xFF]) * 8,
        base + 2: bytes(8),
        **{base + n: bytes([(base + n) & 0xFF]) * 8 for n in range(3, 9)},
    }


def test_two_different_figures_read_as_two_once_the_ram_bank_is_used():
    figure_a, figure_b = figure(0x5E), figure(0x70)
    real = {**figure_a, **figure_b}
    wrong = {code: bytes(8) for code in real}  # what the default bank answers

    codes = floor_codes([(0, 0, 0x5E), (5, 5, 0x70)])
    sess = FakeSession(codes, FakeMonitor(ram_bank=1, real=real, wrong=wrong))

    found = icon_evidence(sess, bytes(36))

    assert found["blocks"] == 2
    assert found["top_row"][0][2] == [
        "0000000000000000", "ffffffffffffffff", "0000000000000000"]
    assert found["distinct_figures"] == 2


def test_a_vice_with_no_ram_bank_is_refused_rather_than_read_anyway():
    """No `ram` bank means no reading, because bank 0 is the bug (#265).

    An earlier version fell back to `bank_ids(m).get("ram", 0)`, and bank 0
    is `default` -- the one that answers the VIC's registers at `$D000`. So
    the fallback put the read straight back into the defect and reported
    `distinct_figures` 1 for every party with nothing to say it had. This
    calls the real `icon_evidence` against a monitor that offers every bank
    except `ram`, and it has to refuse.
    """
    figure_a, figure_b = figure(0x5E), figure(0x70)
    real = {**figure_a, **figure_b}
    wrong = {code: bytes(8) for code in real}

    codes = floor_codes([(0, 0, 0x5E), (5, 5, 0x70)])
    sess = FakeSession(codes, FakeMonitor(ram_bank=1, real=real, wrong=wrong,
                                          offer_ram=False))

    with pytest.raises(SystemExit) as refused:
        icon_evidence(sess, bytes(36))
    assert "ram" in str(refused.value)
