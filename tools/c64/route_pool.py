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
from tools.c64 import screens
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

class PanelError(LookupError):
    """A party line that cannot be chosen: absent, out of range or ambiguous."""

def is_line_number(who: str) -> bool:
    """Whether `who` names a party line by number.  A name made only of digits
    is read as a line number, never as a name."""
    return who.strip().isdecimal() and who.strip().isascii()

def line_number(who: str, count: int | None = None) -> int:
    """The 0-based panel row for the party line number `who`, counting from 1.

    `count` is the number of panel rows when the panel has been read; without
    it only a line below 1 is rejected.
    """
    n = int(who.strip())
    if n < 1 or (count is not None and n > count):
        have = "" if count is None else f", which has {count} lines"
        raise PanelError(f"Party line {n} is not on the panel{have}.")
    return n - 1

def panel_names(s, rows: list[int]) -> tuple[list[str], int]:
    """The name column of each panel row, and that column's width.

    The column runs from `PARTY_COLUMN` to where the `AC` heading starts, so
    the stat columns after it are never part of a name.  Raises `PanelError`
    when there is no heading to bound it.
    """
    for r in S.PARTY_ROWS:
        if S.PARTY_HEADER in s.row(r)[S.PARTY_COLUMN:]:
            width = s.row(r)[S.PARTY_COLUMN:].index(S.PARTY_HEADER)
            break
    else:
        raise PanelError("The party panel has no AC heading, so its name "
                         "column cannot be told from the stats.")
    return [s.row(r)[S.PARTY_COLUMN:S.PARTY_COLUMN + width].strip()
            for r in rows], width

def pick_panel_row(names: list[str], width: int, who: str) -> int:
    """Which panel row `who` is, 0 first: a number counts party lines from 1
    (a name made only of digits is a line number), and a name must equal one
    row's name column.

    The panel cuts a name that does not fit, so a column that fills its whole
    width also matches the start of a longer name.
    """
    if is_line_number(who):
        return line_number(who, len(names))
    who = who.strip()
    wanted = {who.upper(), screens.as_drawn(who).upper()}
    hits = [i for i, field in enumerate(n.upper() for n in names)
            if field in wanted or (field and len(field) == width
                                   and any(w.startswith(field) for w in wanted))]
    if not hits:
        raise PanelError(f"{who} is not on the party panel: {names}.")
    if len(hits) > 1:
        raise PanelError(f"{who} matches more than one party line "
                         f"({', '.join(names[i] for i in hits)}); "
                         "ask for it by line number.")
    return hits[0]

def panel_index(sess: S.Session, name: str) -> int | None:
    """Which row of the world panel names this character, 0 first, or None
    when the panel cannot be read.  A number counts party lines from 1.

    **The panel is in marching order, not save-slot order.** `PORSAVE13`
    keeps MALCYON in slot 0 and lists BRUTUS first, so `select_party(0)` put
    the highlight on BRUTUS and VIEW showed his sheet -- twice, before this
    was read off the screen instead of assumed.  Raises `PanelError` when the
    name is absent or ambiguous, or the line number is off the panel.
    """
    s = sess.screen()
    if s is None:
        return line_number(name) if is_line_number(name) else None
    rows = sess.party_rows(s)
    if is_line_number(name):
        return line_number(name, len(rows))
    names, width = panel_names(s, rows)
    return pick_panel_row(names, width, name)

def open_items(sess: S.Session, log: Log, name: str, label: str,
               tag: str) -> bool:
    """ENCAMP > VIEW > the character called `name` > ITEMS, list left up.

    **From camp, not from the world.** `LIBRARY $4630`, the READY toggle,
    rejects a magical item -- bit 7 of `+15` -- with `NOT HERE` unless
    `$6DE4` is set, and CAMP sets it at `$0818` on entering the camp menu
    and clears it at `$0862` on leaving. Five runs pressed READY on the
    world's VIEW and the message flashed too briefly for a screen read.
    """
    try:
        at = panel_index(sess, name)
    except PanelError as e:
        log.say(f"  {e}")
        at = None
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
#: name starting in column 6 after the `YES`/`NO` column. `screens.ITEM_ROWS`
#: (4 to 22) is the wider window a capture is read through, so a list is never
#: clipped when read as text; the cursor never leaves these rows.
ITEM_ROWS = range(5, 22)

ITEM_NAME_COLUMN = 6

