"""The later C64 titles' two ability arrays, and which one the engine uses.

`#367 (What is the second ability array at 0x065 for, and which of the two
does the engine treat as current?)`.  `0x065` is the character's permanent
score and `0x014` is the current one; everything in play reads `0x014`, and
the engine derives it from `0x065` whenever an item, a spell or a drain
changes what is in force.

The assertions here are about the one number that settles it **without a
screenshot**: the carrying-capacity index at record `0x0E2`, which the engine
computes from the ability score and writes back into the record.  Reproducing
it is a claim about `LIBRARY $19EE`, and the crossed specimen is the claim
that the input was `0x014`.

Every record read here comes off a disk in the specimen tree; nothing is
committed and the tests skip cleanly on a machine that has none.
`docs/201-the-two-ability-arrays.md` is the write-up.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import gamedata  # noqa: E402
from tools import abilitypair  # noqa: E402

# --- the formula, against the brackets the engine's own table names ---------

@pytest.mark.parametrize("exceptional,expect", [
    (0, 18),                        # no percentile at all: the engine skips
    (1, 19), (50, 19),              # 18/01-50
    (51, 20), (75, 20),             # 18/51-75
    (76, 21), (90, 21),             # 18/76-90
    (91, 22), (99, 22),             # 18/91-99
    (100, 23),                      # 18/00
])
def test_the_exceptional_strength_brackets_are_ad_and_ds_own(exceptional,
                                                             expect):
    """`LIBRARY $3FE3` holds 9, 15, 25, 51, 0 and the loop reads it backwards,
    so the running totals are 0, 51, 76, 91 and 100 -- the five AD&D bands.
    A table read the other way round would put every boundary somewhere
    else, which is what this pins."""
    assert abilitypair.weight_index(18, exceptional) == expect


@pytest.mark.parametrize("strength,expect", [
    (3, 3), (9, 9), (17, 17),       # below 18 the index is the score
    (19, 24), (24, 29), (25, 30), (30, 30),   # above it, score + 5 capped
])
def test_the_index_below_and_above_eighteen(strength, expect):
    assert abilitypair.weight_index(strength, 0) == expect


# --- the same formula against bytes the engine wrote ------------------------

def _later_c64_disks():
    """Every Curse and Silver Blades C64 specimen disk, each verified against
    its own provenance hash -- the rule `gamedata.specimen` applies, for
    specimens that are one disk image rather than a directory."""
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = []
    for where in sorted(root.iterdir()):
        if not where.is_dir():
            continue
        for prefix in ("curse", "ssb", "coab"):
            found += sorted(where.glob(f"WISH-SPEC-{prefix}-*.[dD]64"))
    if not found:
        pytest.skip("needs a Curse or Silver Blades C64 specimen disk")
    for path in sorted(set(found)):
        prov = path.with_suffix(".provenance.toml")
        recorded = specimens.read_provenance(prov).get("sha256", {})
        actual = specimens.sha256_file(path)
        if recorded.get(path.name) not in (None, actual):
            pytest.fail(f"{path.name} has changed since it was recorded; "
                        f"run tools/specimens.py check")
    return sorted(set(found))


def _records(path: pathlib.Path):
    """`(who, current, base, stored 0x0E2)` for every occupied slot."""
    _, _, payload = abilitypair.save_payload(path.read_bytes())
    out = []
    for n, who in enumerate(abilitypair.slot_names(payload)):
        if not who:
            continue
        cur, bas = abilitypair.arrays(payload, n)
        stored = payload[abilitypair.SLOT0 + n * abilitypair.SLOT_SIZE + 0x0E2]
        out.append((f"{path.name}:{who}", cur, bas, stored))
    return out


def test_the_weight_index_reproduces_the_engines_byte_on_every_record():
    """Every character on every later-title C64 specimen disk.

    The identity is `0x0E2 == weight_index(0x014, 0x01A)`, and it is a claim
    about a routine rather than about any one save: a wrong bracket table or a
    wrong branch at 18 would break it somewhere in the corpus.  84 records
    over fourteen disks on 2026-09-07, 84 agreeing.
    """
    checked = wrong = 0
    failures = []
    for path in _later_c64_disks():
        for who, cur, bas, stored in _records(path):
            checked += 1
            want = abilitypair.weight_index(cur[0], cur[6])
            if stored != want:
                wrong += 1
                failures.append(f"{who}: 0x0E2 {stored}, expected {want} "
                                f"from str {cur[0]}({cur[6]})")
    assert checked >= 6, f"only {checked} records were read"
    assert not failures, f"{wrong} of {checked} disagree: " + "; ".join(
        failures[:5])


def test_the_engine_wrote_the_weight_index_from_the_current_array():
    """`WISH-SPEC-curse-367-crossed-abilities-resave` is the specimen that
    discriminates, because it is the only Curse save anywhere whose two
    arrays differ **and** which the engine wrote.

    PHILIPPE was staged with strength 9 at `0x014` against 18 at `0x065` and
    SHARA the other way about; both were trained a level in Curse's own hall,
    which is what makes the engine recompute `0x0E2`, and the party was saved
    by `SAVE CURRENT GAME`.  Each came out holding the index its **own**
    `0x014` predicts and not the one `0x065` predicts -- so if this ever
    fails, either the specimen has been replaced or somebody has swapped
    which array the project calls current.
    """
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted(root.glob(
        "*/WISH-SPEC-curse-367-crossed-abilities-resave.[dD]64"))
    if not found:
        pytest.skip("needs specimen WISH-SPEC-curse-367-crossed-abilities-"
                    "resave")
    path = found[0]
    prov = path.with_suffix(".provenance.toml")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    if recorded.get(path.name) not in (None, specimens.sha256_file(path)):
        pytest.fail(f"{path.name} has changed since it was recorded; "
                    f"run tools/specimens.py check")

    crossed = [(who, cur, bas, stored)
               for who, cur, bas, stored in _records(path)
               if cur[0] != bas[0]]
    assert len(crossed) == 2, [c[0] for c in crossed]
    for who, cur, bas, stored in crossed:
        from_current = abilitypair.weight_index(cur[0], cur[6])
        from_base = abilitypair.weight_index(bas[0], bas[6])
        assert from_current != from_base, f"{who} does not discriminate"
        assert stored == from_current, (
            f"{who}: the engine wrote 0x0E2 = {stored}, which is "
            f"{from_base} from 0x065 rather than {from_current} from 0x014")


def test_the_two_arrays_come_off_that_disk_still_disagreeing():
    """The engine saved the crossed party back without resynchronising the
    pair -- so `GEN $1E9C`'s twelve-byte copy is not on the training path, and
    a record whose arrays differ stays that way across a level."""
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted(root.glob(
        "*/WISH-SPEC-curse-367-crossed-abilities-resave.[dD]64"))
    if not found:
        pytest.skip("needs specimen WISH-SPEC-curse-367-crossed-abilities-"
                    "resave")
    apart = [who for who, cur, bas, _ in _records(found[0]) if cur != bas]
    assert len(apart) == 6, apart


def test_a_pool_of_radiance_disk_is_refused_rather_than_read_as_a_pair():
    """Pool of Radiance holds seven zeroes at `0x065` and writes
    `SAVEDGAME0`/`SAVEDGAME1`, so reading one here would invent a base array
    of zeroes for every character."""
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted(root.glob("*/WISH-SPEC-por-*.[dD]64"))
    if not found:
        pytest.skip("needs a Pool of Radiance C64 specimen disk")
    with pytest.raises(SystemExit) as caught:
        abilitypair.save_payload(found[0].read_bytes())
    assert "SAVEDGAME" in str(caught.value)
