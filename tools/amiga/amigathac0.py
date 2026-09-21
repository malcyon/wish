#!/usr/bin/env python3
"""Read the later Amiga engines' THAC0 tables and both recompute loops.

Curse and Silver Blades each carry two loops. One skips class slots whose
level is zero; the other indexes every slot, including row entry zero. This
tool checks those instructions in the player's own executable and prints what
each loop stores for a level 1--5 magic-user.

    tools/amiga/amigathac0.py

The executable is read from the registry's ``amiga`` disks. Nothing is
written, and no bytes from it are kept in this repository.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

import capstone  # noqa: E402

from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools.amiga import amiga68k, amigaglobal, amigasaves  # noqa: E402

CLASS_ORDER = ("cleric", "druid", "fighter", "paladin", "ranger",
               "magic-user", "thief", "monk")


@dataclasses.dataclass(frozen=True)
class Loop:
    """File offsets of the instructions that establish one recompute loop."""

    routine: int
    clear: int
    level_base: int
    level_read: int
    level_test: int | None
    table: int
    store: int
    limit: int
    limit_size: str = "b"

    @property
    def guarded(self) -> bool:
        return self.level_test is not None


@dataclasses.dataclass(frozen=True)
class Title:
    key: str
    title: str
    volume: str
    executable_path: str
    classes: tuple[str, ...]
    thac0_field: int
    levels_field: int
    table_offset: int
    row_bytes: int
    entry_bytes: int
    guarded: Loop
    unguarded: Loop
    unguarded_callers: tuple[int, ...]


TITLES = {
    "curse-of-the-azure-bonds": Title(
        key="curse-of-the-azure-bonds",
        title="Curse of the Azure Bonds",
        volume="CurseA",
        executable_path="/Curse",
        classes=CLASS_ORDER,
        thac0_field=0x073,
        levels_field=0x10A,
        table_offset=0x1B30,
        row_bytes=13,
        entry_bytes=1,
        guarded=Loop(0x189FA, 0x18A46, 0x18A54, 0x18A58, 0x18A58,
                     0x18A7A, 0x18AA8, 0x18AC2),
        unguarded=Loop(0x38A52, 0x38A5A, 0x38A6A, 0x38A6E, None,
                       0x38A82, 0x38AA4, 0x38AF4),
        unguarded_callers=(0x1700C, 0x260B8, 0x26EEA, 0x328F2),
    ),
    "secret-of-the-silver-blades": Title(
        key="secret-of-the-silver-blades",
        title="Secret of the Silver Blades",
        volume="Secret 1",
        executable_path="/Secret",
        classes=CLASS_ORDER[:-1],
        thac0_field=0x06A,
        levels_field=0x0AC,
        table_offset=0x1E30,
        row_bytes=38,
        entry_bytes=2,
        guarded=Loop(0xEAAC, 0xEAF8, 0xEB02, 0xEB06, 0xEB06,
                     0xEB26, 0xEB5E, 0xEB84, "w"),
        unguarded=Loop(0x3C802, 0x3C80A, 0x3C81A, 0x3C81E, None,
                       0x3C834, 0x3C85C, 0x3C8B6),
        unguarded_callers=(0xE694, 0x27130, 0x27FD8),
    ),
}


def executable(title: Title) -> bytes | None:
    """The one measured executable build on the player's Amiga disks."""
    found: dict[bytes, list[str]] = {}
    for label, image in amigasaves.images():
        try:
            disk = AmigaDisk(image)
            if disk.volume_name != title.volume:
                continue
            raw = disk.read_file(title.executable_path)
        except (AmigaDiskError, ValueError):
            continue
        found.setdefault(raw, []).append(label)
    if not found:
        return None
    if len(found) != 1:
        builds = ", ".join(
            f"{len(paths)} copy/copies of a {len(raw)}-byte build"
            for raw, paths in found.items())
        raise SystemExit(f"{title.title}: the Amiga disks disagree: {builds}")
    return next(iter(found))


def attack_table(raw: bytes, title: Title) -> dict[str, list[int]]:
    """The engine's stored-value rows, entry zero included."""
    exe = amiga68k.Executable.parse(raw)
    data = exe.small_data
    if data is None or data.file_offset is None:
        raise ValueError(f"{title.title}: not the measured small-data build")
    start = data.file_offset + title.table_offset
    end = start + len(title.classes) * title.row_bytes
    if end > data.file_offset + data.size:
        raise ValueError(f"{title.title}: THAC0 table runs outside DATA")
    result = {}
    for index, name in enumerate(title.classes):
        row = raw[start + index * title.row_bytes:
                  start + (index + 1) * title.row_bytes]
        result[name] = [int.from_bytes(row[at:at + title.entry_bytes], "big")
                        for at in range(0, len(row), title.entry_bytes)]
    return result


