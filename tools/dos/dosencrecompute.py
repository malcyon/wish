#!/usr/bin/env python3
"""When the DOS engine rewrites a character's stored encumbrance, from its code.

`money + sum(item weight x quantity)` is the identity this project checks a DOS
record with, and `#323 (The encumbrance identity does not survive the training
fee, so failing it is not evidence of an edited record)` asked *when* the engine
makes that true.  `tools/records/enccensus.py` answers it from records and
`tools/dos/dosencsave.py` from a driven boot; this answers it from the shipped
binaries, which no edited save can poison.

Five questions, five modes.

    tools/dos/dosencrecompute.py routine     the recompute routine, per title
    tools/dos/dosencrecompute.py callers     who calls it, and who writes money
    tools/dos/dosencrecompute.py helpers     who adjusts the total coin for coin
    tools/dos/dosencrecompute.py bags        every record carrying a bag of holding
    tools/dos/dosencrecompute.py stock       every item the game itself hands out

**`routine`** finds the one function that rebuilds the field.  It is found by
signature rather than by a remembered address: the routine is the one
containing an `add es:[di+<encumbrance>], r16` -- the accumulate inside the
item-chain walk -- and from there the zero, the seven-purse loop and the tail
are read off.  Pool of Radiance's is **resident**, in the expanded `START.EXE`;
Curse's and Silver Blades' are in `GAME.OVR`.

**`callers`** is the answer to why a training fee survives a save.  It counts
the routines that call the recompute and the routines that write money, and
intersects them -- **counting the coin purses apart from gems and jewelry,
because the answer differs**.  No routine that writes a copper, silver,
electrum, gold or platinum count calls the recompute, in any of the three
titles: 0 of 11, 0 of 12 and 0 of 10.  Exactly one routine per title writes
`gems` or `jewelry` and does call it, and it is the appraise screen, which
decrements the count and rebuilds the total on its way out.  So a trainer's fee
and a shop's change are never repaired and appraising a gem always is.

**`helpers`** is the other half of that answer, and it is why no coin movement
has ever been seen to leave a record *below* the sum.  Beside the recompute
each title carries two leaf routines that move the stored total by an argument,
`encumbrance -= arg` and `encumbrance += arg`, and their callers are the screens
that move coins between a character's purse, another character's and the party
pool.  Those screens mirror every coin they move into the total, so the identity
survives them exactly; the screens that *charge* for something -- the trainer,
the shop, the temple -- call neither routine, and that is the drift.

**`bags`** is the term the identity has never had.  Pool of Radiance's tail
takes 5000 tenths of a pound off the total when a **readied** item's first name
word is `HOLDING`, so a character carrying a bag of holding would store 5000
*below* `money + sum(weight x quantity)` with nobody having edited anything.
This walks every DOS record on the machine looking for one; none has one, and
`stock` says why.

**`stock`** asks the same question of the game rather than of the saves: does
any item in a title's own shop and encounter tables carry that name word at
all?  It reads the C64 `ITEMFILE*` lists and the DOS `ITEM*.DAX` blocks, with
each title's own `ITEMNAMES` index for the word as the control -- a nil answer
means nothing unless the word it looked for is one the title can print.

`tools/dos/dosovrmap.py callers` cannot do Pool of Radiance's routine: it resolves
only targets that live inside `GAME.OVR`, and this one is resident.  That is
the gap this tool fills, so the resident case is handled here.

Reads only, and prints addresses and short windows.  The game's bytes stay in
the player's own directory, and nothing here needs an emulator.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_port as dl  # noqa: E402
from tools.dos import dosbox, dosfieldrefs, dosovrmap, unexepack  # noqa: E402

#: Turbo Pascal's frame setup.  `tools/dos/dosovrmap.py` says why it is this and
#: not `8B EC`: this compiler emits the 8086-encoded `mov bp, sp`.
PROLOGUE = b"\x55\x89\xe5"

#: How far back a routine's prologue may be from a site inside it.  The
#: recompute is about 0x3E0 bytes in Pool of Radiance and the largest caller
#: found is under 0x1200, so this is generous rather than fitted.
BACKSTOP = 0x1600

#: The bag of holding's discount, in tenths of a pound: 500 lb.
BAG_DISCOUNT = 0x1388

#: `ITEMNAMES` index 186, read off `POOL1.D64` through
#: `goldbox.items.load_item_names`.  The DOS item record stores the C64's own
#: name-word indices (`goldbox/dos_port.py`, `name1`), so the compare in the
#: engine is against this number on both ports.
HOLDING = 186

#: The three titles with a C64 port, which are the three `#323` asks about,
#: plus Pools of Darkness where the archives carry it.
TITLES = ("POOLRAD", "CURSE", "SECRET", "DARKNESS")

#: `goldbox/dos_port.py`'s key for each archive directory name.
SHAPE_KEY = {"POOLRAD": "pool-of-radiance",
             "CURSE": "curse-of-the-azure-bonds",
             "SECRET": "secret-of-the-silver-blades",
             "DARKNESS": "pools-of-darkness"}


class NotFound(Exception):
    """No routine matched the signature in this title's binaries."""


