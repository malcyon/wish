"""Re-read effect encodings from player-owned engines; never from edited saves."""

from collections import Counter

import pytest

from automap import gamedisks
from goldbox import c64_port, effects
from tools.c64 import coldread
from tools.c64 import effectcrosswalk as cross


def _root(title):
    try:
        root = gamedisks.find(title)
    except gamedisks.RegistryMissing:
        pytest.skip(f"Needs the player's {title} disks")
    if root is None:
        pytest.skip(f"Needs the player's {title} disks")
    return str(root)


@pytest.mark.parametrize("title, variable", [
    ("pool-of-radiance", "POR_DISKS"),
    ("curse-of-the-azure-bonds", "COAB_DISKS"),
    ("secret-of-the-silver-blades", "SSB_DISKS"),
])
@pytest.mark.parametrize("registry_exists", [True, False])
def test_disk_lookup_skips_missing_data_and_registries(
        monkeypatch, tmp_path, title, variable, registry_exists):
    registry = tmp_path / "gamedisks.yaml"
    monkeypatch.setattr(gamedisks, "REGISTRY", registry)
    if registry_exists:
        registry.write_text("{}\n")
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv(variable, str(empty))
    else:
        monkeypatch.delenv(variable, raising=False)
    with pytest.raises(pytest.skip.Exception, match="Needs the player's"):
        _root(title)


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
        "SPELLE04", "SPELLE01", "CAMP", "SPELLE65", "ECL65", "LIBRARY",
        "COMBAT", "SQRPACI01")}
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


def test_pool_retains_character_owned_prayer_but_not_dos_strength_stacking(pool):
    files, ovr, _image = pool
    assert cross.confirm_pool_state(files, ovr) == (
        "Strength stacking differs", "Prayer character-owner route")


def test_pool_prayer_proof_rejects_truncated_combat_check_lists(pool):
    files, ovr, _image = pool
    table = files["SPELLE65"]
    end = 0x570
    for _ in range(13):
        end = table.index(0, end) + 1
    truncated = table[:end] + bytes(2)
    with pytest.raises(ValueError, match="Prayer check lists"):
        cross.confirm_pool_state({**files, "SPELLE65": truncated}, ovr)


@pytest.mark.parametrize("name, offset, value", [
    ("SPELLE04", 0xA902 - 0xA700, 0x90),
    ("LIBRARY", 0x4000 - 0x2C48, 0xD0),
    ("SQRPACI01", 0x0792 - 0x0400, 0x64),
    ("DOS", 0xF1B8, 0x72),
])
def test_pool_state_proof_rejects_changed_overlap_or_owner_branches(pool, name, offset, value):
    files, ovr, _image = pool
    changed = bytearray(ovr if name == "DOS" else files[name])
    changed[offset] = value
    if name == "DOS":
        ovr = bytes(changed)
    else:
        files = {**files, name: bytes(changed)}
    with pytest.raises(ValueError):
        cross.confirm_pool_state(files, ovr)


@pytest.fixture(scope="module", params=("curse-of-the-azure-bonds",
                                       "secret-of-the-silver-blades"))
def later(request):
    pytest.importorskip("capstone")
    from tools.dos import dosbox, unexepack

    title = request.param
    root = _root(title)
    try:
        folder = dosbox.find_game("CURSE" if title.startswith("curse") else "SECRET")
    except FileNotFoundError:
        pytest.skip(f"Needs the player's DOS {title} engine")
    image, _ = unexepack.unpack((folder / "START.EXE").read_bytes())
    ovr = (folder / "GAME.OVR").read_bytes()
    game = c64_port.by_key(title)
    combat = coldread.overlay(game, b"COMBAT", root)
    table = coldread.overlay(game, b"COMBAT2", root)
    return title, combat, table, ovr, image


def test_later_values_are_read_from_each_titles_handlers(later):
    title = later[0]
    checks = cross.confirm_later_values(*later)
    assert checks == ("Haste age marker", "Prayer allegiance",
                      "Mirror Image count" if title.startswith("secret")
                      else "Mirror Image raw-decrement mismatch")


