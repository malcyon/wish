#!/usr/bin/env python3
"""Watch a converted party's `WRITE_UNSOURCED` bytes through a DOS fight.

The measurement `#69 (No WRITE_UNSOURCED zero has been tested during combat)`
asks for.  `goldbox.dos.write` leaves nine fields zero on the grounds that the
engine supplies its own value, and every measurement behind that is a load, a
`VIEW` and a resave **outside a fight**.  `tools/dosfightrun.py` proved the
fight can be driven; this puts the debugger on the record while it happens.

**There is no read watchpoint.**  DOSBox-X's three memory breakpoints -- `BPM`,
`BPLM`, `BPPM` -- are all "memory change" (`docs/142-dosbox-x-debugger.md`),
so the direct question "is this byte read during a round" cannot be asked of
this emulator.  What can be asked, and is what this tool measures, is
**when the engine writes over our zero, relative to the fight's own phases**:
a field the engine rewrites before the first character's command bar appears
is a field whose zero no combat routine can have consumed as combat state,
because it was gone before any character acted.

How it runs, in order:

1. `goldbox.dos.new_dos_save` builds a save from a C64 disk into a staged
   game tree -- no template, every `WRITE_UNSOURCED` byte zero;
2. DOSBox-X boots, the game loads the slot, and the party walks until a
   wandering encounter stops it at `COMBAT WAIT FLEE ADVANCE`;
3. Alt+Pause, a megabyte dumped, and each `CHRDAT<slot><n>.SAV` matched
   against it to find that character's live record -- the same recipe
   `docs/142-dosbox-x-debugger.md` used for the ECL variable array, and for
   the same reason: there is no symbol table;
4. the watched bytes are read live, `BPM`s are armed on them, and the
   spurious first hit each nonzero one owes is absorbed and counted;
5. `c` starts the fight, and the fight is driven with `q` while every hit is
   logged with the bar that was on screen when it fired and the `CS:IP` that
   wrote it.

Ground truth for "the party fought" is still the save file and never the
screen: experience rising in `CHRDAT<slot><n>.SAV`, as
`docs/149-driving-a-dos-fight.md` sets out.

Output -- a JSON report, the memory image and the PNGs -- goes under
`work/issue69/`, never into the repository.

    tools/dosfightwatch.py watch --c64 PORSAVE13.D64 --slot A
    tools/dosfightwatch.py locate --slot A     # stop after step 3
    tools/dosfightwatch.py truth --c64 PORSAVE13.D64 --slot A --engine-slot B

`truth` is the other half of the comparison: the same party saved back by the
game's own `ENCAMP > SAVE` before it is walked anywhere, then reloaded and
taken to an encounter menu, so what the engine holds at the moment a fight
starts can be set beside what a conversion holds there.

**The party has to be somewhere wandering encounters happen.**  Every save
disk on the player's shelf but two puts the party in New Phlan, area 0, which
has none; `PORSAVE13.D64` and `PORSAVE14.D64` are in the Slums, area 20, and
are the ones to convert for this.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos  # noqa: E402
from goldbox import dos_layout as dl  # noqa: E402
from goldbox.d64 import load_payload  # noqa: E402
from goldbox.games import POOL_OF_RADIANCE  # noqa: E402
from tools import dosbox, dosboxx  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent

#: Where a run's report, memory image and frames land.  Under `work/`, which
#: is gitignored: a frame of the game is the game's own art.
OUT = REPO / "work" / "issue69"

#: `CHRDAT` offsets read directly, as `tools/dosfightrun.py` does.
XP = 0x0AC
HP_CURRENT = 0x11B

#: Every bar that means a fight has started, and at which the walk must stop.
#:
#: **`encounter` is not the only one.**  A run that stopped only at
#: `COMBAT WAIT FLEE ADVANCE` walked into a fight, was handed `MOVE VIEW AIM
#: USE ... QUICK DONE`, pressed `q` at it because `PoolOfRadiance.COMBAT_KEYS`
#: has a key for it, and fought the whole encounter with no watchpoint armed --
#: counting it as one of ten "prompts".  The party then reached the *next*
#: encounter with `hands_used` already 2 rather than the conversion's zero,
#: which is precisely the state `#69 (No WRITE_UNSOURCED zero has been tested
#: during combat)` exists to observe.
#:
#: `claim_treasure` is deliberately absent: its digest is a bare `YES NO`, and
#: the world map asks one of those too -- the boat back to Phlan, the inn --
#: so it is answered `n` and walked past.
FIGHT_BARS = frozenset({"encounter", "message", "command",
                        "continue_battle", "treasure"})


def unsourced_fields() -> list[tuple[str, int, int]]:
    """`(name, offset, size)` for every field `goldbox.dos.write` zeroes.

    Read out of the layout rather than written down here, so a field added to
    or removed from `WRITE_UNSOURCED` changes what this watches without
    anybody remembering to edit a second list.
    """
    return [(n, dl.FIELDS_BY_NAME[n].offset, dl.FIELDS_BY_NAME[n].size)
            for n, _ in dos.WRITE_UNSOURCED]


def find_c64_save(name: str | None) -> pathlib.Path:
    """A C64 save disk: what `--c64` named, or the newest `PORSAVE*.D64`."""
    if name:
        return pathlib.Path(name).expanduser()
    from automap.paths import find_disks
    disks = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")
    found = sorted(disks.glob("PORSAVE*.D64"))
    if not found:
        raise SystemExit("No C64 save disk found; name one with --c64")
    return found[-1]


def records(save_dir: pathlib.Path, letter: str) -> dict[int, bytes]:
    """Every `CHRDAT<letter><n>.SAV` in the staged save directory."""
    out = {}
    for n in range(1, 7):
        p = save_dir / f"CHRDAT{letter.upper()}{n}.SAV"
        if p.is_file():
            out[n] = p.read_bytes()
    return out


def locate_records(image: bytes, recs: dict[int, bytes]) -> dict[int, dict]:
    """Where each character's live record sits in a memory image.

    One `locate` per record.  A record found by fewer than `MIN_VOTES` windows
    is reported with its vote count rather than believed: the caller decides.
    """
    found: dict[int, dict] = {}
    for n, data in recs.items():
        hit = dosboxx.locate(image, data)
        if hit is None:
            found[n] = {"base": None, "votes": 0, "matching": 0}
            continue
        base, votes, same = hit
        seg, ofs = dosboxx.seg_off(base)
        found[n] = {"base": base, "votes": votes, "matching": same,
                    "of": len(data), "at": f"{seg:04X}:{ofs:04X}"}
    return found


def field_values(image: bytes, base: int) -> dict[str, str]:
    """The watched fields, read out of a memory image at a record's base."""
    return {name: image[base + off:base + off + size].hex()
            for name, off, size in unsourced_fields()}


