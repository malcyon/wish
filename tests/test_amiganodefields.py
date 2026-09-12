"""`tools/amiganodefields.py`, and the answer it gave `#387`.

`#387 (The Amiga Silver Blades effect node keeps a byte DOS has not got, and
a converted character loses it)` asked what the byte at offset 1 of an Amiga
*Secret of the Silver Blades* effect node holds.  The answer is that no
instruction in either later Amiga title's executable reaches it: the two
routines that build a node write offsets 0, 2-3, 4, 5 and 6-9 by name, the
four that copy one copy all ten bytes without inspecting any, and the pool
the node comes out of is `AllocMem`ed without `MEMF_CLEAR`.  So the byte is
whatever the pool's memory held, and a writer may put anything in it.

Three kinds of test, and the middle one is the finding:

* the tool on a program built here, so its own logic is pinned with no game
  code involved -- including that a displacement nothing reaches is
  **reported as unreached**, which is the assertion the whole finding rests
  on and would be worthless if it could not fail;
* the census against the player's own `/Curse` and `/Secret`, which skips
  when there are no Amiga disks;
* the shape of the byte in every Amiga Curse and Silver Blades saved game on
  this machine: non-zero only in nodes sitting in the first three slots of
  the pool, which is what stale memory looks like and not what a field does.

`docs/202-the-amiga-effect-node-pad.md` is the write-up.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# Below the import for the same reason `tests/test_amigaglobal.py` puts it
# there: capstone is not a declared dependency, so an `importorskip` above
# the module import never runs and every CI job goes red.
pytest.importorskip("capstone")

from tests.test_amiga68k import hunk_file, pad4, u32  # noqa: E402
from tools import amiga68k, amiganodefields  # noqa: E402
from tools.amiga68k import Executable  # noqa: E402

#: The record's chain-head displacement in the program built below, and the
#: node's own `next`, so the numbers in the test are the tool's arguments.
CHAIN, NEXT = 0x96, 0x06

#: Where each title keeps the effect chain in its record, and the effect
#: node pool's descriptor in its small-data segment.  Read with
#: `tools/amigaglobal.py`; `docs/202-the-amiga-effect-node-pad.md` §2.
TITLES = {
    "/Curse": {"disk": "curse", "chain": 0x0F2, "pool": 0x5B1E,
               "constructor": 0x00F176, "allocator": 0x02C5A0},
    "/Secret": {"disk": "silver", "chain": 0x096, "pool": 0x7618,
                "constructor": 0x012DAC, "allocator": 0x02F30E},
}

#: The node is ten bytes and this is the one nothing reaches.
NODE_SIZE, PAD = 10, 1


def chain_walk_program() -> bytes:
    """A chain head loaded, walked, and every node byte but one touched.

    `move.b (a2), d0` is offset 0, `move.w $2(a2), d1` the duration, `move.b
    $5(a2), d2` the flag and `movea.l $6(a2), a2` the walk -- and nothing
    names offset 1, offset 3, offset 4 or offsets 7 to 9.  The decoy at the
    end reads `$1(a3)` through a register that never held a node, so a census
    that reported it would be reporting any `$1(aN)` in the binary rather
    than a node's.
    """
    code = bytearray()
    code += b"\x24\x6e\x00\x96"                  # 0:  movea.l $96(a6), a2
    code += b"\x10\x12"                          # 4:  move.b (a2), d0
    code += b"\x32\x2a\x00\x02"                  # 6:  move.w $2(a2), d1
    code += b"\x14\x2a\x00\x05"                  # 10: move.b $5(a2), d2
    code += b"\x24\x6a\x00\x06"                  # 14: movea.l $6(a2), a2
    code += b"\x66\xf0"                          # 18: bne.b -16
    code += b"\x16\x2b\x00\x01"                  # 20: move.b $1(a3), d3
    code += b"\x4e\x75"                          # 24: rts
    code = pad4(bytes(code))
    data = bytearray(b"\x4e\xf9" + u32(0))
    data += b"\0" * (0x7FFE + 8 - len(data))
    return hunk_file([
        (amiga68k.HUNK_CODE, code, []),
        (amiga68k.HUNK_DATA, pad4(bytes(data)), [(0, [2])]),
    ])


def census(exe: Executable, chain: int = CHAIN) -> dict[int, list]:
    """`{offset: [(width, writes, count)]}` from the tool's own report."""
    heads = amiganodefields.sites(
        exe, __import__("re").compile(rf"(?<!-)\${chain:x}\(a[0-7]\)"))
    out: dict[int, list] = {}
    for ins in heads:
        walked = amiganodefields.walk(exe, ins.address, chain, NEXT)
        for (offset, width, writes), where in walked["displacements"].items():
            out.setdefault(offset, []).append((width, writes, len(where)))
    return out


