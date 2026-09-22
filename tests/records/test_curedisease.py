"""Where C64 Curse and Silver Blades keep a paladin's cure-disease uses.

Read off the player's own overlays at run time by `tools/c64/curedisease.py`;
each title skips cleanly without its disks. No game bytes are fixtures here.
"""

from __future__ import annotations

import pytest

from tools.c64 import curedisease

#: What the instruction read settles, one row a title.
EXPECTED = {
    "curse-of-the-azure-bonds": {
        "seed": 0x2550,
        "seed_callers": (0x0C1A, 0x1C5F, 0x20BF, 0x23DE),
        "full_count": 0x87EF,
        "gate": 0x46AB,
        "cure_decrement": 0x870F,
        "cure_guard": "uses were full",
        "lay_decrement": 0x873D,
        "expiry_dispatch": 0x14A9,
        "expiry_ids": 0x9953,
        "expiry_magnitude_gate": 0x14DB,
        # (effect id, duration, magnitude, add routine, reset at expiry)
        "cure": (141, 0xC7, 0xC7, 0x8156, 0x85BA),
        "lay": (140, 0xC1, 0xC1, 0x8156, 0x85B3),
        "writes": (("ECL65", 0x85B5, "STA", 0x13),
                   ("ECL65", 0x85BD, "STY", 0x12),
                   ("ECL65", 0x870F, "DEC", 0x12),
                   ("ECL65", 0x873D, "DEC", 0x13),
                   ("GEN", 0x2557, "STY", 0x13),
                   ("GEN", 0x2564, "STY", 0x12),
                   ("GEN", 0x2568, "STA", 0x12),
                   ("GEN", 0x256B, "STA", 0x13)),
    },
    "secret-of-the-silver-blades": {
        "seed": 0x0C69,
        "seed_callers": (0x0BEE, 0x156B, 0x1FC6, 0x212A),
        "full_count": 0x884E,
        "gate": 0x4383,
        "cure_decrement": 0x874B,
        "cure_guard": "no timer running",
        "lay_decrement": 0x8779,
        "expiry_dispatch": 0x12E2,
        "expiry_ids": 0x9496,
        "expiry_magnitude_gate": 0x1314,
        "cure": (110, 0xC7, 0xC7, 0x8156, 0x8657),
        "lay": (109, 0xC1, 0xC1, 0x8156, 0x8650),
        "writes": (("ECL65", 0x8652, "STA", 0x13),
                   ("ECL65", 0x865A, "STY", 0x12),
                   ("ECL65", 0x874B, "DEC", 0x12),
                   ("ECL65", 0x8779, "DEC", 0x13),
                   ("GEN", 0x0C70, "STY", 0x13),
                   ("GEN", 0x0C7D, "STY", 0x12),
                   ("GEN", 0x0C81, "STA", 0x12),
                   ("GEN", 0x0C84, "STA", 0x13)),
    },
}


def _finding(key: str) -> dict:
    try:
        return curedisease.inspect_title(key)
    except SystemExit as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_uses_live_in_record_bytes_0x012_and_0x013(key):
    """Every write to either byte is the seed, a use, or the expiry reset.

    No other routine in `GEN`, `LIBRARY`, `ECL65` or `CAMP` stores to them,
    so nothing else can put a use back.
    """
    finding = _finding(key)
    want = EXPECTED[key]
    assert (finding["counter"], finding["lay_on_hands"]) == (0x012, 0x013)
    assert finding["writes"] == want["writes"]
    for name in ("seed", "seed_callers", "full_count", "cure_decrement",
                 "lay_decrement"):
        assert finding[name] == want[name], name


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_seed_and_the_reset_count_one_two_or_three_by_level(key):
    """1 below paladin level 6, 2 below 11, 3 from 11 up; 0 for no paladin."""
    finding = _finding(key)
    assert finding["thresholds"] == (6, 11)
    assert [curedisease.full_count(level, finding["thresholds"])
            for level in (0, 1, 5, 6, 10, 11, 15)] == [0, 1, 1, 2, 2, 3, 3]


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_sheet_hides_cure_at_zero_and_heal_at_zero(key):
    finding = _finding(key)
    assert finding["gate"] == EXPECTED[key]["gate"]
    assert finding["menu"] == ("ITEMS", "SPELLS", "TRADE", "DROP", "CURE",
                               "HEAL", "EXIT")
    assert finding["gated"] == ("CURE", "HEAL")


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_a_use_starts_a_timer_row_whose_expiry_resets_the_count(key):
    """The spent state is an effect-array row, not memory the save drops."""
    finding = _finding(key)
    want = EXPECTED[key]
    for label, timer in (("cure", finding["cure_timer"]),
                         ("lay", finding["lay_timer"])):
        assert (timer.effect_id, timer.duration, timer.magnitude, timer.add,
                timer.reset) == want[label], label
        # Bit 7 of the magnitude is what lets the camp run the handler.
        assert timer.magnitude & 0x80
        assert finding["expiry_handlers"][timer.effect_id] == timer.reset
    assert finding["cure_guard"] == want["cure_guard"]
    for name in ("expiry_dispatch", "expiry_ids", "expiry_magnitude_gate"):
        assert finding[name] == want[name], name


def test_pool_of_radiance_has_no_paladin_to_keep_uses_for():
    try:
        finding = curedisease.pool()
    except SystemExit as exc:
        pytest.skip(str(exc))
    assert finding["files"] > 0
    assert finding["naming_paladin"] == ()
    assert finding["menu_has_cure"] is False
