"""Read the tail of `ECL10` at the world bar, `15,11` and `15,12`.

Belongs to #334 (The session driver cannot fight in Curse or Silver Blades, and says the party is not in a fight while it is standing on the combat floor).

The experiment named by the 2026-09-16T03:23:57Z comment on that issue.

Reads block 28 of `ECL10` (`$9AC8`-`$9B64`, plus a few flanking bytes) at
three points: the world bar, `15,11`, and `15,12`, and arms a non-stopping
store checkpoint over that range between the first and second so a second
writer -- if there is one -- shows up as a hit count above 157 (the load
itself) rather than only as changed bytes.

Run: `.venv/bin/python tools/secret_of_the_silver_blades/ssbtailprobe.py`. It takes no arguments, claims
an emulator pool slot and boots Silver Blades with `$WISH_SPECIMENS/por-c64/WISH-SPEC-ssb-d-engine-resave-walked.D64`
as the save. Writes readings, screens and `tail-probe.jsonl` under
`<tmp>/wish/ssbtailprobe/`.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from goldbox import c64_port as G  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.c64.laterbattle import Battle  # noqa: E402
from tools.curse_of_the_azure_bonds import (  # noqa: E402
    cursethac0,
)
from tools.curse_of_the_azure_bonds.cursethac0 import checkpoint_hits  # noqa: E402
from tools.registry import (  # noqa: E402
    scratch,
    specimens,
)
from tools.secret_of_the_silver_blades import (  # noqa: E402
    ssbwarp,
)

OUT = scratch.scratch_dir("ssbtailprobe")
SAVE = str(specimens.tree_root() / "por-c64"
            / "WISH-SPEC-ssb-d-engine-resave-walked.D64")

TAIL_START = 0x9AC0
TAIL_LEN = 176  # $9AC0-$9B70

# Store checkpoint over exactly block 28, $9AC8-$9B64.
CKPT_START, CKPT_END = 0x9AC8, 0x9B64

WORLD_EXTRA = {
    "$7F1B": 0x7F1B, "$2D9E": 0x2D9E, "$2DB7": 0x2DB7, "$7EDC": 0x7EDC,
    "$7F47": 0x7F47, "$7F48": 0x7F48, "$7F49": 0x7F49,
    "$0330": 0x0330, "$0331": 0x0331, "$7E9F": 0x7E9F, "$7EE5": 0x7EE5,
}
FINAL_EXTRA = {
    "$7EDC": 0x7EDC, "$7F47": 0x7F47, "$7F48": 0x7F48, "$7F49": 0x7F49,
    "$7F4A": 0x7F4A, "$7F4B": 0x7F4B,
}


def read_block(sess, extra: dict, checkpoint: int | None) -> dict:
    """Tail bytes, the named single bytes, and a checkpoint's hit count --
    all in one paused monitor round trip."""
    with sess.mon(10) as m:
        tail = m.read(TAIL_START, TAIL_LEN)
        vals = {name: m.read(addr, 1)[0] for name, addr in extra.items()}
        hits = None if checkpoint is None else checkpoint_hits(m, checkpoint)
        m.resume()
    return {"tail": tail.hex(" "), "tail_raw": tail, **vals,
            "checkpoint_hits": hits}


def arm_checkpoint(sess) -> int:
    with sess.mon(10) as m:
        n = m.checkpoint_set(CKPT_START, CKPT_END, store=True, stop=False)
        m.resume()
    return n


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    out = OUT
    scratch.ensure(out)
    log_path = out / "tail-probe.jsonl"
    log_file = log_path.open("w")

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

    slot = S.claim_slot(None, "emulator-runner/334-ssb8-tail")
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
        if not ssbwarp.load_party(sess):
            log("loaded", outcome="no")
            return 1
        log("loaded", outcome="loaded")

        addr = ssbwarp.Addresses(game, disks)
        S.INDOORS_AT = addr.indoors
        entered = ssbwarp.enter_world(sess, addr, timeout=240.0,
                                      stop_at_idle=False)
        log("world", entered=entered, row24=sess.screen().row(24).strip()
            if sess.screen() is not None else None)
        if not entered:
            return 1

        s = sess.screen()
        rows = ["(bitmap)"] if s is None else [s.row(r) for r in range(25)]
        (out / "10-world.txt").write_text("\n".join(rows) + "\n")
        sess.kbd.screenshot(str(out / "10-world.png"))

        # -- step 2: the world-bar reading, no checkpoint armed yet --------
        world_read = read_block(sess, WORLD_EXTRA, None)
        (out / "tail-world.bin").write_bytes(world_read["tail_raw"])
        log("world-reading", **{k: v for k, v in world_read.items()
                                if k != "tail_raw"})

        expected_9af9 = bytes.fromhex("2b 01 82 7f 00 01 80 1b")
        expected_9b20 = bytes.fromhex("2b 01 82 7f 00 02 80 03")
        got_9af9 = world_read["tail_raw"][0x9AF9 - TAIL_START:
                                          0x9AF9 - TAIL_START + 8]
        got_9b20 = world_read["tail_raw"][0x9B20 - TAIL_START:
                                          0x9B20 - TAIL_START + 8]
        tail_ok = (got_9af9 == expected_9af9 and got_9b20 == expected_9b20)
        log("tail-check", tail_ok=tail_ok,
            got_9af9=got_9af9.hex(" "), want_9af9=expected_9af9.hex(" "),
            got_9b20=got_9b20.hex(" "), want_9b20=expected_9b20.hex(" "),
            f7f1b=world_read["$7F1B"], f2d9e=world_read["$2D9E"],
            f2db7=world_read["$2DB7"])

        if not tail_ok:
            log("negative-result",
                reason="ECL10's tail is already wrong at the world bar, "
                       "before any walk -- the load itself is the "
                       "question, not anything downstream of it. This is "
                       "the reverse-engineering escape hatch: a live "
                       "before/after-load checkpoint needs a second boot "
                       "armed at the party menu, not this run.")
            rc = 0
            return rc

        # -- step 4: tail is right at the world bar; arm, walk, read again -
        ckpt = arm_checkpoint(sess)
        log("armed", checkpoint=ckpt, start=hex(CKPT_START), end=hex(CKPT_END))

        area, geo = cursethac0.area_geo(SAVE, disks)
        run = Battle(out, quiet=False)
        run.sess = sess
        arrived = run.goto((15, 11), budget=40, geo=geo, accept=True)
        log("goto-15-11", arrived=arrived, area=str(area),
            triple=list(run.triple()), row24=run.row24())
        s = sess.screen()
        rows = ["(bitmap)"] if s is None else [s.row(r) for r in range(25)]
        (out / "11-staged-15-11.txt").write_text("\n".join(rows) + "\n")
        sess.kbd.screenshot(str(out / "11-staged-15-11.png"))

        mid_read = read_block(sess, WORLD_EXTRA, ckpt)
        (out / "tail-15-11.bin").write_bytes(mid_read["tail_raw"])
        log("reading-15-11", **{k: v for k, v in mid_read.items()
                                if k != "tail_raw"})

        if not arrived or run.triple()[:2] != (15, 11):
            log("negative-result",
                reason="the walk to 15,11 did not land there; see "
                       "goto-15-11 above for what stopped it.")
            rc = 0
            return rc

        # -- the one step onto 15,12 ---------------------------------------
        before = run.triple()
        # 15,11 -> 15,12 is y+1: facing 2 (S) in the STEP/turn_to convention.
        run.turn_to(2)
        moved = run.press("I")
        after = run.triple()
        log("the-step", before=list(before), after=list(after), moved=moved,
            row24=run.row24())
        s = sess.screen()
        rows = ["(bitmap)"] if s is None else [s.row(r) for r in range(25)]
        (out / "12-immediately-after-step.txt").write_text(
            "\n".join(rows) + "\n")
        sess.kbd.screenshot(str(out / "12-immediately-after-step.png"))

        time.sleep(6.0)
        s = sess.screen()
        rows = ["(bitmap)"] if s is None else [s.row(r) for r in range(25)]
        (out / "13-after-6s-watch.txt").write_text("\n".join(rows) + "\n")
        sess.kbd.screenshot(str(out / "13-after-6s-watch.png"))

        final_read = read_block(sess, FINAL_EXTRA, ckpt)
        (out / "tail-15-12.bin").write_bytes(final_read["tail_raw"])
        log("reading-15-12", **{k: v for k, v in final_read.items()
                                if k != "tail_raw"})

        edc = final_read["$7EDC"]
        verdict = ("EXIT-was-last" if edc == 0x00 else
                   "HORIZMENU-was-last" if edc == 0x2B else
                   "neither-EXIT-nor-HORIZMENU")
        log("verdict", f7edc=edc, meaning=verdict,
            f7f47=final_read["$7F47"], f7f48=final_read["$7F48"],
            f7f49=final_read["$7F49"], f7f4a=final_read["$7F4A"],
            f7f4b=final_read["$7F4B"],
            expect_return_addr="c1 96 (little-endian for $96C1)",
            checkpoint_hits=final_read["checkpoint_hits"])
        rc = 0
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