class Watcher:
    """Watchpoints on one or more record bytes, and the hits they produced.

    Kept as a class because the fight loop and the arming step both need the
    address-to-name map, and a hit read out of the log carries nothing but an
    address.
    """

    def __init__(self, s: dosboxx.XSession):
        self.s = s
        self.names: dict[int, str] = {}
        self.hits: list[dict] = []
        self.cursor = 0

    def arm(self, addr: int, label: str) -> None:
        seg, ofs = dosboxx.seg_off(addr)
        self.s.dbg(f"BPM {seg:X}:{ofs:X}", expect=r"Set memory breakpoint",
                   timeout=8.0)
        self.names[addr] = label

    def drain(self) -> list[dosboxx.Break]:
        """Every memory-breakpoint line the log has grown since last asked."""
        text = self.s.log_text()
        fresh = dosboxx.parse_breaks(text[self.cursor:])
        self.cursor = len(text)
        return fresh

    def note(self, hit: dosboxx.Break, **extra) -> dict:
        row = {"field": self.names.get(hit.addr, "?"),
               "at": f"{hit.seg:04X}:{hit.ofs:04X}",
               "addr": hit.addr,
               "old": hit.old, "new": hit.new}
        row.update(extra)
        self.hits.append(row)
        return row


def absorb_spurious(w: Watcher, expected: int, timeout: float = 40.0) -> list:
    """Let every watchpoint on a nonzero byte fire its one false hit.

    **A fresh `BPM` remembers the value 00**, so a watchpoint armed on a byte
    that is not zero fires the instant the emulator runs, reporting
    `00 -> <what was already there>`.  Arming them all and then running is
    cheaper than absorbing one at a time, and the count is predictable: it is
    exactly the number of watched bytes that read nonzero when armed.
    """
    got: list[dosboxx.Break] = []
    deadline = time.time() + timeout
    while len(got) < expected and time.time() < deadline:
        w.s.run()
        time.sleep(0.4)
        got += w.drain()
    w.drain()
    return got