# ---------------------------------------------------------------------------
# Loading a title's two code files
# ---------------------------------------------------------------------------
def game_dir(stem: str) -> pathlib.Path:
    """The archive directory holding this title's `GAME.OVR`.

    `tools/dos/dosbox.py`'s `find_game` looks for `START.EXE`, and **Pools of
    Darkness has none** -- its loader is `STARTUP.EXE`, under
    `games/Pools of Darkness/GAME/DARKNESS`.  So the search here is for the
    overlay, which all four titles do have, and the loader is whichever of the
    two names is beside it.
    """
    try:
        return dosbox.find_game(stem)
    except FileNotFoundError:
        pass
    if not dosbox.ARCHIVES.is_dir():
        raise FileNotFoundError(f"no archives at {dosbox.ARCHIVES}")
    for collection in sorted(dosbox.ARCHIVES.iterdir()):
        games = collection / "games"
        if not games.is_dir():
            continue
        for entry in sorted(games.iterdir()):
            inner = entry / "GAME" / stem
            if (inner / "GAME.OVR").is_file():
                return inner
    raise FileNotFoundError(f"no DOS {stem} under {dosbox.ARCHIVES}")


def binaries(stem: str) -> dict[str, bytes]:
    """`GAME.OVR` and the expanded loader image, for one archive directory.

    The image is empty when the title ships no `START.EXE`, or when what it
    ships is not EXEPACKed -- Pools of Darkness's `STARTUP.EXE` is neither.  An
    empty image is harmless here: the recompute is found in whichever file
    holds it, and only the resident case and the unit map need the image.
    """
    game = game_dir(stem)
    image = b""
    for name in ("START.EXE", "STARTUP.EXE"):
        if not (game / name).is_file():
            continue
        try:
            image, _ = unexepack.unpack((game / name).read_bytes())
        except ValueError:
            continue
        break
    return {"GAME.OVR": (game / "GAME.OVR").read_bytes(), "START.img": image}


#: The five coin purses and the two counts of valuables, kept apart because
#: **the answer differs between them**: no routine that writes a coin calls
#: the recompute, and the one routine that writes `gems` or `jewelry` does.
#: Lumping the seven together hides that and reports one misleading number.
COIN_FIELDS = ("copper", "silver", "electrum", "gold", "platinum")
VALUABLE_FIELDS = ("gems", "jewelry")


def offsets(stem: str) -> dict[str, list[int] | int]:
    """The encumbrance and the money displacements for this title.

    Straight out of `goldbox/dos_port.py`, so a shape correction there moves
    this tool rather than leaving it quietly reading the wrong field.  Pools of
    Darkness declares no money fields, so its purses come back empty and its
    `callers` row has nothing to intersect.
    """
    fields = dl.FIELDS_BY_NAME_FOR[SHAPE_KEY[stem]]
    return {"encumbrance": fields["encumbrance"].offset,
            "coins": [fields[c].offset for c in COIN_FIELDS if c in fields],
            "valuables": [fields[c].offset for c in VALUABLE_FIELDS
                          if c in fields]}


def routine_start(data: bytes, site: int) -> int:
    """The prologue of the routine containing `site`, or -1."""
    return data.rfind(PROLOGUE, max(0, site - BACKSTOP), site)


