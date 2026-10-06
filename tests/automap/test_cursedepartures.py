"""The C64 Curse and Silver Blades departures that drop party members and run
the item cleanup: their guards, their writes, and the stub a trip starts the
game at.

The rows are built and tested but disabled, so a test that exercises a row
enables it first (`enabled`)."""
from __future__ import annotations

import dataclasses

import pytest

from automap import actions, c64, departures, fasttravel
from goldbox import areas as goldbox_areas
from goldbox import c64_port
from goldbox.record import RECORD_SIZE, CharacterRecord
from goldbox.savegame import ROSTER_SLOT_INDEX, ROSTER_STRIDE, SLOT_STRIDE

CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
SSB = c64_port.SECRET_OF_THE_SILVER_BLADES
CURSE_ADDR = fasttravel.CURSE_OF_THE_AZURE_BONDS
CURSE_MACHINE = c64.machine_for(CURSE)

ROSTER = 0x6700
RECORDS = 0x4F00
ITEM_PAGES = 0x5B00


class ByteTarget:
    """A 64 KiB machine that can start the game at an address."""

    def __init__(self, can_set_pc: bool = True):
        self.ram = bytearray(0x10000)
        self.jumps: list[int] = []
        self.can_set_pc = can_set_pc

    def read(self, address: int, length: int) -> bytes:
        return bytes(self.ram[address:address + length])

    def write(self, address: int, data: bytes) -> None:
        self.ram[address:address + len(data)] = data

    def __getattr__(self, name):
        if name == "set_pc" and self.can_set_pc:
            return self.jumps.append
        raise AttributeError(name)


def record_page(name: str, npc: bool = False) -> bytes:
    record = CharacterRecord.from_bytes(bytes(RECORD_SIZE))
    record.set("name", name)
    page = bytearray(bytes(record)[:SLOT_STRIDE])
    if npc:
        page[0x0B8] |= 0x80
    return bytes(page)


def put_member(target, game, slot: int, index: int, name: str, npc: bool,
               status: int = 1) -> None:
    machine = c64.machine_for(game)
    block = bytearray(ROSTER_STRIDE)
    block[0] = status
    block[ROSTER_SLOT_INDEX] = index
    target.write(machine.roster_base + slot * ROSTER_STRIDE, bytes(block))
    target.write(machine.slot_area_base + index * SLOT_STRIDE,
                 record_page(name, npc))


def trip_machine(game, addr, area: int, party) -> ByteTarget:
    """`party` is `(slot, record index, name, npc, status)` tuples."""
    target = ByteTarget()
    target.write(addr.slot, bytes([area]))
    target.write(addr.disk, b"\x03")
    target.write(addr.indoors, b"\x01")
    target.write(addr.live_square, bytes([5, 6, 1]))
    for slot, index, name, npc, *status in party:
        put_member(target, game, slot, index, name, npc, *status)
    return target


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(departures, "DEPARTURES", tuple(
        dataclasses.replace(row, enabled=True)
        for row in departures.DEPARTURES))


def curse_trip(target, to: int = 0x10, game=CURSE):
    ft = actions.FastTravel(game)
    return ft.run(target, area=ft._row(to))


def written(outcome) -> list[int]:
    return [a for a, _ in outcome.writes]


# --- the stub ------------------------------------------------------------


def test_the_c2_stub_with_akabar_is_the_30_bytes_the_read_gives():
    stub = actions.item_cleanup_stub(CURSE_ADDR, (94, 96, 97),
                                     dismiss_slot=3, coin_wipe=True)
    assert stub == bytes([
        0xD8,                      # CLD
        0x20, 0xDF, 0x15,          # JSR $15DF
        0xA9, 0x03, 0x8D, 0xB4, 0x7E,   # LDA #3 / STA $7EB4
        0x20, 0x71, 0x16,          # JSR $1671
        0xA9, 0x5E, 0x20, 0xA1, 0x16,   # LDA #94 / JSR $16A1
        0xA9, 0x60, 0x20, 0xA1, 0x16,   # LDA #96 / JSR $16A1
        0xA9, 0x61, 0x20, 0xA1, 0x16,   # LDA #97 / JSR $16A1
        0x4C, 0xDD, 0x21])         # JMP $21DD
    assert len(stub) == CURSE_ADDR.stub_len == 30


def test_a_stub_without_akabar_leaves_out_the_dismissal():
    stub = actions.item_cleanup_stub(CURSE_ADDR, (94, 96, 97),
                                     coin_wipe=True)
    assert stub == (bytes([0xD8, 0x20, 0xDF, 0x15])
                    + bytes([0xA9, 0x5E, 0x20, 0xA1, 0x16,
                             0xA9, 0x60, 0x20, 0xA1, 0x16,
                             0xA9, 0x61, 0x20, 0xA1, 0x16])
                    + bytes([0x4C, 0xDD, 0x21]))


