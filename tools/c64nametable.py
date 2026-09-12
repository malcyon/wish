#!/usr/bin/env python3
"""What the C64's `+$C00` party-name table is for, on Curse and Silver Blades.

`#435 (A rename in Wish leaves the C64 name table holding the old name on
Curse and Silver Blades, and nobody knows what reads it)` is the ticket.  Wish
edits the 256-byte save slot and leaves the second copy of the party's names
alone, and what a player sees because of that was unknown.

**The table is a scratch buffer, not a record.**  `GEN` rebuilds all 256 bytes
of it from the save disk's own **directory** before every one of its three
reads: it clears the block, opens `"$"` on unit 8, and copies the filename out
of each directory line whose first character is this title's prefix byte.  So
the bytes a save carries at `+$C00` are overwritten before any code looks at
them, and the names a player sees on `ADD CHARACTER TO PARTY` are the save
disk's filenames.

    tools/c64nametable.py show DISK [DISK ...]
    tools/c64nametable.py sites --title curse-of-the-azure-bonds
    tools/c64nametable.py run --save DISK --out DIR [--pool N] [--remove NAME]

`show` puts three readings of one disk side by side -- the stored table, the
character files on the disk, and the names in the party's records -- because
the interesting disk is the one where they disagree.  `sites` prints the six
code sites and the routine each belongs to, found in that title's own `GEN`
rather than written down.  `run` boots the disk in a pooled VICE, loads the
party, reads `$5700`-`$57FF` before and after `ADD CHARACTER TO PARTY`, and
keeps the list as text and as a photograph.

The player's disks are read and never written: `run` stages a copy into the
pool slot and the game is never shown anything else.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from goldbox import c64_port, c64_save  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools import d6502, gamedisks  # noqa: E402

#: Where `LINKER` runs an overlay, whatever its own two-byte header claims.
#: Silver Blades' `GEN` header says `$4000` and Curse's says `$1220`; both run
#: here (`docs/118-debug-mode.md`).
OVERLAY_BASE = 0x0800

#: The byte `GEN` puts in front of a character's name to make its filename,
#: and how it is checked.  Read out of the title's own `GEN` by `prefix()`
#: rather than trusted from here; this is what the answer should be, and a
#: disagreement is printed rather than swallowed.
#:
#: Pool of Radiance is `$01` and has no `+$C00` table at all -- it builds the
#: same list from the same directory with no buffer worth saving
#: (`tools/c64addchar.py`, `docs/170-c64-identity-pair.md`).
PREFIX = {
    "pool-of-radiance": 0x01,
    "curse-of-the-azure-bonds": 0x02,
    "secret-of-the-silver-blades": 0x05,
}

#: The 1541 command `GEN` sends to delete a character file before rewriting
#: it: `S0:`, then the prefix byte, then the name copied in at run time.
#: Finding it is what reads the prefix off the game instead of off the table
#: above -- but `GEN` also carries `S0:SAVEDBASH`, the save file's own scratch,
#: so the template wanted is the one whose next byte is a control code rather
#: than a letter.
SCRATCH = b"S0:"

#: How the six sites are told apart, by the shape of the loop around each
#: `$5700` operand.  The addressing mode and the neighbouring instruction are
#: the whole discriminator, so this holds for both titles at both addresses.
#: `d6502.lines` prints `$ADDR  BB BB BB   MNEMONIC OPERAND`, and the bytes
#: column is one, two or three of them wide -- so the mnemonic is taken by
#: pattern rather than by counting words.
RE_LINE = re.compile(r"^\$[0-9A-F]{4}\s+(?:[0-9A-F]{2} )+\s*(\S.*)$")

SITE_KINDS = {
    ("STA", "Y"): "clears all 256 bytes",
    ("STA", "X"): "writes a name into an entry",
    ("CMP", "X"): "compares an entry against the record at $7C00",
    ("LDA", "X"): "copies an entry out to the text buffer at $7A00",
}


# --- reading a disk ----------------------------------------------------------

def table_entries(disk: D64) -> tuple[c64_port.C64Container, int, list[bytes]]:
    """The 16 raw entries of the stored table, and where they live in memory.

    Sixteen, not the eight the container models: the compare loop counts down
    from `#$0F` with a sixteen-byte stride, so the block the game clears and
    fills is the whole `$5700`-`$57FF` page.
    """
    game = c64_port.detect(disk)
    if game is None:
        raise SystemExit("no Gold Box save on this disk")
    container = c64_save.CONTAINERS.get(game.key)
    if container is None or container.name_table is None:
        return game, 0, []
    load, payload = split_load_address(disk.read_file(game.save_file))
    base = container.name_table
    stride = container.name_stride
    return game, load + base, [bytes(payload[base + i * stride:
                                             base + (i + 1) * stride])
                               for i in range(0x100 // stride)]


def as_name(entry: bytes) -> str:
    return entry.split(b"\x00")[0].decode("latin1")


def character_files(disk: D64, prefix: int) -> list[str]:
    """Filenames on the disk that start with this title's prefix byte."""
    out = []
    for e in disk.iter_directory():
        raw = e.name.decode("latin1").rstrip("\xa0 ")
        if raw and ord(raw[0]) == prefix:
            out.append(raw[1:])
    return out


