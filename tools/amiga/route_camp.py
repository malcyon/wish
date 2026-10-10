"""Camp steps for an Amiga route: sheets, laying on hands, rests, effects lists and item lists.

A published route (`route_silver_blades.published_title` or
`route_curse.published_title`) walks two squares, camps and saves, and
Pools of Darkness' and Pool of Radiance's accept routes (`route_darkness.DARKNESS`,
`route_pool.POOL`) walk one.
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
* **The effects list** is the camp bar's `Magic` (`M`, dispatched at `0018DE`
  to the magic menu `000EA4`), whose bar is `Cast Memorize Scribe Display Rest
  Exit` (`0455CE`); `D` runs `000AFE`. That routine walks the whole party from
  `g3CF8` and, with no picker, builds one list: each member's name, then one
  line per node whose id its jump table (`000D2E`, 90 entries) names through
  the spell table, or ` <No Spell Effects>`, then a blank line. The list viewer
  `029410` is called with no bar words of its own, so its bar is `Exit`, and
  `E` returns to the magic menu, whose own `E` returns to the camp bar.

`memorize N` and `cast N` open line N's Memorize or Cast list and leave it again with
nothing chosen, after `P` presses of NP3 when written `memorize N P` or `cast N P`; they are
built for Pools of Darkness only. No guard rule is cut for the magic menu or either list, so a
run that reaches them settles each screen and measures.

`display` opens that list and leaves it again; it is built for Curse and Pool
of Radiance, the titles whose magic menu and list viewer have been read.

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
  `$89 $85 $84 $83 $86 $80 $82 $87 $88 $81`.
* **The camp highlight** is `g57A8`. The camp loop (`00258E`) hands every key
  not on the bar to `023AFC`, which moves it to the next member on `$84`/`$85`
  and to the previous one on `$87`/`$88`, wrapping at either end (NP2, NP1 and
  NP8, NP7). Camp entry does not reset it.
* **The sheet** adds `Items` only while the member has items (`021558`-`02156C`);
  `I` runs the item routine `021932`, whose list starts on the first item
  (`021942`) with a bar of `Rdy`, `Use`, `Trade`, `Drop`, `Halve`, `Join` and `Exit`
  (`Use` is added while the record is active, the area allows magic and the mode byte
  `g5B12` is 2, 3 or 4). `Rdy` (`021BBA`) runs the ready routine `022152`, and the list redraws with the same
  row highlighted. The keypad Down (NP2) moves the row highlight: the cursor Down
  was dropped on this list in a run under FS-UAE.
* **The magic menu** is the camp bar's `M`, with the bar `Cast Memorize Scribe Display Rest
  Exit` (`0382B7`); its `E` returns to the camp bar. Both lists below open for the camp
  highlight with no picker, and each one's `E` returns to the magic menu, as measured in a
  WinUAE boot.
* **`Memorize`** (`M`) shows `<NAME>'S SPELLS IN GRIMOIRE`: ten rows of spells under level
  headings, a scroll bar, a `MAGIC-USER :` row of the free slots per level below them, and the
  bar `CHOOSE SPELL: MEMORIZE EXIT` (`037FA4`), whose `M` would memorize the highlighted spell.
* **`Cast`** (`C`) shows `<NAME>'S SPELLS IN MEMORY`: seventeen rows, each spell once with
  its count as `NAME (N)` when more than one is memorized, and the bar `CHOOSE SPELL: CAST
  EXIT` (`037F9A`), whose `C` would cast the highlighted spell.
* **Both lists** move the highlight one row on NP2 and NP8. NP3 moves it to the window's
  bottom row and each further NP3 scrolls the list on by up to a window, and NP9 does the same
  upwards; at the end of the list NP3 leaves the screen as it was.

Pool of Radiance's `/program` (file offsets; one build on every disk-one image)
takes `items N`, which shows the item list of the member on line N, `rest
DURATION` and `display`, and no `view` or `heal`:

* **The camp bar** is `Save View Magic Rest Alter Exit` (`008DD1`), read by
  the camp loop at `007B2E` through the menu routine `0319FE`. That routine's
  key matcher (`0323F8`) returns a digit `1` to `9` with a flag set, RETURN,
  ESC as 0, or a letter on the bar. The keypad gives those digits: the raw-key
  table at `0347C1` turns keypad 1 to 9 into `1` to `9`.
* **The camp highlight** is the member pointer at hunk 32 + `0x0AEA`; the
  party list starts at hunk 32 + `0x0AEE` and each record's next pointer is at
  `+0x106`. On a flagged digit the camp loop calls `01CBD4`, where `1` moves
  to the next member and from the last wraps to the first, `7` moves to the
  previous one and from the first wraps to the last, and any other digit goes
  to the first member. So NP1 and NP7 move it, as in Curse. Camp entry
  (`007A9E`) does not reset it.
* **`V`** runs the sheet routine `01B47C` for the highlighted member. Its bar
  is built from `Items` (only while the record's item list at `+0xCA` is not
  empty), `Spells`, `Trade`, `Drop`, `Rename` and `Exit` (`01E712`-`01E738`),
  read with no highlight keys. `I` runs the item routine `01B7F4` and `E`
  returns to the camp bar. Only a sheet whose bar shows `Items` may take `I`,
  so the sheet `V` reaches is its own guarded state, whose rule is the bar
  with that word on it: a member with no items stops the run there.
* **The item routine** lists every node of the chain at `+0xCA` (next
  pointer `+0x2A`) under the heading `Items` (`01E7D4`) through the list
  viewer called at `01BADC`, with a bar of `Ready`, `Use`, `Trade`, `Drop`,
  `Halve`, `Join`, `Sell` and `Id` (`01E7A2`-`01E7D0`). It loops until the
  key is `E` or ESC (`01B82A`), and the sheet routine then redraws the sheet
  (`01B6E8`) and reads its bar again.
* **The camp bar's `R`** (`007BF8`) runs `00682E`, which presets the rest time
  to the longest any member needs to memorize (hours at hunk 32 + `0x1A20`,
  minutes in tens and ones at `+0x1A1E` and `+0x1A1C`), then the rest routine
  `005FB6`, whose menu `005B28` reads `Rest Days Hours Mins Add Sub Exit`
  (`008D4A`) and opens on the minutes field. `D`, `H` and `M` choose a field,
  `A` adds a day, an hour or five minutes, `S` subtracts the same, `R` or
  RETURN rests and `E` leaves. The subtraction `005880` zeroes the whole time
  (`setmem` of 14 bytes at `+0x1A1A`) when the field and every field above it
  hold nothing to borrow, so `D S S` clears the preset here too. Each five
  minutes of rest may be interrupted by a roll the area sets (`0060E8`), which
  prints `The Party is rudely interrupted!`.
* **The camp bar's `M`** (`007BE6`) runs the magic menu `0072C2`, whose bar is
  `Cast Memorize Scribe Display Rest Exit` (`008DFA`); `D` runs `006DC2`, which
  walks the whole party from hunk 32 + `0x0AEE` and builds one list: each
  member's name, then one line per node, or ` <No Spell Effects>`, then a blank
  line, shown under the heading `Display` (`0090F2`) through the list viewer
  with no bar words of its own. `E` leaves the magic menu.

The rest menu's `D` and the magic menu's `D` are Pool's after slot letter on its
own route, so a Pool camp run whose steps press `D` saves its after slot to
`route_pool.POOL_CAMP_AFTER` instead.

Silver Blades' `/Secret` (file offsets) takes `items N` and `join N I` beside
its other camp steps:

* **The sheet** offers `Items` only while the member's item list at `+0xFE` is
  not empty (`022B3C`), so, as in Pool of Radiance, the sheet `V` reaches before
  `I` is its own guarded state whose rule is the bar with that word on it.
* **The item routine** `022F12` lists the chain at `+0xFE` under `Ready Item`
  (`023152`) through the list viewer `02A938`. Its bar always carries `Join`
  (`023066`); `Halve` only below 16 items (`023040`), and `Sell` and `Id` only
  in a shop. The key switch at `023508` reads `D` to `U`, and `J` runs JOIN
  (`023B02`) on the highlighted item, which starts on the first one
  (`022F2E`), then redraws the list (`0234AC`). `E` or ESC returns to the
  sheet (`022F40`). Which key moves the highlight is not
  read: `join N I` presses `ITEM_NEXT` (NP2, the `$84` that moves the camp
  highlight and the picker) `I - 1` times, and every press waits for a state of
  its own, so an identity rule cut with row I highlighted shows where it went.
* **JOIN** answers on the message line through `01A088`, which prints, waits
  for the game speed's delay (`01D53A`, one of 0 to 5000 from the table at
  data `+0x235E`, in units not measured) and clears the line again (`0293AA`): so a message is on screen
  only for that delay. In order it answers `Bundles are limited to %d
  scrolls.` when the highlighted joined scroll holds 10 (`023B28`), `Too many
  Bundles!` when the party's joined scrolls (`023AC8`, every member from
  `g5168` along `+0x13A`) and this member's loose scrolls come to more than 120
  (`023BBA`), and `There are no similar items to join with.` when fewer than
  two scrolls can join (`023BCE`). An item that is not a scroll goes to the
  stacking branch, which answers `That cannot be joined with other items.` for
  one with no quantity (`023D80`). A JOIN on a scroll that works prints
  nothing: it folds every loose scroll and every joined scroll that still fits
  into the highlighted one, up to 10 (`023C64`-`023D72`).

`join N I` opens line N's item list, highlights row I, presses `J`, grabs the
screen at once for the message, then settles on the redrawn list, and leaves
through the sheet. `JOIN_MESSAGES` names the guard states the driver tests on
every grab of that first state.

`items N` reads no record byte: whether the rows on screen are the member's
own is the identity rule cut for the run's party, as for a sheet. Every camp
state an `items` or `join` step waits for is strict, the camp bar included, so
a screen its guard does not recognise stops the run before the next key.
"""

