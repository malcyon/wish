"""Corrections checked against the game's own bytes, not against a document.

Each block here is one task from `docs/TASKS.md` and each one exists because a
claim was carried at the wrong confidence. The rule they all serve: a
third-party table is PROBABLE until something on the player's own disks agrees
with it, and our own measurement beats an outside document's alignment.

Everything that needs game data reads it off the player's disks and skips
without them.
"""

from __future__ import annotations

import collections

import pytest
from gamedata import disk_dir, game_file

from por import levels, traits
from por.d64 import D64, split_load_address
from por.encoding import item_protection_ac

# `GEN` runs at $0800 like every other Pool of Radiance overlay, whatever its
# PRG header claims. `$1E5C` is therefore payload offset $1E5C - $0800.
GEN_BASE = 0x0800
CEILINGS = 0x1E5C
CEILING_ROUTINE = 0x1E21


def _gen() -> bytes:
    payload = game_file("GEN")
    return payload[2:] if payload[:2] == b"\x00\x08" else payload


def _at(payload: bytes, address: int, size: int) -> bytes:
    return payload[address - GEN_BASE:address - GEN_BASE + size]


# --- P49: the level ceilings are the game's, not the table's -----------------


def test_the_class_ceiling_table_is_on_the_disk_where_por_levels_says():
    """`docs/119` called the ceilings PROBABLE because "no routine enforcing
    them has been cited". `GEN $1E5C` is the table and eight bytes long, in
    class-bit order -- magic-user 6, cleric 6, thief 9, fighter 8."""
    table = _at(_gen(), CEILINGS, 8)
    assert list(table) == [6, 6, 9, 8, 0, 0, 0, 0]
    pool = levels.for_game(levels.POOL_OF_RADIANCE)
    assert dict(pool.ceilings) == {"magic-user": 6, "cleric": 6,
                                   "thief": 9, "fighter": 8}


def test_a_routine_reads_that_table_and_clamps_to_it():
    """The citation `docs/119` was missing. At `$1E21`: take the class index
    from `$2B58`, raise `$2B50,X`, `CMP $1E5C,X`, and on a value above the
    table bump `$2B74` and write the ceiling back over the level. It clamps
    rather than refusing, which is the part that was guessed at."""
    code = _at(_gen(), CEILING_ROUTINE, 30)
    assert code[:3] == bytes([0xAE, 0x58, 0x2B])          # LDX $2B58
    assert code[3:6] == bytes([0xBD, 0x50, 0x2B])         # LDA $2B50,X
    assert bytes([0xDD, CEILINGS & 0xFF, CEILINGS >> 8]) in code   # CMP $1E5C,X
    assert bytes([0xBD, CEILINGS & 0xFF, CEILINGS >> 8]) in code   # LDA $1E5C,X
    assert bytes([0xEE, 0x74, 0x2B]) in code              # INC $2B74


def test_the_racial_level_limits_are_the_same_table_four_wide():
    """Seven races of four classes at `$1E64`, 99 for unlimited. All 28 bytes
    match `por/levels.py`, which had them from AD&D 1e and nothing else."""
    rows = _at(_gen(), CEILINGS + 8, 28)
    pool = levels.for_game(levels.POOL_OF_RADIANCE)
    for race, limits in pool.racial_limits:
        assert tuple(rows[(race - 1) * 4:(race - 1) * 4 + 4]) == limits, race
    assert list(rows[24:28]) == [levels.UNLIMITED] * 4     # human, all four


# --- P55: what a record agrees with, and what it cannot -----------------------


@pytest.fixture(scope="module")
def carriers() -> dict[int, set[str]]:
    """Which creatures carry which trait code, over every `MON*` on the disks."""
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks")
    out: dict[int, set[str]] = {}
    seen: dict[str, bytes] = {}
    for path in sorted(where.glob("POOL*.[dD]64")):
        try:
            disk = D64.open(str(path))
        except Exception:
            continue
        for entry in disk.directory():
            if not (entry.name.startswith(b"MON") and len(entry.name) == 5):
                continue
            try:
                _, payload = split_load_address(disk.read_file(entry.name))
            except Exception:
                continue
            if len(payload) < 0x120:
                continue
            name = payload[:20].split(b"\x00")[0].decode("latin1")
            seen.setdefault(name, bytes(payload))
    if not seen:
        pytest.skip("no MON records on these disks")
    for name, record in seen.items():
        for code in record[traits.FIRST:traits.FIRST + traits.SLOTS]:
            if code:
                out.setdefault(code, set()).add(name)
    return out