def party(disk: D64) -> list[str]:
    _game, sg0, _sg1 = load_save(disk)
    return [s.record.name for s in sg0.characters]


# --- reading the code --------------------------------------------------------

def gen_body(title: str, disks: str | None) -> bytes:
    """`GEN` for a title, header stripped, from the player's own disks."""
    root = pathlib.Path(disks or gamedisks.find(title) or "")
    if not root.is_dir():
        raise SystemExit(f"no disks for {title}; pass --disks")
    for path in sorted(root.glob("*.[dD]64")):
        image = D64.open(str(path))
        for e in image.iter_directory():
            if e.name.decode("latin1").rstrip("\xa0 ") == "GEN":
                return image.read_file("GEN")[2:]
    raise SystemExit(f"no GEN on any side under {root}")


def prefix(body: bytes) -> int | None:
    """The prefix byte, read off the `S0:` scratch template in `GEN`."""
    at = body.find(SCRATCH)
    while at >= 0:
        got = body[at + len(SCRATCH)]
        if 0 < got < 0x20:
            return got
        at = body.find(SCRATCH, at + 1)
    return None


def sites(body: bytes,
          dropped: list[tuple[int, str]] | None = None
          ) -> list[tuple[int, str, str]]:
    """Every instruction in `GEN` whose absolute operand is `$5700`.

    A byte pair is not an instruction, so each hit is decoded and only the
    four addressing shapes in `SITE_KINDS` are named.

    **Pass `dropped` a list to see what was thrown away**, as
    `(address, text)` -- the whole finding on `#435` is "these six sites and
    no others", and a seventh reader under an addressing mode `SITE_KINDS`
    does not cover would be discarded here in silence. `report_sites` prints
    them. Both titles have two today, and both decode out of embedded text
    rather than out of code.
    """
    found = []
    for i in range(len(body) - 2):
        if (body[i + 1] | body[i + 2] << 8) != 0x5700:
            continue
        line = d6502.lines(body, OVERLAY_BASE, OVERLAY_BASE + i, 1)[0]
        m = RE_LINE.match(line)
        if m is None:
            if dropped is not None:
                dropped.append((OVERLAY_BASE + i, body[i:i + 3].hex()))
            continue
        text = m.group(1)
        mnemonic = text.split()[0]
        index = text[-1] if text.endswith((",X", ",Y")) else ""
        kind = SITE_KINDS.get((mnemonic, index))
        if kind is None:
            if dropped is not None:
                dropped.append((OVERLAY_BASE + i, text))
            continue
        found.append((OVERLAY_BASE + i, text, kind))
    return found


# --- the driven run ----------------------------------------------------------

