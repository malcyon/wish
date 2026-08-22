"""Secret of the Silver Blades read with Pool of Radiance's decoders.

`docs/121-silver-blades.md` phases 1 and 2: the cold read of the disks, and the
shipped pre-generated party through `por/record.py`. Nothing here modifies a
decoder and nothing here needs the emulator -- which is the whole point of
putting these two phases first.

The Pool of Radiance half of every check is the control. An invariant asserted
on one title only is an invariant that will be quietly broken for the other.

**Where the disks are found.** `tests/gamedata.py` carries `POR_DISKS` and
`COAB_DISKS` hooks and no Silver Blades one, and that module is not this
module's to edit, so the lookup is here, behind `SSB_DISKS`, in the same shape.
If a third title ever needs the same thing it should move there rather than be
copied a second time.

Every test skips when the disks are absent. Nothing here reads a committed
fixture: `CLAUDE.md` forbids the game's data in this repository, test fixture
or not.
"""

from __future__ import annotations

import functools
import os
import pathlib
import statistics

import pytest

from por import games
from por.d64 import D64, split_load_address
from por.savegame import load_save
from tests import gamedata

# The sanity bar and the reciprocity machinery are the Curse suite's, used
# unchanged. Sharing them is the assertion: a third title reading correctly
# means the same thing it meant for the second.
from tests.test_curse import (
    ART_FLOOR,
    BARRIER_FLOOR,
    MANGLED_ART_CEILING,
    MEAN_FLOOR,
    _art_reciprocity,
    _barrier_reciprocity,
    _geo_ids,
    _geo_payloads,
    _names,
    _pool_disks,
    _sane_character,
    _stems,
    _swap_art_nibbles,
    _swap_art_planes,
)

SSB = games.SECRET_OF_THE_SILVER_BLADES
POOL = games.POOL_OF_RADIANCE

SSB_ENV = "SSB_DISKS"
_REPO = pathlib.Path(__file__).resolve().parent.parent


def _candidates():
    env = os.environ.get(SSB_ENV)
    if env:
        return [pathlib.Path(env)]
    home = pathlib.Path.home()
    names = ("Secret of the Silver Blades Disks",
             "Secret of the Silver Blades",
             "SecretOfTheSilverBlades-Lithium",
             "Silver Blades", "SSB")
    roots = [pathlib.Path.cwd(), home, home / "Documents", home / "Games",
             home / "c64", home / "roms", home / "Downloads"]
    out = [r / n for r in roots for n in names]
    out.append(_REPO / "work" / "silverblades")
    return out


@functools.lru_cache(maxsize=1)
def ssb_dir():
    """Where the player keeps their Silver Blades disks, or None."""
    for path in _candidates():
        try:
            if path.is_dir() and any(path.glob("SILVER*.[dD]64")):
                return path
        except OSError:
            continue
    return None


def ssb_disks():
    """Every readable Silver Blades side, skipping when there are none."""
    where = ssb_dir()
    if where is None:
        pytest.skip(f"needs the Silver Blades disks; set {SSB_ENV}")
    out = []
    for path in sorted(where.glob("SILVER*.[dD]64")):
        try:
            out.append(D64.open(str(path)))
        except Exception:
            continue                      # an error-byte rip is skipped, not failed
    if not out:
        pytest.skip("no readable Silver Blades disk here")
    return out


def _save_disk() -> pathlib.Path:
    """The side carrying a whole `SAVEDBASH`, or skip."""
    where = ssb_dir()
    if where is None:
        pytest.skip(f"needs the Silver Blades disks; set {SSB_ENV}")
    for path in sorted(where.glob("SILVER*.[dD]64")):
        try:
            prg = D64.open(str(path)).read_file(SSB.save_file)
        except Exception:
            continue
        if SSB.matches_payload(prg):
            return path
    pytest.skip("no Silver Blades side here carries a whole SAVEDBASH")


def _party():
    """The shipped pre-generated party, as a `SaveGame0`."""
    game, sg0, sg1 = load_save(D64.open(str(_save_disk())))
    assert game is SSB
    return sg0, sg1


# --- phase 1: the cold read --------------------------------------------------


def test_the_set_of_sides_is_complete():
    """Three double-sided disks, sides 1-6, every one of them readable.

    `docs/121` phase 0 was written when the disks were not on this machine and
    the number of sides was unknown. It is six.
    """
    disks = ssb_disks()
    assert len(disks) >= 6, f"only {len(disks)} readable Silver Blades sides"
    for disk in disks:
        assert list(disk.directory()), "a side with an empty directory"


