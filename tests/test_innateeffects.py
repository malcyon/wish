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
  route: the two titles' own C64 seed tables (`GEN $2515` in Curse, `GEN
  $0FF0` in Silver Blades) agree on the paladin's at 45 and disagree on the
  ranger's, 134 against 105 -- the same two numbers this file's own `.SPC`
  evidence lands on, by a different route.  Those seeds go into the record's
  ten trait slots and are not, as this file used to say, a combat trait
  computed live rather than stored, which is why the 45 has to be translated
  on the way to DOS: see the last section of this file, and #481.

Every one of the nine-byte records above reads duration zero and
`INNATE_PAYLOAD` in bytes 1-4, which is the shape `docs/162-spc-permanence.md`
established for a record the engine's expiry pass never removes -- not a
`.SPC` record that just happens to share an id with a running effect.
"""

import pathlib

import pytest
from gamedata import specimen, specimen_root
from test_doslatertitles import _mask

from goldbox import c64_codec, c64_port, dos_codec, dos_port, neutral
from goldbox.d64 import D64
from goldbox.savegame import load_save
from tools import gamedisks

CURSE = dos_port.CURSE_OF_THE_AZURE_BONDS
SSB = dos_port.SECRET_OF_THE_SILVER_BLADES
POOL = dos_port.POOL_OF_RADIANCE

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


def _record(shape, effects) -> dos_codec.DosCharacter:
    """An all-zero record of `shape` carrying only the given `.SPC` nodes."""
    return dos_codec.DosCharacter(bytes(shape.record_size), effects=effects,
                            deltas=shape)


def _innate_node(effect_id: int) -> bytes:
    """One nine-byte `.SPC` node in `INNATE_PAYLOAD`'s own shape: duration
    zero, `FF 00` at bytes 3-4, next pointer NULL."""
    return bytes((effect_id,)) + dos_codec.INNATE_PAYLOAD + dos_codec.EFFECT_NEXT_NULL


# --- the tables themselves ----------------------------------------------

def test_pool_of_radiance_is_unchanged():
    """The control #388 asks for: Pool of Radiance's own set is exactly what
    it was, so its pane stays empty."""
    assert dos_codec.INNATE_EFFECTS == frozenset(
        {18, 26, 47, 48, 90, 97, 107, 124})
    assert PALADIN_EFFECT not in dos_codec.INNATE_EFFECTS
    assert RANGER_EFFECT[SSB.key] not in dos_codec.INNATE_EFFECTS
    assert RANGER_EFFECT[CURSE.key] not in dos_codec.INNATE_EFFECTS


def test_a_title_not_listed_gets_pool_of_radiances_set():
    assert dos_codec._innate_effects(POOL.key) is dos_codec.INNATE_EFFECTS
    assert dos_codec._innate_effects(None) is dos_codec.INNATE_EFFECTS
    assert dos_codec._innate_effects("some-title-nobody-has-measured") \
        is dos_codec.INNATE_EFFECTS


def test_the_two_later_titles_add_only_their_own_two_ids():
    assert dos_codec.INNATE_EFFECTS_CURSE - dos_codec.INNATE_EFFECTS == {8, 134}
    assert dos_codec.INNATE_EFFECTS_SILVER_BLADES - dos_codec.INNATE_EFFECTS == {8, 105}
    assert dos_codec._innate_effects(CURSE.key) == dos_codec.INNATE_EFFECTS_CURSE
    assert dos_codec._innate_effects(SSB.key) == dos_codec.INNATE_EFFECTS_SILVER_BLADES


def test_a_titles_ranger_id_is_not_the_others():
    """134 and 105 are two different numbers for two different titles, and
    neither title's set is widened by the other's."""
    assert RANGER_EFFECT[CURSE.key] not in dos_codec.INNATE_EFFECTS_SILVER_BLADES
    assert RANGER_EFFECT[SSB.key] not in dos_codec.INNATE_EFFECTS_CURSE


# --- the read side: to_neutral classifies the id as innate, not granted -----

@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_paladins_protection_from_evil_reads_as_innate(shape):
    char = _record(shape, [_innate_node(PALADIN_EFFECT)])
    out = dos_codec.to_neutral(char)
    assert out.get("innate_effects") == [PALADIN_EFFECT]
    assert "granted_effects" not in out


@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_rangers_own_id_reads_as_innate(shape):
    effect = RANGER_EFFECT[shape.key]
    char = _record(shape, [_innate_node(effect)])
    out = dos_codec.to_neutral(char)
    assert out.get("innate_effects") == [effect]
    assert "granted_effects" not in out


def test_pool_of_radiance_still_reads_the_paladins_id_as_granted():
    """The read-side control: nothing changed for the title the set was
    measured on.  Before #388 this was the *only* way an id 8 record
    survived a DOS -> DOS round trip, and it still is here."""
    char = _record(POOL, [_innate_node(PALADIN_EFFECT)])
    out = dos_codec.to_neutral(char)
    assert out.get("innate_effects") == []
    assert [bytes(g) for g in out.get("granted_effects")] == \
        [_innate_node(PALADIN_EFFECT)]


# --- the write side: dos.write no longer drops the two ids ------------------

@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_paladins_effect_reaches_the_spc_file(shape):
    char = _neutral(shape.key, name="TESTER",
                    innate_effects=[PALADIN_EFFECT])
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == _innate_node(PALADIN_EFFECT)
    assert not [d for d in rep.dropped if "innate_effects" in d]


@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_rangers_effect_reaches_the_spc_file(shape):
    effect = RANGER_EFFECT[shape.key]
    char = _neutral(shape.key, name="TESTER", innate_effects=[effect])
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == _innate_node(effect)
    assert not [d for d in rep.dropped if "innate_effects" in d]


def test_pool_of_radiance_still_drops_the_paladins_id():
    """The write-side control matching the read-side one above: #388 must
    not touch the title it was never wrong for."""
    char = _neutral(POOL.key, name="TESTER", innate_effects=[PALADIN_EFFECT])
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == b""
    assert [d for d in rep.dropped if "innate_effects" in d]


def test_a_curse_characters_own_ranger_id_still_drops_in_silver_blades():
    """134 is Curse's; asked to write it for Silver Blades, the writer still
    turns it away -- the fix is a title's own set, not a merge of both."""
    char = _neutral(SSB.key, name="TESTER",
                    innate_effects=[RANGER_EFFECT[CURSE.key]])
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == b""
    assert [d for d in rep.dropped if "innate_effects" in d]


# --- #62's shape: a character with nothing gets no garbage file -------------

@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_paladin_or_ranger_title_with_no_innate_effects_gets_no_spc_file(
        shape):
    char = _neutral(shape.key, name="TESTER", innate_effects=[])
    rec, itm, spc, rep = dos_codec.write(char)
    assert len(rec) == shape.record_size
    assert itm == b""
    assert spc == b""
    assert not [d for d in rep.dropped if "innate_effects" in d]


# --- the actual bug: a C64 record converted straight to DOS -----------------

def _c64_disk(name: str):
    """A named C64 specimen disk, wherever in the tree it sits.

    The search is every directory rather than `por-c64` alone: the tree grew
    `coab-c64` and `ssb-*` after this file was written, and the Curse disks
    #481 rests on are under `coab-c64` while the Silver Blades one #388 rests
    on is still under `por-c64`.
    """
    root = specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted(root.glob(f"*/WISH-SPEC-{name}.[dD]64"))
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

    _rec, _itm, spc, rep = dos_codec.write(by_name["PAINE"])
    assert spc == bytes.fromhex("690000ff0000000000")
    assert not [d for d in rep.dropped if "innate_effects" in d]

    _rec, _itm, spc, rep = dos_codec.write(by_name["Guy de Valois"])
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
    from goldbox import amiga_later, amiga_por

    char = _neutral(key, name="TESTER", innate_effects=[effect])
    built, rep = amiga_later.write_later(char)
    assert built.effects == (amiga_por.amiga_por_effect_from_dos(
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
            char = dos_codec.read_character(path)
            if char.shape not in (CURSE, SSB):
                continue
            rec, _itm, _spc, _rep = dos_codec.write(dos_codec.to_neutral(char))
            original = char.to_bytes()
            mask = _mask(char.shape, original)
            differs = {i for i in range(len(original))
                      if original[i] != rec[i] and i not in mask}
            if differs:
                fields = {f.name for f in dos_port.LAYOUTS[char.shape.key]
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


# --- #481: a C64 source's paladin seed is 45 and DOS's effect is 8 ----------
#
# `#481 (A C64 Curse paladin converted to DOS loses Protection from Evil for
# good, because the C64 seeds it as trait 45 and DOS writes it as effect 8)`
# is the C64-source half of the loss #388 fixed for a DOS source.  A party
# read out of a DOS record already holds 8 and only the filter was wrong; a
# party read off a C64 disk holds **45**, which no per-title filter can help
# with, because the number itself has to change.
#
# Both later titles seed the same 45 -- Curse `GEN $2515` and Silver Blades
# `GEN $0FF0`, the same routine with the same `LDA #$2D` (`#484 (Does C64
# Silver Blades seed a paladin's Protection from Evil as trait 45, the way
# Curse does, so that direction loses it converting to DOS too?)`) -- and
# both DOS engines write 8, so `goldbox.dos.C64_CLASS_TRAITS` has one row
# each.  Neither ranger needs one: 134 is Curse's on both ports and 105 is
# Silver Blades' on both.