from __future__ import annotations

import dataclasses
import re

from automap.amiga import SNAPSHOT_NAME
from tools.amiga.route import AmigaTitle
from tools.amiga.winuaesession import RouteError

VIEW = "V"
SHEET_EXIT = "E"
ITEMS = "I"
#: The sheet's key for the heal routine, per title: `Heal` in Silver Blades and Curse, `Lay` in
#: Pools of Darkness.
HEAL_KEYS = {"ssb": "H", "curse": "H", "darkness": "L"}
HEAL_SELECT = "S"
CAMP_REST = "R"
CAMP_MAGIC, MAGIC_DISPLAY, DISPLAY_EXIT, MAGIC_EXIT = "M", "D", "E", "E"
REST_DAYS, REST_HOURS, REST_MINS = "D", "H", "M"
REST_ADD, REST_SUBTRACT, REST_GO = "A", "S", "R"
#: The keys that move the camp's highlight and HEAL's picker to the next and the previous
#: member, per title: Silver Blades takes `$84`/`$88` (NP2, NP8; measured), Curse only
#: `$85`/`$87` (NP1, NP7; read from `0237CA` and `01BF8E`). Pools of Darkness' picker takes
#: `$84`/`$88` (`01B084`) and so does its camp highlight (`023AFC`).
MEMBER_KEYS = {"ssb": ("NP2", "NP8"), "curse": ("NP1", "NP7"), "darkness": ("NP2", "NP8"),
               "pool": ("NP1", "NP7")}
