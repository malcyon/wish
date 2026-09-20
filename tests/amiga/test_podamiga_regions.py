from __future__ import annotations

"""The tail of an Amiga Pools of Darkness `.pc`: the items and the effects.

`goldbox.amiga_pod` walks both regions in the reader and builds both in the
writer, so a character crossing between the ports keeps what he is carrying
and what is running on him. This is the proof of it.

What is tested, hardest evidence first.

* **The encumbrance identity**, which is the engine's own arithmetic and puts
  the item stride, the weight offset and the byte order into one sum:
  `money + Σ(weight × max(quantity, 1))` against the big-endian word at record
  `0x056`, on every `.pc` an Amiga disk here holds.
* **The tail is exactly consumed**: `404 + 20 × items + 20 × scroll nodes +
  10 × effects` is the file's own length, with no remainder, walking the
  effect chain the way the loader walks it rather than by what is left over.
* **The conversion runs to the other port**: a `.pc` read into the neutral
  record and written back out as DOS bytes produces a `.THG` with the
  character's own items in it, checked field by field against the `.pc`.
* **And back into a `.pc`**: every item the game wrote is rebuilt byte for
  byte, and an effect node but for the byte nothing reads and the chain
  pointer the loader overwrites.
* **The empty and the odd case**, neither of which any genuine file is: a
  record with no items and no effects, and a scroll, whose own `quantity`
  further twenty-byte nodes the loader reads before the next item.

**The specimens are the `Save/*.pc` files on the player's own Amiga disk
images**, read at run time through `gamedisks.yaml`; everything here skips
without them, which is what CI does. Twelve are on Pools of Darkness disk 3
and seven more are on alternate rips, so a count here is the smallest number
the claim is made at rather than a total.
"""

import pytest
from support.podamiga import pc_bytes

from goldbox import amiga_pod, dos_codec, dos_port

#: Money the `.pc` holds, which is the other half of the encumbrance identity.
PURSES = (amiga_pod.PLATINUM, amiga_pod.GEMS, amiga_pod.JEWELRY)


def pc_records() -> list[tuple[str, bytes]]:
    found = pc_bytes()
    if not found:
        pytest.skip("no Amiga Pools of Darkness .pc files; set $AMIGA_DISKS")
    return sorted(found.items())


def a_record(items: list[bytes] = [], effects: list[bytes] = [],
             count: int | None = None) -> bytes:
    """A synthetic `.pc`: 404 zero bytes, then whatever is asked for.

    Built from the documented format rather than cut out of a game file, so
    the cases no genuine record carries can be tested at all.
    """
    raw = bytearray(amiga_pod.RECORD_BYTES)
    raw[amiga_pod.ITEM_CHAIN:amiga_pod.ITEM_CHAIN + 4] = (
        len(items) if count is None else count).to_bytes(4, "big")
    if effects:
        raw[amiga_pod.EFFECT_CHAIN:amiga_pod.EFFECT_CHAIN + 4] = (
            (0x24B946).to_bytes(4, "big"))
    return bytes(raw) + b"".join(items) + b"".join(effects)


def an_item(**fields: int) -> bytes:
    """Twenty bytes with the named DOS item fields in them."""
    raw = bytearray(amiga_pod.ITEM_FILE_SIZE)
    for name, value in fields.items():
        f = amiga_pod.ITEM_FIELDS[name]
        at = amiga_pod.ITEM_FIELD_AT[name]
        raw[at:at + f.size] = value.to_bytes(f.size, "big")
    return bytes(raw)


def an_effect(effect_id: int, duration: int = 0, following: int = 0) -> bytes:
    """One ten-byte node, in the form all eleven genuine ones have."""
    return (bytes((effect_id, 0)) + duration.to_bytes(2, "big")
            + b"\xff\x00" + following.to_bytes(4, "big"))


# --- the regions, against the files the game itself wrote --------------------

def test_the_twenty_bytes_are_the_later_amiga_item_node():
    """Every item on the disks decodes in range, and the three insertions
    the constructor never writes are zero in all of them.

    A wrong offset inside the node shows here as a `readied` that is not a
    flag, a `plus` outside 1-6 or a pad that is not zero; on this machine it
    is 93 items in 19 files and none of them fails.
    """
    files = items = 0
    for name, data in pc_records():
        char = amiga_pod.PodCharacter.from_bytes(data)
        for item in char.items:
            assert item.get("readied") in (0, 1), (name, item.raw.hex(" "))
            assert item.get("hidden") == 0, name
            assert item.get("cursed") == 0, name
            assert 1 <= item.get("plus") <= 6, (name, item.get("plus"))
            assert 0 < item.type_index < 120, (name, item.type_index)
            assert item.pads == (0, 0, 0), (name, item.pads)
            items += 1
        files += 1
    assert files >= 12, files
    assert items >= 59, items