class Run:
    """One driven session, one JSON line per event as it happens.

    Nothing is held back to the end: a run that dies halfway still says how
    far it got and what the machine held when it stopped.
    """

    def __init__(self, out: pathlib.Path):
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self.log_path = out / "run.jsonl"
        self.sess = None
        self.shots = 0

    def log(self, event: str, **fields) -> None:
        line = json.dumps({"t": round(time.time(), 2), "event": event,
                           **fields})
        with self.log_path.open("a") as fh:
            fh.write(line + "\n")
        print(line, flush=True)

    def dump(self, tag: str) -> str:
        s = self.sess.screen()
        text = "(bitmap)" if s is None else "\n".join(s.row(r).rstrip()
                                                      for r in range(25))
        self.shots += 1
        stem = f"{self.shots:02d}-{tag}"
        (self.out / f"{stem}.txt").write_text(text + "\n")
        self.sess.kbd.screenshot(str(self.out / f"{stem}.png"))
        self.log("screen", tag=tag, stem=stem,
                 lines=[ln for ln in text.splitlines() if ln.strip()])
        return text

    def live_table(self, stage: str) -> list[str]:
        """`$5700`-`$57FF` out of the running machine, as sixteen names.

        This is the measurement the run exists for.  A screen shows what was
        drawn; these bytes show what the buffer holds at the moment it is
        drawn from, which is the difference between the save's copy and the
        directory's.
        """
        with self.sess.mon(8) as m:
            raw = m.read(0x5700, 0x100)
            m.resume()
        names = [as_name(raw[i * 16:(i + 1) * 16]) for i in range(16)]
        self.log("live_table", stage=stage,
                 names=[n for n in names if n], hex=raw[:0x60].hex())
        return names

    def wait_still(self, budget: float, quiet: int = 3) -> None:
        """The add list stars its entries one directory line at a time, so
        wait for three polls a second apart to agree rather than for a clock.

        **The side prompt is answered through the KERNAL buffer as well as by
        XTEST.**  `ADD CHARACTER TO PARTY` sends Curse back to the game side
        before it reads the save disk's directory, and the routine that draws
        `INSERT SIDE # 1` leaves only two ways out -- a key it reads at
        `$C6`/`$0277`, or the fire button.  An XTEST space is not one of them,
        which is what left a first run watching the same prompt for 45
        seconds (`work/issue435/curse1`).
        """
        last, same, end = None, 0, time.time() + max(budget, 6.0)
        while time.time() < end and same < quiet:
            if self.sess.handle_prompt():
                self.sess.press_kernal(0x20)
            s = self.sess.screen()
            text = None if s is None else "\n".join(s.row(r) for r in range(25))
            same = same + 1 if text == last else 0
            last = text
            time.sleep(1.0)

    def wait_bar(self, opening: str, timeout: float) -> str:
        """Wait for row 24 to open with *opening*, answering disk prompts."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.sess.handle_prompt():
                self.sess.press_kernal(0x20)
            s = self.sess.screen()
            if s is not None and s.row(24).strip().startswith(opening):
                return self.dump("add-bar")
            time.sleep(1.0)
        self.log("no bar", opening=opening)
        return self.dump("no-bar")

    def answer_yes(self, tag: str) -> None:
        """A `YES NO` question, wherever the game draws it, and the disk
        prompt that follows a write."""
        s = self.sess.screen()
        if s is not None and s.contains("YES"):
            if not self.sess.select_row("YES", timeout=8.0):
                self.sess.select_bar("YES", timeout=8.0)
            self.sess.press_kernal(0x0D)
        for _ in range(30):
            if self.sess.handle_prompt():
                self.sess.press_kernal(0x20)
            time.sleep(1.0)
        self.dump(tag)

    def pick(self, label: str, tag: str, settle: float = 6.0,
             still: bool = False) -> str:
        ok = self.sess.select_row(label, timeout=25.0)
        if still:
            self.wait_still(settle)
        else:
            self.sess.settle(settle)
        self.log("picked", label=label, selected=ok)
        return self.dump(tag)


def load_party(sess, timeout: float = 300.0) -> bool:
    """`LOAD SAVED GAME`, with the save disk in the drive before the pick.

    The game reads its save file off whatever is in unit 8 rather than
    prompting for it, and the confirmation goes through the KERNAL buffer
    because an XTEST Return does not move it (`tools/cursewarp.py`).
    """
    if sess.wait_text("LOAD SAVED GAME", timeout)[0] is None:
        return False
    sess.attach(sess.save_disk)
    if not sess.select_row("LOAD SAVED GAME"):
        return False
    deadline = time.time() + timeout
    seen = ""
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.5)
            continue
        if "BEGIN ADVENTURING" in s.text():
            return True
        if sess.handle_prompt(s):
            time.sleep(1.0)
            continue
        bar = s.row(24).strip()
        if bar != seen:
            sess.log(f"  load: {bar!r}")
            seen = bar
        if "YES" in bar:
            sess.select_bar("YES")
            sess.press_kernal(0x0D)
        time.sleep(1.0)
    return False


def from_bar(text: str) -> str:
    """The first source on an `ADD FROM: ...` bar, which is this game's own.

    Curse draws `ADD FROM: CURSE POOL HILLSFAR EXIT`: a character can come
    from any of three games, and the answer chooses the filename prefix byte
    the directory scan then filters on.
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("ADD FROM:"):
            words = [w for w in line[len("ADD FROM:"):].split()
                     if w != "EXIT"]
            return words[0] if words else ""
    return ""