# ---------------------------------------------------------------------------
# The tool on a program built here
# ---------------------------------------------------------------------------

def test_every_node_byte_the_program_names_is_reported_at_its_width():
    exe = Executable.parse(chain_walk_program())
    found = census(exe)
    assert sorted(found) == [0, 2, 5, 6]
    assert [w for w, _, _ in found[0]] == [1]
    assert [w for w, _, _ in found[2]] == [2]
    assert [w for w, _, _ in found[6]] == [4]


def test_a_node_byte_nothing_names_is_reported_as_unreached():
    """The assertion the whole finding rests on, made to fail on purpose.

    The program above touches offset 5 and not offset 1.  A census that
    could not tell those apart would answer `#387` by construction.
    """
    exe = Executable.parse(chain_walk_program())
    found = census(exe)
    assert PAD not in found
    assert 5 in found


def test_a_displacement_1_read_through_a_register_that_never_held_a_node_is_not_counted():
    """The decoy at the end of the program: `$1(a3)`, a3 never a node.

    This is the difference between the search that answered `#387` and the
    one that found nothing before it -- grepping the binary for `$1(aN)`
    reports 81 sites in `/Secret`, none of which is a node.
    """
    exe = Executable.parse(chain_walk_program())
    at = exe.by_number(0).file_offset
    walked = amiganodefields.walk(exe, at, CHAIN, NEXT)
    assert all(offset != PAD
               for offset, _, _ in walked["displacements"])
    # The decoy really is in the program, so the test is not passing on an
    # instruction that is not there.
    hits = amiganodefields.sites(
        exe, __import__("re").compile(r"(?<!-)\$1\(a[0-7]\)"))
    assert at + 20 in [h.address for h in hits]


def test_the_walk_reaches_a_node_the_second_time_round_a_loop():
    """A `bne` back to the top is how every chain in these games is walked.

    The reads sit *above* the `movea.l $6(a2), a2` that makes the next node,
    so a single forward pass sees them only for the head.  The fixed point
    is what makes the census a statement about every node in the chain.
    """
    exe = Executable.parse(chain_walk_program())
    at = exe.by_number(0).file_offset
    once = amiganodefields.walk(exe, at, CHAIN, NEXT, passes=1)
    twice = amiganodefields.walk(exe, at, CHAIN, NEXT, passes=3)
    assert len(twice["displacements"]) >= len(once["displacements"])
    assert {0, 2, 5, 6} <= {o for o, _, _ in twice["displacements"]}


def test_a_write_is_told_from_a_read():
    assert amiganodefields.is_write("move.l", "-$4(a5), $96(a3)", "a3")
    assert not amiganodefields.is_write("move.l", "$96(a3), a2", "a3")
    assert amiganodefields.is_write("clr.l", "$6(a0)", "a0")
    assert not amiganodefields.is_write("tst.l", "$6(a0)", "a0")
    assert not amiganodefields.is_write("cmpi.b", "#$49, $2e(a2)", "a2")
    assert amiganodefields.width_of("move.b") == 1
    assert amiganodefields.width_of("move.w") == 2
    assert amiganodefields.width_of("move.l") == 4
    assert amiganodefields.width_of("rts") is None


# ---------------------------------------------------------------------------
# The census against the player's own executables
# ---------------------------------------------------------------------------

def _executable(name: str) -> Executable:
    """One later Amiga title's executable off whichever disk carries it."""
    from goldbox.amiga_adf import AmigaDisk
    from tools import gamedisks
    want = TITLES[name]["disk"]
    for root in gamedisks.candidates("amiga"):
        if not root.is_dir():
            continue
        for image in sorted(root.rglob("*.adf")):
            if want not in image.name.lower().replace("_", ""):
                continue
            try:
                return Executable.parse(AmigaDisk.open(image).read_file(name))
            except Exception:
                continue
    pytest.skip(f"no Amiga disk carrying {name}; set $AMIGA_DISKS")


