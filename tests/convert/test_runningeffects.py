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

import pathlib
import shutil

import pytest
from support.dossave import _save_dir

from goldbox import (
    amiga_later,
    amiga_pod,
    amiga_por,
    amiga_port,
    amiga_savegame,
    c64_codec,
    c64_port,
    dos_codec,
    dos_port,
    effects,
    neutral,
    spells,
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


@pytest.mark.parametrize("deltas", list(amiga_port.AMIGA_DELTAS),
                         ids=lambda s: s.key)
def test_a_running_effect_survives_the_later_amiga_titles(deltas):
    """Curse and Silver Blades: the neutral record writes a chain node with
    the minutes big-endian, and the reader gives it back as a running effect
    instead of dropping it with no line."""
    char = neutral.NeutralCharacter("test", game=c64_port.by_key(deltas.key))
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

    _rec, _itm, spc, _ = dos_codec.write(back, deltas=deltas.dos)
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


# --- DOS running effects into the C64 save's shared arrays ---------------------


def _pool_character(*nodes: bytes) -> neutral.NeutralCharacter:
    char = neutral.NeutralCharacter("DOS", source="built here",
                                    game=c64_port.POOL_OF_RADIANCE)
    char.set("name", "BLESSED", "built here")
    char.set("running_effects", [n + NULL for n in nodes], "built here")
    return char


def _rows(payload: bytearray) -> dict[int, tuple[int, int, int, int]]:
    return {i: (payload[effects.EFFECT_ID_OFFSET + i],
                payload[effects.EFFECT_OWNER_OFFSET + i],
                payload[effects.EFFECT_DURATION_OFFSET + i],
                payload[effects.EFFECT_MAGNITUDE_OFFSET + i])
            for i in range(effects.EFFECT_SLOTS)}


@pytest.mark.parametrize("clock", [0, 725])
def test_a_pool_bless_is_written_as_a_row_owned_by_the_save_slot(clock):
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(_pool_character(BLESS), payload=payload,
                                party_slot=2, clock_minutes=clock)
    rows = _rows(payload)
    assert rows.pop(63) == (1, 2, 0x02, 0x01)
    assert set(rows.values()) == {(0, 0, 0, 0)}
    assert not [d for d in rep.dropped + rep.losses + rep.warnings
                if "running_effects" in d]


def test_two_characters_take_slots_63_and_62():
    payload = bytearray(0x1C00)
    for slot in (2, 3):
        c64_codec.write(_pool_character(BLESS), payload=payload,
                        party_slot=slot, clock_minutes=0)
    rows = _rows(payload)
    assert (rows[63], rows[62]) == ((1, 2, 0x02, 0x01), (1, 3, 0x02, 0x01))


def test_a_running_effect_with_no_payload_is_one_loss_line():
    _rec, rep = c64_codec.write(_pool_character(BLESS))
    assert [d for d in rep.losses if d.startswith("running_effects:")] \
        == [d for d in rep.losses]
    assert len(rep.losses) == 1


def test_a_node_with_no_rule_is_one_dropped_line_and_no_row():
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(
        _pool_character(bytes((13, 2, 0, 1, 0))), payload=payload,
        party_slot=2, clock_minutes=0)
    lines = [d for d in rep.dropped if d.startswith("running_effects:")]
    assert len(lines) == 1 and "effect 13" in lines[0], rep.dropped
    assert payload == bytearray(0x1C00)


def _blessed_row_plan(party, tmp_path):
    from editor import saveplan
    from tools.convert import convertdrops

    assets = saveplan.resolve_assets(party.source, "c64",
                                     game_files=convertdrops.game_files)
    return saveplan.prepare_save_as(party, "c64", tmp_path / "out.d64", assets)


@pytest.mark.parametrize("where", ["specimen", "play"])
def test_save_as_c64_keeps_a_blessed_dos_party_blessed(tmp_path, where):
    """`prepare_save_as` returns a plan instead of refusing, and each blessed
    character has one row in the written save: id 1, owned by that
    character's slot, `$02`, magnitude `$01`."""
    from gamedata import specimen

    from automap import gamedisks
    from editor import roster, saveplan

    if where == "specimen":
        source = specimen("por-item-granted") / "SAVGAMD.DAT"
    else:
        folder = gamedisks.find("por-dos-play")
        if folder is None:
            pytest.skip("needs por-dos-play in gamedisks.yaml")
        source = next(iter(sorted(
            pathlib.Path(folder).rglob("SAVGAMJ.DAT"))), None)
        if source is None:
            pytest.skip("no SAVGAMJ.DAT under por-dos-play")
    party = roster.Party(str(source))
    try:
        plan = _blessed_row_plan(party, tmp_path)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")
    assert isinstance(plan, saveplan.SavePlan)
    out = tmp_path / "written.d64"
    (name, data), = plan.files.items()
    out.write_bytes(data)
    rows = effects.active_effects(roster.Party(str(out)).save0.to_bytes())
    blessed = [(e.id, e.owner, e.duration, e.magnitude) for e in rows]
    assert blessed, "no row was written"
    assert {(i, d, m) for i, _o, d, m in blessed} == {(1, 0x02, 0x01)}
    owners = sorted(o for _i, o, _d, _m in blessed)
    assert owners == sorted(set(owners))


def test_save_as_c64_keeps_a_slow_poisoned_dos_party_slow_poisoned(tmp_path):
    """The Pool specimen written by the game after a camp cast of Slow Poison
    on WISHFTR saves as a C64 save: rows 15 and 22 both carry magnitude `$FF`,
    and WISHFTR keeps the poison node in a trait slot."""
    from gamedata import specimen

    from editor import roster, saveplan

    party = roster.Party(str(specimen(
        "pool-667-slow-poison-camp-cast-resave") / "SAVGAMD.DAT"))
    try:
        plan = _blessed_row_plan(party, tmp_path)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")
    assert isinstance(plan, saveplan.SavePlan)
    (_name, data), = plan.files.items()
    out = tmp_path / "written.d64"
    out.write_bytes(data)
    rows = effects.active_effects(roster.Party(str(out)).save0.to_bytes())
    got = sorted((e.id, e.duration, e.magnitude) for e in rows)
    assert got == [(15, 0x0A, 0xFF), (22, 0x5E, 0xFF)]
    back = roster.Party(str(out))
    names = {m.index: m.name for m in back.members}
    assert {names[e.owner] for e in rows} == {"WISHFTR"}
    holders = {m.name for m in back.members
               if 55 in bytes(back.save0.characters[m.index]
                              .record.get_raw("item_effects"))}
    assert holders == {"WISHFTR"}


_SLOW = bytes((22, 30, 0, 0xFF, 1))
_COMPANION = bytes((15, 10, 0, 0xFF, 1))
_LONG_SLOW = bytes((22, 44, 1, 0xFF, 1))
_POISON = bytes((55, 0, 0, 0xFF, 0))
_TITLES = [c64_port.POOL_OF_RADIANCE, c64_port.CURSE_OF_THE_AZURE_BONDS]


def _slow_poison_character(game, *nodes, granted=(), innate=(),
                           ) -> neutral.NeutralCharacter:
    char = neutral.NeutralCharacter("DOS", source="built here", game=game)
    char.set("name", "RAISED", "built here")
    char.set("running_effects", [n + NULL for n in nodes], "built here")
    if granted:
        char.set("granted_effects", [n + NULL for n in granted], "built here")
    if innate:
        char.set("innate_effects", list(innate), "built here")
    return char


def _written_slow_poison(char, clock=0):
    payload = bytearray(0x1C00)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                               clock_minutes=clock)
    return sorted((r[0], r[3]) for r in _rows(payload).values()
                  if r[0] in (15, 22)), rec, rep, payload


@pytest.mark.parametrize("game", _TITLES)
def test_save_as_c64_keeps_a_raised_fighter_alive_when_slow_poison_ends(game):
    """No poison (55) and a minute-unit Slow Poison row: both rows are `$7F`,
    which runs no C64 handler. With 55 held, or a ten-minute-unit row, they
    stay `$FF`."""
    quiet = [(15, 0x7F), (22, 0x7F)]
    loud = [(15, 0xFF), (22, 0xFF)]
    assert _written_slow_poison(
        _slow_poison_character(game, _SLOW, _COMPANION))[0] == quiet
    assert _written_slow_poison(_slow_poison_character(
        game, _SLOW, _COMPANION, granted=(_POISON,)))[0] == loud
    assert _written_slow_poison(
        _slow_poison_character(game, _LONG_SLOW))[0] == [(22, 0xFF)]


@pytest.mark.parametrize("game", _TITLES)
def test_a_racial_poison_in_a_trait_slot_keeps_slow_poison_loud(game):
    got, rec, _rep, _p = _written_slow_poison(_slow_poison_character(
        game, _SLOW, _COMPANION, innate=(55,)))
    assert got == [(15, 0xFF), (22, 0xFF)]
    assert 55 in bytes(rec.get_raw("item_effects"))


@pytest.mark.parametrize("game", _TITLES)
def test_a_running_poison_the_conversion_drops_does_not_keep_slow_poison_loud(
        game):
    """A running 55 has no C64 row, so the save holds no poison and the rows
    must be the quiet ones."""
    got, rec, rep, _p = _written_slow_poison(_slow_poison_character(
        game, _SLOW, _COMPANION, bytes((55, 5, 0, 0xFF, 0))))
    assert 55 not in bytes(rec.get_raw("item_effects"))
    assert got == [(15, 0x7F), (22, 0x7F)]


@pytest.mark.parametrize("game", _TITLES)
def test_the_companion_follows_its_own_characters_slow_poison_row(game):
    assert _written_slow_poison(
        _slow_poison_character(game, _COMPANION))[0] == [(15, 0xFF)]
    assert _written_slow_poison(
        _slow_poison_character(game, _SLOW))[0] == [(22, 0x7F)]


@pytest.mark.parametrize("clock", [0, 725])
@pytest.mark.parametrize("minutes", [64, 65, 66])
def test_the_quiet_row_is_chosen_by_the_duration_unit_not_the_minutes(
        minutes, clock):
    """`closest_duration` gives a minute-unit byte for 64 minutes at both
    clock phases, and at clock 725 turns to a ten-minute byte for 65 and 66,
    where the row is left as DOS's `$FF`."""
    node = bytes((22, minutes & 0xFF, minutes >> 8, 0xFF, 1))
    got = _written_slow_poison(_slow_poison_character(
        c64_port.POOL_OF_RADIANCE, node), clock)[0]
    minute_unit = effects.closest_duration(minutes, clock) < 0x40
    assert minute_unit == (minutes == 64 or clock == 0)
    assert got == [(22, 0x7F if minute_unit else 0xFF)]


def test_a_pool_own_row_with_data_7f_keeps_its_magnitude_beside_a_poison():
    """Pool's own `(22, data 0x7F, flag 0)` node is `$7F` by its own rule and
    is not the quiet row, so a granted 55 leaves it alone."""
    own = bytes((22, 30, 0, 0x7F, 0))
    got = _written_slow_poison(_slow_poison_character(
        c64_port.POOL_OF_RADIANCE, own, granted=(_POISON,)))[0]
    assert got == [(22, 0x7F)]


@pytest.mark.parametrize("game", _TITLES)
def test_each_slow_poison_row_is_judged_by_its_own_duration_unit(game):
    minute_row = bytes((22, 30, 0, 0xFF, 1))
    hour_row = bytes((22, 44, 1, 0xFF, 1))
    got = _written_slow_poison(_slow_poison_character(
        game, minute_row, hour_row))[0]
    assert got == [(22, 0x7F), (22, 0xFF)]


@pytest.mark.parametrize("granted", [(), (_POISON,)])
def test_a_silver_blades_slow_poison_row_is_7f_with_or_without_poison(granted):
    got = _written_slow_poison(_slow_poison_character(
        c64_port.SECRET_OF_THE_SILVER_BLADES, _SLOW, _COMPANION,
        granted=granted))[0]
    assert got == [(15, 0x7F), (22, 0x7F)]


@pytest.mark.parametrize("game", _TITLES)
def test_a_quiet_slow_poison_row_reads_back_to_the_dos_nodes(game):
    _got, _rec, _rep, payload = _written_slow_poison(
        _slow_poison_character(game, _SLOW, _COMPANION))
    back = _read(payload, 2, game)
    nodes = sorted(bytes(r)[0:1] + bytes(r)[3:5]
                   for r in back.get("running_effects"))
    assert nodes == [bytes((15, 0xFF, 1)), bytes((22, 0xFF, 1))]


def test_save_as_c64_keeps_a_silver_blades_survivor_alive_through_the_rest(
        tmp_path):
    """A Silver Blades DOS save with PAINE under Slow Poison (row 22 still
    running) saves as a C64 save whose row carries magnitude `$7F`, which has
    bit 7 clear, and PAINE keeps 55 in a trait slot. The specimen is the
    control resave of a live DOS run, `WISH-SPEC-ssb-667-slow-poison-running-
    resave`."""
    from gamedata import specimen

    from editor import roster, saveplan

    party = roster.Party(str(specimen(
        "ssb-667-slow-poison-running-resave") / "SAVGAMD.DAT"))
    try:
        plan = _blessed_row_plan(party, tmp_path)
    except saveplan.MissingAssets:
        pytest.skip("needs Silver Blades' own C64 disks")
    assert isinstance(plan, saveplan.SavePlan)
    (_name, data), = plan.files.items()
    out = tmp_path / "written.d64"
    out.write_bytes(data)
    back = roster.Party(str(out))
    names = {m.index: m.name for m in back.members}
    rows = [e for e in effects.active_effects(back.save0.to_bytes())
            if e.id in (15, 22)]
    # The control resave's 10-minute damage node ran out during the rest, so
    # only row 22 is left; every row that is there carries `$7F`.
    assert [(names[e.owner], e.id, e.magnitude) for e in rows] == [
        ("PAINE", 22, 0x7F)]
    holders = {m.name for m in back.members
               if 55 in bytes(back.save0.characters[m.index]
                              .record.get_raw("item_effects"))}
    assert "PAINE" in holders


def test_save_as_c64_keeps_a_curse_party_shielded_and_protected(tmp_path):
    """The Curse specimen made by driving the game holds FLORENTZ under
    Protection from Evil 10' Radius (47 minutes) and Shield (2 minutes) and
    BRYTWYN under Shield: each arrives as a row owned by that character's
    slot, with the caster level as its magnitude (`$0A` and `$0B`) and the
    time through `closest_duration` (`$2F` and `$02`)."""
    from gamedata import specimen

    from editor import roster, saveplan

    party = roster.Party(str(
        specimen("curse-234-party-dualclassed") / "SAVGAMD.DAT"))
    try:
        plan = _blessed_row_plan(party, tmp_path)
    except saveplan.MissingAssets:
        pytest.skip("needs Curse of the Azure Bonds' own C64 disks")
    assert isinstance(plan, saveplan.SavePlan)
    out = tmp_path / "written.d64"
    (_name, data), = plan.files.items()
    out.write_bytes(data)
    back = roster.Party(str(out))
    names = {m.index: m.name for m in back.members}
    rows = sorted((names[e.owner], e.id, e.duration, e.magnitude)
                  for e in effects.active_effects(back.save0.to_bytes()))
    assert rows == sorted([("FLORENTZ", 45, 0x2F, 0x0A),
                           ("FLORENTZ", 17, 0x02, 0x0B),
                           ("BRYTWYN", 17, 0x02, 0x0B)])


@pytest.mark.parametrize("eid, named", [(134, False), (45, True)])
def test_a_refused_effect_line_names_the_effect_only_when_it_has_a_name(eid, named):
    """An unnamed id reads `effect 134`, not `effect 134 (trait 134)`: a running
    effect is not a trait."""
    char = neutral.NeutralCharacter(
        "DOS", source="built here", game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    char.set("name", "SHIELDED", "built here")
    char.set("running_effects", [bytes((eid, 2, 0, 1, 1)) + NULL], "built here")
    _rec, rep = c64_codec.write(char, payload=bytearray(0x1C00),
                                party_slot=0, clock_minutes=0)
    line, = [d for d in rep.dropped if d.startswith("running_effects:")]
    assert ("(" in line) is named, line
    assert "trait" not in line, line


# --- C64 rows back into DOS running effects ------------------------------------

from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS, POOL_OF_RADIANCE  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402


def _read(payload, slot, game=POOL_OF_RADIANCE, clock=0):
    return c64_codec.read(CharacterRecord.blank(), game=game,
                          payload=bytes(payload), party_slot=slot,
                          clock_minutes=clock)


def _lines(out):
    return [d for d in out.dropped if d.startswith("running_effects:")]


def test_a_pool_bless_row_reads_back_for_its_owner_and_no_one_else():
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 1, 2, 0x02, 0x01)
    got = _read(p, 2)
    assert [bytes(r) for r in got.get("running_effects")] == [BLESS + NULL]
    assert not _lines(got)
    other = _read(p, 3)
    assert other.get("running_effects") is None and not _lines(other)


def test_a_row_with_no_rule_is_one_dropped_line():
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 13, 2, 0x02, 0x01)
    got = _read(p, 2)
    assert got.get("running_effects") is None
    lines = _lines(got)
    assert len(lines) == 1 and lines[0].startswith("running_effects: effect 13")


def test_a_never_expiring_row_is_an_innate_effect_with_no_line():
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 45, 2, 0x00, 0x01)
    got = _read(p, 2)
    assert 45 in got.get("innate_effects") and not _lines(got)
    assert got.get("running_effects") is None


def test_curse_cure_and_shield_rows_both_read_and_a_second_cure_is_refused():
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 141, 2, 0xC7, 0xC7)
    effects.write_effect(p, 62, 17, 2, 0x02, 0x0B)
    effects.write_effect(p, 61, 141, 2, 0xC7, 0xC7)
    got = _read(p, 2, CURSE_OF_THE_AZURE_BONDS)
    nodes = [effects.RunningEffect.from_record(bytes(r))
             for r in got.get("running_effects")]
    assert [n.id for n in nodes] == [141, 17]
    assert nodes[1] == effects.RunningEffect(17, 2, 0x0B, 0)
    assert len(_lines(got)) == 1


def test_a_written_bless_reads_back_from_the_same_payload():
    p = bytearray(0x1C00)
    c64_codec.write(_pool_character(BLESS), payload=p, party_slot=2,
                    clock_minutes=0)
    got = _read(p, 2)
    assert [bytes(r) for r in got.get("running_effects")] == [BLESS + NULL]


def test_c64_party_carries_a_staged_bless_and_reports_a_row_no_one_owns():
    from goldbox.savegame import SaveGame0, SaveGame1
    fx = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
    payload = bytearray(SaveGame0.from_prg(
        (fx / "savedgame0.bin").read_bytes()).to_bytes())
    save1 = SaveGame1.from_prg(
        (fx / "savedgame1.bin").read_bytes()).to_bytes()
    effects.write_effect(payload, 63, 1, 0, 0x02, 0x01)
    party, _ = dos_codec.c64_party(bytes(payload), save1,
                                   game=POOL_OF_RADIANCE)
    brutus = next(c for c in party if c.get("name") == "BRUTUS")
    assert [bytes(r) for r in brutus.get("running_effects")] == [BLESS + NULL]
    _rec, _itm, spc, _rep = dos_codec.write(brutus)
    assert spc[:5] == BLESS

    effects.write_effect(payload, 62, 35, 0xFF, 0x41, 0x01)
    party, _ = dos_codec.c64_party(bytes(payload), save1,
                                   game=POOL_OF_RADIANCE)
    brutus = next(c for c in party if c.get("name") == "BRUTUS")
    assert [bytes(r) for r in brutus.get("running_effects")] == \
        [BLESS + NULL, bytes((35, 9, 0, 1, 0)) + NULL]
    assert not [d for c in party for d in c.dropped if "effect 35" in d]

    effects.write_effect(payload, 61, 1, 0xFF, 0x0A, 0x01)
    party, _ = dos_codec.c64_party(bytes(payload), save1,
                                   game=POOL_OF_RADIANCE)
    lines = [d for c in party for d in c.dropped if "the whole party" in d]
    assert len(lines) == 1


def test_a_permanent_row_already_in_a_trait_slot_is_not_listed_twice():
    rec = CharacterRecord.blank()
    rec.set_raw("item_effects", bytes((45,)) + bytes(9))
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 45, 2, 0x00, 0x01)
    got = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=bytes(p),
                         party_slot=2, clock_minutes=0)
    assert list(got.get("innate_effects")).count(45) == 1


def test_an_unowned_never_expiring_row_is_not_reported_as_zero_minutes():
    from goldbox.savegame import SaveGame0, SaveGame1
    fx = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
    payload = bytearray(SaveGame0.from_prg(
        (fx / "savedgame0.bin").read_bytes()).to_bytes())
    save1 = SaveGame1.from_prg(
        (fx / "savedgame1.bin").read_bytes()).to_bytes()
    effects.write_effect(payload, 62, 35, 0x08, 0x00, 0x01)
    party, _ = dos_codec.c64_party(bytes(payload), save1,
                                   game=POOL_OF_RADIANCE)
    lines = [d for c in party for d in c.dropped if "effect 35" in d]
    assert len(lines) == 1
    assert "0 minutes" not in lines[0] and "never expires" in lines[0]


def _dos_plan(tmp_path, payload, save1):
    from editor import roster, saveplan
    from tools.convert import convertdrops

    disk = tmp_path / "in.d64"
    disk.write_bytes(dos_codec.save_disk(
        bytes(payload), save1, POOL_OF_RADIANCE).to_bytes())
    party = roster.Party(str(disk))
    from editor.convert import Source
    from tools.dos import dosbox
    try:
        game_dir = dosbox.find_game("POOLRAD")
    except FileNotFoundError:
        pytest.skip("needs the DOS Pool of Radiance archives ($FR_ARCHIVES)")
    source = Source.of_snapshot(saveplan.prepare(party))
    try:
        assets = saveplan.resolve_assets(source, "dos",
                                         game_files=convertdrops.game_files,
                                         dos_folder=game_dir)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")
    return saveplan.prepare_save_as(party, "dos", tmp_path / "out", assets)


def _fixture_payload():
    from goldbox.savegame import SaveGame0, SaveGame1
    fx = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
    payload = bytearray(SaveGame0.from_prg(
        (fx / "savedgame0.bin").read_bytes()).to_bytes())
    save1 = SaveGame1.from_prg(
        (fx / "savedgame1.bin").read_bytes()).to_bytes()
    return payload, save1


def test_save_as_dos_keeps_a_blessed_c64_character_blessed(tmp_path):
    """The proving test: Bless on slot 0 reaches BRUTUS's `.SPC`; a row with
    no rule makes Save As refuse, naming the effect."""
    from editor import saveplan

    payload, save1 = _fixture_payload()
    effects.write_effect(payload, 63, 1, 0, 0x02, 0x01)
    plan = _dos_plan(tmp_path, payload, save1)
    assert isinstance(plan, saveplan.SavePlan)
    # One `.SPC` per save; only BRUTUS was blessed, so exactly one node.
    spc = plan.files["CHRDATA1.SPC"]
    assert spc.count(BLESS) == 1

    effects.write_effect(payload, 62, 13, 0, 0x02, 0x01)
    with pytest.raises(saveplan.DroppedFields) as err:
        _dos_plan(tmp_path, payload, save1)
    assert "effect 13" in str(err.value)


def _party_facts(party):
    return [(c.get("name"), [bytes(r) for r in c.get("running_effects") or ()],
             [bytes(g) for g in c.get("granted_effects") or ()])
            for c in party]


def test_a_row_owned_by_an_empty_party_slot_converts_to_nothing_and_is_no_loss():
    """A member left behind by a flight leaves his row in his old slot;
    DOS and the Amiga free a departed member's effects with him.
    Provenance: the row is staged here into the committed fixture, whose
    party is BRUTUS alone in slot 0."""
    payload, save1 = _fixture_payload()
    ordinary, _ = dos_codec.c64_party(bytes(payload), save1,
                                   game=POOL_OF_RADIANCE)
    effects.write_effect(payload, 63, 38, 3, 0x41, 0x12)
    party, _ = dos_codec.c64_party(bytes(payload), save1,
                                   game=POOL_OF_RADIANCE)
    assert not [d for c in party for d in c.dropped if "effect 38" in d]
    assert _party_facts(party) == _party_facts(ordinary)
    record, _itm, _spc, _rep = amiga_por.write_por(_brutus(party))
    assert record