def fight_watching(por: dosbox.PoolOfRadiance, w: Watcher, *,
                   budget: float = 900.0, settled: float = 4.0,
                   dwell: float = 1.2, patience: float = 90.0,
                   max_hits: int = 4000) -> dict:
    """`PoolOfRadiance.fight`, with the emulator's halts handled.

    A watchpoint firing stops the emulator, so the screen freezes and the
    driver's own waits would run to their timeouts against a picture that
    cannot change.  The log says it happened immediately -- `DEBUG_ShowMsg`
    writes unbuffered -- so every turn of this loop reads the log first and
    resumes before it looks at the screen at all.

    The bar recorded against a hit is the frame that was on screen when the
    emulator stopped, which is what makes a hit's *phase* readable: a write
    that lands while `COMBAT WAIT FLEE ADVANCE` is up happened before any
    character acted.
    """
    s = por.s
    if por.world_glyphs is None:
        raise RuntimeError("fight_watching needs the world bar load_game recorded")
    started = time.time()
    deadline = started + budget
    world_since: float | None = None
    unknown_since: float | None = None
    resumes = 0
    last_bar = "?"
    while time.time() < deadline:
        fresh = w.drain()
        if fresh:
            bar = por.bar_kind() or "?"
            last_bar = bar
            for hit in fresh:
                w.note(hit, bar=bar, t=round(time.time() - started, 2),
                       cs_ip=None)
            if len(w.hits) <= 40:
                # `EV` is the only way a register reaches the log, and it
                # costs a round trip -- so the writing address is recorded for
                # the first hits, which are the ones that say what the engine
                # did with our zero, and not for a thousandth repeat.
                try:
                    regs = s.regs("CS", "IP")
                    w.hits[-1]["cs_ip"] = f"{regs.get('CS', 0):04X}:{regs.get('IP', 0):04X}"
                except Exception:
                    pass
            resumes += 1
            s.run()
            if len(w.hits) >= max_hits:
                return {"result": False, "why": "hit budget", "resumes": resumes,
                        "seconds": round(time.time() - started, 1)}
            continue

        screen = s.capture()
        bar = screen.glyphs(dosbox.BAR)
        if bar == por.world_glyphs:
            world_since = world_since or time.time()
            if time.time() - world_since >= settled:
                return {"result": True, "resumes": resumes, "last_bar": last_bar,
                        "seconds": round(time.time() - started, 1)}
            time.sleep(0.25)
            continue
        world_since = None
        key = por.COMBAT_KEYS.get(por.bar_kind(screen) or "")
        if key is None:
            unknown_since = unknown_since or time.time()
            if time.time() - unknown_since >= patience:
                s.shot(f"watch_unknown_bar_{bar}", allow_blank=True)
                return {"result": False, "why": f"unknown bar {bar}",
                        "resumes": resumes,
                        "seconds": round(time.time() - started, 1)}
            time.sleep(0.25)
            continue
        unknown_since = None
        s.key(key)
        s.wait_while_glyphs(dosbox.BAR, bar, timeout=dwell)
    s.shot("watch_stuck", allow_blank=True)
    return {"result": False, "why": "budget", "resumes": resumes,
            "seconds": round(time.time() - started, 1)}


