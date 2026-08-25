"""Curse of the Azure Bonds through the whole editor path.

The strongest check here is the last one: **export a save disk to YAML,
re-import it, and assert the two D64 images are byte-identical.** That
exercises D64, PRG, save geometry, slots, roster, items, icons and YAML in one
shot while asserting nothing about the *meaning* of any field, so it passes
while half of Curse's record is still unidentified. `docs/120-curse-testing.md`
calls it tier 5.1 and names it the check worth having.

Pool of Radiance runs the same round trip as the regression control: it is the
one title in the family whose save is two files, and an invariant that only
runs on one game is an invariant that will be quietly broken for the other.

Every test skips when the disks are absent -- CI has none. Nothing here reads a
committed fixture.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import statistics

import pytest
import yaml

from por import games, geo
from por.d64 import D64, split_load_address
from por.savegame import SaveGameError, load_save
from por.yaml_io import ValueError_, export_save, import_into, to_yaml
from tests import gamedata

CURSE = games.CURSE_OF_THE_AZURE_BONDS
POOL = games.POOL_OF_RADIANCE


# --- finding the player's disks ---------------------------------------------
# `gamedata.curse_disks()` deliberately excludes save disks, and it hands back
# open images rather than paths. The round trip needs a path to copy, so it is
# found here instead of by changing a helper another suite depends on.

def _curse_save_disk() -> pathlib.Path:
    """A Curse disk carrying a whole `SAVEAZURE`, or skip.

    Size is the discriminator, not the name: Curse's own side B carries a
    2032-byte `SAVEAZURE` that is a truncated demo party.
    """
    where = gamedata.curse_dir()
    if where is None:
        pytest.skip(f"needs the Curse disks; set {gamedata.CURSE_ENV}")
    for path in sorted(where.glob("CURSE*.[dD]64")):
        try:
            disk = D64.open(path)
            prg = disk.read_file(CURSE.save_file)
        except Exception:
            continue
        if CURSE.matches_payload(prg):
            return path
    pytest.skip("no Curse disk here carries a whole SAVEAZURE")


def _copy(path, tmp_path) -> str:
    """The disks live on read-only media; every test works on its own copy."""
    out = tmp_path / pathlib.Path(path).name
    shutil.copy(path, out)
    return str(out)


# --- the descriptor ---------------------------------------------------------

def test_the_family_shares_one_payload_shape():
    """Five titles, one 7426-byte file; Pool of Radiance is the outlier."""
    later = [g for g in games.GAMES if g is not POOL]
    assert all(g.save_prg_size == 7426 for g in later)
    assert all(g.roster_in_payload for g in later)
    assert POOL.roster_file == b"SAVEDGAME1" and not POOL.roster_in_payload


@pytest.mark.parametrize("game,slots,items,roster", [
    (games.POOL_OF_RADIANCE, 0x4D00, 0x5900, 0x8300),
    (games.CURSE_OF_THE_AZURE_BONDS, 0x4F00, 0x5B00, 0x6700),
    (games.SECRET_OF_THE_SILVER_BLADES, 0x4F00, 0x5B00, 0x6700),
    (games.CHAMPIONS_OF_KRYNN, 0x4400, 0x5000, 0x5C00),
    (games.DEATH_KNIGHTS_OF_KRYNN, 0x4400, 0x5000, 0x5C00),
    (games.GATEWAY_TO_THE_SAVAGE_FRONTIER, 0x4F00, 0x5B00, 0x6700),
])
def test_the_addresses_are_the_ones_measured(game, slots, items, roster):
    """The table in `work/reports/goldbox-inventory.md`, as an assertion."""
    assert (game.slot_area_base, game.item_area_base, game.roster_base) == (
        slots, items, roster)


def test_every_title_has_its_own_save_file_name():
    """The discriminator only works if no two titles share a name."""
    assert len({g.save_file for g in games.GAMES}) == len(games.GAMES)


def test_a_bad_key_names_the_ones_that_work():
    with pytest.raises(games.UnknownGameError) as exc:
        games.by_key("pool-of-radiance-2")
    assert "curse-of-the-azure-bonds" in str(exc.value)


# --- detection --------------------------------------------------------------

def test_a_curse_disk_identifies_itself():
    assert games.detect(D64.open(_curse_save_disk())) is CURSE


def test_a_pool_of_radiance_disk_identifies_itself():
    path = gamedata.save_disk("PORSAVE11")
    assert games.detect(D64.open(str(path))) is POOL


def test_a_roster_disk_identifies_no_title():
    """`PORSAVE10.D64` holds character files and no save game."""
    path = gamedata.save_disk("PORSAVE10")
    assert games.detect(D64.open(str(path))) is None


# --- reading ----------------------------------------------------------------

def test_a_curse_save_loads_with_no_argument():
    game, sg0, sg1 = load_save(D64.open(_curse_save_disk()))
    assert game is CURSE
    assert len(sg0.to_bytes()) == 0x1D00
    assert sg0.characters, "no character decoded out of SAVEAZURE"
    for slot in sg0.characters:
        assert slot.record.name.strip()


def test_the_curse_roster_is_the_last_page_of_the_save():
    """Its slot-index bytes count 0, 1, 2 ... which is what marks it a roster."""
    _, sg0, sg1 = load_save(D64.open(_curse_save_disk()))
    live = [b for b in sg1.roster_blocks if b.occupied]
    assert live, "no roster block occupied"
    assert [b.slot_index for b in live] == list(range(len(live)))
    assert sg1.roster(0).address == 0x6700
    assert sg1.to_bytes() == sg0.roster_page()


def test_curse_slots_sit_at_4f00():
    _, sg0, _ = load_save(D64.open(_curse_save_disk()))
    assert sg0.slot(0).address == 0x4F00
    assert sg0.slot(1).address == 0x5000


def test_a_truncated_save_is_refused_by_size_not_decoded():
    """Curse side B's 2032-byte `SAVEAZURE` is a demo party, not a save."""
    where = gamedata.curse_dir()
    if where is None:
        pytest.skip(f"needs the Curse disks; set {gamedata.CURSE_ENV}")
    for path in sorted(where.glob("CURSE*.[dD]64")):
        try:
            disk = D64.open(path)
            prg = disk.read_file(CURSE.save_file)
        except Exception:
            continue
        if CURSE.matches_payload(prg):
            continue
        with pytest.raises(SaveGameError) as exc:
            load_save(disk)
        assert str(len(prg)) in str(exc.value)
        return
    pytest.skip("no truncated SAVEAZURE on these disks")