@pytest.mark.parametrize("name", sorted(TITLES))
def test_no_instruction_in_either_title_reaches_the_effect_node_pad(name):
    """`#387`'s answer, taken off the player's own disk.

    Everything downstream of every load of the record's chain head, to a
    fixed point: offsets 0, 2, 4 and 6 are read, 2 and 6 are written, and
    **nothing at all reaches offset 1**.  Offsets 3, 5, 7, 8 and 9 are not
    reached either at their own displacement -- 3 is the low half of the
    duration word, 5 is read in the removal routine which takes its node as
    an argument rather than off a chain, and 7 to 9 are the tail of the
    `next` pointer.
    """
    exe = _executable(name)
    found = census(exe, TITLES[name]["chain"])
    assert PAD not in found, f"{name} reaches the pad at offset {PAD}"
    assert {0, 2, 4, 6} <= set(found), found


@pytest.mark.parametrize("name", sorted(TITLES))
def test_the_effect_pool_hands_out_ten_byte_slots_and_never_clears_one(name):
    """Every birth of an effect-node pointer, counted.

    A pool descriptor is named by exactly one instruction per allocation or
    free, so the references to it are the complete list of sites that can
    put a node pointer in a register.  Curse has ten and Silver Blades
    eleven, every one of which asks for `#$a` = 10 bytes, and one of each is
    the descriptor's own set-up.
    """
    exe = _executable(name)
    lines = amiganodefields.report_pool(exe, TITLES[name]["pool"])
    calls = [ln for ln in lines[1:] if "pea.l" in ln]
    assert calls, lines
    assert all("size #$a" in ln for ln in calls), lines
    setup = [ln for ln in lines[1:] if "move.w" in ln]
    assert len(setup) == 1, lines
    allocator = f"{TITLES[name]['allocator']:06x}"
    assert any(allocator in ln for ln in calls), lines


@pytest.mark.parametrize("name", sorted(TITLES))
def test_the_node_constructor_writes_every_byte_but_the_pad(name):
    """The five stores at the end of the constructor, by their bytes.

    `/Curse` `0x00F176` and `/Secret` `0x012DAC` are the same routine
    compiled twice: allocate ten bytes, append to the tail of the chain,
    then `clr.l $6(a0)`, `move.b <arg>, (a0)`, `move.w <arg>, $2(a0)`,
    `move.b <arg>, $5(a0)` and `move.b <arg>, $4(a0)`.  Five arguments and
    no sixth, so there is nothing an effect could put at offset 1.
    """
    exe = _executable(name)
    at = TITLES[name]["constructor"]
    body = exe.data[at:at + 0x80]
    stores = [
        b"\x42\xa8\x00\x06",                    # clr.l   $6(a0)
        b"\x10\xad\x00\x0d",                    # move.b  $d(a5), (a0)
        b"\x31\x6d\x00\x0e\x00\x02",            # move.w  $e(a5), $2(a0)
        b"\x11\x6d\x00\x13\x00\x05",            # move.b  $13(a5), $5(a0)
        b"\x11\x6d\x00\x11\x00\x04",            # move.b  $11(a5), $4(a0)
    ]
    for store in stores:
        assert store in body, (name, store.hex())
    # Nothing in the routine stores at offset 1 through the node register.
    assert b"\x00\x01" not in body[body.index(stores[0]):]


# ---------------------------------------------------------------------------
# What the byte actually holds, in every specimen on this machine
# ---------------------------------------------------------------------------

#: Saved games the engine wrote of a party **this project converted**.  They
#: are evidence about what the engine does with our bytes and not about what
#: it puts in a node of its own, so the census below leaves them out and
#: `test_the_engine_keeps_the_zero_a_converted_party_arrives_with` uses them
#: on their own.  `#384 (Write an Amiga Curse or Silver Blades character, so
#: a C64 or DOS party has an Amiga to arrive on)` made them.
CONVERTED = ("converted-items-drawn", "converted-menu-resave")


def _later_savegames(converted: bool = False) -> list[tuple[str, bytes]]:
    """Every Amiga Curse or Silver Blades saved game on this machine.

    The two shipped on the game disks, plus the engine-written ones in the
    specimen tree.  The three files this project's own code wrote are left
    out by name -- `tests/test_amigalaterwrite.py`'s `OURS`, the same
    exclusion for the same reason: our bytes read back as the engine's is
    how a measurement quietly becomes circular.

    `converted` selects the other side of that line: the saved games the
    engine wrote of a party we converted, and nothing else.
    """
    from tests.gamedata import specimen_root
    from tests.test_amigalaterwrite import _DRAWERS, OURS, _verified
    from tools import amigarecords, gamedisks
    out: list[tuple[str, bytes]] = []
    if not converted:
        for _, volume, name, data, what in amigarecords.specimens(
                [p for p in gamedisks.candidates("amiga") if p.is_dir()]):
            if what == "savegame":
                out.append((f"{volume}/{name}", data))
    root = specimen_root()
    if root is not None:
        for drawer, _shape, suffix in _DRAWERS:
            for where in sorted((root / drawer).glob("WISH-SPEC-*")):
                if not where.is_dir():
                    continue
                _verified(where)
                ours = any(mark in where.name for mark in CONVERTED)
                if ours != converted:
                    continue
                for path in sorted(where.glob(f"savgam*{suffix}")):
                    label = f"{where.name}/{path.name}"
                    if label in OURS:
                        continue
                    out.append((label, path.read_bytes()))
    return out