def test_silver_blades_speaks_pool_of_radiances_file_vocabulary():
    """`docs/121` §3 guessed the stems "may be renamed wholesale". They are not.

    Thirty of the thirty-four stems are Pool of Radiance's, and the one real
    rename is `ITEMFILE` to `ITEM`.
    """
    ssb, pool = _stems(ssb_disks()), _stems(_pool_disks())
    assert len(ssb & pool) >= 30, f"only {len(ssb & pool)} stems shared"
    assert {"GEO", "ECL", "ITEMS", "ITEMNAMES", "LIBRARY", "MON", "SPELLE",
            "WALLDEF", "WALLSET", "CHARSET", "COMBAT"} <= ssb & pool

    assert "ITEM" in ssb and "ITEMFILE" not in ssb
    assert "ITEMFILE" in pool

    # No wilderness or city-block data in any title after Pool of Radiance.
    assert {"SQRDATA", "SQRPACI", "WALLS", "LOAD/SAVE"}.isdisjoint(ssb)

    names = _names(ssb_disks())
    assert SSB.save_file in names
    assert b"SAVEDGAME0" not in names and b"SAVEAZURE" not in names


def test_silver_blades_ships_two_spell_name_tables():
    """`SPELLN64` and `SPELLN65`, where Curse ships only the first."""
    names = _names(ssb_disks())
    assert {b"SPELLN64", b"SPELLN65"} <= names
    assert b"SPELLN00" not in names


def test_all_seventeen_maps_decode_through_the_unmodified_decoder():
    """Phase 1's pass criterion: every `GEO` clears 92% barrier reciprocity."""
    maps = _geo_payloads(ssb_disks())
    assert len(maps) >= 17, f"expected 17 Silver Blades maps, found {len(maps)}"
    scores = {n: _barrier_reciprocity(p) for n, p in maps.items()}
    worst = min(scores, key=scores.get)
    assert scores[worst] > BARRIER_FLOOR, (
        f"{worst} barrier reciprocity {scores[worst]:.3f}")
    assert statistics.mean(scores.values()) > MEAN_FLOOR


def test_silver_blades_wall_art_is_perfectly_reciprocal():
    """Every edge that is drawn is drawn from both sides -- all 17 files.

    Pool of Radiance scores 0.960 on this and its worst file 0.646, because it
    draws genuinely one-sided walls; Curse scores 0.994. Silver Blades has no
    one-sided edge at all, which is the strongest single sign that the two art
    planes are being read the right way round.
    """
    scores = [_art_reciprocity(p) for p in _geo_payloads(ssb_disks()).values()]
    assert min(scores) > ART_FLOOR
    assert statistics.mean(scores) > 0.99


@pytest.mark.parametrize("mangle", [_swap_art_planes, _swap_art_nibbles])
def test_a_transposed_art_parse_fails_the_floor_the_real_one_clears(mangle):
    """The floor above is only evidence if a wrong reading falls through it."""
    scores = [_art_reciprocity(mangle(p))
              for p in _geo_payloads(ssb_disks()).values()]
    assert statistics.mean(scores) < MANGLED_ART_CEILING


def test_map_ids_are_sparse_and_their_high_nibble_names_the_side():
    """`GEO2x` on side 2, `GEO3x` on side 3, without exception.

    Stronger than Curse's chapter grouping, and a free area-to-side index. It
    also means nothing may enumerate maps by count: there is no `GEO00` and the
    ids run `$10` to `$62`.
    """
    ids = _geo_ids(ssb_disks())
    assert len(ids) >= 17
    assert 0x00 not in ids
    assert ids[-1] - ids[0] + 1 > 2 * len(ids), f"{ids} is dense, not sparse"

    where = ssb_dir()
    for path in sorted(where.glob("SILVER-[1-6].[dD]64")):
        side = int(path.stem.rsplit("-", 1)[1])
        for name in _geo_ids([D64.open(str(path))]):
            assert name >> 4 == side, (
                f"GEO{name:02X} sits on side {side}")


def test_the_item_table_is_a_whole_number_of_sixteen_byte_records():
    """Phase 1's other pass criterion."""
    for disk in ssb_disks():
        entry = disk.find(b"ITEMS")
        if entry is None:
            continue
        _, payload = split_load_address(disk.read_file(entry))
        assert payload and len(payload) % 16 == 0, f"ITEMS is {len(payload)}"
        return
    pytest.skip("no ITEMS on these Silver Blades sides")


