"""`automap/amigatrip.py`: the Amiga trip's statements, writes and put-back, on a fake machine."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import struct
import sys

import pytest

from automap import amigatrip as trip
from automap.target import NotConnected

BASE = 0x10000
BUFFER = 0x30000
WINDOW = 0x40000
PORT = 0x40100
GRID = 0x41000
ENTRY = 0x8137
GADGETS = 0x42000
POOL_ENTRY = 0xA000


class FakeAmiga:
    """A flat memory with a data hunk at `BASE`, `read`, `read_blocks` and
    `write(addr, data, verify)`. Every write is logged; a write at `fail_at`
    raises after storing its first `landed` bytes; `on_write` runs after each
    write and `on_read` before each read."""

    def __init__(self):
        self.ram = bytearray(0x50000)
        self.data_base = BASE
        self.log: list[tuple[int, bytes, bool]] = []
        self.fail_at: int | None = None
        self.landed = 0
        self.on_write = None
        self.on_read = None
        self.geo_blob: bytes | None = bytes(1024)

    def read(self, addr, length):
        if self.on_read is not None:
            self.on_read(addr, length)
        return bytes(self.ram[addr:addr + length])

    def read_blocks(self, blocks):
        return [self.read(b[0], b[1]) for b in blocks]

    def write(self, addr, data, verify=True):
        if addr == self.fail_at:
            self.ram[addr:addr + self.landed] = data[:self.landed]
            self.fail_at = None
            raise NotConnected("the emulator went away")
        self.ram[addr:addr + len(data)] = data
        self.log.append((addr, bytes(data), verify))
        if self.on_write is not None:
            self.on_write(addr, bytes(data))

    def geo(self):
        return self.geo_blob

    def poke(self, addr, data):
        self.ram[addr:addr + len(data)] = data

    def at(self, offset, data):
        self.poke(BASE + offset, data)


def lay_gadgets(m, layout):
    """The window's gadget chain, head first, as `(id, LeftEdge, Width)`."""
    for i, (gid, left, width) in enumerate(layout):
        at = GADGETS + 0x40 * i
        following = at + 0x40 if i + 1 < len(layout) else 0
        m.poke(at, struct.pack(">I", following))
        m.poke(at + trip.GADGET_LEFT_EDGE, struct.pack(">h", left))
        m.poke(at + trip.GADGET_WIDTH, struct.pack(">H", width))
        m.poke(at + trip.GADGET_ID, struct.pack(">H", gid))
    m.poke(WINDOW + trip.WINDOW_FIRST_GADGET,
           struct.pack(">I", GADGETS if layout else 0))


def machine(key, length=0x1000, area=1, stale=False, row=None):
    """A game at its world menu in `area`, with a script of `length` bytes in
    a buffer whose tail is zero, or old bytes where `stale`. The script and
    the stale bytes are made up here."""
    row = row or trip.ROWS[key]
    m = FakeAmiga()
    m.poke(BUFFER, b"\xee" * length)
    if stale:
        m.poke(BUFFER + length, b"\x77" * (trip.BUFFER_SIZE - length))
    m.at(row.buffer_pointer, struct.pack(">I", BUFFER - row.buffer_bias))
    m.at(row.area, bytes([area]))
    m.at(row.mode, bytes([row.world_mode]))
    if row.window_pointer is not None:
        m.at(row.step_entry, POOL_ENTRY.to_bytes(2, "big"))
        m.at(row.view, bytes([row.world_view]))
        m.at(row.window_pointer, struct.pack(">I", WINDOW))
        m.poke(WINDOW + trip.WINDOW_USERPORT, struct.pack(">I", PORT))
        m.poke(PORT + trip.PORT_LIST, trip.empty_list(PORT))
        lay_gadgets(m, trip.gadget_layout(row.menu_text))
        m.at(row.grid_spots[0].pointer, struct.pack(">I", GRID))
        m.at(row.square_spots[0].offset, bytes([9, 14, 4]))
    else:
        m.at(row.step_entry, ENTRY.to_bytes(2, "big"))
        m.at(row.menu_kind, b"\x00\x01")
        if row.menu_text is not None:
            m.at(row.menu_at, row.menu_text + b"\0")
        m.at(row.key_buffer, b"\x00\x0d")
    return m


def kinds(armed):
    return [w.kind for w in armed.records]


# -- the statements ------------------------------------------------------------


#: The statements written by hand in the live trips that
#: `docs/96-live-memory-automapper.md` records, which these functions must
#: reproduce from the opcode numbers.
LIVE = [
    ("curse-of-the-azure-bonds", (10, 1, 0), 3,
     "09000a014bc0090001014cc0090000014dc0200003"),
    ("curse-of-the-azure-bonds", (3, 14, 1), 1,
     "090003014bc009000e014cc0090001014dc0200001"),
    ("pool-of-radiance", (4, 0, 2), 14,
     "090004014bc0090000014cc0090002014dc020000e"),
    ("pool-of-radiance", (9, 13, 0), 0,
     "090009014bc009000d014cc0090000014dc0200000"),
    ("pools-of-darkness", (1, 1, 0), 0x15,
     "090001013400090001013500090000011100200015"),
    ("pools-of-darkness", (5, 13, 0), 0x15,
     "09000501340009000d013500090000011100200015"),
]


@pytest.mark.parametrize("key, square, area, expected", LIVE)
def test_the_statements_match_the_live_trips(key, square, area, expected):
    assert trip.encode(key, square, area).hex() == expected


def test_silver_blades_saves_the_square_where_curse_does():
    assert trip.encode("secret-of-the-silver-blades", (2, 3, 3), 0x20).hex() \
        == "090002014bc0090003014cc0090003014dc0200020"


def test_a_square_without_a_facing_saves_x_and_y_only():
    assert trip.encode("curse-of-the-azure-bonds", (2, 3), 4).hex() \
        == "090002014bc0090003014cc0200004"


def test_the_grid_square_and_the_area_file_go_before_newecl():
    assert trip.encode("pool-of-radiance", None, 26, grid=(20, 29)).hex() \
        == "090014" "01c349" "09001d" "01c449" "20001a"
    assert trip.encode("curse-of-the-azure-bonds", (1, 2, 0), 3,
                       area_file=5).endswith(bytes.fromhex("09000501127f200003"))


@pytest.mark.parametrize("key, kwargs", [
    ("pools-of-darkness", {"area_file": 1}),
    ("curse-of-the-azure-bonds", {"grid": (1, 1)}),
])
def test_a_target_the_title_lacks_raises(key, kwargs):
    with pytest.raises(ValueError):
        trip.encode(key, (1, 1, 0), 3, **kwargs)


def test_an_operand_past_a_byte_raises():
    with pytest.raises(ValueError):
        trip.newecl(256)


def test_the_message_has_intuitions_fields_where_the_game_reads_them():
    message = trip.rawkey_message(0xC55A58, 0xC559A8)
    assert len(message) == 52
    succ, pred, kind, _pri, _name, reply, size = struct.unpack_from(
        ">IIBBIIH", message)
    assert (succ, pred, kind, reply, size) == (0xC55A70, 0xC55A6C, 5, 0, 52)
    assert struct.unpack_from(">IH", message, 0x14) == (0x400, 0x08)
    assert struct.unpack_from(">I", message, 0x2C) == (0xC559A8,)
    # The first 44 bytes are the message linked in the live trips; that one's
    # window longword sat one byte late, at +0x2D, which the game never reads.
    assert message[:44].hex() == (
        "00c55a7000c55a6c050000000000000000000034000004000008000000000000"
        "000000000000000000000000")


def test_the_link_makes_the_message_the_lists_one_node():
    assert trip.link(0xC5B8C0).hex() == "00c5b8c00000000000c5b8c0"
    assert trip.empty_list(0xC55A58).hex() == "00c55a700000000000c55a6c"


# -- the tiers ---------------------------------------------------------------


def test_the_tier_comes_from_the_length_on_disk():
    curse = trip.ROWS["curse-of-the-azure-bonds"]
    assert trip.free_tail(curse, 1, {1: trip.BUFFER_SIZE - 21}) == 1
    assert trip.free_tail(curse, 1, {1: trip.BUFFER_SIZE - 20}) == 3
    assert trip.free_tail(curse, 2, {1: 100}) == 3
    assert trip.free_tail(curse, None, {1: 100}) == 3


def test_tier_two_needs_a_confirmed_direct_write():
    curse = trip.ROWS["curse-of-the-azure-bonds"]
    direct = dataclasses.replace(curse, direct_confirmed=True)
    lengths = {1: trip.BUFFER_SIZE - 3}
    assert trip.free_tail(curse, 1, lengths) == 3
    assert trip.free_tail(direct, 1, lengths) == 2
    assert trip.free_tail(direct, 1, {1: trip.BUFFER_SIZE - 2}) == 3


def test_a_plan_with_more_statements_needs_more_tail():
    curse = trip.ROWS["curse-of-the-azure-bonds"]
    lengths = {1: trip.BUFFER_SIZE - 21}
    assert trip.free_tail(curse, 1, lengths,
                          trip.plan(3, (1, 1, 0), area_file=2)) == 3
    assert trip.free_tail(curse, 1, lengths, trip.plan(3, None)) == 1


def test_pool_needs_room_for_its_message_below_the_statements():
    pool = trip.ROWS["pool-of-radiance"]
    at, message = trip.layout(pool, 21)
    assert at == trip.BUFFER_SIZE - 21 and message % 4 == 0
    assert at - 3 <= message + trip.MESSAGE_SIZE <= at
    assert trip.free_tail(pool, 0, {0: message}) == 1
    # The packed layout takes the statements at the script's end, which
    # reaches six bytes further than the default one.
    assert trip.free_tail(pool, 0, {0: message + 1}) == 1
    assert trip.free_tail(pool, 0, {0: 7608}) == 3
    grid = trip.plan(26, None, (20, 29))
    assert trip.free_tail(pool, 0, {0: message}, grid) == 1


def test_script_lengths_reads_the_table_off_a_disk(tmp_path):
    from goldbox.amiga_adf import AmigaDisk
    blocks = [struct.pack(">HHHHH", 2, 1, 1, 3, 2), b"\x01" * 300,
              b"\x02" * 7000]
    head = b"GLIB" + bytes(4) + struct.pack(">HH", len(blocks), 0) + b"DATA"
    at, offsets = len(head) + 4 * (len(blocks) + 1), []
    for block in blocks:
        offsets.append(at)
        at += len(block)
    offsets.append(at)
    glib = head + struct.pack(f">{len(offsets)}I", *offsets) + b"".join(blocks)
    disk = AmigaDisk.blank("B")
    disk.make_dir("/DISKB")
    disk.write_file("/DISKB/ECL.GLB", glib)
    (tmp_path / "b.adf").write_bytes(disk.to_bytes())
    lengths = trip.script_lengths("curse-of-the-azure-bonds", tmp_path)
    assert lengths == {1: 300, 3: 7000}
    assert trip.script_lengths("pools-of-darkness", tmp_path) == {}