def test_the_encumbrance_identity_balances_for_every_record():
    """`money + Σ(weight × max(quantity, 1))` is the stored word at 0x056.

    The engine's own arithmetic, and the one check that fixes the item
    stride, the weight offset and the byte order together: 19 of 19 records
    on this machine balance exactly, at three distinct totals -- 601 for the
    four-item pregens, 960 for most of the twelve and 371 for `T.pc`.
    """
    seen = 0
    for name, data in pc_records():
        char = amiga_pod.PodCharacter.from_bytes(data)
        carried = sum(item.weight * max(item.quantity, 1)
                      for item in char.items)
        money = sum(int.from_bytes(data[at:at + 2], "big") for at in PURSES)
        assert money + carried == char.encumbrance, (
            name, money, carried, char.encumbrance)
        seen += 1
    assert seen >= 12, seen


def test_the_tail_is_exactly_consumed():
    """`404 + 20 × items + 20 × scrolls + 10 × effects` is the file's length.

    The effects are walked by the chain -- the head at 0x004, then each
    node's own `next` -- which is what the loader does, so this is not the
    same claim as "whatever is left over divides by ten".
    """
    seen = effects = 0
    for name, data in pc_records():
        char = amiga_pod.PodCharacter.from_bytes(data)
        spent = (amiga_pod.RECORD_BYTES
                 + amiga_pod.ITEM_FILE_SIZE * len(char.items)
                 + amiga_pod.ITEM_FILE_SIZE * len(char.scroll_nodes)
                 + amiga_pod.EFFECT_FILE_SIZE * len(char.effects))
        assert spent == len(data), (name, spent, len(data))
        assert bool(char.effects) == bool(
            int.from_bytes(data[amiga_pod.EFFECT_CHAIN:
                                amiga_pod.EFFECT_CHAIN + 4], "big")), name
        effects += len(char.effects)
        seen += 1
    assert seen >= 12, seen
    assert effects >= 7, effects


def test_every_effect_node_is_the_payload_dos_holds():
    """`<id> ?? 00 00 FF 00`, which is `INNATE_PAYLOAD` with the Amiga's own
    unnamed byte at 1 -- 11 of 11 nodes here, and the ids are ones DOS Pools
    of Darkness holds for the same kind of character.
    """
    nodes = 0
    for name, data in pc_records():
        for node in amiga_pod.PodCharacter.from_bytes(data).effects:
            assert node[amiga_pod.EFFECT_DURATION:
                        amiga_pod.EFFECT_DURATION + 2] == b"\0\0", name
            assert node[4:6] == b"\xff\x00", (name, node.hex(" "))
            recut = amiga_pod.pod_effect_to_dos(node)
            assert recut[1:] == dos_codec.INNATE_PAYLOAD + bytes(4), name
            assert recut[0] == node[0], name
            nodes += 1
    assert nodes >= 7, nodes


# --- what a converted character now arrives with -----------------------------

def test_a_character_read_off_an_amiga_disk_arrives_in_dos_with_his_items():
    """The loss this half of `#462` was open for: `pod_to_neutral` walks the
    item region, so `dos_codec.write` builds a `.THG` with his own items.

    Checked field by field against the `.pc` rather than by counting: the
    type index, the plus, the weight, the quantity and the value of every
    item, through the sixteen-byte projection both ports share.
    """
    seen = items = 0
    for name, data in pc_records():
        char = amiga_pod.PodCharacter.from_bytes(data)
        out = amiga_pod.pod_to_neutral(data)
        rec, itm, _spc, _report = dos_codec.write(out)
        back = dos_codec.DosCharacter(rec)
        assert back.get("item_count") == len(char.items), name
        assert len(itm) == len(char.items) * dos_port.ITEM_SIZE, name
        for n, item in enumerate(char.items):
            written = itm[n * dos_port.ITEM_SIZE:(n + 1) * dos_port.ITEM_SIZE]
            for field in ("type_index", "plus", "weight", "quantity", "value",
                          "readied", "charges", "effect", "power"):
                f = dos_port.ITEM_FIELDS_BY_NAME[field]
                got = int.from_bytes(written[f.offset:f.offset + f.size],
                                     "little", signed=f.kind.name == "I8")
                assert got == item.get(field), (name, n, field, got)
            items += 1
        seen += 1
    assert seen >= 12, seen
    assert items >= 59, items