def test_a_disk_with_no_save_says_so():
    path = gamedata.game_disk("POOL2")
    with pytest.raises(SaveGameError) as exc:
        load_save(D64.open(str(path)))
    assert "SAVEAZURE" in str(exc.value)


# --- YAML -------------------------------------------------------------------

def test_the_yaml_records_which_game_it_came_from(tmp_path):
    data = export_save(_copy(_curse_save_disk(), tmp_path))
    assert data["game"] == CURSE.key
    assert yaml.safe_load(to_yaml(data))["game"] == CURSE.key
    assert to_yaml(data).startswith("# Curse of the Azure Bonds")


def test_a_curse_party_will_not_import_into_a_pool_of_radiance_disk(tmp_path):
    data = export_save(_copy(_curse_save_disk(), tmp_path))
    target = _copy(gamedata.save_disk("PORSAVE11"), tmp_path)
    with pytest.raises(ValueError_) as exc:
        import_into(target, data, str(tmp_path / "crossed.d64"))
    assert "Curse of the Azure Bonds" in str(exc.value)
    assert "Pool of Radiance" in str(exc.value)


def test_a_pool_of_radiance_party_will_not_import_into_a_curse_disk(tmp_path):
    data = export_save(_copy(gamedata.save_disk("PORSAVE11"), tmp_path))
    target = _copy(_curse_save_disk(), tmp_path)
    with pytest.raises(ValueError_) as exc:
        import_into(target, data, str(tmp_path / "crossed.d64"))
    assert "Pool of Radiance" in str(exc.value)


def test_a_document_without_a_game_key_is_pool_of_radiance(tmp_path):
    """Every YAML written before this key existed is a Pool of Radiance one."""
    src = _copy(gamedata.save_disk("PORSAVE11"), tmp_path)
    data = export_save(src)
    del data["game"]
    assert import_into(src, data, str(tmp_path / "old.d64")) == []


# --- tier 5.1: the byte-identical round trip --------------------------------

def _round_trip(src: str, out: str) -> tuple[bytes, bytes, list[str]]:
    """Export to YAML, parse it back as a person's editor would, re-import."""
    data = yaml.safe_load(to_yaml(export_save(src)))
    changes = import_into(src, data, out)
    return pathlib.Path(src).read_bytes(), pathlib.Path(out).read_bytes(), changes


