"""Repeated Bless nodes on one DOS character become one C64 Bless row.

DOS gives one +1 bonus however many Bless nodes run, and the C64 replaces a
Bless row on recast, so the copies are not losses and do not count toward the
C64's 64 shared effect rows.  No game data is read: every character is built
here.
"""

from __future__ import annotations

import logging

import pytest
from test_leaveeffects import (
    MEMBERS,
    PROTECTION,
    _id_rows,
    _pool_character,
    _save,
)

from goldbox import c64_codec, dos_codec, effects


def _bless(minutes: int, data: int = 6, flag: int = 0) -> bytes:
    return (bytes((1, minutes & 0xFF, minutes >> 8, data, flag))
            + dos_codec.EFFECT_NEXT_NULL)


def _durations(save0, owner: int | None = None) -> list[int]:
    at = dos_codec.EFFECT_ARRAYS[0][0] - dos_codec.SAVE0_BASE
    return [save0[at + effects.EFFECT_DURATION_OFFSET + i]
            for i in range(effects.EFFECT_SLOTS)
            if save0[at + effects.EFFECT_ID_OFFSET + i] == 1
            and (owner is None
                 or save0[at + effects.EFFECT_OWNER_OFFSET + i] == owner)]


def test_repeated_bless_nodes_become_one_row_with_the_longest_time(caplog):
    short = _save([_pool_character([_bless(30)])])
    with caplog.at_level(logging.INFO, logger="wish.goldbox"):
        long_ = _save([_pool_character([_bless(10), _bless(30), _bless(20)],
                                       "BLESSED")])
    assert len(_id_rows(long_[0])) == 1
    assert _durations(long_[0]) == _durations(short[0])
    report = long_[2]
    assert [x for x in (*report.losses, *report.dropped)
            if "running_effects" in x] == []
    assert report.left_behind == []
    assert not [w for w in report.warnings if "Bless" in w]
    assert any("BLESSED: 2 repeated Bless nodes" in r.getMessage()
               for r in caplog.records)


def test_a_party_of_sixty_six_blesses_converts_without_asking():
    save0, _save1, report = _save(_party_of_bless(11))
    assert len(_id_rows(save0)) == MEMBERS
    assert report.left_behind == []
    assert [x for x in report.losses if "running_effects" in x] == []


def _party_of_bless(count: int) -> list:
    return [_pool_character([_bless(2 + n) for n in range(count)],
                            f"MEMBER{n}") for n in range(MEMBERS)]


def test_each_character_keeps_its_own_bless_row():
    party = [_pool_character([_bless(5), _bless(9)], "ONE"),
             _pool_character([_bless(7), _bless(3)], "TWO")]
    save0, _save1, _report = _save(party)
    owners = sorted(owner for _id, owner in _id_rows(save0))
    assert len(owners) == 2 and owners[0] != owners[1]


def test_a_party_still_over_64_asks_and_offers_bless_once():
    party = [_pool_character([_bless(2 + n) for n in range(11)]
                             + [PROTECTION] * 10, f"MEMBER{n}")
             for n in range(MEMBERS)]
    with pytest.raises(dos_codec.EffectsDoNotFit) as caught:
        _save(party)
    overflow = caught.value.overflow
    # Ten id-8 and one Bless row each: 66 rows, two over.
    assert (overflow.needed, overflow.over) == (66, 2)
    ids = [e.effect_id for e in overflow.entries]
    assert ids.count(1) == MEMBERS and ids.count(8) == 60


def _bless_row_magnitudes(save0) -> list[int]:
    at = dos_codec.EFFECT_ARRAYS[0][0] - dos_codec.SAVE0_BASE
    return [save0[at + effects.EFFECT_MAGNITUDE_OFFSET + i]
            for i in range(effects.EFFECT_SLOTS)
            if save0[at + effects.EFFECT_ID_OFFSET + i] == 1]


def test_bless_nodes_at_different_caster_levels_keep_the_longest_whole():
    save0, _save1, _report = _save(
        [_pool_character([_bless(5, data=3), _bless(9, data=8),
                          _bless(2, data=12)])])
    assert _bless_row_magnitudes(save0) == [8]


def test_a_tie_on_time_keeps_the_higher_caster_level():
    save0, _save1, _report = _save(
        [_pool_character([_bless(9, data=3), _bless(9, data=8),
                          _bless(9, data=5)])])
    assert _bless_row_magnitudes(save0) == [8]


def test_one_c64_bless_row_reads_back_as_one_dos_node():
    char = _pool_character([_bless(30)])
    payload = bytearray(0x1C00)
    rec, _rep = c64_codec.write(char, payload=payload, party_slot=0,
                                clock_minutes=0)
    back = c64_codec.read(rec, game=char.game, payload=bytes(payload),
                          party_slot=0, clock_minutes=0)
    nodes = [effects.RunningEffect.from_record(bytes(r))
             for r in back.get("running_effects")]
    assert [n.id for n in nodes] == [1]


def _crowded() -> list:
    """Six members, three Bless and ten Protection from Evil each: 66 rows."""
    return [_pool_character([_bless(2 + n) for n in range(3)]
                            + [PROTECTION] * 10, f"MEMBER{n}")
            for n in range(MEMBERS)]


def test_the_offered_bless_stands_for_the_members_whole_group():
    with pytest.raises(dos_codec.EffectsDoNotFit) as caught:
        _save(_crowded())
    overflow = caught.value.overflow
    assert (overflow.needed, overflow.over) == (66, 2)
    offered = {e.member: e.index for e in overflow.entries
               if e.effect_id == 1}
    assert len(offered) == MEMBERS

    save0, _save1, report = _save(
        _crowded(), leave_effects={0: {offered[0]}, 1: {offered[1]}})
    assert len(report.left_behind) == 6
    assert all("Bless" in x or "BLESS" in x.upper()
               for x in report.left_behind)
    assert [x for x in report.losses if "running_effects" in x] == []
    owners = [owner for _id, owner in _id_rows(save0) if _id == 1]
    assert len(owners) == MEMBERS - 2
    assert not {dos_codec.marching_slot(0, MEMBERS),
                dos_codec.marching_slot(1, MEMBERS)} & set(owners)


def test_a_copy_the_c64_cannot_hold_does_not_stand_for_the_rest():
    # The longest copy has a flag byte no caster-level row carries; the
    # next-longest convertible copy is the row.
    save0, _save1, _report = _save([_pool_character(
        [_bless(50, flag=1), _bless(10, data=4), _bless(5, data=9)])])
    assert _bless_row_magnitudes(save0) == [4]


def test_with_no_convertible_copy_every_copy_reports_as_before():
    save0, _save1, report = _save([_pool_character(
        [_bless(50, flag=1), _bless(10, flag=2)])])
    assert _bless_row_magnitudes(save0) == []
    assert len([x for x in report.dropped if "running_effects" in x]) == 2