def test_the_pad_is_non_zero_only_in_the_first_three_slots_of_the_pool():
    """What a stale allocation looks like, and what a field would not.

    Each node's own heap address is in the save -- the record's chain head
    and each node's `next` -- and in every Silver Blades saved game the five
    nodes sit in five consecutive ten-byte slots.  The three that carry a
    non-zero byte are the pool's slots 0, 1 and 2, and slots 3 and 4 carry
    zero, whichever characters and whichever effect ids they are.  A field
    with a meaning would not stop at the third node in party order.
    """
    saves = _later_savegames()
    if not saves:
        pytest.skip("no Amiga Curse or Silver Blades saved games here")
    from tools import amigasavegame
    nodes = 0
    non_zero: list[tuple[str, int, int]] = []
    for label, data in saves:
        save = amigasavegame.parse(data, source=label)
        here = [(ch.effect_chain, e) for ch in save.characters
                for e in ch.effects]
        # The chain head is the node's own address; walk them in file order.
        addresses: list[int] = []
        for ch in save.characters:
            at = ch.effect_chain
            for node in ch.effects:
                addresses.append(at)
                at = int.from_bytes(node[6:10], "big")
        assert len(addresses) == len(here)
        if not addresses:
            continue
        base = min(addresses)
        for address, (_, node) in zip(addresses, here):
            nodes += 1
            slot, remainder = divmod(address - base, NODE_SIZE)
            assert remainder == 0, (label, hex(address), hex(base))
            if node[PAD]:
                non_zero.append((label, slot, node[PAD]))
    assert nodes >= 5, nodes
    assert all(slot < 3 for _, slot, _ in non_zero), non_zero
    assert {value for _, _, value in non_zero} <= {0x2E, 0x6D, 0x64}, non_zero


def test_the_curse_corpus_carries_no_such_byte_at_all():
    """Same code, same unwritten byte, and every Curse node reads zero.

    Which is the reason the pad went unnoticed until Silver Blades: it is
    not a Silver Blades field, it is memory, and Curse's happened to be
    zero.
    """
    saves = [(label, data) for label, data in _later_savegames()
             if label.endswith(".dat")]
    if not saves:
        pytest.skip("no Amiga Curse saved games here")
    from tools import amigasavegame
    nodes = [e for _, data in saves
             for ch in amigasavegame.parse(data).characters
             for e in ch.effects]
    assert nodes, "no Curse effect nodes in the corpus"
    assert all(node[PAD] == 0 for node in nodes), len(nodes)


def test_the_engine_keeps_the_zero_a_converted_party_arrives_with():
    """A converted Silver Blades party in front of the running game.

    `goldbox.amiga_later.write_later` writes zero at offset 1 because there is
    nothing in a neutral record to write.  Both saved games `#384 (Write an
    Amiga Curse or Silver Blades character, so a C64 or DOS party has an
    Amiga to arrive on)` brought back on 2026-09-07 are the **engine's own**
    rewrite of such a party -- one saved straight back from the party menu,
    one after an ITEMS screen, the opening scene and a camp -- and every
    node in both still reads zero there.

    Which is the reading-the-code finding arriving from the other side: a
    byte the engine never writes is a byte the engine does not miss.  The
    same three characters carry `0x2E`, `0x6D` and `0x64` in the party SSI
    shipped, in the same pool slots.
    """
    saves = _later_savegames(converted=True)
    if not saves:
        pytest.skip("needs the #384 converted Amiga Silver Blades specimens")
    from tools import amigasavegame
    nodes = [(label, ch.name.strip(), node)
             for label, data in saves
             for ch in amigasavegame.parse(data, source=label).characters
             for node in ch.effects]
    assert len(nodes) >= 5, nodes
    assert all(node[PAD] == 0 for _, _, node in nodes), [
        (label, name, node.hex(" ")) for label, name, node in nodes
        if node[PAD]]
    # The party really is the one whose Amiga twins carry a non-zero byte,
    # so this is the same three effects rather than a different party.
    assert {node[0] for _, _, node in nodes} >= {0x08, 0x69, 0x2F}
