"""The Pool of Radiance camp, character-sheet, item-list and rest actions the C64 acceptance driver and the experiments share.

Everything here reads the screen and the machine of a running Pool session:
open a character's item list from camp, toggle READY on an item, read the
live records and effect arrays, and rest for a set time.  `rest` also drives
Curse of the Azure Bonds and Secret of the Silver Blades, whose rest-time bar
and addresses differ.
"""

from __future__ import annotations

import os
import time

from goldbox import c64_port, effects
from tools.c64 import session as S
from tools.c64.runlog import Log

#: The camp's own bar, `ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT` (Pool `CAMP
#: $0899`), matched the same way `tools/c64/acceptance.py`'s `to_camp()` does.
#: `VIEW` alone is on the world bar too, so waiting for this pair is what
#: tells the two apart (#621).
CAMP_BAR = "REST ALTER"

#: The 64-entry active-effect array: ids at `$4900`, owners at `$4940`, and
#: the flag byte `CAMP $131F` reads at `$4B80`.
EFFECTS = (0x4900, 0x300)

def live_record(m, slot: int) -> bytes:
    return m.read(SLOT_BASE + slot * SLOT_STRIDE, SLOT_STRIDE)

def live_effects(m) -> bytes:
    return m.read(*EFFECTS)

def diff_bytes(before: bytes, after: bytes, base: int) -> list[dict]:
    return [{"addr": base + i, "was": a, "now": b}
            for i, (a, b) in enumerate(zip(before, after)) if a != b]

def sheet_rows(sess) -> list[str]:
    s = sess.screen()
    return [] if s is None else [r.rstrip() for r in s.rows()]

#: Which side carries every portrait a Pool of Radiance sheet can ask for --
#: all fourteen heads and twelve bodies `goldbox.portraits.POOL_OF_RADIANCE_
#: MENU` offers -- so answering the sheet's own disk prompt with this side
#: always has the file, whatever the file is (#694).
PORTRAIT_SIDE = 3

def wait_sheet_bar(sess: S.Session, timeout: float) -> bool:
    """Wait for a character sheet's bar, answering its own portrait disk
    prompt with `PORTRAIT_SIDE` rather than the side it names.

    Opening a sheet makes the game fetch the character's portrait, which can
    live on a side other than the one in the drive; the loader's prompt
    (`LIBRARY $4378`) always names the *current area's* side, never the side
    the missing `HEAD`/`BODY` file is actually on. Ordinary `handle_prompt`
    answers with the side named, which is the side already in the drive, so
    the load fails and the prompt comes straight back -- forever (#694). This
    answers that one prompt differently, at most once every 2 s, and leaves
    every other prompt to `handle_prompt`.
    """
    deadline = time.time() + timeout
    swapped = 0.0
    while time.time() < deadline:
        s = sess.screen()
        if s is not None:
            if S.SHEET_BAR in s.row(24) and s.row(1).strip():
                return True
            if time.time() - swapped > 2.0 and S.RE_GAME_SIDE.search(s.text()):
                swapped = time.time()
                sess.attach(os.path.join(sess.here, f"SIDE{PORTRAIT_SIDE}.D64"))
                sess.kbd.key("space")
                continue
            sess.handle_prompt(s)
        time.sleep(0.35)
    return False

def panel_index(sess: S.Session, name: str) -> int | None:
    """Which row of the world panel names this character, 0 first.

    **The panel is in marching order, not save-slot order.** `PORSAVE13`
    keeps MALCYON in slot 0 and lists BRUTUS first, so `select_party(0)` put
    the highlight on BRUTUS and VIEW showed his sheet -- twice, before this
    was read off the screen instead of assumed.
    """
    s = sess.screen()
    if s is None:
        return None
    for i, r in enumerate(sess.party_rows(s)):
        if name in s.row(r)[S.PARTY_COLUMN:]:
            return i
    return None

