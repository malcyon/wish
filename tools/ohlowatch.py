#!/usr/bin/env python3
"""Watch Ohlo's errand move the Quest Log row, in the running game.

`#158 (Track the quests the game itself forgets, starting with Ohlo's potion)`
built the reading side, once behind `WISH_EXPERIMENTAL_QUESTS` and now
shipped unconditionally. The flag's removal condition had two halves and this
tool took the second: the row has to be **seen** to appear while a party
collects the potion and to change when it delivers it.  Everything before
this was a save file read offline; nothing had watched the engine write
`$4A81` with the panel attached.

    POR_HEADLESS=1 tools/ohlowatch.py --out work/issue158

What one run does, in order:

1.  boots a save with the party standing in the Slums -- `NEWSAVE4.D64` by
    default, which `#157` established as *accepted, potion not collected*;
2.  reads the live `$4900`-`$64FF` window, the same block
    `automap/window.py`'s `_refresh_roster` hands to `QuestLogPanel`, and
    renders the panel from it offscreen;
3.  puts the party one square west of the booth and **walks** east on to it,
    so `ECL14`'s own dispatch runs the booth block at `$AE1E`;
4.  answers the booth -- its third menu option, then the word it asks for --
    and watches `$4A81` while it does, sampling every 0.4 s so the moment of
    the write is measured rather than assumed;
5.  renders the panel again;
6.  puts the party inside Ohlo's own block and walks one square within it,
    so the dispatch runs `$9F13`, takes the first option of the menu it puts
    up, and watches `$4A81` again;
7.  renders the panel a third time.

**Four harness decisions, each of which touches what is being measured.**

* **The party is teleported between the two visits by writing `$C04B`-`$C04D`**,
  the live square -- the same three bytes a fast travel writes, and nothing
  near `$4A81` or the script's own flags.  Every step that reaches a script
  is the game's own walk.
* **Ohlo's block is entered by placing the party inside it**, on `GEO14`
  (11,9), and stepping east to (12,9).  Both squares carry attribute 3, so
  the dispatch is genuine, but the walk in through the door is not: the only
  way into x 11-13, y 9-10 is (14,10) heading west and that edge is
  `LOCKED` -- a bash of unbounded length, and not what the ticket asks about.
* **`$4A80` is held at 15 while the party walks, and put back before anything
  is read.**  Both of `ECL14`'s wandering spawns are `COMPARE [$4A80], 15 /
  IF>= / EXIT`, so a party at the cap is never rolled one.  The first run of
  this tool lost its whole budget to a group of goblins that arrived on the
  step into the booth.  `--no-calm` turns it off.
* **Nothing else is written to any flag byte.**  The two writes to `$4A81`
  are the engine's own, at `ECL14 $B048` and `$A3A8`.

Nothing here holds any of the game's words.  The menu options, the prompt and
the word the booth wants are decoded out of `ECL14` on the player's own disk
at run time -- the scripts are 6-bit packed, four characters to three bytes --
and are never printed: the log says "option 3 of 3", the way `tools/eclwalk.py`
prints a string as its length.

The pool owns the emulator: claim, launch, tear down.  The player's disks are
copied into the slot and read there; `Session.attach` refuses a path outside
it.  Captures go to `work/`, which is gitignored; this file does not.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools import session as S  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The window one poll reads. `goldbox/games.py` POOL_OF_RADIANCE, and
#: `automap/live.py`'s `memory_blocks`.
SAVE0_AT, SAVE0_LEN = 0x4900, 0x1C00

#: The live square: x, y, facing (0 north, 1 east, 2 south, 3 west).
SQUARE = 0xC04B
#: The resident area, low seven bits. 20 is the Slums.
AREA_AT, SLUMS = 0x6E1B, 0x14

#: Ohlo's two flags. `goldbox/commissions.py` `SIDE_QUESTS` is the authority
#: on what each value means; these are here so the sampler can watch one byte
#: without building a `Flags` on every read.
ACCEPT_FLAG = 0x4A04
POTION_FLAG = 0x4A81
IN_HAND, FINISHED = 250, 255

#: Bytes the run reports at every capture, so a reading that moved for some
#: other reason is visible rather than inferred. `$4ABB` is ledger index 21,
#: the slums encounter count, which Ohlo's delivery bumps through `$B69C`.
WATCHED = {
    "4A04": ACCEPT_FLAG, "4A19": 0x4A19, "4A1D": 0x4A1D,
    "4A80": 0x4A80, "4A81": POTION_FLAG, "4ABB": 0x4ABB,
}

# --- where in `ECL14` each thing the driver needs is written ----------------
#
# Script addresses, which are unambiguous: an `ECL` loads at `$9900`. Each was
# read with `tools/eclwalk.py listing ECL14`.
ECL14_BASE = 0x9900
#: The booth, area-script id 19, `GEO14` (15,12) and nowhere else.
BOOTH_MENU = 0xAEC8         # OP$2B, three options; the third speaks
BOOTH_OPTION = 2
BOOTH_ASKS = 0xAF7F         # the line printed before the word is typed
BOOTH_WORD = 0xAFA5         # SAVE "<word>", [$982C], compared with what is typed
#: Ohlo, area-script id 3, the block x 11-13, y 9-10. `$9F30 COMPARE [$4A81],
#: 250 / IF= / GOTO [$A25B]` is the arm a party with the potion takes.
OHLO_MENU = 0xA29D          # OP$2B, three options; the first hands it over
OHLO_OPTION = 0

#: One square west of the booth, facing east, and the square inside Ohlo's own
#: block the party steps east from. Both are `(x, y, facing)` for `$C04B`.
AT_BOOTH_DOOR = (14, 12, 1)
IN_OHLOS_ROOM = (11, 9, 1)

#: `I` is the game's own forward key indoors -- `Session.walk`. `MOVE_SUBBAR`
#: is what row 24 reads once `MOVE` has been answered and the game is waiting
#: for one of them.
FORWARD = "I"
MOVE_SUBBAR = S.MOVE_SUBBAR

#: The wandering-fight counter and the value at which both of `ECL14`'s spawn
#: sites stop rolling. `goldbox/commissions.py` `SLUM_WANDERING` is the same
#: 15, from the same two compares.
WANDER_FLAG, WANDER_CAP = 0x4A80, 15


# --- the game's own words, decoded at run time and never printed ------------

def _script(name: str = "ECL14") -> bytes:
    """One area script's body, off whichever of the player's sides carries it."""
    for path in sorted(DISKS.glob("POOL*.[dD]64")):
        image = D64.open(path)
        names = [e.name.decode("latin1").rstrip("\xa0 ")
                 for e in image.iter_directory()]
        if name in names:
            return image.read_file(name)[2:]
    raise RuntimeError(f"no disk under {DISKS} carries {name}")


def unpack(packed: bytes) -> str:
    """A 6-bit packed ECL string, four characters to three bytes.

    The alphabet is ASCII with the letters folded down: 1-26 are `A`-`Z` and
    every other value is itself, so 32 is a space and 46 a full stop. Proven
    on the booth's own three menu options, which come out as words.
    """
    bits = "".join(f"{b:08b}" for b in packed)
    out = []
    for i in range(0, len(bits) - 5, 6):
        v = int(bits[i:i + 6], 2)
        out.append(chr(v + 64) if 1 <= v <= 26 else chr(v) if v >= 32 else "")
    return "".join(out)


def _operand(body: bytes, p: int):
    """One decoded operand and where the next one starts.

    `DUNGEON $1663` is the authority: kind `$00` is a one-byte immediate,
    `$80` an inline packed string with its length in the next byte, and
    anything else a two-byte address.
    """
    kind = body[p]
    if kind == 0x00:
        return ("imm", body[p + 1], p + 2)
    if kind == 0x80:
        n = body[p + 1]
        return ("str", unpack(body[p + 2:p + 2 + n]), p + 2 + n)
    return ("addr", body[p + 1] | (body[p + 2] << 8), p + 3)


def menu_options(body: bytes, at: int) -> list[str]:
    """The options of the `OP$2B` menu at script address `at`."""
    p = at - ECL14_BASE + 1
    _, _, p = _operand(body, p)             # where the answer is stored
    _, count, p = _operand(body, p)
    out = []
    for _ in range(count):
        kind, value, p = _operand(body, p)
        if kind != "str":
            raise RuntimeError(f"menu at ${at:04X} option {len(out)} is {kind}")
        out.append(value)
    return out


def string_at(body: bytes, at: int) -> str:
    """The first inline string on or after script address `at`."""
    p = at - ECL14_BASE
    while body[p] != 0x80:
        p += 1
    return unpack(body[p + 2:p + 2 + body[p + 1]])


def _flat(text: str) -> str:
    """Letters, digits and single spaces, so a wrapped line still matches."""
    return re.sub(r"[^A-Z0-9 ]+", " ", text.upper()).strip()


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", _flat(text))


# --- reading the machine ----------------------------------------------------

def live_window(sess) -> bytes:
    """`$4900`-`$64FF`, the block the Quest Log's own poll reads."""
    with sess.mon(8) as m:
        return bytes(m.read(SAVE0_AT, SAVE0_LEN))


