"""The player's choice of which running effects to leave out reaches the C64
writer.

The C64 holds every character's running effects in one shared table of 64
rows, and DOS keeps them in a list per character with no count limit, so six
members with eleven Bless nodes each need 66.  The writer raises
`EffectsDoNotFit` naming every effect the player can leave out; the choice
comes back as `leave_effects` and each effect left out is a line of
`Report.left_behind`, never a loss, so Save As does not refuse it.  No game
data is read: every character is built here.
"""

from __future__ import annotations

import pytest

from goldbox import c64_port, dos_codec, dos_port, effects, neutral, world_state

#: Effect 1 (Bless), two minutes left, value 1, flag 0.
BLESS = bytes((1, 2, 0, 1, 0)) + dos_codec.EFFECT_NEXT_NULL
#: Effect 49 (Prayer) is the id the C64 keeps as one party-wide row.
PRAYER = bytes((49, 30, 0, 1, 0)) + dos_codec.EFFECT_NEXT_NULL

MEMBERS = 6


def _pool_character(nodes: list[bytes], name: str = "BLESSED"
                    ) -> neutral.NeutralCharacter:
    char = neutral.NeutralCharacter("DOS", source="built here",
                                    game=c64_port.POOL_OF_RADIANCE)
    char.set("name", name, "built here")
    char.set("running_effects", list(nodes), "built here")
    return char


def _party(blesses: int, extra: list[bytes] = ()) -> list:
    return [_pool_character([BLESS] * blesses + list(extra), f"MEMBER{n}")
            for n in range(MEMBERS)]


def _save(party, **kw):
    container = c64_port.POOL_OF_RADIANCE
    state = world_state.from_c64(bytes(container.payload_size))
    return dos_codec.new_save_from_neutral(
        state, party, [None] * len(party), bytes(36),
        bytes(dos_codec.ANIMATE_SIZE), **kw)


def _id_rows(save0) -> list[tuple[int, int]]:
    """`(id, owner)` of every occupied row of the shared effect table."""
    at = dos_codec.EFFECT_ARRAYS[0][0] - dos_codec.SAVE0_BASE
    return [(save0[at + effects.EFFECT_ID_OFFSET + i],
             save0[at + effects.EFFECT_OWNER_OFFSET + i])
            for i in range(effects.EFFECT_SLOTS)
            if save0[at + effects.EFFECT_ID_OFFSET + i]]


def test_eleven_blesses_each_ask_the_player_what_to_leave_out():
    with pytest.raises(dos_codec.EffectsDoNotFit) as caught:
        _save(_party(11))
    overflow = caught.value.overflow
    assert (overflow.limit, overflow.needed, overflow.over) == (64, 66, 2)
    assert len(overflow.entries) == 66
    assert {e.effect_id for e in overflow.entries} == {1}
    assert overflow.names == tuple(f"MEMBER{n}" for n in range(MEMBERS))
    assert overflow.entries[0] == dos_codec.EffectEntry(0, 0, 1, 2)
    assert overflow.entries[11] == dos_codec.EffectEntry(1, 0, 1, 2)


def test_leaving_out_two_nodes_converts_and_is_not_a_loss():
    save0, _save1, report = _save(_party(11), leave_effects={0: {0}, 1: {0}})
    assert not [x for x in (*report.losses, *report.dropped)
                if "running_effects" in x]
    assert len(report.left_behind) == 2
    assert all("left out by the player's choice" in x
               for x in report.left_behind)
    rows = _id_rows(save0)
    assert len(rows) == 64
    owners = sorted(owner for _id, owner in rows)
    assert {o: owners.count(o) for o in set(owners)} == {
        dos_codec.marching_slot(n, MEMBERS): 10 if n < 2 else 11
        for n in range(MEMBERS)}


def test_leaving_out_too_few_asks_again():
    with pytest.raises(dos_codec.EffectsDoNotFit) as caught:
        _save(_party(11), leave_effects={0: {0}})
    overflow = caught.value.overflow
    assert overflow.over == 1
    # The node already left out is not offered again.
    assert len(overflow.entries) == 65
    assert dos_codec.EffectEntry(0, 0, 1, 2) not in overflow.entries


def test_a_party_row_counts_once_and_is_not_offered():
    with pytest.raises(dos_codec.EffectsDoNotFit) as caught:
        _save(_party(11, [PRAYER]))
    overflow = caught.value.overflow
    assert overflow.needed == 67
    assert len(overflow.entries) == 66
    assert 49 not in {e.effect_id for e in overflow.entries}


def test_an_index_outside_the_list_is_refused():
    with pytest.raises(dos_codec.DosRecordError, match="running effect 11"):
        _save(_party(11), leave_effects={0: {11}})
    with pytest.raises(dos_codec.DosRecordError, match="member 9"):
        _save(_party(11), leave_effects={9: {0}})


def test_sixty_nodes_fit_and_ask_nothing():
    _save0, _save1, report = _save(_party(10))
    assert report.left_behind == []
    assert not [x for x in report.losses if "running_effects" in x]


def _dos_party(blesses: int) -> list[dos_codec.DosCharacter]:
    raw = bytearray(dos_port.RECORD_SIZE)
    raw[dos_port.FIELDS_BY_NAME["size"].offset] = 1
    return [dos_codec.DosCharacter(bytes(raw), effects=[BLESS] * blesses)
            for _ in range(MEMBERS)]


def _save_dos(party, **kw):
    container = c64_port.POOL_OF_RADIANCE
    state = world_state.from_c64(bytes(container.payload_size))
    return dos_codec.new_save_from(
        state, party, bytes(36), bytes(dos_codec.ANIMATE_SIZE), **kw)


def test_the_dos_record_route_asks_and_then_converts():
    with pytest.raises(dos_codec.EffectsDoNotFit) as caught:
        _save_dos(_dos_party(11))
    assert (caught.value.overflow.needed,
            len(caught.value.overflow.entries)) == (66, 66)
    save0, _save1, report = _save_dos(_dos_party(11),
                                      leave_effects={2: {4}, 3: {10}})
    assert len(report.left_behind) == 2
    assert len(_id_rows(save0)) == 64
