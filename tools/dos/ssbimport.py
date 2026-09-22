#!/usr/bin/env python3
"""Bring one DOS Curse character into DOS Silver Blades through the game's own
`ADD CHARACTER TO PARTY > CURSE` route, rest a day, and try his CURE.

What a player does: he copies his Curse character's `.GUY` file into Silver
Blades' `SAVE` directory, chooses `ADD CHARACTER TO PARTY`, answers `CURSE`
at `ADD FROM WHERE?`, picks the character and plays on.  This does exactly
that under DOSBox, with one change a player cannot make: `--former-class`
writes the Curse record's byte `0x0F9` -- the fourth byte of the NPC window,
which Silver Blades' importer compares with 3 (paladin) and 4 (ranger)
(`docs/229-the-npc-window-bytes.md`) -- before the file is staged.  Two runs
from the same Curse save, one with 3 and one with 0, are the experiment
that doc names.

Three captures, each a `SAVE` copy plus decoded fields in `summary.json`:

1. `1-import` -- `SAVE CURRENT GAME` from the party menu right after the
   import, before the party has done anything.
2. `2-rest` -- after `BEGIN ADVENTURING`, the intro, `ENCAMP` and a rest of
   `--rest-days` days, saved from camp.
3. `3-cure` -- after opening his sheet in camp and pressing the CURE key;
   if the sheet reacts, the cure prompt is answered with him as the target.

For each: `paladin_cures` (record `0x6D`), the window byte at `0x101`, the
class and level arrays, and the effect ids in `CHRDAT<slot><n>.SFX`.  Every
screen along the way is a PNG under `shots/`.

**Whether the sheet offers CURE is read by what the key does, not by
reading the bar**: the sheet is captured, the key pressed, and the frame
compared.  A key the bar does not carry leaves the frame identical, which
`HEAL` (offered) and `c` (not offered) on the control input showed in the
probe that mapped these screens.

**Screens are recognised by the command bar's `Screen.glyphs` digest**,
measured off this game's own captures in that probe.  A digest names a row of
glyphs at one highlight position and nothing else, so where the highlight can
sit on any word -- the sheet, the camp menu -- the driver waits for a change
instead.  An unrecognised bar where a known one was expected stops the run
with a screenshot rather than pressing on.

    tools/dos/ssbimport.py --curse-save DIR --slot J --who 1 \\
        --former-class 3 --out OUT

Archives and the Curse save are read only; everything written is under the
instance directory and `--out`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS.parent))

from goldbox import dos_port as _port  # noqa: E402
from goldbox import dos_savegame as sav  # noqa: E402
from goldbox.effects import RUNNING_EFFECT_SIZE  # noqa: E402
from tools.dos import dosbox  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: The DOS Curse record, as a `.GUY` or a `CHRDAT<slot><n>.SAV`.
CURSE_RECORD = 422
#: The window's fourth byte in the Curse record, `0x0F9` (`docs/229`).
CURSE_FORMER_CLASS = {f.name: f.offset for f in _port.layout_for(
    _port.CURSE_OF_THE_AZURE_BONDS)}["field_83_87"] + 3

#: The DOS Silver Blades record and the fields this reports, read from
#: `goldbox.dos_port` rather than copied: `paladin_cures` is `0x6D` there.
SSB_RECORD = 439
SSB_FIELDS = ("race", "char_class", "paladin_cures", "hp_max", "level",
              "former_level", "field_83_87", "class_levels",
              "former_class_levels", "experience")
_SSB_LAYOUT = {f.name: (f.offset, f.size) for f in
               _port.layout_for(_port.SECRET_OF_THE_SILVER_BLADES)}
SSB = {name: _SSB_LAYOUT[name] for name in SSB_FIELDS}
#: The window's fourth byte, which the Silver Blades importer compares with
#: 3 and 4 (`0x101`).
SSB_FORMER_CLASS = SSB["field_83_87"][0] + 2

#: The paladin's innate effect id: Protection from Evil, node 8 (`docs/229`).
PALADIN_NODE = 8

#: The party menu's highlight list: nine 8-pixel rows from y=96, read
#: between the left border and the mouse pointer the game parks at x=160.
MENU_RECT = (64, 96, 90, 72)
MENU_BEFORE = {"add": 1}
MENU_AFTER = {"view": 3, "save": 6, "begin": 7}

#: Command-bar digests (`Screen.glyphs(dosbox.BAR)`), measured off DOS Silver
#: Blades 1.30's own captures in the probe that mapped this route.  Each is one
#: bar at one highlight position.
BARS = {
    "87fc69d8225c82c7": "title",          # PLAY DEMO
    "9ea118ca48fdb5bb": "party_menu",     # CHOOSE A FUNCTION SELECT
    "927ce83f92814158": "add_from",       # ADD FROM WHERE? SECRET CURSE EXIT
    "e5d4ccb0f042e360": "add_list",       # ADD A CHARACTER: ADD EXIT
    "ff25bed811ead601": "add_list_added", # the same, EXIT highlighted
    "3be5f71ace63ae51": "pick_character", # PICK CHARACTER SELECT EXIT
    "35045663cfeb4dc5": "save_which",     # SAVE WHICH GAME: A B ... J
    "c1e280e0b635bf5b": "continue",       # PRESS <ENTER>/<RETURN> TO CONTINUE
    "0673632718086ca7": "treasure",       # VIEW TAKE POOL SHARE EXIT
    "ee8750d217378726": "treasure_left",  # (there is still treasure left) YES NO
    "daa8b33293560f31": "map",            # MOVE AREA CAST VIEW ENCAMP SEARCH LOOK
    "e61c9acccfc048ae": "move_mode",      # EXIT, after MOVE
    "190472fcf2345334": "camp",           # SAVE VIEW MAGIC REST ALTER FIX EXIT
    "1d00b47a4fdc6739": "camp",           # the same, VIEW highlighted
    "16b29f069ec9f8f7": "camp",           # the same, REST highlighted
    "0b48cd02f99dbdfd": "cure_anyway",    # (is not diseased) CURE ANYWAY: YES NO
    "a7e6e1e306491ae5": "rest_menu",      # REST DAYS HOURS MINS ADD SUBTRACT EXIT
    "7d9dc294ffc6763d": "quit_to_dos",    # QUIT TO DOS YES NO
}


# --------------------------------------------------------------------------
# Pure parts: staging the input and reading the captures
# --------------------------------------------------------------------------


def record_name(record: bytes) -> str:
    """The character's name: a length byte and up to 15 characters."""
    n = min(record[0], 15)
    return record[1:1 + n].decode("latin-1")