# -- the gate ----------------------------------------------------------------


@pytest.mark.parametrize("key", ["curse-of-the-azure-bonds",
                                 "pools-of-darkness", "pool-of-radiance"])
def test_the_gate_opens_at_the_world_menu(key):
    assert trip.gate(machine(key), trip.ROWS[key])


@pytest.mark.parametrize("offset, data", [
    (0x1C24, b"\x00\x02"),                 # a PRESS RETURN text
    (0x3342, b"Area\0Cast\0View\0Exit"),
    (0x3D56, b"\x05"),                     # a fight
    (0x3804, b"\x01"),                     # a key already waiting
])
def test_the_gate_stays_shut_anywhere_else(offset, data):
    m = machine("curse-of-the-azure-bonds")
    m.at(offset, data)
    assert not trip.gate(m, trip.ROWS["curse-of-the-azure-bonds"])


def test_silver_blades_menu_text_is_the_measured_one():
    key = "secret-of-the-silver-blades"
    assert trip.ROWS[key].menu_text == b"Area Cast View Encamp Search Look"
    assert trip.gate(machine(key), trip.ROWS[key])
    assert not trip.ROWS[key].confirmed


def test_pools_gate_takes_the_grid_and_not_a_waiting_message():
    pool = trip.ROWS["pool-of-radiance"]
    m = machine("pool-of-radiance")
    m.at(pool.mode, b"\x03")
    m.at(pool.view, b"\x03")
    lay_gadgets(m, trip.gadget_layout(pool.grid_menu_text))
    assert trip.gate(m, pool)
    m.at(pool.view, b"\x01")
    assert not trip.gate(m, pool)
    m = machine("pool-of-radiance")
    m.poke(PORT + trip.PORT_LIST, trip.link(0x45000))
    assert not trip.gate(m, pool)


#: Measured on Pool of Radiance (FT-L1): (id, LeftEdge, Width), head first.
WORLD_GADGETS = ((1005, 232, 34), (1004, 176, 50), (1003, 120, 50),
                 (1002, 80, 34), (1001, 40, 34), (1000, 0, 34))
#: Camp puts six gadgets with the same ids behind the prefix "Camp: ", the
#: head at (1005, 264, 34). Its other words are not recorded here, so the rest
#: stands in as the world menu's edges moved 48 to the right.
CAMP_GADGETS = ((1005, 264, 34),) + tuple(
    (gid, left + 48, width) for gid, left, width in WORLD_GADGETS[1:])


def test_the_menu_layout_rule_gives_the_measured_world_menu_and_grid():
    pool = trip.ROWS["pool-of-radiance"]
    assert trip.gadget_layout(pool.menu_text) == WORLD_GADGETS
    assert trip.gadget_layout(pool.grid_menu_text) == (
        (1004, 192, 34), (1003, 136, 50), (1002, 80, 50), (1001, 40, 34),
        (1000, 0, 34))


def test_pools_gate_reads_the_gadgets_and_shuts_on_camp():
    pool = trip.ROWS["pool-of-radiance"]
    m = machine("pool-of-radiance")
    assert trip.menu_gadgets(m, pool) == WORLD_GADGETS
    assert trip.gate(m, pool)
    lay_gadgets(m, CAMP_GADGETS)
    assert not trip.gate(m, pool)


@pytest.mark.parametrize("change", [
    lambda g: g[:-1] + ((1000, 8, 34),),              # one edge off
    lambda g: g[:1] + ((1004, 176, 52),) + g[2:],     # one width off
    lambda g: g[:2] + ((1003, 120, 50),) + g[3:-1],   # a gadget short
    lambda g: ((1006, 280, 34),) + g,                 # a seventh gadget
    lambda g: ((1005, 0, 34),),                       # a single gadget
    lambda g: (),                                     # an empty chain
])
def test_pools_gate_shuts_on_a_near_miss(change):
    pool = trip.ROWS["pool-of-radiance"]
    m = machine("pool-of-radiance")
    lay_gadgets(m, change(WORLD_GADGETS))
    assert not trip.gate(m, pool)


def test_pools_grid_gadgets_open_the_gate_only_in_the_grid_mode():
    pool = trip.ROWS["pool-of-radiance"]
    m = machine("pool-of-radiance")
    lay_gadgets(m, trip.gadget_layout(pool.grid_menu_text))
    assert not trip.gate(m, pool)           # the 3D view wants the world menu
    m.at(pool.mode, b"\x03")
    m.at(pool.view, b"\x03")
    assert trip.gate(m, pool)


# -- the grid exit's prologue --------------------------------------------------

BOAT_EXIT = b"".join(trip.boat_exit_groups())


def test_the_prologue_is_the_five_boat_exit_groups_off_a_window_only():
    pool = trip.ROWS["pool-of-radiance"]
    assert len(BOAT_EXIT) == 53
    assert trip.leave_grid_prologue(pool, 26, 0) == BOAT_EXIT
    for here, to in ((26, 25), (0, 26), (7, 5), (None, 0)):
        assert trip.leave_grid_prologue(pool, here, to) == b""
    curse = trip.ROWS["curse-of-the-azure-bonds"]
    assert trip.leave_grid_prologue(curse, 26, 0) == b""


def test_the_statements_run_the_prologue_first_and_newecl_last():
    pool = trip.ROWS["pool-of-radiance"]
    for tier in (1, 2):
        p = trip.plan(0, (9, 14, 2), tier=tier, prologue=BOAT_EXIT)
        out = trip._statements(pool, p)
        assert out.startswith(trip.picture(255) + trip.clear_box())
        assert out.startswith(BOAT_EXIT) and out.endswith(trip.newecl(0))


def test_free_tail_counts_the_prologue():
    pool = trip.ROWS["pool-of-radiance"]
    bare = trip.plan(0, (9, 14, 2))
    with_prologue = trip.plan(0, (9, 14, 2), prologue=BOAT_EXIT)
    _at, message = trip.layout(pool, len(trip._statements(pool, bare)))
    assert trip.free_tail(pool, 26, {26: message}, bare) == 1
    assert trip.free_tail(pool, 26, {26: message}, with_prologue) == 3


def test_arm_writes_the_prologue_at_the_buffer_tail_and_disarm_puts_it_back():
    key = "pool-of-radiance"
    m = machine(key, area=26)
    before = bytes(m.ram)
    p = trip.plan(0, (9, 14, 2), prologue=BOAT_EXIT)
    armed = trip.arm(m, key, p)
    statements = trip._statements(trip.ROWS[key], p)
    assert m.read(BUFFER + trip.BUFFER_SIZE - len(statements),
                  len(statements)) == statements
    assert statements.startswith(BOAT_EXIT)
    assert trip.disarm(m, armed) is True
    assert bytes(m.ram) == before


# -- arming ------------------------------------------------------------------


def test_curse_writes_statements_then_step_entry_then_key():
    key = "curse-of-the-azure-bonds"
    m = machine(key)
    armed = trip.arm(m, key, trip.plan(3, (10, 1, 0)))
    assert kinds(armed) == ["statements", "entry", "trigger"]
    at = trip.BUFFER_SIZE - 21
    assert m.log == [
        (BUFFER + at, trip.encode(key, (10, 1, 0), 3), True),
        (BASE + 0x584C, (0x8000 + at).to_bytes(2, "big"), True),
        (BASE + 0x3804, b"\x01\xb8", False)]
    assert armed.writes == tuple((a, d) for a, d, _v in m.log)
    assert armed.from_area == 1


def test_pool_links_its_message_last_and_inside_the_buffer():
    key = "pool-of-radiance"
    m = machine(key)
    armed = trip.arm(m, key, trip.plan(14, (4, 0, 2)))
    assert kinds(armed) == ["statements", "message", "entry", "trigger"]
    statements, message, entry, trigger = armed.records
    for w in (statements, message):
        assert BUFFER <= w.address
        assert w.address + len(w.data) <= BUFFER + trip.BUFFER_SIZE
    assert message.address % 4 == 0
    assert message.address + trip.MESSAGE_SIZE <= statements.address
    assert message.data == trip.rawkey_message(PORT, WINDOW)
    assert entry.data == (0x9900 + statements.address - BUFFER).to_bytes(2, "big")
    assert trigger.address == PORT + trip.PORT_LIST
    assert trigger.data == trip.link(message.address)
    assert [v for _a, _d, v in m.log] == [True, True, True, False]


def test_a_buffer_with_old_bytes_in_its_tail_still_arms():
    key = "pools-of-darkness"
    m = machine(key, area=0x15, stale=True)
    armed = trip.arm(m, key, trip.plan(0x16, None))
    assert kinds(armed) == ["statements", "entry", "trigger"]
    assert armed.records[0].original == b"\x77\x77\x77"


def test_a_clearing_title_will_not_write_over_script_bytes():
    key = "curse-of-the-azure-bonds"
    m = machine(key, length=trip.BUFFER_SIZE - 10)
    assert trip.arm(m, key, trip.plan(3, (10, 1, 0))) is None
    assert m.log == []


@pytest.mark.parametrize("why", ["gate", "same area", "tier 3", "tier 2"])
def test_arm_writes_nothing_when_it_should_not_arm(why):
    key = "curse-of-the-azure-bonds"
    m = machine(key)
    p = trip.plan(3, (1, 1, 0))
    if why == "gate":
        m.at(0x1C24, b"\x00\x02")
    elif why == "same area":
        p = trip.plan(1, (1, 1, 0))
    else:
        p = trip.plan(3, (1, 1, 0), tier=3 if why == "tier 3" else 2)
    assert trip.arm(m, key, p) is None
    assert m.log == []


def test_a_failed_write_puts_back_what_was_already_written():
    key = "curse-of-the-azure-bonds"
    m = machine(key)
    before = bytes(m.ram)
    m.fail_at = BASE + 0x584C
    assert trip.arm(m, key, trip.plan(3, (10, 1, 0))) is None
    assert bytes(m.ram) == before
    assert len(m.log) == 2


@pytest.mark.parametrize("key, kind, landed", [
    ("pool-of-radiance", "trigger", 4),     # the link's head, not its tail
    ("pool-of-radiance", "message", 20),
    ("pools-of-darkness", "statements", 10),
    ("curse-of-the-azure-bonds", "trigger", 1),
])
def test_a_write_that_fails_part_way_is_put_back_too(key, kind, landed):
    m = machine(key, stale=key == "pools-of-darkness")
    before = bytes(m.ram)
    row = trip.ROWS[key]
    p = trip.plan(3, (1, 1, 0))
    _buffer, writes = trip._prepare(m, row, p)
    m.fail_at = next(a for a, _d, k in writes if k == kind)
    m.landed = landed
    assert trip.arm(m, key, p) is None
    assert bytes(m.ram) == before


