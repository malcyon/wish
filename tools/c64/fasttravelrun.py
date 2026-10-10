#!/usr/bin/env python3
"""Run the app's own Fast Travel against a live C64 Gold Box game and log every trip.

`automap.actions.FastTravel` is applied through a `ViceTarget` on the session's
monitor port, one trip per `--to`, in order, with `continue_pending` called every
poll so a two-hop trip makes its second hop. Every memory write comes from that
code, except the bytes `--stage` names: each is written before its leg, logged
with the byte read back, and passes the same guard that fails on any write
touching the random-number generator (`$03C2`-`$03C8`).

    tools/c64/fasttravelrun.py --save SPECIMEN.D64 --to 18 --to 2 --to 15 --answer YES

`--title KEY` picks the game (`pool-of-radiance`, the default,
`curse-of-the-azure-bonds` or `secret-of-the-silver-blades`): its session, disk
sides, `FastTravel` container, area table and the cache-slot and came-from
addresses. `--peek ADDR[:LEN]` (hex, repeatable) logs those bytes before and
after every leg. `--stage N:ADDR=VALUE` writes one byte (VALUE decimal, or hex
with `$` or `0x`) before leg N, counted from 0. Every leg also logs the party's
names before and after, the live square after `apply`, and `areas_seen`: each
area the `$6E1B`-style cache slot showed on any 0.2 s poll, in order, without
repeats.

`--no-encounters` calls `Session.suppress_encounters` (the switch of
`tools/c64/acceptance.py --no-encounters`) before each leg and again whenever
the came-from or cache-slot byte changes during the leg, so the area each hop
loads is covered as well as the one the party starts in, and
`restore_encounter_gates` when the run ends, logging each; Only areas in `tools/c64/session.py` `ENCOUNTER_GATES` are covered; an
area with no gate there is logged as `encounters-live`.

A trip has arrived when `$6E1B` and `$49F2` both equal the destination and
`legality` toward a different area passes; a check toward the destination
itself answers "already in that area" and proves nothing. Each poll first lets
`Session.handle_prompt` answer an `insert a disk` prompt, and only then
presses RETURN, and only on a `PRESS ...` message: the move sub-bar
`I,J,K,M, RETURN OR BUTTON` is left alone. `--answer WORD` selects that word
on a bar offering it (`YES NO`, at most `ANSWERS_PER_TRIP` times a trip).
Given several times, each word answers one question in order, only when it is
on the bar, and a question met with none left fails the run.
A "cannot act right now" answer from `legality` or `apply` is retried every
`BUSY_SECONDS`, at most `BUSY_TRIES` times; the bar's "the game was busy"
message every `BAR_BUSY_SECONDS`, at most `BAR_BUSY_TRIES` times.
`--then-save` makes camp and saves once every leg arrived, and keeps the disk
as `saved.D64`. `--step-after` turns before it steps when the party stands where
the forward key leaves the area. Both wait for the world bar first, answering a question the arrival
drew (an `--answer` word on the bar, RETURN on a `PRESS` message), and fail without stepping or saving
when it never comes back.

`--through-bar` runs each leg through the Fast Travel row the window builds for
the title (offscreen), picks the destination in its dropdown, presses its
button and logs a `bar` event with the action's title and the buttons' enabled
state and tooltips. `--to back` is a leg that presses the row's Return button;
it needs `--through-bar`.

OUT/run.jsonl holds one line per event; screenshots sit beside it. OUT defaults
to a directory under `~/.cache/wish/fasttravel`. The emulator slot is claimed
from the pool (`--slot` names one) and released on every exit, and a trip still
pending when the run ends is cancelled.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import re
import sys
import time
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from automap import actions as engine  # noqa: E402
from automap import fasttravel  # noqa: E402
from automap.target import NotConnected  # noqa: E402
from automap.vice import MonitorError  # noqa: E402
from goldbox import c64_port  # noqa: E402

#: Seconds between two `continue_pending` calls.
POLL_SECONDS = 0.2
#: Seconds between two looks at the screen while a trip is outstanding.
SCREEN_SECONDS = 2.0
#: Seconds a leg may take.
BUDGET_SECONDS = 180.0
#: Seconds between two tries of a call that answered "cannot act right now".
BUSY_SECONDS = 0.5
#: Tries of such a call before the leg is given up.
BUSY_TRIES = 40
#: Seconds between two tries of a bar that answered "the game was busy", and the tries
#: before the leg is given up (sixty seconds in all; each try already waits the bar's own two).
BAR_BUSY_SECONDS = 2.0
BAR_BUSY_TRIES = 30
#: Tries of one connection to the monitor before the run gives up.
CONNECT_TRIES = 5
#: Times one leg answers a bar with `--answer`.
ANSWERS_PER_TRIP = 4
#: Seconds the game takes to draw an arrival, before the last screenshot.
SETTLE_SECONDS = 3.0
#: Every Nth screen look also takes a screenshot.
SHOT_EVERY = 4

#: The generator's seven bytes.
RNG_FIRST, RNG_LAST = 0x03C2, 0x03C8
MOVE_SUBBAR = "I,J,K,M"
#: Bar words that mark a game question when `--answer` is given more than once.
QUESTION_WORDS = frozenset({"YES", "NO", "LEAVE", "LARGE", "SMALL", "ATTACK", "TALK"})
#: Consecutive looks at a question bar the next `--answer` word is not on before the leg is given up.
UNANSWERED_LOOKS = 3
#: Looks, a second apart, at the screen before a save while it is cleared back to the world bar.
SAVE_CLEAR_TRIES = 30
#: A script's acknowledgement, which is answered with RETURN.
RETURN_MESSAGE = "PRESS"


#: The leg token that travels back to where the last leg started.
BACK = "back"


class DriverError(RuntimeError):
    """The run cannot go on."""


class BarFastTravel:
    """The `FastTravel` interface over the Fast Travel row, so a leg is run the
    way the window's buttons run it and the row's own state is logged.

    The row rebinds its action when the title changes, so everything here asks
    `bar.fasttravel` at the moment of the call.
    """

    def __init__(self, bar, log):
        self.bar, self.log = bar, log

    @property
    def game(self):
        return self.bar.fasttravel.game

    @property
    def back(self):
        return self.bar.fasttravel.back

    @property
    def pending(self):
        return self.bar.fasttravel.pending

    def _attach(self, target, area=None) -> bool:
        """Attach, and pick `area` in the dropdown; False when it is not listed."""
        self.bar.attach(target)
        if area is None:
            return True
        if area not in self.bar.rows:
            return False
        self.bar.combo.setCurrentIndex(self.bar.rows.index(area))
        self.bar.refresh()
        return True

    def _state(self) -> None:
        bar = self.bar
        self.log("bar", game=bar.fasttravel.game.key,
                 enabled=bar.button.isEnabled(), tooltip=bar.button.toolTip(),
                 back_enabled=bar.back_button.isEnabled(),
                 back_tooltip=bar.back_button.toolTip())

    def legality(self, target, area):
        if not self._attach(target, area):
            return self.bar.fasttravel.legality(target, area)
        self._state()
        if self.bar.button.isEnabled():
            return engine.Verdict(True)
        return engine.Verdict(False, self.bar.button.toolTip())

    def apply(self, target, area=None, **kwargs):
        if not self._attach(target, area):
            raise DriverError(f"{getattr(area, 'name', area)} is not in the row")
        return self.bar.run() or engine.Outcome(False, "the row has no area")

    def back_verdict(self, target):
        self._attach(target)
        self._state()
        if self.bar.back_button.isEnabled():
            return engine.Verdict(True)
        return engine.Verdict(False, self.bar.back_button.toolTip())

    def apply_back(self, target):
        self._attach(target)
        return self.bar.run_back()

    def continue_pending(self, target):
        self.bar.attach(target)
        return None

    def cancel_pending(self):
        self.bar.fasttravel.cancel_pending()


def build_bar(game, disks=None):
    """The Fast Travel row of a window opened on `game`, offscreen, with the maps the window loads."""
    # An exported xcb or wayland platform would open a real window, or abort, after the emulator is up.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication, QMainWindow  # noqa: PLC0415

    from automap.actionbar import FastTravelBar  # noqa: PLC0415
    from wish.ui_window import Ui_WishWindow  # noqa: PLC0415
    from wish.window import load_maps_titled  # noqa: PLC0415
    app = QApplication.instance()
    if app is not None and app.platformName() != "offscreen":
        raise DriverError(f"a {app.platformName()!r} Qt application already exists; "
                          "the driver's bar needs the offscreen platform")
    app = app or QApplication([])
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    root._driver_app = app
    maps, _title = load_maps_titled(None if disks is None else str(disks), game)
    return FastTravelBar(root, title=game.title, game=game, maps=maps)


def parse_leg(text: str):
    """An area id, or `back`."""
    if text == BACK:
        return BACK
    try:
        return int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} is neither an area id nor {BACK!r}") from None


class GuardedTarget:
    """A target that fails on any write touching the generator and passes the rest on."""

    def __init__(self, target):
        self._target = target

    def write(self, addr: int, data: bytes) -> None:
        if addr <= RNG_LAST and addr + len(data) - 1 >= RNG_FIRST:
            raise DriverError(
                f"write of {len(data)} bytes at ${addr:04X} touches the random-number "
                f"generator ${RNG_FIRST:04X}-${RNG_LAST:04X}")
        self._target.write(addr, data)

    def __getattr__(self, name):
        return getattr(self._target, name)


class Log:
    """JSON lines, each stamped with seconds since the run began."""

    def __init__(self, stream, clock: Callable[[], float]):
        self.stream = stream
        self.clock = clock
        self.began = clock()

    def __call__(self, event: str, **fields) -> None:
        self.stream.write(json.dumps(
            {"t": round(self.clock() - self.began, 3), "event": event, **fields},
            default=repr) + "\n")
        self.stream.flush()


def _byte(target, addr: int) -> int:
    return bytes(target.read(addr, 1))[0]


POOL_KEY = "pool-of-radiance"
TITLE_KEYS = (POOL_KEY, "curse-of-the-azure-bonds", "secret-of-the-silver-blades")


def container_for(key: str):
    """The container of one of `TITLE_KEYS`."""
    from goldbox import c64_save  # noqa: PLC0415
    containers = {POOL_KEY: c64_save.POOL_OF_RADIANCE,
                  "curse-of-the-azure-bonds": c64_save.CURSE_OF_THE_AZURE_BONDS,
                  "secret-of-the-silver-blades": c64_save.SECRET_OF_THE_SILVER_BLADES}
    if key not in containers:
        raise DriverError(f"{key} is not one of {', '.join(TITLE_KEYS)}")
    return containers[key]


def reading(target, addresses=None) -> dict:
    """The cache-slot and came-from bytes of a title (Pool of Radiance when None)."""
    addresses = addresses or fasttravel.POOL_OF_RADIANCE
    return {"area6E1B": _byte(target, addresses.slot),
            "script49F2": _byte(target, addresses.came_from)}


def other_area(dest: int, title=engine.ANY_TITLE) -> int:
    """An area of the title to ask legality about that is not the destination.

    It is on the same side of the overland/indoors split as the destination: from the
    overland grid every indoor area is illegal by design, so asking about one never
    reports arrival at an overland window.
    """
    rows = engine.area_rows(title)
    ids = [row.id for row in rows]
    outdoors = {row.id: bool(getattr(row, "outdoors", False)) for row in rows}
    # Pool of Radiance's two known-good answers first, so its indoor runs ask what they always asked.
    for candidate in (2, 18, *ids):
        if (candidate != dest and candidate in ids
                and outdoors[candidate] == outdoors.get(dest, False)):
            return candidate
    raise DriverError(f"{title} has no other area on the same side of the overland split as {dest}")


def parse_peek(text: str) -> tuple[int, int]:
    """`ADDR` or `ADDR:LEN`, both hex; an address with `$` or `0x` in front is allowed."""
    addr, _, length = text.partition(":")
    try:
        return int(addr.lstrip("$"), 16), int(length, 16) if length else 1
    except ValueError:
        raise DriverError(f"--peek {text!r} is not ADDR[:LEN] in hex") from None


def parse_stage(text: str) -> tuple[int, int, int]:
    """`N:ADDR=VALUE` as (leg, address, byte); ADDR is hex, VALUE decimal or `$`/`0x` hex."""
    found = re.fullmatch(r"(\d+):\$?([0-9A-Fa-f]+)=(\$[0-9A-Fa-f]+|\w+)", text.strip())
    try:
        if found is None:
            raise ValueError
        value = found[3]
        parsed = (int(found[1]), int(found[2], 16),
                  int(value[1:], 16) if value.startswith("$") else int(value, 0))
        if not 0 <= parsed[2] <= 255:
            raise ValueError
    except ValueError:
        raise DriverError(f"--stage {text!r} is not N:ADDR=VALUE with a byte value") from None
    if RNG_FIRST <= parsed[1] <= RNG_LAST:
        raise DriverError(f"--stage {text!r} writes the random-number generator")
    return parsed


def fasttravel_addresses(game):
    found = fasttravel.addresses_for(game)
    if found is None:
        raise DriverError(f"{game.title} has no fast-travel addresses")
    return found


STEP_TRIES = 4
#: Compass digits tried, in order, on the travel grid.
OUTDOOR_STEP_KEYS = "3715"


class Driver:
    """The trips of one session."""

    def __init__(self, sess, connect: Callable[[], object], fasttravel, out: pathlib.Path,
                 log: Log, answer: str | list[str] | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 budget: float = BUDGET_SECONDS, game=None,
                 peeks: list[tuple[int, int]] | None = None,
                 stages: list[tuple[int, int, int]] | None = None,
                 party_reader: Callable[[object, object], object] | None = None,
                 no_encounters: bool = False, gates: dict | None = None,
                 step_after: bool = False):
        self.no_encounters = no_encounters
        self.step_after = step_after
        #: `ENCOUNTER_GATES`, or None to take it from `tools/c64/session.py`.
        self.gates = gates
        #: (came-from, cache slot) when the switch was last applied in this leg.
        self._held_at: tuple[int, int] | None = None
        self.sess, self.connect, self.ft = sess, connect, fasttravel
        self.out, self.log, self.answer = out, log, answer
        #: With several `--answer` words each answers one question, in order.
        self.answers_used = 0
        #: (row, looks) of a question bar the next `--answer` word is not on.
        self._unanswered: tuple[str, int] = ("", 0)
        self.sleep, self.clock, self.budget = sleep, clock, budget
        #: The title being travelled in; its table, addresses and party layout.
        self.game = game or c64_port.POOL_OF_RADIANCE
        self.addresses = fasttravel_addresses(self.game)
        self.peeks, self.stages = peeks or [], stages or []
        self.party_reader = party_reader or engine.read_party
        #: The legs finished so far, kept here so a run that stops early can still report them.
        self.results: list[dict] = []

    def target(self):
        """A guarded connection; a busy or briefly absent monitor is retried, bounded."""
        for attempt in range(CONNECT_TRIES):
            try:
                connection = self.connect()
                break
            except NotConnected as exc:
                self.log("connect-retry", attempt=attempt, error=repr(exc))
                if attempt == CONNECT_TRIES - 1:
                    raise
                self.sleep(BUSY_SECONDS)
        return contextlib.closing(GuardedTarget(connection))

    def shot(self, tag: str) -> None:
        self.sess.kbd.screenshot(str(self.out / f"{tag}.png"))

    def row24(self, screen) -> str:
        return screen.row(24).strip() if screen is not None else ""

    def service(self, answer: str | None, answered: int) -> tuple[str | None, str]:
        """Deal with whatever the game is asking; returns (what was done, row 24).

        The order is the point: a disk prompt is answered by `handle_prompt`
        and RETURN is never pressed on one, whatever else the row says.
        """
        screen = self.sess.screen()
        row = self.row24(screen)
        if screen is None:
            return None, row
        if self.sess.handle_prompt(screen):
            return "disk", row
        if self.sess.wanted_disk(screen) is not None or "INSERT" in screen.text():
            return None, row
        if MOVE_SUBBAR in row:
            return None, row
        if isinstance(answer, (list, tuple)):
            words = row.split()
            if self.answers_used < len(answer):
                if answer[self.answers_used] in words:
                    self.sess.select_bar(answer[self.answers_used], timeout=15)
                    self.answers_used += 1
                    self._unanswered = ("", 0)
                    return "answer", row
            if self.question_bar(words):
                # The bar just answered can still be up for a look or two; only a bar that stays is unanswerable.
                looks = self._unanswered[1] + 1 if self._unanswered[0] == row else 1
                self._unanswered = (row, looks)
                if looks >= UNANSWERED_LOOKS:
                    if self.answers_used >= len(answer):
                        raise DriverError(
                            f"the game asks a question ({row}) and all {len(answer)} --answer words are used")
                    self.log("question-unanswerable", words=words, wanted=answer[self.answers_used])
                    raise DriverError(
                        f"the game asks a question ({row}) and the next --answer word "
                        f"{answer[self.answers_used]} is not among {' '.join(words)}")
            else:
                self._unanswered = ("", 0)
        elif answer and answered < ANSWERS_PER_TRIP and answer in row.split():
            self.sess.select_bar(answer, timeout=15)
            return "answer", row
        if RETURN_MESSAGE in row:
            self.sess.kbd.key("Return", 0.2, 0.3)
            return "return", row
        return None, row

    @staticmethod
    def question_bar(words: list[str]) -> bool:
        """Whether row 24 is a menu bar of question words, not a message that happens to contain one."""
        return bool(words) and all(word in QUESTION_WORDS for word in words)

    def _retry_busy(self, tag: str, call: Callable[[object], tuple[bool, str, object]]):
        """`call` until it stops answering "cannot act right now" or the bar's "the game was busy"; bounded."""
        from automap.actionbar import FastTravelBar  # noqa: PLC0415
        bar_tries = 0
        for attempt in range(BUSY_TRIES + BAR_BUSY_TRIES):
            with self.target() as target:
                ok, message, value = call(target)
            if ok:
                return ok, message, value
            if message == FastTravelBar.STILL_BUSY:
                # The bar has already waited its own two seconds; the game is still printing.
                bar_tries += 1
                if bar_tries >= BAR_BUSY_TRIES:
                    return False, message, value
                self.log("busy", tag=tag, attempt=bar_tries, message=message)
                self.sleep(BAR_BUSY_SECONDS)
                continue
            if message != engine.FASTTRAVEL_BUSY:
                return ok, message, value
            self.log("busy", tag=tag, attempt=attempt, message=message)
            if attempt % 4 == 3:
                self.service(None, 0)
            self.sleep(BUSY_SECONDS)
            if attempt + 1 - bar_tries >= BUSY_TRIES:
                break
        return False, message, value

    def trip(self, dest_id: int, tag: str, leg: int = 0) -> dict:
        """One trip. Result: not_legal, not_applied, arrived, failed (with a reason) or timeout."""
        going_back = dest_id == BACK
        if going_back:
            if self.ft.back is None:
                raise DriverError("there is no earlier leg to go back from")
            dest_id = self.ft.back.area
        dest = engine.area_by_id(dest_id, self.game.title)
        if dest is None:
            raise DriverError(f"{dest_id} is not an area of {self.game.title}")
        summary = {"dest": dest_id, "result": "not_legal", "questions": 0,
                   "areas_seen": []}
        self.note_state(tag, "before")
        self.stage(leg, tag)
        self.hold_encounters(tag)

        def legal(target):
            v = (self.ft.back_verdict(target) if going_back
                 else self.ft.legality(target, dest))
            return bool(v), v.reason, v

        ok, reason, _ = self._retry_busy(tag, legal)
        self.log("legality", tag=tag, ok=ok, reason=reason)
        if not ok:
            self.shot(tag + "-blocked")
            return summary

        def apply(target):
            o = (self.ft.apply_back(target) if going_back
                 else self.ft.apply(target, area=dest))
            return o.ok, o.message, o

        try:
            with self.target() as target:
                before = reading(target, self.addresses)
                self.log("pre-apply", tag=tag, **before)
            self.see(summary, before["area6E1B"])
            ok, message, _ = self._retry_busy(tag, apply)
            self.log("apply", tag=tag, ok=ok, message=message)
            if not ok:
                summary["result"] = "not_applied"
                return summary
            with self.target() as target:
                square = engine.FastTravel.current_square(target, self.addresses)
            summary["square_after_apply"] = square
            self.log("square-after-apply", tag=tag, square=square)
            summary["result"] = self._poll(dest_id, tag, summary)
        finally:
            # A trip still pending when this leg ends for any reason is dropped.
            self.ft.cancel_pending()
        self.sleep(SETTLE_SECONDS)
        self.note_state(tag, "after")
        if self.step_after and summary["result"] == "arrived":
            row = self._clear_to_world_bar(self.answer)
            if row is not None:
                raise DriverError(f"leg {tag}: the world bar never came back after arrival ({row})")
            self.step(tag, dest_id)
        self.log("areas-seen", tag=tag, areas_seen=summary["areas_seen"])
        self.shot(tag + "-final")
        return summary

    def exit_squares(self, area: int) -> set[tuple[int, int, int]]:
        """The (x, y, facing) squares where the forward key leaves `area` (the entry-0 exit routes)."""
        return {tuple(route.square) for (frm, _to), route in fasttravel.EXIT_ROUTES.items()
                if frm == area and route.entry == 0}

    def on_exit_square(self, area: int | None) -> bool:
        """Whether the live (x, y, facing) is a square where the forward key leaves `area`."""
        live = self.sess.live_square()
        return (live is not None and len(live) > 2 and area is not None
                and tuple(live[:3]) in self.exit_squares(area))

    def step(self, tag: str, area: int | None = None) -> None:
        """Try up to `STEP_TRIES` moves on the arrived party and log the first that moves it.

        Indoors the live square is read, because `square()` there is the last
        save's and does not move; on the travel grid it is `square()` and the
        keys are compass digits. A party that never moves is logged, not failed;
        so is a monitor error, as `step-error`, and a party whose location cannot
        be read is not stepped at all. Standing on a square where the forward key leaves the area
        (`EXIT_ROUTES`), the party turns before it steps; a step that changes the area stops the run.
        An encounter menu on screen afterwards
        or the game in combat stops the run, because the next leg would apply a trip under it.
        """
        sess = self.sess
        try:
            indoors = sess.indoors()
            if indoors is None:
                self.log("step-skipped", tag=tag, where="unknown")
                return
            grid = indoors is False
            if grid:
                read = sess.square
                tries = [(key,) for key in OUTDOOR_STEP_KEYS]
            else:
                def read():
                    live = sess.live_square()
                    return None if live is None else tuple(live[:2])
                tries = [("I",)] + [(turn, "I") for turn in "JKM"]
                live = sess.live_square()
                if (live is not None and len(live) > 2 and area is not None
                        and tuple(live[:3]) in self.exit_squares(area)):
                    self.log("step-exit-square", tag=tag, square=list(live))
                    tries = tries[1:]
            with self.target() as target:
                area_before = reading(target, self.addresses)["area6E1B"]
            before = read()
            key, after, moved = None, before, False
            for keys in tries[:STEP_TRIES]:
                key = "".join(keys)
                for press in keys:
                    if not grid and press == "I" and self.on_exit_square(area):
                        # A turn can face the exit, and the forward key there leaves the area.
                        self.log("step-exit-square", tag=tag, keys=key)
                        break
                    if grid:
                        sess.walk_outdoors(press)
                    else:
                        sess.walk_one(press)
                after = read()
                moved = before is not None and after is not None and after != before
                if moved:
                    break
            with self.target() as target:
                area_after = reading(target, self.addresses)["area6E1B"]
            screen = sess.screen()
            sess.handle_prompt(screen)
            menu = self.encounter_menu(screen)
            encounter = menu or bool(sess.in_combat())
        except MonitorError as error:
            self.log("step-error", tag=tag, message=str(error))
            return
        self.log("step", tag=tag, key=key, before=before, after=after, moved=moved,
                 encounter=encounter)
        if area_after & 0x7F != area_before & 0x7F:
            self.log("left-area", tag=tag, was=area_before & 0x7F, now=area_after & 0x7F)
            raise DriverError(f"leg {tag}: the step left area {area_before & 0x7F} for {area_after & 0x7F}")
        if encounter:
            raise DriverError(f"leg {tag}: an encounter is under way after the step")

    @staticmethod
    def encounter_menu(screen) -> bool:
        """Whether row 24 is an encounter's opening menu (`COMBAT WAIT FLEE PARLAY`)."""
        if screen is None:
            return False
        from tools.c64 import session  # noqa: PLC0415
        words = screen.row(24).upper().split()
        return session.ENCOUNTER_FIGHT in words and "WAIT" in words

    @staticmethod
    def see(summary: dict, raw_area: int) -> None:
        """Append the area to `areas_seen` unless it is the one seen last."""
        area = raw_area & 0x7F
        seen = summary["areas_seen"]
        if not seen or seen[-1] != area:
            seen.append(area)

    def note_state(self, tag: str, when: str) -> None:
        """Log the party's names and every `--peek` range."""
        with self.target() as target:
            party = self.party_reader(target, self.game)
            names = [m.name for m in party.members] if party is not None else None
            self.log("party", tag=tag, when=when, names=names)
            for addr, length in self.peeks:
                self.log("peek", tag=tag, when=when, addr=f"${addr:04X}", length=length,
                         bytes=bytes(target.read(addr, length)).hex(" "))

    def hold_encounters(self, tag: str, now: dict | None = None) -> None:
        """Under `--no-encounters`, write the running area's gate through the session.

        It uses `Session.suppress_encounters`, the code `acceptance.py` uses,
        which picks the gate by the came-from byte. NOW is the poll's reading,
        or None at the start of a leg, when it is read here. An area with no
        gate in the table is logged as `encounters-live`.
        """
        if not self.no_encounters:
            return
        if now is None:
            with self.target() as target:
                now = reading(target, self.addresses)
        self._held_at = (now["script49F2"], now["area6E1B"] & 0x7F)
        self.sess.no_encounters = True
        self.sess.suppress_encounters()
        area = now["script49F2"] & 0x7F
        self.log("no_encounters", tag=tag, on=True, area=area)
        if (self.game.key, area) not in self._gate_table():
            self.log("encounters-live", tag=tag, area=area)

    def follow_encounters(self, tag: str, now: dict) -> None:
        """Apply the switch again once a hop has changed the came-from or cache-slot byte."""
        if self.no_encounters and (now["script49F2"],
                                   now["area6E1B"] & 0x7F) != self._held_at:
            self.hold_encounters(tag, now)

    def _gate_table(self) -> dict:
        if self.gates is None:
            from tools.c64 import session  # noqa: PLC0415
            self.gates = session.ENCOUNTER_GATES
        return self.gates

    def release_encounters(self) -> None:
        """Put back and verify every gate `hold_encounters` wrote, and log the rows."""
        if not self.no_encounters:
            return
        try:
            rows = self.sess.restore_encounter_gates()
        except Exception as exc:
            self.log("encounter-gates", verified=False, error=repr(exc))
            raise
        self.log("encounter-gates", verified=True, gates=rows)

    def stage(self, leg: int, tag: str) -> None:
        """Write the bytes `--stage` names for this leg, through the guard, and log each."""
        for at, addr, value in self.stages:
            if at != leg:
                continue
            with self.target() as target:
                was = _byte(target, addr)
                target.write(addr, bytes([value]))
                now = _byte(target, addr)
            self.log("stage", tag=tag, addr=f"${addr:04X}", was=was, value=value,
                     read_back=now)

    def _poll(self, dest_id: int, tag: str, summary: dict) -> str:
        started = self.clock()
        next_look = started
        looks = 0
        while self.clock() - started < self.budget:
            self.sleep(POLL_SECONDS)
            with self.target() as target:
                got = self.ft.continue_pending(target)
                if got is not None:
                    self.log("continue_pending", tag=tag, ok=got.ok, message=got.message,
                             pending=self.ft.pending is not None)
                    if not got.ok:
                        # The game has dropped the trip, so waiting out the budget finds nothing.
                        summary["reason"] = got.message
                        return "failed"
                now = reading(target, self.addresses)
            self.see(summary, now["area6E1B"])
            self.follow_encounters(tag, now)
            if self.clock() >= next_look:
                next_look = self.clock() + SCREEN_SECONDS
                done, row = self.service(self.answer, summary["questions"])
                if done == "answer":
                    summary["questions"] += 1
                if done:
                    self.shot(f"{tag}-{done}{summary['questions']}")
                self.log("poll", tag=tag, row24=row, did=done, **now)
                if looks % SHOT_EVERY == 0:
                    self.shot(f"{tag}-poll-{looks:03d}")
                looks += 1
            if now["area6E1B"] == dest_id and now["script49F2"] == dest_id:
                with self.target() as target:
                    other = engine.area_by_id(
                        other_area(dest_id, self.game.title), self.game.title)
                    verdict = self.ft.legality(target, other)
                self.log("arrival-check", tag=tag, legality=bool(verdict),
                         reason=verdict.reason, **now)
                if verdict:
                    return "arrived"
        self.log("timeout", tag=tag, budget=self.budget)
        return "timeout"

    def run(self, legs: list) -> list[dict]:
        """The legs in order, stopping at the first that does not arrive.

        The gates are put back however the legs end. When a leg raised and the
        restore fails too, the leg's error is raised with the restore's noted
        on it; the restore's failure is in the log either way.
        """
        try:
            for index, dest in enumerate(legs):
                self.results.append(self.trip(dest, f"t{index}-to{dest}", leg=index))
                if self.results[-1]["result"] != "arrived":
                    break
        except BaseException as leg_error:
            try:
                self.finish()
            except Exception as end_error:
                leg_error.add_note(f"Ending the run also failed: {end_error!r}")
            raise
        self.finish()
        return self.results

    def _clear_to_world_bar(self, answer) -> str | None:
        """Answer whatever the arrival drew until the world bar is up; None when it is, else the last row 24.

        An empty row 24 just after arrival is the moment before the game's question appears, so only
        the bar itself ends the wait.
        """
        row = ""
        for _ in range(SAVE_CLEAR_TRIES):
            row = self.row24(self.sess.screen())
            if "ENCAMP" in row or MOVE_SUBBAR in row:
                return None
            self.service(answer, 0)
            self.sleep(1.0)
        return row

    def save(self) -> str:
        """Save the game with ENCAMP > SAVE and keep the disk as `saved.D64`; call after `run` has put the gates back.

        The camp and save code is `Session.save_game`, which fails while an
        encounter gate is still written. The screen is first cleared back to the
        world bar (prompts answered), because a leg ends on whatever the arrival drew.
        """
        from tools.c64 import session as S  # noqa: PLC0415
        if self._clear_to_world_bar(self.answer) is not None:
            raise DriverError("the world bar never came back, so nothing was saved")
        if not self.sess.save_game():
            raise DriverError("ENCAMP > SAVE did not complete")
        kept = self.out / "saved.D64"
        try:
            S.copy_closed_disk(pathlib.Path(self.sess.save_disk), kept, attempts=30, backoff=1.0)
        except RuntimeError as exc:
            raise DriverError(str(exc)) from exc
        with self.target() as target:
            party = self.party_reader(target, self.game)
            names = [m.name for m in party.members] if party is not None else None
        self.log("saved", kept=str(kept), names=names)
        self.shot("saved")
        return str(kept)

    def finish(self) -> None:
        """Put the gates back, then drop any pending trip, each even if the other raises."""
        try:
            self.release_encounters()
        except BaseException as gates_error:
            try:
                self.ft.cancel_pending()
            except Exception as cancel_error:
                gates_error.add_note(
                    f"Dropping the pending trip also failed: {cancel_error!r}")
            raise
        self.ft.cancel_pending()