@pytest.mark.parametrize("types, length", [((97, 96), 14), ((94, 96, 97), 19)])
def test_a_c3_stub_is_clear_decimal_flag_the_calls_and_the_jump(types, length):
    stub = actions.item_cleanup_stub(CURSE_ADDR, types)
    expected = bytes([0xD8])
    for t in types:
        expected += bytes([0xA9, t, 0x20, 0xA1, 0x16])
    assert stub == expected + bytes([0x4C, 0xDD, 0x21])
    assert len(stub) == length


def test_a_stub_that_does_not_fit_is_an_error():
    small = dataclasses.replace(CURSE_ADDR, stub_len=29)
    with pytest.raises(ValueError, match="30 bytes"):
        actions.item_cleanup_stub(small, (94, 96, 97), dismiss_slot=3,
                                  coin_wipe=True)


@pytest.mark.parametrize("addr", [fasttravel.POOL_OF_RADIANCE,
                                  fasttravel.SECRET_OF_THE_SILVER_BLADES])
def test_a_title_with_no_stub_addresses_cannot_build_one(addr):
    assert not addr.has_item_cleanup
    with pytest.raises(ValueError):
        actions.item_cleanup_stub(addr, (94,))


def test_only_curse_has_stub_addresses_and_the_buffer_is_the_script_buffer():
    assert CURSE_ADDR.has_item_cleanup
    assert (CURSE_ADDR.item_cleanup_entry, CURSE_ADDR.coin_wipe_entry,
            CURSE_ADDR.dismiss_entry, CURSE_ADDR.stub_base) == (
        0x16A1, 0x15DF, 0x1671, 0x8000)


# --- disabled rows never run ----------------------------------------------


@pytest.mark.parametrize("area, to, party", [
    (0x31, 0x10, [(3, 5, "AKABAR BEL AKAS", True)]),
    (0x25, 0x10, []),
    (0x22, 0x10, []),
    (0x35, 0x10, []),
    (0x11, 0x10, [(1, 2, "ALIAS", True)]),
])
def test_a_disabled_curse_row_goes_straight_to_the_tail(area, to, party):
    target = trip_machine(CURSE, CURSE_ADDR, area, party)
    target.write(0x4C5B, b"\x00")
    target.write(0x4C2D, b"\x80")
    target.write(0x4C2E, b"\x82")
    outcome = curse_trip(target, to)
    assert outcome.ok, outcome.message
    assert target.jumps == [CURSE_ADDR.tail]
    assert CURSE_ADDR.stub_base not in written(outcome)
    assert target.read(0x4C5B, 1) == b"\x00"
    for slot, *_ in party:
        assert target.read(ROSTER + 0x20 * slot, 1) == b"\x01"


def test_the_five_new_rows_and_only_they_are_disabled():
    off = [row for row in departures.DEPARTURES if not row.enabled]
    assert {(r.title, min(r.areas)) for r in off} == {
        (departures.CURSE_OF_THE_AZURE_BONDS, 0x11),
        (departures.SECRET_OF_THE_SILVER_BLADES, 0x44),
        (departures.CURSE_OF_THE_AZURE_BONDS, 0x31),
        (departures.CURSE_OF_THE_AZURE_BONDS, 0x22),
        (departures.CURSE_OF_THE_AZURE_BONDS, 0x25),
        (departures.CURSE_OF_THE_AZURE_BONDS, 0x35)}
    assert len(off) == 6


# --- C1, the Pit of Moander -----------------------------------------------

PIT_PARTY = [(0, 0, "BRUTUS", False), (1, 5, "ALIAS", True),
             (2, 4, "DRAGONBAIT", True), (3, 6, "ALIAS", False)]


def pit(overrides=None):
    memory = {0x4C5B: 0, 0x4C2D: 128, 0x4C2E: 130, **(overrides or {})}
    target = trip_machine(CURSE, CURSE_ADDR, 0x11, PIT_PARTY)
    for address, value in memory.items():
        target.write(address, bytes([value]))
    return target


def test_the_pit_drops_each_npc_it_names_and_not_a_player_of_that_name(enabled):
    target = pit()
    outcome = curse_trip(target)
    assert outcome.ok, outcome.message
    assert outcome.writes[:5] == (
        (ROSTER + 0x20, b"\x00"), (RECORDS + 0x100 * 5, b"\x00"),
        (ROSTER + 0x40, b"\x00"), (RECORDS + 0x100 * 4, b"\x00"),
        (0x4C5B, b"\xff"))
    assert target.read(0x4C5B, 1) == b"\xff"
    # BRUTUS and the player's own ALIAS keep both bytes.
    assert target.read(ROSTER, 1) == b"\x01"
    assert target.read(ROSTER + 0x60, 1) == b"\x01"
    assert target.read(RECORDS + 0x100 * 6, 1) != b"\x00"
    assert target.jumps == [CURSE_ADDR.tail]