def guy_stem(name: str) -> str:
    """A DOS 8.3 stem for a `.GUY` holding `name`.

    Letters and digits only, upper case, at most eight; `GUY` if nothing is
    left.  What stem Curse itself would choose is not measured, and Silver
    Blades lists what it finds under any stem.
    """
    stem = "".join(c for c in name.upper() if c.isascii() and c.isalnum())[:8]
    return stem or "GUY"


def stage_guy(record: bytes, former_class: int | None) -> bytes:
    """The Curse record to stage, with `0x0F9` set when `former_class` is given.

    Nothing else in the record moves, which is what makes two runs differ by
    exactly one byte.
    """
    if len(record) != CURSE_RECORD:
        raise ValueError(
            f"a DOS Curse record is {CURSE_RECORD} bytes, got {len(record)}")
    out = bytearray(record)
    if former_class is not None:
        if not 0 <= former_class <= 0xFF:
            raise ValueError(f"--former-class must be a byte, got {former_class}")
        out[CURSE_FORMER_CLASS] = former_class
    return bytes(out)


def effect_nodes(sfx: bytes) -> list[dict]:
    """The nine-byte nodes of a `.SFX`/`.FX` file: id, minutes, data, flag.

    A trailing partial node is reported rather than dropped.
    """
    nodes = []
    for i in range(0, len(sfx), RUNNING_EFFECT_SIZE):
        node = sfx[i:i + RUNNING_EFFECT_SIZE]
        if len(node) < RUNNING_EFFECT_SIZE:
            nodes.append({"partial": node.hex()})
            continue
        nodes.append({"id": node[0], "minutes": node[1] | node[2] << 8,
                      "data": node[3], "flag": node[4], "raw": node.hex()})
    return nodes