def test_a_curse_save_disk_survives_yaml_byte_for_byte(tmp_path):
    src = _copy(_curse_save_disk(), tmp_path)
    before, after, changes = _round_trip(src, str(tmp_path / "curse-out.d64"))
    assert changes == []
    assert before == after


def test_a_pool_of_radiance_save_disk_survives_yaml_byte_for_byte(tmp_path):
    """The control. Two files instead of one, and the same guarantee."""
    src = _copy(gamedata.save_disk("PORSAVE11"), tmp_path)
    before, after, changes = _round_trip(src, str(tmp_path / "por-out.d64"))
    assert changes == []
    assert before == after


def test_a_curse_edit_lands_and_nothing_else_moves(tmp_path):
    """One field changed, one field different -- the rest byte for byte."""
    src = _copy(_curse_save_disk(), tmp_path)
    out = str(tmp_path / "edited.d64")
    data = yaml.safe_load(to_yaml(export_save(src)))
    data["party"][0]["gold"] = 4242
    import_into(src, data, out)
    _, sg0, _ = load_save(D64.open(out))
    slot = data["party"][0]["slot"]
    assert sg0.slot(slot).record.get("gold") == 4242
    before = pathlib.Path(src).read_bytes()
    after = pathlib.Path(out).read_bytes()
    assert sum(a != b for a, b in zip(before, after)) <= 2   # a 16-bit field


# --- the editor -------------------------------------------------------------

def test_the_editor_opens_a_curse_save(tmp_path):
    from editor.roster import Party
    party = Party(_copy(_curse_save_disk(), tmp_path))
    assert party.game is CURSE
    assert party.is_save and party.save1 is not None
    assert [m.name for m in party.members]
    assert party.describe().startswith("Curse of the Azure Bonds save disk")


def test_the_editor_writes_a_curse_save_back_unchanged(tmp_path):
    from editor.window import EditorWindow
    src = _copy(_curse_save_disk(), tmp_path)
    before = pathlib.Path(src).read_bytes()
    window = EditorWindow(src)
    assert window.save(interactive=False) == "no changes"
    assert pathlib.Path(src).read_bytes() == before


def test_the_editor_shows_which_game_is_open(tmp_path):
    from editor.window import EditorWindow
    window = EditorWindow(_copy(_curse_save_disk(), tmp_path))
    assert window._game_label.text() == "Curse of the Azure Bonds"
    window.load(_copy(gamedata.save_disk("PORSAVE11"), tmp_path))
    assert window._game_label.text() == "Pool of Radiance"


# --- tier 1: the static inventory, as assertions -----------------------------
# `docs/120-curse-testing.md` tier 1 was measured by hand while the plan was
# written. Everything it established is here as a test, so that a rip with a
# different file set, or a decoder that stops reading Curse's records, fails
# instead of quietly disagreeing with the document.

def _stem(name: bytes) -> str:
    """A filename up to its first digit: `GEO45` and `GEO01` are both `GEO`."""
    text = bytes(name).decode("latin1")
    cut = re.search(r"[0-9]", text)
    return text[:cut.start()] if cut else text


def _stems(disks) -> set[str]:
    return {_stem(entry.name) for disk in disks for entry in disk.directory()}


def _names(disks) -> set[bytes]:
    return {bytes(entry.name) for disk in disks for entry in disk.directory()}


def _pool_disks():
    """Every readable Pool of Radiance game side, as the inventory control."""
    where = gamedata.disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    out = []
    for path in sorted(where.glob("POOL*.[dD]64")):
        try:
            out.append(D64.open(str(path)))
        except Exception:
            continue
    if not out:
        pytest.skip("no readable Pool of Radiance disk here")
    return out


def test_curse_speaks_pool_of_radiances_file_vocabulary():
    """Same engine, same stems -- and the four places that is not true."""
    curse, pool = _stems(gamedata.curse_disks()), _stems(_pool_disks())
    assert len(curse & pool) >= 30, f"only {len(curse & pool)} stems shared"
    assert {"GEO", "ECL", "ITEMS", "ITEMNAMES", "ITEMFILE", "LIBRARY", "MON",
            "SPELLE", "WALLDEF", "WALLSET", "CHARSET", "COMBAT"} <= curse & pool

    # Pool of Radiance's wilderness and city-block data, and its save overlay,
    # have no Curse counterpart of that name. `docs/120` §1.1.
    assert {"SQRDATA", "SQRPACI", "WALLS", "LOAD/SAVE"}.isdisjoint(curse)
    assert {"SQRDATA", "SQRPACI", "WALLS", "LOAD/SAVE"} <= pool

    # And the stems that are Curse's own.
    assert {"FSDEF", "STOP", "FASTL.O"} <= curse - pool