# ---------------------------------------------------------------------------
# Finding the recompute
# ---------------------------------------------------------------------------
def find_recompute(stem: str) -> dict:
    """The routine that rebuilds stored encumbrance, found by signature.

    The signature is `add es:[di+<encumbrance>], r16` -- the one accumulate
    into the field, which sits inside the item-chain walk.  Everything else is
    read relative to it, so a title whose routine sits at a different address
    is found without a table of addresses to keep true.
    """
    files = binaries(stem)
    enc = offsets(stem)["encumbrance"]
    for name, data in files.items():
        hits = [r for r in dosfieldrefs.references(data, enc)
                if r["kind"] == "RW" and r["mnem"] == "add m16,r16"]
        if not hits:
            continue
        site = hits[0]["linear"]
        start = routine_start(data, site)
        if start < 0:
            continue
        writes = [r for r in dosfieldrefs.references(data, enc)
                  if "W" in r["kind"]]
        inside = [r for r in writes if start <= r["linear"] < site + 0x900]
        return {"stem": stem, "file": name, "start": start, "accumulate": site,
                "writes_in_file": writes, "writes_in_routine": inside,
                "files": files, "encumbrance": enc}
    raise NotFound(f"{stem}: no accumulate into es:[di+{enc:#x}] anywhere")


def bag_block(found: dict) -> dict:
    """Whether this title takes 5000 off for a readied bag of holding.

    Three states, and the middle one is a defect in the game rather than in
    this reader: the block can be **live** (Pool of Radiance), **present but
    unreachable** because nothing ever sets the local that gates it (Curse of
    the Azure Bonds), or **absent** (Secret of the Silver Blades).

    The gate is found by reading the `cmp byte [bp-N], 0` immediately before
    the `cmp es:[di+enc], 1388h`, then counting every write to that same local
    inside the routine.  One write -- the initialising zero -- means nothing
    can ever turn it on.
    """
    data = found["files"][found["file"]]
    enc = found["encumbrance"]
    disc = [r for r in dosfieldrefs.references(data, enc)
            if r["mnem"] == "sub m16,imm16"
            and struct.unpack_from("<H", data, r["linear"] + 5)[0] == BAG_DISCOUNT]
    if not disc:
        return {"state": "absent"}
    site = disc[0]["linear"]
    tests = [r for r in dosfieldrefs.references(data, enc)
             if r["mnem"] == "cmp m16,imm16" and r["linear"] < site]
    gate = _gate_before(data, tests[-1]["linear"] if tests else site)
    if gate is None:
        return {"state": "unknown", "discount": site}
    local, writes = gate
    return {"state": "live" if len(writes) > 1 else "dead",
            "discount": site, "local": local, "writes": writes}

def _gate_before(data: bytes, site: int) -> tuple[int, list[int]] | None:
    """The `cmp byte [bp-N], 0` guarding `site`, and every write to that local.

    Turbo Pascal keeps the flag in a stack byte, so a write is
    `mov byte [bp-N], imm` or `mov [bp-N], r8`.  A callee cannot set it
    without the address being taken, so an absent `lea` on the same local is
    what makes "one write" conclusive rather than merely suggestive.

    **All eight byte registers, not just `al`.**  This checked `88 46` alone
    until 2026-09-08 -- `mov [bp+disp8], al`, which is the register Turbo
    Pascal uses for a byte flag and so the one that happens to matter here.
    But `docs/125-bug-notes.md` N24 quotes this scan to conclude that nothing
    can set Curse's gate, and a conclusion that rests on seven unchecked
    encodings is not the conclusion the prose claims.  The `lea` sweep is the
    same shape and now covers all eight 16-bit registers.
    """
    window = data[max(0, site - 0x40):site]
    m = None
    for m in re.finditer(rb"\x80\x7e(.)\x00", window):
        pass
    if m is None:
        return None
    local = m.group(1)
    lo, hi = max(0, site - 0x800), site + 0x400
    #: `mov [bp+disp8], r8` for al, cl, dl, bl, ah, ch, dh, bh -- ModRM mod=01
    #: rm=110, reg counting up in steps of 8 from 0x46.
    byte_regs = (0x46, 0x4E, 0x56, 0x5E, 0x66, 0x6E, 0x76, 0x7E)
    writes = [i for pat in [b"\xc6\x46" + local]
              + [bytes([0x88, r]) + local for r in byte_regs]
              for i in _find(data, pat, lo, hi)]
    if any(_find(data, bytes([0x8D, r]) + local, lo, hi)
           for r in byte_regs):
        writes.append(-1)                       # its address is taken somewhere
    return local[0] - 256, sorted(writes)