def drive(save: str, out: str, pool: int | None, disks: str | None,
          remove: str, source: str, resave: bool) -> int:
    from tools import curserun, ssbwarp
    from tools import session as por

    game, _at, entries = table_entries(D64.open(save))
    if game.key not in ("curse-of-the-azure-bonds",
                        "secret-of-the-silver-blades"):
        raise SystemExit(f"{game.title} keeps no +$C00 table")
    curse = game.key == "curse-of-the-azure-bonds"
    where = disks or str(gamedisks.find(game.key) or "")
    if not where:
        raise SystemExit(f"no disks for {game.title}; pass --disks")

    run = Run(pathlib.Path(out))
    slot = por.claim_slot(pool, note="c64nametable/435")
    sess = None
    try:
        # Inside the `try`, so a slot claimed and then lost to a failing
        # write is still torn down rather than held until the lease expires.
        run.log("slot", n=slot.n, monitor=slot.port, display=slot.display,
                dir=str(slot.dir))
        stage = curserun.stage if curse else ssbwarp.stage
        first = stage(slot, where, save)
        sess = (curserun.CurseSession if curse else ssbwarp.SSBSession)(
            first, slot=slot)
        sess.save_disk = f"{slot.dir}/SIDE0.D64"
        run.sess = sess
        disk = D64.open(sess.save_disk)
        run.log("staged", save=save, side0=sess.save_disk,
                stored_table=[as_name(e) for e in entries if as_name(e)],
                character_files=character_files(disk, PREFIX[game.key]),
                party=party(disk))
        if not sess.boot():
            run.dump("boot-failed")
            return 1
        run.log("boot", ok=True)
        run.dump("main-menu")
        if not load_party(sess):
            run.dump("load-failed")
            return 1
        sess.settle(3.0)
        run.dump("loaded")
        run.live_table("after-load")
        if hasattr(sess, "patch_disk_prompt"):
            run.log("disk_prompt_patched", ok=sess.patch_disk_prompt())

        if remove:
            run.pick("REMOVE CHARACTER FROM PARTY", "remove-list", settle=4.0)
            run.pick(remove, f"removed-{remove}", settle=20.0, still=True)
            run.pick("EXIT", "after-remove", settle=4.0)
            sess.wait_text("BEGIN ADVENTURING", 60)
            run.live_table("after-remove")

        text = run.pick("ADD CHARACTER TO PARTY", "add-source", settle=30.0,
                        still=True)
        # The bar can be a few seconds behind the pick -- a first Silver
        # Blades run read row 24 before `ADD FROM:` was drawn on it, skipped
        # the whole list and reported nothing (`work/issue435/ssb1`).
        if not from_bar(text):
            text = run.wait_bar("ADD FROM:", 60.0)
        run.live_table("add-source")
        # `ADD FROM: CURSE POOL HILLSFAR EXIT` -- the bar is which game's
        # characters to list, and each answer is a different filename prefix
        # byte, which is what `$2CE1` (Curse) and `$2AD3` (Silver Blades)
        # hold when the directory scan runs.
        word = source or from_bar(text)
        if word:
            run.log("add_from", bar=text.splitlines()[24].strip(), chose=word)
            ok = sess.select_bar(word, timeout=25.0)
            run.log("bar", label=word, selected=ok)
            run.wait_still(45.0)
            run.dump("add-list")
            run.live_table("add-list")
        run.pick("EXIT", "after-exit", settle=4.0)
        if resave:
            # What the engine then stores at `+$C00` is the buffer the
            # directory scan left there, which is the whole claim.
            sess.wait_text("BEGIN ADVENTURING", 60)
            run.pick("SAVE CURRENT GAME", "save", settle=4.0)
            run.answer_yes("after-save")
            sess.wait_text("BEGIN ADVENTURING", 90)
        kept = run.out / "save-after.D64"
        shutil.copy(sess.save_disk, kept)
        after = D64.open(str(kept))
        run.log("done", ok=True, save_after=str(kept),
                character_files=character_files(after, PREFIX[game.key]),
                stored_table=[as_name(e) for e in table_entries(after)[2]
                              if as_name(e)])
        return 0
    finally:
        if sess is not None:
            sess.terminate()
        slot.teardown()
        run.log("torn down")