def open_items(sess: S.Session, log: Log, name: str, label: str,
               tag: str) -> bool:
    """ENCAMP > VIEW > the character called `name` > ITEMS, list left up.

    **From camp, not from the world.** `LIBRARY $4630`, the READY toggle,
    refuses a magical item -- bit 7 of `+15` -- with `NOT HERE` unless
    `$6DE4` is set, and CAMP sets it at `$0818` on entering the camp menu
    and clears it at `$0862` on leaving. Five runs pressed READY on the
    world's VIEW and the message flashed too briefly for a screen read.
    """
    at = panel_index(sess, name)
    if at is None:
        log.say(f"  {name} is not on the party panel")
        log.emit("screen", tag=f"{tag}-panel", rows=sheet_rows(sess))
        return False
    if not sess.select_party(at):
        log.say("  select_party failed")
        return False
    if not sess.select_bar("ENCAMP", timeout=20):
        log.say("  ENCAMP could not be selected")
        return False
    # Wait for the camp bar itself, not a fixed settle: `VIEW` is on the
    # world bar as well as the camp bar, so a short settle can leave the
    # world bar still up and send `select_bar("VIEW")` after the wrong
    # menu. 90 s because a slot with no JiffyDOS can take that long to
    # load CAMP off a stock KERNAL (#621).
    if sess.wait_text(CAMP_BAR, 90)[0] is None:
        log.say("  camp bar never appeared")
        log.emit("screen", tag=f"{tag}-camp-missing", rows=sheet_rows(sess))
        return False
    log.emit("screen", tag=f"{tag}-camp", rows=sheet_rows(sess))
    if not sess.select_bar("VIEW", timeout=20):
        log.say("  VIEW could not be selected in camp")
        return False
    if not wait_sheet_bar(sess, 90):
        log.say("  no character sheet")
        return False
    time.sleep(0.8)
    log.emit("screen", tag=f"{tag}-sheet", rows=sheet_rows(sess))
    if not sess.select_bar("ITEMS", timeout=15):
        log.say("  ITEMS could not be selected")
        sess.leave_sheet()
        return False
    if sess.wait_text(label, 20)[0] is None:
        log.say(f"  {label} never appeared on the item list")
        log.emit("screen", tag=f"{tag}-items-missing", rows=sheet_rows(sess))
        leave_items(sess, log)
        return False
    time.sleep(0.5)
    log.emit("screen", tag=f"{tag}-items", rows=sheet_rows(sess))
    return True

#: The item list: `EQUIPPED ITEM` heading on row 3, items from row 5, the
#: name starting in column 6 after the `YES`/`NO` column.
ITEM_ROWS = range(5, 22)

ITEM_NAME_COLUMN = 6

def item_rows(s) -> list[int]:
    return [r for r in ITEM_ROWS if s.row(r)[ITEM_NAME_COLUMN:].strip()]

def item_highlight(s, rows: list[int]) -> int | None:
    """Which item row is highlighted: the one whose name colour is the odd
    one out. `select_row` wants white, and the list's highlight was not read
    as white at the name column in run 4, so this asks a weaker question."""
    if not rows:
        return None
    colours = [s.colours[r * 40 + ITEM_NAME_COLUMN] for r in rows]
    if len(set(colours)) == 1:
        return None
    common = max(set(colours), key=colours.count)
    odd = [r for r, c in zip(rows, colours) if c != common]
    return odd[0] if len(odd) == 1 else None

