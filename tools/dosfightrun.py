#!/usr/bin/env python3
"""Drive a DOS Pool of Radiance fight, and capture one before the driver exists.

`tools/dosbox.py` drives everything up to a fight -- the title screens, the
load, the steps and turns, `ENCAMP`, `SAVE` -- and stops there.  This adds the
fight, in the two pieces #114 asked for:

* **`capture`** presses almost nothing and records everything: a labelled log
  of every quarter second from the moment a step walks into an encounter until
  the world command bar comes back, a PNG the first time each command bar
  appears, and the save files either side.  It is how the digests in
  `PoolOfRadiance.COMBAT_BARS` were measured, and how `q` was put to the test.
* **`fight`** is the driver those digests made possible: press `q` at a
  command bar, `Return` at a press-any-key prompt, `n` at `CONTINUE BATTLE`,
  and nothing at all at a screen we have not recognised.

**Ground truth is the save file and never the screen.**  A fight is proven by
experience rising in `CHRDAT<slot><n>.SAV`, because monsters do not kill each
other -- so experience rising names the killer by construction.  Hit points
falling is reported and is never proof: the monsters lower those, and a party
member who swings and misses lowers nothing.

Nothing here reads text off the screen.  Every wait is a digest of a strip of
pixels compared for equality, which cannot be misread, only unequal.  The
words beside each digest in `PoolOfRadiance.COMBAT_BARS` were read once, by a
person, off the PNGs this tool wrote; the driver never reads them.

Run time it needs: whatever `tools/dosbox.py` needs, plus the player's own
copy of the archives.  Output goes under `work/dosbox/p114/`, never into the
repository: the PNGs are the game's own pixels.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldbox import dos_savegame as _sav  # noqa: E402
from tools import dosbox  # noqa: E402
from tools.dosbox import (  # noqa: E402
    BAR,
    STATUS,
    PoolOfRadiance,
    Session,
    claim,
    find_game,
)

#: Where a run's frames, log and saves land.  Under `work/`, which is
#: gitignored, because a frame of the game is the game's own art.
OUT = dosbox.REPO / "work" / "dosbox" / "p114"

#: The Slums encounter counter.  `ECL14` adds one to `$4ABB` in a subroutine
#: reached only after a `COMBAT`, so it says a fight *ended* -- never that the
#: party fought one.  `goldbox/commissions.py` carries the reading.
SLUMS_FIGHTS = 0x4ABB

#: Candidate quickfight bit in the DOS record.  The C64 roster's `+0x0C` lands
#: on DOS `0x10E` by the -2 displacement in `docs/117-save-conversion.md`, and
#: `goldbox-bugs.md` bug 3 says QUICK sets it and nothing ever clears it.
#: PROBABLE by alignment only; a run is what tests it.
QUICKFIGHT_BYTE = 0x10E

#: `CHRDAT` offsets read directly, so a state snapshot needs no field table.
#: Both are `goldbox/dos_layout.py`'s and are asserted against it in
#: `tests/test_dosfight.py`.
XP = 0x0AC          # three bytes, little-endian
HP_CURRENT = 0x11B


# --------------------------------------------------------------------------
# Ground truth: what the files say
# --------------------------------------------------------------------------


def party_state(save_dir: Path, letter: str) -> dict:
    """Experience, hit points and the quickfight candidate, per character.

    Read straight out of `CHRDAT<letter><n>.SAV` rather than through
    `goldbox.dos.read_party`, because a snapshot wants the raw record too: the
    diff between two of these is what says which *other* bytes a fight moved.
    """
    out: dict = {"slot": letter, "chars": [], "save": None}
    for n in range(1, 7):
        path = save_dir / f"CHRDAT{letter.upper()}{n}.SAV"
        if not path.is_file():
            continue
        d = path.read_bytes()
        out["chars"].append(
            {
                "file": path.name,
                "experience": int.from_bytes(d[XP:XP + 3], "little"),
                "hp_current": d[HP_CURRENT],
                "quickfight_candidate": d[QUICKFIGHT_BYTE],
                "mtime": path.stat().st_mtime,
                "raw": d.hex(),
            }
        )
    sav = save_dir / f"SAVGAM{letter.upper()}.DAT"
    if sav.is_file():
        data = sav.read_bytes()
        out["save"] = {
            "file": sav.name,
            "position": list(dosbox.position(data)),
            "area_id": dosbox.area_id(data),
            "slums_fights": _sav.word(data, SLUMS_FIGHTS),
            "mtime": sav.stat().st_mtime,
            "raw": data.hex(),
        }
    return out


def state_diff(before: dict, after: dict) -> dict:
    """What changed between two `party_state` snapshots.

    Experience is the finding; hit points are reported because they are the
    trap.  A monster lowers hit points and so does nothing the party did, so
    the field is evidence the party was *struck*, never that it struck back.
    """
    chars = []
    for a, b in zip(before["chars"], after["chars"]):
        ra, rb = bytes.fromhex(a["raw"]), bytes.fromhex(b["raw"])
        chars.append(
            {
                "file": a["file"],
                "experience": [a["experience"], b["experience"]],
                "hp_current": [a["hp_current"], b["hp_current"]],
                "quickfight_candidate": [
                    a["quickfight_candidate"], b["quickfight_candidate"]
                ],
                "bytes_changed": [i for i in range(min(len(ra), len(rb)))
                                  if ra[i] != rb[i]],
            }
        )
    out: dict = {
        "chars": chars,
        "experience_rose": any(c["experience"][1] > c["experience"][0]
                               for c in chars),
        "hit_points_fell": any(c["hp_current"][1] < c["hp_current"][0]
                               for c in chars),
    }
    if before["save"] and after["save"]:
        sa, sb = before["save"], after["save"]
        ra, rb = bytes.fromhex(sa["raw"]), bytes.fromhex(sb["raw"])
        out["save"] = {
            "position": [sa["position"], sb["position"]],
            "area_id": [sa["area_id"], sb["area_id"]],
            "slums_fights": [sa["slums_fights"], sb["slums_fights"]],
            "changed_in_array": [i for i in range(min(len(ra), len(rb)))
                                 if ra[i] != rb[i] and i < 5121],
            "changed_total": sum(1 for i in range(min(len(ra), len(rb)))
                                 if ra[i] != rb[i]),
        }
    return out


def fought(diff: dict) -> bool:
    """Whether the party killed anything, by the one signal that says so.

    Experience is paid for monsters defeated, and monsters do not kill each
    other -- so a rise names the party as the killer with nothing read off the
    screen.  This is the DOS answer to #163, whose C64 message band prints
    `HITS` and `MISSES` for both sides in the same words.
    """
    return bool(diff["experience_rose"])


# --------------------------------------------------------------------------
# The capture run
# --------------------------------------------------------------------------


class Recorder:
    """A quarter-second log of bar, status and whole-frame digests.

    Every entry carries what was pressed at it, so the offline read of the
    PNGs can say which key moved which bar to which -- which is the whole of
    what a driver needs and the only thing that makes step 1 worth a run.
    """

    def __init__(self, por: PoolOfRadiance, out: Path):
        self.por = por
        self.s = por.s
        self.out = out
        self.log: list[dict] = []
        self.seen: dict[str, str] = {}      # bar ink -> PNG name
        self.t0 = time.time()

    def tick(self, note: str = "", pressed: str = "") -> dict:
        screen = self.s.capture()
        # `glyphs`, not `ink`: the combat screen's paper is `#555555`, which is
        # above `ink`'s threshold, so every combat bar comes back as the sha1
        # of an all-lit strip and the log cannot tell one from another.
        bar = screen.glyphs(BAR)
        entry = {
            "t": round(time.time() - self.t0, 2),
            "bar": bar,
            "ink": screen.ink(BAR),
            "status": screen.ink(STATUS),
            "frame": screen.digest(),
            "note": note,
            "pressed": pressed,
        }
        if bar not in self.seen:
            name = f"bar{len(self.seen):02d}_{bar}"
            try:
                self.s.shot(name, allow_blank=True)
            except Exception as e:                      # pragma: no cover
                entry["shot_error"] = str(e)
            self.seen[bar] = name
            entry["shot"] = name
        self.log.append(entry)
        return entry

    def watch(self, seconds: float, tick: float = 0.25, note: str = "") -> None:
        """Press nothing and record, for `seconds`."""
        end = time.time() + seconds
        while time.time() < end:
            self.tick(note=note)
            time.sleep(tick)

    def press(self, key: str, note: str = "") -> None:
        self.s.key(key)
        self.tick(note=note, pressed=key)

    def write(self, name: str = "capture.jsonl") -> Path:
        path = self.out / name
        path.write_text("".join(json.dumps(e) + "\n" for e in self.log))
        return path

    # -- what the log is for -------------------------------------------

    def bar_table(self) -> list[dict]:
        """One row per distinct command bar: when, for how long, what moved it.

        `digest | seconds | first pressed at it | what it became` -- the table
        #114 asks to be posted before a line of driver is written.  The words
        are not here because nothing in this file reads words; they are added
        by hand from the PNG each row names.
        """
        rows: list[dict] = []
        for e in self.log:
            if rows and rows[-1]["bar"] == e["bar"]:
                row = rows[-1]
                row["until"] = e["t"]
                row["frames"] = row.get("frames", 1) + 1
                if e["pressed"]:
                    row.setdefault("keys", []).append(e["pressed"])
            else:
                if rows:
                    rows[-1]["became"] = e["bar"]
                rows.append({
                    "bar": e["bar"],
                    "from": e["t"],
                    "until": e["t"],
                    "frames": 1,
                    "shot": self.seen.get(e["bar"], ""),
                    "keys": [e["pressed"]] if e["pressed"] else [],
                })
        for row in rows:
            row["seconds"] = round(row["until"] - row["from"], 2)
        return rows

    def stillness(self) -> dict:
        """How often consecutive whole-frame captures agreed, per bar.

        The blink hazard: Gold Box games blink the acting figure on the combat
        map, so `settle()` -- which waits for two identical frames -- may never
        return during a fight.  A bar whose frames never agree is a bar no
        `settle()` may be called at.
        """
        by_bar: dict[str, list[int]] = {}
        for a, b in zip(self.log, self.log[1:]):
            if a["bar"] != b["bar"]:
                continue
            by_bar.setdefault(a["bar"], [0, 0])
            by_bar[a["bar"]][1] += 1
            if a["frame"] == b["frame"]:
                by_bar[a["bar"]][0] += 1
        return {bar: {"agreed": n, "pairs": total,
                      "rate": round(n / total, 3) if total else None}
                for bar, (n, total) in by_bar.items()}


def walk_until_stopped(por: PoolOfRadiance, rec: Recorder,
                       presses: int = 60) -> dict:
    """Step until the world command bar does not come back, or give up.

    A step that leaves the whole frame unchanged is a wall, so turn right and
    try again.  `_move` returning False is the hook #114 guessed at: an
    encounter is one of the things that stops the world bar coming back.
    """
    walked = 0
    for i in range(presses):
        before = por.s.capture().digest()
        moved = por.step()
        rec.tick(note=f"step {i}", pressed="Up")
        if not moved:
            return {"stopped_at": i, "walked": walked, "why": "world bar did not return"}
        if por.s.capture().digest() == before:
            por.turn_right()
            rec.tick(note=f"wall at {i}, turned right", pressed="Right")
        else:
            walked += 1
    return {"stopped_at": None, "walked": walked, "why": f"no encounter in {presses} presses"}


#: The capture run's key ladder, tried in order at whatever is on the screen.
#:
#: `q` first because at a combat command bar it is the thing under test, and
#: everywhere else it has been harmless.  `c` second because it is COMBAT on
#: the encounter bar, which is the one screen `q` provably does not move --
#: the first run pressed `q`, `Return`, `Escape`, `e` and `n` at
#: `COMBAT WAIT FLEE ADVANCE` for two minutes and the bar never changed.  Then
#: `Return` for a press-any-key prompt, `n` for `CONTINUE BATTLE : YES NO`,
#: `e` for EXIT on a treasure bar, and `Escape` to back out of a sub-bar.
LADDER = ("q", "c", "Return", "n", "e", "Escape")


def capture(save: str = "J", before: str = "C", after: str = "D",
            budget: float = 900.0, dwell: float = 1.5,
            out: Path | None = None) -> dict:
    """Walk into a fight, press the ladder, and record the whole thing.

    Drives nothing on purpose: the deliverable is labelled frames and a log,
    not a driver.  What it decides is which shape `fight()` has -- whether `q`
    at a combat command bar hands the character to the computer for the fight,
    resolves one round, or does nothing at all.
    """
    out = out or OUT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    result: dict = {"save": save}
    with claim("p114 capture") as slot:
        with Session(slot, find_game()) as s:
            por = PoolOfRadiance(s)
            rec = Recorder(por, out)
            por.to_main_menu()
            por.load_game(save)
            rec.tick(note="loaded")
            result["world_bar"] = por.world_glyphs
            por.save_game(before)
            result["before"] = party_state(s.save_dir, before)

            result["walk"] = walk_until_stopped(por, rec)
            s.shot("encounter", allow_blank=True)

            # Press nothing for half a minute: does the game proceed to the
            # fight on its own, and does the frame ever settle?
            rec.watch(30.0, note="pressing nothing")

            # Then the ladder.  Two things it must not be built on, both
            # measured rather than assumed:
            #
            # * **Not on the picture holding still.**  It never does -- 165
            #   pixels of the treasure chest moved between eight consecutive
            #   captures with nobody acting and no key pressed -- so a ladder
            #   that presses "once the frame has been unchanged for N seconds"
            #   presses only on its own timeout, and always the same rung.
            # * **Not on the command bar changing when a key lands.**  Every
            #   character's turn in a fight shows the same
            #   `MOVE VIEW AIM USE QUICK DONE`, so its ink is the same from
            #   one turn to the next.  A ladder watching the bar for its reset
            #   crawled at one useful keypress every forty seconds.
            #
            # So: one key every `dwell` at most, and the rung goes back to the
            # top whenever the bar *does* move, which is the only unambiguous
            # sign a key was the right one.
            deadline = time.time() + budget
            rung = 0
            bar = rec.log[-1]["bar"]
            world_since = None
            while time.time() < deadline:
                e = rec.tick(note="ladder")
                if e["bar"] != bar:
                    bar, rung = e["bar"], 0
                if e["bar"] == por.world_glyphs:
                    world_since = world_since or time.time()
                    if time.time() - world_since >= 5.0:
                        result["finished"] = "world bar held 5s"
                        break
                    time.sleep(0.25)
                    continue
                world_since = None
                rec.press(LADDER[rung % len(LADDER)], note="ladder")
                rung += 1
                s.wait_while_glyphs(BAR, e["bar"], timeout=dwell)
            else:
                result["finished"] = "budget"
                s.shot("stuck", allow_blank=True)

            try:
                por.save_game(after)
                result["after"] = party_state(s.save_dir, after)
            except Exception as e:
                result["after_error"] = str(e)
            for name in sorted(rec.seen.values()) + ["encounter", "stuck"]:
                src = s.dir / "shots" / f"{name}.png"
                if src.is_file():
                    shutil.copy2(src, out / f"{name}.png")
    rec.write()
    result["bars"] = rec.bar_table()
    result["stillness"] = rec.stillness()
    if "after" in result:
        result["diff"] = state_diff(result["before"], result["after"])
        result["fought"] = fought(result["diff"])
    (out / "capture.json").write_text(json.dumps(result, indent=2))
    return result


# --------------------------------------------------------------------------
# The driven fight
# --------------------------------------------------------------------------


def fight_run(save: str = "J", before: str = "C", after: str = "D",
              rounds: int = 1, out: Path | None = None) -> dict:
    """Load, walk into a fight, `fight()`, save, and diff -- the proof.

    Returns the diff either side of every fight.  `fought` is experience
    rising, which is the only signal that names the party as the killer.
    """
    out = out or OUT / "fights"
    out.mkdir(parents=True, exist_ok=True)
    runs: list[dict] = []
    with claim("p114 fight") as slot:
        with Session(slot, find_game()) as s:
            por = PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(save)
            for i in range(rounds):
                por.save_game(before)
                start = party_state(s.save_dir, before)
                walked = 0
                for _ in range(60):
                    seen = s.capture().digest()
                    if not por.step():
                        break
                    walked += 1
                    if s.capture().digest() == seen:
                        por.turn_right()
                else:
                    runs.append({"round": i, "error": "no encounter in 60 presses"})
                    continue
                won = por.fight()
                por.save_game(after)
                end = party_state(s.save_dir, after)
                diff = state_diff(start, end)
                runs.append({"round": i, "walked": walked, "fight": won,
                             "fought": fought(diff), "diff": diff})
                if not won:
                    break
    (out / "fights.json").write_text(json.dumps(runs, indent=2))
    return {"runs": runs}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("capture", "fight"))
    ap.add_argument("--save", default="J", help="save slot to load")
    ap.add_argument("--before", default="C", help="scratch slot for the baseline")
    ap.add_argument("--after", default="D", help="scratch slot for the result")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--budget", type=float, default=900.0)
    args = ap.parse_args(argv)
    if args.command == "capture":
        out = capture(save=args.save, before=args.before, after=args.after,
                      budget=args.budget)
        out.pop("before", None)
        out.pop("after", None)
        print(json.dumps(out, indent=2)[:20000])
        return 0
    print(json.dumps(fight_run(save=args.save, before=args.before,
                               after=args.after, rounds=args.rounds),
                     indent=2)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
