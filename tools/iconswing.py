#!/usr/bin/env python3
"""Where a combat icon's **second** nine screen codes go, and who draws them.

An icon is eighteen `CHARPIC00` screen codes -- two 3x3 poses, which the
game's own editor labels READY and ACTION -- and
`docs/174-combat-figures-in-the-running-game.md` proved the engine draws the
first nine from the save's own bytes, 405 readings, 6 of 6 figures.  The
second nine had never been seen, because the driver passed every turn and
because nobody had looked anywhere but the combat floor.  This looks in three
places at once; `docs/186-ready-and-action.md` is what it found.

* **A fight driven with `Session.melee_turn`**, so party members strike rather
  than passing, with a glyph reading on every command bar through
  `tools/savecheck.py`'s own `icon_evidence`.
* **Checkpoints counting the engine's own reads**, at two levels.  The save's
  nine codes a pose at `$4BE0 + slot * 36` say whether the bytes are read at
  all; the 72 expanded bitmap bytes a pose at `$9BE8 + slot * 162` say when a
  pose is **fetched to be drawn**, which is the thing a once-a-turn look at
  the screen cannot catch -- a frame shown for a few tenths of a second is
  gone by the next command bar and a checkpoint is not.
* **`--camp`**, which takes the game to ENCAMP > ALTER > ICON and scores every
  3x3 block of nine consecutive codes on that screen against both poses of
  every occupied save slot.  That is where a player sees the ACTION pose.

Every reading records `$6E11`, the mode byte, so the screen the game was
drawing when it was taken is in the log rather than in somebody's memory:
2 is COMBAT and 9 is CAMP (`#265 (The combat-icon glyph check reads VIC
registers instead of the character set, and half of it passes anyway)`).

    tools/iconpoke.py --disk work/issue184/SIX.D64
    POR_HEADLESS=1 tools/iconswing.py --disk work/issue184/SIX.D64
    POR_HEADLESS=1 tools/iconswing.py --disk work/issue184/SIX.D64 --camp

Nothing is written to the player's disks: the save disk named here is copied
into the slot's own directory before the emulator sees it.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import struct
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from tools import savecheck as V  # noqa: E402
from tools import session as S  # noqa: E402

#: `MON_CMD_CHECKPOINT_GET`.  `automap/vice.py` sets, deletes and lists
#: checkpoints but never asks one for its hit count, which is the whole of
#: what this tool wants from them.
CMD_CHECKPOINT_GET = 0x11

#: The shared icon table, from `goldbox/icons.py`: eight entries of 36 bytes,
#: eighteen screen codes then eighteen colours.
ICON_BASE = 0x4BE0
ICON_STRIDE = 36
POSE_CODES = 9

#: `$6E11`, which overlay is running -- `docs/41-memory-regions.md`.
MODE_COMBAT = 2

#: Where `COM.PREP $122C` expands every icon.  It walks `$4BE0` with a pointer
#: in `$07/$08`, reads **eighteen** screen codes, turns each into eight bytes
#: out of `CHARPIC00` staged at `$8C00` (`$1284`: `code * 8 + $8C00`), writes
#: them through a pointer in `$9E/$9F` that starts at `$9BE8`, and then copies
#: the eighteen colour bytes after them -- 162 bytes a slot, eight slots.
#: Reading it says whether the *second* nine codes of an icon reach the engine
#: at all, which no reading of the screen can.
EXPANDED = 0x9BE8
EXPANDED_GLYPHS = 18
EXPANDED_STRIDE = EXPANDED_GLYPHS * 8 + EXPANDED_GLYPHS      # 162
EXPANDED_SLOTS = 8


def expanded_reading(sess, slots: list[dict], charset: bytes) -> dict:
    """`$9BE8`, against the eighteen codes each save slot holds.

    Per slot: how many of the eighteen expanded glyphs are
    `CHARPIC00[code * 8]` for that slot's own code, split into the first nine
    and the second nine, and whether the eighteen colour bytes that follow
    them are the icon's own.
    """
    with sess.mon(10) as m:
        blob = m.read(EXPANDED, EXPANDED_STRIDE * EXPANDED_SLOTS)
    out = {"base": EXPANDED, "slots": []}
    for entry in slots:
        n = entry["slot"]
        base = n * EXPANDED_STRIDE
        shape = bytes.fromhex(entry["shape"])
        hues = bytes.fromhex(entry["colours"])
        drawn = [bytes(blob[base + i * 8: base + i * 8 + 8])
                 for i in range(EXPANDED_GLYPHS)]
        want = [V.glyph_of(charset, c) for c in shape]
        same = [a == b for a, b in zip(drawn, want)]
        out["slots"].append({
            "slot": n, "occupied": entry["occupied"],
            "pose0": sum(same[:9]), "pose1": sum(same[9:]),
            "colours": bytes(blob[base + 144: base + 162]) == hues,
            "first": drawn[0].hex(), "tenth": drawn[9].hex(),
        })
    return out


def screen_codes(sess) -> tuple[list[bytes], bytes] | None:
    """The screen matrix as 25 rows of 40 raw codes, and colour RAM with it.

    `Screen.row` gives text, and the icon editor draws no text: its cells are
    `CHARPIC00` glyphs whose codes mean nothing as letters.  So the codes are
    taken raw and compared as numbers.
    """
    with sess.mon(5) as m:
        from automap.vice import screen_address
        base = screen_address(m)
        raw = m.read(base, 1000)
        hues = bytes(c & 0x0F for c in m.read(0xD800, 1000))
    return [bytes(raw[r * 40:(r + 1) * 40]) for r in range(25)], hues


def blocks_on(rows: list[bytes]) -> list[tuple[int, int, bytes]]:
    """Every 3x3 block of nine **consecutive** screen codes on the screen.

    The icon editor renumbers exactly the way a fight does: it builds its own
    character set and hands out sequential codes, so the icon's own codes are
    nowhere on the screen and searching for them finds nothing, which is what
    the first run of this reported.  A run of nine consecutive codes laid out
    three by three is what an icon looks like once renumbered.
    """
    out = []
    for r in range(23):
        for c in range(38):
            first = rows[r][c]
            if all(rows[r + dr][c + dc] == first + dr * 3 + dc
                   for dr in range(3) for dc in range(3)):
                out.append((r, c, bytes(rows[r][c:c + 3])))
    return out


def editor_reading(sess, rows: list[bytes], hues: bytes,
                   slots: list[dict], charset: bytes) -> list[dict]:
    """Score every 3x3 block on the editor's screen against the save's icons.

    The same comparison a fight gets, on a different screen: the nine glyph
    bitmaps the block is drawn from, against `CHARPIC00[code * 8]` for the
    nine codes each save slot holds, both poses, plain and mirrored.  The
    character set is read through the `ram` bank for the same reason
    `tools/savecheck.py` reads the combat one that way -- it lands under the
    VIC's registers and the default bank answers those instead
    (`#265 (The combat-icon glyph check reads VIC registers instead of the
    character set, and half of it passes anyway)`).
    """
    with sess.mon(10) as m:
        d018 = m.read(0xD018, 1)[0]
        dd00 = m.read(0xDD00, 1)[0]
        base = ((~dd00 & 3) * 0x4000) + ((d018 >> 1) & 7) * 0x800
        banks = V.bank_ids(m)
        if "ram" not in banks:
            raise SystemExit("this VICE offers no bank called ram")
        glyphs = m.read(base, 0x800, bank=banks["ram"])
    out = []
    for r, c, _ in blocks_on(rows):
        code = rows[r][c]
        drawn = [bytes(glyphs[(code + n) * 8:(code + n) * 8 + 8])
                 for n in range(9)]
        colours = bytes(hues[(r + dr) * 40 + c + dc]
                        for dr in range(3) for dc in range(3))
        scored = []
        for entry in slots:
            if not entry["occupied"]:
                continue
            shape = bytes.fromhex(entry["shape"])
            hue = bytes.fromhex(entry["colours"])
            for pose in (0, 1):
                want = [V.glyph_of(charset, x)
                        for x in shape[pose * 9:pose * 9 + 9]]
                for kind, cells in (("plain", drawn),
                                    ("mirrored", V.mirrored(drawn, colours))):
                    same = sum(1 for a, b in zip(cells, want) if a == b)
                    scored.append({"slot": entry["slot"], "pose": pose,
                                   "kind": kind, "glyphs": same,
                                   "colours": hue[pose * 9:pose * 9 + 9]
                                   == colours})
        best = max((x["glyphs"] for x in scored), default=0)
        out.append({
            "row": r, "col": c, "code": code, "charset": base, "best": best,
            "exact": [(x["slot"], x["pose"], x["kind"]) for x in scored
                      if x["glyphs"] == 9],
            "colour_match": [(x["slot"], x["pose"]) for x in scored
                             if x["colours"] and x["kind"] == "plain"],
        })
    return out


def camp(sess, log, args, slots: list[dict], charset: bytes) -> int:
    """Take the game to its own icon editor and read what it draws.

    ENCAMP > ALTER > ICON is where a player looks at a combat icon outside a
    fight, and it is the one screen that could show both of an icon's poses.
    `$6E11` is logged with the reading, so which overlay drew it is in the
    log: 9 is CAMP, and the editor is `SPELLN64` loaded under it.
    """
    if not sess.select_party(args.who):
        log.say(f"could not highlight party member {args.who}")
    for label in ("ENCAMP", "ALTER", "ICON"):
        s = sess.screen()
        log.say(f"  bar before {label}: |{'' if s is None else s.row(24)}|")
        if not sess.select_bar(label):
            log.say(f"** {label} is not on the bar")
            log.emit("camp_stuck", label=label,
                     row=None if s is None else s.row(24))
            return 1
        sess.settle(2)
    # The editor is `SPELLN64` on POOL3, so pressing ICON asks for a disk and
    # then loads: a screen read taken on the keystroke photographs the camp
    # picture that was already there, which is what the first run of this
    # returned.  `PARTS` is the editor's own menu -- `ICON: PARTS COLOR SIZE
    # EXIT` -- so waiting for that word waits for the thing being measured.
    if not sess.wait_text("PARTS", timeout=args.editor):
        s = sess.screen()
        log.say("** the editor's PARTS menu never appeared; row 24 is "
                f"|{'' if s is None else s.row(24)}|")
    sess.settle(3)
    sess.kbd.screenshot(str(log.dir / f"{args.tag}-icon-editor.png"))
    read = screen_codes(sess)
    if read is None:
        log.say("** nothing readable on the screen")
        return 1
    rows, hues = read
    mode = sess.mode()
    log.say(f"the icon editor is drawn, mode byte {mode}")
    found = editor_reading(sess, rows, hues, slots, charset)
    log.emit("editor_blocks", mode=mode, blocks=found)
    log.say(f"{len(found)} blocks of nine consecutive codes are on the "
            f"screen; the editor's character set is at ${found[0]['charset']:04X}"
            if found else "no block of nine consecutive codes is on the screen")
    for b in found:
        exact = ", ".join(f"slot {s_} pose {p_} {k_}"
                          for s_, p_, k_ in b["exact"]) or "nothing"
        log.say(f"  at row {b['row']}, column {b['col']}, from code "
                f"${b['code']:02X}: {b['best']} of 9 glyphs match the save's "
                f"best icon; exactly {exact}; colours match "
                f"{b['colour_match'] or 'nothing'}")
    log.emit("editor_screen", mode=mode,
             rows=[r.hex() for r in rows], colours=hues.hex())
    if not found:
        log.say("** no icon block from this save is on the screen; the "
                "editor draws something else, or it draws it from a copy")
    return 0


def checkpoint_hits(mon, number: int) -> int:
    """How many times VICE has seen checkpoint `number` hit.

    The response is `MON_RESPONSE_CHECKPOINT_INFO`: the number, a
    currently-hit flag, start, end, four flag bytes, then the hit count as a
    little-endian long at offset 13.  Read by offset rather than by
    unpacking the whole record, because the trailing memspace byte is absent
    from older builds and a full unpack would raise on them.
    """
    body = mon.command(CMD_CHECKPOINT_GET, struct.pack("<I", number))
    return struct.unpack("<I", body[13:17])[0]


def windows(slots: list[dict], control: int = 0) -> list[dict]:
    """Every range to count the engine's reads of, per occupied slot.

    Two levels, because they answer two different questions.

    * **`icon`** -- the nine screen codes of each pose at `$4BE0`.  These say
      whether the save's own bytes are read at all.  Only the codes are
      watched and not the colours: a colour byte is copied to colour RAM
      whichever pose is drawn, so a read of it says nothing about which nine
      glyphs the engine chose.
    * **`glyphs`** -- the 72 expanded bitmap bytes of each pose at `$9BE8`.
      A read there is the engine **fetching a pose to draw it**, which is the
      thing a once-a-turn look at the screen cannot catch: an attack frame
      shown for a few tenths of a second is gone by the next command bar, and
      a checkpoint is not.

    The pose-0 bitmap block is watched for one slot only, named by `control`.
    Watching all six would stop the machine on every redraw of every figure
    and the fight would not finish; one is enough to prove the instrument
    fires when the engine does draw from the table.
    """
    out = []
    for entry in slots:
        if not entry["occupied"]:
            continue
        n = entry["slot"]
        base = ICON_BASE + n * ICON_STRIDE
        for pose in (0, 1):
            start = base + pose * POSE_CODES
            out.append({"kind": "icon", "slot": n, "pose": pose,
                        "start": start, "end": start + POSE_CODES - 1})
        for pose in (0, 1):
            if pose == 0 and n != control:
                continue
            start = EXPANDED + n * EXPANDED_STRIDE + pose * 72
            out.append({"kind": "glyphs", "slot": n, "pose": pose,
                        "start": start, "end": start + 71})
    return out


def arm(sess, watch: list[dict], log) -> None:
    """Set one load checkpoint per window and remember its number.

    `stop=True` on purpose.  A non-stopping checkpoint makes VICE emit an
    event per hit with nothing throttling it, and a window the engine reads
    every frame would fill the socket faster than this drains it; stopping
    means at most one event is outstanding, and the driver's next screen read
    opens a monitor whose close resumes the machine.  The cost is that the
    emulator loses a fraction of a second per hit, which a fight can afford.
    """
    with sess.mon(10) as m:
        m.checkpoints_clear()
        for w in watch:
            w["cp"] = m.checkpoint_set(w["start"], w["end"], load=True,
                                       stop=True)
            w["hits"] = 0
        m.resume()
    icons = sum(1 for w in watch if w["kind"] == "icon")
    log.say(f"armed {len(watch)} load checkpoints: {icons} on the icon "
            f"table's screen codes and {len(watch) - icons} on the expanded "
            f"bitmaps at ${EXPANDED:04X}")


def poll(sess, watch: list[dict]) -> list[dict]:
    """Read every checkpoint's hit count, and say which ones moved."""
    moved = []
    try:
        with sess.mon(10) as m:
            for w in watch:
                if w.get("cp") is None:
                    continue
                now = checkpoint_hits(m, w["cp"])
                if now != w["hits"]:
                    moved.append({"kind": w["kind"], "slot": w["slot"],
                                  "pose": w["pose"], "was": w["hits"],
                                  "now": now})
                    w["hits"] = now
            m.resume()
    except Exception as exc:                     # a count is not worth the run
        moved.append({"error": repr(exc)})
    return moved


