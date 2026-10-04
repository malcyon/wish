"""`automap/amiga.py`: the WinUAE-backed `Target`, driven with no VM at all.

Every test here replaces the one thing that touches the Windows guest -- the
`runner` callable `WinuaeDebugger` is given -- with a fake that behaves the way
the guest was measured behaving in `docs/143-winuae-debugger.md`: it prints the
`<<name>>` markers, it answers a dump with base64, and it can be made to fail
in each of the ways the real one has been seen to fail.

What is deliberately **not** tested here is whether the addresses are right.
That is a measurement on a running Amiga and no fake can stand in for it; see
`#37 (Automap the Amiga version, not just the C64)`.
"""

from __future__ import annotations

import base64
import json
import pathlib

import pytest
from support.amigatarget import BASE, SSB, Guest, target

from automap import amiga
from automap.target import Fix, NotConnected, read_fix, screen_banks

CURSE = amiga.MACHINES["curse-of-the-azure-bonds"]


# -- the transport ------------------------------------------------------------


def test_a_debugger_will_not_exist_without_a_lane_claim():
    """`winuae.ps1` blocks every call without one, so failing here says why
    once instead of once per keystroke."""
    with pytest.raises(ValueError, match="claim"):
        amiga.WinuaeDebugger("")


def test_the_batch_is_one_ssh_call_and_ends_by_resuming():
    t, guest = target({0xC00000: b"\x01\x02\x03\x04"})
    assert t.read(0xC00000, 4) == b"\x01\x02\x03\x04"
    assert len(guest.calls) == 1, "a read must not cost two round trips"
    assert Guest._batch(guest.calls[0]).splitlines()[-1] == "g"


def test_several_blocks_cost_one_round_trip():
    """The whole reason `read_blocks` exists on this backend: a round trip is
    an ssh, a foreground keypress, a scheduled task and a typed console batch,
    not 14 ms of emulated time."""
    t, guest = target({0xC00000: bytes(range(32))})
    blocks = t.read_blocks([(0xC00000, 4), (0xC00010, 4)])
    assert blocks == [bytes(range(4)), bytes(range(16, 20))]
    assert len(guest.calls) == 1


def test_a_block_that_names_its_memory_is_read_anyway():
    """The C64's callers pass `(addr, length, "io")`. A 68000 has one memory,
    so the name is ignored rather than blocked -- the documented behaviour for
    a backend that cannot tell two memories apart."""
    t, _ = target({0xC00000: b"\xaa\xbb"})
    assert t.read_blocks([(0xC00000, 2, "io")]) == [b"\xaa\xbb"]


def test_every_dump_is_named_for_this_call_and_not_the_last_one():
    """A stale dump read as a fresh one is the failure that costs a night, and
    `winuae.ps1` stamps its own receipts for the same reason."""
    t, guest = target({0xC00000: b"\x01"})
    t.read(0xC00000, 1)
    t.read(0xC00000, 1)
    first, second = (Guest._batch(c).splitlines()[0] for c in guest.calls)
    assert first != second, "two reads used the same dump filename"


def test_a_guest_that_never_finished_is_not_read_as_an_answer():
    def runner(argv, timeout):
        return "<<key>>\r\nok\r\n<<send>>\r\nfail winuae-send never started\r\n"
    t = amiga.AmigaTarget(amiga.WinuaeDebugger("wish37", runner=runner), SSB,
                          BASE)
    with pytest.raises(NotConnected, match="did not finish"):
        t.read(0xC00000, 4)


def test_a_missing_dump_says_so_rather_than_returning_zeros():
    t, guest = target({0xC00000: b"\x01\x02"})
    guest.silent = True
    with pytest.raises(NotConnected, match="no dump"):
        t.read(0xC00000, 2)


def test_a_short_dump_is_blocked():
    """Half a block read as a whole one is a plausible wrong answer, which is
    the worst kind."""
    def runner(argv, timeout):
        return ("<<key>>\r\nok\r\n<<send>>\r\nok\r\n<<b0>>\r\n"
                + base64.b64encode(b"\x01").decode() + "\r\n<<end>>\r\n")
    t = amiga.AmigaTarget(amiga.WinuaeDebugger("wish37", runner=runner), SSB,
                          BASE)
    with pytest.raises(NotConnected, match="returned 1"):
        t.read(0xC00000, 4)


