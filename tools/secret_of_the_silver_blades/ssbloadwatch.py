"""Does anything write `$9AC8`-`$9B64` during Silver Blades' boot and load?

Belongs to #334 (The session driver cannot fight in Curse or Silver Blades, and says the party is not in a fight while it is standing on the combat floor).

The 2026-09-16T22:50:33Z comment on the issue found `$9AC0`-`$9B70` holding a
period-8 pattern instead of `ECL10`'s tail at the world bar. This run arms a
non-stopping **store** checkpoint over exactly `$9AC8`-`$9B64` at the party
menu -- before `LOAD SAVED GAME` -- plus two controls inside regions the load
is known to fill, and reads all three hit counts at three points:

    1. the party menu, before the load (baseline, 0 expected everywhere)
    2. `BEGIN ADVENTURING`, after `LOAD SAVED GAME`
    3. the world bar, after `enter_world`

and dumps `$8000`-`$9FFF` at each point so the first byte at which the machine
stops agreeing with `ECL10`'s body can be computed offline. `$2D00`-`$2E00`
and `$3E00`-`$3F80` come along so the loader's own tables can be read out of
the running machine rather than off a transcription.

Run: `.venv/bin/python tools/secret_of_the_silver_blades/ssbloadwatch.py`. It takes no arguments, claims
an emulator pool slot and boots Silver Blades on the disks `tools/gamedisks.py`
finds, with `$WISH_SPECIMENS/por-c64/WISH-SPEC-ssb-d-engine-resave-walked.D64`
as the save. Writes dumps and `load-probe.jsonl` under the `ssbloadwatch` scratch directory.
`ssbloadnoescape.py` and `ssbloadescape.py` are the same boot with one thing
changed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port as G  # noqa: E402
from tools import (  # noqa: E402
    gamedisks,
    scratch,
    specimens,
)
from tools.c64 import session as S  # noqa: E402
from tools.curse_of_the_azure_bonds.cursethac0 import checkpoint_hits  # noqa: E402
from tools.secret_of_the_silver_blades import (  # noqa: E402
    ssbwarp,
)

OUT = scratch.scratch_dir("ssbloadwatch")
SAVE = str(specimens.tree_root() / "por-c64"
            / "WISH-SPEC-ssb-d-engine-resave-walked.D64")

#: (name, start, length) -- dumped whole at every reading point.
REGIONS = [
    ("script", 0x8000, 0x2000),    # $8000-$9FFF: ECL10's whole expected span
    ("linker", 0x2D00, 0x0100),    # $2D00-$2DFF: LINKER and what follows it
    ("loadtab", 0x3E00, 0x0180),   # $3E00-$3F7F: LIBRARY's loader tables
]

#: Store checkpoints. The first is the question; the other two are controls,
#: both inside ranges `ECL10` must fill if it lands at $8000 at all. Without
#: them a zero on the first says nothing -- it could be a broken checkpoint.
CHECKPOINTS = [
    ("tail",  0x9AC8, 0x9B64),     # the 157 bytes of ECL10's last disk block
    ("head",  0x8000, 0x800F),     # the script's entry-point table
    ("mid",   0x9900, 0x990F),     # inside the script, well below the tail
]

SINGLES = {
    "$7EDC": 0x7EDC, "$7F47": 0x7F47, "$7F48": 0x7F48, "$7F49": 0x7F49,
    "$C04B": 0xC04B, "$C04C": 0xC04C, "$C04D": 0xC04D,
}


def read_point(sess, ckpts: dict[str, int], tag: str, out: pathlib.Path,
               log) -> dict:
    """One paused monitor block: every region, every hit count, the singles."""
    with sess.mon(15) as m:
        dumps = {name: m.read(start, length) for name, start, length in REGIONS}
        hits = {name: checkpoint_hits(m, n) for name, n in ckpts.items()}
        singles = {name: m.read(a, 1)[0] for name, a in SINGLES.items()}
        cache = m.read(0x7F13, 26)
        m.resume()
    for name, blob in dumps.items():
        (out / f"{tag}-{name}.bin").write_bytes(blob)
    rec = {"hits": hits, "singles": singles, "cache": cache.hex(" ")}
    log(f"reading-{tag}", **rec)
    return rec


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    out = OUT
    out.mkdir(parents=True, exist_ok=True)
    log_file = (out / "load-probe.jsonl").open("w")

    def log(kind: str, **kw) -> None:
        kw["kind"], kw["t"] = kind, round(time.time(), 3)
        rec = {k: (v.hex(" ") if isinstance(v, (bytes, bytearray)) else v)
               for k, v in kw.items()}
        log_file.write(json.dumps(rec, default=str) + "\n")
        log_file.flush()
        print(kind, {k: v for k, v in rec.items() if k not in ("kind", "t")},
              flush=True)

    game = G.SECRET_OF_THE_SILVER_BLADES
    disks = str(gamedisks.find(game.key) or "")
    if not disks:
        print("no Silver Blades disks found", file=sys.stderr)
        return 2

    slot = S.claim_slot(None, "reverse-engineering/334-ssb14-loadwatch")
    log("slot", n=slot.n, display=slot.display, dir=str(slot.dir))
    sess = None
    rc = 1
    try:
        boot = ssbwarp.stage(slot, disks, SAVE)
        sess = ssbwarp.SSBSession(boot, slot=slot)
        sess.save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
        if not sess.boot():
            log("boot", reached_menu=False)
            return 1
        log("boot", reached_menu=True)

        # -- arm, at the party menu, before LOAD SAVED GAME ----------------
        ckpts: dict[str, int] = {}
        with sess.mon(15) as m:
            stale = m.checkpoints_clear()
            for name, start, end in CHECKPOINTS:
                ckpts[name] = m.checkpoint_set(start, end, store=True,
                                               stop=False)
            m.resume()
        log("armed", cleared=stale,
            checkpoints={k: v for k, v in ckpts.items()},
            ranges={n: f"${s:04X}-${e:04X}" for n, s, e in CHECKPOINTS})

        s = sess.screen()
        (out / "01-party-menu.txt").write_text(
            "\n".join(s.row(r) for r in range(25)) + "\n"
            if s is not None else "(bitmap)\n")
        read_point(sess, ckpts, "01-menu", out, log)

        if not ssbwarp.load_party(sess):
            log("loaded", outcome="no")
            read_point(sess, ckpts, "02-loadfail", out, log)
            return 1
        log("loaded", outcome="loaded")
        s = sess.screen()
        (out / "02-begin-adventuring.txt").write_text(
            "\n".join(s.row(r) for r in range(25)) + "\n"
            if s is not None else "(bitmap)\n")
        sess.kbd.screenshot(str(out / "02-begin-adventuring.png"))
        read_point(sess, ckpts, "02-loaded", out, log)

        addr = ssbwarp.Addresses(game, disks)
        S.INDOORS_AT = addr.indoors
        entered = ssbwarp.enter_world(sess, addr, timeout=240.0,
                                      stop_at_idle=False)
        s = sess.screen()
        log("world", entered=entered,
            row24=s.row(24).strip() if s is not None else None)
        (out / "03-world.txt").write_text(
            "\n".join(s.row(r) for r in range(25)) + "\n"
            if s is not None else "(bitmap)\n")
        sess.kbd.screenshot(str(out / "03-world.png"))
        read_point(sess, ckpts, "03-world", out, log)
        rc = 0 if entered else 1
        return rc
    finally:
        log("done", rc=rc)
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()
        log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
