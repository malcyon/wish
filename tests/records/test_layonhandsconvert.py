"""A paladin's lay-on-hands use, converted between DOS and the Amiga (#628).

`docs/231-where-lay-on-hands-lives.md` has the mapping: one neutral field,
`lay_on_hands_minutes` -- 0 means he may heal now, and a nonzero count is the
same one-day timer every port keeps as an effect node rather than a record
byte. The id differs by title and by port: Curse is 140 everywhere, Silver
Blades and Pools of Darkness are 109 on DOS and 140 on the Amiga.

The C64 side, a row in the save's own 64-slot effect arrays rather than a
node, is `tests/records/test_paladinc64.py`.
"""
from __future__ import annotations

import pytest

from goldbox import amiga_later, amiga_pod, amiga_port, dos_codec, dos_port, neutral
from goldbox.layout import Confidence

CURSE = dos_port.CURSE_OF_THE_AZURE_BONDS
SSB = dos_port.SECRET_OF_THE_SILVER_BLADES
POOL = dos_port.POOL_OF_RADIANCE
POD = dos_port.POOLS_OF_DARKNESS

#: title key -> (DOS heal id, Amiga heal id)
IDS = {
    CURSE.key: (140, 140),
    SSB.key: (109, 140),
    POD.key: (109, 140),
}


def _neutral(game, **fields) -> neutral.NeutralCharacter:
    char = neutral.NeutralCharacter("test", source="made up", game=game)
    char.set("name", "TESTER", "made up", Confidence.CONFIRMED)
    for name, value in fields.items():
        char.set(name, value, "made up for the test", Confidence.CONFIRMED)
    return char


def _dos_effects(spc: bytes) -> list[bytes]:
    return [spc[i:i + 9] for i in range(0, len(spc), 9)]


# --- DOS: writing -------------------------------------------------------

@pytest.mark.parametrize("shape", (CURSE, SSB, POD), ids=lambda s: s.key)
def test_a_paladin_who_may_heal_writes_no_dos_node(shape):
    char = _neutral(shape.key, lay_on_hands_minutes=0)
    _rec, _itm, spc, rep = dos_codec.write(char)
    dos_id, _amiga_id = IDS[shape.key]
    assert dos_id not in [e[0] for e in _dos_effects(spc)]
    assert not any("lay_on_hands_minutes" in d for d in rep.dropped)


@pytest.mark.parametrize("shape", (CURSE, SSB, POD), ids=lambda s: s.key)
def test_a_spent_paladin_writes_a_dos_node_with_the_titles_own_id(shape):
    char = _neutral(shape.key, lay_on_hands_minutes=723)
    _rec, _itm, spc, rep = dos_codec.write(char)
    dos_id, _amiga_id = IDS[shape.key]
    nodes = [e for e in _dos_effects(spc) if e[0] == dos_id]
    assert len(nodes) == 1, _dos_effects(spc)
    assert int.from_bytes(nodes[0][1:3], "little") == 723
    assert nodes[0][3] == 0 and nodes[0][4] == 0, "value 0, not 0xFF"
    assert not any("lay_on_hands_minutes" in d for d in rep.dropped)


def test_pool_of_radiance_has_nowhere_to_put_it():
    char = _neutral(POOL.key, lay_on_hands_minutes=200)
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == b""
    assert any("lay_on_hands_minutes" in d for d in rep.dropped)


def test_a_non_paladin_gets_nothing():
    """A character the field was never set on writes no node at all."""
    char = _neutral(CURSE.key)
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == b""
    assert not any("lay_on_hands_minutes" in d for d in rep.dropped)


# --- DOS: reading --------------------------------------------------------

@pytest.mark.parametrize("shape", (CURSE, SSB, POD), ids=lambda s: s.key)
def test_reading_the_dos_node_back_gives_the_same_minutes(shape):
    dos_id, _amiga_id = IDS[shape.key]
    rec = bytes(shape.record_size)
    node = bytes((dos_id,)) + (500).to_bytes(2, "little") + bytes(2) \
        + dos_codec.EFFECT_NEXT_NULL
    dc = dos_codec.DosCharacter(rec, effects=[node], deltas=shape)
    out = dos_codec.to_neutral(dc)
    assert out.get("lay_on_hands_minutes") == 500


@pytest.mark.parametrize("shape", (CURSE, SSB, POD), ids=lambda s: s.key)
def test_reading_no_dos_node_means_he_may_heal_now(shape):
    rec = bytes(shape.record_size)
    dc = dos_codec.DosCharacter(rec, effects=[], deltas=shape)
    out = dos_codec.to_neutral(dc)
    assert out.get("lay_on_hands_minutes") == 0


# --- DOS <-> Amiga round trips -------------------------------------------