@pytest.mark.parametrize("game, row_id", [
    (POOL_OF_RADIANCE, 38),
    (CURSE_OF_THE_AZURE_BONDS, 12),
    (c64_port.SECRET_OF_THE_SILVER_BLADES, 12)],
    ids=lambda v: v.key if hasattr(v, "key") else str(v))
def test_every_title_converts_a_row_owned_by_an_empty_slot_to_nothing(
        game, row_id):
    """Two members in slots 0 and 1; rows owned by the empty slots 2 and 5
    and, as the control, one owned by slot 1, which still converts."""
    bare = _synthetic_c64_party_payload(game, 2)
    ordinary, _ = dos_codec.c64_party(bytes(bare), None, game=game)
    # The later titles need bit 7 on an Enlarge magnitude (#667's open limit).
    magnitude = 0x03 if game is POOL_OF_RADIANCE else 0x83
    payload = _synthetic_c64_party_payload(
        game, 2, (row_id, 2, 0x3F, magnitude), (row_id, 5, 0x3F, magnitude),
        (row_id, 1, 0x3F, magnitude))
    party, _ = dos_codec.c64_party(bytes(payload), None, game=game)
    assert len(party) == 2
    assert not [d for c in party for d in c.dropped
                if d.startswith("running_effects:")]
    # `c64_party` hands the party back reversed, so slot 1 is first.
    assert len(party[0].get("running_effects") or ()) == 1
    assert _party_facts(party[1:]) == _party_facts(ordinary[1:])


def _roster_status(payload: bytearray, game, slot: int, value: int) -> None:
    from goldbox import c64_save, savegame
    at = (c64_save.container_for(game).roster_offset
          + slot * savegame.ROSTER_STRIDE + savegame.ROSTER_IN_USE)
    payload[at] = value


def test_a_row_owned_by_a_slot_the_game_still_lists_keeps_its_drop_line():
    """Slot 2 has a nonzero roster status but a record `looks_occupied`
    rejects: it is not an emptied slot, so the row is reported, not logged
    away."""
    game = CURSE_OF_THE_AZURE_BONDS
    payload = _synthetic_c64_party_payload(game, 2, (12, 2, 0x3F, 0x83),
                                           (12, 5, 0x3F, 0x83))
    _roster_status(payload, game, 2, 1)
    party, _ = dos_codec.c64_party(bytes(payload), None, game=game)
    lines = [d for c in party for d in c.dropped
             if d.startswith("running_effects:")]
    assert len(lines) == 1 and "party slot 2" in lines[0]


def test_an_orphan_row_is_logged_at_debug_not_dropped(caplog):
    import logging
    payload = _synthetic_c64_party_payload(
        POOL_OF_RADIANCE, 2, (38, 4, 0x3F, 0x03))
    with caplog.at_level(logging.DEBUG, logger="wish.goldbox.dos_codec"):
        dos_codec.c64_party(bytes(payload), None, game=POOL_OF_RADIANCE)
    assert [r for r in caplog.records if r.levelno == logging.DEBUG
            and "owned by party slot 4" in r.getMessage()]


def test_a_row_owned_by_a_monster_is_still_reported():
    payload = _synthetic_c64_party_payload(
        POOL_OF_RADIANCE, 2, (38, 9, 0x3F, 0x03))
    party, _ = dos_codec.c64_party(bytes(payload), None, game=POOL_OF_RADIANCE)
    assert [d for c in party for d in c.dropped if "monster 9" in d]


def test_save_as_dos_accepts_a_row_owned_by_an_empty_party_slot(tmp_path):
    """Provenance: staged here into the committed fixture; no game save is
    read."""
    from editor import saveplan

    payload, save1 = _fixture_payload()
    effects.write_effect(payload, 63, 38, 3, 0x41, 0x12)
    plan = _dos_plan(tmp_path, payload, save1)
    assert isinstance(plan, saveplan.SavePlan)


_ORPHAN_SPECIMENS = [
    pytest.param("por-666-e1-flee-orphan-rows", POOL_OF_RADIANCE, 4,
                 id="pool"),
    pytest.param("ssb-666-e1-flee-orphan-rows",
                 c64_port.SECRET_OF_THE_SILVER_BLADES, 2, id="ssb")]


@pytest.mark.parametrize("name, game, survivors", _ORPHAN_SPECIMENS)
def test_a_game_written_flight_save_converts_its_orphan_rows_to_nothing(
        name, game, survivors):
    """Specimens the C64 engine wrote after a flight that left members behind
    (`tools/registry/specimens.py`); the staged tracking rows owned by the
    emptied slots survive in them. Silver Blades' survivors' own staged rows
    carry a magnitude without bit 7, which is reported on its own line
    and is not an orphan row."""
    from test_convertmatrix import _c64_specimen

    from editor import convert
    disk = _c64_specimen(name)
    if disk is None:
        pytest.skip(f"needs the {name} specimen")
    source = convert.Source.detect(disk)
    rows = effects.active_effects(bytes(source.save0))
    assert any(r.owner < 8 for r in rows)
    party, _ = dos_codec.c64_party(bytes(source.save0), source.save1,
                                   game=game)
    assert len(party) == survivors
    lines = [d for c in party for d in c.dropped
             if d.startswith("running_effects:")]
    assert not [d for d in lines if "holds no character" in d]
    if game is POOL_OF_RADIANCE:
        assert lines == []
        assert all(len(c.get("running_effects")) == 1 for c in party)
    else:
        # The survivors' own staged rows are refused by #667's open
        # limitation (`effects.py`, "a magnitude without bit 7"); this
        # count changes when it is lifted.
        assert len(lines) == survivors


def test_a_game_written_pool_flight_save_converts_to_dos_and_the_amiga(
        tmp_path):
    from test_convertmatrix import _c64_specimen

    from editor import convert, roster, saveplan
    from tools.convert import convertdrops
    from tools.dos import dosbox

    disk = _c64_specimen("por-666-e1-flee-orphan-rows")
    if disk is None:
        pytest.skip("needs the por-666-e1-flee-orphan-rows specimen")
    try:
        game_dir = dosbox.find_game("POOLRAD")
    except FileNotFoundError:
        pytest.skip("needs the DOS Pool of Radiance archives ($FR_ARCHIVES)")
    amiga = convertdrops.amiga_game_disks(tmp_path).get(POOL_OF_RADIANCE.key)
    if amiga is None:
        pytest.skip("needs Pool of Radiance's own Amiga game disk")
    party = roster.Party(str(disk))
    source = party.source or convert.Source.detect(party.path)
    try:
        dos_assets = saveplan.resolve_assets(
            source, "dos", game_files=convertdrops.game_files,
            dos_folder=game_dir)
        amiga_assets = saveplan.resolve_assets(
            source, "amiga", game_files=convertdrops.game_files,
            amiga_disk=amiga)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")
    for port, where, assets in (("dos", tmp_path / "dos", dos_assets),
                                ("amiga", tmp_path / "out.adf", amiga_assets)):
        plan = saveplan.prepare_save_as(party, port, where, assets)
        assert plan.report.dropped == [] and saveplan.losses(plan.report) == []


# --- Save As Amiga keeps a running C64 spell ------------------------------------

#: title, C64 game constant, the first character's name, and the C64
#: magnitude byte staged for that title (Pool's committed fixture BRUTUS,
#: Curse's and Silver Blades' engine-resave specimens' PHILIPPE and
#: MORGAINE), measured on #661's own comment of 2026-09-27T09:43:18Z.
_AMIGA_BLESS_CASES = [
    pytest.param("pool", c64_port.POOL_OF_RADIANCE, "BRUTUS", 0x01, id="pool"),
    pytest.param("curse", c64_port.CURSE_OF_THE_AZURE_BONDS, "PHILIPPE", 0x05,
                 id="curse"),
    pytest.param("ssb", c64_port.SECRET_OF_THE_SILVER_BLADES, "MORGAINE", 0x05,
                 id="ssb"),
]


def _amiga_bless_disk(tmp_path, title, magnitude, refuse=False,
                      refuse_id=13, first_id=1):
    """A C64 party with a 47-minute Bless staged on slot 0, as a `.d64`
    `roster.Party` can open. `refuse=True` also stages an id-13 row, no rule
    converts (`refuse_id`), the way `test_save_as_dos_keeps_a_blessed_c64_character_blessed`
    does. Pool uses the committed fixture; the later titles use the
    engine-resave specimen `tools/dos/acceptance.py` stages for the same run.
    `None` when the later title's specimen is not on this machine.
    """
    rows = [(0x3F, first_id, 0, 0x2F, magnitude)]
    if refuse:
        rows.append((0x3E, refuse_id, 0, 0x2F, magnitude))
    disk = tmp_path / f"{title}-{'refused' if refuse else 'source'}.d64"
    if title == "pool":
        payload, save1 = _fixture_payload()
        for row in rows:
            effects.write_effect(payload, *row)
        disk.write_bytes(dos_codec.save_disk(bytes(payload), save1,
                                             POOL_OF_RADIANCE).to_bytes())
        return disk
    from tools.dos import acceptance as dosacceptance
    base = dosacceptance.c64_base(title)
    if base is None or not base.is_file():
        return None
    data, _staged = dosacceptance.staged_disk(base, title, rows)
    disk.write_bytes(data)
    return disk


def _amiga_bless_character(data: bytes, title, game, name):
    """The named character, read back off a written Amiga `.adf`, as
    `read_slot`/`read_por_characters` give it -- the object
    `amiga_later.to_neutral_later`/`amiga_por.to_neutral` reads."""
    from goldbox.amiga_adf import AmigaDisk

    written = AmigaDisk(bytearray(data))
    if title == "pool":
        drawer = amiga_savegame.por_save_drawer(written)
        chars = amiga_savegame.read_por_characters(written, "A", drawer)
    else:
        chars = amiga_savegame.read_slot(written, "A", game.key).characters
    return next(c for c in chars if c.name == name)


@pytest.mark.parametrize("title, game, name, magnitude", _AMIGA_BLESS_CASES)
def test_save_as_amiga_keeps_a_blessed_c64_character_blessed(
        tmp_path, title, game, name, magnitude):
    """The Amiga half of `test_save_as_dos_keeps_a_blessed_c64_character_
    blessed`: a C64 party under a running Bless converts to the Amiga with
    nothing dropped, and the written save's node holds the same minutes and
    magnitude; an id-13 row makes Save As refuse instead."""
    from editor import convert, roster, saveplan
    from tools.convert import convertdrops

    disk = _amiga_bless_disk(tmp_path, title, magnitude)
    if disk is None:
        pytest.skip(f"needs the {title} C64 specimen")
    party = roster.Party(str(disk))
    amiga = convertdrops.amiga_game_disks(tmp_path).get(game.key)
    if amiga is None:
        pytest.skip(f"needs {game.key}'s own Amiga game disk")
    disk_one = convertdrops.amiga_disks_one(tmp_path).get(game.key)
    if title != "pool" and disk_one is None:
        pytest.skip(f"needs {game.key}'s own Amiga disk 1")
    source = party.source or convert.Source.detect(party.path)
    try:
        assets = saveplan.resolve_assets(source, "amiga",
                                         game_files=convertdrops.game_files,
                                         amiga_disk=amiga,
                                         amiga_disk_one=disk_one)
    except saveplan.MissingAssets:
        pytest.skip(f"needs {game.key}'s own C64 disks")

    plan = saveplan.prepare_save_as(party, "amiga", tmp_path / "out.adf", assets)
    assert plan.report.dropped == [] and saveplan.losses(plan.report) == []
    (image,) = plan.files
    char = _amiga_bless_character(plan.files[image], title, game, name)
    node = bytes(char.effects[0])
    assert (node[0], node[1], node[2:4], node[4]) == (1, 0, b"\x00\x2f", magnitude)
    if title == "pool":
        running = amiga_por.to_neutral(char).get("running_effects")
    else:
        running = amiga_later.to_neutral_later(char).get("running_effects")
    assert [bytes(r)[:5] for r in running] == [
        bytes((1, 0x2F, 0x00, magnitude, 0x00))]

    # Silver Blades converts id 13 as Barkskin, so its rejection uses id 65, one
    # no DOS engine writes.
    refuse_id = 65 if title == "ssb" else 13
    refused = _amiga_bless_disk(tmp_path, title, magnitude, refuse=True,
                                refuse_id=refuse_id)
    if refused is None:
        pytest.skip(f"needs the {title} C64 specimen")
    party = roster.Party(str(refused))
    source = party.source or convert.Source.detect(party.path)
    with pytest.raises(saveplan.DroppedFields) as err:
        saveplan.prepare_save_as(party, "amiga", tmp_path / "out2.adf", assets)
    assert f"effect {refuse_id}" in str(err.value)


def test_save_as_amiga_keeps_a_silver_blades_barkskin_row(tmp_path):
    """A C64 Silver Blades Barkskin row (id 13, level 5) reaches the Amiga
    character as the node `0d 00 00 2f 05` with nothing dropped."""
    from editor import convert, roster, saveplan
    from tools.convert import convertdrops

    game = c64_port.SECRET_OF_THE_SILVER_BLADES
    disk = _amiga_bless_disk(tmp_path, "ssb", 0x05, first_id=13)
    if disk is None:
        pytest.skip("needs the ssb C64 specimen")
    party = roster.Party(str(disk))
    amiga = convertdrops.amiga_game_disks(tmp_path).get(game.key)
    if amiga is None:
        pytest.skip(f"needs {game.key}'s own Amiga game disk")
    disk_one = convertdrops.amiga_disks_one(tmp_path).get(game.key)
    if disk_one is None:
        pytest.skip(f"needs {game.key}'s own Amiga disk 1")
    source = party.source or convert.Source.detect(party.path)
    try:
        assets = saveplan.resolve_assets(source, "amiga",
                                         game_files=convertdrops.game_files,
                                         amiga_disk=amiga,
                                         amiga_disk_one=disk_one)
    except saveplan.MissingAssets:
        pytest.skip(f"needs {game.key}'s own C64 disks")
    plan = saveplan.prepare_save_as(party, "amiga", tmp_path / "out.adf", assets)
    assert plan.report.dropped == []
    (image,) = plan.files
    char = _amiga_bless_character(plan.files[image], "ssb", game, "MORGAINE")
    assert bytes(char.effects[0])[:5] == bytes.fromhex("0d0000 2f05".replace(" ", ""))


@pytest.mark.parametrize("name", ["ssb-d-engine-resave"])
def test_a_silver_blades_barkskin_row_reaches_the_dos_character_as_a_node(name):
    """The DOS twin: the row is staged here into a copy of the specimen's
    payload, as `test_a_later_title_party_wide_detect_magic_row_reaches_the_
    lowest_slot` does."""
    from test_convertmatrix import _c64_specimen

    from editor import convert
    disk = _c64_specimen(name)
    if disk is None:
        pytest.skip(f"needs the {name} specimen")
    source = convert.Source.detect(disk)
    payload = bytearray(source.save0)
    effects.write_effect(payload, effects.free_slot(payload), 13, 0, 0x2F, 0x05)
    party, _ = dos_codec.c64_party(
        bytes(payload), source.save1,
        game=c64_port.SECRET_OF_THE_SILVER_BLADES)
    nodes = [bytes(r)[:5] for c in party for r in c.get("running_effects") or ()
             if bytes(r)[0] == 13]
    assert len(nodes) == 1 and nodes[0][0] == 13 and nodes[0][3:] == b"\x05\x00"
    assert not [d for c in party for d in c.dropped if "effect 13" in d]


# --- Detect Magic, the party-wide row -----------------------------------------

DETECT = bytes((5, 0x0A, 0, 3, 0))
_PARTY_TITLES = [c64_port.POOL_OF_RADIANCE, c64_port.CURSE_OF_THE_AZURE_BONDS,
                 c64_port.SECRET_OF_THE_SILVER_BLADES]


def _title_character(game, *nodes: bytes) -> neutral.NeutralCharacter:
    char = _pool_character(*nodes)
    char.game = game
    return char


@pytest.mark.parametrize("game", _PARTY_TITLES, ids=lambda g: g.key)
def test_detect_magic_is_written_as_one_row_owned_by_the_whole_party(game):
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(_title_character(game, DETECT),
                                payload=payload, party_slot=2,
                                clock_minutes=0)
    rows = _rows(payload)
    assert rows.pop(63) == (5, 0xFF, 0x0A, 0x03)
    assert set(rows.values()) == {(0, 0, 0, 0)}
    assert not [d for d in rep.dropped + rep.losses + rep.warnings
                if "running_effects" in d]


@pytest.mark.parametrize("order", [(2, 3), (3, 2)])
def test_two_detect_magic_nodes_make_one_row_of_the_longest(order):
    payload = bytearray(0x1C00)
    nodes = {2: bytes((5, 0x04, 0, 3, 0)), 3: bytes((5, 0x0A, 0, 7, 0))}
    for slot in order:
        c64_codec.write(_pool_character(nodes[slot]), payload=payload,
                        party_slot=slot, clock_minutes=0)
    rows = _rows(payload)
    assert rows[63] == (5, 0xFF, 0x0A, 0x07)
    assert rows[62] == (0, 0, 0, 0)


def test_a_zero_minute_node_cannot_reach_the_writer():
    # `closest_duration` returns None below a minute, so this is what keeps
    # write_party_row from ever seeing it: a node at zero never expires and
    # is a granted effect, and the record refuses to be built.
    with pytest.raises(ValueError):
        c64_codec.write(_pool_character(bytes((5, 0, 0, 3, 0))),
                        payload=bytearray(0x1C00), party_slot=2,
                        clock_minutes=0)


def _staged_party(*rows):
    """The fixture's party with `rows` staged, as `c64_party` reads it."""
    payload, save1 = _fixture_payload()
    for slot, args in rows:
        effects.write_effect(payload, slot, *args)
    party, _ = dos_codec.c64_party(bytes(payload), save1,
                                   game=POOL_OF_RADIANCE)
    return party


def test_a_party_wide_detect_magic_row_reaches_dos_and_the_amiga():
    party = _staged_party((63, (5, 0xFF, 0x0A, 0x03)))
    brutus = next(c for c in party if c.get("name") == "BRUTUS")
    assert [bytes(r) for r in brutus.get("running_effects")] == \
        [DETECT + NULL]
    assert not [d for c in party for d in c.dropped if "effect 5" in d]
    _rec, _itm, spc, _rep = dos_codec.write(brutus)
    assert spc[:5] == DETECT
    record, _itm, amiga_spc, _rep = amiga_por.write_por(brutus)
    back = amiga_por.to_neutral(amiga_por.por_character(record, b"", amiga_spc))
    assert [bytes(r)[:5] for r in back.get("running_effects")] == [DETECT]


def test_detect_magic_goes_after_the_owned_rows_on_the_lowest_slot():
    party = _staged_party((63, (5, 0xFF, 0x0A, 0x03)),
                          (62, (1, 0, 0x02, 0x01)))
    brutus = next(c for c in party if c.get("name") == "BRUTUS")
    assert [bytes(r)[:5] for r in brutus.get("running_effects")] == \
        [BLESS, DETECT]


@pytest.mark.parametrize("slots", [(63, 62), (62, 63)])
def test_two_party_wide_rows_in_one_save_make_one_node_of_the_longest(slots):
    party = _staged_party((slots[0], (5, 0xFF, 0x04, 0x03)),
                          (slots[1], (5, 0xFF, 0x0A, 0x07)))
    brutus = next(c for c in party if c.get("name") == "BRUTUS")
    assert [bytes(r)[:5] for r in brutus.get("running_effects")] == \
        [bytes((5, 10, 0, 7, 0))]


def test_detect_magic_of_two_characters_leaves_one_row_of_the_longest():
    from goldbox import world_state
    payload, save1 = _fixture_payload()
    party, _ = dos_codec.c64_party(bytes(payload), save1,
                                   game=POOL_OF_RADIANCE)
    import copy
    first = party[0]
    second = copy.deepcopy(first)
    second.set("name", "CASTER", "built here")
    first.set("running_effects", [bytes((5, 4, 0, 3, 0)) + NULL], "built here")
    second.set("running_effects", [bytes((5, 10, 0, 7, 0)) + NULL],
               "built here")
    for order in ((first, second), (second, first)):
        save0 = bytearray(payload)
        for slot in range(effects.EFFECT_SLOTS):
            effects.clear_effect(save0, slot)
        state = world_state.from_c64(bytes(payload), game=POOL_OF_RADIANCE)
        report = dos_codec.write_c64_save(save0, bytearray(save1), state,
                                          list(order), game=POOL_OF_RADIANCE)
        rows = [(e.id, e.owner, e.duration, e.magnitude)
                for e in effects.active_effects(bytes(save0))]
        assert rows == [(5, 0xFF, 0x0A, 0x07)]
        assert not [d for d in report.dropped + report.losses
                    if "effect 5" in d]


GRANTED_DETECT = bytes((5, 0, 0, 3, 0))


@pytest.mark.parametrize("game", _PARTY_TITLES, ids=lambda g: g.key)
def test_a_never_expiring_dos_detect_magic_is_a_party_row_not_a_trait_slot(game):
    payload = bytearray(0x1C00)
    char = _title_character(game)
    char.set("granted_effects", [GRANTED_DETECT + NULL], "built here")
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                               clock_minutes=0)
    rows = _rows(payload)
    assert rows.pop(63) == (5, 0xFF, 0x00, 0x03)
    assert set(rows.values()) == {(0, 0, 0, 0)}
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    assert not [d for d in rep.dropped + rep.losses + rep.warnings
                if "effect 5" in d or "granted" in d]


@pytest.mark.parametrize("order", ["finite first", "granted first"])
def test_a_finite_and_a_never_expiring_detect_magic_make_one_permanent_row(
        order):
    payload = bytearray(0x1C00)
    finite = _pool_character(bytes((5, 0x04, 0, 3, 0)))
    forever = _pool_character()
    forever.set("granted_effects", [GRANTED_DETECT + NULL], "built here")
    pair = [(finite, 2), (forever, 3)]
    if order == "granted first":
        pair.reverse()
    for char, slot in pair:
        c64_codec.write(char, payload=payload, party_slot=slot,
                        clock_minutes=0)
    rows = _rows(payload)
    assert rows[63] == (5, 0xFF, 0x00, 0x03)
    assert rows[62] == (0, 0, 0, 0)


def test_a_never_expiring_party_wide_detect_magic_row_round_trips():
    party = _staged_party((63, (5, 0xFF, 0x00, 0x03)))
    brutus = next(c for c in party if c.get("name") == "BRUTUS")
    assert [bytes(r) for r in brutus.get("granted_effects")
            if bytes(r)[0] == 5] == [GRANTED_DETECT + NULL]
    assert not [r for r in brutus.get("running_effects") or ()
                if bytes(r)[0] == 5]
    assert not [d for c in party for d in c.dropped if "effect 5" in d]
    _rec, _itm, spc, _rep = dos_codec.write(brutus)
    assert spc.count(GRANTED_DETECT) == 1
    payload = bytearray(0x1C00)
    for char in party:
        c64_codec.write(char, payload=payload, party_slot=0, clock_minutes=1)
    assert [(e.id, e.owner, e.duration, e.magnitude)
            for e in effects.active_effects(bytes(payload))] == \
        [(5, 0xFF, 0x00, 0x03)]


def test_a_flagged_detect_magic_node_becomes_the_same_row_as_flag_zero():
    payload = bytearray(0x1C00)
    c64_codec.write(_pool_character(bytes((5, 10, 0, 3, 1))), payload=payload,
                    party_slot=2, clock_minutes=0)
    rows = _rows(payload)
    assert rows[63] == (5, 0xFF, 0x0A, 0x03)
    assert rows[62] == (0, 0, 0, 0)


