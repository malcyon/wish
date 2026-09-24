#!/usr/bin/env python3
"""Load a Wish-written DOS save in the running game, act, and read the engine's resave.

The DOS driver of `docs/235-destination-game-acceptance-runs.md` (D1).  It
stages a whole save this project wrote the way `dossheetread.install_whole`
does, boots DOSBox headless and silent on a pooled slot, runs a step list,
and decodes what the engine wrote back:

    tools/dos/dosacceptance.py --title pool --save DIR --slot A \\
        --steps load camp 'rest 5m' 'save D' read \\
        --expect BRUTUS:1:42:1 --issue 661 --run bless

`--fixture-row SLOT=ID:OWNER:DURATION:MAGNITUDE` (hex, repeatable) replaces
`--save`: the committed C64 fixture party gets those effect rows and is
converted by Save As DOS (`editor.saveplan.prepare_save_as` and `publish`)
into `<out>/source/` before the boot, with the SHA, the file list and the
report's `dropped` and `losses` in the log.  With no `--steps` only that
conversion runs.

| step | what it does |
|---|---|
| `load` | title screens, `LOAD SAVED GAME`, the `--slot` letter; waits for the map |
| `camp` | `ENCAMP`; records the camp bar by `bar_signature` |
| `rest 5m`, `rest 1h30m`, `rest 2d` | camp `REST`, the rest time zeroed and set by key, then rested; minutes in fives |
| `save X` | camp `SAVE` to slot X, believed when `SAVGAMX.DAT` changes; declines the quit |
| `shot NAME` | one PNG and the screen digests, nothing pressed |
| `read` | copies `SAVE/` out and decodes every node and the clock of the installed slot and each saved one |

**The rest-time keys are read from Pool of Radiance's `GAME.OVR`**, overlay
unit `8C` at file offset `0x23DCC`, because nobody had captured the screen.
The rest menu (`0x244ED`) opens on the minutes field; `Y`, `H` and `M`
select days, hours and minutes; `I` adds one day or hour, or **five**
minutes; `D` takes the same away, borrowing, and **clamps at zero**: with
nothing above the field to borrow from, the whole time is zeroed
(`0x24246`).  `R` and `Return` rest, `E` leaves.  The camp's `REST`
(`0x17FAB`) presets the time to the longest memorisation the party has
queued, so it is zeroed from `D` at the days field before it is set.  A
rest takes five minutes off the time and adds five to the clock per pass
(`0x24A66`), so the clock in the resave is the check that the time was set
right.  **Any key pressed while resting asks `Stop Resting?`**, so nothing
is pressed until the camp bar is back.

Each key in the rest menu is believed only when the text window under the
viewport changes, and is pressed a second time at most; a key that changes
nothing twice stops the run with a PNG rather than being counted.

Evidence goes to `~/.cache/wish/acceptance/<issue>/<sha>-<run>/`: `run.jsonl`,
`summary.json`, `shots/`, `installed/` (the save as booted) and `resave/`
(the engine's `SAVE`).  Nothing is committed and the archives are read only.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_codec, world_state  # noqa: E402
from tools.dos import dosbox  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: The titles this driver can run, by the name `--title` takes, to the game
#: directory stem `dosbox.find_game` looks for.  Curse and Silver Blades come
#: next (`docs/235` §3, D1), once their rest menus are read.
TITLES = {"pool": "POOLRAD"}

# The camp bar is `Save View Magic Rest Alter Exit` (`START.EXE`), and its
# `Exit` is exit to DOS, so `e` is never pressed in camp.
ENCAMP = "e"
CAMP_SAVE = "s"
CAMP_REST = "r"
QUIT_NO = "n"

# The rest menu is `Rest daYs Hours Mins Inc Dec Exit` (`GAME.OVR` 0x244A5).
REST_DAYS = "y"
REST_HOURS = "h"
REST_MINS = "m"
REST_INC = "i"
REST_DEC = "d"
REST_GO = "r"
#: What one `Inc` or `Dec` moves the minutes field by (`GAME.OVR` 0x245CB).
REST_STEP = 5
#: The days field's ceiling (`GAME.OVR` 0x24192).
REST_DAYS_MAX = 99

#: The text window under the viewport and the command bar below it, where
#: the rest time is drawn (text row 17) and every rest-menu key shows.  The
#: viewport's picture is left out so nothing it draws reads as a keypress.
TEXT_WINDOW = (0, 120, 320, 80)

#: One character cell of the command bar.
CELL = 8


class StepFailed(RuntimeError):
    """A step did not reach the screen or the file it waits for."""


# --------------------------------------------------------------------------
# Pure parts: steps, durations, screens, and reading a save
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Step:
    kind: str
    text: str
    minutes: int = 0
    letter: str = ""
    name: str = ""


_DURATION = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$")


def parse_duration(text: str) -> int:
    """`5m`, `8h`, `2d` or a run of them such as `1h30m`, in minutes."""
    m = _DURATION.match(text.strip().lower())
    if not text.strip() or m is None or not any(m.groups()):
        raise ValueError(f"not a duration: {text!r} (say 5m, 8h, 2d or 1h30m)")
    d, h, mins = (int(g or 0) for g in m.groups())
    return (d * 24 + h) * 60 + mins


def rest_presses(minutes: int) -> tuple[int, int, int]:
    """(days, hours, five-minute presses) that set a rest of `minutes`."""
    if minutes <= 0:
        raise ValueError("a rest must be longer than no time at all")
    if minutes % REST_STEP:
        raise ValueError(f"the rest menu sets minutes in fives; {minutes} is not one")
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days > REST_DAYS_MAX:
        raise ValueError(f"the rest menu holds at most {REST_DAYS_MAX} days")
    return days, hours, mins // REST_STEP


def parse_step(text: str) -> Step:
    words = text.split()
    if not words:
        raise ValueError("an empty step")
    kind = words[0].lower()
    if kind in ("load", "camp", "read") and len(words) == 1:
        return Step(kind, text)
    if kind == "rest" and len(words) == 2:
        minutes = parse_duration(words[1])
        rest_presses(minutes)
        return Step(kind, text, minutes=minutes)
    if kind == "save" and len(words) == 2 and re.fullmatch(r"[A-Ja-j]", words[1]):
        return Step(kind, text, letter=words[1].upper())
    if kind == "shot" and len(words) == 2 and re.fullmatch(r"[\w-]+", words[1]):
        return Step(kind, text, name=words[1])
    raise ValueError(
        f"not a step: {text!r} (load, camp, 'rest 5m', 'save D', 'shot NAME', read)")


def validate_steps(steps: list[Step]) -> None:
    """Refuse an order the driver would only find out after booting DOSBox."""
    camped = False
    for step in steps:
        if step.kind == "camp":
            camped = True
        elif step.kind in ("rest", "save") and not camped:
            raise ValueError(f"{step.kind} needs camp first: {step.text!r}")


@dataclasses.dataclass(frozen=True)
class Expect:
    name: str
    id: int
    minutes: int
    data: int | None = None


def parse_expect(text: str) -> Expect:
    """`NAME:ID:MINUTES[:DATA]`, numbers decimal or `0x` hex."""
    parts = text.split(":")
    if len(parts) not in (3, 4) or not parts[0]:
        raise ValueError(f"not an expectation: {text!r} (NAME:ID:MINUTES[:DATA])")
    nums = [int(p, 0) for p in parts[1:]]
    return Expect(parts[0].upper(), nums[0], nums[1],
                  nums[2] if len(nums) == 3 else None)


def parse_row(text: str) -> tuple[int, int, int, int, int]:
    """`SLOT=ID:OWNER:DURATION:MAGNITUDE`, all hex, for `effects.write_effect`."""
    slot, sep, rest = text.partition("=")
    parts = rest.split(":")
    if not sep or len(parts) != 4:
        raise ValueError(f"not a row: {text!r} (SLOT=ID:OWNER:DURATION:MAGNITUDE, hex)")
    values = [int(slot, 16)] + [int(p, 16) for p in parts]
    if not 0 <= values[0] < 64 or any(not 0 <= v <= 0xFF for v in values[1:]):
        raise ValueError(f"row out of range: {text!r}")
    return tuple(values)  # type: ignore[return-value]


def bar_signature(screen: dosbox.Screen) -> str:
    """The command bar's words, blind to which word is highlighted.

    `Screen.glyphs` over the whole bar changes when the game moves its
    highlight block from one word to another, because the block's paper
    differs from the bar's.  Taken **one character cell at a time**, each
    cell measures its own paper, so a letter knocked out of the block and
    the same letter lit on black give the same bits.
    """
    x0, y, w, h = dosbox.BAR
    sha = hashlib.sha1()
    for x in range(x0, x0 + w, CELL):
        sha.update(screen.glyphs((x, y, CELL, h)).encode())
    return sha.hexdigest()[:16]


def node_dict(node: bytes) -> dict:
    return {"id": node[0], "minutes": node[1] | node[2] << 8,
            "data": node[3], "flag": node[4], "raw": node[:5].hex()}


def clock_total(digits: tuple[int, ...]) -> int:
    """Minutes from the clock digits: sub-minute, units, tens, hour, day, month.

    Months are counted as 30 days, the digit's own limit, so a difference of
    two readings is exact within a year.
    """
    _, units, tens, hour, day, month = digits[:6]
    return (((month * 30) + day) * 24 + hour) * 60 + tens * 10 + units


def read_slot(folder: pathlib.Path, letter: str) -> dict:
    """The clock and every character's effect nodes in one slot of `folder`."""
    savgam = (folder / f"SAVGAM{letter}.DAT").read_bytes()
    digits = world_state.from_dos(savgam).clock
    out = {"slot": letter, "clock": list(digits),
           "clock_minutes": clock_total(digits), "characters": []}
    for n in range(1, 9):
        path = folder / f"CHRDAT{letter}{n}.SAV"
        if not path.is_file():
            continue
        c = dos_codec.read_character(path)
        out["characters"].append({"name": c.name, "file": path.name,
                                  "nodes": [node_dict(e) for e in c.effects]})
    return out


