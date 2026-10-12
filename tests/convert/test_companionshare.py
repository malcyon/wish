"""A companion who joined on the C64 keeps his treasure share on DOS and the Amiga.

The C64 join (`ADDNPC`, Curse `DUNGEON $28E2`, Silver Blades `$281A`) loads
the companion's `MON` file into the record buffer and stores nothing at
`0x0FA` before saving the slot; the DOS join (Curse `GAME.OVR 0x36D3` and
`0x1E9CD`) copies the `MON` record and leaves its share byte as well. So the
share a converted companion must get is his own `MON` file's. The companions
a player can have hold zero there, which every writer takes unchanged.
RAKSHASA, RUSTLE, CYNTHIA and GRENDEL hold `$FF`, which the DOS writer stops
on; RAKSHASA is removed by his own script before any save, and the other
three join only in the attract-mode demo (`ECL1E`), whose party `INIT`
clears on the way back to the title. The tests read the player's own disks
and the DOS archive, and skip without them.
"""

from __future__ import annotations

import functools
import pathlib

import gamedata
import pytest
from support import silverblades

from goldbox import amiga_later, c64_codec, dos_codec, dos_port, dos_savegame
from goldbox.companions import (
    CURSE_KEY,
    JOINABLE,
    MON_SIZE,
    SILVER_BLADES_KEY,
    Companions,
)
from goldbox.d64 import split_load_address
from goldbox.record import CharacterRecord

#: C64 record offset of the treasure share the join leaves.
C64_SHARE = 0x0FA
DELTAS = {CURSE_KEY: dos_port.CURSE_OF_THE_AZURE_BONDS,
          SILVER_BLADES_KEY: dos_port.SECRET_OF_THE_SILVER_BLADES}
DOS_STEMS = {CURSE_KEY: "CURSE", SILVER_BLADES_KEY: "SECRET"}
#: Joinable `MON` ids whose share has bit 2 set, and why no save holds them.
UNREACHABLE = {
    CURSE_KEY: {0x43: "removed by ECL42 before any save",
                0x55: "the demo's", 0x58: "the demo's", 0x5A: "the demo's"},
    SILVER_BLADES_KEY: {},
}
REACHABLE = [(key, mon_id) for key in (CURSE_KEY, SILVER_BLADES_KEY)
             for mon_id in sorted(JOINABLE[key] - set(UNREACHABLE[key]))]
IDS = [f"{key.split('-')[0]}-{mon_id:02x}" for key, mon_id in REACHABLE]


def _disks(key: str):
    return (gamedata.curse_disks() if key == CURSE_KEY
            else silverblades.ssb_disks())


@functools.lru_cache(maxsize=None)
def _table(key: str) -> Companions:
    return Companions.load(key, _disks(key))


@functools.lru_cache(maxsize=None)
def _payload(key: str, mon_id: int) -> bytes:
    name = f"MON{mon_id:02X}".encode()
    for disk in _disks(key):
        if disk.find(name):
            payload = split_load_address(disk.read_file(name))[1]
            assert len(payload) == MON_SIZE
            return payload
    pytest.fail(f"no side carries MON{mon_id:02X}")


def _join(key: str, mon_id: int) -> CharacterRecord:
    """The record `ADDNPC` saves: the `MON` file, then its own five stores --
    `0x10C = $80`, `0x10D` the slot, `0x0D1`-`0x0D2` cleared and `0x0B8`
    morale 100 halved `| $80`."""
    raw = bytearray(_payload(key, mon_id)
                    + bytes(CharacterRecord.SIZE - MON_SIZE))
    raw[0x10C] = 0x80
    raw[0x10D] = 7
    raw[0x0D1] = raw[0x0D2] = 0
    raw[0x0B8] = (100 >> 1) | 0x80
    return CharacterRecord(bytes(raw))


def _dos_mon_share(key: str, mon_id: int) -> int:
    """The share byte of the DOS `MON<n>CHA.DAX` record the DOS join copies."""
    from tools.dos import dosbox
    try:
        game = pathlib.Path(dosbox.find_game(DOS_STEMS[key]))
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {DOS_STEMS[key]} archive")
    deltas = DELTAS[key]
    size = deltas.record_size
    f83 = dos_port.FIELDS_BY_NAME_FOR[key]["field_83_87"]
    share_offset = f83.offset + (2 if f83.size == 5 else 1)
    shares = set()
    for path in sorted(game.iterdir()):
        name = path.name.upper()
        if not (name.startswith("MON") and name.endswith("CHA.DAX")):
            continue
        for entry in dos_savegame.dax_blocks(path.read_bytes()):
            block_id, raw = entry if isinstance(entry, tuple) else (None, entry)
            if block_id == mon_id and len(raw) == size:
                shares.add(bytes(raw)[share_offset])
    assert len(shares) == 1, f"DOS MON block {mon_id:#04x}: {shares}"
    return shares.pop()


def _dos_share(record: bytes, key: str) -> int:
    f83 = dos_port.FIELDS_BY_NAME_FOR[key]["field_83_87"]
    return record[f83.offset + (2 if f83.size == 5 else 1)]


@pytest.mark.parametrize("key", [CURSE_KEY, SILVER_BLADES_KEY])
def test_only_companions_no_save_holds_have_a_share_the_dos_writer_stops_on(key):
    """Bit 2 of the share is set in exactly the `MON` files no save can hold."""
    bit2 = {mon_id for mon_id in JOINABLE[key]
            if _payload(key, mon_id)[C64_SHARE] & 0x04}
    assert bit2 == set(UNREACHABLE[key])


@pytest.mark.parametrize("key, mon_id", REACHABLE, ids=IDS)
def test_a_c64_joined_companion_gets_the_share_the_dos_join_stores(key, mon_id):
    table = _table(key)
    rec = _join(key, mon_id)
    char = c64_codec.read(rec, game=key, companions=table)
    back, _, _, _ = dos_codec.write(char, deltas=DELTAS[key])
    assert _dos_share(back, key) == _dos_mon_share(key, mon_id)
    assert _dos_share(back, key) == bytes(rec)[C64_SHARE]


@pytest.mark.parametrize("key, mon_id", REACHABLE, ids=IDS)
def test_a_c64_joined_companion_gets_his_share_on_the_amiga(key, mon_id):
    table = _table(key)
    rec = _join(key, mon_id)
    char = c64_codec.read(rec, game=key, companions=table)
    back, _ = amiga_later.write_later(char, key)
    again = amiga_later.to_neutral_later(back)
    assert again.get("treasure_share") == bytes(rec)[C64_SHARE]


@pytest.mark.parametrize("key, mon_id", REACHABLE, ids=IDS)
def test_dos_and_back_gives_the_share_the_c64_join_stores(key, mon_id):
    table = _table(key)
    rec = _join(key, mon_id)
    char = c64_codec.read(rec, game=key, companions=table)
    dos, _, _, _ = dos_codec.write(char, deltas=DELTAS[key])
    again, _ = dos_codec.to_c64_record(dos_codec.DosCharacter(dos),
                                       icon=table.default_icon,
                                       companions=table)
    assert bytes(again)[C64_SHARE] == bytes(rec)[C64_SHARE]
