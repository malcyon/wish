"""What reaches the C64's ten trait slots, from both neutral effect lists.

#394 (A DOS Curse paladin's Protection from Evil sometimes does not reach the
C64, and two specimens disagree on why): a paladin converted from DOS is
supposed to arrive carrying effect id 8, Protection from Evil, in one of the
ten bytes at C64 record `0x0AD` (`docs/171-c64-trait-slots.md`).  Two C64
specimens disagreed about whether he does, and the reason turned out to be the
age of the writer rather than anything in it -- so what these tests hold down
is the property the disagreement was about: **an effect id the source record
holds permanently is in one of the ten slots afterwards, whichever of the two
neutral lists it travelled in.**

`goldbox.c64_codec.write` fills the block from both ends at once --
`innate_effects` from slot 0 upward, the way the engine's own creation seeds a
race, and `granted_effects` from slot 9 down, the way `SPELLE04 $ADD4` scans
for a free slot when an item is readied.  Which list an id lands in is
`goldbox.dos.to_neutral`'s classification and it changes the *position*, not
whether the id crosses; `LIBRARY $402D` reads all ten regardless of holes, and
`docs/171-c64-trait-slots.md` watched an id staged into slot 9 dispatch its
handler.  A test that only looked at `innate_effects` would pass while a
paladin arrived with nothing.

The specimen-backed half runs the DOS half of the conversion for real over
every DOS save in `$WISH_SPECIMENS` and skips without the tree, which is what
CI has.  `tools/traitcross.py` is the same walk with a printed table.
"""

from __future__ import annotations

import pytest
from gamedata import needs_specimens, specimen, specimen_root

from goldbox import c64_codec, dos_codec, dos_port, neutral

CURSE = dos_port.CURSE_OF_THE_AZURE_BONDS
POOL = dos_port.POOL_OF_RADIANCE

#: The ten trait slots, C64 record 0x0AD.
SLOTS = 0x0AD
COUNT = 10

#: Protection from Evil, a paladin's in Curse and in Silver Blades (#388).
PALADIN_EFFECT = 8


def _slots(rec) -> list[int]:
    return list(bytes(rec.to_bytes())[SLOTS:SLOTS + COUNT])


def _neutral(key, **fields) -> neutral.NeutralCharacter:
    char = neutral.NeutralCharacter("test", source="made up", game=key)
    for name, value in fields.items():
        char.set(name, value, "made up for the test")
    return char


def _innate_node(effect_id: int) -> bytes:
    """One nine-byte effect record in the permanent shape: duration zero."""
    return bytes((effect_id,)) + dos_codec.INNATE_PAYLOAD + dos_codec.EFFECT_NEXT_NULL


def _dos_record(shape, effects) -> dos_codec.DosCharacter:
    return dos_codec.DosCharacter(bytes(shape.record_size), effects=effects,
                            deltas=shape)


# --- the two lists, and the ends of the block they fill from -----------------

def test_a_curse_paladins_protection_from_evil_reaches_a_trait_slot():
    """The scenario #394 opens with, from the DOS record inward: a paladin's
    own effect record becomes a non-zero trait slot, and nothing tells the
    player anything was lost."""
    char = _dos_record(CURSE, [_innate_node(PALADIN_EFFECT)])
    rec, rep = c64_codec.write(dos_codec.to_neutral(char))
    assert PALADIN_EFFECT in _slots(rec)
    assert not [d for d in rep.dropped if "effect" in d.lower()]


def test_an_id_the_neutral_record_calls_granted_still_reaches_a_slot():
    """The hypothesis #394 was filed against, pinned so it cannot come back.

    Before #388 a Curse paladin's id 8 was classified `granted_effects`
    rather than `innate_effects`, and the guess was that the reclassification
    is what lost it.  It is not: `write` fills the block from both lists, so
    an id in either one is in the ten bytes afterwards.  This is the assertion
    that says so -- and it is the one the writer of 2026-09-05 02:08 fails,
    because it had no granted path at all.
    """
    char = _neutral(CURSE.key, name="TESTER", innate_effects=[],
                    granted_effects=[_innate_node(PALADIN_EFFECT)])
    rec, _ = c64_codec.write(char)
    assert PALADIN_EFFECT in _slots(rec)


def test_the_two_lists_fill_the_block_from_opposite_ends():
    """Racial ids from slot 0 the way creation seeds them, item grants from
    slot 9 down the way `SPELLE04 $ADD4` scans -- and neither overwrites the
    other."""
    char = _neutral(POOL.key, name="TESTER", innate_effects=[90, 97],
                    granted_effects=[_innate_node(61), _innate_node(98)])
    rec, _ = c64_codec.write(char)
    assert _slots(rec) == [90, 97, 0, 0, 0, 0, 0, 0, 98, 61]


