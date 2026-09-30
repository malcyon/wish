"""Camp steps for an Amiga published route: view a member's sheet, lay on hands, and rest.

A published route (`route_silver_blades.published_title`) walks two squares,
camps and saves. `camp_title` splices the steps a `--camp` list names into it,
after the camp key and before the camp save, so the save that follows holds
what the steps did. The keys come from Silver Blades' `/Secret` (file offsets):

* **The camp bar** is `Save View Magic Rest Alt Fix Load Exit` (string
  `04D49D`); `V` shows the highlighted member's sheet and `R` opens the rest
  menu.
* **HEAL** is on the sheet while the gate at `024D8A` passes: class 3 or a
  paladin level, the game mode byte `-$2DA2(a4)` not 5, record `+0x143` clear
  and no node 140 (`find_affect` at `024DC0`). The heal routine (`024E30`)
  asks `Heal whom? ` through the party picker at `01B5CE`, whose bar is
  `Select Exit` and whose highlight starts on the party's first member
  (`-$2E96(a4)`). `S` or RETURN picks the highlighted member and `E` or ESC
  gives up; the routine then prints `%s feels better` or `%s is unaffected`
  and adds node 140 for 1440 minutes (`024ED8`).
* **The rest menu** is `Rest Days Hours Mins Add Subtract Exit` (`00369F`),
  read by the loop at `002F42`, which opens on the minutes field. `D`, `H`
  and `M` choose a field, `A` adds a day, an hour or five minutes, `S`
  subtracts the same, `R` or RETURN rests and `E` leaves. Subtracting from a
  field with nothing above it to borrow from zeroes the whole time
  (`002D1A`), which is how the preset the camp puts there is cleared: `D`,
  then `S` twice. The days field carries into a month at 30 (the scale table
  at `002ABE`), so a rest here is shorter than 30 days.

The party picker also moves its highlight on the game's internal codes
`$84`/`$85` (next) and `$87`/`$88` (previous). Which WinUAE key the camp
highlight answers to is measured, not read: `NEXT_MEMBER` and `PREV_MEMBER`.

The camp sheet is the party menu's sheet: the same frame, and a bar of
`ITEMS HEAL EXIT` for a paladin who may heal and `ITEMS EXIT` once he has.
"""

from __future__ import annotations

import dataclasses
import re

from tools.amiga.route import AmigaTitle
from tools.amiga.winuaesession import RouteError

VIEW = "V"
SHEET_EXIT = "E"
HEAL = "H"
HEAL_SELECT = "S"
CAMP_REST = "R"
REST_DAYS, REST_HOURS, REST_MINS = "D", "H", "M"
REST_ADD, REST_SUBTRACT, REST_GO = "A", "S", "R"
#: The keys that move the camp's highlight to the next and the previous member: measured,
#: NP2 takes it from the first line to the second and NP8 back.
NEXT_MEMBER, PREV_MEMBER = "NP2", "NP8"
REST_STEP = 5
REST_DAYS_MAX = 29
#: The most members a Gold Box party holds.
PARTY_MAX = 8
#: The party lines whose camp sheet has an identity rule, so the most `view N` can name.
SHEET_LINES = 2

CAMP = "camp"
SHEET = "camp_sheet"
#: The sheet whose bar offers HEAL, and the one whose bar does not.
SHEET_HEAL = "camp_sheet_heal"
SHEET_SPENT = "camp_sheet_spent"
HEAL_WHOM = "heal_whom"
REST_MENU = "rest_menu"
#: The camp save the published route presses next, which the camp steps go before.
CAMP_SAVE_STEP = ("S", "camp_save_picker", "key")

MIN_WAITS = {SHEET: 10.0, SHEET_HEAL: 10.0, SHEET_SPENT: 15.0, HEAL_WHOM: 10.0,
             REST_MENU: 5.0}
#: Seconds the camp bar may take to come back after a rest, beyond the game's own pace.
REST_LIMIT = 900.0
#: A rest this long or longer can land on the clock a run with no rest would show.
CLOCK_BLIND_REST = 24 * 60 - 120

_DURATION = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?")


def sheet_state(line: int) -> str:
    """The camp sheet state for party line `line`, counted from 1: each line has its own identity rule."""
    return SHEET if line == 1 else f"{SHEET}_{line}"


def is_sheet(state: str) -> bool:
    """Whether `state` is a camp sheet, whose screen records whether HEAL is offered."""
    return (state in (SHEET, SHEET_HEAL, SHEET_SPENT)
            or re.fullmatch(rf"{SHEET}_[2-9]", state) is not None)


def parse_duration(text: str) -> int:
    """Minutes in `1d2h30m`, `90m` or `8h`; a rest must be a positive multiple of five under 30 days."""
    m = _DURATION.fullmatch(text)
    if not text or not m or not any(m.groups()):
        raise RouteError(f"rest time {text!r} is not like 1d2h30m")
    days, hours, mins = (int(g or 0) for g in m.groups())
    minutes = days * 1440 + hours * 60 + mins
    if minutes <= 0:
        raise RouteError("a rest must be longer than no time at all")
    if minutes % REST_STEP:
        raise RouteError(f"the rest menu sets minutes in fives; {minutes} is not one")
    if minutes >= (REST_DAYS_MAX + 1) * 1440:
        raise RouteError(f"a rest here is shorter than {REST_DAYS_MAX + 1} days")
    return minutes


def rest_presses(minutes: int) -> tuple[int, int, int]:
    """(days, hours, five-minute presses) that set a rest of `minutes`."""
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    return days, hours, mins // REST_STEP