# --- the two static reports --------------------------------------------------

def show(paths: list[str]) -> int:
    for path in paths:
        disk = D64.open(path)
        game, at, entries = table_entries(disk)
        stored = [as_name(e) for e in entries]
        files = character_files(disk, PREFIX.get(game.key, 0x01))
        names = party(disk)
        print(f"{pathlib.Path(path).name}  {game.title}")
        if not entries:
            print("  no +$C00 table on this title")
        else:
            print(f"  stored table ${at:04X}  {[n for n in stored if n]}")
        print(f"  character files      {files}")
        print(f"  party records        {names}")
        if entries:
            live = [n for n in stored if n]
            print("  the stored table and the disk's own files "
                  + ("agree" if sorted(live) == sorted(files)
                     else "DISAGREE -- the directory is what the game reads"))
    return 0


def report_sites(title: str, disks: str | None) -> int:
    body = gen_body(title, disks)
    got = prefix(body)
    declared = PREFIX.get(title)
    print(f"{title}: GEN is {len(body)} bytes at ${OVERLAY_BASE:04X}")
    if got is None:
        print("  no S0: template found")
    else:
        print(f"  filename prefix ${got:02X}, read off the S0: template")
    if declared is not None and got is not None and declared != got:
        print(f"  ** the table in this file says ${declared:02X} **")
    dropped: list[tuple[int, str]] = []
    for at, text, kind in sites(body, dropped):
        print(f"  ${at:04X}  {text:<14} {kind}")
    for at, text in dropped:
        print(f"  ${at:04X}  {text:<14} not an addressing shape this names")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("show", help="the three readings of one save disk")
    s.add_argument("disks", nargs="+", metavar="DISK")

    c = sub.add_parser("sites", help="the $5700 code sites in a title's GEN")
    c.add_argument("--title", default="curse-of-the-azure-bonds")
    c.add_argument("--disks", default=None)

    r = sub.add_parser("run", help="boot a save disk and read the buffer")
    r.add_argument("--save", required=True, help="the save disk to copy")
    r.add_argument("--out", required=True, help="a directory for this run")
    r.add_argument("--pool", type=int, default=None, help="demand this slot")
    r.add_argument("--disks", default=None, help="the title's own sides")
    r.add_argument("--remove", default="",
                   help="take this character out of the party first, which "
                        "makes the game write a character file")
    r.add_argument("--resave", action="store_true",
                   help="take SAVE CURRENT GAME at the end, so the engine "
                        "writes back whatever the buffer then holds")
    r.add_argument("--source", default="",
                   help="which word on the ADD FROM: bar to take; the "
                        "game's own is the default")

    args = ap.parse_args(argv)
    if args.cmd == "show":
        return show(args.disks)
    if args.cmd == "sites":
        return report_sites(args.title, args.disks)
    return drive(args.save, args.out, args.pool, args.disks, args.remove,
                 args.source, args.resave)


if __name__ == "__main__":
    sys.exit(main())
