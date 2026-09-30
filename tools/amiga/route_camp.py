"""Camp steps for an Amiga route: view a member's sheet, lay on hands, and rest.

A published route (`route_silver_blades.published_title` or
`route_curse.published_title`) walks two squares, camps and saves, and
Pools of Darkness' accept route (`route_darkness.DARKNESS`) walks one.
`camp_title` splices the steps a `--camp` list names into it, after the camp
key and before the camp save, so the save that follows holds what the steps
did. The two titles use the same letters. The keys come from Silver Blades'
`/Secret` (file offsets):

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
`$84`/`$85` (next) and `$87`/`$88` (previous). The keypad reaches those codes
through the same translation in both executables (`/Secret` from `042AD0`,
`/Curse` from `03E2AC`, jump table `03E2FC`): keypad 0 to 9 give
`$89 $85 $84 $83 $86 $80 $82 $87 $88 $81`, and the cursor keys up and down
`$88` and `$84`. So NP2 (`$84`) moves the camp highlight to the next member
and NP8 (`$88`) back, as measured.

The camp sheet is the party menu's sheet: the same frame, and a bar of
`ITEMS HEAL EXIT` for a paladin who may heal and `ITEMS EXIT` once he has.

Curse of the Azure Bonds' `/Curse` (file offsets) differs only where noted:

* **The camp bar** is `Save View Magic Rest Alter Fix Exit` (`0455A5`). The
  camp highlight is `g3CFC` and the party's first member `g3CF8`; `0237CA`
  moves the highlight to the next member on the internal code `$85` only and to
  the previous one on `$87` only, wrapping at either end. Those are NP1 and NP7:
  NP2 and NP8 (`$84`, `$88`) leave the highlight where it is, as a boot showed.
* **The sheet bar** is built at `022016`-`0220C6` from `Items`, `Spells`,
  `Trade`, `Drop`, `Heal` (while the gate `0239F4` passes: class 3 or a
  paladin level, the game mode byte `g3D56` not 5, record `+0x19A` clear and
  no node 140), `Cure` and `Exit`; `H` runs the heal routine `023A9A` for the
  highlighted member.
* **HEAL's target** is chosen by the party picker `01BE98`, called with
  `Heal Whom? ` (`0240BE`). It starts on the first member (`g3CF8`), not on
  the healer; `$85` and `$87` move it, and the bar is `Select Exit`. `S` or
  RETURN keeps the highlighted member and `E` leaves with none. `027F44` only
  returns the member the picker left in `g337A`. The healer, not the target,
  gets node 140 for 1440 minutes (`023B54`), and the routine redraws his sheet
  (`0215BE`) without waiting for a key.
* **The rest menu** (`002328`) has the same letters and opens on the minutes
  field; its subtraction (`0020FE`) zeroes the whole time when nothing above the
  field can be borrowed, so `D S S` clears the preset here too.

`heal N` has the member on line N lay on hands on himself: the camp
highlight goes to his line, and the picker, which starts on the first member,
is moved the same way. Both wrap at either end in Curse, so the last line is
one press back from the first.

Pools of Darkness' `/Pools of Darkness` (file offsets) has the same rest menu
and the same kind of picker, with `Lay` where the other two say `Heal`:

* **The camp bar** is `View Magic Rest Alt Fix Load Save Exit` (`038290`).
* **The sheet bar** is `Items Spells Trade Deposit Drop Lay Cure Exit`
  (`038022`), so the key is `L`. The gate `023CFA` passes for class 3 or a
  paladin level, the game mode byte `g5B12` not 5, record `+0x5E` clear and
  no node 140 (`find_affect` at `023D38`).
* **The heal routine** `023DA0` asks `Heal whom? ` through the picker
  `01AF4A`, whose highlight starts on `g57A4`, the head of the party list
  (the picker's own "next" wraps to it), so on the first member. `RETURN` or
  the bar's first word, `Select`, keeps the highlighted member; `$84`/`$85`
  move it on and `$87`/`$88` back, wrapping (`01B084`). The healer, not the
  target, gets node 140 for 1440 minutes (`023E62`), and the routine redraws
  his sheet (`0209EC`).
* **The rest menu** `002D02` opens on the minutes field and reads the same
  seven words; its subtraction `002ABE` zeroes the whole time (`setmem` of
  14 bytes at `g57B2`) when nothing above the field can be borrowed, so
  `D S S` clears the preset here too.
* The keypad translation is the same code (`04A0A0`): keypad 0 to 9 give
  `$89 $85 $84 $83 $86 $80 $82 $87 $88 $81`. The camp highlight's own keys
  are not read, so only line 1, where neither the highlight nor the picker
  moves, is driven.
"""

