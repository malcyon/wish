"""A spell still counting down keeps its remaining minutes through a conversion.

The DOS `.SPC` record and the Amiga effect node both keep the time left as a
16-bit count of game-clock minutes (`docs/162-spc-permanence.md`), the DOS one
little-endian at byte 1 and the Amiga one big-endian at byte 2.  The Amiga byte
order is PROBABLE and unproven: every node on every Amiga disk is at duration
zero, so these tests use a synthetic value whose two bytes differ, on which a
missing or doubled swap comes out as a different number.  Nothing here holds
game bytes; the specimen check reads the player's own DOS saves and skips
without them.
"""
from __future__ import annotations

import pytest
from support.dossave import _save_dir

from goldbox import (
    amiga_later,
    amiga_pod,
    amiga_por,
    amiga_port,
    c64_port,
    dos_codec,
    dos_port,
    neutral,
)
from goldbox.layout import Confidence

POD = dos_port.POOLS_OF_DARKNESS

#: Effect 1, two minutes left, value 1, flag 0: the running record six
#: Pool of Radiance characters in the archives carry.
BLESS = bytes((1, 2, 0, 1, 0))
NULL = dos_codec.EFFECT_NEXT_NULL


def _pod_record(effects) -> dos_codec.DosCharacter:
    """A made-up Pools of Darkness fighter carrying the given `.EFX` nodes."""
    f = dos_port.FIELDS_BY_NAME_FOR[POD.key]
    raw = bytearray(POD.record_size)
    raw[0] = 5
    raw[1:6] = b"JORIL"
    raw[f["race"].offset] = 5
    raw[f["class_levels"].offset + 2] = 8
    raw[f["class_bits"].offset] = 0x04
    return dos_codec.DosCharacter(bytes(raw), effects=effects)


def _neutral(minutes: int) -> neutral.NeutralCharacter:
    return dos_codec.to_neutral(_pod_record([
        bytes((1,)) + minutes.to_bytes(2, "little") + bytes((1, 0)) + NULL]))


def test_a_running_bless_survives_dos_amiga_pools_of_darkness_and_back():
    """DOS -> neutral -> `.pc` -> neutral -> DOS keeps effect 1 and its two
    minutes, and the chain in the `.pc` holds the minutes big-endian."""
    out = dos_codec.to_neutral(_pod_record([BLESS + NULL]))
    assert [bytes(r) for r in out.get("running_effects")] == [BLESS + NULL]
    pc, _ = amiga_pod.to_pc(out)
    nodes = amiga_pod.PodCharacter.from_bytes(pc).effects
    assert [(n[0], n[2:4]) for n in nodes] == [(1, b"\x00\x02")]
    back = amiga_pod.pod_to_neutral(pc)
    assert "granted_effects" not in back
    assert [bytes(r) for r in back.get("running_effects")] == [BLESS + NULL]
    _rec, _itm, spc, _rep = dos_codec.write(back)
    assert spc == BLESS + NULL


def test_the_amiga_pools_of_darkness_duration_is_big_endian_on_both_ways():
    """0x0102 minutes has two different bytes, so a swap that is missing or
    applied twice reads or writes 0x0201 instead."""
    pc, _ = amiga_pod.to_pc(_neutral(0x0102))
    node = amiga_pod.PodCharacter.from_bytes(pc).effects[0]
    assert node[2:4] == b"\x01\x02"
    back = amiga_pod.pod_to_neutral(pc)
    assert int.from_bytes(bytes(back.get("running_effects")[0])[1:3],
                          "little") == 0x0102

    # The reader against a node written the other way round: the same bytes
    # in the opposite order read as a different count, not as 0x0102.
    swapped = bytearray(pc)
    at = amiga_pod.RECORD_BYTES     # no items, so the chain starts here
    swapped[at + 2:at + 4] = b"\x02\x01"
    other = amiga_pod.pod_to_neutral(bytes(swapped))
    assert int.from_bytes(bytes(other.get("running_effects")[0])[1:3],
                          "little") == 0x0201