def summarise(record: bytes, sfx: bytes | None) -> dict:
    """The fields the experiment compares, from one Silver Blades record."""
    if len(record) != SSB_RECORD:
        raise ValueError(
            f"a DOS Silver Blades record is {SSB_RECORD} bytes, got {len(record)}")
    out: dict = {"name": record_name(record)}
    for key, (off, size) in SSB.items():
        chunk = record[off:off + size]
        if key == "experience":
            out[key] = int.from_bytes(chunk, "little")
        elif size == 1:
            out[key] = chunk[0]
        else:
            out[key] = list(chunk)
    out["former_class_byte"] = record[SSB_FORMER_CLASS]
    nodes = effect_nodes(sfx or b"")
    out["sfx_present"] = sfx is not None
    out["effect_ids"] = [n["id"] for n in nodes if "id" in n]
    out["effect_nodes"] = nodes
    out["paladin_node"] = PALADIN_NODE in out["effect_ids"]
    return out


def find_record(save_dir: pathlib.Path, letter: str, name: str
                ) -> tuple[pathlib.Path, pathlib.Path] | None:
    """The `CHRDAT<letter><n>.SAV` holding `name`, and its `.SFX` path."""
    for n in range(1, 9):
        rec = save_dir / f"CHRDAT{letter.upper()}{n}.SAV"
        if rec.is_file() and record_name(rec.read_bytes()) == name:
            return rec, rec.with_suffix(".SFX")
    return None


def capture(save_dir: pathlib.Path, letter: str, name: str,
            dest: pathlib.Path) -> dict:
    """Copy slot `letter`'s files to `dest` and summarise `name`'s record."""
    dest.mkdir(parents=True, exist_ok=True)
    for p in sorted(save_dir.iterdir()):
        up = p.name.upper()
        if up == f"SAVGAM{letter.upper()}.DAT" or up.startswith(
                f"CHRDAT{letter.upper()}"):
            shutil.copy(p, dest / p.name)
    found = find_record(save_dir, letter, name)
    if found is None:
        return {"error": f"no CHRDAT{letter}n.SAV holds {name!r}"}
    rec, sfx = found
    out = summarise(rec.read_bytes(), sfx.read_bytes() if sfx.is_file() else None)
    out["record_file"] = rec.name
    game = save_dir / f"SAVGAM{letter.upper()}.DAT"
    if game.is_file():
        data = game.read_bytes()
        out["clock_digits"] = [
            sav.word(data, sav.CLOCK + i, sav.SAVE_SECRET_OF_THE_SILVER_BLADES)
            for i in range(sav.CLOCK_DIGITS)]
    return out


def read_input(args) -> tuple[bytes, dict[str, bytes]]:
    """The Curse record and its item and effect files, by suffix."""
    if args.guy:
        guy = pathlib.Path(args.guy)
        record = guy.read_bytes()
        sides = {sfx: guy.with_suffix(sfx) for sfx in (".SWG", ".FX")}
    else:
        base = pathlib.Path(args.curse_save) / f"CHRDAT{args.slot.upper()}{args.who}"
        record = base.with_suffix(".SAV").read_bytes()
        sides = {sfx: base.with_suffix(sfx) for sfx in (".SWG", ".FX")}
    return record, {k: v.read_bytes() for k, v in sides.items() if v.is_file()}


# --------------------------------------------------------------------------
# The driven part
# --------------------------------------------------------------------------


class RouteLost(RuntimeError):
    """The game showed a screen the route did not expect."""