from __future__ import annotations

import dataclasses
import re

from tools.amiga.route import AmigaTitle
from tools.amiga.winuaesession import RouteError

VIEW = "V"
SHEET_EXIT = "E"
#: The sheet's key for the heal routine, per title: `Heal` in Silver Blades and Curse, `Lay` in
#: Pools of Darkness.
HEAL_KEYS = {"ssb": "H", "curse": "H", "darkness": "L"}
HEAL_SELECT = "S"
CAMP_REST = "R"
REST_DAYS, REST_HOURS, REST_MINS = "D", "H", "M"
REST_ADD, REST_SUBTRACT, REST_GO = "A", "S", "R"
#: The keys that move the camp's highlight and HEAL's picker to the next and the previous
#: member, per title: Silver Blades takes `$84`/`$88` (NP2, NP8; measured), Curse only
#: `$85`/`$87` (NP1, NP7; read from `0237CA` and `01BF8E`). Pools of Darkness' picker takes
#: `$84`/`$88` (`01B084`); its camp highlight is not read, and no line it drives moves either.
MEMBER_KEYS = {"ssb": ("NP2", "NP8"), "curse": ("NP1", "NP7"), "darkness": ("NP2", "NP8")}
REST_STEP = 5
REST_DAYS_MAX = 29
#: The most members a Gold Box party holds.
PARTY_MAX = 8
#: The party lines whose camp sheet has an identity rule in the title's guard map, so the
#: lines `view N` can name.
SHEET_LINES = {"ssb": (1, 2), "curse": (1, 6), "darkness": (1,)}
#: The party line of the paladin whose HEAL sheets the title's guard map holds, so the line
#: `heal N` can name: the identity rule of `camp_sheet_heal` and `camp_sheet_spent` is his.
HEAL_LINES = {"ssb": (1,), "curse": (6,), "darkness": (1,)}
#: The titles whose camp highlight and HEAL picker are read to wrap from the first member to
#: the last and back (Curse `0237CA` and `01BF56`-`01BF8A`), so a later line may be reached
#: backwards.
WRAPS = frozenset({"curse"})

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


