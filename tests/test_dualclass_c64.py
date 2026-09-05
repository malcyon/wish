"""The C64 half of a dual-classed character's former class (#256, #234).

`goldbox/c64_codec.py`'s reader used to key `former_levels` by the raw
`dual_class_slot` number rather than the class name every writer looks up
through `LEVEL_FIELDS` -- so a C64-to-C64 round trip could never find its own
class back -- and it gated on `dual_class_slot != 0xFF` where the engine's own
sentinel is `dual_class_level == 0` (`GEN $18EB`), which read every ordinary
Curse or Silver Blades record as `{0: 0}`. `READ_DROPPED` also still reported
the pair dropped in the same read that converted it. This file is the
regression test for all three, plus the writer's rule for whether the old
class has been regained (`GEN $20A3`, PROBABLE).

Synthetic records are built with `goldbox.record.CharacterRecord.blank()` and
`.set`, so they run everywhere with no game data in them. The last two tests
are specimen-backed: `WISH-SPEC-curse-dual-classed` is PHILIPPE, a magic-user
6 who dual-classed into fighter at Curse's own training hall for
`#234 (A dual-classed Curse or Silver Blades character converted to DOS loses
the class he trained out of)`, watched being written. They skip without the
specimen tree.
"""

from __future__ import annotations

import gamedata
import pytest

from goldbox import c64_codec, neutral
from goldbox.d64 import D64
from goldbox.games import (
    CURSE_OF_THE_AZURE_BONDS,
    POOL_OF_RADIANCE,
    SECRET_OF_THE_SILVER_BLADES,
)
from goldbox.record import CharacterRecord
from goldbox.savegame import load_save

CURSE = CURSE_OF_THE_AZURE_BONDS
SSB = SECRET_OF_THE_SILVER_BLADES
POOL = POOL_OF_RADIANCE


def _c64_record(**fields) -> CharacterRecord:
    """A blank 580-byte record with the named C64 fields set."""
    rec = CharacterRecord.blank()
    for name, value in fields.items():
        rec.set(name, value)
    return rec


def _neutral(game, **values) -> neutral.NeutralCharacter:
    char = neutral.NeutralCharacter("test", source="built here", game=game)
    for name, value in values.items():
        char.set(name, value, "built here")
    return char


# --- the reader: keyed by name, gated by the engine's own sentinel ---------

def test_a_curse_record_with_the_pair_set_reads_the_class_by_name():
    """Slot 6 is paladin (`_field("level_paladin").offset - level_magic_user
    == 6`); the old code read `{6: 5}`."""
    rec = _c64_record(dual_class_slot=6, dual_class_level=5)
    out = c64_codec.read(rec, game=CURSE)
    assert out.get("former_levels") == {"paladin": 5}


def test_dual_class_level_zero_is_the_sentinel_not_slot_zero():
    """Slot 0 is magic-user, a real class -- reading every ordinary record's
    `dual_class_slot` (0) as a slot number regardless of `dual_class_level`
    is the old bug, and it set `{0: 0}` on every Curse record that had never
    been near a training hall. `former_levels` is `{}` rather than absent,
    the neutral convention for a title that keeps the field at all
    (`goldbox/neutral.py`)."""
    rec = _c64_record(dual_class_slot=0, dual_class_level=0)
    out = c64_codec.read(rec, game=CURSE)
    assert out.get("former_levels") == {}
    assert "former_levels" in out


def test_silver_blades_reads_the_pair_the_same_way():
    """`SILVER_BLADES_RECORD.dual_class` is True (#224); slot 7 is ranger."""
    rec = _c64_record(dual_class_slot=7, dual_class_level=8)
    out = c64_codec.read(rec, game=SSB)
    assert out.get("former_levels") == {"ranger": 8}


def test_pool_of_radiance_never_reads_a_dual_class_pair():
    """`0xFF, 0xFF` is the NPC fill `goldbox/layout.py`'s note on
    `region_0e4` describes, not a slot number -- Pool of Radiance's own GEN
    never references either byte. The shape gate has to be what stops this,
    not the sentinel, since `0xFF` is non-zero."""
    rec = _c64_record(dual_class_slot=0xFF, dual_class_level=0xFF)
    out = c64_codec.read(rec, game=POOL)
    assert "former_levels" not in out
    assert out.warnings == []


@pytest.mark.parametrize("slot", (4, 5))
def test_a_slot_naming_no_dual_classable_class_warns_rather_than_guesses(slot):
    """Slot 4 is `level_knight` in `LEVEL_FIELDS` -- the Krynn name for the
    same byte the Realms titles use for druid (`goldbox/layout.py`'s note on
    `level_knight`) -- and slot 5 is unused in both numberings. No Curse or
    Silver Blades training hall ever offers a human DRUID or MONK, so neither
    is a class a dual-classed human can have left, and the reader must say so
    rather than call it `knight`."""
    rec = _c64_record(dual_class_slot=slot, dual_class_level=3)
    out = c64_codec.read(rec, game=CURSE)
    assert out.get("former_levels") == {}
    assert len(out.warnings) == 1
    assert str(slot) in out.warnings[0]