def test_a_party_wide_detect_magic_row_makes_a_round_trip():
    party = _staged_party((63, (5, 0xFF, 0x0A, 0x03)))
    payload = bytearray(0x1C00)
    for char in party:
        c64_codec.write(char, payload=payload, party_slot=0, clock_minutes=1)
    assert [(e.id, e.owner, e.duration, e.magnitude)
            for e in effects.active_effects(bytes(payload))] == \
        [(5, 0xFF, 0x0A, 0x03)]


def test_save_as_dos_converts_a_party_wide_detect_magic_row(tmp_path):
    """Provenance: the row is staged here into the committed fixture; no
    game save is read."""
    payload, save1 = _fixture_payload()
    effects.write_effect(payload, 63, 5, 0xFF, 0x0A, 0x03)
    plan = _dos_plan(tmp_path, payload, save1)
    from editor import saveplan
    assert isinstance(plan, saveplan.SavePlan)
    assert plan.files["CHRDATA1.SPC"].count(DETECT) == 1


@pytest.mark.parametrize("name, game", [
    ("curse-h-engine-resave", c64_port.CURSE_OF_THE_AZURE_BONDS),
    ("ssb-d-engine-resave", c64_port.SECRET_OF_THE_SILVER_BLADES)])
def test_a_later_title_party_wide_detect_magic_row_reaches_the_lowest_slot(
        name, game):
    """Specimens made by driving the engine (`tools/registry/specimens.py`);
    the row is staged here into a copy of the payload."""
    from test_convertmatrix import _c64_specimen

    from editor import convert
    disk = _c64_specimen(name)
    if disk is None:
        pytest.skip(f"needs the {name} specimen")
    source = convert.Source.detect(disk)
    payload = bytearray(source.save0)
    slot = effects.free_slot(payload)
    effects.write_effect(payload, slot, 5, 0xFF, 0x0A, 0x03)
    party, _ = dos_codec.c64_party(bytes(payload), source.save1, game=game)
    nodes = [(i, [bytes(r)[:5] for r in c.get("running_effects") or ()
                  if bytes(r)[0] == 5]) for i, c in enumerate(party)]
    assert [n for _i, n in nodes if n] == [[DETECT]]
    assert nodes[-1][1] == [DETECT]
    assert not [d for c in party for d in c.dropped if "effect 5" in d]


# --- party-wide Prayer rows -----------------------------------------------------

PRAYER = bytes((49, 0x0A, 0, 3, 0))


def _prayer_m(game) -> int:
    """The C64 magnitude of a party-side level-3 Prayer: side 1 in bit 6 for
    Pool, 0 elsewhere."""
    return 0x43 if game.key == "pool-of-radiance" else 0x03


def _synthetic_c64_party_payload(game, members: int, *rows) -> bytearray:
    """A title's save payload with `members` occupied slots and `rows`
    staged, built from zeroed bytes: a capital letter and six ability scores
    are what `looks_occupied` asks of a slot, so no game file is read."""
    from goldbox import c64_save, savegame
    payload = bytearray(c64_save.container_for(game).save_size)
    for slot in range(members):
        at = savegame.HEADER_SIZE + slot * savegame.SLOT_STRIDE
        payload[at:at + 2] = b"AB"
        payload[at + 0x14:at + 0x1A] = bytes([10] * 6)
    for args in rows:
        effects.write_effect(payload, effects.free_slot(payload), *args)
    return payload


@pytest.mark.parametrize("members", [1, 3])
@pytest.mark.parametrize("game", _PARTY_TITLES, ids=lambda g: g.key)
def test_a_party_wide_prayer_row_gives_each_member_one_node_and_no_one_else(
        game, members):
    payload = _synthetic_c64_party_payload(
        game, members, (49, 0xFF, 0x0A, _prayer_m(game)))
    party, _ = dos_codec.c64_party(bytes(payload), None, game=game)
    assert len(party) == members
    for char in party:
        assert [bytes(r) for r in char.get("running_effects")] == \
            [bytes((49, 10, 0, 3, 0)) + NULL]
        assert not [d for d in char.dropped if "effect 49" in d]


@pytest.mark.parametrize("magnitude", [0x00, 0x02, 0x04, 0x06])
@pytest.mark.parametrize("deltas", list(amiga_port.AMIGA_DELTAS),
                         ids=lambda s: s.key)
def test_a_level_8_haste_row_reaches_dos_and_the_amiga(deltas, magnitude):
    """A level-8 combat cast writes Haste magnitude 0 and levels 9-11 write
    2, 4 and 6; each converts as DOS data equal to the magnitude."""
    game = c64_port.by_key(deltas.key)
    payload = _synthetic_c64_party_payload(
        game, 1, (39, 0, effects.closest_duration(5, 0), magnitude))
    party, _ = dos_codec.c64_party(bytes(payload), None, game=game)
    (member,) = party
    assert [bytes(r) for r in member.get("running_effects")] == \
        [bytes((39, 5, 0, magnitude, 0)) + NULL]
    assert not [d for d in member.dropped if "effect 39" in d]

    _rec, _itm, spc, _ = dos_codec.write(member, deltas=deltas.dos)
    nodes = [spc[i:i + 9] for i in range(0, len(spc), 9)]
    assert [bytes(n[:5]) for n in nodes if n[0] == 39] == \
        [bytes((39, 5, 0, magnitude, 0))]

    built, _rep = amiga_later.write_later(member)
    assert [(n[0], n[4]) for n in built.effects if n[0] == 39] == [
        (39, magnitude)]
    back = amiga_later.to_neutral_later(built)
    assert [bytes(r)[:5] for r in back.get("running_effects")] == \
        [bytes((39, 5, 0, magnitude, 0))]


@pytest.mark.parametrize("game", _PARTY_TITLES, ids=lambda g: g.key)
def test_prayer_is_written_as_one_row_owned_by_the_whole_party(game):
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(_title_character(game, PRAYER),
                                payload=payload, party_slot=2,
                                clock_minutes=0)
    rows = _rows(payload)
    assert rows.pop(63) == (49, 0xFF, 0x0A, _prayer_m(game))
    assert set(rows.values()) == {(0, 0, 0, 0)}
    assert not [d for d in rep.dropped + rep.losses + rep.warnings
                if "running_effects" in d]
    # The other side's data byte gives the other side's magnitude.
    payload = bytearray(0x1C00)
    c64_codec.write(_title_character(game, bytes((49, 0x0A, 0, 0x13, 0))),
                    payload=payload, party_slot=2, clock_minutes=0)
    assert _rows(payload)[63][3] == (0x03 if game.key == "pool-of-radiance"
                                     else 0x43)


def test_pool_camp_prayer_id_35_is_written_and_curse_now_converts_it():
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(
        _title_character(c64_port.POOL_OF_RADIANCE,
                         bytes((35, 0x0A, 0, 3, 0))),
        payload=payload, party_slot=2, clock_minutes=0)
    assert _rows(payload)[63] == (35, 0xFF, 0x0A, 0x03)
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(
        _title_character(c64_port.CURSE_OF_THE_AZURE_BONDS,
                         bytes((35, 0x0A, 0, 3, 0))),
        payload=payload, party_slot=2, clock_minutes=0)
    lines = [d for d in rep.dropped if d.startswith("running_effects:")]
    assert not lines
    assert _rows(payload)[63] == (35, 2, 0x0A, 0x03)


@pytest.mark.parametrize("game", _PARTY_TITLES, ids=lambda g: g.key)
def test_six_members_holding_prayer_fold_into_one_row(game):
    payload = bytearray(0x1C00)
    for slot in range(6):
        c64_codec.write(_title_character(game, PRAYER), payload=payload,
                        party_slot=slot, clock_minutes=0)
    rows = _rows(payload)
    assert rows.pop(63) == (49, 0xFF, 0x0A, _prayer_m(game))
    assert set(rows.values()) == {(0, 0, 0, 0)}
    for order in ((2, 3), (3, 2)):
        payload = bytearray(0x1C00)
        nodes = {2: bytes((49, 4, 0, 3, 0)), 3: bytes((49, 0x0A, 0, 3, 0))}
        for slot in order:
            c64_codec.write(_title_character(game, nodes[slot]),
                            payload=payload, party_slot=slot,
                            clock_minutes=0)
        rows = _rows(payload)
        assert rows[63][2] == 0x0A and rows[62] == (0, 0, 0, 0)


def _brutus(party):
    return next(c for c in party if c.get("name") == "BRUTUS")


def test_a_pool_camp_prayer_row_reaches_dos_and_the_amiga():
    party = _staged_party((63, (35, 0xFF, 0x0A, 0x03)))
    node = bytes((35, 10, 0, 3, 0))
    assert [bytes(r) for r in _brutus(party).get("running_effects")] == \
        [node + NULL]
    three, _ = dos_codec.c64_party(
        bytes(_synthetic_c64_party_payload(
            POOL_OF_RADIANCE, 3, (35, 0xFF, 0x0A, 0x03))),
        None, game=POOL_OF_RADIANCE)
    assert [[bytes(r) for r in c.get("running_effects")] for c in three] == \
        [[node + NULL]] * 3
    assert not [d for c in party for d in c.dropped if "effect 35" in d]
    _rec, _itm, spc, _rep = dos_codec.write(_brutus(party))
    assert spc[:5] == node
    record, _itm, amiga_spc, _rep = amiga_por.write_por(_brutus(party))
    back = amiga_por.to_neutral(amiga_por.por_character(record, b"", amiga_spc))
    assert [bytes(r)[:5] for r in back.get("running_effects")] == [node]


@pytest.mark.parametrize("magnitude, data", [(0x43, 0x03), (0x03, 0x13)])
def test_a_pool_combat_prayer_row_becomes_a_node_with_the_side_inverted(
        magnitude, data):
    party = _staged_party((63, (49, 0xFF, 0x0A, magnitude)))
    assert [bytes(r) for r in _brutus(party).get("running_effects")] == \
        [bytes((49, 10, 0, data, 0)) + NULL]
    three, _ = dos_codec.c64_party(
        bytes(_synthetic_c64_party_payload(
            POOL_OF_RADIANCE, 3, (49, 0xFF, 0x0A, magnitude))),
        None, game=POOL_OF_RADIANCE)
    assert [[bytes(r) for r in c.get("running_effects")] for c in three] == \
        [[bytes((49, 10, 0, data, 0)) + NULL]] * 3
    assert not [d for c in party for d in c.dropped if "effect 49" in d]


@pytest.mark.parametrize("game, row, record", [
    (POOL_OF_RADIANCE, (35, 0xFF, 0x00, 0x03), (35, 0, 0, 0x03, 0)),
    (POOL_OF_RADIANCE, (49, 0xFF, 0x00, 0x43), (49, 0, 0, 0x03, 0)),
    (c64_port.CURSE_OF_THE_AZURE_BONDS, (49, 0xFF, 0x00, 0x03),
     (49, 0, 0, 0x03, 0)),
    (c64_port.SECRET_OF_THE_SILVER_BLADES, (49, 0xFF, 0x00, 0x43),
     (49, 0, 0, 0x13, 0)),
], ids=lambda v: v.key if hasattr(v, "key") else str(v))
def test_a_never_expiring_prayer_row_is_a_granted_record_on_every_member(
        game, row, record):
    payload = _synthetic_c64_party_payload(game, 2, row)
    party, _ = dos_codec.c64_party(bytes(payload), None, game=game)
    assert len(party) == 2
    for char in party:
        assert [bytes(r) for r in char.get("granted_effects")] == \
            [bytes(record) + NULL]
        assert not [r for r in char.get("running_effects") or ()
                    if bytes(r)[0] == row[0]]
        assert not [d for d in char.dropped if f"effect {row[0]}" in d]
    fresh = bytearray(len(payload))
    for slot, char in enumerate(reversed(party)):
        c64_codec.write(char, payload=fresh, party_slot=slot, clock_minutes=0)
    assert [(e.id, e.owner, e.duration, e.magnitude)
            for e in effects.active_effects(bytes(fresh))] == [row]


def test_two_ids_at_once_keep_each_ids_own_node():
    party = _staged_party((63, (5, 0xFF, 0x0A, 0x03)),
                          (62, (49, 0xFF, 0x0A, 0x43)))
    assert [bytes(r)[:5] for r in _brutus(party).get("running_effects")] == \
        [DETECT, bytes((49, 10, 0, 3, 0))]


_PRAYER_ROUND_TRIPS = [
    (c64_port.POOL_OF_RADIANCE, (35, 0xFF, 0x0A, 0x03)),
    (c64_port.POOL_OF_RADIANCE, (49, 0xFF, 0x0A, 0x43)),
    (c64_port.POOL_OF_RADIANCE, (49, 0xFF, 0x0A, 0x03)),
    (c64_port.CURSE_OF_THE_AZURE_BONDS, (49, 0xFF, 0x0A, 0x03)),
    (c64_port.CURSE_OF_THE_AZURE_BONDS, (49, 0xFF, 0x0A, 0x43)),
    (c64_port.SECRET_OF_THE_SILVER_BLADES, (49, 0xFF, 0x0A, 0x03)),
    (c64_port.SECRET_OF_THE_SILVER_BLADES, (49, 0xFF, 0x0A, 0x43)),
]


@pytest.mark.parametrize("game, row", _PRAYER_ROUND_TRIPS,
                         ids=lambda v: v.key if hasattr(v, "key") else str(v))
def test_a_prayer_row_makes_a_c64_dos_c64_round_trip(game, row):
    payload = _synthetic_c64_party_payload(game, 2, row)
    party, _ = dos_codec.c64_party(bytes(payload), None, game=game)
    fresh = bytearray(len(payload))
    for char in party:
        c64_codec.write(char, payload=fresh, party_slot=0, clock_minutes=1)
    assert [(e.id, e.owner, e.duration, e.magnitude)
            for e in effects.active_effects(bytes(fresh))] == [row]


@pytest.mark.parametrize("game", _PARTY_TITLES, ids=lambda g: g.key)
def test_prayer_makes_a_dos_c64_dos_round_trip(game):
    import copy

    from goldbox import world_state
    payload = _synthetic_c64_party_payload(game, 2)
    party, _ = dos_codec.c64_party(bytes(payload), None, game=game)
    first, second = party[0], copy.deepcopy(party[0])
    second.set("name", "CASTER", "built here")
    first.set("running_effects", [PRAYER + NULL], "built here")
    second.set("running_effects", [], "built here")
    save0 = bytearray(payload)
    state = world_state.from_c64(bytes(payload), game=game)
    report = dos_codec.write_c64_save(save0, None, state, [first, second],
                                      game=game)
    # Literal: side 1 is bit 6 on Pool alone, where DOS keeps it inverted.
    magnitude = 0x43 if game.key == "pool-of-radiance" else 0x03
    assert [(e.id, e.owner, e.duration, e.magnitude)
            for e in effects.active_effects(bytes(save0))] == \
        [(49, 0xFF, 0x0A, magnitude)]
    assert not [d for d in report.dropped + report.losses
                if "effect 49" in d]
    back, _ = dos_codec.c64_party(bytes(save0), None, game=game)
    assert len(back) == 2
    for char in back:
        assert [bytes(r) for r in char.get("running_effects")] == \
            [PRAYER + NULL]


@pytest.mark.parametrize("row, node", [
    ((35, 0xFF, 0x0A, 0x03), bytes((35, 0x0A, 0, 3, 0))),
    ((49, 0xFF, 0x0A, 0x43), bytes((49, 0x0A, 0, 3, 0)))])
def test_save_as_dos_converts_a_prayer_row(tmp_path, row, node):
    """Provenance: the row is staged here into the committed fixture; no
    game save is read."""
    payload, save1 = _fixture_payload()
    effects.write_effect(payload, 63, *row)
    plan = _dos_plan(tmp_path, payload, save1)
    from editor import saveplan
    assert isinstance(plan, saveplan.SavePlan)
    assert plan.files["CHRDATA1.SPC"].count(node) == 1


@pytest.mark.parametrize("name, game", [
    ("curse-h-engine-resave", c64_port.CURSE_OF_THE_AZURE_BONDS),
    ("ssb-d-engine-resave", c64_port.SECRET_OF_THE_SILVER_BLADES)])
def test_a_later_title_prayer_row_reaches_every_member(name, game):
    """Specimens made by driving the engine; the row is staged into a copy."""
    from test_convertmatrix import _c64_specimen

    from editor import convert
    disk = _c64_specimen(name)
    if disk is None:
        pytest.skip(f"needs the {name} specimen")
    source = convert.Source.detect(disk)
    payload = bytearray(source.save0)
    effects.write_effect(payload, effects.free_slot(payload), 49, 0xFF, 0x0A,
                         0x03)
    party, _ = dos_codec.c64_party(bytes(payload), source.save1, game=game)
    assert len(party) == 6
    for char in party:
        assert [bytes(r)[:5] for r in char.get("running_effects") or ()
                if bytes(r)[0] == 49] == [bytes((49, 10, 0, 3, 0))]
    assert not [d for c in party for d in c.dropped if "effect 49" in d]
    fresh = bytearray(0x1C00)
    for i, char in enumerate(party):
        c64_codec.write(char, payload=fresh, party_slot=i, clock_minutes=0)
    assert [(e.id, e.owner, e.duration, e.magnitude)
            for e in effects.active_effects(bytes(fresh))] == \
        [(49, 0xFF, 0x0A, 0x03)]


# --- Fear (Curse 142, Silver Blades 111): the row and the record together ---

_FEAR_TITLES = [(c64_port.CURSE_OF_THE_AZURE_BONDS, 142),
                (c64_port.SECRET_OF_THE_SILVER_BLADES, 111)]


def _feared_character(game, eid, data=0):
    char = _title_character(game, bytes((eid, 0x0A, 0, data, 1)))
    char.set("npc", True, "built here")
    char.set("npc_control_byte", c64_codec.DOS_PC_TAKEN_OVER, "built here")
    char.set("quickfight", True, "built here")
    return char


@pytest.mark.parametrize("game, eid", _FEAR_TITLES, ids=lambda v: getattr(
    v, "key", v))
def test_a_feared_player_character_writes_as_one_not_a_companion(game, eid):
    payload = bytearray(0x1C00)
    rec, rep = c64_codec.write(_feared_character(game, eid), payload=payload,
                               party_slot=2, clock_minutes=0)
    assert _rows(payload).pop(63) == (eid, 2, 0x0A, 0x80)
    assert rec.get("flags_0b8") == 0x00
    assert rec.get("combat_side") == 0xC0
    assert not [d for d in rep.dropped + rep.losses + rep.warnings
                if "running_effects" in d or "npc_control_byte" in d]


def test_a_taken_over_player_character_with_no_fear_node_still_zeroes_0b8():
    char = neutral.NeutralCharacter("DOS", source="built here",
                                    game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    char.set("name", "X", "built here")
    char.set("npc", True, "built here")
    char.set("npc_control_byte", c64_codec.DOS_PC_TAKEN_OVER, "built here")
    rec, _rep = c64_codec.write(char)
    assert rec.get("flags_0b8") == 0x00
    assert rec.get("combat_side") & 0x40 == 0


@pytest.mark.parametrize("game, eid", _FEAR_TITLES, ids=lambda v: getattr(
    v, "key", v))
def test_a_fear_row_reads_back_as_a_player_character_taken_over(game, eid):
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, eid, 2, 0x0A, 0x80)
    rec = CharacterRecord.blank()
    rec.set("combat_side", 0xC0)
    out = c64_codec.read(rec, game=game, payload=payload, party_slot=2,
                         clock_minutes=1, source="x")
    assert bytes(out.get("running_effects")[0])[:5] == \
        bytes((eid, 10, 0, 0, 1))
    assert out.get("npc") is True
    assert out.get("npc_control_byte") == c64_codec.DOS_PC_TAKEN_OVER
    assert out.get("quickfight") is True
    assert not [d for d in out.dropped if "0x10C" in d or "bits 1-6" in d]
    _r, _i, spc, _rep = dos_codec.write(out)
    f83 = dos_port.FIELDS_BY_NAME_FOR[game.key]["field_83_87"]
    control_offset = f83.offset + (1 if f83.size == 5 else 0)
    assert _r[control_offset] == c64_codec.DOS_PC_TAKEN_OVER
    quickfight_offset = (dos_port.FIELDS_BY_NAME_FOR[game.key]
                         ["field_10c_10f"].offset + 3)
    assert _r[quickfight_offset] == 1


@pytest.mark.parametrize("game", _PARTY_TITLES, ids=lambda g: g.key)
def test_a_0x10c_bit_6_with_no_fear_row_gives_one_drop_line(game):
    payload = bytearray(0x1C00)
    rec = CharacterRecord.blank()
    rec.set("combat_side", 0xC0)
    out = c64_codec.read(rec, game=game, payload=payload, party_slot=2,
                         clock_minutes=1, source="x")
    lines = [d for d in out.dropped if "bits 1-6" in d]
    assert len(lines) == 1


@pytest.mark.parametrize("game, eid", _FEAR_TITLES, ids=lambda v: getattr(
    v, "key", v))
def test_a_fear_row_makes_a_dos_c64_dos_round_trip(game, eid):
    payload = bytearray(0x1C00)
    rec, _rep = c64_codec.write(_feared_character(game, eid, data=5),
                                payload=payload, party_slot=2,
                                clock_minutes=0)
    out = c64_codec.read(rec, game=game, payload=payload, party_slot=2,
                         clock_minutes=1, source="x")
    assert bytes(out.get("running_effects")[0])[:5] == \
        bytes((eid, 10, 0, 5, 1))
    assert out.get("npc_control_byte") == c64_codec.DOS_PC_TAKEN_OVER
    _r, _i, spc, _rep = dos_codec.write(out)
    assert spc[:5] == bytes((eid, 10, 0, 5, 1))


@pytest.mark.parametrize("record, party_row", [
    (bytes((5, 0, 0, 0x03, 0)), True),    # permanent Detect Magic, level 3
    (bytes((5, 0, 0, 0xFF, 1)), False),   # an item's grant, removed on un-ready
    (bytes((5, 0, 0, 0xFF, 0)), False),   # a C64 trait-slot id 5 written by DOS
    (bytes((5, 0, 0, 0x0C, 1)), False),   # flag 1 keeps its trait slot
], ids=["permanent-03-00", "item-grant-FF-01", "trait-FF-00", "flag-one-0C-01"])
def test_only_a_flag_zero_non_ff_id_5_record_becomes_a_party_row(
        record, party_row):
    payload = bytearray(0x1C00)
    char = _title_character(c64_port.POOL_OF_RADIANCE)
    char.set("granted_effects", [record + NULL], "built here")
    rec, _rep = c64_codec.write(char, payload=payload, party_slot=2,
                                clock_minutes=0)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    slots = bytes(rec.get_raw("item_effects"))
    if party_row:
        assert rows == [(5, 0xFF, 0x00, record[3])]
        assert slots == bytes(10)
    else:
        assert rows == []
        assert slots == bytes(9) + b"\x05"


def test_a_c64_trait_slot_id_5_stays_in_its_slot_through_dos(tmp_path):
    """A real C64 trait slot holding 5, read as the DOS record `05 00 00 FF 00`
    and written back, lands in a trait slot again and not in a party row."""
    from goldbox.savegame import SaveGame0
    payload, save1 = _fixture_payload()
    sg = SaveGame0(bytes(payload))
    slot = sg.characters[0]
    rec = slot.record
    rec.set_raw("item_effects", bytes(9) + b"\x05")
    sg.write_record(slot.index, rec)
    party, _ = dos_codec.c64_party(sg.to_bytes(), save1,
                                   game=POOL_OF_RADIANCE)
    char = next(c for c in party if c.get("name") == slot.record.name)
    trait = bytes((5, 0, 0, 0xFF, 0))
    assert 5 in char.get("innate_effects")
    dos_rec, itm, spc, _rep = dos_codec.write(char)
    assert [spc[i:i + 5] for i in range(0, len(spc), 9)
            if spc[i] == 5] == [trait]
    (tmp_path / "TESTER.SAV").write_bytes(bytes(dos_rec))
    (tmp_path / "TESTER.ITM").write_bytes(bytes(itm))
    (tmp_path / "TESTER.SPC").write_bytes(bytes(spc))
    from_dos = dos_codec.to_neutral(
        dos_codec.read_character(tmp_path / "TESTER.SAV"))
    fresh = bytearray(0x1C00)
    back, _rep = c64_codec.write(from_dos, payload=fresh, party_slot=0,
                                 clock_minutes=0)
    assert 5 in bytes(back.get_raw("item_effects"))
    assert [r for r in _rows(fresh).values() if r != (0, 0, 0, 0)] == []