def compare_nodes(before: dict, after: dict) -> list[dict]:
    """Each node of `before`, matched by character name and id in `after`.

    Two nodes of one id on one character are matched in file order.  A node
    only `after` holds is listed with `before` None.
    """
    rows = []
    after_by = {c["name"]: list(c["nodes"]) for c in after["characters"]}
    for c in before["characters"]:
        left = after_by.get(c["name"])
        for node in c["nodes"]:
            match = None
            if left is not None:
                for i, cand in enumerate(left):
                    if cand["id"] == node["id"]:
                        match = left.pop(i)
                        break
            rows.append({
                "name": c["name"], "id": node["id"],
                "before": node["minutes"], "data_before": node["data"],
                "after": None if match is None else match["minutes"],
                "data_after": None if match is None else match["data"],
                "lost": None if match is None else node["minutes"] - match["minutes"],
                "character_present": left is not None,
            })
    for name, nodes in after_by.items():
        for node in nodes:
            rows.append({"name": name, "id": node["id"], "before": None,
                         "data_before": None, "after": node["minutes"],
                         "data_after": node["data"], "lost": None,
                         "character_present": True})
    return rows


def judge(expect: Expect, after: dict) -> dict:
    """Whether `after` holds the node `expect` names, with its minutes and data."""
    who = [c for c in after["characters"] if c["name"].upper() == expect.name]
    base = {"expect": dataclasses.asdict(expect)}
    if not who:
        return {**base, "verdict": "refutes", "why": f"no {expect.name} in the resave"}
    nodes = [n for n in who[0]["nodes"] if n["id"] == expect.id]
    if not nodes:
        return {**base, "verdict": "refutes",
                "why": f"{expect.name} holds no node with id {expect.id}"}
    for n in nodes:
        if n["minutes"] == expect.minutes and (
                expect.data is None or n["data"] == expect.data):
            return {**base, "verdict": "accepts", "found": n}
    return {**base, "verdict": "refutes", "found": nodes,
            "why": f"{expect.name}'s id {expect.id} node holds "
                   + ", ".join(f"{n['minutes']} minutes data {n['data']:02X}"
                               for n in nodes)}


