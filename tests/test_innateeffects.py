from __future__ import annotations

"""Curse of the Azure Bonds' and Secret of the Silver Blades' own innate
effect ids (#388, A converted paladin or ranger loses his innate effect on
the way to DOS, because the writer filters through Pool of Radiance's id
list).

`goldbox.dos.INNATE_EFFECTS` is Pool of Radiance's own set -- the racial and
constitutional bonuses `goldbox/dos.py`'s own docstring already measured.
Pool of Radiance has no paladin and no ranger (`goldbox.games.POOL_OF_RADIANCE`
carries `CLASS_BITS_CLASSIC`, with neither class bit), so the set was never
wrong for the title it was measured on -- it was wrong to use, unchanged, for
the two titles that do instantiate both classes.

Four ids, all CONFIRMED from DOS `.SPC` records this project watched the
running game write, none of them passed through `goldbox.dos.write` or
`goldbox.c64_codec.write` first (every specimen's own `provenance.toml` says
so):

* **8, "Protection from Evil", is the paladin's in both titles** --
  DEMELTINA, MATHEW and MARK in Curse (`WISH-SPEC-curse-234-before`,
  `WISH-SPEC-curse-131-four-items-readied`,
  `WISH-SPEC-curse-131-dualclassed-in-area-1`) and Guy de Valois in Silver
  Blades (`WISH-SPEC-ssb-234-party-pair`, `WISH-SPEC-ssb-slote-zeroed140`).
* **134 is Curse's own ranger id** -- ARGORA and RWELLYN,
  `WISH-SPEC-curse-234-party-dualclassed`.
* **105 is Silver Blades' own ranger id, and a different number** -- PAINE,
  `WISH-SPEC-ssb-234-before`, `WISH-SPEC-ssb-234-party-pair`,
  `WISH-SPEC-ssb-slote-zeroed140`.  `docs/121-silver-blades.md` had already
  found the ranger's ids disagree between the two titles, from a different
  route: the two titles' own seed tables for a *different*, C64-side combat
  trait computed live rather than stored (`GEN $2515` in Curse, `GEN $0FF0`
  in Silver Blades) agree on the paladin's at 45 and disagree on the
  ranger's, 134 against 105 -- the same two numbers this file's own `.SPC`
  evidence lands on, by a different route.

Every one of the nine-byte records above reads duration zero and
`INNATE_PAYLOAD` in bytes 1-4, which is the shape `docs/162-spc-permanence.md`
established for a record the engine's expiry pass never removes -- not a
`.SPC` record that just happens to share an id with a running effect.
"""

import pytest
from gamedata import specimen, specimen_root
from test_doslatertitles import _mask

from goldbox import c64_codec, dos, dos_layout, neutral
from goldbox.d64 import D64
from goldbox.savegame import load_save

CURSE = dos_layout.CURSE_OF_THE_AZURE_BONDS
SSB = dos_layout.SECRET_OF_THE_SILVER_BLADES
POOL = dos_layout.POOL_OF_RADIANCE

#: Protection from Evil, the paladin's -- the same id in both later titles.
PALADIN_EFFECT = 8
#: The two titles' own, different, ranger ids (docs/121, this file's own
#: measurement).
RANGER_EFFECT = {CURSE.key: 134, SSB.key: 105}


def _neutral(game, **fields) -> neutral.NeutralCharacter:
    """A neutral character for `game` carrying only what a test names."""
    char = neutral.NeutralCharacter("test", source="made up", game=game)
    for name, value in fields.items():
        char.set(name, value, "made up for the test")
    return char


def _record(shape, effects) -> dos.DosCharacter:
    """An all-zero record of `shape` carrying only the given `.SPC` nodes."""
    return dos.DosCharacter(bytes(shape.record_size), effects=effects,
                            shape=shape)


def _innate_node(effect_id: int) -> bytes:
    """One nine-byte `.SPC` node in `INNATE_PAYLOAD`'s own shape: duration
    zero, `FF 00` at bytes 3-4, next pointer NULL."""
    return bytes((effect_id,)) + dos.INNATE_PAYLOAD + dos.EFFECT_NEXT_NULL


# --- the tables themselves ----------------------------------------------

def test_pool_of_radiance_is_unchanged():
    """The control #388 asks for: Pool of Radiance's own set is exactly what
    it was, so its pane stays empty."""
    assert dos.INNATE_EFFECTS == frozenset(
        {18, 26, 47, 48, 90, 97, 107, 124})
    assert PALADIN_EFFECT not in dos.INNATE_EFFECTS
    assert RANGER_EFFECT[SSB.key] not in dos.INNATE_EFFECTS
    assert RANGER_EFFECT[CURSE.key] not in dos.INNATE_EFFECTS


def test_a_title_not_listed_gets_pool_of_radiances_set():
    assert dos._innate_effects(POOL.key) is dos.INNATE_EFFECTS
    assert dos._innate_effects(None) is dos.INNATE_EFFECTS
    assert dos._innate_effects("some-title-nobody-has-measured") \
        is dos.INNATE_EFFECTS