def test_a_write_goes_in_as_the_debuggers_own_W():
    t, guest = target()
    t.write(0xC00000, bytes(range(20)))
    lines = Guest._batch(guest.calls[0]).splitlines()
    assert lines[0].startswith("W c00000 00 01")
    assert lines[1].startswith("W c00010 10 11 12 13")
    assert lines[-1] == "g"


def test_a_closed_target_will_not_read():
    t, _ = target({0xC00000: b"\x01"})
    t.close()
    with pytest.raises(NotConnected, match="closed"):
        t.read(0xC00000, 1)


def test_the_encoded_command_survives_a_batch_full_of_windows_paths():
    """The whole point of `-EncodedCommand`: nothing between `winvm ssh` and
    PowerShell has to be quoted right."""
    script = amiga.encode("Write-Output 'C:\\Amiga\\dump\\a.bin'")
    assert base64.b64decode(script).decode("utf-16-le").endswith("a.bin'")


# -- finding the base ---------------------------------------------------------


def test_locate_measures_the_base_from_the_anchor_rather_than_assuming_it():
    memory = {BASE + SSB.anchor_offset: SSB.anchor}
    t, guest = target(memory, base=None)
    assert t.locate() == BASE
    assert len(guest.calls) == 1, "the first region searched holds the game"


def test_locate_blocks_when_the_anchor_is_nowhere():
    """A machine running some other title, or one that has not finished
    loading. Blocking is the point: a base guessed here misreads every byte
    after it."""
    t, _ = target({}, base=None)
    with pytest.raises(NotConnected, match="nowhere"):
        t.locate()


def test_locate_blocks_two_candidates_rather_than_taking_the_first():
    memory = {BASE + SSB.anchor_offset: SSB.anchor,
              BASE + 0x40000 + SSB.anchor_offset: SSB.anchor}
    t, _ = target(memory, base=None)
    with pytest.raises(NotConnected, match="more than one place"):
        t.locate()


def test_find_anchor_reports_every_hit():
    blob = b"..xx..xx.."
    assert amiga.find_anchor(blob, 0x1000, b"xx", 2) == [0x1000, 0x1004]


def test_reading_before_the_base_is_measured_says_which_call_is_missing():
    t, _ = target({}, base=None)
    with pytest.raises(NotConnected, match="locate"):
        t.fix()


# -- what the automapper asks for ---------------------------------------------


def square(x, y, doubled, layout=SSB, wall=0):
    """The bytes the engine holds: x and y at the title's width, the facing as
    one byte, and the wall type ahead in the byte after it."""
    w = layout.width
    return {BASE + layout.party_x: x.to_bytes(w, "big"),
            BASE + layout.party_y: y.to_bytes(w, "big"),
            BASE + layout.party_facing: bytes([doubled, wall])}


@pytest.mark.parametrize("doubled,facing", [(0, 0), (2, 1), (4, 2), (6, 3)])
def test_the_facing_is_halved_because_the_engine_stores_it_doubled(doubled,
                                                                   facing):
    t, _ = target(square(5, 9, doubled))
    assert t.fix() == Fix(5, 9, facing, "memory")


@pytest.mark.parametrize("doubled,wall,facing", [
    (2, 0, 1), (4, 0, 2), (6, 3, 3), (0, 12, 0), (0, 2, 0)])
def test_curse_reads_its_facing_as_one_byte_before_the_wall_type(doubled, wall,
                                                                 facing):
    """Curse stores x and y as `u16be` but the facing as a byte, and the byte
    after it is the wall type ahead. A word read there gives
    `facing * 256 + wall`, which is no fix at all facing east, and the wrong
    facing at an even wall type."""
    t, _ = target(square(5, 9, doubled, layout=CURSE, wall=wall), layout=CURSE)
    assert t.fix() == Fix(5, 9, facing, "memory")


def test_a_square_off_the_grid_is_no_fix_at_all():
    """In a menu, in camp, or mid-load. The map holds its last reading, which
    is what it does on the C64 for a bitmap screen."""
    t, _ = target(square(200, 9, 0))
    assert t.fix() is None


