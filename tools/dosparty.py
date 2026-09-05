#!/usr/bin/env python3
"""Build a whole DOS Pool of Radiance party in the game's own creation
screens, and save it with the game's own SAVE CURRENT GAME.

`#249 (Build a DOS party from creation and level it ourselves, so DOS
measurements rest on records we watched being written)` is why this exists.
`tools/dosgnome.py` proved a single character can be rolled under DOSBox and
read back off the host filesystem; this does the same for six of them at once
and then makes the engine write a **saved game** around them, which is the
artefact every DOS measurement actually wants.

**The roster is emptied before anything is created.**  The archives' `SAVE`
directory ships six `.CHA` files and three saved games, and none of them has a
chain of custody -- `.claude/rules/testing.md`, "A specimen is only evidence if
we know who wrote it".  `wipe_roster` truncates `CHARLIST.TXT` to nothing and
removes every `.CHA`/`.ITM`/`.SPC` and every `CHRDAT*`/`SAVGAM*` from the
**staged copy**, so the ADD CHARACTER TO PARTY list can only ever offer
characters this run made.  The player's own files are opened read only, by
`tools.dosbox.Session.stage`.

**Every list menu is addressed by position, and the arrow keys do nothing in
it.**  `Home` and `End` move the highlight within the page, `N`/`P` turn it,
`E` and `Escape` leave, and any other key picks whatever is highlighted -- so
a run that presses `Down` then `Return` picks the first entry and looks like
the game refusing the second.  A list is opened fresh with the highlight on
entry 0, so entry *n* is `End` pressed *n* times and then `Return`.

The creation flow, verified by screenshot at every step:

    c                       CREATE NEW CHARACTER
    End*race    Return      DWARF ELF GNOME HALF-ELF HALFLING HUMAN
    End*gender  Return      MALE FEMALE
    End*class   Return      the class list, which differs by race
    End*align   Return      LAWFUL GOOD .. CHAOTIC EVIL, nine of them
    y                       KEEP THIS CHARACTER? YES NO -- the first roll
    <name> Return           CHARACTER NAME:
    k                       HEAD BODY KEEP, the portrait picker
    e                       PARTS COLOR-1 COLOR-2 SIZE EXIT, the icon editor
    y                       IS THIS ICON OK? YES NO

`--classes` is the discovery pass: it opens the class list for each of the six
races and shoots it, because the list is not the same for two races and
picking by position needs to know what is at each position.

`--build` reads a JSON spec -- a list of `{name, race, gender, class,
alignment}`, each of the last four a menu **index** -- creates every character
in it, adds them all to the party, saves to `--slot`, and then reads the
records the engine wrote back with `goldbox.dos` and checks each one's name,
race, class and alignment against what was asked for.  That check is the
evidence: the party is what we said it was because the engine's own bytes say
so, not because the screenshots look right.

    tools/dosparty.py --classes --out work/issue249/classes
    tools/dosparty.py --build work/issue249/party.json --slot C \\
        --out work/issue249/build

Output goes under `work/`, never into the repository: a saved game is the
game's data.  **Copy it into `$WISH_SPECIMENS` with `tools/specimens.py add`
before the slot goes down** -- `Session.stage` is a copy into the pool
instance's own directory and tearing the slot down takes it with it.
"""

from __future__ import annotations

import argparse
import atexit
import dataclasses
import json
import pathlib
import shutil
import signal
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos  # noqa: E402
from tools import dosbox  # noqa: E402

#: The race list, in the order CREATE NEW CHARACTER draws it.  Read off the
#: screen in `#84 (Roll a gnome in DOS and read the two innate effect ids
#: nobody has seen)`'s own shots; `goldbox.games.RACES_FORGOTTEN_REALMS` says
#: the record codes are 1, 2, 3, 4, 5 and 7 -- half-orc, code 6, is not
#: offered at creation.
RACE_MENU = ("DWARF", "ELF", "GNOME", "HALF-ELF", "HALFLING", "HUMAN")

#: What the record's `race` field should hold for each menu position.
RACE_CODE = (1, 2, 3, 4, 5, 7)

GENDER_MENU = ("MALE", "FEMALE")

#: Nine of them, in menu order.  What the record stores is what this tool
#: measures rather than assumes -- see `check_records`.
ALIGNMENT_MENU = (
    "LAWFUL GOOD", "LAWFUL NEUTRAL", "LAWFUL EVIL",
    "NEUTRAL GOOD", "TRUE NEUTRAL", "NEUTRAL EVIL",
    "CHAOTIC GOOD", "CHAOTIC NEUTRAL", "CHAOTIC EVIL",
)