def test_a_character_with_a_running_effect_arrives_with_it():
    """The effect chain reaches `granted_effects` and then the DOS `.EFX`
    bytes, id for id, for every `.pc` that has one.

    Everything that never expires goes in whole, because which node is an
    innate property and which a readied item granted cannot be told apart for
    this title -- `innate_effects` is on `pod_read_dropped()` saying exactly
    that.
    """
    seen = 0
    for name, data in pc_records():
        char = amiga_pod.PodCharacter.from_bytes(data)
        out = amiga_pod.pod_to_neutral(data)
        if not char.effects:
            assert out.get("granted_effects") is None, name
            continue
        granted = out.get("granted_effects")
        assert [g[0] for g in granted] == [n[0] for n in char.effects], name
        _rec, _itm, spc, _report = dos_codec.write(out)
        assert [spc[i] for i in range(0, len(spc), 9)] == [
            n[0] for n in char.effects], name
        seen += 1
    assert seen >= 4, seen
    assert "innate_effects" in {n for n, _ in amiga_pod.pod_read_dropped()}


# --- and what the writer builds back out of it -------------------------------

def test_every_item_the_game_wrote_is_written_back_byte_for_byte():
    """The item region read into the neutral record and built again from it,
    node against node: **93 of 93 items on this machine are identical**.

    That is the whole twenty bytes, not the fields a reader happens to name.
    The sixteen-byte projection both ports share carries every one of the
    fifteen DOS item fields the node holds, and the three insertion bytes are
    zero on both sides, so there is nothing in a node for the round trip to
    quietly lose.
    """
    seen = exact = 0
    for name, data in pc_records():
        char = amiga_pod.PodCharacter.from_bytes(data)
        out, _rep = amiga_pod.to_pc(amiga_pod.pod_to_neutral(data))
        at = amiga_pod.RECORD_BYTES
        for n in range(len(char.items)):
            end = at + amiga_pod.ITEM_FILE_SIZE
            assert out[at:end] == data[at:end], (name, n, out[at:end].hex(" "))
            at = end
            exact += 1
        assert int.from_bytes(out[amiga_pod.ITEM_CHAIN:
                                  amiga_pod.ITEM_CHAIN + 4], "big") == len(
            char.items), name
        seen += 1
    assert seen >= 12, seen
    assert exact >= 59, exact


def test_an_effect_node_is_written_back_but_for_the_pad_and_the_pointer():
    """The node's id, duration and payload survive; two things do not, and
    both are named rather than left to the diff.

    The byte at 1 is the one nothing in the engine reads -- non-zero in 7 of
    the 11 nodes the game wrote here -- and there is nowhere in the neutral
    record to hold it. The four-byte `next` is a live Amiga heap address in a
    file the game wrote and a 1 in one this writes: the loader allocates each
    node and overwrites the stored pointer before the read that fills it, so
    what it tests is whether another node follows.
    """
    nodes = 0
    for name, data in pc_records():
        char = amiga_pod.PodCharacter.from_bytes(data)
        if not char.effects:
            continue
        out, _rep = amiga_pod.to_pc(amiga_pod.pod_to_neutral(data))
        at = amiga_pod.RECORD_BYTES + amiga_pod.ITEM_FILE_SIZE * len(
            char.items)
        for n, node in enumerate(char.effects):
            built = out[at:at + amiga_pod.EFFECT_FILE_SIZE]
            assert built[0] == node[0], (name, n)
            assert built[2:6] == node[2:6], (name, n, built.hex(" "))
            assert built[amiga_pod.EFFECT_UNNAMED] == 0, (name, n)
            following = int.from_bytes(built[amiga_pod.EFFECT_NEXT:
                                             amiga_pod.EFFECT_NEXT + 4], "big")
            assert bool(following) == (n + 1 < len(char.effects)), (name, n)
            at += amiga_pod.EFFECT_FILE_SIZE
            nodes += 1
        assert int.from_bytes(out[amiga_pod.EFFECT_CHAIN:
                                  amiga_pod.EFFECT_CHAIN + 4], "big") == \
            amiga_pod.POD_CHAIN_PRESENT, name
    assert nodes >= 7, nodes