def _find(data: bytes, pattern: bytes, lo: int, hi: int) -> list[int]:
    return [m.start() for m in re.finditer(re.escape(pattern), data)
            if lo <= m.start() <= hi]


# ---------------------------------------------------------------------------
# Who calls it, and who writes money
# ---------------------------------------------------------------------------
def call_sites(found: dict) -> list[tuple[str, int]]:
    """Every near and far call to the recompute, in both of a title's files.

    A far call names `seg:off`, and in the expanded image a segment is
    image-relative, so `seg * 16 + off` is the linear target -- the rule
    `tools/dos/dosovrmap.py` states and this reuses.  For a routine inside
    `GAME.OVR` the far call goes through the unit's `CD 3F` entry stub
    instead, which is why the two cases are separate here.
    """
    out: list[tuple[str, int]] = []
    ovr, img = found["files"]["GAME.OVR"], found["files"]["START.img"]
    if found["file"] == "START.img":
        target_seg_off = found["start"]
        for name, data in (("GAME.OVR", ovr), ("START.img", img)):
            for i in range(len(data) - 5):
                if data[i] != 0x9A:
                    continue
                off, seg = struct.unpack_from("<HH", data, i + 1)
                if seg * 16 + off == target_seg_off:
                    out.append((name, i))
    else:
        umap = dosovrmap.units(img, len(ovr))
        unit = dosovrmap.unit_of(umap, found["start"])
        if unit is not None:
            for stub, code in unit["ents"]:
                if code == found["start"] - unit["fileoff"]:
                    pat = b"\x9a" + struct.pack("<HH", stub, unit["seg"])
                    out += [("GAME.OVR", m.start())
                            for m in re.finditer(re.escape(pat), ovr)]
    data = ovr if found["file"] == "GAME.OVR" else None
    if data is not None:
        out += [("GAME.OVR", p) for p in range(len(data) - 3)
                if data[p] == 0xE8
                and p + 3 + int.from_bytes(data[p + 1:p + 3], "little",
                                           signed=True) == found["start"]]
    return sorted(set(out))


def money_writers(found: dict, which: str = "coins") -> dict[int, list[int]]:
    """Routines in `GAME.OVR` that write a money field, keyed by prologue.

    `which` is `coins` or `valuables`.  Only `GAME.OVR` is walked: every
    recompute caller found so far is there, so an intersection over the same
    file is the comparison that means something.

    **`dosfieldrefs.references` is an upper bound and it matters here.**  It
    scans bytes rather than walking instructions, so a match may be data.
    Every site this reports was read back as an instruction before anything
    was concluded from it -- the two that decide the `valuables` answer are
    `dec word es:[di+gems]` and `dec word es:[di+jewelry]`, and a scan for
    the `mov`/`add`/`sub` forms alone misses both.  That omission is what made
    an earlier reading of this report say "no routine does both".
    """
    ovr = found["files"]["GAME.OVR"]
    out: dict[int, list[int]] = collections.defaultdict(list)
    for off in offsets(found["stem"])[which]:
        for ref in dosfieldrefs.references(ovr, off):
            if "W" not in ref["kind"]:
                continue
            start = routine_start(ovr, ref["linear"])
            out[start].append(ref["linear"])
    return dict(out)


# ---------------------------------------------------------------------------
# The two leaves that adjust the total instead of rebuilding it
# ---------------------------------------------------------------------------
#: The arithmetic that tells the two leaves apart: `sub ax, [bp+6]` and
#: `add ax, [bp+6]`, the argument each was called with.  Both titles' later
#: forms carry an `sbb`/`adc` of `[bp+8]` after it and are unaffected.
HELPER_ARITH = {"minus": b"\x2b\x46\x06", "plus": b"\x03\x46\x06"}

#: How far a leaf's store may be from its own prologue.  The three titles'
#: are 0x11, 0x11 and 0x16 bytes in; the recompute's first write is 0x5C into
#: its routine, so this separates them without naming an address.
HELPER_SPAN = 0x20