def test_a_half_linked_message_the_game_takes_is_a_trip_that_happened():
    key = "pool-of-radiance"
    m = machine(key)
    row = trip.ROWS[key]
    p = trip.plan(14, (4, 0, 2))
    _buffer, writes = trip._prepare(m, row, p)
    m.fail_at = next(a for a, _d, k in writes if k == "trigger")
    m.landed = 4

    def game_takes_it(addr, length):
        # Before the link is put back, the game's GetMsg takes the message.
        if m.fail_at is None and addr == PORT + trip.PORT_LIST:
            m.at(row.area, b"\x0e")
            m.poke(PORT + trip.PORT_LIST, trip.empty_list(PORT))
    m.on_read = game_takes_it
    armed = trip.arm(m, key, p)
    assert armed is not None and trip.fired(m, armed) is True
    assert m.read(BASE + row.step_entry, 2) != POOL_ENTRY.to_bytes(2, "big")


def test_tier_two_writes_the_square_first():
    key = "curse-of-the-azure-bonds"
    row = dataclasses.replace(trip.ROWS[key], direct_confirmed=True)
    m = machine(key, row=row)
    armed = trip.arm(m, row, trip.plan(3, (10, 1, 2), tier=2))
    assert kinds(armed) == ["square"] * 3 + ["statements", "entry", "trigger"]
    assert [w.data for w in armed.records[:3]] == [b"\x00\x0a", b"\x00\x01",
                                                   b"\x04"]
    assert armed.records[3].data == trip.newecl(3)


# -- after the key -----------------------------------------------------------


def test_fired_is_none_until_the_area_changes():
    key = "curse-of-the-azure-bonds"
    m = machine(key)
    armed = trip.arm(m, key, trip.plan(3, (10, 1, 0)))
    assert trip.fired(m, armed) is None
    m.at(0x5CE1, b"\x03")
    assert trip.fired(m, armed) is True


@pytest.mark.parametrize("key", ["curse-of-the-azure-bonds",
                                 "pool-of-radiance", "pools-of-darkness"])
def test_a_trip_that_does_not_fire_is_put_back(key):
    m = machine(key, stale=key == "pools-of-darkness")
    before = bytes(m.ram)
    armed = trip.arm(m, key, trip.plan(3, (1, 1, 0)))
    assert bytes(m.ram) != before
    assert trip.disarm(m, armed) is True
    assert bytes(m.ram) == before


def test_put_back_leaves_alone_what_the_game_changed_since():
    key = "curse-of-the-azure-bonds"
    m = machine(key)
    armed = trip.arm(m, key, trip.plan(3, (1, 1, 0)))
    m.at(0x3804, b"\x00")                  # the game took the key
    m.at(0x584C, b"\x80\x14")              # and a script load reset the entry
    trip.disarm(m, armed)
    assert m.read(BASE + 0x3804, 2) == b"\x00\xb8"
    assert m.read(BASE + 0x584C, 2) == b"\x80\x14"
    statements = armed.records[0]
    assert m.read(statements.address, len(statements.data)) == bytes(21)


def test_pools_message_taken_by_another_prompt_keeps_the_games_mark():
    key = "pool-of-radiance"
    m = machine(key)
    armed = trip.arm(m, key, trip.plan(14, (4, 0, 2)))
    message = armed.records[1]
    m.poke(PORT + trip.PORT_LIST, trip.empty_list(PORT))   # GetMsg took it
    m.poke(message.address + 8, b"\x06")                  # ReplyMsg: NT_FREEMSG
    assert trip.disarm(m, armed) is True
    assert m.read(message.address, trip.MESSAGE_SIZE) == bytes(8) + b"\x06" \
        + bytes(trip.MESSAGE_SIZE - 9)
    assert m.read(BASE + 0xAA, 2) == POOL_ENTRY.to_bytes(2, "big")


def test_a_key_taken_while_putting_back_counts_as_a_trip():
    """The game takes the key after `disarm` looked at the area: the trip
    fires, and the step entry and statements are left for `tidy`."""
    key = "pools-of-darkness"
    m = machine(key, area=0x15, stale=True)
    row = trip.ROWS[key]
    armed = trip.arm(m, key, trip.plan(0x16, (5, 13, 0)))

    def game_takes_the_key(addr, length):
        # After disarm's first look at the area, as it reads the key back.
        if addr == BASE + row.key_buffer:
            m.at(row.key_buffer, b"\x00")
            m.at(row.area, b"\x16")
    m.on_read = game_takes_the_key
    written = len(m.log)
    assert trip.disarm(m, armed) is False
    assert len(m.log) == written
    statements = armed.records[0]
    assert m.read(statements.address, 21) == statements.data


def test_put_back_does_nothing_once_the_area_has_changed():
    key = "curse-of-the-azure-bonds"
    m = machine(key)
    armed = trip.arm(m, key, trip.plan(3, (1, 1, 0)))
    m.at(0x5CE1, b"\x03")
    written = len(m.log)
    assert trip.disarm(m, armed) is False
    assert len(m.log) == written


def _arrive(m, key, armed, area, length):
    """The game's load of `area`'s made-up script over the buffer, without
    clearing it, as Silver Blades and Pools of Darkness do."""
    row = trip.ROWS[key] if isinstance(key, str) else key
    m.at(row.area, bytes([area]))
    m.poke(BUFFER, b"\x55" * length)


def test_tidy_zeroes_only_leftover_statements_past_the_new_script():
    key = "pools-of-darkness"
    m = machine(key, area=0x15, stale=True)
    armed = trip.arm(m, key, trip.plan(0x16, (5, 13, 0)))
    statements = armed.records[0]
    first = statements.address - BUFFER
    _arrive(m, key, armed, 0x16, first + 5)
    # The new script's last five bytes happen to equal the statements' first.
    m.poke(statements.address, statements.data[:5])
    m.poke(statements.address + 10, b"\x99")   # a byte something else wrote
    zeroed = trip.tidy(m, armed, 0x16, {0x16: first + 5})
    tail = m.read(statements.address, 21)
    assert tail[:5] == statements.data[:5]
    assert tail[10] == 0x99
    assert zeroed == 15
    assert all(b == 0 for i, b in enumerate(tail[5:], 5) if i != 10)


def test_tidy_on_silver_blades_too():
    row = trip.ROWS["secret-of-the-silver-blades"]
    m = machine(row.key, area=0x20, stale=True, row=row)
    armed = trip.arm(m, row, trip.plan(0x21, (1, 2, 0)))
    _arrive(m, row, armed, 0x21, 100)
    assert trip.tidy(m, armed, 0x21, {0x21: 100}) > 0
    assert m.read(armed.records[0].address, 21) == bytes(21)


@pytest.mark.parametrize("why", ["clears", "unknown area", "buffer moved"])
def test_tidy_leaves_everything_alone_when_it_cannot_tell(why):
    key = "curse-of-the-azure-bonds" if why == "clears" else "pools-of-darkness"
    m = machine(key, area=0x15, stale=why != "clears")
    armed = trip.arm(m, key, trip.plan(0x16, (5, 13, 0)))
    row = trip.ROWS[key]
    m.at(row.area, b"\x16")
    lengths = {0x16: 10}
    if why == "unknown area":
        lengths = {}
    elif why == "buffer moved":
        m.at(row.buffer_pointer, struct.pack(">I", BUFFER + 0x100 - row.buffer_bias))
    written = len(m.log)
    assert trip.tidy(m, armed, 0x16, lengths) == 0
    assert len(m.log) == written


# -- reading the party -------------------------------------------------------


def test_square_and_overland_read_the_engines_own_bytes():
    pool = trip.ROWS["pool-of-radiance"]
    m = machine("pool-of-radiance")
    assert trip.square(m, pool) == (9, 14, 2)
    assert trip.area_id(m, pool) == 1
    m.poke(GRID + 0x1CC, b"\x00\x01")
    assert trip.overland(m, pool) is None
    m.poke(GRID + 0x1CC, b"\x00\x00")
    m.poke(GRID + 0x186, b"\x00\x14\x00\x1d")
    assert trip.overland(m, pool) == (20, 29)
    assert trip.overland(machine("curse-of-the-azure-bonds"),
                         trip.ROWS["curse-of-the-azure-bonds"]) is None


def test_nothing_reads_before_the_target_is_located():
    m = machine("curse-of-the-azure-bonds")
    m.data_base = None
    row = trip.ROWS["curse-of-the-azure-bonds"]
    assert trip.area_id(m, row) is None and trip.square(m, row) is None
    assert not trip.gate(m, row)
    assert trip.arm(m, row, trip.plan(3, (1, 1, 0))) is None


# -- what is offered ---------------------------------------------------------


def test_only_measured_rows_are_confirmed_and_no_difference_is_offered():
    assert {k for k, r in trip.ROWS.items() if r.confirmed} == {
        "pool-of-radiance", "curse-of-the-azure-bonds", "pools-of-darkness"}
    assert not any(r.direct_confirmed for r in trip.ROWS.values())
    assert not any(d.offered for r in trip.ROWS.values() for d in r.differences)


def test_what_each_difference_holds():
    def held(key, here, to, back=False):
        return {d.name for d in trip.ROWS[key].differences
                if d.covers(here, to, back)}

    assert held("curse-of-the-azure-bonds", 3, 1) == set()
    assert held("curse-of-the-azure-bonds", 1, 3) == set()
    assert held("curse-of-the-azure-bonds", 1, 3, back=True) == set()
    assert held("curse-of-the-azure-bonds", 3, 1, back=True) == set()
    assert held("pools-of-darkness", 0x15, 0x16, back=True) == set()
    assert held("pools-of-darkness", 0x15, 0x16) == set()
    assert "weak_gate" not in held("pool-of-radiance", 0, 14)
    assert "leave_grid" not in {d.name for d in
                                trip.ROWS["pool-of-radiance"].differences}
    assert "onto_grid" not in held("pool-of-radiance", 26, 0)
    assert "onto_grid" not in held("pool-of-radiance", 0, 26)
    assert "arrival_unplaced" in held(SILVER, 0x34, 0x33)
    assert "arrival_unplaced" not in held(SILVER, 0x34, 0x33, back=True)
    for to in (0x33, 0x34, 0x51, 0x52):
        assert held(SILVER, 0x10, to) == set()
        assert "return_unplaced" in held(SILVER, 0x10, to, back=True)
    assert "return_unplaced" not in held(SILVER, 0x10, 0x41, back=True)