def item_rows(s) -> list[int]:
    # Column 39 is the window border, drawn on blank rows too.
    return [r for r in ITEM_ROWS if s.row(r)[ITEM_NAME_COLUMN:39].strip()]

#: The colour of an item-list cell the cursor is not on: green on every row
#: of a Pool capture, with the cursor row white.
ITEM_PLAIN_COLOUR = 5

def item_baseline(s, rows: list[int]) -> int:
    """The colour an unhighlighted cell has on this list: a blank row below
    the entries, which the cursor never visits, else the known ordinary colour.
    Counting colours instead picks the wrong row on a two-row list, where
    each colour occurs once."""
    below = max(rows, default=ITEM_ROWS.start) + 1
    for r in range(below, ITEM_ROWS.stop):
        if not s.row(r)[1:39].strip():
            return s.colours[r * 40 + ITEM_NAME_COLUMN]
    return ITEM_PLAIN_COLOUR

def item_highlight(s, rows: list[int]) -> int | None:
    """Which item row the cursor is on: the one whose name colour differs from
    `item_baseline`, or None when no row or more than one does."""
    if not rows:
        return None
    base = item_baseline(s, rows)
    odd = [r for r in rows if s.colours[r * 40 + ITEM_NAME_COLUMN] != base]
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
        # Rows are drawn inside a `$` border, so compare the text between.
        rows = [r for r in ITEM_ROWS if s.row(r)[1:39].strip()]
        at = item_highlight(s, rows)
        exit_row = next((r for r in rows if s.row(r)[1:39].strip() == "EXIT"), None)
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

#: Pool's rest-interrupted marker: `CAMP $1E29` stores `REST_INTERRUPTED`
#: here when the area's check stops a rest, and `CAMP $0886` then leaves camp
#: with no key; `DUNGEON $19D9` runs the area script's entry 3, which zeroes
#: it again -- in New Phlan (`ECL00 $9A93`) before the city watch's `GO STAY`
#: (`docs/207-c64-rest-interruption.md`).  The camp code is gone, and the
#: marker back at 0, within about ten seconds of the clock stopping, so
#: `CAMP_TICK_BYTES` missing is the other sign of the same interruption.
REST_MARKER = 0x6DD3
REST_INTERRUPTED = 0xFF
#: `CAMP $1E0F`, `LDA $6DD2 / BEQ`: the rest loop's first bytes, there only
#: while `CAMP` is the overlay at `$0800` (`tools/c64/c64restinterrupt.py`).
CAMP_TICK = 0x1E0F
CAMP_TICK_BYTES = bytes((0xAD, 0xD2, 0x6D, 0xF0, 0x20))


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
#: $1F76` and Silver Blades `CAMP $1D73`: an interval of 0 skips the check
#: on every pass.  Read here; only `Session.suppress_rest_interruption`
#: writes it.
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

def rest(sess, log, minutes: int, hours: int, cp: dict,
         quiet: bool = False) -> dict:
    """`REST` for *minutes* minutes and *hours* hours, sampled either side.

    The rest length is written into `CAMP`'s own rest-time field rather than
    driven with `INCREASE`, the way `tools/c64/c64restinterrupt.py` does it:
    the default is whatever the party has left to memorise, and `INCREASE`'s
    step grows while the key is held.  The engine then counts the field down
    five minutes at a time, and each five-minute pass is one call of the
    expiry sweep.

    A Pool rest the area's check interrupted -- `REST_MARKER` still
    `REST_INTERRUPTED`, or `CAMP` already gone from `$0800` -- also returns
    `ended` (`interrupted`), `interrupted`, `bar` (row 24 as read, which can
    still be the rest-time bar after camp has closed), `rest_marker` and
    `camp_resident`; an uninterrupted one returns none of them.

    A Curse or Silver Blades session (`sess.game`) goes to `rest_later`.

    *quiet* zeroes the area's rest interruption for this rest whether or not
    the session's `no_encounters` is on (`Session.suppress_rest_interruption`
    with `force`), so a check such as Tilverton's guards, which ends every
    rest after its first pass, does not run; the result then says so in
    `rest_interrupt_suppressed`.
    """
    game = getattr(sess, "game", c64_port.POOL_OF_RADIANCE)
    if game.key in LATER_REST_TIME:
        return rest_later(sess, log, minutes, hours, cp,
                          LATER_REST_TIME[game.key], quiet=quiet)
    if not sess.select_bar("REST"):
        log.say("  REST was not on the camp bar")
        return {"failed": "no REST on the camp bar"}
    if sess.wait_text("INCREASE", timeout=30)[0] is None:
        log.say("  the rest-time bar never appeared")
        return {"failed": "no rest-time bar"}
    with sess.mon(10) as m:
        before = sample(m)
        m.write(REST_TIME, bytes((minutes, hours, 0)))
        sess.suppress_rest_interruption(m, force=quiet)
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
        marker = m.read(REST_MARKER, 1)[0]
        in_camp = bytes(m.read(CAMP_TICK, len(CAMP_TICK_BYTES))) == CAMP_TICK_BYTES
        m.resume()
    log.say(f"  rest {minutes}m {hours}h: clock {before['clock']} -> "
            f"{after['clock']}")
    log.say(f"    durations {before['duration'][:6]} -> "
            f"{after['duration'][:6]}")
    log.say(f"    ids {after['id'][:6]}  counts {counts}")
    got = {"before": before, "after": after, "records": records, **counts}
    if quiet:
        got["rest_interrupt_suppressed"] = True
    if marker == REST_INTERRUPTED or not in_camp:
        s = sess.screen()
        bar = "" if s is None else s.row(24).rstrip()
        log.say(f"    interrupted: ${REST_MARKER:04X} = ${marker:02X}, CAMP "
                f"{'still' if in_camp else 'no longer'} at $0800, "
                f"row 24 {bar!r}")
        got.update(ended="interrupted", interrupted=True, bar=bar,
                   rest_marker=marker, camp_resident=in_camp)
    return got