class Driver:
    def __init__(self, session: dosbox.Session, note, cure_key: str = "c",
                 select_key: str = "s", anyway_key: str = "y"):
        self.s = session
        self.note = note
        self.cure_key = cure_key
        self.select_key = select_key
        self.anyway_key = anyway_key
        self.n = 0
        self.camp_status: str | None = None

    def shot(self, label: str) -> str:
        self.n += 1
        name = f"{self.n:03d}-{label}"
        self.s.shot(name, allow_blank=True)
        return name

    def bar(self, screen: dosbox.Screen | None = None) -> str:
        screen = screen or self.s.settle(quiet=0.6, timeout=30.0)
        return BARS.get(screen.glyphs(dosbox.BAR), "?")

    def wait_bar(self, want: str, timeout: float = 45.0) -> dosbox.Screen:
        deadline = time.time() + timeout
        screen = self.s.settle(quiet=0.6, timeout=timeout)
        while time.time() < deadline:
            if BARS.get(screen.glyphs(dosbox.BAR)) == want:
                return screen
            time.sleep(0.3)
            screen = self.s.settle(quiet=0.6, timeout=max(1.0, deadline - time.time()))
        name = self.shot(f"lost-waiting-for-{want}")
        raise RouteLost(f"expected the {want} bar, got {screen.glyphs(dosbox.BAR)} "
                        f"({BARS.get(screen.glyphs(dosbox.BAR), 'unknown')}); "
                        f"see {name}.png")

    def press(self, key: str, want: str | None = None, label: str = "") -> None:
        self.s.key(key)
        if want:
            self.wait_bar(want)
        else:
            self.s.settle(quiet=0.6, timeout=30.0)
        if label:
            self.shot(label)

    def menu(self, row: int, label: str) -> None:
        """Move the party menu's highlight to `row` and select it."""
        got = self.s.walk_highlight(MENU_RECT, row, key="Down")
        if got != row:
            name = self.shot(f"lost-menu-{label}")
            raise RouteLost(f"party menu highlight reached {got}, wanted {row}; "
                            f"see {name}.png")
        self.s.key("Return")

    # -- the steps ---------------------------------------------------------

    def to_party_menu(self, timeout: float = 120.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.bar() == "title":
                break
            self.s.key("Return")
        else:
            raise RouteLost("never reached the PLAY DEMO screen")
        self.press("p", "party_menu", "party-menu")

    def import_curse(self) -> None:
        self.menu(MENU_BEFORE["add"], "add")
        self.wait_bar("add_from")
        self.shot("add-from")
        self.press("c", "add_list", "curse-list")
        self.press("a", "add_list_added", "added")
        self.press("e", "party_menu", "party-after-import")

    def party_save(self, letter: str) -> None:
        self.menu(MENU_AFTER["save"], "save")
        self.wait_bar("save_which")
        self.save_letter(letter)
        self.wait_bar("party_menu")
        self.shot(f"saved-{letter}")

    def save_letter(self, letter: str) -> None:
        path = self.s.save_file(letter)
        was = path.read_bytes() if path.is_file() else None
        self.s.key(letter.lower())
        deadline = time.time() + 60.0
        while time.time() < deadline:
            if path.is_file() and path.read_bytes() != was:
                break
            time.sleep(0.3)
        else:
            raise RouteLost(f"{path.name} never changed")
        dosbox.settle_files(self.s.save_dir, quiet=1.0, timeout=30.0)

    def sheet_cure(self, label: str, use: bool) -> dict:
        """On an open sheet: shoot it, press CURE, and see whether it reacts.

        `use` answers the cure prompt with the first character; otherwise the
        prompt is left with EXIT.  Returns what was seen.

        **`CURE WHOM? SELECT EXIT` opens with EXIT highlighted**, so `Return`
        there leaves without casting and reads exactly like a cure that did
        nothing; the prompt is answered with the SELECT key instead.
        """
        before = self.s.settle(quiet=0.8, timeout=30.0)
        out = {"sheet": self.shot(f"{label}-sheet"),
               "sheet_bar": before.glyphs(dosbox.BAR)}
        self.s.key(self.cure_key)
        after = self.s.settle(quiet=0.8, timeout=30.0)
        out["cure_offered"] = after.digest() != before.digest()
        if not out["cure_offered"]:
            self.note(event="cure", stage=label, offered=False)
            return out
        out["cure_prompt"] = self.shot(f"{label}-cure-prompt")
        out["cure_prompt_bar"] = after.glyphs(dosbox.BAR)
        if not use:
            self.press("e", label=f"{label}-cure-declined")
            return out
        self.s.key(self.select_key)
        shots = []
        for i in range(8):
            screen = self.s.settle(quiet=1.0, timeout=30.0)
            shots.append(self.shot(f"{label}-cure-{i}"))
            if self.in_camp(screen):
                break
            if self.bar(screen) == "cure_anyway":
                out["cure_anyway"] = self.anyway_key
            self.s.key(self.leave_key(screen))
        out["cure_screens"] = shots
        self.note(event="cure", stage=label, offered=True, screens=shots)
        return out

    def in_camp(self, screen: dosbox.Screen) -> bool:
        """The camp menu itself, not a prompt drawn over the camp picture.

        The status line alone cannot say so: `CURE ANYWAY`, `SAVE WHICH GAME`
        and the rest menu all keep `CAMPING` under the viewport.
        """
        return (self.camp_status is not None
                and screen.glyphs(dosbox.STATUS) == self.camp_status
                and BARS.get(screen.glyphs(dosbox.BAR)) == "camp")

    def intro(self, limit: int = 60) -> None:
        """From BEGIN ADVENTURING to the map, answering what the intro shows."""
        for i in range(limit):
            screen = self.s.settle(quiet=1.0, timeout=40.0)
            kind = self.bar(screen)
            if kind == "map":
                self.shot("map")
                return
            if kind == "continue":
                self.s.key("Return")
            elif kind == "treasure":
                self.shot("intro-treasure")
                self.s.key("e")
            elif kind == "treasure_left":
                self.s.key("n")
            elif kind == "move_mode":
                self.s.key("Escape")
            else:
                name = self.shot("lost-intro")
                raise RouteLost(f"intro showed bar {screen.glyphs(dosbox.BAR)}; "
                                f"see {name}.png")
        raise RouteLost(f"not on the map after {limit} intro screens")

    def encamp(self) -> None:
        self.s.key("e")
        screen = self.wait_bar("camp")
        self.camp_status = screen.glyphs(dosbox.STATUS)
        self.shot("camp")

    def leave_key(self, screen: dosbox.Screen) -> str:
        """The key that moves from `screen` towards the camp menu.

        **`e` is EXIT on the camp menu itself**, where it breaks camp, so an
        unrecognised bar under the camp's own status line stops the run
        instead of being pressed through.
        """
        kind = self.bar(screen)
        if kind == "quit_to_dos":
            return "n"
        if kind == "cure_anyway":
            return self.anyway_key
        if kind == "continue":
            return "Return"
        if screen.glyphs(dosbox.STATUS) == self.camp_status:
            name = self.shot("lost-unknown-camp-bar")
            raise RouteLost(f"unrecognised bar {screen.glyphs(dosbox.BAR)} over "
                            f"the camp; see {name}.png")
        return "e"

    def back_to_camp(self, tries: int = 6) -> None:
        for _ in range(tries):
            screen = self.s.settle(quiet=0.8, timeout=30.0)
            if self.in_camp(screen):
                return
            self.s.key(self.leave_key(screen))
        name = self.shot("lost-leaving-to-camp")
        raise RouteLost(f"could not get back to camp; see {name}.png")

    def rest(self, days: int) -> None:
        self.press("r", "rest_menu", "rest-menu")
        self.s.key("d")
        self.s.settle(quiet=0.6, timeout=20.0)
        for _ in range(days):
            self.s.key("a")
            self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("rest-time")
        self.s.key("r")
        self.s.settle(quiet=3.0, timeout=300.0)
        self.shot("rested")
        self.back_to_camp()

    def camp_save(self, letter: str) -> None:
        self.s.key("s")
        self.wait_bar("save_which")
        self.save_letter(letter)
        self.wait_bar("quit_to_dos")
        self.s.key("n")
        self.back_to_camp()
        self.shot(f"saved-{letter}")


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    record, sides = read_input(args)
    staged = stage_guy(record, args.former_class)
    name = record_name(staged)
    stem = guy_stem(name)
    inp = out / "input"
    inp.mkdir(exist_ok=True)
    (inp / f"{stem}.GUY").write_bytes(staged)
    note(event="input", name=name, stem=stem,
         former_class_before=record[CURSE_FORMER_CLASS],
         former_class_staged=staged[CURSE_FORMER_CLASS],
         differs_at=[hex(i) for i in range(CURSE_RECORD) if record[i] != staged[i]],
         sides=sorted(sides))

    summary: dict = {"name": name, "former_class_staged": staged[CURSE_FORMER_CLASS],
                     "stages": {}}
    slot = dosbox.claim(args.note)
    session = dosbox.Session(slot, dosbox.find_game("SECRET"))
    try:
        session.stage(fresh=True)
        (session.dir / "shots").mkdir(parents=True, exist_ok=True)
        for old in (session.dir / "shots").glob("*.png"):
            old.unlink()
        for old in session.save_dir.glob("*"):
            old.unlink()
        (session.save_dir / f"{stem}.GUY").write_bytes(staged)
        for sfx, data in sides.items():
            (session.save_dir / f"{stem}{sfx}").write_bytes(data)
        session.boot(fresh=False)
        d = Driver(session, note, args.cure_key, args.select_key,
                   args.anyway_key)
        d.to_party_menu()
        d.import_curse()

        a, b, c = args.letters.upper()
        d.party_save(a)
        stage = capture(session.save_dir, a, name, out / "1-import")
        d.menu(MENU_AFTER["view"], "view")
        d.wait_bar("pick_character")
        d.s.key("Return")
        stage.update(d.sheet_cure("1-import", use=False))
        d.s.key("e")
        d.wait_bar("party_menu")
        summary["stages"]["1-import"] = stage
        note(event="stage", stage="1-import", **_brief(stage))

        d.menu(MENU_AFTER["begin"], "begin")
        d.intro()
        d.encamp()
        d.rest(args.rest_days)
        d.camp_save(b)
        stage = capture(session.save_dir, b, name, out / "2-rest")
        summary["stages"]["2-rest"] = stage
        note(event="stage", stage="2-rest", **_brief(stage))

        d.s.key("v")
        stage = d.sheet_cure("3-cure", use=True)
        d.back_to_camp()
        d.camp_save(c)
        stage.update(capture(session.save_dir, c, name, out / "3-cure"))
        summary["stages"]["3-cure"] = stage
        note(event="stage", stage="3-cure", **_brief(stage))
        summary["completed"] = True
    except RouteLost as e:
        summary["completed"] = False
        summary["lost"] = str(e)
        note(event="lost", why=str(e))
    finally:
        try:
            shots = out / "shots"
            shots.mkdir(parents=True, exist_ok=True)
            for png in sorted((session.dir / "shots").glob("*.png")):
                shutil.copy(png, shots / png.name)
        except OSError as e:
            print(f"could not keep the shots: {e}", file=sys.stderr)
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        session.close()
        slot.release()
    return 0 if summary.get("completed") else 1


def _brief(stage: dict) -> dict:
    keys = ("paladin_cures", "former_class_byte", "effect_ids", "paladin_node",
            "cure_offered", "class_levels", "former_class_levels", "level",
            "former_level", "clock_digits", "error")
    return {k: stage[k] for k in keys if k in stage}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--curse-save", help="a DOS Curse SAVE directory")
    src.add_argument("--guy", help="a DOS Curse .GUY file, with its .SWG and "
                                   ".FX beside it if it has them")
    ap.add_argument("--slot", default="A",
                    help="with --curse-save: the save's slot letter")
    ap.add_argument("--who", type=int, default=1,
                    help="with --curse-save: the party position, 1-6")
    ap.add_argument("--former-class", type=lambda s: int(s, 0), default=None,
                    help="write this at Curse record 0x0F9 before staging "
                         "(3 paladin, 4 ranger, 0 none); left alone if not given")
    ap.add_argument("--rest-days", type=int, default=1)
    ap.add_argument("--letters", default="CDE",
                    help="the three Silver Blades save slots: after import, "
                         "after the rest, after the cure")
    ap.add_argument("--cure-key", default="c", help="the sheet's CURE key")
    ap.add_argument("--select-key", default="s",
                    help="the SELECT key at CURE WHOM?, whose highlight "
                         "opens on EXIT")
    ap.add_argument("--anyway-key", default="y",
                    help="the answer to '<name> IS NOT DISEASED' / CURE "
                         "ANYWAY: YES NO; y casts on a healthy character")
    ap.add_argument("--note", default="issue614 ssb import")
    ap.add_argument("--out", default=str(scratch.scratch_dir("ssbimport") / "run"))
    args = ap.parse_args(argv)
    if len(args.letters) != 3:
        ap.error("--letters takes three slot letters")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