def test_a_facing_the_engine_never_writes_is_no_fix_at_all():
    t, _ = target(square(5, 9, 3))
    assert t.fix() is None


def test_read_fix_prefers_this_backends_own_answer():
    """`automap/target.py` finds `fix` with `getattr`, so the C64's 40x25
    screen reader is never asked about a machine that has no such screen."""
    t, guest = target(square(1, 2, 4))
    assert read_fix(t) == Fix(1, 2, 2, "memory")
    assert len(guest.calls) == 1


def test_this_backend_claims_no_banks_capability():
    """A 68000 has one memory. `#421 (The automapper reads the screen through the CPU's banking, so it reads the wrong memory while the game loads)`'s optional capability is absent, and
    `screen_banks` hands back the one reader, which is right rather than a
    compromise."""
    assert getattr(t_for_banks(), "banks", None) is None
    banks = screen_banks(t_for_banks())
    assert banks is not None and banks.ram == banks.io


def t_for_banks():
    t, _ = target()
    return t


def test_the_resident_map_is_found_through_the_pointer_the_engine_uses():
    memory = {BASE + SSB.geo_pointer: (0xC30000).to_bytes(4, "big"),
              0xC30000: bytes(range(256)) * 4}
    t, _ = target(memory)
    assert t.resident_geo_address() == 0xC30000
    assert t.geo() == bytes(range(256)) * 4


def test_a_null_geo_pointer_is_no_map_rather_than_an_address():
    t, _ = target({BASE + SSB.geo_pointer: bytes(4)})
    assert t.resident_geo_address() is None
    assert t.geo() is None


def test_a_geo_pointer_outside_this_machines_memory_is_blocked():
    """Before an area has loaded the global holds whatever was there."""
    t, _ = target({BASE + SSB.geo_pointer: (0x00DEAD00).to_bytes(4, "big")})
    assert t.resident_geo_address() is None


# -- the table ----------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(amiga.MACHINES))
def test_every_layout_names_a_width_the_reader_can_use(key):
    layout = amiga.MACHINES[key]
    assert layout.width in (1, 2)
    assert layout.party_y == layout.party_x + layout.width
    assert layout.party_facing == layout.party_y + layout.width


# -- the table against the player's own disks ---------------------------------
#
# The offsets above are a claim about a build, and this is what turns it back
# into one: `tools/amiga/amigatarget.py verify` opens the executable off whichever
# disk the player has and checks that the anchor is where the table says, that
# it is there exactly once, and that the globals land in the part of the data
# hunk the loader zero-fills.  It needs no emulator.

#: How each title's disk image is spelt, once the underscores are taken out --
#: the same match `tests/amiga/test_amiganodefields.py` makes.
DISK = {"secret-of-the-silver-blades": "silver",
        "curse-of-the-azure-bonds": "curse",
        "pools-of-darkness": "darkness",
        "pool-of-radiance": "radiance"}


def _named(key: str, label: str) -> bool:
    """Whether this image is called after `key`'s title.

    The file's own name, and the zip's for a member of one, and never the
    folders above them: a folder called `darkness` must not make every disk
    under it Pools of Darkness'.
    """
    names = " ".join(pathlib.PurePath(part).name for part in label.split("!"))
    return DISK[key] in names.lower().replace("_", "")


def _image(key: str, tmp_path, accept):
    """The first Amiga image of this title that `accept` takes, or None.

    A loose `.adf` is used where it stands. Pools of Darkness ships inside zip
    files, which a `rglob("*.adf")` never sees, so those are written under
    `tmp_path` and the registered disks are never touched.
    """
    from automap import gamedisks
    from tools.amiga import amigasaves

    def named(label: str) -> bool:
        return _named(key, label)

    for root in gamedisks.candidates("amiga"):
        if not root.is_dir():
            continue
        for image in sorted(root.rglob("*.adf")):
            if not named(image.name):
                continue
            try:
                if accept(image):
                    return image
            except Exception:
                continue
    for n, (label, data) in enumerate(amigasaves.images()):
        if not named(label):
            continue
        image = tmp_path / f"{n}.adf"
        image.write_bytes(data)
        try:
            if accept(image):
                return image
        except Exception:
            continue
    return None