def adjust_helpers(found: dict) -> dict[str, int]:
    """The two leaf routines that move stored encumbrance by an argument.

    Found the way the recompute is: a write to the field whose prologue is
    within :data:`HELPER_SPAN` bytes, with `sub ax, [bp+6]` or `add ax, [bp+6]`
    between the two.  They are not the recompute and must not be read as one --
    a caller of these adjusts the total by what it just moved and leaves every
    other derived field alone.
    """
    ovr = found["files"]["GAME.OVR"]
    enc = found["encumbrance"]
    out: dict[str, int] = {}
    for ref in dosfieldrefs.references(ovr, enc):
        if "W" not in ref["kind"]:
            continue
        start = routine_start(ovr, ref["linear"])
        if start < 0 or ref["linear"] - start > HELPER_SPAN:
            continue
        body = ovr[start:ref["linear"]]
        for which, pattern in HELPER_ARITH.items():
            if pattern in body:
                out.setdefault(which, start)
    return out


def helper_callers(found: dict, helper: int) -> dict[int, dict]:
    """Every routine that calls one leaf, and what else that routine does.

    `calls` is how many times it calls it, `coins` the coin-purse writes in it
    and `recompute` whether it also rebuilds the whole record -- which no
    caller of either leaf does in any of the three titles, so the two
    mechanisms belong to different screens rather than to one that hedges.
    """
    ovr = found["files"]["GAME.OVR"]
    coins = money_writers(found, "coins")
    rebuilt = {routine_start(ovr, site)
               for name, site in call_sites(found) if name == "GAME.OVR"}
    out: dict[int, dict] = {}
    for p in range(len(ovr) - 3):
        if ovr[p] != 0xE8:
            continue
        target = p + 3 + int.from_bytes(ovr[p + 1:p + 3], "little", signed=True)
        if target != helper:
            continue
        start = routine_start(ovr, p)
        row = out.setdefault(start, {"calls": 0, "coins": coins.get(start, []),
                                     "recompute": start in rebuilt})
        row["calls"] += 1
    return out


# ---------------------------------------------------------------------------
# The corpus half: who carries a bag of holding
# ---------------------------------------------------------------------------
def bag_rows() -> tuple[list[dict], dict[str, int]]:
    """Records holding an item named `HOLDING`, and the sample it came from.

    Walks the same roots `tools/records/enccensus.py` walks, with the same exclusions,
    so "no record has one" is a statement about the corpus that census
    reports on rather than about some other set of files.  **It does not
    deduplicate**: a nil result wants the widest sample, and a record found
    three times is three chances to have missed it.

    The second return is the sample size -- record files, items, readied items
    -- because "none of them" is only a finding beside how many there were.
    """
    out: list[dict] = []
    sample = {"records": 0, "items": 0, "readied": 0}
    for path, char in _dos_characters():
        sample["records"] += 1
        for slot, item in enumerate(char.items):
            sample["items"] += 1
            sample["readied"] += bool(item.get("readied"))
            words = [item.get(n) for n in ("name1", "name2", "name3")]
            if HOLDING not in words:
                continue
            out.append({"path": path, "who": char.name or "(unnamed)",
                        "title": char.deltas.key, "slot": slot,
                        "readied": bool(item.get("readied")),
                        "line": item.get("text"),
                        "stored": char.get("encumbrance"),
                        "expected": char.expected_encumbrance()})
    return out, sample


# ---------------------------------------------------------------------------
# The game's half: what the shop and encounter tables can hand out
# ---------------------------------------------------------------------------
#: The registry entry holding each title's C64 disks, where it has a C64 port.
#: Gateway is swept as well as the four the other modes use, because its name
#: table carries `HOLDING` at the same index and a title that ships the word
#: is a title where a nil answer says something.
C64_ENTRY = {"POOLRAD": "pool-of-radiance",
             "CURSE": "curse-of-the-azure-bonds",
             "SECRET": "secret-of-the-silver-blades",
             "GATEWAY": "gateway-to-the-savage-frontier"}

#: The C64 item record's three name words, and the DOS one's, which
#: `goldbox.dos_codec.item_to_c64` maps onto each other.
C64_NAME_BYTES = (1, 2, 3)


