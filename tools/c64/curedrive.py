#!/usr/bin/env python3
"""Stage a C64 Curse paladin's cure-disease state and watch the game use it.

    tools/c64/curedrive.py stage --base SAVE.D64 --out STAGED.D64 \\
        --who PALADIN --level 11 --cures 1 --row-minutes 3000
    tools/c64/curedrive.py run --save STAGED.D64 --out DIR \\
        --script "read;sheet;cure;read;rest 6:0:0;read;rest 1:0:0;read;sheet"

`stage` writes **inputs only** into a copy of a Curse save, through
`goldbox.savegame`: the paladin level `0x0CF`, the uses left `0x012`, and
any number of cure-timer rows (id 141) in the save's effect arrays -- id at
payload `0x000`, owner `0x040`, duration `0x080`, magnitude `0x280`.  A row's
duration is given either as a byte or as DOS minutes left, which
`goldbox.effects.closest_duration` turns into the byte at the save's own
clock.  Every existing 140/141 row the paladin owns is cleared first, so the
staged rows are the only ones.

`run` boots the staged save on a pooled VICE slot, walks it into the world
and plays a `;`-separated script, logging one JSON line per step under
`--out` with a screenshot and the screen text:

* `read` -- the paladin's `0x012`, `0x013` and `0x0CF` from his save slot
  and from the `$7C00` staging page, every 140/141 row, and the clock;
* `sheet` -- `VIEW` the paladin and record the command bar, which offers
  `CURE` only while `0x012` is not 0 (`LIBRARY $46AB`);
* `cure` -- `VIEW`, `CURE`, pick the first character offered, answer any
  question with `Y`, and leave the sheet;
* `rest D:H:M` -- `ENCAMP`, `REST`, write the rest time into the camp's
  own field, rest until the clock stops, read, and `EXIT`;
* `expire` -- rest to five minutes short of the paladin's cure row's
  expiry, read, then rest fifteen minutes more and read;
* `save [NAME]` -- the game's own `ENCAMP > SAVE`, and the disk kept.

Everything is done from the camp: the world's `VIEW` sheet offers `EXIT`
alone whatever the paladin holds (`$7FF7` is `$41` there and `$FF` in camp),
so only the camp's `VIEW` can show `CURE`.

Non-stopping exec checkpoints count `ECL65 $870C` (the cure's `JSR` that
adds the timer), `$870F` (its `DEC $7C12`) and `$85BA` (the camp's reset of
`0x012` when a 141 row expires); their counts are logged with every `read`.

Nothing writes to the player's disks; the staged save is a copy and the slot
copies the six sides.  `summary DIR...` prints each run's readings.
Findings: `docs/234-a-paladins-cure-disease-across-dos-and-the-c64.md`.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import struct
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import effects  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save, store_save  # noqa: E402

#: The later titles' four effect arrays, as offsets into the save payload
#: that loads at `$4B00` (`docs/226-the-c64-running-effect-crosswalk.md`).
PAYLOAD_BASE = 0x4B00
ROW_ID, ROW_OWNER, ROW_DURATION, ROW_MAGNITUDE = 0x000, 0x040, 0x080, 0x280
ROWS = 0x40

#: The magnitude the cure writes (Curse `ECL65 $8701`-`$8709`, Silver
#: Blades `$873D`-`$8745`): the same byte as the starting duration.
CURE_MAGNITUDE = 0xC7

#: Per title: the cure and lay-on-hands timer ids, `CAMP`'s rest-time field
#: (minutes, hours, days; zeroed at Curse `CAMP $1D54`, Silver Blades
#: `$1B52`), and what the checkpoints count in `ECL65`, which loads at
#: `$8000` and stays there through the camp -- the cure's `JSR` that adds the
#: timer, its `DEC $7C12`, and the camp's reset of `0x012` when a cure row
#: expires.
TITLES = {
    "curse-of-the-azure-bonds": {
        "cure_id": 141, "heal_id": 140, "rest_field": 0x2C1B,
        "points": {"cure_timer_add": 0x870C, "cure_dec": 0x870F,
                   "cure_reset": 0x85BA}},
    "secret-of-the-silver-blades": {
        "cure_id": 110, "heal_id": 109, "rest_field": 0x2A8E,
        "points": {"cure_timer_add": 0x8748, "cure_dec": 0x874B,
                   "cure_reset": 0x8657}},
}

#: The game clock: sub-minute, minute units, minute tens, hour, day, month
#: (`tools/c64/c64clock.py`).  Payload offset `0xC6`.
CLOCK = 0x4BC6

#: The staging page and the three record bytes this reads.
STAGING = 0x7C00
CURES, LAY_ON_HANDS, PALADIN_LEVEL = 0x012, 0x013, 0x0CF

#: What only the camp's own bar carries, in both titles: Curse draws
#: `CAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT` and Silver Blades the same
#: without `CAMP:`.
CAMP_BAR = "REST ALTER"

#: The area's rest-interruption interval and chance, read by Curse
#: `CAMP $1F76` and Silver Blades `CAMP $1D73`.
REST_INTERRUPT = 0x7ED2


# --- staging ---------------------------------------------------------------

def clock_minutes(payload: bytes) -> int:
    """Minutes since midnight on the save's clock."""
    at = CLOCK - PAYLOAD_BASE
    units, tens, hour = payload[at + 1], payload[at + 2], payload[at + 3]
    return hour * 60 + tens * 10 + units