# -- the player's own disks ----------------------------------------------------


def _images():
    from tools.amiga import amigasaves
    return [data for _label, data in amigasaves.images()]


@pytest.mark.parametrize("key, area, end", [
    # Where the live trips read the end of the loaded script in the game.
    ("curse-of-the-azure-bonds", 1, 0x1DC6),
    ("pool-of-radiance", 0, 0x1D2C),
    ("pool-of-radiance", 14, 0x1CA2),
])
def test_the_players_disks_give_the_script_ends_measured_live(key, area, end):
    found = []
    for image in _images():
        lengths = trip.script_lengths(key, [image])
        if area in lengths:
            found.append(lengths[area])
    if not found:
        pytest.skip(f"needs the player's Amiga {key} disks")
    assert end in found


def test_every_pool_departing_area_but_two_fits_a_trip_on_the_players_disks():
    pool = trip.ROWS["pool-of-radiance"]
    areas = (0, 1, 2, 3, 9, 13, 14, 16, 17, 18, 21, 22, 23, 25, 26, 27, 28)
    # The scripts of areas 1 and 28 leave no room for their departure
    # statements past the script, so those trips go in the init span.
    no_room = ()
    for image in _images():
        lengths = trip.script_lengths("pool-of-radiance", [image])
        if not all(a in lengths for a in areas):
            continue
        init = trip.init_rooms(pool, [image])
        assert init == {1, 28}
        for here in areas:
            held = trip.leg_held(pool, here, 0, False, lengths, None, init)
            assert held is (here in no_room), here
            if here in no_room:
                assert not trip.leg_held(pool, here, 0, False, lengths)
        # Without the match a trip out of areas 1 and 28 is still held.
        assert trip.leg_held(pool, 1, 0, False, lengths)
        assert trip.leg_held(pool, 28, 0, False, lengths)
        return
    pytest.skip("needs the player's Amiga Pool of Radiance disks")


def test_a_trip_out_of_the_nomad_camp_is_held_for_no_destination_on_the_players_disks():
    pool = trip.ROWS["pool-of-radiance"]
    for image in _images():
        lengths = trip.script_lengths("pool-of-radiance", [image])
        if not all(a in lengths for a in (0, 17, 26)):
            continue
        for to in (0, 26):
            for outdoors in (False, to == 26):
                assert not trip.leg_held(pool, 17, to, False, lengths,
                                         outdoors)
        return
    pytest.skip("needs the player's Amiga Pool of Radiance disks")


def test_a_trip_into_tilverton_writes_the_area_byte_before_the_key():
    key = "curse-of-the-azure-bonds"
    m = machine(key, area=3)
    armed = trip.arm(m, key, trip.plan(1, (3, 14, 1)))
    assert kinds(armed) == ["statements", "entry", "came_from", "trigger"]
    assert (armed.records[2].address, armed.records[2].data) \
        == (BASE + 0x5CE1, b"\x01")
    elsewhere = trip.arm(machine(key, area=1), key, trip.plan(3, (3, 14, 1)))
    assert "came_from" not in kinds(elsewhere)


def test_a_tilverton_trip_fires_on_the_step_entry_not_the_area_byte():
    key = "curse-of-the-azure-bonds"
    m = machine(key, area=3)
    armed = trip.arm(m, key, trip.plan(1, (3, 14, 1)))
    assert m.read(BASE + 0x5CE1, 1) == b"\x01"
    assert trip.fired(m, armed) is None
    m.at(0x584C, b"\x80\x14")              # vm_init_ecl rewrote the entry
    assert trip.fired(m, armed) is True


def test_an_untaken_tilverton_trip_puts_the_area_byte_back():
    key = "curse-of-the-azure-bonds"
    m = machine(key, area=3)
    before = bytes(m.ram)
    armed = trip.arm(m, key, trip.plan(1, (3, 14, 1)))
    assert trip.disarm(m, armed) is True
    assert bytes(m.ram) == before


def test_a_tilverton_trip_with_the_key_taken_leaves_the_area_byte_alone():
    key = "curse-of-the-azure-bonds"
    m = machine(key, area=3)
    armed = trip.arm(m, key, trip.plan(1, (3, 14, 1)))
    m.at(0x3804, b"\x00")                  # the game took the key
    m.at(0x584C, b"\x80\x14")              # and loaded the script
    written = len(m.log)
    assert trip.disarm(m, armed) is False
    assert len(m.log) == written
    assert m.read(BASE + 0x5CE1, 1) == b"\x01"


def test_a_failed_came_from_write_puts_every_earlier_write_back():
    key = "curse-of-the-azure-bonds"
    m = machine(key, area=3)
    before = bytes(m.ram)
    m.fail_at = BASE + 0x5CE1
    assert trip.arm(m, key, trip.plan(1, (3, 14, 1))) is None
    assert bytes(m.ram) == before


def test_a_key_flag_change_without_the_step_entry_changing_is_not_a_taken_trip():
    key = "curse-of-the-azure-bonds"
    m = machine(key, area=3)
    before = bytes(m.ram)
    armed = trip.arm(m, key, trip.plan(1, (3, 14, 1)))
    m.at(0x3804, b"\x00")                  # the key flag changed, no script ran
    assert trip.disarm(m, armed) is True
    after = bytearray(m.ram)
    key = armed.records[-1]                # the changed key is left to the game
    after[key.address:key.address + len(key.data)] = \
        before[key.address:key.address + len(key.data)]
    assert bytes(after) == before


# -- doors ---------------------------------------------------------------------


def _route(entry, square):
    from automap import fasttravel
    return fasttravel.ExitRoute(entry, square)


def test_an_entry_zero_row_with_a_facing_stands_on_its_own_square_and_facing():
    assert trip.stand_for(2, 18, _route(0, (4, 0, 0))) == (4, 0, 0)


def test_an_entry_zero_row_without_a_facing_has_no_stand():
    assert trip.stand_for(2, 18, _route(0, (4, 0))) is None


def test_an_entry_one_row_stands_on_its_square_facing_the_table_side():
    assert trip.stand_for(13, 27, _route(1, (6, 15))) == (6, 15, 2)
    # A row the table has no side for is held, never given a neighbour.
    assert trip.stand_for(0, 8, _route(1, (4, 4))) is None


_F4R3_STANDS = {
    (0, 21): (15, 1, 0), (0, 26): (15, 1, 0), (0, 27): (15, 1, 0),
    (0, 11): (6, 2, 2), (9, 6): (7, 7, 3),
    (22, 23): (14, 7, 0), (22, 26): (13, 15, 0), (23, 22): (6, 0, 0),
}


def test_each_f4_r3_stand_has_its_facing():
    from automap import fasttravel
    for (here, to), stand in _F4R3_STANDS.items():
        route = fasttravel.EXIT_ROUTES[(here, to)]
        assert trip.stand_for(here, to, route) == stand
        assert (here, to) not in trip.DOORS_PROVEN


def _geo_blob() -> bytes:
    from goldbox import geo
    blob = bytearray(geo.GEO_SIZE)
    blob[0x000 + 4] = 0x70           # (4,0) north wall art 7
    blob[0x200 + 4] = 0x93           # (4,0) attribute 0x93
    return bytes(blob)


def _door_machine():
    pool = trip.ROWS["pool-of-radiance"]
    m = machine("pool-of-radiance", area=14)
    m.geo_blob = _geo_blob()
    return m, pool


def test_a_door_writes_the_square_wall_attribute_message_then_the_key():
    m, pool = _door_machine()
    armed = trip.arm_door(m, pool, (4, 0, 0))
    assert kinds(armed) == ["square", "square", "square", "wall", "attribute",
                            "message", "trigger"]
    notes = trip.amiga.MACHINES["pool-of-radiance"].notes
    done = {a: d for a, d, _v in m.log}
    assert done[BASE + notes["wall_ahead"]] == b"\x07"
    assert done[BASE + notes["square_attribute"]] == b"\x93"
    assert m.log[-1][0] == PORT + trip.PORT_LIST
    assert not any(w.kind == "entry" for w in armed.records)


def test_a_door_has_fired_only_once_the_game_takes_the_key():
    m, pool = _door_machine()
    armed = trip.arm_door(m, pool, (4, 0, 0))
    assert not trip.door_fired(m, armed)
    assert trip.trip_fired(m, armed) is None
    m.poke(PORT + trip.PORT_LIST, trip.empty_list(PORT))     # the game took it
    assert trip.door_fired(m, armed)
    assert trip.trip_fired(m, armed) is True
    assert trip.area_id(m, pool) == 14                        # and stayed


def test_a_door_whose_key_is_not_taken_puts_every_byte_back_key_first():
    m, pool = _door_machine()
    before = bytes(m.ram)
    armed = trip.arm_door(m, pool, (4, 0, 0))
    assert bytes(m.ram) != before
    m.log.clear()
    assert trip.disarm(m, armed) is True
    assert bytes(m.ram) == before
    assert m.log[0][0] == PORT + trip.PORT_LIST


def test_a_door_whose_key_was_taken_is_left_alone_by_the_put_back():
    m, pool = _door_machine()
    armed = trip.arm_door(m, pool, (4, 0, 0))
    m.poke(PORT + trip.PORT_LIST, trip.empty_list(PORT))
    m.log.clear()
    assert trip.disarm(m, armed) is False
    assert m.log == []


def test_a_key_taken_between_the_look_and_the_put_back_leaves_the_rest_alone():
    m, pool = _door_machine()
    armed = trip.arm_door(m, pool, (4, 0, 0))
    m.poke(PORT + trip.PORT_LIST, trip.empty_list(PORT))
    m.log.clear()
    assert trip._put_back(m, armed) is False
    assert m.log == []


def test_a_door_is_not_armed_with_no_map_a_waiting_key_or_off_the_menu():
    m, pool = _door_machine()
    m.geo_blob = None
    assert trip.arm_door(m, pool, (4, 0, 0)) is None
    m, pool = _door_machine()
    m.poke(PORT + trip.PORT_LIST, trip.link(BUFFER))
    before = bytes(m.ram)
    assert trip.arm_door(m, pool, (4, 0, 0)) is None
    assert bytes(m.ram) == before
    m, pool = _door_machine()
    m.at(pool.mode, b"\x00")
    assert trip.arm_door(m, pool, (4, 0, 0)) is None


def test_a_door_write_that_fails_puts_back_what_landed():
    m, pool = _door_machine()
    notes = trip.amiga.MACHINES["pool-of-radiance"].notes
    before = bytes(m.ram)
    m.fail_at = BASE + notes["wall_ahead"]
    assert trip.arm_door(m, pool, (4, 0, 0)) is None
    assert bytes(m.ram) == before