REST_STEP = 5
REST_DAYS_MAX = 29
#: The most members a Gold Box party holds.
PARTY_MAX = 8
#: The party lines whose camp sheet the title's guard map recognises, so the lines `view N`
#: can name. Curse's sheet frame is the same for every member; whose sheet it is is checked
#: by the identity map cut for the run's own party; a sheet that map has no rule for is
#: skipped, and the run's summary then carries `identity_checked=False`, which drops the
#: `rest` pass flag and adds a "no identity rule checked" note.
SHEET_LINES = {"ssb": (1, 2, 3, 4, 5, 6), "curse": (1, 2, 3, 4, 5, 6), "darkness": (1, 2, 3, 4, 5, 6, 7)}
#: The party line of the paladin whose HEAL sheets the title's guard map holds, so the line
#: `heal N` can name: the identity rule of `camp_sheet_heal` and `camp_sheet_spent` is his.
HEAL_LINES = {"ssb": (1,), "curse": (6,), "darkness": (1,)}
#: The titles whose magic menu and effects list have been read, so `display` may name them.
DISPLAY_TITLES = frozenset({"curse", "pool"})
#: The titles whose camp highlight and HEAL picker are read to wrap from the first member to
#: the last and back (Curse `0237CA` and `01BF56`-`01BF8A`, Pools of Darkness' highlight
#: `023AFC`, Pool of Radiance's highlight `01CBD4`), so a later line may be reached backwards.
WRAPS = frozenset({"curse", "darkness", "pool"})
#: The titles whose sheet and item routine have been read, so `items N` may name them.
ITEMS_TITLES = frozenset({"darkness", "pool", "ssb"})
#: The titles whose item routine's `Rdy` has been read, so `ready N I` may name them.
READY_TITLES = frozenset({"darkness"})
READY = "R"
#: The titles whose item routine's `Use` on a scroll case has been read, so `use N I S|Y...`
#: may name them.
USE_TITLES = frozenset({"darkness"})
USE = "U"
#: The key that casts the highlighted spell of a case's spell list.
USE_CAST = "C"
#: What a case spell asks next: `S` picks the caster at the target picker, `Y` answers YES to the
#: combat-only prompt. Each spell used leaves the item list on the same row.
USE_ANSWERS = {"S": "camp_use_target", "Y": "camp_use_combat"}
USE_LIST = "camp_use_list"
#: The titles whose camp Memorize and Cast lists have been measured, so `memorize N [P]` and
#: `cast N [P]` may name them.
MAGIC_LIST_TITLES = frozenset({"darkness"})
#: The magic menu's keys for the two lists, and the key that leaves either list.
MAGIC_LIST_KEYS = {"memorize": "M", "cast": "C"}
LIST_EXIT = "E"
#: The key that pages a Memorize or Cast list: to the window's bottom row, then on by a window.
LIST_PAGE = "NP3"
#: The most NP3 presses one `memorize` or `cast` step takes.
LIST_PAGES_MAX = 20
#: The titles whose camp sheet steps, `view N` and `heal N`, are not built: Pool of Radiance's
#: sheet has no HEAL, and its guard map holds no camp sheet.
SHEETLESS = frozenset({"pool"})
#: The titles whose JOIN routine has been read, so `join N I` may name them.
JOIN_TITLES = frozenset({"ssb"})
JOIN = "J"
#: The key `join N I` presses to move the item list's highlight down one row (see above).
ITEM_NEXT = "NP2"
#: The most rows an item list holds: a member carries at most 16 items.
ITEM_ROWS = 16
#: The guard states the driver tests on every grab right after `J`, each the message line
#: showing one of JOIN's answers.
JOIN_MESSAGES = {
    "join_limited": "Bundles are limited to %d scrolls.",
    "join_too_many": "Too many Bundles!",
    "join_no_similar": "There are no similar items to join with.",
    "join_cannot": "That cannot be joined with other items.",
}

CAMP = "camp"
SHEET = "camp_sheet"
#: The sheet whose bar offers HEAL, and the one whose bar does not.
SHEET_HEAL = "camp_sheet_heal"
SHEET_SPENT = "camp_sheet_spent"
HEAL_WHOM = "heal_whom"
REST_MENU = "rest_menu"
#: The magic menu reached from the camp bar, and the effects list its `Display` shows.
MAGIC_MENU = "camp_magic"
DISPLAY = "camp_display"
#: The guard state for an effects list whose bar reads `NEXT EXIT`: the list has a further
#: page, which `display` does not turn to, so only the first page is read.
DISPLAY_MORE = "camp_display_more"
#: The item list a sheet's `Items` shows, for party line 1; `items_state` names the others.
ITEMS_LIST = "camp_items"
#: The sheet whose bar offers `Items`, for party line 1; `items_sheet_state` names the others.
ITEMS_SHEET = "camp_sheet_items"
#: The camp save the published route presses next, which the camp steps go before.
CAMP_SAVE_STEP = ("S", "camp_save_picker", "key")

#: The Memorize and Cast lists, for party line 1; `magic_list_state` names the others.
MAGIC_LISTS = {"memorize": "camp_memorize", "cast": "camp_cast"}