def install(save: pathlib.Path, save_dir: pathlib.Path, letter: str) -> dict:
    """Empty `save_dir` and put the one slot `save` holds into it as `letter`.

    The staged tree's own `SAVE` is the archives' copy, which is the edited
    play directory (`.claude/rules/testing.md`), so none of it is kept.
    """
    sources = sorted(p for p in save.iterdir() if re.fullmatch(
        r"SAVGAM[A-J]\.DAT", p.name.upper()))
    if len(sources) != 1:
        raise FileNotFoundError(
            f"{save} holds {len(sources)} SAVGAM?.DAT files; one is wanted")
    source = sources[0].name.upper()[6]
    for old in save_dir.glob("*"):
        if old.is_file():
            old.unlink()
    took = {"from_slot": source, "as_slot": letter.upper(), "files": []}
    for p in sorted(save.iterdir()):
        name = p.name.upper()
        if name == f"SAVGAM{source}.DAT":
            dest = f"SAVGAM{letter.upper()}.DAT"
        elif name.startswith(f"CHRDAT{source}"):
            dest = f"CHRDAT{letter.upper()}{name[7:]}"
        else:
            continue
        (save_dir / dest).write_bytes(p.read_bytes())
        took["files"].append(dest)
    return took


def default_out(issue: str, run: str, sha: str) -> pathlib.Path:
    return scratch.cache_dir("acceptance", issue, f"{sha[:10]}-{run}")