_AMIGA_SHAPES = ((CURSE, amiga_port.CURSE_DELTAS),
                 (SSB, amiga_port.SILVER_BLADES_DELTAS))


@pytest.mark.parametrize("shape,deltas", _AMIGA_SHAPES,
                         ids=lambda s: getattr(s, "key", str(s)))
def test_a_spent_paladin_converts_dos_to_amiga_with_the_amiga_id(shape, deltas):
    char = _neutral(shape.key, lay_on_hands_minutes=640)
    amiga, report = amiga_later.write_later(char, deltas=deltas)
    heal = [e for e in amiga.effects if e[0] == 140]
    assert len(heal) == 1, amiga.effects
    assert int.from_bytes(heal[0][2:4], "big") == 640
    assert not any("lay_on_hands" in d for d in report.dropped)

    back = amiga_later.to_neutral_later(amiga)
    assert back.get("lay_on_hands_minutes") == 640


@pytest.mark.parametrize("shape,deltas", _AMIGA_SHAPES,
                         ids=lambda s: getattr(s, "key", str(s)))
def test_a_healed_paladin_converts_dos_to_amiga_with_no_node(shape, deltas):
    char = _neutral(shape.key, lay_on_hands_minutes=0)
    amiga, _report = amiga_later.write_later(char, deltas=deltas)
    assert 140 not in [e[0] for e in amiga.effects]
    back = amiga_later.to_neutral_later(amiga)
    assert back.get("lay_on_hands_minutes") == 0


@pytest.mark.parametrize("shape,deltas", _AMIGA_SHAPES,
                         ids=lambda s: getattr(s, "key", str(s)))
def test_a_spent_paladin_converts_amiga_to_dos_with_dos_own_id(shape, deltas):
    """The Amiga's 140 must become the title's own DOS id on the way back --
    never copied unchanged (docs/231, "An effect copied with the same id")."""
    dos_id, _amiga_id = IDS[shape.key]
    node = bytes((140, 0)) + (400).to_bytes(2, "big") + bytes(2) + bytes(4)
    amiga_char = amiga_later.AmigaCharacter.from_bytes(
        bytes(deltas.record_size), deltas=deltas, effects=[node])
    reread = amiga_later.to_neutral_later(amiga_char)
    assert reread.get("lay_on_hands_minutes") == 400

    _rec, _itm, spc, rep = dos_codec.write(reread, deltas=shape)
    nodes = [e for e in _dos_effects(spc) if e[0] == dos_id]
    assert len(nodes) == 1, _dos_effects(spc)
    assert int.from_bytes(nodes[0][1:3], "little") == 400
    assert dos_id != 140 or shape is CURSE  # sanity: SSB's own id is 109
    assert not any("lay_on_hands_minutes" in d for d in rep.dropped)


# --- DOS <-> Amiga Pools of Darkness --------------------------------------

def test_pools_of_darkness_a_spent_paladin_converts_to_the_amiga_id():
    char = _neutral(POD.key, lay_on_hands_minutes=900, race=5, sex=0, alignment=0, class_bits=64)
    writer, report = amiga_pod.write_pod(char)
    heal = [e for e in writer.effects if e[0] == 140]
    assert len(heal) == 1, writer.effects
    assert int.from_bytes(heal[0][2:4], "big") == 900
    assert not any("lay_on_hands" in d for d in report.dropped)

    raw = writer.to_bytes()
    back = amiga_pod.pod_to_neutral(raw)
    assert back.get("lay_on_hands_minutes") == 900


def test_pools_of_darkness_a_healed_paladin_writes_no_amiga_node():
    char = _neutral(POD.key, lay_on_hands_minutes=0, race=5, sex=0, alignment=0, class_bits=64)
    writer, _report = amiga_pod.write_pod(char)
    assert 140 not in [e[0] for e in writer.effects]
    raw = writer.to_bytes()
    back = amiga_pod.pod_to_neutral(raw)
    assert back.get("lay_on_hands_minutes") == 0


def test_pools_of_darkness_reading_the_amiga_node_gives_dos_its_own_id():
    """The Amiga's 140 must become Pools of Darkness's own 109 on the way
    back to DOS, never copied unchanged (docs/231, "An effect copied with
    the same id")."""
    neutral_char = _neutral(POD.key, lay_on_hands_minutes=350, race=5, sex=0, alignment=0, class_bits=64)
    writer, _report = amiga_pod.write_pod(neutral_char)
    raw = writer.to_bytes()
    reread = amiga_pod.pod_to_neutral(raw)
    _rec, _itm, spc, _rep = dos_codec.write(reread)
    nodes = [e for e in _dos_effects(spc) if e[0] == 109]
    assert len(nodes) == 1, _dos_effects(spc)
    assert int.from_bytes(nodes[0][1:3], "little") == 350
    assert 140 not in [e[0] for e in _dos_effects(spc)]
