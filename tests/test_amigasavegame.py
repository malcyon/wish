"""The Amiga saved-game map in `tools/amigasavegame.py`, against the code's numbers.

`#28 (Decode an Amiga saved game, not just a character file)` read the map out
of each title's own save routine.  The synthetic tests here build a saved game
from that map with no game data in it and read it back, so they run
everywhere; the specimen tests read the saved games off the player's own
disks through `tools/amigarecords.py` and `tools/amigasaves.py` and skip when
no disk is on the machine.
"""

from __future__ import annotations

import functools
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools import amigarecords, amigasavegame, amigasaves  # noqa: E402
from tools.amigasavegame import (  # noqa: E402
    CURSE,
    POOL_OF_RADIANCE,
    SILVER_BLADES,
    AmigaSaveError,
    check,
    detect,
    parse,
    report,
)

# -- the map's own arithmetic ------------------------------------------------

def test_the_header_lands_the_first_record_where_the_scan_found_it():
    # 1 + 2048 + 2048 + 1024 + 7680 + 8 + 1 + 1 + 12 + 2 on Curse; the scan
    # on the shipped save hit `0x3219`.  Silver Blades has no script buffer
    # and a six-byte square, and its first record was at `0x1417`.
    assert CURSE.party_at == 0x3219
    assert SILVER_BLADES.party_at == 0x1417


def test_pool_of_radiance_is_thirteen_bytes_between_script_and_names():
    # No container byte, a ten-byte square write, view type, mode, count.
    assert POOL_OF_RADIANCE.vm_at == 0
    assert POOL_OF_RADIANCE.square_at == 12800
    assert POOL_OF_RADIANCE.party_at == 12813
    assert POOL_OF_RADIANCE.fixed_size == 13141


def test_variable_words_sit_at_the_dos_offsets_shifted_by_the_header():
    assert CURSE.vm_offset(0x5012) == 1 + 2 * (0x5012 - 0x4900)
    assert POOL_OF_RADIANCE.vm_offset(0x5012) == 2 * (0x5012 - 0x4900)
    with pytest.raises(ValueError):
        CURSE.vm_offset(0x6B00)


# -- synthetic saved games, built from the map -------------------------------

def fake_record(shape: amiga.AmigaShape, name: str) -> bytes:
    """A record the signature scan accepts, carrying no items or effects."""
    raw = bytearray(shape.record_size)
    raw[:len(name)] = name.encode()
    for i in range(6):
        raw[0x10 + 2 * i] = raw[0x11 + 2 * i] = 12
    return bytes(raw)


def vm_with(shape, **words) -> bytearray:
    vm = bytearray(amigasavegame.VM_BYTES)
    for name, value in words.items():
        at = shape.vm_offset(int(name, 16)) - shape.vm_at
        vm[at:at + 2] = value.to_bytes(2, "big")
    return vm


def synthetic_curse(names=("ALPHA", "BETA")) -> bytes:
    out = bytearray([2])
    out += vm_with(CURSE, **{"0x5012": 2, "0x503E": len(names),
                             "0x49C9": 1, "0x49C8": 1, "0x49C7": 5})
    out += bytes(amigasavegame.ECL_BYTES)
    out += (3).to_bytes(2, "big") + (14).to_bytes(2, "big") + bytes([2, 0, 0, 0])
    out += bytes([4, 2])
    for block, slot in ((1, 1), (2, 2), (3, 3)):
        out += block.to_bytes(2, "big") + slot.to_bytes(2, "big")
    out += len(names).to_bytes(2, "big")
    for n in names:
        out += fake_record(amiga.CURSE_SHAPE, n)
    return bytes(out)


def synthetic_silver_blades(names=("GAMMA",)) -> bytes:
    out = bytearray([1])
    out += vm_with(SILVER_BLADES, **{"0x5012": 1, "0x503E": len(names)})
    out += bytes([7, 13, 0, 0, 0, 0])
    out += bytes([4, 0])
    out += bytes.fromhex("00000001ffffffffffffffff")
    out += len(names).to_bytes(2, "big")
    for n in names:
        out += fake_record(amiga.SILVER_BLADES_SHAPE, n)
    return bytes(out)