def stage_title(key: str, S, slot, disks: pathlib.Path, save: pathlib.Path) -> tuple[str, type]:
    """Copy the title's sides and the save into the slot; the image to boot and the session class."""
    if key == POOL_KEY:
        boot = S.stage_disks(slot, disks)
        S.stage_writable(save, pathlib.Path(slot.dir) / "SIDE0.D64")
        session_class = S.Session
    elif key == "curse-of-the-azure-bonds":
        from tools.curse_of_the_azure_bonds import curserun  # noqa: PLC0415
        boot = curserun.stage(slot, str(disks), str(save))
        session_class = curserun.CurseSession
    else:
        from tools.secret_of_the_silver_blades import ssbsession  # noqa: PLC0415
        boot = ssbsession.stage(slot, str(disks), str(save))
        session_class = ssbsession.silver_session_class()
    for image in pathlib.Path(slot.dir).glob("*.D64"):
        os.chmod(image, 0o644)
    return boot, session_class


def load_note(log: Log):
    """The `note` callback `curseload.load_saved_game` takes, writing each step as `load-<event>`.

    The loader names its step with an `event` keyword, and `Log.__call__` already
    takes the record's own `event` first, so the step is folded into that name.
    """
    return lambda event, **fields: log(f"load-{event}", **fields)