def rest_later(sess, log, minutes: int, hours: int, cp: dict,
               field: int, quiet: bool = False) -> dict:
    """Curse's or Silver Blades' `REST`, the same way `rest` drives Pool's.

    The camp's `REST` puts up `REST TIME :  0 DAYS  0 HRS  0 MINS` over
    `REST ADD SUBTRACT EXIT`.  The time is written into the rest-time
    `field` (minutes, hours, days), with hours of 24 or more carried into
    days, rather than stepped with `ADD`, and the bar's own `REST` starts it.
    No key is sent while it runs.  A rest of no time, or one whose minutes
    or days do not fit a byte, is rejected before anything is pressed.

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
    threshold when that is what stopped it.  `rest_interrupt` is the area's
    interval and chance (`REST_INTERRUPT`) as found before anything was
    written, and *quiet* zeroes the interval as `rest` describes.  An
    interrupted rest also returns
    `text`, the message rows 17-22 without their frame: a scripted event's
    words, such as Silver Blades' THE BLACK CIRCLE SENDS MONSTERS AGAINST
    THE TOWN over `PRESS BUTTON OR RETURN TO CONTINUE.`, before the fight
    it starts.
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
        sess.suppress_rest_interruption(m, force=quiet)
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
    if quiet:
        extra["rest_interrupt_suppressed"] = True
    if ended == "interrupted" and s is not None:
        extra["text"] = [t for t in (s.row(r).strip("$%& ")
                                     for r in range(17, 23)) if t]
    log.say(f"  rest {minutes}m {hours}h: clock {before['clock']} -> "
            f"{after['clock']}, field left {list(left)}, {ended}")
    log.say(f"    ids {after['id'][:6]}  counts {counts}")
    log.emit("screen", tag="rest-end", rows=sheet_rows(sess), ended=ended,
             rest_left=list(left), rest_interrupt=interrupt, **extra)
    return {"before": before, "after": after, "ended": ended,
            "interrupted": ended == "interrupted", "rest_left": list(left),
            "bar": bar, "rest_interrupt": interrupt, **extra, **counts}


#: `SAVEDGAME1` loads at `$8300`; the roster is eight 32-byte blocks with the
#: current hit points at `+$19` (`goldbox/savegame.py`).
SAVE1_LOAD = 0x8300
ROSTER_STRIDE = 0x20
ROSTER_HP = 0x19


def roster_hp(m) -> list[int]:
    """Current hit points of the eight roster blocks at `$8300`."""
    raw = m.read(SAVE1_LOAD, ROSTER_STRIDE * 8)
    return [raw[i * ROSTER_STRIDE + ROSTER_HP] for i in range(8)]


class Caster:
    """A fight tactic: the named caster casts the named spell at the named
    party member when his turn comes, and everybody else fights as before.

    `queue` is `[(caster, spell, target), ...]`, names as the panel prints
    them; a target of None is a spell the game casts without a target prompt
    (a party spell such as Prayer). `otherwise` is the tactic for every turn
    that is not a cast, `Session.melee_turn` unless the caller wants another.
    With `last`, the caster casts only once every other occupied party slot has
    bit 7 of its roster status set (running, or down), so the spell is the last
    thing cast before the fight ends; until then his turns run `wait`, or
    `otherwise` when `wait` is None.
    Everything it does is logged with the screen, because nothing in this
    project has driven CAST in combat before and a failed attempt has to say
    where it got to.
    """

    BACK_OUT_PRESSES = 3

    #: Own turns spent waiting for the others after which every member's
    #: roster status is logged, so a stalled wait names the member holding it.
    WAIT_REPORT_TURNS = 20

    def __init__(self, log: Log, queue: list[tuple[str, str, str | None]],
                 otherwise=None, wait=None, last=False):
        self.log = log
        self.queue = list(queue)
        self.otherwise = otherwise or S.Session.melee_turn
        self.wait = wait or self.otherwise
        self.last = last
        self.turn = 0
        self.waits = 0
        self.casts: list[dict] = []

    def __call__(self, sess: S.Session, state) -> str:
        self.turn += 1
        with sess.mon(8) as m:
            now = roster_hp(m)
            m.resume()
        self.log.emit("hp", turn=self.turn, hp=now)
        b = sess.battle()
        me = sess.acting(b)
        if me is not None and self.queue and \
                me.name.strip() == self.queue[0][0]:
            if self.last and not self.others_gone(sess, me):
                self.waits += 1
                if self.waits >= self.WAIT_REPORT_TURNS:
                    self.report_wait(sess)
                return self.wait(sess, state)
            _, spell, target = self.queue[0]
            if self.cast(sess, b, me, spell, target):
                self.queue.pop(0)
                return "CAST"
            # One attempt per queued cast: a cast that failed is dropped, so
            # every later turn of that member is the other tactic's and the
            # fight is not spent retrying it.
            self.log.say(f"  {spell} dropped after one failed attempt")
            self.queue.pop(0)
        return self.otherwise(sess, state)

    @staticmethod
    def down_words(gone: bool = True) -> frozenset[int]:
        """The low three bits of a roster status that name a member who is
        out of the fight: dead, dying, unconscious, stoned and, with `gone`,
        gone."""
        from tools.pool_of_radiance import fleedrive
        names = ("DEAD", "DYING", "UNCONSIOUS", "STONED") + (
            ("GONE",) if gone else ())
        return frozenset(code for code, word in fleedrive.STATUS_WORDS.items()
                         if word in names)

    @staticmethod
    def others_gone(sess: S.Session, me) -> bool:
        """Whether every other occupied party slot is running or down."""
        from tools.pool_of_radiance import fleedrive
        down = Caster.down_words()
        states = fleedrive.statuses(fleedrive.roster_page(sess))
        return all(st == 0 or st & 0x80 or st & 7 in down
                   for slot, st in enumerate(states) if slot != me.index)

    def report_wait(self, sess: S.Session) -> None:
        """Log every roster status, naming who the caster is still waiting for."""
        from tools.pool_of_radiance import fleedrive
        states = fleedrive.statuses(fleedrive.roster_page(sess))
        self.log.emit("cast-wait", turn=self.turn, waits=self.waits,
                      statuses=[f"{st:02X}" for st in states],
                      words=[fleedrive.describe(st) for st in states])

    def cast(self, sess: S.Session, b, me, spell: str,
             target: str | None) -> bool:
        who = None
        if target is not None:
            who = next((c for c in b.characters if c.name.strip() == target),
                       None)
            if who is None:
                self.log.say(f"  no {target} on the map")
                return False
        with sess.mon(8) as m:
            before = roster_hp(m)
            m.resume()
        if not sess.combat_bar("CAST", timeout=12):
            self.log.say("  CAST could not be selected")
            return False
        time.sleep(1.0)
        self.log.emit("screen", tag="cast-list", rows=sheet_rows(sess))
        if sess.wait_text(spell, 10)[0] is None:
            self.log.say(f"  {spell} is not on the list")
            self.log.emit("screen", tag="cast-nospell", rows=sheet_rows(sess))
            sess.press_kernal(0x0D)
            return False
        # `SPELLS: CAST EXIT` is the bar; CAST on it puts a cursor on the
        # list, the same form as the item list, and fire picks the row.
        if not sess.select_bar("CAST", timeout=10):
            self.log.say("  CAST could not be selected on the spells bar")
            return False
        time.sleep(0.8)
        chosen = False
        deadline = time.time() + 15
        while time.time() < deadline:
            s = sess.screen()
            if s is None:
                time.sleep(0.3)
                continue
            # Only the spell rows and the list's own EXIT: the heading and
            # the level line are coloured on their own account and would
            # make the odd-one-out test find nothing.
            rows = [r for r in range(3, 22)
                    if spell in s.row(r) or s.row(r).strip() == "EXIT"]
            want = next((r for r in rows if spell in s.row(r)), None)
            at = item_highlight(s, rows)
            if want is None or at is None:
                time.sleep(0.3)
                continue
            if at == want:
                press_select(sess)
                chosen = True
                break
            sess.kbd.key("Down" if at < want else "Up", 0.15, 0.30)
        if not chosen:
            self.log.say(f"  could not choose {spell}")
            self.log.emit("screen", tag="cast-stuck", rows=sheet_rows(sess))
            return False
        time.sleep(1.0)
        if target is None:
            return self.finish_untargeted(sess, me, spell, before)
        self.log.emit("screen", tag="cast-aim", rows=sheet_rows(sess),
                      me=(me.x, me.y), target=(who.x, who.y))
        # The game then puts up `NEXT PREV MANUAL TARGET EXIT`: NEXT cycles
        # the candidate targets and the right-hand panel names the current
        # one, TARGET confirms.
        if sess.wait_text("TARGET", 10)[0] is None:
            self.log.say("  no targeting bar after choosing the spell")
            self.log.emit("screen", tag="cast-notarget", rows=sheet_rows(sess))
            return False
        aimed = False
        for n in range(24):
            s = sess.screen()
            if s is None:
                time.sleep(0.3)
                continue
            panel = " ".join(s.row(r)[S.PANEL_LEFT:] for r in range(0, 12))
            self.log.emit("aim", n=n, panel=panel.split())
            if target in panel:
                aimed = True
                break
            if not sess.combat_bar("NEXT", timeout=8):
                break
            time.sleep(0.7)
        self.log.emit("screen", tag="cast-aimed", rows=sheet_rows(sess),
                      aimed=aimed)
        if not aimed:
            self.log.say(f"  NEXT never brought the panel round to {target}")
            sess.combat_bar("EXIT", timeout=8)
            return False
        if not sess.combat_bar("TARGET", timeout=8):
            self.log.say("  TARGET could not be selected")
            return False
        time.sleep(2.5)
        self.log.emit("screen", tag="cast-done", rows=sheet_rows(sess))
        sess.handle_prompt()
        with sess.mon(8) as m:
            after = roster_hp(m)
            m.resume()
        record = {"caster": me.name.strip(), "spell": spell, "target": target,
                  "hp_before": before, "hp_after": after}
        self.casts.append(record)
        self.log.emit("cast", **record)
        self.log.say(f"  {me.name.strip()} cast {spell} at {target}: hp "
                     f"{before[:6]} -> {after[:6]}")
        return True

    def finish_untargeted(self, sess: S.Session, me, spell: str,
                          before: list[int]) -> bool:
        """The end of a cast whose spell has no target prompt: the game casts
        it on the pick. A targeting bar that does appear is backed out of and
        reported, because that spell is not one this path knows how to aim."""
        if sess.wait_text("TARGET", 4)[0] is not None:
            self.log.say(f"  {spell} asked for a target")
            self.log.emit("screen", tag="cast-asked-target",
                          rows=sheet_rows(sess))
            # The next turn starts from the combat bar, so EXIT until it is
            # back; a bar that never returns fails the step.
            for _ in range(self.BACK_OUT_PRESSES):
                sess.combat_bar("EXIT", timeout=8)
                if sess.await_bar((S.BAR_COMMAND,), timeout=4) is not None:
                    return False
            raise RuntimeError(f"the combat bar did not come back after "
                               f"backing out of {spell}")
        time.sleep(2.5)
        self.log.emit("screen", tag="cast-done", rows=sheet_rows(sess))
        sess.handle_prompt()
        with sess.mon(8) as m:
            after = roster_hp(m)
            m.resume()
        record = {"caster": me.name.strip(), "spell": spell, "target": None,
                  "hp_before": before, "hp_after": after}
        self.casts.append(record)
        self.log.emit("cast", **record)
        self.log.say(f"  {me.name.strip()} cast {spell}")
        return True