def test_a_pool_of_radiance_amiga_spc_keeps_the_minutes_byte_swapped():
    char = dos_codec.to_neutral(dos_codec.DosCharacter(
        bytes(dos_port.RECORD_SIZE),
        effects=[bytes((1,)) + (0x0102).to_bytes(2, "little")
                 + bytes((1, 0)) + NULL]))
    record, _itm, spc, _rep = amiga_por.write_por(char)
    assert spc[:5] == bytes((1, 0, 0x01, 0x02, 1))
    read = amiga_por.to_neutral(amiga_por.por_character(record, b"", spc))
    assert int.from_bytes(bytes(read.get("running_effects")[0])[1:3],
                          "little") == 0x0102
    _rec, _itm, dos_spc, _ = dos_codec.write(read)
    assert dos_spc == bytes((1, 0x02, 0x01, 1, 0)) + NULL


@pytest.mark.parametrize("shape", list(amiga_port.AMIGA_DELTAS),
                         ids=lambda s: s.key)
def test_a_running_effect_survives_the_later_amiga_titles(shape):
    """Curse and Silver Blades: the neutral record writes a chain node with
    the minutes big-endian, and the reader gives it back as a running effect
    instead of dropping it with no line."""
    char = neutral.NeutralCharacter("test", game=c64_port.by_key(shape.key))
    ok = Confidence.CONFIRMED
    char.set("name", "TESTER", "a test name", ok)
    for ability in neutral.ABILITIES:
        char.set(ability, 12, "a test score", ok)
    char.set("granted_effects", [bytes((61, 0, 0, 5, 1)) + NULL],
             "a ring's grant", ok)
    char.set("running_effects",
             [bytes((1,)) + (0x0102).to_bytes(2, "little")
              + bytes((1, 0)) + NULL], "a running Bless", ok)
    built, _rep = amiga_later.write_later(char)
    assert [(n[0], n[2:4]) for n in built.effects] == [
        (61, b"\x00\x00"), (1, b"\x01\x02")]

    back = amiga_later.to_neutral_later(built)
    running = back.get("running_effects")
    assert [(bytes(r)[0], int.from_bytes(bytes(r)[1:3], "little"))
            for r in running] == [(1, 0x0102)]
    assert [bytes(g)[0] for g in back.get("granted_effects")] == [61]
    # Counted nowhere else either: it is converted, so there is no line
    # about a loss and no node missing.
    assert not [d for d in back.dropped if "effect" in d]

    _rec, _itm, spc, _ = dos_codec.write(back, deltas=shape.dos)
    nodes = [spc[i:i + 9] for i in range(0, len(spc), 9)]
    assert [(n[0], int.from_bytes(n[1:3], "little")) for n in nodes
            if n[0] in (1, 61)] == [(61, 0), (1, 0x0102)]


def test_the_six_running_bless_records_in_the_players_saves_come_back_whole():
    """`CHRDATJ1.SPC` to `CHRDATJ6.SPC`, the archive party: every record with
    time left survives DOS -> neutral -> DOS and DOS -> neutral -> Amiga
    Pool of Radiance -> neutral -> DOS with its own minutes."""
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    seen = 0
    for n in range(1, 7):
        sav = where / f"CHRDATJ{n}.SAV"
        if not (sav.is_file() and (where / f"CHRDATJ{n}.SPC").is_file()):
            continue
        char = dos_codec.read_character(sav)
        held = [bytes(e[:5]) for e in char.effects
                if e[0] not in dos_codec.INNATE_EFFECTS
                and int.from_bytes(e[1:3], "little") != 0]
        if not held:
            continue
        seen += 1
        assert held == [BLESS], (n, held)
        out = dos_codec.to_neutral(char)
        assert [bytes(r)[:5] for r in out.get("running_effects")] == held, n
        _r, _i, spc, _ = dos_codec.write(out)
        assert [spc[i:i + 5] for i in range(0, len(spc), 9)
                if int.from_bytes(spc[i + 1:i + 3], "little")] == held, n
        record, itm, amiga_spc, _ = amiga_por.write_por(out)
        read = amiga_por.to_neutral(
            amiga_por.por_character(record, itm, amiga_spc))
        assert [bytes(r)[:5] for r in read.get("running_effects")] == held, n
        _r, _i, again, _ = dos_codec.write(read)
        assert [again[i:i + 5] for i in range(0, len(again), 9)
                if int.from_bytes(again[i + 1:i + 3], "little")] == held, n
    if not seen:
        pytest.skip("no running effect in the DOS saves found here")
