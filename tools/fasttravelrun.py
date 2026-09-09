#!/usr/bin/env python3
"""Drive the *shipped* `automap.actions.FastTravel().run()` through a real
`automap.target.ViceTarget`, and check that it ran the exit's own handler.

`#207 (Run an exit's own handler before Fast Travel warps out)`'s two
existing proofs are elsewhere: `tools/exitreentry.py`'s `reenter()` rebuilds
the 6502 stack directly and calls it a re-entry point, and
`tools/reentrypoints.py` checks the five addresses that rests on against a
shipped `DUNGEON` with no emulator at all. Neither calls the production code
path a player's own Fast Travel button runs. This does:
`automap.actions.FastTravel().run()`, unmodified, through `automap.target.
ViceTarget`, on a pool slot the way `tools/livecheck.py` boards one.

The one case this has been run against is the one #207 was filed for:
warping out of the Kobold Caves (area 13) to the East Window (area 27) drops
Princess Fatima from the roster the same way walking out does, because
`ECL0D $9A84`'s own prologue runs before the warp. `--from-area`,
`--to-area` and `--member` generalise the check to another exit and NPC if
one is ever wanted, but only the Kobold Caves case has a save that carries
the NPC -- `npc_party.d64` -- and has actually been driven this way.

    tools/fasttravelrun.py --disks $POR_DISKS --save ~/Downloads/npc_party.d64 \\
        --out work/issue207/live2

Nothing is written to the player's disks: `tools.session.stage_disks` copies
the sides into the slot, and `--save` is copied in as `SIDE0.D64`. The pool
owns the emulator lifecycle throughout -- `tools.session.claim_slot` leases
a slot through `tools.instance.claim`, and the slot is torn down on every
exit path, including an exception, the same `finally` shape
`tools/exitreentry.py` and `tools/livecheck.py` use.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions as A  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from automap.target import ViceTarget  # noqa: E402
from tools import session as S  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")
DEFAULT_SAVE = pathlib.Path("~/Downloads/npc_party.d64").expanduser()

CAVES, EAST = 13, 27
SLOT_RECORD, SLOT_ROSTER, SLOTS = 0x4D00, 0x8300, 8
#: `$6E1B`, masked to seven bits: `docs/163-dos-vm-address-map.md`'s area
#: byte, the same one `automap.actions.FastTravel.current_area` reads.
AREA_BYTE = 0x6E1B


def name(raw: bytes) -> str:
    """The first null-terminated run of *raw*, printable bytes as
    themselves and anything else as `.` -- `<empty>` for a zeroed slot."""
    if not raw or raw[0] == 0:
        return "<empty>"
    out = raw.split(b"\x00")[0]
    return "".join(chr(c) if 32 <= c < 127 else "." for c in out)


def party(sess) -> list[dict]:
    """The eight roster slots' name and status byte, read in one monitor
    session so the party cannot change mid-read."""
    rows = []
    with sess.mon(8) as m:
        for i in range(SLOTS):
            rec = m.read(SLOT_RECORD + i * 0x100, 0x100)
            ros = m.read(SLOT_ROSTER + i * 0x20, 0x20)
            rows.append({"slot": i, "name": name(rec[:16]), "status": ros[0]})
    return rows


def area_of(sess) -> int:
    with sess.mon(5) as m:
        return m.read(AREA_BYTE, 1)[0] & 0x7F


def has_member(rows: list[dict], substring: str) -> bool:
    """Whether any live roster row's name contains *substring*."""
    return any(substring in r["name"] for r in rows if r["name"] != "<empty>")


def verdict(before: list[dict], after: list[dict], area_before: int,
            area_after: int, from_area: int, to_area: int,
            member: str) -> tuple[bool, str]:
    """The pass/fail judgement over four readings, with no monitor in it at
    all -- the part of this tool that can be proven right without a slot.

    Four ways to fail, checked in the order a run would actually discover
    them: the save was not staged where the check assumes, the warp did not
    land, the named member was never in the party to begin with (a mistyped
    `--member`, not a finding), or -- the one #207 is about -- the member
    is still there, meaning the exit's own handler never ran.
    """
    if area_before != from_area:
        return False, f"the save is not in area {from_area}: read {area_before}"
    if area_after != to_area:
        return False, f"did not land in area {to_area}: read {area_after}"
    if not has_member(before, member):
        return False, f"{member!r} was not in the party to begin with"
    if has_member(after, member):
        return False, (f"the handler did not drop {member!r} -- "
                        "the whole point of #207")
    return True, (f"the production FastTravel.run() ran the exit's own "
                  f"handler and dropped {member!r}")


