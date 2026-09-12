#!/usr/bin/env python3
"""Which words a converted Amiga saved game zeroes could an unvisited area fill?

`#446 (The Amiga saved game's zero argument rests on three of the game's
twenty-nine areas)` is the ticket.  `goldbox.amiga_por.por_savegame_zeroes` ends
by sweeping every offset of the 5120-byte variable array no earlier writer
claimed and declaring all of them zero on the strength of "this word reads
zero in every Amiga saved game swept so far" -- and every Amiga saved game on
this machine was made in three of the game's twenty-nine areas.  A word that
is zero in New Phlan, the Slums and one wilderness window need not be zero in
Valjevo Castle.

This says how many of those bytes an unvisited area could plausibly fill, and
which saved game would settle each.  It reads seven things, none of them
committed and none of them ours:

1. **The build.** A container built by `goldbox.amiga_por.new_por_savegame` from a
   real source save, so the catch-all count is the writer's own rather than a
   number quoted from a document.
2. **The game's own scripts**, `ecl.dax` off Amiga disk 2, every block walked
   from its five entry `GOTO`s through `tools/eclcensus.py`'s decoder -- so a
   word is "named by a script" because a reachable statement names it, not
   because two bytes of a data table happen to spell it.
3. **The VM's address classes.**  A script names the second and third heap
   blocks `$6B00`-`$6EFF` and `$9700`-`$98FF`; the file names them `$4D00`-
   `$50FF` and `$5100`-`$52FF` (`docs/163-dos-vm-address-map.md`).  Censusing
   under the file's contiguous name is what hid every one of those references
   the last time somebody looked, which is why the mapping is here and not
   assumed away.
4. **The Amiga corpus**, every distinct `savgam*.dat` in the specimen tree.
5. **The DOS corpus**, optionally: DOS runs the same scripts at the same VM
   addresses, so a word a DOS save holds non-zero is a word some area fills,
   whichever port is asked.  It is corroboration and not proof -- the two
   engines already disagree about `$5082` (`docs/165-amiga-savegame.md`).
6. **The C64 corpus**, every distinct `SAVEDGAME0` in the specimen tree: a
   third port, standing in three areas neither of the other two reaches, and
   a witness for block 1 alone.
7. **`/program` off Amiga disk 1**, under `--engine`: every site that loads
   one of the three block pointers and then uses a constant displacement off
   it, which is the only way the engine reaches an array word without going
   through the VM.  A word neither this nor the script census names is one
   nothing in the game touches at a statically known address.

    tools/amigazerowords.py                       the report
    tools/amigazerowords.py --dos PATH [PATH...]  add DOS containers
    tools/amigazerowords.py --engine             add the engine's own accesses
    tools/amigazerowords.py --json work/issue446/words.json

Everything is read; nothing is written but the JSON the caller asks for, and
no string of the game's is printed.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import amiga_dax, amiga_por, c64_port  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from tools import amigasaves, eclcensus, gamedisks  # noqa: E402

#: The head of the sweep sentence `por_savegame_zeroes` gives every word no
#: earlier writer claimed.  Matched rather than reproduced, so a reword of
#: the reason string shows up here as a count of zero instead of silently
#: changing what is being measured.
CATCH_ALL = "zeroed: this word reads zero in every Amiga saved game swept"

#: The three heap blocks the array is written from, as `(vm base, words)` in
#: file order.  `docs/163-dos-vm-address-map.md`, from the DOS VM's own
#: address classifier at `GAME.OVR:0x7BCE`; the Amiga writes the same three
#: pointers.
BLOCKS = ((0x4900, 1024), (0x6B00, 1024), (0x9700, 512))

#: Areas the Amiga corpus stands in, filled from the corpus itself.  Named
#: here only so a reader can see there is no hard-coded list.
CORPUS_AREAS: set = set()


def vm_word(address: int) -> "int | None":
    """File word index for a VM address, or None if it is not in the array."""
    at = 0
    for base, words in BLOCKS:
        if base <= address < base + words:
            return at + address - base
        at += words
    return None


def vm_address(word: int) -> int:
    """The VM address of a file word -- the name a script would use."""
    at = 0
    for base, words in BLOCKS:
        if word < at + words:
            return base + word - at
        at += words
    raise ValueError(word)


def file_address(word: int) -> int:
    """The contiguous `$4900`-`$52FF` name the file and our own code use."""
    return 0x4900 + word


# -- the inputs --------------------------------------------------------------

def ecl_dax() -> bytes:
    """`/ecl.dax` off the player's own Amiga Pool of Radiance disk 2."""
    for _name, data in amigasaves.images():
        try:
            return AmigaDisk(bytearray(data)).read_file("/ecl.dax")
        except Exception:                       # not that disk
            continue
    raise SystemExit("No /ecl.dax on any Amiga disk; see tools/gamedisks.py")


