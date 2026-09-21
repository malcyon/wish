"""Re-read effect encodings from player-owned engines; never from edited saves."""

import pytest
from gamedata import require_registered

from automap import gamedisks
from goldbox import c64_port, effects
from tools.c64 import coldread
from tools.c64 import effectcrosswalk as cross


def _root(title):
    root = gamedisks.find(title)
    if root is None:
        require_registered(title)
        pytest.skip(f"Needs the player's {title} disks")
    return str(root)


@pytest.fixture(scope="module", params=tuple(cross.SITES))
def packing(request):
    title = request.param
    code, library = cross.load_c64(title, _root(title))
    return cross.read_packing(title, code, library)


def test_all_three_engines_promote_at_64_and_truncate_through_the_same_units(packing):
    assert packing.threshold == 64
    assert packing.ratios == (1, 10, 6, 24)
    assert packing.units == (0, 0x40, 0x80, 0xC0)
    assert packing.divide == {
        "pool-of-radiance": 0x3F04,
        "curse-of-the-azure-bonds": 0x3FE8,
        "secret-of-the-silver-blades": 0x2E93,
    }[packing.title]


def test_the_slot_store_operands_match_the_existing_save_reader(packing):
    base = c64_port.by_key(packing.title).save_load_address
    assert tuple(address - base for address in packing.arrays) == (
        effects.EFFECT_ID_OFFSET, effects.EFFECT_OWNER_OFFSET,
        effects.EFFECT_DURATION_OFFSET, effects.EFFECT_MAGNITUDE_OFFSET)


@pytest.mark.parametrize("minutes, byte", [
    (0, 0), (1, 1), (63, 0x3F), (64, 0x46), (69, 0x46),
    (630, 0x7F), (639, 0x7F), (640, 0x8A), (3780, 0xBF),
    (3839, 0xBF), (3840, 0xC2), (65535, 0xED),
])
def test_promotions_discard_the_remainder_instead_of_rounding_up(packing, minutes, byte):
    assert packing.from_minutes(minutes) == byte


@pytest.mark.parametrize("byte, clock, expected", [
    (0x60, 21 * 60 + 16, 314), (0xA0, 21 * 60 + 17, 1903),
    (0xE0, 21 * 60 + 17, 44803), (1, 21 * 60 + 17, 1),
    (0, 21 * 60 + 17, None),
])
def test_expiry_depends_on_the_clock_phase(byte, clock, expected):
    assert cross.remaining_minutes(byte, clock) == expected


def test_64_minutes_is_unrepresentable_at_a_ten_minute_boundary():
    assert cross.exact_durations(64, 0) == ()
    assert cross.exact_durations(64, 6) == (0x47,)
    assert cross.remaining_minutes(0x46, 0) == 60
    assert cross.remaining_minutes(0x46, 6) == 54


@pytest.mark.parametrize("byte", [0x40, 0x80, 0xC0])
def test_a_nonzero_byte_with_zero_count_is_not_treated_as_permanent(byte):
    with pytest.raises(ValueError, match="zero count"):
        cross.remaining_minutes(byte, 0)


@pytest.fixture(scope="module")
def pool():
    pytest.importorskip("capstone")
    from tools.dos import dosbox, unexepack

    root = _root("pool-of-radiance")
    try:
        game_dir = dosbox.find_game()
    except FileNotFoundError:
        pytest.skip("Needs the player's DOS Pool of Radiance engine")
    image, _ = unexepack.unpack((game_dir / "START.EXE").read_bytes())
    ovr = (game_dir / "GAME.OVR").read_bytes()
    game = c64_port.POOL_OF_RADIANCE
    files = {name: coldread.overlay(game, name.encode(), root) for name in (
        "SPELLE04", "SPELLE01", "CAMP", "SPELLE65", "ECL65")}
    return files, ovr, image


def _confirm(pool):
    files, ovr, image = pool
    return cross.confirm_pool_values(files["SPELLE04"], files["SPELLE01"],
                                     files["CAMP"], files["SPELLE65"], ovr, image)


def test_every_reported_value_rule_reaches_the_engines_own_handler(pool):
    assert _confirm(pool) == (
        "Generic caster level", "Strength", "Charisma", "Mirror Image",
        "Haste age marker", "Prayer allegiance", "Removal flag")


