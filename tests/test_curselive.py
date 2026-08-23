"""What a live Curse of the Azure Bonds session settled, pinned offline.

`docs/120-curse-testing.md` tiers 3 and 4 were done under VICE: the game was
booted from the player's own disks, a save was loaded, the party was walked, and
memory was read before and after every step. None of that can run here -- CI has
no emulator and no disks -- so what this file asserts is the part of those
findings that survives without one:

* the **constants** the live run measured, so that changing one has to be
  deliberate;
* the **code paths** the live run exercised, driven against a screen and a
  memory map built by hand around the player's own `GEO` files;
* the **route** the party actually walked, replayed through `Fingerprint`
  against the real maps -- the coordinates are our own observations, not the
  game's data, so they may live here.

The live evidence itself is in `work/reports/p8-curse-live.md`.

Every test skips when the Curse disks are absent. Nothing here reads a
committed fixture.
"""

from __future__ import annotations

import pytest

from automap.area import RESIDENT_GEO, Fingerprint, ResidentGeo
from automap.target import PARTY_X, party_fix
from por import games, geo
from por.d64 import D64
from tests import gamedata

CURSE = games.CURSE_OF_THE_AZURE_BONDS

# --- what the live run measured ---------------------------------------------
# Each of these was found by searching RAM for a value read off the save,
# corroborated by a second value, and then confirmed by changing it in the game
# and reading it back. See the report for the evidence behind each.

#: The save image's own copy of x, y, facing. Live at this address the whole
#: time -- the payload at `$4B00` was byte-identical to the file -- but the
#: engine writes it only when the game is saved, so it names the square the
#: party was standing on at the *last save*, not the one it is on now.
CURSE_SAVE_POSITION = 0x4BC0

#: What the engine actually moves. `$C04B` x, `$C04C` y, `$C04D` facing; the
#: code that writes it is a pair of self-modified immediates followed by
#: `STA $C04B` / `STA $C04C` at `$C1F7`.
CURSE_LIVE_POSITION = 0xC04B

#: The game clock, in the save image and live: minute units, tens, hour. It
#: advances by one minute per completed forward step and not on a turn.
CURSE_CLOCK = 0x4BC7

#: Payload offsets, which is the form that transfers between titles.
POSITION_OFFSET = 0x0C0
CLOCK_OFFSET = 0x0C7
AREA_OFFSET = 0x2C2
AREA_DIRTY_BIT = 0x80


# --- a machine made of a dictionary ------------------------------------------

def _codes(text: str) -> bytes:
    """PETSCII screen codes for a line of the game's own status line."""
    out = bytearray()
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(ord(ch) - 64)
        else:
            out.append(ord(ch))
    return bytes(out)


class MemoryTarget:
    """Enough of a C64 for `party_fix` and `ResidentGeo` to read.

    `$D011`, `$D018` and `$DD00` are set so `automap.screen` computes the
    game's own screen base of `$CC00`, which is where Curse draws exactly as
    Pool of Radiance does.
    """

    def __init__(self, blocks: dict[int, bytes] | None = None,
                 status: str | None = None):
        self.blocks = {0xD011: bytes([0x1B]),      # text mode, not bitmap
                       0xD018: bytes([0x30]),      # screen at bank + $0C00
                       0xDD00: bytes([0xFC]),      # bank $C000
                       0xCC00: bytes(1000),
                       0xD800: bytes(1000)}
        self.blocks.update(blocks or {})
        if status is not None:
            screen = bytearray(self.blocks[0xCC00])
            row = _codes(status.ljust(40))[:40]
            screen[14 * 40:14 * 40 + 40] = row
            self.blocks[0xCC00] = bytes(screen)

    def read(self, addr: int, length: int) -> bytes:
        for base, blob in self.blocks.items():
            if base <= addr and addr + length <= base + len(blob):
                return blob[addr - base:addr - base + length]
        return bytes(length)

    def write(self, addr: int, data: bytes) -> None:      # pragma: no cover
        raise NotImplementedError