def git_state() -> dict:
    def git(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    dirty = [line[3:] for line in git("status", "--porcelain",
                                      "--untracked-files=no").splitlines()]
    return {"sha": git("rev-parse", "HEAD") or "unknown", "dirty": dirty}


# --------------------------------------------------------------------------
# The conversion: the fixture party, staged, through Save As DOS
# --------------------------------------------------------------------------


def build_source(rows: list[tuple[int, int, int, int, int]], out: pathlib.Path) -> dict:
    """Stage `rows` into the C64 fixture party and Save As DOS into `out/source`.

    The route is the editor's own, `prepare_save_as` then `publish`, as
    `tests/convert/test_runningeffects.py`'s `_dos_plan` prepares it.
    `prepare_save_as` refuses a conversion that would drop a field, which is
    reported as `refused` and ends the run before any boot.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from editor import roster, saveplan
    from editor.convert import Source
    from goldbox import effects
    from goldbox.c64_port import POOL_OF_RADIANCE
    from goldbox.savegame import SaveGame0, SaveGame1
    from tools.convert import convertdrops

    fixtures = REPO / "tests" / "fixtures"
    payload = bytearray(SaveGame0.from_prg(
        (fixtures / "savedgame0.bin").read_bytes()).to_bytes())
    save1 = SaveGame1.from_prg((fixtures / "savedgame1.bin").read_bytes()).to_bytes()
    for row in rows:
        effects.write_effect(payload, *row)
    disk = out / "source.d64"
    disk.write_bytes(dos_codec.save_disk(bytes(payload), save1,
                                         POOL_OF_RADIANCE).to_bytes())
    party = roster.Party(str(disk))
    source = Source.of_snapshot(saveplan.prepare(party))
    assets = saveplan.resolve_assets(source, "dos",
                                     game_files=convertdrops.game_files,
                                     dos_folder=dosbox.find_game("POOLRAD"))
    dest = out / "source"
    report: dict = {"rows": [list(r) for r in rows], "disk": disk.name}
    try:
        plan = saveplan.prepare_save_as(party, "dos", dest, assets)
    except saveplan.DroppedFields as e:
        return {**report, "refused": str(e)}
    report["dropped"] = list(plan.report.dropped)
    report["losses"] = list(plan.report.losses)
    saveplan.publish(plan, party)
    report["files"] = sorted(p.name for p in dest.iterdir())
    report["nodes"] = {
        p.name: [node_dict(p.read_bytes()[i:i + dos_codec.EFFECT_SIZE])
                 for i in range(0, p.stat().st_size - dos_codec.EFFECT_SIZE + 1,
                                dos_codec.EFFECT_SIZE)]
        for p in sorted(dest.glob("*.SPC")) if p.stat().st_size}
    return report


# --------------------------------------------------------------------------
# The driven part
# --------------------------------------------------------------------------


class Driver:
    """The steps, on one booted session of DOS Pool of Radiance.

    Every screen the driver waits at is logged with its `bar_signature`,
    `Screen.glyphs(BAR)` and whole-frame digest beside a PNG, which is what a
    later classifier row is written from.
    """

    def __init__(self, session, note, slot: str):
        self.s = session
        self.note = note
        self.slot = slot
        self.game = dosbox.PoolOfRadiance(session)
        self.camp_sig: str | None = None
        self.n = 0

    # -- evidence ----------------------------------------------------------

    def shot(self, label: str) -> str:
        self.n += 1
        name = f"{self.n:03d}-{label}"
        self.s.shot(name, allow_blank=True)
        screen = self.s.capture()
        self.note(event="screen", shot=f"{name}.png", bar=bar_signature(screen),
                  glyphs=screen.glyphs(dosbox.BAR), digest=screen.digest())
        return name

    def fail(self, label: str, why: str) -> StepFailed:
        name = self.shot(f"lost-{label}")
        return StepFailed(f"{why}; see {name}.png")

    # -- helpers -----------------------------------------------------------

    def text(self, quiet: float = 0.5) -> str:
        return self.s.settle(quiet=quiet, timeout=20.0).digest(TEXT_WINDOW)

    def press_changes(self, key: str, tries: int = 2, wait: float = 5.0) -> bool:
        """Press `key` until the text window changes, at most `tries` times.

        Each press is given `wait` seconds to show before the next, so a key
        the game was merely slow to draw is not pressed twice.
        """
        before = self.text()
        for _ in range(tries):
            self.s.key(key)
            if self.s.wait_for(lambda sc: sc.digest(TEXT_WINDOW) != before, wait):
                self.text()
                return True
        return False

    def in_camp(self, screen=None) -> bool:
        screen = screen if screen is not None else self.s.capture()
        return self.camp_sig is not None and bar_signature(screen) == self.camp_sig

    def wait_camp(self, timeout: float, hold: float = 1.0) -> bool:
        """Wait for the camp bar, and for it to still be there `hold` later."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.in_camp():
                time.sleep(hold)
                if self.in_camp():
                    return True
            time.sleep(0.3)
        return False

    # -- the steps ---------------------------------------------------------

    def load(self) -> dict:
        self.game.to_main_menu()
        self.shot("menu")
        try:
            self.game.load_game(self.slot)
        except TimeoutError as e:
            raise self.fail("load", str(e)) from None
        self.shot("loaded")
        return {"slot": self.slot, "status": self.game.status()}

    def camp(self) -> dict:
        world = self.game.world_bar or self.game.bar()
        self.s.key(ENCAMP)
        if not self.s.wait_while_ink(dosbox.BAR, world, 30.0):
            raise self.fail("camp", "ENCAMP did not change the command bar")
        screen = self.s.settle(quiet=1.5, timeout=30.0)
        self.camp_sig = bar_signature(screen)
        self.shot("camp")
        return {"camp_bar": self.camp_sig}

    def zero_rest_time(self, limit: int = 120) -> int:
        """Select days and press `Dec` until three presses change nothing.

        With days at zero the first `Dec` zeroes the whole time; with days
        above it each press takes one off and the next zeroes the rest.
        Three quiet presses in a row, not one, so a swallowed key is not
        read as the time having reached zero.
        """
        if not self.press_changes(REST_DAYS):
            raise self.fail("rest-days", "the days field did not take the highlight")
        before, still, presses = self.text(), 0, 0
        while still < 3:
            if presses >= limit:
                raise self.fail("rest-zero", f"{limit} presses of Dec never settled")
            self.s.key(REST_DEC)
            presses += 1
            now = self.text()
            still = still + 1 if now == before else 0
            before = now
        return presses

    def set_rest_time(self, minutes: int) -> dict:
        """From the days field at zero: days, then hours, then fives of minutes."""
        days, hours, fives = rest_presses(minutes)
        for _ in range(days):
            if not self.press_changes(REST_INC):
                raise self.fail("rest-inc-days", "Inc on days changed nothing")
        if not self.press_changes(REST_HOURS):
            raise self.fail("rest-hours", "the hours field did not take the highlight")
        for _ in range(hours):
            if not self.press_changes(REST_INC):
                raise self.fail("rest-inc-hours", "Inc on hours changed nothing")
        if not self.press_changes(REST_MINS):
            raise self.fail("rest-mins", "the minutes field did not take the highlight")
        for _ in range(fives):
            if not self.press_changes(REST_INC):
                raise self.fail("rest-inc-mins", "Inc on minutes changed nothing")
        return {"days": days, "hours": hours, "fives": fives}

    def rest(self, minutes: int) -> dict:
        if self.camp_sig is None:
            raise StepFailed("rest needs camp first")
        if not self.press_changes(CAMP_REST, wait=10.0):
            raise self.fail("rest-menu", "REST did not open the rest menu")
        self.shot("rest-menu")
        zeroed = self.zero_rest_time()
        self.shot("rest-zero")
        presses = self.set_rest_time(minutes)
        self.shot("rest-set")
        self.s.key(REST_GO)
        passes = minutes // REST_STEP
        if not self.wait_camp(timeout=60.0 + 2.0 * passes):
            raise self.fail("rest-end", "the camp bar never came back after resting "
                            "(interrupted, or a screen this driver does not know)")
        self.shot("rested")
        return {"asked": minutes, "zero_presses": zeroed, **presses}

    def save(self, letter: str) -> dict:
        if self.camp_sig is None:
            raise StepFailed("save needs camp first")
        path = self.s.save_file(letter)
        was = path.read_bytes() if path.is_file() else None
        camp_ink = self.s.capture().ink(dosbox.BAR)
        self.s.key(CAMP_SAVE)
        if not self.s.wait_while_ink(dosbox.BAR, camp_ink, 30.0):
            raise self.fail("save-which", "SAVE did not open the slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("save-which")
        self.s.key(letter.lower())
        deadline = time.time() + 60.0
        while not (path.is_file() and path.read_bytes() != was):
            if time.time() > deadline:
                raise self.fail("save-file", f"{path.name} never changed")
            time.sleep(0.3)
        dosbox.settle_files(self.s.save_dir, quiet=1.0, timeout=30.0)
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("saved")
        self.s.key(QUIT_NO)
        back = self.wait_camp(timeout=15.0)
        self.shot("after-save")
        return {"slot": letter, "file": path.name, "size": path.stat().st_size,
                "back_in_camp": back}


def run(args) -> int:
    git = git_state()
    out = pathlib.Path(args.out) if args.out else default_out(args.issue, args.run,
                                                              git["sha"])
    scratch.ensure(out)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    steps = [parse_step(s) for s in args.steps]
    expects = [parse_expect(e) for e in args.expect]
    summary: dict = {"title": args.title, "slot": args.slot.upper(),
                     "steps": args.steps, **git, "completed": False}
    note(event="start", out=str(out), **summary)

    def write_summary():
        (out / "summary.json").write_text(json.dumps(summary, indent=2))

    save = pathlib.Path(args.save) if args.save else None
    if args.fixture_row:
        shutil.rmtree(out / "source", ignore_errors=True)
        built = build_source([parse_row(r) for r in args.fixture_row], out)
        summary["source"] = built
        note(event="converted", **built)
        if "refused" in built or built["dropped"] or built["losses"]:
            summary["lost"] = "the conversion dropped or lost a field"
            write_summary()
            return 1
        save = out / "source"
    if not steps:
        summary["completed"] = True
        write_summary()
        return 0

    letter = args.slot.upper()
    saved: list[str] = []
    with contextlib.ExitStack() as stack:
        # Registered first so it runs last, and every callback runs even when an
        # earlier one raises: a failed close must not leave a slot leased.
        stack.callback(log.close)
        game = dosbox.find_game(TITLES[args.title])
        slot = dosbox.claim(args.note)
        stack.callback(slot.release)
        session = dosbox.Session(slot, game)
        stack.callback(session.close)

        def keep_evidence():
            write_summary()
            try:
                kept = out / "shots"
                kept.mkdir(exist_ok=True)
                for png in sorted((session.dir / "shots").glob("*.png")):
                    shutil.copy(png, kept / png.name)
                if saved and "read" not in summary:
                    resave = out / "resave"
                    shutil.rmtree(resave, ignore_errors=True)
                    shutil.copytree(session.save_dir, resave)
            except OSError as e:
                print(f"could not keep the evidence: {e}", file=sys.stderr)
            write_summary()

        stack.callback(keep_evidence)
        d: Driver | None = None
        try:
            session.stage(fresh=True)
            shots = session.dir / "shots"
            shutil.rmtree(shots, ignore_errors=True)
            shots.mkdir(parents=True)
            took = install(save, session.save_dir, letter)
            installed = out / "installed"
            shutil.rmtree(installed, ignore_errors=True)
            shutil.copytree(session.save_dir, installed)
            summary["installed"] = took
            note(event="staged", **took)
            session.boot(fresh=False)
            d = Driver(session, note, letter)
            results = []
            for step in steps:
                note(event="step", step=step.text)
                if step.kind == "load":
                    r = d.load()
                elif step.kind == "camp":
                    r = d.camp()
                elif step.kind == "rest":
                    r = d.rest(step.minutes)
                elif step.kind == "save":
                    r = d.save(step.letter)
                    saved.append(step.letter)
                elif step.kind == "shot":
                    r = {"shot": d.shot(step.name)}
                else:
                    r = read_step(session.save_dir, out, letter, saved, steps, expects)
                    summary["read"] = r
                results.append({"step": step.text, **r})
                note(event="done", step=step.text,
                     **{k: v for k, v in r.items() if k != "slots"})
            summary["results"] = results
            summary["completed"] = True
        except StepFailed as e:
            summary["lost"] = str(e)
            note(event="lost", why=str(e))
        except (TimeoutError, dosbox.DosboxUnavailable, dosbox.BlankCapture) as e:
            why = f"{type(e).__name__}: {e}"
            if d is not None:
                try:
                    why = str(d.fail("timeout", why))
                except Exception:  # noqa: BLE001 -- the capture may be what failed
                    pass
            summary["lost"] = why
            note(event="lost", why=why)
    return 0 if summary["completed"] else 1


def read_step(save_dir: pathlib.Path, out: pathlib.Path, letter: str,
              saved: list[str], steps: list[Step], expects: list[Expect]) -> dict:
    """Copy `SAVE/` out and decode the installed slot against each saved one."""
    resave = out / "resave"
    shutil.rmtree(resave, ignore_errors=True)
    shutil.copytree(save_dir, resave)
    before = read_slot(out / "installed", letter)
    asked = sum(s.minutes for s in steps if s.kind == "rest")
    result: dict = {"installed": before, "rested_minutes": asked, "slots": {}}
    for x in saved:
        after = read_slot(resave, x)
        result["slots"][x] = {
            **after,
            "clock_advanced": after["clock_minutes"] - before["clock_minutes"],
            "compare": compare_nodes(before, after),
        }
    if saved and expects:
        result["verdicts"] = [judge(e, result["slots"][saved[-1]]) for e in expects]
    for line in describe(result):
        print(line, flush=True)
    return result


def describe(result: dict) -> list[str]:
    """The reading, one line per fact, for the terminal."""
    lines = []
    for x, s in result["slots"].items():
        lines.append(f"slot {x}: clock advanced {s['clock_advanced']} minutes "
                     f"(rested {result['rested_minutes']})")
        for row in s["compare"]:
            if row["before"] is None:
                lines.append(f"  {row['name']} id {row['id']}: new node, "
                             f"{row['after']} minutes")
            elif row["after"] is None:
                lines.append(f"  {row['name']} id {row['id']}: {row['before']} "
                             f"minutes before, no node after")
            else:
                lines.append(f"  {row['name']} id {row['id']}: {row['before']} -> "
                             f"{row['after']} minutes (lost {row['lost']}), data "
                             f"{row['data_before']:02X} -> {row['data_after']:02X}")
    for v in result.get("verdicts", []):
        e = v["expect"]
        lines.append(f"expect {e['name']} id {e['id']} at {e['minutes']} minutes: "
                     f"{v['verdict']}" + (f" ({v['why']})" if "why" in v else ""))
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", choices=sorted(TITLES), default="pool")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--save", help="a DOS save folder Wish wrote, one SAVGAM?.DAT "
                                    "and its CHRDAT files")
    src.add_argument("--fixture-row", action="append", default=[],
                     metavar="SLOT=ID:OWNER:DURATION:MAGNITUDE",
                     help="hex; stage this effect row into the C64 fixture party "
                          "and convert it with Save As DOS first (repeatable)")
    ap.add_argument("--slot", default="A", help="the letter to install and load as")
    ap.add_argument("--steps", nargs="*", default=[],
                    help="load, camp, 'rest 5m', 'save D', 'shot NAME', read")
    ap.add_argument("--expect", action="append", default=[],
                    metavar="NAME:ID:MINUTES[:DATA]",
                    help="a node the last saved slot must hold (repeatable)")
    ap.add_argument("--issue", default="661")
    ap.add_argument("--run", default="run", help="the run's name in the evidence path")
    ap.add_argument("--out", default=None,
                    help="evidence directory (default ~/.cache/wish/acceptance/"
                         "<issue>/<sha>-<run>)")
    ap.add_argument("--note", default="dosacceptance")
    args = ap.parse_args(argv)
    try:
        for s in args.steps:
            parse_step(s)
        for e in args.expect:
            parse_expect(e)
        for r in args.fixture_row:
            parse_row(r)
        validate_steps([parse_step(s) for s in args.steps])
    except ValueError as e:
        ap.error(str(e))
    if not re.fullmatch(r"[A-Ja-j]", args.slot):
        ap.error("--slot is one letter, A to J")
    if not re.fullmatch(r"[\w-]+", args.run) or not re.fullmatch(r"[\w-]+", args.issue):
        ap.error("--issue and --run are simple names")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