def paladin_rows(payload: bytes, owner: int, conf: dict) -> list[dict]:
    """Every cure and lay-on-hands row, with its slot index and bytes."""
    out = []
    for i in range(ROWS):
        eid = payload[ROW_ID + i]
        if eid in (conf["cure_id"], conf["heal_id"]):
            out.append({"row": i, "id": eid, "owner": payload[ROW_OWNER + i],
                        "duration": payload[ROW_DURATION + i],
                        "magnitude": payload[ROW_MAGNITUDE + i],
                        "mine": payload[ROW_OWNER + i] == owner})
    return out


def find_slot(sg0, who: str):
    for slot in sg0.characters:
        rec = slot.record
        if rec is not None and rec.name.strip().upper() == who.upper():
            return slot
    names = [s.record.name for s in sg0.characters if s.record is not None]
    raise SystemExit(f"no character called {who!r}; the save has {names}")


def stage(base: pathlib.Path, out: pathlib.Path, who: str, level: int | None,
          cures: int, rows: list[tuple[int, int]], owner: int | None) -> dict:
    """Write the inputs into a copy of `base` at `out`, and describe them.

    `rows` is `(duration byte, magnitude)` per cure-timer row wanted.
    """
    disk = D64.from_bytes(base.read_bytes())
    game, sg0, sg1 = load_save(disk)
    conf = TITLES[game.key]
    slot = find_slot(sg0, who)
    rec = slot.record
    if level is not None:
        rec.level_paladin = level
    rec.paladin_cures = cures
    sg0.write_record(slot.index, rec)
    who_owns = slot.index if owner is None else owner
    payload = bytearray(sg0.to_bytes())
    for i in range(ROWS):
        if (payload[ROW_ID + i] in (conf["cure_id"], conf["heal_id"])
                and payload[ROW_OWNER + i] == who_owns):
            for off in (ROW_ID, ROW_OWNER, ROW_DURATION, ROW_MAGNITUDE):
                payload[off + i] = 0
    for duration, magnitude in rows:
        free = next(i for i in range(ROWS) if payload[ROW_ID + i] == 0)
        payload[ROW_ID + free] = conf["cure_id"]
        payload[ROW_OWNER + free] = who_owns
        payload[ROW_DURATION + free] = duration
        payload[ROW_MAGNITUDE + free] = magnitude
    sg0 = type(sg0).from_bytes(bytes(payload), game)
    store_save(disk, sg0, None, game)
    out.parent.mkdir(parents=True, exist_ok=True)
    disk.save(str(out))
    check = load_save(D64.from_bytes(out.read_bytes()))[1]
    got = find_slot(check, who).record
    body = check.to_bytes()
    return {"save": str(out), "who": who, "slot": slot.index,
            "level_paladin": got.level_paladin,
            "paladin_cures": got.paladin_cures,
            "lay_on_hands_uses": got.lay_on_hands_uses,
            "clock_minutes": clock_minutes(body),
            "title": game.key, "rows": paladin_rows(body, who_owns, conf)}