def _curse_maps() -> dict[str, geo.Geo]:
    """Every `GEO` on the player's Curse disks, or skip."""
    maps: dict[str, geo.Geo] = {}
    for disk in gamedata.curse_disks():
        for entry in disk.directory():
            name = bytes(entry.name)
            if not name.startswith(b"GEO"):
                continue
            try:
                payload = disk.read_file(entry)[2:]
            except Exception:
                continue
            if len(payload) == geo.GEO_SIZE:
                maps[name.decode()] = geo.Geo(payload)
    if not maps:
        pytest.skip("no Curse GEO files on the player's disks")
    return maps


def _curse_save_payload() -> bytes:
    """A Curse save disk's `SAVEAZURE` payload, or skip.

    A save disk, not a game side: only a save the player wrote carries a party
    that has been anywhere.
    """
    where = gamedata.curse_dir()
    if where is None:
        pytest.skip(f"needs the Curse disks; set {gamedata.CURSE_ENV}")
    for path in sorted(where.glob("CURSE*.[dD]64")):
        try:
            disk = D64.open(path)
            prg = disk.read_file(CURSE.save_file)
        except Exception:
            continue
        if CURSE.matches_payload(prg) and any(prg[2 + POSITION_OFFSET:
                                                  2 + POSITION_OFFSET + 2]):
            return prg[2:]
    pytest.skip("no Curse save here holds a party that has left the roster")


# --- tier 3: the addresses ---------------------------------------------------

def test_the_save_image_lives_at_its_own_load_address():
    """The whole 7424 bytes were byte-identical at `$4B00` in the running game.

    So `por.games`' geometry is not merely the file's shape, it is the live
    layout, and every payload offset in it names a real address.
    """
    assert CURSE.save_load_address == 0x4B00
    assert CURSE.save_size == 0x1D00
    assert CURSE.slot_area_base == 0x4F00
    assert CURSE.roster_base == 0x6700
    assert CURSE.save_load_address + POSITION_OFFSET == CURSE_SAVE_POSITION
    assert CURSE.save_load_address + CLOCK_OFFSET == CURSE_CLOCK


def test_the_position_triple_in_the_save_is_a_square_and_a_facing():
    payload = _curse_save_payload()
    x, y, facing = payload[POSITION_OFFSET:POSITION_OFFSET + 3]
    assert 0 <= x < geo.GRID
    assert 0 <= y < geo.GRID
    assert 0 <= facing < 4


def test_the_area_byte_names_a_map_the_disks_carry():
    """`$4DC2`, payload `+$2C2`, with `$80` set -- the same offset Pool of
    Radiance keeps it at, and the map it named was the one resident at `$0400`.
    """
    payload = _curse_save_payload()
    raw = payload[AREA_OFFSET]
    assert raw & AREA_DIRTY_BIT, f"expected the dirty bit set, got ${raw:02X}"
    assert f"GEO{raw & ~AREA_DIRTY_BIT:02X}" in _curse_maps()


def test_the_live_triple_is_the_one_address_that_is_not_save_geometry():
    """The one address that does **not** transfer, stated as a fact.

    `$49C0` in a running Curse is engine code, not a party position. Curse
    keeps the position in two places, neither of them here: the save image's
    copy at `$4BC0`, refreshed only when the game saves, and the engine's
    working copy at `$C04B`, which is what moves -- and which is outside the
    save image, so no payload offset can reach it.
    """
    assert PARTY_X == 0x49C0
    assert CURSE_SAVE_POSITION != PARTY_X
    assert CURSE_LIVE_POSITION != PARTY_X
    assert CURSE_LIVE_POSITION not in range(CURSE.save_load_address,
                                            CURSE.save_load_address
                                            + CURSE.save_size)
    # Which is why it is a descriptor field and not a derived property.
    assert CURSE.live_position == CURSE_LIVE_POSITION


def test_the_memory_fallback_no_longer_reads_the_save_images_stale_copy():
    """What the fallback used to cost, and does not any more.

    Hand `party_fix` a machine with Curse's save image where Curse puts it and
    no status line on screen. The old reader answered from `$49C0`, which in a
    running Curse is engine code. The reader now goes to `$C04B` -- which this
    machine does not carry -- so it does not answer with the *stale* square in
    the save image either, which is the other wrong answer available here.
    """
    payload = _curse_save_payload()
    stale = tuple(payload[POSITION_OFFSET:POSITION_OFFSET + 3])
    machine = MemoryTarget({0x4B00: payload})
    fix = party_fix(machine.read, CURSE)
    assert fix is None or (fix.x, fix.y, fix.facing) != stale