#: What the C64's own `GEN` seeds a paladin, in both later titles.
PALADIN_C64_TRAIT = 45


def _c64_neutral(game, **fields) -> neutral.NeutralCharacter:
    """A neutral character read, as far as the writer can tell, off a C64
    disk -- which is what makes the translation apply at all."""
    char = neutral.NeutralCharacter("C64", source="made up", game=game)
    for name, value in fields.items():
        char.set(name, value, "made up for the test")
    return char


def _innate_drops(rep) -> list[str]:
    return [d for d in rep.dropped if "innate_effects" in d]


# --- the table, and the bit it is guarded on --------------------------------

def test_both_later_titles_map_the_same_paladin_pair():
    """One row each, and the same row: the C64's 45 becomes DOS's 8 for a
    character carrying the paladin bit."""
    assert dos_codec.C64_CLASS_TRAITS[CURSE.key] == \
        ((dos_codec.PALADIN_CLASS_BIT, PALADIN_C64_TRAIT, PALADIN_EFFECT),)
    assert dos_codec.C64_CLASS_TRAITS[SSB.key] == \
        ((dos_codec.PALADIN_CLASS_BIT, PALADIN_C64_TRAIT, PALADIN_EFFECT),)


def test_the_guarded_bit_is_the_paladins_in_both_titles_own_tables():
    """`PALADIN_CLASS_BIT` is a number in this module, and the tables it has
    to agree with are `goldbox.games`'.  A renumbering that left this behind
    would silently stop translating, or start translating a fighter's ids."""
    for game in (c64_port.CURSE_OF_THE_AZURE_BONDS,
                 c64_port.SECRET_OF_THE_SILVER_BLADES):
        assert dict(game.class_bits)[dos_codec.PALADIN_CLASS_BIT] == "paladin"
    assert "paladin" not in dict(c64_port.POOL_OF_RADIANCE.class_bits).values()


