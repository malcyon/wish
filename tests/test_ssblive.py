"""What driving Secret of the Silver Blades under VICE established.

`docs/121-silver-blades.md` phases 3, 4 and 5. The run itself is in
`work/reports/p9-ssb-live.md`; what is here is the part of it a machine with
the player's disks can check again without an emulator.

Three kinds of assertion, and they are different in nature:

* **The walk corpus.** Twelve moves the driven party actually made in `GEO10`,
  nine completed and three refused, recorded square by square. Against the
  decoded map every completed move must cross a passable edge and every refusal
  must meet an impassable one. That is the automapper validation, frozen: if a
  later change to `por/geo.py` starts reading the barrier planes differently,
  these twelve facts fail.
* **The import diff**, expressed as the rule it obeys rather than as bytes. The
  game rewrote `0x072` from 7 to 6, from 4 to 2 and from 2 to 1 -- which is
  exactly "keep the race, take Silver Blades' code for it". `por/games.py`'s two
  race tables have to agree with that.
* **The spellbook's width.** `GEN` clears sixteen bytes at the record's `0x078`,
  so the mask is `0x078`-`0x087`; the shipped party reaches `0x083` and no
  further. Both bounds are checked here against the player's own save.

Everything skips when the disks are absent. Nothing reads a committed fixture.
"""

from __future__ import annotations

import pytest

from por import games
from por.d64 import D64, split_load_address
from por.geo import EAST, GEO_SIZE, NORTH, SOUTH, WEST, Geo
from tests.gamedata import curse_dir, curse_disks
from tests.test_silverblades import _party, ssb_dir, ssb_disks

SSB = games.SECRET_OF_THE_SILVER_BLADES
CURSE = games.CURSE_OF_THE_AZURE_BONDS

#: The map the party stands on when the story drops it into New Verdigris. The
#: game asks for "SIDE A" and side 1 carries exactly one `GEO`.
FIRST_MAP = "GEO10"

#: Every move the driven party made, as `(x, y, direction, moved)`. Read off
#: the status line and corroborated against `$C04B` at each step; the three
#: refusals are the valuable half, because an impassable edge is rare.
WALK = [
    (3, 3, SOUTH, True),
    (3, 4, SOUTH, True),
    (3, 5, NORTH, True),
    (3, 4, NORTH, True),
    (3, 3, EAST, False),
    (3, 3, NORTH, False),
    (3, 3, WEST, True),
    (2, 3, WEST, False),
    (2, 3, NORTH, True),
    (2, 2, NORTH, True),
    (2, 1, NORTH, True),
    (2, 0, EAST, True),
]

#: Where `spells_known` starts, and how wide `GEN` treats it as being.
SPELLBOOK = 0x078
SPELLBOOK_WIDTH = 16


def _first_map() -> Geo:
    """`GEO10` off whichever side carries it, decoded."""
    for disk in ssb_disks():
        entry = disk.find(FIRST_MAP.encode())
        if entry is None:
            continue
        _, payload = split_load_address(disk.read_file(entry))
        return Geo.from_bytes(payload)
    pytest.skip(f"no Silver Blades side here carries {FIRST_MAP}")


# --- phase 5: the automapper validation, as a corpus -------------------------


def test_the_map_the_party_starts_on_is_perfectly_reciprocal():
    """480 of 480 edges agree with their neighbour -- the parse checks itself."""
    agreed, total = _first_map().reciprocity()
    assert total == 480
    assert agreed == total, f"{FIRST_MAP} reciprocity {agreed}/{total}"


def test_every_square_the_party_stood_on_is_on_the_map():
    geo = _first_map()
    for x, y, _, _ in WALK:
        assert 0 <= x < GEO_SIZE and 0 <= y < GEO_SIZE
        # A square the party occupied must be reachable: something has to be
        # open, or it could not have been walked into.
        assert any(geo.is_passable(x, y, d)
                   for d in (NORTH, EAST, SOUTH, WEST)), f"({x},{y}) is sealed"


def test_every_step_the_party_completed_crossed_a_passable_edge():
    geo = _first_map()
    done = [(x, y, d) for x, y, d, moved in WALK if moved]
    assert len(done) == 9
    for x, y, d in done:
        assert geo.is_passable(x, y, d), (
            f"the party walked ({x},{y}) direction {d}, which the decoded "
            f"{FIRST_MAP} says is blocked")