def amiga_program() -> bytes:
    """`/program` off the player's own Amiga Pool of Radiance disk 1."""
    for _name, data in amigasaves.images():
        try:
            return AmigaDisk(bytearray(data)).read_file("/program")
        except Exception:                       # not that disk
            continue
    raise SystemExit("No /program on any Amiga disk; see tools/gamedisks.py")


def amiga_corpus() -> "list[tuple[str, bytes]]":
    """Every distinct Amiga Pool of Radiance saved game in the specimen tree."""
    from tools import specimens

    root = specimens.tree_root()
    found: dict = {}
    for image in sorted(pathlib.Path(root).rglob("*.[aA][dD][fF]")):
        try:
            disk = AmigaDisk(bytearray(image.read_bytes()))
        except Exception:
            continue
        for path, _entry in disk.walk():
            if "savgam" not in path.lower():
                continue
            data = disk.read_file(path)
            if len(data) != amiga_por.POR_SAVEGAME_SIZE:
                continue
            found.setdefault(hashlib.md5(data).hexdigest(),
                             (f"{image.parent.name}{path}", data))
    return [found[key] for key in sorted(found, key=lambda k: found[k][0])]


def c64_corpus() -> "list[tuple[str, bytes]]":
    """Every distinct C64 `SAVEDGAME0` in the specimen tree.

    A third port, and it reaches areas the other two corpora do not -- but it
    witnesses **block 1 only**: `SAVEDGAME0` images `$4900`-`$64FF` and
    `SAVEDGAME1` `$8300`-`$8AFF`, so the VM's `$6B00` and `$9700` blocks are
    in neither file.  Above about `$4B00` it is not a witness even for block
    1, because the C64's engine keeps resident display data in the page the
    VM addresses as block 1 while the Amiga allocates its own.  The caller is
    told the count so it can see that for itself.
    """
    from goldbox import d64
    from tools import specimens

    found: dict = {}
    for image in sorted(pathlib.Path(specimens.tree_root()).rglob("*.[dD]64")):
        try:
            disk = d64.D64(image.read_bytes())
        except Exception:
            continue
        for entry in disk.directory():
            if entry.raw_name.rstrip(b"\xa0") != b"SAVEDGAME0":
                continue
            try:
                data = disk.read_file("SAVEDGAME0")
            except Exception:
                continue
            found.setdefault(hashlib.md5(data).hexdigest(),
                             (image.stem, data))
    return [found[key] for key in sorted(found, key=lambda k: found[k][0])]


def dos_corpus(paths: "list[str]") -> "list[tuple[str, bytes]]":
    """Every distinct DOS Pool of Radiance container under the paths given."""
    from goldbox import dos_savegame

    size = dos_savegame.SAVGAM_SIZE
    found: dict = {}
    for entry in paths:
        here = pathlib.Path(entry).expanduser()
        files = ([here] if here.is_file()
                 else sorted(here.rglob("[sS][aA][vV][gG][aA][mM]*")))
        for path in files:
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if len(data) != size:
                continue
            found.setdefault(hashlib.md5(data).hexdigest(), (str(path), data))
    return [found[key] for key in sorted(found, key=lambda k: found[k][0])]


