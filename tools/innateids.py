#!/usr/bin/env python3
"""Where a DOS innate effect id comes from: the engine's table, and who carries it.

`#395 (A Curse cleric carries the ranger's innate effect and a human carries
the elf's, in the specimen both ids were graded from)` is why this exists.
`goldbox/dos_codec.py` grades effect id 134 as Curse of the Azure Bonds' ranger id
and 107 as the elf's, and a code review found a cleric carrying 134 and a
human carrying 107 in the same specimen the grades cite.  A grade of that
shape is a claim about a **partition** -- every carrier of this id is a
ranger, and no non-ranger carries it -- and a partition can be checked two
ways, so there is a subcommand for each.

**`seed` reads the engine's own creation table** out of `GAME.OVR`, which is
the route `.claude/rules/testing.md` says to prefer when provenance is in
doubt: a finding taken from the game's own instructions cannot be poisoned by
an edited save.  It finds `add_affect` by the shape of its call sites, walks
character creation's switch on the record's race byte and on its class byte,
and prints the `(id, duration, data, flag)` each branch pushes -- which is the
nine-byte `.SPC`/`.FX` record the engine then writes.

    tools/innateids.py seed                 # the archives' Pool of Radiance
    tools/innateids.py seed --game CURSE
    tools/innateids.py seed --game-dir DIR  # a directory holding GAME.OVR

**`census` enumerates the corpus**: every DOS Gold Box character record it can
find, its sibling effect file (`.SPC`/`.FX`/`.SFX`/`.EFX`, per title), and who
carries what.

    tools/innateids.py census --title curse            # one row per record
    tools/innateids.py census --title curse --by-id    # one block per id

`--by-id` is the view that answers the question: for each id, every distinct
record carrying it with its race, class and class levels, so "all rangers and
nothing else" is visible as a fact rather than asserted.

**Provenance is printed, never assumed.**  `.claude/rules/testing.md`: a
specimen is only evidence if we know who wrote it.  Each row carries a grade:

* `spec`  -- inside `$WISH_SPECIMENS`, with the specimen name;
* `ours`  -- written by one of this project's own writers, by the filename
  prefixes `tools/dostailcensus.py` already lists, or by a `provenance.toml`
  whose `made_by` names our writer.  Never evidence about the game;
* `found` -- anywhere else: the archives, a game disk, a `work/` directory.
  No chain of custody.

Records this project wrote are **excluded by default** and included, marked,
by `--ours`; an emulator instance's staged game tree is skipped outright, the
exclusion `tools/dostailcensus.py` records as the trap that cost a re-take.

Nothing is written anywhere; every file is opened read-only, and only
addresses and small tables of numbers are printed -- never the game's bytes.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import pathlib
import re
import struct
import sys
import tomllib

import capstone

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_codec as gdos  # noqa: E402
from goldbox import dos_port as dl  # noqa: E402
from tools import dostailcensus, specimens  # noqa: E402

#: The four titles' effect-file suffixes, from each shape.  Named here so the
#: sweep can find a record's effects without opening every file twice.
EFFECT_SUFFIXES = tuple(sorted({s.effect_suffix for s in dl.DELTAS_BY_SIZE.values()}))

#: Bytes 1-4 of an innate effect's record.  `goldbox/dos_codec.py`'s own constant;
#: a record matching it in those four bytes is in "the innate payload shape",
#: which is the phrase `#395` uses.
INNATE_PAYLOAD = gdos.INNATE_PAYLOAD


def _provenance_for(path: pathlib.Path) -> tuple[str | None, dict]:
    """The specimen name and `provenance.toml` covering `path`, if any."""
    for parent in path.parents:
        toml = parent / specimens.PROVENANCE_NAME
        if toml.is_file():
            try:
                return parent.name, tomllib.loads(toml.read_text())
            except (OSError, tomllib.TOMLDecodeError):   # pragma: no cover
                return parent.name, {}
        sibling = parent / f"{path.stem}.provenance.toml"
        if sibling.is_file():                            # pragma: no cover
            try:
                return path.stem, tomllib.loads(sibling.read_text())
            except (OSError, tomllib.TOMLDecodeError):
                return path.stem, {}
    return None, {}


#: Phrases in a `provenance.toml`'s `made_by` that mean the record is ours.
#: `tools/specimens.py` asks for that field in exactly these words, and two
#: specimens in the tree are our writer's output kept deliberately.
OURS_IN_MADE_BY = ("our own writer", "our writer", "this project's own writer",
                   "goldbox.dos.new_dos_save", "dosrecordwrite.py")


class Record:
    """One distinct DOS record with its effect file."""

    def __init__(self, path: pathlib.Path, data: bytes, spc: bytes) -> None:
        self.path = path
        self.data = data
        self.spc = spc
        self.shape = dl.deltas_for(len(data))
        self.char = gdos.DosCharacter(data, deltas=self.shape)
        self.effects = [spc[i:i + dl.EFFECT_SIZE]
                        for i in range(0, len(spc), dl.EFFECT_SIZE)
                        if len(spc[i:i + dl.EFFECT_SIZE]) == dl.EFFECT_SIZE]
        self.digest = hashlib.sha256(data + spc).hexdigest()[:12]
        self.specimen, prov = _provenance_for(path)
        made = str(prov.get("made_by", "")).lower()
        self.ours = (dostailcensus.is_built(path)
                     or any(p in made for p in OURS_IN_MADE_BY))
        self.grade = ("ours" if self.ours
                      else "spec" if self.specimen else "found")
        self.paths = [path]

    # -- the columns -------------------------------------------------------
    @property
    def name(self) -> str:
        try:
            return self.char.name or "(unnamed)"
        except Exception:                                # pragma: no cover
            return "(unreadable)"

    def _get(self, field):
        try:
            return self.char.get(field)
        except Exception:                                # pragma: no cover
            return None

    @property
    def race(self) -> str:
        n = self._get("race")
        table = self.shape.race_numbers
        return table[n] if isinstance(n, int) and n < len(table) else f"?{n}"

    @property
    def klass(self) -> str:
        n = self._get("char_class")
        return (dl.CLASS_NUMBERS[n]
                if isinstance(n, int) and n < len(dl.CLASS_NUMBERS)
                else f"?{n}")

    @property
    def levels(self) -> str:
        return "/".join(f"{k[:4]}{v}" for k, v in self.char.class_levels.items())

    @property
    def former(self) -> str:
        raw = self._get("former_class_levels")
        if not raw:
            return ""
        return "/".join(f"{gdos.CLASS_BY_SLOT.get(n, n)[:4]}{v}"
                        for n, v in enumerate(raw) if v)

    @property
    def ids(self) -> list[int]:
        return [e[0] for e in self.effects]

    def shape_of(self, effect: bytes) -> str:
        """`innate` when bytes 1-4 are `INNATE_PAYLOAD`, else the four bytes."""
        return ("innate" if effect[1:5] == INNATE_PAYLOAD
                else " ".join(f"{b:02X}" for b in effect[1:5]))

    @property
    def who(self) -> str:
        return (f"{self.name:16s} {self.race:9s} {self.klass:20s} "
                f"{self.levels:24s}")


#: Directory names of Gold Box titles on the same engine whose record this
#: module has **no layout for**, and `foreign_title()`, which names the one a
#: path is inside.  Moved to `tools/dostailcensus.py` by
#: `#400 (The DOS record census counts Gateway and Treasures characters as
#: Curse and Pools of Darkness ones, because it identifies a title by record
#: size)`, so every caller of its finder gets the same exclusion this module
#: worked out first -- kept as names here so nothing importing them breaks.
FOREIGN_TITLES = dostailcensus.FOREIGN_TITLES
foreign_title = dostailcensus.foreign_title


def collect(roots, want_ours: bool, title: str | None,
            foreign: bool = False) -> tuple[list[Record], collections.Counter]:
    """Every distinct record under `roots`, deduplicated on record+effects.

    Returns the records and a count of what was skipped for belonging to a
    title this module has no layout for.
    """
    seen: dict[str, Record] = {}
    skipped: collections.Counter = collections.Counter()
    for root in roots:
        root = pathlib.Path(root)
        if not root.exists():
            continue
        walk = sorted(root.rglob("*")) if root.is_dir() else [root]
        for path in walk:
            if (not path.is_file()
                    or path.suffix.lower() not in dostailcensus.RECORD_SUFFIXES):
                continue
            if any(d in path.as_posix() for d in dostailcensus.SCRATCH_DIRS):
                continue
            try:
                size = path.stat().st_size
            except OSError:                              # pragma: no cover
                continue
            if size not in dl.DELTAS_BY_SIZE:
                continue
            other = foreign_title(path)
            if other and not foreign:
                skipped[other] += 1
                continue
            shape = dl.DELTAS_BY_SIZE[size]
            if title and title.lower() not in shape.key:
                continue
            spc_path = path.with_suffix(shape.effect_suffix)
            spc = spc_path.read_bytes() if spc_path.is_file() else b""
            try:
                rec = Record(path, path.read_bytes(), spc)
            except Exception as exc:                     # pragma: no cover
                print(f"  skipped {path}: {exc}", file=sys.stderr)
                continue
            if rec.ours and not want_ours:
                continue
            key = f"{rec.shape.key}:{rec.digest}"
            if key in seen:
                seen[key].paths.append(path)
            else:
                seen[key] = rec
    return list(seen.values()), skipped


def by_record(records: list[Record]) -> None:
    for rec in sorted(records, key=lambda r: (r.shape.key, r.name)):
        effects = ", ".join(
            f"{e[0]} [{rec.shape_of(e)}]" for e in rec.effects) or "-"
        print(f"  {rec.grade:5s} {rec.who} items{rec.char.get('item_count'):<3d}"
              f" {effects}")
        if rec.former:
            print(f"        former {rec.former}")
        print(f"        {rec.specimen or rec.path.parent.name}/{rec.path.name}")


def by_id(records: list[Record]) -> None:
    carriers: dict[int, list[tuple[Record, bytes]]] = collections.defaultdict(list)
    for rec in records:
        for e in rec.effects:
            carriers[e[0]].append((rec, e))
    for eid in sorted(carriers):
        rows = carriers[eid]
        classes = collections.Counter(r.klass for r, _ in rows)
        races = collections.Counter(r.race for r, _ in rows)
        print(f"\nid {eid} (0x{eid:02X}) -- {len(rows)} record(s)")
        print(f"  classes: {dict(classes)}")
        print(f"  races:   {dict(races)}")
        for rec, e in sorted(rows, key=lambda t: t[0].name):
            print(f"    {rec.grade:5s} {rec.who} [{rec.shape_of(e)}] "
                  f"{rec.specimen or rec.path.parent.name}/{rec.path.name}")


# ---------------------------------------------------------------------------
# The engine's own creation table
# ---------------------------------------------------------------------------
#: `9A off16 seg16` -- a far call, which is how every Gold Box overlay reaches
#: another unit's public entry.
FAR_CALL = re.compile(rb"\x9a(..)(..)", re.S)

#: `mov al, imm8 / push ax`, the only way this compiler passes a small
#: constant, and `xor ax, ax / push ax` for zero.
PUSH_IMM = re.compile(rb"(?:\xb0(.)\x50|\x31\xc0\x50)", re.S)

#: `mov al, byte ptr es:[di + imm8]` -- a record field being read into `al`,
#: which is what every one of these switches is keyed on.
FIELD_READ = re.compile(rb"\x26\x8a\x45(.)", re.S)


def _md() -> capstone.Cs:
    return capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)


def _call_sites(ovr: bytes) -> dict[tuple[int, int], list[int]]:
    """Far-call target -> the file offsets that call it."""
    out: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    for m in FAR_CALL.finditer(ovr):
        off, seg = struct.unpack("<HH", m.group(0)[1:])
        out[(seg, off)].append(m.start())
    return out


def _pushed_before(ovr: bytes, at: int, want: int = 4) -> list[int] | None:
    """The last `want` constants pushed immediately before the call at `at`.

    Read backwards over `mov al, imm / push ax` and `xor ax, ax / push ax`
    pairs only, so a call whose arguments are computed rather than constant
    comes back `None` instead of a guess.
    """
    out: list[int] = []
    cursor = at
    while len(out) < want:
        if cursor >= 3 and ovr[cursor - 3:cursor] == b"\x31\xc0\x50":
            out.append(0)
            cursor -= 3
        elif cursor >= 3 and ovr[cursor - 3] == 0xB0 and ovr[cursor - 1] == 0x50:
            out.append(ovr[cursor - 2])
            cursor -= 3
        else:
            return None
    return list(reversed(out))


def add_affect(ovr: bytes, race_field: int, window: int = 0x400) -> tuple[int, int]:
    """The far call character creation's race switch makes with constants.

    `docs/162-spc-permanence.md` names it `add_affect(id, duration, data,
    flag)` in Pool of Radiance, where it is `lcall 0xB0:0x52`.  The address
    moves between titles and the **shape** does not, so it is found by the
    shape -- but "the call reached with four constants most often in the
    overlay" is the wrong shape and picks something else in Pool of Radiance.

    What is distinctive is *where* it is called from: inside a switch on the
    record's race byte.  So this scores each far-call target by the constant
    calls to it that sit in a race-switch window, and takes the best.
    """
    score: collections.Counter = collections.Counter()
    for m in FIELD_READ.finditer(ovr):
        at = m.start()
        if m.group(1)[0] != race_field or ovr[at + 4] != 0x3C:
            continue
        for c in FAR_CALL.finditer(ovr[at:at + window]):
            if _pushed_before(ovr, at + c.start()) is None:
                continue
            off, seg = struct.unpack("<HH", c.group(0)[1:])
            score[(seg, off)] += 1
    if not score:
        raise ValueError("no far call with four constant arguments inside a "
                         f"switch on record byte 0x{race_field:02X}")
    return score.most_common(1)[0][0]


def seed_switches(ovr: bytes, target: tuple[int, int], field: int,
                  window: int = 0x400
                  ) -> list[tuple[int, dict[int, list[tuple[int, ...]]]]]:
    """Every `(file offset, {value: add_affect arguments})` switch on `field`.

    Anchored on a read of the record byte at `field` into `al`, followed by
    `cmp al` and at least two `add_affect` calls in `window` bytes.  The walk
    stops at the first read of a *different* record byte, so one switch never
    runs into the next.

    **All of them, not the first.**  Curse of the Azure Bonds holds two copies
    of the racial table -- creation's, and the one on the path that takes a
    character in from a file -- and a reader that stopped at the first would
    never know the second was there or whether it agreed.
    """
    seg, off = target
    call = b"\x9a" + struct.pack("<HH", off, seg)
    found = []
    for m in FIELD_READ.finditer(ovr):
        at = m.start()
        if m.group(1)[0] != field or ovr[at + 4] != 0x3C:
            continue
        if ovr[at:at + window].count(call) < 2:
            continue
        out: dict[int, list[tuple[int, ...]]] = {}
        value: int | None = None
        for insn in _md().disasm(ovr[at:at + window], at):
            m2, ops = insn.mnemonic, insn.op_str
            if (m2 == "mov" and insn.address != at
                    and ops.startswith("al, byte ptr es:[di + ")
                    and int(ops.rsplit("+ ", 1)[1].rstrip("]"), 16) != field):
                break
            if m2 == "cmp" and ops.startswith("al, "):
                try:
                    value = int(ops.rsplit(", ", 1)[1], 0)
                except ValueError:
                    # `cmp al, byte ptr [bp - 0x50]` -- a comparison against
                    # something that is not a constant, so this branch is not
                    # keyed on a value this reader can name.
                    value = None
            elif m2 == "lcall" and ops == f"0x{seg:x}, 0x{off:x}":
                args = _pushed_before(ovr, insn.address)
                if args is None or value is None:
                    continue
                out.setdefault(value, []).append(tuple(args))
        if out:
            found.append((at, out))
    if not found:
        raise ValueError(f"no switch on record byte 0x{field:02X} "
                         f"seeding {seg:04x}:{off:04x}")
    return found


def constant_sites(ovr: bytes, target: tuple[int, int],
                   eid: int | None = None) -> list[int]:
    """The file offsets calling `target` with four constants pushed.

    `eid` restricts that to the sites whose first argument is that effect id,
    which is what turns "the ranger branch pushes 134" into "and nothing else
    in the overlay does".
    """
    seg, off = target
    call = b"\x9a" + struct.pack("<HH", off, seg)
    out = []
    for m in re.finditer(re.escape(call), ovr):
        args = _pushed_before(ovr, m.start())
        if args and (eid is None or args[0] == eid):
            out.append(m.start())
    return out


def seed(game: pathlib.Path, ids: list[int]) -> int:
    ovr = (game / "GAME.OVR").read_bytes()
    shape = _shape_for_game(game)
    fields = dl.FIELDS_BY_NAME_FOR[shape.key]
    target = add_affect(ovr, fields["race"].offset)
    print(f"{game}")
    print(f"  GAME.OVR {len(ovr)} bytes, read as {shape.title}")
    print(f"  add_affect is lcall {target[0]:04x}:{target[1]:04x}, "
          f"{len(constant_sites(ovr, target))} call sites with "
          f"four constant arguments")
    for what, field, names in (
            ("race", fields["race"].offset, shape.race_numbers),
            ("class", fields["char_class"].offset, dl.CLASS_NUMBERS)):
        print(f"\n  switch on the record's {what} byte 0x{field:02X} "
              f"-- (id, duration, data, flag)")
        try:
            switches = seed_switches(ovr, target, field)
        except ValueError as exc:
            print(f"    {exc}")
            continue
        for at, table in switches:
            print(f"    GAME.OVR:0x{at:X}")
            for value, calls in sorted(table.items()):
                who = names[value] if value < len(names) else "?"
                shown = ", ".join(f"{c[0]} ({c[1]}, 0x{c[2]:02X}, {c[3]})"
                                  for c in calls)
                print(f"      {value:2d} {who:20s} {shown}")
    for eid in ids:
        sites = constant_sites(ovr, target, eid)
        where = ", ".join(f"0x{s:X}" for s in sites) or "nowhere"
        print(f"\n  id {eid} is pushed to add_affect at {len(sites)} "
              f"site(s): {where}")
    return 0


def _shape_for_game(game: pathlib.Path):
    """Which title's record layout this game directory holds.

    Named by the directory, and checked against the overlay: a title whose
    record byte offsets are wrong would read the wrong switch silently.
    """
    by_dir = {"poolrad": "pool-of-radiance", "curse": "curse-of-the-azure-bonds",
              "secret": "secret-of-the-silver-blades",
              "pools of darkness": "pools-of-darkness"}
    key = by_dir.get(game.name.lower())
    if key is None:
        raise ValueError(f"{game.name} is not a directory this reads a layout "
                         f"for -- one of {sorted(by_dir)}")
    return dl.DELTAS_BY_KEY[key]


def _game_dir(args) -> pathlib.Path:
    if args.game_dir:
        return pathlib.Path(args.game_dir)
    from tools import dosbox  # noqa: PLC0415
    return dosbox.find_game(args.game) if args.game else dosbox.find_game()


def census(args) -> int:
    roots = list(args.roots)
    if not roots:
        roots.append(specimens.tree_root())
        arch = dostailcensus.archives()
        if arch:
            roots.append(arch)
        roots.append(REPO / "work")

    records, skipped = collect(roots, args.ours, args.title, args.foreign)
    ours = sum(1 for r in records if r.ours)
    print(f"{len(records)} distinct records "
          f"({len(records) - ours} not ours, {ours} ours) under:")
    for r in roots:
        print(f"  {r}")
    with_effects = sum(1 for r in records if r.effects)
    print(f"{with_effects} carry an effect file")
    for other, n in sorted(skipped.items()):
        print(f"skipped {n} record(s) under {other}: the same record size as "
              f"a title read here, and not the same id space")
    if args.by_id:
        by_id(records)
    else:
        by_record(records)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("census", help="who carries which id, across the corpus")
    c.add_argument("roots", nargs="*", type=pathlib.Path,
                   help="directories to sweep; default the specimen tree, "
                        "the archives and work/")
    c.add_argument("--title", help="substring of a shape key: pool, curse, "
                                   "silver, darkness")
    c.add_argument("--by-id", action="store_true",
                   help="one block per effect id, with every carrier")
    c.add_argument("--ours", action="store_true",
                   help="include records this project's writers made")
    c.add_argument("--foreign", action="store_true",
                   help="include titles this module has no layout for, whose "
                        "records are read through a same-sized title's table")

    s = sub.add_parser("seed", help="the engine's own creation table")
    s.add_argument("--game", help="archives game directory name, e.g. CURSE")
    s.add_argument("--game-dir", help="a directory holding GAME.OVR")
    s.add_argument("--ids", default="",
                   help="comma-separated ids to locate every call site of")

    args = ap.parse_args(argv)
    if args.command == "census":
        return census(args)
    ids = [int(x, 0) for x in args.ids.split(",") if x.strip()]
    return seed(_game_dir(args), ids)


if __name__ == "__main__":
    raise SystemExit(main())