#: The screen right after `J`, for party line 1, grabbed at once for JOIN's message;
#: `join_state` names the others.
JOIN_LIST = "camp_join"
#: The item list redrawn after JOIN, for party line 1; `joined_state` names the others.
JOINED_LIST = "camp_joined"

MIN_WAITS = {SHEET: 10.0, SHEET_HEAL: 10.0, SHEET_SPENT: 15.0, HEAL_WHOM: 10.0,
             REST_MENU: 5.0, MAGIC_MENU: 5.0, DISPLAY: 10.0, ITEMS_LIST: 10.0,
             ITEMS_SHEET: 10.0,
             **{f"{state}_{n}": 10.0 for state in (ITEMS_LIST, ITEMS_SHEET)
                for n in range(2, PARTY_MAX + 1)}}
#: Seconds after the first grab past `J` before the redrawn list is settled on, so JOIN's
#: message delay has run out. How long the speed table's longest delay lasts is not measured.
JOINED_WAIT = 10.0
#: Seconds to wait for a highlight move to be drawn.
ROW_WAIT = 5.0
#: Seconds the camp bar may take to come back after a rest, beyond the game's own pace.
REST_LIMIT = 900.0
#: A rest this long or longer can land on the clock a run with no rest would show.
CLOCK_BLIND_REST = 24 * 60 - 120

_DURATION = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?")


def sheet_state(line: int) -> str:
    """The camp sheet state for party line `line`, counted from 1, with its own identity rule."""
    return SHEET if line == 1 else f"{SHEET}_{line}"


def items_sheet_state(line: int) -> str:
    """The sheet offering `Items` for party line `line`, counted from 1, with its own identity rule."""
    return ITEMS_SHEET if line == 1 else f"{ITEMS_SHEET}_{line}"


def items_state(line: int) -> str:
    """The camp item list state for party line `line`, counted from 1, with its own identity rule."""
    return ITEMS_LIST if line == 1 else f"{ITEMS_LIST}_{line}"


def items_row_state(line: int, row: int) -> str:
    """Party line `line`'s item list with row `row` highlighted, both counted from 1."""
    return items_state(line) if row == 1 else f"{items_state(line)}_row{row}"


def magic_list_state(kind: str, line: int, page: int = 0) -> str:
    """Party line `line`'s `memorize` or `cast` list after `page` presses of `LIST_PAGE`."""
    state = MAGIC_LISTS[kind] if line == 1 else f"{MAGIC_LISTS[kind]}_{line}"
    return state if page == 0 else f"{state}_page{page}"


def join_state(line: int) -> str:
    """The screen right after `J` on party line `line`'s item list, grabbed for the message."""
    return JOIN_LIST if line == 1 else f"{JOIN_LIST}_{line}"


def joined_state(line: int) -> str:
    """Party line `line`'s item list as JOIN redrew it, settled on after the message."""
    return JOINED_LIST if line == 1 else f"{JOINED_LIST}_{line}"


_LINE = "(?:_[2-9])?"
_ROW = "(?:_row(?:[2-9]|1[0-6]))?"


def is_items(state: str) -> bool:
    """Whether `state` is a camp item list, whose rows are read by its identity rule."""
    return re.fullmatch(rf"{ITEMS_LIST}{_LINE}{_ROW}", state) is not None


def is_magic_list(state: str) -> bool:
    """Whether `state` is a camp Memorize or Cast list, on any page."""
    names = "|".join(MAGIC_LISTS.values())
    return re.fullmatch(rf"(?:{names}){_LINE}(?:_page[1-9][0-9]?)?", state) is not None


def is_join(state: str) -> bool:
    """Whether `state` is the grab right after `J`, on which JOIN's message is looked for."""
    return re.fullmatch(rf"{JOIN_LIST}{_LINE}", state) is not None


def may_keep_screen(key: str, state: str) -> bool:
    """Whether a `key` step on `state` can legitimately leave the screen as it was.

    The rest menu's second `S` and repeated `D` land on a field already chosen; JOIN's first grab
    is taken at once and can come before any change; READY redraws the item list with the same
    row highlighted whatever it did; a page press at the end of a magic list moves nothing.
    """
    return (state == REST_MENU or is_join(state) or (key == READY and is_items(state))
            or (key == LIST_PAGE and is_magic_list(state)))


def is_joined(state: str) -> bool:
    """Whether `state` is the item list JOIN redrew, whose rows are read by its identity rule."""
    return re.fullmatch(rf"{JOINED_LIST}{_LINE}", state) is not None


def joined_after(state: str) -> str:
    """The redrawn list that follows join state `state`."""
    if not is_join(state):
        raise RouteError(f"{state!r} is not a join state")
    return JOINED_LIST + state[len(JOIN_LIST):]


def _min_wait(state: str) -> float:
    if is_join(state):
        return 0.0
    if is_joined(state):
        return JOINED_WAIT
    if (is_items(state) and "_row" in state) or (is_magic_list(state) and "_page" in state):
        return ROW_WAIT
    return MIN_WAITS.get(state, 10.0)


def is_sheet(state: str) -> bool:
    """Whether `state` is a camp sheet, whose screen records whether HEAL is offered."""
    return (state in (SHEET, SHEET_HEAL, SHEET_SPENT)
            or re.fullmatch(rf"{SHEET}_[2-9]", state) is not None)


def is_display(state: str) -> bool:
    """Whether `state` is the camp effects list, whose screen is recorded like a camp sheet."""
    return state == DISPLAY


