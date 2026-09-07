"""`tools/toamigapor.py`'s `read_c64_party` hands its party to
`goldbox.amiga.write_por_slot`, which writes list position *n* to
`CHRDAT<L><n+1>` -- so the list has to arrive in the order the Amiga wants,
front of the party first.

`#385 (A C64 party converted to an Amiga disk marches in the reverse of its
C64 order)`: the C64 displays the *highest occupied slot* first on its own
`ENCAMP > ALTER > ORDER` screen, and the Amiga, like DOS, lists
`CHRDAT<L>1` first.  `read_c64_party` used to walk `SaveGame0.characters`
low to high and hand that straight to the writer, so the C64's front-rank
character landed in the Amiga's last file and vice versa -- the same bug
`#106 (A C64 party exported to DOS marches in the reverse of its C64 order)`
was for the DOS direction, which `goldbox.dos.c64_party` already carries the
fix for.  This asserts `read_c64_party` now routes through it.

Everything here reads a C64 specimen out of `$WISH_SPECIMENS` and skips on a
machine that has none; no Amiga disk is needed, since the ordering is decided
before `goldbox.amiga` ever sees the party.
"""

from __future__ import annotations

import pathlib

import pytest

from tests import gamedata

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _c64_specimen(name: str) -> pathlib.Path:
    """A C64 specimen disk, which is one file rather than a directory --
    `tests/test_toamigapor.py`'s own helper, in the shape a new file has to
    repeat since a fixture is not shared across test modules here."""
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]


def _hide_all_but(disk_path: pathlib.Path, keep_index: int,
                  out_path: pathlib.Path) -> None:
    """A copy of `disk_path` with every slot but `keep_index` un-occupied.

    Built by patching `SaveGame0`'s own bytes in place rather than by
    keeping a fixture: `looks_occupied` (`goldbox/savegame.py`) reads a
    slot's first byte as the name and refuses anything outside `A`-`Z`, so
    zeroing that one byte per slot hides it from `SaveGame0.characters`
    without touching anything else on the disk -- the roster, the items and
    the kept slot's own 256 bytes are the specimen's, unedited.  This is
    what "a party of one" means for this test: a real character, with every
    other real character removed from view.
    """
    from goldbox.d64 import D64, attach_load_address, split_load_address
    from goldbox.games import by_key
    from goldbox.savegame import HEADER_SIZE, SLOT_STRIDE

    game = by_key("pool-of-radiance")
    source = D64.open(str(disk_path))
    disk = D64.from_bytes(bytearray(source.to_bytes()))

    load_address, payload = split_load_address(disk.read_file(game.save_file))
    payload = bytearray(payload)
    for index in range(game.slot_count):
        if index == keep_index:
            continue
        payload[HEADER_SIZE + index * SLOT_STRIDE] = 0
    disk.write_file_inplace(game.save_file,
                            attach_load_address(load_address, bytes(payload)))
    disk.save(str(out_path))


# ---------------------------------------------------------------------------
# The full party: every name in the C64's own marching order
# ---------------------------------------------------------------------------

def test_a_full_party_arrives_in_the_c64s_own_marching_order(tmp_path):
    """`WISH-SPEC-por-party-twin-pair`'s `ENCAMP > ALTER > ORDER` screen
    reads BRUTUS first, per `#385`'s own measurement of this specimen --
    the C64's slots 0-5 are MALCYON, TWIN, ROLAND, LADY KATHERINE, MAGNUS,
    BRUTUS, and BRUTUS, the highest slot, is what the party sees first."""
    from tools import toamigapor

    disk = _c64_specimen("por-party-twin-pair")
    party = toamigapor.read_c64_party(str(disk))

    names = [str(char.get("name")) for char in party]
    assert names == ["BRUTUS", "MAGNUS", "LADY KATHERINE", "ROLAND", "TWIN",
                     "MALCYON"]


def test_a_second_full_party_agrees(tmp_path):
    """A second specimen, so the first is not a coincidence of its own slot
    layout."""
    from tools import toamigapor

    disk = _c64_specimen("porunconscious1")
    party = toamigapor.read_c64_party(str(disk))

    assert len(party) == 6
    names = [str(char.get("name")) for char in party]
    # The C64 lists the highest slot first; this specimen's slot 5 is
    # BRUTUS, so the converted party's front rank -- position 0, the one
    # that becomes CHRDAT<L>1 -- has to be him, and slot 0's MALCYON has
    # to be last.
    assert names[0] == "BRUTUS"
    assert names[-1] == "MALCYON"
    assert len(set(names)) == 6


# ---------------------------------------------------------------------------
# A party of one: the size a naive reversal gets right by accident
# ---------------------------------------------------------------------------

def test_a_party_of_one_names_the_single_survivor(tmp_path):
    """One real character, every other slot hidden (`_hide_all_but`).

    Kept as slot 0 -- the C64's *last* marching position, and the one a
    reversed-index bug would still place correctly on its own, which is why
    the full-party tests above are the ones that actually pin the order.
    This one is here for the size `.claude/rules/conversions.md` and `#62
    (A converted character who owns nothing gets a corrupt sheet, and DOS
    then invents a garbage item)` both ask to be tried on its own: a party
    the writer sees as a list of exactly one.
    """
    from tools import toamigapor

    disk = _c64_specimen("por-party-twin-pair")
    solo = tmp_path / "solo.d64"
    _hide_all_but(disk, keep_index=0, out_path=solo)

    party = toamigapor.read_c64_party(str(solo))

    assert len(party) == 1
    assert str(party[0].get("name")) == "MALCYON"


def test_a_party_of_one_from_the_front_rank_slot(tmp_path):
    """The other end: keeping slot 5 -- BRUTUS, the C64's *first* marching
    position -- alone, so a party of one is proven at both ends rather than
    only the one a bug would get right by accident."""
    from tools import toamigapor

    disk = _c64_specimen("por-party-twin-pair")
    solo = tmp_path / "solo.d64"
    _hide_all_but(disk, keep_index=5, out_path=solo)

    party = toamigapor.read_c64_party(str(solo))

    assert len(party) == 1
    assert str(party[0].get("name")) == "BRUTUS"
