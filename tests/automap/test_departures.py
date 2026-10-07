"""The departures table: each row names something that exists."""
from __future__ import annotations

from itertools import combinations

from automap import departures, fasttravel


def test_every_route_row_names_a_route_of_its_own_title_that_cannot_fight():
    for row in departures.DEPARTURES:
        if row.route_to is None:
            continue
        assert row.title == departures.POOL_OF_RADIANCE, row
        assert fasttravel.ADDRESSES[row.title].has_exit_reentry, row
        for area in row.areas:
            route = fasttravel.EXIT_ROUTES[(area, row.route_to)]
            assert not route.combat, (area, row.route_to)


def test_no_two_rows_overlap():
    for one, other in combinations(departures.DEPARTURES, 2):
        if one.title != other.title or not one.ports & other.ports:
            continue
        assert one.areas.isdisjoint(other.areas), (one, other)


def test_a_row_is_found_by_title_port_and_area():
    assert departures.find("pool-of-radiance", "c64", 13, 0).member
    assert departures.find("pool-of-radiance", "amiga", 16, 0).writes == (
        (0x4AB5, 254),)
    assert departures.find("pool-of-radiance", "c64", 0, 18) is None
    assert departures.find("secret-of-the-silver-blades", "c64", 0x20, 0) is None


def test_the_pools_of_darkness_row_is_amiga_only_and_ends_with_clear_box():
    row = departures.find("pools-of-darkness", "amiga", 17, 19,
                          to_overland=False)
    assert row.writes == ((0x24, 0), (0x22, 1))
    assert row.clear_box
    assert departures.find("pools-of-darkness", "amiga", 17, 19) is None
    assert departures.find("pools-of-darkness", "amiga", 17, 19,
                           to_overland=True) is None
    assert departures.find("pools-of-darkness", "c64", 17, 19,
                           to_overland=False) is None
    assert departures.find("pools-of-darkness", "amiga", 19, 17,
                           to_overland=False) is None


def test_a_guard_tests_the_byte_the_way_its_operation_says():
    assert departures.Guard(1, "==", 3).holds(3)
    assert departures.Guard(1, "!=", 3).holds(4)
    assert not departures.Guard(1, "not in", (254, 255)).holds(255)
    assert departures.Guard(1, "bits", 0x08).holds(0x18)
    assert not departures.Guard(1, "bits", 0x08).holds(0x10)


def test_applies_is_none_when_a_byte_or_the_party_cannot_be_read():
    row = departures.find("pool-of-radiance", "c64", 13, 0)
    assert departures.applies(row, lambda a: None, None) is None
    assert departures.applies(row, lambda a: 0, ["PRINCESS FATIMA"])
    assert departures.applies(row, lambda a: 0, ["BRUTUS"]) is False
    row = departures.find("pool-of-radiance", "c64", 16, 0)
    assert departures.applies(row, lambda a: None, None) is None
    assert departures.applies(row, lambda a: 255, None) is False


def _pool(area, port="c64", to=0):
    return departures.find(departures.POOL_OF_RADIANCE, port, area, to)


def test_lizardman_keep_needs_both_the_unpaid_byte_and_forty_kills():
    row = _pool(16)
    assert row.route_to is None and row.writes == ((0x4AB5, 254),)
    kills = {0x4A5D: 40, 0x4AB5: 0}
    assert departures.applies(row, kills.get, None)
    assert not departures.applies(row, {**kills, 0x4A5D: 39}.get, None)
    assert not departures.applies(row, {**kills, 0x4AB5: 255}.get, None)
    assert departures.applies(row, {**kills, 0x4AB5: 254}.get, None)


def test_the_pool_write_rows_have_the_guards_and_bytes_of_their_scripts():
    expected = {1: ((("==", 0x4AA9, 1),), ((0x4AA9, 254),)),
                17: ((("bits", 0x4A7C, 5), ("!=", 0x4AB7, 255)),
                     ((0x4AB7, 254),)),
                28: ((), ((0x4AB4, 253),)),
                25: ((("==", 0x4A9E, 255),), ((0x4A9E, 0),))}
    expected[26] = expected[27] = expected[25]
    for area, (guards, writes) in expected.items():
        for port in (departures.C64, departures.AMIGA):
            row = _pool(area, port)
            assert row.writes == writes, area
            assert [(g.op, g.address, g.value) for g in row.guards] == [
                (op, a, v) for op, a, v in guards], area