def test_curse_ships_spelln64_and_no_spelln00():
    """`docs/116` said "Curse has no SPELLN"; it has one of the two."""
    curse, pool = _names(gamedata.curse_disks()), _names(_pool_disks())
    assert b"SPELLN64" in curse and b"SPELLN00" not in curse
    assert {b"SPELLN00", b"SPELLN64"} <= pool


def test_the_curse_save_is_one_file_where_pool_of_radiance_writes_two():
    disk = D64.open(_curse_save_disk())
    prg = disk.read_file(CURSE.save_file)
    assert len(prg) == 7426 == CURSE.save_prg_size
    assert split_load_address(prg)[0] == 0x4B00 == CURSE.save_load_address
    assert CURSE.files == (b"SAVEAZURE",)
    assert POOL.files == (b"SAVEDGAME0", b"SAVEDGAME1")


def _geo_ids(disks) -> list[int]:
    """Every `GEOnn` id on a set of sides, as numbers, sorted and unique."""
    out = set()
    for disk in disks:
        for entry in disk.directory():
            name = bytes(entry.name)
            if len(name) == 5 and name.startswith(b"GEO"):
                try:
                    out.add(int(name[3:], 16))
                except ValueError:
                    continue
    return sorted(out)


def test_curse_map_ids_are_sparse_so_nothing_may_enumerate_by_count():
    """`GEO01 03 04 / 10 11 15 / 20 21 25 / 32 33 35 / 40 42 43 45`.

    Pool of Radiance runs `$00`-`$20` nearly dense, so a loop over `range(n)`
    works there and finds three quarters of nothing in Curse. Anything that
    enumerates maps must read the directory.
    """
    curse, pool = _geo_ids(gamedata.curse_disks()), _geo_ids(_pool_disks())
    assert len(curse) >= 16
    assert 0x00 not in curse, "Curse has no GEO00"
    span = curse[-1] - curse[0] + 1
    assert span > 2 * len(curse), f"{curse} is dense, not sparse"
    # The control: the same measure on Pool of Radiance says dense.
    assert pool[-1] - pool[0] + 1 < 1.5 * len(pool)


# --- tier 1.3: the records come out sane -------------------------------------

#: PETSCII as a name may use it: space through `_`, upper case only. `F/T` is a
#: real Curse character name, so punctuation is in and lower case is out.
_NAME_BYTES = frozenset(range(0x20, 0x60))


def _sane_name(raw: bytes) -> None:
    """The name reads to its NUL, and every byte of it is printable PETSCII.

    **Not NUL-padded, and asserting that it is fails on real specimens.** The
    field is 20 bytes and the game terminates at the first NUL without clearing
    what follows: `MALCYON\\x00N` and `SILAS\\x00S` in Pool of Radiance are
    characters renamed shorter, and Curse's `PALADIN` carries `\\x01\\x01` in
    its last two bytes where Silver Blades' `GUY DE VALOIS` carries
    `\\x02\\x01`. The residue is stale, not name.
    """
    text = raw.split(b"\x00")[0]
    assert text, "a character with no name"
    assert set(text) <= _NAME_BYTES, f"{raw!r} is not printable PETSCII"
    assert len(raw) == 20


def _sane_character(rec) -> None:
    """Things a person would recognise, not merely bytes that parsed."""
    _sane_name(rec.get_raw("name"))
    for score in (rec.strength, rec.intelligence, rec.wisdom, rec.dexterity,
                  rec.constitution, rec.charisma):
        assert 3 <= score <= 18, f"ability score {score} is not 3-18"
    assert 0 <= rec.exceptional_strength <= 100
    assert 1 <= rec.race <= 7
    assert 1 <= rec.level <= 40
    assert 0 < rec.hp_max <= 999
    assert rec.hp_rolled <= rec.hp_max
    for save in (rec.save_paralysis, rec.save_petrification, rec.save_wands,
                 rec.save_breath, rec.save_spell):
        assert 1 <= save <= 20, f"saving throw {save} out of range"
    assert 1 <= rec.movement <= 24
    # 10 for every player character: the `60 - value` encoding intact.
    assert rec.armour_class_base_value == 10

    # `class_bits` is the field to read, and it is one bit per non-zero slot of
    # the eight-wide level array at `0x0C9`. Curse fills slots 6 and 7 --
    # paladin and ranger -- which is why the array is eight and not four.
    levels = rec.slice(0x0C9, 8)
    assert rec.get("class_bits") == sum(
        1 << i for i, lv in enumerate(levels) if lv), (
        f"class_bits {rec.get('class_bits'):#04x} against {list(levels)}")
    assert max(levels) <= rec.level


