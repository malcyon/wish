"""Checks `goldbox/treasuresplit.py` against the measured and code-read numbers, with no game data."""

from fractions import Fraction

import pytest

from goldbox import treasuresplit as ts
from goldbox.treasuresplit import Member

POOL = "pool-of-radiance"
CURSE = "curse-of-the-azure-bonds"
SILVER = "secret-of-the-silver-blades"


def player(status=0):
    return Member(control=0x00, share=0, status=status)


def companion(share, status=0):
    return Member(control=0xB2, share=share, status=status)


def c64(share, status=1):
    """A C64 companion; status 0 there is an empty slot."""
    return companion(share, status)


def party(*extra, players=6, status=0):
    return [player(status) for _ in range(players)] + list(extra)


def test_dos_pool_ff_with_six_players_is_7_of_13():
    s = ts.share_for(POOL, "DOS", party(companion(0xFF)), 6)
    assert (s.kind, s.value, s.parts, s.denominator) == ("fraction", Fraction(7, 13), 7, 13)
    assert s.companion_parts == 7 and s.wrap_at == 256 * 13


def test_dos_pool_03_is_3_of_9():
    s = ts.share_for(POOL, "DOS", party(companion(0x03)), 6)
    assert s.value == Fraction(3, 9) and s.denominator == 9


def test_pile_arithmetic_cut_64_to_21_for_fb():
    s = ts.share_for(POOL, "DOS", party(companion(0xFB)), 6)
    assert (s.parts, s.denominator) == (3, 9)
    assert ts.pile_cut(64, s.denominator, s.companion_parts) == 21
    assert ts.split_piles([64], s.denominator, s.companion_parts, POOL) == [43]


def test_pile_cut_wraps_on_the_byte_quotient_and_never_goes_negative():
    assert ts.pile_cut(256 * 13, 13, 7) == 0
    assert ts.pile_cut(0, 13, 7) == 0
    assert ts.pile_cut(12, 13, 7) == 0


def test_two_companions_give_7_16_and_3_16():
    r = ts.party_shares(POOL, "DOS", party(companion(0xFF), companion(0x03)))
    assert [r.shares[6].value, r.shares[7].value] == [Fraction(7, 16), Fraction(3, 16)]
    assert r.combined == Fraction(10, 16)
    assert r.shares[7].companion_parts == 10
    # a pile of 160 loses 100, 70 for the first and 30 for the second
    assert ts.pile_cut(160, 16, 10) == 100


def test_status_not_zero_takes_nothing_and_counts_as_one():
    s = ts.share_for(POOL, "DOS", party(companion(0xFF, status=1)), 6)
    assert (s.value, s.parts, s.denominator) == (0, 0, 7)


def test_share_low_bits_zero_adds_nothing_to_the_denominator():
    s = ts.share_for(POOL, "DOS", party(companion(0x08)), 6)
    assert (s.value, s.denominator) == (0, 6)


def test_player_character_gets_none():
    assert ts.share_for(POOL, "DOS", party(companion(0xFF)), 0) is None


@pytest.mark.parametrize("title,port", [(POOL, "Amiga"), (CURSE, "DOS"), (SILVER, "DOS")])
def test_same_fraction_on_amiga_pool_and_later_dos_titles(title, port):
    assert ts.share_for(title, port, party(companion(0xFF)), 6).value == Fraction(7, 13)


@pytest.mark.parametrize("title", [CURSE, SILVER])
def test_later_title_companion_with_share_zero_gets_zero(title):
    s = ts.share_for(title, "DOS", party(companion(0)), 6)
    assert s.value == 0 and s.kind == "fraction"


def test_silver_blades_leaves_pile_zero_out():
    piles = [1000, 1000, 1000]
    assert ts.split_piles(piles, 13, 7, title_key=SILVER) == [1000, 1000 - 76 * 7, 1000 - 76 * 7]
    assert ts.split_piles(piles, 13, 7, title_key=POOL)[0] == 1000 - 76 * 7


def test_c64_one_ff_companion_with_six_players_is_3_of_11():
    r = ts.party_shares(POOL, "C64", party(c64(0xFF), status=1))
    s = r.shares[6]
    assert s.kind == "chance" and s.value == Fraction(3, 11) == r.combined
    assert (s.companion_parts, s.occupied_slots, s.denominator) == (3, 7, 11)
    assert s.wrap_at is None


def test_c64_other_rows_of_the_read():
    assert ts.party_shares(POOL, "C64", party(c64(0xFF), players=3, status=1)).combined == Fraction(3, 8)
    assert ts.party_shares(POOL, "C64", party(c64(0x01), status=1)).combined == Fraction(1, 9)
    two = ts.party_shares(POOL, "C64", party(c64(0xFF), c64(0xFF), status=1))
    assert two.combined == Fraction(6, 15)
    assert two.shares[6].value + two.shares[7].value == two.combined


def test_c64_downed_companion_and_zero_low_bits_add_nothing():
    down = ts.party_shares(POOL, "C64", party(c64(0xFF, 0x81), status=1))
    assert down.combined == 0 and down.shares[6].occupied_slots == 7
    zero = ts.party_shares(POOL, "C64", party(c64(0x84), status=1))
    assert zero.combined == 0 and zero.shares[6].value == 0


def test_c64_curse_uses_the_same_rule_code_read_not_measured_and_silver_blades_never_takes():
    """Curse's 3/11 is read from the code and has not been measured live."""
    assert ts.party_shares(CURSE, "C64", party(c64(0xFF), status=1)).combined == Fraction(3, 11)
    r = ts.party_shares(SILVER, "C64", party(c64(0xFF), status=1))
    assert r.combined == 0 and r.shares[6].value == 0
    assert r.certain is False and r.shares[6].certain is False
    assert ts.party_shares(POOL, "C64", party(c64(0xFF), status=1)).certain is True
    assert ts.party_shares(SILVER, "DOS", party(companion(0xFF))).certain is True


def test_c64_companion_with_status_zero_is_left_out_of_s_and_n():
    """A dropped slot counts in neither; the code read leaves S open."""
    r = ts.party_shares(POOL, "C64", party(c64(0xFF, 0), status=1))
    assert r.combined == Fraction(0, 7) and r.shares[6].occupied_slots == 6


def test_no_rule_gives_none():
    assert ts.party_shares("pools-of-darkness", "DOS", party(c64(0xFF))) is None
    assert ts.share_for(SILVER, "Amiga", party(c64(0xFF)), 6) is None
    assert ts.share_for(CURSE, "Amiga", party(c64(0xFF)), 6) is None
    assert ts.share_for(POOL, "Atari", party(c64(0xFF)), 6) is None