def drop_over(sess, watch: list[dict], log, ceiling: int) -> None:
    """Delete any window the machine has read more than `ceiling` times.

    `tools/absrefsweep.py` puts absolute operands naming `$4C0A`, `$4C10`,
    `$4C11` and `$4C13` in `DUNGEON` -- inside slot 1's nine code bytes -- and
    a hit there is a byte pair in an overlay as easily as it is an
    instruction.  Either way a window read every frame stops the machine
    thousands of times and the run never reaches its end, so a window over
    the ceiling is deleted and said so rather than left to spoil the fight.
    """
    hot = [w for w in watch if w.get("cp") is not None and w["hits"] > ceiling]
    if not hot:
        return
    with sess.mon(10) as m:
        for w in hot:
            m.checkpoint_delete(w["cp"])
            w["cp"] = None
            log.say(f"  dropped the watch on slot {w['slot']}'s "
                    f"{w['kind']} pose {w['pose']}: {w['hits']} reads, "
                    f"too many to keep stopping the machine for")
        m.resume()


def prune(sess, watch: list[dict], log, ceiling: int = 500) -> None:
    """Count what has been read so far, and drop anything already storming."""
    for hit in poll(sess, watch):
        log.say(f"  before any fight, the engine read slot "
                f"{hit.get('slot')}'s {hit.get('kind')} pose-"
                f"{hit.get('pose')} bytes {hit.get('now')} times")
    drop_over(sess, watch, log, ceiling)