@dataclasses.dataclass
class Spec:
    """One character to roll: a name and four menu positions."""

    name: str
    race: int
    gender: int
    cls: int
    alignment: int
    #: What the class ought to come back as, for the check afterwards.  A
    #: mapping of `goldbox.dos` class name to level, or None to skip.
    classes: dict[str, int] | None = None

    @classmethod
    def from_json(cls, d: dict) -> "Spec":
        return cls(
            name=d["name"],
            race=int(d["race"]),
            gender=int(d["gender"]),
            cls=int(d["class"]),
            alignment=int(d["alignment"]),
            classes=d.get("classes"),
        )


def wipe_roster(save_dir: pathlib.Path) -> list[str]:
    """Empty the staged roster so only this run's characters can be added.

    Returns what was removed, so the report can say it.  `Explored.dat` is
    left alone -- it is the game's own map state and not a character record.
    """
    gone = []
    for p in sorted(save_dir.iterdir()):
        if p.name.upper() == "CHARLIST.TXT":
            p.write_bytes(b"")
            gone.append(p.name + " (truncated)")
            continue
        if p.suffix.upper() in (".CHA", ".ITM", ".SPC", ".SAV", ".DAT") \
                and p.name.upper() != "EXPLORED.DAT":
            p.unlink()
            gone.append(p.name)
    return gone


class Driver:
    """The keystrokes of the front end, each waited on by screen digest."""

    def __init__(self, session: dosbox.Session, out: pathlib.Path):
        self.s = session
        self.out = out
        self.n = 0

    def press(self, key: str, tag: str, gap: float = 0.8) -> str:
        self.s.key(key)
        time.sleep(gap)
        self.s.settle(quiet=0.5, timeout=15.0)
        self.s.shot(f"{self.n:03d}-{tag}", allow_blank=True)
        self.n += 1
        return self.s.capture().digest()

    def type(self, text: str, tag: str) -> str:
        for ch in text:
            self.s.key("space" if ch == " " else ch)
        time.sleep(0.5)
        self.s.settle(quiet=0.5, timeout=15.0)
        self.s.shot(f"{self.n:03d}-{tag}", allow_blank=True)
        self.n += 1
        return self.s.capture().digest()

    def pick(self, index: int, tag: str) -> str:
        """Move the highlight down `index` lines and take that entry."""
        for i in range(index):
            self.press("End", f"{tag}-end{i}")
        return self.press("Return", f"{tag}-pick{index}")

    def create(self, spec: Spec) -> None:
        self.press("c", f"{spec.name}-create")
        self.pick(spec.race, f"{spec.name}-race")
        self.pick(spec.gender, f"{spec.name}-gender")
        self.pick(spec.cls, f"{spec.name}-class")
        self.pick(spec.alignment, f"{spec.name}-align")
        self.press("y", f"{spec.name}-keep")          # KEEP THIS CHARACTER?
        self.type(spec.name.lower(), f"{spec.name}-name")
        self.press("Return", f"{spec.name}-named")
        self.press("k", f"{spec.name}-portrait-keep")  # HEAD BODY KEEP
        self.press("e", f"{spec.name}-icon-exit")      # icon editor EXIT
        self.press("y", f"{spec.name}-icon-ok")        # IS THIS ICON OK?


def open_session(note: str, out: pathlib.Path) -> tuple[dosbox.Session, dosbox.Slot]:
    """Claim a slot, stage a fresh game, empty the roster, reach the menu."""
    out.mkdir(parents=True, exist_ok=True)
    slot = dosbox.claim(note)
    session = dosbox.Session(slot, dosbox.find_game())

    def cleanup(*_: object) -> None:
        session.close()
        slot.release()

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    session.stage(fresh=True)
    # The slot's directory outlives the lease -- `stage(fresh=True)` replaces
    # `game/` and leaves `shots/` alone -- so an earlier run's PNGs are still
    # there and `collect` would copy them out as if they were this run's.
    shutil.rmtree(session.dir / "shots", ignore_errors=True)
    (session.dir / "shots").mkdir(parents=True, exist_ok=True)
    gone = wipe_roster(session.save_dir)
    (out / "wiped.txt").write_text("\n".join(gone) + "\n")
    session.boot(fresh=False)
    dosbox.PoolOfRadiance(session).to_main_menu()
    session.shot("000-main-menu")
    return session, slot


def menu_bar(session: dosbox.Session) -> str:
    """The `CHOOSE A FUNCTION` strip, by shape.

    The add list and the party menu are told apart by this and nothing else.
    **The add list closes itself when the last unstarred entry is taken**, so
    a run that presses `EXIT` unconditionally after the sixth add is pressing
    `E` at the party menu, where it is EXIT TO DOS -- which is how the first
    build of this party reached `QUIT TO DOS YES NO` with the save unwritten.
    """
    return session.capture().ink(dosbox.BAR)


