#!/usr/bin/env python3
"""Walk a Curse or Silver Blades party into a fight, and read the combat screen.

`tools/fightrun.py` and `tools/combatdiag.py` do this for Pool of Radiance and
both boot their own `Session`, which is that title's front end.  Curse and
Silver Blades boot differently (`tools/curserun.py`, `tools/ssbrun.py`), and
by the time either has a party in the world the session is already **served**
on its command port -- so this drives that port rather than booting anything,
and the same file works for both titles.

    tools/curseload.py --save work/issue131-m1/CURSEI.D64 --pool 2 --repair --serve
    POR_CMD_PORT=6562 tools/laterfight.py --out work/issue131-m2/curse

    tools/ssbrun.py --pool 3 --save work/193/SSBD.D64 --out work/193/run1
    POR_CMD_PORT=6563 tools/laterfight.py --out work/issue131-m2/ssb

**Three things about these two titles that Pool of Radiance's drivers do not
know, and each cost a run before it was found** (`#192`, `#291`, and the runs
behind this file):

* **`I J K M` do not arrive by XTEST.**  Every move key goes through the
  KERNAL buffer (`kernal 49/4A/4B/4D`), and an XTEST `I` is silently ignored,
  which looks exactly like a party that cannot move.
* **The status line lies.**  Curse redraws the square only in some areas and
  Silver Blades hides it in eleven of twenty-two, so a step is judged by the
  live triple at `$C04B`-`$C04D` -- x, y, facing -- which is unrelocated in
  all three titles.  In this file's own first run the status line still read
  `3,12` with the party standing at `02 0c 03`.
* **A step that goes nowhere is usually a menu**, not a wall: the shopkeeper's
  `YES NO`, a sign's `PRESS BUTTON OR RETURN TO CONTINUE.`, or the move
  sub-bar `I,J,K,M, RETURN OR BUTTON` waiting for a direction.  Row 24 is
  re-read before every key and classified, and each kind gets its own answer.

What it writes to `--out`: `run.jsonl` (one line per step, with the triple and
the row-24 classification), a screenshot and the 25 rows of every distinct
screen the walk met, and -- when a fight starts -- `combat.png`, the combat
bar verbatim, and the party's figures on the floor.

Nothing is written outside `--out` and the slot's own directory; the session
this talks to owns the emulator and tears it down.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import socket
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))

#: The move keys, as PETSCII codes for the KERNAL buffer.  `I` is forward,
#: `J` turns left, `K` turns right, `M` reverses.
MOVE = {"I": 0x49, "J": 0x4A, "K": 0x4B, "M": 0x4D}

#: The live position triple, unrelocated in Pool of Radiance, Curse and Silver
#: Blades alike: x, y, facing.  Read this and never the status line.
POSITION = 0xC04B

#: Row 24 when the move sub-bar is up and the game wants a direction.
MOVE_BAR = "I,J,K,M"

#: Words that only appear on a combat command bar.  `DONE` ends a combatant's
#: turn and `GUARD` is combat's own; neither is on any world or camp bar in
#: either title.
COMBAT_WORDS = ("DONE", "GUARD")

#: Row 24 of the world command bar.  Curse draws `MOVE VIEW CAST AREA ENCAMP
#: SEARCH LOOK` and Silver Blades the same words in a different order, so the
#: test is `MOVE` plus `ENCAMP` rather than the whole string.
WORLD_WORDS = ("MOVE", "ENCAMP")

RE_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s\|(.{40})\|$")


class Port:
    """One line at a time to a served session, the way `tools/porcmd` does."""

    def __init__(self, port: int, timeout: float = 300.0):
        self.port = port
        self.timeout = timeout

    def __call__(self, *words: object) -> str:
        line = " ".join(str(w) for w in words)
        s = socket.create_connection(("127.0.0.1", self.port),
                                     timeout=self.timeout)
        s.settimeout(self.timeout)
        s.sendall((line + "\n").encode())
        out = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
        s.close()
        return out.decode("latin1")


def rows(dump: str) -> list[str]:
    """The 25 screen rows out of a `screen` dump, or [] if it held none."""
    got = {}
    for line in dump.splitlines():
        m = RE_ROW.match(line)
        if m:
            got[int(m.group(1))] = m.group(3)
    return [got.get(r, " " * 40) for r in range(25)]


def triple(send: Port) -> tuple[int, int, int] | None:
    """x, y, facing off `$C04B`, or None when the read came back short."""
    raw = send("peek", f"{POSITION:04X}", 3).split("\n")[0].strip()
    parts = raw.split()
    if len(parts) != 3:
        return None
    try:
        return tuple(int(p, 16) for p in parts)          # type: ignore[return-value]
    except ValueError:
        return None


def kind(row24: str) -> str:
    """What row 24 is: the classification every answer hangs off."""
    text = row24.strip()
    if not text:
        return "blank"
    if any(w in text for w in COMBAT_WORDS):
        return "combat"
    if MOVE_BAR in text:
        return "movebar"
    if "INSERT" in text:
        return "disk"
    if "PRESS" in text and ("RETURN" in text or "BUTTON" in text or "KEY" in text):
        return "press"
    if text.split()[:2] == ["YES", "NO"]:
        return "yesno"
    if all(w in text for w in WORLD_WORDS):
        return "world"
    return "other"


class Run:
    def __init__(self, send: Port, out: pathlib.Path, answer: str):
        self.send = send
        self.out = out
        self.answer = answer
        self.log = (out / "run.jsonl").open("a")
        self.seen: set[str] = set()
        self.n = 0

    def note(self, **kw) -> None:
        kw["t"] = round(time.time(), 2)
        self.log.write(json.dumps(kw) + "\n")
        self.log.flush()
        print(json.dumps(kw), flush=True)

    def screen(self) -> list[str]:
        return rows(self.send("screen"))

    def keep(self, tag: str, screen: list[str]) -> None:
        """A screenshot and the 25 rows, once per distinct screen."""
        text = "\n".join(screen)
        digest = str(hash(text))
        if digest in self.seen:
            return
        self.seen.add(digest)
        self.n += 1
        stem = self.out / f"{self.n:02d}-{tag}"
        self.send("shot", str(stem.with_suffix(".png").resolve()))
        stem.with_suffix(".txt").write_text(text + "\n")

    def press_bar(self, word: str, tries: int = 12) -> bool:
        """Put the bar highlight on `word` and press Return **through the KERNAL**.

        `Session.select_bar` walks the highlight with XTEST arrows, which
        these two titles do read, and then presses Return with XTEST, which
        they do **not** -- the same finding `tools/curseload.py` records for
        `LOAD SAVED GAME ? YES NO`, and it holds on the combat bar too.  So a
        `bar QUICK` looks as if it worked, returns True, and nothing happens.

        The highlight is colour 1 in row 24's colour RAM against colour 5 for
        the rest of the bar, so where it is can be read rather than counted
        from an assumed start -- which matters because Curse's combat bar is
        two pages (`MOVE VIEW AIM TURN QUICK DONE` and `GUARD DELAY QUIT
        SPEED EXIT`) and walking off the end of one lands on the other.
        """
        for _ in range(tries):
            row = self.screen()[24]
            col = row.find(word)
            if col < 0:
                return False
            hot = [i for i, c in enumerate(bytes.fromhex(
                self.send("colours", 24).split("\n")[0].replace(" ", "")))
                if c == 1]
            if not hot:
                return False
            if hot[0] == col:
                self.send("kernal", "0D")
                return True
            self.send("key", "Right" if hot[0] < col else "Left", 0.15, 0.4)
        return False

    def answer_screen(self, k: str) -> bool:
        """Deal with whatever is not a plain world bar.  True if it acted."""
        if k == "press":
            self.send("kernal", "0D")
            return True
        if k == "yesno":
            self.send("bar", self.answer)
            return True
        if k == "disk":
            self.send("settle", 8)
            return True
        return False

    def step(self, key: str) -> dict:
        """One move key, judged by the triple rather than the status line."""
        before = triple(self.send)
        self.send("kernal", f"{MOVE[key]:02X}")
        after = triple(self.send)
        screen = self.screen()
        k = kind(screen[24])
        # **A turn is not a move.**  `J` and `K` change the third byte of the
        # triple and nothing else, so a walker that calls the triple changing
        # "moved" never advances past the first turn in its pattern and spins
        # on the spot -- measured on `#131`, 2026-09-05, twelve full circles
        # at 3,11.  Only x and y count.
        moved = (before is None or after is None or before[:2] != after[:2])
        return {"key": key, "before": before, "after": after,
                "moved": moved, "row24": screen[24].strip(),
                "kind": k, "screen": screen}


def walk_to_a_fight(run: Run, steps: int, pattern: str) -> dict | None:
    """Press move keys until row 24 is a combat bar, or the budget runs out.

    The pattern is the order the keys are tried in; a step that changes
    nothing takes the next key, which is how the party gets round a corner
    without anybody mapping the streets.
    """
    keys = list(pattern)
    i = 0
    misses = 0
    turn_next = False
    for n in range(steps):
        screen = run.screen()
        k = kind(screen[24])
        if k == "combat":
            run.keep("combat", screen)
            run.note(event="combat", step=n, row24=screen[24].strip())
            return {"step": n, "screen": screen}
        if run.answer_screen(k):
            run.note(event="answered", step=n, kind=k,
                     row24=screen[24].strip())
            run.keep(k, screen)
            # **A script in front of the party is a wall for this purpose.**
            # The engine puts the party back on the square it stepped from,
            # facing the script, so the *next* key has to be a turn: taking
            # the next entry of the pattern is not enough, and a run that
            # does spends its whole budget walking into the same shopkeeper.
            # Measured on `#131`, 2026-09-05: 64 steps, 3,12 to 2,12 and back
            # sixteen times, no fight.
            if k in ("yesno", "press"):
                turn_next = True
            continue
        if k in ("world", "blank", "other"):
            # A blank row 24 is a screen mid-redraw as often as it is a
            # wedged one, so a miss is only a miss after three of them.
            if run.send("bar", "MOVE").startswith("True"):
                misses = 0
                continue
            misses += 1
            run.note(event="move-miss", step=n, misses=misses,
                     row24=screen[24].strip())
            if misses >= 3:
                run.keep("move-miss", screen)
                return None
            time.sleep(1.5)
            continue
        if turn_next:
            got = run.step("K")
            turn_next = False
        else:
            got = run.step(keys[i % len(keys)])
            if not got["moved"]:
                i += 1
        run.note(event="step", step=n, key=got["key"], before=got["before"],
                 after=got["after"], moved=got["moved"], kind=got["kind"],
                 row24=got["row24"])
        if got["kind"] == "combat":
            run.keep("combat", got["screen"])
            run.note(event="combat", step=n, row24=got["row24"])
            return {"step": n, "screen": got["screen"]}
    run.note(event="no-fight", steps=steps)
    return None


#: Where the combat panel draws the acting character's name.  Row 2 of the
#: right-hand column in Curse and Silver Blades alike.
ACTING_ROW = 2


def survey_bars(run: Run, rounds: int) -> None:
    """Whose turn it is and what their command bar offers, character by character.

    **This is how a per-character combat command is proved rather than
    assumed.**  `TURN` on the bar of a paladin whose `turn_power` the
    conversion computed says nothing on its own: the bar might carry the word
    for everybody.  Pressing `DONE` walks the turn on to the next combatant,
    and a magic-user whose byte is zero is the control -- if his bar carries
    `TURN` too, the word is furniture and the measurement is worthless.
    """
    seen: dict[str, str] = {}
    for n in range(rounds):
        screen = run.screen()
        if kind(screen[24]) != "combat":
            run.note(event="not-combat", round=n, row24=screen[24].strip())
            return
        who = screen[ACTING_ROW].strip(" $*<>|").strip()
        bar = screen[24].strip()
        run.note(event="turn", round=n, who=who, bar=bar)
        if who and who not in seen:
            seen[who] = bar
            run.keep(f"turn-{who or n}", screen)
        run.send("bar", "DONE")
        time.sleep(1.0)
    run.note(event="bars", bars=seen)


def read_the_fight(run: Run, melee: bool, budget: float) -> None:
    """What the combat screen holds, before anybody is asked to act."""
    run.note(event="combat-bar", row24=run.screen()[24].strip())
    run.note(event="battle", text=run.send("battle").strip()[:2000])
    run.note(event="party-panel",
             rows=[r.rstrip() for r in run.screen()[0:20]])
    if melee:
        run.note(event="melee", result=run.send("melee", budget).strip()[:2000])
        run.keep("after-melee", run.screen())


def quickfight(run: Run, turns: int) -> None:
    """Press `QUICK` for every combatant until the fight is over.

    Quickfight is the one combat command a converted party can be asked for
    without anybody deciding tactics, so it is what says whether the party can
    *fight* rather than only reach the floor.  It is per character and per
    turn, not a mode: each press resolves one combatant's turn and the panel
    moves on to the next.
    """
    for n in range(turns):
        screen = run.screen()
        if kind(screen[24]) != "combat":
            run.note(event="fight-over", turn=n, row24=screen[24].strip())
            run.keep("fight-over", screen)
            return
        who = screen[ACTING_ROW].strip(" $*<>|").strip()
        run.note(event="quick", turn=n, who=who, bar=screen[24].strip(),
                 panel=[r.rstrip() for r in screen[3:10]])
        if not run.press_bar("QUICK"):
            run.note(event="quick-miss", turn=n, row24=screen[24].strip())
            return
        time.sleep(2.0)
    run.note(event="quick-budget", turns=turns)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("POR_CMD_PORT") or 0),
                    help="the served session's command port; $POR_CMD_PORT")
    ap.add_argument("--out", default="work/laterfight",
                    help="where the log, the screens and the shots go")
    ap.add_argument("--steps", type=int, default=120,
                    help="how many move keys to spend looking for a fight")
    ap.add_argument("--pattern", default="IIIKIIIJ",
                    help="the order the move keys are tried in")
    ap.add_argument("--answer", default="NO",
                    help="what to say to a YES NO a script puts up")
    ap.add_argument("--melee", action="store_true",
                    help="drive the fight once it starts")
    ap.add_argument("--budget", type=float, default=600.0,
                    help="seconds the melee may take")
    ap.add_argument("--quick", type=int, default=0,
                    help="resolve this many combat turns with QUICK")
    ap.add_argument("--survey-bars", type=int, default=0,
                    help="press DONE this many times and log whose turn it "
                         "is and what their combat bar offers")
    ap.add_argument("--read-only", action="store_true",
                    help="read the combat screen and walk nowhere: for a "
                         "session already standing in a fight")
    args = ap.parse_args(argv)
    if not args.port:
        print("no command port: pass --port or set POR_CMD_PORT")
        return 2
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run = Run(Port(args.port), out, args.answer)
    run.note(event="start", port=args.port, steps=args.steps,
             pattern=args.pattern)
    if not args.read_only:
        got = walk_to_a_fight(run, args.steps, args.pattern)
        if got is None:
            return 1
    read_the_fight(run, args.melee, args.budget)
    if args.quick:
        quickfight(run, args.quick)
    if args.survey_bars:
        survey_bars(run, args.survey_bars)
    run.note(event="done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