def test_pools_doors_are_confirmed_and_no_other_title_has_any():
    assert [k for k, r in trip.ROWS.items() if r.door_confirmed] == [
        "pool-of-radiance"]


def _lengths(**full):
    """Every script is short; the named areas have 26 bytes of room left."""
    table = {i: 0x1000 for i in range(0x80)}
    table.update({int(k[1:]): trip.BUFFER_SIZE - 26 for k in full})
    return table


_POOL_TRIPS = [(0, 18), (2, 26), (3, 0), (9, 18), (18, 0), (21, 0), (22, 0),
               (23, 0), (14, 0), (0, 8)]


@pytest.mark.parametrize("here, to", _POOL_TRIPS)
def test_a_pool_trip_the_door_holds_used_to_hold_is_offered(here, to):
    # Every trip from these areas is a script trip with room past its script.
    pool = trip.ROWS["pool-of-radiance"]
    assert not trip.leg_held(pool, here, to, False, _lengths())


@pytest.mark.parametrize("here", [25, 26, 27])
def test_a_trip_from_a_grid_window_is_offered(here):
    pool = trip.ROWS["pool-of-radiance"]
    assert not trip.leg_held(pool, here, 0, False, _lengths())


def test_pool_has_no_difference_about_doors():
    assert trip.ROWS["pool-of-radiance"].differences == ()


def test_the_doors_walked_live_are_still_recorded():
    assert trip.DOORS_PROVEN == {(7, 5), (13, 27), (14, 26), (16, 27)}


def test_a_door_row_the_departures_table_names_is_proven():
    from automap import departures, fasttravel
    for row in departures.DEPARTURES:
        if row.route_to is None or "amiga" not in row.ports:
            continue
        for here in row.areas:
            assert (here, row.route_to) in trip.DOORS_PROVEN
            assert (here, row.route_to) in fasttravel.EXIT_ROUTES


def test_the_amiga_finds_the_pool_departures_and_no_other():
    pool = "pool-of-radiance"
    assert trip.departure_for(pool, 13, 0).member == "PRINCESS FATIMA"
    assert trip.departure_for(pool, 16, 0).writes == ((0x4AB5, 254),)
    assert all(trip.departure_for(pool, here, 0).writes
               for here in (1, 16, 17, 25, 26, 27, 28))
    assert all(trip.departure_for(pool, here, 0) is None
               for here in (0, 2, 3, 7, 9, 14, 18, 21, 22, 23))
    # Silver Blades' area 16 is a town, not Lizardman Keep.
    assert trip.departure_for("secret-of-the-silver-blades", 16, 0) is None


def test_a_departure_that_writes_nothing_adds_no_statements():
    assert trip.departure_prologue("pool-of-radiance", 13, 0) == b""
    assert trip.departure_prologue("pool-of-radiance", 0, 18) == b""


POOL = "pool-of-radiance"
#: Where the fake data hunk keeps Pool's `$4900` table.
VARS = 0x40000


def staged(values):
    """A Pool machine whose `$4900` table holds `values` (variable -> word),
    and the `read` that `AmigaFastTravel` hands `departure_prologue`."""
    from automap import amigavars
    m = machine(POOL)
    m.at(0x98, struct.pack(">I", VARS))
    for variable, word in values.items():
        m.poke(VARS + 2 * (variable - 0x4900), word.to_bytes(2, "big"))
    return lambda v: amigavars.read_variable(m, POOL, v).value


def _save(value, address):
    return trip.save(value, address)


@pytest.mark.parametrize("here, values, expected", [
    (1, {0x4AA9: 1}, _save(254, 0x4AA9)),
    (1, {0x4AA9: 0}, b""),
    (1, {0x4AA9: 255}, b""),
    (28, {}, _save(253, 0x4AB4)),
    (25, {0x4A9E: 255}, _save(0, 0x4A9E)),
    (26, {0x4A9E: 0}, b""),
    (27, {0x4A9E: 255}, _save(0, 0x4A9E)),
])
def test_a_pool_departure_prologue_is_the_one_save_when_its_guard_holds(
        here, values, expected):
    assert trip.departure_prologue(POOL, here, 0, None, staged(values)) \
        == expected


@pytest.mark.parametrize("kills, paid, expected", [
    (39, 0, b""), (40, 0, _save(254, 0x4AB5)), (41, 0, _save(254, 0x4AB5)),
    (40, 255, b""), (39, 255, b"")])
def test_lizardman_keep_saves_only_for_forty_kills_and_an_unpaid_commission(
        kills, paid, expected):
    read = staged({0x4A5D: kills, 0x4AB5: paid})
    assert trip.departure_prologue(POOL, 16, 0, None, read) == expected


@pytest.mark.parametrize("flags, done, saved", [
    (0x04, 0, True), (0x01, 0, True), (0x05, 254, True), (0x02, 0, False),
    (0x00, 0, False), (0x05, 255, False), (0x80, 0, False)])
def test_the_nomad_camp_saves_254_exactly_when_the_exit_block_would(
        flags, done, saved):
    read = staged({0x4A7C: flags, 0x4AB7: done})
    assert trip.departure_prologue(POOL, 17, 0, None, read) \
        == (_save(254, 0x4AB7) if saved else b"")


def test_without_a_reader_the_prologue_is_the_most_a_trip_can_need():
    for here, size in ((1, 6), (28, 6), (25, 6), (16, 6), (17, 6)):
        prologue = trip.departure_prologue(POOL, here, 0)
        assert len(prologue) == size
        assert [name for _at, name in _decode(prologue)] == ["SAVE"]


def test_a_departure_prologue_is_not_made_for_a_title_that_has_no_row():
    assert trip.departure_prologue("curse-of-the-azure-bonds", 16, 0) == b""
    assert trip.departure_prologue(POOL, 0, 18) == b""


def test_a_guard_that_cannot_be_read_raises_and_makes_no_statements():
    with pytest.raises(trip.GuardUnreadable):
        trip.departure_prologue(POOL, 17, 0, None, lambda v: None)
    # The first guard decides: a later unreadable one is not reached.
    assert trip.departure_prologue(
        POOL, 16, 0, None, lambda v: 1 if v == 0x4A5D else None) == b""
    assert issubclass(trip.GuardUnreadable, ValueError)


def _decode(blob: bytes):
    """`(offset, mnemonic)` for each statement, by the operand kinds."""
    out, at = [], 0
    while at < len(blob):
        assert blob[at] == 0x09, "only SAVE is made"
        out.append((at, "SAVE"))
        at += 1
        for _ in range(2):
            at += 2 if blob[at] == 0 else 3
    assert at == len(blob)
    return out


def test_a_departure_with_two_writes_makes_both_saves(monkeypatch):
    from automap import departures
    row = departures.Departure(
        POOL, frozenset({3}), frozenset({"amiga"}),
        guards=(departures.Guard(0x4AA9, "==", 1),),
        writes=((0x4AA9, 254), (0x4AB4, 253)))
    monkeypatch.setattr(departures, "DEPARTURES", (row,))
    assert trip.departure_prologue(POOL, 3, 0) \
        == _save(254, 0x4AA9) + _save(253, 0x4AB4)
    assert trip.departure_prologue(POOL, 3, 0, None,
                                   staged({0x4AA9: 1})) \
        == _save(254, 0x4AA9) + _save(253, 0x4AB4)
    assert trip.departure_prologue(POOL, 3, 0, None,
                                   staged({0x4AA9: 2})) == b""


def _most_room_that_holds(here: int) -> int:
    """The longest script `here` can have and the trip still be held."""
    pool = trip.ROWS[POOL]
    free = [n for n in range(trip.BUFFER_SIZE)
            if not trip.leg_held(pool, here, 0, False, {here: n, 0: 1})]
    return len(free)


@pytest.mark.parametrize("here, size", [(16, 6), (17, 6), (1, 6)])
def test_the_departure_statements_are_counted_in_the_room_a_trip_needs(
        here, size):
    # Area 2 has no row, so the difference is the prologue alone.
    assert 0 < _most_room_that_holds(2) - _most_room_that_holds(here) <= size


def test_a_second_trip_from_lizardman_keep_walks_no_door_and_asks_nothing():
    # The prologue's own guard decides, so no `(16, 27)` door is walked and no
    # exit question is put to the player on any trip.
    assert trip.departure_for(POOL, 16, 0).route_to is None
    assert trip.departure_for(POOL, 16, 27).route_to is None


def test_a_27_byte_plan_past_a_7601_byte_script_is_tier_one_packed():
    pool = trip.ROWS[POOL]
    p = trip.plan(0, (1, 2, 3), prologue=b"\x09\x00\x00\x01\x00\x00")
    assert len(trip._statements(pool, p)) == 27
    lengths = {17: 7601}
    assert trip.place(pool, 17, lengths, p) == trip.Placement(7601, 0x1DCC)
    assert 0x1DCC + trip.MESSAGE_SIZE == trip.BUFFER_SIZE
    assert trip.free_tail(pool, 17, lengths, p) == 1
    # One byte longer and the message runs off the buffer.
    assert trip.place(pool, 17, {17: 7602}, p) is None
    assert trip.free_tail(pool, 17, {17: 7602}, p) == 3


def test_the_default_layout_is_kept_where_it_fits():
    pool = trip.ROWS[POOL]
    p = trip.plan(0, (1, 2, 3))
    at, message = trip.layout(pool, 21)
    assert trip.place(pool, 17, {17: 100}, p) == trip.Placement(at, message)
    assert trip.place(pool, 17, {}, p) is None
    assert trip.place(pool, None, {17: 100}, p) is None


def test_a_title_with_no_message_has_no_packed_layout():
    curse = trip.ROWS["curse-of-the-azure-bonds"]
    p = trip.plan(3, (1, 1, 0))
    assert trip.place(curse, 1, {1: trip.BUFFER_SIZE - 20}, p) is None
    assert trip.place(curse, 1, {1: 100}, p).message_at is None


def test_a_packed_trip_writes_the_statements_at_the_script_end_then_the_message():
    key = POOL
    m = machine(key, length=7601, area=17)
    row = trip.ROWS[key]
    p = trip.plan(0, (1, 2, 3), prologue=trip.save(254, 0x4AB7))
    placed = trip.place(row, 17, {17: 7601}, p)
    armed = trip.arm(m, row, dataclasses.replace(p, placement=placed))
    assert armed is not None
    written = {w.kind: w.address for w in armed.records}
    assert written["statements"] == BUFFER + 7601
    assert written["message"] == BUFFER + 0x1DCC
    assert m.read(BUFFER + 7601, 6) == trip.save(254, 0x4AB7)
    entry = m.read(trip.ROWS[key].step_entry + BASE, 2)
    assert int.from_bytes(entry, "big") == row.ecl_origin + 7601