def _curse_parties():
    """Every whole Curse save on the player's disks, as `(name, SaveGame0)`."""
    where = gamedata.curse_dir()
    if where is None:
        pytest.skip(f"needs the Curse disks; set {gamedata.CURSE_ENV}")
    out = []
    for path in sorted(where.glob("CURSE*.[dD]64")):
        try:
            game, sg0, _ = load_save(D64.open(path))
        except Exception:
            continue                      # no save, or the truncated demo one
        if game is CURSE:
            out.append((path.name, sg0))
    if not out:
        pytest.skip("no whole Curse save on these disks")
    return out


def test_every_curse_character_parses_with_fields_a_person_would_recognise():
    seen = 0
    for name, sg0 in _curse_parties():
        assert sg0.characters, f"{name} decoded no characters"
        for slot in sg0.characters:
            _sane_character(slot.record)
            seen += 1
    assert seen >= 6, f"only {seen} Curse characters checked"


def test_pool_of_radiance_characters_satisfy_the_same_invariants():
    """The control. If this fails the invariants are wrong, not Curse."""
    _, sg0, _ = load_save(D64.open(str(gamedata.save_disk("PORSAVE11"))))
    assert sg0.characters
    for slot in sg0.characters:
        _sane_character(slot.record)


# --- tier 2: the map files ---------------------------------------------------
# Two reciprocity measures, because they fail at different things. The barrier
# field catches a wrong plane order or a wrong direction order; it is blind to
# the two art planes, which is exactly the transposition `docs/120` tier 2
# flagged as PROBABLE and untested. Wall art catches that, and the mangled
# controls below are what make either floor worth asserting.

#: Measured over Curse's sixteen maps: barrier mean 0.984, worst 0.935; art
#: mean 0.994, worst 0.919. Pool of Radiance is barrier 0.991/0.940 and art
#: 0.960/0.646. A wrong parse scores about 0.3-0.5.
BARRIER_FLOOR = 0.92
ART_FLOOR = 0.90
MEAN_FLOOR = 0.97
MANGLED_ART_CEILING = 0.70
MANGLED_BARRIER_CEILING = 0.90


def _geo_payloads(disks) -> dict[str, bytes]:
    out = {}
    for disk in disks:
        for entry in disk.directory():
            if not entry.name.startswith(b"GEO"):
                continue
            data = disk.read_file(entry)
            load, payload = split_load_address(data)
            assert len(payload) == geo.GEO_SIZE, (
                f"{entry.name!r} is {len(payload)} bytes, not a GEO")
            out[bytes(entry.name).decode("latin1")] = payload
    return out


def _barrier_reciprocity(payload: bytes) -> float:
    agree, total = geo.Geo(payload).reciprocity()
    return agree / total


def _art_reciprocity(payload: bytes) -> float:
    """Does an edge carry wall art read from both of the squares it divides?

    Deliberately presence, not value: the art *index* differs between the two
    sides of a one-way wall, and Curse indexes a different `WALLDEF` set than
    Pool of Radiance does. What must agree is that a wall is drawn at all.
    """
    grid = geo.Geo(payload)
    ok = total = 0
    for y in range(geo.GRID):
        for x in range(geo.GRID):
            for direction in (geo.EAST, geo.SOUTH):
                dx, dy = geo.STEP[direction]
                nx, ny = x + dx, y + dy
                if not (0 <= nx < geo.GRID and 0 <= ny < geo.GRID):
                    continue
                total += 1
                ok += bool(grid.wall(x, y, direction)) == bool(
                    grid.wall(nx, ny, geo.OPPOSITE[direction]))
    return ok / total


def _swap_art_planes(payload: bytes) -> bytes:
    """`$000` and `$100` exchanged: north/east art read as south/west."""
    out = bytearray(payload)
    out[0x000:0x100], out[0x100:0x200] = out[0x100:0x200], out[0x000:0x100]
    return bytes(out)


def _swap_art_nibbles(payload: bytes) -> bytes:
    """High and low nibble exchanged in both art planes."""
    out = bytearray(payload)
    for i in range(0x200):
        out[i] = ((out[i] & 0x0F) << 4) | (out[i] >> 4)
    return bytes(out)