# --- the round trip: the fix for #256 and #234 -----------------------------

def test_curse_round_trips_the_pair_with_no_dropped_line():
    """Read then write puts `6, 5` back at `0x0B9`/`0x0BA`, and the report
    carries neither `NO_DUAL_CLASS_SLOT` nor a stale `READ_DROPPED` line about
    the pair -- both present before the fix."""
    rec = _c64_record(dual_class_slot=6, dual_class_level=5, class_bits=0x02)
    out = c64_codec.read(rec, game=CURSE)
    written, rep = c64_codec.write(out)
    assert written.get("dual_class_slot") == 6
    assert written.get("dual_class_level") == 5
    assert not any("dual" in d.lower() for d in rep.dropped)


def test_silver_blades_round_trips_the_pair_too():
    rec = _c64_record(dual_class_slot=7, dual_class_level=8, class_bits=0x01)
    out = c64_codec.read(rec, game=SSB)
    written, rep = c64_codec.write(out)
    assert written.get("dual_class_slot") == 7
    assert written.get("dual_class_level") == 8
    assert not any("dual" in d.lower() for d in rep.dropped)


# --- the writer's regained rule: PROBABLE on GEN $20A3 ----------------------

def test_the_old_class_is_regained_once_the_new_one_passes_it():
    """DOS never stores this -- `class_levels[old]` reads zero for good on
    both of `#234`'s own watched specimens -- so a DOS-sourced neutral record
    always reports `levels["paladin"] == 0`, and the C64 writer has to derive
    whether the old class is back from `level` against `former_levels` rather
    than trust that zero."""
    char = _neutral(CURSE, former_levels={"paladin": 5}, level=9,
                    levels={"paladin": 0, "cleric": 9})
    written, _ = c64_codec.write(char)
    assert written.get("level_paladin") == 5


def test_the_old_class_stays_frozen_below_the_threshold():
    char = _neutral(CURSE, former_levels={"paladin": 5}, level=3,
                    levels={"paladin": 0, "cleric": 3})
    written, _ = c64_codec.write(char)
    assert written.get("level_paladin") == 0


# --- the layout-wide account: no field silently unaccounted -----------------

def test_dual_class_pair_is_a_read_target_not_only_a_drop():
    assert "dual_class_slot" in c64_codec.READ_TARGETS
    assert "dual_class_level" in c64_codec.READ_TARGETS
    assert not any(name in ("dual_class_slot", "dual_class_level")
                   for name, _ in c64_codec.READ_DROPPED)


# --- the specimen: PHILIPPE, watched dual-classing at Curse's own hall -----

def _curse_dual_classed_disk():
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted((root / "por-c64").glob(
        "WISH-SPEC-curse-dual-classed.[dD]64"))
    if not found:
        pytest.skip("needs specimen WISH-SPEC-curse-dual-classed")
    path = found[0]
    prov = path.with_suffix(".provenance.toml")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail(f"WISH-SPEC-curse-dual-classed: {path.name} has changed "
                    f"since it was recorded; run tools/specimens.py check")
    return path


def test_philippe_reads_the_pair_by_name():
    """PHILIPPE, one action past `HUMAN CHANGE CLASS`: magic-user 6 into
    fighter. `dual_class_slot` 0 (magic-user), `dual_class_level` 6,
    `level_magic_user` zeroed, `class_bits` holding fighter's bit alone --
    `#234`'s own worked example, watched being written."""
    disk = D64.open(str(_curse_dual_classed_disk()))
    game, sg0, sg1 = load_save(disk)
    slot = sg0.slots[0]
    assert str(slot.record.name) == "PHILIPPE"

    out = c64_codec.read(slot.record, roster=sg1.roster(0), game=game)
    assert out.get("former_levels") == {"magic-user": 6}
    assert out.get("levels")["magic-user"] == 0
    assert out.get("levels")["fighter"] == 1
    assert out.get("class_bits") == 0x08
    assert out.warnings == []


def test_philippe_round_trips_the_pair_byte_for_byte():
    disk = D64.open(str(_curse_dual_classed_disk()))
    game, sg0, _sg1 = load_save(disk)
    slot = sg0.slots[0]

    out = c64_codec.read(slot.record, game=game)
    written, _ = c64_codec.write(out)
    assert written.get("dual_class_slot") == slot.record.get("dual_class_slot")
    assert (written.get("dual_class_level")
            == slot.record.get("dual_class_level"))
    assert (written.get("level_magic_user")
            == slot.record.get("level_magic_user"))
    assert written.get("level_fighter") == slot.record.get("level_fighter")