def parse_rows(args, payload_clock: int) -> list[tuple[int, int]]:
    rows = []
    for text in args.row or ():
        byte, _, mag = text.partition(":")
        rows.append((int(byte, 16), int(mag, 16) if mag else CURE_MAGNITUDE))
    for minutes in args.row_minutes or ():
        byte = effects.closest_duration(minutes, payload_clock)
        if byte is None:
            raise SystemExit(f"{minutes} minutes has no duration byte")
        rows.append((byte, CURE_MAGNITUDE))
    return rows


def cmd_stage(args) -> int:
    base = pathlib.Path(args.base)
    payload = load_save(D64.from_bytes(base.read_bytes()))[1].to_bytes()
    rows = parse_rows(args, clock_minutes(payload))
    info = stage(base, pathlib.Path(args.out), args.who, args.level,
                 args.cures, rows, args.owner)
    for r in info["rows"]:
        r["minutes_left"] = effects.remaining_minutes(r["duration"],
                                                      info["clock_minutes"])
    print(json.dumps(info, indent=2))
    return 0


# --- driving ----------------------------------------------------------------

def _session_class():
    """`curserun.CurseSession`, whose own `boot` already survives a VICE
    dialog swallowing the fastloader answer."""
    from tools.curse_of_the_azure_bonds import curserun

    return curserun.CurseSession


def _silver_session_class():
    """`ssbwarp.SSBSession` with `CurseSession`'s bar helpers.

    The camp, sheet and rest steps below wait for and press bars the same way
    in both later titles; `curserun.CurseSession` holds those helpers and
    Silver Blades' session does not, so they are borrowed rather than
    copied.
    """
    from tools.curse_of_the_azure_bonds import curserun
    from tools.secret_of_the_silver_blades import ssbwarp

    class SilverCureSession(ssbwarp.SSBSession):
        BLANK = curserun.CurseSession.BLANK
        press_bar = curserun.CurseSession.press_bar
        wait_bar = curserun.CurseSession.wait_bar
        to_world_bar = curserun.CurseSession.to_world_bar

    return SilverCureSession


