"""`tools/dos/dosaffectreads.py`: which bytes of a DOS effect node the engine reads.

A C64 trait slot carries an effect id and nothing else, so writing one as a
DOS node means choosing bytes 3 and 4.  This pins, per title and out of the
player's own `GAME.OVR` and `START.EXE`, which ids have a handler, a
`find_affect` caller or a chain walker that reads those bytes; the two
readers that read them for every id (Dispel Magic's `0xFF` test and
`remove_affect`'s flag test); what a readied magical item writes; Pool of
Radiance's strength-item value byte; and that Silver Blades' C64 halfling id
92 is not the effect DOS gives a halfling, 97.
`docs/230-who-reads-a-dos-effect-node.md` has the reading.

The synthetic tests pin the pointer tracker on routines assembled here and
need no game.  The rest skip without the archives (and the C64 half of the
halfling test without the Silver Blades disks).
"""

from __future__ import annotations

import struct

import pytest

# The tool imports capstone at module level, and the CI runners have none.
pytest.importorskip("capstone")

from automap import gamedisks  # noqa: E402
from goldbox import c64_port  # noqa: E402
from tools.dos import dosaffectreads as reads  # noqa: E402
from tools.dos import dosbox  # noqa: E402

PROLOGUE = bytes.fromhex("5589e5")          # push bp / mov bp, sp
RETF_A = bytes.fromhex("5dca0a00")          # pop bp / retf 0xa


def _engine(blob: bytes) -> reads.Engine:
    """An engine over a hand-assembled overlay, with no dispatcher in it."""
    eng = reads.Engine("synthetic", blob, b"", [])
    eng.dispatcher = eng.remove_affect_at = len(blob) + 0x100
    return eng


def test_a_read_through_the_node_argument_is_found():
    """`les di, [bp + 8] / mov al, es:[di + 3]`: the handler reads byte 3."""
    blob = PROLOGUE + bytes.fromhex("c47e08" "268a4503") + RETF_A
    uses = reads.pointer_uses(_engine(blob), "GAME.OVR", 0, 8)
    assert {(b, rw) for b, rw, _ in uses.access} == {(3, "r")}


def test_a_read_through_the_player_argument_is_not():
    """The same instruction through `[bp + 0xc]`, the player, is no node read."""
    blob = PROLOGUE + bytes.fromhex("c47e0c" "268a4503") + RETF_A
    assert reads.pointer_uses(_engine(blob), "GAME.OVR", 0, 8).access == set()


def test_a_copy_into_a_local_is_followed():
    """Copied through `ax`/`dx` into `[bp - 4]`, then the flag byte tested."""
    blob = PROLOGUE + bytes.fromhex(
        "83ec04"          # sub sp, 4
        "8b4608" "8b560a"  # mov ax, [bp + 8] / mov dx, [bp + 0xa]
        "8946fc" "8956fe"  # mov [bp - 4], ax / mov [bp - 2], dx
        "c47efc"          # les di, [bp - 4]
        "26807d0400"      # cmp byte ptr es:[di + 4], 0
        "89ec") + RETF_A
    uses = reads.pointer_uses(_engine(blob), "GAME.OVR", 0, 8)
    assert {(b, rw) for b, rw, _ in uses.access} == {(4, "r")}


def _handoff(callee_slot: int) -> bytes:
    """A handler pushing the node and one byte, then calling a far-return routine
    that writes byte 3 through `[bp + callee_slot]`."""
    head = PROLOGUE + bytes.fromhex("ff760a" "ff7608" "b00550" "0e")
    call_at = len(head)
    tail = RETF_A
    callee_at = call_at + 3 + len(tail)
    call = b"\xe8" + struct.pack("<h", callee_at - (call_at + 3))
    callee = PROLOGUE + bytes((0xC4, 0x7E, callee_slot)) + bytes.fromhex(
        "26c6450300") + bytes.fromhex("5dca0600")   # mov byte ptr es:[di + 3], 0
    return head + call + tail + callee


def test_a_node_handed_to_a_callee_is_followed_to_the_right_argument():
    """Two more bytes pushed after the node put it at the callee's `[bp + 8]`."""
    uses = reads.pointer_uses(_engine(_handoff(8)), "GAME.OVR", 0, 8)
    assert {(b, rw) for b, rw, _ in uses.access} == {(3, "w")}


