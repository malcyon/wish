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
import shutil

import pytest
import yaml

from por import games
from por.d64 import D64
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