def parse_duration(text: str) -> int:
    """Minutes in `1d2h30m`, `90m` or `8h`: a positive multiple of five under 30 days."""
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
    """The party lines `view N` and `heal N` may name for title `name`; none in `SHEETLESS`."""
    if name in SHEETLESS:
        return (), ()
    try:
        return SHEET_LINES[name], HEAL_LINES[name]
    except KeyError:
        raise RouteError("camp steps are built for Silver Blades, Curse, Pools of Darkness "
                         "and Pool of Radiance only") from None


def _lines_text(lines: tuple[int, ...]) -> str:
    if len(lines) == 1:
        return f"line {lines[0]}"
    if lines == tuple(range(lines[0], lines[-1] + 1)):
        return f"lines {lines[0]} to {lines[-1]}"
    return "lines " + ", ".join(map(str, lines[:-1])) + f" and {lines[-1]}"


def _normal_token(part: str) -> str:
    """One step in lower case, except a snapshot's name, whose case the user chose."""
    words = part.split()
    if words[0].lower() in MACHINE_VERBS:
        return " ".join([words[0].lower(), *words[1:]])
    token = " ".join(words).lower()
    # The answer letters of `use N I S|Y...` are upper case, the only form `_use_place` reads.
    return token[:-len(words[-1])] + words[-1].upper() if words[0].lower() == "use" and len(words) == 4 else token


def parse_steps(text: str, name: str = "ssb") -> tuple[str, ...]:
    """Read `view;heal;rest 1h` into tokens for title `name`, each checked by `validate_steps`."""
    tokens = tuple(_normal_token(part) for part in text.split(";") if part.strip())
    validate_steps(tokens, name=name)
    return tokens


def _step_line(words: list[str]) -> int | None:
    """The party line a `view`, `heal` or `items` token names (1 when left out), else None."""
    if words[0] not in ("view", "heal", "items") or len(words) > 2:
        return None
    if len(words) == 1:
        return 1
    return int(words[1]) if words[1].isdigit() else None


def _item_place(words: list[str]) -> tuple[int, int] | None:
    """The party line and item row a `join N I` or `ready N I` token names, else None."""
    if len(words) != 3 or not all(w.isdigit() for w in words[1:]):
        return None
    return int(words[1]), int(words[2])


def _use_place(words: list[str]) -> tuple[int, int, str] | None:
    """The party line, item row and answer letters a `use N I S|Y...` token names, else None."""
    if len(words) != 4 or words[0] != "use" or not all(w.isdigit() for w in words[1:3]):
        return None
    if not words[3] or any(c not in USE_ANSWERS for c in words[3]):
        return None
    return int(words[1]), int(words[2]), words[3]


def _magic_place(words: list[str]) -> tuple[int, int] | None:
    """The party line and page presses a `memorize N [P]` or `cast N [P]` token names, else None."""
    if words[0] not in MAGIC_LIST_KEYS or len(words) not in (2, 3):
        return None
    if not all(w.isdigit() for w in words[1:]):
        return None
    return int(words[1]), int(words[2]) if len(words) == 3 else 0


def _join_place(words: list[str]) -> tuple[int, int] | None:
    """The party line and item row a `join N I` token names, else None."""
    return _item_place(words) if words[0] == "join" else None


#: The steps that act on the machine and not on the game: `snapshot NAME` saves it, `restore NAME`
#: puts it back. They are not route steps, so a title's route never holds one.
MACHINE_VERBS = ("snapshot", "restore")


def is_machine_step(token: str) -> bool:
    """Whether `token` is a `snapshot NAME` or `restore NAME` step."""
    return token.split()[0] in MACHINE_VERBS if token.split() else False


def split_machine_steps(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[tuple[int, str, str], ...]]:
    """The game's camp steps, and where each machine step goes among them.

    Each mark is `(n, verb, name)`: it fires after the first `n` of the returned camp steps.
    """
    game: list[str] = []
    marks: list[tuple[int, str, str]] = []
    for token in tokens:
        if is_machine_step(token):
            verb, _, arg = token.partition(" ")
            marks.append((len(game), verb, arg))
        else:
            game.append(token)
    return tuple(game), tuple(marks)


def _validate_machine_steps(tokens: tuple[str, ...]) -> None:
    """Block a snapshot name the lane cannot keep, or a restore with no snapshot before it."""
    taken: set[str] = set()
    for token in tokens:
        words = token.split()
        if len(words) != 2 or not SNAPSHOT_NAME.fullmatch(words[1]):
            raise RouteError(f"camp step {token!r} is not {words[0]} NAME: a snapshot name is "
                             f"letters, digits, - and _, up to 32")
        if words[0] == "snapshot":
            taken.add(words[1].lower())
        elif words[1].lower() not in taken:
            raise RouteError(f"{token!r}: no snapshot {words[1]!r} was taken before it")