def parse_steps(text: str) -> tuple[str, ...]:
    """Read `view;heal;rest 1h` into normalised tokens, each checked by `validate_steps`."""
    tokens = tuple(" ".join(part.split()).lower() for part in text.split(";") if part.strip())
    validate_steps(tokens)
    return tokens


def validate_steps(tokens: tuple[str, ...], party_size: int = PARTY_MAX) -> None:
    """Refuse a camp step list the route cannot drive.

    `view` or `view N` shows the sheet of party line N (1 when left out; only
    lines 1 and 2 have an identity rule),
    `heal` has the first member lay on hands on himself, and `rest DURATION`
    rests that long. A `heal` whose sheet does not offer HEAL fails the run at
    that sheet, since its guard is the bar with the word on it.
    """
    if not tokens:
        raise RouteError("the camp step list is empty")
    healed = False
    for token in tokens:
        if token == "heal":
            if healed:
                raise RouteError("a second heal needs a rest before it: the sheet no longer "
                                 "offers HEAL")
            healed = True
        elif token.startswith("rest "):
            healed = False
    last_line = min(party_size, SHEET_LINES)
    for token in tokens:
        words = token.split()
        if words == ["view"] or words == ["heal"]:
            continue
        if words[0] == "view" and len(words) == 2 and words[1].isdigit():
            line = int(words[1])
            if not 1 <= line <= last_line:
                raise RouteError(f"{token!r}: the camp route can read sheets for lines 1 to "
                                 f"{last_line} only")
            continue
        if words[0] == "rest" and len(words) == 2:
            parse_duration(words[1])
            continue
        raise RouteError(f"camp step {token!r} is not view, view N, heal or rest DURATION")
    if rest_minutes(tokens) >= CLOCK_BLIND_REST:
        last_rest = max(i for i, t in enumerate(tokens) if t.startswith("rest "))
        if not any(t.split()[0] in ("view", "heal") for t in tokens[last_rest + 1:]):
            raise RouteError(
                f"rests totalling {CLOCK_BLIND_REST} minutes or more need a view or heal "
                f"after the last rest: the clock cannot prove such a rest, so the run needs "
                f"a sheet to show it")


def normalise(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """`view` as `view 1`, and a rest time as its minutes, so two spellings build one route."""
    out = []
    for token in tokens:
        words = token.split()
        if words == ["view"]:
            out.append("view 1")
        elif words[0] == "rest":
            out.append(f"rest {parse_duration(words[1])}m")
        else:
            out.append(token)
    return tuple(out)


def rest_minutes(tokens: tuple[str, ...]) -> int:
    """The minutes every `rest` in the list adds to the clock."""
    return sum(parse_duration(t.split()[1]) for t in tokens if t.startswith("rest "))


def steps_for(tokens: tuple[str, ...]) -> tuple[tuple[str, str, str], ...]:
    """The route steps, from the camp bar back to the camp bar, for each token in order."""
    steps: list[tuple[str, str, str]] = []
    for token in normalise(tokens):
        words = token.split()
        if words[0] == "view":
            line = int(words[1])
            steps += [(NEXT_MEMBER, CAMP, "key")] * (line - 1)
            steps += [(VIEW, sheet_state(line), "key"), (SHEET_EXIT, CAMP, "key")]
            steps += [(PREV_MEMBER, CAMP, "key")] * (line - 1)
        elif words[0] == "heal":
            steps += [(VIEW, SHEET_HEAL, "key"), (HEAL, HEAL_WHOM, "key"),
                      (HEAL_SELECT, SHEET_SPENT, "key"), (SHEET_EXIT, CAMP, "key")]
        else:
            days, hours, fives = rest_presses(parse_duration(words[1]))
            steps += [(CAMP_REST, REST_MENU, "key"), (REST_DAYS, REST_MENU, "key"),
                      (REST_SUBTRACT, REST_MENU, "key"), (REST_SUBTRACT, REST_MENU, "key")]
            for field, count in ((REST_DAYS, days), (REST_HOURS, hours), (REST_MINS, fives)):
                if count:
                    steps += [(field, REST_MENU, "key")]
                    steps += [(REST_ADD, REST_MENU, "key")] * count
            steps += [(REST_GO, CAMP, "key")]
    return tuple(steps)


def camp_title(title: AmigaTitle, tokens: tuple[str, ...], party_size: int = PARTY_MAX
               ) -> AmigaTitle:
    """`title` with the camp steps before its camp save.

    The camp states are not strict: a screen the guard map lacks is settled and
    marks the run as measuring, so one boot can capture them all, and the camp
    save's own strict picker still stops the run before any write. A kept slot
    letter the rest menu uses as a key (`A`, for a source loaded from slot D)
    becomes a plain key on the rest menu only.
    """
    validate_steps(tokens, party_size)
    route = list(title.route)
    try:
        at = route.index(CAMP_SAVE_STEP)
    except ValueError:
        raise RouteError("the route has no camp save to put the camp steps before") from None
    if at == 0 or route[at - 1][1] != CAMP:
        raise RouteError("the route's camp save does not follow the camp bar")
    added = steps_for(tokens)
    route[at:at] = added
    plain = tuple(dict.fromkeys(
        (*title.plain_keys,
         *((key, state) for key, state, _ in added if key in title.kept_letters))))
    limits = dict(title.wait_limits)
    if rest_minutes(tokens):
        limits[CAMP] = max(limits.get(CAMP, 0.0), REST_LIMIT)
    return dataclasses.replace(
        title, route=tuple(route), plain_keys=plain,
        min_waits={**title.min_waits, **MIN_WAITS}, wait_limits=limits)