def test_pool_of_radiance_has_no_row_and_translates_nothing():
    """Measured rather than assumed (#484): Pool of Radiance's `GEN` never
    reads the paladin or ranger level byte and the immediate `A9 2D` is
    nowhere in its overlay, so a Pool of Radiance 45 is somebody's item power
    and stays one."""
    assert POOL.key not in dos_codec.C64_CLASS_TRAITS
    assert dos_codec._from_c64_class_traits(
        POOL.key, dos_codec.PALADIN_CLASS_BIT, [PALADIN_C64_TRAIT]) \
        == [PALADIN_C64_TRAIT]
    assert dos_codec._from_c64_class_traits(None, 0xFF, [PALADIN_C64_TRAIT]) \
        == [PALADIN_C64_TRAIT]


# --- the write side, synthetic: every title runs this without disks ---------

@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_c64_paladins_seed_reaches_the_spc_file_as_the_dos_id(shape):
    """The bug itself: 45 in, `08 00 00 FF 00` + a NULL next pointer out, and
    nothing reported."""
    char = _c64_neutral(shape.key, name="TESTER",
                        class_bits=dos_codec.PALADIN_CLASS_BIT,
                        innate_effects=[PALADIN_C64_TRAIT])
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == _innate_node(PALADIN_EFFECT)
    assert _innate_drops(rep) == []


@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_c64_cleric_carrying_the_same_id_gains_no_paladins_effect(shape):
    """The guard, and the assertion this fix would be dangerous without.

    A C64 record's ten trait slots hold racial seeds, item grants and the
    paladin's own seed in one namespace with no byte saying which is which,
    so the reader hands every id it finds to `innate_effects`.  On the DOS
    side 45 is a live id meaning a Protection from Evil 10' Radius somebody
    **cast** -- two DOS Curse records carry it for FLORENTZ, a human cleric.
    Translating without asking the class would give this cleric a paladin's
    permanent effect.
    """
    char = _c64_neutral(shape.key, name="TESTER", class_bits=2,
                        innate_effects=[PALADIN_C64_TRAIT])
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == b""
    assert _innate_drops(rep), "a cleric's 45 must still be reported"