def records_with_word(block: bytes, stride: int, word: int) -> list[int]:
    """Indices of the DOS item records in `block` whose name words include
    `word`.  A record of all zeroes is a hole rather than an item."""
    at = [dl.ITEM_FIELDS_BY_NAME[n].offset for n in ("name1", "name2", "name3")]
    return [i for i in range(len(block) // stride)
            if any(block[i * stride:(i + 1) * stride])
            and word in {block[i * stride + a] for a in at}]


def c64_records_with_word(payload: bytes, word: int) -> list[int]:
    """The same for a C64 `ITEMFILE*` list, whose records are sixteen bytes."""
    from goldbox import items as gitems  # noqa: PLC0415
    size = gitems.ITEM_SIZE
    return [i for i in range(len(payload) // size)
            if any(payload[i * size:(i + 1) * size])
            and word in {payload[i * size + b] for b in C64_NAME_BYTES}]


def word_index(stem: str, word: str = "HOLDING") -> tuple[int | None, int]:
    """`(index, names)` for a word in this title's own `ITEMNAMES` table.

    The index is the control on a nil sweep: a title whose table has no such
    word cannot hand the item out whatever its tables hold, and one whose table
    has it at 186 is a title where the engine's own compare would fire.
    """
    from automap import gamedisks  # noqa: PLC0415
    from goldbox import c64_port  # noqa: PLC0415
    from goldbox import items as gitems  # noqa: PLC0415
    entry = C64_ENTRY.get(stem)
    root = gamedisks.find(entry) if entry else None
    if root is None:
        return None, 0
    game = c64_port.BY_KEY.get(entry)
    for disk in sorted(p for p in root.rglob("*") if p.suffix.lower() == ".d64"):
        try:
            names = gitems.load_item_names(str(disk), game)
        except Exception:                        # noqa: BLE001 -- a bad rip
            continue
        if not names:
            continue
        for index, text in names.items():
            if text.upper() == word:
                return index, len(names)
        return None, len(names)
    return None, 0


def stock_rows(word: str = "HOLDING") -> tuple[list[dict], list[dict]]:
    """Every item in the games' own tables carrying `word`, and the sample.

    Two ports read apart: the C64 `ITEMFILE*`/`ITEM<hh>` lists off the player's
    disks, and the DOS `ITEM*.DAX` blocks out of the archives.  A `.DAX` whose
    blocks are divisible by neither item stride is **counted as undecoded**
    rather than as zero hits, because a table this cannot read is not a table
    that holds nothing.

    What is searched for is :data:`HOLDING`, the constant Pool of Radiance's
    engine compares against.  The `word` a sample row reports is that title's
    *own* index for the word, which is the control: `186` means the title can
    print it, `None` means it has no such word to print.
    """
    from automap import gamedisks  # noqa: PLC0415
    from goldbox import items as gitems  # noqa: PLC0415
    from goldbox.d64 import D64, split_load_address  # noqa: PLC0415
    from goldbox.dos_savegame import dax_blocks  # noqa: PLC0415
    hits: list[dict] = []
    sample: list[dict] = []
    strides = sorted({d.item_size for d in dl.DELTAS})
    for stem in sorted(set(TITLES) | set(C64_ENTRY)):
        index, names = word_index(stem, word)
        entry = C64_ENTRY.get(stem)
        root = gamedisks.find(entry) if entry else None
        row = {"title": stem, "port": "c64", "word": index, "names": names,
               "tables": 0, "records": 0, "undecoded": 0}
        for disk in (sorted(p for p in root.rglob("*")
                            if p.suffix.lower() == ".d64") if root else []):
            try:
                img = D64.open(str(disk))
            except Exception:                    # noqa: BLE001 -- a bad rip
                continue
            for name in img.directory():
                if not gitems.is_item_list(name.name):
                    continue
                try:
                    _, payload = split_load_address(img.read_file(name))
                except Exception:                # noqa: BLE001
                    row["undecoded"] += 1
                    continue
                row["tables"] += 1
                row["records"] += sum(
                    1 for i in range(len(payload) // gitems.ITEM_SIZE)
                    if any(payload[i * gitems.ITEM_SIZE:
                                   (i + 1) * gitems.ITEM_SIZE]))
                for i in c64_records_with_word(payload, HOLDING):
                    raw = payload[i * gitems.ITEM_SIZE:
                                  (i + 1) * gitems.ITEM_SIZE]
                    hits.append({"title": stem, "port": "c64",
                                 "where": f"{disk.name}:"
                                          f"{bytes(name.name).decode('latin-1')}",
                                 "slot": i, "raw": bytes(raw).hex(" ")})
        if root is not None:
            sample.append(row)

        row = {"title": stem, "port": "dos", "word": index, "names": names,
               "tables": 0, "records": 0, "undecoded": 0}
        try:
            game = game_dir(stem)
        except FileNotFoundError:
            continue
        for path in sorted(game.glob("ITEM*.DAX")):
            try:
                blocks = list(dax_blocks(path.read_bytes(), path.name))
            except Exception:                    # noqa: BLE001
                row["undecoded"] += 1
                continue
            stride = next((s for s in strides
                           if all(len(b) % s == 0 for _, b in blocks if b)), 0)
            if not stride:
                row["undecoded"] += 1
                continue
            row["tables"] += 1
            for bid, block in blocks:
                row["records"] += sum(1 for i in range(len(block) // stride)
                                      if any(block[i * stride:(i + 1) * stride]))
                for i in records_with_word(block, stride, HOLDING):
                    hits.append({"title": stem, "port": "dos",
                                 "where": f"{path.name}:block {bid}",
                                 "slot": i,
                                 "raw": block[i * stride:
                                              (i + 1) * stride].hex(" ")})
        sample.append(row)
    return hits, sample


def _dos_characters():
    """`(path, character)` for every DOS record `enccensus` would count."""
    from goldbox import dos_codec as gdos  # noqa: PLC0415
    from tools.dos import dostailcensus  # noqa: PLC0415
    from tools.records import enccensus  # noqa: PLC0415
    for root in enccensus.dos_roots():
        if not root.exists():
            continue
        walk = sorted(root.rglob("*")) if root.is_dir() else [root]
        for path in walk:
            if (not path.is_file()
                    or path.suffix.lower() not in dostailcensus.RECORD_SUFFIXES
                    or any(d in path.as_posix()
                           for d in dostailcensus.SCRATCH_DIRS)):
                continue
            try:
                if path.stat().st_size not in dl.DELTAS_BY_SIZE:
                    continue
                if dostailcensus.foreign_title(path):
                    continue
                yield path, gdos.read_character(path)
            except (OSError, ValueError, gdos.DosRecordError):
                continue


# ---------------------------------------------------------------------------
# The three commands
# ---------------------------------------------------------------------------
def cmd_routine(args) -> int:
    for stem in args.titles:
        try:
            found = find_recompute(stem)
        except (FileNotFoundError, NotFound) as exc:
            print(f"{stem}: {exc}")
            continue
        enc = found["encumbrance"]
        print(f"{stem}: recompute at {found['file']} {found['start']:#08x}, "
              f"encumbrance at record {enc:#05x}")
        for ref in found["writes_in_routine"]:
            print(f"    {ref['linear']:#08x}  {ref['mnem']}")
        bag = bag_block(found)
        if bag["state"] == "absent":
            print("    bag of holding: no 5000 discount in this title")
        elif bag["state"] == "unknown":
            print(f"    bag of holding: discount at {bag['discount']:#08x}, "
                  "gate not identified")
        else:
            writes = ", ".join(f"{w:#08x}" for w in bag["writes"] if w >= 0)
            print(f"    bag of holding: discount at {bag['discount']:#08x} "
                  f"gated on [bp{bag['local']:+d}] -- {bag['state'].upper()}, "
                  f"writes to that local: {writes or 'none'}")
    return 0


def cmd_callers(args) -> int:
    print(f"{'title':10s} {'sites':>6s} {'routines':>9s} "
          f"{'coin writers':>13s} {'+recompute':>11s} "
          f"{'gem writers':>12s} {'+recompute':>11s}")
    for stem in args.titles:
        try:
            found = find_recompute(stem)
        except (FileNotFoundError, NotFound) as exc:
            print(f"{stem}: {exc}")
            continue
        sites = call_sites(found)
        ovr = found["files"]["GAME.OVR"]
        routines = {routine_start(ovr, s) for f, s in sites if f == "GAME.OVR"}
        coins = money_writers(found, "coins")
        vals = money_writers(found, "valuables")
        both_c = sorted(set(coins) & routines)
        both_v = sorted(set(vals) & routines)
        print(f"{stem:10s} {len(sites):>6d} {len(routines):>9d} "
              f"{len(coins):>13d} {len(both_c):>11d} "
              f"{len(vals):>12d} {len(both_v):>11d}")
        if not found["files"]["START.img"] and found["file"] == "GAME.OVR":
            print("    no expanded loader image, so no overlay unit map and "
                  "no far callers -- the site count above is near calls only")
        if args.verbose:
            for f, s in sites:
                print(f"    call  {f} {s:#08x} in "
                      f"{routine_start(found['files'][f], s):#08x}")
        for label, both in (("a coin purse", both_c),
                            ("gems or jewelry", both_v)):
            if both:
                print(f"    writes {label} and recomputes: "
                      + ", ".join(f"{r:#08x}" for r in both))
    return 0


def cmd_helpers(args) -> int:
    for stem in args.titles:
        try:
            found = find_recompute(stem)
        except (FileNotFoundError, NotFound) as exc:
            print(f"{stem}: {exc}")
            continue
        leaves = adjust_helpers(found)
        if not leaves:
            print(f"{stem}: no leaf adjusts the field in GAME.OVR")
            continue
        print(f"{stem}: " + ", ".join(
            f"encumbrance {'-' if which == 'minus' else '+'}= arg at "
            f"{addr:#08x}" for which, addr in sorted(leaves.items())))
        for which, addr in sorted(leaves.items()):
            rows = helper_callers(found, addr)
            paying = sum(1 for r in rows.values() if not r["coins"])
            print(f"    {'-' if which == 'minus' else '+'}= "
                  f"{sum(r['calls'] for r in rows.values())} call sites in "
                  f"{len(rows)} routines, "
                  f"{len(rows) - paying} of them write a coin purse, "
                  f"{sum(1 for r in rows.values() if r['recompute'])} "
                  f"also recompute")
            for start, row in sorted(rows.items()):
                where = ", ".join(f"{s:#x}" for s in row["coins"]) \
                    if row["coins"] else "no coin write"
                print(f"        {start:#08x} x{row['calls']}  {where}")
    return 0


def cmd_stock(args) -> int:
    hits, sample = stock_rows()
    print(f"{'title':10s} {'port':5s} {'word':>5s} {'names':>6s} "
          f"{'tables':>7s} {'records':>8s} {'undecoded':>10s}")
    for row in sample:
        print(f"{row['title']:10s} {row['port']:5s} "
              f"{str(row['word']):>5s} {row['names']:>6d} "
              f"{row['tables']:>7d} {row['records']:>8d} "
              f"{row['undecoded']:>10d}")
    if not hits:
        print(f"\nNo item in any table carries the word {HOLDING} (HOLDING), "
              "so nothing the engine hands out reaches the 5000 discount.")
        return 0
    for h in hits:
        print(f"{h['title']:10s} {h['port']:5s} {h['where']:28s} "
              f"slot {h['slot']:3d}  {h['raw']}")
    return 0


def cmd_bags(args) -> int:
    rows, sample = bag_rows()
    print(f"{sample['records']} record files, {sample['items']} items, "
          f"{sample['readied']} of them readied")
    if not rows:
        print("None carries an item whose name words include "
              f"{HOLDING} (HOLDING).")
        print("So the 5000 discount is a claim about the code alone: nothing "
              "here corroborates it and nothing here refutes it.")
        return 0
    for r in rows:
        delta = r["stored"] - r["expected"]
        print(f"{r['title']:28s} {r['who']:16s} slot {r['slot']:2d} "
              f"readied={r['readied']!s:5s} stored={r['stored']:6d} "
              f"expected={r['expected']:6d} delta={delta:+7d}  {r['path']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("cmd", choices=("routine", "callers", "helpers",
                                    "bags", "stock"))
    ap.add_argument("--titles", nargs="+", default=list(TITLES),
                    help="archive directory stems, default all four")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="callers: print every call site")
    args = ap.parse_args(argv)
    return {"routine": cmd_routine, "callers": cmd_callers,
            "helpers": cmd_helpers, "bags": cmd_bags,
            "stock": cmd_stock}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
