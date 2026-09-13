"""Copy-only recovery of one empty NPC icon; all save inputs are generated."""
from __future__ import annotations

import os
from hashlib import sha256
from types import SimpleNamespace

import gamedata
import pytest

from goldbox import c64_save, savegame
from goldbox.d64 import D64, attach_load_address
from goldbox.record import CharacterRecord
from tools import dirtenicon as repair


@pytest.fixture
def seed():
    """A distinct-byte sentinel, not a copy of the game's art."""
    return bytes(range(1, 37))


def generated_disk(slot=7):
    # Nonzero surroundings expose writes to records, slack, headers or other
    # icons; this is deliberately a format fixture, not native game evidence.
    p0 = bytearray(i % 251 for i in range(repair.POOL.payload_size))
    p1 = bytearray((i * 3) % 251 for i in range(repair.POOL.roster_size))
    record = CharacterRecord.blank()
    record.set("name", "DIRTEN")
    record.set_npc(True)
    at = repair.POOL.slot(slot)
    p0[at:at + 256] = record.to_bytes()[:256]
    at = repair.POOL.icon(slot)
    p0[at:at + 36] = bytes(36)
    p1[slot * 32] = 1
    p1[slot * 32 + savegame.ROSTER_SLOT_INDEX] = slot
    disk = D64.blank()
    disk.write_file("SAVEDGAME0", attach_load_address(0x4900, p0))
    disk.write_file("SAVEDGAME1", attach_load_address(0x8300, p1))
    disk.write_file("UNRELATED", bytes(range(100)))
    return disk


def replace_payload(disk, name, offset, value):
    raw = bytearray(disk.read_file(name))
    raw[2 + offset:2 + offset + len(value)] = value
    disk.write_file_inplace(name, raw)


@pytest.mark.parametrize("slot", range(8))
def test_a_reordered_dirten_changes_only_his_36_icon_bytes(slot, seed):
    disk = generated_disk(slot)
    original = disk.to_bytes()
    old_prg = disk.read_file("SAVEDGAME0")
    plan = repair.plan_repair(original, seed)
    output = D64(plan.output)
    assert plan.slot == slot
    assert plan.source_sha256 == sha256(original).hexdigest()
    assert plan.output_sha256 == sha256(plan.output).hexdigest()
    assert plan.changed_bytes == 36
    at = 2 + 0x2E0 + slot * 36  # Independent documented PRG location.
    assert output.read_file("SAVEDGAME0") == old_prg[:at] + seed + old_prg[at + 36:]
    for entry in disk.directory():
        if entry.name != b"SAVEDGAME0":
            assert output.read_file(entry.name) == disk.read_file(entry)
    # Invert the patch, then compare the entire physical image. This includes
    # all links, directory/BAM bytes, unused sectors and final-sector slack.
    replacement = output.read_file("SAVEDGAME0")
    output.write_file_inplace("SAVEDGAME0", replacement[:at] + bytes(36) + replacement[at + 36:])
    assert output.to_bytes() == original
    assert disk.to_bytes() == original


@pytest.mark.parametrize("condition,message", [
    ("absent", "exactly one DIRTEN"),
    ("ambiguous", "exactly one DIRTEN"),
    ("player", "not a joined NPC"),
    ("inactive", "not a joined NPC"),
    ("wrong_roster_slot", "not a joined NPC"),
    ("nonzero", "nonzero icon"),
])
def test_identity_and_existing_art_are_never_guessed(condition, message, seed):
    disk = generated_disk()
    if condition == "absent":
        replace_payload(disk, "SAVEDGAME0", repair.POOL.slot(7), b"OTHER\0")
    elif condition == "ambiguous":
        replace_payload(disk, "SAVEDGAME0", repair.POOL.slot(2), b"DIRTEN\0")
    elif condition == "player":
        replace_payload(disk, "SAVEDGAME0", repair.POOL.slot(7) + 0xB8, b"\0")
    elif condition == "inactive":
        replace_payload(disk, "SAVEDGAME1", 7 * 32, b"\0")
    elif condition == "wrong_roster_slot":
        replace_payload(disk, "SAVEDGAME1", 7 * 32 + savegame.ROSTER_SLOT_INDEX, b"\x02")
    elif condition == "nonzero":
        replace_payload(disk, "SAVEDGAME0", repair.POOL.icon(7) + 35, b"\x01")
    original = disk.to_bytes()
    with pytest.raises(repair.RepairError, match=message):
        repair.plan_repair(original, seed)
    assert disk.to_bytes() == original