def _adf(key: str, tmp_path):
    from goldbox.amiga_adf import AmigaDisk
    exe = amiga.MACHINES[key].executable
    found = _image(key, tmp_path,
                   lambda image: AmigaDisk.open(image).read_file(exe))
    if found is None:
        pytest.skip(f"no Amiga disk carrying {exe}; set $AMIGA_DISKS")
    return found


@pytest.mark.parametrize("key", sorted(amiga.MACHINES))
def test_the_layout_still_describes_the_build_on_the_players_disk(key, tmp_path):
    """A different release with the anchor somewhere else is caught here,
    rather than as a plausible wrong square on a live machine."""
    from tools.amiga import amigatarget
    assert amigatarget.verify(amiga.MACHINES[key], _adf(key, tmp_path)) == []


@pytest.mark.parametrize("key", sorted(amiga.MACHINES))
def test_a_wrong_anchor_offset_is_what_verify_is_for(key, tmp_path):
    """Proves the check above can fail: move the offset by one and it must."""
    from dataclasses import replace

    from tools.amiga import amigatarget
    layout = amiga.MACHINES[key]
    bad = amigatarget.verify(replace(layout,
                                     anchor_offset=layout.anchor_offset + 1),
                             _adf(key, tmp_path))
    assert bad and "not" in bad[0]


def test_a_many_hunk_row_is_checked_against_each_of_its_claims(tmp_path):
    """Each claim of the Pool of Radiance row fails on its own, with its own
    message, so the check above is not passing for an unrelated reason."""
    from dataclasses import replace

    from tools.amiga import amigatarget
    layout = amiga.MACHINES["pool-of-radiance"]
    image = _adf("pool-of-radiance", tmp_path)
    assert amigatarget.verify(layout, image) == []
    wrong = {
        "allocates": replace(layout, segments=replace(
            layout.segments, data_size=layout.segments.data_size + 4)),
        "in the file, not": replace(layout, anchor_offset=0x3D8),
        "relocates": replace(layout, geo_pointer=layout.geo_pointer + 2),
        "outside": replace(layout, party_x=0x3000),
    }
    for needle, row in wrong.items():
        bad = amigatarget.verify(row, image)
        assert any(needle in line for line in bad), (needle, bad)


# -- the map the running game is drawing --------------------------------------
#
# `automap/area.py`'s `ResidentGeo` reads the C64's block at a fixed `$0400`,
# because the C64's loader leaves the file where it read it. The Amiga's
# loader allocates the buffer, so the address is a pointer the engine holds --
# and `ResidentGeo.address_now()` is the optional capability that asks a
# backend where its own block is. These are the tests of that seam from the
# Amiga side; the C64's own behaviour is pinned below as well, because the
# same hunk is what could take it away.

GEO_AT = 0xC30000


def _map_block():
    """A well-formed map built from the format, never a copy of one."""
    from gamedata import synthetic_geo
    return synthetic_geo()


def _resident(block=None, at=GEO_AT, layout=SSB, extra=None):
    """An `AmigaTarget` with a map at `at` and the engine's pointer to it."""
    block = _map_block() if block is None else block
    memory = {BASE + layout.geo_pointer: at.to_bytes(4, "big"), at: block}
    memory.update(extra or {})
    return target(memory, layout=layout)


def test_the_resident_reader_follows_this_backends_pointer():
    """The whole of the shared change: `ResidentGeo` asks the target where the
    block is, and the Amiga answers by dereferencing the engine's own global.
    Against the C64's fixed `$0400` this machine holds the 68000's exception
    vectors, which are not a map and never will be."""
    from automap.area import ResidentGeo
    from goldbox.geo import Geo
    t, _ = _resident()
    reader = ResidentGeo(t)
    assert reader.address_now() == GEO_AT
    assert reader.identify({"GEO10": Geo(_map_block())}) == "GEO10"


def test_a_backend_that_cannot_say_keeps_the_c64s_fixed_address():
    """The capability is absent on every other backend, and absence means the
    behaviour they all had before it existed."""
    from automap.area import RESIDENT_GEO, ResidentGeo
    from automap.target import MemoryTarget
    from goldbox.geo import Geo
    reader = ResidentGeo(MemoryTarget({RESIDENT_GEO: _map_block()}))
    assert reader.address_now() == RESIDENT_GEO == 0x0400
    assert reader.identify({"GEO10": Geo(_map_block())}) == "GEO10"


