#!/usr/bin/env python3
"""Drive the *shipped* `automap.actions.FastTravel().run()` through a real
`automap.target.ViceTarget`, and check that it ran the exit's own handler.

`#207 (Run an exit's own handler before Fast Travel warps out)`'s two
existing proofs are elsewhere: `tools/areas/exitreentry.py`'s `reenter()` rebuilds
the 6502 stack directly and calls it a re-entry point, and
`tools/areas/reentrypoints.py` checks the five addresses that rests on against a
shipped `DUNGEON` with no emulator at all. Neither calls the production code
path a player's own Fast Travel button runs. This does:
`automap.actions.FastTravel().run()`, unmodified, through `automap.target.
ViceTarget`, on a pool slot the way `tools/gui/livecheck.py` boards one.

The one case this has been run against is the one #207 was filed for:
warping out of the Kobold Caves (area 13) to the East Window (area 27) drops
Princess Fatima from the roster the same way walking out does, because
`ECL0D $9A84`'s own prologue runs before the warp. `--from-area`,
`--to-area` and `--member` generalise the check to another exit and NPC if
one is ever wanted, but only the Kobold Caves case has a save that carries
the NPC -- `npc_party.d64` -- and has actually been driven this way.

    tools/areas/fasttravelrun.py --disks $POR_DISKS --out DIR

The two-hop case (`WISH_EXPERIMENTAL_TWO_HOP_FAST_TRAVEL`) is the Kobold Caves
to New Phlan (area 0) and is driven with the flag exported and a wait long
enough to show the 120 s deadline. `--to-area 27` is a one-exit route and never
reaches the two-hop branch:

    WISH_EXPERIMENTAL_TWO_HOP_FAST_TRAVEL=1 .venv/bin/python \\
        tools/areas/fasttravelrun.py --from-area 13 --to-area 0 \\
        --answer-timeout 150 --out DIR

A run saves four screenshots under `--out` (`1-before.png`, `2-question.png`,
`3-after-second-hop.png`, `4-after-walk.png`) and writes `result.json` with
`second_hop_seconds` -- the seconds from the area byte first reading the area
the exit leads to, to reading the destination; None when there was no second
hop -- and
`total_seconds`, which runs from before the slot is claimed to the landing and
so includes staging and boot. After a PASS the party walks a few steps each way and opens
and closes the first character's sheet before teardown; a walk that fails is
its own FAIL and leaves the earlier verdict as it was.

Nothing is written to the player's disks: `tools.c64.session.stage_disks` copies
the sides into the slot, and `--save` is copied in as `SIDE0.D64`. The pool
owns the emulator lifecycle throughout -- `tools.c64.session.claim_slot` leases
a slot through `tools.registry.instance.claim`, and the slot is torn down on every
exit path, including an exception, the same `finally` shape
`tools/areas/exitreentry.py` and `tools/gui/livecheck.py` use.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions as A  # noqa: E402
from automap.actions import _read, mode, program_counter  # noqa: E402
from automap.paths import tool_disks  # noqa: E402
from automap.target import ViceTarget  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.registry import scratch  # noqa: E402

DISKS: pathlib.Path | None = tool_disks()

CAVES, EAST = 13, 27
SLOT_RECORD, SLOT_ROSTER, SLOTS = 0x4D00, 0x8300, 8
#: `$6E1B`, masked to seven bits: `docs/163-dos-vm-address-map.md`'s area
#: byte, the same one `automap.actions.FastTravel.current_area` reads.
AREA_BYTE = 0x6E1B

#: The fixed screenshot names, one per checkpoint, saved under `--out`.
SHOTS = {"before": "1-before.png", "question": "2-question.png",
         "after_hop": "3-after-second-hop.png", "after_walk": "4-after-walk.png"}

#: Two steps in each of four directions. Outdoors those are compass digits
#: (north, east, south, west -- `tools.c64.session.COMPASS`); indoors a turn is
#: a move of its own, so `IIKIIKIIKII` goes forward twice, then turns three
#: times with two steps forward after each.
WALK_OUTDOORS = "11335577"
WALK_INDOORS = "IIKIIKIIKII"


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
            member: str, two_hop: bool = False,
            second_hop_seconds: float | None = None) -> tuple[bool, str]:
    """The pass/fail judgement over four readings, with no monitor in it at
    all -- the part of this tool that can be proven right without a slot.

    `to_area` is the destination that was asked for, so a two-hop trip that
    stopped in the area its door leads to fails the second check rather than
    passing on the way through.

    `two_hop` says the trip had a pending second hop; it must then have been
    timed, so a run that reads the destination with no `second_hop_seconds`
    measured the wrong thing and fails rather than passing without a number.

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
    if two_hop and second_hop_seconds is None:
        return False, (f"area {to_area} was read but the second hop was never "
                        "timed, so this run measured nothing about it")
    if not has_member(before, member):
        return False, f"{member!r} was not in the party to begin with"
    if has_member(after, member):
        return False, (f"the handler did not drop {member!r} -- "
                        "the whole point of #207")
    return True, (f"the production FastTravel.run() ran the exit's own "
                  f"handler and dropped {member!r}")