def _reverse_barrier_directions(payload: bytes) -> bytes:
    """`N E S W` read as `W S E N`: the two-bit field in the wrong order."""
    out = bytearray(payload)
    for i in range(geo.BARRIERS, geo.BARRIERS + 0x100):
        b = out[i]
        out[i] = ((b & 3) << 6) | (((b >> 2) & 3) << 4) | \
                 (((b >> 4) & 3) << 2) | ((b >> 6) & 3)
    return bytes(out)


def test_every_curse_map_decodes_through_the_unmodified_decoder():
    maps = _geo_payloads(gamedata.curse_disks())
    assert len(maps) >= 16, f"expected at least 16 Curse maps, found {len(maps)}"
    scores = {n: _barrier_reciprocity(p) for n, p in maps.items()}
    worst = min(scores, key=scores.get)
    assert scores[worst] > BARRIER_FLOOR, (
        f"{worst} barrier reciprocity {scores[worst]:.3f}")
    assert statistics.mean(scores.values()) > MEAN_FLOOR


def test_curse_wall_art_is_reciprocal_which_the_barrier_field_cannot_show():
    """The art planes are not transposed, which reciprocity alone never says.

    `docs/120` tier 2 lists the nibble order as PROBABLE precisely because
    `Geo.reciprocity` reads barriers only and would survive a consistent
    transposition of the art. This is the check that would not.
    """
    maps = _geo_payloads(gamedata.curse_disks())
    scores = {n: _art_reciprocity(p) for n, p in maps.items()}
    worst = min(scores, key=scores.get)
    assert scores[worst] > ART_FLOOR, (
        f"{worst} wall-art reciprocity {scores[worst]:.3f}")
    assert statistics.mean(scores.values()) > MEAN_FLOOR


@pytest.mark.parametrize("mangle", [_swap_art_planes, _swap_art_nibbles])
def test_a_transposed_art_parse_fails_the_floor_the_real_one_clears(mangle):
    """The floor is only evidence if a wrong reading falls through it."""
    maps = _geo_payloads(gamedata.curse_disks())
    scores = [_art_reciprocity(mangle(p)) for p in maps.values()]
    assert statistics.mean(scores) < MANGLED_ART_CEILING


def test_reading_the_barrier_directions_backwards_fails_too():
    maps = _geo_payloads(gamedata.curse_disks())
    scores = [_barrier_reciprocity(_reverse_barrier_directions(p))
              for p in maps.values()]
    assert statistics.mean(scores) < MANGLED_BARRIER_CEILING


def test_pool_of_radiance_maps_clear_the_same_barrier_floor():
    """The control for the barrier floor, on the corpus it was derived from."""
    maps = _geo_payloads(_pool_disks())
    assert len(maps) >= 29
    scores = {n: _barrier_reciprocity(p) for n, p in maps.items()}
    worst = min(scores, key=scores.get)
    assert scores[worst] > BARRIER_FLOOR, (
        f"{worst} barrier reciprocity {scores[worst]:.3f}")
    assert statistics.mean(scores.values()) > MEAN_FLOOR


def test_pool_of_radiance_wall_art_is_less_reciprocal_than_curses():
    """Not a defect: Pool of Radiance draws genuinely one-sided walls.

    Its worst file scores 0.646 where Curse's worst is 0.919, which is why the
    per-file art floor is asserted on Curse and only the corpus mean on Pool of
    Radiance. Stated as a test so the difference stays a measurement rather
    than folklore.
    """
    scores = [_art_reciprocity(p) for p in _geo_payloads(_pool_disks()).values()]
    assert 0.95 < statistics.mean(scores) < MEAN_FLOOR
    assert min(scores) < ART_FLOOR


# --- tier 5.1(c): a Curse character export round-trips -----------------------

def test_a_curse_character_export_round_trips_byte_for_byte():
    """The export path, which the save round trip never touches.

    Curse marks an export with a leading `\\x02` where Pool of Radiance uses
    `\\x01`, and writes 582 bytes at `$7C00` -- a different marker and a
    different load address, but the same 580-byte record. It is also the file
    the directory reports as **zero blocks**, which is why finding it at all
    took a fix to `tests/gamedata.py:curse_file`.
    """
    from por.record import CharacterRecord
    exports = gamedata.curse_exports()
    if not exports:
        pytest.skip("no Curse character export on the player's disks")
    for name, prg in exports.items():
        assert name.startswith(b"\x02"), f"{name!r} is not a Curse export"
        assert len(prg) == 582
        assert split_load_address(prg)[0] == 0x7C00
        record = CharacterRecord.from_prg(prg, 0x7C00)
        _sane_character(record)
        assert record.to_prg(0x7C00) == prg