def synthetic_pool_of_radiance(slot="A", count=6) -> bytes:
    out = bytearray()
    out += vm_with(POOL_OF_RADIANCE, **{"0x503E": count, "0x5012": 3})
    out += bytes(amigasavegame.ECL_BYTES)
    out += bytes([0, 4, 6, 1, 25, 0, 0, 0, 0, 0])
    out += bytes([1, 2, count])
    table = bytearray(amigasavegame.NAME_SLOTS * amigasavegame.NAME_SLOT_BYTES)
    for i in range(count):
        table[i * 41:i * 41 + 8] = f"CHRDAT{slot}{i + 1}".encode()
    # the two slots the party does not fill hold stack junk in a real save
    table[6 * 41:6 * 41 + 4] = b"\x0a\xd0 E"
    out += table
    return bytes(out)


def test_a_synthetic_curse_save_reads_back_through_the_map():
    save = parse(synthetic_curse())
    assert save.shape is CURSE
    assert save.header_byte == 2
    assert save.square == {"x": 3, "y": 14, "facing": 2, "wall_ahead": 0,
                           "square_property": 0, "pad": 0}
    assert (save.first_mode, save.mode) == (4, 2)
    assert save.wallset == ((1, 1), (2, 2), (3, 3))
    assert save.count == 2
    assert [c.name for c in save.characters] == ["ALPHA", "BETA"]
    assert save.blocks == ((0x3219, 0x3219 + 428), (0x3219 + 428, 0x3219 + 856))
    assert save.clock == "01:15"
    assert all(ok for _, ok, _ in check(save)), check(save)


def test_a_synthetic_silver_blades_save_reads_back_through_the_map():
    save = parse(synthetic_silver_blades())
    assert save.shape is SILVER_BLADES
    assert save.square["x"] == 7 and save.square["y"] == 13
    assert save.wallset == ((0, 1), (0xFFFF, 0xFFFF), (0xFFFF, 0xFFFF))
    assert save.blocks == ((0x1417, 0x1417 + 340),)
    assert all(ok for _, ok, _ in check(save)), check(save)


def test_a_synthetic_pool_of_radiance_save_reads_back_through_the_map():
    save = parse(synthetic_pool_of_radiance("B"))
    assert save.shape is POOL_OF_RADIANCE
    assert save.header_byte is None
    assert save.square["x"] == 0 and save.square["y"] == 4
    assert save.square["facing"] == 6
    assert save.square["square_property"] == 25
    assert (save.first_mode, save.mode, save.count) == (1, 2, 6)
    assert save.names[:6] == tuple(f"CHRDATB{i}" for i in range(1, 7))
    assert all(ok for _, ok, _ in check(save)), check(save)


def test_the_count_word_is_the_table_of_contents_not_the_scan():
    # Two records embedded, count says one: the loader would read one, and
    # so does the parser -- and the check reports the disagreement.
    data = bytearray(synthetic_curse())
    data[CURSE.count_at:CURSE.party_at] = (1).to_bytes(2, "big")
    save = parse(bytes(data))
    assert save.count == 1 and len(save.characters) == 1
    failed = [claim for claim, ok, _ in check(save) if not ok]
    assert "every block starts where the scan finds a record" in failed
    assert "the last block ends at the end of the file" in failed


def test_a_file_that_fits_no_map_is_refused():
    with pytest.raises(AmigaSaveError):
        detect(bytes(20000))
    with pytest.raises(AmigaSaveError):
        parse(bytes(100), CURSE)


def test_the_report_names_every_region():
    text = report(parse(synthetic_curse()), "synthetic")
    for needle in ("container number 2", "square block at 0x3201",
                   "mode before at 0x3209: 4", "game mode at 0x320a: 2",
                   "wallset table at 0x320b", "party count at 0x3217: 2",
                   "[ok]"):
        assert needle in text
    assert "[FAIL]" not in text


# -- the saved games on the player's own disks -------------------------------

@functools.cache
def later_savegames() -> tuple[tuple[str, bytes], ...]:
    """Every Curse and Silver Blades saved game on the Amiga disks here."""
    return tuple((f"{volume}:{name}", data)
                 for _label, volume, name, data, what
                 in amigarecords.specimens() if what == "savegame")


@functools.cache
def pool_of_radiance_savegames() -> tuple[tuple[str, bytes], ...]:
    """Every `save/savgam*` on a Pool of Radiance disk on the machine."""
    found = []
    for label, image in amigasaves.images():
        try:
            disk = AmigaDisk(image)
            if disk.volume_name.lower() != "poolgame":
                continue
            for path, data in amigasavegame.savegames_on(disk):
                found.append((f"{label}!{path}", data))
        except (AmigaDiskError, ValueError):
            continue
    return tuple(found)


def _specimens():
    return later_savegames() + pool_of_radiance_savegames()


@pytest.fixture(scope="module")
def specimens():
    found = _specimens()
    if not found:
        pytest.skip("no Amiga saved game on this machine; set $AMIGA_DISKS")
    return found