def toggle_item(sess: S.Session, log: Log, label: str, tag: str,
                sample=None) -> bool:
    """On the item list, put the highlight on `label` and press Return.

    The list's bar is `READY TRADE DROP EXIT`, and the verb comes **first**:
    with the list up no row is highlighted at all (run 5 read colour RAM `02
    05 05 ...` on every item row), the bar holds the highlight, and Return on
    READY is what puts a cursor on the list. Then the row, then Return, and
    one READY readies an un-readied item and un-readies a readied one.

    An optional diagnostic sampler reads the screen and saves selected
    checkpoints before the fire, at its first changed target row, and when
    the item list returns or the bounded poll ends. It does not judge whether
    the game's item state changed.
    """
    s = sess.screen()
    if s is None or item_highlight(s, item_rows(s)) is None:
        # No cursor on the list yet: READY on the bar puts one there. After a
        # toggle the cursor stays, and pressing READY again would be a Return
        # on whatever row it is on.
        if not sess.select_bar("READY", timeout=10):
            log.say("  READY could not be selected on the items bar")
            return False
        time.sleep(0.8)
    deadline = time.time() + 20
    logged = False
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.3)
            continue
        rows = item_rows(s)
        want = next((r for r in rows if label in s.row(r)), None)
        at = item_highlight(s, rows)
        if not logged:
            log.emit("item_list", rows={r: [s.row(r).rstrip(),
                                           s.colours[r * 40:(r + 1) * 40].hex()]
                                       for r in rows}, highlight=at, want=want)
            logged = True
        if want is None or at is None:
            time.sleep(0.3)
            continue
        if at == want:
            if sample is not None:
                s = sample("before", lambda seen: (
                    seen is not None
                    and label in seen.row(want)
                    and item_highlight(seen, item_rows(seen)) == want))
                if s is None or label not in s.row(want):
                    continue
                if item_highlight(s, item_rows(s)) != want:
                    continue
            was = s.row(want)
            press_select(sess)
            screen_changed = False
            stable_candidate = None
            settled = False
            after_screen = None
            for _ in range(20):
                time.sleep(0.3)
                if sample is None:
                    s2 = sess.screen()
                elif not screen_changed:
                    s2 = sample("change", lambda seen: (
                        seen is not None and seen.row(want) != was))
                else:
                    s2 = sample("stable", lambda seen: (
                        stable_candidate is not None
                        and ready_list_signature(seen, label) == stable_candidate))
                after_screen = s2
                if s2 is not None and s2.row(want) != was:
                    screen_changed = True
                    if sample is None:
                        break
                if sample is not None and screen_changed:
                    signature = ready_list_signature(s2, label)
                    if signature is not None and signature == stable_candidate:
                        settled = True
                        break
                    stable_candidate = signature
            if sample is not None and not settled:
                after_screen = sample("timeout", lambda _: True)
            after_rows = (sheet_rows(sess) if sample is None else
                          [] if after_screen is None else
                          [row.rstrip() for row in after_screen.rows()])
            log.emit("screen", tag=f"{tag}-after", rows=after_rows,
                     screen_changed=screen_changed, flipped=screen_changed)
            return screen_changed
        sess.kbd.key("Down" if at < want else "Up", 0.15, 0.30)
    log.say(f"  could not put the highlight on {label}")
    log.emit("screen", tag=f"{tag}-stuck", rows=sheet_rows(sess),
             screen_changed=False)
    return False

def ready_list_signature(s, label: str):
    """The item rows and their name colours when the named list is up."""
    if s is None or "READY" not in s.row(24) or "EXIT" not in s.row(24):
        return None
    if not any(label in s.row(r) for r in item_rows(s)):
        return None
    return (tuple((s.row(r), s.colours[r * 40 + ITEM_NAME_COLUMN])
                  for r in ITEM_ROWS), s.row(24))

#: What selects a row on a list with a cursor on it. `LIBRARY $2E4E`, the
#: game's key fetcher, reads joystick port 2 (`$DC00`) as well as the KERNAL
#: buffer, and the list cursor wants **fire**: eleven keyboard keys did
#: nothing in `cited/252/probe1/`. `--joy` gives VICE a numpad joystick
#: and KP_0 is its fire button.
SELECT = {"key": "KP_0"}

def press_select(sess: S.Session) -> None:
    key = SELECT["key"]
    if key.startswith("kernal:"):
        sess.press_kernal(int(key[7:], 16))
    else:
        sess.kbd.key(key, 0.2, 0.30)

