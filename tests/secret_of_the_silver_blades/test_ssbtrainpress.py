from __future__ import annotations

"""What `tools/secret_of_the_silver_blades/ssbtrain.py press` writes into the running game.

A record page has `hp_max` at `0x076` and no current hit points: the number
the party list prints, and the one `SAVE CURRENT GAME` writes into the save's
roster block, lives in a separate page at `$6700 + slot * $20 + $19`. A training
press raises both, so `press` must poke the party list's copy to the record's
own `hp_max`, or a save taken between presses holds more current hit points
than the maximum.

The command port is faked here: every `poke` lands in a dictionary and every
`peek` reads back out of it, which is enough for `press`, since it only reads
what it wrote. No emulator, no game bytes; the record is built in the test.
"""

import pytest

from goldbox.savegame import ROSTER_HP_CURRENT, ROSTER_STRIDE
from tools.secret_of_the_silver_blades import ssbtrain


def _record(hp_max: int) -> bytes:
    """A 256-byte record page with `hp_max` at `0x076` and nothing else."""
    body = bytearray(256)
    body[0:8] = b"TESTER\0\0"
    body[ssbtrain.HP_MAX:ssbtrain.HP_MAX + 2] = hp_max.to_bytes(2, "little")
    return bytes(body)


@pytest.fixture
def fake_port(monkeypatch):
    """`ssbtrain.cmd` against a dictionary of bytes; returns (mem, calls)."""
    mem: dict[int, int] = {}
    calls: list[tuple[str, ...]] = []

    def cmd(port, *words):
        words = tuple(str(w) for w in words)
        calls.append(words)
        if words[0] == "poke":
            addr = int(words[1], 16)
            for i, b in enumerate(bytes.fromhex("".join(words[2:]))):
                mem[addr + i] = b
            return ""
        if words[0] == "peek":
            addr, n = int(words[1], 16), int(words[2])
            return bytes(mem.get(addr + i, 0) for i in range(n)).hex()
        return ""

    monkeypatch.setattr(ssbtrain, "cmd", cmd)
    monkeypatch.setattr(ssbtrain.time, "sleep", lambda s: None)
    return mem, calls


def _press(tmp_path, slot: int, hp_max: int) -> int:
    page = tmp_path / "rec.hex"
    page.write_text(_record(hp_max).hex())
    return ssbtrain.main(["press", "--slot", str(slot), "--name", "TESTER",
                          "--record", str(page),
                          "--out", str(tmp_path / "press")])


def test_press_writes_the_party_list_copy_of_the_current_hit_points(
        tmp_path, fake_port):
    """Without this the party list keeps the last press's total."""
    mem, _ = fake_port
    assert _press(tmp_path, 0, 35) == 0
    at = ssbtrain.PARTY_CACHE + ROSTER_HP_CURRENT
    assert mem[at] == 35
    assert mem[ssbtrain.ROSTER + ssbtrain.HP_MAX] == 35


def test_the_party_list_copy_moves_by_the_slot_stride(tmp_path, fake_port):
    """Slot 5 is `$20` further on five times over, and slot 0 is untouched."""
    mem, _ = fake_port
    assert _press(tmp_path, 5, 102) == 0
    at = ssbtrain.PARTY_CACHE + 5 * ROSTER_STRIDE + ROSTER_HP_CURRENT
    assert mem[at] == 102
    assert ssbtrain.PARTY_CACHE + ROSTER_HP_CURRENT not in mem


def test_press_fails_when_the_party_list_poke_does_not_land(
        tmp_path, fake_port, monkeypatch):
    """A dropped poke must stop the press rather than save a gap."""
    real = ssbtrain.cmd
    at = ssbtrain.PARTY_CACHE + ROSTER_HP_CURRENT

    def dropping(port, *words):
        if words[0] == "poke" and int(str(words[1]), 16) == at:
            return ""
        return real(port, *words)

    monkeypatch.setattr(ssbtrain, "cmd", dropping)
    with pytest.raises(SystemExit, match="party list did not take"):
        _press(tmp_path, 0, 35)


def test_press_refuses_an_hp_max_the_party_list_byte_cannot_hold(
        tmp_path, fake_port):
    """The party list's byte is one wide, so 300 is refused rather than clamped."""
    mem, _ = fake_port
    with pytest.raises(SystemExit, match="255"):
        _press(tmp_path, 0, 300)
    assert not mem