def disarm(sess, watch: list[dict]) -> None:
    try:
        with sess.mon(10) as m:
            m.checkpoints_clear()
            m.resume()
    except Exception:
        pass
    for w in watch:
        w["cp"] = None


def tactic_for(sess, log, watch, seen, evidence, expanded, attack: bool):
    """One command bar: read the machine, then take a turn.

    The reading is taken **before** the turn is driven, so what it describes
    is the state the game put up rather than the state this tool caused.
    """
    def tactic(_sess, state):
        turn = len(seen) + 1
        roll = V.roll_call(_sess)
        entry = {"turn": turn, "mode": _sess.mode(), "bar": state.text,
                 "roll": roll, "hits": poll(_sess, watch)}
        for key, call in (("icons", evidence), ("expanded", expanded)):
            if call is None:
                continue
            try:
                entry[key] = call(_sess)
            except Exception as exc:
                entry[key] = {"error": repr(exc)}
        seen.append(entry)
        drop_over(_sess, watch, log, 20000)
        for hit in entry["hits"]:
            if "error" in hit:
                log.say(f"  turn {turn}: checkpoint read failed: {hit['error']}")
            else:
                log.say(f"  turn {turn}: the engine read slot "
                        f"{hit['slot']}'s {hit['kind']} pose-{hit['pose']} "
                        f"bytes {hit['now'] - hit['was']} more times "
                        f"({hit['now']} in all)")
        return _sess.melee_turn(state) if attack else _sess.combat_turn()
    return tactic


