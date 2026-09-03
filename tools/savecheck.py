#!/usr/bin/env python3
"""Boot a save disk in VICE and read the party off the game's own screens.

The acceptance check behind #119: a `.d64` Wish built from nothing is booted,
the game's own `LOAD SAVED GAME` is asked for it, and what comes back is read
off the screen rather than out of the file.  Bytes matching is necessary and
not sufficient -- an AC of 9 displayed as 51, a dropped combat tail and a
garbage weapon line are three faults this project has shipped that passed
every byte-level check that existed.

    tools/savecheck.py --disk work/NEWJ.D64 --slot 1 --walk II

What it reads, in order:

* whether the game's `LOAD SAVED GAME` picker takes the disk at all -- the
  `#109`-shaped failure, where a file is written correctly and the game's own
  load screen does not list it;
* the status line: facing, clock and square, which is the DOS save's own;
* the party panel: every name the game lists, with its armour class and hit
  points, and **how many** rows it lists, which is what catches a stranger
  left in slot 7;
* each character's `VIEW` sheet, verbatim;
* the combat floor, when `--fight` is given, and the screen codes each party
  figure is drawn from -- which is the only place a converted combat icon is
  ever seen.

`tools/dosdisk.py --sheet` prints the DOS side of the same comparison.

Nothing is written to the player's disks: `Session.attach` refuses a path
outside the slot's own directory, and the sides and the save are copied there
first.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import session as S  # noqa: E402

from automap import combat as C  # noqa: E402
from automap.paths import find_disks  # noqa: E402

#: Where the player keeps the C64 game disks.  Read only.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The world screen's party panel is the right-hand columns of the top rows,
#: and it is **not** the window `Session.acting` reads: that one is combat's,
#: at column 22, and slicing the world panel there cuts five letters off every
#: name -- `THRENDER GRONE` arrives as `DER GRONE`.  Measured on the arrival
#: screen of a converted Slums save: the name field starts at column 17 and
#: the `AC` and `HP` columns follow it.
#:
#: Reading it by column rather than splitting on whitespace matters either
#: way: a scratch reader that split on spaces counted three of six party
#: members during #118 and the panel really showed all six.
PANEL_LEFT = 17
PANEL_ROWS = range(0, 12)

#: The header the panel's rows hang under.  Counting *rows with a name under
#: it* is what says how many characters the game is listing, which is the
#: number a converted save has to get right (#104) -- counting non-blank rows
#: instead counts the panel's own frame and answers eight every time.
PANEL_HEADER = "AC"

#: Where a fight draws the party.  Each combatant is a 3x3 block of
#: `CHARPIC00` screen codes, and screen code 0 is a real glyph rather than a
#: space -- which is why a zeroed icon draws as black hooks and why looking at
#: this is the only check the composed icon has ever had in the running game
#: (#57, #118).
FLOOR_ROWS = range(0, 20)
FLOOR_COLS = range(0, 22)


#: The resident area, `$6E1B & $7F` -- `docs/118-debug-mode.md`, where it is
#: what `NEWECL` compares against so it can skip a same-area transition.
#: Reading it is how an area change is seen rather than inferred from a
#: status line that shows the same `x,y` on both sides of a door.
AREA_AT = 0x6E1B


def area(sess) -> int:
    with sess.mon(5) as m:
        return m.read(AREA_AT, 1)[0] & 0x7F


def answer_bars(sess, log: Log, answer: str = "NO", tries: int = 60,
                seconds: float | None = None) -> str:
    """Press through whatever the game puts up until the world bar is back.

    An area change reached by *walking* is not one keypress: stepping into
    the training hall prints a room description, waits on `PRESS <RETURN> OR
    BUTTON TO CONTINUE`, loads for about twenty-five seconds and then asks
    two `YES NO` questions (`docs/70-driving-the-game.md`).  A driver that
    only sent moves would sit in front of the first of those for ever, and
    the step would be reported as a wall.

    `answer` is what to give a `YES NO`; `NO` declines training, which is the
    answer that leaves the party standing in the new area with nothing else
    changed.
    """
    deadline = None if seconds is None else time.time() + seconds
    while tries > 0 if deadline is None else time.time() < deadline:
        tries -= 1
        s = sess.screen()
        if s is None:
            time.sleep(1.0)
            continue
        if sess.handle_prompt(s):
            continue
        row = s.row(24)
        if "MOVE" in row and "ENCAMP" in row:
            return "world"
        if "PRESS" in row:
            sess.kbd.key("Return")
        elif "YES" in row and "NO" in row:
            log.say(f"    answering {answer} to |{row.strip()}|")
            if not sess.select_bar(answer, timeout=8):
                sess.kbd.key("Return")
        time.sleep(1.2)
    return "stuck"


def icon_bytes(disks: pathlib.Path) -> bytes:
    """The 36 bytes of the icon a conversion writes, off a game disk.

    `tools/dosdisk.py` composes the same icon when it builds the save, so
    this is what the floor is compared against.  The bytes are never stored
    here: they are read off the player's own disk both times.
    """
    import dosdisk

    return dosdisk.game_files(disks)[0]


class Log:
    """Everything the run saw, to the terminal and to a `.jsonl` beside it."""

    def __init__(self, out: pathlib.Path):
        out.parent.mkdir(parents=True, exist_ok=True)
        self.dir = out.parent
        self.file = open(out, "w")

    def emit(self, kind: str, **kw) -> None:
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        self.file.write(json.dumps(kw, default=str) + "\n")
        self.file.flush()

    def say(self, *a) -> None:
        print(*a, flush=True)

    def close(self) -> None:
        self.file.close()


def panel(sess) -> tuple[list[str], list[str]]:
    """The party panel: every row of it, and the ones that name a character.

    The second list is the answer #104 wants -- how many characters the game
    is listing -- and it is taken from the rows under the `AC` header that
    carry a name, because the panel's frame is non-blank on every row and
    counting non-blank rows answers eight whatever is in the save.
    """
    s = sess.screen()
    if s is None:
        return [], []
    rows = [s.row(r)[PANEL_LEFT:].rstrip() for r in PANEL_ROWS]
    header = next((i for i, r in enumerate(rows) if PANEL_HEADER in r), None)
    if header is None:
        return rows, []
    named = []
    for row in rows[header + 1:]:
        # The name occupies the columns left of where `AC` starts; a row with
        # nothing there is the panel's own border rather than a character.
        who = row[:rows[header].index(PANEL_HEADER)].strip()
        if who:
            named.append(row.strip())
    return rows, named


def sheets(sess, count: int, log: Log, tag: str) -> list[list[str]]:
    """Every character's `VIEW` screen, verbatim, then back to the world bar.

    **`VIEW` is not a list.**  Asking for it on the world bar puts the *first*
    character's sheet straight up, with a bar carrying `NEXT`; there is no
    menu of names to walk a highlight down, and a driver that looked for one
    reported `THRENDER GRONE never appeared in the VIEW list` against a screen
    that was already showing his sheet.  So the party is stepped through with
    `NEXT` and the name is read off the sheet rather than chosen.
    """
    out: list[list[str]] = []
    if not sess.select_bar("VIEW", timeout=20):
        log.say("  could not open VIEW")
        return out
    for n in range(count):
        time.sleep(1.2)
        s = sess.screen()
        lines = [] if s is None else \
            [line.rstrip() for line in s.rows() if line.strip()]
        out.append(lines)
        sess.kbd.screenshot(str(log.dir / f"{tag}-sheet-{n}.png"))
        if n + 1 < count and not sess.select_bar("NEXT", timeout=12):
            log.say(f"  no NEXT after sheet {n + 1}; stopping there")
            break
    # `EXIT` off the sheet.  Ask for it by name rather than pressing Return at
    # whatever happens to be highlighted; a stale row 24 is not evidence.
    for _ in range(3):
        if sess.select_bar("EXIT", timeout=8):
            break
        sess.leave_move(2)
    time.sleep(1.0)
    return out


def floor(sess) -> list[str]:
    """The combat map as screen codes, one row of hex per line.

    Read as codes and not as text because the party figures are `CHARPIC00`
    glyphs and have no letters in them; a zeroed icon is eighteen `00`s in a
    3x3 block and a composed one is not.
    """
    s = sess.screen()
    if s is None:
        return []
    return [bytes(s.codes[r * 40 + c] for c in FLOOR_COLS).hex()
            for r in FLOOR_ROWS]


def combatants(sess, s=None) -> list[tuple[int, int, bytes]]:
    """Every 3x3 block of nine **consecutive** screen codes on the screen.

    That is what a figure on the combat floor is, and it is not the icon's
    own codes.  Measured on a converted Slums save in a fight: the six party
    members were drawn from codes `$5E`-`$93`, six runs of nine in order, and
    the five orcs from one run of nine reused -- while every one of the six
    icons in the save was the same 18 codes `20 A0 20 86 87 88 06 07 08`.  So
    the engine copies each icon's glyph *bitmaps* into a combat character set
    and hands out sequential codes; searching the screen for the icon's own
    codes finds nothing, which is what a first pass reported.

    Returns `(row, column, codes)`.
    """
    if s is None:
        s = sess.screen()
    if s is None:
        return []
    out = []
    for r in range(23):
        for c in range(38):
            at = r * 40 + c
            block = bytes(s.codes[at + dr * 40 + dc]
                          for dr in range(3) for dc in range(3))
            if block[0] > 0x20 and list(block) == list(
                    range(block[0], block[0] + 9)):
                out.append((r, c, block))
    return out


def roll_call(sess) -> dict:
    """Who the engine has in the fight, out of its own combatant table.

    The floor scan can only ever count what is **drawn**, and the game draws a
    7x7 window (`automap.combat.VIEW`, `COM.PREP $08C6 LDA #$07`) onto a map
    that has been 56x26 in every fight read here.  So "four figures for a party
    of six" is not by itself a fault: two members standing more than six
    squares from the camera's corner are off the drawn portion and there is
    nothing wrong with them.

    `read_battle` settles it without an inference.  The position table says
    where all `count` combatants are, `$FF` says a combatant has left the map
    altogether, and `$037E` is the window's own top-left square -- so a member
    that is absent from the floor can be told apart three ways: outside the
    window, off the map, or not in the table at all.  Only the last two are
    defects, and only the last would be the conversion's (`#185`).

    Returns the counts and a row per party member; `{}` if there is no
    readable fight.
    """
    battle = sess.battle()
    if battle is None:
        return {}
    x0, y0 = battle.camera

    def inside(c) -> bool:
        return (c.on_map and x0 <= c.x < x0 + C.VIEW
                and y0 <= c.y < y0 + C.VIEW)

    party = [{"index": c.index, "name": c.name.strip(), "x": c.x, "y": c.y,
              "on_map": c.on_map, "hp": c.hp, "alive": c.alive,
              "in_window": inside(c)}
             for c in battle.party]
    return {
        "map": [battle.shape.width, battle.shape.height],
        "camera": [x0, y0],
        "view": C.VIEW,
        "count": battle.shape.count,
        "party": party,
        "party_size": len(party),
        "party_on_map": sum(1 for c in party if c["on_map"]),
        "party_in_window": sum(1 for c in party if c["in_window"]),
        "enemies": len(battle.enemies),
        "enemies_in_window": sum(1 for c in battle.enemies if inside(c)),
    }


def undrawn(roll: dict, blocks: int) -> list[str]:
    """The complaint a floor scan on its own cannot make.

    `--icon` counted the figures it found and said nothing about how many it
    should have found, so a converted party of six that draws four was reported
    as a pass (`#185`).  What it is compared against is **not** the party size
    -- that would fail on every fight where somebody is legitimately outside
    the 7x7 window -- but the number the position table says are inside it.

    **Only a shortfall is reported.**  The screen and the position table are
    two reads a few milliseconds apart, and the camera moves between one
    combatant's turn and the next, so the screen can still be carrying the
    figures from before a scroll: on the engine-written Sokol Keep control
    (`work/p185/SOKOLENG.log`) 27 of 30 turns matched exactly and the other
    three drew **two more** than the table put in the window, never fewer.  An
    extra figure is that frame and is not a fault anybody could have; a missing
    one is the thing being looked for.
    """
    if not roll:
        return ["The fight's combatant table could not be read, so the "
                "figures on the floor were not checked against it"]
    out = []
    want = roll["party_in_window"] + roll["enemies_in_window"]
    if blocks < want:
        out.append(f"The floor drew only {blocks} figures where the combatant "
                   f"table puts {want} inside the {roll['view']}x{roll['view']}"
                   f" window ({roll['party_in_window']} of the party, "
                   f"{roll['enemies_in_window']} enemies)")
    gone = [c for c in roll["party"] if not c["on_map"]]
    if gone:
        out.append("Off the map altogether: "
                   + ", ".join(c["name"] or f"#{c['index']}" for c in gone))
    return out


def icon_evidence(sess, icon: bytes) -> dict:
    """What the running game drew, against the 36 bytes the save carries.

    Two independent checks, because the codes on screen are the engine's and
    not ours:

    * **the colours.**  An icon's second eighteen bytes are copied straight to
      colour RAM, cell for cell, so a figure's 3x3 colour block must equal one
      of the icon's two poses' colours.  Nothing renumbers those.
    * **the glyphs.**  The first eighteen are `CHARPIC00` codes, and two of
      them are ordinary characters whose bitmaps are known without finding
      `CHARPIC00` at all: `$20` is the space, eight zero bytes, and `$A0` is
      the reversed space, eight `$FF`s.  The composed icon's pose 1 is
      `20 A0 20 ...`, so the top row of every party figure must be blank,
      solid, blank in the combat character set.

    Together they say the bytes the conversion wrote are the bytes the engine
    drew from -- which is the last of #118's 5405, and the one that had only
    a file-level measurement behind it.
    """
    blocks = combatants(sess)
    if not blocks:
        return {"blocks": 0}
    with sess.mon(5) as m:
        d018 = m.read(0xD018, 1)[0]
        dd00 = m.read(0xDD00, 1)[0]
        bank = (~dd00 & 3) * 0x4000
        chars = bank + ((d018 >> 1) & 7) * 0x800
        colours = bytes(c & 0x0F for c in m.read(0xD800, 1000))
        glyphs = {}
        for _r, _c, block in blocks:
            for code in block:
                if code not in glyphs:
                    glyphs[code] = m.read(chars + code * 8, 8)
    poses = [icon[18:27], icon[27:36]]
    out = {"blocks": len(blocks), "charset": chars, "matched": [],
           "top_row": [], "distinct_figures": []}
    for r, c, block in blocks:
        here = bytes(colours[(r + dr) * 40 + c + dc]
                     for dr in range(3) for dc in range(3))
        out["matched"].append((r, c, block[0],
                               [bytes(p) == here for p in poses], here.hex()))
        # `20 A0 20` is the composed icon's own top row: blank, solid, blank.
        out["top_row"].append((r, c, [glyphs[code].hex() for code in block[:3]]))
        shape = b"".join(glyphs[code] for code in block)
        if shape not in out["distinct_figures"]:
            out["distinct_figures"].append(shape)
    out["distinct_figures"] = len(out["distinct_figures"])
    return out


def watch_turns(seen: list) -> object:
    """A fight tactic that takes a roll call every time the party is asked.

    The floor is read once, before the first blow, and one reading cannot show
    the thing `#185` turns on: that the seven-square window **moves**, so which
    party members are drawn changes from turn to turn while the party itself
    does not.  Watching every command bar is what turns "they were probably
    off the window" into a measurement -- a turn where the table puts five of
    six inside the window and the floor draws five party figures says it
    outright.

    Passes the turn, which is `Session.fight`'s own default: this is here to
    look, not to play.
    """
    def tactic(sess, state):
        s = sess.screen()
        roll = roll_call(sess)
        if roll:
            roll["blocks"] = len(combatants(sess, s))
            seen.append(roll)
        return sess.combat_turn()
    return tactic


def run(args, log: Log) -> int:
    slot = S.claim_slot(args.slot, f"savecheck/{pathlib.Path(args.disk).name}")
    log.say(f"slot {slot.n} display {slot.display}")
    sess = None
    rc = 0
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks))
        shutil.copy(args.disk, pathlib.Path(slot.dir) / "SIDE0.D64")
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")

        # The #109 guard.  `load_save` reaches `BEGIN ADVENTURING` only when
        # the game itself accepted the disk as a saved game, so its answer is
        # the one bytes cannot give.
        listed = sess.load_save()
        log.emit("picker", listed=listed)
        log.say(f"the game's LOAD SAVED GAME accepted the disk: {listed}")
        if not listed:
            raise RuntimeError("the game did not load the save")
        # Not `Session.begin_adventuring`, which waits 240 seconds for the
        # world bar.  An arrival that plays an animation takes longer than
        # that -- Sokol Keep's boat -- and the difference between "the game is
        # still loading" and "the conversion wedged it" is what this whole run
        # is for, so the wait is the caller's and a failure is photographed
        # rather than reported as a boolean.
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        # **An arrival can have a scene in front of it**, and `Session`'s own
        # `begin_adventuring` waits for the world bar without answering one.
        # Loading a Sokol Keep party draws the boat, prints `THE BOAT
        # DISEMBARKS YOU AT SOKAL KEEP.` and waits on `(PRESS <RETURN> OR
        # BUTTON TO CONTINUE)` -- so a driver that only waits reports a
        # perfectly healthy save as `begin_adventuring failed`, which is what
        # the first run of this said.
        arrived = answer_bars(sess, log, args.answer, seconds=args.arrive)
        log.emit("arrival", outcome=arrived)
        if arrived != "world":
            raise RuntimeError(
                f"no world bar {args.arrive}s after BEGIN ADVENTURING")
        sess.settle(3)

        where = sess.status()
        rows, named = panel(sess)
        log.emit("arrived", status=where, panel=rows, named=named,
                 outdoors=None if where is None else where.outdoors)
        # `Status.where()` rather than `facing=<number>`.  On the travel grid
        # there is no facing at all, and this printed `facing=2` -- south --
        # for every outdoor party on every square, because the old pattern
        # took the final `S` of `OUTDOORS` for a reading (`#189`).
        if where is None:
            log.say("No status line was on the screen")
        else:
            log.say(f"Status line: {where.where()}")
        log.say(f"the party panel lists {len(named)} characters:")
        for r in rows:
            log.say(f"    |{r}|")
        sess.kbd.screenshot(str(log.dir / f"{args.tag}-arrived.png"))

        if args.view:
            for n, lines in enumerate(sheets(sess, args.view, log, args.tag)):
                log.emit("sheet", n=n, lines=lines)
                log.say(f"  -- sheet {n + 1} --")
                for line in lines:
                    log.say(f"    {line}")

        if args.resave:
            # The control `#185` wanted and nobody had: the **engine's** own
            # save of the party now standing here.  `ENCAMP > SAVE` writes over
            # the slot's copy of the disk -- never the player's -- so what
            # comes out is the same party in the same place with every byte
            # written by the game, which is the one thing a converted save
            # cannot be compared against any other way.
            ok = sess.save_game()
            log.emit("resave", ok=ok, to=args.resave)
            log.say(f"The game's own ENCAMP > SAVE wrote the party back: {ok}")
            if ok:
                shutil.copy(sess.save_disk, args.resave)
                log.say(f"The engine-written disk is at {args.resave}")
            sess.settle(3)

        was = area(sess)
        log.say(f"the resident area is {was}")
        for move in args.walk:
            moved = sess.walk_one(move)
            sess.handle_prompt()
            if args.route:
                # A walked area change is several screens, not one keypress.
                log.say(f"  after {move}: {answer_bars(sess, log, args.answer)}")
            now = area(sess)
            # Read once and reported three times.  It used to be read three
            # times, which is up to 24 screen reads for one line of log -- and
            # outdoors the three could disagree, because the status line lags
            # a step out there.
            at = sess.status()
            # The square out of memory beside it, because that is what proves
            # an outdoor step: `$49C3`/`$49C4` move on the press and the
            # status line catches up afterwards (`#189`).
            here = sess.square()
            log.emit("walk", move=move, moved=moved, status=at, area=now,
                     square=here)
            log.say(f"Walk {move}: moved={moved} "
                    f"status={'none' if at is None else at.where()} "
                    f"square={'?' if here is None else f'{here[0]},{here[1]}'} "
                    f"area={now}")
            if now != was:
                log.emit("area_change", before=was, after=now, status=at)
                log.say(f"** the area changed, {was} -> {now} **")
                sess.kbd.screenshot(str(log.dir / f"{args.tag}-area-{now}.png"))
                was = now
            if sess.in_combat():
                log.say("  a random encounter started")
                break

        if args.fight:
            steps = 0
            while not sess.in_combat() and steps < args.steps:
                sess.walk_one(args.fight_move)
                sess.handle_prompt()
                steps += 1
            if sess.in_combat():
                sess.settle(2)
                codes = floor(sess)
                log.emit("floor", rows=codes)
                log.say("the combat floor, as screen codes:")
                for line in codes:
                    log.say(f"    {line}")
                sess.kbd.screenshot(str(log.dir / f"{args.tag}-combat.png"))
                roll = roll_call(sess)
                log.emit("roll_call", **roll)
                if not roll:
                    log.say("The fight's combatant table could not be read")
                else:
                    log.say(f"The battlefield is {roll['map'][0]}x"
                            f"{roll['map'][1]} and the game draws "
                            f"{roll['view']}x{roll['view']} of it from "
                            f"{roll['camera'][0]},{roll['camera'][1]}; the "
                            f"table holds {roll['count']} combatants, "
                            f"{roll['party_size']} of them the party")
                    for c in roll["party"]:
                        where = (f"{c['x']},{c['y']}" if c["on_map"]
                                 else "off the map")
                        log.say(f"    {c['index']}. {c['name'] or '?'} "
                                f"at {where}, {c['hp']} hp, "
                                f"{'in' if c['in_window'] else 'outside'} "
                                f"the drawn window")
                if args.icon:
                    icon = icon_bytes(pathlib.Path(args.disks))
                    found = icon_evidence(sess, icon)
                    log.emit("icons", **found)
                    log.say(f"figures on the floor: {found.get('blocks')}, "
                            f"distinct: {found.get('distinct_figures')}")
                    for row in found.get("matched", []):
                        log.say(f"    colours at {row[0]},{row[1]} "
                                f"code ${row[2]:02X}: {row[4]} "
                                f"pose match {row[3]}")
                    for row in found.get("top_row", []):
                        log.say(f"    glyphs at {row[0]},{row[1]}: {row[2]}")
                    # The count on its own is not a check: what says a figure
                    # is missing is the combatant table, not the party size.
                    for line in undrawn(roll, found.get("blocks", 0)):
                        log.say(f"  ** {line}")
                        log.emit("undrawn", complaint=line)
                seen: list = []
                r = sess.fight(budget=args.budget,
                               tactic=watch_turns(seen) if args.icon else None)
                log.emit("fight", outcome=r.outcome, turns=r.turns,
                         acted=r.acted, blows=r.blows, lines=r.lines,
                         evidence=r.evidence)
                log.say(f"fight: {r.outcome} turns={r.turns} acted={r.acted} "
                        f"blows={r.blows}")
                for n, roll in enumerate(seen, 1):
                    log.emit("turn_roll", turn=n, **roll)
                    log.say(f"  turn {n}: camera "
                            f"{roll['camera'][0]},{roll['camera'][1]}; "
                            f"{roll['party_in_window']} of "
                            f"{roll['party_size']} party in the window, "
                            f"{roll['enemies_in_window']} enemies, "
                            f"{roll['blocks']} figures drawn")
                    for line in undrawn(roll, roll["blocks"]):
                        log.say(f"  ** {line}")
                log.say(r.evidence)
                sess.kbd.screenshot(str(log.dir / f"{args.tag}-fight-end.png"))
            else:
                log.say(f"no encounter in {steps} steps")
                log.emit("no_fight", steps=steps)
    except Exception as exc:
        import traceback
        # Photograph what the machine was showing.  A run that stops with
        # `no world bar` and no picture cannot say whether the game was
        # mid-animation, sitting on a prompt nobody answered, or wedged --
        # and that is the whole question a conversion run is asking.
        try:
            if sess is not None:
                sess.kbd.screenshot(str(log.dir / f"{args.tag}-failure.png"))
                s = sess.screen()
                rows = [] if s is None else \
                    [line.rstrip() for line in s.rows() if line.strip()]
                log.emit("failure_screen", rows=rows, bitmap=s is None)
                log.say("the screen when it stopped"
                        + (" (a bitmap, so no text)" if s is None else ":"))
                for line in rows:
                    log.say(f"    |{line}|")
        except Exception:
            log.say("could not photograph the failure")
        log.emit("failed", error=repr(exc), traceback=traceback.format_exc())
        traceback.print_exc()
        rc = 1
    finally:
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:
                log.emit("cleanup_failed", step=what, error=repr(exc))
                log.say(f"Cleanup failed at {what}: {exc!r}")
                rc = rc or 1
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, help="the save .d64 to boot")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's game disks are; read, never written")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--tag", default=None, help="prefix for the screenshots")
    p.add_argument("--out", default=None,
                   help="the log (default work/savecheck/<disk>.jsonl)")
    p.add_argument("--view", type=int, default=0,
                   help="how many VIEW sheets to read, stepped with NEXT")
    p.add_argument("--walk", default="",
                   help="Moves: the game's own letters I J K M in a dungeon, "
                        "the compass digits 1-8 on the travel grid")
    p.add_argument("--fight", action="store_true",
                   help="walk until something ambushes the party, then fight")
    p.add_argument("--fight-move", default="I",
                   help="The move to repeat while looking for a fight; "
                        "a compass digit if the party is on the travel grid")
    p.add_argument("--steps", type=int, default=60,
                   help="give up looking for a fight after this many steps")
    p.add_argument("--budget", type=float, default=900.0,
                   help="seconds to give the fight")
    p.add_argument("--resave", default=None,
                   help="After arriving, have the game's own ENCAMP > SAVE "
                        "write the party back, and copy that disk here")
    p.add_argument("--icon", action="store_true",
                   help="check the combat floor against the composed icon")
    p.add_argument("--route", action="store_true",
                   help="answer the screens a walked area change puts up")
    p.add_argument("--answer", default="NO",
                   help="what to answer a YES NO bar while routing")
    p.add_argument("--arrive", type=float, default=240.0,
                   help="seconds to wait for the world bar after BEGIN "
                        "ADVENTURING; an arrival that animates needs longer")
    args = p.parse_args(argv)
    stem = pathlib.Path(args.disk).stem
    args.tag = args.tag or stem
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "savecheck" / f"{stem}.jsonl")
    log = Log(out)
    try:
        return run(args, log)
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