def test_the_pointer_is_read_every_time_because_an_area_change_moves_it():
    """A cached address would name the old area's map for as long as the new
    one is being walked. The map moves; the global is the only fixed thing."""
    from automap.area import ResidentGeo
    from goldbox.geo import Geo
    other = bytearray(_map_block())
    other[0x2FF] = 0x99                       # a different block, still a map
    t, guest = _resident(extra={0xC40000: bytes(other)})
    reader = ResidentGeo(t)
    maps = {"GEO10": Geo(_map_block()), "GEO20": Geo(bytes(other))}
    assert reader.identify(maps) == "GEO10"
    guest.memory[BASE + SSB.geo_pointer] = (0xC40000).to_bytes(4, "big")
    assert reader.identify(maps) == "GEO20"


def test_no_map_is_resident_before_an_area_has_loaded():
    """The buffer is allocated before anything is read into it, so the pointer
    is null at the party menu -- measured on 2026-09-08, 1024 zero bytes at an
    address the global already held."""
    from automap.area import UNKNOWN, ResidentGeo
    from goldbox.geo import Geo
    t, _ = target({BASE + SSB.geo_pointer: bytes(4)})
    reader = ResidentGeo(t)
    assert reader.address_now() is None
    assert reader.read() is None
    assert reader.identify({"GEO10": Geo(_map_block())}) is None
    assert reader.verdict({"GEO10": Geo(_map_block())}) == (UNKNOWN, None)


# -- the shipped automapper, over this backend --------------------------------


def _mapper(t, name="GEO10", block=None, title="Secret of the Silver Blades"):
    from automap.state import Automapper
    from goldbox.geo import Geo
    maps = {name: Geo(_map_block() if block is None else block)}
    return Automapper(t, maps, title=title)


def test_the_shipped_automapper_names_the_area_and_records_the_square():
    """`Automapper.poll()` is the window's own code and nothing here replaces
    any of it: the fix comes from the engine's globals, the area from the
    block the `GEO` pointer leads to, and the explored squares from the map."""
    from automap.area import OURS
    t, _ = _resident(extra=square(6, 9, 2))
    mapper = _mapper(t)
    assert mapper.poll() is True
    assert (mapper.state.area, mapper.state.x, mapper.state.y) == ("GEO10", 6, 9)
    assert mapper.state.facing == 1 and mapper.state.source == "memory"
    assert mapper.title_check is OURS
    assert mapper.state.exploration.seen, "the party's own square is explored"


def test_a_fresh_curse_mapper_names_the_area_facing_a_wall():
    """A window opened with the party at a wall has no earlier fix to fall
    back on: the wall byte after the facing must not hide the position."""
    from automap.area import OURS
    t, _ = _resident(layout=CURSE,
                     extra=square(3, 11, 0, layout=CURSE, wall=12))
    mapper = _mapper(t, title="Curse of the Azure Bonds")
    assert mapper.poll() is True
    assert mapper.title_check is OURS
    assert (mapper.state.x, mapper.state.y, mapper.state.facing) == (3, 11, 0)


def test_the_marker_follows_a_step_and_the_explored_set_grows():
    """One square east, which is what one `NP8` did on the running machine."""
    t, guest = _resident(extra=square(6, 9, 2))
    mapper = _mapper(t)
    mapper.poll()
    before = len(mapper.state.exploration.seen)
    guest.memory.update(square(7, 9, 2))
    assert mapper.poll() is True
    assert (mapper.state.x, mapper.state.y) == (7, 9)
    assert len(mapper.state.exploration.seen) >= before


def test_nothing_is_recorded_while_no_area_is_loaded():
    """At the party menu the globals still hold a square -- the file's own --
    and the `GEO` pointer holds no map. A mapper that believed the square
    would draw it onto whatever map was last loaded, which is exactly what
    `Automapper._running` will not do."""
    t, _ = target({BASE + SSB.geo_pointer: bytes(4), **square(6, 9, 2)})
    mapper = _mapper(t)
    assert mapper.poll() is False
    assert mapper.state.area is None
    assert not mapper.state.exploration.seen