def test_pools_item_grant_of_detect_magic_takes_a_party_row_and_no_byte_says_otherwise():
    """The known collision: `05 00 00 0C 00`, Pool's item-grant form for id 5,
    is byte-identical to a magnitude-12 permanent row, so it becomes a party
    row. No Pool item template grants effect 5 (#666's collision finding), so
    no save a game wrote holds this form from an item."""
    payload = bytearray(0x1C00)
    char = _title_character(c64_port.POOL_OF_RADIANCE)
    char.set("granted_effects", [bytes((5, 0, 0, 0x0C, 0)) + NULL], "built here")
    rec, _rep = c64_codec.write(char, payload=payload, party_slot=2,
                                clock_minutes=0)
    assert [r for r in _rows(payload).values() if r != (0, 0, 0, 0)] == \
        [(5, 0xFF, 0x00, 0x0C)]
    assert bytes(rec.get_raw("item_effects")) == bytes(10)


def test_a_granted_id_5_without_a_payload_takes_a_trait_slot_and_says_so():
    char = _title_character(c64_port.POOL_OF_RADIANCE)
    char.set("granted_effects", [GRANTED_DETECT + NULL], "built here")
    rec, rep = c64_codec.write(char)
    assert bytes(rec.get_raw("item_effects")) == bytes(9) + b"\x05"
    assert [d for d in rep.losses if "effect 5" in d and "never expires" in d]


def test_two_party_wide_never_expiring_rows_keep_the_higher_magnitude():
    party = _staged_party((62, (5, 0xFF, 0x00, 0x07)),
                          (63, (5, 0xFF, 0x00, 0x03)))
    granted = [bytes(r)[:5] for c in party
               for r in c.get("granted_effects") or () if bytes(r)[0] == 5]
    assert granted == [bytes((5, 0, 0, 7, 0))]


# --- Enlarge, Friends, Mirror Image and Strength -------------------------------

_POOL_G = c64_port.POOL_OF_RADIANCE
_CURSE_G = c64_port.CURSE_OF_THE_AZURE_BONDS
_SILVER_G = c64_port.SECRET_OF_THE_SILVER_BLADES
# (game, DOS node, the C64 row it becomes for party slot 2)
_VALUE_WRITES = [
    (_POOL_G, "0C 0A 00 63 01", (12, 2, 0x0A, 0xE2)),
    (_POOL_G, "26 0A 00 73 01", (38, 2, 0x0A, 0xF3)),
    (_POOL_G, "0E 0A 00 0C 01", (14, 2, 0x0A, 0x8C)),
    (_POOL_G, "1C 0A 00 03 00", (28, 2, 0x0A, 0x03)),
    (_CURSE_G, "26 0A 00 68 01", (38, 2, 0x0A, 0xB8)),
    (_SILVER_G, "0C 0A 00 7A 00", (12, 2, 0x0A, 0x8A)),
    (_CURSE_G, "0E 0A 00 05 01", (14, 2, 0x0A, 0xC5)),
    (_CURSE_G, "1C 0A 00 4F 00", (28, 2, 0x0A, 0x04)),
    (_CURSE_G, "1C 0A 00 0F 00", (28, 2, 0x0A, 0x00)),
]
_VALUE_IDS = [f"{g.key}-{n[:2]}-{n[9:11]}" for g, n, _ in _VALUE_WRITES]


@pytest.mark.parametrize("game, node, row", _VALUE_WRITES, ids=_VALUE_IDS)
def test_an_enlarge_friends_mirror_image_or_strength_node_is_written_as_a_row(
        game, node, row):
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(
        _title_character(game, bytes.fromhex(node.replace(" ", ""))),
        payload=payload, party_slot=2, clock_minutes=0)
    rows = _rows(payload)
    assert rows.pop(63) == row
    assert set(rows.values()) == {(0, 0, 0, 0)}
    assert not [d for d in rep.dropped + rep.losses + rep.warnings
                if "running_effects" in d]


@pytest.mark.parametrize("game, node, row", _VALUE_WRITES, ids=_VALUE_IDS)
def test_such_a_row_reads_back_as_the_node_DOS_holds(game, node, row):
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, row[0], row[1], row[2], row[3])
    got = _read(p, 2, game=game)
    want = bytes.fromhex(node.replace(" ", ""))
    if game is not _POOL_G and row[0] == 28:
        want = bytes((want[0], want[1], want[2], (row[3] << 4) | row[3],
                      want[4]))
    assert [bytes(r) for r in got.get("running_effects")] == [want + NULL]
    assert not _lines(got)


@pytest.mark.parametrize("game, node, row", _VALUE_WRITES, ids=_VALUE_IDS)
def test_a_written_node_reads_back_through_the_writer_and_the_reader(
        game, node, row):
    p = bytearray(0x1C00)
    c64_codec.write(_title_character(game, bytes.fromhex(node.replace(" ", ""))),
                    payload=p, party_slot=2, clock_minutes=0)
    got = _read(p, 2, game=game)
    want = bytes.fromhex(node.replace(" ", ""))
    if row[0] == 28 and game is not _POOL_G:
        # The C64 row holds no caster level, so the count fills both nibbles.
        want = want[:3] + bytes((row[3] << 4 | row[3],)) + want[4:]
    assert [bytes(r) for r in got.get("running_effects")] == [want + NULL]


def test_two_pool_strength_nodes_on_one_character_write_no_row_and_say_so():
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(
        _pool_character(bytes.fromhex("260A007301"),
                        bytes.fromhex("0C0A006301")),
        payload=payload, party_slot=2, clock_minutes=0)
    assert payload == bytearray(0x1C00)
    lines = _lines(rep)
    assert len(lines) == 2
    assert any("effect 38" in d for d in lines)
    assert any("effect 12" in d for d in lines)


def test_two_restoring_pool_rows_of_equal_minutes_read_back_as_two_lines():
    """Both rows restore, so which ends first depends on a sweep order nobody
    has read: the reader refuses rather than guess."""
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 12, 2, 0x0A, 0xE2)
    effects.write_effect(p, 62, 38, 2, 0x0A, 0xF3)
    got = _read(p, 2)
    assert got.get("running_effects") is None
    assert len(_lines(got)) == 2


def test_pool_strength_rows_no_timeline_produces_read_back_as_two_lines():
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 38, 2, effects.closest_duration(10, 0), 0x94)
    effects.write_effect(p, 62, 12, 2, effects.closest_duration(60, 0), 0x71)
    got = _read(p, 2)
    assert got.get("running_effects") is None
    assert len(_lines(got)) == 2


def test_a_pool_strength_row_reads_back_and_a_bad_node_is_one_line():
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 38, 2, 0x0A, 0xF3)
    got = _read(p, 2)
    assert [bytes(r) for r in got.get("running_effects")] \
        == [bytes((38, 10, 0, 0x73, 1)) + NULL]
    assert not _lines(got)


def test_save_as_dos_converts_a_pool_strength_row(tmp_path):
    from editor import saveplan

    payload, save1 = _fixture_payload()
    effects.write_effect(payload, 63, 38, 0, 0x0A, 0xF3)
    plan = _dos_plan(tmp_path, payload, save1)
    assert isinstance(plan, saveplan.SavePlan)
    assert plan.files["CHRDATA1.SPC"].count(bytes.fromhex("260A007301")) == 1


# --- #621: readied Gauntlets of Ogre Power, a duration-0 array row ------------
#
# `SPELLE04 $AE2D` (readying) and `$A8CC` (the magnitude) write id 38 into the
# active-effect array at duration 0, magnitude `0x80 | old strength`, never
# into a trait slot.  `c64_codec.read` used to hand every duration-0 row to
# `innate_effects`, and `dos_codec.write`/`amiga_later.write_later` then
# refused it as an unread item grant.  It now converts to DOS's own strength
# node, `26 00 00 vv 01` (`docs/230-who-reads-a-dos-effect-node.md` (c)).

ROLAND_STRENGTH_MAGNITUDE = 0xF3  # 15/0, "SPELLE04 $A8CC": (15 + 100) | 0x80.
ROLAND_STRENGTH_NODE = bytes((38, 0, 0, 0x73, 1)) + NULL


def test_a_readied_gauntlets_row_converts_to_a_dos_strength_node_not_innate():
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 38, 2, 0, ROLAND_STRENGTH_MAGNITUDE)
    got = _read(p, 2)
    assert not (got.get("innate_effects") or [])
    assert [bytes(r) for r in got.get("granted_effects")] \
        == [bytes((38, 0, 0, 0x73, 1)) + NULL]
    assert not _lines(got)


def test_an_18_76_strength_row_encodes_as_4d():
    """18/76 is `0x80 | 0x4C`; `_value_node`'s strength rule gives DOS's own
    encoding for a percentile score, `p + 1`."""
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 38, 2, 0, 0xCC)
    got = _read(p, 2)
    assert [bytes(r) for r in got.get("granted_effects")] \
        == [bytes((38, 0, 0, 0x4D, 1)) + NULL]


def test_save_as_dos_converts_a_readied_gauntlets_row(tmp_path):
    from editor import saveplan

    payload, save1 = _fixture_payload()
    effects.write_effect(payload, 63, 38, 0, 0, ROLAND_STRENGTH_MAGNITUDE)
    plan = _dos_plan(tmp_path, payload, save1)
    assert isinstance(plan, saveplan.SavePlan)
    assert plan.files["CHRDATA1.SPC"].count(ROLAND_STRENGTH_NODE) == 1


def test_save_as_amiga_converts_a_readied_gauntlets_row():
    from goldbox import amiga_por

    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 38, 2, 0, ROLAND_STRENGTH_MAGNITUDE)
    char = _read(p, 2)
    char.set("name", "ROLAND", "built here")
    _rec, _itm, spc, rep = amiga_por.write_por(char)
    amiga_node = amiga_por.amiga_por_effect_from_dos(ROLAND_STRENGTH_NODE)
    assert spc.count(amiga_node) == 1
    assert not _lines(rep)


def test_a_second_strength_source_still_refuses_rather_than_double_convert():
    """A running Enlarge (id 12, a strength-setting id) on the same character
    as the gauntlets' duration-0 row: DOS Pool holds one strength score, so
    both are refused rather than one silently overwriting the other -- the
    same guard `test_two_pool_strength_nodes_on_one_character_write_no_row_and_say_so`
    proves for the DOS -> C64 direction."""
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 38, 2, 0, ROLAND_STRENGTH_MAGNITUDE)
    effects.write_effect(p, 62, 12, 2, 0x0A, 0x63)
    got = _read(p, 2)
    assert got.get("granted_effects") is None
    assert 38 in (got.get("innate_effects") or [])
    lines = _lines(got)
    assert len(lines) == 1 and "more than one strength row" in lines[0]


def test_two_duration_0_strength_rows_are_both_refused_and_logged():
    """Two readied-gauntlets-style rows (id 38, duration 0) on one owner: the
    duration-0 fallthrough must refuse and log like the duration != 0 branch
    does (`test_a_second_strength_source_still_refuses_rather_than_double_convert`),
    not fall silently into `innate_effects` with nothing said."""
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 38, 2, 0, ROLAND_STRENGTH_MAGNITUDE)
    effects.write_effect(p, 62, 38, 2, 0, ROLAND_STRENGTH_MAGNITUDE)
    got = _read(p, 2)
    assert got.get("granted_effects") is None
    assert (got.get("innate_effects") or []).count(38) == 2
    lines = [d for d in got.dropped if "more than one strength row" in d]
    assert len(lines) == 2


# --- Haste, invisible, the combat spells, id 113 and id 13 ----------------------

# (game, DOS node, the C64 row it becomes for party slot 2)
_OWN_WRITES = (
    [(g, "27 0A 00 0C 00", (39, 2, 0x0A, 0x0C)) for g in (_POOL_G, _CURSE_G, _SILVER_G)]
    + [(g, "27 0A 00 1C 00", (39, 2, 0x0A, 0x1C)) for g in (_POOL_G, _CURSE_G, _SILVER_G)]
    + [(g, f"{eid:02X} 0A 00 05 00", (eid, 2, 0x0A, 0x05))
       for g in (_POOL_G, _CURSE_G, _SILVER_G) for eid in (21, 29, 36)]
    + [(g, "19 0A 00 0C 00", (25, 2, 0x0A, 0x0C))
       for g in (_CURSE_G, _SILVER_G)]
    + [(_SILVER_G, "71 0A 00 79 01", (113, 2, 0x0A, 0xBC))]
    + [(_CURSE_G, "92 0A 00 79 01", (146, 2, 0x0A, 0xBC))]
    + [(_CURSE_G, f"{eid:02X} 0A 00 00 00", (eid, 2, 0x0A, 0))
       for eid in (143, 50, 54)]
    + [(_SILVER_G, f"{eid:02X} 0A 00 00 00", (eid, 2, 0x0A, 0))
       for eid in (112, 50, 54)]
    + [(_CURSE_G, "49 0A 00 05 00", (73, 2, 0x0A, 0x05)),
       (_CURSE_G, "6D 0A 00 0F 00", (109, 2, 0x0A, 0x0F))]
)
_OWN_IDS = [f"{g.key}-{n[:2]}-{n[9:11]}" for g, n, _ in _OWN_WRITES]


@pytest.mark.parametrize("game, node, row", _OWN_WRITES, ids=_OWN_IDS)
def test_haste_invisible_and_the_combat_spells_are_written_as_rows(
        game, node, row):
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(
        _title_character(game, bytes.fromhex(node.replace(" ", ""))),
        payload=payload, party_slot=2, clock_minutes=0)
    rows = _rows(payload)
    assert rows.pop(63) == row
    assert set(rows.values()) == {(0, 0, 0, 0)}
    assert not [d for d in rep.dropped + rep.losses + rep.warnings
                if "running_effects" in d]


@pytest.mark.parametrize("game, node, row", _OWN_WRITES, ids=_OWN_IDS)
def test_such_a_row_reads_back_as_the_node_DOS_wrote(game, node, row):
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, row[0], row[1], row[2], row[3])
    got = _read(p, 2, game=game)
    want = bytes.fromhex(node.replace(" ", ""))
    assert [bytes(r) for r in got.get("running_effects")] == [want + NULL]
    assert not _lines(got)


def test_id_13_is_still_refused_with_a_line_and_writes_no_row():
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(
        _title_character(_CURSE_G, bytes((13, 10, 0, 5, 0))),
        payload=payload, party_slot=2, clock_minutes=0)
    assert set(_rows(payload).values()) == {(0, 0, 0, 0)}
    lines = [d for d in rep.dropped if "effect 13" in d]
    assert len(lines) == 1 and "no DOS engine writes" in lines[0]


# --- spells DOS writes at duration 0: a row, not a trait slot -----------------

_SPELL_CASES = [
    (c64_port.CURSE_OF_THE_AZURE_BONDS, "19 00 00 05 00", (25, 2, 0x00, 0x05)),
    (c64_port.POOL_OF_RADIANCE, "19 00 00 05 00", (25, 2, 0x00, 0x05)),
    (c64_port.SECRET_OF_THE_SILVER_BLADES, "21 00 00 07 00",
     (33, 2, 0x00, 0x07)),
    (c64_port.POOL_OF_RADIANCE, "22 00 00 05 01", (34, 2, 0x00, 0x85)),
    (c64_port.POOL_OF_RADIANCE, "47 00 00 0C 00", (71, 2, 0x00, 0x0C)),
    (c64_port.CURSE_OF_THE_AZURE_BONDS, "44 00 00 0A 00", (68, 2, 0x00, 0x8A)),
    (c64_port.SECRET_OF_THE_SILVER_BLADES, "44 00 00 0A 00",
     (68, 2, 0x00, 0x8A)),
]


@pytest.mark.parametrize("game,node,row", _SPELL_CASES,
                         ids=lambda v: v if isinstance(v, str) else None)
def test_a_never_expiring_spell_is_a_row_the_character_owns(game, node, row):
    node = bytes.fromhex(node)
    payload = bytearray(0x1C00)
    char = _title_character(game)
    char.set("granted_effects", [node + NULL], "built here")
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                               clock_minutes=0)
    rows = _rows(payload)
    assert rows.pop(63) == row
    assert set(rows.values()) == {(0, 0, 0, 0)}
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    assert not [d for d in rep.dropped + rep.losses + rep.warnings
                if f"effect {node[0]}" in d]
    back = _read(payload, 2, game)
    assert [bytes(r) for r in back.get("granted_effects")] == [node + NULL]
    assert node[0] not in (back.get("innate_effects") or ())
    assert not _lines(back)


# --- Feeblemind (68): the row, and INT and WIS in force -----------------------

_FEEBLE_TITLES = [c64_port.CURSE_OF_THE_AZURE_BONDS,
                  c64_port.SECRET_OF_THE_SILVER_BLADES]
_FEEBLE_NODE = bytes.fromhex("44 00 00 0A 00") + NULL


def _c64_feebleminded(game, intelligence=14, wisdom=12, row=True):
    """A C64 character as the C64 holds him: permanent scores `intelligence`
    and `wisdom`, and with the row the scores its Feeblemind leaves in force."""
    payload = bytearray(0x1C00)
    if row:
        effects.write_effect(payload, 63, 68, 2, 0, 0x8A)
    char = _read(payload, 2, game)
    in_force = {"intelligence": intelligence, "wisdom": wisdom}
    if row:
        in_force.update(effects.c64_feeblemind_scores(game.key, in_force))
    for name, score in in_force.items():
        char.set(name, score, "built here")
    char.set("abilities_second", {"intelligence": intelligence,
                                  "wisdom": wisdom}, "built here")
    return char


def _dos_pair(rec, game, name):
    at = dos_port.FIELDS_BY_NAME_FOR[game.key][name].offset
    return rec[at], rec[at + 1]


@pytest.mark.parametrize("game", _FEEBLE_TITLES, ids=lambda g: g.key)
def test_a_feebleminded_c64_character_reaches_dos_and_the_amiga_at_int_and_wis_3(
        game):
    char = _c64_feebleminded(game)
    assert [bytes(g) for g in char.get("granted_effects")] == [_FEEBLE_NODE]
    rec, _itm, spc, _rep = dos_codec.write(char)
    assert _dos_pair(rec, game, "intelligence") == (14, 3)
    assert _dos_pair(rec, game, "wisdom") == (12, 3)
    assert spc[:5] == bytes.fromhex("44 00 00 0A 00")

    built, _rep = amiga_later.write_later(char)
    back = amiga_later.to_neutral_later(built)
    assert back.get("intelligence") == 3
    assert back.get("wisdom") == 3
    assert back.get("abilities_second")["intelligence"] == 14
    assert back.get("abilities_second")["wisdom"] == 12
    assert [bytes(g)[0] for g in back.get("granted_effects")] == [68]

    # Without the row nothing is lowered. With it, an in-force INT of 5 is
    # still put to 3, because the destination's recompute sets the score to 3
    # whatever it was, higher or lower.
    ordinary, _i, _s, _r = dos_codec.write(_c64_feebleminded(game, row=False))
    assert _dos_pair(ordinary, game, "intelligence") == (14, 14)
    assert _dos_pair(ordinary, game, "wisdom") == (12, 12)
    low, _i, _s, _r = dos_codec.write(_c64_feebleminded(game, intelligence=5))
    assert _dos_pair(low, game, "intelligence") == (5, 3)


def _c64_feeble_cleric(game, row=True):
    """A level 5 cleric in the state the C64 leaves a cast in: WIS 17 permanent,
    and in force 17 in Curse and 3 in Silver Blades."""
    char = _c64_feebleminded(game, intelligence=14, wisdom=17, row=row)
    char.set("levels", {"cleric": 5}, "built here")
    char.set("spells_castable", {"cleric": (0, 0, 0, 0, 0)}, "built here")
    return char


@pytest.mark.parametrize("game", _FEEBLE_TITLES, ids=lambda g: g.key)
def test_a_feebleminded_c64_cleric_gets_no_wisdom_bonus_spells_on_dos_or_the_amiga(
        game):
    """The cleric's slots are computed from the WIS 3 the file holds, so DOS's
    load rebuild has nothing to take away and the Amiga, which does not
    rebuild, keeps no slot he should not have."""
    def slots(wisdom):
        return spells.capacity_by_class({"cleric": 5}, wisdom,
                                        game.key)["cleric"]

    def dos_slots(rec):
        field = dos_port.FIELDS_BY_NAME_FOR[game.key]["spells_castable_cleric"]
        return tuple(rec[field.offset:field.offset + field.size])

    def fit(run, depth):
        return (tuple(run) + (0,) * depth)[:depth]

    char = _c64_feeble_cleric(game)
    rec, _itm, _spc, _rep = dos_codec.write(char)
    depth = len(dos_slots(rec))
    assert dos_slots(rec) == fit(slots(3), depth)
    built, _rep = amiga_later.write_later(char)
    back = amiga_later.to_neutral_later(built)
    assert tuple(back.get("spells_castable")["cleric"])[:depth] == fit(
        slots(3), depth)

    # Control: with no row nothing lowered his WIS, so his bonus stays.
    ordinary, _itm, _spc, _rep = dos_codec.write(
        _c64_feeble_cleric(game, row=False))
    assert dos_slots(ordinary) == fit(slots(17), depth)
    assert slots(17) != slots(3)


def _foreign_feebleminded(game, port="DOS", permanent=True, node=True):
    char = neutral.NeutralCharacter(port, source="built here", game=game)
    char.set("name", "FEEBLE", "built here")
    char.set("intelligence", 3, "built here")
    char.set("wisdom", 3, "built here")
    if permanent:
        char.set("abilities_second", {"intelligence": 14, "wisdom": 12},
                 "built here")
    if node:
        char.set("granted_effects", [_FEEBLE_NODE], "built here")
    return char


def _write_c64(char, payload):
    return c64_codec.write(char, payload=payload, party_slot=2,
                           clock_minutes=0)


_C64_FEEBLE_IN_FORCE = {"curse-of-the-azure-bonds": (3, 12),
                        "secret-of-the-silver-blades": (3, 3)}


@pytest.mark.parametrize("game", _FEEBLE_TITLES, ids=lambda g: g.key)
def test_where_the_68_lands_decides_the_c64_scores(game):
    # A 68 written nowhere leaves nothing on the C64 to restore a lowered
    # score, so the character arrives with his permanent scores and no
    # Feeblemind, as the loss line says.
    full = bytearray(0x1C00)
    while (slot := effects.free_slot(full)) is not None:
        effects.write_effect(full, slot, 1, 2, 5, 1)
    rec, rep = _write_c64(_foreign_feebleminded(game), full)
    assert (rec.get("intelligence"), rec.get("wisdom")) == (14, 12)
    assert any("no free slot" in line for line in rep.losses)
    assert 68 not in [row[0] for row in _rows(full).values()]
    assert 68 not in bytes(rec.get_raw("item_effects"))

    # A trait slot is a 68 on the character, which Silver Blades' cure
    # restores from, so the title's Feeblemind scores apply.
    rec, rep = _write_c64(_foreign_feebleminded(game), None)
    assert ((rec.get("intelligence"), rec.get("wisdom"))
            == _C64_FEEBLE_IN_FORCE[game.key])
    assert 68 in bytes(rec.get_raw("item_effects"))
    assert any("trait slot" in line for line in rep.losses)


@pytest.mark.parametrize("game", _FEEBLE_TITLES, ids=lambda g: g.key)
def test_an_amiga_feebleminded_character_reaches_the_c64_at_the_c64s_feeblemind_scores(
        game):
    payload = bytearray(0x1C00)
    rec, _rep = _write_c64(_foreign_feebleminded(game, port="Amiga"), payload)
    assert ((rec.get("intelligence"), rec.get("wisdom"))
            == _C64_FEEBLE_IN_FORCE[game.key])
    assert _rows(payload).pop(63) == (68, 2, 0x00, 0x8A)