def walk_to_encounter(por: dosbox.PoolOfRadiance, steps: int) -> dict:
    """Walk until the encounter menu comes up, dismissing whatever else does.

    A blocked step returns to the same bar with the same status line; the
    party turns rather than counting it, so the walk goes somewhere it can
    meet something.

    **Not every step that fails to come back on the world bar is a fight.**
    A `YES NO` prompt -- the boat back to Phlan is the one the Slums offers --
    stops the world bar exactly as an encounter does, and answering it `n` and
    walking on is what this wants.  The first run of this tool armed its
    watchpoints at one of those, pressed `n`, watched the world bar come back
    in 4.7 seconds and reported a fight that never happened.
    """
    walked = blocked = prompts = 0
    i = -1
    tries = 0
    while walked + blocked < steps and tries < steps * 4:
        i += 1
        tries += 1
        before = por.status()
        if por.step():
            if por.status() == before:
                blocked += 1
                por.turn_right()
                continue
            walked += 1
            continue
        kind = por.bar_kind()
        if kind in FIGHT_BARS:
            return {"met": True, "at_step": i + 1, "bar": kind, "walked": walked,
                    "blocked": blocked, "prompts": prompts}
        key = por.COMBAT_KEYS.get(kind or "")
        if key is None:
            return {"met": False, "why": f"a bar nobody has labelled ({kind})",
                    "at_step": i + 1, "walked": walked, "blocked": blocked,
                    "prompts": prompts}
        # Something answerable that is not the encounter menu: answer it and
        # keep walking.  `n` is the decline on every `YES NO` the map offers.
        # **Turn afterwards.**  Declining the inn's "IT WILL COST YOU 1
        # PLATINUM PIECE TO REST HERE" leaves the party facing the same door,
        # so the next step walks into it again -- 67 prompts and 10 squares
        # walked, in the run that found this out.
        prompts += 1
        por.s.key(key)
        por.s.wait_until_ink(dosbox.BAR, por.world_bar or "", timeout=20.0)
        por.turn_right()
    return {"met": False, "why": "no encounter in the steps asked",
            "walked": walked, "blocked": blocked, "prompts": prompts}


def run(*, c64: pathlib.Path | None, slot: str, steps: int, out: pathlib.Path,
        stop_after_locate: bool, watch_chars: tuple[int, ...],
        only: tuple[str, ...] = (), resave: str = "E") -> dict:
    """The whole measurement.  Everything it learned comes back in the dict."""
    out.mkdir(parents=True, exist_ok=True)

    def checkpoint() -> None:
        """Write what is known so far.  A run that dies late still reports."""
        (out / "report.json").write_text(json.dumps(report, indent=1,
                                                   default=str))

    game = dosbox.find_game()
    report: dict = {"slot": slot, "steps_asked": steps,
                    "fields": [n for n, _, _ in unsourced_fields()]}

    disk = find_c64_save(c64 if c64 is None else str(c64))
    report["c64"] = str(disk)
    save0 = load_payload(str(disk), POOL_OF_RADIANCE.save_file)
    try:
        save1 = load_payload(str(disk), POOL_OF_RADIANCE.roster_file)
    except Exception:
        save1 = None

    with dosboxx.claim("issue69 fight watch") as claimed:
        s = dosboxx.XSession(claimed, game)
        try:
            s.stage(fresh=True)
            written = dos.new_dos_save(save0, save1, s.save_dir, slot,
                                       s.game_dir)
            report["accounted"] = f"{len(written.sources)}/{written.total}"
            report["warnings"] = written.warnings
            built = records(s.save_dir, slot)
            report["built_records"] = {
                n: {"len": len(d),
                    "unsourced": field_values(d, 0)} for n, d in built.items()}
            for n, d in built.items():
                (out / f"BUILT-CHRDAT{slot.upper()}{n}.SAV").write_bytes(d)

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(slot)
            shutil.copy(s.shot("loaded"), out / "loaded.png")
            report["status_at_load"] = por.status()
            checkpoint()

            report["walk"] = walk_to_encounter(por, steps)
            checkpoint()
            if not report["walk"]["met"]:
                return report
            shutil.copy(s.shot("encounter", allow_blank=True),
                        out / "encounter.png")

            report["attached"] = s.attach()
            if not report["attached"]:
                return report
            image = s.read(0, 0x100000)
            (out / "memory-at-encounter.bin").write_bytes(image)
            report["dumped"] = len(image)
            where = locate_records(image, built)
            report["records"] = {n: dict(v) for n, v in where.items()}
            report["live_at_encounter"] = {
                n: field_values(image, v["base"])
                for n, v in where.items() if v["base"]}
            checkpoint()
            if stop_after_locate:
                return report

            # -- arm ------------------------------------------------------
            w = Watcher(s)
            nonzero = 0
            for n in watch_chars:
                base = where.get(n, {}).get("base")
                if base is None:
                    continue
                for name, off, _size in unsourced_fields():
                    if only and name not in only:
                        continue
                    addr = base + off
                    w.arm(addr, f"c{n}.{name}")
                    if image[addr] != 0:
                        nonzero += 1
            report["watchpoints"] = len(w.names)
            report["expected_spurious"] = nonzero
            w.drain()
            got = absorb_spurious(w, nonzero)
            report["absorbed"] = [
                {"field": w.names.get(h.addr, "?"), "old": h.old, "new": h.new}
                for h in got]
            report["breakpoint_list"] = s.breakpoints()
            checkpoint()

            # -- fight ----------------------------------------------------
            s.run()
            report["fight"] = fight_watching(por, w)
            report["hits"] = w.hits
            report["hit_counts"] = _counts(w.hits)
            checkpoint()

            # The emulator may be halted at a last hit; let it run so the
            # game can be saved through its own menus.
            for _ in range(6):
                if not s.halted(timeout=2.0):
                    break
                w.drain()
                s.run()

            # What the fields hold at the end of the fight, read out of memory
            # rather than out of a file.  This is what separates "the engine
            # wrote it during the fight" from "the engine wrote it while
            # saving": a byte that is still our zero here and is not zero in
            # the resave was written by `ENCAMP > SAVE` and by nothing else.
            if s.attach():
                after_image = s.read(0, 0x100000)
                (out / "memory-after-fight.bin").write_bytes(after_image)
                where2 = locate_records(after_image, built)
                report["records_after_fight"] = {n: dict(v)
                                                 for n, v in where2.items()}
                report["live_after_fight"] = {
                    n: field_values(after_image, v["base"])
                    for n, v in where2.items() if v["base"]}
                checkpoint()
                s.clear_breakpoints()
                s.run()
            else:
                report["live_after_fight"] = None

            try:
                engine = por.save_game(resave)
                (out / f"RESAVE-SAVGAM{resave.upper()}.DAT").write_bytes(engine)
                report["resaved"] = True
            except Exception as e:
                # The fight's hits are the finding; the resave is the check on
                # top of it.  Losing the whole run because ENCAMP did not open
                # is how the first attempt reported nothing at all.
                report["resaved"] = False
                report["resave_error"] = f"{type(e).__name__}: {e}"
                checkpoint()
            # **The records to read back are the ones `save_game` just wrote,
            # and they are not in `slot`.**  This read `records(s.save_dir,
            # slot)` -- the converted slot, which the game never writes -- so
            # it compared the conversion against itself: `experience_rose` was
            # `0` for every character of every run and `fought` was always
            # False.  The first fight this tool actually drove reported
            # `fought: false` while the engine's own slot E held 16 more
            # experience points for all six.
            after = records(s.save_dir, resave)
            report["after_records"] = {
                n: {"experience": int.from_bytes(d[XP:XP + 3], "little"),
                    "hp_current": d[HP_CURRENT],
                    "unsourced": field_values(d, 0)}
                for n, d in after.items()}
            report["experience_rose"] = {
                n: int.from_bytes(after[n][XP:XP + 3], "little")
                - int.from_bytes(built[n][XP:XP + 3], "little")
                for n in after if n in built}
            report["fought"] = any(v > 0 for v in
                                   report["experience_rose"].values())
            for n, d in after.items():
                (out / f"AFTER-CHRDAT{resave.upper()}{n}.SAV").write_bytes(d)
        finally:
            checkpoint()
            s.close()
    return report