def recompute(rows: dict[str, list[int]], levels: dict[str, int],
              *, guarded: bool) -> int:
    """Apply either loop exactly: the larger stored byte is the better THAC0."""
    best = 0
    for name, row in rows.items():
        level = int(levels.get(name, 0))
        if guarded and level <= 0:
            continue
        best = max(best, row[min(max(level, 0), len(row) - 1)])
    return best


def _instruction(raw: bytes, at: int) -> tuple[str, str]:
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    try:
        one = next(md.disasm(raw[at:at + 12], at, count=1))
    except StopIteration as why:
        raise ValueError(f"no instruction at file offset {at:#x}") from why
    return one.mnemonic, one.op_str


def _loop_errors(raw: bytes, title: Title, loop: Loop) -> list[str]:
    expected = {
        loop.clear: ("clr.b", f"${title.thac0_field:x}"),
        loop.level_base: ("adda.w", f"#${title.levels_field:x}"),
        loop.level_read: (("tst.b" if loop.guarded else "move.b"),
                          "(a0,"),
        loop.table: ("lea.l", "(a4)"),
        loop.store: ("move.b", f"${title.thac0_field:x}"),
        loop.limit: (f"cmpi.{loop.limit_size}",
                     f"#${len(title.classes) - 1:x}"),
    }
    errors = []
    for at, (mnemonic, operand) in expected.items():
        got_mnemonic, got_operands = _instruction(raw, at)
        if got_mnemonic != mnemonic or operand not in got_operands:
            errors.append(
                f"{at:#x}: expected {mnemonic} containing {operand}, got "
                f"{got_mnemonic} {got_operands}")
    displacement = int.from_bytes(raw[loop.table + 2:loop.table + 4],
                                  "big", signed=True)
    landed = amiga68k.SMALL_DATA_BIAS + displacement
    if landed != title.table_offset:
        errors.append(
            f"{loop.table:#x}: table operand lands at data+{landed:#x}, "
            f"not data+{title.table_offset:#x}")
    return errors


def check(raw: bytes, title: Title) -> list[str]:
    """Return every disagreement between this build and the measured loops."""
    errors = _loop_errors(raw, title, title.guarded)
    errors += _loop_errors(raw, title, title.unguarded)
    exe = amiga68k.Executable.parse(raw)
    callers = tuple(at for at, _mnemonic, _ops in
                    amigaglobal.callers(exe, title.unguarded.routine))
    if callers != title.unguarded_callers:
        errors.append(
            f"{title.unguarded.routine:#x}: callers are "
            f"{', '.join(hex(at) for at in callers)}, expected "
            f"{', '.join(hex(at) for at in title.unguarded_callers)}")
    return errors


def _location(raw: bytes, at: int) -> str:
    exe = amiga68k.Executable.parse(raw)
    code = next(h for h in exe.hunks if h.kind == "CODE")
    assert code.file_offset is not None
    return f"file {at:#08x}, CODE+{at - code.file_offset:#08x}"


def report(raw: bytes, title: Title) -> list[str]:
    errors = check(raw, title)
    if errors:
        return [f"{title.title}: {error}" for error in errors]
    rows = attack_table(raw, title)
    data = amiga68k.Executable.parse(raw).small_data
    assert data is not None and data.file_offset is not None
    table_file = data.file_offset + title.table_offset
    levels = {"magic-user": 5}
    guarded = recompute(rows, levels, guarded=True)
    unguarded = recompute(rows, levels, guarded=False)
    return [
        title.title,
        f"  table: file {table_file:#08x}, DATA+{title.table_offset:#06x}",
        f"  guarded loop: {_location(raw, title.guarded.clear)}; "
        f"magic-user 5 -> {guarded}",
        f"  unguarded loop: {_location(raw, title.unguarded.clear)}; "
        f"magic-user 5 -> {unguarded}",
        "  unguarded callers: "
        + ", ".join(_location(raw, at) for at in title.unguarded_callers),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", choices=tuple(TITLES), action="append",
                        help="one title key; default is both")
    args = parser.parse_args(argv)
    keys = args.title or list(TITLES)
    status = 0
    for key in keys:
        title = TITLES[key]
        raw = executable(title)
        if raw is None:
            print(f"{title.title}: no Amiga disk; set the registry's amiga entry")
            status = 2
            continue
        errors = check(raw, title)
        print("\n".join(report(raw, title)))
        if errors:
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
