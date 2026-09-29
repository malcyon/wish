#!/usr/bin/env python3
"""Build a C64 Pool of Radiance party in the game's own CREATE NEW CHARACTER screens.

The C64 twin of `tools/dos/dosparty.py`: it rolls each character of a spec on a
pooled VICE, keeps the first roll, saves the party with the game's own SAVE
CURRENT GAME, and reads back what the engine wrote.

    tools/c64/creation.py --lists --issue N --run lists
    tools/c64/creation.py --build SPEC.json --issue N --run build \\
        [--enter-world] [--pool N] [--max-seconds S] [--world-budget S]

`--lists` opens the class list for every race and the alignment list for every
class and writes them as `lists.json`.  `--build` reads a JSON list of `{name,
race, gender, class, alignment, classes}`: the first five are the on-screen
text and `classes` is the `class_levels` expected back, defaulting to level 1
in each class the label names.  It stages a blank save disk, creates every
character, copies the disk as `rolled.D64` before any add, adds them all,
saves as `party.D64`, and compares each record with the spec.  `--enter-world`
goes on through BEGIN ADVENTURING and a camp save to `intown.D64`.

**A screen is text, so a spec names a menu entry by its label** and
`Session.select_row` walks the highlight onto it; nothing counts presses from
an assumed start.  A label missing from its list, a screen this driver does
not recognise and a deadline all stop the run with a capture
and a `lost` line, having pressed nothing further.

**The C64 order is race, gender, roll, class, alignment, name, `SAVE?`,
portrait, icon, the write, then PICK RACE again.**  The roll comes before the
class, backing out of PICK CLASS rerolls, and the ADD list stays up after an
add, so EXIT is pressed only while it is.  Exceptional strength is rolled after
the alignment and is not on the roll screen, so it is left out of the
comparison with the roll.

**Three things no other tool does:** the save disk is re-attached before it is
copied after a write made on a menu, because VICE holds the drive's last
directory track until the head moves; every wait re-reads text rather than
waiting for a still screen, because a row-24 prompt blinks; and each list is
given the column its labels start in.

Evidence goes to `~/.cache/wish/acceptance/<issue>/<sha10>-<run>/`:
`run.jsonl`, `shots/NNN-<tag>.png` and `.txt`, the disks, `records.txt` and
`summary.json`.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import pathlib
import re
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from goldbox import derive, levels, savegame  # noqa: E402
from goldbox.classcode import CLASS_BIT_FOR_NAME  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402
from goldbox.yaml_io import ALIGNMENTS as ALIGNMENT_CODES  # noqa: E402
from tools.c64 import runlog  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.registry import evidence, scratch  # noqa: E402

ISSUE_NOTE = "c64creation"

#: What the race list draws, and the code `GEN $0946` stores at record `0x072`.
RACES = {"DWARF": 1, "ELF": 2, "GNOME": 3, "HALF-ELF": 4, "HALFLING": 5,
         "HUMAN": 7}
GENDERS = {"MALE": 0, "FEMALE": 1}
#: The classes a creation list combines; paladin, ranger and the rest are in
#: `CLASS_BIT_FOR_NAME` but no Pool race is offered them.
CLASS_PARTS = ("cleric", "fighter", "magic-user", "thief")
#: The class list each race is offered, in on-screen order.  `check_specs` reads
#: it before the first key so a class the race is never offered is refused up
#: front.
CLASSES_BY_RACE = {
    "DWARF": ("FIGHTER", "THIEF", "FIGHTER/THIEF"),
    "ELF": ("FIGHTER", "MAGIC-USER", "THIEF", "FIGHTER/MAGIC-USER",
            "FIGHTER/THIEF", "FIGHTER/MAGIC-USER/THIEF", "MAGIC-USER/THIEF"),
    "GNOME": ("FIGHTER", "THIEF", "FIGHTER/THIEF"),
    "HALF-ELF": ("CLERIC", "FIGHTER", "MAGIC-USER", "THIEF", "CLERIC/FIGHTER",
                 "CLERIC/FIGHTER/MAGIC-USER", "CLERIC/MAGIC-USER",
                 "FIGHTER/MAGIC-USER", "FIGHTER/THIEF",
                 "FIGHTER/MAGIC-USER/THIEF", "MAGIC-USER/THIEF"),
    "HALFLING": ("FIGHTER", "THIEF", "FIGHTER/THIEF"),
    "HUMAN": ("CLERIC", "FIGHTER", "MAGIC-USER", "THIEF"),
}

#: The constitution each sturdy race's creation roll can give, from a static
#: read of the clamp tables in `GEN`, not from rolls seen on the screen.  A band
#: outside it is refused before any key is pressed.
CON_LIMITS = {"DWARF": (12, 19), "GNOME": (8, 18), "HALFLING": (10, 19)}
#: The saving throws in stored order, `0x09A` to `0x09E`.
SAVE_FIELDS = ("save_paralysis", "save_petrification", "save_wands",
               "save_breath", "save_spell")
#: Rolls made looking for a constitution band before the run gives up.
MAX_ROLLS = 2000
#: How long the rest of the party menu is waited for once its first row shows.
MENU_DRAW_WAIT = 10.0
#: How long a new roll is waited for after ROLL AGAIN.
REROLL_WAIT = 3.0

#: On-screen text, in the order of the code stored at `0x0D8`.
ALIGNMENTS = tuple(a.upper() for a in ALIGNMENT_CODES)


def alignments_offered(cls: str) -> tuple[str, ...]:
    """The alignment list a class label is offered, in on-screen order.

    Measured on every race and class pair a creation list offers: a class
    containing CLERIC has no TRUE NEUTRAL, one containing THIEF has no LAWFUL
    GOOD and no CHAOTIC GOOD, and every other class has all nine.
    """
    parts = cls.split("/")
    barred = set()
    if "CLERIC" in parts:
        barred.add("TRUE NEUTRAL")
    if "THIEF" in parts:
        barred |= {"LAWFUL GOOD", "CHAOTIC GOOD"}
    return tuple(a for a in ALIGNMENTS if a not in barred)

#: The six ability lines of the roll screen, in record order (`0x014`-`0x019`).
ABILITIES = ("strength", "intelligence", "wisdom", "dexterity", "constitution",
             "charisma")
#: Each row of the roll screen sits inside the game's window frame, so the
#: text starts with a `$`; the frame is optional, so an unframed row still reads.
RE_SCORE = re.compile(r"^\$?\s*(STRENGTH|INTELLIGENCE|WISDOM|DEXTERITY|CONSTITUTION"
                      r"|CHARISMA)\s+(\d+)", re.M)

#: The name routine rejects any byte at or above `$5B` and holds fifteen.
RE_NAME = re.compile(r"[A-Z0-9]{1,15}")
#: Menu words a name must not contain: the ADD list and the `SAVE?` walk select
#: rows by the first row holding the text, so a name holding one would be
#: mistaken for that entry.
RESERVED_IN_NAMES = ("YES", "EXIT")

#: The screens this driver knows, recognised by `recognise`.
PARTY_MENU, PICK_RACE, PICK_GENDER, ROLL = "party", "race", "gender", "roll"
PICK_CLASS, PICK_ALIGN, NAME, SHEET = "class", "alignment", "name", "sheet"
PORTRAIT, ICON, ADD_LIST, SAVE_YN = "portrait", "icon", "add", "save-yn"
SAVING, WORLD, DISK, REFUSED = "saving", "world", "disk", "refused"

#: Screens on which the game has stopped asking for what the driver has: a
#: full disk, a failed write, and the format question whose YES wipes the disk.
REFUSALS = ("12 CHARACTERS PER DISK MAX", "SAVE FAILED", "FORMAT?")

#: Where each list's labels start.  The class list fills its row from column
#: 1; the ADD list's names start in column 4 with a star in column 3.
RACE_COLUMN = GENDER_COLUMN = ALIGN_COLUMN = ROLL_COLUMN = 2
CLASS_COLUMN = 1
ADD_COLUMN = 4
ADD_STAR_COLUMN = 3
YES_COLUMN = 28
#: A list's entries are on the rows above its prompt, never past this column.
LIST_FIRST_ROW = 2
LIST_WIDTH = 26
#: The party menu keeps rows 13 and down, so the ADD list's prompt, which is
#: above them, is what tells the two apart.
ADD_PROMPT_ROWS = range(3, 13)

#: The row the typed name appears on, under the prompt.
NAME_ROW = 3
BACK = 0x5F          # the left-arrow key, delivered through the KERNAL buffer
CLEANUP_SECONDS = 60.0
WAIT = 60.0
LOAD_WAIT = 150.0     # a load, a disk prompt or a write between two screens
#: A screen no recogniser names, held this long, ends the run.
UNRECOGNISED_SECONDS = 45.0
#: A key whose screen has not changed after this long is sent once more.
RETRY_AFTER = 6.0
SELECT_TIMEOUT = 30.0
POLL = 0.5
WORLD_BUDGET = 400.0


class Lost(Exception):
    """The run cannot go on; the message says why and a capture was taken."""


class LabelProblem(Lost):
    """A label is missing from its list, or would select the wrong row."""


@dataclasses.dataclass
class Spec:
    """One character to create, in the words the screens use."""

    name: str
    race: str
    gender: str
    cls: str
    alignment: str
    classes: dict[str, int]
    #: The constitution the roll must show, low and high, or None to keep the
    #: first roll.
    constitution: tuple[int, int] | None = None

    @classmethod
    def from_json(cls, d: dict) -> "Spec":
        name = str(d["name"]).upper()
        if not RE_NAME.fullmatch(name):
            raise ValueError(f"{name!r}: a name is 1-15 letters or digits")
        if any(word in name for word in RESERVED_IN_NAMES):
            raise ValueError(f"{name}: a name must not contain "
                             f"{' or '.join(RESERVED_IN_NAMES)}, which are menu "
                             f"entries")
        race, gender = str(d["race"]).upper(), str(d["gender"]).upper()
        klass, alignment = str(d["class"]).upper(), str(d["alignment"]).upper()
        if race not in RACES:
            raise ValueError(f"{name}: race {race!r} is not one of {list(RACES)}")
        if gender not in GENDERS:
            raise ValueError(f"{name}: gender {gender!r} is not one of {list(GENDERS)}")
        if alignment not in ALIGNMENTS:
            raise ValueError(f"{name}: alignment {alignment!r} is not one of "
                             f"{list(ALIGNMENTS)}")
        parts = [p.lower() for p in klass.split("/")]
        bad = [p for p in parts if p not in CLASS_PARTS]
        if bad:
            raise ValueError(f"{name}: unknown class {bad} in {klass!r}")
        classes = d.get("classes") or {p: 1 for p in parts}
        band = d.get("constitution")
        if band is not None:
            if len(band) != 2:
                raise ValueError(f"{name}: constitution is [low, high]")
            band = (int(band[0]), int(band[1]))
            if band[0] > band[1]:
                raise ValueError(f"{name}: constitution {list(band)} is "
                                 f"empty: low is above high")
            limits = CON_LIMITS.get(race)
            if limits and (band[0] > limits[1] or band[1] < limits[0]):
                raise ValueError(f"{name}: a {race} rolls constitution "
                                 f"{limits[0]}-{limits[1]}, so {list(band)} "
                                 f"can never be met")
        return cls(name, race, gender, klass, alignment,
                   {str(k).lower(): int(v) for k, v in classes.items()}, band)

    @property
    def class_bits(self) -> int:
        bits = 0
        for part in self.class_parts:
            bits |= CLASS_BIT_FOR_NAME[part]
        return bits

    @property
    def class_parts(self) -> list[str]:
        return [p.lower() for p in self.cls.split("/")]


def load_specs(path: pathlib.Path) -> list[Spec]:
    return [Spec.from_json(d) for d in json.loads(pathlib.Path(path).read_text())]


def check_specs(specs: list[Spec]) -> None:
    """Refuse, before any key is pressed, a party the driver cannot build.

    A class the race is never offered, or an alignment the class is never offered,
    stops the run here rather than after the characters before it are made.  A
    roll that trims an otherwise valid class list is only seen on the screen.
    """
    if not specs:
        raise Lost("the spec names no characters")
    names = [s.name for s in specs]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise Lost(f"a name is used twice: {dupes}; the ADD list and the "
                   f"exports are found by name")
    crossed = sorted({a for a in names for b in names if a != b and a in b})
    if crossed:
        raise Lost(f"a name is part of another name: {crossed}; the ADD list "
                   f"selects the first row containing the text")
    for spec in specs:
        shown = CLASSES_BY_RACE[spec.race]
        if spec.cls not in shown:
            raise LabelProblem(f"{spec.name}: a {spec.race} is never offered "
                               f"{spec.cls}; its class list is {list(shown)}")
        offered = alignments_offered(spec.cls)
        if spec.alignment not in offered:
            raise LabelProblem(f"{spec.name}: {spec.cls} is never offered "
                               f"{spec.alignment}; its alignment list is "
                               f"{list(offered)}")


# -- reading a screen ---------------------------------------------------------


def _prompt_row(s, prompt: str, rows=None) -> int | None:
    for r in range(25):
        if rows is not None and r not in rows:
            continue
        if prompt in s.row(r):
            return r
    return None


def recognise(sess, s) -> str | None:
    """Which screen of creation, the party menu or the save this is, or None."""
    if s is None:
        return None
    text = s.text()
    if any(phrase in text for phrase in REFUSALS):
        return REFUSED
    if sess.wanted_disk(s) is not None:
        return DISK
    row24 = s.row(24)
    if "PICK RACE" in text:
        return PICK_RACE
    if "PICK GENDER" in text:
        return PICK_GENDER
    if "PICK CLASS" in text:
        return PICK_CLASS
    if "PICK ALIGNMENT" in text:
        return PICK_ALIGN
    if "INPUT NAME OF CHARACTER" in text:
        return NAME
    if "SAVE?" in text:
        return SHEET
    if "CHANGE:" in row24:
        return PORTRAIT
    if "ICON:" in row24:
        return ICON
    if "ROLL AGAIN" in text:
        return ROLL
    if re.search(r"SAVE GAME:\s*YES", row24):
        return SAVE_YN
    if "SAVING" in text:
        return SAVING
    if _prompt_row(s, "ADD CHARACTER TO PARTY", ADD_PROMPT_ROWS) is not None:
        return ADD_LIST
    if "ENCAMP" in text:
        return WORLD
    if "CREATE NEW CHARACTER" in text or "BEGIN ADVENTURING" in text:
        return PARTY_MENU
    return None


#: The prompt each list draws under its entries, and where its labels start.
LISTS = {PICK_RACE: ("PICK RACE", RACE_COLUMN),
         PICK_GENDER: ("PICK GENDER", GENDER_COLUMN),
         PICK_CLASS: ("PICK CLASS", CLASS_COLUMN),
         PICK_ALIGN: ("PICK ALIGNMENT", ALIGN_COLUMN),
         ADD_LIST: ("ADD CHARACTER TO PARTY", ADD_STAR_COLUMN)}

#: The lists whose rows hold a label and nothing else.  The ADD list's rows may
#: lead with a star (`entries` strips one), so it is matched by containment.
EXACT_LISTS = (PICK_RACE, PICK_GENDER, PICK_CLASS, PICK_ALIGN)


def entries(s, kind: str) -> list[str] | None:
    """The labels a list shows, in order, or None for a screen that is no list.

    The prompt sits below the entries and moves with the list's length, so the
    entries are the non-blank rows between the top and the prompt.
    """
    if kind not in LISTS:
        return None
    prompt, column = LISTS[kind]
    at = _prompt_row(s, prompt, ADD_PROMPT_ROWS if kind == ADD_LIST else None)
    if at is None:
        return None
    out = []
    for r in range(LIST_FIRST_ROW, at):
        label = s.row(r)[column:column + LIST_WIDTH].strip().lstrip("*").strip()
        if label:
            out.append(label)
    return out


def scores(s) -> dict[str, int]:
    """The six ability scores on the roll screen, by record field name."""
    got = {m.group(1).lower(): int(m.group(2)) for m in RE_SCORE.finditer(s.text())}
    return {k: got[k] for k in ABILITIES if k in got}


def digest(s) -> bytes | None:
    return None if s is None else s.text().encode() + bytes(s.colours)


# -- the driver -----------------------------------------------------------------


class Driver:
    """The keystrokes of the front end, each waited on by what the screen says."""

    def __init__(self, sess, out: pathlib.Path, log, *, clock=time.monotonic,
                 sleep=time.sleep, deadline: float | None = None,
                 cleanup: float = CLEANUP_SECONDS, max_rolls: int = MAX_ROLLS):
        self.sess, self.out, self.log = sess, out, log
        self.max_rolls = max_rolls
        self.clock, self.sleep = clock, sleep
        self.limit = None if deadline is None else deadline - cleanup
        self.unrecognised_seconds = UNRECOGNISED_SECONDS
        self.select_timeout = SELECT_TIMEOUT
        self.poll = POLL
        self.shots = 0
        self.rolls: dict[str, dict[str, int]] = {}
        self.rolls_seen: dict[str, list[dict[str, int]]] = {}
        self.record_lines: list[str] = []

    # -- the clock ---------------------------------------------------------

    def spent(self) -> bool:
        return self.limit is not None and self.clock() >= self.limit

    def left(self, want: float) -> float:
        """WANT seconds, or what is left of the run when that is less."""
        if self.limit is None:
            return want
        return max(0.0, min(want, self.limit - self.clock()))

    def check(self, what: str) -> None:
        if self.spent():
            raise self.lost(f"the run's seconds were spent before {what}",
                            "deadline")

    # -- evidence ----------------------------------------------------------

    def capture(self, tag: str, s=None) -> None:
        if s is None:
            s = self.sess.screen()
        self.shots += 1
        stem = f"{self.shots:03d}-{re.sub(r'[^A-Za-z0-9]+', '-', tag).strip('-')}"
        shots = self.out / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        rows = None if s is None else [s.row(r).rstrip() for r in range(25)]
        (shots / f"{stem}.txt").write_text(
            "(bitmap)\n" if rows is None else "\n".join(rows) + "\n",
            encoding="utf-8")
        with contextlib.suppress(Exception):
            self.sess.kbd.screenshot(str(shots / f"{stem}.png"))
        self.log.emit("screen", tag=tag, stem=stem,
                      rows=[r for r in (rows or []) if r])

    def lost(self, why: str, tag: str = "lost", cls=Lost) -> Lost:
        self.capture(f"lost-{tag}")
        return cls(why)

    # -- waiting -------------------------------------------------------------

    def expect(self, kinds, timeout: float = WAIT, tag: str | None = None,
               before=None, again=None, retry_after: float | None = None):
        """Wait for a screen of one of KINDS, answering a disk prompt on the way.

        A refusal ends the run at once.  An unrecognised screen ends it once it
        has stood for `unrecognised_seconds`.  `again`, when given, is sent one
        more time if the screen still equals `before` after `retry_after`
        seconds: a key that provably did nothing, and only that.
        """
        kinds = (kinds,) if isinstance(kinds, str) else tuple(kinds)
        began = self.clock()
        end = began + self.left(timeout)
        unknown_since = None
        retried = again is None or retry_after is None
        last = None
        while self.clock() < end:
            s = self.sess.screen()
            last = s
            kind = recognise(self.sess, s)
            if kind == REFUSED:
                raise self.lost("the game refused: "
                                + " / ".join(r.strip() for r in s.rows()
                                             if any(p in r for p in REFUSALS)),
                                "refused")
            if kind in kinds:
                self.capture(tag or "-".join(kinds), s)
                return s
            if kind == DISK:
                self.sess.handle_prompt(s)
            if kind is None and s is not None:
                unknown_since = unknown_since if unknown_since is not None \
                    else self.clock()
                if self.clock() - unknown_since >= self.unrecognised_seconds:
                    raise self.lost(f"an unrecognised screen for "
                                    f"{self.unrecognised_seconds:g} s while "
                                    f"waiting for {kinds}", "unrecognised")
            else:
                unknown_since = None
            if (not retried and self.clock() - began >= retry_after
                    and digest(s) == before):
                retried = True
                self.log.emit("retry", waiting=kinds)
                again()
            self.sleep(self.poll)
        why = "the run's seconds were spent" if self.spent() else "timed out"
        shows = None if last is None else next(
            (r.strip() for r in last.rows() if r.strip()), "")
        raise self.lost(f"{why} waiting for {kinds}; the screen shows "
                        f"{recognise(self.sess, last)!r} ({shows!r})",
                        "deadline" if self.spent() else "timeout")

    # -- choosing ----------------------------------------------------------

    def choose(self, s, kind: str, label: str, then, *, column: int | None = None,
               timeout: float = WAIT, retry_after: float | None = RETRY_AFTER,
               tag: str | None = None):
        """Select LABEL in the list on screen S, then wait for a THEN screen.

        The label must be on screen.  A creation list's rows are bare labels,
        so they are matched whole (`MAGIC-USER/THIEF` is not the tail of
        `FIGHTER/MAGIC-USER/THIEF`); any other screen takes the first row
        containing the text, so in such a list an earlier row containing the
        label is refused before a key is pressed.
        """
        self.check(f"selecting {label}")
        shown = entries(s, kind)
        if shown is not None:
            if label not in shown:
                raise self.lost(f"{label} is not in the {kind} list {shown}",
                                "label", LabelProblem)
            if kind in EXACT_LISTS:
                # `select_row(exact=True)` needs a whole row equal to the label;
                # `entries` reads only a slice of each row.
                if S.Session._exact_hit(s, label) is None:
                    raise self.lost(f"no whole row of the {kind} list is "
                                    f"{label}: {shown}", "label", LabelProblem)
            else:
                earlier = next(e for e in shown if label in e)
                if earlier != label:
                    raise self.lost(f"{label} would select {earlier}, which "
                                    f"comes first in the {kind} list {shown}",
                                    "ambiguous", LabelProblem)
        elif not s.contains(label):
            raise self.lost(f"{label} is not on the {kind} screen",
                            "label", LabelProblem)
        self.log.emit("select", screen=kind, label=label, column=column)

        def act() -> bool:
            return self.sess.select_row(
                label, timeout=self.left(self.select_timeout), column=column,
                exact=kind in EXACT_LISTS)

        before = digest(s)
        if not act():
            raise self.lost(f"could not walk the highlight onto {label} in "
                            f"the {kind} list", "select")
        return self.expect(then, timeout, tag or f"{label}-then", before,
                           act, retry_after)

    def choose_bar(self, s, kind: str, label: str, then, *,
                   timeout: float = WAIT, tag: str | None = None):
        """Select LABEL on row 24, whose entries lie side by side."""
        self.check(f"selecting {label}")
        if label not in s.row(24):
            raise self.lost(f"{label} is not on the bar {s.row(24).strip()!r}",
                            "label", LabelProblem)
        self.log.emit("select", screen=kind, label=label, bar=True)
        if not self.sess.select_bar(label, timeout=self.left(self.select_timeout)):
            raise self.lost(f"could not walk the bar onto {label}", "select")
        return self.expect(then, timeout, tag or f"{label}-then")

    def back(self, then, tag: str = "back"):
        """One screen back: the left-arrow key through the KERNAL buffer."""
        self.check("going back")
        self.log.emit("kernal", code=BACK)
        self.sess.press_kernal(BACK)
        return self.expect(then, WAIT, tag)

    def read_scores(self, s) -> dict[str, int]:
        """The roll on screen, read twice so a half-drawn line is not kept."""
        first = scores(s)
        self.sleep(self.poll)
        again = scores(self.sess.screen())
        if len(first) != len(ABILITIES) or first != again:
            raise self.lost(f"the roll screen did not hold six steady scores: "
                            f"{first} then {again}", "roll")
        return first

    def roll_for(self, s, spec: Spec):
        """Roll until the constitution is in SPEC's band; keep the first roll
        when there is none.  Returns the ROLL screen the kept roll is on."""
        seen = self.rolls_seen[spec.name] = []
        roll = self.read_scores(s)
        seen.append(roll)
        self.log.emit("roll", name=spec.name, attempt=1, **roll)
        band = spec.constitution
        while band and not band[0] <= roll["constitution"] <= band[1]:
            if len(seen) >= self.max_rolls:
                low = min(r["constitution"] for r in seen)
                raise self.lost(
                    f"{spec.name}: no constitution in {list(band)} in "
                    f"{len(seen)} rolls; the lowest was {low}", "rolls")
            s = self.choose(s, ROLL, "ROLL AGAIN", ROLL, column=ROLL_COLUMN,
                            tag=f"{spec.name}-reroll")
            # The same roll twice is possible, so a screen still showing the
            # last roll after the wait is taken as it is.  A half-drawn screen
            # is not a new roll: all six scores must be there.
            end = self.clock() + self.left(REROLL_WAIT)
            while self.clock() < end:
                now = self.sess.screen()
                got = {} if now is None else scores(now)
                if len(got) == len(ABILITIES) and got != roll:
                    break
                self.sleep(self.poll)
            roll, s = self.settled_roll(s)
            seen.append(roll)
            self.log.emit("roll", name=spec.name, attempt=len(seen), **roll)
        self.rolls[spec.name] = roll
        return s

    def settled_roll(self, s, tries: int = 6):
        """The roll on the live screen once two reads a poll apart agree.

        A redraw still under way is read again, up to TRIES times, before it
        is a loss.  Returns the roll and the screen it was read from.
        """
        for _ in range(tries):
            first = self.sess.screen()
            self.sleep(self.poll)
            live = self.sess.screen()
            if (first is not None and live is not None
                    and len(scores(live)) == len(ABILITIES)
                    and scores(first) == scores(live)):
                return scores(live), live
        return self.read_scores(self.sess.screen() or s), self.sess.screen() or s

    # -- one character -----------------------------------------------------

    def to_pick_race(self):
        s = self.expect((PARTY_MENU, PICK_RACE), LOAD_WAIT, "start")
        if recognise(self.sess, s) == PARTY_MENU:
            # The overlay behind this key takes 3.4-12 s to draw, longer than
            # `RETRY_AFTER`, so a resend would land on PICK RACE.
            s = self.choose(s, PARTY_MENU, "CREATE NEW CHARACTER", PICK_RACE,
                            retry_after=None)
        return s

    def name_it(self, s, name: str):
        before = digest(s)
        self.log.emit("text", text=name)
        self.sess.kbd.text(name)
        began, retried = self.clock(), False
        while True:
            now = self.sess.screen()
            if now is not None and name in now.row(NAME_ROW):
                break
            if self.clock() - began >= 4.0:
                if retried or digest(now) != before:
                    raise self.lost(f"the name {name} did not reach the "
                                    f"name field", "name")
                retried = True
                self.log.emit("retry", waiting="the name")
                self.sess.kbd.text(name)
                began = self.clock()
            self.sleep(self.poll)
        self.sess.kbd.key("Return")
        return self.expect(SHEET, WAIT, f"{name}-named")

    def create(self, spec: Spec):
        """Create SPEC; return the PICK RACE screen the write ends on."""
        s = self.to_pick_race()
        s = self.choose(s, PICK_RACE, spec.race, PICK_GENDER,
                        column=RACE_COLUMN, tag=f"{spec.name}-race")
        s = self.choose(s, PICK_GENDER, spec.gender, ROLL,
                        column=GENDER_COLUMN, tag=f"{spec.name}-roll")
        s = self.roll_for(s, spec)
        s = self.choose(s, ROLL, "KEEP", PICK_CLASS, column=ROLL_COLUMN,
                        tag=f"{spec.name}-kept")
        s = self.choose(s, PICK_CLASS, spec.cls, PICK_ALIGN,
                        column=CLASS_COLUMN, tag=f"{spec.name}-class")
        s = self.choose(s, PICK_ALIGN, spec.alignment, NAME,
                        column=ALIGN_COLUMN, tag=f"{spec.name}-alignment")
        s = self.name_it(s, spec.name)
        s = self.choose(s, SHEET, "YES", PORTRAIT, column=YES_COLUMN,
                        timeout=LOAD_WAIT, retry_after=None,
                        tag=f"{spec.name}-portrait")
        s = self.choose_bar(s, PORTRAIT, "KEEP", ICON, timeout=LOAD_WAIT,
                            tag=f"{spec.name}-portrait-kept")
        return self.choose_bar(s, ICON, "EXIT", PICK_RACE, timeout=LOAD_WAIT,
                               tag=f"{spec.name}-written")

    # -- the party menu ------------------------------------------------------

    def leave_pick_race(self, s):
        return self.choose(s, PICK_RACE, "EXIT", PARTY_MENU,
                           column=RACE_COLUMN, tag="party-menu")

    def add_all(self, s, specs: list[Spec]):
        """ADD CHARACTER TO PARTY for each spec, then EXIT if the list is still up.

        The list stays up after every add, the last included, and EXIT is what
        leaves it.  A list that had closed itself is left alone: pressing EXIT
        at the party menu is not this driver's to do.
        """
        s = self.drawn_menu(s, "ADD CHARACTER TO PARTY")
        s = self.choose(s, PARTY_MENU, "ADD CHARACTER TO PARTY", ADD_LIST,
                        tag="add-open")
        for i, spec in enumerate(specs):
            s = self.choose(s, ADD_LIST, spec.name, (ADD_LIST, PARTY_MENU),
                            column=ADD_COLUMN, retry_after=None,
                            tag=f"add-{spec.name}")
            if recognise(self.sess, s) == PARTY_MENU:
                if i + 1 < len(specs):
                    raise self.lost(f"the ADD list closed after {spec.name} "
                                    f"with {len(specs) - i - 1} still to add",
                                    "add-closed")
                return s
            s = self.starred(spec.name)
        self.sleep(self.poll)
        s = self.sess.screen()
        if recognise(self.sess, s) == ADD_LIST:
            s = self.choose(s, ADD_LIST, "EXIT", PARTY_MENU, column=ADD_COLUMN,
                            tag="add-exit")
        else:
            s = self.expect(PARTY_MENU, WAIT, "add-closed")
        return s

    def drawn_menu(self, s, label: str):
        """The party menu once LABEL is on it.

        The menu is recognised by its first row, which is drawn before the rows
        below it, so the screen that ends a wait can still lack the entry the
        next step selects.  A label that never appears is left for `choose` to
        refuse.
        """
        end = self.clock() + self.left(MENU_DRAW_WAIT)
        while s is not None and not s.contains(label) and self.clock() < end:
            self.sleep(self.poll)
            s = self.sess.screen() or s
        return s

    def starred(self, name: str):
        """Wait for the star that says the game took NAME into the party."""
        end = self.clock() + self.left(WAIT)
        while self.clock() < end:
            s = self.sess.screen()
            if s is not None and any(f"*{name}" in row for row in s.rows()):
                self.capture(f"starred-{name}", s)
                return s
            self.sleep(self.poll)
        raise self.lost(f"{name} was never starred in the ADD list", "star")

    def save_party(self, s):
        s = self.drawn_menu(s, "SAVE CURRENT GAME")
        s = self.choose(s, PARTY_MENU, "SAVE CURRENT GAME", SAVE_YN,
                        tag="save-open")
        self.check("answering SAVE GAME")
        # The menu is still drawn under the bar when YES is taken, so the write
        # is waited on by its own `SAVING` text and only then for the menu.
        s = self.choose_bar(s, SAVE_YN, "YES", SAVING, tag="save-yes")
        return self.expect(PARTY_MENU, LOAD_WAIT, "saved")

    def copy_disk(self, name: str) -> pathlib.Path:
        """The save disk, re-attached so VICE lets go of the directory track
        it holds after a menu write, then copied once every entry is closed."""
        self.check(f"copying {name}")
        self.sess.attach(self.sess.save_disk)
        dest = self.out / name
        try:
            S.copy_closed_disk(self.sess.save_disk, dest)
        except RuntimeError as e:
            raise self.lost(str(e), "copy") from e
        self.log.emit("disk", name=name)
        return dest

    def enter_world(self, s, budget: float):
        """BEGIN ADVENTURING, the arrival, then a camp save.

        `Session.begin_adventuring` waits a fixed 240 s for the world bar, which
        the arrival can outlast, so its two calls are made here with `budget`.
        `Session.save_game` has fixed waits of about 200 s that the deadline
        cannot bound, and returns True even when EXIT never selects, so the
        save is confirmed from the disk: `intown.D64` must hold a `SAVEDGAME0`
        that differs from the one on `party.D64`.
        """
        self.check("BEGIN ADVENTURING")
        if not self.sess.select_row("BEGIN ADVENTURING",
                                    timeout=self.left(self.select_timeout)):
            raise self.lost("BEGIN ADVENTURING could not be selected", "begin")
        if not self.sess.wait_for_world(timeout=self.left(budget)):
            raise self.lost(f"the world bar did not come within {budget:g} s",
                            "world")
        self.capture("world")
        self.check("the camp save")
        if not self.sess.save_game():
            raise self.lost("the camp save was not taken", "camp-save")
        self.capture("camped")
        self.check("copying intown.D64")
        try:
            S.copy_closed_disk(self.sess.save_disk, self.out / "intown.D64")
        except RuntimeError as e:
            raise self.lost(str(e), "copy") from e
        before, after = (self._slot0(self.out / name)
                         for name in ("party.D64", "intown.D64"))
        if after is None or after == before:
            raise self.lost("the camp save did not land: intown.D64 holds "
                            + ("no SAVEDGAME0" if after is None
                               else "the SAVEDGAME0 of party.D64"), "camp-save")

    @staticmethod
    def _slot0(path: pathlib.Path) -> bytes | None:
        try:
            return D64.open(str(path)).read_file(b"SAVEDGAME0")
        except Exception:  # noqa: BLE001 -- a missing file and a bad chain both mean no save
            return None

    # -- the two passes --------------------------------------------------------

    def build(self, specs: list[Spec], enter_world: bool = False,
              world_budget: float = WORLD_BUDGET) -> None:
        check_specs(specs)
        s = None
        for spec in specs:
            s = self.create(spec)
            self.log.say(f"created {spec.name}")
        self.copy_disk("rolled.D64")
        s = self.leave_pick_race(s)
        s = self.add_all(s, specs)
        s = self.save_party(s)
        self.copy_disk("party.D64")
        self.record_lines = check_records(self.out / "rolled.D64",
                                          self.out / "party.D64", specs,
                                          self.rolls)
        (self.out / "records.txt").write_text(
            "\n".join(self.record_lines) + "\n", encoding="utf-8")
        for line in self.record_lines:
            self.log.say(line)
        if enter_world:
            self.enter_world(s, world_budget)

    def lists(self) -> dict:
        found: dict = {"classes": {}, "alignments": {}, "skipped": {}, "rolls": {}}
        s = self.to_pick_race()
        for race in RACES:
            s = self.choose(s, PICK_RACE, race, PICK_GENDER,
                            column=RACE_COLUMN, tag=f"{race}-gender")
            s = self.choose(s, PICK_GENDER, "MALE", ROLL, column=GENDER_COLUMN,
                            tag=f"{race}-roll")
            found["rolls"][race] = self.read_scores(s)
            s = self.choose(s, ROLL, "KEEP", PICK_CLASS, column=ROLL_COLUMN,
                            tag=f"{race}-kept")
            classes = entries(s, PICK_CLASS) or []
            found["classes"][race] = classes
            for cls in classes:
                if cls in found["alignments"] or cls in found["skipped"]:
                    continue
                try:
                    a = self.choose(s, PICK_CLASS, cls, PICK_ALIGN,
                                    column=CLASS_COLUMN,
                                    tag=f"{race}-{cls}-alignments")
                except LabelProblem as e:
                    found["skipped"][cls] = str(e)
                    continue
                found["alignments"][cls] = entries(a, PICK_ALIGN)
                s = self.back(PICK_CLASS, f"{race}-{cls}-back")
            self.back(ROLL, f"{race}-reroll")
            self.back(PICK_GENDER, f"{race}-gender-back")
            s = self.back(PICK_RACE, f"{race}-race-back")
        self.leave_pick_race(s)
        (self.out / "lists.json").write_text(json.dumps(found, indent=2) + "\n",
                                             encoding="utf-8")
        return found


# -- what the engine wrote ------------------------------------------------------


def _expected(spec: Spec, roll: dict[str, int] | None) -> dict:
    want = {"name": spec.name, "race": RACES[spec.race],
            "sex": GENDERS[spec.gender],
            "alignment": ALIGNMENTS.index(spec.alignment),
            "class_bits": spec.class_bits, "class_levels": spec.classes,
            "level": 1, "experience": 0}
    if roll:
        want.update(roll)
        # The rule `GEN $1F44` applies at creation, from the roll's own
        # constitution, so a sturdy race's bonus is checked as well.
        saves = levels.saving_throws(spec.classes, RACES[spec.race],
                                     roll["constitution"], "pool-of-radiance")
        want.update(zip(SAVE_FIELDS, saves or ()))
    return want


def _read(rec: CharacterRecord) -> dict:
    got = {"name": rec.name, "class_levels": derive.class_levels(rec)}
    for field in ("race", "sex", "alignment", "class_bits", "level",
                  "experience", *ABILITIES, *SAVE_FIELDS):
        got[field] = rec.get(field)
    return got


def _line(where: str, spec: Spec, rec: CharacterRecord | None,
          roll: dict[str, int] | None, error: str = "") -> tuple[str, bool]:
    if rec is None:
        return f"{spec.name} {where}: MISSING {error}".rstrip(), False
    got, want = _read(rec), _expected(spec, roll)
    bad = [f"{k} {got[k]!r} != {v!r}" for k, v in want.items() if got[k] != v]
    shown = "  ".join(f"{k}={v}" for k, v in got.items())
    return (f"{spec.name} {where}: {shown}"
            + ("   MISMATCH: " + "; ".join(bad) if bad else "   ok"), not bad)


def check_records(rolled: pathlib.Path, party: pathlib.Path, specs: list[Spec],
                  rolls: dict[str, dict[str, int]]) -> list[str]:
    """Compare what the engine wrote with the spec and the roll screen.

    The exports on `rolled` are whole records and the slots of `party` hold the
    first 256 bytes, which is every field compared.  Exceptional strength
    (`0x01A`) is not compared: the roll screen never shows it.  The last line
    is `all records match the spec` only when every field of every character
    agrees, every character has a roll and no name is used twice.
    """
    lines: list[str] = []
    ok = True
    names = [s.name for s in specs]
    for dupe in sorted({n for n in names if names.count(n) > 1}):
        lines.append(f"{dupe}: named twice in the spec   MISMATCH")
        ok = False
    exports, slots, export_error = None, {}, ""
    try:
        exports = D64.open(str(rolled))
    except Exception as e:  # noqa: BLE001 -- reported on the lines
        export_error = repr(e)
        lines.append(f"rolled.D64: cannot be read {export_error}   MISMATCH")
        ok = False
    try:
        _game, sg0, _sg1 = savegame.load_save(D64.open(str(party)))
        slots = {s.record.name.upper(): s.record for s in sg0.characters}
    except Exception as e:  # noqa: BLE001 -- reported on the lines
        lines.append(f"party.D64: cannot be read {e!r}   MISMATCH")
        ok = False
    for spec in specs:
        roll = rolls.get(spec.name)
        if roll is None:
            lines.append(f"{spec.name}: no roll was read   MISMATCH")
            ok = False
        rec, error = None, export_error
        try:
            if exports is None:
                raise OSError("rolled.D64 could not be read")
            rec = CharacterRecord.from_prg(
                exports.read_file(b"\x01" + spec.name.encode("latin-1")))
        except Exception as e:  # noqa: BLE001 -- reported on the line
            error = repr(e)
        line, good = _line("export", spec, rec, roll, error)
        lines.append(line)
        ok = ok and good
        line, good = _line("party", spec, slots.get(spec.name), roll)
        lines.append(line)
        ok = ok and good
    lines.append("all records match the spec" if ok else "SPEC MISMATCH")
    return lines


# -- running ------------------------------------------------------------------------


def new_summary(git: dict | None, argv: list[str] | None) -> dict:
    return {**(git or {"sha": "unknown", "dirty": []}),
            "argv": list(argv if argv is not None else sys.argv[1:]),
            "completed": False, "lost": None}


def write_summary(out: pathlib.Path, summary: dict) -> None:
    scratch.ensure(out)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str),
                                      encoding="utf-8")


def run(sess, out: pathlib.Path, *, lists: bool = False,
        specs: list[Spec] | None = None, enter_world: bool = False,
        world_budget: float = WORLD_BUDGET, max_seconds: float = 3600.0,
        max_rolls: int = MAX_ROLLS, argv: list[str] | None = None,
        git: dict | None = None, clock=time.monotonic, sleep=time.sleep,
        deadline: float | None = None, summary: dict | None = None) -> int:
    """One pass on a booted session; always writes `summary.json`.

    `summary`, when given, is filled in place so the caller can write it too.

    `deadline` is on `clock`; it defaults to `max_seconds` from now, and
    `main` sets it before the boot so the boot counts against it.
    """
    scratch.ensure(out)
    log = runlog.Log(out / "run.jsonl")
    if summary is None:
        summary = new_summary(git, argv)
    drv = Driver(sess, out, log, clock=clock, sleep=sleep,
                 deadline=clock() + max_seconds if deadline is None else deadline,
                 max_rolls=max_rolls)
    try:
        if lists:
            drv.lists()
            summary["completed"] = True
        else:
            drv.build(specs or [], enter_world, world_budget)
            lines = drv.record_lines
            summary["completed"] = lines[-1].startswith("all records")
            if not summary["completed"]:
                summary["lost"] = "SPEC MISMATCH: see records.txt"
    except Lost as e:
        summary["lost"] = str(e)
        log.emit("lost", why=str(e))
        log.say(f"lost: {e}")
    except Exception as e:  # noqa: BLE001 -- the run's own failure line
        summary["lost"] = repr(e)
        log.emit("failed", error=repr(e))
        log.say(f"failed: {e!r}")
        with contextlib.suppress(Exception):
            drv.capture("lost-error")
    finally:
        summary["rolls"] = drv.rolls
        summary["roll_counts"] = {
            name: {"count": len(seen),
                   "lowest": min(r["constitution"] for r in seen),
                   "highest": max(r["constitution"] for r in seen)}
            for name, seen in drv.rolls_seen.items() if seen}
        try:
            write_summary(out, summary)
        finally:
            log.close()
    return 0 if summary["completed"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--lists", action="store_true",
                      help="write every race's class list and every class's "
                           "alignment list")
    what.add_argument("--build", type=pathlib.Path, metavar="SPEC.json",
                      help="the party to create")
    ap.add_argument("--issue", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--disks", default=None,
                    help="where the player's disks are; read, never written")
    ap.add_argument("--pool", type=int, default=None,
                    help="demand this pool slot")
    ap.add_argument("--max-seconds", type=float, default=3600.0)
    ap.add_argument("--enter-world", action="store_true",
                    help="after the party save, BEGIN ADVENTURING and a camp "
                         "save")
    ap.add_argument("--world-budget", type=float, default=WORLD_BUDGET,
                    help="seconds to wait for the world bar after BEGIN "
                         "ADVENTURING")
    ap.add_argument("--max-rolls", type=int, default=MAX_ROLLS,
                    help="rolls made looking for a spec's constitution band "
                         "before the run gives up; each roll takes seconds, "
                         "so a large count needs a larger --max-seconds")
    args = ap.parse_args(argv)

    try:
        specs = load_specs(args.build) if args.build else None
    except (ValueError, KeyError, OSError) as e:
        raise SystemExit(f"spec: {e!r}")
    found = args.disks or gamedisks.find("pool-of-radiance")
    if not found:
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    git = evidence.git_state(ROOT)
    out = evidence.default_out(args.issue, args.run, git["sha"])

    runlog.catch_signals()
    deadline = time.monotonic() + args.max_seconds
    summary = new_summary(git, sys.argv[1:])
    slot = sess = None
    try:
        if specs is not None:
            # Before a slot is claimed or VICE booted, but with the summary
            # written, so a refused party leaves its reason in the evidence.
            check_specs(specs)
        slot = S.claim_slot(args.pool, f"{ISSUE_NOTE}/{args.issue}/{args.run}")
        first = S.stage_disks(slot, pathlib.Path(found))
        save = pathlib.Path(slot.dir) / "SIDE0.D64"
        D64.blank().save(str(save))
        scratch.ensure(out)
        shutil.copy(save, out / "blank.D64")
        sess = S.Session(first, slot=slot)
        sess.save_disk = str(save)
        with sess.watching_dialogs():
            if not sess.boot():
                raise SystemExit("boot failed")
            if sess.wait_text("LOAD SAVED GAME", 240)[0] is None:
                raise SystemExit("no party menu")
            return run(sess, out, lists=args.lists, specs=specs,
                       enter_world=args.enter_world,
                       world_budget=args.world_budget,
                       max_seconds=args.max_seconds, max_rolls=args.max_rolls,
                       argv=sys.argv[1:], git=git,
                       deadline=deadline, summary=summary)
    except SystemExit as e:
        summary["lost"] = summary["lost"] or str(e.code)
        raise
    except Lost as e:
        summary["lost"] = str(e)
        raise SystemExit(f"spec: {e}") from e
    except Exception as e:
        summary["lost"] = summary["lost"] or repr(e)
        raise
    finally:
        # The emulator and the slot are let go first, so a summary that cannot
        # be written does not leave VICE running or the slot leased.  A stop
        # before `run` (boot failed, no party menu, a staging error) still
        # leaves the evidence directory a summary.
        try:
            if sess is not None:
                with contextlib.suppress(Exception):
                    sess.terminate()
            if slot is not None:
                try:
                    slot.teardown()
                finally:
                    slot.release()
        finally:
            write_summary(out, summary)


if __name__ == "__main__":
    sys.exit(main())