def truth(*, c64: pathlib.Path | None, slot: str, engine_slot: str, steps: int,
          out: pathlib.Path) -> dict:
    """What the engine's *own* party holds at an encounter menu (#69).

    The comparison `#69 (No WRITE_UNSOURCED zero has been tested during
    combat)` asks for and that no run has made: not the engine's resave after
    a fight, but the engine's live records **at the same point in the same
    place** as a converted party's.

    The trick is that the party is the same one either way.  A converted save
    is written to `slot`, loaded, and immediately saved back to `engine_slot`
    through `ENCAMP > SAVE`, which makes the engine author all seven files for
    a party it did not convert.  The emulator is restarted so the load is a
    real load rather than a party still in memory, `engine_slot` is loaded,
    and the walk to an encounter and the megabyte dump are the ones `locate`
    takes.  Every field that then differs from the converted run's is a field
    where our zero is not what the engine would have had when the fight began.
    """
    out.mkdir(parents=True, exist_ok=True)
    game = dosbox.find_game()
    report: dict = {"mode": "truth", "slot": slot, "engine_slot": engine_slot,
                    "steps_asked": steps,
                    "fields": [n for n, _, _ in unsourced_fields()]}

    def checkpoint() -> None:
        (out / "report.json").write_text(json.dumps(report, indent=1,
                                                   default=str))

    disk = find_c64_save(c64 if c64 is None else str(c64))
    report["c64"] = str(disk)
    save0 = load_payload(str(disk), POOL_OF_RADIANCE.save_file)
    try:
        save1 = load_payload(str(disk), POOL_OF_RADIANCE.roster_file)
    except Exception:
        save1 = None

    with dosboxx.claim("issue69 engine truth") as claimed:
        s = dosboxx.XSession(claimed, game)
        try:
            s.stage(fresh=True)
            written = dos.new_dos_save(save0, save1, s.save_dir, slot,
                                       s.game_dir)
            report["accounted"] = f"{len(written.sources)}/{written.total}"
            built = records(s.save_dir, slot)
            report["built_records"] = {
                n: {"unsourced": field_values(d, 0)} for n, d in built.items()}

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(slot)
            report["status_at_load"] = por.status()
            checkpoint()

            # The engine authors the party.  Nothing has been fought and
            # nothing walked: this is the same party, one `ENCAMP > SAVE`
            # later, with every `WRITE_UNSOURCED` byte the engine's own.
            por.save_game(engine_slot)
            engine = records(s.save_dir, engine_slot)
            report["engine_records"] = {
                n: {"unsourced": field_values(d, 0)} for n, d in engine.items()}
            for n, d in engine.items():
                (out / f"ENGINE-CHRDAT{engine_slot.upper()}{n}.SAV").write_bytes(d)
            checkpoint()

            # A restart, so the party is loaded off disk rather than still in
            # the heap the conversion was read into.
            s.restart()
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(engine_slot)
            shutil.copy(s.shot("engine-loaded"), out / "engine-loaded.png")
            checkpoint()

            report["walk"] = walk_to_encounter(por, steps)
            checkpoint()
            if not report["walk"]["met"]:
                return report
            shutil.copy(s.shot("engine-encounter", allow_blank=True),
                        out / "engine-encounter.png")

            report["attached"] = s.attach()
            if not report["attached"]:
                return report
            image = s.read(0, 0x100000)
            (out / "engine-memory-at-encounter.bin").write_bytes(image)
            where = locate_records(image, engine)
            report["records"] = {n: dict(v) for n, v in where.items()}
            report["live_at_encounter"] = {
                n: field_values(image, v["base"])
                for n, v in where.items() if v["base"]}
            checkpoint()
            s.clear_breakpoints()
            s.run()
        finally:
            checkpoint()
            s.close()
    return report


