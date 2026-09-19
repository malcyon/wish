#!/usr/bin/env python3
"""The one measurement `#350 (The Messages window logs the party's attacks and
dice but nothing a monster does)` had not taken: the assembled window,
`AutomapBinding` on its own `QTimer`, against a live driven fight -- rather
than `CombatLog.poll` driven directly by a harness, which is all
`tools/monstermsg.py fight` does.

**Why this needed its own target.** `automap/target.py`'s `ViceTarget` holds
one binary-monitor connection open for the whole session and resumes it
between reads. `tools/c64/session.py`'s `Session` does the opposite for every
action it takes -- `press_kernal`, `combat_turn`, `melee_turn`, `screen()`,
all of it opens `Session.mon()` fresh and closes it again. VICE serves
exactly one binary-monitor connection per process, so a persistent
`ViceTarget` and `Session`'s own transient connections cannot both be open
against the same instance: whichever holds the socket starves the other.

`TransientTarget` below takes `Session`'s side of that discipline instead of
`ViceTarget`'s: connect, do the one read or write, disconnect. It only
implements `read`/`write` -- `automap.state.read_fix` and `automap.combatlog.
CombatLog.poll` both fall back to that alone when a backend has no `fix()` or
`banks()`, which is the whole reason a simple `Target` was ever enough for a
test fixture.

Claims one pool slot, stages `PORSAVE13.D64` from the player's own disks
(`$POR_DISKS`, else `automap.paths.find_disks()`), walks until a fight starts
and then pumps the real Qt event loop for `--budget` seconds while the fight is
driven. Writes one JSON line per event to `--out`.

Run offscreen, single slot, foreground with a timeout:

    env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \\
        GDK_BACKEND=x11 .venv/bin/python -m tools.gui.automapfightwindow
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from automap.paths import find_disks  # noqa: E402
from automap.state import Automapper  # noqa: E402
from automap.vice import Monitor  # noqa: E402
from automap.window import AutomapBinding  # noqa: E402
from tools import scratch  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from wish.ui_window import Ui_WishWindow  # noqa: E402


class TransientTarget:
    """A `Target` that connects fresh for every read/write. See module docstring."""

    def __init__(self, port: int):
        self.port = port

    def read(self, addr: int, length: int) -> bytes:
        with Monitor(port=self.port, timeout=5) as m:
            return m.read(addr, length)

    def write(self, addr: int, data: bytes) -> None:
        with Monitor(port=self.port, timeout=5) as m:
            m.write(addr, data)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path,
                    default=scratch.scratch_dir("automapfightwindow") / "events.jsonl",
                    help="where to write the JSON-lines event log")
    ap.add_argument("--budget", type=float,
                    default=float(os.environ.get("WHOLEWINDOW_BUDGET", "300")),
                    help="seconds to drive the fight for (default: "
                         "$WHOLEWINDOW_BUDGET, else 300)")
    args = ap.parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    out = args.out
    config_dir = out.parent / "automapfightwindow-config"

    disks = os.environ.get("POR_DISKS") or str(find_disks() or "")
    if not disks or not os.path.isdir(disks):
        print("No game disks. Set $POR_DISKS.", file=sys.stderr)
        return 2

    scratch.ensure(config_dir)
    lines = out.open("w")

    def emit(kind, **kw):
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        lines.write(json.dumps(kw, default=str) + "\n")
        lines.flush()

    app = QApplication.instance() or QApplication([])
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)

    slot = S.claim_slot(None, "issue350-wholewindow")
    sess = None
    try:
        sess = S.Session(S.stage_disks(slot, disks, "PORSAVE13.D64"), slot=slot)
        print(f"slot {slot.n} display {slot.display}  log {out}", flush=True)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)

        # Set only after `Session.boot()` has launched VICE through the
        # flatpak -- `Session.launch()` copies the *whole* process environment
        # into that subprocess (`instance.launch_env`), and `$XDG_DATA_HOME` is
        # where flatpak keeps its own record of which refs are installed. Set
        # globally before the boot, it makes flatpak look for VICE in an empty
        # scratch directory and fail with "app/net.sf.VICE/x86_64/master not
        # installed".
        os.environ["XDG_CONFIG_HOME"] = str(config_dir / "config")
        os.environ["XDG_DATA_HOME"] = str(config_dir / "data")

        target = TransientTarget(slot.port)
        mapper = Automapper(target, {})
        binding = AutomapBinding(root, mapper, interval_ms=200)
        emit("assembled")

        steps = 0
        while not sess.in_combat():
            if steps > 400:
                raise RuntimeError("route exhausted with no fight")
            sess.walk_one("I")
            sess.handle_prompt()
            steps += 1
        emit("fight_start", steps=steps)
        print(f"fight after {steps} steps", flush=True)

        binding.timer.start(200)
        end = time.time() + args.budget
        last_line_count = 0

        def note_messages():
            nonlocal last_line_count
            lines_now = binding.messages.lines()
            for line in lines_now[last_line_count:]:
                emit("panel_line", line=line)
                print(f"  panel: {line}", flush=True)
            last_line_count = len(lines_now)

        while time.time() < end and sess.mode() == S.COMBAT:
            # Pump the real Qt event loop so `binding.timer`'s own QTimer
            # fires `AutomapBinding.tick()` on its own schedule -- not a
            # substitute call, the actual signal/slot the shipped window uses.
            app.processEvents()
            time.sleep(0.02)
            note_messages()

            s = sess.screen()
            text = s.text() if s is not None else ""
            if S.LOST_TEXT in text or S.WON_TEXT in text:
                emit("outcome", text=S.LOST_TEXT if S.LOST_TEXT in text
                     else S.WON_TEXT)
                break
            bar = sess.combat_state(s)
            if bar.kind == S.BAR_COMMAND:
                emit("turn", bar=bar.text)
                sess.combat_turn()
            elif bar.kind == S.BAR_DONE:
                sess.end_turn()
            elif bar.kind in (S.BAR_PRESS,):
                sess.press_kernal(0x0D)
            elif bar.kind == S.BAR_MOVE:
                sess.press_kernal(0x0D)
            elif bar.kind in (S.BAR_YESNO, S.BAR_CONTINUE):
                sess.combat_bar("NO", timeout=8)
            elif bar.kind == S.BAR_DISK:
                sess.handle_prompt(s)
            else:
                sess.idle(0.05)
            note_messages()

        # A few more pumps after the loop ends, so a tick already queued
        # (the fight's last message, flushed when `poll_battle` sees the
        # battle disappear) gets a chance to land in the panel.
        for _ in range(20):
            app.processEvents()
            time.sleep(0.02)
        note_messages()

        panel_lines = binding.messages.lines()
        monster_lines = [ln for ln in panel_lines
                         if any(w in ln.lower() for w in ("orc",))]
        emit("summary", panel_line_count=len(panel_lines),
             monster_lines=len(monster_lines), battle=str(binding.battle))
        print(f"\n{len(panel_lines)} panel lines, "
              f"{len(monster_lines)} mentioning a monster", flush=True)
    except Exception as exc:
        import traceback
        emit("failed", error=repr(exc), traceback=traceback.format_exc())
        traceback.print_exc()
        return 1
    finally:
        lines.close()
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:                       # noqa: BLE001
                print(f"{what}: {exc!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