def report(log, seen: list[dict], watch: list[dict]) -> None:
    """What the run saw, in the terms the ticket asks its question in."""
    poses = {}
    for entry in seen:
        for fig in entry.get("icons", {}).get("figures", []):
            for slot, pose, kind in fig.get("exact", []):
                poses.setdefault(pose, 0)
                poses[pose] += 1
    log.say("")
    log.say(f"{len(seen)} command bars read, all with the mode byte at "
            f"{sorted({e['mode'] for e in seen})}")
    for pose in sorted(poses):
        log.say(f"  {poses[pose]} figure readings matched an icon's "
                f"pose {pose} exactly")
    log.say("the engine's own reads, by window:")
    for w in watch:
        log.say(f"  slot {w['slot']} {w['kind']} pose {w['pose']} "
                f"(${w['start']:04X}-${w['end']:04X}): {w['hits']} loads"
                + ("" if w.get("cp") is not None else "  [dropped]"))
    for kind in ("icon", "glyphs"):
        one = sum(w["hits"] for w in watch
                  if w["pose"] == 1 and w["kind"] == kind)
        nil = sum(w["hits"] for w in watch
                  if w["pose"] == 0 and w["kind"] == kind)
        log.say(f"  {kind}: {nil} loads from the first pose, {one} from the "
                f"second")