def test_the_nomad_camp_needs_bit_4_or_bit_1_and_an_unset_byte():
    row = _pool(17)
    for flags, byte, holds in ((4, 0, True), (1, 0, True), (5, 0, True),
                               (2, 0, False), (0, 0, False),
                               (4, 255, False)):
        assert bool(departures.applies(
            row, {0x4A7C: flags, 0x4AB7: byte}.get, None)) is holds


def test_the_cave_flag_row_covers_all_three_windows():
    assert _pool(25).areas == _pool(26).areas == _pool(27).areas == {25, 26, 27}


def test_silver_blades_rows_are_its_own_and_c64_only():
    ssb = departures.SECRET_OF_THE_SILVER_BLADES
    verdigris = departures.find(ssb, "c64", 0x10, 0x20, include_disabled=True)
    assert departures.find(ssb, "c64", 0x10, 0x20) is None
    assert verdigris.writes == ((0x4CD9, 0xFF),)
    assert [(g.address, g.op, g.value) for g in verdigris.guards] == [
        (0x4CD9, "==", 1)]
    assert departures.find(ssb, "amiga", 0x10, 0x20) is None
    for here in (0x50, 0x51, 0x52):
        assert departures.find(ssb, "c64", here, 0x10) is None
        row = departures.find(ssb, "c64", here, 0x10, include_disabled=True)
        assert row.writes == ((0xC059, 9), (0xC05A, 12))
        assert row.guards == ()
        for inside in (0x50, 0x51, 0x52):
            assert departures.find(ssb, "c64", here, inside,
                                   include_disabled=True) is None
    # Pool's rows are not Silver Blades'.
    assert departures.find(ssb, "c64", 17, 0x10) is None
    assert departures.find(ssb, "c64", 28, 0x10) is None


def test_every_item_cleanup_row_names_a_title_that_can_run_a_stub():
    rows = [row for row in departures.DEPARTURES if row.item_cleanup]
    assert rows
    for row in rows:
        assert fasttravel.ADDRESSES[row.title].has_item_cleanup, row
        assert departures.C64 in row.ports, row


def test_a_row_that_dismisses_through_the_stub_names_a_cleanup_to_carry_it():
    for row in departures.DEPARTURES:
        if row.stub_dismiss or row.stub_coin_wipe:
            assert row.item_cleanup, row


def test_a_disabled_row_is_found_only_when_asked_for():
    row = departures.find("curse-of-the-azure-bonds", "c64", 0x25, 0x10,
                          include_disabled=True)
    assert row.item_cleanup == (97, 96) and not row.enabled
    assert departures.find("curse-of-the-azure-bonds", "c64", 0x25, 0x10) is None
    assert departures.find("secret-of-the-silver-blades", "c64", 0x44, 0x10) is None


def test_the_pit_row_carries_the_trigger_the_script_tests():
    row = departures.find("curse-of-the-azure-bonds", "c64", 0x11, 0x10,
                          include_disabled=True)
    assert row.dismiss == ("ALIAS", "DRAGONBAIT") and row.dismiss_npc_only
    assert row.writes == ((0x4C5B, 255),)
    flag = {g.address: g for g in row.guards}
    assert flag[0x4C5B].holds(0) and not flag[0x4C5B].holds(255)
    assert flag[0x4C2D].holds(128) and flag[0x4C2D].holds(255)
    assert not flag[0x4C2D].holds(0)
    assert flag[0x4C2E].holds(130) and not flag[0x4C2E].holds(0)
    assert departures.find("curse-of-the-azure-bonds", "c64", 0x11, 0x12,
                           include_disabled=True) is None


def test_the_haptooth_row_stops_at_the_first_akabar_and_skips_haptooth_moves():
    row = departures.find("curse-of-the-azure-bonds", "c64", 0x31, 0x10,
                          include_disabled=True)
    assert row.dismiss == ("AKABAR BEL AKAS",)
    assert row.dismiss_npc_only and row.dismiss_first_only
    assert row.item_cleanup == (94, 96, 97)
    for to in (0x30, 0x31, 0x32, 0x33):
        assert departures.find("curse-of-the-azure-bonds", "c64", 0x31, to,
                               include_disabled=True) is None


def test_sir_derics_row_tests_no_npc_bit():
    row = departures.find("secret-of-the-silver-blades", "c64", 0x44, 0x10,
                          include_disabled=True)
    assert row.dismiss == ("SIR DERIC",) and not row.dismiss_npc_only
    assert row.dismiss_first_only and row.dismiss_status_flag == (0x4C05, 1)


def test_the_in_guard_tests_membership():
    assert departures.Guard(1, "in", (128, 255)).holds(255)
    assert not departures.Guard(1, "in", (128, 255)).holds(0)
