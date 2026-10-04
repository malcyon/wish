"""`automap/amigaparty.py`: walking an Amiga title's party list in synthetic memory.

Every byte here is made up: records carry an invented name and hit points at
the row's own offsets, and the lists are linked at the row's own link offsets.
Whether those offsets are the game's is a measurement on a running Amiga, in
`docs/96-live-memory-automapper.md`; these tests check the walk and its guards.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from automap import amiga
from automap import amigaparty as ap
from goldbox import amiga_pod, amiga_por, amiga_port

CHIP = 0x000000
SLOW = 0xC00000
BASE = 0xC10000          # the data hunk
HEAP = 0xC20000


class Memory:
    """Chip and slow memory as bytearrays, read the way a transport reads them.

    `reads` counts single reads and `trips` counts `read_blocks` calls, each
    of which stands for one round trip to the emulator.
    """

    def __init__(self):
        self.regions = {CHIP: bytearray(0x80000), SLOW: bytearray(0x80000)}
        self.reads = self.trips = 0

    def _where(self, addr: int, length: int):
        for base, mem in self.regions.items():
            if base <= addr and addr + length <= base + len(mem):
                return mem, addr - base
        raise amiga.GuestError(f"no memory at {addr:#x}+{length:#x}")

    def read(self, addr: int, length: int) -> bytes:
        self.reads += 1
        mem, at = self._where(addr, length)
        return bytes(mem[at:at + length])

    def read_blocks(self, blocks) -> list[bytes]:
        self.trips += 1
        out = [self.read(addr, length) for addr, length in blocks]
        self.reads -= len(blocks)
        return out

    def put(self, addr: int, data: bytes) -> None:
        mem, at = self._where(addr, len(data))
        mem[at:at + len(data)] = data

    def long(self, addr: int, value: int) -> None:
        self.put(addr, value.to_bytes(4, "big"))


def record(row: ap.PartyRow, name: bytes, hp: int, hp_max: int) -> bytearray:
    raw = bytearray(row.record_size)
    raw[row.name:row.name + len(name)] = name
    raw[row.hp.offset] = hp
    raw[row.hp_max.offset] = hp_max
    return raw


def lay_party(mem: Memory, row: ap.PartyRow, people, items=(), effects=(),
              slots=None, heap=HEAP):
    """Records at HEAP, 0x400 apart, linked in order; returns their addresses.

    `items[i]` and `effects[i]` are how many nodes member `i` holds, and
    `slots[i]` its slot byte (its index when not given).
    """
    addrs = [heap + 0x400 * i for i in range(len(people))]
    node_at = heap + 0x20000
    for i, (address, (name, hp, hp_max)) in enumerate(zip(addrs, people)):
        raw = record(row, name, hp, hp_max)
        raw[row.slot] = i if slots is None else slots[i]
        following = addrs[i + 1] if i + 1 < len(addrs) else 0
        raw[row.next_offset:row.next_offset + 4] = following.to_bytes(4, "big")
        for chain, count in ((row.items, items[i] if items else 0),
                             (row.effects, effects[i] if effects else 0)):
            nodes = [node_at + 0x80 * n for n in range(count)]
            node_at += 0x80 * count
            first = nodes[0] if nodes else 0
            raw[chain.head:chain.head + 4] = first.to_bytes(4, "big")
            for n, at in enumerate(nodes):
                body = bytearray(chain.size)
                body[0] = 0xA0 + n
                nxt = nodes[n + 1] if n + 1 < len(nodes) else 0
                body[chain.link:chain.link + 4] = nxt.to_bytes(4, "big")
                mem.put(at, bytes(body))
        mem.put(address, bytes(raw))
    mem.long(BASE + row.head, addrs[0] if addrs else 0)
    return addrs


THREE = [(b"ALDRIC", 12, 20), (b"BRYNNA", 7, 7), (b"COSIMO", 0, 9)]


@pytest.mark.parametrize("key", sorted(ap.ROWS))
def test_a_party_is_walked_in_list_order_on_every_title(key):
    row, mem = ap.ROWS[key], Memory()
    addrs = lay_party(mem, row, THREE, items=(2, 0, 3), effects=(1, 2, 0))
    party = ap.walk(mem.read, row, BASE)
    assert [m.address for m in party] == addrs
    assert [(m.name, m.hp, m.hp_max) for m in party] == [
        ("ALDRIC", 12, 20), ("BRYNNA", 7, 7), ("COSIMO", 0, 9)]
    assert [len(m.items()) for m in party] == [2, 0, 3]
    assert [len(m.effects()) for m in party] == [1, 2, 0]
    assert [node[0] for _, node in party[2].items()] == [0xA0, 0xA1, 0xA2]
    assert all(len(node) == row.items.size for _, node in party[0].items())


def test_pools_of_darkness_links_through_the_records_first_longword():
    row = ap.ROWS["pools-of-darkness"]
    assert row.next_offset == 0
    mem = Memory()
    addrs = lay_party(mem, row, THREE)
    assert int.from_bytes(mem.read(addrs[0], 4), "big") == addrs[1]
    assert [m.name for m in ap.walk(mem.read, row, BASE)] == [
        "ALDRIC", "BRYNNA", "COSIMO"]


def test_an_empty_list_is_an_empty_party():
    row, mem = ap.ROWS["curse-of-the-azure-bonds"], Memory()
    assert ap.walk(mem.read, row, BASE) == ()


def test_a_list_that_comes_back_on_itself_is_refused():
    row, mem = ap.ROWS["secret-of-the-silver-blades"], Memory()
    addrs = lay_party(mem, row, THREE)
    mem.long(addrs[2] + row.next_offset, addrs[0])
    with pytest.raises(ap.PartyError, match="comes back to"):
        ap.walk(mem.read, row, BASE)


def test_a_pointer_in_the_targets_measured_memory_is_not_outside_it():
    row, mem = ap.ROWS["pool-of-radiance"], Memory()
    lay_party(mem, row, THREE)
    mem.long(BASE + row.head, 0x00F00000)

    class Target(amiga.AmigaTarget):
        def __init__(self):
            self.memory = ((0x00F00000, 0x1000),)

        def read_blocks(self, blocks):
            return [mem.read(a, n) for a, n in blocks]

    with pytest.raises(Exception) as caught:
        ap.walk(Target(), row, BASE)
    assert "outside the Amiga's memory" not in str(caught.value)


def test_an_odd_pointer_is_refused():
    row, mem = ap.ROWS["pool-of-radiance"], Memory()
    addrs = lay_party(mem, row, THREE)
    mem.long(addrs[0] + row.next_offset, addrs[1] + 1)
    with pytest.raises(ap.PartyError, match="odd address"):
        ap.walk(mem.read, row, BASE)


def test_a_pointer_outside_memory_is_refused_before_it_is_read():
    row, mem = ap.ROWS["pool-of-radiance"], Memory()
    lay_party(mem, row, THREE)
    mem.long(BASE + row.head, 0x00F00000)
    with pytest.raises(ap.PartyError, match="outside the Amiga's memory"):
        ap.walk(mem.read, row, BASE)


def test_a_list_that_never_ends_is_refused():
    row, mem = ap.ROWS["curse-of-the-azure-bonds"], Memory()
    lay_party(mem, row, [(b"X%d" % i, 1, 1) for i in range(ap.MAX_RECORDS + 1)],
              slots=[8] * (ap.MAX_RECORDS + 1))
    with pytest.raises(ap.PartyError, match="not ended after 64"):
        ap.walk(mem.read, row, BASE)


def test_in_a_fight_the_monsters_after_the_party_are_not_members():
    mem = Memory()
    key = "secret-of-the-silver-blades"
    row = ap.ROWS[key]
    lay_party(mem, row, THREE + [(b"DRAGON", 88, 88)] * 2,
              slots=[0, 1, 2, 8, 8])
    records = ap.walk(mem.read, row, BASE)
    assert [m.in_party for m in records] == [True] * 3 + [False] * 2
    assert [m.name for m in ap.read_party(target_for(key, mem))] == [
        "ALDRIC", "BRYNNA", "COSIMO"]


def test_more_than_eight_members_is_not_a_party():
    mem = Memory()
    key = "curse-of-the-azure-bonds"
    lay_party(mem, ap.ROWS[key], [(b"X%d" % i, 1, 1) for i in range(9)],
              slots=[i % 8 for i in range(9)])
    assert ap.read_party(target_for(key, mem)) is None


def test_an_item_chain_that_loops_is_refused():
    row, mem = ap.ROWS["curse-of-the-azure-bonds"], Memory()
    lay_party(mem, row, THREE, items=(2, 0, 0))
    party = ap.walk(mem.read, row, BASE)
    first, second = (a for a, _ in party[0].items())
    mem.long(second + row.items.link, first)
    with pytest.raises(ap.PartyError, match="item list comes back"):
        ap.walk(mem.read, row, BASE)


def test_comparable_blanks_the_pointers_and_nothing_else():
    row = ap.ROWS["curse-of-the-azure-bonds"]
    raw = bytes(range(256)) * 2
    blank = ap.comparable(raw, row)
    assert len(blank) == row.record_size
    pointer_bytes = {p + i for p in row.pointers for i in range(4)}
    for at in range(row.record_size):
        assert blank[at] == (0 if at in pointer_bytes else raw[at])


@pytest.mark.parametrize("key", sorted(ap.ROWS))
def test_every_pointer_named_in_a_row_is_a_longword_inside_the_record(key):
    row = ap.ROWS[key]
    for at in (row.next_offset, row.items.head, row.effects.head):
        assert at in row.pointers
    assert all(p % 2 == 0 and p + 4 <= row.record_size for p in row.pointers)
    for spot in (row.hp, row.hp_max, row.memorised, row.quickfight):
        assert all(not (p <= spot.offset < p + 4) for p in row.pointers)


def test_the_record_sizes_are_the_codecs_record_sizes():
    sizes = {k: r.record_size for k, r in ap.ROWS.items()}
    assert sizes == {
        "pool-of-radiance": amiga_por.AMIGA_POR_RECORD_SIZE,
        "curse-of-the-azure-bonds": amiga_port.CURSE_DELTAS.record_size,
        "secret-of-the-silver-blades":
            amiga_port.SILVER_BLADES_DELTAS.record_size,
        "pools-of-darkness": amiga_pod.RECORD_BYTES,
    }


def test_there_is_one_row_per_title_the_automapper_knows():
    assert set(ap.ROWS) == set(amiga.MACHINES)
    for key, row in ap.ROWS.items():
        assert row.title == amiga.MACHINES[key].title


FOUR = {"heal", "store-spells", "restore-spells", "identify"}


def test_only_the_writes_seen_on_screen_and_kept_over_a_step_are_confirmed():
    # The R2, R3 and gap-run measurements in docs/96, "Which writes are proven".
    assert {k: r.confirmed for k, r in ap.ROWS.items()} == {
        "pool-of-radiance": FOUR,
        "curse-of-the-azure-bonds": FOUR,
        "secret-of-the-silver-blades": FOUR,
        "pools-of-darkness": FOUR,
    }


def test_the_measured_facts_are_the_ones_read_off_a_running_game():
    # hp_max: seen on the sheet and kept over a step; combat_value: the mode
    # byte read in a fight. Curse has no fight read; Pool's sheet shows no
    # maximum; Curse's and Silver Blades' maxima were not re-read after a
    # step.
    assert {k: r.measured for k, r in ap.ROWS.items()} == {
        "pool-of-radiance": {"combat_value"},
        "curse-of-the-azure-bonds": set(),
        "secret-of-the-silver-blades": {"combat_value"},
        "pools-of-darkness": {"hp_max", "combat_value"},
    }


def test_no_action_is_proven_safe_in_a_fight():
    for row in ap.ROWS.values():
        assert row.combat_legal == frozenset()
        assert row.combat_value == 5


def test_the_confirmed_fields_are_the_measured_offsets():
    measured = {
        "pool-of-radiance": dict(hp=(0x11D, 1, 0xFF), memorised=(0x17, 21),
                                 hidden=(0x35, 1, 0x07)),
        "curse-of-the-azure-bonds": dict(
            hp=(0x1A9, 1, 0xFF), hp_max=(0x78, 1, 0xFF), memorised=(0x1E, 84),
            hidden=(0x36, 1, 0x07)),
        "secret-of-the-silver-blades": dict(
            hp=(0x152, 1, 0xFF), hp_max=(0x70, 1, 0xFF), memorised=(0x1E, 75),
            hidden=(0x36, 1, 0x07)),
        "pools-of-darkness": dict(
            hp=(0x191, 1, 0xFF), hp_max=(0x81, 1, 0xFF),
            memorised=(0xCC, 141), hidden=(0x36, 1, 0x07)),
    }
    for key, fields in measured.items():
        row = ap.ROWS[key]
        for name, want in fields.items():
            spot = getattr(row, name)
            assert (spot.offset, spot.length, spot.mask)[:len(want)] == want, (
                key, name)
    modes = {k: r.mode for k, r in ap.ROWS.items()}
    assert modes == {"pool-of-radiance": 0xBA,
                     "curse-of-the-azure-bonds": 0x3D56,
                     "secret-of-the-silver-blades": 0x525C,
                     "pools-of-darkness": 0x5B12}


def target_for(key: str, mem: Memory, data_base=BASE):
    return SimpleNamespace(layout=amiga.MACHINES[key], data_base=data_base,
                           read=mem.read)


def test_row_for_finds_the_title_through_a_forwarding_wrapper():
    mem = Memory()
    tgt = target_for("secret-of-the-silver-blades", mem)
    assert ap.row_for(tgt) is ap.ROWS["secret-of-the-silver-blades"]
    assert ap.row_for(SimpleNamespace(target=tgt, read=mem.read)) is (
        ap.ROWS["secret-of-the-silver-blades"])
    assert ap.row_for(SimpleNamespace(layout=None)) is None
    assert ap.row_for(None) is None


def test_mode_reads_the_rows_byte_and_is_none_before_locate():
    mem = Memory()
    row = ap.ROWS["pools-of-darkness"]
    mem.put(BASE + row.mode, b"\x05")
    assert ap.mode(target_for("pools-of-darkness", mem)) == 5
    assert ap.mode(target_for("pools-of-darkness", mem, None)) is None


def test_read_party_returns_the_members_or_none():
    mem = Memory()
    key = "curse-of-the-azure-bonds"
    tgt = target_for(key, mem)
    assert ap.read_party(tgt) is None                # nothing loaded yet
    lay_party(mem, ap.ROWS[key], THREE)
    assert [m.name for m in ap.read_party(tgt)] == ["ALDRIC", "BRYNNA",
                                                    "COSIMO"]
    assert ap.read_party(target_for(key, mem, None)) is None


@pytest.mark.parametrize("people", [
    [(b"ALDRIC", 30, 20)],                           # more hp than maximum
    [(b"\x01\x02", 1, 1)],                           # not a name
    [(b"", 1, 1)],                                   # no name
])
def test_read_party_is_none_for_a_record_that_is_not_a_character(people):
    mem = Memory()
    key = "pool-of-radiance"
    lay_party(mem, ap.ROWS[key], people)
    assert ap.read_party(target_for(key, mem)) is None


def test_read_party_is_none_rather_than_raising_on_a_broken_list():
    mem = Memory()
    key = "pool-of-radiance"
    row = ap.ROWS[key]
    addrs = lay_party(mem, row, THREE)
    mem.long(addrs[1] + row.next_offset, addrs[0])
    assert ap.read_party(target_for(key, mem)) is None


def test_a_members_spans_are_read_at_the_rows_spots():
    mem = Memory()
    key = "secret-of-the-silver-blades"
    row = ap.ROWS[key]
    addrs = lay_party(mem, row, THREE)
    mem.put(addrs[1] + row.memorised.offset, bytes(range(1, 6)))
    mem.put(addrs[1] + row.quickfight.offset, b"\x01")
    party = ap.walk(mem.read, row, BASE)
    assert party[1].memorised()[:6] == bytes([1, 2, 3, 4, 5, 0])
    assert len(party[1].memorised()) == row.memorised.length
    assert [m.quickfight for m in party] == [False, True, False]


def test_a_monster_with_a_bad_item_pointer_does_not_spoil_the_party():
    mem = Memory()
    key = "curse-of-the-azure-bonds"
    row = ap.ROWS[key]
    addrs = lay_party(mem, row, THREE + [(b"TROLL", 30, 30)],
                      slots=[0, 1, 2, 8])
    mem.long(addrs[3] + row.items.head, 0x00F00001)
    mem.long(addrs[3] + row.effects.head, addrs[3])
    records = ap.walk(mem.read, row, BASE)
    assert records[3].items() == () and records[3].effects() == ()
    assert [m.name for m in ap.read_party(target_for(key, mem))] == [
        "ALDRIC", "BRYNNA", "COSIMO"]


def test_a_members_bad_item_pointer_still_spoils_the_party():
    mem = Memory()
    key = "curse-of-the-azure-bonds"
    row = ap.ROWS[key]
    addrs = lay_party(mem, row, THREE)
    mem.long(addrs[1] + row.items.head, 0x00F00000)
    with pytest.raises(ap.PartyError, match="member 2's item list"):
        ap.walk(mem.read, row, BASE)
    assert ap.read_party(target_for(key, mem)) is None


def test_the_lists_are_read_a_level_at_a_time():
    mem = Memory()
    key = "secret-of-the-silver-blades"
    row = ap.ROWS[key]
    lay_party(mem, row, THREE, items=(2, 0, 3), effects=(1, 2, 0))
    party = ap.walk(mem, row, BASE)
    # the head, one per record, then one per level of the deepest list (3)
    assert mem.trips == 1 + 3 + 3 and mem.reads == 0
    single = Memory()
    lay_party(single, row, THREE, items=(2, 0, 3), effects=(1, 2, 0))
    alone = SimpleNamespace(read=single.read)
    assert ap.walk(alone, row, BASE) == party
    assert single.reads == 1 + 3 + 8 and single.trips == 0


def test_read_party_batches_through_a_targets_read_blocks():
    mem = Memory()
    key = "pool-of-radiance"
    lay_party(mem, ap.ROWS[key], THREE, items=(1, 1, 1))
    tgt = SimpleNamespace(layout=amiga.MACHINES[key], data_base=BASE,
                          read=mem.read, read_blocks=mem.read_blocks)
    assert len(ap.read_party(tgt)) == 3
    assert mem.trips == 1 + 3 + 1 and mem.reads == 0


@pytest.mark.parametrize("members", [3, 8])
def test_the_party_is_exactly_the_members_before_twenty_monsters(members):
    mem = Memory()
    key = "secret-of-the-silver-blades"
    people = [(b"HERO%d" % i, 5, 5) for i in range(members)]
    lay_party(mem, ap.ROWS[key], people + [(b"ORC", 6, 6)] * 20,
              slots=list(range(members)) + [8] * 20)
    party = ap.read_party(target_for(key, mem))
    assert [m.name for m in party] == [f"HERO{i}" for i in range(members)]
    assert len(ap.walk(mem.read, ap.ROWS[key], BASE)) == members + 20


def test_an_item_list_that_never_ends_is_refused():
    mem = Memory()
    row = ap.ROWS["pools-of-darkness"]
    lay_party(mem, row, THREE, items=(ap.MAX_NODES + 1, 0, 0))
    with pytest.raises(ap.PartyError,
                       match=f"item list has not ended after {ap.MAX_NODES}"):
        ap.walk(mem.read, row, BASE)
    mem2 = Memory()
    lay_party(mem2, row, THREE, items=(ap.MAX_NODES, 0, 0))
    assert len(ap.walk(mem2.read, row, BASE)[0].items()) == ap.MAX_NODES


def test_a_record_that_runs_past_the_end_of_memory_is_refused():
    mem = Memory()
    row = ap.ROWS["curse-of-the-azure-bonds"]
    lay_party(mem, row, THREE)
    straddle = SLOW + 0x80000 - 0x10
    mem.long(BASE + row.head, straddle)
    with pytest.raises(ap.PartyError, match="outside the Amiga's memory"):
        ap.walk(mem.read, row, BASE)
    chip_end = CHIP + 0x80000 - row.record_size + 2
    mem.long(BASE + row.head, chip_end)
    with pytest.raises(ap.PartyError, match="outside the Amiga's memory"):
        ap.walk(mem.read, row, BASE)


def test_records_in_chip_memory_are_walked():
    # Pool of Radiance's records are in chip memory under Kickstart 2.04.
    mem = Memory()
    key = "pool-of-radiance"
    addrs = lay_party(mem, ap.ROWS[key], THREE, items=(2, 1, 0),
                      heap=0x04E800)
    assert addrs[0] < 0x80000
    party = ap.read_party(target_for(key, mem))
    assert [m.address for m in party] == addrs
    assert [len(m.items()) for m in party] == [2, 1, 0]


@pytest.mark.parametrize("people,slots", [
    ([(b"   ", 1, 1)] + THREE[1:], None),               # a blank name
    (THREE, [0, 1, 1]),                                 # two in one slot
])
def test_read_party_is_none_for_a_blank_name_or_a_shared_slot(people, slots):
    mem = Memory()
    key = "curse-of-the-azure-bonds"
    lay_party(mem, ap.ROWS[key], people, slots=slots)
    assert ap.read_party(target_for(key, mem)) is None


# -- the card fields ---------------------------------------------------------

#: Per title, the C0 offsets written out literally rather than read from the
#: module: levels, former levels, level byte, experience, AC byte, THAC0 byte.
CARD_OFFSETS = {
    "pool-of-radiance": (0x098, None, 0x073, 0x0AE, 0x113, 0x112),
    "curse-of-the-azure-bonds": (0x10A, 0x112, 0x0E5, 0x128, 0x19F, 0x19E),
    "secret-of-the-silver-blades": (0x0AC, 0x0B3, 0x088, 0x0C8, 0x148, 0x147),
    "pools-of-darkness": (0x09D, 0x0A4, 0x089, 0x044, 0x187, 0x186),
}


def member_with(key: str, **put) -> ap.AmigaMember:
    row = ap.ROWS[key]
    raw = bytearray(row.record_size)
    for at, value in put.items():
        raw[int(at[1:], 16)] = value
    return ap.AmigaMember(row=row, index=0, address=HEAP, raw=bytes(raw))


@pytest.mark.parametrize("key", sorted(CARD_OFFSETS))
def test_a_card_reads_class_level_experience_ac_and_thac0(key):
    levels, _former, level, exp, ac, thac0 = CARD_OFFSETS[key]
    put = {f"o{levels + 2:x}": 7,        # fighter slot
           f"o{levels + 6:x}": 8,        # thief slot
           f"o{level:x}": 8,
           f"o{exp + 3:x}": 0x10, f"o{exp + 2:x}": 0x27,
           f"o{ac:x}": 53, f"o{thac0:x}": 47}
    fields = ap.card_fields(member_with(key, **put))
    assert fields.classes == (("fighter", 7), ("thief", 8))
    assert fields.level == 8
    assert fields.experience == 10000
    assert fields.armour_class == 7
    assert fields.thac0 == 13


def test_a_class_is_named_from_its_slot_not_from_class_bits():
    # Silver Blades' paladin and ranger share class_bits 0x40; the slots differ.
    levels = CARD_OFFSETS["secret-of-the-silver-blades"][0]
    paladin = ap.card_fields(member_with(
        "secret-of-the-silver-blades", **{f"o{levels + 3:x}": 5, "o6c": 0x40}))
    ranger = ap.card_fields(member_with(
        "secret-of-the-silver-blades", **{f"o{levels + 4:x}": 5, "o6c": 0x40}))
    assert paladin.classes == (("paladin", 5),)
    assert ranger.classes == (("ranger", 5),)


@pytest.mark.parametrize("key", ["curse-of-the-azure-bonds",
                                 "secret-of-the-silver-blades",
                                 "pools-of-darkness"])
def test_a_dual_class_slot_adds_its_former_level_as_the_sheet_does(key):
    levels, former = CARD_OFFSETS[key][:2]
    fields = ap.card_fields(member_with(
        key, **{f"o{levels + 6:x}": 3, f"o{former + 6:x}": 4}))
    assert fields.classes == (("thief", 7),)