@pytest.mark.parametrize("condition", [
    "missing_roster", "wrong_load", "short_save", "wrong_title", "mixed_titles",
    "duplicate_name", "unclosed", "wrong_type", "cross_link", "free_block",
    "block_count", "directory_loop", "file_loop", "bad_bam", "error_map",
])
def test_unsupported_or_malformed_sources_are_refused(condition, seed):
    disk = generated_disk()
    if condition in ("missing_roster", "wrong_load", "short_save", "wrong_title"):
        damaged = D64.blank()
        for entry in disk.directory():
            name, data = entry.name, disk.read_file(entry)
            if name == b"SAVEDGAME1" and condition == "missing_roster":
                continue
            if name == b"SAVEDGAME1" and condition == "wrong_load":
                data = b"\0\0" + data[2:]
            if name == b"SAVEDGAME0" and condition == "short_save":
                data = data[:-1]
            if name == b"SAVEDGAME0" and condition == "wrong_title":
                name = c64_save.CURSE_OF_THE_AZURE_BONDS.save_file
            damaged.write_file(name, data)
        disk = damaged
    elif condition == "mixed_titles":
        disk.write_file(c64_save.CURSE_OF_THE_AZURE_BONDS.save_file, bytes(4))
    elif condition in ("duplicate_name", "unclosed", "wrong_type", "cross_link", "block_count"):
        entry = disk.entry("SAVEDGAME1")
        sector = bytearray(disk.read_sector(entry.dir_track, entry.dir_sector))
        at = 2 + entry.slot * 32
        if condition == "duplicate_name":
            sector[at + 3:at + 19] = b"SAVEDGAME0".ljust(16, b"\xA0")
        elif condition == "unclosed":
            sector[at] &= 0x7F
        elif condition == "wrong_type":
            sector[at] = 0x81
        elif condition == "cross_link":
            # A second file sharing the icon's sector is unsafe even though
            # a physical 36-byte diff still falls within the declared window.
            first = disk.entry("SAVEDGAME0")
            sector[at + 1:at + 3] = bytes((first.first_track, first.first_sector))
            sector[at + 28:at + 30] = first.block_count.to_bytes(2, "little")
        else:
            sector[at + 28] += 1
        disk.write_sector(entry.dir_track, entry.dir_sector, sector)
    elif condition == "free_block":
        track, block = disk.sector_chain("SAVEDGAME0")[0]
        bam = bytearray(disk.read_sector(18, 0))
        bam[4 + (track - 1) * 4 + 1 + block // 8] |= 1 << (block % 8)
        disk.write_sector(18, 0, bam)
    elif condition in ("directory_loop", "file_loop"):
        block = (18, 1) if condition == "directory_loop" else disk.sector_chain("SAVEDGAME0")[0]
        sector = bytearray(disk.read_sector(*block))
        sector[:2] = bytes(block)
        disk.write_sector(*block, sector)
    elif condition == "bad_bam":
        bam = bytearray(disk.read_sector(18, 0))
        bam[2] = 0
        disk.write_sector(18, 0, bam)
    original = disk.to_bytes()
    if condition == "error_map":
        original += bytes([1] * 683)
    with pytest.raises((ValueError, repair.D64Error)):
        repair.plan_repair(original, seed)


def test_the_byte_verifier_catches_an_unrelated_write(monkeypatch, seed):
    original_write = D64.write_file_inplace

    def wrong_write(disk, entry, new_data):
        original_write(disk, entry, new_data)
        bam = bytearray(disk.read_sector(18, 0))
        bam[0x90] ^= 1
        disk.write_sector(18, 0, bam)

    disk = generated_disk()
    monkeypatch.setattr(D64, "write_file_inplace", wrong_write)
    with pytest.raises(repair.RepairError, match="outside DIRTEN's icon"):
        repair.plan_repair(disk.to_bytes(), seed)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.d64"
    path.write_bytes(generated_disk().to_bytes())
    return path


def test_the_cli_inspects_by_default_and_only_writes_an_explicit_new_copy(
        source, seed, monkeypatch, capsys):
    monkeypatch.setattr(repair, "native_default", lambda: repair.NativeDefault(seed, ()))
    original = source.read_bytes()
    assert repair.main([str(source)]) == 0
    assert "Inspection only: No file written" in capsys.readouterr().out
    assert list(source.parent.iterdir()) == [source]
    output = source.with_name("repaired.d64")
    assert repair.main([str(source), "--out", str(output)]) == 0
    assert output.read_bytes() == repair.plan_repair(original, seed).output
    assert source.read_bytes() == original
    assert not list(source.parent.glob(".dirtenicon-*"))


@pytest.mark.parametrize("kind", ("input", "normalized", "existing", "symlink", "dangling", "symlink_loop", "hardlink"))
def test_output_aliases_and_existing_files_are_never_overwritten(source, seed, kind):
    original = source.read_bytes()
    plan = repair.plan_repair(original, seed)
    output = source.with_name("output.d64")
    if kind == "input":
        output = source
    elif kind == "normalized":
        output = source.parent / "." / source.name
    elif kind == "existing":
        output.write_bytes(b"Keep this file")
    elif kind in ("symlink", "dangling", "symlink_loop"):
        try:
            target = (source if kind == "symlink" else output
                      if kind == "symlink_loop" else source.with_name("missing"))
            output.symlink_to(target)
        except OSError:
            pytest.skip("Symlinks are unavailable on this platform")
    else:
        os.link(source, output)
    before = output.read_bytes() if output.exists() else None
    with pytest.raises(repair.RepairError):
        repair.publish_copy(source, output, plan)
    assert source.read_bytes() == original
    if before is not None:
        assert output.read_bytes() == before
    assert not list(source.parent.glob(".dirtenicon-*"))


def test_a_destination_created_during_publication_is_not_clobbered(source, seed, monkeypatch):
    plan = repair.plan_repair(source.read_bytes(), seed)
    output = source.with_name("race.d64")
    link = os.link

    def raced_link(temporary, target):
        target.write_bytes(b"A different process won")
        link(temporary, target)

    monkeypatch.setattr(repair.os, "link", raced_link)
    with pytest.raises(FileExistsError):
        repair.publish_copy(source, output, plan)
    assert output.read_bytes() == b"A different process won"
    assert sha256(source.read_bytes()).hexdigest() == plan.source_sha256
    assert not list(source.parent.glob(".dirtenicon-*"))


def test_a_changed_input_aborts_before_publication(source, seed, monkeypatch):
    plan = repair.plan_repair(source.read_bytes(), seed)
    output = source.with_name("stale.d64")

    def source_changed(_fd):
        source.write_bytes(b"Simulated external edit")

    monkeypatch.setattr(repair.os, "fsync", source_changed)
    with pytest.raises(repair.RepairError, match="input changed"):
        repair.publish_copy(source, output, plan)
    assert not output.exists()
    assert source.read_bytes() == b"Simulated external edit"
    assert not list(source.parent.glob(".dirtenicon-*"))


def test_failed_publication_leaves_no_partial_copy(source, seed, monkeypatch):
    plan = repair.plan_repair(source.read_bytes(), seed)
    output = source.with_name("failed.d64")

    def failed_link(*_args):
        raise OSError("Generated link failure")

    monkeypatch.setattr(repair.os, "link", failed_link)
    with pytest.raises(OSError, match="link failure"):
        repair.publish_copy(source, output, plan)
    assert not output.exists()
    assert sha256(source.read_bytes()).hexdigest() == plan.source_sha256
    assert not list(source.parent.glob(".dirtenicon-*"))


def test_a_staged_output_hash_mismatch_is_never_published(source, seed, monkeypatch):
    plan = repair.plan_repair(source.read_bytes(), seed)
    output = source.with_name("damaged.d64")

    def damaged_stage(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, b"Damaged during staging")

    monkeypatch.setattr(repair.os, "fsync", damaged_stage)
    with pytest.raises(repair.RepairError, match="staged output failed"):
        repair.publish_copy(source, output, plan)
    assert not output.exists()
    assert sha256(source.read_bytes()).hexdigest() == plan.source_sha256
    assert not list(source.parent.glob(".dirtenicon-*"))


@pytest.mark.parametrize("bad_icon", (bytes(36), bytes(35), bytes(37)))
def test_a_missing_or_wrong_width_default_is_not_a_repair(bad_icon):
    with pytest.raises(repair.RepairError, match="36-byte native default"):
        repair.plan_repair(generated_disk().to_bytes(), bad_icon)


def test_cli_refusal_writes_no_file_and_reports_no_traceback(source, seed, monkeypatch, capsys):
    monkeypatch.setattr(repair, "native_default", lambda: repair.NativeDefault(seed, ()))
    source.write_bytes(repair.plan_repair(source.read_bytes(), seed).output)
    original = source.read_bytes()
    output = source.with_name("another.d64")
    assert repair.main([str(source), "--out", str(output)]) == 1
    assert capsys.readouterr().err.startswith("Refused: DIRTEN already has nonzero icon data")
    assert source.read_bytes() == original
    assert not output.exists()


@pytest.fixture
def generated_game_disks(tmp_path, seed, monkeypatch):
    root = tmp_path / "game"
    root.mkdir()
    init = bytearray(repair.INIT_SIZE)
    init[repair.INIT_SEED:repair.INIT_SEED + 36] = seed
    first = D64.blank()
    first.write_file("INIT", attach_load_address(0x1000, init))
    (root / "POOL1.D64").write_bytes(first.to_bytes())
    third = D64.blank()
    for name in ("SPELLE64", "SPELLN64"):
        third.write_file(name, bytes(10))
    (root / "POOL3.D64").write_bytes(third.to_bytes())
    monkeypatch.setattr(repair.IconParts, "load", lambda _disk: SimpleNamespace(default_icon=lambda: seed))
    return root


@pytest.mark.parametrize("environment", (False, True))
def test_native_data_uses_the_existing_discovery_convention(
        generated_game_disks, environment, monkeypatch, seed):
    monkeypatch.delenv("POR_DISKS", raising=False)
    monkeypatch.setattr(repair, "find_disks", lambda: generated_game_disks)
    if environment:
        monkeypatch.setenv("POR_DISKS", str(generated_game_disks))
        monkeypatch.setattr(repair, "find_disks", lambda: pytest.fail("POR_DISKS takes precedence"))
    result = repair.native_default()
    assert result.icon == seed
    assert result.sources == tuple(
        (name, sha256((generated_game_disks / name).read_bytes()).hexdigest())
        for name in ("POOL1.D64", "POOL3.D64"))


def test_disagreeing_native_sources_are_refused(generated_game_disks, monkeypatch):
    monkeypatch.setenv("POR_DISKS", str(generated_game_disks))
    monkeypatch.setattr(repair.IconParts, "load", lambda _disk: SimpleNamespace(default_icon=lambda: bytes([99] * 36)))
    with pytest.raises(repair.RepairError, match="does not match"):
        repair.native_default()


def test_truncated_native_init_is_refused(generated_game_disks, monkeypatch):
    monkeypatch.setenv("POR_DISKS", str(generated_game_disks))
    path = generated_game_disks / "POOL1.D64"
    disk = D64.open(path)
    disk.write_file_inplace("INIT", disk.read_file("INIT")[:-1])
    path.write_bytes(disk.to_bytes())
    with pytest.raises(repair.RepairError, match="Unsupported Pool INIT layout"):
        repair.native_default()


@gamedata.needs_disks
def test_the_players_native_sources_agree_without_reading_a_saved_party(monkeypatch):
    monkeypatch.setenv("POR_DISKS", str(gamedata.disk_dir()))
    result = repair.native_default()
    assert len(result.icon) == 36
    assert any(result.icon)
    assert {name for name, _hash in result.sources} == {"POOL1.D64", "POOL3.D64"}