def test_every_saved_game_on_the_disks_reads_through_the_map(specimens):
    for label, data in specimens:
        save = parse(data, source=label)
        failed = [(claim, detail) for claim, ok, detail in check(save)
                  if not ok]
        assert not failed, f"{label}: {failed}"


def test_the_embedded_party_is_the_signature_scans_party(specimens):
    seen = 0
    for label, data in specimens:
        save = parse(data, source=label)
        if save.shape.party != "records":
            continue
        scanned = amiga.party_in_savegame(data, save.shape.record_shape)
        assert [c.name for c in save.characters] == [c.name for c in scanned]
        assert save.count == len(scanned) == save.word(0x503E)
        seen += 1
    if not seen:
        pytest.skip("no Curse or Silver Blades saved game on this machine")


def test_a_pool_of_radiance_save_names_its_party_after_its_slot(specimens):
    seen = 0
    for label, data in specimens:
        save = parse(data, source=label)
        if save.shape is not POOL_OF_RADIANCE:
            continue
        slot = label.rsplit("savgam", 1)[-1][0].upper()
        assert save.names[:save.count] == tuple(
            f"CHRDAT{slot}{i + 1}" for i in range(save.count)), label
        assert (save.first_mode, save.mode) == (1, 2), label
        seen += 1
    if not seen:
        pytest.skip("no Pool of Radiance saved game on this machine")


# -- writing a party back into a saved game (#28 step 4) ---------------------

def test_a_synthetic_save_rebuilds_to_the_bytes_it_was_read_from():
    """The identity that makes every other claim about the writer testable.

    `rebuild` puts the header back, writes the count, and concatenates each
    character's `block_bytes`; a save whose party has not changed must come
    back byte for byte, or the writer is doing something the reader did not
    see.
    """
    for build in (synthetic_curse, synthetic_silver_blades):
        data = build()
        assert amigasavegame.rebuild(parse(data)) == data


def test_a_shorter_party_shortens_the_file_and_moves_nothing_else():
    """The party region is the last thing in the file, so a party that loses
    a character shortens it by exactly that character's block and leaves
    every byte in front of the count where it was."""
    data = synthetic_curse(("ALPHA", "BETA"))
    save = parse(data)
    out = amigasavegame.rebuild(save, save.characters[:1])
    assert len(out) == len(data) - amiga.CURSE_SHAPE.record_size
    at = CURSE.vm_offset(0x503E)
    moved = [i for i in range(CURSE.count_at) if out[i] != data[i]]
    assert moved == [at + 1], moved
    again = parse(out)
    assert again.count == 1
    assert [c.name for c in again.characters] == ["ALPHA"]
    assert all(ok for _, ok, _ in check(again)), check(again)


def test_the_party_size_word_is_kept_truthful():
    """`$503E` is cleared and rebuilt by both loaders, so the file's copy is
    never read -- but a saved game that says six in one place and one in
    another is a file that lies to the next reader, including `check`."""
    save = parse(synthetic_curse(("ALPHA", "BETA")))
    out = parse(amigasavegame.rebuild(save, save.characters[:1]))
    assert out.word(0x503E) == out.count == 1


def test_a_party_from_the_wrong_title_is_refused():
    save = parse(synthetic_curse())
    other = parse(synthetic_silver_blades()).characters
    with pytest.raises(AmigaSaveError):
        amigasavegame.rebuild(save, other)


def test_an_empty_or_oversized_party_is_refused():
    save = parse(synthetic_curse())
    with pytest.raises(AmigaSaveError):
        amigasavegame.rebuild(save, [])
    with pytest.raises(AmigaSaveError):
        amigasavegame.rebuild(save, save.characters * 4)


def test_pool_of_radiance_is_refused_because_its_party_is_not_in_the_file():
    save = parse(synthetic_pool_of_radiance())
    with pytest.raises(AmigaSaveError):
        amigasavegame.rebuild(save)


def test_a_specimen_saved_game_rebuilds_byte_for_byte(specimens):
    """The same identity against the two saved games this project has.

    They are **found** files rather than ones we watched being written, so
    this tests our reader and writer against each other and establishes
    nothing about the format; what establishes the format is the loader,
    read in `goldbox/amiga.py`.
    """
    seen = 0
    for label, data in specimens:
        save = parse(data, source=label)
        if save.shape.party != "records":
            continue
        assert amigasavegame.rebuild(save) == data, label
        seen += 1
    if not seen:
        pytest.skip("no Curse or Silver Blades saved game on this machine")