@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_cleric_paladin_is_still_a_paladin(shape):
    """`class_bits` is a mask and the guard is a bit test, not equality: two
    of the five C64 Curse specimens carrying this are multi-classed, MARK at
    66 (cleric and paladin) and MATHEW at 72 (fighter and paladin)."""
    for bits in (2 | dos_codec.PALADIN_CLASS_BIT, 8 | dos_codec.PALADIN_CLASS_BIT):
        char = _c64_neutral(shape.key, name="TESTER", class_bits=bits,
                            innate_effects=[PALADIN_C64_TRAIT])
        _rec, _itm, spc, rep = dos_codec.write(char)
        assert spc == _innate_node(PALADIN_EFFECT), bits
        assert _innate_drops(rep) == [], bits


@pytest.mark.parametrize("held", [[45, 8], [8, 45]], ids=["45 first", "8 first"])
@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_paladin_holding_both_ids_gets_one_record(shape, held):
    """A paladin Wish converted to the C64 arrives holding 8 and keeps it, and
    `GEN $0FF0` removes only 45 and 105 before re-seeding, so a C64 record can
    legitimately hold both ids for one effect.  He crosses back with one
    `.SPC` record, not two, in either order."""
    char = _c64_neutral(shape.key, name="TESTER",
                        class_bits=dos_codec.PALADIN_CLASS_BIT,
                        innate_effects=held)
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == _innate_node(PALADIN_EFFECT)
    assert _innate_drops(rep) == []


@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_dos_source_carrying_45_is_not_translated(shape):
    """The port control.  45 read out of a DOS record is a running spell or
    an item power whatever the character's class -- DOS writes 8 for the
    innate one -- so nothing about a DOS source changes here."""
    char = _neutral(shape.key, name="TESTER",
                    class_bits=dos_codec.PALADIN_CLASS_BIT,
                    innate_effects=[PALADIN_C64_TRAIT])
    char.port = "DOS"
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == b""
    assert _innate_drops(rep)


@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_a_c64_paladins_other_ids_are_untouched(shape):
    """Only the mapped id moves.  107 is the elf's racial seed and is the
    same number on both ports, so it comes through beside the paladin's in
    the order the trait slots held them."""
    char = _c64_neutral(shape.key, name="TESTER",
                        class_bits=dos_codec.PALADIN_CLASS_BIT,
                        innate_effects=[PALADIN_C64_TRAIT, 107])
    _rec, _itm, spc, rep = dos_codec.write(char)
    assert spc == _innate_node(PALADIN_EFFECT) + _innate_node(107)
    assert _innate_drops(rep) == []


@pytest.mark.parametrize("shape", [CURSE, SSB], ids=lambda s: s.key)
def test_the_report_says_the_id_was_translated(shape):
    """Every byte of the output is justified in the report, so the byte that
    changed number says which number it came from -- a reader of the report
    would otherwise see an 8 attributed to a record that holds 45."""
    char = _c64_neutral(shape.key, name="TESTER",
                        class_bits=dos_codec.PALADIN_CLASS_BIT,
                        innate_effects=[PALADIN_C64_TRAIT])
    rec, itm, _spc, rep = dos_codec.write(char)
    line = rep.sources[len(rec) + len(itm)]
    assert "45" in line, line
    assert "effect 8" in line, line


# --- the write side, on records the two engines themselves wrote ------------

def test_a_c64_curse_paladin_converts_with_protection_from_evil():
    """`WISH-SPEC-curse-party-with-items` is the C64 game's own
    `ENCAMP > SAVE` of the shipped Tilverton party after shopping, made under
    VICE by `tools/curserun.py` with `edited_afterwards = false` -- it never
    went through Wish.  Its PALADIN carries trait 45 and its RANGER 134, and
    the ranger is the control: his id is the same number on both ports and
    must arrive unchanged.
    """
    party = _c64_party(_c64_disk("curse-party-with-items"))
    by_name = {c.get("name").strip(): c for c in party}
    assert {"PALADIN", "RANGER"} <= set(by_name)

    paladin = by_name["PALADIN"]
    assert paladin.get("class_bits") & dos_codec.PALADIN_CLASS_BIT
    assert PALADIN_C64_TRAIT in paladin.get("innate_effects")
    _rec, _itm, spc, rep = dos_codec.write(paladin)
    assert spc == bytes.fromhex("080000ff0000000000")
    assert _innate_drops(rep) == []

    _rec, _itm, spc, rep = dos_codec.write(by_name["RANGER"])
    assert spc == _innate_node(RANGER_EFFECT[CURSE.key])
    assert _innate_drops(rep) == []


