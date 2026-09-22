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


# --------------------------------------------------------------------------
# Applying an effect: what a target's own effects cancel
# --------------------------------------------------------------------------

#: title -> apply routine, the global it parks the incoming id in, the cancel
#: helper, and check list 9's ids -- the list the apply routine walks.
APPLY = {
    "pool": (0x2C540, 0x6817, 0xEC5B,
             [105, 106, 107, 108, 109, 110, 111, 112, 124, 125]),
    "curse": (0x37303, 0x6FAD, 0xFF00,
              [105, 106, 107, 108, 109, 110, 111, 112, 124, 125, 63, 129]),
    "silver-blades": (0x37EB0, 0x87D3, 0x10D4A,
                      [18, 28, 63, 76, 79, 92, 95, 96, 99]),
}


def test_an_applied_effect_is_checked_against_list_9_of_the_target(engine):
    apply, glob, helper, list9 = APPLY[engine.title]
    walk = reads.apply_walk(engine)
    assert (walk["apply"], walk["glob"], walk["list"]) == (apply, glob, 9)
    assert walk["lists"][9] == list9
    assert reads.cancel_helper(engine) == (helper, glob)


def test_silver_blades_dos_92_protects_against_fear_and_nothing_else():
    """A C64 halfling's 92 cancels Ray of Enfeeblement (29), Feeblemind (68)
    and Fear (111).  On DOS 92 is on list 9 and cancels 111 alone, no handler
    of the 113 cancels 29 or 68, and the five `find_affect` callers that take
    their id from `ds:0x1B3D` walk the cure list 31, 34, 43, 44 and remove it."""
    eng = _title("silver-blades")
    blocked = reads.cancels(eng)
    assert blocked[92] == [111]
    assert 92 in reads.apply_walk(eng)["lists"][9]
    assert not any({29, 68} & set(ids) for ids in blocked.values())
    assert reads.data_list(eng, 0x1B3D, 1, 4) == [31, 34, 43, 44]
    callers = reads.data_indexed_callers(eng, 0x1B3D)
    assert [c["site"] for c in callers] == [0x5BD2, 0x5ED5, 0x1CA0A, 0x1CDC0, 0x2B0B6]
    assert all(c["removes"] for c in callers)
    constant_92 = [s for s in reads.find_affect_sites(eng) if s[2] == 92]
    assert [s[1] for s in constant_92] == [0x13755]
    assert eng.ovr.rfind(b"\x55\x89\xe5", 0, 0x13755) == eng.handlers[82][1]


def test_curse_is_the_title_whose_dos_engine_cancels_29_and_68():
    """The negative above is Silver Blades' own: Curse's DOS 133 does cancel
    both, so the reader can see such a handler when one exists."""
    assert reads.cancels(_title("curse"))[133] == [0, 29, 68, 142]


# --------------------------------------------------------------------------
# The C64 Dispel Magic, `tools/c64/dispelread.py`
# --------------------------------------------------------------------------


def _c64_dispel_routine(predicate: int, trait_read: bool = False) -> bytes:
    """A dispel loop at `$A700` in the form the C64 titles use, asking
    `predicate`; `trait_read` puts a `LDA $6BAD,X` after the removal.  The
    chance routine sits at `$A720` and the removal at `$A740`."""
    after = bytes.fromhex("20" "40a7") + (bytes.fromhex("bdad6b") if trait_read else b"")
    tail = bytes.fromhex("b0") + bytes((len(after),)) + after
    test = bytes.fromhex("c9ff") + bytes((0xF0, 2 + 3 + len(tail))) + \
        bytes.fromhex("290f" "20" "20a7") + tail
    body = bytes.fromhex("bd804b") + test
    loop = bytes.fromhex("a23f" "8a" "20") + struct.pack("<H", predicate) + \
        bytes((0x90, len(body))) + body
    loop += b"\xca" + bytes((0xD0, (2 - (len(loop) + 1) - 2) & 0xFF)) + b"\x60"
    chance = bytes.fromhex("38ed052baaa932b0081869" "05e830fa100ae000f00638e902cad0fa60")
    removal = bytes.fromhex("20e43f60")
    return loop.ljust(0x20, b"\xea") + chance.ljust(0x20, b"\xea") + removal