def watched(sess) -> dict:
    with sess.mon(5) as m:
        out = {k: m.read(a, 1)[0] for k, a in WATCHED.items()}
        out["square"] = list(m.read(SQUARE, 3))
        out["area"] = m.read(AREA_AT, 1)[0] & 0x7F
    return out


def flag(sess, address: int = POTION_FLAG) -> int:
    with sess.mon(5) as m:
        return m.read(address, 1)[0]


# --- the panel, rendered from those bytes -----------------------------------

def render(bin_path: pathlib.Path, png_path: pathlib.Path) -> dict:
    """Run this file's `rows` mode on a captured window, offscreen.

    A subprocess, and deliberately: the driver holds an emulator and a slot,
    and a Qt import that goes wrong in it would take both down with it. The
    environment is `.claude/rules/gui-text.md`'s -- `WAYLAND_DISPLAY` unset is
    the part that is easy to miss, because a Qt child prefers it over
    whatever is set for X.
    """
    env = dict(os.environ)
    for key in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
        env.pop(key, None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["GDK_BACKEND"] = "x11"
    r = subprocess.run(
        [sys.executable, str(TOOLS / "ohlowatch.py"), "rows",
         "--bin", str(bin_path), "--png", str(png_path)],
        env=env, capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr.strip()[-600:]}
    return json.loads(r.stdout)


def rows_mode(args) -> int:
    """Print the rows the Quest Log draws from a captured window, as JSON."""
    from PyQt6.QtWidgets import QApplication, QMainWindow

    from automap.questlog import QuestLogPanel, enabled
    from wish.ui_window import Ui_WishWindow

    data = pathlib.Path(args.bin).read_bytes()
    app = QApplication.instance() or QApplication([])
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    panel = QuestLogPanel(root)
    panel.update_from(data)
    out = {"gate": enabled(), "groups": {}}
    for name, group in panel.groups.items():
        out["groups"][name] = [
            {"name": r.what.text(), "state": r.state.text(),
             "note": r.note.text(), "tooltip": r.toolTip(),
             "dim": r.what.styleSheet()}
            for r in group.visible_rows()]
    if args.png:
        scroll = panel.scroll
        if scroll is not None and scroll.widget() is not None:
            widget = scroll.widget()
            widget.setFixedWidth(args.width)
            widget.adjustSize()
            widget.grab().save(args.png)
            out["png"] = args.png
    print(json.dumps(out))
    app.quit()
    return 0


# --- driving one script -----------------------------------------------------

def capture(sess, out: pathlib.Path, label: str, note: str) -> dict:
    """Everything one stage of the run is evidence for."""
    meta = {"label": label, "note": note, "at": time.time()}
    meta.update(watched(sess))
    window = live_window(sess)
    binp = out / f"{label}.save0.bin"
    binp.write_bytes(window)
    meta["window_sha"] = hashlib.sha256(window).hexdigest()[:16]
    sess.kbd.screenshot(str(out / f"{label}.game.png"))
    meta["panel"] = render(binp, out / f"{label}.panel.png")
    (out / f"{label}.json").write_text(json.dumps(meta, indent=1))
    rows = meta["panel"].get("groups", {}).get("commissions", [])
    print(f"[{label}] area={meta['area']} square={meta['square']} "
          f"$4A81={meta['4A81']} $4A04={meta['4A04']} $4ABB={meta['4ABB']}",
          flush=True)
    for r in rows:
        print(f"          row: {r['name']!r} / {r['state']!r}", flush=True)
    return meta


def answer(sess, body, out, label, menu_at, option, expect,
           word_at=None, asks_at=None, budget=300.0) -> dict:
    """Answer whatever the square's script puts up, until `$4A81` reads `expect`.

    Driven by what is on the screen rather than by a fixed sequence, the same
    shape `tools/koboldnpc.py`'s `answer_the_exit` uses: a script answers a
    walked step with several screens and the order is not knowable in advance.
    `$4A81` is sampled on every pass, so the run measures when the engine
    wrote it rather than assuming the screen that followed.
    """
    options = menu_options(body, menu_at)
    want = options[option]
    asks = _squash(string_at(body, asks_at)) if asks_at else None
    word = string_at(body, word_at) if word_at else None
    started, shots, seen, typed = time.time(), 0, [], 0
    picked, blind = 0, 0
    result = {"picked": 0, "typed": 0, "screens": [], "seconds": None,
              "options": len(options)}
    while time.time() - started < budget:
        now = flag(sess)
        if now == expect:
            result["seconds"] = round(time.time() - started, 1)
            return result
        s = sess.screen()
        if s is None:
            # A picture puts the machine in bitmap mode and `Session.screen`
            # answers None rather than guess at glyphs. A continue prompt
            # underneath it still takes a Return, so press one now and then.
            blind += 1
            if blind % 8 == 0:
                sess.press_kernal(0x0D)
            time.sleep(0.4)
            continue
        blind = 0
        if sess.handle_prompt(s):
            continue
        row = s.row(24)
        if not seen or seen[-1] != row:
            seen.append(row)
            shots += 1
            sess.kbd.screenshot(str(out / f"{label}-bar-{shots:02d}.png"))
            # The bar is the game's own words: its length and its shape go in
            # the log, never the words themselves.
            result["screens"].append({"len": len(row.strip()),
                                      "words": len(row.split())})
        # A keypress the game swallowed leaves the same row up and is worth
        # re-sending, so this does not refuse a repeat -- it caps them, and
        # waits for the row to move before trying again. Without the cap a
        # script that ends on a bar carrying the same word would be answered
        # for ever.
        if want.upper() in row.upper() and picked < 6:
            if sess.select_bar(want, timeout=20):
                picked += 1
                result["picked"] = picked
                print(f"          menu: option {option + 1} of {len(options)}",
                      flush=True)
                for _ in range(8):              # let the answer take effect
                    time.sleep(0.4)
                    later = sess.screen()
                    if later is None or later.row(24) != row:
                        break
                continue
        if asks and asks in _squash(s.text()):
            sess.kbd.text(word)
            sess.press_kernal(0x0D)
            typed += 1
            result["typed"] = typed
            print(f"          typed the {len(word)}-letter word it asked for",
                  flush=True)
            time.sleep(1.5)
            continue
        upper = row.upper()
        if "PRESS" in upper or "BUTTON" in upper:
            sess.press_kernal(0x0D)
            time.sleep(1.0)
            continue
        if "FLEE" in upper and "PARLAY" in upper:
            # A wandering fight the run did not ask for. `calm` should stop
            # these before they start; if one gets through, avoiding it is
            # cheaper than a fight and leaves fewer of the game's own bytes
            # moved than winning one would.
            result["encounters"] = result.get("encounters", 0) + 1
            sess.select_bar("FLEE", timeout=10)
            time.sleep(2.0)
            continue
        if "YES" in upper and "NO" in upper:
            sess.select_bar("NO", timeout=10)
            time.sleep(1.0)
            continue
        if "GO BACK" in upper and "LEAVE TREASURE" in upper:
            # Ohlo's reward is a `TREASURE`/`COMBAT` pair and `$4A81` is not
            # written until the pair is finished with -- `$A3A1 COMBAT`,
            # `$A3A8 SAVE 255, [$4A81]`. Leaving the treasure is what ends
            # it without adding an item to anybody's record; taking it would
            # move bytes this run has no reason to move.
            result["treasure_left"] = result.get("treasure_left", 0) + 1
            sess.select_bar("LEAVE TREASURE", timeout=10)
            time.sleep(1.5)
            continue
        if "EXIT" in upper and "MOVE" not in upper:
            sess.select_bar("EXIT", timeout=10)
            time.sleep(1.0)
            continue
        time.sleep(0.4)
    result["seconds"] = None
    return result


def square_now(sess) -> tuple[int, int, int]:
    with sess.mon(5) as m:
        return tuple(m.read(SQUARE, 3))


def calm(sess, hold: int = WANDER_CAP) -> int:
    """Hold `$4A80` at its own cap, and say what it was.

    `ECL14 $9B32` and `$ADD6` are both `COMPARE [$4A80], 15 / IF>= / EXIT`, so
    a party at the cap is never rolled a wandering fight. The first run of
    this tool lost its budget to a group of goblins that interrupted the step
    into the booth; the fortune-teller run in `docs/50-experiments.md` lost
    one to three of them and a party wipe.

    **It is put back before anything is read.** `$4A80` is not a byte the
    Quest Log reads -- the slums row is ledger index 21, `$4ABB` -- but a run
    that leaves a flag holding a value the game did not put there is a run
    whose later readings nobody can trust.
    """
    was = flag(sess, WANDER_FLAG)
    with sess.mon(5) as m:
        m.write(WANDER_FLAG, bytes([hold]))
    return was


def uncalm(sess, was: int) -> None:
    with sess.mon(5) as m:
        m.write(WANDER_FLAG, bytes([was]))


def step_on(sess, where, out, label, tries: int = 5) -> dict:
    """Put the party on `where` and walk one square forward from it.

    The direction key is re-sent rather than pressed once. `Session.walk_one`
    says why: the first burst after a screen change is swallowed, and the
    move sub-bar has to be on the screen before `I` means anything. This
    cannot use `walk_one` itself because that verifies by the status line,
    and the Slums' line carries no coordinates -- `E 8:07`, no `x,y` -- so
    every step there reads as blocked.
    """
    with sess.mon(5) as m:
        m.write(SQUARE, bytes(where))
    sess.settle(2)
    print(f"  placed at {where} (x, y, facing), stepping forward", flush=True)
    sess.kbd.screenshot(str(out / f"{label}-placed.png"))
    log = {"placed": list(where), "presses": 0, "square": None, "moved": False}
    for _ in range(tries):
        s = sess.screen()
        row = "" if s is None else s.row(24)
        if MOVE_SUBBAR not in row:
            if not sess.select_bar("MOVE", timeout=20):
                time.sleep(1.0)
                continue
            for _ in range(10):                 # wait for the sub-bar itself
                time.sleep(0.3)
                s = sess.screen()
                if s is not None and MOVE_SUBBAR in s.row(24):
                    break
        sess.kbd.key(FORWARD.lower(), 0.15, 0.30)
        log["presses"] += 1
        for _ in range(10):
            time.sleep(0.4)
            here = square_now(sess)
            if here[:2] != tuple(where[:2]):
                log["square"], log["moved"] = list(here), True
                print(f"  stepped to {here[:2]} "
                      f"on press {log['presses']}", flush=True)
                return log
            s = sess.screen()
            if s is not None and MOVE_SUBBAR not in s.row(24):
                break                           # something answered the step
        log["square"] = list(square_now(sess))
    print(f"  never left {where[:2]} after {log['presses']} presses",
          flush=True)
    return log


#: Which side the Slums' own files are on. `ECL14 $995C` is `SAVE 2, [$6E12]`,
#: and the disk the game asks for on the way in is the one it names.
SLUMS_SIDE = 2


def unstick(sess, out) -> bool:
    """Answer the `insert side` prompt `Session.handle_prompt` did not see.

    Seen twice in four boots: the arrival prompt goes up, `wait_for_world`
    sits out its whole 240 s and the screen it is reading comes back **blank**
    -- `row 24` all spaces while a screenshot of the same moment shows the
    prompt. So the fault is in what the screen reader is pointed at rather
    than in the prompt handler's own match, and nothing that reads the screen
    can get out of it. #336 is the ticket.

    This does not read the screen. It attaches the side the Slums lives on
    and presses the key the prompt asks for, which is right whether or not
    anything can be read, and then waits again.
    """
    sess.kbd.screenshot(str(out / "00-no-world.png"))
    s = sess.screen()
    print(f"  no world bar; screen {'unreadable' if s is None else 'row 24 |' + s.row(24) + '|'}",
          flush=True)
    for attempt in range(3):
        sess.attach(f"{sess.here}/SIDE{SLUMS_SIDE}.D64")
        sess.kbd.key("space")
        print(f"  nudged side {SLUMS_SIDE}, attempt {attempt + 1}", flush=True)
        if sess.wait_for_world(120):
            return True
    sess.kbd.screenshot(str(out / "00-still-no-world.png"))
    return False


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    body = _script()
    log = {"save": args.save, "stages": []}
    slot = S.claim_slot(args.slot, "issue158 ohlo potion watch")
    print(f"Slot {slot.n} display {slot.display}", flush=True)
    sess = None
    try:
        boot = S.stage_disks(slot, DISKS, save=args.save)
        for p in pathlib.Path(slot.dir).glob("*.D64"):
            os.chmod(p, 0o644)
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("Boot failed")
        if not sess.load_save():
            raise RuntimeError("The game did not accept the save disk")
        if not sess.begin_adventuring() and not unstick(sess, out):
            raise RuntimeError("BEGIN ADVENTURING did not reach the world")
        sess.settle(4)

        first = capture(sess, out, "00-loaded", f"{args.save} just loaded")
        log["stages"].append(first)
        if first["area"] != SLUMS:
            raise RuntimeError(f"the save is in area {first['area']}, "
                               f"not the Slums ({SLUMS})")
        if first["4A81"] != 0:
            raise RuntimeError(f"$4A81 is already {first['4A81']}; this run "
                               f"needs a party that has not been to the booth")

        was = calm(sess) if args.calm else None
        log["wandering_was"] = was
        log["booth_step"] = step_on(sess, AT_BOOTH_DOOR, out, "01-booth")
        got = answer(sess, body, out, "01-booth", BOOTH_MENU, BOOTH_OPTION,
                     IN_HAND, word_at=BOOTH_WORD, asks_at=BOOTH_ASKS,
                     budget=args.budget)
        log["booth"] = got
        if was is not None:
            uncalm(sess, was)
        print(f"  booth: $4A81 reached {IN_HAND} after {got['seconds']}s"
              if got["seconds"] is not None else
              f"  booth: $4A81 never reached {IN_HAND}", flush=True)
        sess.settle(3)
        log["stages"].append(capture(sess, out, "01-potion-in-hand",
                                     "after the booth block, ECL14 $B048"))

        if was is not None:
            calm(sess)
        log["ohlo_step"] = step_on(sess, IN_OHLOS_ROOM, out, "02-ohlo")
        got = answer(sess, body, out, "02-ohlo", OHLO_MENU, OHLO_OPTION,
                     FINISHED, budget=args.budget)
        log["ohlo"] = got
        if was is not None:
            uncalm(sess, was)
        print(f"  Ohlo: $4A81 reached {FINISHED} after {got['seconds']}s"
              if got["seconds"] is not None else
              f"  Ohlo: $4A81 never reached {FINISHED}", flush=True)
        sess.settle(3)
        log["stages"].append(capture(sess, out, "02-delivered",
                                     "after Ohlo's block, ECL14 $A3A8"))
        return 0
    finally:
        (out / "run.json").write_text(json.dumps(log, indent=1))
        for what, fn in (("session", sess.terminate if sess else None),
                         ("slot teardown", slot.teardown),
                         ("slot release", slot.release)):
            if fn is None:
                continue
            try:
                fn()
            except Exception as e:              # noqa: BLE001
                print(f"  {what} failed: {e}", flush=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="mode")
    r = sub.add_parser("rows", help="render the Quest Log from a captured window")
    r.add_argument("--bin", required=True)
    r.add_argument("--png", default="")
    r.add_argument("--width", type=int, default=300)
    p.add_argument("--save", default="NEWSAVE4.D64",
                   help="a save disk with the party standing in the Slums "
                        "and $4A81 still 0; copied in as SIDE0")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--out", default=str(ROOT / "work" / "issue158"))
    p.add_argument("--budget", type=float, default=300.0,
                   help="seconds to spend answering one square's script")
    p.add_argument("--no-calm", dest="calm", action="store_false",
                   help="leave $4A80 alone, and take whatever wandering "
                        "fights the two steps roll")
    args = p.parse_args(argv)
    if args.mode == "rows":
        return rows_mode(args)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