def validate_steps(tokens: tuple[str, ...], party_size: int = PARTY_MAX,
                   name: str = "ssb") -> None:
    """Block a camp step list the route cannot drive for title `name`.

    `snapshot NAME` and `restore NAME` save the machine and put it back; the other steps are
    judged without them.

    `view` or `view N` shows the sheet of party line N (1 when left out; only
    the lines in `SHEET_LINES` have a guard rule), `heal` or `heal N` has
    the member on line N lay on hands on himself (1 when left out; only the
    line in `HEAL_LINES`, whose HEAL sheets have identity rules), and
    `rest DURATION` rests that long, and `display` shows the effects list (only
    for a title in `DISPLAY_TITLES`). A `heal` whose sheet does not offer HEAL
    fails the run at that sheet, since its guard is the bar with the word on it.
    `items` or `items N` shows the item list of party line N (1 when left out;
    only for a title in `ITEMS_TITLES`). A title in `SHEETLESS` takes no `view`
    or `heal`, so its rests must total less than `CLOCK_BLIND_REST`, which the
    clock can prove. `join N I` presses JOIN on row I of line N's item list
    (only for a title in `JOIN_TITLES`), `row N I` pages line N's item list to row I and leaves it
    with no key pressed on the row (only for a title in `ITEMS_TITLES`), and `ready N I` presses READY on it (only for a
    title in `READY_TITLES`). `use N I ANSWERS` presses USE on row I and casts one case spell
    per letter of ANSWERS, `S` for a spell that asks whom and `Y` for a combat-only one (only for
    a title in `USE_TITLES`). The caller gives one answer per spell: the guards tell the list,
    the target picker and the prompt apart, not how many spells are left in the case, so the run's
    later `read` of the game-written save is what proves none was left unread. `memorize N` and
    `cast N` open line N's Memorize or Cast list, press NP3 P times when written `memorize N P`
    or `cast N P`, and leave it with nothing chosen (only for a title in `MAGIC_LIST_TITLES`).
    """
    view_lines, heal_lines = sheet_lines(name)
    _validate_machine_steps(tuple(t for t in tokens if is_machine_step(t)))
    tokens, _ = split_machine_steps(tokens)
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
    lines_held = min(party_size, PARTY_MAX)
    for token in tokens:
        words = token.split()
        if words[0] == "items":
            if name not in ITEMS_TITLES:
                raise RouteError(f"{token!r}: the item list is built for Pool of Radiance, "
                                 f"Pools of Darkness and Silver Blades only")
            line = _step_line(words)
            if line is None:
                raise RouteError(f"camp step {token!r} is not items or items N")
            if not 1 <= line <= lines_held:
                raise RouteError(f"{token!r}: the party has lines 1 to {lines_held} only")
            continue
        if words[0] == "row":
            if name not in ITEMS_TITLES:
                raise RouteError(f"{token!r}: the item list is built for Pool of Radiance, "
                                 f"Pools of Darkness and Silver Blades only")
            place = _item_place(words)
            if place is None:
                raise RouteError(f"camp step {token!r} is not row N I")
            line, row = place
            if not 1 <= line <= lines_held:
                raise RouteError(f"{token!r}: the party has lines 1 to {lines_held} only")
            if not 1 <= row <= ITEM_ROWS:
                raise RouteError(f"{token!r}: an item list has rows 1 to {ITEM_ROWS} only")
            continue
        if words[0] == "ready":
            if name not in READY_TITLES:
                raise RouteError(f"{token!r}: READY is built for Pools of Darkness only")
            place = _item_place(words)
            if place is None:
                raise RouteError(f"camp step {token!r} is not ready N I")
            line, row = place
            if not 1 <= line <= lines_held:
                raise RouteError(f"{token!r}: the party has lines 1 to {lines_held} only")
            if not 1 <= row <= ITEM_ROWS:
                raise RouteError(f"{token!r}: an item list has rows 1 to {ITEM_ROWS} only")
            continue
        if words[0] == "use":
            if name not in USE_TITLES:
                raise RouteError(f"{token!r}: USE is built for Pools of Darkness only")
            place = _use_place(words)
            if place is None:
                raise RouteError(f"camp step {token!r} is not use N I followed by one S or Y "
                                 f"per spell")
            line, row, _ = place
            if not 1 <= line <= lines_held:
                raise RouteError(f"{token!r}: the party has lines 1 to {lines_held} only")
            if not 1 <= row <= ITEM_ROWS:
                raise RouteError(f"{token!r}: an item list has rows 1 to {ITEM_ROWS} only")
            continue
        if words[0] in MAGIC_LIST_KEYS:
            if name not in MAGIC_LIST_TITLES:
                raise RouteError(f"{token!r}: the Memorize and Cast lists are built for Pools of "
                                 f"Darkness only")
            place = _magic_place(words)
            if place is None:
                raise RouteError(f"camp step {token!r} is not {words[0]} N or {words[0]} N P")
            line, pages = place
            if not 1 <= line <= lines_held:
                raise RouteError(f"{token!r}: the party has lines 1 to {lines_held} only")
            if pages > LIST_PAGES_MAX:
                raise RouteError(f"{token!r}: a list takes 0 to {LIST_PAGES_MAX} page presses")
            continue
        if words[0] == "join":
            if name not in JOIN_TITLES:
                raise RouteError(f"{token!r}: JOIN is built for Silver Blades only")
            place = _join_place(words)
            if place is None:
                raise RouteError(f"camp step {token!r} is not join N I")
            line, row = place
            if not 1 <= line <= lines_held:
                raise RouteError(f"{token!r}: the party has lines 1 to {lines_held} only")
            if not 1 <= row <= ITEM_ROWS:
                raise RouteError(f"{token!r}: an item list has rows 1 to {ITEM_ROWS} only")
            continue
        line = _step_line(words)
        if line is not None and name in SHEETLESS:
            raise RouteError(f"camp step {token!r}: the camp route reads no sheet on Pool of "
                             f"Radiance, which takes items N, rest DURATION and display")
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
        if words == ["display"]:
            if name not in DISPLAY_TITLES:
                raise RouteError("'display': the effects list is built for Curse and Pool of "
                                 "Radiance only")
            continue
        also = (", nor items N" if name in ITEMS_TITLES else "") + (
            " or join N I" if name in JOIN_TITLES else "") + (
            " or row N I" if name in ITEMS_TITLES else "") + (
            " or ready N I" if name in READY_TITLES else "") + (
            " or use N I S|Y" if name in USE_TITLES else "") + (
            " or memorize N [P] or cast N [P]" if name in MAGIC_LIST_TITLES else "")
        raise RouteError(f"camp step {token!r} is not view, view N, heal, heal N, "
                         f"rest DURATION or display{also}")
    if rest_minutes(tokens) >= CLOCK_BLIND_REST and name in SHEETLESS:
        raise RouteError(
            f"rests totalling {CLOCK_BLIND_REST} minutes or more need a sheet after the last "
            f"rest, and the camp route reads no sheet on Pool of Radiance")
    if rest_minutes(tokens) >= CLOCK_BLIND_REST:
        last_rest = max(i for i, t in enumerate(tokens) if t.startswith("rest "))
        if not any(t.split()[0] in ("view", "heal") for t in tokens[last_rest + 1:]):
            raise RouteError(
                f"rests totalling {CLOCK_BLIND_REST} minutes or more need a view or heal "
                f"after the last rest: the clock cannot prove such a rest, so the run needs "
                f"a sheet to show it")