def _c64_read(blob: bytes):
    from tools.c64 import dispelread, traitquery

    library = bytes(0x3FE1 - 0x2C48) + b"\xae"      # the LDX wrapper's opcode
    pred = traitquery.Predicate("LIBRARY", 0x2C48, 0x4027, 0x3FE4, 0x6E6E, 0x402D)
    route = dispelread.Route("combat", ("X", 0, 9, 7), ("SPELLE00",), 0xA700)
    return dispelread._read_routine(c64_port.POOL_OF_RADIANCE, route, "SPELLE00",
                                    blob, 0xA700, pred, library, {})


def test_a_c64_dispel_asking_the_array_only_is_read_as_blind_to_trait_slots():
    d = _c64_read(_c64_dispel_routine(0x3FE1))
    assert d.predicate_kind == "array only"
    assert d.ids == list(range(63, 0, -1))
    assert (d.skip, d.level_mask) == (0xFF, 0x0F)
    assert (d.chance_base, d.per_level_above, d.per_level_below) == (50, 5, 2)
    assert d.removal_asks == [(0x3FE4, "array only")]
    assert d.trait_refs == []


def test_a_c64_dispel_asking_the_trait_predicate_is_read_as_such():
    """The mutation: the same loop through `$4027`, and one reading the
    block, are both reported rather than read as blind."""
    assert _c64_read(_c64_dispel_routine(0x4027)).predicate_kind == \
        "array then trait slots"
    assert _c64_read(_c64_dispel_routine(0x3FE1, trait_read=True)).trait_refs == [0xA719]


#: title -> (route, file, entry, the ids it tries or how many, index 0 of the list)
C64_DISPEL = {
    "pool-of-radiance": [("combat", "SPELLE00", 0xABCE, list(range(63, 0, -1)), None),
                         ("camp", "SPELLE04", 0xAA5B, list(range(63, 0, -1)), None)],
    "curse-of-the-azure-bonds": [("combat", "COMBAT", 0x18BD, 48, 1)],
    "secret-of-the-silver-blades": [("combat", "COMBAT", 0x1C7C, 35, 1)],
}


@pytest.mark.parametrize("key", sorted(C64_DISPEL))
def test_the_c64_dispel_magic_never_reaches_a_trait_slot(key):
    """Both DISPEL MAGIC spells of each title run one routine per route; it
    finds an effect through the array-only predicate, skips a magnitude of
    0xFF, rolls against the low nibble, removes through a routine that asks
    the array only, and names the trait block nowhere."""
    from tools.c64 import dispelread

    game = c64_port.by_key(key)
    root = gamedisks.find(game.key)
    if root is None:
        pytest.skip(f"no {game.title} disks on this machine")
    got = dispelread.read(str(root), game)
    assert [(d.route, d.file, d.entry) for d in got] == \
        [(r, f, e) for r, f, e, _, _ in C64_DISPEL[key]]
    for d, (_r, _f, _e, ids, zero) in zip(got, C64_DISPEL[key]):
        assert sorted(d.spells) == [41, 46]
        assert d.ids == ids if isinstance(ids, list) else len(d.ids) == ids
        assert d.skipped_index_zero == zero
        assert d.predicate_kind == "array only"
        assert {k for _a, k in d.removal_asks} <= {
            "array only", "the index the loop's own predicate returned"}
        assert d.removal_asks
        assert (d.skip, d.level_mask) == (0xFF, 0x0F)
        assert (d.chance_base, d.per_level_above, d.per_level_below) == (50, 5, 2)
        assert d.trait_refs == []