def test_every_step_the_game_refused_met_an_impassable_edge():
    """The strongest single observation available: refusals are rare.

    Three of them, and each one identifies the map far more sharply than a
    successful step does -- `GEO10` has 480 edges and only a handful are shut.
    """
    geo = _first_map()
    refused = [(x, y, d) for x, y, d, moved in WALK if not moved]
    assert len(refused) == 3
    for x, y, d in refused:
        assert not geo.is_passable(x, y, d), (
            f"the game refused ({x},{y}) direction {d}, which the decoded "
            f"{FIRST_MAP} says is open")


def test_the_walk_is_a_connected_route():
    """Each completed step lands on the square the next line starts from.

    Cheap, and it is what catches a corpus edited by hand into nonsense.
    """
    step = {NORTH: (0, -1), EAST: (1, 0), SOUTH: (0, 1), WEST: (-1, 0)}
    for (x, y, d, moved), (nx, ny, _, _) in zip(WALK, WALK[1:]):
        dx, dy = step[d] if moved else (0, 0)
        assert (x + dx, y + dy) == (nx, ny), (
            f"({x},{y}) direction {d} moved={moved} does not lead to ({nx},{ny})")


# --- phase 4: what the import did, as a rule ---------------------------------


def test_the_import_rewrites_the_race_byte_into_silver_blades_numbering():
    """`0x072` went 7 to 6, 4 to 2 and 2 to 1 across six imported characters.

    Not a diff of specimens: the game's own import arithmetic. Each pair is
    "same race, this title's code for it", so `por/games.py`'s two tables have
    to reproduce all three -- and human moving 7 to 6 is the one that would
    silently turn a Curse human into a Silver Blades halfling if either table
    were wrong.
    """
    curse = dict(games.RACES_CURSE)
    ssb = {name: code for code, name in SSB.races}
    for before, after in ((7, 6), (4, 2), (2, 1)):
        assert curse[before] in ssb, f"Curse race {before} has no name here"
        assert ssb[curse[before]] == after, (
            f"{curse[before]} is {before} in Curse and should be {after} in "
            f"Silver Blades")
    assert ssb["human"] == 6 and curse[7] == "human"


def test_the_two_titles_share_a_class_table_so_the_import_need_not_touch_it():
    """Paladin and ranger survived the import untouched, and this is why."""
    assert SSB.class_bits == CURSE.class_bits
    assert dict(SSB.class_bits)[0x40] == "paladin"
    assert dict(SSB.class_bits)[0x80] == "ranger"


def test_a_curse_export_is_the_four_save_blocks_concatenated():
    """The offsets the import diff was measured at, checked against the game.

    An exported character is 580 bytes: the slot at `0x400 + i*0x100`, the
    roster block at `0x1C00 + i*0x20`, the item page at `0x1000 + i*0x100` and
    the combat icon at `0x2E0 + i*36`, in that order. Assembling those four out
    of a save and comparing with the export the same game wrote is what makes
    a record read out of live memory trustworthy -- and it is the reading the
    Silver Blades import diff rests on.

    Reads the player's own Curse save disks; skips when there are none with an
    exported character on them.
    """
    if curse_dir() is None:
        pytest.skip("needs the Curse disks")
    checked = 0
    for disk in curse_disks(engine_only=False):
        exports = {bytes(e.name)[1:].rstrip(b"\xa0"): e
                   for e in disk.directory()
                   if bytes(e.name).startswith(b"\x02")}
        if not exports or disk.find(CURSE.save_file) is None:
            continue
        _, payload = split_load_address(disk.read_file(CURSE.save_file))
        if len(payload) != CURSE.save_size:
            continue
        for name, entry in exports.items():
            try:
                raw = disk.read_file(entry)
            except Exception:
                continue                  # a chain the drive never closed
            if len(raw) != 582:
                continue
            address, record = split_load_address(raw)
            assert address == 0x7C00
            slot = _slot_holding(payload, name)
            if slot is None:
                continue
            assert _assemble(payload, slot) == record, (
                f"{name.decode('latin1')} does not reassemble from the save")
            checked += 1
    if not checked:
        pytest.skip("no Curse save disk here pairs an export with its save")