# --- phase 2: the shipped party ---------------------------------------------


def test_the_save_file_is_curses_geometry_under_a_different_name():
    """`docs/121` expected a third load address. There is not one.

    One file, 7426 bytes, `$4B00`, slots `$4F00`, items `$5B00`, roster
    `$6700` -- byte for byte Curse's numbers.
    """
    disk = D64.open(str(_save_disk()))
    assert games.detect(disk) is SSB
    prg = disk.read_file(SSB.save_file)
    assert len(prg) == 7426 == SSB.save_prg_size
    assert split_load_address(prg)[0] == 0x4B00
    assert (SSB.slot_area_base, SSB.item_area_base, SSB.roster_base) == (
        0x4F00, 0x5B00, 0x6700)
    curse = games.CURSE_OF_THE_AZURE_BONDS
    assert SSB.save_load_address == curse.save_load_address
    assert SSB.save_size == curse.save_size


def test_the_shipped_party_decodes_with_fields_a_person_would_recognise():
    """Six characters, level 8-9, through `por/record.py` unmodified."""
    sg0, _ = _party()
    assert len(sg0.characters) == 6, "SSI ships six pre-generated characters"
    for slot in sg0.characters:
        _sane_character(slot.record)
    names = [slot.record.name for slot in sg0.characters]
    assert all(names) and len(set(names)) == len(names)


def test_every_slot_round_trips_byte_identically():
    """The 256 bytes the save stores survive decode and re-encode unchanged."""
    sg0, _ = _party()
    for slot in sg0.characters:
        assert slot.record.to_bytes()[:games.SLOT_STRIDE] == slot.record_bytes
    assert len(sg0.to_bytes()) == SSB.save_size


def test_class_bits_is_one_bit_per_slot_of_the_eight_wide_level_array():
    """This is phase 2's pass criterion, and it holds -- including for `0x40`
    and `0x80`.

    `work/reports/goldbox-inventory.md` §3.3(a) reports it *failing* on PAINE
    and GUY DE VALOIS, and says their level array is all zero. That reading
    took the array at `0x0C9` to be four bytes. It is eight: PAINE's level 8
    sits in slot 7 (`level_ranger`) and GUY DE VALOIS's in slot 6
    (`level_paladin`), which is exactly what bits `0x80` and `0x40` claim.
    Curse fills the same two slots -- `docs/116` -- so nothing about the field
    is new in Silver Blades.
    """
    sg0, _ = _party()
    seen = set()
    for slot in sg0.characters:
        rec = slot.record
        levels = rec.slice(0x0C9, 8)
        assert rec.get("class_bits") == sum(
            1 << i for i, lv in enumerate(levels) if lv)
        seen.add(rec.get("class_bits"))
    assert {0x40, 0x80} <= seen, "the pregens should include a paladin and a ranger"


def test_a_silver_blades_caster_writes_past_pool_of_radiances_spellbook():
    """`spells_known` is at least eight bytes, and this is the specimen.

    `docs/116` lists the bitmask's width as NOT FOUND because no Curse
    character writes past `0x07C`. DOMINIC sets `0x07D`, `0x07E` and `0x07F`;
    `0x07F = 0x04` is bit 2, spell id 58 on the documented indexing. That is
    `docs/121` §3's prediction held, and it is the strongest new fact the cold
    read produced.
    """
    sg0, _ = _party()
    past = [slot.record.name for slot in sg0.characters
            if any(slot.record.slice(0x07D, 3))]
    assert past, "no Silver Blades caster reaches 0x07D"
    assert any(slot.record.slice(0x07F, 1)[0] for slot in sg0.characters), (
        "no character sets 0x07F, which por/layout.py still calls a gap")


def test_pool_of_radiance_never_writes_past_its_seven_bytes():
    """The control: seven bytes really is this game's width, not the engine's."""
    _, sg0, _ = load_save(D64.open(str(gamedata.save_disk("PORSAVE11"))))
    for slot in sg0.characters:
        assert not any(slot.record.slice(0x07D, 3)), (
            f"{slot.record.name} sets a byte above spell id 56")


def test_the_roster_is_the_last_page_of_the_save():
    """Curse's arrangement, third title running."""
    sg0, sg1 = _party()
    live = [b for b in sg1.roster_blocks if b.occupied]
    assert [b.slot_index for b in live] == list(range(len(live)))
    assert sg1.roster(0).address == 0x6700
    assert sg1.to_bytes() == sg0.roster_page()