def test_the_two_later_titles_add_only_their_own_two_ids():
    assert dos.INNATE_EFFECTS_CURSE - dos.INNATE_EFFECTS == {8, 134}
    assert dos.INNATE_EFFECTS_SILVER_BLADES - dos.INNATE_EFFECTS == {8, 105}
    assert dos._innate_effects(CURSE.key) == dos.INNATE_EFFECTS_CURSE
    assert dos._innate_effects(SSB.key) == dos.INNATE_EFFECTS_SILVER_BLADES


def test_a_titles_ranger_id_is_not_the_others():
    """134 and 105 are two different numbers for two different titles, and
    neither title's set is widened by the other's."""
    assert RANGER_EFFECT[CURSE.key] not in dos.INNATE_EFFECTS_SILVER_BLADES
    assert RANGER_EFFECT[SSB.key] not in dos.INNATE_EFFECTS_CURSE


# --- the read side: to_neutral classifies the id as innate, not granted -----

@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_paladins_protection_from_evil_reads_as_innate(shape):
    char = _record(shape, [_innate_node(PALADIN_EFFECT)])
    out = dos.to_neutral(char)
    assert out.get("innate_effects") == [PALADIN_EFFECT]
    assert "granted_effects" not in out


@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_rangers_own_id_reads_as_innate(shape):
    effect = RANGER_EFFECT[shape.key]
    char = _record(shape, [_innate_node(effect)])
    out = dos.to_neutral(char)
    assert out.get("innate_effects") == [effect]
    assert "granted_effects" not in out


def test_pool_of_radiance_still_reads_the_paladins_id_as_granted():
    """The read-side control: nothing changed for the title the set was
    measured on.  Before #388 this was the *only* way an id 8 record
    survived a DOS -> DOS round trip, and it still is here."""
    char = _record(POOL, [_innate_node(PALADIN_EFFECT)])
    out = dos.to_neutral(char)
    assert out.get("innate_effects") == []
    assert [bytes(g) for g in out.get("granted_effects")] == \
        [_innate_node(PALADIN_EFFECT)]


# --- the write side: dos.write no longer drops the two ids ------------------

@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_paladins_effect_reaches_the_spc_file(shape):
    char = _neutral(shape.key, name="TESTER",
                    innate_effects=[PALADIN_EFFECT])
    _rec, _itm, spc, rep = dos.write(char)
    assert spc == _innate_node(PALADIN_EFFECT)
    assert not [d for d in rep.dropped if "innate_effects" in d]


@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_rangers_effect_reaches_the_spc_file(shape):
    effect = RANGER_EFFECT[shape.key]
    char = _neutral(shape.key, name="TESTER", innate_effects=[effect])
    _rec, _itm, spc, rep = dos.write(char)
    assert spc == _innate_node(effect)
    assert not [d for d in rep.dropped if "innate_effects" in d]


def test_pool_of_radiance_still_drops_the_paladins_id():
    """The write-side control matching the read-side one above: #388 must
    not touch the title it was never wrong for."""
    char = _neutral(POOL.key, name="TESTER", innate_effects=[PALADIN_EFFECT])
    _rec, _itm, spc, rep = dos.write(char)
    assert spc == b""
    assert [d for d in rep.dropped if "innate_effects" in d]


def test_a_curse_characters_own_ranger_id_still_drops_in_silver_blades():
    """134 is Curse's; asked to write it for Silver Blades, the writer still
    turns it away -- the fix is a title's own set, not a merge of both."""
    char = _neutral(SSB.key, name="TESTER",
                    innate_effects=[RANGER_EFFECT[CURSE.key]])
    _rec, _itm, spc, rep = dos.write(char)
    assert spc == b""
    assert [d for d in rep.dropped if "innate_effects" in d]


# --- #62's shape: a character with nothing gets no garbage file -------------

@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_paladin_or_ranger_title_with_no_innate_effects_gets_no_spc_file(
        shape):
    char = _neutral(shape.key, name="TESTER", innate_effects=[])
    rec, itm, spc, rep = dos.write(char)
    assert len(rec) == shape.record_size
    assert itm == b""
    assert spc == b""
    assert not [d for d in rep.dropped if "innate_effects" in d]


# --- the actual bug: a C64 record converted straight to DOS -----------------