@pytest.mark.parametrize("game", _FEEBLE_TITLES, ids=lambda g: g.key)
def test_a_feeblemind_row_with_no_permanent_scores_keeps_the_scores_in_force(
        game):
    # Nothing says what the scores were before the spell, and inventing them
    # would be a guess; the row still lands, and the 3 stays.
    payload = bytearray(0x1C00)
    rec, _rep = _write_c64(_foreign_feebleminded(game, permanent=False),
                           payload)
    assert (rec.get("intelligence"), rec.get("wisdom")) == (3, 3)
    assert _rows(payload).pop(63) == (68, 2, 0x00, 0x8A)


def test_pool_of_radiance_has_no_feeblemind_to_convert():
    game = c64_port.POOL_OF_RADIANCE
    assert not effects.feebleminded(game.key, [_FEEBLE_NODE])
    payload = bytearray(0x1C00)
    rec, _rep = _write_c64(_foreign_feebleminded(game), payload)
    assert (rec.get("intelligence"), rec.get("wisdom")) == (3, 3)
    assert 68 not in [row[0] for row in _rows(payload).values()]


@pytest.mark.parametrize("game", _FEEBLE_TITLES, ids=lambda g: g.key)
@pytest.mark.parametrize("in_force", [3, 7])
def test_a_feebleminded_dos_character_reaches_the_c64_at_the_c64s_feeblemind_scores(
        game, in_force):
    def dos_character(row):
        char = neutral.NeutralCharacter("DOS", source="built here", game=game)
        char.set("name", "FEEBLE", "built here")
        char.set("intelligence", in_force, "built here")
        char.set("wisdom", in_force, "built here")
        char.set("abilities_second", {"intelligence": 14, "wisdom": 12},
                 "built here")
        if row:
            char.set("granted_effects", [_FEEBLE_NODE], "built here")
        return char

    payload = bytearray(0x1C00)
    rec, _rep = c64_codec.write(dos_character(True), payload=payload,
                                party_slot=2, clock_minutes=0)
    assert ((rec.get("intelligence"), rec.get("wisdom"))
            == _C64_FEEBLE_IN_FORCE[game.key])
    assert _rows(payload).pop(63) == (68, 2, 0x00, 0x8A)
    assert bytes(rec.get_raw("item_effects")) == bytes(10)

    kept, _rep = c64_codec.write(dos_character(False))
    assert kept.get("intelligence") == in_force
    assert kept.get("wisdom") == in_force


@pytest.mark.parametrize("node", ["19 00 00 FF 00", "19 00 00 FF 01"])
def test_the_racial_and_item_forms_of_a_spell_id_keep_their_trait_slot(node):
    payload = bytearray(0x1C00)
    char = _title_character(c64_port.CURSE_OF_THE_AZURE_BONDS)
    char.set("granted_effects", [bytes.fromhex(node) + NULL], "built here")
    rec, _rep = c64_codec.write(char, payload=payload, party_slot=2,
                                clock_minutes=0)
    assert bytes(rec.get_raw("item_effects"))[9] == 25
    assert set(_rows(payload).values()) == {(0, 0, 0, 0)}


def test_a_spell_row_goes_beside_a_running_effect():
    payload = bytearray(0x1C00)
    char = _title_character(c64_port.CURSE_OF_THE_AZURE_BONDS, BLESS)
    char.set("granted_effects", [bytes((25, 0, 0, 5, 0)) + NULL], "built here")
    c64_codec.write(char, payload=payload, party_slot=2, clock_minutes=0)
    rows = _rows(payload)
    assert rows[63] == (1, 2, 0x02, 0x01)
    assert rows[62] == (25, 2, 0x00, 0x05)


def test_a_spell_with_no_payload_takes_a_trait_slot_and_says_so():
    char = _title_character(c64_port.CURSE_OF_THE_AZURE_BONDS)
    char.set("granted_effects", [bytes((25, 0, 0, 5, 0)) + NULL], "built here")
    rec, rep = c64_codec.write(char)
    assert bytes(rec.get_raw("item_effects"))[9] == 25
    lines = [d for d in rep.losses if "effect 25, which never expires" in d]
    assert len(lines) == 1


# --- #694: a DOS strength node (readied Gauntlets of Ogre Power) converts to
# a C64 array row too, the mirror of #621's C64 -> DOS direction. Round-trip
# math: DOS vv 0x5C (92) <-> C64 magnitude 0x80 | (92 - 1) = 0xDB, the same
# `_value_row`/`_value_node` pair `never_expiring_strength_record` uses.

ADDERLY_STRENGTH_NODE = bytes((38, 0, 0, 0x5C, 1))


def test_a_dos_strength_node_is_a_row_the_character_owns_not_a_trait_slot():
    payload = bytearray(0x1C00)
    char = _title_character(c64_port.POOL_OF_RADIANCE)
    char.set("granted_effects", [ADDERLY_STRENGTH_NODE + NULL], "built here")
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                               clock_minutes=0)
    rows = _rows(payload)
    assert rows.pop(63) == (38, 2, 0x00, 0xDB)
    assert set(rows.values()) == {(0, 0, 0, 0)}
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    assert not [d for d in rep.dropped + rep.losses + rep.warnings
                if "effect 38" in d]
    back = _read(payload, 2, c64_port.POOL_OF_RADIANCE)
    assert [bytes(r) for r in back.get("granted_effects")] \
        == [ADDERLY_STRENGTH_NODE + NULL]
    assert 38 not in (back.get("innate_effects") or ())
    assert not _lines(back)


def test_a_dos_strength_node_with_no_payload_takes_a_trait_slot_and_says_so():
    char = _title_character(c64_port.POOL_OF_RADIANCE)
    char.set("granted_effects", [ADDERLY_STRENGTH_NODE + NULL], "built here")
    rec, rep = c64_codec.write(char)
    assert bytes(rec.get_raw("item_effects"))[9] == 38
    lines = [d for d in rep.losses if "effect 38, which never expires" in d]
    assert len(lines) == 1


def test_a_flagged_spell_row_of_the_wrong_kind_stays_an_innate_effect():
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 25, 2, 0x00, 0x85)
    assert 25 in _read(p, 2, CURSE_OF_THE_AZURE_BONDS).get("innate_effects")


def test_a_spell_row_reaches_dos_and_the_amiga():
    party = _staged_party((63, (25, 0, 0x00, 0x05)))
    brutus = next(c for c in party if c.get("name") == "BRUTUS")
    spell = bytes((25, 0, 0, 5, 0))
    assert [bytes(r) for r in brutus.get("granted_effects")] == [spell + NULL]
    _rec, _itm, spc, _rep = dos_codec.write(brutus)
    assert spc.count(spell) == 1
    assert spell + bytes((0xFF,)) not in spc
    record, _itm, amiga_spc, _rep = amiga_por.write_por(brutus)
    back = amiga_por.to_neutral(amiga_por.por_character(record, b"", amiga_spc))
    assert [bytes(r)[:5] for r in back.get("granted_effects")] == [spell]


def test_save_as_dos_keeps_the_caster_level_of_an_invisible_c64_character(
        tmp_path):
    from editor import saveplan

    payload, save1 = _fixture_payload()
    effects.write_effect(payload, 63, 25, 0, 0x00, 0x05)
    plan = _dos_plan(tmp_path, payload, save1)
    assert isinstance(plan, saveplan.SavePlan)
    spc = plan.files["CHRDATA1.SPC"]
    assert spc.count(bytes((25, 0, 0, 5, 0))) == 1
    assert bytes((25, 0, 0, 0xFF, 0)) not in spc


def _write_nodes(nodes, game, payload, party_slot=2):
    char = _title_character(game)
    char.set("granted_effects", [n + NULL for n in nodes], "built here")
    return c64_codec.write(char, payload=payload, party_slot=party_slot,
                           clock_minutes=0)


def test_a_spell_with_all_64_rows_taken_is_dropped_with_a_line():
    payload = bytearray(0x1C00)
    for i in range(effects.EFFECT_SLOTS):
        effects.write_effect(payload, i, 1, 3, 0x02, 0x01)
    before = bytes(payload)
    rec, rep = _write_nodes([bytes((25, 0, 0, 5, 0))],
                            c64_port.CURSE_OF_THE_AZURE_BONDS, payload)
    assert bytes(payload) == before
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    lines = [d for d in rep.losses if "effect 25, which never expires" in d
             and "no free slot" in d]
    assert len(lines) == 1


def test_several_spells_on_one_character_round_trip_as_rows():
    payload = bytearray(0x1C00)
    nodes = [bytes((25, 0, 0, 5, 0)), bytes((34, 0, 0, 6, 1)),
             bytes((51, 0, 0, 7, 0))]
    rec, rep = _write_nodes(nodes, c64_port.POOL_OF_RADIANCE, payload)
    rows = _rows(payload)
    assert [rows[i] for i in (63, 62, 61)] == [
        (25, 2, 0x00, 0x05), (34, 2, 0x00, 0x86), (51, 2, 0x00, 0x07)]
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    back = _read(payload, 2, c64_port.POOL_OF_RADIANCE)
    assert sorted(bytes(r) for r in back.get("granted_effects")) == sorted(
        n + NULL for n in nodes)
    assert not (back.get("innate_effects") or ())


def test_a_curse_set_on_one_character_round_trips_as_rows():
    payload = bytearray(0x1C00)
    nodes = [bytes((25, 0, 0, 5, 0)), bytes((33, 0, 0, 7, 0)),
             bytes((73, 0, 0, 9, 0))]
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    _write_nodes(nodes, game, payload)
    rows = _rows(payload)
    assert [rows[i] for i in (63, 62, 61)] == [
        (25, 2, 0x00, 0x05), (33, 2, 0x00, 0x07), (73, 2, 0x00, 0x09)]
    back = _read(payload, 2, game)
    assert sorted(bytes(r) for r in back.get("granted_effects")) == sorted(
        n + NULL for n in nodes)


def test_two_nodes_of_one_spell_id_take_two_rows():
    payload = bytearray(0x1C00)
    nodes = [bytes((25, 0, 0, 5, 0)), bytes((25, 0, 0, 9, 0))]
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    _write_nodes(nodes, game, payload)
    rows = _rows(payload)
    assert [rows[63], rows[62]] == [(25, 2, 0x00, 0x05),
                                    (25, 2, 0x00, 0x09)]
    back = _read(payload, 2, game)
    assert sorted(bytes(r) for r in back.get("granted_effects")) == sorted(
        n + NULL for n in nodes)


def test_a_spell_written_with_a_payload_and_no_party_slot_goes_to_slot_0():
    # No caller does this: every `write` with a payload also passes the
    # character's party slot. This pins the fallback.
    payload = bytearray(0x1C00)
    char = _title_character(c64_port.CURSE_OF_THE_AZURE_BONDS)
    char.set("granted_effects", [bytes((25, 0, 0, 5, 0)) + NULL], "built here")
    c64_codec.write(char, payload=payload, clock_minutes=0)
    assert _rows(payload)[63] == (25, 0, 0x00, 0x05)


def test_a_silver_blades_enlarge_at_23_is_written_as_the_c64s_enlarge_at_22():
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(
        _title_character(_SILVER_G, bytes.fromhex("0C0A007B00")),
        payload=payload, party_slot=2, clock_minutes=0)
    rows = _rows(payload)
    assert rows.pop(63) == (12, 2, 0x0A, 0x8A)
    assert set(rows.values()) == {(0, 0, 0, 0)}
    assert not [d for d in rep.dropped + rep.losses if "running_effects" in d]
    assert any("strength 23" in w for w in rep.warnings)


@pytest.mark.parametrize("game", _PARTY_TITLES, ids=lambda g: g.key)
def test_a_slowed_node_is_written_as_a_row_and_not_dropped(game):
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(
        _title_character(game, bytes((42, 8, 0, 5, 0))), payload=payload,
        party_slot=2, clock_minutes=0)
    assert not [d for d in rep.dropped if d.startswith("running_effects:")]
    assert 42 in [v[0] for v in _rows(payload).values()]


# --- Curse and Silver Blades charm (11): the cast's row, and 0x10C at $80 ---

_LATER_GAMES = [c64_port.CURSE_OF_THE_AZURE_BONDS,
                c64_port.SECRET_OF_THE_SILVER_BLADES]
_HANDED_BACK = ("handed back if the player presses SPACE at a bar, or any "
                "key but M or the joystick during a computer turn; DOS keeps "
                "a member at 0xB3 under the computer")
_BY_MONSTERS = ("fights for the party under the computer, where DOS fights "
                "him for the monsters")
_QUICK = ("leaves the fight at $80, still under QUICK until the player "
          "presses a key, where DOS hands him back")


def _later_charmed(game, data=0x26, flag=1, minutes=0, control=None,
                   npc=True, hostile=False):
    """A player character holding one charm node: Curse's is granted, Silver
    Blades' a running node of `minutes` (120 unless said), as each DOS engine
    writes it."""
    if game is c64_port.SECRET_OF_THE_SILVER_BLADES:
        minutes = minutes or 120
    node = bytes((effects.CHARM_ID, minutes & 0xFF, minutes >> 8, data, flag))
    char = _title_character(game)
    char.set("running_effects" if minutes else "granted_effects",
             [node + NULL], "built here")
    char.set("npc", npc, "built here")
    if control is not None:
        char.set("npc_control_byte", control, "built here")
    char.set("quickfight", True, "built here")
    char.set("hostile", hostile, "built here")
    return char


def _later_read(game, payload, side):
    rec = CharacterRecord.blank()
    rec.set("combat_side", side)
    return c64_codec.read(rec, game=game, payload=payload, party_slot=2,
                          clock_minutes=1, source="x")


@pytest.mark.parametrize("game", _LATER_GAMES, ids=lambda g: g.key)
def test_a_later_dos_charm_writes_the_casts_row_and_0x10c_80(game):
    char = _later_charmed(game, control=c64_codec.DOS_PC_TAKEN_OVER)
    rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert rec.get("combat_side") == 0x80
    assert rec.get("flags_0b8") == 0
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    assert not rep.losses
    mine = [w for w in rep.warnings if f"effect {effects.CHARM_ID}" in w
            or "running" in w]
    assert len(mine) == (3 if game is _SILVER_G else 1)
    assert any(_HANDED_BACK in w for w in mine)
    assert not any(_BY_MONSTERS in w for w in mine)
    assert any(_QUICK in w for w in mine) == (game is _SILVER_G)
    assert any("lets it run out after 120 minutes" in w
               and "the row is kept until the next fight ends" in w
               for w in mine) == (game is _SILVER_G)


@pytest.mark.parametrize("game", _LATER_GAMES, ids=lambda g: g.key)
def test_a_later_charm_by_the_monsters_writes_the_tables_form(game):
    char = _later_charmed(game, data=0xA6, hostile=True,
                          control=c64_codec.DOS_PC_TAKEN_OVER)
    rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0xC6)]
    # Bit 0 stays clear: any of bits 0-6 puts him at the monsters' edge.
    assert rec.get("combat_side") == 0x80
    assert any(_BY_MONSTERS in w for w in rep.warnings)
    assert not any("hostile is" in w for w in rep.warnings)
    assert not rep.losses


def test_a_later_charm_nodes_side_beats_a_disagreeing_hostile_flag():
    char = _later_charmed(c64_port.CURSE_OF_THE_AZURE_BONDS, hostile=True,
                          control=c64_codec.DOS_PC_TAKEN_OVER)
    rec, rep, _payload = _write_charmed(char)
    assert rec.get("combat_side") == 0x80
    assert any("hostile is True" in w for w in rep.warnings)


@pytest.mark.parametrize("game", _LATER_GAMES, ids=lambda g: g.key)
def test_a_later_charm_with_the_dispel_proof_magnitude_loses_the_own_side_bit(
        game):
    char = _later_charmed(game, data=0xFF,
                          control=c64_codec.DOS_PC_TAKEN_OVER)
    _rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0xDF)]
    assert any("$FF" in w and "Dispel Magic" in w for w in rep.warnings)


@pytest.mark.parametrize("side", [0x80, 0xC4, 0xC5, 0xC7])
@pytest.mark.parametrize("game", _LATER_GAMES, ids=lambda g: g.key)
def test_a_c64_later_charm_row_reads_back_as_a_player_character_taken_over(
        game, side):
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, effects.CHARM_ID, 2, 0, 0x86)
    out = _later_read(game, payload, side)
    charmer = side & 1
    data = charmer << 7 | (side >> 1 & 1) << 6 | 0x26
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, data, 1))]
    assert out.get("npc") is True
    assert out.get("npc_control_byte") == c64_codec.DOS_PC_TAKEN_OVER
    assert out.get("quickfight") is True
    assert out.get("hostile") is bool(charmer)
    assert not [d for d in out.dropped if "bits 1-6" in d]


@pytest.mark.parametrize("magnitude, data", [(0x86, 0x26), (0xC6, 0xA6),
                                             (0xA6, 0x66)])
def test_a_c64_later_charm_row_at_80_carries_its_sides_in_the_magnitude(
        magnitude, data):
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, effects.CHARM_ID, 2, 0, magnitude)
    out = _later_read(_SILVER_G, payload, 0x80)
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, data, 1))]
    assert out.get("hostile") is bool(data >> 7)
    assert not [d for d in out.dropped if "bits 1-6" in d]


@pytest.mark.parametrize("game", _LATER_GAMES, ids=lambda g: g.key)
@pytest.mark.parametrize("side", [0x80, 0xC5])
def test_a_later_charm_row_with_time_left_reads_back_as_a_running_node(
        game, side):
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, effects.CHARM_ID, 2, 0x05, 0x86)
    out = _later_read(game, payload, side)
    assert not [d for d in out.dropped if "bits 1-6" in d]
    node = bytes(out.get("running_effects")[0])
    assert node[3:5] == bytes((0xA6 if side & 1 else 0x26, 1))
    assert node[1] | node[2] << 8 == effects.remaining_minutes(0x05, 1)
    assert out.get("npc") is True


@pytest.mark.parametrize("data", [0x26, 0xA6, 0xE6, 0x66])
@pytest.mark.parametrize("game", _LATER_GAMES, ids=lambda g: g.key)
def test_a_later_charm_makes_a_dos_c64_dos_round_trip(game, data):
    char = _later_charmed(game, data=data, hostile=bool(data >> 7),
                          control=c64_codec.DOS_PC_TAKEN_OVER)
    _rec, _rep, payload = _write_charmed(char)
    out = _later_read(game, payload, 0x80)
    # A duration-0 row is a granted node with no minutes, which neither DOS
    # engine ages, so Silver Blades' running node comes back granted.
    node = bytes(out.get("granted_effects")[0])
    assert node[0] == effects.CHARM_ID and node[3:5] == bytes((data, 1))
    assert out.get("npc") is True and out.get("hostile") is bool(data >> 7)
    dos_rec, _i, _spc, _r = dos_codec.write(out)
    fields = dos_port.FIELDS_BY_NAME_FOR[game.key]
    f83 = fields["field_83_87"]
    assert dos_rec[f83.offset + (1 if f83.size == 5 else 0)] == \
        c64_codec.DOS_PC_TAKEN_OVER
    sides = fields["field_10c_10f"].offset
    assert dos_rec[sides + 2] == data >> 7
    assert dos_rec[sides + 3] == 1


def test_two_curse_charm_nodes_write_one_row_with_the_last_nodes_level_and_charmer():
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    char = _later_charmed(game, control=c64_codec.DOS_PC_TAKEN_OVER)
    char.set("granted_effects", [bytes((11, 0, 0, 0x26, 1)) + NULL,
                                 bytes((11, 0, 0, 0xA9, 1)) + NULL],
             "built here")
    rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0xC9)]
    assert "second charm node" in rep.sources[0x10C]
    assert not rep.losses
    assert rec.get("combat_side") == 0x80


@pytest.mark.parametrize("game", _LATER_GAMES, ids=lambda g: g.key)
def test_a_charmed_later_companion_keeps_his_byte(game):
    char = _later_charmed(game, control=0x8C)
    rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert rec.get("flags_0b8") == 0x8C
    assert rec.get("combat_side") == 0x80
    assert not rep.losses


@pytest.mark.parametrize("game", _LATER_GAMES, ids=lambda g: g.key)
def test_a_later_charm_node_with_bit_5_clear_writes_the_state_dos_sets_up_at_the_next_fight(
        game):
    char = _later_charmed(game, data=0x06, npc=False)
    rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert rec.get("combat_side") == 0x80
    assert rec.get("flags_0b8") == 0
    assert "data bit 5 is clear" in rep.sources[0x10C]
    assert not rep.losses
    assert not any("bit 5" in w for w in rep.warnings)


def test_a_blades_charms_minutes_become_a_warning_and_the_row_has_no_duration():
    char = _later_charmed(_SILVER_G, minutes=0x0203,
                          control=c64_codec.DOS_PC_TAKEN_OVER)
    _rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert any("run out after 515 minutes" in w for w in rep.warnings)


@pytest.mark.parametrize("game", _LATER_GAMES, ids=lambda g: g.key)
def test_a_later_charm_node_with_no_payload_is_a_loss(game):
    rec, rep = c64_codec.write(
        _later_charmed(game, control=c64_codec.DOS_PC_TAKEN_OVER))
    assert any(f"effect {effects.CHARM_ID}:" in line or "running" in line
               for line in rep.losses)
    assert bytes(rec.get_raw("item_effects")) == bytes(10)


@pytest.mark.parametrize("game", _LATER_GAMES, ids=lambda g: g.key)
def test_a_later_charm_node_with_no_free_effect_slot_is_a_loss_and_no_row(game):
    payload = bytearray(0x1C00)
    for i in range(effects.EFFECT_SLOTS):
        effects.write_effect(payload, i, 1, 3, 0x02, 0x01)
    before = bytes(payload)
    rec, rep, payload = _write_charmed(
        _later_charmed(game, control=c64_codec.DOS_PC_TAKEN_OVER), payload)
    assert bytes(payload) == before
    assert any("no free slot" in line for line in rep.losses)
    assert bytes(rec.get_raw("item_effects")) == bytes(10)


# --- Pool charm (11): the party cast's own row, and 0x10C left at $80 --------

_CHARM = bytes((effects.CHARM_ID, 0, 0, 0x26, 1))


def _charmed_character(share, node=_CHARM, control=c64_codec.DOS_PC_TAKEN_OVER):
    char = _title_character(c64_port.POOL_OF_RADIANCE)
    char.set("granted_effects", [node], "built here")
    char.set("npc", True, "built here")
    char.set("npc_control_byte", control, "built here")
    char.set("quickfight", True, "built here")
    char.set("hostile", False, "built here")
    char.set("treasure_share", share, "built here")
    return char


@pytest.mark.parametrize("share", [0, 1])
def test_a_dos_pool_charm_node_writes_the_c64_charm_row_and_leaves_side_80(
        share):
    payload = bytearray(0x1C00)
    rec, rep = c64_codec.write(_charmed_character(share), payload=payload,
                               party_slot=2, clock_minutes=0)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert rec.get("combat_side") == 0x80
    assert rec.get("flags_0b8") == share
    assert rec.get("treasure_share") == 0
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    assert not rep.losses


def test_a_pool_charm_node_with_no_payload_is_a_loss():
    rec, rep = c64_codec.write(_charmed_character(0))
    assert any(f"effect {effects.CHARM_ID}:" in line for line in rep.losses)
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    # The character stays engine-driven: no row was written to explain a
    # player-driven one.
    assert rec.get("flags_0b8") == c64_codec.DOS_PC_TAKEN_OVER