def bring_up(key: str, sess, disks: pathlib.Path, out: pathlib.Path, log: Log) -> None:
    """Boot, load the save and reach the world bar, the way each title's own driver does."""
    def shot(tag: str) -> None:
        sess.kbd.screenshot(str(out / f"{tag}.png"))

    if not sess.boot():
        raise DriverError("boot failed")
    if key == POOL_KEY:
        if not sess.load_save():
            raise DriverError("the game did not accept the save")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise DriverError("BEGIN ADVENTURING was not selected")
        if not sess.wait_for_world(timeout=240):
            raise DriverError("the world bar never came up")
    elif key == "curse-of-the-azure-bonds":
        from tools.curse_of_the_azure_bonds import curseload  # noqa: PLC0415
        outcome = curseload.load_saved_game(
            sess, note=load_note(log), shot=shot, wait=240)
        if outcome != "loaded":
            raise DriverError(f"the game did not accept the save: {outcome}")
        sess.patch_disk_prompt()
        addr = curseload.Addresses(sess.game, str(disks))
        if not curseload.enter_world(sess, addr, timeout=600):
            raise DriverError("the world was never reached")
        curseload.clear_messages(sess)
    else:
        from tools.secret_of_the_silver_blades import ssbsession  # noqa: PLC0415
        if not ssbsession.load_party(sess):
            raise DriverError("the game did not accept the save")
        addr = ssbsession.Addresses(sess.game, str(disks))
        if not ssbsession.enter_world(sess, addr, timeout=600):
            raise DriverError("the world was never reached")
        if "ENCAMP" not in ssbsession.clear_messages(sess):
            raise DriverError("the world bar never came up")
    sess.settle(4)


