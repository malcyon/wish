#!/usr/bin/env python3
"""Prove a Curse or Silver Blades fight in the running machine, and drive one.

`#334 (The session driver cannot fight in Curse or Silver Blades, and says the
party is not in a fight while it is standing on the combat floor)`. Every
combat address for the two later C64 titles was derived from their own
binaries and is in `tools/latercombat.py`; this is what reads them off a
machine that is actually fighting, which is the difference between a routine
read right and a byte anybody has seen.

    tools/laterbattle.py --pool 2 \
        --save ~/wish-specimens/por-c64/WISH-SPEC-curse-h-engine-resave-walked.D64 \
        --out work/issue334/run1 --keys --melee 240

What one run does, in order, logging every reading to `battle.jsonl` as it is
taken because a run that dies half way still has to have said what it saw:

1. boot Curse, load the party through the game's own `LOAD SAVED GAME`, and
   walk to Tilverton's tavern at `6,10` over the area's own `GEO` passability;
2. `PUNCH BARKEEP`, which is the cheapest fight in the game's first area;
3. **the probe** -- the mode byte, the `$0600` parameter block, the camera,
   the position page, the roster page and the initiative table, raw, plus what
   `Session.battle()` makes of them. Taken once in the world as a control and
   again on the combat floor, so a page that reads plausibly in both proves
   nothing and is visibly proving nothing;
4. `--keys`, the movement question: enter `MOVE`, read `MOVE LEFT`, press one
   joystick key and read the acting combatant's square back out of the
   position table. Eight keys, one at a time, each with the square before and
   after it;
5. `--melee N`, which hands the fight to `Session.fight(tactic=melee_turn)`
   for N seconds and reports what it did.

Nothing is written outside `--out` and the pool slot's own directory. The
player's disks are opened read only, `POR_HEADLESS` keeps the window off the
desktop, and the slot is torn down whatever happens.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port as G  # noqa: E402
from goldbox.savegame import ROSTER_HP_CURRENT, ROSTER_STRIDE  # noqa: E402
from tools import cursethac0, gamedisks, latercombat  # noqa: E402
from tools import session as S  # noqa: E402

#: The tavern in Tilverton, and the script bar it puts up. `#131 (Lift
#: WISH_EXPERIMENTAL_DOS_IMPORT, which needs the import working for all three
#: C64 titles)` found it: ninety-five driven steps around the streets produced
#: no random encounter, and this square produces a fight on the first press.
TAVERN = (6, 10)
PUNCH = "PUNCH BARKEEP"

#: The eight joystick directions as VICE's keyset delivers them, which is what
#: `tools/session.py`'s `STEP_KEYS` already is: the numeric keypad is joystick
#: port 2, and all three titles read the stick at `LIBRARY`'s one
#: `LDA $DC00`. Ordered so a key that is likely to be blocked comes late.
KEYS = ("KP_8", "KP_2", "KP_6", "KP_4", "KP_9", "KP_7", "KP_3", "KP_1")


class Battle(cursethac0.Run):
    """`tools/cursethac0.py`'s driven run, asking a different question.

    The walk to the tavern is not this file's work: `Run.goto` plans it over
    the area's own `GEO`, bans an edge that goes nowhere and plans again, and
    that took `#368 (Does the C64 Curse engine read thac0_current in a fight,
    since the training hall overwrites it with the base and loses the strength
    bonus?)` four runs to get right. Reproducing it here would only produce a
    second one that is wrong in a different way, so this subclasses it and
    changes what gets read on the floor at the end.
    """

    def __init__(self, out: pathlib.Path, quiet: bool):
        super().__init__(out, quiet)
        # Its own log file, so a `cursethac0` run and one of these in the same
        # directory do not write over each other's answers.
        self.file.close()
        self.file = (out / "battle.jsonl").open("w")

    def reading(self, stage: str) -> dict:
        """`cursethac0`'s THAC0 reading is not this file's question."""
        return {}

    def in_combat(self) -> bool:
        """Ask the mode byte, not row 24.

        `cursethac0.Run.in_combat` looks for `DONE` or `GUARD` on row 24, and
        that is what everything driving these two titles has had to do. It has
        two failure modes and this file's third run hit both: the combat
        screen draws for several seconds with row 24 blank, and the message
        the brawl prints first is a bitmap, so `screen()` answers None and the
        row reads empty. `$7F11` is 2 the moment `LINKER` dispatches to
        `COMBAT`, whatever is on the screen -- which is the whole of what
        `#334` is about.
        """
        return bool(self.sess.in_combat())

    def press(self, key: str) -> bool:
        """One move key, judged by the live triple, in whichever title.

        `cursethac0.Run.press` hands the step to `CurseSession.walk_one`,
        which is right for Curse and is that class's own. Silver Blades has no
        such override, so the step falls to `Session.walk_one` -- which judges
        by the status line, and `docs/121-silver-blades.md` records that
        eleven of that title's twenty-two areas draw no square on it at all.

        So a title whose driver has its own `walk_one` keeps it, and one that
        does not gets this: enter the move sub-bar, send the key over XTEST
        the way `ssbwarp.walk_proof` measured it, fall back to the KERNAL
        buffer if nothing moved, and read `$C04B` back either way.
        """
        if type(self.sess).walk_one is not S.Session.walk_one:
            return bool(self.sess.walk_one(key))
        s = self.sess.screen()
        bar = "" if s is None else s.row(24).strip()
        if "I,J,K,M" not in bar:
            self.sess.select_bar("MOVE", timeout=10)
            time.sleep(0.8)
        before = self.triple()
        self.sess.kbd.key(key.lower(), 0.15, 0.30)
        time.sleep(1.2)
        if self.triple() == before:
            self.sess.press_kernal(ord(key.upper()))
            time.sleep(1.2)
        return self.triple()[:2] != before[:2]

    # -- the probe ---------------------------------------------------------

    def probe(self, stage: str) -> dict:
        """Every address `tools/latercombat.py` claims, raw, at one moment.

        **The world reading is the control and is taken first.** A page that
        holds plausible-looking combatants outside a fight is a page that
        proves nothing inside one, and `automap/combat.py` already records
        that trap for Pool of Radiance: outside combat `$8B00` is a graphics
        buffer, and an ungated reader stacks every combatant at (0,0).
        """
        where = latercombat.memory_for(self.sess.game)
        params = self.peek(latercombat.PARAMS, latercombat.PARAMS_LEN)
        shape = latercombat.shape_from_params(params)
        out: dict = {
            "stage": stage,
            "mode_at": f"${where.mode:04X}",
            "mode": self.peek(where.mode, 1)[0],
            "params": params.hex(" "),
            "camera": list(self.peek(latercombat.CAMERA, 2)),
            "shape": None if shape is None else {
                "map": f"${shape.map_base:04X}",
                "positions": f"${shape.positions:04X}",
                "count": shape.count,
                "width": shape.width, "height": shape.height,
                "stride": shape.stride},
        }
        if shape is not None:
            positions = self.peek(shape.positions, shape.count * 4)
            out["positions"] = positions[:64].hex(" ")
            out["on_map"] = [[i, positions[i * 4], positions[i * 4 + 1],
                              positions[i * 4 + 2]]
                             for i in range(shape.count)
                             if positions[i * 4] != 0xFF]
        roster = self.peek(where.roster, 64 * ROSTER_STRIDE)
        out["roster_first_bytes"] = roster[:0x40].hex(" ")
        out["roster_hp"] = [roster[i * ROSTER_STRIDE + ROSTER_HP_CURRENT]
                            for i in range(12)]
        out["roster_occupied"] = [i for i in range(64)
                                  if roster[i * ROSTER_STRIDE]]
        init = self.peek(where.initiative, 64)
        out["initiative"] = init.hex(" ")
        out["initiative_nonzero"] = [i for i in range(64) if init[i]]
        out["result_byte"] = self.peek(where.result, 1)[0]
        b = self.sess.battle()
        out["battle"] = None if b is None else {
            "count": len(b.combatants),
            "camera": list(b.camera),
            "party": [[c.index, c.x, c.y, c.name, c.hp, c.on_map]
                      for c in b.party],
            "enemies": [[c.index, c.x, c.y, c.name, c.hp, c.on_map]
                        for c in b.enemies][:12],
        }
        self.log("probe", **out)
        return out

    # -- the movement question --------------------------------------------

    def acting_index(self):
        """Which combatant the panel says is acting, by position-table index."""
        b = self.sess.battle()
        who = self.sess.acting(b)
        return None if who is None else who.index

    def key_sweep(self) -> None:
        """Press each joystick direction once and read the square back.

        **This is the question `#334` called its blocker**: `MOVE` puts up
        `MOVE/ATTACK, MOVE LEFT : 12` and neither XTEST arrows nor a KERNAL
        Return moved the counter across eight presses. Neither of those is
        how a Gold Box character moves in a fight -- Pool of Radiance's is the
        numeric keypad, which VICE maps to joystick port 2, and all three
        titles read the stick at the same single `LDA $DC00` in `LIBRARY`.

        So the answer is read out of the position table rather than off the
        counter: a step that lands moves the acting combatant's `x, y`, and a
        step into an occupied square is a blow that moves nobody. Both are
        logged, and a key that did neither is a key that did nothing.
        """
        # **Wait for a command bar first.** The first run to try this asked
        # who was acting on the frame the floor finished drawing, before the
        # round had begun: the panel named nobody, `Session.acting` answered
        # None and the sweep pressed nothing at all
        # (`work/issue334/run5`, `key-sweep {'acting': None}`).
        if self.sess.await_bar((S.BAR_COMMAND,), timeout=60, interval=2.0) \
                is None:
            self.log("key-sweep", reached_a_command_bar=False,
                     row24=self.row24())
            return
        index = self.acting_index()
        self.log("key-sweep", acting=index, row24=self.row24())
        if index is None:
            return
        if not self.sess.combat_bar("MOVE", timeout=15):
            self.log("key-sweep", entered_move=False, row24=self.row24())
            return
        bar = self.sess.await_bar((S.BAR_MOVE,), timeout=8)
        self.log("key-sweep", entered_move=True,
                 row24=self.row24(),
                 moves_left=None if bar is None else bar.moves_left)
        for key in KEYS:
            b = self.sess.battle()
            me = None if b is None else next(
                (c for c in b.combatants if c.index == index), None)
            before = None if me is None else (me.x, me.y)
            was = self.sess.combat_state()
            self.sess.kbd.key(key, 0.15, 0.30)
            time.sleep(1.2)
            b = self.sess.battle()
            me = None if b is None else next(
                (c for c in b.combatants if c.index == index), None)
            after = None if me is None else (me.x, me.y)
            now = self.sess.combat_state()
            self.log("key", key=key, before=before, after=after,
                     moved=before is not None and before != after,
                     moves_left_before=was.moves_left,
                     moves_left_after=now.moves_left,
                     bar=now.kind, row24=now.text)
            if now.kind != S.BAR_MOVE:
                self.log("key-sweep", left_move_bar=now.kind, row24=now.text)
                return


def curse_fight(run: Battle, args, disks: str) -> int:
    """Boot, load, walk to the tavern and punch the barkeep."""
    from tools import curseload, curserun  # noqa: PLC0415

    area, geo = cursethac0.area_geo(args.save, disks)
    boot = curserun.stage(run.slot, disks, args.save)
    sess = curserun.CurseSession(boot, slot=run.slot)
    run.sess = sess
    sess.save_disk = str(pathlib.Path(run.slot.dir) / "SIDE0.D64")
    run.log("staged", area=str(area), map_read=geo is not None)
    if not sess.boot():
        run.log("boot", reached_menu=False)
        return 1
    outcome = curseload.load_saved_game(
        sess, note=lambda **kw: run.log("load", **kw),
        shot=lambda tag: run.dump(tag))
    run.log("loaded", outcome=outcome)
    if outcome != "loaded":
        return 1
    # `begin_adventuring` waits 240 seconds and then says only False, which on
    # the first run of this file was the whole of what came back: the party
    # menu had loaded six characters and something between it and the world
    # bar was never seen.  So the wait is spelled out here, saying what row 24
    # held and whether the screen was readable at all, every `--look` seconds.
    picked = sess.select_row("BEGIN ADVENTURING", timeout=40.0)
    run.log("begin", pressed=picked, row24=run.row24())
    deadline = time.time() + args.world
    entered = False
    patched = False
    while time.time() < deadline:
        s = sess.screen()
        if s is not None and s.contains("ENCAMP"):
            entered = True
            break
        run.log("waiting-for-world", readable=s is not None,
                row24="" if s is None else s.row(24).strip(),
                row10="" if s is None else s.row(10).strip(),
                attached=pathlib.Path(sess.attached).name)
        # **`INSERT SIDE # 2, AND PRESS ANY KEY.` is a loop this harness
        # cannot answer**, and it is what stopped this file's first two runs
        # dead: `curserun`'s `handle_prompt` attaches the side and then sends
        # an XTEST space, which Curse does not read, so the party menu had
        # six characters on it and the world never arrived -- twenty-three
        # readings of the same prompt in 200 seconds
        # (`work/issue334/run2`). `CurseSession.patch_disk_prompt` NOPs the
        # two `BNE`s that make the loop, and `#301` measured that patching
        # while the prompt is on the screen is what works.
        if s is not None and "INSERT SIDE" in s.text() and not patched:
            patched = sess.patch_disk_prompt()
            run.log("patch-disk-prompt", applied=patched)
        sess.handle_prompt(s)
        # A continue prompt or a script bar can stand between the party menu
        # and the world, and neither clears itself.
        state = sess.combat_state(s)
        if state.kind == S.BAR_PRESS:
            sess.press_kernal(0x0D)
        sess.settle(args.look)
    run.log("world", entered=entered, row24=run.row24())
    run.dump("world")
    if not entered:
        return 1
    run.probe("in-the-world")          # the control, before any fight exists
    arrived = run.goto(TAVERN, args.steps, geo=geo)
    run.log("goto", target=list(TAVERN), arrived=arrived,
            triple=list(run.triple()), row24=run.row24())
    run.dump("arrived")
    if not run.in_combat():
        pressed = sess.press_bar(PUNCH, timeout=20.0)
        sess.settle(3.0)
        run.log("script", word=PUNCH, pressed=pressed, row24=run.row24())
    return 0


def ssb_fight(run: Battle, args, disks: str) -> int:
    """Boot Silver Blades, load, reach the world, and walk until a fight.

    **There is no `PUNCH BARKEEP` here.** Curse's first area has a tavern that
    starts a brawl on one keypress; nobody has found the equivalent in Silver
    Blades, so this walks and waits for a wandering monster, which is a gamble
    rather than a route. The step budget is the whole of the method.

    The one thing it does not gamble on is *noticing*: every step asks
    `$7F11`, so a fight that starts while the screen is still a bitmap is seen
    on the next step rather than walked out of.
    """
    from tools import ssbwarp  # noqa: PLC0415

    # The guard that used to live here -- clearing whatever the last run left
    # in SIDE0 before `ssbwarp.stage` -- came out once `#469 (A second Silver
    # Blades run in the same pool slot cannot start, because the staged save
    # disk is left read-only)` closed: `ssbwarp.stage` now unlinks and
    # restores the write bit itself (`tools.session.stage_writable`, `#472`),
    # so a caller no longer has to.
    boot = ssbwarp.stage(run.slot, disks, args.save)
    sess = ssbwarp.SSBSession(boot, slot=run.slot)
    run.sess = sess
    sess.save_disk = str(pathlib.Path(run.slot.dir) / "SIDE0.D64")
    if not sess.boot():
        run.log("boot", reached_menu=False)
        return 1
    run.log("boot", reached_menu=True)
    if not ssbwarp.load_party(sess):
        run.log("loaded", outcome="no")
        return 1
    run.log("loaded", outcome="loaded")
    where = ssbwarp.Addresses(G.SECRET_OF_THE_SILVER_BLADES, disks)
    entered = ssbwarp.enter_world(sess, where, timeout=args.world,
                                  stop_at_idle=False)
    run.log("world", entered=entered, row24=run.row24())
    run.dump("world")
    if not entered:
        return 1
    run.probe("in-the-world")
    if args.goto:
        # **A pattern walker cannot leave the starting pocket.** 400 steps of
        # one stood on sixteen distinct squares of `GEO10` and never met
        # anything (`work/issue334/ssb3`), which is the same failure
        # `#368 (Does the C64 Curse engine read thac0_current in a fight,
        # since the training hall overwrites it with the base and loses the
        # strength bonus?)` found in Tilverton. The area's own map is what
        # gets a party out of it.
        area, geo = cursethac0.area_geo(args.save, disks)
        # Several squares, walked to in turn and then round again, because
        # one trip is not enough steps: `docs/121-silver-blades.md` records a
        # wandering encounter arriving 228 driven steps out of New Verdigris,
        # and the furthest square in `GEO10` is 29 steps from where this
        # party stands.
        stops = [tuple(int(n) for n in stop.split(","))
                 for stop in args.goto.split("/")]
        spent = 0
        while spent < args.steps and not run.in_combat():
            for stop in stops:
                budget = min(args.laps, args.steps - spent)
                if budget <= 0 or run.in_combat():
                    break
                arrived = run.goto(stop, budget, geo=geo)
                spent += budget
                run.log("goto", target=list(stop), arrived=arrived,
                        area=str(area), spent=spent,
                        triple=list(run.triple()), row24=run.row24())
        if run.in_combat():
            run.log("wandered-into-a-fight", step=spent)
            return 0
    # **A blocked step is answered with a turn, not with the next key.** The
    # first Silver Blades run spent 78 of its 90 steps pressing `I` at the
    # same wall: the party stood on twelve distinct squares and the walk went
    # nowhere (`work/issue334/ssb1`). `docs/121-silver-blades.md` records that
    # a wandering encounter took **228 driven steps** out of New Verdigris, so
    # a walker that wastes five of every six is not going to reach one.
    keys = list(args.pattern)
    i = 0
    turn_next = False
    for n in range(args.steps):
        if run.in_combat():
            run.log("wandered-into-a-fight", step=n)
            return 0
        s = sess.screen()
        bar = "" if s is None else s.row(24).strip()
        if "I,J,K,M" not in bar:
            # A script bar or a message eats the move keys until it is
            # answered, the same way Curse's does.
            for word in ("QUIT", "LEAVE", "NO", "EXIT"):
                if word in bar.split():
                    sess.select_bar(word, timeout=8)
                    break
            else:
                if "PRESS" in bar or s is None:
                    sess.press_kernal(0x0D)
            sess.select_bar("MOVE", timeout=10)
            time.sleep(0.8)
        before = run.triple()
        key = "K" if turn_next else keys[i % len(keys)]
        turn_next = False
        # `ssbwarp.walk_proof` sends these over XTEST and measured them that
        # way over eight sessions, which is the one place Silver Blades and
        # Curse differ about keys. The KERNAL copy is the fallback rather than
        # the first try, so a title that reads both does not get two.
        sess.kbd.key(key.lower(), 0.15, 0.30)
        time.sleep(1.2)
        after = run.triple()
        if after == before:
            sess.press_kernal(ord(key))
            time.sleep(1.2)
            after = run.triple()
        if after[:2] == before[:2]:
            i += 1
            turn_next = key != "K"          # walled in: turn, then try again
        run.log("step", n=n, key=key, before=list(before), after=list(after),
                mode=sess.mode(), row24=run.row24())
    run.log("no-fight", steps=args.steps)
    return 2


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--title", choices=("curse", "ssb"), default="curse",
                   help="which later title to drive")
    p.add_argument("--pattern", default="IIIKIIIJ",
                   help="the order the move keys are tried in (Silver Blades "
                        "only: Curse has a route to the tavern)")
    p.add_argument("--save", required=True, help="the save disk to boot")
    p.add_argument("--disks", default=None,
                   help="that title's six sides")
    p.add_argument("--pool", dest="slot", type=int, default=None,
                   help="claim this instance-pool slot")
    p.add_argument("--out", default="work/issue334/run", help="run directory")
    p.add_argument("--steps", type=int, default=60, help="walk budget")
    p.add_argument("--goto", default="",
                   help="Silver Blades only: walk to this square over "
                        "the area's own GEO before falling back to the "
                        "pattern; several, separated by /, are walked "
                        "in turn and then round again")
    p.add_argument("--laps", type=int, default=45,
                   help="steps allowed for one leg of a --goto tour")
    p.add_argument("--wait", type=int, default=15,
                   help="settles to give the combat screen to draw")
    p.add_argument("--world", type=float, default=240.0,
                   help="seconds to give BEGIN ADVENTURING to reach the world")
    p.add_argument("--look", type=float, default=8.0,
                   help="seconds between readings while waiting for the world")
    p.add_argument("--keys", action="store_true",
                   help="press each joystick direction once and read the "
                        "acting combatant's square back")
    p.add_argument("--quick", type=int, default=0,
                   help="resolve this many turns with the game's own QUICK")
    p.add_argument("--melee", type=float, default=0.0,
                   help="seconds to give Session.fight(melee_turn)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    game = (G.CURSE_OF_THE_AZURE_BONDS if args.title == "curse"
            else G.SECRET_OF_THE_SILVER_BLADES)
    disks = args.disks or str(gamedisks.find(game.key) or "")
    if not disks:
        raise SystemExit(f"no {game.title} disks; pass --disks")
    out = pathlib.Path(args.out)
    run = Battle(out, args.quiet)
    run.slot = S.claim_slot(args.slot, "laterbattle/334")
    run.log("slot", n=run.slot.n, display=run.slot.display,
            dir=str(run.slot.dir), save=args.save, disks=disks,
            title=game.title)
    rc = 1
    try:
        rc = (curse_fight if args.title == "curse" else ssb_fight)(
            run, args, disks)
        if rc:
            return rc
        sess = run.sess
        for n in range(args.wait):
            if run.in_combat():
                break
            s = sess.screen()
            state = sess.combat_state(s)
            run.log("waiting-for-combat", look=n, mode=sess.mode(),
                    readable=s is not None, bar=state.kind,
                    row24=state.text.strip())
            # `YOU GET INTO A BRAWL.` is drawn over a picture and waits on a
            # keypress, so a run that only settles never sees the floor.
            if state.kind == S.BAR_PRESS or s is None:
                sess.press_kernal(0x0D)
            sess.settle(4.0)
        run.dump("combat-floor")
        run.log("combat", on_the_floor=run.in_combat(), mode=sess.mode(),
                row24=run.row24())
        if not run.in_combat():
            rc = 2
            return rc
        run.probe("combat-floor")
        if args.keys:
            run.key_sweep()
            run.probe("after-keys")
        if args.quick:
            run.quickfight(args.quick)
            run.probe("after-quick")
        if args.melee:
            result = sess.fight(budget=args.melee, tactic=S.Session.melee_turn)
            run.log("melee", outcome=result.outcome, turns=result.turns,
                    blows=result.blows, seconds=round(result.seconds, 1),
                    evidence=result.evidence, bars=result.bars[-12:],
                    lines=result.lines[-20:])
            run.dump("after-melee")
            run.probe("after-melee")
        rc = 0
    finally:
        run.log("done", rc=rc)
        if run.sess is not None:
            run.sess.terminate()
        if getattr(run, "slot", None) is not None:
            run.slot.teardown()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
