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


# --- issue #31: the fields the editor shows ---------------------------------
# Every check below is a cold read -- no emulator, no running game -- and each
# one is paired with the thing that depends on it coming out right, because a
# table read off a disk that nothing consumes is not evidence that it was read
# correctly.


def _game_disk_with(name: bytes) -> pathlib.Path:
    """The Silver Blades side carrying `name`, or skip."""
    where = ssb_dir()
    if where is None:
        pytest.skip(f"needs the Silver Blades disks; set {SSB_ENV}")
    for path in sorted(where.glob("SILVER*.[dD]64")):
        try:
            if D64.open(str(path)).find(name) is not None:
                return path
        except Exception:
            continue
    pytest.skip(f"no Silver Blades side here carries {name.decode()}")


def test_silver_blades_keeps_its_spell_names_in_combat2_like_curse():
    """Same file, same shape, a longer text block: 194 entries at `$E000`.

    The geometry is fitted by asking which entry count makes every pointer land
    inside the text -- and the same fit run against Curse recovers Curse's
    already-known 170, `$07DB`, `$0885`, which is what makes the answer here
    worth believing.
    """
    from por import spells

    table = spells.SECRET_OF_THE_SILVER_BLADES
    assert table.file == spells.CURSE_OF_THE_AZURE_BONDS.file == b"COMBAT2"
    disk = _game_disk_with(table.file)
    _, payload = split_load_address(D64.open(str(disk)).read_file(table.file))

    starts = {0} | {i + 1 for i, b in enumerate(payload[:table.text_offset
                                                        + table.high_offset])
                    if b == 0}
    inside = on_start = 0
    for i in range(table.entries):
        addr = (payload[table.low_offset + i]
                | payload[table.high_offset + i] << 8)
        off = addr - table.resident_base
        if 0 <= off < table.high_offset:
            inside += 1
            on_start += off in starts
    assert inside >= table.entries - 1, "a pointer lands outside the text"
    assert on_start >= 186, f"only {on_start} pointers start a string"


def test_ids_one_to_fifty_six_mean_the_same_spell_but_for_heal_and_harm():
    """The two SSI moved, and nothing else -- so no stride is off by one.

    An off-by-one anywhere in the fit would disagree on nearly all 56, not on
    two isolated ids. 36 and 56 are `HEAL` and `HARM` here where the earlier
    two titles have `ANIMATE DEAD` and `RESTORATION`.
    """
    from por import spells

    ssb = spells.load_spell_names(str(_game_disk_with(b"COMBAT2")),
                                  spells.SECRET_OF_THE_SILVER_BLADES)
    por = spells.load_spell_names(str(gamedata.game_disk("POOL1")),
                                  spells.POOL_OF_RADIANCE)
    moved = {i for i in range(1, 57) if ssb.get(i) != por.get(i)}
    assert moved == {36, 56}, moved
    assert (ssb[36], ssb[56]) == ("HEAL", "HARM")
    assert ssb[20] == por[20] == "SHOCKING GRASP"


def test_the_shipped_ranger_knows_the_four_first_level_druid_spells():
    """The corroboration the spell table needed, and it is an AD&D rule.

    A ranger gets druid spells and no others until ninth level. PAINE's
    spellbook holds exactly four bits, and all four fall in the druid group
    `por/spells.py` reads out of `GEN`'s own grant table.
    """
    from por import spells

    table = spells.SECRET_OF_THE_SILVER_BLADES
    names = spells.load_spell_names(str(_game_disk_with(b"COMBAT2")), table)
    sg0, _ = _party()
    rangers = [s.record for s in sg0.characters
               if s.record.get("class_bits") == 0x80]
    assert rangers, "the shipped party should include a ranger"
    for rec in rangers:
        mask = rec.slice(0x078, 16)
        ids = [i for i in range(1, table.last_spell + 1)
               if mask[i >> 3] & (1 << (i & 7))]
        assert ids, f"{rec.name} knows nothing"
        assert all(spells.spell_group(i, table) == ("druid", 1) for i in ids), (
            [(i, names.get(i)) for i in ids])