# --- issue #31: the fields the editor shows ---------------------------------


def _curse_file(name: bytes) -> bytes:
    """One payload off whichever Curse side carries it, or skip."""
    for disk in gamedata.curse_disks():
        entry = disk.find(name)
        if entry is not None:
            return split_load_address(disk.read_file(entry))[1]
    pytest.skip(f"no Curse side here carries {name.decode()}")


def _curse_disk_with(name: bytes) -> pathlib.Path:
    where = gamedata.curse_dir()
    if where is None:
        pytest.skip("needs the Curse disks")
    for path in sorted(where.glob("CURSE*.[dD]64")):
        try:
            if D64.open(str(path)).find(name) is not None:
                return path
        except Exception:
            continue
    pytest.skip(f"no Curse side here carries {name.decode()}")


def test_the_combat_icon_charset_is_pool_of_radiances_byte_for_byte():
    """`CHARPIC00` is on every Curse side and is the same 2030 bytes.

    So the icon editor's charset needs no per-title anything for this title;
    Silver Blades redraws three glyphs and that is the whole family's variation.
    """
    from por.icons import load_icon_charset

    por = load_icon_charset(str(gamedata.game_disk("POOL1")))
    seen = 0
    for disk in gamedata.curse_disks():
        if disk.find(b"CHARPIC00") is None:
            continue
        assert load_icon_charset(disk) == por
        seen += 1
    assert seen >= 5, f"only {seen} Curse sides carry CHARPIC00"


def test_every_shipped_curse_icon_is_a_weapon_and_a_head():
    """`SPELLE64` is Pool of Radiance's bytes at `$8E00` rather than `$A700`.

    `IconParts` fits the base out of the editor's own pointer table. Before
    #31 it named `$A700`, every table offset came out negative, and composing
    an icon raised `IndexError` -- so the parts picker could not be opened on
    this title at all.
    """
    from por.iconparts import IconParts
    from por.icons import ICON_COUNT, ICON_SIZE

    parts = IconParts.load(str(_curse_disk_with(b"SPELLE64")))
    assert parts.base == 0x8E00
    assert parts.count("large", "weapon") == 35

    reachable = set()
    for weapon_size in ("small", "large"):
        for head_size in ("small", "large"):
            for w in range(parts.count(weapon_size, "weapon")):
                shape = parts.apply(bytes([0x20] * 18), weapon_size, "weapon", w)
                for h in range(parts.count(head_size, "head")):
                    reachable.add(parts.apply(shape, head_size, "head", h))

    # SSI's own pre-generated party, not the player's: an icon a person has
    # hand-edited need not be one pair, because a weapon change preserves the
    # head and the two menus can be walked in any order. `legal_shapes` is the
    # question that asks about those; this one asks about the tables.
    payload = None
    for disk in gamedata.curse_disks():
        entry = disk.find(CURSE.save_file)
        if entry is not None and CURSE.matches_payload(disk.read_file(entry)):
            payload = split_load_address(disk.read_file(entry))[1]
            break
    if payload is None:              # side B's SAVEAZURE is a 2032-byte stub
        pytest.skip("no Curse side here carries a whole SAVEAZURE")
    base = games.ICON_TABLE_OFFSET
    unmade = [payload[base + i * ICON_SIZE:][:18].hex()
              for i in range(ICON_COUNT)
              if any(payload[base + i * ICON_SIZE:][:18])
              and bytes(payload[base + i * ICON_SIZE:][:18]) not in reachable]
    assert not unmade, unmade


def test_curses_item_lists_still_carry_the_file_in_their_name():
    """`ITEMFILE01`, not Silver Blades' `ITEM10` -- and `ITEMS` is neither."""
    from por.items import is_item_list

    stems = {bytes(e.name).upper()
             for disk in gamedata.curse_disks() for e in disk.directory()}
    lists = {n for n in stems if is_item_list(n)}
    assert len(lists) >= 10, sorted(lists)
    assert all(n.startswith(b"ITEMFILE") for n in lists), sorted(lists)
    assert not ({b"ITEMS", b"ITEMNAMES"} & lists)