def test_every_c64_curse_specimen_carrying_the_seed_converts_it():
    """The sample size, and the reason one specimen was not enough: a drop
    line is composed only for a field the character actually carries, so a
    party with no paladin in it reports nothing and looks like proof.  Five
    of the ten C64 Curse specimens on this machine carry a paladin with trait
    45, and MARK at `class_bits` 66 and MATHEW at 72 are multi-classed.
    """
    names = ("curse-party-with-items", "curse-409-regained-paladin",
             "curse-dual-classed", "curse-dualclass-trained",
             "curse-trained-party")
    seen = 0
    for name in names:
        for char in _c64_party(_c64_disk(name)):
            if PALADIN_C64_TRAIT not in (char.get("innate_effects") or []):
                continue
            assert char.get("class_bits") & dos_codec.PALADIN_CLASS_BIT, char.get("name")
            _rec, _itm, spc, rep = dos_codec.write(char)
            assert spc[:9] == bytes.fromhex("080000ff0000000000"), char.get("name")
            assert _innate_drops(rep) == [], char.get("name")
            seen += 1
    assert seen == 6, seen


def test_a_c64_silver_blades_paladin_converts_with_protection_from_evil():
    """The Silver Blades half, and it has to come off the player's own game
    disk rather than the specimen tree: every C64 Silver Blades specimen here
    descends from a DOS record through Wish and already holds 8, which is
    why `tools/convertdrops.py` reported this direction clean over six of
    them while the loss was real.

    `SAVEDBASH` on the `SILVER-6` side is SSI's own pre-generated party.  It
    has no chain of custody -- `.claude/rules/testing.md` -- so it is a
    reproduction of the symptom and not the evidence for the id: the 45 and
    the 8 are both read out of the two engines' own code (#484).  GUY DE
    VALOIS carries `class_bits` 64 and trait 45; PAINE, the ranger, carries
    105 on both ports and is the control.
    """
    root = gamedisks.find(c64_port.SECRET_OF_THE_SILVER_BLADES.key)
    if root is None:
        pytest.skip("no Secret of the Silver Blades disks on this machine")
    side = pathlib.Path(root) / "SILVER-6.D64"
    if not side.exists():
        pytest.skip("no SILVER-6 side, which is where SAVEDBASH sits")

    by_name = {c.get("name").strip().upper(): c for c in _c64_party(side)}
    assert {"GUY DE VALOIS", "PAINE"} <= set(by_name)

    paladin = by_name["GUY DE VALOIS"]
    assert paladin.get("class_bits") & dos_codec.PALADIN_CLASS_BIT
    assert PALADIN_C64_TRAIT in paladin.get("innate_effects")
    _rec, _itm, spc, rep = dos_codec.write(paladin)
    assert spc == bytes.fromhex("080000ff0000000000")
    assert _innate_drops(rep) == []

    _rec, _itm, spc, rep = dos_codec.write(by_name["PAINE"])
    assert spc == _innate_node(RANGER_EFFECT[SSB.key])
    assert _innate_drops(rep) == []


def test_a_dos_paladin_crossing_to_the_c64_and_back_keeps_his_effect():
    """The round trip the fix must not have broken.  A DOS paladin's 8 is
    written into a C64 trait slot as 8, read back as 8, and written out as 8
    -- the translation collapses nothing on the way, because 8 is not a key.

    `WISH-SPEC-ssb-d-engine-resave` is exactly that record after the C64
    engine itself resaved it, and Guy de Valois still holds 8 alone: the
    re-seed that would have put a 45 beside it did not happen there, on this
    specimen or on the five other C64 specimens carrying a converted paladin.
    """
    party = _c64_party(_c64_disk("ssb-d-engine-resave"))
    by_name = {c.get("name").strip().upper(): c for c in party}
    paladin = by_name["GUY DE VALOIS"]
    assert paladin.get("innate_effects") == [PALADIN_EFFECT]
    _rec, _itm, spc, rep = dos_codec.write(paladin)
    assert spc == bytes.fromhex("080000ff0000000000")
    assert _innate_drops(rep) == []