def test_a_pods_trip_from_the_hand_over_areas_has_the_two_saves():
    # `$24` and `$22` are script variables: the statements are the game's own
    # `SAVE`, which evaluates nothing, so they are placed ahead of the trip.
    expected = trip.save(0, 0x24) + trip.save(1, 0x22) + trip.clear_box()
    for here in (17, 25, 51, 80):
        assert trip.departure_prologue("pools-of-darkness", here, 19,
                                       False) == expected
        # An overland destination does not skip the hand-over.
        assert trip.departure_prologue("pools-of-darkness", here, 19,
                                       True) == b""
    assert trip.departure_prologue("pools-of-darkness", 19, 17, False) == b""
    # The row is Pools of Darkness' on the Amiga only.
    assert trip.departure_prologue("curse-of-the-azure-bonds", 17, 19,
                                   False) == b""


def test_the_hand_over_saves_are_counted_in_the_room_a_trip_needs():
    pods = trip.ROWS["pools-of-darkness"]
    bare = len(trip._statements(pods, trip.plan(19, (0, 0, 0))))
    # One byte more than the bare trip needs: the 12 bytes of `SAVE`s do not fit.
    lengths = {3: trip.BUFFER_SIZE - bare - 1, 17: trip.BUFFER_SIZE - bare - 1,
               19: 1}
    assert not trip.leg_held(pods, 3, 19, False, lengths, False)
    assert trip.leg_held(pods, 17, 19, False, lengths, False)


def _pods(area, mode):
    row = trip.ROWS["pools-of-darkness"]
    m = machine("pools-of-darkness", area=area)
    m.at(row.mode, bytes([mode]))
    return m, row


def _overland(area, mode=3, kind=4, text=b"Encamp"):
    m, row = _pods(area, mode=mode)
    m.at(row.menu_kind, kind.to_bytes(2, "big"))
    m.at(row.menu_at, text + b"\0" + b"\0" * 40)
    return m, row


@pytest.mark.parametrize("area", [17, 25, 51, 80])
def test_the_gate_opens_at_the_overland_menu(area):
    m, row = _overland(area)
    assert trip.gate(m, row)


@pytest.mark.parametrize("mode,kind,text", [
    (3, 1, b"Encamp"),
    (3, 4, b"Area Cast View Encamp Search Look"),
    (4, 4, b"Encamp"),
    (0, 4, b"Encamp"),
])
def test_the_gate_stays_shut_at_mixed_overland_state(mode, kind, text):
    m, row = _overland(17, mode=mode, kind=kind, text=text)
    assert not trip.gate(m, row)


def test_the_gate_stays_shut_at_the_overland_with_a_key_pending():
    m, row = _overland(17)
    m.at(row.key_buffer, b"\x01\x0d")
    assert not trip.gate(m, row)


@pytest.mark.parametrize("area", [17, 25, 51, 80])
def test_with_the_gate_open_the_hand_over_saves_lead_the_trip(area):
    m, row = _overland(area)
    assert trip.gate(m, row)
    prologue = trip.departure_prologue(row.key, area, 19, False)
    plan = trip.plan(19, (1, 2, 0), None, 1, prologue=prologue)
    armed = trip.arm(m, row, plan)
    assert armed is not None
    statements = b"".join(d for a, d, _v in m.log
                          if a >= BUFFER and a < BUFFER + trip.BUFFER_SIZE)
    assert (trip.save(0, 0x24) + trip.save(1, 0x22) + trip.clear_box()
            in statements)


@pytest.mark.parametrize("key", ["curse-of-the-azure-bonds",
                                 "secret-of-the-silver-blades",
                                 "pools-of-darkness"])
def test_entry_words_reads_only_the_step_entry_off_pool(key):
    row = trip.ROWS[key]
    m = machine(key)
    m.at(row.step_entry + 2, b"\x99" * 8)
    assert trip.entry_words(m, row) == ENTRY.to_bytes(2, "big")


def test_entry_words_reads_five_words_on_pool():
    row = trip.ROWS["pool-of-radiance"]
    m = machine("pool-of-radiance")
    assert len(trip.entry_words(m, row)) == 2 * trip.ENTRY_WORDS


@pytest.mark.parametrize("here, to, square", [
    (7, 5, (5, 7, 3)),
    (13, 27, (6, 15)),
    (16, 27, (8, 15, 2)),
])
def test_the_proven_door_routes_are_pinned(here, to, square):
    from automap import fasttravel
    route = fasttravel.EXIT_ROUTES[(here, to)]
    assert (here, to) in trip.DOORS_PROVEN and not route.combat
    assert tuple(route.square) == square


# -- the init span -------------------------------------------------------------

INIT_AREA = 1
#: A made-up area: a 9-byte tail, with the init entry 0x57 bytes before the end.
INIT_LENGTH = trip.BUFFER_SIZE - 9
INIT_START = 0x1DA0


def init_room(monkeypatch, area=INIT_AREA, size=INIT_LENGTH - INIT_START):
    """`INIT_ROOM` for `area`, hashing the made-up script bytes `machine`
    lays down, so no game byte is involved."""
    room = trip.InitRoom(INIT_START, trip.BUFFER_SIZE, size,
                         hashlib.sha1(b"\xee" * size).hexdigest())
    monkeypatch.setitem(trip.INIT_ROOM, (POOL, area), room) \
        if isinstance(trip.INIT_ROOM, dict) else monkeypatch.setattr(
            trip, "INIT_ROOM", {**trip.INIT_ROOM, (POOL, area): room})
    return room


@pytest.fixture(autouse=True)
def _journal_in_tmp(tmp_path, monkeypatch):
    """No test writes a trip journal into the player's cache."""
    monkeypatch.setattr(trip, "journal_dir", lambda: tmp_path / "journal")


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(trip, "journal_dir", lambda: tmp_path / "journal")
    return tmp_path / "journal"


def init_machine(room):
    """A Pool machine in the init area, whose script is `0xEE` to the end of
    the disk bytes, its tail zero, and whose fifth entry word is the span's."""
    m = machine(POOL, length=INIT_LENGTH, area=INIT_AREA)
    row = trip.ROWS[POOL]
    m.at(row.step_entry + 2 * (trip.ENTRY_WORDS - 1),
         (row.ecl_origin + room.start).to_bytes(2, "big"))
    return m


def init_plan(room, prologue=b"\x09\x00\x00\x01\x00\x00"):
    pool = trip.ROWS[POOL]
    p = trip.plan(0, (1, 2, 3), prologue=prologue)
    assert len(trip._statements(pool, p)) == 27
    return p, trip.place(pool, INIT_AREA, {INIT_AREA: INIT_LENGTH}, p,
                         frozenset({INIT_AREA}))


def test_a_trip_from_a_nine_byte_tail_has_no_placement_without_the_span(
        monkeypatch):
    init_room(monkeypatch)
    pool = trip.ROWS[POOL]
    p = trip.plan(0, (1, 2, 3))
    lengths = {INIT_AREA: INIT_LENGTH, 0: 100}
    assert trip.place(pool, INIT_AREA, lengths, p) is None
    assert trip.free_tail(pool, INIT_AREA, lengths, p) == 3
    assert trip.leg_held(pool, INIT_AREA, 0, False, lengths)


def test_the_init_span_takes_the_statements_at_its_start_and_the_message_after(
        monkeypatch):
    room = init_room(monkeypatch)
    pool = trip.ROWS[POOL]
    p, placed = init_plan(room)
    # 27 bytes from 0x1DA0 end at 0x1DBB; the message follows on a longword.
    assert placed == trip.Placement(0x1DA0, 0x1DBC, room)
    assert placed.message_at + trip.MESSAGE_SIZE <= room.end
    lengths = {INIT_AREA: INIT_LENGTH, 0: 100}
    assert trip.free_tail(pool, INIT_AREA, lengths, p,
                          frozenset({INIT_AREA})) == 1
    assert not trip.leg_held(pool, INIT_AREA, 0, False, lengths, None,
                             frozenset({INIT_AREA}))
    # The span is offered only for an area the disks matched.
    assert trip.place(pool, INIT_AREA, lengths, p, frozenset()) is None


def test_an_init_trip_writes_into_the_span_and_disarm_restores_it_exactly(
        monkeypatch, journal):
    room = init_room(monkeypatch)
    m = init_machine(room)
    before = bytes(m.ram)
    p, placed = init_plan(room)
    armed = trip.arm(m, POOL, dataclasses.replace(p, placement=placed))
    assert armed is not None
    assert kinds(armed) == ["init", "init", "entry", "trigger"]
    statements, message, entry, _trigger = armed.records
    assert statements.address == BUFFER + room.start
    assert BUFFER + room.start < message.address
    assert message.address + trip.MESSAGE_SIZE <= BUFFER + room.end
    assert message.address % 4 == 0
    assert int.from_bytes(entry.data, "big") == (
        trip.ROWS[POOL].ecl_origin + room.start)
    # The originals are the script's bytes, which a put-back writes again.
    assert statements.original == b"\xee" * len(statements.data)
    assert trip.disarm(m, armed) is True
    assert bytes(m.ram) == before
    assert not journal.exists() or not list(journal.iterdir())


@pytest.mark.parametrize("what", ["hash", "tail", "init word"])
def test_a_span_that_is_not_the_disks_arms_nothing(monkeypatch, journal, what):
    room = init_room(monkeypatch)
    m = init_machine(room)
    row = trip.ROWS[POOL]
    if what == "hash":
        m.poke(BUFFER + room.start + 3, b"\x01")
    elif what == "tail":
        m.poke(BUFFER + room.size + room.start + 1, b"\x01")
    else:
        m.at(row.step_entry + 8, (row.ecl_origin + 0x1000).to_bytes(2, "big"))
    p, placed = init_plan(room)
    assert trip.arm(m, POOL, dataclasses.replace(p, placement=placed)) is None
    assert m.log == []
    assert not journal.exists()


def test_a_journal_that_cannot_be_written_arms_nothing(monkeypatch, tmp_path):
    room = init_room(monkeypatch)
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    monkeypatch.setattr(trip, "journal_dir", lambda: blocker / "journal")
    m = init_machine(room)
    p, placed = init_plan(room)
    assert trip.arm(m, POOL, dataclasses.replace(p, placement=placed)) is None
    assert m.log == []


def test_an_init_trip_is_journalled_before_the_first_write(monkeypatch, journal):
    room = init_room(monkeypatch)
    m = init_machine(room)
    seen = []
    m.on_write = lambda addr, data: seen.append(
        json.loads(next(journal.iterdir()).read_text())) if not seen else None
    p, placed = init_plan(room)
    armed = trip.arm(m, POOL, dataclasses.replace(p, placement=placed))
    saved = seen[0]
    assert saved["from_area"] == INIT_AREA and saved["title"] == POOL
    assert [r["kind"] for r in saved["records"]] == kinds(armed)
    first = saved["records"][0]
    assert first["address"] == BUFFER + room.start
    assert first["original"] == (b"\xee" * len(armed.records[0].data)).hex()