def scripts(ecl: bytes) -> "dict[int, bytes]":
    """Each area's own `ecl.dax` block past its two-byte header, by area id."""
    out = {}
    for area in range(64):
        try:
            out[area] = amiga_dax.block(ecl, area, "ecl.dax")[2:]
        except Exception:
            continue
    return out


# -- the census --------------------------------------------------------------

class Census:
    """Which areas' scripts name each word of the variable array."""

    def __init__(self, bodies: "dict[int, bytes]"):
        game = c64_port.by_key("pool-of-radiance")
        root = gamedisks.find("pool-of-radiance")
        if root is None:
            raise SystemExit("No Pool of Radiance disks; see tools/gamedisks.py")
        # The opcode tables and operand counts come out of the C64 DUNGEON,
        # exactly as tools/eclcensus.py reads the DOS blocks with them.
        machine, _base, _c64, _sides, _dos = eclcensus.load_port(
            str(root), game, None)
        keyed = {f"{area:02d}": body for area, body in bodies.items()}
        self.base = eclcensus.script_base(machine, keyed)
        hits, reach = eclcensus.census(machine, keyed, self.base)
        self.coverage = (sum(a for a, _b in reach.values()),
                         sum(b for _a, b in reach.values()))
        self.writes: dict = collections.defaultdict(set)
        self.reads: dict = collections.defaultdict(set)
        for hit in hits:
            word = vm_word(hit.address)
            if word is None:
                continue
            area = int(hit.script)
            (self.writes if hit.write else self.reads)[word].add(area)
        self.raw: dict = collections.defaultdict(set)
        for area, body in bodies.items():
            for word in self._pairs(body):
                self.raw[word].add(area)

    @staticmethod
    def _pairs(body: bytes) -> set:
        """Every array word a little-endian byte pair anywhere in the script
        would name.  A gross over-approximation of "referenced", on purpose:
        a word that does not appear even here is named by nothing, whatever
        the walk missed."""
        seen = set()
        for i in range(len(body) - 1):
            word = vm_word(body[i] | (body[i + 1] << 8))
            if word is not None:
                seen.add(word)
        return seen


#: The three heap-block pointers, as offsets into `/program`'s BSS hunk 32.
#: The load routine at `0x27186`-`0x271cc` reads 2048, 2048 and 1024 bytes
#: through them in file order, which is what identifies them; the fourth,
#: `0xa4`, takes the 7680-byte script buffer.
POINTERS = {0x98: 0x4900, 0x9C: 0x6B00, 0xA0: 0x9700}
#: How far past a `movea.l h32+ptr, aN` to keep reading displacements off
#: that register.  Measured rather than guessed: 40, 60, 120 and 240 bytes
#: all give the same 52 words, so nothing is being cut off.
POINTER_WINDOW = 120