def test_a_stranger_s_map_is_not_drawn_as_ours(tmp_path):
    """The block is a Gold Box map and none of the ones we hold: the machine is
    running another title, and `#21`'s rejection has to reach this backend too.

    Two of the player's own maps rather than the synthetic one, because the
    rejection is only reached for a block that `looks_like_a_map`, and a map
    built from the format draws every wall from one side -- 0 edges walled
    from both, where the check wants 20."""
    from automap.area import NOT_OURS, looks_like_a_map
    ours, theirs = list(amiga.load_maps(
        _map_disk("secret-of-the-silver-blades", tmp_path)).values())[:2]
    assert looks_like_a_map(theirs) and ours.to_bytes() != theirs.to_bytes()
    t, _ = _resident(block=theirs.to_bytes(), extra=square(6, 9, 2))
    mapper = _mapper(t, block=ours.to_bytes())
    for _ in range(mapper.CONTRADICTIONS_BEFORE_DISABLING):
        mapper._check_resident()                              # noqa: SLF001
    assert mapper.title_check is NOT_OURS


# -- the maps, off the player's own Amiga disk --------------------------------


def _map_disk(key: str, tmp_path):
    """The first Amiga image of this title carrying `GEO.GLB`, or a skip."""
    found = _image(key, tmp_path, amiga.load_maps)
    if found is None:
        pytest.skip(f"no Amiga disk here carries {key}'s GEO.GLB")
    return found


@pytest.mark.parametrize("key", sorted(amiga.MACHINES))
def test_the_library_is_keyed_the_way_the_c64_names_the_same_areas(key, tmp_path):
    """`GEO{id:02X}` -- the C64's own filename for the same area, so an Amiga
    party's map is drawn on the same sheet and reads the same notes. Silver
    Blades ships 17, Curse 16 and Pools of Darkness 32, which is what each port's disks hold."""
    maps = amiga.load_maps(_map_disk(key, tmp_path))
    assert maps, "the library decoded to no maps at all"
    assert all(name.startswith("GEO") and len(name) == 5 for name in maps)
    assert len(maps) == {"secret-of-the-silver-blades": 17,
                         "curse-of-the-azure-bonds": 16,
                         "pools-of-darkness": 32}[key]


@pytest.mark.parametrize("key", sorted(amiga.MACHINES))
def test_every_block_in_the_library_reads_as_a_map(key, tmp_path):
    """The check `ResidentGeo.verdict` puts a live block through, run over the
    disk copies it would be matched against. All of them, or the live reading
    would be blocked for a map the game itself is drawing -- except the one
    block Pools of Darkness ships with no walls."""
    from automap.area import looks_like_a_map
    maps = amiga.load_maps(_map_disk(key, tmp_path))
    bad = [name for name, geo in maps.items() if not looks_like_a_map(geo)]
    if key == "pools-of-darkness":
        # GEO12 has no wall on any plane and attribute 128 on every square, so
        # it reads as open ground. A live GEO12 is still named, because
        # `verdict` matches exactly before it asks whether a block is a map.
        # A second failure is a finding, not a reason to widen this list.
        assert bad == ["GEO12"]
        return
    assert bad == [], f"{len(bad)} of {len(maps)} blocks do not read as maps"


def _geo_pointers_by_usage(exe_bytes: bytes) -> set[int]:
    """Every data-hunk offset the code loads into `a0` and then offsets by both
    `+$100` and `+$200` (`movea.l d16(a4),a0` then `adda.w #imm,a0`)."""
    import re

    from tools.amiga.amiga68k import SMALL_DATA_BIAS, Executable
    exe = Executable.parse(exe_bytes)
    code = next(h for h in exe.hunks if h.kind == "CODE")
    blob = exe.data[code.file_offset:code.file_offset + code.size]
    added: dict[int, set[int]] = {}
    for m in re.finditer(rb"\x20\x6c(..)\xd0\xfc(..)", blob, re.S):
        d16 = int.from_bytes(m.group(1), "big", signed=True)
        added.setdefault(d16 + SMALL_DATA_BIAS, set()).add(
            int.from_bytes(m.group(2), "big"))
    return {g for g, adds in added.items() if {0x100, 0x200} <= adds}


