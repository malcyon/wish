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

import pytest
from support.dossave import _save_dir

from goldbox import (
    amiga_later,
    amiga_pod,
    amiga_por,
    amiga_port,
    c64_codec,
    c64_port,
    dos_codec,
    dos_port,
    effects,
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
    payload = bytearray(c64_save.container_for(game).game.save_size)
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


def test_pool_camp_prayer_id_35_is_written_and_a_later_title_has_no_35():
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
    assert len(lines) == 1 and "no rule yet" in lines[0]
    assert payload == bytearray(0x1C00)


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


def test_a_never_expiring_prayer_row_is_a_node_of_the_longest_time():
    party = _staged_party((63, (49, 0xFF, 0x00, 0x43)))
    assert [bytes(r) for r in _brutus(party).get("running_effects")] == \
        [bytes((49, 0xFF, 0xFF, 0x03, 0)) + NULL]


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


def test_a_c64_trait_slot_id_5_stays_in_its_slot_through_dos():
    trait = bytes((5, 0, 0, 0xFF, 0))
    payload = bytearray(0x1C00)
    char = _title_character(c64_port.POOL_OF_RADIANCE)
    char.set("granted_effects", [trait + NULL], "built here")
    rec, _rep = c64_codec.write(char, payload=payload, party_slot=0,
                                clock_minutes=0)
    assert 5 in bytes(rec.get_raw("item_effects"))
    assert [r for r in _rows(payload).values() if r != (0, 0, 0, 0)] == []


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
