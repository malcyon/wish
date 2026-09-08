#!/usr/bin/env python3
"""Watch what the screen reader reads, and what it *should* have read.

`#336 (The screen reader goes blind on the insert-a-side prompt, and every
screen-driven recovery fails with it)` reports a driven session reading forty
spaces off row 24 while the display showed `INSERT SIDE # 2, AND PRESS ANY
KEY.`  The reader computes the screen address from `$D018` and `$DD00` rather
than assuming `$0400`, so the question this tool answers is whether those two
reads are themselves right at the moment the reader takes them.

They are not always.  VICE's binary monitor reads bank 0, "default", which is
whatever the CPU can see -- and `$01` spends part of every load at `$30`, with
the I/O chips banked out and RAM underneath.  A `$D018` read in that state is a
byte of RAM.  This samples both banks at every poll a driven boot makes and
writes one JSON line per sample, so a disagreement is a record rather than an
argument.

`--stage` does not wait for that window, which is four polls in a thousand: it
writes `$30` to `$01` with the machine stopped, reads the screen through the
old reader and the new one, and puts `$01` back before a cycle passes.

    .venv/bin/python tools/screenblind.py --disks "$POR_DISKS" --save PORSAVE.D64

Everything is logged as it is measured (`work/screenblind/<tag>/samples.jsonl`),
because a run that dies at minute nine still has minutes one to eight.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap import screen as _screen  # noqa: E402
from automap.vice import CMD_BANKS_AVAILABLE  # noqa: E402
from tools import session as S  # noqa: E402


def banks(mon) -> dict[str, int]:
    """`{name: id}` for every bank this VICE offers, from the machine itself.

    The ids are not guessable and are not the same on two machines' worth of
    VICE builds, so they are read rather than assumed.
    """
    resp = mon.command(CMD_BANKS_AVAILABLE)
    count = int.from_bytes(resp[:2], "little")
    out, off = {}, 2
    for _ in range(count):
        size = resp[off]
        bank_id = int.from_bytes(resp[off + 1 : off + 3], "little")
        name_len = resp[off + 3]
        out[resp[off + 4 : off + 4 + name_len].decode("ascii", "replace")] = bank_id
        off += size + 1
    return out


class Log:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a", buffering=1)

    def emit(self, kind: str, **fields) -> None:
        self.fh.write(json.dumps({"t": round(time.time(), 3), "kind": kind,
                                  **fields}) + "\n")


class Watched(S.Session):
    """A session that records the registers behind every screen it reads."""

    jlog: Log
    io_bank = 0
    ram_bank = 0
    samples = 0
    disagreements = 0
    stage_prompt = False
    staged_prompt = False

    def screen(self):
        try:
            with self.mon(3) as m:
                port1 = m.peek(0x01)
                d011 = m.peek(0xD011)
                d018 = m.peek(0xD018)
                dd00 = m.peek(0xDD00)
                d011_io = m.peek(0xD011, bank=self.io_bank)
                d018_io = m.peek(0xD018, bank=self.io_bank)
                dd00_io = m.peek(0xDD00, bank=self.io_bank)
                here = _screen.screen_address(m.read)
                there = ((~dd00_io & 3) * 0x4000) + ((d018_io >> 4) & 0xF) * 0x400
                bitmap = bool(d011_io & 0x20)
                row24_here = _screen.codes_to_text(
                    m.read(here + 24 * 40, 40, bank=self.ram_bank))
                row24_there = _screen.codes_to_text(
                    m.read(there + 24 * 40, 40, bank=self.ram_bank))
                codes = m.read(there, 1000, bank=self.ram_bank)
                colours = m.read(0xD800, 1000, bank=self.io_bank)
        except Exception as exc:
            self.jlog.emit("read-failed", error=repr(exc))
            return None
        self.samples += 1
        bad = (d018, dd00) != (d018_io, dd00_io)
        if bad:
            self.disagreements += 1
        self.jlog.emit(
            "sample", n=self.samples, p01=port1,
            d011=d011, d018=d018, dd00=dd00,
            d011_io=d011_io, d018_io=d018_io, dd00_io=dd00_io,
            here=here, there=there, disagree=bad, bitmap=bitmap,
            row24_here=row24_here, row24_there=row24_there,
        )
        if bad:
            print(f"  DISAGREE $01={port1:02X} default ${here:04X} io ${there:04X}"
                  f" |{row24_here}| vs |{row24_there}|", flush=True)
        if bitmap:
            return None
        got = _screen.Screen(codes, colours, there)
        # The prompt `#336` is named for, and the one poll that first sees it:
        # stage the banking here, before `handle_prompt` answers it, so the
        # question is asked of the screen the ticket is about rather than of
        # a menu that happens to be up.
        if (self.stage_prompt and not self.staged_prompt
                and S.RE_GAME_SIDE.search(got.text())):
            self.staged_prompt = True
            with self.mon(5) as m:
                out = staged_reads(m, "the insert-a-side prompt")
            self.jlog.emit("staged", **out)
            report(out)
        return got


def staged(sess, log, where: str) -> dict:
    """Bank the chips out on purpose and read the screen both ways.

    The window in which the game does this to itself is four polls in a
    thousand, so waiting for it is not an experiment.  The machine is stopped
    for as long as a monitor connection is open, so `$01` is written, read
    from and put back without a single emulated cycle passing: the game never
    runs with it, and the reader is asked the same question the loader asks
    it.

    `automap.vice.read_screen` is the reader as it was -- every read on the
    default bank -- and `tools.drive.read_screen` is the one under test.
    """
    with sess.mon(5) as m:
        out = staged_reads(m, where)
    log.emit("staged", **out)
    report(out)
    return out


def staged_reads(m, where: str) -> dict:
    """The staging itself, over a monitor somebody else has already opened.

    `automap.vice.read_screen` is the reader as it was -- every read on the
    default bank -- and `tools.drive.read_screen` is the one under test.
    """
    from automap import vice as V
    from tools import drive as Dr

    out = {"where": where}
    was = m.read(0x01, 1)[0]
    out["p01_before"] = was
    before = Dr.read_screen(m)
    out["before"] = {"addr": before.address, "row24": before.row(24)}
    m.write(0x01, bytes([0x30]))
    out["p01_staged"] = m.read(0x01, 1)[0]
    old = V.read_screen(m)
    out["old_reader"] = {"addr": old.address, "row24": old.row(24)}
    new = Dr.read_screen(m)
    out["new_reader"] = {"addr": new.address, "row24": new.row(24)}
    m.write(0x01, bytes([was]))
    out["p01_after"] = m.read(0x01, 1)[0]
    return out


def report(out: dict) -> None:
    print(f"staged at {out['where']}: $01 ${out['p01_before']:02X} -> "
          f"${out['p01_staged']:02X} -> ${out['p01_after']:02X}", flush=True)
    for which in ("before", "old_reader", "new_reader"):
        print(f"  {which:11s} ${out[which]['addr']:04X} |{out[which]['row24']}|",
              flush=True)


def run(args) -> int:
    tag = args.tag or time.strftime("%H%M%S")
    out = pathlib.Path(S.TOOLS).parent / "work" / "screenblind" / tag
    log = Log(out / "samples.jsonl")
    slot = S.claim_slot(args.slot, f"screenblind/{tag}")
    print(f"slot {slot.n} display {slot.display}; log {log.path}", flush=True)
    sess = None
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks))
        if args.save:
            shutil.copy(pathlib.Path(args.disks) / args.save,
                        pathlib.Path(slot.dir) / "SIDE0.D64")
        sess = Watched(boot, slot=slot)
        sess.jlog = log
        sess.stage_prompt = args.stage
        sess.launch()
        with sess.mon(5) as m:
            available = banks(m)
        log.emit("banks", banks=available)
        print("banks:", available, flush=True)
        sess.io_bank = available.get("io", 0)
        sess.ram_bank = available.get("ram", 0)
        log.emit("phase", phase="boot")
        # `Session.boot` launches; this one has launched already, so the
        # rest of it is spelled out rather than re-entered.
        if sess.wait_text("DISABLE FASTLOADER", 120)[0] is None:
            raise RuntimeError("no fastloader prompt")
        sess.kbd.key(sess.fastloader, 0.15, 0.28)
        if sess.wait_text("PLAY GAME", 240)[0] is None:
            raise RuntimeError("no PLAY GAME menu")
        sess.kbd.key("Return")
        if sess.wait_text("INPUT THE CODE WORD", 240)[0] is None:
            raise RuntimeError("no code word prompt")
        if not sess.pass_protection():
            raise RuntimeError("copy protection")
        if args.stage:
            staged(sess, log, "the main menu")
        log.emit("phase", phase="load_save")
        listed = sess.load_save()
        log.emit("load_save", listed=listed)
        if not listed:
            raise RuntimeError("the game did not list the save")
        log.emit("phase", phase="begin_adventuring")
        arrived = sess.begin_adventuring()
        log.emit("arrival", arrived=arrived)
        if args.stage and arrived:
            staged(sess, log, "the world")
        sess.kbd.screenshot(str(out / "arrived.png"))
        print(f"arrived={arrived} samples={sess.samples} "
              f"disagreements={sess.disagreements}", flush=True)
        log.emit("done", arrived=arrived, samples=sess.samples,
                 disagreements=sess.disagreements)
        return 0 if arrived else 1
    finally:
        if sess is not None:
            sess.close()
        slot.teardown()
        slot.release()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--disks", default=None, help="the player's disk directory")
    ap.add_argument("--save", default="", help="which save image to stage as SIDE0")
    ap.add_argument("--slot", type=int, default=None)
    ap.add_argument("--tag", default="")
    ap.add_argument("--stage", action="store_true",
                    help="bank the chips out on purpose and read both ways")
    args = ap.parse_args(argv)
    if args.disks is None:
        from automap import paths
        args.disks = str(paths.find_disks())
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