def elapsed(start: float | None, end: float | None) -> float | None:
    """Seconds from *start* to *end*, rounded to a tenth; None when either
    moment never happened, so a missing measurement cannot read as zero."""
    if start is None or end is None:
        return None
    return round(end - start, 1)


def walk_verdict(steps: list[dict], sheet_opened: bool) -> tuple[bool, str]:
    """Whether the party is walkable after the trip, judged from the steps
    `walk_afterwards` recorded and with no monitor in it.

    A step that a wall stops is a fact about the map and is not a failure;
    what fails is a party whose square changed on none of its steps (a turn is
    not a move), a driver that
    pressed nothing, or a roster sheet that never came up -- each of which is
    what a wedged party looks like.
    """
    if not steps:
        return False, "no step was tried"
    refused = [s for s in steps if s.get("refused")]
    if refused:
        return False, f"the driver refused a step: {refused[0]['refused']}"
    walked = [s for s in steps if "move" in s]
    moved = sum(1 for s in walked if s.get("after") != s.get("before"))
    if not moved:
        return False, (f"the party did not move: its square did not change on "
                       f"any of {len(walked)} steps")
    if not sheet_opened:
        return False, "the character sheet did not open after the walk"
    return True, (f"the party changed square on {moved} of {len(walked)} "
                  "steps and the character sheet opened and closed")