def _absolute_geo_pointers_by_usage(exe_bytes: bytes, data_hunk: int) -> set[int]:
    """The many-hunk variant: `movea.l $X.l,aN` whose operand is relocated into
    the data hunk, with `#$100` and `#$200` added to a register within the next
    ten instructions."""
    import re

    from tools.amiga.amiga68k import Executable, disassemble
    pytest.importorskip("capstone")
    exe = Executable.parse(exe_bytes)
    added: dict[int, set[int]] = {}
    for (number, at), into in exe.relocs.items():
        hunk = exe.by_number(number)
        if into != data_hunk or hunk.kind != "CODE":
            continue
        field = hunk.file_offset + at
        if exe.data[field - 2:field] not in {
                bytes([0x20 | n << 1, 0x79]) for n in range(7)}:
            continue
        value = int.from_bytes(exe.data[field:field + 4], "big")
        for line in disassemble(exe, field - 2, field + 40):
            for m in re.finditer(r"#\$(100|200)\b", line):
                added.setdefault(value, set()).add(int(m.group(1), 16))
    return {g for g, adds in added.items() if {0x100, 0x200} <= adds}


@pytest.mark.parametrize("key", sorted(amiga.MACHINES))
def test_the_geo_pointer_is_the_global_the_code_offsets_by_the_planes(key, tmp_path):
    """`verify` never checks what a pointer points at. The engine indexes the
    resident block by adding `$100` and `$200` to one global, and exactly one
    global is offset by both, so a row naming any other one reads garbage."""
    from goldbox.amiga_adf import AmigaDisk
    layout = amiga.MACHINES[key]
    image = _adf(key, tmp_path)
    exe = AmigaDisk.open(image).read_file(layout.executable)
    if layout.segments is None:
        assert _geo_pointers_by_usage(exe) == {layout.geo_pointer}
    else:
        assert _absolute_geo_pointers_by_usage(
            exe, layout.segments.data_hunk) == {layout.geo_pointer}


@pytest.mark.parametrize("key", sorted(amiga.MACHINES))
def test_the_anchor_is_in_its_own_executable_once(key, tmp_path):
    from goldbox.amiga_adf import AmigaDisk
    layout = amiga.MACHINES[key]
    exe = AmigaDisk.open(_adf(key, tmp_path)).read_file(layout.executable)
    assert exe.count(layout.anchor) == 1


@pytest.mark.parametrize("key,other", [
    (key, other) for key in sorted(amiga.MACHINES)
    for other in sorted(amiga.MACHINES) if other != key])
def test_no_anchor_is_in_another_titles_executable(key, other):
    """`locate_machines` sweeps every row, so a machine running `other` must
    never match `key`'s row as well, in its code hunk or anywhere else. Every
    release of `other` on the player's disks is read, not only the first."""
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasaves
    executable = amiga.MACHINES[other].executable
    found = []
    for label, data in amigasaves.images():
        if not _named(other, label):
            continue
        try:
            exe = AmigaDisk(bytearray(data)).read_file(executable)
        except Exception:
            continue
        found.append((label, exe))
    if not found:
        pytest.skip(f"no Amiga disk carrying {executable}; set $AMIGA_DISKS")
    anchor = amiga.MACHINES[key].anchor
    assert [label for label, exe in found if anchor in exe] == []


def test_a_disk_with_no_library_on_it_is_not_an_error(tmp_path):
    """Every title's disk A. The caller reads both sides and takes whichever
    answers, which is what `load_maps_in` does."""
    image = _map_disk("secret-of-the-silver-blades", tmp_path)
    other = [p for p in sorted(image.parent.glob("*.adf")) if p != image]
    if not other:
        pytest.skip("only one image of this title here")
    assert amiga.load_maps(other[0]) == {}


def test_the_glib_parse_blocks_a_container_it_is_not():
    with pytest.raises(ValueError, match="GLIB"):
        amiga.glib_blocks(b"NOPE" + bytes(60))


# -- the tool that drove the live run -----------------------------------------