def test_the_journal_goes_once_the_trip_has_fired_or_been_put_back(
        monkeypatch, journal):
    room = init_room(monkeypatch)
    row = trip.ROWS[POOL]
    p, placed = init_plan(room)
    plan = dataclasses.replace(p, placement=placed)
    m = init_machine(room)
    armed = trip.arm(m, POOL, plan)
    assert list(journal.iterdir())
    trip.disarm(m, armed)
    assert not list(journal.iterdir())
    armed = trip.arm(m, POOL, plan)
    m.at(row.area, b"\x00")                  # the game ran it
    trip.tidy(m, armed, 0, {0: 100})
    assert not list(journal.iterdir())


def test_a_crashed_run_is_repaired_from_its_journal(monkeypatch, journal):
    room = init_room(monkeypatch)
    m = init_machine(room)
    before = bytes(m.ram)
    p, placed = init_plan(room)
    assert trip.arm(m, POOL, dataclasses.replace(p, placement=placed))
    # Wish stops here, with the trip written and the key linked.
    assert bytes(m.ram) != before
    assert trip.repair(m) is True
    assert bytes(m.ram) == before
    assert not list(journal.iterdir())
    assert trip.repair(m) is False


def test_a_journalled_trip_the_game_has_run_is_forgotten_not_undone(
        monkeypatch, journal):
    room = init_room(monkeypatch)
    m = init_machine(room)
    p, placed = init_plan(room)
    trip.arm(m, POOL, dataclasses.replace(p, placement=placed))
    m.at(trip.ROWS[POOL].area, b"\x00")
    now = bytes(m.ram)
    assert trip.repair(m) is True
    assert bytes(m.ram) == now and not list(journal.iterdir())


def test_a_journal_of_another_boot_is_forgotten_not_undone(
        monkeypatch, journal):
    room = init_room(monkeypatch)
    m = init_machine(room)
    p, placed = init_plan(room)
    trip.arm(m, POOL, dataclasses.replace(p, placement=placed))
    now = bytes(m.ram)
    m.data_base += 0x100
    assert trip.repair(m) is True
    assert bytes(m.ram) == now and not list(journal.iterdir())


def test_a_machine_that_cannot_be_written_leaves_the_journal_for_next_time(
        monkeypatch, journal):
    room = init_room(monkeypatch)
    m = init_machine(room)
    before = bytes(m.ram)
    p, placed = init_plan(room)
    trip.arm(m, POOL, dataclasses.replace(p, placement=placed))
    m.fail_at = BUFFER + room.start
    with pytest.raises(NotConnected):
        trip.repair(m)
    assert list(journal.iterdir())
    assert trip.repair(m) is True
    assert bytes(m.ram) == before


def test_a_put_back_that_fails_too_raises_with_the_records_and_disarm_finishes(
        monkeypatch, journal):
    room = init_room(monkeypatch)
    m = init_machine(room)
    before = bytes(m.ram)
    p, placed = init_plan(room)
    plan = dataclasses.replace(p, placement=placed)
    _buffer, writes = trip._prepare(m, trip.ROWS[POOL], plan)
    dead = {"on": False, "done": False}
    real = m.write

    def write(addr, data, verify=True):
        if dead["on"]:
            raise NotConnected("the emulator went away")
        real(addr, data, verify)
        if addr == writes[2][0] and not dead["done"]:
            # The entry word has landed, and the machine goes away.
            dead["on"] = dead["done"] = True
            raise NotConnected("the emulator went away")

    m.write = write
    with pytest.raises(trip.ArmIncomplete) as err:
        trip.arm(m, POOL, plan)
    assert kinds(err.value.armed) == ["init", "init", "entry"]
    dead["on"] = False
    assert trip.disarm(m, err.value.armed) is True
    assert bytes(m.ram) == before


def test_init_rooms_match_a_span_by_its_hash_in_every_copy(monkeypatch):
    room = init_room(monkeypatch, area=17)
    pool = trip.ROWS[POOL]
    body = b"\x11" * 0x1DA0 + b"\xee" * room.size
    other = body[:-1] + b"\x00"

    def copies(bodies):
        monkeypatch.setattr(trip, "_script_copies",
                            lambda row, disks: iter(bodies))

    copies([{17: body}, {17: body, 3: b"x"}])
    assert trip.init_rooms(pool, None) == {17}
    copies([{17: body}, {17: other}])
    assert trip.init_rooms(pool, None) == frozenset()
    copies([{3: body}])
    assert trip.init_rooms(pool, None) == frozenset()
    copies([{17: body + b"\x00"}])
    assert trip.init_rooms(pool, None) == frozenset()
    assert trip.init_rooms("curse-of-the-azure-bonds", None) == frozenset()


def test_a_connection_is_named_by_its_lane_holder_or_its_address():
    class Debugger:
        holder = "w/1"

    class Target:
        debugger = Debugger()

    assert trip.connection_name(Target()) == "w-1"
    Target.debugger = type("D", (), {"host": "127.0.0.1", "port": 6520})()
    assert trip.connection_name(Target()) == "127.0.0.1-6520"
    assert trip.connection_name(object()) == "local"


def test_a_journal_another_live_wish_wrote_is_left_alone(monkeypatch, journal):
    room = init_room(monkeypatch)
    m = init_machine(room)
    before = bytes(m.ram)
    p, placed = init_plan(room)
    assert trip.arm(m, POOL, dataclasses.replace(p, placement=placed))
    armed_ram = bytes(m.ram)
    path = next(journal.iterdir())
    saved = json.loads(path.read_text())
    # Written by a process that is not this one and is still running.
    saved["owner"] = {"pid": os.getppid(), "started": trip._started(
        os.getppid())}
    path.write_text(json.dumps(saved))
    assert trip.repair(m) is False
    assert bytes(m.ram) == armed_ram and path.exists()
    # The same journal from a process that has gone is put back.
    saved["owner"] = {"pid": 2 ** 22 + 12345, "started": None}
    path.write_text(json.dumps(saved))
    assert trip.repair(m) is True
    assert bytes(m.ram) == before and not list(journal.iterdir())


def test_a_journal_another_instance_in_this_process_wrote_is_left_alone(
        monkeypatch, journal):
    room = init_room(monkeypatch)
    m = init_machine(room)
    before = bytes(m.ram)
    p, placed = init_plan(room)
    assert trip.arm(m, POOL, dataclasses.replace(p, placement=placed), "a")
    armed_ram = bytes(m.ram)
    assert trip.repair(m, "b") is False
    assert bytes(m.ram) == armed_ram and list(journal.iterdir())
    assert trip.repair(m, "a") is True
    assert bytes(m.ram) == before and not list(journal.iterdir())


@pytest.mark.parametrize("error, alive", [(5, True), (87, False)])
def test_windows_access_denied_is_a_live_owner(monkeypatch, error, alive):
    import types
    kernel32 = types.SimpleNamespace(
        OpenProcess=lambda *a: None, CloseHandle=lambda h: 1,
        WaitForSingleObject=lambda h, t: 0x102)
    ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(kernel32=kernel32),
        GetLastError=lambda: error, c_void_p=object, c_uint32=object,
        c_int=object)
    monkeypatch.setitem(sys.modules, "ctypes", ctypes)
    monkeypatch.setattr(trip.os, "name", "nt")
    assert trip._owner_alive({"pid": 4242, "started": None}) is alive
    assert kernel32.OpenProcess.restype is object


def test_a_pid_of_zero_or_below_is_a_dead_owner():
    assert not trip._owner_alive({"pid": 0, "started": None})
    assert not trip._owner_alive({"pid": -1, "started": None})


def test_a_pid_that_cannot_be_signalled_is_alive_and_logged(
        monkeypatch, caplog):
    def kill(pid, sig):
        raise PermissionError
    if os.name == "nt":
        pytest.skip("Windows asks _windows_alive, not os.kill")
    monkeypatch.setattr(trip.os, "kill", kill)
    # Once any test has imported wish/debuglog.py the "wish" logger stops
    # propagating to the root, where caplog listens, so attach it directly.
    monkeypatch.setattr(trip._log, "handlers", [caplog.handler])
    monkeypatch.setattr(trip._log, "propagate", False)
    caplog.set_level("INFO", logger=trip._log.name)
    assert trip._owner_alive({"pid": os.getppid(), "started": None},
                             None, "the-journal.json")
    assert "the-journal.json" in caplog.text


def test_a_reused_pid_is_not_the_journals_owner(monkeypatch, journal):
    if trip._started(os.getppid()) is None:
        pytest.skip("no /proc to read a start time from")
    assert not trip._owner_alive({"pid": os.getppid(), "started": "1"})


def test_arm_clears_the_journal_whenever_nothing_was_left_armed(
        monkeypatch, journal):
    room = init_room(monkeypatch)
    m = init_machine(room)
    p, placed = init_plan(room)
    # A put-back that succeeds without clearing, as any later exit might.
    monkeypatch.setattr(trip, "_put_back", lambda target, armed: True)
    m.fail_at = BUFFER + room.start
    assert trip.arm(m, POOL, dataclasses.replace(p, placement=placed)) is None
    assert not list(journal.iterdir())


def test_a_tail_trip_is_journalled_before_the_first_write(journal):
    key = "pool-of-radiance"
    m = machine(key, area=26)
    seen = []
    m.on_write = lambda addr, data: seen.append(
        json.loads(next(journal.iterdir()).read_text())) if not seen else None
    armed = trip.arm(m, key, trip.plan(0, (9, 14, 2), prologue=BOAT_EXIT))
    saved = seen[0]
    assert saved["from_area"] == 26 and saved["title"] == key
    assert [r["kind"] for r in saved["records"]] == kinds(armed)
    assert "init" not in kinds(armed)


def test_a_tail_arm_stopped_partway_is_repaired_and_the_next_arm_succeeds(
        journal):
    key = "pool-of-radiance"
    m = machine(key, area=26)
    before = bytes(m.ram)
    writes = []

    def stop(addr, data):
        writes.append(addr)
        if len(writes) == 2:
            raise SystemExit

    m.on_write = stop
    p = trip.plan(0, (9, 14, 2), prologue=BOAT_EXIT)
    with pytest.raises(SystemExit):
        trip.arm(m, key, p)
    m.on_write = None
    assert bytes(m.ram) != before
    assert trip.arm(m, key, p) is None
    assert trip.repair(m) is True
    assert bytes(m.ram) == before
    assert not list(journal.iterdir())
    assert trip.arm(m, key, p) is not None