def test_an_id_in_either_list_survives_the_round_trip_back():
    """`c64_codec.read` strips the zeroes and gives every non-zero slot back
    as `innate_effects`, wherever in the block it sits -- so a granted id at
    slot 9 is not invisible to the reader either."""
    char = _neutral(POOL.key, name="TESTER", innate_effects=[90],
                    granted_effects=[_innate_node(61)])
    rec, _ = c64_codec.write(char)
    back = c64_codec.read(rec, game=POOL.key)
    assert sorted(back.get("innate_effects")) == [61, 90]


# --- the ceiling -------------------------------------------------------------

def test_eleven_ids_fill_every_slot_and_the_eleventh_is_dropped_silently():
    """Ten is the machine's number, not ours (`.claude/rules/conversions.md`),
    so the eleventh cannot be written.  #236 (A character converted to the
    C64 with more than ten innate effects loses the extra ones with no
    report) drafted a sentence for this; #399's own 950-character census
    found nobody reaching the ceiling for real (widest anywhere: 5), and
    Donald ruled the sentence unneeded -- "I agree that we do not need the
    sentences." -- so the eleventh is still cut off, just not named."""
    char = _neutral(POOL.key, name="TESTER",
                    innate_effects=list(range(1, 12)))
    rec, rep = c64_codec.write(char)
    assert _slots(rec) == list(range(1, 11))
    assert not [w for w in rep.warnings if "on their own" in w]


def test_a_grant_with_no_free_slot_left_is_dropped_silently_too():
    """The other half of the same ceiling: ten racial ids and a ring."""
    char = _neutral(POOL.key, name="TESTER",
                    innate_effects=list(range(1, 11)),
                    granted_effects=[_innate_node(61)])
    rec, rep = c64_codec.write(char)
    assert _slots(rec) == list(range(1, 11))
    assert not [w for w in rep.warnings if "items grant" in w]


# --- every DOS record on this machine ----------------------------------------

def _permanent_ids(char: dos_codec.DosCharacter) -> list[int]:
    """The effect ids the engine's expiry pass never removes -- duration zero
    at bytes 1-2, `docs/162-spc-permanence.md`.  A running spell counting down
    is deliberately not converted and is not one of these."""
    return [e[0] for e in char.effects
            if int.from_bytes(e[1:3], "little") == 0]


@needs_specimens
def test_no_permanent_effect_id_in_the_specimen_tree_fails_to_cross():
    """The census #394 asks for, over every DOS save we watched being
    written: 236 records, 128 of them carrying at least one effect, and no id
    that should have crossed missing from the ten bytes.

    Sixteen of those records are the two classes the older half of #394's own
    disagreement is about -- ten paladins carrying id 8 across Curse and
    Silver Blades, and six rangers carrying 134 or 105.
    """
    from tools import specimens

    root = specimen_root()
    checked = carriers = 0
    lost: list[str] = []
    for folder in sorted(p for p in root.rglob("*") if p.is_dir()):
        records = sorted(folder.glob("CHRDAT*.SAV")) + \
            sorted(folder.glob("*.CHA"))
        if not records:
            continue
        # Hashed here rather than through `gamedata.specimen`, which resolves
        # a name under `por-*` only: the DOS records of the later titles sit
        # in `coab-dos` and `ssb-dos` as well, and a specimen whose bytes have
        # moved must fail rather than quietly leave the census short.
        prov = folder / "provenance.toml"
        assert prov.is_file(), f"{folder}: no provenance.toml -- not a specimen"
        for filename, expected in \
                specimens.read_provenance(prov).get("sha256", {}).items():
            actual = specimens.sha256_file(folder / filename)
            assert actual == expected, (
                f"{folder.name}/{filename} has changed -- recorded "
                f"{expected[:12]}, now {actual[:12]}; run tools/specimens.py "
                f"check")
        for path in records:
            char = dos_codec.read_character(path)
            rec, _ = c64_codec.write(dos_codec.to_neutral(char))
            slots = _slots(rec)
            checked += 1
            ids = _permanent_ids(char)
            carriers += bool(ids)
            lost += [f"{folder.name}/{path.name}: {i}" for i in ids
                     if i not in slots]
    assert checked >= 200, f"only {checked} DOS records found under {root}"
    assert carriers >= 100, f"only {carriers} of {checked} carry an effect"
    assert not lost, f"{len(lost)} permanent effect ids reached no slot: {lost}"


@needs_specimens
@pytest.mark.parametrize("record", ("CHRDATJ1.SAV", "CHRDATJ2.SAV"))
def test_both_paladins_of_the_disagreeings_own_source_arrive_with_id_8(record):
    """`WISH-SPEC-curse-131-dualclassed-in-area-1` is the DOS save the
    surviving half of #394's disagreement was converted from, and MATHEW and
    MARK are its two paladins.  Each holds one `.FX` record, `08 00 00 FF 00`,
    and each arrives with 8 in the block."""
    where = specimen("curse-131-dualclassed-in-area-1")
    char = dos_codec.read_character(where / record)
    assert [e[0] for e in char.effects] == [PALADIN_EFFECT]
    rec, rep = c64_codec.write(dos_codec.to_neutral(char))
    assert _slots(rec)[0] == PALADIN_EFFECT
    assert not [d for d in rep.dropped if "effect" in d.lower()]
