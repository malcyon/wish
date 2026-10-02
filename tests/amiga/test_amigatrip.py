"""`automap/amigatrip.py`: the Amiga trip's statements, writes and put-back, on a fake machine."""
from __future__ import annotations

import dataclasses
import struct

import pytest

from automap import amigatrip as trip
from automap.target import NotConnected

BASE = 0x10000
BUFFER = 0x30000
WINDOW = 0x40000
PORT = 0x40100
GRID = 0x41000
ENTRY = 0x8137
POOL_ENTRY = 0xA000


class FakeAmiga:
    """A flat memory with a data hunk at `BASE`, `read`, `read_blocks` and
    `write(addr, data, verify)`. Every write is logged; `fail_on` names a
    write kind's address that raises; `on_write` runs after each write."""

    def __init__(self):
        self.memory = bytearray(0x50000)
        self.data_base = BASE
        self.log: list[tuple[int, bytes, bool]] = []
        self.fail_at: int | None = None
        self.on_write = None

    def read(self, addr, length):
        return bytes(self.memory[addr:addr + length])

    def read_blocks(self, blocks):
        return [self.read(b[0], b[1]) for b in blocks]

    def write(self, addr, data, verify=True):
        if addr == self.fail_at:
            raise NotConnected("the emulator went away")
        self.memory[addr:addr + len(data)] = data
        self.log.append((addr, bytes(data), verify))
        if self.on_write is not None:
            self.on_write(addr, bytes(data))

    def poke(self, addr, data):
        self.memory[addr:addr + len(data)] = data

    def at(self, offset, data):
        self.poke(BASE + offset, data)


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
        m.at(row.grid_spots[0].pointer, struct.pack(">I", GRID))
        m.at(row.square_spots[0].offset, bytes([9, 14, 4]))
    else:
        m.at(row.step_entry, ENTRY.to_bytes(2, "big"))
        m.at(row.menu_kind, b"\x00\x01")
        if row.menu_text is not None:
            m.at(row.menu_at, row.menu_text + b"\0")
        m.at(row.key_buffer, b"\x00\x0d")
    return m


def blades():
    """Silver Blades' row with a menu text, which it does not have yet."""
    return dataclasses.replace(trip.ROWS["secret-of-the-silver-blades"],
                               menu_text=b"Made Up Menu")


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
    assert trip.free_tail(pool, 0, {0: message + 1}) == 3
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


def test_silver_blades_gate_stays_shut_until_its_menu_is_measured():
    key = "secret-of-the-silver-blades"
    assert not trip.gate(machine(key, row=blades()), trip.ROWS[key])
    assert trip.gate(machine(key, row=blades()), blades())


def test_pools_gate_takes_the_grid_and_not_a_waiting_message():
    pool = trip.ROWS["pool-of-radiance"]
    m = machine("pool-of-radiance")
    m.at(pool.mode, b"\x03")
    m.at(pool.view, b"\x03")
    assert trip.gate(m, pool)
    m.at(pool.view, b"\x01")
    assert not trip.gate(m, pool)
    m = machine("pool-of-radiance")
    m.poke(PORT + trip.PORT_LIST, trip.link(0x45000))
    assert not trip.gate(m, pool)


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
    before = bytes(m.memory)
    m.fail_at = BASE + 0x584C
    assert trip.arm(m, key, trip.plan(3, (10, 1, 0))) is None
    assert bytes(m.memory) == before
    assert len(m.log) == 2


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
    before = bytes(m.memory)
    armed = trip.arm(m, key, trip.plan(3, (1, 1, 0)))
    assert bytes(m.memory) != before
    assert trip.disarm(m, armed) is True
    assert bytes(m.memory) == before


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
    row = blades()
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

    assert held("curse-of-the-azure-bonds", 3, 1) == {"tilverton"}
    assert held("curse-of-the-azure-bonds", 1, 3) == set()
    assert held("curse-of-the-azure-bonds", 1, 3, back=True) == {
        "return_landing"}
    assert held("pools-of-darkness", 0x15, 0x16) == set()
    assert "weak_gate" in held("pool-of-radiance", 0, 14)
    assert {"leave_grid", "onto_grid"} & held("pool-of-radiance", 26, 0) == {
        "leave_grid"}
    assert "onto_grid" in held("pool-of-radiance", 0, 26)


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