def _slot_holding(payload: bytes, name: bytes) -> int | None:
    for i in range(SSB.slot_count):
        at = games.HEADER_SIZE + i * games.SLOT_STRIDE
        if payload[at:at + len(name)] == name and not payload[at + len(name)]:
            return i
    return None


def _assemble(payload: bytes, i: int) -> bytes:
    """The 580-byte record for slot *i*, out of the four places it is kept."""
    head = payload[games.HEADER_SIZE + i * games.SLOT_STRIDE:][:games.SLOT_STRIDE]
    roster = payload[CURSE.roster_offset + i * 0x20:][:0x20]
    items = payload[games.ITEM_AREA_OFFSET + i * games.SLOT_STRIDE:][:games.SLOT_STRIDE]
    icon = payload[games.ICON_TABLE_OFFSET + i * 36:][:36]
    return bytes(head + roster + items + icon)


# --- the spellbook's width ---------------------------------------------------


def test_the_shipped_casters_reach_0x083_and_no_further():
    """Twelve bytes by usage, where `por/layout.py` declares seven.

    MORGAINE sets `0x082` and `0x083`, DOMINIC `0x07F` and `0x080`, PAINE
    `0x081` and `0x082` -- three casters, three different bands, and every
    non-caster in the party reads zero across the whole region. So the bits
    above `0x07E` are the spellbook and not something sharing the space.
    """
    sg0, _ = _party()
    highest = -1
    for slot in sg0.characters:
        mask = slot.record.slice(SPELLBOOK, SPELLBOOK_WIDTH)
        for i, byte in enumerate(mask):
            if byte:
                highest = max(highest, i)
    assert highest >= 0x083 - SPELLBOOK, "no caster reaches 0x083"
    assert highest <= SPELLBOOK_WIDTH - 1, "a caster writes past 0x087"


def test_no_shipped_caster_writes_between_the_spellbook_and_the_saves():
    """`0x088`-`0x097` is not spellbook, and nothing in the party uses it.

    `GEN` clears sixteen bytes from `0x078`, so the mask stops at `0x087`; the
    twenty-five bytes `por/layout.py` calls `gap_07f` are therefore the mask's
    last nine plus sixteen that stay unexplained. This pins the second half so
    a later reading cannot quietly widen the field into it.
    """
    sg0, _ = _party()
    for slot in sg0.characters:
        tail = slot.record.slice(SPELLBOOK + SPELLBOOK_WIDTH, 0x098 - 0x088)
        assert not any(tail), (
            f"{slot.record.name} writes into 0x088-0x097")


# --- phase 3: the save geometry ----------------------------------------------


def test_the_position_triple_and_the_clock_sit_at_pool_of_radiances_offsets():
    """Measured live at `$4BC0` and `$4BC7`, which are those offsets on `$4B00`.

    The shipped save has never adventured, so it reads zero everywhere here;
    what this asserts is that `por/savegame.py` computes the same addresses the
    driven game was read at, which is the part that could rot.
    """
    sg0, _ = _party()
    base = SSB.save_load_address
    assert base == 0x4B00
    assert sg0.party.x == 0 and sg0.party.y == 0
    assert sg0.party.clock == (0, 0)
    # $4BC0, $4BC1, $4BC2 and $4BC7 -- the addresses the run read.
    assert base + 0xC0 == 0x4BC0
    assert base + 0xC7 == 0x4BC7


def test_the_first_side_carries_exactly_one_map_and_it_is_the_one_we_walked():
    """`GEO10`'s high nibble says side 1, and the game asks for "SIDE A"."""
    where = ssb_dir()
    if where is None:
        pytest.skip("needs the Silver Blades disks")
    side1 = sorted(where.glob("SILVER-1.[dD]64"))
    if not side1:
        pytest.skip("no side 1 here")
    disk = D64.open(str(side1[0]))
    maps = [bytes(e.name) for e in disk.directory()
            if bytes(e.name).startswith(b"GEO")]
    assert maps == [FIRST_MAP.encode()]