@pytest.mark.parametrize("dos_data", [1, 5, 17, 21])
def test_later_prayer_preserves_the_side_bit_without_pools_inversion(later, dos_data):
    cross.confirm_later_values(*later)
    magnitude = cross.prayer_allegiance(dos_data, title=later[0])
    for target_side in (0, 1):
        assert ((magnitude >> 6) == target_side) == (
            ((dos_data >> 4) & 1) == target_side)


@pytest.mark.parametrize("part", ["prayer", "haste", "mirror", "dispatch"])
def test_later_proof_rejects_changed_handlers(later, part):
    title, combat, table, ovr, image = later
    curse = title.startswith("curse")
    if part in ("prayer", "haste"):
        changed = bytearray(combat)
        at = ((0x2272 if curse else 0x27CB) if part == "prayer"
              else (0x2211 if curse else 0x2762))
        changed[at - 0x0800] ^= 0x20 if part == "prayer" else 1
        combat = bytes(changed)
    elif part == "dispatch":
        changed = bytearray(table)
        changed[(0xEE2A if curse else 0xEF90) - 0xE000 + 49] ^= 1
        table = bytes(changed)
    else:
        changed = bytearray(ovr)
        changed[0x10639 if curse else 0x117D8] = 3
        ovr = bytes(changed)
    with pytest.raises(ValueError):
        cross.confirm_later_values(title, combat, table, ovr, image)


@pytest.mark.parametrize("data, count", [(0x11, 1), (0x4F, 4), (0xF1, 15)])
def test_silver_blades_mirror_image_removes_the_caster_level_nibble(data, count):
    assert cross.mirror_image_value("secret-of-the-silver-blades", data) == count


def test_curse_mirror_image_is_not_silently_given_silver_blades_rule():
    with pytest.raises(ValueError, match="not mapped"):
        cross.mirror_image_value("curse-of-the-azure-bonds", 0x41)


@pytest.mark.parametrize("phase, exact", [(0, 216), (17, 215), (1439, 214)])
def test_duration_census_counts_exact_minutes_and_bounds_floor_policy_loss(phase, exact):
    assert cross.duration_census(phase) == (exact, 1439)


def test_all_camp_clock_phases_have_the_reported_duration_coverage():
    results = [cross.duration_census(phase) for phase in range(1440)]
    assert Counter(exact for exact, _loss in results) == {
        213: 21, 214: 276, 215: 702, 216: 441}
    assert {loss for _exact, loss in results} == {1439}


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
    monkeypatch.setattr(cross, "confirm_pool_state", lambda *_: ())
    monkeypatch.setattr(unexepack, "unpack", lambda _: (b"", {}))
    (tmp_path / "GAME.OVR").write_bytes(b"")
    (tmp_path / "START.EXE").write_bytes(b"")

    assert cross.main(["--dos-dir", str(tmp_path)]) == 0
    assert lookups == [c64_port.POOL_OF_RADIANCE]
    assert reads == [b"SPELLE04", b"LIBRARY", b"ECL65", b"SPELLE01",
                     b"CAMP", b"SPELLE65", b"COMBAT", b"SQRPACI01"]


@pytest.mark.parametrize("argv", [[], ["--disks", ""]])
def test_the_cli_reports_absent_disks_without_writing(monkeypatch, capsys, argv):
    monkeypatch.setattr(cross, "tool_disks", lambda _game: None)
    assert cross.main(argv) == 2
    assert "No C64 disks found" in capsys.readouterr().out


def test_the_cli_rejects_negative_clock_minutes_before_resolving_disks(monkeypatch, capsys):
    def unexpected_lookup(_game):
        pytest.fail("Invalid clock input reached the disk lookup")

    monkeypatch.setattr(cross, "tool_disks", unexpected_lookup)
    with pytest.raises(SystemExit) as stopped:
        cross.main(["--clock-minutes", "-1"])
    assert stopped.value.code == 2
    assert "Clock minutes must be zero or greater" in capsys.readouterr().err