def test_a_pool_charm_node_with_no_free_effect_slot_is_a_loss_and_no_row():
    payload = bytearray(0x1C00)
    for slot in range(effects.EFFECT_SLOTS):
        effects.write_effect(payload, slot, 1, 5, 0x02, 1)
    before = bytes(payload)
    rec, rep = c64_codec.write(_charmed_character(0), payload=payload,
                               party_slot=2, clock_minutes=0)
    assert bytes(payload) == before
    assert any(f"effect {effects.CHARM_ID}:" in line and "no free slot" in line
               for line in rep.losses)
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    assert rec.get("flags_0b8") == c64_codec.DOS_PC_TAKEN_OVER


@pytest.mark.parametrize("count, charmer, low_bit_lost", [
    (7, 0, True),    # $96: the C64 dispels at level 6, DOS at 7
    (6, 1, True),    # $97
    (1, 0, True),
    (6, 0, False),   # $86, the C64's own form
    (7, 1, False),   # $87
    (12, 1, True),
    (15, 1, False),
])
def test_a_charm_count_whose_low_bit_differs_from_the_charmer_is_noted_and_not_a_loss(
        count, charmer, low_bit_lost):
    payload = bytearray(0x1C00)
    node = bytes((effects.CHARM_ID, 0, 0, charmer << 7 | 0x20 | count, 1))
    _rec, rep = c64_codec.write(_charmed_character(0, node),
                                payload=payload, party_slot=2,
                                clock_minutes=0)
    assert effects.charm_magnitude(count, charmer) in {
        m for (_a, _b, _c, m) in _rows(payload).values()}
    lines = [d for d in rep.warnings if "low bit" in d]
    assert bool(lines) is low_bit_lost
    if low_bit_lost:
        assert "one level off" in lines[0]
    assert not rep.losses


def test_a_pool_charm_node_no_dos_route_writes_is_a_loss_and_takes_no_row():
    payload = bytearray(0x1C00)
    rec, rep = c64_codec.write(
        _charmed_character(0, bytes((effects.CHARM_ID, 0, 0, 0x01, 1))),
        payload=payload, party_slot=2, clock_minutes=0)
    assert set(_rows(payload).values()) == {(0, 0, 0, 0)}
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    assert any(f"effect {effects.CHARM_ID}:" in line for line in rep.losses)


def test_a_pool_taken_over_byte_with_no_charm_node_is_still_a_companion():
    # No Pool engine writes 0xB3 without a charm or Animate Dead node, so a
    # bare one is written as it always was.
    char = _title_character(c64_port.POOL_OF_RADIANCE)
    char.set("npc", True, "built here")
    char.set("npc_control_byte", c64_codec.DOS_PC_TAKEN_OVER, "built here")
    char.set("status", "okay", "built here")
    rec, _rep = c64_codec.write(char, payload=bytearray(0x1C00),
                                party_slot=2, clock_minutes=0)
    assert rec.get("flags_0b8") == c64_codec.DOS_PC_TAKEN_OVER


@pytest.mark.parametrize("side", [0x80, 0xC0])
def test_a_c64_pool_charm_row_reads_back_as_a_player_character_taken_over(
        side):
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, effects.CHARM_ID, 2, 0, 0x86)
    rec = CharacterRecord.blank()
    rec.set("combat_side", side)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, 0x26, 1))]
    assert out.get("npc") is True
    assert out.get("npc_control_byte") == c64_codec.DOS_PC_TAKEN_OVER
    assert out.get("quickfight") is True
    assert out.get("hostile") is False
    assert not [d for d in out.dropped if "bits 1-6" in d]
    dos_rec, _i, _spc, _rep = dos_codec.write(out)
    f83 = dos_port.FIELDS_BY_NAME_FOR[POOL_OF_RADIANCE.key]["field_83_87"]
    control_offset = f83.offset + (1 if f83.size == 5 else 0)
    assert dos_rec[control_offset] == c64_codec.DOS_PC_TAKEN_OVER
    quickfight_offset = (dos_port.FIELDS_BY_NAME_FOR[POOL_OF_RADIANCE.key]
                         ["field_10c_10f"].offset + 3)
    assert dos_rec[quickfight_offset] == 1


@pytest.mark.parametrize("magnitude, side, data, hostile", [
    (0x87, 0xC1, 0xA7, True),    # a monster's charm, after the handler ran
    (0x87, 0x80, 0xA7, True),    # the same, before its first event
    (0x87, 0x81, 0xE7, True),    # a party member the monsters charmed
    (0x06, 0xC0, 0x26, False),   # the vampire's gaze on a party member
    (0x07, 0xC1, 0xA7, True),    # the same, charmed for the monsters
    (0x86, 0xE0, 0x66, False),   # a monster the party charmed, now his own
])
def test_a_c64_pool_charm_row_in_any_form_reads_back_as_the_node(
        magnitude, side, data, hostile):
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, effects.CHARM_ID, 2, 0, magnitude)
    rec = CharacterRecord.blank()
    rec.set("combat_side", side)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, data, 1))]
    assert not out.get("innate_effects")
    assert out.get("npc") is True
    assert out.get("npc_control_byte") == c64_codec.DOS_PC_TAKEN_OVER
    assert out.get("quickfight") is bool(side & 0x80)
    assert out.get("hostile") is hostile
    assert not [d for d in out.dropped if "bits 1-6" in d]
    dos_rec, _i, _spc, _rep = dos_codec.write(out)
    f83 = dos_port.FIELDS_BY_NAME_FOR[POOL_OF_RADIANCE.key]["field_83_87"]
    control_offset = f83.offset + (1 if f83.size == 5 else 0)
    assert dos_rec[control_offset] == c64_codec.DOS_PC_TAKEN_OVER


def test_a_c64_pool_charm_row_with_bit_5_and_no_bit_6_stays_permanent():
    # The handler sets bit 5 and bit 6 together, so this is a state no game
    # leaves; it keeps the drop line rather than a guess.
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, effects.CHARM_ID, 2, 0, 0x86)
    rec = CharacterRecord.blank()
    rec.set("combat_side", 0xA0)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert effects.CHARM_ID in out.get("innate_effects")
    assert not out.get("granted_effects")
    assert [d for d in out.dropped if "bits 1-6" in d]


@pytest.mark.parametrize("share", [0, 1])
def test_a_pool_charm_makes_a_dos_c64_dos_round_trip(share):
    payload = bytearray(0x1C00)
    rec, _rep = c64_codec.write(_charmed_character(share), payload=payload,
                                party_slot=2, clock_minutes=0)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    # The count becomes the C64 charm's fixed level, 6, not the caster's.
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, 0x26, 1))]
    assert out.get("npc_control_byte") == c64_codec.DOS_PC_TAKEN_OVER
    assert out.get("quickfight") is True
    assert out.get("treasure_share") == share


def _pc_below_0x80_character(node=_CHARM):
    # What the DOS reader gives for a control byte below 0x80: npc false and
    # no control byte.
    char = _charmed_character(0, node)
    char.set("npc", False, "built here")
    del char.fields["npc_control_byte"]
    return char


def _hostile_character(node):
    char = _charmed_character(0, node)
    char.set("hostile", True, "built here")
    return char


@pytest.mark.parametrize("share", [0, 1])
def test_a_charmed_pc_with_a_control_byte_below_0x80_writes_as_a_pc(share):
    # The C64's handler takes a player character over at his first event
    # whatever 0x0B8 holds, so he needs no control byte to convert.
    char = _pc_below_0x80_character()
    char.set("treasure_share", share, "built here")
    rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert rec.get("flags_0b8") == share
    assert rec.get("combat_side") == 0x80
    assert rec.get("treasure_share") == 0
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    assert not rep.losses
    assert not [d for d in rep.dropped if "npc_control_byte" in d]


def test_a_charmed_pc_with_a_control_byte_below_0x80_comes_back_taken_over():
    rec, _rep, payload = _write_charmed(_pc_below_0x80_character())
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, 0x26, 1))]
    assert out.get("npc_control_byte") == c64_codec.DOS_PC_TAKEN_OVER


@pytest.mark.parametrize("data, magnitude, side", [
    (0xA7, 0x87, 0x80),   # a monster charmed him, and he was the party's
    (0xE7, 0x87, 0x81),   # a monster charmed him, and he was already theirs
    (0x66, 0x86, 0x81),   # the party's charm on a monster: own side is 1
])
@pytest.mark.parametrize("build", ["pc", "companion", "pc-below-0x80"])
def test_a_charm_node_with_a_side_bit_writes_the_rows_charmer_and_own_side(
        build, data, magnitude, side):
    node = bytes((effects.CHARM_ID, 0, 0, data, 1))
    char = (_charmed_character(0, node) if build == "pc" else
            _charmed_character(2, node, control=0x93) if build == "companion"
            else _pc_below_0x80_character(node))
    # DOS's side byte holds the charmer's side while the charm stands.
    char.set("hostile", bool(data & 0x80), "built here")
    rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, magnitude)]
    assert rec.get("combat_side") == side
    assert not rep.losses
    assert not rep.warnings or all("hostile" not in w for w in rep.warnings)


@pytest.mark.parametrize("data", [0xA7, 0xE7, 0x66, 0x26])
@pytest.mark.parametrize("build", ["pc", "companion"])
def test_a_charm_with_a_side_bit_makes_a_dos_c64_dos_round_trip(build, data):
    node = bytes((effects.CHARM_ID, 0, 0, data, 1))
    char = (_charmed_character(0, node) if build == "pc" else
            _charmed_character(2, node, control=0x93))
    char.set("hostile", bool(data & 0x80), "built here")
    rec, _rep, payload = _write_charmed(char)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == [node]
    assert out.get("hostile") is bool(data & 0x80)
    assert out.get("quickfight") is True


def test_a_charm_nodes_side_beats_a_disagreeing_hostile_flag():
    # DOS's handler makes the record's side byte the charmer's, so a record
    # where they differ was not written by the game; the node decides the
    # row and the difference is logged.
    rec, rep, payload = _write_charmed(_hostile_character(_CHARM))
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert rec.get("combat_side") == 0x80
    assert not rep.losses
    assert any("hostile" in w for w in rep.warnings)


@pytest.mark.parametrize("node", [
    bytes((effects.CHARM_ID, 0x0A, 0, 0x26, 1)),
    bytes((effects.CHARM_ID, 0x34, 0x12, 0xA7, 1)),
], ids=["party", "monster"])
@pytest.mark.parametrize("build", ["pc", "companion"])
def test_a_running_charm_node_writes_the_charm_row_and_no_running_row(
        build, node):
    # A charm with time left is a running node; the C64 never ages a charm,
    # so its row has duration 0 like the granted one.
    char = _pool_character(node)
    char.set("npc", True, "built here")
    char.set("npc_control_byte",
             c64_codec.DOS_PC_TAKEN_OVER if build == "pc" else 0x93,
             "built here")
    char.set("quickfight", True, "built here")
    char.set("hostile", bool(node[3] & 0x80), "built here")
    char.set("treasure_share", 2, "built here")
    rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86 | node[3] >> 7)]
    assert rec.get("combat_side") == 0x80
    assert rec.get("flags_0b8") == (0 if build == "pc" else 0x93)
    assert not rep.losses
    assert not [d for d in rep.dropped if "effect 11" in d]


def test_a_running_charm_node_with_no_payload_is_a_loss():
    char = _pool_character(bytes((effects.CHARM_ID, 0x0A, 0, 0x26, 1)))
    char.set("npc", True, "built here")
    char.set("npc_control_byte", c64_codec.DOS_PC_TAKEN_OVER, "built here")
    _rec, rep = c64_codec.write(char)
    assert any("effect 11" in line for line in rep.losses)


def test_a_granted_and_a_running_charm_node_are_one_row():
    char = _charmed_character(0)
    char.set("running_effects",
             [bytes((effects.CHARM_ID, 0x0A, 0, 0x26, 1)) + NULL],
             "built here")
    _rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert not rep.losses


def test_two_pool_charm_nodes_write_one_row_and_no_loss():
    # Both Pool engines replace a charm with the next one (DOS
    # `GAME.OVR:0x2C540`, C64 `ECL64 $9A13`), so two nodes are one charm.
    char = _charmed_character(0)
    char.set("granted_effects", [_CHARM, _CHARM], "built here")
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                                clock_minutes=0)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert not [x for x in rep.losses if f"effect {effects.CHARM_ID}:" in x]


@pytest.mark.parametrize("control", [0x8C, 0x93, 0xFF])
def test_a_charmed_pool_companion_writes_the_charm_row_and_keeps_his_byte(
        control):
    payload = bytearray(0x1C00)
    rec, rep = c64_codec.write(_charmed_character(2, control=control),
                               payload=payload, party_slot=2,
                               clock_minutes=0)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert rec.get("flags_0b8") == control
    assert rec.get("combat_side") == 0x80
    assert rec.get("treasure_share") == 2
    assert bytes(rec.get_raw("item_effects")) == bytes(10)
    assert not rep.losses


@pytest.mark.parametrize("side", [0x80, 0xC0])
def test_a_c64_pool_charm_row_on_a_companion_reads_back_as_the_node(side):
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, effects.CHARM_ID, 2, 0, 0x86)
    rec = CharacterRecord.blank()
    rec.set("flags_0b8", 0x8C)
    rec.set("combat_side", side)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, 0x26, 1))]
    assert not out.get("innate_effects")
    assert out.get("npc") is True
    assert out.get("npc_control_byte") == 0x8C
    assert out.get("quickfight") is True
    assert out.get("hostile") is False
    assert not [d for d in out.dropped if "bits 1-6" in d]
    dos_rec, _i, _spc, _rep = dos_codec.write(out)
    f83 = dos_port.FIELDS_BY_NAME_FOR[POOL_OF_RADIANCE.key]["field_83_87"]
    control_offset = f83.offset + (1 if f83.size == 5 else 0)
    assert dos_rec[control_offset] == 0x8C
    quickfight_offset = (dos_port.FIELDS_BY_NAME_FOR[POOL_OF_RADIANCE.key]
                         ["field_10c_10f"].offset + 3)
    assert dos_rec[quickfight_offset] == 1


def test_a_charmed_pool_companion_makes_a_dos_c64_dos_round_trip():
    payload = bytearray(0x1C00)
    rec, _rep = c64_codec.write(_charmed_character(2, control=0x93),
                                payload=payload, party_slot=2,
                                clock_minutes=0)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    # The count becomes the C64 charm's fixed level, 6, not the caster's.
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, 0x26, 1))]
    assert out.get("npc") is True
    assert out.get("npc_control_byte") == 0x93
    assert out.get("quickfight") is True
    assert out.get("treasure_share") == 2


def _write_charmed(char, payload=None):
    payload = bytearray(0x1C00) if payload is None else payload
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                               clock_minutes=0)
    return rec, rep, payload


def test_two_charm_nodes_leave_the_merge_in_the_surviving_0x10c_source():
    # The combat-side note is written to 0x10C after the charm loop and
    # replaces any note the loop left there, so the merge is reported inside it.
    char = _charmed_character(2, control=0x93)
    char.set("granted_effects", [_CHARM, _CHARM], "built here")
    _rec, rep, _payload = _write_charmed(char)
    assert "second charm node" in rep.sources[0x10C]
    assert rep.sources[0x10C].startswith("combat side $")


def test_a_companion_charm_with_no_free_slot_is_a_loss_and_keeps_his_byte():
    # Pins behaviour that held before the review too.
    payload = bytearray(0x1C00)
    for slot in range(effects.EFFECT_SLOTS):
        effects.write_effect(payload, slot, 1, 5, 0x02, 1)
    before = bytes(payload)
    rec, rep, payload = _write_charmed(
        _charmed_character(2, control=0x93), payload)
    assert bytes(payload) == before
    assert any(f"effect {effects.CHARM_ID}:" in line and "no free slot" in line
               for line in rep.losses)
    assert rec.get("flags_0b8") == 0x93


def test_an_animated_companion_with_a_charm_node_and_another_byte_is_a_loss():
    # Pins behaviour that held before the review too.
    char = _charmed_character(2, control=0x93)
    char.set("status", "animated", "built here")
    _rec, rep, payload = _write_charmed(char)
    assert set(_rows(payload).values()) == {(0, 0, 0, 0)}
    assert any(f"effect {effects.CHARM_ID}:" in line for line in rep.losses)


def test_a_companion_the_monsters_charmed_writes_the_row_and_keeps_his_byte():
    char = _charmed_character(
        2, bytes((effects.CHARM_ID, 0, 0, 0xA7, 1)), control=0x93)
    char.set("hostile", True, "built here")
    rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x87)]
    assert rec.get("flags_0b8") == 0x93
    assert rec.get("combat_side") == 0x80
    assert not rep.losses


def test_a_second_charm_node_writes_the_row_when_the_first_was_refused():
    # Pins behaviour that held before the review too.
    char = _charmed_character(0)
    char.set("granted_effects",
             [bytes((effects.CHARM_ID, 0, 0, 0x01, 1)), _CHARM], "built here")
    _rec, rep, payload = _write_charmed(char)
    rows = [r for r in _rows(payload).values() if r != (0, 0, 0, 0)]
    assert rows == [(effects.CHARM_ID, 2, 0, 0x86)]
    assert len([x for x in rep.losses
                if f"effect {effects.CHARM_ID}:" in x]) == 1


def _assert_only_the_charm_low_bit_loss(rep, node):
    """No loss at all; the one-level Dispel Magic difference is a warning, when due."""
    off = (node[3] ^ node[3] >> 7) & 1
    assert not rep.losses
    assert len([w for w in rep.warnings if "low bit" in w]) == off


@pytest.mark.parametrize("count", range(16))
@pytest.mark.parametrize("data_high", [0x20, 0x60, 0xA0, 0xE0])
def test_a_charm_nodes_count_survives_a_dos_c64_dos_round_trip(
        count, data_high):
    node = bytes((effects.CHARM_ID, 0, 0, data_high | count, 1))
    char = _charmed_character(0, node)
    char.set("hostile", bool(data_high & 0x80), "built here")
    rec, rep, payload = _write_charmed(char)
    _assert_only_the_charm_low_bit_loss(rep, node)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == [node]
    assert not [d for d in out.dropped if "charm" in d.lower()]


@pytest.mark.parametrize("magnitude, data", [(0x86, 0x26), (0x87, 0xA7)])
def test_a_c64_charm_row_reads_to_dos_with_the_count_6_or_7(magnitude, data):
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, effects.CHARM_ID, 2, 0, magnitude)
    rec = CharacterRecord.blank()
    rec.set("combat_side", 0x80)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, data, 1))]


@pytest.mark.parametrize("magnitude, data", [
    (0x06, 0x26), (0x07, 0xA7), (0x86, 0x26), (0x87, 0xA7)])
def test_a_c64_charm_row_without_bit_7_reads_like_the_one_with_it(
        magnitude, data):
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, effects.CHARM_ID, 2, 0, magnitude)
    rec = CharacterRecord.blank()
    rec.set("combat_side", 0xC0)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, data, 1))]


@pytest.mark.parametrize("own", [0, 1])
@pytest.mark.parametrize("charmer", [0, 1])
def test_a_charm_writes_0x10c_with_own_side_in_bit_0_and_bits_5_and_6_clear(
        own, charmer):
    node = bytes((effects.CHARM_ID, 0, 0, charmer << 7 | own << 6 | 0x26, 1))
    char = _charmed_character(0, node)
    char.set("hostile", bool(charmer), "built here")
    rec, rep, _payload = _write_charmed(char)
    _assert_only_the_charm_low_bit_loss(rep, node)
    assert rec.get("combat_side") == 0x80 | own


@pytest.mark.parametrize("own", [0, 1])
def test_a_charm_row_beside_a_bit_6_record_keeps_the_own_side_from_bit_5(own):
    # After the C64's handler ran, bit 6 is set, bit 5 is the own side and bit
    # 0 holds the charmer ORed with whatever was there.
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 0, effects.CHARM_ID, 2, 0, 0x87)
    rec = CharacterRecord.blank()
    rec.set("combat_side", 0xC1 | own << 5)
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert [bytes(n)[:5] for n in out.get("granted_effects")] == \
        [bytes((effects.CHARM_ID, 0, 0, 0x80 | own << 6 | 0x27, 1))]
    assert not [d for d in out.dropped if "bits 1-6" in d]


def test_a_charm_with_own_side_1_and_a_fear_id_node_keeps_the_own_side():
    # Pool has no Fear row, so a Curse fear id beside a charm does not set
    # bit 6 and the own side stays in bit 0.
    node = bytes((effects.CHARM_ID, 0, 0, 0x66, 1))
    char = _charmed_character(0, node)
    char.set("granted_effects", [node, bytes((142, 0x0A, 0, 0, 1))],
             "built here")
    rec, _rep, payload = _write_charmed(char)
    assert rec.get("combat_side") == 0x81
    out = c64_codec.read(rec, game=POOL_OF_RADIANCE, payload=payload,
                         party_slot=2, clock_minutes=1, source="x")
    assert bytes(out.get("granted_effects")[0])[:5] == node


# Silver Blades' Slow Poison companion (15) and the poison itself (22), as a
# DOS save holds them: the second is the one the Amiga's removal routine
# leaves alone, the first is the one it would run a damage handler for.
_SSB_POISON = bytes((22, 120, 0, 0xFF, 1)) + NULL
_SSB_COMPANION = bytes((15, 10, 0, 0xFF, 1)) + NULL


def _slow_poisoned(game, port="DOS") -> neutral.NeutralCharacter:
    char = neutral.NeutralCharacter(port, source="built here", game=game)
    char.set("name", "PAINE", "built here")
    for ability in neutral.ABILITIES:
        char.set(ability, 12, "built here")
    char.set("running_effects", [_SSB_POISON, _SSB_COMPANION], "built here")
    return char


def _flags(built) -> dict[int, int]:
    return {bytes(n)[0]: bytes(n)[5] for n in built.effects}


def test_a_dos_silver_blades_slow_poison_companion_reaches_the_amiga_with_no_handler():
    """A DOS Silver Blades fighter saved within ten minutes of a Slow Poison
    cast would lose a hit point on the Amiga when the companion ends, because
    the Amiga's removal runs handler 15 for any non-zero flag byte."""
    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    built, _rep = amiga_later.write_later(_slow_poisoned(ssb))
    assert _flags(built) == {22: 1, 15: 0}
    assert bytes(next(n for n in built.effects if n[0] == 15))[4] == 0xFF
    # An Amiga source keeps its own bytes, and Curse is untouched.
    amiga, _rep = amiga_later.write_later(_slow_poisoned(ssb, "Amiga"))
    assert _flags(amiga) == {22: 1, 15: 1}
    curse, _rep = amiga_later.write_later(
        _slow_poisoned(c64_port.CURSE_OF_THE_AZURE_BONDS))
    assert _flags(curse) == {22: 1, 15: 1}


def test_an_amiga_flag_zero_companion_reads_back_as_the_dos_node():
    """Amiga to C64 must not refuse the node the DOS writer made, and the
    C64 row is the `$7F` one that never runs the drain."""
    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    built, _rep = amiga_later.write_later(_slow_poisoned(ssb))
    back = amiga_later.to_neutral_later(built)
    got = {bytes(r)[0]: tuple(bytes(r)[1:5])
           for r in back.get("running_effects")}
    assert got[15] == (10, 0, 0xFF, 1)
    raw = bytes(next(r for r in back.get("running_effects")
                     if bytes(r)[0] == 15))
    node = effects.RunningEffect(raw[0], int.from_bytes(raw[1:3], "little"),
                                 raw[3], raw[4])
    assert effects.c64_row(dos_port.SECRET_OF_THE_SILVER_BLADES.key,
                           node) == (15, 0x7F)


def test_a_dos_silver_blades_slow_poison_survives_the_amiga_and_back_byte_for_byte():
    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    built, _rep = amiga_later.write_later(_slow_poisoned(ssb))
    back = amiga_later.to_neutral_later(built)
    assert sorted(bytes(r) for r in back.get("running_effects")) == sorted(
        [_SSB_POISON, _SSB_COMPANION])
    _rec, _itm, spc, _ = dos_codec.write(
        back, deltas=dos_port.SECRET_OF_THE_SILVER_BLADES)
    nodes = {spc[i]: spc[i:i + 9] for i in range(0, len(spc), 9)}
    assert nodes[15] == _SSB_COMPANION and nodes[22] == _SSB_POISON


