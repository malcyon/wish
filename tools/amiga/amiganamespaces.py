#!/usr/bin/env python3
"""Where each Amiga Gold Box title strips characters out of a name, read from its executable.

    tools/amiga/amiganamespaces.py                 # every title, then the census
    tools/amiga/amiganamespaces.py --title pool-of-radiance
    tools/amiga/amiganamespaces.py --model "MARY SUE FOX" --model "J. R"
    tools/amiga/amiganamespaces.py --census-only

Every title has one routine that removes a fixed set of characters from a
string: `" .*,?/:;|"` in Pool of Radiance's `/program`, `' =+<>"[].*,?/\\:;|'`
in `/Curse`, `/Secret` and `/Pools of Darkness`. Each is found by the
reference to its character set rather than by an address, and each call site
is classified by where the cleaned text goes: back into the routine's first
argument (a character record, in the one Pool of Radiance site that does it),
or into a stack buffer that becomes a file name.

A second search finds any place that swaps a space for `$FF` in place, which
is what Pool of Radiance's character creation does before its first save.

`--model` runs a name through what `/program` does to it at a save, as read
from the instructions (the `.`-pair remover, then the set remover, then the
upper-casing), and through what creation does before that.

The census reads every character record on the player's Amiga disks and in
the specimen tree (`$WISH_SPECIMENS`, then `~/wish-specimens`) and counts the
names holding a space, `$FF`, a character from either set, lower case, or
bytes left behind the terminator. The disks and specimens are opened
read-only; nothing is written. Needs `capstone`.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import os
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

import capstone  # noqa: E402

from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools.amiga import amigabackstab, amigasaves  # noqa: E402
from tools.amiga.amiga68k import SMALL_DATA_BIAS, Executable  # noqa: E402
from tools.amiga.amigaglobal import callers as small_data_callers  # noqa: E402

#: Pool of Radiance's set, NUL-terminated as `/program` stores it.
POR_SET = b" .*,?/:;|\x00"
#: The later titles' set; the routine walks exactly these seventeen bytes.
LATER_SET = b' =+<>"[].*,?/\\:;|'

#: The name field, every title: sixteen bytes, NUL-terminated.
NAME_BYTES = 16
#: Where the name sits in a Pools of Darkness `.pc` record.
POD_NAME_AT = 0x60
POR_RECORD_BYTES = 288

_LINK_A5 = 0x4E55
_RTS = 0x4E75
_JMP_ABS = 0x4EF9
_PC_CALLS = (0x4EBA, 0x6100)      # jsr d16(pc), bsr.w


def _md() -> "capstone.Cs":
    return capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)


def _word(raw: bytes, at: int) -> int:
    return struct.unpack_from(">H", raw, at)[0]


def _one(raw: bytes, at: int):
    """The single instruction at a file offset, or `None`."""
    return next(iter(_md().disasm(raw[at:at + 10], at, 1)), None)


def _run(raw: bytes, start: int, end: int) -> list:
    """Instructions decoded from `start` to `end`, stopping at the first gap."""
    out, at = [], start
    while at < end:
        ins = _one(raw, at)
        if ins is None:
            break
        out.append(ins)
        at += ins.size
    return out


def _pc_callers(raw: bytes, lo: int, hi: int, target: int) -> list[int]:
    """Every `jsr d16(pc)`, `bsr.w` or `bsr.b` between two offsets reaching `target`."""
    out = []
    for at in range(lo, hi - 3, 2):
        word = _word(raw, at)
        if word in _PC_CALLS:
            if at + 2 + struct.unpack_from(">h", raw, at + 2)[0] == target:
                out.append(at)
        elif (word & 0xFF00) == 0x6100 and word & 0xFF not in (0, 0xFF):
            short = word & 0xFF
            if at + 2 + (short - 256 if short > 127 else short) == target:
                out.append(at)
    return out


@dataclasses.dataclass(frozen=True)
class Site:
    """One call to the strip routine."""

    at: int
    #: The operand pushed as the string, as capstone prints it.
    argument: str
    #: `record` when the cleaned text is copied back through the calling
    #: routine's own first argument, `buffer` otherwise.
    result: str
    #: The routine the call is in, by its entry.
    routine: int


@dataclasses.dataclass
class Finding:
    title: str
    #: File offset of the strip routine.
    strip: int
    #: File offset of the character set it walks.
    set_at: int
    set_text: str
    sites: list[Site]
    #: Every place a space is replaced with `$FF` in place.
    ff_sites: list[int]
    #: The routines that copy the cleaned text back into a record, and for
    #: each, whether nothing but a stack check branches before it does.
    in_place: dict[int, bool]
    #: Every call to each routine in `in_place`.
    record_callers: dict[int, list[int]] = dataclasses.field(
        default_factory=dict)

    def saved_after(self, ff_site: int, reach: int = 0x60) -> int | None:
        """The first call into a record-stripping routine after a `$FF` swap."""
        later = [c for calls in self.record_callers.values() for c in calls
                 if ff_site < c <= ff_site + reach]
        return min(later) if later else None

    @property
    def strips_a_record(self) -> bool:
        return bool(self.in_place)


def _routine_start(raw: bytes, at: int, lo: int) -> int:
    """The entry of the routine containing `at`: a `link a5` or just after an `rts`."""
    for back in range(at - (at & 1), lo - 2, -2):
        word = _word(raw, back)
        if word == _LINK_A5:
            return back
        if word == _RTS and back < at - 2:
            return back + 2
    raise ValueError(f"no routine entry found before {at:#x}")


def _pushed_before(raw: bytes, entry: int, call: int):
    """The instruction that ends exactly at `call`, decoded from the entry."""
    run = [i for i in _run(raw, entry, call) if i.address + i.size == call]
    return run[0] if run else None


def _first_argument_register(raw: bytes, entry: int) -> str | None:
    """The address register the prologue loads from `$8(a5)` or `$c(a7)`."""
    for ins in _run(raw, entry, entry + 0x20):
        if ins.mnemonic == "movea.l" and ins.op_str.split(", ")[0] in (
                "$8(a5)", "$c(a7)", "$10(a7)"):
            return ins.op_str.split(", ")[1]
    return None


def _writes_back(raw: bytes, call: int, register: str | None) -> bool:
    """Whether the result of the call at `call` is copied into `register`.

    The copy is `move.l d0, -(a7)` for the source followed by the
    destination pushed last, `move.l aN, -(a7)`, and the call -- the
    instructions `/program` uses at its one write-back site.
    """
    if register is None:
        return False
    after = _run(raw, call + 4, call + 0x30)
    for n, ins in enumerate(after):
        if ins.mnemonic in ("jsr", "bsr.w", "bsr.b"):
            pushed = [i.op_str for i in after[:n]]
            return ("d0, -(a7)" in pushed
                    and bool(pushed) and pushed[-1] == f"{register}, -(a7)")
    return False


def _straight_to(raw: bytes, entry: int, end: int) -> bool:
    """Whether nothing branches between a routine's entry and `end`.

    The stack check every routine opens with, `cmpa.l ..., a7` then `bcs`,
    is not a branch in this sense: it leaves only on a stack overflow.
    """
    run = _run(raw, entry, end)
    for n, ins in enumerate(run):
        branch = (ins.mnemonic.startswith(("b", "db", "jmp", "rt"))
                  and not ins.mnemonic.startswith(("btst", "bset", "bclr",
                                                   "bchg")))
        if not branch:
            continue
        if (ins.mnemonic.startswith("bcs") and n
                and run[n - 1].mnemonic == "cmpa.l"
                and run[n - 1].op_str.endswith("a7")):
            continue
        return False
    return bool(run)


def _ff_sites(raw: bytes) -> list[int]:
    """Every compare against a space followed within five instructions by `move.b #$ff`."""
    out = []
    md = _md()
    for at in range(0, len(raw) - 12, 2):
        word = _word(raw, at)
        space = ((word & 0xF1FF) == 0x7020
                 or ((word & 0xFFC0) == 0x0C00 and _word(raw, at + 2) == 0x20))
        if not space:
            continue
        run = list(md.disasm(raw[at:at + 40], at, 6))
        if run and any(i.mnemonic == "move.b" and i.op_str.startswith("#$ff")
                       for i in run[1:]):
            out.append(at)
    return out


def _code_hunks(exe: Executable):
    return [h for h in exe.hunks if h.kind == "CODE"]


def _hunk_of(exe: Executable, at: int):
    hunk = exe.hunk_at(at)
    if hunk is None:
        raise ValueError(f"{at:#x} is in no hunk")
    return hunk


def _por_calls(exe: Executable, raw: bytes, target: int) -> list[int]:
    """Every call to a `/program` routine, direct or through a hunk's stub.

    A call from another hunk goes through that hunk's own `jmp abs.l` stub,
    whose operand has a `RELOC32` entry naming the target's hunk.
    """
    home = _hunk_of(exe, target)
    calls = _pc_callers(raw, home.file_offset, home.file_offset + home.size,
                        target)
    for (number, off), hunk_number in exe.relocs.items():
        if hunk_number != home.number:
            continue
        hunk = exe.by_number(number)
        value = struct.unpack_from(">I", raw, hunk.file_offset + off)[0]
        if (home.file_offset + value == target
                and _word(raw, hunk.file_offset + off - 2) == _JMP_ABS):
            calls += _pc_callers(raw, hunk.file_offset,
                                 hunk.file_offset + hunk.size,
                                 hunk.file_offset + off - 2)
    return sorted(set(calls))


def inspect_por(raw: bytes, title: str) -> Finding:
    """Pool of Radiance: many hunks, absolute references through `RELOC32`."""
    exe = Executable.parse(raw)
    set_at = raw.find(POR_SET)
    if set_at < 0:
        raise ValueError(f"{title}: the character set is not in the executable")
    set_hunk = _hunk_of(exe, set_at)
    fields = []
    for (number, off), target in exe.relocs.items():
        if target != set_hunk.number:
            continue
        hunk = exe.by_number(number)
        value = struct.unpack_from(">I", raw, hunk.file_offset + off)[0]
        if set_hunk.file_offset + value == set_at:
            fields.append(hunk.file_offset + off)
    if len(fields) != 1:
        raise ValueError(f"{title}: {len(fields)} references to the set, not 1")
    code = _hunk_of(exe, fields[0])
    strip = _routine_start(raw, fields[0] - 2, code.file_offset)

    calls = _por_calls(exe, raw, strip)

    sites, in_place = [], {}
    for call in sorted(calls):
        hunk = _hunk_of(exe, call)
        entry = _routine_start(raw, call, hunk.file_offset)
        push = _pushed_before(raw, entry, call)
        argument = push.op_str if push is not None else "?"
        register = _first_argument_register(raw, entry)
        back = _writes_back(raw, call, register)
        sites.append(Site(call, argument, "record" if back else "buffer",
                          entry))
        if back:
            in_place[entry] = _straight_to(raw, entry, call)
    return Finding(title, strip, set_at, POR_SET[:-1].decode("latin1"),
                   sites, _ff_sites(raw), in_place,
                   {entry: _por_calls(exe, raw, entry) for entry in in_place})


def inspect_later(raw: bytes, title: str) -> Finding:
    """Curse, Silver Blades, Pools of Darkness: SAS/Lattice small data."""
    exe = Executable.parse(raw)
    data = exe.small_data
    if data is None:
        raise ValueError(f"{title}: not a small-data executable")
    set_at = raw.find(LATER_SET, data.file_offset,
                      data.file_offset + data.size)
    if set_at < 0:
        raise ValueError(f"{title}: the character set is not in the data hunk")
    disp = (set_at - data.file_offset - SMALL_DATA_BIAS) & 0xFFFF
    code = _code_hunks(exe)[0]
    leas = [code.file_offset + at
            for at in range(0, code.size - 3, 2)
            if (_word(raw, code.file_offset + at) & 0xF1FF) == 0x41EC
            and _word(raw, code.file_offset + at + 2) == disp]
    if len(leas) != 1:
        raise ValueError(f"{title}: {len(leas)} references to the set, not 1")
    strip = _routine_start(raw, leas[0], code.file_offset)
    calls = [at for at, mnemonic, _ops in small_data_callers(exe, strip)
             if mnemonic == "jsr"]
    calls += _pc_callers(raw, code.file_offset, code.file_offset + code.size,
                         strip)
    sites, in_place = [], {}
    for call in sorted(calls):
        entry = _routine_start(raw, call, code.file_offset)
        push = _pushed_before(raw, entry, call)
        argument = push.op_str if push is not None else "?"
        # The routine works in place on its one argument, so a stack buffer
        # there is the whole answer: no record is touched.
        local = (push is not None and push.mnemonic == "pea.l"
                 and argument.startswith("-$") and argument.endswith("(a5)"))
        sites.append(Site(call, argument, "buffer" if local else "record",
                          entry))
        if not local:
            in_place[entry] = _straight_to(raw, entry, call)
    return Finding(title, strip, set_at, LATER_SET.decode("latin1"), sites,
                   _ff_sites(raw), in_place)


def inspect(raw: bytes, key: str) -> Finding:
    title = amigabackstab.TITLES[key].title
    if key == "pool-of-radiance":
        return inspect_por(raw, title)
    return inspect_later(raw, title)


# --- What `/program` does to a name, as read from the instructions -------

def _delete(buf: bytearray, at: int, count: int) -> None:
    """`$485FE`: remove `count` bytes at `at`, stopping at the terminator."""
    if count <= 0 or at > len(buf):
        return
    del buf[at:at + count]


def _remove_dot_pairs(name: bytes) -> bytes:
    """`$1627C` called with `'.'`: the substring test looks one byte back.

    It compares the one-byte substring starting at `i - 1` with `"."`, so it
    deletes a dot only at the start of the name or when the byte before it
    is a dot too, and the bound is fixed from the length before any delete.
    """
    buf = bytearray(name)
    bound = len(name) - 1 + 1
    for i in range(bound):
        if i >= len(buf) or buf[i] != 0x2E:
            continue
        start = max(i - 1, 0)
        if bytes(buf[start:start + 1]) == b".":
            _delete(buf, i, 1)
    return bytes(buf)


def _remove_set(name: bytes) -> bytes:
    """`$1634C`: for each position, test the nine set bytes in order.

    A delete shifts the next byte into the same position, which is then only
    tested against the set bytes after the one that matched, before the
    position advances. So a space that slides into place behind a deleted
    byte survives the pass. Then every `a`-`z` is upper-cased (`$79C`).
    """
    buf = bytearray(name)
    table = POR_SET[:-1]
    i = 0
    while i < len(buf):
        for c in table:
            if i < len(buf) and buf[i] == c:
                _delete(buf, i, 1)
        i += 1
    return bytes(b - 0x20 if 0x61 <= b <= 0x7A else b for b in buf)


def por_saved(name: bytes) -> bytes:
    """What `/program`'s save leaves in a record's name (`$2646C`)."""
    return _remove_set(_remove_dot_pairs(name))[:39]


def por_created(name: bytes) -> bytes:
    """What creation writes (`$184C6` then `$2646C`): spaces become `$FF`."""
    return por_saved(name.replace(b" ", b"\xff"))


# --- The census ----------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Name:
    title: str
    where: str
    raw: bytes

    @property
    def text(self) -> bytes:
        return self.raw.split(b"\x00", 1)[0]

    @property
    def tail(self) -> bytes:
        """What sits behind the terminator in the sixteen-byte field."""
        cut = self.raw.find(b"\x00")
        return b"" if cut < 0 else self.raw[cut + 1:].rstrip(b"\x00")


def _specimen_roots() -> list[pathlib.Path]:
    base = os.environ.get("WISH_SPECIMENS") or str(
        pathlib.Path.home() / "wish-specimens")
    root = pathlib.Path(base)
    if not root.is_dir():
        return []
    return [p for p in sorted(root.iterdir())
            if p.is_dir() and p.name.endswith("-amiga")]


def _images():
    yield from amigasaves.images()
    for root in _specimen_roots():
        for path in sorted(root.rglob("*.adf")):
            yield str(path), path.read_bytes()


def _later_shapes(disk: AmigaDisk, entries: list[str]):
    """The Curse or Silver Blades record layouts to scan this disk with.

    A disk carrying `/Curse` or `/Secret` is that title's; a save disk with
    neither is scanned with both and each record kept under the layout that
    finds the most characters in its file.
    """
    from goldbox.amiga_port import AMIGA_DELTAS

    leaves = {path.rsplit("/", 1)[-1] for path in entries}
    by_exe = {"Curse": "Curse of the Azure Bonds",
              "Secret": "Secret of the Silver Blades"}
    named = [by_exe[leaf] for leaf in by_exe if leaf in leaves]
    return [shape for shape in AMIGA_DELTAS
            if not named or shape.title in named]


def _names_in(disk: AmigaDisk, label: str):
    from goldbox.amiga_later import party_in_savegame
    from goldbox.amiga_savegame import PodSaveError, pod_parse

    entries = [path for path, _entry in disk.walk()]
    shapes = _later_shapes(disk, entries)
    for path in entries:
        leaf = path.rsplit("/", 1)[-1]
        low = leaf.lower()
        try:
            data = disk.read_file(path)
        except AmigaDiskError:
            continue
        where = f"{label}:{path}"
        if low.endswith((".sav", ".cha")) and len(data) == POR_RECORD_BYTES:
            yield Name("Pool of Radiance", where, data[:NAME_BYTES])
        elif low.endswith(".pc") and len(data) > POD_NAME_AT + NAME_BYTES:
            yield Name("Pools of Darkness", where,
                       data[POD_NAME_AT:POD_NAME_AT + NAME_BYTES])
        elif low.startswith("savgam") and low.endswith(".pty"):
            try:
                save = pod_parse(data)
            except PodSaveError:
                continue
            for block in save.characters:
                at = block.at + POD_NAME_AT
                yield Name("Pools of Darkness", f"{where}@{block.at:#x}",
                           data[at:at + NAME_BYTES])
        elif low.endswith(".guy") or (low.startswith("savgam")
                                      and low.endswith((".dat", ".sav"))):
            found = [(len(party), shape.title, party) for shape in shapes
                     for party in [party_in_savegame(data, shape)] if party]
            if not found:
                continue
            best = max(n for n, _title, _party in found)
            titles = [title for n, title, _party in found if n == best]
            title = titles[0] if len(titles) == 1 else " or ".join(titles)
            party = next(p for n, _t, p in found if n == best)
            for char in party:
                yield Name(title, where, char.raw[:NAME_BYTES])


def everything() -> list[Name]:
    """Every name field on the disks and in the specimens, one per file."""
    out: list[Name] = []
    for label, image in _images():
        try:
            disk = AmigaDisk(image)
            out += list(_names_in(disk, pathlib.Path(label.split("!")[0]).name))
        except (AmigaDiskError, ValueError):
            continue
    return out


def census(names: list[Name] | None = None) -> list[Name]:
    """Every distinct `(title, name field)` on the disks and in the specimens."""
    seen: dict[tuple[str, bytes], Name] = {}
    for name in everything() if names is None else names:
        seen.setdefault((name.title, name.raw), name)
    return sorted(seen.values(), key=lambda n: (n.title, n.raw))


def resaved(names: list[Name]) -> list[tuple[Name, Name | None]]:
    """Each Pool of Radiance name the save would change, and its resave.

    The resave is a record on the same disk image whose name is what
    `por_saved` predicts; `None` when that image holds no such record.
    """
    out = []
    por = [n for n in names if n.title == "Pool of Radiance"]
    for name in por:
        want = por_saved(name.text)
        if want == name.text:
            continue
        image = name.where.split(":", 1)[0]
        match = next((n for n in por if n.where.split(":", 1)[0] == image
                      and n.where != name.where and n.text == want), None)
        out.append((name, match))
    return out


def classify(name: Name) -> dict[str, bool]:
    text = name.text
    return {
        "space": b" " in text,
        "ff": b"\xff" in text,
        "por_set": any(c in POR_SET[1:-1] for c in text),
        "later_set": any(c in LATER_SET[1:] for c in text),
        "lower": any(0x61 <= c <= 0x7A for c in text),
        "tail": bool(name.tail),
    }


def _hexname(raw: bytes) -> str:
    return " ".join(f"{b:02x}" for b in raw)


def _report(finding: Finding) -> list[str]:
    out = [f"== {finding.title}",
           f"strip routine {finding.strip:06x}, set {finding.set_text!r} at "
           f"{finding.set_at:06x}"]
    for site in finding.sites:
        out.append(f"  call {site.at:06x} in {site.routine:06x}: "
                   f"argument {site.argument}, result into {site.result}")
    for entry, straight in sorted(finding.in_place.items()):
        out.append(f"  writes a record: routine {entry:06x}, "
                   f"{'unconditional' if straight else 'conditional'} from entry")
    for entry, calls in sorted(finding.record_callers.items()):
        out.append(f"  callers of {entry:06x}: "
                   + ", ".join(f"{c:06x}" for c in calls))
    swaps = [f"{a:06x}" + (f" (saved by the call at {finding.saved_after(a):06x})"
                           if finding.saved_after(a) is not None else "")
             for a in finding.ff_sites]
    out.append("  space -> $FF: " + (", ".join(swaps) or "none"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--title", choices=sorted(amigabackstab.TITLES),
                        action="append")
    parser.add_argument("--model", action="append", default=[],
                        help="a name to run through Pool of Radiance's save")
    parser.add_argument("--census-only", action="store_true")
    parser.add_argument("--no-census", action="store_true")
    args = parser.parse_args(argv)

    for text in args.model:
        raw = text.encode("latin1")
        print(f"{text!r}: saved {por_saved(raw)!r}, saved again "
              f"{por_saved(por_saved(raw))!r}, created {por_created(raw)!r}")
    if args.model and not args.title and not args.census_only:
        return 0

    status = 0
    if not args.census_only:
        for key in args.title or sorted(amigabackstab.TITLES):
            raw = amigabackstab.executable(amigabackstab.TITLES[key])
            if raw is None:
                print(f"== {amigabackstab.TITLES[key].title}: no executable "
                      f"on any disk here")
                status = 2
                continue
            print("\n".join(_report(inspect(raw, key))))
    if not args.no_census:
        every = everything()
        names = census(every)
        counts: dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter)
        for name in names:
            counts[name.title]["names"] += 1
            for flag, on in classify(name).items():
                counts[name.title][flag] += on
        print("== census: distinct name fields")
        for title, row in sorted(counts.items()):
            print(f"  {title}: " + ", ".join(f"{k} {v}" for k, v in row.items()))
        for name in names:
            flags = [k for k, on in classify(name).items() if on]
            if flags:
                print(f"  {name.title:<28} {_hexname(name.raw)}  "
                      f"{','.join(flags)}  {name.where}")
        print("== Pool of Radiance names the save would change")
        for name, match in resaved(every):
            print(f"  {name.text!r} at {name.where}: "
                  + (f"{match.text!r} at {match.where}" if match
                     else "no resave on that image"))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