def _c64_disk(name: str):
    root = specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = list((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]


def _c64_party(path):
    disk = D64.open(str(path))
    game, sg0, sg1 = load_save(disk)
    out = []
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        out.append(c64_codec.read(slot.record, roster=block, game=game,
                                  source=f"slot {slot.index}"))
    return out


def test_a_c64_silver_blades_paladin_and_ranger_convert_with_their_own_ids():
    """The scenario #388 opens with, reproduced end to end: a C64 party is
    read and handed straight to `dos.write`, the way `editor/convert.py`
    does.  `WISH-SPEC-ssb-d-engine-resave.D64` is the C64 save the C64 engine
    itself wrote (its own `provenance.toml`), and the two nine-byte records
    below are the ones #388's own issue body quoted out of the shipped DOS
    `CHRDATA1.SFX`/`CHRDATA2.SFX`.
    """
    party = _c64_party(_c64_disk("ssb-d-engine-resave"))
    by_name = {c.get("name").strip(): c for c in party}
    assert {"PAINE", "Guy de Valois"} <= set(by_name)

    _rec, _itm, spc, rep = dos.write(by_name["PAINE"])
    assert spc == bytes.fromhex("690000ff0000000000")
    assert not [d for d in rep.dropped if "innate_effects" in d]

    _rec, _itm, spc, rep = dos.write(by_name["Guy de Valois"])
    assert spc == bytes.fromhex("080000ff0000000000")
    assert not [d for d in rep.dropped if "innate_effects" in d]


# --- goldbox/amiga.py's write_later, read-only: no double, no drop ---------
#
# `goldbox.amiga.write_later` calls `goldbox.dos.write` for its DOS half and
# builds its own Amiga effect chain separately, from the neutral record
# rather than from `dos.write`'s `.SPC` payload
# (`goldbox.amiga.LATER_EFFECTS_FROM_NEUTRAL`) -- precisely so a dwarf's
# racial bonus is not written twice.  `_later_effect_nodes` reads
# `innate_effects` and `granted_effects` directly and does not consult
# `dos.INNATE_EFFECTS` or `_innate_effects` at all, so #388's fix changes
# which of those two neutral fields a paladin's or a ranger's id lands in
# but not what `write_later` does with it.  Confirmed by reverting the fix
# (`goldbox/dos.py` copied aside, `#388`'s change removed, `__pycache__`
# cleared) and comparing: the Amiga block's own effect bytes are identical
# either way; what changes is that `rep.dropped`, copied from `dos.write`'s
# own report, carried a spurious "innate_effects ... not one of the ids"
# line before the fix even though the id reached the Amiga block correctly
# -- a false drop this fix also removes, on a file this issue does not own.

@pytest.mark.parametrize("key, effect", [
    (CURSE.key, PALADIN_EFFECT), (CURSE.key, RANGER_EFFECT[CURSE.key]),
    (SSB.key, PALADIN_EFFECT), (SSB.key, RANGER_EFFECT[SSB.key]),
])
def test_write_later_writes_the_id_once_and_drops_nothing(key, effect):
    from goldbox import amiga

    char = _neutral(key, name="TESTER", innate_effects=[effect])
    built, rep = amiga.write_later(char)
    assert built.effects == (amiga.amiga_por_effect_from_dos(
        _innate_node(effect)),)
    assert not [d for d in rep.dropped if "innate_effects" in d]


# --- round trip, masked by the writer's own declared lists, not the diff ----

CLASS_SPECIMENS = ("curse-234-before", "curse-234-party-dualclassed",
                   "ssb-234-before", "ssb-234-party-pair",
                   "ssb-slote-zeroed140")


def test_the_paladin_and_ranger_specimens_round_trip_masked_by_the_declared_lists():
    """DOS -> `to_neutral` -> `write`, over every record in the five
    specimens #388's own evidence rests on, byte for byte outside the
    writer's own declared mask (`.claude/rules/conversions.md`: masked by
    the declared list, never by the diff).

    Before #388 these characters already round-tripped -- their `.SPC` node
    took the `granted_effects` path instead of `innate_effects` -- so this is
    not the regression test on its own; `test_a_c64_silver_blades_paladin_
    and_ranger_convert_with_their_own_ids` above is, since a C64 source has
    no `granted_effects` field to fall back to.  This test is what proves the
    reclassification changed no byte a player would see.

    MALACHITE is the one already-declared exception, and only in that field:
    `test_every_engine_written_record_of_a_later_title_round_trips` in
    `tests/test_doslatertitles.py` has it too, `field_83_87`'s treasure-share
    bit (#304), unrelated to an innate effect.
    """
    seen = 0
    checked_paladin = checked_ranger = False
    for name in CLASS_SPECIMENS:
        where = specimen(name)
        for path in sorted(where.glob("CHRDAT*.SAV")):
            char = dos.read_character(path)
            if char.shape not in (CURSE, SSB):
                continue
            rec, _itm, _spc, _rep = dos.write(dos.to_neutral(char))
            original = char.to_bytes()
            mask = _mask(char.shape, original)
            differs = {i for i in range(len(original))
                      if original[i] != rec[i] and i not in mask}
            if differs:
                fields = {f.name for f in dos_layout.LAYOUTS[char.shape.key]
                          for i in differs if f.offset <= i < f.end}
                assert fields == {"field_83_87"}, (char.name, path,
                                                    sorted(differs))
                assert char.name == "MALACHITE", (char.name, path)
            seen += 1
            ids = set(char.effect_ids)
            checked_paladin |= PALADIN_EFFECT in ids
            checked_ranger |= any(e in ids for e in RANGER_EFFECT.values())
    assert seen >= 5, seen
    assert checked_paladin, "no specimen here carried the paladin's id"
    assert checked_ranger, "no specimen here carried a ranger's id"