class EngineCensus:
    """Which array words `/program` itself touches at a constant offset.

    The engine reaches the array two ways.  Almost all of it goes through the
    ECL VM's address classifier, so a script's `$6DD2` is an address in the
    bytecode and not in the executable; those are `Census` above.  The rest is
    the engine's own code loading a block pointer and using a fixed
    displacement -- `movea.l h32+0x98, a0; move.w $1FE(a0), d0` is the loader
    reading `$49FF`.  This finds every one of those.

    A word neither census names is one nothing in the game reads or writes at
    a statically known address.  It can still be reached by an *indexed*
    access, so the count of those is reported rather than assumed to be zero.
    """

    def __init__(self, program: bytes):
        import re
        import struct

        from tools import amiga68k

        exe = amiga68k.Executable.parse(program)
        md = amiga68k._capstone()
        disp = re.compile(r"(-?)\$([0-9a-f]+)\(a([0-7])\)")
        self.reads: dict = collections.defaultdict(set)
        self.writes: dict = collections.defaultdict(set)
        self.indexed = 0
        self.sites = 0
        for i in range(0, len(program) - 6, 2):
            op = struct.unpack(">H", program[i:i + 2])[0]
            if (op & 0xF1FF) != 0x2079:      # movea.l abs.l, aN
                continue
            reg = (op >> 9) & 7
            value = struct.unpack(">I", program[i + 2:i + 6])[0]
            hunk = exe.hunk_at(i)
            if hunk is None or hunk.kind != "CODE":
                continue
            if exe.relocs.get((hunk.number, i + 2 - hunk.file_offset)) != 32:
                continue
            if value not in POINTERS:
                continue
            self.sites += 1
            base = POINTERS[value]
            at, end, biased = i + 6, i + 6 + POINTER_WINDOW, False
            while at < end:
                try:
                    insn = next(iter(md.disasm(program[at:end], at)))
                except StopIteration:
                    break
                text = insn.op_str
                if insn.mnemonic.startswith("adda") and text.endswith(f"a{reg}"):
                    biased = True
                if (insn.mnemonic.startswith("movea")
                        and text.endswith(f"a{reg}") and at != i):
                    break                      # the register is somebody else's
                for m in disp.finditer(text):
                    if int(m.group(3)) != reg:
                        continue
                    d = int(m.group(2), 16)
                    if m.group(1) == "-":
                        d = -d
                    if biased:
                        self.indexed += 1
                        continue
                    if not 0 <= d < 2048 or d % 2:
                        continue
                    word = vm_word(base + d // 2)
                    if word is None:
                        continue
                    # The displacement is a write when it is the destination,
                    # which for 68000 is the last operand -- and `clr` has no
                    # other.
                    dest = (text.rsplit(",", 1)[-1].strip() == m.group(0)
                            or insn.mnemonic.startswith("clr"))
                    (self.writes if dest else self.reads)[word].add(at)
                at = insn.address + insn.size

    def touches(self, word: int) -> bool:
        return bool(self.reads.get(word) or self.writes.get(word))


def live_words(saves: "list[tuple[str, bytes]]", *, at: int, big: bool) -> set:
    """Word indices non-zero in at least one of these containers."""
    out = set()
    for _label, data in saves:
        for word in range(2560):
            i = at + 2 * word
            if int.from_bytes(data[i:i + 2], "big" if big else "little"):
                out.add(word)
    return out


def catch_all_words(source: bytes, label: str, ecl: bytes) -> "tuple[list, dict]":
    """The words a build of this source save leaves to the catch-all sweep."""
    state = amiga_por.por_state_from_amiga(source, label)
    count = source[amiga_por.POR_PARTY_SIZE_BYTE] or 1
    _built, report = amiga_por.new_por_savegame(state, "A", count, ecl)
    words = sorted({i // 2 for i, why in report.sources.items()
                    if i < 2 * 2560 and why.startswith(CATCH_ALL)})
    classes: dict = collections.Counter()
    for i, why in report.sources.items():
        classes[why.split(":")[0][:52] if ":" in why[:52] else why[:52]] += 1
    return words, classes


# -- the report --------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dos", nargs="+", default=[], metavar="PATH",
                        help="directories or files holding DOS containers")
    parser.add_argument("--json", help="write the per-word table here")
    parser.add_argument("--engine", action="store_true",
                        help="also census the engine's own constant-offset "
                             "accesses, reading /program off the player's "
                             "disk 1")
    parser.add_argument("--program", metavar="PATH",
                        help="read /program from here instead of the disk")
    args = parser.parse_args(argv)

    ecl = ecl_dax()
    bodies = scripts(ecl)
    census = Census(bodies)
    engine = None
    if args.engine or args.program:
        engine = EngineCensus(pathlib.Path(args.program).read_bytes()
                              if args.program else amiga_program())
    saves = amiga_corpus()
    if not saves:
        raise SystemExit("No Amiga saved game in the specimen tree")
    for _label, data in saves:
        CORPUS_AREAS.add(amiga_por.por_word(data, 0x49F2))
    amiga_live = live_words(saves, at=amiga_por.POR_VAR_OFFSET, big=True)
    dos = dos_corpus(args.dos)
    dos_live = live_words(dos, at=1, big=False)
    dos_areas = {int.from_bytes(d[1 + 2 * (0x49F2 - 0x4900):][:2], "little")
                 for _l, d in dos}

    label, data = saves[0]
    catch, classes = catch_all_words(data, label, ecl)

    print(f"the game's own scripts: {len(bodies)} blocks of ecl.dax, "
          f"base ${census.base:04X}, walk reaches "
          f"{100 * census.coverage[0] / census.coverage[1]:.1f}% of "
          f"{census.coverage[1]} bytes")
    print(f"the Amiga corpus: {len(saves)} saved games, areas "
          f"{sorted(CORPUS_AREAS)}, {len(amiga_live)} of 2560 words non-zero "
          f"in at least one")
    if dos:
        print(f"the DOS corpus: {len(dos)} containers, areas "
              f"{sorted(dos_areas)}, {len(dos_live)} words non-zero")
    print()
    print(f"a build from {label}: {sum(classes.values())} bytes accounted "
          f"for, of which the catch-all sweep claims {2 * len(catch)} "
          f"({len(catch)} words)")
    print()

    def block_name(word: int) -> str:
        base = vm_address(word) & 0xFF00
        for start, words in BLOCKS:
            if start <= vm_address(word) < start + words:
                return f"${start:04X}-${start + words - 1:04X}"
        return f"${base:04X}"

    print("the catch-all words, by what the game's own scripts do with them")
    print("  block          written  read only  named nowhere  "
          "not even as a byte pair")
    for start, words in BLOCKS:
        here = [w for w in catch
                if start <= vm_address(w) < start + words]
        written = [w for w in here if census.writes.get(w)]
        read = [w for w in here if census.reads.get(w)
                and not census.writes.get(w)]
        named = [w for w in here if not census.writes.get(w)
                 and not census.reads.get(w)]
        raw = [w for w in named if not census.raw.get(w)]
        print(f"  ${start:04X}-${start + words - 1:04X}  "
              f"{len(written):7d}  {len(read):9d}  {len(named):13d}  "
              f"{len(raw):22d}")
    written_all = [w for w in catch if census.writes.get(w)]
    print(f"  total          {len(written_all):7d}")
    print()

    if dos:
        both = sorted(set(catch) & dos_live)
        extra = sorted(dos_live - amiga_live)
        print(f"the cross-port check: DOS stands in "
              f"{sorted(dos_areas - CORPUS_AREAS)} as well, and holds "
              f"{len(extra)} words non-zero that no Amiga saved game does.")
        print(f"  of those {len(extra)}, {len([w for w in extra if w in catch])} "
              f"are in the catch-all set and "
              f"{len([w for w in extra if w not in catch])} are words this "
              f"writer already claims one by one.")
        print(f"  catch-all words non-zero in any of the {len(dos)} DOS "
              f"containers: {len(both)}")
        for word in both:
            print(f"    ${vm_address(word):04X} (file "
                  f"${file_address(word):04X})")
        print()

    c64 = c64_corpus()
    if c64:
        from goldbox import world_state

        c64_areas = set()
        c64_live = set()
        for label_, data_ in c64:
            c64_areas.add(world_state.from_c64(data_, source=label_).area)
            body = data_[2:]                    # past the two-byte load address
            for word in range(min(1024, len(body))):
                if body[word]:
                    c64_live.add(word)
        block1 = [w for w in catch if w < 1024]
        print(f"the C64 corpus: {len(c64)} SAVEDGAME0, areas "
              f"{sorted(c64_areas)}. It witnesses block 1 alone -- "
              f"SAVEDGAME0 is $4900-$64FF and SAVEDGAME1 $8300-$8AFF, so the "
              f"VM's $6B00 and $9700 blocks are in neither.")
        print(f"  {len([w for w in block1 if w in c64_live])} of the "
              f"{len(block1)} block-1 catch-all words are non-zero in some "
              f"C64 save, by page:")
        for page in range(0x4900, 0x4D00, 0x100):
            here = [w for w in block1
                    if (0x4900 + w) & 0xFF00 == page]
            live = [w for w in here if w in c64_live]
            print(f"    ${page:04X}  {len(live)} of {len(here)}")
        print("  A C64 word live where the Amiga's is zero is the two ports "
              "using one address for different things, not an area the "
              "Amiga corpus has missed (docs/163-dos-vm-address-map.md).")
        print()

    visited = set(CORPUS_AREAS)
    at_risk = [w for w in written_all if not (census.writes[w] & visited)]
    print(f"{len(written_all)} of the {len(catch)} catch-all words are "
          f"written by some area's script.")
    print(f"  {len(written_all) - len(at_risk)} of those are written by a "
          f"script of an area the corpus stands in, so the sweep has already "
          f"watched the game run the write and leave the word zero.")
    print(f"  {len(at_risk)} are written only by scripts of areas no saved "
          f"game here comes from -- {2 * len(at_risk)} bytes.")
    if dos:
        also = [w for w in at_risk if w in dos_live]
        print(f"  of those {len(at_risk)}, {len(also)} are non-zero in some "
              f"DOS container and {len(at_risk) - len(also)} are zero in all "
              f"{len(dos)}.")
    print()

    print("what a saved game from each area would newly cover")
    print("  area  words it writes that no visited area's script writes")
    per_area: dict = collections.Counter()
    for word in at_risk:
        for area in census.writes[word]:
            per_area[area] += 1
    for area, n in sorted(per_area.items(), key=lambda kv: (-kv[1], kv[0])):
        words = sorted(w for w in at_risk if area in census.writes[w])
        names = " ".join(f"${vm_address(w):04X}" for w in words)
        print(f"  {area:4d}  {n:3d}  {names}")
    print()

    print("every catch-all word an unvisited area's script writes")
    print("  VM      file    written by                read by")
    for word in at_risk:
        print(f"  ${vm_address(word):04X}  ${file_address(word):04X}  "
              f"{sorted(census.writes[word])!s:24.24}  "
              f"{sorted(census.reads.get(word, ()))!s:24.24}"
              + ("  DOS-live" if word in dos_live else ""))
    print()

    if engine is not None:
        touched = sorted(set(engine.reads) | set(engine.writes))
        inside = [w for w in touched if w in set(catch)]
        print(f"the engine's own accesses: {engine.sites} sites load a block "
              f"pointer, naming {len(touched)} array words at a constant "
              f"displacement and {engine.indexed} at a computed one.")
        print(f"  {len(inside)} of the {len(catch)} catch-all words are "
              f"among them:")
        print("  VM      file    engine r/w  script writes")
        for word in inside:
            rw = ("w" if engine.writes.get(word) else "") + \
                 ("r" if engine.reads.get(word) else "")
            print(f"  ${vm_address(word):04X}  ${file_address(word):04X}  "
                  f"{rw:10.10}  {sorted(census.writes.get(word, ()))!s:30.30}")
        nothing = [w for w in catch if not engine.touches(w)
                   and not census.writes.get(w) and not census.reads.get(w)]
        print(f"  {len(nothing)} catch-all words ({2 * len(nothing)} bytes) "
              f"are named by no script and by no constant displacement in "
              f"/program.")
        print()

    if args.json:
        out = []
        for word in catch:
            out.append({
                "word": word,
                "vm": f"${vm_address(word):04X}",
                "file": f"${file_address(word):04X}",
                "block": block_name(word),
                "writes": sorted(census.writes.get(word, ())),
                "reads": sorted(census.reads.get(word, ())),
                "named_raw": sorted(census.raw.get(word, ())),
                "dos_live": word in dos_live,
                "engine_reads": (bool(engine.reads.get(word))
                                 if engine else None),
                "engine_writes": (bool(engine.writes.get(word))
                                  if engine else None),
            })
        pathlib.Path(args.json).write_text(json.dumps(
            {"corpus_areas": sorted(CORPUS_AREAS),
             "dos_areas": sorted(dos_areas),
             "catch_all": len(catch),
             "words": out}, indent=1))
        print(f"\n{args.json}: {len(out)} words")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