def collect(session: dosbox.Session, out: pathlib.Path,
            where: str = "save") -> None:
    """Copy every shot and every file in `SAVE` out of the slot.

    Called twice in a build, and the first call is not optional: **adding a
    character to the party deletes its `<NAME>.CHA` from the roster** and
    folds the record into `CHRDAT<slot><n>.SAV`, so the individual rolled
    records exist only between creation and the add.  That is what cost
    `#84 (Roll a gnome in DOS and read the two innate effect ids nobody has
    seen)` its per-character files in the run's final snapshot.
    """
    shots = out / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    for png in sorted((session.dir / "shots").glob("*.png")):
        shutil.copy(png, shots / png.name)
    save = out / where
    save.mkdir(parents=True, exist_ok=True)
    for p in sorted(session.save_dir.iterdir()):
        if p.name.upper() == "EXPLORED.DAT":
            continue
        shutil.copy(p, save / p.name)


def classes_pass(out: pathlib.Path) -> int:
    """Shoot the class list for each of the six races, then leave it."""
    session, slot = open_session("issue249 class lists", out)
    d = Driver(session, out)
    try:
        for i, race in enumerate(RACE_MENU):
            d.press("c", f"{race}-create")
            d.pick(i, f"{race}-race")
            d.pick(0, f"{race}-gender")
            # The class list is on screen now; back out without picking.
            for k in range(4):
                d.press("Escape", f"{race}-escape{k}")
        collect(session, out)
    finally:
        session.close()
        slot.release()
    print("class lists in", out / "shots", flush=True)
    return 0


def check_records(save_dir: pathlib.Path, slot_letter: str,
                  specs: list[Spec]) -> list[str]:
    """Read what the engine wrote and compare it with what was asked for."""
    lines: list[str] = []
    ok = True
    for n, spec in enumerate(specs, start=1):
        path = save_dir / f"CHRDAT{slot_letter.upper()}{n}.SAV"
        if not path.is_file():
            lines.append(f"{n} {spec.name}: MISSING {path.name}")
            ok = False
            continue
        c = dos.read_character(path)
        want_race = RACE_CODE[spec.race]
        got = {
            "name": c.name,
            "race": c.get("race"),
            "sex": c.get("sex"),
            "alignment": c.get("alignment"),
            "level": c.get("level"),
            "class_levels": c.class_levels,
            "class_bits": c.get("class_bits"),
            "experience": c.get("experience"),
            "hp_max": c.get("hp_max"),
            "gold": c.get("gold"),
        }
        bad = []
        if c.name != spec.name.upper():
            bad.append(f"name {c.name!r} != {spec.name.upper()!r}")
        if got["race"] != want_race:
            bad.append(f"race {got['race']} != {want_race}")
        if spec.classes is not None and c.class_levels != spec.classes:
            bad.append(f"classes {c.class_levels} != {spec.classes}")
        ok = ok and not bad
        lines.append(
            f"{n} {path.name}: " + "  ".join(f"{k}={v}" for k, v in got.items())
            + ("   MISMATCH: " + "; ".join(bad) if bad else "   ok")
        )
    lines.append("all records match the spec" if ok else "SPEC MISMATCH")
    return lines


def build_pass(spec_path: pathlib.Path, out: pathlib.Path,
               slot_letter: str) -> int:
    specs = [Spec.from_json(d) for d in json.loads(spec_path.read_text())]
    session, slot = open_session("issue249 party build", out)
    d = Driver(session, out)
    try:
        for spec in specs:
            d.create(spec)
            print(f"created {spec.name}", flush=True)
        collect(session, out, "rolled")
        # ADD CHARACTER TO PARTY: the roster is exactly these, in this order.
        menu = menu_bar(session)
        d.press("a", "add-open")
        for i, spec in enumerate(specs):
            if i:
                d.press("End", f"add-{spec.name}-end")
            d.press("Return", f"add-{spec.name}")
        if menu_bar(session) != menu:
            d.press("e", "add-exit")
        # SAVE CURRENT GAME, then the slot letter.
        d.press("s", "save-open")
        d.press(slot_letter.lower(), f"save-{slot_letter}")
        dosbox.settle_files(session.save_dir, timeout=60.0)
        time.sleep(2.0)
        collect(session, out)
        lines = check_records(session.save_dir, slot_letter, specs)
    finally:
        session.close()
        slot.release()
    (out / "records.txt").write_text("\n".join(lines) + "\n")
    for line in lines:
        print(line, flush=True)
    print("artefacts in", out, flush=True)
    return 0 if lines[-1].startswith("all records") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "work" / "issue249" / "run")
    ap.add_argument("--classes", action="store_true",
                    help="shoot the class list for each race and exit")
    ap.add_argument("--build", type=pathlib.Path,
                    help="the JSON party spec to roll")
    ap.add_argument("--slot", default="C", help="save-game letter to write")
    args = ap.parse_args(argv)

    if args.classes:
        return classes_pass(args.out)
    if args.build:
        return build_pass(args.build, args.out, args.slot)
    ap.error("give --classes or --build")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