def test_every_spell_a_shipped_caster_knows_is_one_its_class_may_cast():
    """No cleric holds an arcane id and no magic-user a clerical one."""
    from por import spells

    table = spells.SECRET_OF_THE_SILVER_BLADES
    allowed = {0x01: {"magic-user"}, 0x02: {"cleric"}, 0x80: {"druid"}}
    sg0, _ = _party()
    checked = 0
    for slot in sg0.characters:
        rec = slot.record
        want = allowed.get(rec.get("class_bits"))
        if want is None:
            continue
        mask = rec.slice(0x078, 16)
        ids = [i for i in range(1, table.last_spell + 1)
               if mask[i >> 3] & (1 << (i & 7))]
        for i in ids:
            group = spells.spell_group(i, table)
            assert group is not None, f"{rec.name} knows non-spell {i}"
            assert group[0] in want, f"{rec.name} ({want}) knows {i} {group}"
        checked += len(ids)
    assert checked > 50, "too few spells known to be a real check"


def test_no_shipped_caster_knows_a_spell_past_the_last_one():
    """117 is the last spell; the table past it is combat messages."""
    from por import spells

    last = spells.SECRET_OF_THE_SILVER_BLADES.last_spell
    sg0, _ = _party()
    for slot in sg0.characters:
        mask = slot.record.slice(0x078, 16)
        over = [i for i in range(last + 1, 128)
                if mask[i >> 3] & (1 << (i & 7))]
        assert not over, f"{slot.record.name} knows {over}, past spell {last}"


