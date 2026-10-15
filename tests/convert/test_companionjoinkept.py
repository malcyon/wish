"""A Curse companion converted into the C64 holds what the C64's own join
copies from his `MON` file, where no other port's record has a field.

The C64 join (`ADDNPC`) loads the companion's whole `MON` file over the
party slot, so a C64-joined ALIAS holds `$FF` at `0x0B7`, `level_monk`,
`0x0D3`, `region_0e4` and `monster_count`, DRAGONBAIT `$30` at `0x01B`, and
both `$0C` at `0x11C`. DOS and the Amiga keep none of these, so the C64
writer takes them from the player's own `MON` files
(`goldbox.companions.JOIN_KEPT`). The native save is the C64 game's own join
(`WISH-SPEC-c64-join-alias-dragonbait-wish388`); the DOS source is the DOS
game's own save of that party after a conversion
(`WISH-SPEC-curse-c64join-alias-dragonbait-dos-resave`, slot D). The tests
read the player's disks and the specimen tree, and skip without them.
"""

from __future__ import annotations

import functools
import pathlib

import gamedata
import pytest
from gamedata import specimen_root
from support import silverblades

from goldbox import c64_codec, dos_codec
from goldbox.companions import (
    CURSE_KEY,
    JOIN_KEPT,
    JOINABLE,
    MON_SIZE,
    SILVER_BLADES_KEY,
    Companions,
    Monster,
)
from goldbox.d64 import D64
from goldbox.savegame import ROSTER_STRIDE, load_save

NATIVE_JOIN = "c64-join-alias-dragonbait-wish388"
DOS_RESAVE = "curse-c64join-alias-dragonbait-dos-resave"
COMPANIONS = ("ALIAS", "DRAGONBAIT")
#: The size of the record a C64 save keeps per slot: 256 bytes of record and
#: the 32-byte roster block at 0x100.
SAVED = 0x120


@functools.lru_cache(maxsize=None)
def _table() -> Companions:
    return Companions.load(CURSE_KEY, gamedata.curse_disks())


def _native() -> dict[str, bytes]:
    """Each companion's 0x000-0x11F as the C64 game's own join saved it."""
    root = specimen_root()
    found = list(root.glob(f"*-c64/WISH-SPEC-{NATIVE_JOIN}.[dD]64")) if root else []
    if not found:
        pytest.skip(f"needs specimen WISH-SPEC-{NATIVE_JOIN}")
    _game, save0, _save1 = load_save(D64.open(str(found[0])))
    roster = save0.roster_page()
    out = {}
    for slot in save0.characters:
        name = str(slot.record.get("name"))
        if name in COMPANIONS:
            at = slot.index * ROSTER_STRIDE
            out[name] = slot.record_bytes + roster[at:at + ROSTER_STRIDE]
    assert set(out) == set(COMPANIONS)
    return out


def _converted() -> dict[str, tuple[bytes, object]]:
    """Each member of the DOS game's save D, written as a C64 record."""
    folder = pathlib.Path(gamedata.specimen(DOS_RESAVE))
    table = _table()
    out = {}
    for char in dos_codec.read_party(folder, "D"):
        neutral = dos_codec.to_neutral(char)
        rec, rep = c64_codec.write(neutral, icon=table.default_icon,
                                   companions=table)
        out[str(neutral.get("name"))] = (rec.to_bytes(), rep)
    return out


def _runs():
    for offset, size in JOIN_KEPT[CURSE_KEY]:
        yield offset, size


def test_a_converted_companion_holds_what_the_c64_join_copied():
    native = _native()
    converted = _converted()
    for name in COMPANIONS:
        mon = _table().monsters[_table().match(name)].payload
        written = converted[name][0][:SAVED]
        for offset, size in _runs():
            span = slice(offset, offset + size)
            # The C64 game's own join holds his file's bytes ...
            assert native[name][span] == mon[span], (name, hex(offset))
            # ... and so does the converted companion. Fails without the
            # fix: 0 at every one of these.
            assert written[span] == native[name][span], (name, hex(offset))


def test_the_runs_hold_what_the_ticket_measured():
    """0x0B7, 0x0CE, 0x0D3, 0x0E4 and 0x0FB for both, 0x01B for DRAGONBAIT,
    and 0x11C, the roster block's byte, for both."""
    converted = _converted()
    alias, dragonbait = (converted[n][0] for n in COMPANIONS)
    for offset in (0x0B7, 0x0CE, 0x0D3, 0x0E4, 0x0FB):
        assert (alias[offset], dragonbait[offset]) == (0xFF, 0xFF), hex(offset)
    assert (alias[0x01B], dragonbait[0x01B]) == (0x00, 0x30)
    assert (alias[0x11C], dragonbait[0x11C]) == (0x0C, 0x0C)


def test_a_player_keeps_the_writers_zero_there():
    """Nothing the writer sources sits in a kept run: a player gets the
    closing sweep's zero at every byte of every run, or the empty monk
    slot's."""
    converted = _converted()
    players = [n for n in converted if n not in COMPANIONS]
    assert players
    for name in players:
        raw, rep = converted[name]
        for offset, size in _runs():
            for i in range(offset, offset + size):
                assert raw[i] == 0, (name, hex(i))
                why = rep.sources[i]
                assert ("zero (" in why or why.startswith("level_monk: zero")
                        ), (name, hex(i), why)


def test_silver_blades_companions_need_no_kept_run():
    """Every joinable Silver Blades file holds 0 where Curse's runs lie, but
    for 0x01B-0x01F, which is Silver Blades' memorised-spell list."""
    assert SILVER_BLADES_KEY not in JOIN_KEPT
    table = Companions.load(SILVER_BLADES_KEY, silverblades.ssb_disks())
    for mon_id in JOINABLE[SILVER_BLADES_KEY]:
        payload = table.monsters[mon_id].payload
        for offset, size in _runs():
            if offset == 0x01B:
                continue
            assert not any(payload[offset:offset + size]), (
                f"MON{mon_id:02X}", hex(offset))


# -- the lookup, on synthetic tables -----------------------------------------

def _synthetic(payload: bytes = b"") -> Companions:
    monsters = {m: Monster(m, f"JOINER {m:02X}", bytes(4),
                           payload if m == 0x16 else b"")
                for m in JOINABLE[CURSE_KEY]}
    return Companions(CURSE_KEY, monsters, bytes(36))


def test_join_kept_slices_the_runs_out_of_the_file():
    payload = bytes(i & 0xFF for i in range(MON_SIZE))
    got = _synthetic(payload).join_kept(0x16)
    assert got == [(offset, payload[offset:offset + size])
                   for offset, size in JOIN_KEPT[CURSE_KEY]]


def test_join_kept_needs_the_whole_file():
    with pytest.raises(ValueError, match="MON17 was not read whole"):
        _synthetic().join_kept(0x17)


def test_join_kept_names_a_missing_file():
    with pytest.raises(KeyError, match="MON99"):
        _synthetic().join_kept(0x99)
