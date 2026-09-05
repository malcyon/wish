#!/usr/bin/env python3
"""Climb a DOS Pool of Radiance party a level at a time through the game's own
four training schools, one boot per level, keeping every record the trainer
writes.

`#249 (Build a DOS party from creation and level it ourselves, so DOS
measurements rest on records we watched being written)` has the six characters
`tools/dosparty.py` rolled and one level-up out of the clerics' school.  This
is the ladder: it visits **all four** schools in one boot -- clerics `(5,0)`,
magic users `(7,0)`, fighters `(8,0)`, thieves `(9,0)` -- so every character in
the party gains a level per rung, and it re-stages experience and gold between
rungs because the trainer clamps experience so hard that nobody can train twice
on one staging.

**What is ours and what is the engine's.**  `.claude/rules/testing.md` draws
the line and this tool keeps to it: **experience and gold are inputs we write**
before each rung, and prove nothing about the game.  Everything the trainer
computes from them -- level, `class_levels`, `hp_max`, `hp_rolled`, THAC0,
saving throws, spell slots, thief skills, and the experience it *leaves* --
is the engine's, and the per-rung record diff is the measurement.

**The route is computed, not memorised.**  Area 11 has no map of its own: it
reuses `GEO00`, so the walls are New Phlan's own and `goldbox.geo` answers
which way the party can step.  The schools are the squares `ECL0B` dispatches
on (`docs/50-experiments.md`, P18), and a breadth-first search over the thirteen
squares of the hall turns "go to the thieves' school" into turns and steps.
Nothing is pressed blind: a step that does not bring the map's command bar back
is a prompt, and it is photographed and pressed through by name.

    tools/dosladder.py --party $WISH_SPECIMENS/por-dos/WISH-SPEC-por-party-trained-c2 \\
        --rungs 4 --xp 300000 --gold 20000 --out work/issue249/ladder

The party starts wherever the save it was handed says -- a save the trainer
wrote is inside the hall already, so no walk into the hall is needed and the
`(7,2)`-facing-west entry `tools/dostrain.py` documents is only for a save made
outside one.  `--enter` does that walk when it is wanted.

Output goes under `work/`, which is gitignored and has been lost twice: **copy
a rung worth keeping into `$WISH_SPECIMENS` with `tools/specimens.py add`
before the slot goes down.**
"""

from __future__ import annotations

import argparse
import atexit
import json
import pathlib
import shutil
import signal
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automap import maps  # noqa: E402
from goldbox import dos  # noqa: E402
from goldbox import dos_savegame as _sav  # noqa: E402
from tools import dosbox  # noqa: E402
from tools.dosparty import wipe_roster  # noqa: E402
from tools.dostrain import move_to  # noqa: E402
from tools.dostrainprobe import install  # noqa: E402

#: The training hall's own squares, by what `ECL0B` does on each.  Taken from
#: `docs/50-experiments.md` P18, which read them out of the script's
#: `ONGOTO [$9800], 9` after `SUB 10`, and corroborated here by `GEO00`'s
#: script ids: (5,0) is 12, (7,0) 13, (8,0) 16, (9,0) 17, exactly as that table
#: says.  `check_hall` asserts it against the player's own disk at run time.
SCHOOLS = {
    (5, 0): "cleric",
    (7, 0): "magic-user",
    (8, 0): "fighter",
    (9, 0): "thief",
}
SCRIPT_IDS = {(5, 0): 12, (6, 0): 11, (7, 0): 13, (8, 0): 16, (9, 0): 17,
              (6, 1): 10, (7, 1): 14, (8, 1): 15, (9, 1): 18,
              (6, 2): 10, (7, 2): 14, (8, 2): 14, (9, 2): 14}
#: Every square the hall's script covers.  A route that leaves this set has
#: left the training hall, so the search is confined to it.
HALL = set(SCRIPT_IDS)

#: 0 N, 1 E, 2 S, 3 W -- the save's facing byte divided by `FACING_SCALE`.
STEPS = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}
COMPASS = "NESW"