def run(args, log) -> int:
    slot = S.claim_slot(args.slot, f"iconswing/{pathlib.Path(args.disk).name}")
    log.say(f"slot {slot.n} display {slot.display}")
    sess = None
    watch: list[dict] = []
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks))
        shutil.copy(args.disk, pathlib.Path(slot.dir) / "SIDE0.D64")
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("the game did not load the save")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        arrived = V.answer_bars(sess, log, args.answer, seconds=args.arrive)
        log.emit("arrival", outcome=arrived)
        if arrived != "world":
            raise RuntimeError(f"no world bar {args.arrive}s after arrival")
        sess.settle(3)

        slots = V.slot_icons(pathlib.Path(args.disk))
        charset = V.icon_charset(pathlib.Path(args.disks))
        icon = V.icon_bytes(pathlib.Path(args.disks))
        log.emit("save_icons", slots=slots)
        for entry in slots:
            if entry["occupied"]:
                log.say(f"  save slot {entry['slot']}: "
                        f"pose 0 {entry['shape'][:18]} "
                        f"pose 1 {entry['shape'][18:]}")

        if args.camp:
            return camp(sess, log, args, slots, charset)

        # Armed **before** the encounter, so COM.PREP's own copy into the
        # combat character set is counted rather than missed: it runs before
        # the first command bar and is the one place the first nine codes are
        # known to be read.
        watch = windows(slots)
        arm(sess, watch, log)

        steps = 0
        while not sess.in_combat() and steps < args.steps:
            sess.walk_one(args.fight_move)
            sess.handle_prompt()
            steps += 1
            if steps == 3:
                prune(sess, watch, log)
        if not sess.in_combat():
            log.say(f"no encounter in {steps} steps")
            log.emit("no_fight", steps=steps)
            return 1
        sess.settle(2)
        log.say(f"an encounter started after {steps} steps; mode is "
                f"{sess.mode()}")
        sess.kbd.screenshot(str(log.dir / f"{args.tag}-combat.png"))
        first = poll(sess, watch)
        log.emit("prepare_reads", hits=first)
        for hit in first:
            log.say(f"  by the first command bar the engine had read slot "
                    f"{hit.get('slot')}'s {hit.get('kind')} pose-"
                    f"{hit.get('pose')} bytes {hit.get('now')} times")

        seen: list[dict] = []

        def evidence(s):
            return V.icon_evidence(s, icon, slots=slots, charset=charset,
                                   roll=V.roll_call(s))

        def expanded(s):
            return expanded_reading(s, slots, charset)

        tactic = tactic_for(sess, log, watch, seen, evidence, expanded,
                            attack=not args.pass_turns)
        r = sess.fight(budget=args.budget, tactic=tactic)
        log.emit("fight", outcome=r.outcome, turns=r.turns, acted=r.acted,
                 blows=r.blows, lines=r.lines, evidence=r.evidence)
        log.say(f"fight: {r.outcome} turns={r.turns} blows={r.blows}")
        log.say(r.evidence)
        for entry in seen:
            log.emit("turn", **entry)
        report(log, seen, watch)
        sess.kbd.screenshot(str(log.dir / f"{args.tag}-end.png"))
        return 0
    except Exception as exc:
        import traceback
        try:
            if sess is not None:
                sess.kbd.screenshot(str(log.dir / f"{args.tag}-failure.png"))
        except Exception:
            pass
        log.emit("error", error=repr(exc))
        log.say(f"** {exc}")
        log.say(traceback.format_exc())
        return 2
    finally:
        if sess is not None:
            disarm(sess, watch)
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:
                log.emit("cleanup_failed", step=what, error=repr(exc))
                log.say(f"Cleanup failed at {what}: {exc!r}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, help="the save .d64 to boot")
    p.add_argument("--disks", default=str(V.DISKS),
                   help="where the player's game disks are; read only")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--tag", default=None, help="prefix for the screenshots")
    p.add_argument("--out", default=None, help="where the log goes")
    p.add_argument("--fight-move", default="I",
                   help="the key pressed looking for an encounter")
    p.add_argument("--steps", type=int, default=60,
                   help="how many of those before giving up")
    p.add_argument("--budget", type=float, default=900.0,
                   help="seconds the fight is driven for")
    p.add_argument("--answer", default="NO",
                   help="what to answer a yes/no bar on arrival")
    p.add_argument("--arrive", type=float, default=240.0,
                   help="seconds to wait for the world after BEGIN ADVENTURING")
    p.add_argument("--camp", action="store_true",
                   help="read the game's own ENCAMP > ALTER > ICON editor "
                        "instead of driving a fight")
    p.add_argument("--editor", type=float, default=120.0,
                   help="seconds to wait for the icon editor to draw")
    p.add_argument("--who", type=int, default=0,
                   help="which party panel row the editor is opened on")
    p.add_argument("--pass-turns", action="store_true",
                   help="pass every turn instead of attacking, as the "
                        "control run did")
    args = p.parse_args(argv)
    args.tag = args.tag or pathlib.Path(args.disk).stem
    out = pathlib.Path(args.out or ROOT / "work" / "issue184" /
                       f"{args.tag}-swing.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    log = V.Log(out)
    started = time.time()
    try:
        rc = run(args, log)
    finally:
        log.say(f"({time.time() - started:.0f}s)")
        log.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