@pytest.mark.parametrize("code", [103, 114, 118, 126])
def test_the_vampires_own_effects_are_carried_by_the_vampire_alone(code, carriers):
    """Gaseous form, half damage from electricity, half damage from cold, and
    the gaze that is avoided rather than reflected. The *Monster Manual* gives
    all four to the vampire and to nothing else in this bestiary, and the
    vampire is the only creature on the disks carrying any of them."""
    assert carriers[code] == {"VAMPIRE"}
    assert traits.confidence(code) == "CONFIRMED"


def test_the_whole_vampire_block_reads_as_one_monster_manual_entry(carriers):
    """The promotion rests on the block, not on any one code: four already
    confirmed and four promoted, and every one of the eight is a line of the
    vampire's own entry."""
    vampire = {code for code, who in carriers.items() if "VAMPIRE" in who}
    entry = {86, 98, 119, 125} | {103, 114, 118, 126}
    assert entry <= vampire
    assert all(traits.confidence(c) == "CONFIRMED" for c in entry)
    # 117 is the one the vampire carries that the block does not settle: every
    # undead has it, and "undead, and therefore turnable" predicts the same.
    assert vampire - entry == {117}


def test_the_gaze_pair_splits_the_way_the_monster_manual_splits_it(carriers):
    """A basilisk's and a medusa's gaze are turned back by a mirror; a
    vampire's is only avoided by not meeting its eyes. Neither gorgon carries
    126 and the vampire does not carry 127."""
    assert carriers[127] == {"BASILISK", "MEDUSA"}
    assert carriers[126] == {"VAMPIRE"}
    assert not carriers[126] & carriers[127]


@pytest.mark.parametrize("code,rival", [
    (117, "undead, and therefore turnable"),
    (120, "hurls boulders"),
])
def test_the_two_that_look_promotable_stay_probable(code, rival, carriers):
    """117 lands on all nine undead and 120 on both giants -- and a rival
    reading of each predicts exactly the same carrier set. A population that
    cannot separate two readings has not tested either."""
    assert traits.confidence(code) == "PROBABLE", rival
    assert carriers[code]


def test_the_fill_byte_is_only_ever_the_last_slot(carriers):
    """255 is not an effect id. Across every `MON*` record on the disks it
    occurs only in slot 9, the last of the ten, and no record carries a real
    code after one -- which is what promoted it, not the guide."""
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks")
    positions: collections.Counter = collections.Counter()
    records = 0
    for path in sorted(where.glob("POOL*.[dD]64")):
        try:
            disk = D64.open(str(path))
        except Exception:
            continue
        for entry in disk.directory():
            if not (entry.name.startswith(b"MON") and len(entry.name) == 5):
                continue
            try:
                _, payload = split_load_address(disk.read_file(entry.name))
            except Exception:
                continue
            if len(payload) < 0x120:
                continue
            records += 1
            block = list(payload[traits.FIRST:traits.FIRST + traits.SLOTS])
            for slot, code in enumerate(block):
                if code == traits.FILL:
                    positions[slot] += 1
                    assert all(x in (0, traits.FILL) for x in block[slot + 1:])
    assert records
    assert set(positions) == {traits.SLOTS - 1}
    assert traits.confidence(traits.FILL) == "CONFIRMED"


def test_the_census_is_the_only_thing_that_promotes_a_name():
    """44 of the 129 names had a carrier when the guide was transcribed; the
    P55 pass took it to 49. The rest cannot be promoted by more looking --
    nothing on the C64 exercises them."""
    counts = collections.Counter(sure for _, sure in traits.NAMES.values())
    assert counts["CONFIRMED"] == 49
    assert counts["UNKNOWN"] == 1                 # 92, which the guide has unused
    assert sum(counts.values()) == 129


# --- P58: the armour rule is the family's own bias --------------------------


def test_item_protection_is_read_with_the_general_rule():
    """`por/encoding.py` was the last copy of `12 - (byte & 0x0F)`. That is the
    general rule in disguise while the high nibble is $B and nonsense below
    it."""
    assert item_protection_ac(0xB4) == 8          # leather
    assert item_protection_ac(0xB9) == 3          # plate


def test_the_two_armour_rules_diverge_at_armour_class_thirteen():
    """$AF is the divergent case and nothing in the game reaches it, which is
    exactly why it is pinned here: the data we hold cannot tell the readings
    apart."""
    assert item_protection_ac(0xAF) == 13
    assert 12 - (0xAF & 0x0F) == -3               # what it used to say
