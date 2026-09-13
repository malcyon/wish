#!/usr/bin/env python3
"""Inspect DIRTEN's missing Pool combat icon, or repair a new disk-image copy.

    tools/dirtenicon.py save.d64
    tools/dirtenicon.py save.d64 --out repaired.d64

Inspection is the default. The only accepted repair is a unique joined NPC
named DIRTEN whose entire icon is zero. No existing file is ever overwritten.
Game data comes from POR_DISKS, then automap.paths.find_disks(); no art is
embedded here. POOL3's composed default must match POOL1 INIT's native seed.

The engine evidence and the 36-byte control/repair comparison are in
docs/50-experiments.md, "Dirten inherits a legacy import's zero combat icon".
This is recovery for one known defect, not a general icon editor or migration.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import stat
import sys
import tempfile
from dataclasses import dataclass
from hashlib import sha256

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap.paths import find_disks  # noqa: E402
from goldbox import c64_port, c64_save, savegame  # noqa: E402
from goldbox.d64 import (  # noqa: E402
    BAM_DOS_TYPE,
    D64,
    DOS_TYPE,
    DOS_VERSION,
    PAYLOAD_PER_SECTOR,
    D64Error,
    sector_offset,
)
from goldbox.iconparts import IconParts  # noqa: E402
from goldbox.layout import RECORD_SIZE  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402

POOL = c64_save.POOL_OF_RADIANCE
# INIT's payload runs at $0800 despite its PRG header naming $1000. Its
# $0B02 routine seeds eight 36-byte entries from $0B2D; no game art is stored.
INIT_SIZE = 2939
INIT_SEED = 0x32D


class RepairError(ValueError):
    """The evidence is insufficient for this narrowly permitted repair."""


@dataclass(frozen=True)
class NativeDefault:
    icon: bytes
    sources: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class RepairPlan:
    slot: int
    source_sha256: str
    output_sha256: str
    changed_bytes: int
    output: bytes


def _one_entry(disk: D64, name: bytes):
    entries = [entry for entry in disk.directory() if entry.name == name]
    if len(entries) != 1 or entries[0].file_type != 2 or not entries[0].is_closed:
        raise RepairError(f"Expected one closed PRG named {name.decode()}")
    return entries[0]


def native_default() -> NativeDefault:
    """Read and corroborate the default from the player's two Pool disks."""
    directory = os.environ.get("POR_DISKS") or find_disks()
    if not directory:
        raise RepairError("Game disks not found; set POR_DISKS to their directory")
    root = pathlib.Path(directory)
    images = {}
    sources = []
    for name in ("POOL1.D64", "POOL3.D64"):
        paths = [path for path in root.iterdir() if path.name.upper() == name]
        if len(paths) != 1:
            raise RepairError(f"Expected exactly one {name} in the game directory")
        raw = paths[0].read_bytes()
        images[name] = D64(raw)
        sources.append((name, sha256(raw).hexdigest()))

    disk = images["POOL1.D64"]
    init = disk.read_file(_one_entry(disk, b"INIT"))
    if len(init) != INIT_SIZE + 2 or int.from_bytes(init[:2], "little") != 0x1000:
        raise RepairError("Unsupported Pool INIT layout; no default can be verified")
    creation = images["POOL3.D64"]
    for name in (b"SPELLE64", b"SPELLN64"):
        _one_entry(creation, name)
    icon = IconParts.load(creation).default_icon()
    if (len(icon) != POOL.icon_size or not any(icon)
            or icon != init[2 + INIT_SEED:2 + INIT_SEED + POOL.icon_size]):
        raise RepairError("The composed default does not match Pool INIT's seed")
    return NativeDefault(icon, tuple(sources))


def _validated_save(image: bytes):
    disk = D64(image)
    if not disk.writable:
        raise RepairError("Only a plain 35-track D64 save is supported")
    bam = disk.read_sector(18, 0)
    if (bam[:2] != bytes((18, 1)) or bam[2] != DOS_VERSION
            or bam[BAM_DOS_TYPE:BAM_DOS_TYPE + 2] != DOS_TYPE):
        raise RepairError("The save disk has an unsupported BAM header")
    entries = disk.directory()
    names = [entry.name for entry in entries]
    if len(set(names)) != len(names):
        raise RepairError("Duplicate directory names make this disk ambiguous")
    if any(game.save_file in names for game in c64_port.GAMES
           if game.key != POOL.key):
        raise RepairError("Only an unambiguous Pool of Radiance save is supported")
    first = _one_entry(disk, POOL.save_file)
    second = _one_entry(disk, POOL.roster_file)

    # The allowed physical diff alone cannot protect another logical file
    # sharing a sector. Refuse cross-links, free-marked blocks and directory
    # sectors before changing anything, including on otherwise readable disks.
    used = {(18, 0)}
    block = (18, 1)
    while block[0]:
        used.add(block)  # Include empty directory sectors, too.
        block = tuple(disk.read_sector(*block)[:2])
    for entry in entries:
        if not entry.is_closed or entry.file_type not in (1, 2, 3):
            raise RepairError("Only ordinary closed SEQ, PRG and USR files are supported")
        chain = disk.sector_chain(entry)
        raw = disk.read_file(entry)
        if len(chain) != entry.block_count or len(chain) != D64.blocks_needed(len(raw)):
            raise RepairError("A file's sector count does not match its directory entry")
        for block in chain:
            if block in used or disk.is_free(*block):
                raise RepairError("Cross-linked or free-marked file sectors are unsafe")
            used.add(block)
    sg0 = savegame.SaveGame0.from_prg(disk.read_file(first), POOL)
    sg1 = savegame.SaveGame1.from_prg(disk.read_file(second), POOL)
    return disk, first, sg0, sg1