def sheet_lines(name: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """The party lines `view N` and `heal N` may name for title `name`."""
    try:
        return SHEET_LINES[name], HEAL_LINES[name]
    except KeyError:
        raise RouteError("camp steps are built for Silver Blades, Curse and Pools of Darkness "
                         "only") from None


def _lines_text(lines: tuple[int, ...]) -> str:
    if len(lines) == 1:
        return f"line {lines[0]}"
    if lines == tuple(range(lines[0], lines[-1] + 1)):
        return f"lines {lines[0]} to {lines[-1]}"
    return "lines " + ", ".join(map(str, lines[:-1])) + f" and {lines[-1]}"


def parse_steps(text: str, name: str = "ssb") -> tuple[str, ...]:
    """Read `view;heal;rest 1h` into tokens for title `name`, each checked by `validate_steps`."""
    tokens = tuple(" ".join(part.split()).lower() for part in text.split(";") if part.strip())
    validate_steps(tokens, name=name)
    return tokens


def _step_line(words: list[str]) -> int | None:
    """The party line a `view` or `heal` token names (1 when left out), or None for another token."""
    if words[0] not in ("view", "heal") or len(words) > 2:
        return None
    if len(words) == 1:
        return 1
    return int(words[1]) if words[1].isdigit() else None


def validate_steps(tokens: tuple[str, ...], party_size: int = PARTY_MAX,
                   name: str = "ssb") -> None:
    """Refuse a camp step list the route cannot drive for title `name`.

    `view` or `view N` shows the sheet of party line N (1 when left out; only
    the lines in `SHEET_LINES` have an identity rule), `heal` or `heal N` has
    the member on line N lay on hands on himself (1 when left out; only the
    line in `HEAL_LINES`, whose HEAL sheets have identity rules), and
    `rest DURATION` rests that long. A `heal` whose sheet does not offer HEAL
    fails the run at that sheet, since its guard is the bar with the word on it.
    """
    view_lines, heal_lines = sheet_lines(name)
    if not tokens:
        raise RouteError("the camp step list is empty")
    healed = False
    for token in tokens:
        if token.split()[0] == "heal":
            if healed:
                raise RouteError("a second heal needs a rest before it: the sheet no longer "
                                 "offers HEAL")
            healed = True
        elif token.startswith("rest "):
            healed = False
    for token in tokens:
        words = token.split()
        line = _step_line(words)
        if line is not None:
            lines = tuple(n for n in (view_lines if words[0] == "view" else heal_lines)
                          if n <= party_size)
            if line not in lines:
                doing = "read sheets" if words[0] == "view" else "lay on hands"
                raise RouteError(
                    f"{token!r}: the camp route can {doing} for {_lines_text(lines)} only"
                    if lines else f"{token!r}: the party has no line the camp route can "
                                  f"{doing} for")
            continue
        if words[0] == "rest" and len(words) == 2:
            parse_duration(words[1])
            continue
        raise RouteError(f"camp step {token!r} is not view, view N, heal, heal N or "
                         f"rest DURATION")
    if rest_minutes(tokens) >= CLOCK_BLIND_REST:
        last_rest = max(i for i, t in enumerate(tokens) if t.startswith("rest "))
        if not any(t.split()[0] in ("view", "heal") for t in tokens[last_rest + 1:]):
            raise RouteError(
                f"rests totalling {CLOCK_BLIND_REST} minutes or more need a view or heal "
                f"after the last rest: the clock cannot prove such a rest, so the run needs "
                f"a sheet to show it")


def normalise(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """`view` as `view 1`, `heal 1` as `heal`, and a rest time as its minutes, so two spellings build one route."""
    out = []
    for token in tokens:
        words = token.split()
        if words == ["view"]:
            out.append("view 1")
        elif words == ["heal", "1"]:
            out.append("heal")
        elif words[0] == "rest":
            out.append(f"rest {parse_duration(words[1])}m")
        else:
            out.append(token)
    return tuple(out)


def rest_minutes(tokens: tuple[str, ...]) -> int:
    """The minutes every `rest` in the list adds to the clock."""
    return sum(parse_duration(t.split()[1]) for t in tokens if t.startswith("rest "))


def _moves(line: int, name: str, party_size: int | None, state: str) -> tuple[list, list]:
    """The presses from the first member to party line `line` and back, in `state`.

    Where title `name` wraps (`WRAPS`) and `party_size` is known, the highlight
    goes the other way round, from the first member to the last, when that is shorter.
    """
    ahead, behind = MEMBER_KEYS[name]
    forward = line - 1
    if (name in WRAPS and party_size is not None and 1 <= line <= party_size
            and party_size - forward < forward):
        back = party_size - forward
        return [(behind, state, "key")] * back, [(ahead, state, "key")] * back
    return [(ahead, state, "key")] * forward, [(behind, state, "key")] * forward


def steps_for(tokens: tuple[str, ...], name: str = "ssb", party_size: int | None = None
              ) -> tuple[tuple[str, str, str], ...]:
    """The route steps for title `name`, from the camp bar back to the camp bar, for each token in order.

    `party_size` lets a title whose highlight wraps reach a later line backwards;
    without it the highlight moves forward only.
    """
    steps: list[tuple[str, str, str]] = []
    for token in normalise(tokens):
        words = token.split()
        if words[0] == "view":
            line = int(words[1])
            there, back = _moves(line, name, party_size, CAMP)
            steps += there
            steps += [(VIEW, sheet_state(line), "key"), (SHEET_EXIT, CAMP, "key")]
            steps += back
        elif words[0] == "heal":
            line = _step_line(words)
            there, back = _moves(line, name, party_size, CAMP)
            steps += there
            steps += [(VIEW, SHEET_HEAL, "key"), (HEAL_KEYS[name], HEAL_WHOM, "key")]
            # The picker starts on the first member, so it moves as far as the camp highlight did.
            steps += _moves(line, name, party_size, HEAL_WHOM)[0]
            steps += [(HEAL_SELECT, SHEET_SPENT, "key"), (SHEET_EXIT, CAMP, "key")]
            steps += back
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


def camp_title(title: AmigaTitle, tokens: tuple[str, ...], party_size: int = PARTY_MAX, *,
               name: str) -> AmigaTitle:
    """`title`, the published route of title `name`, with the camp steps before its camp save.

    The camp states are not strict: a screen the guard map lacks is settled and
    marks the run as measuring, so one boot can capture them all, and the camp
    save's own strict picker still stops the run before any write. A kept slot
    letter the rest menu uses as a key (`A`, for a source loaded from slot D)
    becomes a plain key on the rest menu only.
    """
    validate_steps(tokens, party_size, name=name)
    route = list(title.route)
    try:
        at = route.index(CAMP_SAVE_STEP)
    except ValueError:
        raise RouteError("the route has no camp save to put the camp steps before") from None
    if at == 0 or route[at - 1][1] != CAMP:
        raise RouteError("the route's camp save does not follow the camp bar")
    added = steps_for(tokens, name, party_size)
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