def leave_items(sess: S.Session, log: Log) -> None:
    """Off the item list and off the sheet, by name each time.

    With a cursor on the list the way out is its own `EXIT` row, below the
    items; with the highlight on the bar it is the bar's EXIT. The list
    re-arms itself: its EXIT returns to the sheet bar and a bare Return
    there drops straight back in (`docs/70-driving-the-game.md`).

    `log` records when the final camp-exit `select_bar("EXIT")` fails.
    """
    for _ in range(12):
        s = sess.screen()
        if s is None:
            break
        rows = [r for r in ITEM_ROWS if s.row(r)[1:].strip()]
        at = item_highlight(s, rows)
        exit_row = next((r for r in rows if s.row(r).strip() == "EXIT"), None)
        if at is None or exit_row is None:
            break
        if at == exit_row:
            press_select(sess)
            time.sleep(1.0)
            break
        sess.kbd.key("Down" if at < exit_row else "Up", 0.15, 0.30)
    sess.select_bar("EXIT", timeout=10)
    time.sleep(0.8)
    sess.leave_sheet()
    time.sleep(0.8)
    if not sess.select_bar("EXIT", timeout=10):      # and out of camp
        # A caller that expects to be back on the world bar after this --
        # `save_game`, for one -- has nothing to go on when this doesn't
        # land; the failure used to vanish here (#621).
        log.say("  leave_items: EXIT out of camp never selected")

#: `SAVEDGAME0` loads at `$4900`; the twelve character slots start at `$4D00`.
SAVE0_LOAD = 0x4900

SLOT_BASE = 0x4D00

SLOT_STRIDE = 0x100

CLOCK = 0x49C6

#: The page an overlay copies the working character into, and the two record
#: bytes the strength handler writes: `0x014` STR and `0x01A` STR %.
STAGING_PAGE = 0x6B00

REC_STR = 0x014

REC_STR_PCT = 0x01A

REC_CHA = 0x019

#: `CAMP`'s rest-time field: minutes, hours, days, counted down five minutes
#: at a time -- `tools/c64/c64restinterrupt.py`.
REST_TIME = 0x2898


#: Curse and Silver Blades load the save payload at `$4B00`, so their four
#: effect arrays and the clock sit `$200` above Pool's, at the same offsets
#: (`docs/226-the-c64-running-effect-crosswalk.md`, `tools/c64/curedrive.py`).
LATER_LOAD = 0x4B00

#: Each later title's `CAMP` rest-time field: minutes, hours, days (zeroed at
#: Curse `CAMP $1D54`, Silver Blades `$1B52`).  `tools/c64/curedrive.py` rested
#: both titles through these bytes and the clock advanced by exactly the time
#: written (`docs/234-a-paladins-cure-disease-across-dos-and-the-c64.md`).
LATER_REST_TIME = {
    c64_port.CURSE_OF_THE_AZURE_BONDS.key: 0x2C1B,
    c64_port.SECRET_OF_THE_SILVER_BLADES.key: 0x2A8E,
}

#: The word only the later titles' rest-time bar carries: `REST ADD SUBTRACT
#: EXIT`, under `REST TIME : 0 DAYS 0 HRS 0 MINS`, where Pool's says `INCREASE`.
LATER_REST_BAR = "SUBTRACT"

#: The area's rest-interruption interval and chance, read by Curse `CAMP
#: $1F76` and Silver Blades `CAMP $1D73`; logged, never written.
REST_INTERRUPT = 0x7ED2

#: How many one-second reads in a row a later-title rest may show no movement
#: of the clock or the field before it is taken as stopped.  A finished rest is
#: back on the camp bar at once and ends the wait without this; a live Silver
#: Blades rest ran a week (2016 passes) in about 35 s, so a running rest moves
#: the clock on every read and 30 s of stillness is not one.
LATER_REST_STILL = 30

#: The least time a later-title rest is given (`tools/c64/curedrive.py`'s own
#: limit), and the extra seconds per five-minute pass above it.
LATER_REST_DEADLINE = 900
LATER_REST_PASS_SECONDS = 1.0