def normalise(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Each step in one spelling, so two spellings build one route.

    `view` becomes `view 1`, `items` becomes `items 1`, `heal 1` becomes
    `heal`, a rest time becomes its minutes, and `memorize N 0` and `cast N 0` drop the zero;
    `join N I` and `ready N I` are already one spelling.
    """
    out = []
    for token in tokens:
        words = token.split()
        if words == ["view"]:
            out.append("view 1")
        elif words == ["items"]:
            out.append("items 1")
        elif words == ["heal", "1"]:
            out.append("heal")
        elif words[0] == "rest":
            out.append(f"rest {parse_duration(words[1])}m")
        elif words[0] in MAGIC_LIST_KEYS and words[2:] == ["0"]:
            out.append(" ".join(words[:2]))
        else:
            out.append(token)
    return tuple(out)


def rest_minutes(tokens: tuple[str, ...]) -> int:
    """The minutes the clock ends up advanced: every `rest`, less any a `restore` undid."""
    total, at_snapshot = 0, {}
    for token in tokens:
        words = token.split()
        if words[0] == "rest":
            total += parse_duration(words[1])
        elif words[0] == "snapshot" and len(words) == 2:
            at_snapshot[words[1].lower()] = total
        elif words[0] == "restore" and len(words) == 2:
            total = at_snapshot.get(words[1].lower(), total)
    return total


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
    """The route steps for title `name`, from the camp bar back to it, for each token in order.

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
        elif words[0] == "items":
            line = int(words[1])
            there, back = _moves(line, name, party_size, CAMP)
            steps += there
            steps += [(VIEW, items_sheet_state(line), "key"),
                      (ITEMS, items_state(line), "key"),
                      (SHEET_EXIT, items_sheet_state(line), "key"), (SHEET_EXIT, CAMP, "key")]
            steps += back
        elif words[0] == "join":
            line, row = int(words[1]), int(words[2])
            there, back = _moves(line, name, party_size, CAMP)
            steps += there
            steps += [(VIEW, items_sheet_state(line), "key"), (ITEMS, items_state(line), "key")]
            steps += [(ITEM_NEXT, items_row_state(line, n), "key") for n in range(2, row + 1)]
            # The driver settles on `joined_state(line)` after this grab, before `E` goes out.
            steps += [(JOIN, join_state(line), "key"),
                      (SHEET_EXIT, items_sheet_state(line), "key"), (SHEET_EXIT, CAMP, "key")]
            steps += back
        elif words[0] == "ready":
            line, row = int(words[1]), int(words[2])
            there, back = _moves(line, name, party_size, CAMP)
            steps += there
            steps += [(VIEW, items_sheet_state(line), "key"), (ITEMS, items_state(line), "key")]
            steps += [(ITEM_NEXT, items_row_state(line, n), "key") for n in range(2, row + 1)]
            # The list redraws with the same row highlighted, whatever READY did to the item.
            steps += [(READY, items_row_state(line, row), "key"),
                      (SHEET_EXIT, items_sheet_state(line), "key"), (SHEET_EXIT, CAMP, "key")]
            steps += back
        elif words[0] == "row":
            line, row = int(words[1]), int(words[2])
            there, back = _moves(line, name, party_size, CAMP)
            steps += there
            steps += [(VIEW, items_sheet_state(line), "key"), (ITEMS, items_state(line), "key")]
            steps += [(ITEM_NEXT, items_row_state(line, n), "key") for n in range(2, row + 1)]
            steps += [(SHEET_EXIT, items_sheet_state(line), "key"), (SHEET_EXIT, CAMP, "key")]
            steps += back
        elif words[0] == "use":
            line, row = int(words[1]), int(words[2])
            there, back = _moves(line, name, party_size, CAMP)
            steps += there
            steps += [(VIEW, items_sheet_state(line), "key"), (ITEMS, items_state(line), "key")]
            steps += [(ITEM_NEXT, items_row_state(line, n), "key") for n in range(2, row + 1)]
            for answer in words[3]:
                # The list comes back with the same row highlighted, the count redrawn.
                steps += [(USE, USE_LIST, "key"), (USE_CAST, USE_ANSWERS[answer], "key"),
                          (answer, items_row_state(line, row), "key")]
            steps += [(SHEET_EXIT, items_sheet_state(line), "key"), (SHEET_EXIT, CAMP, "key")]
            steps += back
        elif words[0] in MAGIC_LIST_KEYS:
            line, pages = _magic_place(words)
            there, back = _moves(line, name, party_size, CAMP)
            steps += there
            # The list opens for the camp highlight; its own M or C would memorize or cast, so
            # only NP3 and E are pressed on it.
            steps += [(CAMP_MAGIC, MAGIC_MENU, "key"),
                      (MAGIC_LIST_KEYS[words[0]], magic_list_state(words[0], line), "key")]
            steps += [(LIST_PAGE, magic_list_state(words[0], line, n), "key")
                      for n in range(1, pages + 1)]
            steps += [(LIST_EXIT, MAGIC_MENU, "key"), (MAGIC_EXIT, CAMP, "key")]
            steps += back
        elif words[0] == "display":
            # The list is left from its first page; a further page is recorded, not read.
            steps += [(CAMP_MAGIC, MAGIC_MENU, "key"), (MAGIC_DISPLAY, DISPLAY, "key"),
                      (DISPLAY_EXIT, MAGIC_MENU, "key"), (MAGIC_EXIT, CAMP, "key")]
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


#: The steps whose keys only move a highlight or open and leave a screen, so a measure run may
#: press them on a screen no rule recognises.
NAVIGATION_VERBS = frozenset({"view", "items", "row", "memorize", "cast", "display"})


def measure_blockers(tokens: tuple[str, ...]) -> list[str]:
    """The game steps among `tokens` that change game state, which a measure run cannot drive."""
    game, _ = split_machine_steps(normalise(tokens))
    return [t for t in game if t.split()[0] not in NAVIGATION_VERBS]


def camp_title(title: AmigaTitle, tokens: tuple[str, ...], party_size: int = PARTY_MAX, *,
               name: str) -> AmigaTitle:
    """`title`, the published route of title `name`, with the camp steps before its camp save.

    The camp states are not strict: a screen the guard map lacks is settled and
    marks the run as measuring, so one boot can capture them all, and the camp
    save's own strict picker still stops the run before any write. The states of
    an `items`, `join`, `ready` or `use` step are strict instead, the camp bar and each list JOIN
    redraws included, so every key of those steps goes out on a screen its guard
    recognised. A measure run settles on a screen no rule matches only in the states of the
    steps in `NAVIGATION_VERBS`, which press keys that change no game state; `measure_blockers`
    names the steps a measure run cannot drive, and the route's measure copy still holds them. A kept slot letter the rest menu uses as a key (`A`, for a source
    loaded from slot D) becomes a simple key on the rest menu only.
    """
    validate_steps(tokens, party_size, name=name)
    tokens, _ = split_machine_steps(tokens)
    route = list(title.route)
    try:
        at = route.index(CAMP_SAVE_STEP)
    except ValueError:
        raise RouteError("the route has no camp save to put the camp steps before") from None
    if at == 0 or route[at - 1][1] != CAMP:
        raise RouteError("the route's camp save does not follow the camp bar")
    added = steps_for(tokens, name, party_size)
    route[at:at] = added
    measured = list(title.measure_route)
    # A measure run drives the same camp steps, so its crops of those screens can be cut. A
    # measure copy that ends before the camp save keeps no camp steps; `run_recon` blocks a
    # measure run that was asked for them.
    if CAMP_SAVE_STEP in measured:
        measured[measured.index(CAMP_SAVE_STEP):measured.index(CAMP_SAVE_STEP)] = added
    loose_tokens = tuple(t for t in normalise(tokens) if t.split()[0] in NAVIGATION_VERBS)
    loose = {state for _, state, _ in steps_for(loose_tokens, name, party_size)}
    simple = tuple(dict.fromkeys(
        (*title.plain_keys,
         *((key, state) for key, state, _ in added if key in title.kept_letters))))
    limits = dict(title.wait_limits)
    if rest_minutes(tokens):
        limits[CAMP] = max(limits.get(CAMP, 0.0), REST_LIMIT)
    item_tokens = tuple(t for t in normalise(tokens)
                        if t.split()[0] in ("items", "row", "join", "ready", "use"))
    item_states = {state for _, state, _ in steps_for(item_tokens, name, party_size)}
    item_states |= {joined_after(state) for state in item_states if is_join(state)}
    strict = title.strict | ({CAMP} | item_states if item_states else set())
    waits = {state: _min_wait(state) for state in item_states}
    return dataclasses.replace(
        title, route=tuple(route), measure_route=tuple(measured), plain_keys=simple,
        strict=frozenset(strict),
        measure_loose=title.measure_loose | loose,
        min_waits={**title.min_waits, **MIN_WAITS, **waits}, wait_limits=limits)


def camp_marks(title: AmigaTitle, tokens: tuple[str, ...], party_size: int = PARTY_MAX, *,
               name: str) -> dict[int, tuple[tuple[str, str], ...]]:
    """Where the machine steps among `tokens` fire in the route `camp_title` built.

    `title` is that result. The key is a route index and the machine steps fire before that
    step runs; an index equal to the route's length fires after the last one.
    """
    validate_steps(tokens, party_size, name=name)
    game, marks = split_machine_steps(tokens)
    at = list(title.route).index(CAMP_SAVE_STEP) - len(steps_for(game, name, party_size))
    out: dict[int, list[tuple[str, str]]] = {}
    for after, verb, arg in marks:
        index = at + len(steps_for(game[:after], name, party_size))
        out.setdefault(index, []).append((verb, arg))
    return {index: tuple(pairs) for index, pairs in out.items()}