def _counts(hits: list[dict]) -> dict:
    """How many hits each watched field took, and on which bars."""
    out: dict[str, dict] = {}
    for h in hits:
        row = out.setdefault(h["field"], {"n": 0, "bars": {}, "first": None})
        row["n"] += 1
        row["bars"][h.get("bar", "?")] = row["bars"].get(h.get("bar", "?"), 0) + 1
        if row["first"] is None:
            row["first"] = {"bar": h.get("bar"), "t": h.get("t"),
                            "old": h["old"], "new": h["new"],
                            "cs_ip": h.get("cs_ip")}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("locate", "watch", "truth"))
    ap.add_argument("--c64", default=None, help="the C64 save disk to convert")
    ap.add_argument("--slot", default="A", help="the DOS slot to write")
    ap.add_argument("--steps", type=int, default=40,
                    help="how many steps to try before giving up on a fight")
    ap.add_argument("--chars", default="1",
                    help="which party slots to watch, comma separated")
    ap.add_argument("--only", default="",
                    help="watch only these fields, comma separated")
    ap.add_argument("--out", default=None, help="where the run's files go")
    ap.add_argument("--engine-slot", default="B",
                    help="the slot `truth` has the engine write for itself")
    args = ap.parse_args(argv)

    chars = tuple(int(x) for x in args.chars.split(",") if x.strip())
    only = tuple(x for x in args.only.split(",") if x.strip())
    out = pathlib.Path(args.out or OUT)
    if args.command == "truth":
        report = truth(c64=args.c64, slot=args.slot,
                       engine_slot=args.engine_slot, steps=args.steps,
                       out=out)
    else:
        report = run(c64=args.c64, slot=args.slot, steps=args.steps, out=out,
                     stop_after_locate=args.command == "locate",
                     watch_chars=chars, only=only)
    text = json.dumps(report, indent=1, default=str)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