def test_a_door_put_back_leaves_another_trips_journal_alone(journal):
    key = "pool-of-radiance"
    tail = machine(key, area=26)
    assert trip.arm(tail, key, trip.plan(0, (9, 14, 2), prologue=BOAT_EXIT))
    saved = next(journal.iterdir()).read_text()
    m, pool = _door_machine()
    armed = trip.arm_door(m, pool, (4, 0, 0))
    assert trip.disarm(m, armed) is True
    assert next(journal.iterdir()).read_text() == saved


def test_a_key_buffer_title_has_taken_the_key_once_its_buffer_byte_reads_zero():
    m = FakeAmiga()
    pods = trip.ROWS["pools-of-darkness"]
    assert pods.window_pointer is None
    m.at(pods.key_buffer, bytes([trip.FORWARD_KEY[0]]))
    assert not trip.port_empty(m, pods)
    m.at(pods.key_buffer, b"\x00")
    assert trip.port_empty(m, pods)


def test_a_pools_of_darkness_trip_can_write_the_overland_cell():
    pod = trip.ROWS["pools-of-darkness"]
    assert trip.encode(pod, None, 17, grid=(6, 12)) \
        == trip.save(6, 0x25) + trip.save(12, 0x26) + trip.newecl(17)


def test_pools_of_darkness_reads_its_overland_cell_only_on_an_overland():
    pod = trip.ROWS["pools-of-darkness"]
    table = 0x44000
    m = FakeAmiga()
    m.at(0x57AC, struct.pack(">I", table))
    m.poke(table + 0x25, bytes([20]))
    m.poke(table + 0x26, bytes([7]))
    m.at(pod.mode, bytes([pod.world_mode]))
    assert trip.overland(m, pod) is None
    m.at(pod.mode, bytes([pod.overland_mode]))
    assert trip.overland(m, pod) == (20, 7)


SILVER = "secret-of-the-silver-blades"

#: The C64 row's values: (destination, variable, value).
_SILVER_ARRIVALS = {
    0x21: [(0x4C62, 1), (0x4C2A, 1)],
    0x41: [(0x4CFD, 0xFF)], 0x44: [(0x4CFD, 0xFF)],
    0x61: [(0x4CFD, 0xFF)], 0x62: [(0x4CFD, 0xFF)],
    0x51: [(0x4BF0, 0), (0x4BF1, 8), (0x4CFD, 49), (0x4CFE, 87),
           (0x4C6C, 49), (0x4C6D, 87)],
    0x52: [(0x4CFD, 65), (0x4CFE, 85), (0x4C6C, 65), (0x4C6D, 85)],
    0x33: [(0x4CFD, 50), (0x4CFE, 50), (0x4C69, 0), (0x4C6E, 1),
           (0x4C6A, 1), (0x4C6F, 0)],
}


def _room_lengths(room):
    """Every script is short, except area 0x20's, which leaves `room` bytes."""
    table = _lengths()
    table[0x20] = trip.BUFFER_SIZE - room
    return table


def test_the_silver_blades_arrival_writes_are_the_c64_rows():
    from automap import fasttravel
    assert (trip.ROWS[SILVER].arrival_writes
            == fasttravel.SECRET_OF_THE_SILVER_BLADES.arrival_writes)


@pytest.mark.parametrize("to, writes", sorted(_SILVER_ARRIVALS.items()))
def test_a_silver_blades_trip_stores_its_arrival_writes(to, writes):
    expected = b"".join(trip.save(v, a) for a, v in writes)
    assert trip.arrival_prologue(SILVER, to) == expected
    assert len(expected) == 6 * len(writes)


def test_loadpieces_is_seven_bytes():
    assert trip.loadpieces(3, 127, 127) == bytes((0x37, 0, 3, 0, 127, 0, 127))


def test_the_village_walls_load_after_the_area_file_save():
    row = trip.ROWS[SILVER]
    p = trip.plan(0x51, (0, 8, 1), area_file=5,
                  epilogue=trip.arrival_epilogue(SILVER, 0x51))
    assert trip._statements(row, p).endswith(
        trip.save(5, 0x7F12) + trip.save(1, 0x4BE7) + trip.save(1, 0x4BE8)
        + trip.save(1, 0x4BE9) + trip.loadpieces(3, 127, 127)
        + trip.newecl(0x51))


@pytest.mark.parametrize("to", [0x34, 0x52])
def test_areas_without_pins_or_walls_have_no_arrival_epilogue(to):
    assert trip.arrival_epilogue(SILVER, to) == b""


def test_the_village_arrival_epilogue_is_twenty_five_bytes():
    assert len(trip.arrival_epilogue(SILVER, 0x51)) == 25


_CLEAR_ONLY = [0x22, 0x30, 0x40, 0x41, 0x44, 0x60, 0x61, 0x62, 0x63]


@pytest.mark.parametrize("to", _CLEAR_ONLY)
def test_a_silver_blades_trip_into_a_two_piece_wall_area_clears_the_third_pin(
        to):
    row = trip.ROWS[SILVER]
    assert trip.arrival_epilogue(SILVER, to) == trip.save(0, 0x4BE9)
    for side in (3, 4):
        p = trip.plan(to, (3, 3, 1), area_file=side,
                      epilogue=trip.arrival_epilogue(SILVER, to))
        assert trip._statements(row, p).endswith(
            trip.save(side, 0x7F12) + trip.save(0, 0x4BE9)
            + trip.newecl(to))


def test_a_silver_blades_trip_into_area_51_sets_all_three_pins():
    epilogue = trip.arrival_epilogue(SILVER, 0x33)
    assert epilogue == (trip.save(1, 0x4BE7) + trip.save(1, 0x4BE8)
                        + trip.save(0, 0x4BE9))
    assert len(epilogue) == 18


def _saves_4be9(code: bytes) -> bool:
    """Whether `code` holds a whole `SAVE value, [$4BE9]` statement."""
    whole = trip.save(0, 0x4BE9)
    return any(code[i] == whole[0] and code[i + 1] == whole[1]
               and code[i + 3:i + 6] == whole[3:]
               for i in range(len(code) - len(whole) + 1))


def test_every_two_piece_wall_area_missing_a_piece_clears_the_third_pin():
    """A walked arrival has $4BE9 clear; a trip from a pin-1 area has not."""
    import struct

    from automap import amiga
    from goldbox import areas
    from goldbox.amiga_adf import AmigaDisk
    from tools.areas import eclsweep
    ids = None
    for image in _images():
        disk = AmigaDisk(image)
        for path, _entry in disk.walk():
            if path.upper().endswith("/WALLDEF.GLB"):
                table = amiga.glib_blocks(disk.read_file(path))[0]
                count = struct.unpack(">H", table[:2])[0]
                ids = {i for i, _b in struct.iter_unpack(
                    ">HH", table[2:2 + 4 * count])}
                if 3 in ids and 21 in ids:
                    break
                ids = None
        if ids:
            break
    if not ids:
        pytest.skip("needs the player's Amiga Silver Blades disks")
    row = trip.ROWS[SILVER]
    checked = set()
    for bodies in trip._script_copies(row, _images()):
        for area, body in bodies.items():
            if areas.area_in(area, row.title) is None:
                continue
            for at, op, operands in eclsweep.raw_loads(body):
                second = operands[1]
                if (op != trip.LOADPIECES or second in (127, 255)
                        or second in ids
                        or _saves_4be9(body[:at])):
                    continue
                checked.add(area)
                assert trip.save(0, 0x4BE9) in trip.arrival_epilogue(
                    SILVER, area), hex(area)
    assert checked >= set(_CLEAR_ONLY) | {0x33}


def test_leg_held_counts_the_arrival_epilogue():
    assert not trip.leg_held(trip.ROWS[SILVER], 0x20, 0x51, False,
                             _room_lengths(88))
    assert trip.leg_held(trip.ROWS[SILVER], 0x20, 0x51, False,
                         _room_lengths(87))


@pytest.mark.parametrize("to", [0x22, 0x30, 0x40])
def test_a_silver_blades_trip_without_arrival_writes_adds_none(to):
    assert trip.arrival_prologue(SILVER, to) == b""


def test_other_titles_have_no_arrival_writes():
    assert trip.arrival_prologue(POOL, 0x21) == b""


def test_area_file_for_names_the_destination_group_only_across_groups():
    assert trip.area_file_for(SILVER, 0x10, 0x30) == 3
    assert trip.area_file_for(SILVER, 0x10, 0x11) is None
    assert trip.area_file_for(SILVER, 0x10, 0x51) == 5
    assert trip.area_file_for(SILVER, 0x30, 0x10) == 1
    assert trip.area_file_for("curse-of-the-azure-bonds", 1, 16) == 3
    assert trip.area_file_for(POOL, 0x21, 0x22) is None
    assert trip.area_file_for("pools-of-darkness", 1, 2) is None


def test_the_area_file_save_holds_no_curse_leg_on_the_players_disks(
        monkeypatch):
    """Every Curse leg is held or offered as it was before the area-file
    `SAVE` was counted."""
    curse = trip.ROWS["curse-of-the-azure-bonds"]
    for image in _images():
        lengths = trip.script_lengths(curse.key, [image])
        if not lengths:
            continue
        init = trip.init_rooms(curse, [image])
        for here in lengths:
            for to in lengths:
                for back in (False, True):
                    with_save = trip.leg_held(curse, here, to, back, lengths,
                                              None, init)
                    with monkeypatch.context() as m:
                        m.setattr(trip, "area_file_for", lambda *a: None)
                        without = trip.leg_held(curse, here, to, back,
                                                lengths, None, init)
                    assert with_save == without, (here, to, back)
        return
    pytest.skip("needs the player's Amiga Curse disks")


def test_leg_held_counts_the_area_file_save():
    row = trip.ROWS[SILVER]
    assert not trip.leg_held(row, 0x20, 0x22, False, _room_lengths(27))
    assert trip.leg_held(row, 0x20, 0x22, False, _room_lengths(26))
    assert trip.leg_held(row, 0x20, 0x30, False, _room_lengths(27))
    assert not trip.leg_held(row, 0x20, 0x30, False, _room_lengths(33))


@pytest.mark.parametrize("to, extra", [(0x22, 6), (0x41, 18), (0x21, 12)])
def test_leg_held_counts_the_arrival_writes(to, extra):
    row = trip.ROWS[SILVER]
    # The 21-byte trip fits exactly in 21 bytes of room.
    assert not trip.leg_held(row, 0x20, to, False, _room_lengths(21 + extra))
    if extra:
        assert trip.leg_held(row, 0x20, to, False, _room_lengths(20 + extra))