def main(argv: list[str] | None = None) -> int:
    from automap.paths import tool_disks  # noqa: PLC0415
    from tools.c64 import session as S  # noqa: PLC0415
    from tools.registry import scratch  # noqa: PLC0415
    from wish.backends import ViceTarget  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default=POOL_KEY, choices=TITLE_KEYS,
                        help="the game to travel in")
    parser.add_argument("--save", required=True, help="a save disk image of that game")
    parser.add_argument("--peek", action="append", default=[], metavar="ADDR[:LEN]",
                        help="hex bytes to log before and after each leg; repeatable")
    parser.add_argument("--stage", action="append", default=[], metavar="N:ADDR=VALUE",
                        help="write one byte before leg N (from 0); repeatable")
    parser.add_argument("--to", type=parse_leg, action="append", required=True,
                        help="a destination area id, or `back` (with --through-bar) for the way "
                             "back to where the last leg started; repeat for each further leg")
    parser.add_argument("--through-bar", action="store_true",
                        help="run each leg through the Fast Travel row the window builds "
                             "for the title, and log its buttons' state")
    parser.add_argument("--answer", action="append", metavar="WORD",
                        help="a bar word to select when the game asks, e.g. YES; given more than once "
                             "each word answers one question, in order, and a further question fails the run")
    parser.add_argument("--then-save", action="store_true",
                        help="after every leg arrived, make camp and save the game, and keep the "
                             "disk as saved.D64 in --out")
    parser.add_argument("--no-encounters", action="store_true",
                        help="hold the running area's random encounters off before each leg "
                             "(the gates are put back when the run ends)")
    parser.add_argument("--step-after", action="store_true",
                        help="after each leg arrives, try up to four moves and log a `step` event")
    parser.add_argument("--budget", type=float, default=BUDGET_SECONDS,
                        help="seconds each leg may take")
    parser.add_argument("--disks", help="the folder of the title's disk images")
    parser.add_argument("--slot", type=int, default=None,
                        help="a specific instance-pool slot; otherwise the next free one")
    parser.add_argument("--out", help="directory for the log and screenshots")
    args = parser.parse_args(argv)
    game = container_for(args.title)
    answer = args.answer[0] if args.answer and len(args.answer) == 1 else args.answer
    if BACK in args.to and not args.through_bar:
        parser.error(f"--to {BACK} needs --through-bar")
    for dest in args.to:
        if dest != BACK and engine.area_by_id(dest, game.title) is None:
            parser.error(f"--to {dest} is not an area of {game.title}")
    try:
        peeks = [parse_peek(text) for text in args.peek]
        stages = [parse_stage(text) for text in args.stage]
    except DriverError as exc:
        parser.error(str(exc))
    for leg, _, _ in stages:
        if leg >= len(args.to):
            parser.error(f"--stage names leg {leg} but there are {len(args.to)} legs")
    disks = pathlib.Path(args.disks) if args.disks else tool_disks(game)
    if disks is None:
        parser.error(f"no {game.title} disks; pass --disks or set POR_DISKS")
    os.environ.setdefault("POR_HEADLESS", "1")
    out = scratch.ensure(args.out or scratch.cache_dir(
        "fasttravel", time.strftime("%Y%m%d-%H%M%S")))
    slot = S.claim_slot(args.slot, "fasttravelrun")
    sess = None
    driver = None
    failure: Exception | None = None
    try:
        with open(out / "run.jsonl", "w") as stream:
            log = Log(stream, time.monotonic)
            try:
                boot, session_class = stage_title(
                    args.title, S, slot, disks, pathlib.Path(args.save))
                sess = session_class(boot, slot=slot)
                with sess.watching_dialogs() if args.title != POOL_KEY \
                        else contextlib.nullcontext():
                    bring_up(args.title, sess, disks, out, log)
                    action = engine.FastTravel(game)
                    if args.through_bar:
                        action = BarFastTravel(build_bar(game, disks), log)
                    driver = Driver(sess, lambda: ViceTarget(port=sess.mon_port),
                                    action, out, log, answer=answer,
                                    budget=args.budget, game=game, peeks=peeks,
                                    stages=stages, no_encounters=args.no_encounters,
                                    step_after=args.step_after)
                    driver.shot("0-start")
                    driver.run(args.to)
                    driver.shot("final")
                    if args.then_save and all(r["result"] == "arrived" for r in driver.results):
                        driver.save()
            except Exception as exc:
                # The failure is on record in the log before the slot goes away.
                log("error", error=repr(exc))
                failure = exc
    finally:
        for step in (lambda: sess and sess.close(), slot.teardown, slot.release):
            try:
                step()
            except Exception as failed:
                print(f"cleanup failed: {failed!r}", file=sys.stderr)
    results = driver.results if driver is not None else []
    for result in results:
        print(json.dumps(result))
    if isinstance(failure, DriverError):
        raise SystemExit(str(failure)) from failure
    if failure is not None:
        raise failure
    return 0 if len(results) == len(args.to) and all(
        r["result"] == "arrived" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