def test_the_callee_reading_the_wrong_argument_is_not_counted():
    """The mutation of the test above: the callee reads `[bp + 6]`, the byte
    pushed last, so nothing reaches the node."""
    assert reads.pointer_uses(_engine(_handoff(6)), "GAME.OVR", 0, 8).access == set()


def test_a_node_handed_to_an_indirect_call_raises_rather_than_under_reports():
    blob = PROLOGUE + bytes.fromhex("ff760a" "ff7608" "ff1e0010") + RETF_A
    with pytest.raises(ValueError, match="indirect"):
        reads.pointer_uses(_engine(blob), "GAME.OVR", 0, 8)


def test_the_encoder_matches_the_one_specimen_girdle_node():
    """ADDERLY's Amiga girdle node carries `5C` (`docs/162-spc-permanence.md`):
    18/91 under this encoding, a legal exceptional strength."""
    assert reads.encode_strength(18, 91) == 0x5C
    assert reads.encode_strength(17, 0) == 117
    assert reads.encode_strength(18, 100) == 101


# --------------------------------------------------------------------------
# The player's own engines
# --------------------------------------------------------------------------


@pytest.fixture(scope="module", params=sorted(reads.TITLES))
def engine(request):
    try:
        game = dosbox.find_game(reads.TITLES[request.param])
    except FileNotFoundError:
        pytest.skip(f"needs DOS {reads.TITLES[request.param]} in the archives")
    return reads.load(game, request.param)


def _title(name):
    try:
        return reads.load(dosbox.find_game(reads.TITLES[name]), name)
    except FileNotFoundError:
        pytest.skip(f"needs DOS {reads.TITLES[name]} in the archives")


#: title -> dispatcher, handler table, hook global, hook handler, find_affect,
#: remove_affect and its byte-4 test, add_affect, chain offset in the record.
ROUTINES = {
    "pool": (0x2AEEA, 0x6828, None, None, ("START.img", 0x2D39),
             0x2AF10, 0x2AF70, (0xB0, 0x52), 0x7F),
    "curse": (0x350E9, 0x6FC0, 0x720C, 0x125BA, ("GAME.OVR", 0x399EA),
              0x3512C, 0x3518D, (0xE3, 0x57), 0xF2),
    "silver-blades": (0x3620B, 0x87E6, 0x89C6, 0x145D3, ("GAME.OVR", 0x3AA19),
                      0x35E8E, 0x35EE9, (0x145, 0x4D), 0xFB),
}

#: title -> the effect ids the table covers, and every one of them whose
#: handler, `find_affect` callers or id-testing chain walkers read byte 3 or 4.
VALUE_READ = {
    "pool": (127, {11, 12, 14, 15, 28, 32, 34, 38, 39, 40, 43, 44, 49, 50, 57,
                   62, 74, 75, 78, 88, 89, 95, 99, 102, 103}),
    "curse": (146, {3, 11, 12, 13, 14, 15, 28, 32, 34, 38, 39, 40, 43, 44, 49,
                    62, 78, 88, 89, 90, 91, 95, 99, 102, 128, 137, 139, 144, 146}),
    "silver-blades": (113, {3, 11, 12, 14, 15, 28, 34, 38, 39, 40, 43, 44, 49,
                            62, 64, 83, 89, 91, 100, 104, 107}),
}

#: title -> where Dispel Magic tests every node's byte 3 against 0xFF.
DISPEL = {"pool": 0x2940E, "curse": 0x3120B, "silver-blades": 0x2F9EF}


def test_the_routines_are_where_the_reading_says(engine):
    (dispatcher, table, hook, hook_handler, find, remove, flag,
     add, chain) = ROUTINES[engine.title]
    assert engine.dispatcher == dispatcher
    assert engine.table == table
    assert engine.hook == hook
    assert (engine.hook_handler or (None, None))[1] == hook_handler
    assert engine.find_affect_at == find
    assert (engine.remove_affect_at, engine.remove_flag_test) == (remove, flag)
    assert engine.add_affect == add
    assert engine.chain == chain


def test_the_ids_whose_value_byte_is_read(engine):
    count, flagged = VALUE_READ[engine.title]
    v = reads.verdicts(engine)
    assert sorted(v) == list(range(1, count + 1))
    assert {e for e, x in v.items() if x.value_read} == flagged