def sample(m, base: int = SAVE0_LOAD) -> dict:
    """The four arrays and the clock, read in one pass; for Pool, the
    staging page's strength bytes as well.

    `base` is where the title loads its save payload: `SAVE0_LOAD` for Pool,
    `LATER_LOAD` for Curse and Silver Blades.  The staging page is Pool's
    and is not read for another base.
    """
    head = m.read(base, 0x300)
    mag = m.read(base + effects.EFFECT_MAGNITUDE_OFFSET, 0x40)
    clock = CLOCK - SAVE0_LOAD
    out = {
        "id": list(head[0x00:0x40]),
        "owner": list(head[0x40:0x80]),
        "duration": list(head[0x80:0xC0]),
        "magnitude": list(mag[0x00:0x40]),
        "clock": list(head[clock:clock + 6]),
    }
    if base == SAVE0_LOAD:
        rec = m.read(STAGING_PAGE, 0x40)
        out["staging_str"] = [rec[REC_STR], rec[REC_STR_PCT], rec[REC_CHA]]
    return out

def live_records(m) -> dict[int, list[int]]:
    block = m.read(SLOT_BASE, SLOT_STRIDE * 8)
    out = {}
    for slot in range(8):
        rec = block[slot * SLOT_STRIDE:(slot + 1) * SLOT_STRIDE]
        if any(rec):
            out[slot] = [rec[REC_STR], rec[REC_STR_PCT], rec[REC_CHA]]
    return out

def rest(sess, log, minutes: int, hours: int, cp: dict) -> dict:
    """`REST` for *minutes* minutes and *hours* hours, sampled either side.

    The rest length is written into `CAMP`'s own rest-time field rather than
    driven with `INCREASE`, the way `tools/c64/c64restinterrupt.py` does it:
    the default is whatever the party has left to memorise, and `INCREASE`'s
    step grows while the key is held.  The engine then counts the field down
    five minutes at a time, and each five-minute pass is one call of the
    expiry sweep.

    A Curse or Silver Blades session (`sess.game`) goes to `rest_later`.
    """
    game = getattr(sess, "game", c64_port.POOL_OF_RADIANCE)
    if game.key in LATER_REST_TIME:
        return rest_later(sess, log, minutes, hours, cp, LATER_REST_TIME[game.key])
    if not sess.select_bar("REST"):
        log.say("  REST was not on the camp bar")
        return {"failed": "no REST on the camp bar"}
    if sess.wait_text("INCREASE", timeout=30)[0] is None:
        log.say("  the rest-time bar never appeared")
        return {"failed": "no rest-time bar"}
    with sess.mon(10) as m:
        before = sample(m)
        m.write(REST_TIME, bytes((minutes, hours, 0)))
        staged = tuple(m.read(REST_TIME, 3))
        m.resume()
    if staged != (minutes, hours, 0):
        return {"failed": f"rest time read back {staged}"}
    if not sess.select_bar("REST"):
        return {"failed": "no REST on the rest-time bar"}
    # The rest is over when the clock stops moving.  No key is sent while it
    # runs: `CAMP $1E44` reads the keyboard every pass and SPACE ends it.
    deadline, still, last = time.time() + 300, 0, None
    while time.time() < deadline and still < 10:
        time.sleep(1.0)
        with sess.mon(10) as m:
            now = bytes(m.read(CLOCK, 6))
            m.resume()
        still = still + 1 if now == last else 0
        last = now
    with sess.mon(10) as m:
        after = sample(m)
        counts = {k: m.checkpoint_hits(v) for k, v in cp.items()}
        records = live_records(m)
        m.resume()
    log.say(f"  rest {minutes}m {hours}h: clock {before['clock']} -> "
            f"{after['clock']}")
    log.say(f"    durations {before['duration'][:6]} -> "
            f"{after['duration'][:6]}")
    log.say(f"    ids {after['id'][:6]}  counts {counts}")
    return {"before": before, "after": after, "records": records, **counts}