def test_a_curse_flag_zero_node_15_is_not_rewritten_on_the_way_back():
    """Only Silver Blades' node is read back with the flag on."""
    curse = c64_port.CURSE_OF_THE_AZURE_BONDS
    char = _slow_poisoned(curse)
    char.set("running_effects", [bytes((15, 10, 0, 0xFF, 0)) + NULL],
             "built here")
    built, _rep = amiga_later.write_later(char)
    back = amiga_later.to_neutral_later(built)
    assert bytes(back.get("running_effects")[0])[:5] == bytes(
        (15, 10, 0, 0xFF, 0))


def _companion_flag(built) -> int:
    return next(bytes(n)[5] for n in built.effects if n[0] == 15)


def test_an_amiga_native_flag_one_companion_stays_flag_one_through_the_reader():
    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    built, _rep = amiga_later.write_later(_slow_poisoned(ssb, "Amiga"))
    assert _companion_flag(built) == 1
    back = amiga_later.to_neutral_later(built)
    assert {bytes(r)[0]: bytes(r)[4] for r in back.get("running_effects")} == {
        22: 1, 15: 1}


def test_a_silver_blades_node_15_with_other_data_is_left_alone_both_ways():
    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    char = _slow_poisoned(ssb)
    char.set("running_effects", [bytes((15, 10, 0, 0x7F, 1)) + NULL],
             "built here")
    built, _rep = amiga_later.write_later(char)
    assert _companion_flag(built) == 1
    char.set("running_effects", [bytes((15, 10, 0, 0x7F, 0)) + NULL],
             "built here")
    built, _rep = amiga_later.write_later(char)
    assert _companion_flag(built) == 0
    back = amiga_later.to_neutral_later(built)
    assert bytes(back.get("running_effects")[0])[3:5] == bytes((0x7F, 0))


def test_a_c64_source_silver_blades_companion_is_written_with_flag_zero():
    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    built, _rep = amiga_later.write_later(_slow_poisoned(ssb, "C64"))
    assert _flags(built) == {22: 1, 15: 0}


def test_an_in_place_amiga_edit_leaves_a_native_flag_one_companion_alone():
    """`rewrite_amiga_later` renders only the record and keeps the chain it
    read, so an edit in Wish must not turn a native node 15 into flag 0."""
    from goldbox import rewrite
    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    deltas = amiga_port.SILVER_BLADES_DELTAS
    built, _rep = amiga_later.write_later(_slow_poisoned(ssb, "Amiga"),
                                          deltas=deltas)
    rec, _ = dos_codec.neutral_to_c64_record(
        amiga_later.to_neutral_later(built))
    after = c64_codec.CharacterRecord(rec.to_bytes(), rec.stored_size)
    after.gold = 4321
    out = rewrite.rewrite_amiga_later(built, rec, after, ssb)
    assert _flags(out.character) == {22: 1, 15: 1}


def test_save_as_amiga_keeps_a_slow_poisoned_silver_blades_party_harmless(
        tmp_path):
    """PAINE, in the control resave of a live DOS run, holds nodes 55, 22 (120
    minutes) and 15 (10 minutes).  Saved as an Amiga save the companion 15 has
    its handler flag clear and 22 keeps its own, and read back to DOS node 15
    is the source's bytes again."""
    from gamedata import specimen

    from editor import roster, saveplan
    from goldbox.amiga_adf import AmigaDisk
    from tools.convert import convertdrops

    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    party = roster.Party(str(specimen(
        "ssb-667-slow-poison-companion-running-resave") / "SAVGAMD.DAT"))
    amiga = convertdrops.amiga_game_disks(tmp_path).get(ssb.key)
    disk_one = convertdrops.amiga_disks_one(tmp_path).get(ssb.key)
    if amiga is None or disk_one is None:
        pytest.skip(f"needs {ssb.key}'s own Amiga disks")
    try:
        assets = saveplan.resolve_assets(party.source, "amiga",
                                         game_files=convertdrops.game_files,
                                         amiga_disk=amiga,
                                         amiga_disk_one=disk_one)
    except saveplan.MissingAssets:
        pytest.skip(f"needs {ssb.key}'s own C64 disks")
    plan = saveplan.prepare_save_as(party, "amiga", tmp_path / "out.adf",
                                    assets)
    (image,) = plan.files
    # The slot letter is the source's own (`SAVGAMD.DAT` gives `D`), where a
    # C64 source is written to `A`.
    written = AmigaDisk(bytearray(plan.files[image]))
    char = next(c for c in amiga_savegame.read_slot(
        written, party.source.slot, ssb.key).characters if c.name == "PAINE")
    assert len(char.effects) == 3
    flags = {bytes(n)[0]: bytes(n)[5] for n in char.effects}
    assert flags[15] == 0 and flags[22] == 1 and 55 in flags
    assert bytes(next(n for n in char.effects if n[0] == 15))[4] == 0xFF

    source = next(m for m in party.members if m.name == "PAINE").native
    want = {bytes(r)[0]: bytes(r) for r in
            dos_codec.to_neutral(source).get("running_effects")}
    assert bytes(want[15])[1:5] == bytes((10, 0, 0xFF, 1))
    back = amiga_later.to_neutral_later(char)
    got = {bytes(r)[0]: bytes(r) for r in back.get("running_effects")}
    assert got[15] == want[15] and got[22] == want[22]
    _rec, _itm, spc, _ = dos_codec.write(
        back, deltas=dos_port.SECRET_OF_THE_SILVER_BLADES)
    assert len(spc) % 9 == 0
    nodes = {spc[i]: spc[i:i + 9] for i in range(0, len(spc), 9)}
    assert nodes[15] == want[15] and nodes[22] == want[22]


def _write_members(game, members_granted, order=1):
    payload = bytearray(0x1C00)
    pairs = list(enumerate(members_granted))[::order]
    for slot, records in pairs:
        char = _title_character(game)
        if records:
            char.set("granted_effects", [r + NULL for r in records],
                     "built here")
        c64_codec.write(char, payload=payload, party_slot=slot,
                        clock_minutes=0)
    return payload


@pytest.mark.parametrize("order", [1, -1])
def test_members_with_different_granted_prayer_data_write_the_higher_data(
        order):
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    payload = _write_members(game, [[bytes((49, 0, 0, 0x03, 0))],
                                    [bytes((49, 0, 0, 0x13, 0))]], order)
    rows = _rows(payload)
    assert rows[63] == (49, 0xFF, 0, 0x43)
    assert rows[62] == (0, 0, 0, 0)


@pytest.mark.parametrize("order", [1, -1])
def test_pool_prayer_data_is_compared_as_data_not_as_the_c64_magnitude(order):
    # Pool inverts the side: data 0x13 is magnitude 0x03, data 0x03 is 0x43.
    payload = _write_members(POOL_OF_RADIANCE,
                             [[bytes((49, 0, 0, 0x03, 0))],
                              [bytes((49, 0, 0, 0x13, 0))]], order)
    assert _rows(payload)[63] == (49, 0xFF, 0, 0x03)


def test_a_permanent_and_a_finite_row_of_one_id_write_back_only_the_permanent():
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    payload = _synthetic_c64_party_payload(
        game, 2, (49, 0xFF, 0x0A, 0x03), (49, 0xFF, 0x00, 0x03))
    party, _ = dos_codec.c64_party(bytes(payload), None, game=game)
    fresh = bytearray(len(payload))
    for slot, char in enumerate(reversed(party)):
        c64_codec.write(char, payload=fresh, party_slot=slot, clock_minutes=0)
    assert [(e.id, e.owner, e.duration, e.magnitude)
            for e in effects.active_effects(bytes(fresh))] == \
        [(49, 0xFF, 0, 0x03)]


def test_a_granted_record_on_one_member_reads_back_as_one_party_row():
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    payload = _write_members(game, [[], [bytes((49, 0, 0, 0x03, 0))], []])
    assert [(e.id, e.owner, e.duration, e.magnitude)
            for e in effects.active_effects(bytes(payload))] == \
        [(49, 0xFF, 0, 0x03)]


@pytest.mark.parametrize("game", [POOL_OF_RADIANCE,
                                  c64_port.CURSE_OF_THE_AZURE_BONDS],
                         ids=lambda g: g.key)
@pytest.mark.parametrize("node_id", [35, 49])
def test_a_granted_record_with_data_ff_is_not_a_party_row(game, node_id):
    record = bytes((node_id, 0, 0, 0xFF, 0))
    assert not effects.is_party_granted_record(game.key, record)


def test_party_granted_magnitude_undoes_the_prayer_data_only_for_49():
    assert effects.party_granted_magnitude(
        "pool-of-radiance", bytes((49, 0, 0, 0x03, 0))) == 0x43
    assert effects.party_granted_magnitude(
        "pool-of-radiance", bytes((49, 0, 0, 0x13, 0))) == 0x03
    assert effects.party_granted_magnitude(
        "curse-of-the-azure-bonds", bytes((49, 0, 0, 0x13, 0))) == 0x43
    assert effects.party_granted_magnitude(
        "pool-of-radiance", bytes((35, 0, 0, 0x13, 0))) == 0x13
    assert effects.party_granted_magnitude(
        "pool-of-radiance", bytes((5, 0, 0, 0x0C, 0))) == 0x0C


def test_a_granted_prayer_record_survives_the_pool_amiga_writer():
    record = bytes((49, 0, 0, 0x13, 0)) + NULL
    char = _pool_character()
    char.set("granted_effects", [record], "built here")
    rec, _itm, spc, _rep = amiga_por.write_por(char)
    read = amiga_por.to_neutral(amiga_por.por_character(rec, b"", spc))
    assert [bytes(g) for g in read.get("granted_effects")] == [record]


def test_save_as_c64_converts_a_second_stinking_cloud(tmp_path):
    """The Curse specimen the game wrote after a fight kept RANGER's second
    Stinking Cloud node, `(40, 574, 0x1A, 1)`: Save As C64 gives a plan whose
    RANGER holds one id-40 row with bit 7 of its magnitude clear."""
    from gamedata import specimen

    from editor import roster, saveplan

    party = roster.Party(str(specimen(
        "curse-667-fight-strip-second-node-kept") / "SAVGAMD.DAT"))
    try:
        plan = _blessed_row_plan(party, tmp_path)
    except saveplan.MissingAssets:
        pytest.skip("needs Curse of the Azure Bonds' own C64 disks")
    assert isinstance(plan, saveplan.SavePlan)
    (_name, data), = plan.files.items()
    out = tmp_path / "written.d64"
    out.write_bytes(data)
    back = roster.Party(str(out))
    names = {m.index: m.name for m in back.members}
    rows = [e for e in effects.active_effects(back.save0.to_bytes())
            if e.id == 40]
    assert [(names[e.owner], e.magnitude) for e in rows] == [("RANGER", 0x1A)]


def test_curse_invisibility_nodes_make_one_c64_row():
    """Two `(25, n, 0xFF, 0)` nodes write one row of the longer, magnitude 0,
    and the debug log says the other was merged."""
    char = _slow_poison_character(
        c64_port.CURSE_OF_THE_AZURE_BONDS,
        bytes((25, 150, 0, 0xFF, 0)), bytes((25, 200, 0, 0xFF, 0)))
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                                clock_minutes=0)
    rows = [r for r in _rows(payload).values() if r[0] == 25]
    assert rows == [(25, 2, effects.closest_duration(200, 0), 0)]
    assert not [d for d in rep.dropped + rep.losses
                if "running_effects" in d or "effect 25" in d]
    assert len([w for w in rep.warnings if "merged" in w]) == 1


def test_a_refused_caster_level_25_node_does_not_hide_the_monster_row():
    """Merging only the `(25, n, 0xFF, 0)` nodes: a refused `(25, .., 0x0C,
    1)` beside a monster node still writes the monster's row, and no merge
    line claims otherwise."""
    char = _slow_poison_character(
        c64_port.CURSE_OF_THE_AZURE_BONDS,
        bytes((25, 150, 0, 0x0C, 1)), bytes((25, 200, 0, 0xFF, 0)))
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                                clock_minutes=0)
    assert [r[3] for r in _rows(payload).values() if r[0] == 25] == [0]
    assert not [w for w in rep.warnings if "merged" in w]


def test_two_caster_level_25_nodes_stay_two_rows():
    char = _slow_poison_character(
        c64_port.CURSE_OF_THE_AZURE_BONDS,
        bytes((25, 150, 0, 0x0C, 0)), bytes((25, 200, 0, 0x0D, 0)))
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                                clock_minutes=0)
    assert sorted(r[3] for r in _rows(payload).values() if r[0] == 25) \
        == [0x0C, 0x0D]
    assert not [w for w in rep.warnings if "merged" in w]


_HOLD = bytes((52, 0, 0, 0xFF, 0))


def _hold_write(game, *granted):
    char = _slow_poison_character(game, granted=granted)
    payload = bytearray(0x1C00)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                               clock_minutes=0)
    return rec, rep, payload


def test_curse_never_ending_hold_is_the_c64s_own_row_and_no_trait_slot():
    rec, rep, payload = _hold_write(c64_port.CURSE_OF_THE_AZURE_BONDS, _HOLD)
    assert [r for r in _rows(payload).values() if r[0] == 52] == [
        (52, 2, 0, 0)]
    assert 52 not in bytes(rec.get_raw("item_effects"))
    assert not rep.losses


def test_two_curse_holds_make_one_row():
    _rec, _rep, payload = _hold_write(
        c64_port.CURSE_OF_THE_AZURE_BONDS, _HOLD, _HOLD)
    assert [r for r in _rows(payload).values() if r[0] == 52] == [
        (52, 2, 0, 0)]


def test_curse_hold_row_reads_back_as_the_dos_node():
    rec, _rep, payload = _hold_write(c64_port.CURSE_OF_THE_AZURE_BONDS, _HOLD)
    out = c64_codec.read(rec, game=c64_port.CURSE_OF_THE_AZURE_BONDS,
                         payload=bytes(payload), party_slot=2,
                         clock_minutes=0, source="x")
    assert [bytes(g)[:5] for g in out.get("granted_effects")] == [_HOLD]
    assert 52 not in (out.get("innate_effects") or [])


@pytest.mark.parametrize("game", [c64_port.POOL_OF_RADIANCE,
                                  c64_port.SECRET_OF_THE_SILVER_BLADES],
                         ids=lambda g: g.key)
def test_other_titles_keep_a_hold_in_a_trait_slot(game):
    rec, _rep, payload = _hold_write(game, _HOLD)
    assert not [r for r in _rows(payload).values() if r[0] == 52]
    assert 52 in bytes(rec.get_raw("item_effects"))


def test_curse_hold_with_no_payload_is_reported_not_put_in_a_trait_slot():
    char = _slow_poison_character(
        c64_port.CURSE_OF_THE_AZURE_BONDS, granted=(_HOLD,))
    rec, rep = c64_codec.write(char, payload=None, party_slot=2,
                               clock_minutes=0)
    assert 52 not in bytes(rec.get_raw("item_effects"))
    assert any("effect 52" in m and "not written" in m for m in rep.losses)


def test_curse_hold_with_every_slot_taken_is_reported_not_a_trait_slot():
    char = _slow_poison_character(
        c64_port.CURSE_OF_THE_AZURE_BONDS, granted=(_HOLD,))
    payload = bytearray(0x1C00)
    for i in range(effects.EFFECT_SLOTS):
        effects.write_effect(payload, i, 63, 1, 5, 1)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                               clock_minutes=0)
    assert 52 not in bytes(rec.get_raw("item_effects"))
    assert not [r for r in _rows(payload).values() if r[0] == 52]
    assert any("effect 52" in m and "no free slot" in m for m in rep.losses)


def test_a_hand_built_c64_hold_row_reads_as_the_dos_hold_node():
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 5, 52, 2, 0, 0)
    out = c64_codec.read(CharacterRecord.blank(),
                         game=c64_port.CURSE_OF_THE_AZURE_BONDS,
                         payload=bytes(payload), party_slot=2,
                         clock_minutes=0, source="x")
    assert [bytes(g)[:5] for g in out.get("granted_effects")] == [_HOLD]


# --- Save As keeps a feebleminded character feebleminded ---------------------

#: title, C64 game, DOS archive stem, and the first character's name.
_FEEBLE_SAVE_AS = [
    pytest.param("curse", c64_port.CURSE_OF_THE_AZURE_BONDS, "CURSE",
                 "MATHEW", id="curse"),
    pytest.param("ssb", c64_port.SECRET_OF_THE_SILVER_BLADES, "SECRET",
                 "MORGAINE", id="ssb"),
]


def _feeble_c64_party(tmp_path, title):
    """The title's feebleminded C64 party as an open party, and the feebleminded
    character's permanent INT and WIS.

    Curse's is the game's own save of a real Feeblemind cast (MATHEW at INT 3,
    WIS 16 in force). Silver Blades' is the engine-resave party with the cast's
    row and INT and WIS 3 staged onto slot 0, since no cast of it was saved.
    """
    from support.doslatertitles import _c64_party

    from editor import roster
    from tests.c64.test_c64nametable import specimen_disk
    from tools.c64 import acceptance as c64acceptance
    from tools.dos import acceptance as dosacceptance

    disk = tmp_path / f"{title}-feeble.d64"
    if title == "curse":
        shutil.copyfile(specimen_disk("curse-661-feeblemind-cast-resave"), disk)
    else:
        base = dosacceptance.c64_base(title)
        if base is None or not base.is_file():
            pytest.skip(f"needs the {title} C64 specimen")
        c64acceptance.stage(base, disk, c64_port.by_key(_FEEBLE_KEYS[title]).key,
                            rows=[(0x3D, 68, 0, 0, 0x8A)],
                            record_bytes=[(0, 0x15, 3), (0, 0x16, 3)])
    _game, chars = _c64_party(disk)
    (mine,) = [c for c in chars if c.get("name") == _FEEBLE_NAMES[title]]
    # The permanent scores are `abilities_second`: the scores in force are 3
    # for a real cast.
    perm = {n: mine.get("abilities_second")[n]
            for n in effects.FEEBLEMIND_SCORES}
    return roster.Party(str(disk)), perm


_FEEBLE_KEYS = {"curse": "curse-of-the-azure-bonds",
                "ssb": "secret-of-the-silver-blades"}
_FEEBLE_NAMES = {"curse": "MATHEW", "ssb": "MORGAINE"}
#: The node and the row magnitude each title's source holds: Curse's is the
#: game's own cast, at level 1, and Silver Blades' is staged at level 10.
_FEEBLE_SOURCE_NODES = {"curse": "44 00 00 01 00", "ssb": "44 00 00 0A 00"}
_FEEBLE_MAGNITUDES = {"curse": 0x81, "ssb": 0x8A}


def _feeble_dos_plan(tmp_path, title, game, stem):
    from editor import convert, saveplan
    from tools.convert import convertdrops
    from tools.dos import dosbox

    party, perm = _feeble_c64_party(tmp_path, title)
    source = party.source or convert.Source.detect(party.path)
    try:
        game_dir = dosbox.find_game(stem)
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {game.title} archives ($FR_ARCHIVES)")
    try:
        assets = saveplan.resolve_assets(source, "dos",
                                         game_files=convertdrops.game_files,
                                         dos_folder=game_dir)
    except saveplan.MissingAssets:
        pytest.skip(f"needs {game.key}'s own C64 disks")
    plan = saveplan.prepare_save_as(party, "dos", tmp_path / "dos", assets)
    return plan, perm


def _dos_character(files, name):
    """The named character out of a written DOS save's files, neutral."""
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        folder = pathlib.Path(scratch)
        for fname, data in files.items():
            (folder / fname).write_bytes(data)
        for path in sorted(folder.glob("CHRDATA*.SAV")):
            char = dos_codec.to_neutral(dos_codec.read_character(path))
            if char.get("name") == name:
                return char
    raise AssertionError(f"{name} is not in the written files")


@pytest.mark.parametrize("destination", ["dos", "amiga"])
@pytest.mark.parametrize("title, game, stem, name", _FEEBLE_SAVE_AS)
def test_save_as_dos_keeps_a_feebleminded_c64_character_feebleminded(
        tmp_path, destination, title, game, stem, name):
    from editor import saveplan

    if destination == "dos":
        plan, perm = _feeble_dos_plan(tmp_path, title, game, stem)
        assert isinstance(plan, saveplan.SavePlan)
        assert saveplan.losses(plan.report) == []
        char = _dos_character(plan.files, name)
    else:
        from tools.convert import convertdrops

        party, perm = _feeble_c64_party(tmp_path, title)
        amiga = convertdrops.amiga_game_disks(tmp_path).get(game.key)
        if amiga is None:
            pytest.skip(f"needs {game.key}'s own Amiga game disk")
        disk_one = convertdrops.amiga_disks_one(tmp_path).get(game.key)
        if disk_one is None:
            pytest.skip(f"needs {game.key}'s own Amiga disk 1")
        from editor import convert
        source = party.source or convert.Source.detect(party.path)
        try:
            assets = saveplan.resolve_assets(
                source, "amiga", game_files=convertdrops.game_files,
                amiga_disk=amiga, amiga_disk_one=disk_one)
        except saveplan.MissingAssets:
            pytest.skip(f"needs {game.key}'s own C64 disks")
        plan = saveplan.prepare_save_as(party, "amiga", tmp_path / "out.adf",
                                        assets)
        assert saveplan.losses(plan.report) == []
        (image,) = plan.files
        char = amiga_later.to_neutral_later(
            _amiga_bless_character(plan.files[image], title, game, name))
    assert (char.get("intelligence"), char.get("wisdom")) == (3, 3)
    second = char.get("abilities_second")
    assert {n: second[n] for n in effects.FEEBLEMIND_SCORES} == perm
    assert bytes.fromhex(_FEEBLE_SOURCE_NODES[title]) in [
        bytes(g)[:5] for g in char.get("granted_effects")]
    # His cleric slots come from the WIS 3 the file holds, so DOS's load
    # rebuild has nothing to take away.
    want = spells.capacity_by_class(dict(char.get("levels")), 3,
                                    game.key).get("cleric", ())
    got = tuple(char.get("spells_castable").get("cleric", ()))
    assert got == (tuple(want) + (0,) * len(got))[:len(got)]


def _feeble_c64_plan(tmp_path, title, game, stem):
    """Save As C64 of the DOS folder the first plan wrote."""
    from editor import roster, saveplan

    plan, perm = _feeble_dos_plan(tmp_path, title, game, stem)
    folder = tmp_path / "dos"
    folder.mkdir()
    for fname, data in plan.files.items():
        (folder / fname).write_bytes(data)
    back = roster.Party(str(folder))
    from editor import convert
    from tools.convert import convertdrops
    source = back.source or convert.Source.detect(back.path)
    assets = saveplan.resolve_assets(source, "c64",
                                     game_files=convertdrops.game_files)
    return back, assets, perm


@pytest.mark.parametrize("title, game, stem, name", _FEEBLE_SAVE_AS)
def test_save_as_c64_keeps_a_feebleminded_dos_character_feebleminded(
        tmp_path, title, game, stem, name):
    from support.doslatertitles import _c64_party

    from editor import roster, saveplan

    try:
        back, assets, perm = _feeble_c64_plan(tmp_path, title, game, stem)
    except saveplan.MissingAssets:
        pytest.skip(f"needs {game.key}'s own C64 disks")
    plan = saveplan.prepare_save_as(back, "c64", tmp_path / "out.d64", assets)
    assert saveplan.losses(plan.report) == []
    (image,) = plan.files
    written = tmp_path / "read-back.d64"
    written.write_bytes(plan.files[image])
    _game, chars = _c64_party(written)
    (char,) = [c for c in chars if c.get("name") == name]
    assert ({n: char.get(n) for n in effects.FEEBLEMIND_SCORES}
            == effects.c64_feeblemind_scores(game.key, perm))
    rows = effects.active_effects(roster.Party(str(written)).save0.to_bytes())
    mine = [(e.id, e.duration, e.magnitude) for e in rows if e.id == 68]
    assert mine == [(68, 0, _FEEBLE_MAGNITUDES[title])]