def test_every_node_s_byte_3_and_byte_4_have_one_generic_reader_each(engine):
    """Dispel Magic passes over a node whose byte 3 is 0xFF; `remove_affect`
    runs the handler only when byte 4 is set.  A computed-id `find_affect`
    caller reads the duration and nothing past it."""
    assert reads.dispel_routine(engine)["test"] == DISPEL[engine.title]
    assert reads.computed_reads(engine) == {1, 2}


def test_pool_of_radiance_s_four_named_handlers():
    """The plan's reading, now by structure: 5 is empty, 45 reads the attacker
    and not the node, 61 never touches it, 89 keeps displacement's state in
    byte 3."""
    eng = _title("pool")
    v = reads.verdicts(eng)
    assert [v[e].handler for e in (5, 45, 61, 89)] == [0x11DF6, 0xEFD2, 0x100EB, 0x110EB]
    assert not any(v[e].value_read for e in (5, 45, 61))
    uses = reads.handler_uses(eng, 89)
    assert {(b, rw) for b, rw, _ in uses.access} == {(3, "r"), (3, "w")}


def test_a_readied_item_in_pool_of_radiance():
    """Power byte 0x3E is the handler id: eight powers share the grant that
    writes `id 00 00 0C 00`, 0x83 writes the strength node, three write none."""
    powers = reads.item_powers(_title("pool"))
    grant = [("item[0x3d]", 0, 0x0C, 0)]
    assert {p for p, calls in powers.items() if calls == grant} == \
        {0x80, 0x81, 0x82, 0x85, 0x86, 0x88, 0x8A, 0x8B}
    assert powers[0x83] == [(38, 0, "local[bp - 1]", 1)]
    assert {p for p, calls in powers.items() if not calls} == {0x84, 0x87, 0x89}


@pytest.mark.parametrize("title", ["curse", "silver-blades"])
def test_a_readied_item_in_the_later_titles(title):
    """Power 0x80 alone grants a node, and it is `id 00 00 FF 01`; the other
    powers' switch reaches no add_affect within three levels of calls."""
    eng = _title(title)
    assert reads.item_powers(eng) == {0x80: [("item[0x3d]", 0, 0xFF, 1)]}
    switch = reads.item_switch(eng)
    assert switch["add_affect_calls"] == []
    assert switch["powers"][0] == 0


def test_pool_of_radiance_s_strength_item_value_byte():
    s = reads.strength_encoding(_title("pool"))
    assert (s["handler"], s["encoder"]) == (0x11BB2, 0x2BFCE)
    assert (s["offset"], s["eighteen"], s["percentile_plus_one"]) == (100, 18, True)
    assert s["add_affect"] == [(38, 0, "local[bp - 1]", 1)]


def test_silver_blades_dos_97_is_the_constitution_bonus_and_92_cancels_fear():
    eng = _title("silver-blades")
    bands = reads.score_bands(eng, 97)
    assert bands["bands"] == [(4, 6, 1), (7, 10, 2), (11, 13, 3), (14, 17, 4), (18, 20, 5)]
    assert reads.score_bands(_title("pool"), 97)["bands"] == bands["bands"]
    assert reads.constant_calls(eng, 92) == [(0x10D4A, 111)]
    assert eng.handlers[92] != eng.handlers[97]


def test_silver_blades_c64_92_cancels_three_effects_and_97_is_the_filler():
    """The C64 side of the halfling: 92's handler cancels 29, 68 and 111
    through one helper, and 97 has the table's shared filler handler."""
    from tools.c64 import traitquery

    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    root = gamedisks.find(ssb.key)
    if root is None:
        pytest.skip("no Secret of the Silver Blades disks on this machine")
    table = traitquery.handler_addresses(str(root), ssb)
    assert table[92] != table[97]
    assert sum(1 for a in table.values() if a == table[97]) >= 10
    code = traitquery.handler_bytes(str(root), ssb, 92, 15)
    cancels = [(code[i + 1], code[i + 3] | code[i + 4] << 8)
               for i in range(0, len(code) - 4, 5)
               if code[i] == 0xA9 and code[i + 2] in (0x20, 0x4C)]
    assert [c for c, _ in cancels] == [29, 68, 111]
    assert len({t for _, t in cancels}) == 1