class Run:
    """One boot of a staged save, and the log of everything done to it."""

    def __init__(self, out: pathlib.Path, save: pathlib.Path, who: str,
                 disks: str, pool: int | None):
        from tools.c64 import session as por
        from tools.curse_of_the_azure_bonds import curserun
        from tools.secret_of_the_silver_blades import ssbwarp
        self.out = out
        self.who = who
        self.disks = disks
        self.log_file = (out / "curedrive.jsonl").open("a")
        self.n = 0
        game, payload, _ = load_save(D64.from_bytes(save.read_bytes()))
        self.title = game.key
        self.conf = TITLES[game.key]
        self.silver = game.key == "secret-of-the-silver-blades"
        self.slot = por.claim_slot(pool, "curedrive")
        stage_sides = ssbwarp.stage if self.silver else curserun.stage
        first = stage_sides(self.slot, disks, str(save))
        self.save_disk = str(pathlib.Path(self.slot.dir) / "SIDE0.D64")
        os.chmod(self.save_disk, 0o644)
        cls = _silver_session_class() if self.silver else _session_class()
        self.sess = cls(first, slot=self.slot)
        self.sess.save_disk = self.save_disk
        self.checkpoints: dict[str, int] = {}
        self.stack = contextlib.ExitStack()
        self.slot_index = find_slot(payload, who).index
        self.window = payload._window_offset(self.slot_index)
        self.log(event="slot", title=self.title, n=self.slot.n,
                 display=self.slot.display,
                 cmd_port=self.slot.cmd_port, save=str(save), who=who,
                 save_slot=self.slot_index,
                 record_address=f"${PAYLOAD_BASE + self.window:04X}")

    def log(self, **kw) -> None:
        kw["t"] = round(time.time(), 2)
        line = json.dumps(kw, default=str)
        self.log_file.write(line + "\n")
        self.log_file.flush()
        print(line, flush=True)

    def shot(self, tag: str) -> str:
        self.n += 1
        name = f"{self.n:02d}-{tag}"
        self.sess.kbd.screenshot(str(self.out / f"{name}.png"))
        s = self.sess.screen()
        text = "(bitmap)" if s is None else "\n".join(s.row(r)
                                                      for r in range(25))
        (self.out / f"{name}.txt").write_text(text + "\n")
        return name

    def row24(self) -> str:
        s = self.sess.screen()
        return "" if s is None else s.row(24).strip()

    # -- boot ----------------------------------------------------------------
    def boot(self, wait: float) -> bool:
        # VICE's own warning dialogs take the keyboard away from the game;
        # the watcher answers them for the whole run.
        self.stack.enter_context(self.sess.watching_dialogs())
        if not self.sess.boot():
            self.log(event="boot-failed")
            return False
        if not (self._enter_silver(wait) if self.silver
                else self._enter_curse(wait)):
            return False
        self.shot("world")
        with self.sess.mon(10) as m:
            for name, address in self.conf["points"].items():
                self.checkpoints[name] = m.checkpoint_set(
                    address, exec_=True, stop=False)
            m.resume()
        return True

    def _enter_silver(self, wait: float) -> bool:
        from tools.secret_of_the_silver_blades import ssbwarp
        if not ssbwarp.load_party(self.sess):
            self.log(event="load", outcome="not loaded")
            return False
        addr = ssbwarp.Addresses(self.sess.game, self.disks)
        if not ssbwarp.enter_world(self.sess, addr, timeout=wait):
            self.log(event="never-reached-the-world")
            self.shot("stuck")
            return False
        self.log(event="world", bar=ssbwarp.clear_messages(self.sess))
        # A loaded Silver Blades party can arrive on the starting-treasure
        # bar or a sheet it opens, `VIEW TAKE POOL SHARE EXIT` or `EXIT`, and
        # leaving the treasure asks `GO BACK LEAVE TREASURE`; `to_world_bar`
        # answers none of the three.
        for _ in range(12):
            row = self.row24()
            if "ENCAMP" in row:
                return True
            if "LEAVE TREASURE" in row:
                self.sess.press_bar("LEAVE TREASURE")
            elif "EXIT" in row.split():
                self.sess.press_bar("EXIT")
            elif not self.sess.to_world_bar(timeout=20):
                continue
            time.sleep(1.5)
        self.log(event="never-reached-the-world-bar", row24=self.row24())
        return False

    def _enter_curse(self, wait: float) -> bool:
        from tools.curse_of_the_azure_bonds import curseload, cursewarp
        outcome = curseload.load_saved_game(
            self.sess, note=lambda **kw: self.log(**kw),
            shot=lambda tag: self.shot(tag), wait=wait)
        self.log(event="load", outcome=outcome)
        if outcome != "loaded":
            return False
        self.sess.patch_disk_prompt()
        addr = cursewarp.Addresses(self.sess.game, self.disks)
        if not cursewarp.enter_world(self.sess, addr, timeout=wait):
            self.log(event="never-reached-the-world")
            self.shot("stuck")
            return False
        self.log(event="world", bar=cursewarp.clear_messages(self.sess))
        return True

    # -- readings ------------------------------------------------------------
    def read(self, tag: str = "read") -> dict:
        with self.sess.mon(10) as m:
            head = bytes(m.read(PAYLOAD_BASE, 0x300))
            rec = bytes(m.read(PAYLOAD_BASE + self.window, 0x100))
            staging = bytes(m.read(STAGING, 0x100))
            clock = list(m.read(CLOCK, 6))
            counts = {}
            for name, number in self.checkpoints.items():
                body = m.command(0x11, struct.pack("<I", number))
                counts[name] = struct.unpack("<I", body[13:17])[0]
            m.resume()
        payload = head + bytes(0x300)
        rows = paladin_rows(payload, self.slot_index, self.conf)
        minute = clock[3] * 60 + clock[2] * 10 + clock[1]
        for r in rows:
            r["minutes_left"] = effects.remaining_minutes(r["duration"],
                                                          minute)
        reading = {
            "tag": tag,
            "slot": {"cures": rec[CURES], "lay_on_hands": rec[LAY_ON_HANDS],
                     "level_paladin": rec[PALADIN_LEVEL],
                     "name": rec[:16].split(b"\0")[0].decode("latin1")},
            "staging": {"cures": staging[CURES],
                        "lay_on_hands": staging[LAY_ON_HANDS],
                        "level_paladin": staging[PALADIN_LEVEL],
                        "name": staging[:16].split(b"\0")[0].decode("latin1")},
            "rows": rows,
            "clock": {"digits": clock, "day": clock[4], "hour": clock[3],
                      "minute": clock[2] * 10 + clock[1]},
            "counts": counts,
        }
        self.log(event="read", **reading)
        return reading


    # -- steps ---------------------------------------------------------------
    def in_camp(self) -> bool:
        return CAMP_BAR in self.row24()

    def camp(self) -> bool:
        """`ENCAMP`, then clear the area's rest interruption.

        Tilverton's streets set `$7ED2`/`$7ED3` to 1 and `$FF` when the party
        camps (`CAMP $1F76`-`$1F8C` reads them every five-minute pass), so a
        rest there ends after five minutes with `ROYAL GUARDS TELL YOU TO MOVE
        ALONG.`  Zeroing the interval is an input to the rest loop alone: it
        touches no record byte and no effect row.
        """
        if not self.in_camp():
            if not self.sess.to_world_bar():
                return False
            if not self.sess.wait_bar("ENCAMP") or not self.sess.press_bar(
                    "ENCAMP"):
                return False
            if not self.sess.wait_bar(CAMP_BAR, 60):
                return False
        with self.sess.mon(10) as m:
            was = list(m.read(REST_INTERRUPT, 2))
            m.write(REST_INTERRUPT, b"\0")
            m.resume()
        self.log(event="camp", rest_interrupt_was=was)
        return True

    def pick_paladin(self) -> bool:
        from tools.c64 import session as por
        rows = self.sess.stable_party_rows()
        s = self.sess.screen()
        names = [] if s is None else [
            s.row(r)[por.PARTY_COLUMN:].strip() for r in rows]
        index = next((k for k, text in enumerate(names)
                      if text.upper().startswith(self.who.upper())), None)
        if index is None:
            self.log(event="no-paladin-row", panel=names)
            return False
        return self.sess.select_party(index)

    def open_sheet(self) -> str | None:
        if not self.camp() or not self.pick_paladin():
            return None
        if not self.sess.press_bar("VIEW"):
            return None
        deadline = time.time() + 30
        while time.time() < deadline:
            s = self.sess.screen()
            if s is not None and "EXIT" in s.row(24) and \
                    self.who.upper() in s.row(1).upper():
                time.sleep(0.8)
                return self.row24()
            time.sleep(0.4)
        return None

    def close_sheet(self) -> None:
        if "EXIT" in self.row24() and not self.in_camp():
            self.sess.press_bar("EXIT")
        self.sess.wait_bar(CAMP_BAR, 20)

    def sheet(self) -> dict:
        bar = self.open_sheet()
        name = self.shot("sheet")
        self.log(event="sheet", bar=bar, cure_offered=bool(
            bar and "CURE" in bar.split()), shot=name)
        self.close_sheet()
        return {"bar": bar}

    def cure(self) -> dict:
        """`CURE` on the paladin's camp sheet, on the first name offered."""
        bar = self.open_sheet()
        if not bar or "CURE" not in bar.split():
            self.log(event="cure-not-offered", bar=bar, shot=self.shot(
                "cure-not-offered"))
            self.close_sheet()
            return {"cured": False, "bar": bar}
        self.sess.press_bar("CURE")
        target = None
        # Silver Blades takes about half a minute to put the prompt up.
        deadline = time.time() + 120
        while time.time() < deadline:
            if "WHOM" in self.row24():
                target = self.row24()
                break
            time.sleep(0.4)
        self.shot("cure-whom")
        if target is None:
            self.log(event="cure-no-prompt", row24=self.row24())
            self.close_sheet()
            return {"cured": False}
        self.sess.kbd.key("Return", 0.15, 0.30)
        deadline = time.time() + 20
        while time.time() < deadline and "WHOM" in self.row24():
            time.sleep(0.4)
        time.sleep(1.5)
        after = self.row24()
        name = self.shot("cured")
        self.log(event="cure", prompt=target, bar_after=after, shot=name)
        self.close_sheet()
        return {"cured": True}

    def rest(self, days: int, hours: int, minutes: int) -> dict:
        """`REST` for exactly the time given, written into `$2C1B`-`$2C1D`."""
        if not self.camp():
            return {"failed": "no camp"}
        if not self.sess.press_bar("REST") or not self.sess.wait_bar(
                "SUBTRACT", 20):
            return {"failed": "no rest-time bar"}
        with self.sess.mon(10) as m:
            m.write(self.conf["rest_field"], bytes((minutes, hours, days)))
            m.resume()
        before = self.read(f"rest-before {days}:{hours}:{minutes}")
        self.sess.press_bar("REST")
        deadline = time.time() + 900
        while time.time() < deadline:
            time.sleep(3)
            with self.sess.mon(10) as m:
                left = bytes(m.read(self.conf["rest_field"], 3))
                m.resume()
            if left == b"\0\0\0" and self.in_camp():
                break
            if "CONTINUE" in self.row24():
                self.log(event="rest-interrupted", row24=self.row24(),
                         shot=self.shot("rest-interrupted"))
                return {"failed": "interrupted"}
        after = self.read(f"rest-after {days}:{hours}:{minutes}")
        self.shot("rested")
        return {"before": before, "after": after}

    def rest_to_expiry(self) -> None:
        """Rest to five minutes short of the paladin's cure row, then past it.

        The time left is the engine's own rule for a unit's digit wrap,
        `goldbox.effects.remaining_minutes`, read off the live clock.
        """
        now = self.read("expiry-plan")
        mine = [r for r in now["rows"]
                if r["mine"] and r["id"] == self.conf["cure_id"]]
        if not mine:
            self.log(event="no-row-to-expire")
            return
        left = min(r["minutes_left"] for r in mine)
        short = max(0, (left - 1) // 5 * 5)
        self.log(event="expiry-plan", minutes_left=left, short_rest=short)
        if short:
            self.rest(short // 1440, short % 1440 // 60, short % 60)
        self.rest(0, 0, 15)

    def save(self, keep: pathlib.Path) -> bool:
        """The camp's own `SAVE`, then `SAVE GAME`, and the disk kept.

        `CurseSession.save_game` starts from the world bar, and the steps
        here end in camp, so this presses the two camp bars itself; the
        save disk goes back in the drive first, as `save_game` does.
        """
        from tools.c64 import session as por
        ok = self.camp()
        for word in ("SAVE", "SAVE GAME"):
            if word == "SAVE GAME":
                self.sess.attach(self.save_disk)
            ok = ok and self.sess.wait_bar(word) and self.sess.press_bar(word)
        ok = ok and self.sess.wait_text("SAVING GAME", 30)[0] is not None
        # The write is over when the camp bar is back; a copy taken while
        # `SAVING GAME...` is still up finds `SAVEAZURE` unclosed.
        ok = ok and self.sess.wait_bar(CAMP_BAR, 180)
        self.sess.settle(4)
        self.shot("saved")
        if ok:
            try:
                por.copy_closed_disk(pathlib.Path(self.save_disk), keep)
            except RuntimeError as exc:
                self.log(event="save-not-copied", error=str(exc))
                ok = False
        self.log(event="saved", ok=ok, kept=str(keep) if ok else None)
        return ok

    def play(self, script: str) -> None:
        for step in filter(None, (s.strip() for s in script.split(";"))):
            verb, _, arg = step.partition(" ")
            self.log(event="step", step=step)
            if verb == "read":
                self.read(arg or "read")
            elif verb == "sheet":
                self.sheet()
            elif verb == "cure":
                self.cure()
            elif verb == "rest":
                d, h, m = (int(x) for x in arg.split(":"))
                self.rest(d, h, m)
            elif verb == "expire":
                self.rest_to_expiry()
            elif verb == "save":
                self.save(self.out / (arg or "saved.D64"))
            else:
                raise SystemExit(f"unknown step {step!r}")


def cmd_run(args) -> int:
    from automap import gamedisks
    from tools.registry import scratch
    out = scratch.ensure(pathlib.Path(args.out))
    disks = args.disks or str(gamedisks.find(
        load_save(D64.from_bytes(pathlib.Path(args.save).read_bytes()))[0].key)
        or "")
    run = Run(out, pathlib.Path(args.save), args.who, disks, args.pool)
    rc = 0
    try:
        if not run.boot(args.wait):
            return 1
        run.read("arrived")
        run.play(args.script)
        if args.serve:
            from tools.c64 import session as por
            run.log(event="serving", port=run.slot.cmd_port)
            por.serve(run.sess)
    except Exception as exc:                        # noqa: BLE001
        run.log(event="failed", error=repr(exc))
        rc = 1
    finally:
        with contextlib.suppress(Exception):
            run.shot("end")
        run.stack.close()
        run.sess.close()
        run.slot.teardown()
        run.log_file.close()
    return rc


def summarise(run_dir: pathlib.Path) -> list[str]:
    """One line per reading and per sheet, from a run's `curedrive.jsonl`."""
    out = []
    for line in (run_dir / "curedrive.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e["event"] == "read":
            c = e["clock"]
            rows = [f"{r['id']}/${r['duration']:02X}/${r['magnitude']:02X}"
                    f"/owner {r['owner']}/{r['minutes_left']}m"
                    for r in e["rows"] if r["mine"]]
            out.append(f"{e['tag']:<22} day {c['day']} {c['hour']:02d}:"
                       f"{c['minute']:02d}  0x012={e['slot']['cures']}  "
                       f"rows {rows or '-'}  {e['counts']}")
        elif e["event"] in ("sheet", "cure", "cure-not-offered", "saved",
                            "rest-interrupted", "failed"):
            keep = {k: v for k, v in e.items() if k not in ("t", "event")}
            out.append(f"{e['event']:<22} {keep}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    st = sub.add_parser("stage", help="write the inputs into a save copy")
    st.add_argument("--base", required=True)
    st.add_argument("--out", required=True)
    st.add_argument("--who", default="PALADIN")
    st.add_argument("--level", type=int, default=None)
    st.add_argument("--cures", type=int, required=True)
    st.add_argument("--row", action="append",
                    help="a cure-timer row: DURATION[:MAGNITUDE], hex")
    st.add_argument("--row-minutes", type=int, action="append",
                    help="a cure-timer row for DOS minutes left")
    st.add_argument("--owner", type=int, default=None,
                    help="the row's owner byte; default the save slot")
    rn = sub.add_parser("run", help="boot a staged save and play a script")
    rn.add_argument("--save", required=True)
    rn.add_argument("--out", required=True)
    rn.add_argument("--who", default="PALADIN")
    rn.add_argument("--disks", default="",
                    help="the title's six sides; default the registry's")
    rn.add_argument("--pool", type=int, default=None)
    rn.add_argument("--wait", type=float, default=240.0)
    rn.add_argument("--script", default="")
    rn.add_argument("--serve", action="store_true")
    sm = sub.add_parser("summary", help="print what each run read")
    sm.add_argument("runs", nargs="+")
    args = ap.parse_args(argv)
    if args.mode == "summary":
        for run in args.runs:
            print(f"== {run}")
            print("\n".join(summarise(pathlib.Path(run))))
        return 0
    return cmd_stage(args) if args.mode == "stage" else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