def enable_debug_logging() -> None:
    """Send the automapper's own debug lines -- `FastTravel._idle_verdict`'s and
    `continue_pending`'s explanations of why they did nothing -- to stdout, the
    driver's log. Idempotent: a second call adds no second handler."""
    logger = logging.getLogger("wish.automap")
    logger.setLevel(logging.DEBUG)
    if not any(getattr(h, "_fasttravelrun", False) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler._fasttravelrun = True
        handler.setFormatter(logging.Formatter("  %(name)s: %(message)s"))
        logger.addHandler(handler)


def second_hop(ft, open_target, marks: dict | None = None,
               clock=time.monotonic):
    """One poll of a two-hop trip's second hop, the way the automapper's own
    poll makes it: `ft.continue_pending` through the real target.

    The target is opened for this one call and closed straight after, for the
    same reason `run` does it around `FastTravel.run`: VICE serves one monitor
    connection, and every `sess.mon()` call opens its own. `open_target` is
    required so that no caller falls back on the default monitor port, which
    is not where a pool slot's emulator listens.

    While a hop is pending, each poll prints what `continue_pending` decides
    on -- the raw area byte, the overlay mode and the program counter -- so a
    hop that never fires says which check refused. `marks["through"]` is set
    to `clock()` on the first poll that reads the area the door leads to with the loader idle
    (bit 7 clear), before
    `continue_pending` can make the hop: the start of the second hop's own
    timing.
    """
    target = open_target()
    try:
        pending = ft.pending
        if pending is not None:
            raw = _read(target, AREA_BYTE, 1)
            print(f"  poll: $6E1B={raw.hex() if raw else None} "
                  f"mode={mode(target)} pc={program_counter(target)}",
                  flush=True)
            if (marks is not None and raw and "through" not in marks
                    and raw[0] == pending.through):
                marks["through"] = clock()
        return ft.continue_pending(target)
    finally:
        target.close()


#: The menus the driver knows how to answer: the words that must all be on row
#: 24, and the word to select. `YES`/`NO` is the exit handler's own question.
#: `LARGE SMALL LEAVE` is the wilderness square's arrival menu after a walk out
#: of the Kobold Caves; `LARGE` and `SMALL` walk the party back into the caves,
#: so only `LEAVE` keeps the trip going. A row matching no entry is not
#: answered.
MENUS = ((("YES", "NO"), "YES"), (("LARGE", "SMALL", "LEAVE"), "LEAVE"))


def choice_for(row: str) -> str | None:
    """The word to select on the command bar *row*, or None when it is not a
    menu in `MENUS`."""
    words = row.split()
    for needed, pick in MENUS:
        if all(w in words for w in needed):
            return pick
    return None


def answer_and_wait(sess, to_area: int, deadline_s: float = 60.0,
                    between=None, on_question=None, marks: dict | None = None,
                    clock=time.monotonic):
    """Answer whatever the exit's handler puts on row 24, the way a player
    would, until the area byte says the warp landed.

    Only the menus in `MENUS` are answered, each once; anything else times out
    rather than guessing at a menu this tool has never seen.

    `between`, when given, is called once a lap until it answers an `Outcome`
    -- a two-hop trip's `second_hop`. That outcome is returned at once when it
    is a failure (the trip gave up) and otherwise once the area byte lands.

    `on_question` is called once, when the game's `YES`/`NO` is up and before it
    is answered; the arrival menu does not call it. `marks["landed"]` is set to `clock()` at the moment the area
    byte reads `to_area`, which is the end of the second-hop timing.
    """
    deadline = time.time() + deadline_s
    answered: set[str] = set()
    hop = None
    while time.time() < deadline:
        if between is not None and hop is None:
            hop = between()
            if hop is not None:
                print(f"  second hop: ok={hop.ok} message={hop.message}",
                      flush=True)
                if not hop.ok:
                    return hop
        s = sess.screen()
        row = s.row(24).strip() if s is not None else ""
        if row:
            print(f"  row 24: {row!r}", flush=True)
        pick = choice_for(row)
        if pick is not None and pick not in answered:
            if pick == "YES" and on_question is not None:
                on_question()
            sess.select_bar(pick, timeout=15)
            answered.add(pick)
            time.sleep(1.0)
            continue
        if area_of(sess) == to_area:
            if marks is not None:
                marks["landed"] = clock()
            return hop
        time.sleep(0.6)
    return hop


def shoot(sess, out: pathlib.Path, key: str, shots: dict) -> None:
    """One checkpoint screenshot under *out*; `shots[key]` is the path, or
    None when the screenshot failed -- which never stops the run."""
    path = out / SHOTS[key]
    try:
        shots[key] = str(path) if sess.kbd.screenshot(str(path)) else None
    except Exception as e:                                # noqa: BLE001
        print(f"  screenshot {key} failed: {e}", flush=True)
        shots[key] = None


def row24(sess) -> str:
    """Row 24 of the screen, stripped; empty when there is no screen to read."""
    s = sess.screen()
    return s.row(24).strip() if s is not None else ""


def settle_world(sess, out: pathlib.Path, shots: dict) -> tuple[bool, str]:
    """Wait for the world's command bar before the walk, so the walk never
    starts on a disk prompt or a menu. On failure row 24 is recorded verbatim
    in the message and a screenshot is taken."""
    if sess.wait_for_world(timeout=60):
        print(f"  settled: row 24 {row24(sess)!r}", flush=True)
        return True, ""
    row = row24(sess)
    print(f"  not settled: row 24 {row!r}", flush=True)
    shoot(sess, out, "after_walk", shots)
    return False, f"the world's command bar never came up; row 24 reads {row!r}"


def walk_afterwards(sess) -> tuple[list[dict], bool]:
    """A few steps in each direction, then the first character's sheet opened
    and closed -- the one action that is not a move. Returns every step's
    result and whether the sheet came up.

    Row 24 is read before every step and stored in it. A fight is handed to
    `Session.fight` with `melee_turn` (the default tactic only passes, which
    never ends one) and recorded as `{"fight": ...}`. Any row that is neither
    the world bar nor the move sub-bar stops the walk with a refused step,
    because `walk_one` would press Return at it and pick a menu's first
    option.

    Called before teardown, because the session is gone once `run` returns.
    """
    indoors = sess.indoors()
    if indoors is None:
        return [], False
    steps: list[dict] = []
    for move in (WALK_INDOORS if indoors else WALK_OUTDOORS):
        row = row24(sess)
        if sess.in_combat():
            result = sess.fight(budget=300, tactic=S.Session.melee_turn)
            back = bool(sess.wait_for_world())
            steps.append({"fight": getattr(result, "outcome", str(result)),
                          "row": row, "world": back})
            print(f"  fight: {steps[-1]['fight']} world={back}", flush=True)
            if not back:
                steps[-1]["refused"] = "the world did not come back after a fight"
                return steps, False
            row = row24(sess)
        if "ENCAMP" not in row and S.MOVE_SUBBAR not in row:
            steps.append({"move": move, "ok": False, "row": row,
                          "before": sess.square(), "after": sess.square(),
                          "refused": f"row 24 is neither the world bar nor "
                                     f"the move sub-bar: {row!r}"})
            print(f"  walk {move}: stopped on row 24 {row!r}", flush=True)
            return steps, False
        before = sess.square()
        ok = sess.walk_one(move)
        steps.append({"move": move, "ok": bool(ok), "row": row,
                      "before": before, "after": sess.square(),
                      "refused": getattr(sess, "walk_refused", None)})
        print(f"  walk {move}: ok={ok} {before} -> {steps[-1]['after']}",
              flush=True)
    sheet = sess.character_sheet(0)
    return steps, bool(sheet)


def disks_of(args) -> pathlib.Path | None:
    """The disk folder to stage from: `--disks` when given, else the default."""
    return pathlib.Path(args.disks) if args.disks else DISKS


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    disks = disks_of(args)
    slot = S.claim_slot(args.slot, "issue207 fasttravelrun.py")
    print(f"slot {slot.n} display {slot.display}", flush=True)
    sess = None
    target = None
    result = {"ok": False, "message": "did not reach a verdict"}
    shots: dict = {}
    marks: dict = {}
    started = time.monotonic()
    try:
        boot = S.stage_disks(slot, disks)
        # The save usually lives outside the disk directory -- the default
        # is the `npc-party-save` registry entry's file -- so it is staged by hand rather
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

        shoot(sess, out, "before", shots)
        target = ViceTarget(port=sess.mon_port)
        ft = A.FastTravel()
        marks["run_start"] = time.monotonic()
        try:
            # `ViceTarget` holds one persistent monitor connection and VICE
            # serves exactly one, so it is opened only for the one call
            # that needs it and closed straight after -- every `sess.mon()`
            # call above and below opens and closes its own.
            outcome = ft.run(target, area=A.area_by_id(args.to_area))
        finally:
            target.close()
            target = None
        marks["run_returned"] = time.monotonic()
        print(f"run(): ok={outcome.ok} message={outcome.message}", flush=True)
        two_hop = ft.pending is not None
        if not outcome.ok:
            # The console has already printed both of these, so the file a
            # reader parses afterwards should carry them too.
            result = {"ok": False, "message": outcome.message,
                      "before": before, "area_before": area_before,
                      "screenshots": shots}
            return 1

        # A two-hop trip (`WISH_EXPERIMENTAL_TWO_HOP_FAST_TRAVEL`) has walked
        # the party out through the area's one door and is waiting on the
        # poll to make its second hop, so this loop is that poll.
        hop = answer_and_wait(
            sess, args.to_area, deadline_s=args.answer_timeout,
            between=(lambda: second_hop(
                ft, lambda: ViceTarget(port=sess.mon_port),
                marks)) if two_hop else None,
            on_question=lambda: shoot(sess, out, "question", shots),
            marks=marks)
        second_hop_seconds = (elapsed(marks.get("through"),
                                      marks.get("landed")) if two_hop else None)
        total_seconds = elapsed(started, marks.get("landed"))
        timing = {"second_hop_seconds": second_hop_seconds,
                  "total_seconds": total_seconds,
                  "first_hop_seconds": elapsed(marks["run_start"],
                                               marks["run_returned"])}
        print(f"second_hop_seconds={second_hop_seconds} "
              f"total_seconds={total_seconds}", flush=True)
        if hop is not None and not hop.ok:
            result = {"ok": False, "message": hop.message,
                      "before": before, "area_before": area_before,
                      "screenshots": shots, **timing}
            return 1
        sess.settle(6)
        shoot(sess, out, "after_hop", shots)

        after = party(sess)
        area_after = area_of(sess)
        print(f"area after: {area_after}", flush=True)
        print("party after:",
              [r for r in after if r["name"] != "<empty>"], flush=True)

        ok, message = verdict(before, after, area_before, area_after,
                               args.from_area, args.to_area, args.member,
                               two_hop=two_hop,
                               second_hop_seconds=second_hop_seconds)
        result = {"ok": ok, "message": message, "before": before,
                  "after": after, "area_before": area_before,
                  "area_after": area_after, "screenshots": shots, **timing}
        print(("PASS: " if ok else "FAIL: ") + message, flush=True)
        if not ok:
            return 1

        # The walk is judged on its own: the trip's verdict above is already
        # final, and a party that cannot walk afterwards is a second finding.
        try:
            settled, why = settle_world(sess, out, shots)
            if settled:
                steps, sheet = walk_afterwards(sess)
                walk_ok, walk_message = walk_verdict(steps, sheet)
            else:
                steps, sheet, walk_ok, walk_message = [], False, False, why
        except Exception as e:                             # noqa: BLE001
            steps, sheet = [], False
            walk_ok, walk_message = False, f"the walk raised {e!r}"
        if "after_walk" not in shots:
            shoot(sess, out, "after_walk", shots)
        result.update({"walk_ok": walk_ok, "walk_message": walk_message,
                       "walk": steps, "sheet_opened": sheet,
                       "screenshots": shots})
        print(("PASS: walk: " if walk_ok else "FAIL: walk: ") + walk_message,
              flush=True)
        return 0 if walk_ok else 1
    finally:
        # A result that cannot be written must not stop the teardown below, or
        # the emulator slot leaks.
        try:
            (out / "result.json").write_text(json.dumps(result, indent=1))
        except Exception as e:                           # noqa: BLE001
            print(f"  result.json failed: {e}", flush=True)
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
    p.add_argument("--disks", default=DISKS,
                    help="the game disk directory ($POR_DISKS if unset)")
    p.add_argument("--save", default=str(S.npc_party_save()),
                    help="the save disk to load, staged in as SIDE0.D64")
    p.add_argument("--out", default=str(scratch.cache_dir("fasttravelrun", "live")))
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
    args = p.parse_args(argv)
    enable_debug_logging()
    if disks_of(args) is None:
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