def plan_repair(image: bytes, icon: bytes) -> RepairPlan:
    """Build and verify an in-memory copy; never mutate the supplied bytes."""
    if len(icon) != POOL.icon_size or not any(icon):
        raise RepairError("A nonzero 36-byte native default is required")
    disk, entry, sg0, sg1 = _validated_save(image)
    matches = []
    for slot in range(POOL.party_slots):
        window = sg0.slot(slot).window
        record = CharacterRecord(window + bytes(RECORD_SIZE - len(window)))
        if record.name.upper() == "DIRTEN":
            matches.append((slot, record))
    if len(matches) != 1:
        raise RepairError("Expected exactly one DIRTEN in the eight party slots")
    slot, record = matches[0]
    roster = sg1.roster(slot)
    if not record.is_npc or not roster.roster_in_use or roster.slot_index != slot:
        raise RepairError("DIRTEN is not a joined NPC with a matching active roster")
    prg = disk.read_file(entry)
    start = 2 + POOL.icon(slot)
    if any(prg[start:start + POOL.icon_size]):
        raise RepairError("DIRTEN already has nonzero icon data; nothing will be replaced")
    replacement = prg[:start] + icon + prg[start + POOL.icon_size:]
    disk.write_file_inplace(entry, replacement)
    output = disk.to_bytes()

    # Independently map only the permitted PRG window to disk offsets. This
    # proves that links, BAM, directory, slack, other icons and all records
    # survive, rather than masking whatever the writer happened to change.
    chain = disk.sector_chain(entry)
    expected = bytearray(image)
    for position, value in enumerate(icon, start):
        block, within = divmod(position, PAYLOAD_PER_SECTOR)
        expected[sector_offset(*chain[block]) + 2 + within] = value
    if output != bytes(expected) or disk.read_file(entry) != replacement:
        raise RepairError("Verification failed: bytes outside DIRTEN's icon changed")
    return RepairPlan(slot, sha256(image).hexdigest(), sha256(output).hexdigest(),
                      sum(a != b for a, b in zip(image, output)), output)


def _check_output(source: pathlib.Path, output: pathlib.Path) -> None:
    if output.is_symlink():
        raise RepairError("The output already exists as a symlink; choose a new file")
    if source.resolve() == output.resolve():
        raise RepairError("The output must not be the input or an alias of it")
    if output.exists():
        raise RepairError("The output already exists; choose a new file")
    if output.suffix.lower() != ".d64" or not output.parent.is_dir():
        raise RepairError("The output must be a new .d64 file in an existing directory")


def publish_copy(source: pathlib.Path, output: pathlib.Path, plan: RepairPlan) -> None:
    """Publish a verified, complete copy atomically, with no overwrite path."""
    _check_output(source, output)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                prefix=".dirtenicon-", suffix=".tmp", dir=output.parent,
                delete=False) as stream:
            temporary = pathlib.Path(stream.name)
            stream.write(plan.output)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256(temporary.read_bytes()).hexdigest() != plan.output_sha256:
            raise RepairError("The staged output failed its hash check")
        if sha256(source.read_bytes()).hexdigest() != plan.source_sha256:
            raise RepairError("The input changed during inspection; no copy was published")
        # A link fails if *anything* appeared at the destination meanwhile.
        # Unlike replace/rename, it never clobbers a file or dangling symlink.
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("save", type=pathlib.Path, help="Pool save disk to inspect read-only")
    parser.add_argument("--out", type=pathlib.Path, help="Create this new repaired copy")
    args = parser.parse_args(argv)
    try:
        if not stat.S_ISREG(args.save.stat().st_mode):
            raise RepairError("The input must be a regular save-image file")
        if args.out is not None:
            _check_output(args.save, args.out)
        original = args.save.read_bytes()
        default = native_default()
        plan = plan_repair(original, default.icon)
        print(f"Input SHA-256: {plan.source_sha256}")
        for name, digest in default.sources:
            print(f"Game source {name} SHA-256: {digest}")
        print(f"Native default SHA-256: {sha256(default.icon).hexdigest()}")
        print(f"DIRTEN: Joined NPC in party slot {plan.slot}; icon is entirely zero")
        print(f"Verified change: {plan.changed_bytes} disk bytes, only DIRTEN's icon")
        print(f"Output SHA-256: {plan.output_sha256}")
        if args.out is None:
            print("Inspection only: No file written; use --out with a new .d64 path")
        else:
            publish_copy(args.save, args.out, plan)
            print(f"Created: {args.out}; input unchanged")
        return 0
    except (OSError, D64Error, ValueError, IndexError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