def rest_later(sess, log, minutes: int, hours: int, cp: dict,
               field: int) -> dict:
    """Curse's or Silver Blades' `REST`, the same way `rest` drives Pool's.

    The camp's `REST` puts up `REST TIME :  0 DAYS  0 HRS  0 MINS` over
    `REST ADD SUBTRACT EXIT`.  The time is written into the rest-time
    `field` (minutes, hours, days), with hours of 24 or more carried into
    days, rather than stepped with `ADD`, and the bar's own `REST` starts it.
    No key is sent while it runs.  A rest of no time, or one whose minutes
    or days do not fit a byte, is refused before anything is pressed.

    `ended` in the result says how the wait stopped:

    * `completed` -- the field read zero with the camp bar on row 24;
    * `interrupted` -- neither the clock nor the field moved for
      `LATER_REST_STILL` reads, and row 24 held something the game put up in
      place of the rest: the camp bar with time still in the field, or any
      other text (`curedrive.py` read an interruption as `CONTINUE`);
    * `stalled` -- the same stillness with row 24 blank or still the rest-time
      bar, which is no known ending;
    * `deadline` -- the clock was still moving when the time allowed
      (`LATER_REST_DEADLINE`, or one `LATER_REST_PASS_SECONDS` per pass when
      that is more) ran out.

    `interrupted` is true for the second alone; `rest_left` is the field and
    `bar` row 24 when the wait stopped, and `still_reads` names the stillness
    threshold when that is what stopped it.
    """
    want = (minutes, hours % 24, hours // 24)
    if want == (0, 0, 0):
        log.say("  a rest of no time was asked for")
        return {"failed": "a rest of no time"}
    if not all(0 <= b <= 0xFF for b in want):
        log.say(f"  the rest time {want} does not fit the field's three bytes")
        return {"failed": f"rest time {want} does not fit the rest-time field"}
    press = getattr(sess, "press_bar", sess.select_bar)
    if not press("REST"):
        log.say("  REST was not on the camp bar")
        return {"failed": "no REST on the camp bar"}
    if sess.wait_text(LATER_REST_BAR, timeout=30)[0] is None:
        log.say("  the rest-time bar never appeared")
        return {"failed": "no rest-time bar"}
    with sess.mon(10) as m:
        before = sample(m, LATER_LOAD)
        interrupt = list(m.read(REST_INTERRUPT, 2))
        m.write(field, bytes(want))
        staged = tuple(m.read(field, 3))
        m.resume()
    if staged != want:
        log.say(f"  the rest time read back {staged}, not {want}")
        return {"failed": f"rest time read back {staged}"}
    if not press("REST"):
        log.say("  REST was not on the rest-time bar")
        return {"failed": "no REST on the rest-time bar"}
    passes = -(-(hours * 60 + minutes) // 5)
    allowed = max(LATER_REST_DEADLINE, passes * LATER_REST_PASS_SECONDS)
    deadline, still, last, left = time.time() + allowed, 0, None, bytes(want)
    ended = "deadline"
    while time.time() < deadline:
        time.sleep(1.0)
        with sess.mon(10) as m:
            now = bytes(m.read(CLOCK - SAVE0_LOAD + LATER_LOAD, 6))
            left = bytes(m.read(field, 3))
            m.resume()
        s = sess.screen() if left == bytes(3) else None
        if s is not None and CAMP_BAR in s.row(24):
            ended = "completed"
            break
        still = still + 1 if (now, left) == last else 0
        last = (now, left)
        if still >= LATER_REST_STILL:
            ended = "stopped"
            break
    with sess.mon(10) as m:
        after = sample(m, LATER_LOAD)
        counts = {k: m.checkpoint_hits(v) for k, v in cp.items()}
        m.resume()
    s = sess.screen()
    bar = "" if s is None else s.row(24).rstrip()
    extra = {}
    if ended == "stopped":
        extra["still_reads"] = LATER_REST_STILL
        shown = bar.strip()
        ended = ("stalled" if not shown or LATER_REST_BAR in shown
                 else "interrupted")
    log.say(f"  rest {minutes}m {hours}h: clock {before['clock']} -> "
            f"{after['clock']}, field left {list(left)}, {ended}")
    log.say(f"    ids {after['id'][:6]}  counts {counts}")
    log.emit("screen", tag="rest-end", rows=sheet_rows(sess), ended=ended,
             rest_left=list(left), rest_interrupt=interrupt, **extra)
    return {"before": before, "after": after, "ended": ended,
            "interrupted": ended == "interrupted", "rest_left": list(left),
            "bar": bar, "rest_interrupt": interrupt, **extra, **counts}