# The cleric's spell grant, read out of `GEN` rather than guessed from the
# names. The routine is `LDX <cleric level> / BEQ out / LDY levels,X /
# LDX offsets,Y / LDA masks,Y / ORA record,X / STA record,X / DEY / BPL`, and
# the `BEQ` target is the `RTS` that the level table's own index 0 sits on --
# which is what fixes the overlay's base without fitting anything.
_GRANT_LOOP = re.compile(
    rb"\xAE(.)\x7C\xF0(.)\xBC(..)\xBE(..)\xB9(..)\x1D\x00\x7C\x9D\x00\x7C"
    rb"\x88\x10\xF1\x60", re.DOTALL)


def _grant_table(payload: bytes, record_offset: int):
    """(level -> set of spell ids) for one of `GEN`'s grant routines."""
    for match in _GRANT_LOOP.finditer(payload):
        if match.group(1)[0] != record_offset:
            continue
        levels, offsets, masks = (
            g[0] | g[1] << 8 for g in match.group(3, 4, 5))
        rts = match.end() - 1                        # file offset of the RTS
        base = levels - rts                          # the overlay's load address
        assert base == 0x0800, f"${base:04X} is not the overlay base"
        out, granted = {}, set()
        for level in range(1, 11):
            top = payload[levels - base + level]
            granted = set()
            for y in range(top + 1):
                byte = payload[offsets - base + y]
                mask = payload[masks - base + y]
                assert 0x078 <= byte <= 0x087, f"${byte:02X} is not the mask"
                granted |= {(byte - 0x078) * 8 + bit
                            for bit in range(8) if mask & (1 << bit)}
            out[level] = granted
        return out
    pytest.skip("GEN carries no grant loop for that class")


def test_curses_cleric_spell_groups_are_read_out_of_gens_own_grant_table():
    """`por/spells.py`'s Curse cleric groups were inferred from the names.
    This is the game's own table saying the same thing.

    It also carries an AD&D check of its own: the levels at which a new spell
    level appears are 1, 3, 5, 7 and 9, which is the 1st edition cleric
    progression exactly.
    """
    from por.spells import CURSE_OF_THE_AZURE_BONDS as TABLE

    grants = _grant_table(_curse_file(b"GEN"), 0xCA)      # 0x0CA, cleric level
    expected = {}
    for low, high, cls, level in TABLE.groups:
        if cls == "cleric":
            expected.setdefault(level, set()).update(range(low, high + 1))

    got_new = {level: grants[level] - grants.get(level - 1, set())
               for level in sorted(grants) if grants[level] != grants.get(level - 1)}
    assert sorted(got_new) == [1, 3, 5, 7, 9], sorted(got_new)
    for spell_level, (game_level, ids) in enumerate(sorted(got_new.items()), 1):
        want = expected[spell_level]
        # Everything the trainer grants is inside the group `por/spells.py`
        # claims -- that is the direction that matters. Two ids the group
        # claims are never granted: 36 ANIMATE DEAD and 100 BESTOW CURSE, both
        # of which a player meets on a scroll rather than at a temple.
        assert ids <= want, (spell_level, sorted(ids - want))
        assert want - ids <= {36, 100}, (spell_level, sorted(want - ids))


def test_curses_magic_user_grant_writes_no_further_than_0x07e():
    """What is actually measured about Curse's spellbook width, and no more.

    Silver Blades' width is settled -- `GEN` clears sixteen bytes at `$7C78`.
    Curse's `GEN` has no such loop, so the only measurement available is where
    its own grant tables write: `0x07E` for the magic-user, `0x081` for the
    cleric. Ten bytes, not seven and not proven to be sixteen.
    """
    payload = _curse_file(b"GEN")
    assert b"\xA2\x0F\xA9\x00\x9D\x78\x7C\xCA\x10\xFA" not in payload, (
        "Curse's GEN does have a spellbook clear loop after all -- read it")

    reach = 0
    for record_offset in (0xC9, 0xCA):
        for match in _GRANT_LOOP.finditer(payload):
            if match.group(1)[0] != record_offset:
                continue
            offsets = match.group(4)[0] | match.group(4)[1] << 8
            levels = match.group(3)[0] | match.group(3)[1] << 8
            base = levels - (match.end() - 1)
            top = max(payload[levels - base + lv] for lv in range(1, 11))
            reach = max(reach,
                        max(payload[offsets - base + y] for y in range(top + 1)))
    assert reach == 0x081, f"the grant tables reach 0x{reach:03X}"