def test_the_pit_zeroes_the_resident_copy_of_a_dismissed_member(enabled):
    target = pit()
    target.write(0x7EB4, b"\x02")
    target.write(0x7EB1, b"\x04")
    outcome = curse_trip(target)
    assert outcome.writes[2:6] == (
        (ROSTER + 0x40, b"\x00"), (RECORDS + 0x100 * 4, b"\x00"),
        (0x7D00, b"\x00"), (0x7C00, b"\x00"))
    assert 0x7D00 not in written(curse_trip(pit()))


def test_the_resident_copy_is_left_alone_when_another_member_is_loaded(enabled):
    target = pit()
    target.write(0x7EB4, b"\x00")
    target.write(0x7EB1, b"\x00")
    assert 0x7D00 not in written(curse_trip(target))


@pytest.mark.parametrize("overrides", [
    {0x4C5B: 255}, {0x4C2D: 0}, {0x4C2D: 129}, {0x4C2E: 0}])
def test_the_pit_writes_nothing_unless_its_trigger_holds(enabled, overrides):
    target = pit(overrides)
    outcome = curse_trip(target)
    assert outcome.ok, outcome.message
    assert not set(written(outcome)) & {ROSTER + 0x20, ROSTER + 0x40,
                                        RECORDS + 0x500, 0x4C5B}


@pytest.mark.parametrize("held", [128, 255])
def test_the_pit_triggers_on_either_of_the_two_values_of_its_flag(enabled, held):
    assert (0x4C5B, b"\xff") in curse_trip(pit({0x4C2D: held})).writes


def test_a_trip_inside_the_pit_levels_is_not_its_exit(enabled):
    target = pit()
    outcome = curse_trip(target, 0x12)
    assert (0x4C5B, b"\xff") not in outcome.writes


# --- S1, Sir Deric --------------------------------------------------------


def compound(*party):
    return trip_machine(SSB, fasttravel.SECRET_OF_THE_SILVER_BLADES, 0x44,
                        party)


def ssb_trip(target):
    return curse_trip(target, 0x10, game=SSB)


def ssb_bases():
    machine = c64.machine_for(SSB)
    return machine.roster_base, machine.slot_area_base


def test_sir_deric_is_matched_by_name_alone_and_only_the_first(enabled):
    roster, records = ssb_bases()
    target = compound((0, 0, "BRUTUS", False), (1, 3, "SIR DERIC", False, 1),
                      (2, 4, "SIR DERIC", False, 1))
    outcome = ssb_trip(target)
    assert outcome.ok, outcome.message
    assert outcome.writes[:2] == ((roster + 0x20, b"\x00"),
                                  (records + 0x300, b"\x00"))
    assert 0x4C05 not in written(outcome)
    assert target.read(roster + 0x40, 1) == b"\x01"
    assert target.jumps == [fasttravel.SECRET_OF_THE_SILVER_BLADES.tail]


def test_sir_deric_not_at_status_one_sets_the_questions_flag_first(enabled):
    roster, records = ssb_bases()
    target = compound((1, 3, "SIR DERIC", False, 2))
    outcome = ssb_trip(target)
    assert outcome.writes[:3] == ((0x4C05, b"\x01"),
                                  (roster + 0x20, b"\x00"),
                                  (records + 0x300, b"\x00"))


def test_nobody_named_sir_deric_writes_nothing_for_him(enabled):
    outcome = ssb_trip(compound((0, 0, "BRUTUS", False)))
    assert outcome.ok
    assert 0x4C05 not in written(outcome)
    assert 0x7D00 not in written(outcome)


# --- C2, Haptooth ---------------------------------------------------------

HAPTOOTH = [(0, 0, "BRUTUS", False), (3, 5, "AKABAR BEL AKAS", True)]


def haptooth(party=HAPTOOTH):
    return trip_machine(CURSE, CURSE_ADDR, 0x31, party)


def test_haptooth_starts_the_game_at_the_stub_with_akabars_slot(enabled):
    target = haptooth()
    outcome = curse_trip(target)
    assert outcome.ok, outcome.message
    stub = actions.item_cleanup_stub(CURSE_ADDR, (94, 96, 97),
                                     dismiss_slot=3, coin_wipe=True)
    assert target.jumps == [0x8000]
    assert target.read(0x8000, len(stub)) == stub
    # The stub is written after the row's writes and before NEWECL's own, and
    # no direct dismissal write is made: the game's own $3E does it.
    assert written(outcome)[0] == 0x8000
    assert ROSTER + 0x60 not in written(outcome)
    assert RECORDS + 0x500 not in written(outcome)
    assert target.read(CURSE_ADDR.slot, 1) == bytes([0x10 | 0x80])