def check_hall(geo) -> list[str]:
    """Compare `SCRIPT_IDS` against the player's own `GEO00`.

    Returns the disagreements.  An empty list is a free corroboration of the
    school squares every route here depends on; anything in it means the map
    this tool is routing over is not the map it was written against, and the
    run should stop rather than walk into a wall.
    """
    bad = []
    for square, want in sorted(SCRIPT_IDS.items()):
        got = geo.script_id(*square)
        if got != want:
            bad.append(f"{square} script {got}, expected {want}")
    return bad


def route(geo, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
    """The shortest legal walk from `start` to `goal` inside the hall."""
    if start == goal:
        return [start]
    seen = {start: None}
    queue = [start]
    while queue:
        here = queue.pop(0)
        for d, (dx, dy) in STEPS.items():
            nxt = (here[0] + dx, here[1] + dy)
            if nxt in seen or nxt not in HALL:
                continue
            if not geo.is_passable(here[0], here[1], d):
                continue
            seen[nxt] = here
            if nxt == goal:
                path = [nxt]
                while seen[path[-1]] is not None:
                    path.append(seen[path[-1]])
                return list(reversed(path))
            queue.append(nxt)
    raise ValueError(f"no route from {start} to {goal} inside the hall")


def turns(facing: int, want: int) -> list[str]:
    """The fewest Left/Right presses that turn `facing` into `want`."""
    diff = (want - facing) % 4
    if diff == 0:
        return []
    if diff == 1:
        return ["Right"]
    if diff == 3:
        return ["Left"]
    return ["Right", "Right"]


def direction(a: tuple[int, int], b: tuple[int, int]) -> int:
    for d, step in STEPS.items():
        if (a[0] + step[0], a[1] + step[1]) == b:
            return d
    raise ValueError(f"{a} and {b} are not neighbours")


def read_party(folder: pathlib.Path, letter: str | None = None
               ) -> list[dos.DosCharacter]:
    """Every `CHRDAT<letter><n>.SAV` in a folder, in slot order.

    A snapshot of `SAVE/` after a rung holds **several** parties -- the slot
    the rung loaded and one per school it saved at -- so a caller that wants
    one of them says which letter.  Reading them all mixes two states of the
    same six characters and diffs them against each other.
    """
    pat = f"CHRDAT{letter.upper()}?.SAV" if letter else "CHRDAT*.SAV"
    files = sorted(folder.glob(pat), key=lambda p: p.name[7:8])
    return [dos.read_character(p) for p in files]


def source_letter(party: pathlib.Path) -> str:
    """Which slot letter a party directory is named for.

    **The save names its own character files.**  `SAVGAM<letter>.DAT`'s party
    table at `PARTY_TABLE` holds `CHRDAT<letter>1` .. `CHRDAT<letter>6` as
    counted strings, so installing a party under a *different* letter renames
    the files out from under the names still written in the container.  Loading
    one is asking the engine for six files that are not there.  So a rung
    installs under the letter its input already uses.
    """
    for p in sorted(party.iterdir()):
        if p.name.upper().startswith("SAVGAM") and p.suffix.upper() == ".DAT":
            return p.name.upper()[6]
    raise ValueError(f"no SAVGAM<letter>.DAT in {party}")


def extract(snap: pathlib.Path, letter: str, dest: pathlib.Path) -> pathlib.Path:
    """Copy one slot's files out of a snapshot, so the next rung loads one party."""
    dest.mkdir(parents=True, exist_ok=True)
    letter = letter.upper()
    for p in sorted(snap.iterdir()):
        name = p.name.upper()
        if name.startswith(f"CHRDAT{letter}") or name == f"SAVGAM{letter}.DAT":
            shutil.copy(p, dest / p.name)
    return dest


def line(c: dos.DosCharacter) -> str:
    return (f"{c.name:8s} lvl={c.get('level'):2d} {c.class_levels} "
            f"xp={c.get('experience'):7d} hp={c.get('hp_max'):3d} "
            f"rolled={c.get('hp_rolled'):3d} thac0={c.get('thac0_base'):3d} "
            f"gold={c.get('gold'):6d}")


def plan(party: list[dos.DosCharacter]) -> dict[str, list[int]]:
    """Which roster positions to train at which school, one class each.

    A character with more than one class trains **the class it is furthest
    behind in**, so a multi-class character climbs its classes in turn rather
    than one of them running away.  One training per character per rung: the
    trainer's experience clamp makes a second one impossible on one staging,
    measured in `#249`.
    """
    want: dict[str, list[int]] = {}
    for i, c in enumerate(party, start=1):
        levels = c.class_levels
        if not levels:
            continue
        cls = min(levels, key=lambda k: (levels[k], k))
        want.setdefault(cls, []).append(i)
    return want


def stage_experience(save_dir: pathlib.Path, letter: str,
                     party: list[dos.DosCharacter], want: dict[str, list[int]],
                     flat: int, margin: int) -> dict[str, int]:
    """Write each record the experience for **one** level and no more.

    The flat staging every earlier run used -- 300,000 into every record --
    cannot tell the trainer's clamp apart from a price: whatever it does, a
    number that large comes out at the cap.  This writes
    `threshold(next level) + margin` instead, which is below the cap the
    trainer clamps to, so the two readings predict different bytes:

    * **the clamp trims a surplus** -- the record keeps what it went in with,
      less nothing, and reads `threshold + margin` afterwards;
    * **training is paid for** -- the record reads `margin`, or `threshold +
      margin` less some price.

    **A multi-class character is staged from the class it is about to train**,
    at that class's own single-class threshold, which is a second question in
    the same boot: if the school trains it, a multi-class character is not
    asked for a multiple of the threshold; if it refuses, it is.
    Returns what each record was given, so the run's log says which number is
    ours.
    """
    from goldbox import levels
    from tools.dostrainprobe import XP_AT, XP_SIZE

    staged: dict[str, int] = {}
    for i, c in enumerate(party, start=1):
        cls = next((k for k, v in want.items() if i in v), None)
        value = flat
        if cls is not None:
            thr = levels.next_threshold(cls, c.class_levels[cls])
            if thr is not None:
                value = thr + margin
        path = save_dir / f"CHRDAT{letter.upper()}{i}.SAV"
        data = bytearray(path.read_bytes())
        data[XP_AT:XP_AT + XP_SIZE] = int(value).to_bytes(XP_SIZE, "little")
        path.write_bytes(bytes(data))
        staged[c.name] = value
    return staged


class Ladder:
    """One boot: walk the hall, train, save, and write down what happened."""

    def __init__(self, session: dosbox.Session, game: dosbox.PoolOfRadiance,
                 geo, out: pathlib.Path, log: pathlib.Path,
                 at: tuple[int, int, int], gap: float = 0.8):
        self.s = session
        self.g = game
        self.geo = geo
        self.out = out
        self.logfile = log
        self.x, self.y, self.facing = at
        self.gap = gap
        self.n = 0
        self.world = game.world_bar or game.bar()
        #: Which roster line the highlight is on, 1-6.  **It survives the
        #: menu closing**: a school opened after another school opens with the
        #: highlight where the last one left it, not on the first character.
        #: One rung was spent training whoever was two lines below the last
        #: trainee.  `End` moves it down and wraps from 6 back to 1, so the
        #: count from any line to any other is `(want - here) % 6`.
        self.cur = 1
        #: The party menu's own command bar, captured when a school opens it.
        self.menu: str | None = None

    # -- bookkeeping ----------------------------------------------------

    def log(self, **kw: object) -> None:
        kw["t"] = round(time.time(), 3)
        with self.logfile.open("a") as fh:
            fh.write(json.dumps(kw) + "\n")
        print(json.dumps(kw), flush=True)

    def shot(self, name: str) -> None:
        self.s.shot(f"{self.n:03d}-{name}", allow_blank=True)
        self.n += 1

    def press(self, key: str, name: str | None = None) -> str:
        self.s.key(key)
        time.sleep(self.gap)
        screen = self.s.settle(quiet=0.5, timeout=20.0)
        self.shot(name or key)
        return screen.digest()

    def press_until_change(self, key: str, tries: int = 5) -> bool:
        """Press until the screen differs, up to `tries`.

        **The first keypress after a redraw is reliably swallowed here** --
        `docs/70-driving-the-game.md` reports the same on the C64 -- and a lost
        `End` in the roster panel trains the character one line above the one
        the run meant, which is a measurement of somebody else.
        """
        before = self.s.capture().digest()
        for _ in range(tries):
            if self.press(key) != before:
                return True
        return False

    # -- the map --------------------------------------------------------

    def face(self, want: int) -> None:
        for key in turns(self.facing, want):
            self.g.move(key)
            self.shot(f"turn-{key}")
        self.facing = want

    def step_plain(self, to: tuple[int, int]) -> None:
        """Step onto a square that is not a school, and clear what it prints."""
        self.face(direction((self.x, self.y), to))
        ok = self.g.move("Up")
        self.x, self.y = to
        self.shot(f"at-{to[0]}-{to[1]}")
        if not ok:
            self.clear_prompt(to)
        self.log(event="step", square=list(to), facing=COMPASS[self.facing],
                 script=SCRIPT_IDS.get(to), prompt=not ok)

    def clear_prompt(self, at: tuple[int, int]) -> None:
        """A step that did not bring the command bar back walked into something.

        `n` declines an offer, `Return` dismisses a message, `Escape` backs out
        of a menu -- pressed in that order and logged by name, because *which*
        one was needed is the finding.
        """
        for key in ("Return", "n", "Escape", "Return", "n", "Escape"):
            if self.g.bar() == self.world:
                return
            self.press(key, f"clear-{key}")
            self.log(event="prompt", square=list(at), key=key)
        raise TimeoutError(f"the command bar never came back at {at}")

    def enter_school(self, square: tuple[int, int]) -> bool:
        """Step onto a school square and answer YES to its offer to train.

        Returns whether the party menu came up.  A school reached without a
        prompt is stepped off and back on, which is what opens it on the C64
        when the party arrived by a route that did not dispatch.
        """
        self.face(direction((self.x, self.y), square))
        self.g.move("Up")
        self.x, self.y = square
        self.shot(f"school-{square[0]}-{square[1]}")
        if self.g.bar() == self.world:
            # The first keypress after a redraw is reliably swallowed, and a
            # school square is a dead end -- forward is a wall -- so pressing
            # `Up` again either arrives or does nothing at all.
            self.g.move("Up")
            self.shot(f"school-again-{square[0]}-{square[1]}")
        if self.g.bar() == self.world:
            self.log(event="school-silent", square=list(square))
            back = (self.x - STEPS[self.facing][0], self.y - STEPS[self.facing][1])
            self.step_plain(back)
            self.face(direction((self.x, self.y), square))
            self.g.move("Up")
            self.x, self.y = square
            self.shot(f"school-retry-{square[0]}-{square[1]}")
            if self.g.bar() == self.world:
                self.log(event="school-refused", square=list(square))
                return False
        self.press("y", "school-yes")
        self.menu = self.s.capture().ink(dosbox.BAR)
        return True

    def back_to_menu(self, tries: int = 8) -> bool:
        """Press until `CHOOSE A FUNCTION` is on the bar again.

        **A magic-user who gains a level chooses a spell before the menu comes
        back.**  The screen is `<NAME>'S SPELLS TO CHOOSE FROM` with
        `CHOOSE SPELL: LEARN` on the bar, and until it is answered every key
        the run presses lands in it -- which is what made a `SAVE CURRENT
        GAME` write nothing and `BEGIN ADVENTURING` never reach the map.  `l`
        is LEARN and takes the spell the game has highlighted.
        """
        for i in range(tries):
            if self.menu is None or self.s.capture().ink(dosbox.BAR) == self.menu:
                return True
            key = ("l", "l", "Return", "Escape")[i % 4]
            self.press(key, f"back-{key}")
            self.log(event="after-training", key=key)
        return False

    # -- the party menu -------------------------------------------------

    def train(self, want: list[int], school: str) -> list[dict]:
        """Train the roster positions in `want`, in order, at an open school.

        `End` moves the highlight down a line and wraps at the bottom, and
        where it starts is wherever the last menu left it -- so the count is
        `(want - here) % 6` and the tool tracks `here` across the whole boot.
        A `t` that leaves the screen exactly as it was is the school refusing
        the character -- there is no message left on a settled screen -- and a
        `t` that changes it is the confirmation `<NAME> WILL BECOME: A LEVEL n
        <CLASS>`, which `y` accepts.
        """
        results = []
        for idx in sorted(want):
            for _ in range((idx - self.cur) % 6):
                self.press_until_change("End")
            self.cur = idx
            before = self.s.capture().digest()
            after = self.press("t", f"t-{idx}")
            if after == before:
                after = self.press("t", f"t-{idx}-again")
            if after == before:
                self.log(event="refused", school=school, slot=idx)
                results.append({"slot": idx, "school": school, "trained": False})
                continue
            self.press("y", f"train-{idx}")
            self.back_to_menu()
            self.log(event="trained", school=school, slot=idx)
            results.append({"slot": idx, "school": school, "trained": True})
        return results

    def save_to(self, letter: str, expect: tuple[int, int] | None = None) -> bool:
        """`SAVE CURRENT GAME` from the party menu, to a slot letter."""
        path = self.s.save_file(letter)
        was = path.read_bytes() if path.is_file() else None
        self.press("s", f"save-{letter}")
        self.press(letter.lower(), f"save-{letter}-slot")
        deadline = time.time() + 30.0
        while time.time() < deadline:
            if path.is_file() and path.read_bytes() != was:
                dosbox.settle_files(self.s.save_dir, timeout=20.0)
                data = path.read_bytes()
                pos = (data[_sav.POS_X], data[_sav.POS_Y],
                       data[_sav.POS_FACING] // _sav.FACING_SCALE)
                # **The save says where the party was.**  The route is driven
                # blind otherwise -- nothing on the screen is read as text --
                # so the square the engine writes into `POS_X`/`POS_Y` is the
                # one measurement that proves the walk went where it meant to.
                self.log(event="saved", slot=letter, square=[pos[0], pos[1]],
                         facing=COMPASS[pos[2] % 4],
                         area=_sav.word(data, _sav.SCRIPT),
                         expected=list(expect) if expect else None,
                         where_expected=expect is None or tuple(pos[:2]) == expect,
                         train_level=int.from_bytes(data[0xD51:0xD53], "little"))
                return True
            time.sleep(0.3)
        self.log(event="save-failed", slot=letter)
        return False

    def leave_menu(self) -> None:
        """`BEGIN ADVENTURING` back onto the map."""
        for _ in range(4):
            self.press("b", "begin")
            if self.g.bar() == self.world:
                return
        raise TimeoutError("BEGIN ADVENTURING never got back to the map")

    def visit(self, square: tuple[int, int], want: list[int],
              letter: str) -> list[dict]:
        """Walk to a school, train, save, and step back onto the map.

        A party already standing on the school -- which is where the last rung
        left it -- steps off and back on, because the script fires on arrival
        and standing still is not one.
        """
        if (self.x, self.y) == square:
            for d, (dx, dy) in STEPS.items():
                nxt = (square[0] + dx, square[1] + dy)
                if nxt in HALL and self.geo.is_passable(square[0], square[1], d):
                    self.step_plain(nxt)
                    break
            else:
                raise ValueError(f"nowhere to step off {square}")
        for nxt in route(self.geo, (self.x, self.y), square)[1:-1]:
            self.step_plain(nxt)
        if not self.enter_school(square):
            return []
        results = self.train(want, SCHOOLS[square])
        self.back_to_menu()
        if any(r["trained"] for r in results):
            self.save_to(letter, square)
        self.leave_menu()
        return results


def snapshot(session: dosbox.Session, out: pathlib.Path, tag: str) -> pathlib.Path:
    d = out / tag
    d.mkdir(parents=True, exist_ok=True)
    for p in sorted(session.save_dir.iterdir()):
        if p.name.upper() == "EXPLORED.DAT":
            continue
        shutil.copy(p, d / p.name)
    return d


def rung(party: pathlib.Path, out: pathlib.Path, letter: str, xp: int | None,
         gold: int | None, at: str | None, gap: float,
         save_letters: str, mode: str = "flat",
         margin: int = 7) -> tuple[pathlib.Path, str | None]:
    """One boot: install, load, visit every school the party needs, save."""
    out.mkdir(parents=True, exist_ok=True)
    log = out / "run.jsonl"
    geo = maps.load_maps()["GEO00"]
    bad = check_hall(geo)
    if bad:
        raise SystemExit("GEO00 is not the map this tool routes over: "
                         + "; ".join(bad))

    slot = dosbox.claim("issue249 ladder")
    session = dosbox.Session(slot, dosbox.find_game())

    def cleanup(*_: object) -> None:
        session.close()
        slot.release()

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    session.stage(fresh=True)
    shutil.rmtree(session.dir / "shots", ignore_errors=True)
    (session.dir / "shots").mkdir(parents=True, exist_ok=True)
    wipe_roster(session.save_dir)
    install(party, session.save_dir, letter, None,
            None if mode == "threshold" else xp, gold)
    if at:
        move_to(session.save_dir / f"SAVGAM{letter.upper()}.DAT", at)

    party_now = read_party(session.save_dir, letter)
    want = plan(party_now)
    staged = None
    if mode == "threshold":
        staged = stage_experience(session.save_dir, letter, party_now, want,
                                  xp or 300000, margin)
        party_now = read_party(session.save_dir, letter)
    snapshot(session, out, "before")
    start = (session.save_dir / f"SAVGAM{letter.upper()}.DAT").read_bytes()
    here = (start[_sav.POS_X], start[_sav.POS_Y],
            start[_sav.POS_FACING] // _sav.FACING_SCALE)

    try:
        session.boot(fresh=False)
        last = None
        game = dosbox.PoolOfRadiance(session)
        game.to_main_menu()
        game.load_game(letter)
        session.shot("000-loaded", allow_blank=True)
        # **A save the trainer wrote loads back to the party menu, not the
        # map.**  `SAVE CURRENT GAME` is a party-menu command, and Pool of
        # Radiance puts you back where you saved from -- so a ladder whose
        # input is its own last rung starts at `CHOOSE A FUNCTION` and every
        # movement key it presses goes into a menu that ignores it.  One boot
        # was spent walking an imaginary party around the hall to learn that.
        # `b` is BEGIN ADVENTURING there and nothing on the map, so pressing it
        # and watching the command bar is both the test and the fix.
        was = game.bar()
        session.key("b")
        time.sleep(1.0)
        screen = session.settle(quiet=0.5, timeout=30.0)
        session.shot("000-begin", allow_blank=True)
        if screen.ink(dosbox.BAR) != was:
            game.world_bar = screen.ink(dosbox.BAR)
            game.world_glyphs = screen.glyphs(dosbox.BAR)
        ladder = Ladder(session, game, geo, out, log, here, gap)
        ladder.log(event="rung-start", party=[line(c) for c in party_now],
                   plan={k: v for k, v in want.items()}, start=list(here),
                   area=_sav.word(start, _sav.SCRIPT), mode=mode,
                   staged=staged)
        letters = iter(save_letters)
        for square, cls in SCHOOLS.items():
            if cls not in want:
                continue
            to = next(letters)
            try:
                results = ladder.visit(square, want[cls], to)
            except (TimeoutError, ValueError) as exc:
                # One school that will not close its menu must not cost the
                # rung the trainings that already happened and were saved.
                ladder.log(event="visit-failed", school=cls, error=str(exc))
                break
            if any(r["trained"] for r in results):
                last = to
        ladder.log(event="rung-end", last_save=last, square=[ladder.x, ladder.y])
    finally:
        shots = out / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        for png in sorted((session.dir / "shots").glob("*.png")):
            shutil.copy(png, shots / png.name)
        after = snapshot(session, out, "after")
        session.close()
        slot.release()
    return after, last


def diff(before: pathlib.Path, after: pathlib.Path, was: str,
         now: str) -> list[str]:
    """A named per-field diff of every record, before against after."""
    out = []
    b = {c.name: c for c in read_party(before, was)}
    for c in read_party(after, now):
        was = b.get(c.name)
        if was is None:
            continue
        moved = []
        for name in sorted(set(was.fields) | set(c.fields)):
            x, y = was.get(name), c.get(name)
            if x != y:
                moved.append(f"{name} {x}->{y}")
        out.append(f"{c.name}: " + (", ".join(moved) if moved else "unchanged"))
    return out


def clamp_cap(class_levels: dict[str, int]) -> int | None:
    """What the trainer's experience clamp is predicted to leave behind.

    **The rule, from the levels a character had when `TRAIN` was pressed:**
    the largest, over its classes, of the threshold two levels above that
    class, less one.  A single-class character therefore comes out of a
    level-up one point short of its next level, which is why nobody can train
    twice on one staging of experience.

    Returns None where every class is near enough its ceiling that no such
    threshold exists -- Pool of Radiance stops a cleric at 6 -- which is a
    case nothing has measured yet rather than a rule.
    """
    from goldbox import levels

    caps = []
    for name, level in class_levels.items():
        row = levels.at_level(name, level + 2)
        if row is not None:
            caps.append(row.experience - 1)
    return max(caps) if caps else None


def save_order(log: pathlib.Path) -> list[str]:
    """The slot letters a rung saved to, in the order it saved them."""
    out = []
    if not log.is_file():
        return out
    for row in log.read_text().splitlines():
        try:
            event = json.loads(row)
        except ValueError:
            continue
        if event.get("event") == "saved":
            out.append(event["slot"])
    return out


def audit(root: pathlib.Path) -> list[str]:
    """Compare every rung's before and after against `clamp_cap`.

    The prediction is made from the *before* record and checked against the
    *after* one, so a rung that disagrees names itself.  Experience is the one
    field this can be done for: it is the only thing the trainer writes whose
    value is a function of what it found rather than of a die roll.
    """
    rows = ["rung character         classes before          staged  ->      left  predicted"]
    for out in sorted(root.glob("rung*")):
        if not (out / "before").is_dir() or not (out / "after").is_dir():
            continue
        letters = {p.name[6] for p in (out / "before").glob("CHRDAT?*.SAV")}
        was = {c.name: c for c in read_party(out / "before", sorted(letters)[0])}
        # Every save the rung took holds the whole party, so a character
        # appears once per school visited.  **The end state is the one the
        # *last* save wrote, and the letters are not in the order they were
        # written** -- a rung installed as F and saving to A, B, D, E leaves F
        # last alphabetically and it is the untouched copy the rung began
        # with, so an audit that sorts by letter reports that nothing changed.
        # `run.jsonl` records the order, which is the only place it exists.
        ends: dict[str, dos.DosCharacter] = {}
        for letter in save_order(out / "run.jsonl"):
            for now in read_party(out / "after", letter):
                ends[now.name] = now
        for name, now in ends.items():
            old = was.get(name)
            if old is None:
                continue
            trained = old.class_levels != now.class_levels
            moved = old.get("experience") != now.get("experience")
            if not trained and not moved:
                continue
            want = clamp_cap(old.class_levels)
            got = now.get("experience")
            if got == old.get("experience"):
                # Trained and the experience did not move: the clamp trims a
                # surplus rather than charging a price, so a record staged
                # below the cap comes back out holding what it went in with.
                mark = ("ok, below the cap" if want is None or got <= want
                        else f"ABOVE THE CAP {want}")
            else:
                mark = "ok" if want == got else f"MISMATCH want {want}"
            rows.append(
                f"{out.name:5s} {name:8s} {str(old.class_levels):44s} "
                f"{old.get('experience'):7d} -> {got:9d}  {mark}")
    return rows


def thac0_rows(root: pathlib.Path) -> list[str]:
    """What the DOS engine stored in `thac0_base` at every level it wrote.

    `goldbox/dos_layout.py` reads `0x02D` as `60 - THAC0`, and
    `goldbox/levels.py`'s rows are the **C64's**, expanded from `GEN $1F1F`.
    Comparing the two says whether the two ports agree, and one place they are
    known to be in question is magic-user and thief level 1, which the C64
    table gives as 21 against the published 20.

    Single-class characters only: a multi-class character's THAC0 is the best
    of its classes and would be comparing against the wrong row.
    """
    from goldbox import levels

    seen: dict[tuple[str, int], set[int]] = {}
    for out in sorted(root.glob("rung*")):
        for tag in ("before", "after"):
            folder = out / tag
            if not folder.is_dir():
                continue
            for letter in sorted({p.name[6] for p in folder.glob("CHRDAT?*.SAV")}):
                for c in read_party(folder, letter):
                    if len(c.class_levels) != 1:
                        continue
                    (name, level), = c.class_levels.items()
                    seen.setdefault((name, level), set()).add(c.get("thac0_base"))
    rows = ["class       level  stored  DOS THAC0  levels.py  agree"]
    for (name, level), values in sorted(seen.items()):
        row = levels.at_level(name, level)
        for stored in sorted(values):
            want = row.thac0 if row else None
            rows.append(f"{name:11s} {level:5d}  {stored:6d}  {60 - stored:9d}"
                        f"  {str(want):9s}  {60 - stored == want}")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--party", type=pathlib.Path)
    ap.add_argument("--audit", type=pathlib.Path, default=None,
                    help="read a finished run's rungs and check every "
                         "experience the trainer left against clamp_cap")
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "work" / "issue249" / "ladder")
    ap.add_argument("--save-letters", default="ABDEFGHIJ",
                    help="slot letters a boot may save to, one per school; the "
                         "letter the party is installed under is skipped")
    ap.add_argument("--rungs", type=int, default=1)
    ap.add_argument("--xp", type=lambda s: int(s, 0), default=300000,
                    help="experience staged into every record before a rung; "
                         "ours, an input, and evidence of nothing")
    ap.add_argument("--gold", type=lambda s: int(s, 0), default=20000)
    ap.add_argument("--xp-mode", choices=("flat", "threshold"), default="flat",
                    help="flat writes --xp into every record; threshold writes "
                         "one level's worth plus --margin into each "
                         "single-class record, which is what tells the "
                         "trainer's clamp apart from a price")
    ap.add_argument("--margin", type=int, default=7,
                    help="how far above the next threshold to stage")
    ap.add_argument("--enter", default=None, metavar="X,Y,FACING",
                    help="poke the party's position first, e.g. 7,2,W for a "
                         "save made outside the hall")
    ap.add_argument("--gap", type=float, default=0.8)
    args = ap.parse_args(argv)

    if args.audit:
        for row in audit(args.audit):
            print(row, flush=True)
        print(flush=True)
        for row in thac0_rows(args.audit):
            print(row, flush=True)
        return 0
    if args.party is None:
        ap.error("--party is required unless --audit is given")

    party = args.party
    for n in range(args.rungs):
        out = args.out / f"rung{n}"
        here = source_letter(party)
        letters = "".join(c for c in args.save_letters.upper() if c != here)
        after, last = rung(party, out, here, args.xp, args.gold,
                           args.enter if n == 0 else None, args.gap, letters,
                           args.xp_mode, args.margin)
        print(f"-- rung {n}, installed as slot {here}", flush=True)
        if last is None:
            print("   nobody trained; stopping rather than repeating a rung",
                  flush=True)
            return 1
        for row in diff(out / "before", after, here, last):
            print("  ", row, flush=True)
        for c in read_party(after, last):
            print("  ", line(c), flush=True)
        party = extract(after, last, out / "party")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