def test_the_combat_icon_charset_is_pool_of_radiances_but_for_three_glyphs():
    """`CHARPIC00` exists, is the same 2030 bytes, and is nearly the same art.

    Curse's copy is byte-identical to Pool of Radiance's on all fourteen sides.
    Silver Blades redraws three glyphs and changes nothing else, so the icon
    editor's eight-bytes-per-glyph reading transfers untouched.
    """
    from por.icons import load_icon_charset

    ssb = load_icon_charset(str(_game_disk_with(b"CHARPIC00")))
    por = load_icon_charset(str(gamedata.game_disk("POOL1")))
    assert len(ssb) == len(por) == 2030
    differing = {i // 8 for i, (a, b) in enumerate(zip(ssb, por)) if a != b}
    assert differing == {132, 133, 207}, differing


def test_every_shipped_icon_is_a_weapon_and_a_head_from_the_editors_lists():
    """`SPELLE64` is the same file at a different address, and this proves it.

    The parts data is byte-identical to Pool of Radiance's; only the load
    address moves, to `$8E00`. `IconParts` fits that base out of the pointers
    rather than naming it, and the test of the fit is that all eight shipped
    shapes come back out of a (weapon, head) pair -- where the hardcoded
    `$A700` raised `IndexError` before #31.
    """
    from por.iconparts import IconParts
    from por.icons import ICON_COUNT, ICON_SIZE

    parts = IconParts.load(str(_game_disk_with(b"SPELLE64")))
    assert parts.base == 0x8E00

    reachable = {}
    for weapon_size in ("small", "large"):
        for head_size in ("small", "large"):
            for w in range(parts.count(weapon_size, "weapon")):
                shape = parts.apply(bytes([0x20] * 18), weapon_size, "weapon", w)
                for h in range(parts.count(head_size, "head")):
                    reachable.setdefault(
                        parts.apply(shape, head_size, "head", h),
                        (weapon_size, w, head_size, h))

    payload = D64.open(str(_save_disk())).read_file(SSB.save_file)[2:]
    base = games.ICON_TABLE_OFFSET
    shapes = [bytes(payload[base + i * ICON_SIZE:][:18]) for i in range(ICON_COUNT)]
    unmade = [s.hex() for s in shapes if any(s) and s not in reachable]
    assert not unmade, unmade


def test_the_parts_file_is_the_same_bytes_in_all_three_titles():
    """Which is why only its address had to be found."""
    from por.iconparts import PARTS_FILE

    def payload(path):
        return split_load_address(D64.open(str(path)).read_file(PARTS_FILE))[1]

    assert payload(_game_disk_with(PARTS_FILE)) == payload(
        gamedata.game_disk("POOL3"))


def test_the_item_lists_are_named_item_rather_than_itemfile():
    """Silver Blades drops the `FILE`, and `ITEMS` must not be swept up.

    Matching on a bare `ITEM` prefix would read the 128-entry type table and
    the word pool as item records and name them nonsense.
    """
    from por.items import is_item_list

    stems = {bytes(e.name).upper()
             for disk in ssb_disks() for e in disk.directory()}
    lists = {n for n in stems if is_item_list(n)}
    assert len(lists) >= 30, sorted(lists)
    assert all(n.startswith(b"ITEM") and not n.startswith(b"ITEMFILE")
               for n in lists), sorted(lists)
    assert b"ITEMS" in stems and b"ITEMNAMES" in stems
    assert not ({b"ITEMS", b"ITEMNAMES"} & lists)


def test_the_item_lists_decode_to_named_items_with_ad_and_d_statistics():
    """Every template names itself out of `ITEMNAMES`, and its type record
    holds the AD&D 1st edition line for that item.

    Banded mail AC 4 at 35 lb and 90 gp, leather AC 8 at 15 lb and 5 gp, a
    shield at +1 -- the same rule table that confirmed the field meanings on
    Pool of Radiance, read here off a wholly different `ITEMS` file.
    """
    from por.items import Item, load_item_names, load_item_templates, load_item_types

    disk = _game_disk_with(b"ITEMS")
    names = load_item_names(str(disk), SSB)
    types = load_item_types(str(disk))
    templates = load_item_templates(str(disk), names, game=SSB)

    assert len(templates) > 80, len(templates)
    assert not [n for n in templates if not n or "?" in n]
    assert not ({Item(r).type_index for r in templates.values()}
                - set(types) - {0})

    def line(name):
        item = Item(templates[name], names)
        kind = types[item.type_index]
        return kind.armour_class, item.weight_lb, item.cost_gp

    assert line("LEATHER ARMOR") == (8, 15.0, 5)
    assert line("BANDED MAIL") == (4, 35.0, 90)
    assert line("SHIELD") == (1, 5.0, 10)
    assert types[Item(templates["LONG BOW"]).type_index].damage_vs_medium == "1d6"


def test_races_classes_and_alignments_are_named_from_itemnames():
    """Silver Blades has no race table in `LIBRARY`: it folds the labels into
    `ITEMNAMES`'s own string pool, at `140 + race`.

    The corroboration is the rule cases in the shipped party -- the paladin is
    lawful good and the ranger is good, which AD&D 1st edition requires -- and
    those two facts also say the alignment codes are Pool of Radiance's,
    unchanged, at pool index `158 + alignment`.
    """
    from por.items import load_item_names

    names = load_item_names(str(_game_disk_with(b"ITEMNAMES")), SSB)
    assert {code: names[140 + code] for code, _ in SSB.races} == {
        code: label.upper() for code, label in SSB.races}
    assert names[140] == "ELF", "race 0 shares elf's label"

    alignments = [names[158 + i] for i in range(9)]
    assert alignments[0] == "LAWFUL GOOD" and alignments[8] == "CHAOTIC EVIL"

    sg0, _ = _party()
    for slot in sg0.characters:
        rec = slot.record
        bits = rec.get("class_bits")
        if bits == 0x40:                       # paladin: lawful good, always
            assert alignments[rec.get("alignment")] == "LAWFUL GOOD"
        if bits == 0x80:                       # ranger: good, always
            assert alignments[rec.get("alignment")].endswith("GOOD")


def test_a_yaml_export_names_silver_blades_spells_from_its_own_table():
    """The export path reads `COMBAT2` because it is told which title this is.

    Without the title it reaches for `SPELLN00`, which Silver Blades does not
    ship, and every spell comes out as a bare number.

    **The export still stops at spell 55**, which is issue #81: the ranger's
    four druid spells and MORGAINE's fourth- and fifth-level ones are ids 77-94
    and the seven-byte mask cannot reach them. This test asserts the naming,
    not the width, and the two assertions at the end are the width defect
    written down so that fixing it fails here and gets noticed.
    """
    from por.yaml_io import export_save

    data = export_save(str(_save_disk()), str(_game_disk_with(b"COMBAT2")))
    named = [line for entry in data["party"]
             for line in entry.get("_spells_known_named", ())]
    assert named, "no character exported a named spellbook"
    assert not [n for n in named if n.startswith("spell ")], named[:5]
    assert any("(magic-user 3)" in n for n in named)
    assert any("(cleric 3)" in n for n in named)
    assert not any("(druid" in n for n in named), "#81 is fixed; update this"
    assert not any(n.startswith("HOLD MONSTERS") for n in named)


def test_castable_per_level_is_blank_rather_than_pool_of_radiances_numbers():
    """Silver Blades' progression tables have not been read, so nothing is
    claimed about them -- the same rule an unknown race table follows."""
    from por.spells import capacity

    assert capacity(0x02, 9, 18, SSB) == {}
    assert capacity(0x02, 9, 18, games.POOL_OF_RADIANCE)["cleric"]
