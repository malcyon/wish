"""The C64 reader's half of the class code repair (#310).

`goldbox.dos.write` already checks a record's class code against its own
classes and repairs it when the two contradict each other -- Curse of the
Azure Bonds' own `GEN $1939` stops maintaining `char_class` the moment a
character is trained. `tests/test_dosclasscode.py` covers that half.

This file is the other one: `goldbox.c64_codec.read` makes the same repair,
so the neutral record itself carries the right code, and so does anything
that reads it -- `goldbox/yaml_io.py`'s export, a C64-to-C64 round trip, and
any future writer that is not `goldbox.dos.write`. `docs/187-the-class-code-
byte.md` has the reading and the census; `goldbox/classcode.py` is the shared
rule both readers and the DOS writer now call.
"""

from __future__ import annotations

import gamedata
import pytest

from goldbox import c64_codec
from goldbox.d64 import D64
from goldbox.games import (
    CURSE_OF_THE_AZURE_BONDS,
    POOL_OF_RADIANCE,
    SECRET_OF_THE_SILVER_BLADES,
)
from goldbox.neutral import Provenance
from goldbox.record import CharacterRecord
from goldbox.savegame import load_save
from goldbox.yaml_io import export_save, import_into

CURSE = CURSE_OF_THE_AZURE_BONDS
POOL = POOL_OF_RADIANCE
SSB = SECRET_OF_THE_SILVER_BLADES


def _c64_record(**fields) -> CharacterRecord:
    """A blank 580-byte record with the named C64 fields set."""
    rec = CharacterRecord.blank()
    for name, value in fields.items():
        rec.set(name, value)
    return rec


def test_a_trained_curse_records_zeroed_code_reads_repaired():
    """TRAVIS's shape: a dwarf thief 6 / fighter 5 whose code reads 0, what
    Curse's own trainer leaves. The neutral record carries 14
    (fighter/thief), marked `COMPUTED` rather than `COPIED`, so anything
    reading the neutral value -- not only `goldbox.dos.write` -- sees the
    repaired class."""
    rec = _c64_record(class_bits=0x0C, char_class=0,
                      level_thief=6, level_fighter=5)
    out = c64_codec.read(rec, game=CURSE)
    assert out.get("char_class") == 14
    assert out.value("char_class").how is Provenance.COMPUTED
    assert "recomputed from class_bits" in out.value("char_class").origin


def test_silas_shape_reads_copied_and_unchanged():
    """SILAS, shipped with Pool of Radiance: `char_class` 2 and `class_bits`
    `0x08`, both fighter, with a thief 1 in his level array that neither
    knows about. The mask is the source, so his code is not touched -- it
    reads `COPIED`, the same as any record whose code already agrees."""
    rec = _c64_record(class_bits=0x08, char_class=2,
                      level_fighter=4, level_thief=1)
    out = c64_codec.read(rec, game=POOL)
    assert out.get("char_class") == 2
    assert out.value("char_class").how is Provenance.COPIED


def test_a_pool_of_radiance_records_disagreement_is_left_alone():
    """`DWARVEN FIGHTER`'s own shape -- fighter bits, cleric code -- is a
    disagreement Pool of Radiance's own NPCs ship with, not a Curse-trainer
    artifact (`docs/50-experiments.md`, "A losslessness bug, found by
    taking the NPCs seriously": *"if the game ships records like that, an
    editor that forces them into agreement cannot represent them."*)

    A blanket, title-agnostic repair fired on this shape too -- `class_bits`
    `0x08` (fighter) and `char_class` 0 (cleric) came back **2**, a
    fabricated code nobody wrote, because nothing distinguished Curse's
    stale byte from a title that never stops maintaining its own. Pool of
    Radiance's own census is 24 of 24 clean (`#310`), so there is no defect
    of this title's own to repair, and the record must survive untouched."""
    rec = _c64_record(class_bits=0x08, char_class=0, level_fighter=4)
    out = c64_codec.read(rec, game=POOL)
    assert out.get("char_class") == 0
    assert out.value("char_class").how is Provenance.COPIED


def test_a_silver_blades_records_disagreement_is_also_left_alone():
    """Silver Blades' own `GEN` never stores to `char_class` at all
    (`#310`'s census), so what its own creation code leaves there is
    UNMEASURED -- repairing a disagreement here would invent a value
    rather than restore one, the same reason Pool of Radiance's is left
    alone above."""
    rec = _c64_record(class_bits=0x08, char_class=0, level_fighter=4)
    out = c64_codec.read(rec, game=SSB)
    assert out.get("char_class") == 0
    assert out.value("char_class").how is Provenance.COPIED