def test_haptooth_without_akabar_still_runs_the_cleanup(enabled):
    target = haptooth([(0, 0, "BRUTUS", False)])
    outcome = curse_trip(target)
    assert outcome.ok, outcome.message
    stub = actions.item_cleanup_stub(CURSE_ADDR, (94, 96, 97), coin_wipe=True)
    assert target.jumps == [0x8000]
    assert target.read(0x8000, len(stub)) == stub


def test_a_player_character_named_akabar_is_not_dismissed(enabled):
    target = haptooth([(3, 5, "AKABAR BEL AKAS", False)])
    curse_trip(target)
    stub = actions.item_cleanup_stub(CURSE_ADDR, (94, 96, 97), coin_wipe=True)
    assert target.read(0x8000, len(stub)) == stub


@pytest.mark.parametrize("to", [0x30, 0x31, 0x32, 0x33])
def test_a_trip_inside_haptooth_or_to_its_outskirts_runs_no_stub(enabled, to):
    target = haptooth()
    outcome = curse_trip(target, to)
    assert outcome.ok, outcome.message
    assert target.jumps == [CURSE_ADDR.tail]
    assert 0x8000 not in written(outcome)


def test_the_stub_order_is_dismissal_row_writes_stub_then_newecl(enabled):
    target = haptooth()
    outcome = curse_trip(target)
    order = written(outcome)
    assert order.index(0x8000) < order.index(CURSE_ADDR.slot)
    assert order[0] == 0x8000


# --- C3 -------------------------------------------------------------------


@pytest.mark.parametrize("area, types", [(0x22, (97, 96)), (0x25, (97, 96)),
                                         (0x35, (94, 96, 97))])
def test_the_dungeon_exits_start_at_a_stub_with_their_types(enabled, area, types):
    target = trip_machine(CURSE, CURSE_ADDR, area, [(0, 0, "BRUTUS", False)])
    outcome = curse_trip(target)
    assert outcome.ok, outcome.message
    stub = actions.item_cleanup_stub(CURSE_ADDR, types)
    assert target.jumps == [0x8000]
    assert target.read(0x8000, len(stub)) == stub
    assert written(outcome)[0] == 0x8000


# --- a trip that cannot run the stub --------------------------------------


def test_a_backend_that_cannot_set_the_pc_fails_and_writes_nothing(enabled):
    target = trip_machine(CURSE, CURSE_ADDR, 0x25, [])
    target.can_set_pc = False
    assert not actions.can_jump(target)
    before = bytes(target.ram)
    outcome = curse_trip(target)
    assert not outcome.ok and outcome.message == actions.FASTTRAVEL_FAILED
    assert outcome.writes == ()
    assert bytes(target.ram) == before


def test_a_failed_jump_puts_every_written_byte_back(enabled, monkeypatch):
    target = haptooth()
    for address in (0x8000, 0x8001, 0x801D, 0x4C00):
        target.write(address, b"\xee")
    before = bytes(target.ram)
    monkeypatch.setattr(actions, "jump", lambda t, a: False)
    outcome = curse_trip(target)
    assert not outcome.ok and outcome.message == actions.FASTTRAVEL_FAILED
    assert bytes(target.ram) == before


def test_a_row_with_a_cleanup_on_a_title_without_stub_addresses_fails(
        monkeypatch):
    row = departures.Departure(departures.POOL_OF_RADIANCE, frozenset({10}),
                               frozenset({departures.C64}),
                               item_cleanup=(94,))
    monkeypatch.setattr(departures, "DEPARTURES", (row,))
    pool = fasttravel.POOL_OF_RADIANCE
    target = trip_machine(c64_port.POOL_OF_RADIANCE, pool, 10, [])
    before = bytes(target.ram)
    outcome = actions.FastTravel().run(target, area=actions.area_by_id(0))
    assert not outcome.ok and outcome.message == actions.FASTTRAVEL_FAILED
    assert bytes(target.ram) == before and target.jumps == []


def test_an_unreadable_party_fails_a_dismissal_trip_and_writes_nothing(enabled):
    class Unreadable(ByteTarget):
        def read(self, address, length):
            if address == ROSTER + 0x20:
                raise OSError("unreadable")
            return super().read(address, length)

    target = Unreadable()
    target.write(CURSE_ADDR.slot, b"\x11")
    target.write(0x4C2D, b"\x80")
    target.write(0x4C2E, b"\x82")
    before = bytes(target.ram)
    outcome = curse_trip(target)
    assert not outcome.ok and outcome.message == actions.FASTTRAVEL_FAILED
    assert bytes(target.ram) == before and target.jumps == []


def test_the_destination_the_tests_use_exists():
    assert any(a.id == 0x10 for a in goldbox_areas.AREAS_CURSE)