def test_the_spell_tables_agree_except_for_camp_prayer(pool):
    files, _ovr, image = pool
    pairs = cross.spell_pairs(files["ECL65"], image)
    assert len(pairs) == 56
    assert [(p.spell, p.dos_effect, p.c64_camp_effect) for p in pairs
            if p.dos_effect != p.c64_camp_effect] == [(42, 49, 35)]
    assert cross.ordinary_level_ids(pairs) == (
        1, 5, 8, 9, 10, 16, 17, 19, 20, 24, 25, 37, 41, 45, 46)


@pytest.mark.parametrize("data, flag, magnitude", [
    (1, 1, 0x80), (99, 1, 0xE2), (100, 1, 0xE3), (101, 1, 0xE4),
    (115, 1, 0xF3), (125, 1, 0xFD), (99, 0, 0x62),
])
def test_strength_uses_the_restored_value_and_the_separate_flag(pool, data, flag, magnitude):
    _confirm(pool)
    assert cross.flagged_value(cross.strength_value(data), flag) == magnitude


@pytest.mark.parametrize("data", [0, 128, 227, 255])
def test_overlapping_strength_data_is_an_explicit_unknown(data):
    with pytest.raises(ValueError, match="not mapped"):
        cross.strength_value(data)


@pytest.mark.parametrize("value, flag, expected", [
    (15, 1, 0x8F), (1, 0, 1), (4, 0, 4), (5, 0, 5), (0x15, 0, 0x15),
])
def test_charisma_image_count_and_the_haste_age_bit_are_preserved(pool, value, flag, expected):
    _confirm(pool)
    assert cross.flagged_value(value, flag) == expected


@pytest.mark.parametrize("caster_side", [0, 1])
@pytest.mark.parametrize("target_side", [0, 1])
def test_prayers_side_bit_has_the_same_bonus_branch_after_inversion(pool, caster_side, target_side):
    _confirm(pool)
    dos_data = 5 | caster_side << 4
    magnitude = cross.prayer_allegiance(dos_data)
    dos_bonus = ((dos_data >> 4) & 1) == target_side
    c64_bonus = (((magnitude >> 6) & 1) ^ target_side) != 0
    assert c64_bonus == dos_bonus


def test_an_unrecognised_engine_cannot_confirm_the_strength_rule(pool):
    files, ovr, image = pool
    changed = bytearray(ovr)
    changed[0x2BFEA] = 0x48  # A generated mutation: decrement instead of increment.
    with pytest.raises(ValueError, match="Expected inc ax"):
        cross.confirm_pool_values(files["SPELLE04"], files["SPELLE01"],
                                  files["CAMP"], files["SPELLE65"], bytes(changed), image)


def test_the_cli_reuses_the_resolved_registry_root(monkeypatch, tmp_path):
    from tools.dos import unexepack

    disk_root = tmp_path / "c64"
    lookups = []
    reads = []

    def find(game):
        lookups.append(game)
        return disk_root if len(lookups) == 1 else None

    def overlay(_game, name, root):
        assert root == str(disk_root)
        reads.append(name)
        return b""

    monkeypatch.setattr(cross, "tool_disks", find)
    monkeypatch.setattr(cross.coldread, "overlay", overlay)
    monkeypatch.setattr(cross, "read_packing", lambda title, *_:
                        cross.Packing(title, 0, (), (), (), 0))
    monkeypatch.setattr(cross, "spell_pairs", lambda *_: ())
    monkeypatch.setattr(cross, "confirm_pool_values", lambda *_: ())
    monkeypatch.setattr(unexepack, "unpack", lambda _: (b"", {}))
    (tmp_path / "GAME.OVR").write_bytes(b"")
    (tmp_path / "START.EXE").write_bytes(b"")

    assert cross.main(["--dos-dir", str(tmp_path)]) == 0
    assert lookups == [c64_port.POOL_OF_RADIANCE]
    assert reads == [b"SPELLE04", b"LIBRARY", b"ECL65", b"SPELLE01",
                     b"CAMP", b"SPELLE65"]


@pytest.mark.parametrize("argv", [[], ["--disks", ""]])
def test_the_cli_reports_absent_disks_without_writing(monkeypatch, capsys, argv):
    monkeypatch.setattr(cross, "tool_disks", lambda _game: None)
    assert cross.main(argv) == 2
    assert "No C64 disks found" in capsys.readouterr().out