def test_a_scroll_is_written_with_the_nodes_the_loader_will_read_after_it():
    """A scroll's own `quantity` further twenty-byte nodes are part of the
    file, so a writer that emitted the item alone would leave the loader
    reading the next item's twenty bytes as a spell node and then running off
    the end of a file it had been told was longer.

    No genuine record carries one, so this is built from the format: a scroll
    of two and an ordinary sword after it. The two chained nodes are written
    empty -- the neutral record has nowhere to hold their spell ids -- and the
    loss is on the report rather than silent.
    """
    record = bytearray(a_record(
        [an_item(type_index=amiga_pod.SCROLL_TYPE_INDEX, quantity=2, weight=1),
         an_item(charges=11, effect=22, power=33),
         an_item(charges=44, effect=55, power=66),
         an_item(type_index=5, plus=2, weight=50, value=1400)], count=2))
    record[:amiga_pod.RECORD_BYTES] = amiga_pod.PodWriter(
        name="SCROLLER",
        character_class=amiga_pod.CLASSES.index("FIGHTER"),
        class_levels=(0, 0, 1, 0, 0, 0, 0),
        class_bits=amiga_pod.CLASS_BIT["fighter"],
    ).to_bytes()[:amiga_pod.RECORD_BYTES]
    record[amiga_pod.ITEM_CHAIN:amiga_pod.ITEM_CHAIN + 4] = (2).to_bytes(
        4, "big")
    out, rep = amiga_pod.to_pc(amiga_pod.pod_to_neutral(bytes(record)))

    assert len(out) == amiga_pod.RECORD_BYTES + 4 * amiga_pod.ITEM_FILE_SIZE
    assert int.from_bytes(out[amiga_pod.ITEM_CHAIN:
                              amiga_pod.ITEM_CHAIN + 4], "big") == 2
    back = amiga_pod.PodCharacter.from_bytes(out)
    assert [it.type_index for it in back.items] == [
        amiga_pod.SCROLL_TYPE_INDEX, 5]
    assert back.items[1].get("value") == 1400
    assert len(back.scroll_nodes) == 2
    assert back.scroll_nodes == (bytes(amiga_pod.ITEM_FILE_SIZE),) * 2
    assert [line for line in rep.dropped if "scroll" in line], rep.dropped
    assert rep.unaccounted(out) == []


# --- the empty case, and the one no genuine record carries -------------------

def test_a_record_with_no_items_and_no_effects_reads_empty():
    """What `PodWriter` itself emits: 484 bytes whose counts are both zero,
    with 80 bytes of zero padding after the record the loader never reads.

    The extreme case on the other side from a full pack, and the one a
    reader that walked the tail by length rather than by count would get
    wrong -- eighty zero bytes divide into four item records exactly.
    """
    raw = amiga_pod.PodWriter(name="TEST").to_bytes()
    assert len(raw) == amiga_pod.RECORD_LENGTH
    char = amiga_pod.PodCharacter.from_bytes(raw)
    assert char.items == ()
    assert char.effects == ()
    out = amiga_pod.pod_to_neutral(raw)
    assert out.get("inventory") == []
    assert out.get("granted_effects") is None
    assert out.dropped == []


def test_a_scroll_carries_its_chained_nodes_and_the_next_item_still_reads():
    """The loader reads a scroll's own `quantity` further twenty-byte nodes
    before the next item, and a reader that did not would take the first of
    them for the item after it.

    No item in the nineteen genuine files is a scroll, so this is built from
    the format: a scroll of two, two chained nodes, and an ordinary sword
    after them.
    """
    scroll = an_item(type_index=amiga_pod.SCROLL_TYPE_INDEX, quantity=2,
                     weight=1, value=100)
    chained = [an_item(charges=11, effect=22, power=33),
               an_item(charges=44, effect=55, power=66)]
    sword = an_item(type_index=5, plus=2, weight=50, quantity=0, value=1400,
                    readied=1)
    data = a_record([scroll] + chained + [sword], count=2)

    char = amiga_pod.PodCharacter.from_bytes(data)
    assert [it.type_index for it in char.items] == [
        amiga_pod.SCROLL_TYPE_INDEX, 5]
    assert char.items[1].get("value") == 1400
    assert char.scroll_nodes == tuple(chained)

    out = amiga_pod.pod_to_neutral(data)
    assert len(out.get("inventory")) == 2
    assert [line for line in out.dropped if "scroll" in line], out.dropped


def test_an_item_count_past_the_end_of_the_file_stops_the_walk():
    """A count that claims more items than the file holds reads what is there
    rather than raising: this title checks no length, so a `.pc` may be short.
    """
    data = a_record([an_item(type_index=5, weight=1)], count=9)
    char = amiga_pod.PodCharacter.from_bytes(data)
    assert len(char.items) == 1
    assert amiga_pod.pod_to_neutral(data).get("inventory") != []


def test_the_effect_walk_stops_where_the_chain_does():
    """Three nodes, the last with a NULL `next`, and ten more bytes after
    them that are not a node: the chain says where to stop, not the length.
    """
    nodes = [an_effect(8, following=0x24B950), an_effect(105, following=1),
             an_effect(47, following=0)]
    data = a_record([], nodes + [bytes(amiga_pod.EFFECT_FILE_SIZE)])
    char = amiga_pod.PodCharacter.from_bytes(data)
    assert [n[0] for n in char.effects] == [8, 105, 47]