def test_the_memory_fallback_reads_curses_own_live_triple():
    """And what it does instead: `$C04B`, the address the live run measured."""
    machine = MemoryTarget({0x4B00: _curse_save_payload(),
                            CURSE_LIVE_POSITION: bytes([9, 2, 1])})
    fix = party_fix(machine.read, CURSE)
    assert (fix.x, fix.y, fix.facing, fix.source) == (9, 2, 1, "memory")


def test_the_status_line_reads_through_the_unchanged_party_fix():
    """`STATUS_ROW` and `RE_STATUS` transfer: Curse draws `S 0:03  5,13` on the
    same row 14 of the same `$CC00` screen, and the automapper's preferred
    source needs no change at all."""
    fix = party_fix(MemoryTarget(status=" S 0:03  5,13").read)
    assert fix is not None
    assert (fix.x, fix.y, fix.facing) == (5, 13, 2)
    assert fix.source == "status"
    assert fix.clock == 3


# --- tier 4: the automapper --------------------------------------------------

def test_the_resident_map_block_is_at_0400_in_curse_too():
    """`ResidentGeo` transfers unchanged, which is the strategy that matters.

    Live, `$0400`-`$07FF` was byte-identical to `GEO01` and `identify()` named
    it outright. Here the same call is made against a machine with a real Curse
    map at the same address, so the constant and the exact-match path are both
    covered without an emulator.
    """
    maps = _curse_maps()
    name = sorted(maps)[0]
    target = MemoryTarget({RESIDENT_GEO: maps[name].to_bytes()})
    assert RESIDENT_GEO == 0x0400
    assert ResidentGeo(target).identify(maps) == name


def test_a_map_that_is_not_resident_is_not_named():
    maps = _curse_maps()
    assert ResidentGeo(MemoryTarget()).identify(maps) is None


#: The route the party actually walked in `GEO01`, as observed: the square it
#: started on, the steps it completed, and the one step the game refused. Our
#: own measurements, so they belong in this repository; the maps they are
#: checked against are read off the player's disks at run time.
WALKED = [(5, 13), (6, 13), (6, 14), (6, 15), (7, 15)]
STEPS = [((5, 13), (6, 13)), ((6, 13), (6, 14)),
         ((6, 14), (6, 15)), ((6, 15), (7, 15))]
REFUSED = ((7, 15), geo.NORTH)


def test_the_walked_route_fits_geo01_and_narrows_sixteen_maps_to_two():
    """The fingerprint strategy on Curse, from the real route.

    Four completed steps and one refusal take sixteen candidates to two, with
    `GEO01` -- the map `ResidentGeo` named independently -- among them, and no
    contradictions. A wrong decode of the maps could not produce that.
    """
    maps = _curse_maps()
    fp = Fingerprint(maps)
    assert len(fp.names) == 16
    for x, y in WALKED:
        fp.saw(x, y)
    for (x0, y0), (x1, y1) in STEPS:
        fp.moved(x0, y0, x1, y1)
    fp.refused(*REFUSED[0], REFUSED[1])
    assert fp.contradictions == 0
    assert "GEO01" in fp.names
    assert len(fp.names) <= 2


def test_geo01_agrees_with_every_step_the_game_allowed_and_the_one_it_refused():
    """The same evidence read the other way round: the decoded `GEO01` predicts
    the game's own answers, edge by edge."""
    geo01 = _curse_maps()["GEO01"]
    for (x0, y0), (x1, y1) in STEPS:
        direction = next(d for d, step in geo.STEP.items()
                         if step == (x1 - x0, y1 - y0))
        assert geo01.is_passable(x0, y0, direction), (x0, y0, direction)
    (x, y), direction = REFUSED
    assert not geo01.is_passable(x, y, direction)