def answer_and_wait(sess, to_area: int, deadline_s: float = 60.0) -> None:
    """Answer whatever the exit's handler puts on row 24, the way a player
    would, until the area byte says the warp landed.

    Only the shape the Kobold Caves' own handler is known to show --
    `YES`/`NO` in the command bar -- is handled; anything else times out
    rather than guessing at a menu this tool has never seen.
    """
    deadline = time.time() + deadline_s
    answered = False
    while time.time() < deadline:
        s = sess.screen()
        row = s.row(24).strip() if s is not None else ""
        if row:
            print(f"  row 24: {row!r}", flush=True)
        if not answered and "YES" in row.split() and "NO" in row.split():
            sess.select_bar("YES", timeout=15)
            answered = True
            time.sleep(1.0)
            continue
        if area_of(sess) == to_area:
            return
        time.sleep(0.6)


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    disks = pathlib.Path(args.disks) if args.disks else DISKS
    slot = S.claim_slot(args.slot, "issue207 fasttravelrun.py")
    print(f"slot {slot.n} display {slot.display}", flush=True)
    sess = None
    target = None
    result = {"ok": False, "message": "did not reach a verdict"}
    try:
        boot = S.stage_disks(slot, disks)
        # The save usually lives outside the disk directory -- the default
        # is `~/Downloads/npc_party.d64` -- so it is staged by hand rather
        # than through `stage_disks`'s own `save` argument, which looks for
        # it alongside the eight sides.
        S.stage_writable(pathlib.Path(args.save).expanduser(),
                          pathlib.Path(slot.dir) / "SIDE0.D64")
        for p in pathlib.Path(slot.dir).glob("*.D64"):
            os.chmod(p, 0o644)
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("save not accepted")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING failed")
        if not sess.wait_for_world(timeout=args.arrive):
            raise RuntimeError("no command bar after BEGIN ADVENTURING")
        sess.settle(4)

        before = party(sess)
        area_before = area_of(sess)
        print(f"area before: {area_before}", flush=True)
        print("party before:",
              [r for r in before if r["name"] != "<empty>"], flush=True)

        target = ViceTarget()
        try:
            # `ViceTarget` holds one persistent monitor connection and VICE
            # serves exactly one, so it is opened only for the one call
            # that needs it and closed straight after -- every `sess.mon()`
            # call above and below opens and closes its own.
            outcome = A.FastTravel().run(target, area=A.area_by_id(args.to_area))
        finally:
            target.close()
            target = None
        print(f"run(): ok={outcome.ok} message={outcome.message}", flush=True)
        if not outcome.ok:
            # The console has already printed both of these, so the file a
            # reader parses afterwards should carry them too.
            result = {"ok": False, "message": outcome.message,
                      "before": before, "area_before": area_before}
            return 1

        answer_and_wait(sess, args.to_area, deadline_s=args.answer_timeout)
        sess.settle(6)

        after = party(sess)
        area_after = area_of(sess)
        print(f"area after: {area_after}", flush=True)
        print("party after:",
              [r for r in after if r["name"] != "<empty>"], flush=True)

        ok, message = verdict(before, after, area_before, area_after,
                               args.from_area, args.to_area, args.member)
        result = {"ok": ok, "message": message, "before": before,
                  "after": after, "area_before": area_before,
                  "area_after": area_after}
        print(("PASS: " if ok else "FAIL: ") + message, flush=True)
        return 0 if ok else 1
    finally:
        (out / "result.json").write_text(json.dumps(result, indent=1))
        if target is not None:
            try:
                target.close()
            except Exception as e:                       # noqa: BLE001
                print(f"target close failed: {e}", flush=True)
        for what, fn in (("session", sess.terminate if sess else None),
                         ("slot teardown", slot.teardown),
                         ("slot release", slot.release)):
            if fn is None:
                continue
            try:
                fn()
            except Exception as e:                        # noqa: BLE001
                print(f"  {what} failed: {e}", flush=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disks", default=str(DISKS),
                    help="the game disk directory ($POR_DISKS if unset)")
    p.add_argument("--save", default=str(DEFAULT_SAVE),
                    help="the save disk to load, staged in as SIDE0.D64")
    p.add_argument("--out", default=str(ROOT / "work" / "issue207" / "live"))
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--from-area", type=int, default=CAVES)
    p.add_argument("--to-area", type=int, default=EAST)
    p.add_argument("--member", default="FATIMA")
    p.add_argument("--arrive", type=float, default=240.0,
                    help="seconds to wait for the command bar after "
                         "BEGIN ADVENTURING")
    p.add_argument("--answer-timeout", type=float, default=60.0,
                    help="seconds to wait for the handler's own prompt "
                         "and the warp to land")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