def test_a_dual_classed_records_code_takes_the_levels():
    """A human who dual-classed out of magic-user 6 into fighter, one level
    short of regaining the old class: `char_class` reads 6, her old level,
    which is THIEF -- the mask cannot answer for her, because it carries
    both bits once she passes the level she left magic-user at, but the
    current level array does: the old slot is zeroed at the change."""
    rec = _c64_record(class_bits=0x08, char_class=6,
                      level_fighter=1, level_magic_user=0,
                      dual_class_slot=0, dual_class_level=6)
    out = c64_codec.read(rec, game=CURSE)
    assert out.get("former_levels") == {"magic-user": 6}
    assert out.get("char_class") == 2          # fighter
    assert out.value("char_class").how is Provenance.COMPUTED
    assert "recomputed from levels" in out.value("char_class").origin


# --- the census, through the neutral record rather than the raw byte -------

def _clean_c64_disks(prefix: str):
    """Every specimen C64 disk under `por-c64` whose name starts `prefix`,
    verified against its own provenance -- `WISH-SPEC-por-*` and
    `WISH-SPEC-ssb-*`, neither of which Curse's trainer ever touches.

    Skips the whole test when the specimen tree is absent; fails it when a
    disk has changed since it was recorded, the same two rules
    `gamedata.specimen` applies to a single named specimen.
    """
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted((root / "por-c64").glob(f"WISH-SPEC-{prefix}-*.[dD]64"))
    if not found:
        pytest.skip(f"needs a WISH-SPEC-{prefix}-* specimen")
    for path in found:
        prov = path.with_suffix(".provenance.toml")
        recorded = specimens.read_provenance(prov).get("sha256", {})
        actual = specimens.sha256_file(path)
        if recorded.get(path.name) not in (None, actual):
            pytest.fail(f"{path.name} has changed since it was recorded; "
                        f"run tools/specimens.py check")
    return found


def _named_specimen_disk(name: str):
    """One named C64 specimen disk under `por-c64`, verified against its own
    provenance -- the same rule `gamedata.specimen` applies, for a specimen
    that is one disk image rather than a directory."""
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs specimen WISH-SPEC-{name}")
    path = found[0]
    prov = path.with_suffix(".provenance.toml")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail(f"WISH-SPEC-{name}: {path.name} has changed since it was "
                    f"recorded; run tools/specimens.py check")
    return path


def test_an_unedited_export_of_a_trained_curse_party_imports_with_no_changes(
        tmp_path):
    """`WISH-SPEC-curse-trained-party`: five characters trained at Curse's
    own hall, four of them left with a stale `char_class`
    (`docs/187-the-class-code-byte.md`'s census). Exporting the party and
    importing the document straight back, with nothing edited, must change
    nothing.

    Before this fix it did: `entry_for` writes the *repaired* code (once
    `c64_codec.read` makes it), and the importer compared it against the
    *raw* stored byte, so an untouched file looked like an explicit edit and
    rewrote every trained character's `char_class` back to the value the
    export had already corrected -- a no-op import that was not a no-op.
    """
    src = _named_specimen_disk("curse-trained-party")
    data = export_save(str(src))
    out = tmp_path / "roundtrip.d64"
    changes = import_into(str(src), data, str(out))
    assert changes == []
    assert src.read_bytes() == out.read_bytes()


def test_pool_of_radiance_and_silver_blades_c64_specimens_are_never_repaired():
    """`docs/187-the-class-code-byte.md`'s census: 24 of 24 Pool of Radiance
    and 24 of 24 Silver Blades C64 records agree with their own classes, so
    the repair this reader makes must never fire on either title -- if it
    did, a clean record would arrive at the DOS sheet with an invented
    class. Read through `c64_codec.read`, which is the neutral record every
    other reader of `char_class` now sees, not the raw byte the older
    `tools/classcodecensus.py` compares."""
    checked = 0
    for prefix, game in (("por", POOL), ("ssb", SSB)):
        for path in _clean_c64_disks(prefix):
            game_read, sg0, sg1 = load_save(D64.open(str(path)))
            for slot in sg0.characters:
                block = sg1.roster(slot.index) if sg1 is not None else None
                out = c64_codec.read(slot.record, roster=block,
                                     game=game_read or game, source=path.name)
                assert out.value("char_class").how is not Provenance.COMPUTED, (
                    f"{path.name}#{slot.index} {slot.record.name}: the class "
                    f"code was repaired, so it disagreed with its own classes")
                checked += 1
    assert checked > 0, "the census walked no records"