def test_the_automap_command_drives_the_shipped_mapper_and_draws_it(tmp_path,
                                                                    monkeypatch):
    """`tools/amiga/amigatarget.py automap` end to end against a fake guest.

    What it must not do is re-derive anything: the square comes from the
    backend, the area from `ResidentGeo`, the picture from
    `automap.render.to_svg`. This is the path the live run of 2026-09-08 took,
    so a change that breaks the wiring fails here rather than after a
    twenty-minute boot.
    """
    from automap import state as mapstate
    from tools.amiga import amigatarget
    image = _map_disk("secret-of-the-silver-blades", tmp_path)
    t, guest = _resident(block=amiga.load_maps(image)["GEO10"].to_bytes(),
                         extra=square(6, 9, 2))
    # `draw` rebinds this so a run never writes into the player's own notes.
    # Recording it with monkeypatch is what puts it back for the rest of the
    # worker -- `#428` is the incident where a tool's rebinding leaked.
    monkeypatch.setattr(mapstate, "_data_dir", mapstate._data_dir)  # noqa: SLF001
    monkeypatch.setattr(amigatarget, "connect", lambda *a, **k: t)
    rc = amigatarget.main(["--holder", "wish37", "automap",
                           "--out", str(tmp_path), "--maps", str(image),
                           "--polls", "2"])
    assert rc == 0
    log = [json.loads(line) for line
           in (tmp_path / "automap.jsonl").read_text().splitlines()]
    polls = [row for row in log if row["event"] == "poll"]
    assert [(row["area"], row["x"], row["y"]) for row in polls] \
        == [("GEO10", 6, 9), ("GEO10", 6, 9)]
    assert polls[0]["title"] == "ours" and polls[0]["seen"] > 0
    assert (tmp_path / "poll00.svg").read_text().startswith("<svg")
    assert guest.calls, "nothing was read from the machine at all"


def test_the_automap_command_blocks_a_disk_with_no_maps_on_it(tmp_path,
                                                               monkeypatch):
    """Rather than drawing an empty map for a party it cannot place."""
    from tools.amiga import amigatarget
    t, _ = _resident(extra=square(6, 9, 2))
    monkeypatch.setattr(amigatarget, "connect", lambda *a, **k: t)
    with pytest.raises(SystemExit, match="GEO.GLB"):
        amigatarget.main(["--holder", "wish37", "automap", "--out",
                          str(tmp_path), "--maps", str(tmp_path), "--polls", "1"])


def test_a_truncated_geo_index_is_an_error_and_not_an_empty_library():
    """A damaged `GEO.GLB` must not read as a disk with no maps on it.

    Slicing past the end of `bytes` gives `b""`, which reads as id 0 naming
    block 0 -- the index itself -- and is dropped for being the wrong size, so
    every pair of a short index vanished and the container came back empty.
    That is what a disk with no library on it looks like, which is the case
    the loader skips past, so a bad transfer was reported as the wrong thing
    entirely (`#37 (Automap the Amiga version, not just the C64)`).
    """
    import struct

    import pytest

    from automap import amiga

    index = struct.pack(">H", 4) + b"\x00\x01\x00\x01"   # 4 declared, 1 given
    body = index + b"\x00" * amiga.GEO_SIZE
    offsets = [0, len(index), len(body)]
    head = (b"GLIB" + struct.pack(">I", len(body))
            + struct.pack(">HH", 2, 0) + b"GEO ")
    data = head + b"".join(struct.pack(">I", o + len(head) + 4 * len(offsets))
                           for o in offsets) + body
    with pytest.raises(ValueError, match="declares 4 maps"):
        amiga.geo_library(data)


def test_two_holders_write_and_send_different_batch_files():
    """Two holders share the console route's guest folder, so one batch file would be overwritten by the other."""
    scripts = [amiga.WinuaeDebugger(who, runner=lambda *_: "")._script(["m 0 1", "g"], [])
               for who in ("wish37", "wish38")]
    assert amiga.WinuaeDebugger("wish37").batch_path != amiga.WinuaeDebugger("wish38").batch_path
    for who, script in zip(("wish37", "wish38"), scripts):
        assert script.count(f"wish-batch-{who}.txt") == 2
    assert "wish-batch-wish38" not in scripts[0]


def test_a_holder_that_is_not_a_name_cannot_reach_a_guest_path():
    with pytest.raises(ValueError, match="holder"):
        amiga.WinuaeDebugger("a b")