@pytest.mark.parametrize("title, game, stem, name", _FEEBLE_SAVE_AS)
def test_save_as_c64_refuses_a_feeblemind_row_with_no_free_slot(
        tmp_path, monkeypatch, title, game, stem, name):
    """A row that cannot land leaves the character with his permanent scores
    and no Feeblemind, so the 3s his source held are reported lost."""
    from editor import saveplan

    try:
        back, assets, perm = _feeble_c64_plan(tmp_path, title, game, stem)
    except saveplan.MissingAssets:
        pytest.skip(f"needs {game.key}'s own C64 disks")
    monkeypatch.setattr(effects, "free_slot", lambda payload: None)
    with pytest.raises(saveplan.DroppedFields) as err:
        saveplan.prepare_save_as(back, "c64", tmp_path / "out.d64", assets)
    assert "effect 68" in str(err.value)
    assert f"intelligence: 3 arrived as {perm['intelligence']}" in str(err.value)


# --- a running Strength converts to the destination's own score (#667) --------

_CURSE_KEY = "curse-of-the-azure-bonds"
_SSB_KEY = "secret-of-the-silver-blades"
_NODE_101 = bytes((38, 10, 0, 101, 1))


def _strength_character(port, game, roll, permanent, in_force, levels,
                        *extra_nodes):
    char = neutral.NeutralCharacter(port, source="built here", game=game)
    char.set("name", "STRONG", "built here")
    char.set("running_effects",
             [bytes((38, 10, 0, 100 + roll, 1)) + NULL]
             + [n + NULL for n in extra_nodes], "built here")
    char.set("strength", in_force[0], "built here")
    char.set("exceptional_strength", in_force[1], "built here")
    char.set("abilities_second",
             {**{n: 10 for n in neutral.ABILITIES},
              "strength": permanent[0], "exceptional_strength": permanent[1]},
             "built here")
    char.set("levels", levels, "built here")
    return char


def _c64_strength(char):
    rec, _rep = c64_codec.write(char, payload=bytearray(0x1C00), party_slot=2,
                                clock_minutes=0)
    return ((rec.get("strength"), rec.get("exceptional_strength")),
            (rec.get_raw("abilities_second")[0],
             rec.get_raw("abilities_second")[6]), rec)


def _dos_strength(char, **kwargs):
    rec, _itm, _spc, rep = dos_codec.write(char, **kwargs)
    read = dos_codec.to_neutral(dos_codec.DosCharacter(rec))
    return ((read.get("strength"), read.get("exceptional_strength")),
            (read.get("abilities_second")["strength"],
             read.get("abilities_second")["exceptional_strength"]), rep)


@pytest.mark.parametrize("key", [_CURSE_KEY, _SSB_KEY])
@pytest.mark.parametrize("roll, permanent, in_force, levels, want", [
    (8, (17, 0), (18, 0), {"cleric": 5}, (18, 70)),
    (3, (15, 0), (18, 0), {"paladin": 5}, (18, 0)),
    (3, (18, 12), (18, 42), {"fighter": 4}, (18, 42)),
    (3, (18, 12), (18, 72), {"fighter": 4}, (18, 42)),
    (1, (18, 25), (18, 100), {"fighter": 4}, (18, 35)),
    (1, (18, 0), (18, 100), {"magic-user": 5}, (18, 10)),
])
def test_a_dos_running_strength_arrives_at_the_c64s_own_score(
        key, roll, permanent, in_force, levels, want):
    game = c64_port.by_key(key)
    char = _strength_character("DOS", game, roll, permanent, in_force, levels)
    score, kept, rec = _c64_strength(char)
    assert score == want
    # The permanent score and the roll's row are untouched.
    assert kept == permanent
    assert rec.get("strength_index") == c64_codec.strength_index(*want)
    payload = bytearray(0x1C00)
    c64_codec.write(char, payload=payload, party_slot=2, clock_minutes=0)
    assert [r[3] for r in _rows(payload).values() if r[0] == 38] == [
        effects.later_ability_magnitude(roll, (100 + roll) & 0x0F)]


def test_the_c64_strength_score_reaches_the_hit_step_and_the_report():
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    char = _strength_character("DOS", game, 8, (17, 0), (18, 0),
                               {"cleric": 5})
    rec, rep = c64_codec.write(char, payload=bytearray(0x1C00), party_slot=2,
                               clock_minutes=0)
    assert c64_codec.c64_strength_hit_step(18, 70) != \
        c64_codec.c64_strength_hit_step(18, 0)
    assert rec.get("strength_index") == c64_codec.strength_index(18, 70)
    assert any("strength" in line and "ECL65 $9160" in line
               for line in rep.sources.values())


@pytest.mark.parametrize("port", ["DOS", "Amiga"])
def test_another_strength_source_leaves_the_c64_score_copied(port):
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    enlarge = bytes((12, 10, 0, 0x76, 1))
    char = _strength_character(port, game, 8, (17, 0), (18, 0),
                               {"cleric": 5}, enlarge)
    assert _c64_strength(char)[0] == (18, 0)


def test_an_amiga_source_strength_arrives_at_the_c64s_own_score():
    """The state is one the model explains, so the Amiga source gets the C64's
    own score for the roll (18/70), as a DOS source does."""
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    char = _strength_character("Amiga", game, 8, (17, 0), (18, 0),
                               {"cleric": 5})
    assert _c64_strength(char)[0] == (18, 70)


def test_a_c64_source_is_written_to_c64_as_it_was_given():
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    char = _strength_character("C64", game, 8, (17, 0), (18, 70),
                               {"cleric": 5})
    assert _c64_strength(char)[0] == (18, 70)


@pytest.mark.parametrize("key", [_CURSE_KEY, _SSB_KEY])
@pytest.mark.parametrize("roll, permanent, levels, c64, want", [
    (8, (17, 0), {"cleric": 5}, (18, 70), (18, 0)),
    (3, (18, 12), {"fighter": 4}, (18, 42), (18, 42)),
    (1, (18, 25), {"fighter": 4}, (18, 35), (18, 100)),
    (1, (18, 0), {"magic-user": 5}, (18, 10), (18, 100)),
])
def test_a_c64_running_strength_arrives_at_what_a_dos_cast_gives(
        key, roll, permanent, levels, c64, want):
    game = c64_port.by_key(key)
    char = _strength_character("C64", game, roll, permanent, c64, levels)
    score, kept, _rep = _dos_strength(char)
    assert score == want
    assert kept == permanent


def test_a_dos_or_amiga_source_keeps_its_score_in_force_on_a_dos_write():
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    for port in ("DOS", "Amiga"):
        char = _strength_character(port, game, 3, (18, 12), (18, 72),
                                   {"fighter": 4})
        assert _dos_strength(char)[0] == (18, 72)


def test_a_c64_strength_written_for_the_amiga_is_the_destinations_score():
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    char = _strength_character("C64", game, 8, (17, 0), (18, 70),
                               {"cleric": 5})
    assert _dos_strength(char, into="Amiga")[0] == (18, 0)


def test_a_c64_roll_of_one_is_written_to_the_amiga_with_its_score():
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    from goldbox.amiga_later import CURSE_DELTAS

    for roll in (1, 2):
        char = _strength_character("C64", game, roll, (18, 25), (18, 35),
                                   {"fighter": 4})
        nodes, dropped = amiga_later._later_effect_nodes(char, CURSE_DELTAS.dos)
        assert len([n for n in nodes if n[0] == 38]) == 1
        assert not dropped
    char = _strength_character("C64", game, 1, (18, 25), (18, 35),
                               {"fighter": 4})
    assert _dos_strength(char, into="Amiga")[0] == (18, 100)


def test_a_dual_classed_ex_fighter_climbs_by_tens_on_dos_but_not_on_the_amiga():
    """Silver Blades' Amiga warrior test counts a former class only above
    `former_level`, which a record we write never satisfies; Curse's does."""
    def character(key):
        char = _strength_character(
            "C64", c64_port.by_key(key), 3, (17, 0),
            effects.raise_strength(17, 0, 3), {"thief": 5})
        char.set("former_levels", {"fighter": 5}, "built here")
        return char

    assert _dos_strength(character(_SSB_KEY))[0] == (18, 20)
    assert _dos_strength(character(_SSB_KEY), into="Amiga")[0] == (18, 0)
    assert _dos_strength(character(_CURSE_KEY), into="Amiga")[0] == (18, 20)


def test_an_amiga_silver_blades_source_uses_the_current_class_warrior_test():
    """A climbed 18/72 is a state only a warrior's recalculation reaches, so
    it is explained (and converted to 18/42) only where the ex-fighter counts."""
    def score(key):
        char = _strength_character("Amiga", c64_port.by_key(key), 3, (18, 12),
                                   (18, 72), {"thief": 5})
        char.set("former_levels", {"fighter": 5}, "built here")
        return _c64_strength(char)[0]

    assert score(_CURSE_KEY) == (18, 42)
    assert score(_SSB_KEY) == (18, 72)


def _strength_specimen_party(name, platform):
    if platform == "dos":
        from gamedata import specimen

        from editor import roster

        return roster.Party(str(specimen(name) / "SAVGAMD.DAT"))
    from editor import roster
    from tests.c64.test_c64nametable import specimen_disk

    return roster.Party(str(specimen_disk(name)))


def test_save_as_c64_converts_the_whole_strength_rebuild_party(tmp_path):
    """The Curse party the game saved with a Strength on five of six members:
    each arrives with STRENGTH and the C64's own score for its roll."""
    from editor import roster, saveplan

    party = _strength_specimen_party(
        "curse-667-strength-rebuild-dos-resave", "dos")
    try:
        plan = _blessed_row_plan(party, tmp_path)
    except saveplan.MissingAssets:
        pytest.skip("needs Curse of the Azure Bonds' own C64 disks")
    assert isinstance(plan, saveplan.SavePlan)
    (_name, data), = plan.files.items()
    out = tmp_path / "written.d64"
    out.write_bytes(data)
    back = roster.Party(str(out))
    names = {m.index: m.name for m in back.members}
    rows = effects.active_effects(back.save0.to_bytes())
    assert sorted((names[e.owner], e.id, e.magnitude) for e in rows) == [
        ("LEDERA", 38, 0x85), ("MARK", 38, 0xA7), ("PHILIPPE", 38, 0x85),
        ("SHARA", 38, 0xFC), ("TRAVIS", 38, 0xA7)]
    scores = {m.name: (m.record.get("strength"),
                       m.record.get("exceptional_strength"),
                       m.record.get("strength_index"))
              for m in back.members}
    want = {"MARK": (18, 0), "TRAVIS": (18, 42), "LEDERA": (18, 35),
            "SHARA": (18, 70), "PHILIPPE": (18, 10)}
    for name, score in want.items():
        assert scores[name] == (*score, c64_codec.strength_index(*score))
        # The permanent score behind it is the DOS one.
    assert {m.name: m.record.get_raw("abilities_second")[0]
            for m in back.members if m.name in want} == {
        "MARK": 15, "TRAVIS": 18, "LEDERA": 18, "SHARA": 17, "PHILIPPE": 18}


def test_save_as_dos_converts_the_whole_strength_ladder_party(tmp_path):
    from editor import convert, saveplan
    from tools.convert import convertdrops
    from tools.dos import dosbox

    party = _strength_specimen_party(
        "curse-667-strength-ladder-c64-resave", "c64")
    source = party.source or convert.Source.detect(party.path)
    try:
        game_dir = dosbox.find_game("CURSE")
    except FileNotFoundError:
        pytest.skip("needs the DOS Curse archives ($FR_ARCHIVES)")
    try:
        assets = saveplan.resolve_assets(
            source, "dos", game_files=convertdrops.game_files,
            dos_folder=game_dir)
    except saveplan.MissingAssets:
        pytest.skip("needs Curse of the Azure Bonds' own C64 disks")
    plan = saveplan.prepare_save_as(party, "dos", tmp_path / "dos", assets)
    got = {}
    for name in ("SHARA", "TRAVIS", "LEDERA", "PHILIPPE", "MARK"):
        char = _dos_character(plan.files, name)
        (node,) = [bytes(r) for r in char.get("running_effects")]
        got[name] = (node[3], node[4], char.get("strength"),
                     char.get("exceptional_strength"))
    assert got == {
        "SHARA": (108, 1, 18, 0), "TRAVIS": (103, 1, 18, 42),
        "LEDERA": (101, 1, 18, 100), "PHILIPPE": (101, 1, 18, 100),
        "MARK": (103, 1, 18, 0)}


# --- a Pool Strength and Enlarge together (#667) ---------------------------------

_POOL_ACTIVE = bytes((38, 10, 0, 0x71, 1))
_POOL_PARKED = bytes((12, 60, 0, 0x95, 1))


def _pool_pair_rows(*nodes, granted=()):
    char = _pool_character(*nodes)
    if granted:
        char.set("granted_effects", [g + NULL for g in granted], "built here")
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                                clock_minutes=0)
    rows = {s: r for s, r in _rows(payload).items() if r[0]}
    return rows, rep


def test_a_pool_strength_and_enlarge_pair_becomes_two_timed_rows():
    rows, rep = _pool_pair_rows(_POOL_ACTIVE, _POOL_PARKED)
    ten, sixty = effects.closest_duration(10, 0), effects.closest_duration(60, 0)
    # The earlier-ending node takes the higher slot.
    assert rows == {63: (38, 2, ten, 0x94), 62: (12, 2, sixty, 0xF1)}
    assert not [d for d in rep.dropped + rep.losses if "running_effects" in d]


def test_a_pool_pair_written_in_the_other_order_takes_slots_by_expiry():
    rows, _rep = _pool_pair_rows(_POOL_PARKED, _POOL_ACTIVE)
    assert rows == {
        63: (38, 2, effects.closest_duration(10, 0), 0x94),
        62: (12, 2, effects.closest_duration(60, 0), 0xF1)}


@pytest.mark.parametrize("first, second, want", [
    # The active node ends first, so its row holds the parked boost.
    (bytes((38, 10, 0, 0x71, 1)), bytes((38, 60, 0, 0x95, 1)), 0x94),
    # The parked node ends first and restores nothing.
    (bytes((38, 60, 0, 0x71, 1)), bytes((38, 10, 0, 0x95, 1)), 0x14),
], ids=["active-first", "parked-first"])
def test_two_pool_strength_casts_become_two_timed_rows(first, second, want):
    rows, rep = _pool_pair_rows(first, second)
    ten, sixty = effects.closest_duration(10, 0), effects.closest_duration(60, 0)
    assert rows == {63: (38, 2, ten, want), 62: (38, 2, sixty, 0xF1)}
    assert not [d for d in rep.dropped + rep.losses if "running_effects" in d]
    payload = bytearray(0x1C00)
    c64_codec.write(_pool_character(first, second), payload=payload,
                    party_slot=2, clock_minutes=0)
    out = _read(payload, 2)
    assert not _lines(out)
    assert sorted(bytes(r)[:5] for r in out.get("running_effects")) \
        == sorted([first, second])


@pytest.mark.parametrize("spell, gauntlets", [
    # The spell is parked with its own boost; the gauntlets hold the base.
    (bytes((38, 10, 0, 0x95, 1)), bytes((38, 0, 0, 0x73, 1))),
    (bytes((12, 10, 0, 0x95, 1)), bytes((38, 0, 0, 0x73, 1))),
    # A Strength at exactly 18/00 on a fighter already wearing the gauntlets
    # holds the base, and the gauntlets are parked with data 0xE5.
    (bytes((38, 10, 0, 0x73, 1)), bytes((38, 0, 0, 0xE5, 1))),
    # An Enlarge that ties the gauntlets and came second holds the base.
    (bytes((12, 10, 0, 0x73, 1)), bytes((38, 0, 0, 0xE5, 1))),
    # A magic-user, cleric or thief: the Strength is parked with boost 1.
    (bytes((38, 10, 0, 0x81, 1)), bytes((38, 0, 0, 0x73, 1))),
], ids=["strength", "enlarge", "strength-holds-base", "enlarge-tie",
        "strength-parked-boost-1"])
def test_gauntlets_beside_a_running_pool_strength_convert_as_the_gauntlets(
        spell, gauntlets):
    char = _pool_character(spell)
    char.set("granted_effects", [gauntlets + NULL], "built here")
    char.set("strength", 18, "built here")
    char.set("exceptional_strength", 0, "built here")
    payload = bytearray(0x1C00)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                               clock_minutes=0)
    rows = {s: r for s, r in _rows(payload).items() if r[0]}
    assert rows == {63: (38, 2, 0, ROLAND_STRENGTH_MAGNITUDE)}
    assert (rec.get("strength"), rec.get("exceptional_strength")) == (18, 0)
    label = c64_codec.running_effect_label(spell[0], 10, char.game)
    assert not [d for d in rep.dropped + rep.losses if d.startswith(label)]


def test_a_parked_pool_node_ending_first_is_a_row_with_bit_7_clear():
    rows, _rep = _pool_pair_rows(bytes((38, 60, 0, 0x71, 1)),
                                 bytes((12, 10, 0, 0x95, 1)))
    assert sorted(r[3] for r in rows.values()) == [0x14, 0xF1]


@pytest.mark.parametrize("nodes, granted", [
    ((_POOL_ACTIVE, _POOL_PARKED, bytes((12, 5, 0, 0x66, 1))), ()),
    ((_POOL_ACTIVE, _POOL_PARKED), (bytes((38, 0, 0, 0x73, 1)),)),
    # Not the pair: one running Strength beside a granted one, neither parked.
    ((_POOL_ACTIVE,), (bytes((38, 0, 0, 0x73, 1)),)),
])
def test_other_pool_strength_states_are_still_refused(nodes, granted):
    rows, rep = _pool_pair_rows(*nodes, granted=granted)
    assert not [r for r in rows.values() if r[0] in (12, 38)]
    assert [d for d in rep.dropped if "more than one strength" in d]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("clock, active_minutes, parked_minutes", [
    (0, 10, 10), (0, 63, 64), (0, 64, 63), (0, 70, 75), (0, 75, 70),
    (725, 10, 10), (725, 75, 80), (725, 80, 75)])
def test_tied_pool_expiries_write_the_parked_row_clear_in_either_order(
        clock, active_minutes, parked_minutes, reverse):
    """Equal minutes, or minutes that share a duration byte, are one instant
    to the C64: the parked node's row restores nothing and the active node's
    base is the only restore, whatever the list order."""
    assert (effects.closest_duration(active_minutes, clock)
            == effects.closest_duration(parked_minutes, clock))
    nodes = [bytes((38,)) + active_minutes.to_bytes(2, "little")
             + bytes((0x71, 1)),
             bytes((12,)) + parked_minutes.to_bytes(2, "little")
             + bytes((0x95, 1))]
    if reverse:
        nodes.reverse()
    payload = bytearray(0x1C00)
    c64_codec.write(_pool_character(*nodes), payload=payload, party_slot=2,
                    clock_minutes=clock)
    strength = [r for r in _rows(payload).values() if r[0] in (12, 38)]
    assert sorted((r[0], r[3]) for r in strength) == [(12, 0x14), (38, 0xF1)]
    assert len({r[2] for r in strength}) == 1


def test_the_two_pool_rows_read_back_as_the_same_two_nodes():
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 38, 2, effects.closest_duration(10, 0), 0x94)
    effects.write_effect(p, 62, 12, 2, effects.closest_duration(60, 0), 0xF1)
    out = _read(p, 2)
    assert not _lines(out)
    got = sorted(bytes(r)[:5] for r in out.get("running_effects"))
    assert got == sorted([_POOL_ACTIVE, _POOL_PARKED])
    _r, _i, spc, _rep = dos_codec.write(out)
    assert sorted(spc[i:i + 5] for i in range(0, len(spc), 9)) == got


def test_pool_rows_no_two_node_timeline_makes_are_still_refused():
    p = bytearray(0x1C00)
    effects.write_effect(p, 63, 38, 2, effects.closest_duration(10, 0), 0x94)
    effects.write_effect(p, 62, 12, 2, effects.closest_duration(60, 0), 0x71)
    out = _read(p, 2)
    assert len(_lines(out)) == 2 and not out.get("running_effects")


def test_a_written_pool_pair_survives_write_then_read():
    p = bytearray(0x1C00)
    _rec, _rep = c64_codec.write(
        _pool_character(_POOL_ACTIVE, _POOL_PARKED), payload=p, party_slot=2,
        clock_minutes=0)
    out = _read(p, 2)
    assert sorted(bytes(r)[:5] for r in out.get("running_effects")) == sorted(
        [_POOL_ACTIVE, _POOL_PARKED])


def test_the_amiga_warrior_test_refuses_a_title_it_has_no_rule_for():
    with pytest.raises(ValueError):
        c64_codec.amiga_strength_warrior("pool-of-radiance",
                                         {"fighter": 4}, {})


# --- the gauntlets beside a running Strength through Save As --------------------


_POOL_PARKED_STRENGTH = bytes((38, 10, 0, 0x95, 1))
_GAUNTLETS_NODE = bytes((38, 0, 0, 0x73, 1))


def test_save_as_c64_writes_the_gauntlets_alone_and_is_not_blocked(
        tmp_path, monkeypatch):
    """A DOS Pool party whose first member holds the gauntlets' node and a
    running, parked Strength: the dialog's own no-loss rule finds nothing
    lost, and the C64 save it writes holds the gauntlets' row and 18/00. The
    node pair is put on the specimen member as the codec reads it, because
    no save the game wrote holds the pair."""
    from gamedata import specimen_root
    from PyQt6.QtWidgets import QApplication

    from editor import roster, saveplan
    from goldbox.d64 import D64
    from goldbox.savegame import load_save
    from tools.convert import convertdrops

    QApplication.instance() or QApplication([])
    root = specimen_root()
    found = list(root.glob("*-dos/WISH-SPEC-por-hireling-swordsman-03")
                 ) if root else []
    if not found:
        pytest.skip("needs WISH-SPEC-por-hireling-swordsman-03 "
                    "(tools/registry/specimens.py)")
    party = roster.Party(str(found[0]))
    try:
        assets = saveplan.resolve_assets(
            party.source, "c64", game_files=convertdrops.game_files)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks, found through "
                    "automap/gamedisks.py")
    target = party.members[0].record.get("name")
    # The comparison Save As ends with reads the member's own record, so the
    # score it expects is the one the node pair leaves.
    party.members[0].record.set("strength", 18)
    party.members[0].record.set("exceptional_strength", 0)
    real = dos_codec.to_neutral

    def with_the_pair(character, **kwargs):
        char = real(character, **kwargs)
        if char.get("name") == target:
            char.set("running_effects", [_POOL_PARKED_STRENGTH + NULL],
                     "built here")
            char.set("granted_effects", [_GAUNTLETS_NODE + NULL],
                     "built here")
            char.set("strength", 18, "built here")
            char.set("exceptional_strength", 0, "built here")
        return char

    monkeypatch.setattr(dos_codec, "to_neutral", with_the_pair)
    from editor import convert
    source = convert.Source.of_snapshot(saveplan.prepare(party))
    rehearsal, _slot = saveplan.rehearse(saveplan.route(source, "c64"),
                                         source, assets)
    assert not [d for d in saveplan.losses(rehearsal.report)
                if "strength" in d.lower() or "effect 38" in d]
    plan = saveplan.prepare_save_as(party, "c64", tmp_path / "out.d64", assets)
    (image,) = plan.files
    disk = tmp_path / "read-back.d64"
    disk.write_bytes(plan.files[image])
    _game, save0, _save1 = load_save(D64.open(str(disk)))
    strength = [e for e in effects.active_effects(save0.to_bytes())
                if e.id in effects.STRENGTH_IDS]
    assert [(e.id, e.duration, e.magnitude) for e in strength] \
        == [(38, 0, ROLAND_STRENGTH_MAGNITUDE)]
    from support.doslatertitles import _c64_party

    _game, chars = _c64_party(disk)
    (char,) = [c for c in chars if c.get("name") == target]
    assert (char.get("strength"), char.get("exceptional_strength")) == (18, 0)
