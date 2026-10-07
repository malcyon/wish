#!/usr/bin/env python3
"""Load a Wish-written DOS save in the running game, act, and read the engine's resave.

The DOS driver of `docs/235-destination-game-acceptance-runs.md` (D1), for
DOS Pool of Radiance, Curse of the Azure Bonds, Secret of the Silver Blades
and Pools of Darkness.  It stages a whole save this project wrote the way
`dossheetread.install_whole` does, boots DOSBox headless and silent on a
pooled slot, runs a step list, and decodes what the engine wrote back:

    tools/dos/acceptance.py --title pool --save DIR --slot A \\
        --steps load camp 'rest 5m' 'save D' read \\
        --expect BRUTUS:1:42:1 --issue 661 --run bless

    tools/dos/acceptance.py --title curse --fixture-row 3F=01:00:2F:05 \\
        --steps load begin camp 'rest 5m' 'save D' read \\
        --expect PHILIPPE:1:42:5 --issue 661 --run curse-bless

`--fixture-row SLOT=ID:OWNER:DURATION:MAGNITUDE` (hex, repeatable) replaces
`--save`: a C64 party gets those effect rows and is converted by Save As DOS
(`editor.saveplan.prepare_save_as` and `publish`) into `<out>/source/` before
the boot, with the SHA, the file list, the converted nodes and the report's
`dropped` and `losses` in the log.  The party is the committed fixture for
Pool of Radiance and the title's engine-written specimen under
`$WISH_SPECIMENS/por-c64/` for the other two (`C64_BASES`), or `--c64-save`.
With no `--steps` only that conversion runs.

    tools/dos/acceptance.py --title darkness \\
        --amiga-disk 'Pools Of Darkness.zip!Pools of Darkness3.adf' \\
        --amiga-slot SavGamA.pty \\
        --steps load begin camp 'sheet 4' 'items 4' 'save D' read \\
        --issue 650 --run scrolls

`--amiga-slot` (with `--amiga-disk`, a path to an `.adf` or the end of a
`tools/amiga/amigasaves.py` label) replaces `--save` for Pools of Darkness:
the Amiga saved game is converted by the Convert window's own route,
`editor.convert.PodAmigaToDos` with `WISH_EXPERIMENTAL_POD_CONVERT` set for
this process, into `<out>/source/` as DOS slot A, with the disk's label and
SHA-256, the report's `dropped` and `losses` and every warning the
conversion logged.

`--convert PATH [--convert-slot L]` replaces `--save` for pool, curse and ssb:
a C64 `.D64` or Amiga `.adf` at `PATH`, whatever title or port it is (a C64
save, or an Amiga Curse, Silver Blades or Pool of Radiance one), is read at
slot `L` (default `A`) through `editor.convert.Source.detect` and converted by
Save As DOS the same way `--fixture-row` converts a staged C64 party, blocking
a source whose title does not match `--title`:

    tools/dos/acceptance.py --title ssb \\
        --convert $WISH_SPECIMENS/ssb-c64/WISH-SPEC-ssb-512-amigatoc64-walk-resave.D64 \\
        --steps load begin 'walk 1' camp 'save D' read --issue 639 --run ssb-share

| step | what it does |
|---|---|
| `load` | title screens, `LOAD SAVED GAME`, the `--slot` letter; Pool lands on the map, the other three on the party menu.  Pools of Darkness asks `LOAD FROM WHERE? POOLS SECRET EXIT` first and gets `P`.  Pool presses Return past each `PRESS <ENTER>/<RETURN> TO CONTINUE` bar first, when the loaded save is on an event square, so that screen is never recorded as the map (#701); a party that has not taken Rolf's opening tour meets eight (PROBABLE: one boot of one party), and the run stops at `POOL_LOAD_CONTINUE_ROUNDS` (#631).  Pool's map is believed only on a measured bar of `POOL_MAP_BARS`; a save made at the party menu loads back onto it, which is read as text with the title's font and left for `begin`, and any other screen stops the run naming its bar's words (#797) |
| `begin` | Curse, Silver Blades and Pools of Darkness, and Pool straight after a `load` onto its party menu: `BEGIN ADVENTURING`, through Silver Blades' intro bars, Pools of Darkness' journal question and `YES NO` bars (below), and Pool's continue screens, to the map; Pool's party menu must read `BEGIN ADVENTURING` before `b` goes out, and Pool's and Pools of Darkness' map is believed only by a measured bar |
| `camp` guard | Pool presses `ENCAMP` only on a measured map bar of `POOL_MAP_BARS`, and no title presses it on the party menu, where `e` is EXIT TO DOS |
| `camp` | `ENCAMP`; records the camp bar by `bar_signature`.  After `vault`, Pools of Darkness presses `REST` on Elminster's menu instead, which opens the camp loop, and requires a bar reading `SAVE ... EXIT` |
| `vault` | Pools of Darkness, straight after `begin`, which then takes Elminster's menu in Limbo (area 18) as its end: `STORAGE`, the vault's bar read as text, `TAKE` (and `ITEMS` at `TAKE: MONEY ITEMS EXIT`) when offered, every page of the stored items read as text with `NEXT`, `EXIT` back to the vault and `EXIT` to Elminster's menu; records the rows and the `TMPVAULT.DAT` leaving wrote.  The run fails unless every page reads the names that file caches, in order and to the last, and the file and the last saved slot's vault hold the installed items and coins (`vault_verdict`).  Blocked before the boot unless the installed save names area 18 in variable `$16` and `$A2` is not 1 |
| `deposit 5 2` | Pools of Darkness, after `vault`, at Elminster's menu: `STORAGE`, roster line 5 highlighted, `ITEMS`, row 2 highlighted and `D` (`DEPOSIT`, no question), `EXIT` twice, then the vault read back as `vault` reads it.  Stops before `D` on a readied row or a list's last row, and fails unless the list lost that row, `TMPVAULT.DAT` gained it as its last record with the coins unchanged, the readback lists every record, and the last saved slot's vault holds what the deposit left (`deposit_verdict`) |
| `leave` | Curse and Silver Blades, in camp: the camp bar's `Exit` (`CAMP_EXIT`), believed when the map bar is back, so a `fight` can follow a camp `save` in the same boot.  Curse's has left camp in one boot; Silver Blades' is read from its key set only and is not yet verified live |
| `sheet N`, `items N` | Curse, Silver Blades and Pools of Darkness (`items` Pools of Darkness only; Pool's is the next row), in camp: roster line N (from 1) highlighted (`End` in Curse, `Down` in the other two), `VIEW`, the sheet's name checked against line N's, the bar read for `heal_offered` and `cure_offered` (`sheet_offers`), and for `items` its `ITEMS` list page by page with `NEXT`; back to camp |
| `heal N` | the same three, in camp: line N's sheet, `HEAL` (`LAY` in Pools of Darkness), `SELECT` at `HEAL WHOM?` on the member it opens on, and the sheet required back without the word; back to camp |
| `cure N` | Curse, in camp: line N's sheet, `CURE`, `SELECT` at `CURE WHOM?`, `YES` to `CURE ANYWAY` if asked, the sheet required back; back to camp |
| `change N CLASS` | Curse, at the party menu with the hall open (`--hall`): line N, `HUMAN CHANGE CLASSES`, the class list's row for CLASS as the engine's own test orders them (`class_choices`), checked against the rows the highlight reaches, `SELECT`, back to the party menu |
| `halve N I`, `join N I` | Pools of Darkness, in camp: member N's `ITEMS`, the highlight moved to row I (from 1, at most 18) with `Down`, `h` or `j` pressed once, and the rows counted before and after; `halve` must add a row and keep the highlight or the run stops before any save, `join` only records; back to camp.  Silver Blades' `join N I`, at the party menu before `begin`: `VIEW CHARACTER`, line N at `PICK CHARACTER` with `Down`, `SELECT`, the sheet checked by its name, `ITEMS`, row I highlighted, `j` once, the rows counted and read as text before and after, and `Exit` back to the party menu; it only records |
| `trade N I M` | Silver Blades, at the party menu before `begin`: line N's `ITEMS` as `join` opens it, row I highlighted, `TRADE`, line M picked at `TRADE WITH WHOM?` with `Down` and `SELECT`, and the list required back; N's rows and M's name are recorded, and nothing checks that the item moved |
| `memorize N` | Pools of Darkness, in camp: roster line N highlighted with `Down`, `MAGIC`, `MEMORIZE`; the grimoire's title checked against line N's name; every page shot and its eleven rows read, turning with `NEXT` until the bar stops offering it; `lists_126` says whether a page draws `MONSTER SUMMONING`, spell id 126; `EXIT` to the Magic bar and to camp.  Nothing is memorized |
| `add NAME` | Pool, first or after another `add`, with no `load`: the party menu (title screens pressed past as `load` does), `ADD CHARACTER TO PARTY` (`a`), the highlight walked with `End` onto the row reading NAME (several words, as `CHARLIST.TXT` lists it), `Return`, believed only when the row redraws as `* NAME`, then `EXIT` (`e`), and NAME required on the party menu's roster.  Each screen is read as text with the title's font before its key and an unknown one stops the run with nothing more pressed; a list longer than one screen is not paged.  Before the boot the save folder is emptied and every exported character of the title's own `SAVE` folder (`.CHA`, `.ITM`, `.SPC`) and its `CHARLIST.TXT` are staged into it, and a NAME that `CHARLIST.TXT` does not list is blocked.  A run that begins with `add` takes no `--save`, and then no staging option, `--expect` or `read`; `view N` and `save X` may follow |
| `view N` | At the party menu, before `begin`.  Pool, after `add`: `End` to line N, `VIEW CHARACTER` (`v`), the sheet read as text (its name row must read line N's name, `encumbrance` is the figure it draws), `ITEMS` when the sheet offers it, the list's title `<NAME>'S ITEMS` checked and each row read as `ready`, `marked` and `name`, and `Escape` twice back.  Pools of Darkness and Silver Blades: `VIEW CHARACTER`, line N at `PICK CHARACTER` with `Down`, `SELECT`.  Curse: `End` to line N on the party menu, then `v`.  The sheet is checked by its name as above (never by a bar); a sheet that draws `(NPC)` two cells after the name (a control byte above 0x7F) is the member's too, read with the title's font, and the result's `header` names it.  `EXIT` returns to the party menu, and only Pools of Darkness pages `ITEMS` |
| `items N` | Pool, in camp: member N's `ITEMS` list, first screen only, from `End` to the line, `v`, `i`, and `Escape` twice back to camp; blocks a sheet with no `ITEMS`; records `rows` and `marked`, the rows (from 1) drawn with the Detect Magic `* ` |
| `sheet N` | Pool: member N's sheet from the map (`End` to the line, `v`, `Escape`); the sheet is taken on a measured `POOL_SHEET_BARS` bar or, for any class's bar, on its words read as `POOL_SHEET_BAR_TEXT`; needs either measured map bar of `POOL_MAP_BARS` back |
| `display` | Pool, Curse and Silver Blades, in camp: `MAGIC`, `DISPLAY`, every page of the list of spells in effect read as text with the title's own font (`load_font`), turning with `n` while the bar is ` NEXT EXIT`; `members` is each member's name and the effect names under it, and the list must name every member (Pool's page also six name rows); `Return` or `e` back to the Magic bar (`DISPLAY_LEAVE`) and `e` to camp |
| `cast N SPELL [T]` | Pool, Curse and Silver Blades, in camp: roster line N highlighted (`End` in Pool and Curse, `Down` in Silver Blades), `MAGIC`, `CAST`; the caster's spell list read as text with the title's font (`load_font`), its title checked against line N's name, every row required to read, and SPELL (any memorised spell, as the list spells it; a hyphen reads as a space) required on it, a Curse or Silver Blades row `STRENGTH (2)` counting as two copies (`CAST_COUNT`); the highlight moved with `CAST_LIST_DOWN` (`End`, Silver Blades `Down`) to SPELL's row, reading it after each press, and `CAST`.  A spell that asks `CAST SPELL ON WHOM` gets T picked with the roster's key and `SELECT` (`Return` in Pool, `S` in the other two, `CAST_SELECT`); one that asks with no T given stops with nothing more pressed, a target prompt on any other bar stops naming it, and a spell that goes off without asking when T was given fails the step after the cast.  The cast is believed only when the list comes back holding one SPELL fewer, or, for the caster's only row, when the Magic bar comes back and `CAST` pressed there twice opens nothing, which is what it does with nothing memorised (a list that does open must not hold SPELL); `EXIT` twice to camp.  Any other screen stops the run with nothing more pressed, `LOSE IT` included |
| `scribe N SPELL` | Pool, Curse and Silver Blades, in camp: roster line N highlighted (`End` in Pool and Curse, `Down` in Silver Blades), `MAGIC`, `SCRIBE`; the scroll list read as text with the title's font (`load_font`), its title checked against line N's name, and SPELL (several words; a hyphen reads as a space) required on it without the `*` of a spell being scribed; the highlight walked onto SPELL's row with `SCRIBE_LIST_DOWN`, reading it after each press, and `SCRIBE` believed only when that row redraws as `*SPELL`.  Each `SCRIBE` is sent only while the row is highlighted and unmarked, the second only when no text row changed after the first, while it was awaited or on a reading taken after; a changed text row without the mark is the game blocking, and the step fails with the words it drew, while a change outside the text (the camp picture, Silver Blades' pointer) is not one.  A rejection drawn and gone between two readings is not seen, so two presses with neither a mark nor a change fail saying it may have been one.  Then the list's `EXIT`, the chosen spells read (SPELL must be listed `*`), their `EXIT`, `YES` at `SCRIBE THESE SPELLS?` and the Magic bar's `EXIT`, each pressed only at the screen it belongs to.  The party stays camped, so a camp `save` keeps the scribe pending and a `rest` finishes it; that rest's `scribe_pending` says a scribe was pending when it began, which any step outside `SCRIBE_KEEPS` forgets.  A `SCRIBE` that leaves the Magic bar up with the message window changed is sent a second time, and fails if that opens no list either, naming any words drawn.  Seen live once in Curse: the window is cleared and nothing is drawn while a converted scroll with a hidden name is unread, and the list opens with a staged Read Magic effect node (a memory edit, not a cast); the cleric and item-class condition is code reading only, and the `has no copyable scrolls` string (`SCRIBE_NONE`) was never seen live.  Driven in Pool of Radiance and Curse; Silver Blades' screens and keys are the hand-driven run's |
| `rest 5m`, `rest 1h30m`, `rest 8d` | camp `REST`, the rest time zeroed and set by key, then rested; minutes in fives; Pool's `GO STAY` random event at the end is answered `GO` (see below); in Curse a message over the continue bar that ends the rest (Tilverton's Royal Guards) gets `Return`, the map bar is required, and the party camps again, logged as `ended_by_message` |
| `save X` | in camp, camp `SAVE` to slot X and decline the quit; at the party menu, `SAVE CURRENT GAME`; believed when `SAVGAMX.DAT` changes |
| `train N` | Curse: roster line N (from 1), `TRAIN CHARACTER`, `YES`, and `LEARN` for any spell the level brings, back to the party menu |
| `shot NAME` | one PNG and the screen digests, nothing pressed |
| `snapshot NAME`, `restore NAME` | DOSBox-X only (`dossnapshot.SnapshotSession`; a run with either step boots it): `snapshot` saves the whole machine under NAME (letters, digits, `-`, `_`); `restore` puts it back and settles, and the `SAVE` files changed since the snapshot are logged and recorded as `changed_saves`, because a game save stays on disk.  A `restore` needs an earlier `snapshot` of that name and no `save` between them; the run stops before boot otherwise.  Each is in `run.jsonl` and `summary.json`.  Random encounters stay on, except under `--no-encounters`, where a `restore` clears the values the switch wrote and re-arms it.  A `snapshot` after a `press` is taken only once the screen has held unchanged for `Driver.SNAPSHOT_QUIET` seconds (30 s at most) and fails if it never does or changes while the state is written; its digest is recorded as `screen`, and a `restore` of that name fails unless the same screen comes back |
| `press KEY` | one X keysym (`Down`, `Return`, `t`), then a settle and a PNG; capture only, so only `press`, `shot`, `read`, `snapshot` and `restore` may come after it, and none of the last two after a `prayer-watch` |
| `walk MI`, `walk I`, `walk 1` | Pool and Curse (`MI`): turn right twice at the map bar and step one square.  Pool (`I`): step one square forward without turning.  Silver Blades and Pools of Darkness (`1`): press MOVE, step one square turning right past a wall, and leave move mode (`e` in Silver Blades, `Escape` in Pools of Darkness) back to the map bar.  In Pool and Curse a `PRESS <ENTER>/<RETURN> TO CONTINUE` story box the step lands on is answered with `Return`, `WALK_CONTINUE_ROUNDS` boxes at most, each logged as `press_continue`; combat or any other screen still stops the walk.  A step is believed only when the `x,y` on the status line changes (never the clock beside it), a blank line is never the starting reading; in Pool, where a turn can leave the line as `S 03:59` with no `x,y`, such a turn or step is judged by the square the DOSBox-X debugger reads at `POOL_PLACE` (x, y, facing doubled), which every reading logs as `place`, so a Pool walk or turn boots DOSBox-X, and a run with a walk fails unless `read` shows the last saved slot's place differs from the installed one |
| `walk KKIIJI` | Pool: a run of `I` (step forward), `J` (turn left) and `K` (turn right), each move judged by the place the DOSBox-X debugger reads at `POOL_PLACE` and the area byte `POOL_AREA`, both logged as `place`: a step must change the square or the area and a turn must leave both alone, so the area changes only on the step that crosses into the next one (`crossings` lists them).  A story box a step lands on gets `Return`.  The last step may end on a screen that is not the map, whose text is kept as `arrival` (the temple's `DO YOU SEEK HEALING?` for `temple raise`); on any earlier move such a screen stops the run |
| `temple raise N` | Pool, at the temple's arrival question a walk ended on (from the Slums square 15,4 facing W, `walk KKIIJI` reaches it at 1,3 in New Phlan): `YES`; roster line N highlighted (`End`); its sheet's money read (`VIEW`, `Escape`); `HEAL`, the service list read and its highlight moved with `End` onto `RAISE DEAD`, read after each press; `HEAL`; the price read off `PAY FOR CURE YES NO`; `YES`; the message window watched until the list holds clear; the list's `EXIT`, the sheet's money read again and the temple's `EXIT` back to the map.  `outcome` is `no-money` when the window says `NOT ENOUGH MONEY`, `alive` when the roster line's hit points then read 1 and the money changed, and `unknown` otherwise (the game draws no message for a raise and rolls nothing).  The result has the price, `gold_before`, `gold_after` and each sheet's money.  A run with it stages record bytes only with `--stage-record`, and only gold (`0x08E`, `0x08F`) and constitution (`0x014`) |
| `turn N` | N from 1 to 4: the walk's control.  Silver Blades and Pools of Darkness press MOVE first and leave move mode after; N `Right` presses, each reading the `x,y` square, which a turn must leave alone (`lost-walk-turn`); the party stays on the map for `camp`, `save D` and `read`.  A run with `turn` and no `walk` fails unless `read` shows the saved place unchanged ("did not move") |
| `fight first-bar` | Pool, Curse and Silver Blades, from the map: walk into a fight as `fight` does, log `placement` (judged from each square, as a dead member reads off the map but its fallen figure is drawn) and who acts at the first command bar, shoot it (`first_bar_shot`), and stop there with nothing pressed at it; no fight is fought out, so only `shot` and `read` may come after it |
| `fight`, `fight 900` | Pool: walk with `dosfightwatch.walk_to_encounter` until a fight bar shows, answer each bar by `PoolOfRadiance.COMBAT_KEYS`, log the command bars as below, and end on the map once its bar has held `FIGHT_SETTLED` seconds; one fight a boot.  Curse and Silver Blades, from the map: walk (Silver Blades in move mode) preferring squares not yet stood on (`Explorer`) until a fight starts, answer each bar by `FIGHT_KEYS` (`COMBAT`, `QUICK`, `EXIT` at the treasure and at a locked door, which the walk then marks walled, `NO` at `YES NO`, `Return` to continue), and end on the map once its bar has held `FIGHT_SETTLED` seconds; the number bounds walk and fight, in seconds (`FIGHT_SECONDS`).  At each command bar the debugger names who acts (`bar` in `run.jsonl`); at the first it logs `placement`, every combatant's square, side, quickfight and control (`COMBAT_LAYOUTS`), and `--first-bar-key KEY` is pressed there once instead of `QUICK`, the next bar logging every record again as `after-first-bar-key`.  A Silver Blades fight in area 16 is blocked unless the gate `$4C2D` is 1, since a successful wandering roll there is a compliment: add `--stage-var 4C2D=1`.  With `--intervene` (Silver Blades only) the game starts as `START.EXE X Gem` (`CHEAT_ARGS`) and Alt+X, the game's own end-the-fight key, is pressed once at the bar after the first-bar key, or at the first bar without one; a command bar coming back stops the run (`fight-intervene`).  The defeat screen (`PARTY_DESTROYED`) stops it at once (`fight-destroyed`).  A second `fight` in the boot follows `camp`, `save X` and `leave`, or another `fight`; the first-bar key and Alt+X are the first fight's only, each result names its fight by number, and every later fight presses `SPACE` once at its first combat screen (`HAND_BACK`: a command bar, or a blank or unclassified bar once combat has begun -- the encounter menu answered, the placement read, or the combat window changed from what the last fight left and reading as a fight, probed at most every `COMBAT_PROBE_SECONDS`), because `QUICK` survives into the next fight, logging every combatant's quickfight just before it (`before-hand-back`) and recording `handed_back`, `handed_back_to` and `before_hand_back`.  A run with a `fight` boots DOSBox-X (`dosboxx.XSession`) rather than DOSBox 0.74 |
| `prayer-watch 49`, `prayer-watch 35` | Pool (35 and 49), Curse and Silver Blades (49), from the map, `load` first, with each title's addresses (`dosfightwatch.PRAYER_LAYOUTS`).  Pool walks to an encounter (`walk_to_encounter`) and arms at the encounter menu; Curse and Silver Blades walk as `fight` does (Silver Blades' area 16 needs `--stage-var 4C2D=1` here too) and arm at the first command bar, once `placement` is logged and `QUICK` pressed there.  At that point it reads every member's effect nodes and Prayer's handler table, breaks on the id-49 stub (and Pool's id-35 stub) and the attack roll's stub (Pool's `08D2:003E`, the table's segment less the Prayer unit plus the attack unit), arm the list-10 call and its return at the segment that stub's far jump names, re-arming when a stub hit shows a new one, arm the handler, bonus test, +1 helper and penalty at the overlay segment the stub's far jump names once it loads, answer each bar (Pool by `COMBAT_KEYS`, Curse and Silver Blades by `FIGHT_KEYS`), and log each halt as `prayer-halt`: registers, 16 bytes at `SS:SP`, the four-frame `BP` chain, combatant name and side, the node's five bytes and the two roll bytes the +1 helper raises (Pool's `DS:0x6816` and `DS:0x6822`).  A party attack is a list-10 call halt with a side-0 attacker, closed by that attacker's next return halt.  For id 49 the step stops after one party attack whose own helper or penalty halt fell inside it, and in Curse and Silver Blades only once a monster's attack has also reached the penalty (`monster_penalties`), which a conclusive run there needs (only a list-10 penalty, an attack, counts as a monster's attack; a saving-throw penalty, list 12, does not; and a later round replaces an ally's round until a member carrying the node has completed one); for id 35 three completed pairs with no Prayer stub halt inside them are a conclusive result, and the step stops after the third.  It also stops when the map has held `FIGHT_SETTLED` seconds, at the defeat screen (Curse and Silver Blades), or after `PRAYER_FIGHT_SECONDS`; the step fails if the menu or first command bar came more than `PRAYER_BOOT_SECONDS` after the driver was made (Pool's walk is bounded by its 40 steps, the other two's by `FIGHT_SECONDS`, and both by the run's `--deadline`).  The result is `conclusive: False`, and the run exits 2 with `inconclusive` in `summary.json` rather than `lost` or `completed`, when no member carried the node at the menu or at the stop, an armed or halted routine's code did not match `GAME.OVR`, the stop-time party was not read, or, for id 49, no party attack armed at the stubs ran its helper or penalty (the first call loads the overlay before its routines are armed, so a round needs a later attack).  Only `shot`, `press` and `read` may follow |
| `read` | copies `SAVE/` out and decodes every node, the clock, the place and each character's experience, installed slot against each saved one; for Pools of Darkness also each character's eight thief skills, item count, encumbrance, movement, current movement, record byte 0x130 (spell id 126's book byte, `book_0x130`) and items |

**Pools of Darkness' screens are read off its `GAME.EXE` strings, not off a
capture.**  Its party menu holds Silver Blades' thirteen entries in the same
order (`GAME.EXE` 0xAB4E-0xAC90 against Silver Blades' `START.EXE`
0xE207-0xE349), so it is driven as Silver Blades' highlight list at
`route_silver_blades`'s rows; the map bar is `Move Area Cast View Encamp Search Look`
(0xBC79), the camp bar `Save View Magic Rest Alter Fix Exit` (0xBEBE), the
rest menu Curse's (0xBB26), the sheet's bar `Items Spells Trade Deposit Drop
Lay Cure Exit` (0xBB4F).  The party menu, map bar, camp bar and sheet have
answered their keys in three complete foundation boots (load, view, begin,
walk or turn, camp save, items); the rest menu has not been reached and
stays PROBABLE.  A screen that does not answer its key stops the run with a
`lost-*.png`.

**`--no-encounters` is for driver and automapper testing, never for a run that
proves a conversion.**  It boots DOSBox-X and, through
`dosnoencounters.NoEncounters`, writes the running area's encounter gate before
every move key of a `walk`, `turn` or `fight`; the gates are saved variables, so
a `save` step stops the run while the switch is on.  In Pools of Darkness it
changes each encounter roll in the loaded script to `SAVE` instead
(`dosnoencounters.SCRIPT_GATES`), and a `save` step stops the run the same way.
`--speculative-encounters` allows Silver Blades, whose offsets were not read in
a running game.
`summary.json` records `no_encounters: true` and a `no_encounters_report` of
the switch's reads and writes.  Without the flag random encounters stay on and
nothing is written.

**The load route is read from the code.**  `LOAD SAVED GAME` (`GAME.OVR`
0x12887) asks `load from where?` over `Pools Secret Exit`: `Pools` is this
title's own `SAVGAM<L>.PTY`, `Secret` a Silver Blades save, `Exit` backs out.
It then lists `load which game: A B C D E F G H I J`, keeping only the letters
whose `SAVGAM<L>.PTY` exists, and loads the one picked.  The menu routine
(0x3A422) takes a word's capital as its key through `UpCase`, so `p` then the
slot letter.  The party menu after a load shows `Train Character` and `Human
Change Classes` only when byte 0x2F of the save's first 1,024 bytes is not
zero (0x14253), which moves `View`, `Save` and `Begin` down two rows.
Silver Blades does the same on the word at 0xD51 of `SAVGAM<L>.DAT`
(`route_silver_blades.menu_after`).

**Pools of Darkness asks a journal copy-protection question between `Begin
Adventuring` and the map**, and the archives' build passes any answer
(`dospod.answer_journal` has the code).  `dospod.journal_question` knows the
screen by two glyph digests, never by its words; the driver looks for it
before every step and inside `begin`, shoots it, types `x` and `Return`, and
lists it in `events` as `journal`.  Nothing else is ever typed into it: a step
that finds it where it would press `Exit` answers it and stops the run.

**After the journal question the arrival may ask a `YES NO` question**, over
a portrait and story text.  The driver knows the bar by `POD_YES_NO_BAR`, a
`bar_signature` digest of the bar row only, and declines with `N`: the menu
routine keys each word by its first capital and returns at once (the
constants have the offsets).  It does so inside `begin` and before every
step, at most `POD_YES_NO_ROUNDS` in a row, and lists each in `events` as
`yes_no`.  `begin` then calls a screen the map only when its bar is
one of the `POD_MAP_BARS`, each measured from a capture of a real map, and
logs which kind it took (`map_bar` in `run.jsonl`); any other screen stops at
once with a `lost-begin-screen.png`, and anything else after the answer stops
the run in the same way rather than being typed into.  Journal, `YES NO` and
continue screens are counted one screen at a time, at most `POD_INTERSTITIALS`
in `begin`.  A party saved in Elminster's camp in Limbo (area 18) begins at
his help menu `POD_ELMINSTER_BAR`; `begin` shoots it as `town-screen` and
stops with `lost-begin-screen`, pressing nothing, unless the run goes on to
`vault`.  Use the party-menu steps (`load 'view 1' 'save D' read`) for such a
party otherwise.

**`vault` opens Pools of Darkness' item vault, which only Elminster's menu
in Limbo offers to a player.**  `ECL1.DAX` block 18 (area 18) sends both its
step entry (`$97F6`) and, when variable `$16` already holds 18, its arrival
entry (`$801D`) straight to the menu at `$8471`, so any square of the area
reaches it and a save made there opens on it.  The menu has `STORAGE` while
variable `$A2` is not 1 (`$84C0`); `STORAGE` saves 1 in variable `$31` and
runs opcode `$24`, which opens the vault screen (`GAME.OVR` 0x3261).  The
step runs `load begin vault`: `begin` takes Elminster's menu as its end,
`S` opens the vault, whose bar `VIEW TAKE POOL MONEY ITEMS EXIT`
(`DS:0x3196`) is read as text with the title's font; `TAKE` is drawn only
while the vault holds something.  With it, `T`, then `I` when the game
asks `TAKE: MONEY ITEMS EXIT` (`GAME.OVR` 0x5468, both coins and items
stored), lists the stored items; each page's rows are read as text, turned
with `NEXT`, and left with `EXIT`.  `E` at the take question and at the
vault bar goes back to Elminster's menu, the game having written
`TMPVAULT.DAT` (`GAME.OVR` 0x34C0), which the next `SAVE` renames to
`VAULT<L>.DAT`.  The screen is checked against that file: the game caches
each item's drawn name in its record (bytes 0x00-0x29), and every page
must read those names in order (`vault_window_check`), the file holding
the installed `VAULT<L>.DAT`'s items and coins.
`camp` from that menu presses `REST`, whose `PROGRAM 9` opens the camp loop
(`GAME.OVR` 0x21FF), so `load begin vault camp 'save D' read` stores the
game's own vault file.  The installed save must name area 18 in variable
`$16` with `$A2` not 1, which `--stage-var A2=0` arranges; the square is
not read.

**Pools of Darkness picks a character by its roster highlight, read off the
screen.**  The current character's name is the one roster line drawn in
white; `Down` moves it a member on and wraps (`POD_ROSTER_NEXT` has the
code), and `End` does nothing.  The camp's `VIEW` and the party menu's
`PICK CHARACTER` both view the highlighted character.  Each sheet is
believed only when the name cells at its top left carry the same glyphs as
roster line N's (`name_signature`), and a sheet frame two lines share stops
the run.  `ITEMS` is left with `Exit` to the sheet and the sheet with `Exit`
to where `VIEW` was pressed (`GAME.OVR` 0x2452E ends its loop on word 7,
`Exit`, or `Escape`); the driver looks before each `Exit` and never presses
one on the camp bar or the party menu.

Staging, written into the installed copy before the boot and logged in
bytes (`.claude/rules/testing.md`, "Poke a field before the boot"):
`--hall` sets the word at `SAVGAM+0xD51` to `0x00FF`, which puts `TRAIN
CHARACTER` in the party menu wherever the party stands for every class
(`docs/194-the-dos-training-ladder.md`); `--xp N=VALUE` sets roster line N's
experience; `--add-node N=ID:MINUTES:DATA:FLAG` appends one effect node to
line N's effect file (`.SPC`, `.FX` or `.SFX`); `--stage-side
LINE=SIDE[:QUICKFIGHT]` sets line N's combat side byte and optionally the
quickfight byte after it (`stage_side`); `--stage-record
LINE:OFFSET=VALUE` sets one byte of line N's `CHRDAT` record below its length; `--stage-var
ADDRESS=VALUE` sets one script-variable word of `SAVGAM`, or in Pools of
Darkness one byte of `SAVGAM<L>.PTY` by the scripts' own 1-based index (`read`
reports it as the last saved slot holds it); `--stage-place
X,Y,FACING` puts the party on a square of an indoor `SAVGAM`, or of a
Pools of Darkness save made in a dungeon, facing 0 to 3 (N E S W), last of the stages.

**The rest-time keys are read from each title's `GAME.OVR`**, because nobody
had captured the screen.  Pool of Radiance's rest menu is `Rest daYs Hours
Mins Inc Dec Exit` (key loop `0x244ED`); Curse's and Silver Blades' is `Rest
Days Hours Mins Add Subtract Exit` (Curse `0x2B4A7`, Silver Blades
`0x2BD63`).  The three loops are one routine with different letters: the
menu opens on the minutes field; the days, hours and minutes keys select a
field; the add key adds one day or hour, or **five** minutes; the subtract
key takes the same away, borrowing, and **clamps at zero**: with nothing
above the field to borrow from, the whole time is zeroed (Pool `0x24246`,
Curse `0x2B1F5`, Silver Blades `0x2BAB2`).  `R` and `Return` rest.  The
camp's `REST` presets hours and minutes to the longest memorisation the party
has queued (Pool `0x17FAB`, Curse `0x19730`), so the time is zeroed from the
days field before it is set.  A rest takes five minutes off the time and adds
five to the clock per pass (Pool `0x24A66`, Curse `0x2BB59`-`0x2BB84`), so
the clock in the resave is the check that the time was set right.  **Any key
pressed while resting asks `Stop Resting?`**, so nothing is pressed until the
camp bar is back.

**A Pool rest can end in a random event instead of the camp bar**: the city
watch rousts the party and asks `GO STAY`.  The clock has already moved on
and the effects have aged by then.  The driver presses `G` and waits for the
map bar; the party is then out of camp, so the next `rest` or `save` presses
`ENCAMP` again.  `S` is never pressed, since STAY would start a fight.  At
most two such events are answered in one rest; a third, a fight or any other
screen stops the run with a `lost-*.png`, and so does a screen under the
viewport that stops changing for `REST_STALL` seconds without being the camp
bar -- a rest redraws its time every five passes, so a still screen is a
message, a fight, or the game having stopped.  Each event is logged as
`event: random` in `run.jsonl` and listed in the summary's `events`.

Each key in the rest menu is believed only when the text window under the
viewport changes, and is pressed a second time at most; a key that changes
nothing twice stops the run with a PNG rather than being counted.

Evidence goes to `~/.cache/wish/acceptance/<issue>/<sha>-<run>/`: `run.jsonl`,
`summary.json`, `shots/`, `installed/` (the save as booted) and `resave/`
(the engine's `SAVE`).  Nothing is committed and the archives are read only.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import logging
import os
import pathlib
import re
import shutil
import signal
import sys
import time
import traceback
from collections.abc import Callable

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_codec, dos_savegame, effects, world_state  # noqa: E402
from tools.dos import (  # noqa: E402
    dosbox,
    dosboxx,
    dosfightwatch,
    dosnoencounters,
    dospod,
    dossnapshot,
    route_silver_blades,
    unexepack,
)
from tools.dos.screens import (  # noqa: E402
    BLANK_NAME,
    CELL,
    POD_NAME_CELLS,
    POD_NAME_ROWS,
    POD_ROSTER,
    POD_SHEET_NAME,
    POOL_ITEMS_BAR,  # noqa: F401 -- the constant lives in screens, which reads it; tests and runs name it here
    STATUS_COLUMNS,
    bar_signature,
    item_highlight,
    item_rows,
    on_items_list,
    roster_line,
    roster_name,
    sheet_name,
    status_square,
)
from tools.dos.staging import (  # noqa: E402
    HALL_TITLES,
    HALL_WORD,
    containers_in,
    install,
    node_dict,
    slots_in,
    source_slot,
    stage_control,
    stage_hall,
    stage_node,
    stage_place,
    stage_record,
    stage_var,
    stage_xp,
)
from tools.registry import evidence, scratch  # noqa: E402

# The camp bar is `Save View Magic Rest Alter Exit` in Pool of Radiance and
# `Save View Magic Rest Alter Fix Exit` in the other two (`START.EXE`).
# Pool's `Exit` is exit to DOS, so `e` is never pressed in camp.
ENCAMP = "e"
CAMP_SAVE = "s"
CAMP_REST = "r"
QUIT_NO = "n"
# The camp Magic bar `CAST MEMORIZE SCRIBE DISPLAY REST EXIT` and the one-page
# Display bar ` EXIT`, by `bar_signature`.  Measured in Pool first; Curse's
# and Silver Blades' Magic bars and Curse's one-page Display bar give the same
# values (#666's `7080ae935c-curse-display-measure` and
# `7080ae935c-ssb-display-measure`).
POOL_MAGIC_BAR = "062aa229ea7afd11"
POOL_DISPLAY_BAR = "98286ceaa33edc12"
#: A Display list longer than its window: ` NEXT EXIT` on the first page and
#: ` PREV EXIT` on the last, by `bar_signature`, measured in Silver Blades,
#: where `n` scrolled a 20-line list by one line and `p` scrolled it back.
#: Curse's paged bars are unmeasured and read as these by the shared font.
DISPLAY_NEXT_BAR = "392973724e8ad548"
DISPLAY_PREV_BAR = "862edc20f753abcc"
DISPLAY_BARS = {POOL_DISPLAY_BAR: "exit", DISPLAY_NEXT_BAR: "next",
                DISPLAY_PREV_BAR: "prev"}
#: The titles whose camp `MAGIC > DISPLAY` the `display` step drives.
DISPLAY_TITLES = frozenset({"pool", "curse", "ssb"})
#: The Display list's window, in text cells: rows 4 to 22, columns 1 to 38
#: (Curse `GAME.OVR` 0x1A3DB-0x1A3ED passes rows 4-0x16, columns 1-0x26 to
#: the list routine).  Each member is a line at column 1, each effect a line
#: at column 2, and a blank line after each member.
DISPLAY_ROWS = range(4, 23)
DISPLAY_COLUMNS = range(1, 39)
#: The line a member with no effect gets: Pool's and Curse's, Silver Blades'.
NO_EFFECTS = ("<NO SPELL EFFECTS>", "<NO MAGICAL EFFECTS>")
#: At most this many Display pages before the run stops.  Silver Blades'
#: `n` scrolls one line, so a list of L lines takes L - 18 pages; paging
#: stops earlier when a page adds no line to the merged list.
DISPLAY_PAGES = 64
#: The keys that leave the Display list, the first tried first.  ` EXIT`
#: alone answers `Return` in Pool and Curse (measured); on a paged bar
#: `Return` changed nothing in Silver Blades, so `e`, the word's capital, as
#: `n` and `p` are.  The second is pressed only while the list still shows.
DISPLAY_LEAVE = {"exit": ("Return", "e"), "prev": ("e", "Return"),
                 "next": ("e", "Return")}
#: The text font: block 201 of the title's `8X8D*.DAX`, eight bytes a glyph,
#: the high bit leftmost, indexed by the upper-cased character modulo 0x40.
FONT_BLOCK = 201
FONT_GLYPHS = 0x40
#: Silver Blades draws its mouse pointer, a white arrow, over the Display
#: list, whose text is cyan (names) and green (effects).
POINTER_INK = b"\xff\xff\xff"
#: The titles whose camp `MAGIC > SCRIBE` the `scribe` step drives.
SCRIBE_TITLES = frozenset({"pool", "curse", "ssb"})
#: The titles whose camp `MAGIC > CAST` the `cast` step drives.
CAST_TITLES = frozenset({"pool", "curse", "ssb"})
#: A camp spell-list row holding several copies of one spell: Curse and
#: Silver Blades draw `STRENGTH (2)` where Pool draws two `STRENGTH` rows, the
#: count falling by one a cast (`274/6e6a1b0e90-curse-cast` and
#: `274/6e6a1b0e90-ssb-cast`, under DOSBox-X).
CAST_COUNT = re.compile(r"(.*\S) \((\d+)\)")
#: The key that moves the camp spell list's highlight a spell on, wrapping.
#: Pool's `End` (`dosbox.LIST_DOWN`); Curse's `End` and Silver Blades' `Down`,
#: measured in those two runs, where each list opened on its last row and two
#: presses wrapped through the first to the spell.
CAST_LIST_DOWN = {"pool": dosbox.LIST_DOWN, "curse": dosbox.LIST_DOWN, "ssb": "Down"}
#: `SELECT` at `CAST SPELL ON WHOM SELECT EXIT`: Pool's is `Return`; Curse
#: and Silver Blades take `S` (three casts in each of those runs).
CAST_SELECT = {"pool": "Return", "curse": "s", "ssb": "s"}
#: `SCRIBE` on the Magic bar and on the scroll list's `CHOOSE SPELL: SCRIBE
#: EXIT`, `EXIT` on the list and on the chosen spells, and `YES` at `SCRIBE
#: THESE SPELLS? YES NO`: each word's capital, measured in Silver Blades and
#: Pool of Radiance.
MAGIC_SCRIBE = "s"
SCRIBE_PICK = "s"
SCRIBE_LEAVE = "e"
SCRIBE_YES = "y"
#: The key that moves the scroll list's highlight a row down, wrapping:
#: `End` (`dosbox.LIST_DOWN`) in Pool, measured on this list, which opened on
#: its last row, and in Curse, measured on its grimoire; in Silver Blades
#: `Down`, the key its roster and party menu take, unmeasured here because its
#: list opened on the one spell the measured run scribed.
SCRIBE_LIST_DOWN = {"pool": dosbox.LIST_DOWN, "curse": dosbox.LIST_DOWN, "ssb": "Down"}
#: The scroll list, the chosen spells and the text read off both: the list
#: menu's rows are 8 pixels from y 40 (text row 5), the highlighted one found
#: by `Screen.highlight_row`; the title is text row 1 and the bar row 24, each
#: read with the title's font (`load_font`).  Pool and Silver Blades draw a
#: level heading at column 1, a spell at column 3, and a spell being scribed
#: as `*` at column 2 before its name.
SCRIBE_LIST = (8, 40, 296, 128)
SCRIBE_HEAD_ROW = 1
BAR_ROW = dosbox.BAR[1] // 8
SCRIBE_LEVEL = re.compile(r"\d+(ST|ND|RD|TH) LEVEL")
SCRIBE_MARK = "*"
#: What tells the three scribe screens apart: the list's bar opens `CHOOSE
#: SPELL` and its title holds `ON SCROLL` (`<NAME>'S SPELLS ON SCROLLS`); the
#: chosen spells' bar is `EXIT` alone under `<NAME>'S SPELLS TO SCRIBE` (Pool:
#: `SPELLS TO BE SCRIBED`); the confirmation's bar holds `THESE SPELLS?`.
#: Measured in Pool, Silver Blades and Curse (`GAME.OVR` 0x2A4A7, 0x2A4C8,
#: 0x2E178), where the list read `<NAME>'S SPELLS ON SCROLLS`.
SCRIBE_LIST_BAR = "CHOOSE SPELL"
SCRIBE_LIST_HEAD = "ON SCROLL"
SCRIBE_CHOSEN_HEAD = "SPELLS TO"
SCRIBE_CONFIRM = "THESE SPELLS?"
#: The message window's text rows and columns, where Curse writes `THE PARTY
#: MAKES CAMP...` (row 18) and any answer to `SCRIBE` that is not the list.
SCRIBE_MESSAGE_ROWS = range(17, 23)
#: Curse's string for a character whose scrolls list no spell (`GAME.OVR`
#: 0x19A8E, `<NAME> has no copyable scrolls`) is unconfirmed: the string was
#: never seen live.  Seen live once in Curse: the game clears the message
#: window and stays on the Magic bar with nothing a capture drew at ten frames
#: a second for six seconds, for a converted MU scroll with mask 6, and the
#: list opened after a staged Read Magic (effect 16) node, a memory edit and
#: not a cast.  From code reading only: a scroll whose name is hidden (item
#: `+0x35` non-zero) lists its spells while the character has Read Magic in
#: effect, or for a cleric reading a scroll of the item class the type table
#: marks 12, and listing it clears the mask (`GAME.OVR` 0x2E8C7).
SCRIBE_NONE = "NO COPYABLE SCROLLS"
#: How long a pick is given to redraw its row as `*SPELL` before the next key.
SCRIBE_PICK_SECONDS = 6.0
#: The steps after which a scribe is still pending: none of them leaves camp.
#: The camp save does not cancel it (Silver Blades, measured); camp exit and
#: camp entry do (`GAME.OVR` 0x1D359 and 0x1D1B9 call the party clear).
SCRIBE_KEEPS = frozenset({"scribe", "rest", "save", "shot", "read"})
#: Pool's map command bars and its character sheet's bar `VIEW: TRADE DROP
#: EXIT`, by `bar_signature`, each measured off a real screen: `town` on the
#: runs that already used the map (#666's `ca4bbff4fa-dos-pool-sheet-live`,
#: for example), `overland` on #634's `ca4bbff4fa-dos-pool-rebuild`.  On the
#: map `End` moves the roster highlight a member on and wraps; `v` opens the
#: sheet, and `Escape` (never `d`, which the sheet's bar offers as DROP)
#: returns to the map with the highlight where it was.  `town` reads `AREA
#: CAST VIEW ENCAMP SEARCH LOOK` and `overland` `CAST VIEW ENCAMP SEARCH
#: LOOK`.  `load`, `begin` and `camp` take a screen for the map only on one
#: of these; any other bar stops the run, naming its words.
POOL_MAP_BARS: dict[str, str] = {"town": "809e2e1cc9504b5b",
                                 "overland": "f379c606cadd4484"}
#: The character sheet's bar, by `bar_signature`, one entry per kind of sheet,
#: each measured off real screens: `no_items` is `VIEW:TRADE DROP EXIT`,
#: `items` is `VIEW:ITEMS TRADE DROP EXIT`, `caster` is `VIEW ITEMS SPELLS
#: TRADE DROP EXIT` (a cleric's sheet); which of the first two shows depends
#: on whether the sheet offers ITEMS, not on where the party stands.  An NPC's
#: sheet offers no TRADE or DROP: `npc_items` is `VIEW:ITEMS EXIT` (an NPC
#: fighter, several captures across DOSBox runs of the pooled `dosbox.conf`
#: on the town map) and `npc_caster` is `VIEW:ITEMS SPELLS EXIT` (an NPC
#: magic-user, one capture).  `caster_no_items` is `VIEW:SPELLS TRADE DROP
#: EXIT`, a magic-user carrying nothing (MALCYON, one capture).  A bar not
#: measured here is still a sheet's when its words, read with the title's
#: font, are `POOL_SHEET_BAR_TEXT` (`Driver.on_pool_sheet`), so a class whose
#: bar has no digest here does not stop a `sheet` or `items` step.
POOL_SHEET_BARS: dict[str, str] = {"no_items": "33ad531ed78cfa70",
                                   "items": "95afa0d95cd09ab7",
                                   "caster": "49958cda77bfdd82",
                                   "caster_no_items": "84c7653e93c251c1",
                                   "npc_caster": "740a10d0bc93a12a",
                                   "npc_items": "90b53c9e64947226"}
#: The `POOL_SHEET_BARS` entries whose bar offers no `ITEMS`.
POOL_SHEET_NO_ITEMS = ("no_items", "caster_no_items")
#: Every Pool sheet bar read as text: `VIEW:`, the class's own words, `EXIT`.
#: All six measured bars read this way with the title's font.
POOL_SHEET_BAR_TEXT = re.compile(r"VIEW:(?:\S.* )?EXIT")
POOL_ROSTER_NEXT = "End"
#: Where Pool's `ITEMS` list draws the Detect Magic mark, `* ` between the
#: READY column and the name: text column 7 (x 56) of each row, from y 40, one
#: row per 8 pixels.  `POOL_ITEM_MARK` is the `*` glyph's signature there,
#: `Screen.glyphs` of one 8x8 cell, measured on 2 marked rows (both on the
#: highlighted row 1); a mark on another row or on a `NO` row is unmeasured.
POOL_ITEM_MARK_X = 56
POOL_ITEM_MARK = "4590f6541a365c32"
# Names start at x=8; effect lines are indented to x=17. Count the left
# character cell across the page, allowing row spacing to change by effect.
POOL_DISPLAY_NAME_ROWS = range(32, 184, 8)

#: The titles whose party-menu `ADD CHARACTER TO PARTY` the `add` step drives.
ADD_TITLES = frozenset({"pool"})
#: Pool's party menu before any load, read as text with the title's font
#: (`load_font`) in #791's probe boot: the bar `CHOOSE A FUNCTION`, the roster
#: from text row 4 at column 1 (`POD_ROSTER["party"]`), and the functions at
#: rows 12 to 22 from column 2, each keyed by its first letter.  `VIEW
#: CHARACTER` is drawn only once the party has a member.
PARTY_MENU_BAR = "CHOOSE A FUNCTION"
PARTY_MENU_ROWS = range(12, 23)
PARTY_ADD_ENTRY = "ADD CHARACTER TO PARTY"
PARTY_VIEW_ENTRY = "VIEW CHARACTER"
#: A Pool save made at the party menu (`SAVE CURRENT GAME`) loads back onto
#: it, not the map; its `BEGIN ADVENTURING`, keyed `PARTY_BEGIN`, is what
#: `begin` presses there.
PARTY_BEGIN_ENTRY = "BEGIN ADVENTURING"
#: Seconds Pool's `camp` waits for a measured map bar on a settled screen
#: that shows none, before it stops the run with nothing pressed.
CAMP_MAP_WAIT = 10.0
PARTY_ADD = "a"
#: `ADD A CHARACTER: ADD EXIT` lists `CHARLIST.TXT`'s names from text row 2
#: at column 1, one a row.  `End` moved the highlight a row down and `Home`
#: back (measured, one press each); the arrow keys do nothing and any other
#: key picks (`dosaddchar.py`).  `Return` picked ARRONEL and redrew his row
#: as `* ARRONEL`; `e` left the list for the party menu.
ADD_LIST_BAR = "ADD A CHARACTER: ADD EXIT"
ADD_LIST = (8, 16, 304, 168)
ADD_LIST_DOWN = dosbox.LIST_DOWN
ADD_PICK = "Return"
ADD_LEAVE = "e"
ADD_MARK = "* "
#: Seconds the list is given to star the picked row: the file is read first.
ADD_PICK_SECONDS = 15.0
#: The roster's lines at the party menu, at most.
PARTY_ROSTER_LINES = 8
#: What the `add` step stages from the title's own `SAVE` folder: every
#: exported character (`<stem>.CHA` and its `.ITM` and `.SPC`) and the
#: `CHARLIST.TXT` the list is built from.  The saved games' `CHRDAT` files
#: are left out.
EXPORT_SUFFIXES = (".CHA", ".ITM", ".SPC")
CHARLIST = "CHARLIST.TXT"
#: Pool's sheet bar opens `VIEW`; its `ITEMS` list's bar opens `READY` and
#: its title is `<NAME>'S ITEMS`, the rows from text row 5 as ` YES  LONG
#: SWORD`, a readied flag and the name (#791's probe boot, ARRONEL).
POOL_SHEET_BAR_HEAD = "VIEW"
POOL_ITEMS_BAR_HEAD = "READY"
POOL_ITEMS_TITLE = "'S ITEMS"
POOL_ITEM_FIRST_ROW = 5
#: A type-0 item draws no name, so its row is the flag alone.
POOL_ITEM_ROW = re.compile(r"(YES|NO)(?:\s+(\*\s*)?(\S.*)?)?")
#: The sheet's rows read as text, and the figure the `view` step reports.
POOL_SHEET_ROWS = range(1, 23)
POOL_ENCUMBRANCE = re.compile(r"ENCUMBRANCE\s+(\d+)")

# Pool's rest menu is `Rest daYs Hours Mins Inc Dec Exit` (`GAME.OVR` 0x244A5).
REST_DAYS = "y"
REST_HOURS = "h"
REST_MINS = "m"
REST_INC = "i"
REST_DEC = "d"
REST_GO = "r"
#: What one add or subtract moves the minutes field by (Pool `GAME.OVR`
#: 0x245CB, Curse 0x2B585, Silver Blades 0x2BE41).
REST_STEP = 5
#: The days field's ceiling (Pool `GAME.OVR` 0x24192, Curse 0x2B148).
REST_DAYS_MAX = 99
#: Seconds the text window may stay still during a rest before the run stops.
REST_STALL = 90.0

#: The `GO STAY` command bar of Pool's city watch random event, by
#: `bar_signature`, measured off the screen of a live Bless run.
WATCH_BAR = "4aaded0229f46861"
WATCH_GO = "g"
#: Random events answered in one rest before the run gives up.
MAX_EVENTS = 2

#: The text window under the viewport and the command bar below it, where
#: the rest time is drawn (text row 17) and every rest-menu key shows.  The
#: viewport's picture is left out so nothing it draws reads as a keypress.
TEXT_WINDOW = (0, 120, 320, 80)


#: Curse's party menu takes a letter per command, `C D M T H V A R L S B E J`
#: (`START.EXE`): `LOAD SAVED GAME`, `SAVE CURRENT GAME`, `BEGIN ADVENTURING`
#: and `TRAIN CHARACTER`.
PARTY_LOAD = "l"
PARTY_SAVE = "s"
PARTY_BEGIN = "b"
PARTY_TRAIN = "t"
#: `DO YOU WISH TO TRAIN? YES NO` (`docs/194-the-dos-training-ladder.md`).
TRAIN_YES = "y"
#: Moves the roster highlight down a line and wraps from the last to the first.
ROSTER_NEXT = "End"
#: Pressed in turn until the party menu is back after a training: `LEARN` at
#: `<NAME>'S SPELLS TO CHOOSE FROM`, then whatever message is left.
AFTER_TRAIN = ("l", "l", "Return", "Escape")

#: Silver Blades' party menu is a highlight list (`route_silver_blades.MENU_RECT`).
#: With no party it is `Create New Character`, `Add Character to Party`,
#: `Load Saved Game`, ...; `route_silver_blades.MENU_BEFORE` measured `Add` at row 1,
#: and `Load Saved Game` comes after it in `START.EXE`'s list, so row 2; the
#: Silver Blades foundation boots (`found-ssb-a`, `-b`, `-control`) and, as
#: `POD_LOAD_ROW`, the Pools of Darkness ones (`found-pod-a`, `-b2`,
#: `-control`) load a save through it.
SSB_LOAD_ROW = 2

#: Pools of Darkness' party menu, driven as Silver Blades' highlight list
#: because `GAME.EXE` holds the same entries in the same order.  The rows are
#: Silver Blades'; the load, view, save and begin rows have answered in three
#: complete foundation boots of this title.  The eleven-row height is an
#: unverified inference from Silver Blades' own measurement, not from this
#: title's own data: all sixteen captures behind the y=184 frame cutoff were
#: Silver Blades captures, and no Pools of Darkness capture has confirmed its
#: own frame sits at the same y.
POD_MENU_RECT = route_silver_blades.MENU_RECT
POD_LOAD_ROW = SSB_LOAD_ROW
POD_MENU_AFTER = route_silver_blades.MENU_AFTER
#: `POOLS` at `LOAD FROM WHERE? POOLS SECRET EXIT` (`GAME.EXE` data 0x2E1B,
#: asked at `GAME.OVR` 0x12901): this title's own `SAVGAM<L>.PTY`.  `S` would
#: read a Silver Blades save instead.
POD_LOAD_FROM = "p"
#: The save byte whose non-zero value puts `Train Character` and `Human Change
#: Classes` on the party menu (`GAME.OVR` 0x14253, read from the first 1,024
#: bytes the load puts at `[0x87F8]`), two rows above `View`.
POD_TRAIN_BYTE = 0x2F
#: A `YES NO` bar with nothing else on the bar row, by `bar_signature`.
#: Measured on the arrival dialog `Begin` led to in run `75e0c741ac-run0-control`
#: of #650 (shots 006 and 007, one screen); none of the 17 other shots of the
#: three runs has it (7 other signatures).  The words are never kept.
POD_YES_NO_BAR = "02af736347597b37"
#: `No` on that bar.  The menu routine (`GAME.OVR` 0x3A422) keys each word by
#: its first character in the set 0-9, A-Z (0x3A220, the set at 0x3A200),
#: puts the key pressed through `UpCase` (0x3A90F), returns the index of the
#: word it keys (0x3A376) and does so at once, without `Return` (0x3A954).
#: The engine's own yes-or-no question (0x3B66D) asks it over `Yes No`
#: (`GAME.EXE` data 0x2B64) and returns 1 for `No`.
POD_DECLINE = "n"
#: `YES NO` bars declined one after another before the run gives up.
POD_YES_NO_ROUNDS = 3
#: A story dialog whose bottom row reads `PRESS BUTTON OR ENTER TO CONTINUE`,
#: by `bar_signature` of that row alone.  Measured on the screen after `No` on
#: the arrival question; the words are never kept.
POD_CONTINUE_BAR = "7a286012361f96ae"
#: What the bar says continues it.
POD_CONTINUE = "Return"
#: Continue screens answered one after another before the run gives up.
POD_CONTINUE_ROUNDS = 5

#: Curse's `PRESS <ENTER>/<RETURN> TO CONTINUE` bar (`Screen.glyphs(dosbox.BAR)`), the
#: one `route_silver_blades.BARS` measured; a party saved before BEGIN ADVENTURING
#: meets it on the world view.
CURSE_CONTINUE_BAR = next(k for k, v in route_silver_blades.BARS.items() if v == "continue")

#: Pool's `PRESS <ENTER>/<RETURN> TO CONTINUE` bar, the `press_return` row of
#: `dosbox.PoolOfRadiance.COMBAT_BARS`; a party saved on an event square meets
#: it on load, before the map is showing (#701).
POOL_CONTINUE_BAR = next(digest for width, digest, label in dosbox.PoolOfRadiance.COMBAT_BARS
                         if label == "press_return")

#: How many continue screens `press_continue_screens` answers for Curse's
#: BEGIN and rest before it gives up.
CONTINUE_ROUNDS = 3
#: The `PRESS <ENTER>/<RETURN> TO CONTINUE` story box a `walk` step can land
#: on, by title: Curse shows one at 2,14 in the town (`GHARRI WAS SEEN JUST
#: OUTSIDE OF TOWN`), over `CURSE_CONTINUE_BAR`.  The box offers nothing but
#: `Return`, and whatever follows it is judged as the step's own screen.
WALK_CONTINUE_BARS: dict[str, str] = {"pool": POOL_CONTINUE_BAR,
                                      "curse": CURSE_CONTINUE_BAR}
#: How many chained story boxes a `walk` step answers before it gives up.
#: Not measured past one box; the bound only keeps a stuck screen from looping.
WALK_CONTINUE_ROUNDS = 5
#: How many Pool's load answers before it gives up.  A party that has never
#: taken Rolf's opening tour (clock zero at area 0, 15,1, as any party made in
#: the Amiga or C64 game is) loads into the whole tour: eight chained screens,
#: `GREETINGS, COURAGEOUS ONES` through `YOUR TOUR IS ENDED`, each a different
#: frame, and then the map at 0,4 (#631, run `dce274bcca-tour-count-cap25`).
#: PROBABLE: measured on one boot of one party, taken as a general figure.
#: Two more than the tour, so a stuck screen still stops the run.
POOL_LOAD_CONTINUE_ROUNDS = 10
#: Journal, `YES NO` and continue screens `begin` answers in all, counted one
#: screen at a time, before it gives up, so that no mix of them can loop.
POD_INTERSTITIALS = 12
#: The map command bars, by `bar_signature`, which `begin` accepts as the map
#: after the arrival screens, each measured off a real screen: `dungeon` (the
#: bar `MOVE AREA CAST VIEW ENCAMP SEARCH LOOK`) on the control run
#: `e38a1bb514-run0-control` of #650, and `overland` (`MOVE ENCAMP`) on the
#: Amiga cleric party's run `840311866e-run1-cleric`.  Any other bar stops
#: `begin`; an empty mapping makes it stop at every screen.
POD_MAP_BARS: dict[str, str] = {"dungeon": "0409f26b63f9c492",
                                "overland": "8ce27036e9d49c83"}
#: Elminster's help menu in Limbo, `HEAL TRAIN STORAGE REST MOVE ON`
#: (`ECL1.DAX` block 18, `$84CB`), by `bar_signature`, measured on the Amiga
#: thief party's run `88eac43064-run2-thief` of #650 (`lost-begin-screen`);
#: its glyph signature there was `53b2db87f794e8bb`, and WISH-2's run3b of
#: SavGamH drew the same.  It is not a map.  The destination menu after MOVE
#: ON is bar `151b806b9b9fe327`, unmeasured and deliberately not entered:
#: only `vault`'s `STORAGE` and `camp`'s `REST` are pressed on this bar.
POD_ELMINSTER_BAR = "f8c32c677c85b2d4"
#: Variable `$16` holds the area the party was last in (the engine copies
#: `DS:0xC580` into it after an area's entry script, `GAME.OVR` 0xE5F and
#: 0x2BFA), and area 18's arrival entry goes to Elminster's menu when it
#: already reads 18.  Variable `$A2` = 1 takes `STORAGE` off the menu.
ELMINSTER_AREA = 18
POD_AREA_VAR = 0x16
POD_STORAGE_VAR = 0xA2
#: `STORAGE` and `REST` on Elminster's menu, keyed by their capitals.
ELMINSTER_STORAGE = "s"
ELMINSTER_REST = "r"
#: The vault screen's bar, `View Take Pool Money Items Exit` (`DS:0x3196`);
#: the menu builder (`GAME.OVR` 0x330D-0x339D) leaves out `Take` with an
#: empty vault, `Money` when the member has no coins and `Items` when he
#: has no items.
VAULT_WORDS = ("VIEW", "TAKE", "POOL", "MONEY", "ITEMS", "EXIT")
VAULT_TAKE = "t"
#: `Take: ` over `Money Items Exit` (`GAME.OVR` 0x5468 and 0x546F), asked
#: only when the vault holds both coins and items (0x5480); `I` lists the
#: items, and with no coins the list opens at once.
VAULT_TAKE_PROMPT = ("TAKE:", "MONEY", "ITEMS", "EXIT")
VAULT_TAKE_ITEMS = "i"
VAULT_EXIT = "e"
#: What leaving the vault screen writes (`GAME.OVR` 0x34C0 -> 0x13B5D).
TMPVAULT = "TMPVAULT.DAT"
#: Where the vault's item list is read: rows 1 to 22, one item a row,
#: inside the frame's columns (WISH-2 stage 9, SavGamH's 40 items).  `NEXT`
#: moves the window 22 items on but never past the last full window, so
#: the second page of 40 showed items 19 to 40.  The whole area above the
#: bar is what a page turn must change.
VAULT_ITEM_ROWS = range(1, 23)
VAULT_WINDOW = len(VAULT_ITEM_ROWS)
VAULT_TEXT_COLUMNS = range(1, 39)
VAULT_LIST_RECT = (0, 8, 320, 176)
#: Where each 63-byte vault record carries the name the game last drew for
#: the item, as a length byte and text (`goldbox.dos_port.ITEM_LAYOUT`
#: 0x00-0x29): the vault screen fills it, and its writer stores it.
VAULT_NAME = slice(0x00, 0x2A)
#: `ITEMS` on the vault bar lists the highlighted member's items under the
#: bar `READY TRADE DEPOSIT HALVE JOIN EXIT`, and `D` deposits the
#: highlighted item at once, with no question: the row leaves the list and
#: the highlight stays on the same row (one press, then one `Return` on the
#: lit `DEPOSIT`, each taking one row off a 14-row list).  `D` on a readied
#: item leaves the list as it was (one press; the drop at `GAME.OVR` 0x247E5
#: turns a readied item away).  The vault screen draws the roster where camp
#: does, and `Down` moves its highlight a member on (four presses, line 1 to
#: 5).  `E` leaves the list.
VAULT_ITEMS = "i"
VAULT_DEPOSIT = "d"
VAULT_ITEMS_EXIT = "e"
VAULT_ROSTER = "camp"
#: The member's list is headed `<NAME>'S ITEMS` on text row 1.
VAULT_ITEMS_HEAD_ROW = 1
VAULT_ITEMS_HEAD = "'S ITEMS"


def is_vault_bar(words: list[str]) -> bool:
    """Whether `words` are the vault screen's bar: `VIEW`, `POOL` and `EXIT`
    always, the rest of `VAULT_WORDS` in their order where offered."""
    if not words or words[0] != "VIEW" or words[-1] != "EXIT" or "POOL" not in words:
        return False
    rest = iter(VAULT_WORDS)
    return all(w in rest for w in words)


def tmpvault(save_dir: pathlib.Path) -> dict | None:
    """The `TMPVAULT.DAT` leaving the vault wrote, decoded, or None."""
    path = next((p for p in save_dir.iterdir() if p.name.upper() == TMPVAULT), None)
    if path is None:
        return None
    data = path.read_bytes()
    out = {"file": path.name, "size": len(data),
           "sha256": hashlib.sha256(data).hexdigest()}
    try:
        v = dos_codec.pod_vault_from_dos(data)
    except dos_codec.DosRecordError as e:
        return {**out, "error": str(e)}
    return {**out, "items": len(v.items), "platinum": v.platinum, "gems": v.gems,
            "jewelry": v.jewelry, "names": [record_name(r) for r in v.items]}


def record_name(record: bytes) -> str:
    """The name a vault record caches, upper case and stripped, as the
    screen's font reads it."""
    field = record[VAULT_NAME]
    return field[1:1 + field[0]].decode("latin-1").upper().strip()


def vault_window_check(pages: list[list[str]], names: list[str]) -> dict:
    """Whether the list pages read off the screen show `names` in order:
    page k must equal `names` from `min(k * VAULT_WINDOW, len(names) -
    VAULT_WINDOW)` on, a `?` read under the pointer matching any character,
    and the last page must end at the last name.  Returns each page's top
    and the first page that disagrees, if any."""
    def same(row: str, name: str) -> bool:
        return len(row) == len(name) and all(a in ("?", b) for a, b in zip(row, name))

    tops: list[int] = []
    for k, rows in enumerate(pages):
        top = max(0, min(k * VAULT_WINDOW, len(names) - VAULT_WINDOW))
        tops.append(top)
        want = names[top:top + VAULT_WINDOW]
        if len(rows) != len(want) or not all(map(same, rows, want)):
            return {"tops": tops, "covered": False, "page": k + 1,
                    "read": rows, "names": want}
    end = tops[-1] + len(pages[-1]) if pages else 0
    return {"tops": tops, "covered": end == len(names)}


def vault_page_limit(records: int) -> int:
    """How many pages a vault of `records` items lists: one window of
    `VAULT_WINDOW` rows a page, the last never past the end, and one page
    for an empty or short list.  A list still offering `NEXT` after that many
    pages holds more than the vault file does."""
    return max(1, -(-records // VAULT_WINDOW))


def same_name(read: str, name: str) -> bool:
    """Whether a name read off the screen is `name`, a `?` read under the
    pointer matching any character."""
    return len(read) == len(name) and all(a in ("?", b) for a, b in zip(read, name))


def vault_item_entry(text: str) -> tuple[bool | None, str]:
    """A row of the member's list in the vault, `YES  NAME` or `NO   NAME`:
    whether it is readied (None when the column reads neither) and the name."""
    words = text.split(None, 1)
    if not words:
        return None, ""
    ready = {"YES": True, "NO": False}.get(words[0])
    if ready is None:
        return None, text.strip()
    return ready, words[1].strip() if len(words) > 1 else ""


def parse_deposit(words: list[str], text: str):
    """`deposit MEMBER ROW`: roster line 1-8 and a row the list draws, from
    1, or None when `words` are not a deposit step."""
    if len(words) != 3 or words[0].lower() != "deposit" or not re.fullmatch(
            r"[1-8]", words[1]) or not re.fullmatch(r"\d+", words[2]):
        return None
    row = int(words[2])
    if not 1 <= row <= ITEM_ROWS:
        raise ValueError(f"deposit row {row} is blocked: the list shows rows 1 to "
                         f"{ITEM_ROWS} and the rows past them need Next, which "
                         "is not driven here")
    return Step("deposit", text, line=int(words[1]), row=row)


def deposit_rejection(title: str, where: str, step) -> str | None:
    """Why `step`, a deposit, cannot run with the party `where`, or None: it
    starts at Elminster's menu, which only `vault` (or a deposit) leaves the
    party at, in Pools of Darkness."""
    if title != "darkness":
        return f"deposit is driven in darkness only, not {title}"
    if where != "elminster":
        return (f"deposit comes after vault, which leaves the party at Elminster's "
                f"menu: {step.text!r}")
    return None

#: `View` on the map and camp bars; `Items` and `Exit` on the sheet's bar
#: `Items Spells Trade Deposit Drop Lay Cure Exit` (`GAME.EXE` 0xBB4F).  The
#: `ITEMS` list turns its page with `Next` (0xA6AF), the list protocol's `n`.
VIEW = "v"
SHEET_ITEMS = "i"
LEAVE = "e"
ITEMS_NEXT = dosbox.LIST_PAGE_DOWN
#: Pages of `ITEMS` captured before the run gives up on reaching the last.
ITEMS_PAGES = 6
#: The `ITEMS` list draws at most 18 rows, at y = 40 + 8k (all 37 Pools of
#: Darkness `ITEMS` captures of #650's runs).  `Next` pages past them, which
#: `halve` and `join` do not drive.
ITEM_ROWS = 18
#: `Down` moves the `ITEMS` highlight one row on (2 of 2 presses) and `Up` one
#: back (1 of 1); `End` and `Home` did nothing (1 press each), so
#: `dosbox.LIST_DOWN` is not this list's key.  Not measured: whether the
#: highlight wraps.
ITEM_NEXT_ROW = "Down"
#: `HALVE` and `JOIN` act at once and ask nothing: 7 rows became 8 and back to
#: 7, the highlight staying on row 1 (one press each, TURBO K's 50 arrows).
#: Not measured: a stack of 1, a full list, a list of 18 rows.
ITEM_HALVE = "h"
ITEM_JOIN = "j"
#: Silver Blades' `ITEMS` bar is `READY TRADE DROP [HALVE] JOIN EXIT`; `t`
#: opens `TRADE WITH WHOM?` and `j` joins at once, both seen in a driven boot.
ITEM_TRADE = "t"
#: That prompt's bar, `TRADE WITH WHOM? SELECT EXIT`, by `bar_signature`: the
#: same on 2 captures.  It draws the
#: party-menu roster with the trader's line highlighted; `Down` moved the
#: highlight a line on, and `s` gave the item to the highlighted member and
#: brought the trader's list back without the item.
SSB_TRADE_BAR = "c4590a78b4fc9cbd"
#: Where each title's `join` runs: Pools of Darkness in camp, Silver Blades
#: at the party menu, where its sheet's `ITEMS` was driven.
JOIN_WHERE = {"darkness": "camp", "ssb": "party"}
#: The `ITEMS` list's first text row: its rows start at y = 40
#: (`screens.ITEM_LIST_RECT`), eight pixels a row.
ITEM_TEXT_ROW = 40 // CELL

#: Pools of Darkness' roster selector (`GAME.OVR` 0x2680C, far entry `AA:4D`)
#: moves the current character to the next member on scancode 0x50 and to
#: the one before on 0x48, wrapping at both ends, and ignores every other
#: key, `End` (0x4F) included.  The camp loop (0x105F1) and the party menu's
#: `PICK CHARACTER` prompt (0x26E4E) hand it each special key their menu
#: returns; the menu routine (0x3A422) returns an arrow as its scancode, and
#: `2` and `8` as 0x50 and 0x48 through the table at `DS:0x5364`.
POD_ROSTER_NEXT = "Down"
#: The map bar's first word, `Move`, keyed by its capital as every Pools of
#: Darkness bar is.  Until it is pressed the arrows go to the roster
#: selector; pressed, the bar is `EXIT` alone and the arrows move the party.
#: Silver Blades' `dossheetread.walk` does the same; unmeasured in this title.
POD_MOVE = "m"
#: What leaves move mode, `dossheetread`'s `--move-exit` default.
POD_MOVE_EXIT = "Escape"
#: The keys that enter and leave move mode, by title key.  Silver Blades'
#: `m` is CONFIRMED (bar `EXIT` alone, ink `e61c9acccfc048ae`, three runs); its
#: `e` leaves it: runs with `--move-exit e` and the foundation boots came back
#: to the map bar, and `Escape` does not, since it leaves the move bar showing.
#: Curse has no move mode: `Up` steps at the map bar.
#: Pools of Darkness keeps `m` and `Escape`.
MOVE_KEYS = {"darkness": (POD_MOVE, POD_MOVE_EXIT), "ssb": ("m", "e")}
#: Curse's party-menu `bar_signature`, the loaded menu and the empty one alike:
#: CONFIRMED on 12 shots of 4 boots.  It does not tell a loaded menu from an
#: empty one, so `check_party_drawn` still reads the roster.
CURSE_PARTY_BAR = "31286bfc4a3695fc"
#: Silver Blades' `bar_signature` after `PICK CHARACTER`'s select key is the
#: sheet's own bar, and it depends on the member (`SPELLS EXIT` on a ranger,
#: PAINE, `ae25da8be0427b42`; `route_silver_blades.BARS` lists the `HEAL` sheets), so a
#: Silver Blades sheet is judged by its name and never by a bar.  Unmeasured:
#: the bar of any other member's sheet.
#: `Select`, the only word of the `PICK CHARACTER` prompt (`GAME.EXE` data
#: `DS:0x2859` over `DS:0x2B8D`), keyed by its first letter.  The prompt then
#: views the character the roster highlight is on (`AA:39`, 0x2452E).
POD_PICK = "s"
#: Roster-highlight moves tried per member before `pick_line` gives up.
POD_PICK_ROUNDS = 2

#: `Magic` on the camp bar, and `Memorize` on the Magic bar `CAST MEMORIZE
#: SCRIBE DISPLAY EXIT` it opens (`GAME.EXE` data 0xD13E lists a `Rest` the
#: screen does not draw).  The Magic bar by `bar_signature`, measured on 5
#: shots of the #509 probe boot `probe-memorize-live` (lines 1 and 5).
POD_MAGIC = "m"
POD_MEMORIZE = "m"
POD_MAGIC_BAR = "24a79a5ab06c2164"
#: The grimoire `<NAME>'S SPELLS IN GRIMOIRE` that `Memorize` opens for the
#: highlighted character.  Its bar is `CHOOSE SPELL:MEMORIZE` and then the
#: list words, `NEXT EXIT` on the first page, `NEXT PREV EXIT` between and
#: `PREV EXIT` on the last (`GAME.EXE` data 0xC64F and 0xCA79).  The head,
#: its first 21 cells, is the same on every page (6 shots, 2 characters); a
#: list of one page, `MEMORIZE EXIT`, is unmeasured, and the head is what
#: knows it.
POD_GRIMOIRE_HEAD = "524989d1c25436a9"
POD_GRIMOIRE_HEAD_CELLS = 21
#: The two whole-bar signatures that offer `NEXT`, first page and between;
#: the last page's is `47a21ea1ca2723b9`.  `Next` on the last page changes
#: nothing (7 presses over 2 characters) and the list does not wrap.
POD_GRIMOIRE_NEXT_BARS = frozenset({"37d28076a433f661", "41b0de522281a00d"})
POD_GRIMOIRE_NEXT = dosbox.LIST_PAGE_DOWN
#: Pages shot before the run gives up on reaching the last; HILDE's
#: magic-user book from level 1 to 9 is 7.
GRIMOIRE_PAGES = 16
#: The title's first cell, and the signature of the `'S` after the name in
#: it: the roster name's cells, then these two (HILDE and TROND AAGE L, 3
#: shots).
GRIMOIRE_TITLE = (8, 8)
GRIMOIRE_POSSESSIVE = "4ed3290842b823f9"
#: The list: eleven 8-pixel rows from y = 40.  A row is read from x = 8 over
#: 19 cells, which holds a level header and a spell name of 17 characters
#: after its two-cell indent; the game's mouse arrow sits at x 161-174 over
#: rows 7 to 9 and is left out.  A longer name is read by its first 17.
GRIMOIRE_ROWS_AT = (8, 40)
GRIMOIRE_ROW_COUNT = 11
GRIMOIRE_ROW_CELLS = 19
#: Rows by the signature `grimoire_rows` reads, measured on HILDE's last page
#: with the highlight on each of the four bottom rows in turn (the reading
#: is the same whichever row is lit).  The names are the last three entries
#: of `GAME.EXE`'s spell-name table (0x23 bytes each, `Bless` first, 126
#: entries), so `Monster Summoning` is id 126 and appears nowhere else.
NINTH_LEVEL_ROW = "5bb57d1d629bc1df"
GRIMOIRE_SPELLS = {"46508bd7a6ec4097": 124,     # METEOR SWARM
                   "e1ad523ef877d882": 125,     # POWER WORD KILL
                   "42b47c6c0a74f78d": 126}     # MONSTER SUMMONING
SPELL_126_ROW = next(k for k, v in GRIMOIRE_SPELLS.items() if v == 126)
#: The record byte that holds spell id 126: the last of the 126-byte book at
#: 0x0B3 (`goldbox/dos_port.py`'s Pools of Darkness `spellbook`).  The list
#: builder (`GAME.OVR` 0x2A80B) lists 126 when it is not zero.
POD_BOOK_126 = 0x130

#: The camp sheet's own words, read from each title's `GAME.OVR`.  Curse
#: builds its bar at 0x27C94-0x27DF4 from `Items Spells Trade Drop Heal Cure
#: Exit`, each word drawn only when its test passes: `Heal` when the gate at
#: 0x2A64D passes (a paladin, or a regained one, not in game mode 5, status
#: `0x195` zero, no node 140), `Cure` when 0x2A6B2 does (the same, and uses at
#: `0x191` above zero).  The menu routine (0x3C465) returns the capital pressed
#: and the loop calls the heal routine on `H` (0x27E75) and the cure on `C`
#: (0x27E87).  Silver Blades is the same loop (gate 0x2AE3B; `H` at 0x28147,
#: `C` at 0x2815F).  Pools of Darkness' bar is `Items Spells Trade Deposit Drop
#: Lay Cure Exit` (`GAME.EXE` 0xBB4F), `Lay` enabled at 0x2467D when the gate
#: 0x26ADA passes, and the loop dispatches word 5 (`Lay`) to the heal routine
#: 0x26BC3 and word 6 to the cure 0x26CE6; the menu keys each word by its
#: capital.
SHEET_KEYS = {"curse": {"heal": "h", "cure": "c"},
              "ssb": {"heal": "h", "cure": "c"},
              "darkness": {"heal": "l", "cure": "c"}}
#: The titles whose camp sheet `sheet N` and `heal N` drive.
CAMP_SHEETS = frozenset(SHEET_KEYS)
#: The titles `cure N` is driven in: the cure's prompts are read from Curse's
#: code for #649's runs; the other two titles' are the same strings, undriven.
CURES = frozenset({"curse"})
#: What moves the camp's current member on, by title.  Curse's camp, like its
#: party menu, hands `End` (scan code 0x4F) and `Home` (0x47) to the roster
#: handler at `GAME.OVR` 0x2A32C, which every menu that opens the sheet calls;
#: Silver Blades' handler (0x2AB0F) and Pools of Darkness' (0x2680C) take
#: `Down` (0x50) and `Up` (0x48).
CAMP_ROSTER_NEXT = {"curse": ROSTER_NEXT, "ssb": POD_ROSTER_NEXT,
                    "darkness": POD_ROSTER_NEXT}
#: `SELECT` at `HEAL WHOM?` and `CURE WHOM?`.  Curse's prompt (0x3A4C8) is the
#: prompt, `Select` and `Exit`; its loop ends on Return, Escape, `E` or `S`
#: (the set at 0x3A4A0), takes the member it is on for `S`, and opens on the
#: party's first member (`[0x6524]`).  `End` and `Home` move it.  Silver
#: Blades' `CURE WHOM? SELECT EXIT` took `S` in `ssbimport.py`'s run.
PICK_SELECT = "s"
#: `YES` to `<NAME> IS NOT DISEASED` / `CURE ANYWAY: YES NO`, which the cure
#: asks when nobody in the party has a disease (Curse 0x2A8C6-0x2A915: it
#: goes on only on `Y`).
CURE_ANYWAY = "y"
#: How long a sheet may take to come back after `SELECT`: the heal and the
#: cure print their message and wait `[0x4FC2]` tenths of a second, the
#: message speed, through `Delay` (`START.EXE` image 0x57F9), before the
#: sheet redraws; no key is asked for.
SHEET_BACK_SECONDS = 60.0

#: `HUMAN CHANGE CLASSES` on Curse's party menu, `H` (`GAME.OVR` 0x20486),
#: enabled at 0x20252 when the hall word `--hall` opens is set and the
#: current member may change.  It calls 0x3BB4D on the current member.
PARTY_CHANGE = "h"
#: The class list 0x3BB4D shows (the list menu 0x104:0x34 over text columns
#: 1-38 and rows 2-22): a `Pick New Class` header, then every class the member
#: qualifies for, in his race's table order; `S` takes the highlighted class.
#: The same list menu drives Curse's grimoire, where `End` moves the
#: highlight down and wraps (`dosbox.Camp.GRIMOIRE_LIST`).  The rectangle is
#: the list window clear of its border columns, not measured on this screen:
#: the step counts the rows it can reach and stops unless they are as many
#: as the classes the engine's own test allows.
CHANGE_LIST = (16, 16, 288, 168)
#: Rows a class list can hold: the eight classes of a human's table.
CHANGE_ROWS = 8

#: `START.EXE` data-segment tables 0x3BB4D and its test 0x3B99E read: class
#: names (27-byte Pascal strings), each race's class list (a count, then
#: class ids), each class's six ability minima, and each class's alignments
#: (a count, then up to nine).
CLASS_NAMES_AT, CLASS_NAME_SIZE = 0x0CB8, 27
RACE_CLASSES_AT, RACE_CLASSES_SIZE = 0x3FFA, 14
CLASS_MINIMA_AT, CLASS_MINIMA_SIZE = 0x4174, 6
CLASS_ALIGNMENTS_AT, CLASS_ALIGNMENTS_SIZE = 0x41DA, 10
#: 0x3BF66: the current class is `0x11`, none, for any race but 7, human.
HUMAN_RACE, NO_CLASS = 7, 0x11
#: 0x3B99E: a minimum of 9 or more marks an ability the change tests; the
#: class left must have each above 14 and the class taken each above 16.
REQUISITE, KEEP_ABOVE, TAKE_ABOVE = 9, 14, 16
#: The record fields the test reads (Curse `goldbox.dos_port`): the six
#: abilities (the first byte of each two), race, the class-level array and
#: alignment, at 0x10, 0x74, 0x109 and 0x11B in the code.
ABILITIES = ("strength", "intelligence", "wisdom", "dexterity", "constitution",
             "charisma")


def bar_words(screen: dosbox.Screen) -> list[list[str]]:
    """The command bar as words: runs of cells that are not flat, each cell
    `Screen.glyphs` against its own paper, so a word lit by the highlight
    block reads as the same word unlit."""
    x0, y, w, h = dosbox.BAR
    words: list[list[str]] = []
    word: list[str] = []
    for x in range(x0, x0 + w, CELL):
        rect = (x, y, CELL, h)
        if screen.flat(rect):
            if word:
                words.append(word)
            word = []
        else:
            word.append(screen.glyphs(rect))
    if word:
        words.append(word)
    return words


def font_table(block: bytes) -> dict[bytes, str]:
    """Each glyph's eight bytes to its character, from a font block.

    Glyph i is the character whose upper case modulo 0x40 is i: 0 to 0x1F
    are `@` to `_`, 0x20 to 0x3F are space to `?`.  The blank glyph and the
    solid one (drawn for both `\\` and `%`) are left out, since neither can
    be told from paper.
    """
    table: dict[bytes, str] = {}
    for i in range(min(FONT_GLYPHS, len(block) // 8)):
        bits = bytes(block[i * 8:i * 8 + 8])
        if not any(bits) or bits == b"\xff" * 8:
            continue
        table.setdefault(bits, chr(i + 0x40) if i < 0x20 else chr(i))
    return table


def load_font(game: pathlib.Path) -> dict[bytes, str]:
    """The title's text font, `FONT_BLOCK` of whichever `8X8D*.DAX` holds it
    (`8X8D1` in Pool and Curse, `8X8D5` in Silver Blades)."""
    for path in sorted(game.iterdir()):
        if not re.fullmatch(r"8X8D\d*\.DAX", path.name, re.IGNORECASE):
            continue
        data = path.read_bytes()
        if any(entry[0] == FONT_BLOCK for entry in dos_savegame.dax_index(data)):
            return font_table(dos_savegame.dax_block(data, FONT_BLOCK, path.name))
    raise FileNotFoundError(f"no 8X8D*.DAX in {game} holds block {FONT_BLOCK}")


def read_cell(screen: dosbox.Screen, x: int, y: int, font: dict[bytes, str]) -> str:
    """The character in the 8x8 cell at `x`, `y`, `?` when none matches.

    Ink is whatever is not the cell's commonest colour; a glyph drawn
    reversed matches through its complement.  When neither matches, each ink
    colour is tried alone, which reads a letter under Silver Blades' white
    pointer, and a cell whose only ink is the pointer's colour is blank.
    """
    px = screen.rows((x, y, CELL, CELL))
    colours = [px[i:i + 3] for i in range(0, len(px), 3)]
    counts: dict[bytes, int] = {}
    for c in colours:
        counts[c] = counts.get(c, 0) + 1
    paper = max(counts, key=lambda k: counts[k])

    def bits(lit) -> bytes:
        return bytes(sum(0x80 >> dx for dx in range(CELL) if lit(colours[dy * CELL + dx]))
                     for dy in range(CELL))

    ink = bits(lambda c: c != paper)
    if not any(ink):
        return " "
    for b in (ink, bytes(0xFF ^ v for v in ink)):
        if b in font:
            return font[b]
    for colour in sorted(set(counts) - {paper}):
        alone = bits(lambda c, colour=colour: c == colour)
        if alone in font:
            return font[alone]
    if set(counts) == {paper, POINTER_INK}:
        return " "
    return "?"


def display_lines(screen: dosbox.Screen, font: dict[bytes, str]) -> list[str]:
    """The Display list's window as text, a line a row, right-stripped."""
    return ["".join(read_cell(screen, col * CELL, row * CELL, font)
                    for col in DISPLAY_COLUMNS).rstrip()
            for row in DISPLAY_ROWS]


def text_row(screen: dosbox.Screen, row: int, font: dict[bytes, str],
             columns=range(40)) -> str:
    """Text row `row` over `columns`, read with the title's font, right-stripped."""
    return "".join(read_cell(screen, col * CELL, row * CELL, font)
                   for col in columns).rstrip()


def spell_key(text: str) -> str:
    """A spell's name for comparison: upper case, a hyphen read as a space,
    runs of spaces as one."""
    return " ".join(text.upper().replace("-", " ").split())


def scribe_entries(screen: dosbox.Screen, font: dict[bytes, str]) -> list[dict]:
    """The spells of the scroll list or of the chosen spells, each with its
    list row (from 0, as `highlight_row` counts), the level heading above it,
    and whether it is drawn `*`, being scribed."""
    x, y, _, h = SCRIBE_LIST
    out, level = [], None
    for k in range(h // CELL):
        line = text_row(screen, y // CELL + k, font, DISPLAY_COLUMNS)
        text = line.strip()
        if not text:
            continue
        if SCRIBE_LEVEL.fullmatch(text):
            level = text
        elif line.startswith(" "):
            marked = text.startswith(SCRIBE_MARK)
            out.append({"row": k, "level": level, "marked": marked,
                        "spell": text[len(SCRIBE_MARK):].strip() if marked else text})
    return out


def scribe_screen(screen: dosbox.Screen, font: dict[bytes, str]) -> str | None:
    """`list`, `chosen` or `confirm` for the three scribe screens, else None."""
    bar = text_row(screen, BAR_ROW, font)
    head = text_row(screen, SCRIBE_HEAD_ROW, font, DISPLAY_COLUMNS)
    if bar.strip().startswith(SCRIBE_LIST_BAR) and SCRIBE_LIST_HEAD in head:
        return "list"
    if bar.strip() == "EXIT" and SCRIBE_CHOSEN_HEAD in head:
        return "chosen"
    if SCRIBE_CONFIRM in bar:
        return "confirm"
    return None


def cast_list(screen: dosbox.Screen, font: dict[bytes, str]) -> dosbox.SpellList:
    """A camp spell list (`<NAME>'S SPELLS IN MEMORY`) read as text: the same
    rows as the scroll list (`scribe_entries`), each name as `spell_key`
    spells it.  A row Curse or Silver Blades draws as `STRENGTH (2)` is two
    copies of `STRENGTH` on that row (`CAST_COUNT`); Pool draws each copy as
    its own row."""
    spells = []
    for e in scribe_entries(screen, font):
        name = spell_key(e["spell"])
        counted = CAST_COUNT.fullmatch(name)
        if counted and int(counted[2]) > 0:
            spells += [(e["row"], counted[1])] * int(counted[2])
        else:
            spells.append((e["row"], name))
    return dosbox.SpellList(
        head=text_row(screen, SCRIBE_HEAD_ROW, font, DISPLAY_COLUMNS).strip(),
        bar=text_row(screen, BAR_ROW, font).strip(),
        spells=tuple(spells))


def roster_text(screen: dosbox.Screen, line: int, font: dict[bytes, str]) -> str:
    """Camp roster line `line`'s name, read with the title's font."""
    x, y = POD_ROSTER["camp"]
    return "".join(read_cell(screen, x + CELL * i, y + CELL * (line - 1), font)
                   for i in range(POD_NAME_CELLS)).strip()


def party_menu_entries(screen: dosbox.Screen, font: dict[bytes, str]) -> list[str] | None:
    """Pool's party-menu functions, top down, or None off the party menu."""
    if text_row(screen, BAR_ROW, font).strip() != PARTY_MENU_BAR:
        return None
    return [t for t in (text_row(screen, r, font, DISPLAY_COLUMNS).strip()
                        for r in PARTY_MENU_ROWS) if t]


def party_roster(screen: dosbox.Screen, font: dict[bytes, str]) -> list[str]:
    """The party menu's roster names, top down, to the first blank line."""
    x, y = POD_ROSTER["party"]
    names = []
    for line in range(PARTY_ROSTER_LINES):
        name = "".join(read_cell(screen, x + CELL * i, y + CELL * line, font)
                       for i in range(POD_NAME_CELLS)).strip()
        if not name:
            break
        names.append(name)
    return names


def pool_map_kind(screen: dosbox.Screen) -> str | None:
    """Which measured Pool map bar of `POOL_MAP_BARS` is showing, or None."""
    sig = bar_signature(screen)
    return next((k for k, bar in POOL_MAP_BARS.items() if bar == sig), None)


def add_entries(screen: dosbox.Screen, font: dict[bytes, str]) -> list[str] | None:
    """The `ADD A CHARACTER` list's rows as drawn (a picked one as `* NAME`),
    to the first blank row, or None off the list."""
    if text_row(screen, BAR_ROW, font).strip() != ADD_LIST_BAR:
        return None
    x, y, _, h = ADD_LIST
    entries = []
    for k in range(h // CELL):
        text = text_row(screen, y // CELL + k, font, DISPLAY_COLUMNS).strip()
        if not text:
            break
        entries.append(text)
    return entries


def pool_item_list(screen: dosbox.Screen, font: dict[bytes, str]) -> list[dict]:
    """Pool's `ITEMS` rows, each `ready`, `marked` (Detect Magic's `*`) and
    `name`, to the first blank row; a row that reads otherwise is a
    ValueError naming it."""
    items = []
    for k in range(ITEM_ROWS):
        text = text_row(screen, POOL_ITEM_FIRST_ROW + k, font, DISPLAY_COLUMNS).strip()
        if not text:
            break
        m = POOL_ITEM_ROW.fullmatch(text)
        if m is None:
            raise ValueError(f"item row {k + 1} reads {text!r}")
        items.append({"ready": m.group(1) == "YES", "marked": bool(m.group(2)),
                      "name": (m.group(3) or "").strip()})
    return items


def changed_rows(before: dosbox.Screen, after: dosbox.Screen,
                 font: dict[bytes, str]) -> list[str]:
    """The text rows that differ between two frames, as `after` draws them."""
    out = []
    for row in range(25):
        now = text_row(after, row, font)
        if now != text_row(before, row, font) and now.strip("? "):
            out.append(now.strip("? "))
    return out


def message_lines(screen: dosbox.Screen, font: dict[bytes, str]) -> list[str]:
    """The message window's lines (`SCRIBE_MESSAGE_ROWS`), each stripped."""
    return [text_row(screen, row, font, DISPLAY_COLUMNS).strip()
            for row in SCRIBE_MESSAGE_ROWS]


def _same_line(a: str, b: str) -> bool:
    """Two readings of one line, `?` matching any character."""
    n = max(len(a), len(b))
    return all(p == q or "?" in (p, q) for p, q in zip(a.ljust(n), b.ljust(n)))


def _real(line: str) -> bool:
    """Whether a line holds a character that was read, not only blanks and `?`."""
    return any(c not in " ?" for c in line)


def merge_pages(pages: list[list[str]]) -> list[str]:
    """One list from pages that scroll it, each page's head laid over the
    longest tail of the list so far that it matches.  An overlap counts only
    when at least one of its lines was read on both pages, so a blank or
    unreadable page is appended rather than laid over real lines.  A line
    read with a `?` on one page takes the other page's reading when that has
    none."""
    lines = list(pages[0]) if pages else []
    for page in pages[1:]:
        overlap = 0
        for k in range(min(len(lines), len(page)), 0, -1):
            pairs = list(zip(lines[-k:], page[:k]))
            if (all(_same_line(a, b) for a, b in pairs)
                    and any(_real(a) and _real(b) for a, b in pairs)):
                overlap = k
                break
        for i in range(overlap):
            at = len(lines) - overlap + i
            if "?" in lines[at] and "?" not in page[i]:
                lines[at] = page[i]
        lines.extend(page[overlap:])
    return lines


def display_members(lines: list[str]) -> list[dict]:
    """Each member the Display list names, in order, with the effect lines
    under it; `NO_EFFECTS` is an empty list.  A line at column 1 is a name,
    one at column 2 an effect; blank lines separate members."""
    members: list[dict] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if not line.startswith(" "):
            members.append({"name": text, "effects": []})
        elif not members:
            raise ValueError(f"an effect line before any name: {text!r}")
        elif text not in NO_EFFECTS:
            members[-1]["effects"].append(text)
    return members


def sheet_offers(words: list[list[str]], title: str) -> dict[str, bool] | None:
    """Whether a sheet bar's words offer the heal and the cure, or None when
    the bar does not end in the four-letter `EXIT` every sheet bar ends in.

    Read by letter position, not by a measured digest, because which words
    a sheet shows varies with what the member carries and knows.  The last
    word's first cell is `E`.  Curse's and Silver Blades' `HEAL` is the one
    four-letter word with `E` second; `CURE` the one with `E` fourth
    (`DROP`, the other, has none); Pools of Darkness' `LAY` is its only
    three-letter word.  Checked against the one Curse paladin's sheet and the
    one Pools of Darkness paladin's sheet captured so far.
    """
    if not words or len(words[-1]) != 4:
        return None
    e = words[-1][0]
    rest = words[:-1]
    if title == "darkness":
        heal = any(len(w) == 3 for w in rest)
    else:
        heal = any(len(w) == 4 and w[1] == e for w in rest)
    cure = any(len(w) == 4 and w[3] == e and w[1] != e for w in rest)
    return {"heal": heal, "cure": cure}


def acted_word(words: list[list[str]], title: str, act: str) -> int | None:
    """The index of the `HEAL`/`LAY` or `CURE` word in a sheet bar's words.

    Shares `sheet_offers`'s guard against a bar that does not end in the
    four-letter `EXIT`, so the two cannot read a bar's form differently.
    """
    if sheet_offers(words, title) is None:
        return None
    e = words[-1][0]
    for i, w in enumerate(words[:-1]):
        if act == "heal" and (len(w) == 3 if title == "darkness"
                              else len(w) == 4 and w[1] == e):
            return i
        if act == "cure" and len(w) == 4 and w[3] == e and w[1] != e:
            return i
    return None


def yes_no_words(words: list[list[str]]) -> bool:
    """A bar that ends `YES NO`: a three-letter word and a two-letter one."""
    return len(words) >= 2 and len(words[-2]) == 3 and len(words[-1]) == 2


def _lengths(words: list[list[str]], *want: int) -> bool:
    return len(words) >= len(want) and all(
        len(w) == n for w, n in zip(words, want))


def continue_battle_words(words: list[list[str]]) -> bool:
    """Silver Blades' `CONTINUE BATTLE: YES NO`, asked when no monster is left.

    The colon touches the `Y`, so `BATTLE:YES` reads as one ten-cell word and
    `yes_no_words` never sees it.  With the words `c, b, n`, `N` is
    `CONTINUE`'s third and sixth cells and opens `NO`, `O` is its second and
    `NO`'s second, `T` is its fourth and `BATTLE`'s third and fourth, and `E`
    is its last and `BATTLE`'s sixth and the last cell of `YES`.  The
    highlighted answer reads as the same cells as an unlit one.
    """
    if len(words) != 3 or not _lengths(words, 8, 10, 2):
        return False
    c, b, n = words
    return (c[2] == c[5] == n[0] and c[1] == n[1]
            and c[3] == b[2] == b[3] and c[7] == b[5] == b[8])


def command_words(words: list[list[str]]) -> bool:
    """A combat command bar: `MOVE VIEW AIM` first, whatever follows.

    Curse's bar is `Move View Aim Use Cast Turn Quick Done` (`GAME.OVR`
    0xAC73) and Silver Blades' `Move View Aim Use Cast Quick Done` (0xC0E5),
    each word drawn only when the member may use it.  Read by which cells
    repeat, not by a measured digest: `V` is `MOVE`'s third cell and `VIEW`'s
    first, `E` `MOVE`'s fourth and `VIEW`'s third, `I` `VIEW`'s second and
    `AIM`'s second, `M` `MOVE`'s first and `AIM`'s third, and `O` and `W`
    are neither of those.
    """
    if not _lengths(words, 4, 4, 3):
        return False
    move, view, aim = words[:3]
    m, o, v, e = move
    return (view[0] == v and view[2] == e and aim[1] == view[1]
            and aim[2] == m and view[3] not in (m, o, v, e)
            and len({m, o, v, e, view[1], aim[0]}) == 6)


def encounter_words(words: list[list[str]]) -> bool:
    """An encounter menu that opens `COMBAT WAIT FLEE`: `A` and `T` are
    `COMBAT`'s fifth and sixth cells and `WAIT`'s second and fourth, and
    `FLEE` ends in two cells alike."""
    if not _lengths(words, 6, 4, 4):
        return False
    combat, wait, flee = words[:3]
    return (wait[1] == combat[4] and wait[3] == combat[5]
            and flee[2] == flee[3] and len(set(combat)) == 6)


def treasure_words(words: list[list[str]]) -> bool:
    """The treasure bar: Curse's and Pool's `VIEW TAKE POOL SHARE EXIT`, or
    Silver Blades' `VIEW TAKE POOL EXIT`.

    `E` ends `VIEW`'s third cell, `TAKE` and `SHARE` and opens `EXIT`, and
    `POOL` doubles its `O`.  Silver Blades has no `SHARE`, so `EXIT` is the
    fourth word, and `I` is `VIEW`'s second cell and `EXIT`'s third.
    """
    if _lengths(words, 4, 4, 4, 4) and len(words) == 4:
        view, take, pool, exit_ = words
        return (view[2] == take[3] == exit_[0] and view[1] == exit_[2]
                and pool[1] == pool[2] and take[0] == exit_[3])
    if not _lengths(words, 4, 4, 4, 5, 4) or len(words) != 5:
        return False
    view, take, pool, share, exit_ = words
    return (view[2] == take[3] == share[4] == exit_[0]
            and pool[1] == pool[2] and take[0] == exit_[3])


def locked_words(words: list[list[str]]) -> bool:
    """A locked door: `LOCKED.` over `BASH PICK KNOCK EXIT`, whichever of
    the first three the party is offered (Curse `GAME.OVR` 0x18B8C, Silver
    Blades 0x19C6F).

    `LOCKED.` is seven cells, all different, the `.` its last; its fifth,
    `E`, opens `EXIT`, the last word, whose other three cells are not in
    `LOCKED.`; one to three words between are four or five cells.
    """
    if not 3 <= len(words) <= 5 or len(words[0]) != 7 or len(words[-1]) != 4:
        return False
    locked, exit_ = words[0], words[-1]
    return (len(set(locked)) == 7 and len(set(exit_)) == 4
            and exit_[0] == locked[4] and not set(exit_[1:]) & set(locked)
            and all(len(w) in (4, 5) for w in words[1:-1]))


def fight_bar_kind(screen: dosbox.Screen) -> str | None:
    """What a Curse or Silver Blades screen's bar is during `fight`, or None.

    `blank` is a bar row of one colour (a monster's turn, an animation);
    `continue`, `treasure` and `treasure_left` are `route_silver_blades.BARS`'
    measured digests, which Curse shares for its continue bar
    (`CURSE_CONTINUE_BAR`); the rest are read from the bar's words.
    """
    if screen.flat(dosbox.BAR):
        return "blank"
    known = route_silver_blades.BARS.get(screen.glyphs(dosbox.BAR))
    if known in FIGHT_KEYS:
        return known
    words = bar_words(screen)
    # Only an exact digest is safe against a torn bar row; a torn row could
    # in principle repeat cells in the pattern a matcher below looks for.
    if command_words(words):
        return "command"
    if encounter_words(words):
        return "encounter"
    if treasure_words(words):
        return "treasure"
    if continue_battle_words(words):
        return "continue_battle"
    if locked_words(words):
        return "locked"
    if yes_no_words(words):
        return "yes_no"
    return None


#: What `fight` presses at each bar kind.  `QUICK` hands the member at the
#: bar to the computer for the rest of the fight, so the fight runs itself to
#: its end; `COMBAT` at the encounter menu; `EXIT` at the treasure, leaving
#: it where it lies; `NO` at every `YES NO` (the treasure left behind, and
#: any other question the walk meets) and at `CONTINUE BATTLE`, where
#: `Return` would answer YES and start another round; `EXIT` at a locked
#: door, which leaves the party where it stood, so the walk marks that way
#: walled (`Explorer.at`).  A bar not listed is waited out.
FIGHT_KEYS = {"command": "q", "encounter": "c", "continue": "Return",
              "treasure": "e", "treasure_left": "n", "yes_no": "n",
              "continue_battle": "n", "locked": "e"}
#: What a fight after the first in one boot presses once, at its first
#: combat screen, before answering it: a command bar, or a blank bar or one
#: nobody has classified once combat has begun -- the encounter menu was
#: answered, the placement was read, or the combat window (`combat_window`)
#: no longer holds what the last fight left in it and reads as a fight
#: (`_combat_begun`).  Before that, those screens are the walk's own.  `QUICK` survives the end of a fight and goes into
#: the save (every member `QUICK` was pressed for read quickfight 1 in
#: #667's `1c9ea1d9d3-l51-driver-check` save C), so without it the next
#: fight offers nobody a bar.  SPACE at the combat menu or during a QUICK
#: turn sets quickfight 0 for every member whose control byte is below 0x80
#: (Curse `GAME.OVR` 0xAADF-0xAB0C and 0xCD17-0xCD62, Silver Blades 0xBF84
#: and 0xE18F); the encounter menu comes before the fight and is answered
#: first.
HAND_BACK = "space"
#: The kinds that are a combat screen only once combat has begun.
HAND_BACK_AFTER_ENCOUNTER = frozenset({"blank", None})
#: Seconds between two reads of the combat window while a later fight waits
#: to know that combat has begun.
COMBAT_PROBE_SECONDS = 3.0
#: What `--intervene` starts the game with, after `START.EXE`.  Silver Blades'
#: Alt+X handler at the combat command bar (`GAME.OVR` 0xC06D, then 0x18D17)
#: compares `ParamStr(2)` with the Pascal string `Gem` in `START.EXE`'s data
#: segment (`DS:0x190F`) and, on a match, kills every side-1 combatant and
#: ends the acting member's turn; nothing on that path reads `ParamStr(1)`.
#: The first argument is not `Hoop`, whose start-up branch (`START.EXE` image
#: 0x1B4) is unread; any other word leaves start-up as it is.
CHEAT_ARGS = {"ssb": "X Gem"}
#: The screen that ends a lost fight, `THE MONSTERS REJOICE FOR THE PARTY HAS
#: BEEN DESTROYED` over `PRESS ANY KEY TO CONTINUE`: the `glyphs` digest of the
#: bar row and of `PARTY_DESTROYED_LINE`, the message's first text row.  The
#: bar alone is too generic to trust.
PARTY_DESTROYED = ("01364f4c1cd47efa", "e97633ef7e8cf145")
PARTY_DESTROYED_LINE = (16, 40, 288, 8)
#: The titles `fight` drives.
FIGHT_TITLES = frozenset({"pool", "curse", "ssb"})
#: The titles whose `fight` may run a second time in one boot: the later
#: fight hands the party back with `HAND_BACK`, whose handler is read in
#: Curse and Silver Blades only.
SECOND_FIGHT_TITLES = frozenset({"curse", "ssb"})
#: `fight first-bar`: walk into a fight, log the placement and who acts at
#: its first command bar, shoot it and end the run there.
FIRST_BAR = "first-bar"
#: Steps Pool's `fight` walks with `dosfightwatch.walk_to_encounter` before
#: giving up on meeting one.
POOL_FIGHT_WALK_STEPS = 40
#: The Prayer node ids `prayer-watch` tests: 49 is DOS's own Prayer (the
#: control), 35 the id a C64 camp Prayer converts to.
PRAYER_NODES = (35, 49)
#: The titles `prayer-watch` drives, and the ids it tests in each: 35 is
#: Prayer's +1 half only in Pool, and a C64 Prayer converts to 49 in the other
#: two (`dosfightwatch.PRAYER_LAYOUTS` has each title's addresses).
PRAYER_WATCH_NODES = {"pool": (35, 49), "curse": (49,), "ssb": (49,)}
#: `prayer-watch`'s budgets, seconds: the fight work after the encounter menu
#: (which bounds the fight), and the time from the driver's creation to that
#: menu, which is checked once the walk has reached it and does not cut the
#: walk short.  A run's `--deadline` has to hold both and the cleanup.
PRAYER_FIGHT_SECONDS = 600
PRAYER_BOOT_SECONDS = 1500
#: Steps `prayer-watch` tries before giving up on a fight.
PRAYER_WALK_STEPS = 40
#: The step's default budget, seconds, walk and fight together.
FIGHT_SECONDS = 600
#: Seconds the map bar must hold after a fight before the step believes it over.
FIGHT_SETTLED = 4.0
#: Seconds a bar nobody has classified may stay before the run stops.
FIGHT_PATIENCE = 60.0
#: Seconds to wait for a bar to change after its key, and presses before a
#: key the bar never answered stops the run.
FIGHT_DWELL = 8.0
FIGHT_PRESSES = 3


@dataclasses.dataclass(frozen=True)
class CombatLayout:
    """Where a title keeps a fight's combatants: `DS` offsets and record offsets.

    Read from each `GAME.OVR`'s combat setup, which stores each combatant's
    record pointer and then its map entry (Pool 0xE202, Curse 0xF166, Silver
    Blades 0xFE1C: `mov [array+4i], offset / segment`, `mov al, es:[di+side]`,
    `mov [map+4i+2], index`, `mov [map+4i+3], size`), and from the `SPACE`
    handler of the combat menu, which walks the combatant list (the party
    first) from `party_at` through `next_at` and clears `quick_at` wherever
    `control_at` is below 0x80 (Curse 0xAADF, Silver Blades 0xBF84).  `selected_at` is the pointer
    the overlays load most (`les di, [selected_at]`: Pool 202 sites, Curse
    288, Silver Blades 315); Curse's is `player_ptr` in the reconstruction's
    listing.  Pool's setup (0xE1C2-0xE3D9) sets `[map_at+3]` to 1, walks the
    list from `party_at` through `next_at`, and stores the pointer at
    0xE202, the index at 0xE223 and the size (record `0x6C` and 7) at
    0xE23D; its control byte is the one `Attack Ally` tests for 0x80
    (`docs/169-dos-combat-side.md`).
    """

    #: Four bytes per combatant, from entry 1: x, y, index, size.  Entry 0's
    #: fourth byte is one more than the count: the setup sets it to 1 and adds
    #: one after storing each combatant (Curse 0xF11B, 0xF2A7, 0xF31C; Silver
    #: Blades 0xFDD4, 0xFF7A, 0xFFEC), so it names the next free entry.
    map_at: int
    #: A far pointer (offset, segment) per combatant to its record, from entry 1.
    array_at: int
    selected_at: int
    party_at: int
    next_at: int
    control_at: int
    #: Status, active, side (0 the party's, 1 the enemy's), quickfight.
    status_at: int
    hp_at: int


COMBAT_LAYOUTS = {
    "pool": CombatLayout(map_at=0x5F27, array_at=0x65B9, selected_at=0x5D92,
                         party_at=0x5D96, next_at=0x104, control_at=0x84,
                         status_at=0x10C, hp_at=0x11B),
    "curse": CombatLayout(map_at=0x66BD, array_at=0x6D4F, selected_at=0x6520,
                          party_at=0x6524, next_at=0x189, control_at=0xF7,
                          status_at=0x195, hp_at=0x1A4),
    "ssb": CombatLayout(map_at=0x7EDF, array_at=0x8571, selected_at=0x7D38,
                        party_at=0x7D3C, next_at=0x19D, control_at=0xFF,
                        status_at=0x1A6, hp_at=0x1B5),
}
#: The most combatants a map holds: its count is one byte.
MAX_COMBATANTS = 255
#: What `placement` logs of each combatant, as the C64 driver's event does,
#: with the record's own status, active, quickfight and control bytes.
PLACEMENT_FIELDS = ("name", "index", "slot", "position", "size", "on_map", "hp",
                    "status", "active", "side", "quickfight", "control", "party",
                    "raw_name")
#: Shots of bars nobody has classified, per fight: an animation can show a
#: new digest on every look.
FIGHT_UNKNOWN_SHOTS = 5


class CombatUnread(ValueError):
    """The bytes read are not a live fight's combatants (a wrong `DS`)."""


def combat_window(layout: CombatLayout) -> tuple[int, int]:
    """The one `DS` range holding the map, the pointers, the selected member
    and the party head: its start and length."""
    lo = min(layout.map_at, layout.array_at, layout.selected_at, layout.party_at)
    hi = max(layout.map_at, layout.array_at) + 4 * (MAX_COMBATANTS + 1)
    return lo, hi - lo


def far_pointer(raw: bytes) -> tuple[int, int]:
    """(segment, offset) of a stored far pointer, offset first."""
    return int.from_bytes(raw[2:4], "little"), int.from_bytes(raw[0:2], "little")


def read_combat(window: bytes, base: int, layout: CombatLayout) -> dict:
    """The combatants in a `combat_window` read from `base`.

    Entry 0's fourth byte is one more than the count (`CombatLayout.map_at`),
    so the combatants are entries 1 to that byte less one.  Raises
    `CombatUnread` for a byte that leaves no combatant or a combatant with no
    record, which is what the window holds under a `DS` that is not the game's.

    A dead member reads `on_map` False (size 0) although a fallen figure is
    drawn, so judge placement from `position`, not `on_map`.
    """
    def at(offset: int, n: int) -> bytes:
        return window[offset - base:offset - base + n]

    count = at(layout.map_at + 3, 1)[0] - 1
    if count < 1:
        raise CombatUnread(f"the combat map's count is {max(count, 0)}")
    combatants = []
    for i in range(1, count + 1):
        x, y, index, size = at(layout.map_at + 4 * i, 4)
        pointer = far_pointer(at(layout.array_at + 4 * i, 4))
        if pointer == (0, 0):
            raise CombatUnread(f"combatant {i} of {count} has no record")
        combatants.append({"index": i, "position": [x, y], "size": size,
                           "on_map": size != 0, "map_index": index,
                           "pointer": list(pointer)})
    selected = far_pointer(at(layout.selected_at, 4))
    return {"count": count, "combatants": combatants,
            "selected": next((c["index"] for c in combatants
                              if tuple(c["pointer"]) == selected), None),
            "selected_pointer": list(selected),
            "party_head": list(far_pointer(at(layout.party_at, 4)))}


def c_record(read_now: dict, known: dict, ptr: tuple[int, int]) -> dict:
    """A combatant's record as just read, or as read at an earlier bar."""
    return read_now[ptr] if ptr in read_now else known[ptr]


def combatant_record(record: bytes, layout: CombatLayout) -> dict:
    """A combatant record's name and the bytes that say whose side it fights on.

    A name that is not a Pascal string of 1 to 15 printable bytes (a monster
    record laid out otherwise) gives `name` None and the record's first 16
    bytes as `raw_name`, so one odd record never ends a fight's reading.
    """
    n = record[0] if record else 0
    name = record[1:1 + n]
    status, active, side, quick = record[layout.status_at:layout.status_at + 4]
    out = {"name": name.decode("latin-1"), "status": status, "active": active,
           "side": side, "quickfight": quick,
           "control": record[layout.control_at], "hp": record[layout.hp_at]}
    if not 1 <= n <= 15 or not all(0x20 <= b < 0x7F for b in name):
        out.update(name=None, raw_name=record[:16].hex())
    return out


def loose_halve(screen: dosbox.Screen) -> dosbox.Screen:
    """A DOSBox-X grab (640x400) as 320x200 by each block's top-left pixel.

    `dosboxx.halve` blocks a grab torn between two blits; this takes it,
    for the rows `fight` reads, which the tear does not reach while only the
    picture moves.  A frame already 320 wide is returned as it is.
    """
    if screen.width < 640 or screen.width % 2 or screen.height % 2:
        return screen
    w, h = screen.width // 2, screen.height // 2
    stride = screen.width * 3
    out = bytearray(w * h * 3)
    for y in range(h):
        top = screen.px[2 * y * stride:(2 * y + 1) * stride]
        row = bytearray(w * 3)
        row[0::3], row[1::3], row[2::3] = top[0::6], top[1::6], top[2::6]
        out[y * w * 3:(y + 1) * w * 3] = row
    return dosbox.Screen(w, h, bytes(out))


#: Pool of Radiance's party square in the game's data segment: x, y and the
#: facing doubled (0 N, 2 E, 4 S, 6 W), the engine's own copy that the VM
#: hands back as `$C04B`-`$C04D` (`GAME.OVR` 0x83CA-0x8416) and the save
#: writes at 12801 (`docs/163-dos-vm-address-map.md`).
POOL_PLACE = 0x6AAD


def pool_place(raw: bytes) -> dict | None:
    """x, y and facing 0-3 from `POOL_PLACE`'s three bytes, or None when the
    facing byte is not a doubled facing (the data segment is not the game's)."""
    x, y, facing = raw[:3]
    if facing not in (0, 2, 4, 6) or x > 0x3F or y > 0x3F:
        return None
    return {"x": x, "y": y, "facing": facing // 2}


#: Pool of Radiance's current-area byte in the data segment: the start-up
#: copy `les di, [0x49D2]; mov al, es:[di+0x1E4]; mov [0x84DC], al`, read 20
#: in the Slums in a running game.  The live VM word `$49F2` is the area the
#: party came from, not the one it is in.
POOL_AREA = 0x84DC
#: Pool's message window: the text rows inside the frame under the picture,
#: where a story box, the temple's question and its price are drawn.
POOL_MESSAGE_ROWS = range(17, 23)

#: Pool's temple, as the DOS game draws it (`GAME.OVR` strings 0x4578-0x4A7D
#: and 0x51DF; captured in New Phlan at 1,3 facing N, area 0): the question
#: the party's arrival asks, the temple bar, the service list's bar and its
#: rows (text rows 4 to 13, the highlight white), the price prompt's bar, and
#: the keys: `y` YES, `h` HEAL, `v` VIEW, `e` EXIT, `Escape` from the sheet,
#: and `dosbox.LIST_DOWN` down the list.
TEMPLE_ARRIVAL = "DO YOU SEEK HEALING"
TEMPLE_BAR = "HEAL VIEW POOL APPRAISE EXIT"
TEMPLE_LIST_BAR = "HEAL EXIT"
TEMPLE_PRICE_BAR = "PAY FOR CURE YES NO"
TEMPLE_LIST_ROWS = range(4, 14)
#: The service list's title row, `<NAME>, HOW CAN WE HELP YOU?`.
TEMPLE_TITLE_ROW = 1
TEMPLE_LIST_RECT = (16, 32, 288, 80)
TEMPLE_RAISE = "RAISE DEAD"
TEMPLE_YES, TEMPLE_HEAL, TEMPLE_VIEW, TEMPLE_EXIT = "y", "h", "v", "e"
TEMPLE_SHEET_BACK = "Escape"
#: `RAISE DEAD WILL ONLY COST 5500 GOLD PIECES.`
TEMPLE_PRICE = re.compile(r"COST (\d+) (\w+) PIECES")
#: What the message window says after `YES` at the price, to the outcome:
#: `Not enough money.` (0x461B), upper case as drawn.  A raise draws no
#: message: the handler (`GAME.OVR` 0x4A88-0x4CA4) takes a status 6 (dead) or
#: 1 member, asks the price (0x4636, 5500 gold), removes effect ids 32 and 55,
#: and sets hit points 1 (0x4B5C), status 0, active 1 and constitution one
#: lower, with no roll, so a raise that was paid for cannot fail.
TEMPLE_OUTCOMES = (("NOT ENOUGH MONEY", "no-money"),)
#: The hit points the raise leaves, which the temple's roster line then draws.
TEMPLE_RAISED_HP = 1
#: Seconds `temple raise` watches the message window after `YES`, and how
#: long the list must hold unchanged before the watch ends.
TEMPLE_RESULT_SECONDS = 20.0
TEMPLE_RESULT_HOLD = 3.0
#: The only record bytes `--stage-record` may write in a run with `temple
#: raise`: Pool's gold (`0x08E`, two bytes little-endian) for the payment and
#: constitution (`0x014`), which keeps the raised character above the minimum
#: after the raise's one-point loss.
TEMPLE_STAGE_FIELDS = {0x08E: "gold", 0x08F: "gold", 0x014: "constitution"}
#: The money words a Pool sheet draws, and where: text rows 7 to 12, columns
#: 1 to 26, left of the portrait's frame.
SHEET_MONEY = re.compile(r"\b(COPPER|SILVER|ELECTRUM|GOLD|PLATINUM|GEMS|JEWELRY) (\d+)")
SHEET_MONEY_ROWS = range(7, 13)


def map_square(screen: dosbox.Screen, column: int) -> str | None:
    """`status_square`, or None when the line has no `x,y` token.

    A line reads `x,y facing clock`; some views draw only `facing clock`,
    whose first token would otherwise be read as a square.  Fewer than three
    blank-separated tokens means the position is unknown.
    """
    x0, y, w, h = dosbox.STATUS
    tokens, inside = 0, False
    for x in range(column, x0 + w, CELL):
        lit = not screen.flat((x, y, CELL, h))
        tokens += lit and not inside
        inside = lit
    return status_square(screen, column) if tokens >= 3 else None


class Explorer:
    """Where `fight` walks next, from the squares it has stood on.

    The status line gives a square's identity (`status_square`, a digest)
    and never its coordinates, so this keeps what each tried direction led
    to and prefers, in order, a direction never tried from here, then the
    neighbour stood on least, taking ahead, right, left and back in that
    order among equals.  Directions are counted from the facing the walk
    began at, a right turn adding one.
    """

    ORDER = (0, 1, 3, 2)
    BLOCKED = "blocked"

    def __init__(self) -> None:
        self.facing = 0
        self.square: str | None = None
        self.edges: dict[tuple[str, int], str] = {}
        self.visits: dict[str, int] = {}
        self.steps = 0
        self.bumps = 0
        #: The square and direction of a step in flight: set before `Up`,
        #: settled by `stepped`, or by `at` when the step showed a screen
        #: (a message, a question) and the square had to be read again.
        self.pending: tuple[str, int] | None = None

    def at(self, square: str) -> None:
        """Stand on `square`.  After a step that showed a screen, the
        direction tried leads here, or is walled when the party never left,
        so a prompt declined is not walked into again and again."""
        if self.pending is not None:
            start, d = self.pending
            self.pending = None
            if square == start:
                self.edges[(start, d)] = self.BLOCKED
                self.bumps += 1
            else:
                self.edges[(start, d)] = square
                self.steps += 1
        self.square = square
        self.visits[square] = self.visits.get(square, 0) + 1

    def stepping(self) -> None:
        self.pending = None if self.square is None else (self.square, self.facing)

    def choose(self) -> int:
        best = None
        for rel in self.ORDER:
            d = (self.facing + rel) % 4
            led = self.edges.get((self.square, d))
            if led == self.BLOCKED:
                continue
            score = -1 if led is None else self.visits.get(led, 0)
            if best is None or score < best[0]:
                best = (score, d)
        if best is None:
            raise StepFailed("the walk is walled in on all four sides")
        return best[1]

    def turn_keys(self, d: int) -> list[str]:
        return {0: [], 1: ["Right"], 2: ["Right", "Right"],
                3: ["Left"]}[(d - self.facing) % 4]

    def turned(self, key: str) -> None:
        self.facing = (self.facing + (1 if key == "Right" else -1)) % 4

    def stepped(self, square: str | None) -> bool:
        """The square after `Up`; whether the party moved."""
        self.pending = None
        if square is None or self.square is None:
            if square is not None:
                self.at(square)
            return False
        if square == self.square:
            self.edges[(self.square, self.facing)] = self.BLOCKED
            self.bumps += 1
            return False
        self.edges[(self.square, self.facing)] = square
        self.steps += 1
        self.at(square)
        return True


def class_tables(start_exe: bytes) -> bytes:
    """The data segment of Curse's `START.EXE`, where 0x3BB4D's tables are."""
    from tools.dos import dosspellslots, unexepack
    try:
        image, _ = unexepack.unpack(start_exe)
    except ValueError:
        image = start_exe[int.from_bytes(start_exe[8:10], "little") * 16:]
    return image[dosspellslots.data_segment(image) * 16:]


def class_name(ds: bytes, cid: int) -> str:
    at = CLASS_NAMES_AT + CLASS_NAME_SIZE * cid
    return ds[at + 1:at + 1 + ds[at]].decode("latin-1").upper()


def class_choices(record: bytes, ds: bytes) -> list[tuple[int, str]]:
    """The classes 0x3BB4D lists for `record`, in the list's order, or none
    when the party menu does not offer it the command.

    The menu offers it (0x2022A-0x20252) only to a human (0xFE:0x3E, race 7)
    who has not changed class before (0xFE:0x43, the same reading as the
    current class over the former-class array, must find none).  The list is
    the race's table in order, keeping each class 0x3B99E passes: not the
    current class (0x3BF66, the first class level that is not zero, when it
    is above zero, for a human); every ability the current class's minima
    mark above `KEEP_ABOVE`; every ability the new class's mark above
    `TAKE_ABOVE`; and the member's alignment among the new class's.
    """
    from goldbox import dos_port
    fields = dos_port.FIELDS_BY_NAME_FOR["curse-of-the-azure-bonds"]
    race = record[fields["race"].offset]

    def first_class(field: str) -> int:
        at = fields[field].offset
        levels = record[at:at + 8]
        first = next((i for i in range(7) if levels[i]), 7)
        return first if 0 < levels[first] < 0x80 else NO_CLASS

    if race != HUMAN_RACE or first_class("former_class_levels") != NO_CLASS:
        return []
    abilities = [record[fields[a].offset] for a in ABILITIES]
    alignment = record[fields["alignment"].offset]
    current = first_class("class_levels")

    def meets(cid: int, above: int) -> bool:
        at = CLASS_MINIMA_AT + CLASS_MINIMA_SIZE * cid
        return all(ds[at + k] < REQUISITE or abilities[k] > above for k in range(6))

    table = RACE_CLASSES_AT + RACE_CLASSES_SIZE * race
    out = []
    for idx in range(1, ds[table] + 1 if ds[table] < 0x80 else 1):
        cid = ds[table + idx]
        aligned = CLASS_ALIGNMENTS_AT + CLASS_ALIGNMENTS_SIZE * cid
        allowed = ds[aligned + 1:aligned + 1 + ds[aligned]]
        if (cid != current and meets(current, KEEP_ABOVE) and meets(cid, TAKE_ABOVE)
                and alignment in allowed):
            out.append((cid, class_name(ds, cid)))
    return out


def status_column(title: str) -> int:
    """The pixel column `title`'s status token starts at, or a rejection."""
    try:
        return STATUS_COLUMNS[title]
    except KeyError:
        raise StepFailed(
            f"{title}'s status-line column is unmeasured (no DOS capture of it "
            "has been read), so its square cannot be read; the measuring boot "
            "of #679 package 7 supplies it") from None


def _cells(screen: dosbox.Screen, x: int, y: int, count: int,
           height: int = POD_NAME_ROWS) -> list[str]:
    """`count` character cells from `(x, y)`, each `Screen.glyphs` against its
    own paper, so a highlighted cell reads as the same letter unlit."""
    return [screen.glyphs((x + CELL * i, y, CELL, height)) for i in range(count)]


_BLANK_CELL = dosbox.Screen(CELL, POD_NAME_ROWS, bytes(CELL * POD_NAME_ROWS * 3)).glyphs()


def _cell_digest(cells: list[str]) -> str:
    return hashlib.sha1("".join(cells).encode()).hexdigest()[:16]


def name_cells(screen: dosbox.Screen, where: str, line: int) -> list[str]:
    """Roster line `line`'s name at the party menu or in camp, cell by cell,
    without trailing blanks."""
    x, y = POD_ROSTER[where]
    cells = _cells(screen, x, y + CELL * (line - 1), POD_NAME_CELLS)
    while cells and cells[-1] == _BLANK_CELL:
        cells.pop()
    return cells


def roster_cells(screen: dosbox.Screen, line: int) -> list[str]:
    """Camp roster line `line`'s name, cell by cell, without trailing blanks."""
    return name_cells(screen, "camp", line)


def sheet_header(screen: dosbox.Screen, name: list[str],
                 font: dict[bytes, str]) -> str | None:
    """`NPC_HEADER` when the sheet on `screen` draws `name` (`name_cells`),
    two blank cells and `(NPC)` read with the title's `font`, and nothing
    else in the name's fifteen cells; otherwise None."""
    if not name:
        return None
    x, y = POD_SHEET_NAME
    cells = _cells(screen, x, y, POD_NAME_CELLS)
    at = len(name) + NPC_HEADER_GAP
    if cells[:len(name)] != name or any(c != _BLANK_CELL for c in cells[len(name):at]):
        return None
    text = "".join(read_cell(screen, x + CELL * (at + i), y, font)
                   for i in range(len(NPC_HEADER)))
    if text != NPC_HEADER:
        return None
    if any(c != _BLANK_CELL for c in cells[at + len(NPC_HEADER):]):
        return None
    return NPC_HEADER


def grimoire_is_for(screen: dosbox.Screen, name: list[str]) -> bool:
    """Whether the grimoire's title opens with `name` and then `'S`."""
    if not name:
        return False
    title = _cells(screen, *GRIMOIRE_TITLE, len(name) + 2)
    return (title[:len(name)] == name and hashlib.sha1(
        "".join(title[len(name):]).encode()).hexdigest()[:16] == GRIMOIRE_POSSESSIVE)


def on_grimoire(screen: dosbox.Screen) -> bool:
    return bar_signature(screen, POD_GRIMOIRE_HEAD_CELLS) == POD_GRIMOIRE_HEAD


def grimoire_rows(screen: dosbox.Screen) -> list[str]:
    """Each of the list's eleven rows as one signature of its cells, blind to
    the highlight, comparable with `NINTH_LEVEL_ROW` and `GRIMOIRE_SPELLS`."""
    x, y = GRIMOIRE_ROWS_AT
    return [hashlib.sha1("".join(_cells(screen, x, y + CELL * k, GRIMOIRE_ROW_CELLS,
                                        CELL)).encode()).hexdigest()[:16]
            for k in range(GRIMOIRE_ROW_COUNT)]


def ninth_level(rows: list[str]) -> list[int | str]:
    """The rows after the `9TH LEVEL` header, as spell ids where the row is
    one of `GRIMOIRE_SPELLS` and as its signature where it is not."""
    if NINTH_LEVEL_ROW not in rows:
        return []
    after = rows[rows.index(NINTH_LEVEL_ROW) + 1:]
    return [GRIMOIRE_SPELLS.get(r, r) for r in after]










#: The walks each title drives: `MI`, two turns and a step at the map bar (Pool,
#: Curse); `I`, one step forward without turning (Pool, for a party already
#: facing open ground); `1`, a step in move mode (Silver Blades, Pools of Darkness).
WALKS = {"pool": ("MI", "I"), "curse": ("MI",), "ssb": ("1",), "darkness": ("1",)}
#: Pool's other walks: a run of `I` (step forward), `J` (turn left) and `K`
#: (turn right), each judged from the party's place in memory, as the C64
#: driver's moves are named.
POOL_WALK_LETTERS = re.compile(r"[IJK]+")
#: The titles whose `turn N` control is driven: those with a walk to check.
TURNS = frozenset(WALKS)
#: The titles whose party menu `view N` opens a sheet from.  Pool's party
#: menu is reached by `add`, since its load puts the party on the map.
VIEWS = frozenset({"curse", "ssb", "darkness", "pool"})
#: The titles whose camp `leave` exits to the map, and its key.  The camp
#: loop of Curse (`GAME.OVR` 0x1B41F-0x1B43B) runs until the menu returns a
#: key in the set at 0x1B362, which holds only 0 and `E`.  Silver Blades
#: holds the same set at 0x1D113, after the same camp message; its loop is
#: not read.
#: Pool of Radiance's camp `Exit` is exit to DOS, and Pools of Darkness'
#: camp loop is unread.
LEAVE_TITLES = frozenset({"curse", "ssb"})
CAMP_EXIT = "e"
#: What a sheet draws two cells after the name of a character whose control
#: byte is above 0x7F: Curse `GAME.OVR` 0x27112-0x27140 tests record 0xF7
#: and draws `(NPC)` at text column name length + 3, the name starting at 1.
NPC_HEADER = "(NPC)"
NPC_HEADER_GAP = 2


def pod_menu_after(savgam: bytes | None) -> dict[str, int]:
    """The party menu's `view`, `save` and `begin` rows after loading `savgam`.

    With a party loaded the enabled entries are, in order, Create, Drop,
    Modify, [Train, Human Change], View, Add, Remove, Save, Begin, Exit; the
    bracketed two only when `POD_TRAIN_BYTE` is set.  A missing save gives
    the rows without them.
    """
    shift = 2 if savgam and len(savgam) > POD_TRAIN_BYTE and savgam[POD_TRAIN_BYTE] else 0
    return {k: v + shift for k, v in POD_MENU_AFTER.items()}


@dataclasses.dataclass(frozen=True)
class RestKeys:
    days: str
    hours: str
    mins: str
    inc: str
    dec: str
    go: str


#: Curse's and Silver Blades' rest menu, `Rest Days Hours Mins Add Subtract
#: Exit` (Curse `GAME.OVR` 0x2B461, Silver Blades 0x2BD1D).
LATER_REST = RestKeys("d", "h", "m", "a", "s", "r")


@dataclasses.dataclass(frozen=True)
class Title:
    """What differs between the three titles in the steps this driver runs."""

    key: str
    #: The game directory stem `dosbox.find_game` looks for.
    stem: str
    #: `map` when `LOAD SAVED GAME` puts the party on the map, `party` when it
    #: leaves it at the party menu with `BEGIN ADVENTURING` still to press.
    loads_to: str
    #: Pool's city watch `GO STAY` event can end a rest.
    watch: bool
    #: `train N` is driven; Silver Blades' training keys are unread.
    trains: bool
    #: What the DOSBox autoexec runs.
    exe: str = "START.EXE"
    #: The saved game's suffix: `SAVGAM<slot>.DAT`, or Pools of Darkness'
    #: `SAVGAM<slot>.PTY` with a `VAULT<slot>.DAT` beside it.
    suffix: str = ".DAT"

    def rest_keys(self) -> RestKeys:
        if self.key == "pool":
            return RestKeys(REST_DAYS, REST_HOURS, REST_MINS, REST_INC,
                            REST_DEC, REST_GO)
        return LATER_REST

    def find_game(self) -> pathlib.Path:
        """The title's directory in the archives, found by its launcher."""
        if self.exe == "START.BAT":
            return dospod.find_game(self.stem)
        return dosbox.find_game(self.stem)


TITLES = {
    "pool": Title("pool", "POOLRAD", "map", True, False),
    "curse": Title("curse", "CURSE", "party", False, True),
    "ssb": Title("ssb", "SECRET", "party", False, False),
    # `Load Saved Game` is a party-menu entry here as in Curse and Silver
    # Blades, and both leave the party at that menu after a load, so this
    # title's `loads_to` is `party`, as the foundation boots show.  The
    # container names its own `CHRDAT` files and the engine loads those, not
    # the letter picked (`docs/141-dos-savegame.md`, 12809-13136), so a
    # renamed slot would load nothing.
    "darkness": Title("darkness", "DARKNESS", "party", False, False,
                      exe="START.BAT", suffix=".PTY"),
}

def launch_args(title: Title, intervene: bool = False) -> dict[str, str]:
    """The `exe` a session for `title` is started with, in either emulator.

    `START.EXE` is `Session`'s own default, so only another launcher is
    named.  `intervene` adds the title's `CHEAT_ARGS`.
    """
    exe = f"{title.exe} {CHEAT_ARGS[title.key]}" if intervene else title.exe
    return {} if exe == "START.EXE" else {"exe": exe}


#: The `dosnoencounters` title each `--no-encounters` run names.
NO_ENCOUNTER_TITLES = {"pool": dosnoencounters.POOL,
                       "curse": dosnoencounters.CURSE,
                       "ssb": dosnoencounters.SILVER,
                       "darkness": dosnoencounters.DARKNESS}

#: The C64 party `--fixture-row` stages into for each later title: an
#: engine-written save in `$WISH_SPECIMENS/por-c64/` (`docs/235` §4).  Pool
#: of Radiance uses the committed fixture party instead.
C64_BASES = {
    "curse": "WISH-SPEC-curse-h-engine-resave.D64",
    "ssb": "WISH-SPEC-ssb-d-engine-resave.D64",
}

#: The effect files of the three titles (`dos_codec.read_character`).
EFFECT_SUFFIXES = (".SPC", ".FX", ".SFX")


class StepFailed(RuntimeError):
    """A step did not reach the screen or the file it waits for."""


class DeadlineReached(TimeoutError):
    """The run's route window is over; what is left belongs to the cleanup."""


class Terminated(BaseException):
    """The wrapper's `timeout` sent SIGTERM.

    A `BaseException`, so that no `except Exception` on the way -- the failure
    capture's, a step's -- can swallow it and leave the run going with the
    signal already ignored.
    """


#: The run's whole budget, and the part of it kept for the cleanup (the
#: failure capture, the shots and the resave copied out, the emulator stopped).
#: The wrapper's own `timeout` is a backstop at least `WRAPPER_MARGIN` seconds
#: longer than the deadline, so the driver, not the wrapper, ends the run.
DEADLINE_SECONDS = 900.0
CLEANUP_SECONDS = 120.0
WRAPPER_MARGIN = 300.0
#: The longest single wait that is not cut to the route window: a settle's
#: `timeout=90.0`.  The cleanup and one such wait, begun just inside the route
#: window, must both fit in `WRAPPER_MARGIN`, or the wrapper's `timeout` ends the
#: run before the driver has written its summary.
LONGEST_UNBOUNDED_WAIT = 90.0
#: The longest one capture or key press takes, with room to spare: a wait with
#: less than this left does not start another.
ACTION_SECONDS = 5.0


class Deadline:
    """The route window of a run: `seconds` from the start less `cleanup`.

    The cleanup is never more than half the budget.  `clock` is injectable so
    a test can pass the deadline without waiting.
    """

    def __init__(self, clock, seconds: float, cleanup: float = CLEANUP_SECONDS):
        self.clock, self.seconds = clock, float(seconds)
        self.cleanup = min(float(cleanup), self.seconds / 2)
        if self.cleanup + LONGEST_UNBOUNDED_WAIT > WRAPPER_MARGIN:
            raise ValueError(
                f"a cleanup window of {self.cleanup:.0f} s and an unbounded wait "
                f"of {LONGEST_UNBOUNDED_WAIT:.0f} s exceed the {WRAPPER_MARGIN:.0f} s "
                "the wrapper's `timeout` is given beyond the deadline")
        self.begun = clock()
        self.route_end = self.begun + self.seconds - self.cleanup

    def left(self) -> float:
        return self.route_end - self.clock()

    def check(self, label: str) -> None:
        """Stop the route when less than one action's time is left."""
        if self.left() < ACTION_SECONDS:
            raise DeadlineReached(
                f"the route window of {self.seconds - self.cleanup:.0f} s is over "
                f"during {label} (the deadline is {self.seconds:.0f} s, "
                f"{self.cleanup:.0f} s of it for the cleanup)")

    def bound(self, wait: float, label: str) -> float:
        """`wait`, cut to the route time left; never a remainder shorter than an action."""
        self.check(label)
        return min(wait, self.left())


# --------------------------------------------------------------------------
# Pure parts: steps, durations, screens, staging, and reading a save
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Step:
    kind: str
    text: str
    minutes: int = 0
    letter: str = ""
    name: str = ""
    line: int = 0
    key: str = ""
    row: int = 0
    seconds: int = 0
    node: int = 0
    to: int = 0


_DURATION = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$")


def parse_duration(text: str) -> int:
    """`5m`, `8h`, `2d` or a run of them such as `1h30m`, in minutes."""
    m = _DURATION.match(text.strip().lower())
    if not text.strip() or m is None or not any(m.groups()):
        raise ValueError(f"not a duration: {text!r} (say 5m, 8h, 2d or 1h30m)")
    d, h, mins = (int(g or 0) for g in m.groups())
    return (d * 24 + h) * 60 + mins


def rest_presses(minutes: int) -> tuple[int, int, int]:
    """(days, hours, five-minute presses) that set a rest of `minutes`."""
    if minutes <= 0:
        raise ValueError("a rest must be longer than no time at all")
    if minutes % REST_STEP:
        raise ValueError(f"the rest menu sets minutes in fives; {minutes} is not one")
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days > REST_DAYS_MAX:
        raise ValueError(f"the rest menu holds at most {REST_DAYS_MAX} days")
    return days, hours, mins // REST_STEP


STEP_HELP = ("load, begin, vault, 'walk MI', 'walk I', 'walk 1', 'turn 4', camp, leave, "
             "display, "
             "'rest 5m', 'save D', "
             "'train 1', 'change 2 FIGHTER', 'sheet 1', 'heal 1', 'cure 1', 'items 1', "
             "'halve 1 1', 'join 4 15', 'trade 1 2 3', 'view 1', 'memorize 5', 'cast 2 BLESS', "
             "'cast 2 RESIST-COLD 4', 'scribe 5 PROTECTION FROM GOOD', 'shot NAME', "
             "'press KEY', 'fight', 'fight 900', 'fight first-bar', 'prayer-watch 49', "
             "'add ARRONEL', 'walk KKIIJI', 'temple raise 1', "
             "'snapshot NAME', 'restore NAME', 'deposit 5 2', read")
#: The class names `change N CLASS` takes: Curse's own (`START.EXE` data
#: 0x0CB8), upper case.
CHANGE_CLASSES = ("CLERIC", "DRUID", "FIGHTER", "PALADIN", "RANGER", "MAGIC-USER",
                  "THIEF", "MONK")


def parse_step(text: str) -> Step:
    words = text.split()
    if not words:
        raise ValueError("an empty step")
    kind = words[0].lower()
    if kind in ("load", "begin", "camp", "leave", "display", "vault",
                "read") and len(words) == 1:
        return Step(kind, text)
    deposit = parse_deposit(words, text)
    if deposit is not None:
        return deposit
    if kind == "rest" and len(words) == 2:
        minutes = parse_duration(words[1])
        rest_presses(minutes)
        return Step(kind, text, minutes=minutes)
    if kind == "save" and len(words) == 2 and re.fullmatch(r"[A-Ja-j]", words[1]):
        return Step(kind, text, letter=words[1].upper())
    if kind in ("train", "sheet", "items", "view", "memorize", "heal", "cure") and len(
            words) == 2 and re.fullmatch(r"[1-8]", words[1]):
        return Step(kind, text, line=int(words[1]))
    if kind == "cast" and len(words) >= 3 and re.fullmatch(r"[1-8]", words[1]):
        name, target = words[2:], 0
        if len(name) > 1 and re.fullmatch(r"\d+", name[-1]):
            if not re.fullmatch(r"[1-8]", name[-1]):
                raise ValueError(f"cast target line {name[-1]} is blocked: the roster "
                                 f"has lines 1 to 8: {text!r}")
            target = int(name.pop())
        spell = "-".join(spell_key(" ".join(name)).split())
        return Step(kind, text, line=int(words[1]), name=spell, row=target)
    if kind == "scribe" and len(words) >= 3 and re.fullmatch(r"[1-8]", words[1]):
        spell = spell_key(" ".join(words[2:]))
        if SCRIBE_MARK in spell:
            raise ValueError(f"scribe {spell!r} is blocked: name the spell without "
                             f"the {SCRIBE_MARK} the list draws on one being scribed")
        return Step(kind, text, line=int(words[1]), name=spell)
    if kind == "change" and len(words) == 3 and re.fullmatch(r"[1-8]", words[1]):
        if words[2].upper() not in CHANGE_CLASSES:
            raise ValueError(f"change to {words[2]!r} is blocked: the class is one "
                             f"of {', '.join(CHANGE_CLASSES)}")
        return Step(kind, text, line=int(words[1]), name=words[2].upper())
    if kind in ("halve", "join") and len(words) == 3 and re.fullmatch(
            r"[1-8]", words[1]) and re.fullmatch(r"\d+", words[2]):
        row = int(words[2])
        if not 1 <= row <= ITEM_ROWS:
            raise ValueError(f"{kind} row {row} is blocked: the list shows rows 1 to "
                             f"{ITEM_ROWS} and the rows past them need Next, which "
                             "is not driven here")
        return Step(kind, text, line=int(words[1]), row=row)
    if kind == "trade" and len(words) == 4 and re.fullmatch(
            r"[1-8]", words[1]) and re.fullmatch(r"\d+", words[2]) and re.fullmatch(
            r"[1-8]", words[3]):
        row, to = int(words[2]), int(words[3])
        if not 1 <= row <= ITEM_ROWS:
            raise ValueError(f"trade row {row} is blocked: the list shows rows 1 to "
                             f"{ITEM_ROWS}")
        if to == int(words[1]):
            raise ValueError(f"trade {text!r} is blocked: line {to} would trade "
                             "with itself")
        return Step(kind, text, line=int(words[1]), row=row, to=to)
    if kind == "walk" and len(words) == 2 and (any(
            words[1].upper() in routes for routes in WALKS.values())
            or POOL_WALK_LETTERS.fullmatch(words[1].upper())):
        return Step(kind, text, key=words[1].upper())
    if kind == "turn" and len(words) == 2 and re.fullmatch(r"[1-4]", words[1]):
        return Step(kind, text, line=int(words[1]))
    if kind == "shot" and len(words) == 2 and re.fullmatch(r"[\w-]+", words[1]):
        return Step(kind, text, name=words[1])
    if kind in ("snapshot", "restore") and len(words) == 2:
        if not dossnapshot.SNAPSHOT_NAME.match(words[1]):
            raise ValueError(f"{text!r}: a snapshot name is letters, digits, - and _")
        return Step(kind, text, name=words[1])
    if kind == "fight" and len(words) == 2 and words[1].lower() == FIRST_BAR:
        return Step(kind, text, name=FIRST_BAR)
    if kind == "fight" and (len(words) == 1 or (
            len(words) == 2 and re.fullmatch(r"[1-9]\d*", words[1]))):
        return Step(kind, text, seconds=int(words[1]) if len(words) == 2 else 0)
    if kind == "temple" and len(words) == 3 and words[1].lower() == "raise" \
            and re.fullmatch(r"[1-8]", words[2]):
        return Step(kind, text, name="raise", line=int(words[2]))
    if kind == "prayer-watch" and len(words) == 2 and words[1] in (
            str(n) for n in PRAYER_NODES):
        return Step(kind, text, node=int(words[1]))
    if kind == "add" and len(words) >= 2:
        name = " ".join(words[1:]).upper()
        if len(name) > POD_NAME_CELLS or name.startswith("*"):
            raise ValueError(f"add {name!r} is blocked: a name is at most "
                             f"{POD_NAME_CELLS} characters and is given without "
                             "the * the list draws on one already picked")
        return Step(kind, text, name=name)
    if kind == "press" and len(words) == 2 and re.fullmatch(r"\w+", words[1]):
        if words[1].lower() in ("e", "escape"):
            raise ValueError(f"press {words[1]} is blocked: E is exit to DOS at "
                             "Curse's party menu and Escape backs out of a prompt")
        return Step(kind, text, key=words[1])
    raise ValueError(f"not a step: {text!r} ({STEP_HELP})")


def validate_steps(steps: list[Step], title: str = "pool") -> None:
    """Block an order the driver would only find out after booting DOSBox.

    The party is somewhere at each step -- not yet loaded, on the map, at the
    party menu or in camp -- and each step needs one of those.  `shot` and
    `read` need nothing.  After a `press` nobody knows where the party is,
    so only more `press`, `shot` and `read` may come after it, or a `snapshot`
    or `restore` (a restore puts back where its snapshot was), and after
    `fight first-bar`, which ends the run at a fight's first command bar,
    only `shot` and `read`.
    """
    t = TITLES[title]
    where = "boot"
    last = None
    #: Each snapshot taken so far, by name: whether a `save` has come since.
    taken: dict[str, bool] = {}
    #: Where the party was at each snapshot, which a restore returns it to.
    places: dict[str, str] = {}
    fights = 0
    #: Whether a `prayer-watch` has run, which may leave the debugger halted.
    watched = False
    for step in steps:
        k = step.kind
        if k in ("shot", "read"):
            continue
        # Pool's load lands on the map, or on the party menu for a save made
        # there; `begin` straight after it is for the second.
        pool_after_load = title == "pool" and last == "load"
        previous, last = last, k
        if where == "first-bar":
            raise ValueError(f"only shot and read may come after fight "
                             f"{FIRST_BAR}: {step.text!r}")
        if where == "pressed" and k not in ("press", "snapshot", "restore"):
            raise ValueError(f"only press, shot and read, or a snapshot or restore, "
                             f"may come after a press: {step.text!r}")
        if watched and k in ("snapshot", "restore"):
            raise ValueError(f"no snapshot or restore after prayer-watch, which "
                             f"leaves the emulator mid-fight: {step.text!r}")
        if where == "boot" and k not in ("load", "add"):
            raise ValueError(f"{k} needs load first: {step.text!r}")
        if k == "press":
            where = "pressed"
            continue
        if k == "load":
            if where != "boot":
                raise ValueError("load is one step, the first")
            where = t.loads_to
        elif k == "begin":
            if pool_after_load:
                where = "map"
                continue
            if t.loads_to == "map":
                raise ValueError(f"{title}'s load puts the party on the map; "
                                 "begin is for the titles that load to the "
                                 "party menu, and for Pool straight after a "
                                 "load onto the party menu")
            if where != "party":
                raise ValueError(f"begin needs the party menu: {step.text!r}")
            where = "map"
        elif k == "camp":
            if where == "party":
                raise ValueError(f"camp needs begin first: {step.text!r}")
            if where == "camp":
                raise ValueError(f"already camped: {step.text!r}")
            where = "camp"
        elif k == "vault":
            if title != "darkness":
                raise ValueError(f"vault is driven in darkness only, not {title}")
            if previous != "begin":
                raise ValueError(f"vault follows begin, which ends at Elminster's "
                                 f"menu for it: {step.text!r}")
            where = "elminster"
        elif k == "deposit":
            why = deposit_rejection(title, where, step)
            if why:
                raise ValueError(why)
        elif k == "leave":
            if title not in LEAVE_TITLES:
                raise ValueError(f"leave is driven in {', '.join(sorted(LEAVE_TITLES))} "
                                 f"only, not {title}")
            if where != "camp":
                raise ValueError(f"leave needs camp first: {step.text!r}")
            where = "map"
        elif k == "walk":
            if title not in WALKS:
                raise ValueError(f"walk is not driven in {title}")
            letters = title == "pool" and POOL_WALK_LETTERS.fullmatch(step.key)
            if step.key not in WALKS[title] and not letters:
                routes = " or ".join(f"'walk {r}'" for r in WALKS[title])
                more = " (or a run of I, J and K)" if title == "pool" else ""
                raise ValueError(f"{title}'s walk is {routes}, not {step.text!r}{more}")
            if where != "map":
                raise ValueError(f"walk needs the map: {step.text!r}")
        elif k == "turn":
            if title not in TURNS:
                raise ValueError(f"turn is not driven in {title}")
            if where != "map":
                raise ValueError(f"turn needs the map: {step.text!r}")
        elif k == "sheet" and title == "pool":
            if where != "map":
                raise ValueError(f"sheet needs the loaded map: {step.text!r}")
        elif k in ("sheet", "heal", "cure") and title in CAMP_SHEETS:
            if k == "cure" and title not in CURES:
                raise ValueError(f"cure is driven in {', '.join(sorted(CURES))} "
                                 f"only, not {title}")
            if where != "camp":
                raise ValueError(f"{k} needs camp first: {step.text!r}")
        elif k in ("heal", "cure"):
            raise ValueError(f"{k} is driven in "
                             f"{', '.join(sorted(CAMP_SHEETS if k == 'heal' else CURES))} "
                             f"only, not {title}")
        elif k == "change":
            if title != "curse":
                raise ValueError(f"change is driven in curse only, not {title}")
            if where != "party":
                raise ValueError(f"change needs the party menu, before begin: "
                                 f"{step.text!r}")
        elif k == "items" and title == "pool":
            if where != "camp":
                raise ValueError(f"items needs camp first: {step.text!r}")
        elif k in ("join", "trade"):
            if k == "trade" and title != "ssb":
                raise ValueError(f"trade is driven in ssb only, not {title}")
            if title not in JOIN_WHERE:
                raise ValueError(f"join is driven in {', '.join(sorted(JOIN_WHERE))} "
                                 f"only, not {title}")
            if where != JOIN_WHERE[title]:
                raise ValueError(f"{k} needs " + ("camp first" if JOIN_WHERE[title] == "camp"
                                                  else "the party menu, before begin")
                                 + f": {step.text!r}")
        elif k in ("items", "halve", "memorize"):
            if title != "darkness":
                raise ValueError(f"{k} is driven in darkness only, not {title}")
            if where != "camp":
                raise ValueError(f"{k} needs camp first: {step.text!r}")
        elif k == "add":
            if title not in ADD_TITLES:
                raise ValueError(f"add is driven in {', '.join(sorted(ADD_TITLES))} "
                                 f"only, not {title}")
            if where not in ("boot", "party"):
                raise ValueError(f"add needs the party menu before any load, since "
                                 f"{title}'s load puts the party on the map: "
                                 f"{step.text!r}")
            where = "party"
        elif k == "view":
            if title not in VIEWS:
                raise ValueError(f"view is driven in {', '.join(sorted(VIEWS))} only")
            if where != "party":
                raise ValueError(f"view needs the party menu, before begin: "
                                 f"{step.text!r}")
        elif k == "rest":
            if where != "camp":
                raise ValueError(f"rest needs camp first: {step.text!r}")
        elif k == "display":
            if title not in DISPLAY_TITLES:
                raise ValueError(f"display is driven in "
                                 f"{', '.join(sorted(DISPLAY_TITLES))} only, not {title}")
            if where != "camp":
                raise ValueError(f"display needs camp first: {step.text!r}")
        elif k == "scribe":
            if title not in SCRIBE_TITLES:
                raise ValueError(f"scribe is driven in "
                                 f"{', '.join(sorted(SCRIBE_TITLES))} only, not {title}")
            if where != "camp":
                raise ValueError(f"scribe needs camp first: {step.text!r}")
        elif k == "cast":
            if title not in CAST_TITLES:
                raise ValueError(f"cast is driven in "
                                 f"{', '.join(sorted(CAST_TITLES))} only, not {title}")
            if where != "camp":
                raise ValueError(f"cast needs camp first: {step.text!r}")
        elif k == "save":
            if where not in ("camp", "party"):
                raise ValueError(f"save needs camp first: {step.text!r}")
            taken = dict.fromkeys(taken, True)
        elif k == "snapshot":
            taken[step.name] = False
            places[step.name] = where
        elif k == "restore":
            if step.name not in taken:
                raise ValueError(f"{step.text!r}: no snapshot {step.name!r} "
                                 "was taken before it")
            if taken[step.name]:
                raise ValueError(
                    f"{step.text!r}: a save came between its snapshot and it, and a "
                    "restore puts the machine back while the game's save stays on "
                    "disk, so the run would no longer be one consistent game")
            where = places[step.name]
        elif k == "fight":
            if title not in FIGHT_TITLES:
                raise ValueError(f"fight is driven in "
                                 f"{', '.join(sorted(FIGHT_TITLES))} only, not {title}")
            if where != "map":
                raise ValueError(f"fight needs the map: {step.text!r}")
            if fights and title not in SECOND_FIGHT_TITLES:
                raise ValueError(f"a second fight in one boot is driven in "
                                 f"{', '.join(sorted(SECOND_FIGHT_TITLES))} only, "
                                 f"not {title}: its hand-back key is unread")
            fights += 1
            if step.name == FIRST_BAR:
                where = "first-bar"
        elif k == "temple":
            if title != "pool":
                raise ValueError(f"temple raise is driven in pool only, not {title}")
            if where != "map":
                raise ValueError(f"temple raise needs the map, where the walk "
                                 f"to the temple begins: {step.text!r}")
        elif k == "prayer-watch":
            why = prayer_watch_rejection(title, step.node)
            if why:
                raise ValueError(why)
            if where != "map":
                raise ValueError(f"prayer-watch needs the map: {step.text!r}")
            # The emulator is left halted-or-running mid-fight.
            where = "pressed"
            watched = True
        elif k == "train":
            if not t.trains:
                raise ValueError(f"train is driven in curse only; {title}'s "
                                 "training keys are unread")
            if where != "party":
                raise ValueError(f"train needs the party menu, before begin: "
                                 f"{step.text!r}")


@dataclasses.dataclass(frozen=True)
class Expect:
    name: str
    id: int
    minutes: int
    data: int | None = None


def parse_expect(text: str) -> Expect:
    """`NAME:ID:MINUTES[:DATA]`, numbers decimal (a leading zero, as in `05`,
    is still decimal) or `0x` hex."""
    parts = text.split(":")
    if len(parts) not in (3, 4) or not parts[0]:
        raise ValueError(f"not an expectation: {text!r} (NAME:ID:MINUTES[:DATA])")
    nums = [int(p, 10) if re.fullmatch(r"[0-9]+", p) else int(p, 0)
            for p in parts[1:]]
    return Expect(parts[0].upper(), nums[0], nums[1],
                  nums[2] if len(nums) == 3 else None)


def parse_row(text: str) -> tuple[int, int, int, int, int]:
    """`SLOT=ID:OWNER:DURATION:MAGNITUDE`, all hex, for `effects.write_effect`."""
    slot, sep, rest = text.partition("=")
    parts = rest.split(":")
    if not sep or len(parts) != 4:
        raise ValueError(f"not a row: {text!r} (SLOT=ID:OWNER:DURATION:MAGNITUDE, hex)")
    values = [int(slot, 16)] + [int(p, 16) for p in parts]
    if not 0 <= values[0] < 64 or any(not 0 <= v <= 0xFF for v in values[1:]):
        raise ValueError(f"row out of range: {text!r}")
    return tuple(values)  # type: ignore[return-value]


def parse_xp(text: str) -> tuple[int, int]:
    """`LINE=VALUE`: roster line 1-8 and the experience to stage."""
    line, sep, value = text.partition("=")
    if not sep or not re.fullmatch(r"[1-8]", line.strip()):
        raise ValueError(f"not an experience stage: {text!r} (LINE=VALUE)")
    xp = int(value, 0)
    if not 0 <= xp <= 0xFFFFFFFF:
        raise ValueError(f"experience out of range: {text!r}")
    return int(line), xp


def parse_control(text: str) -> tuple[int, int, int | None]:
    """`LINE=CONTROL[:SHARE]`, numbers decimal or `0x` hex: roster line 1-8's
    field_83_87 control byte, and optionally the treasure-share byte after it."""
    line, sep, rest = text.partition("=")
    parts = rest.split(":")
    if not sep or not re.fullmatch(r"[1-8]", line.strip()) or len(parts) not in (1, 2):
        raise ValueError(f"not a control stage: {text!r} (LINE=CONTROL[:SHARE])")
    control = int(parts[0], 0)
    share = int(parts[1], 0) if len(parts) == 2 else None
    if not 0 <= control <= 0xFF or (share is not None and not 0 <= share <= 0xFF):
        raise ValueError(f"control or share out of range: {text!r}")
    return int(line), control, share


_RECORD_NUMBER = re.compile(r"0|[1-9][0-9]*|0[xX][0-9a-fA-F]+")


def parse_side(text: str) -> tuple[int, int, int | None]:
    """`LINE=SIDE[:QUICKFIGHT]`, numbers decimal or `0x` hex, each one byte:
    roster line 1-8's combat side byte, 1 for the enemy's, and optionally
    the quickfight byte after it."""
    line, sep, rest = text.partition("=")
    parts = rest.split(":")
    if (not sep or not re.fullmatch(r"[1-8]", line.strip()) or len(parts) not in (1, 2)
            or not all(_RECORD_NUMBER.fullmatch(p.strip()) for p in parts)):
        raise ValueError(f"not a side stage: {text!r} (LINE=SIDE[:QUICKFIGHT], "
                         "decimal or 0x hex)")
    side = int(parts[0], 0)
    quick = int(parts[1], 0) if len(parts) == 2 else None
    if side > 0xFF or (quick is not None and quick > 0xFF):
        raise ValueError(f"side or quickfight out of range: {text!r} "
                         "(LINE=SIDE[:QUICKFIGHT], one byte each)")
    return int(line), side, quick


def stage_side(save_dir: pathlib.Path, letter: str, line: int, side: int,
               quickfight: int | None = None) -> dict:
    """Write `side` into roster line `line`'s combat side byte, and
    `quickfight` into the byte after it when given: the third and fourth
    bytes of `field_10c_10f`, which `goldbox.dos_codec.to_neutral` reads as
    `hostile` and `quickfight` (Pool 0x10E, Curse 0x197, Silver Blades
    0x1A8)."""
    path = save_dir / f"CHRDAT{letter.upper()}{line}.SAV"
    c = dos_codec.read_character(path)
    at = c.fields["field_10c_10f"].offset + 2
    data = bytearray(path.read_bytes())
    result = {"stage": "side", "file": path.name, "name": c.name,
              "side_offset": hex(at), "side_before": f"{data[at]:02x}",
              "side_after": f"{side:02x}", "quickfight_offset": hex(at + 1)}
    data[at] = side
    if quickfight is not None:
        result.update(quickfight_before=f"{data[at + 1]:02x}",
                      quickfight_after=f"{quickfight:02x}")
        data[at + 1] = quickfight
    path.write_bytes(bytes(data))
    return result


def parse_key(text: str) -> str:
    """`SPACE` or one letter or digit, as the X keysym `fight` presses.

    `Y` is blocked: it answers `YES`, which the step never answers.
    """
    if text.upper() == "SPACE":
        return "space"
    if text.upper() == "Y":
        raise ValueError(f"{text!r}: Y answers YES, which the fight step never does")
    if len(text) == 1 and text.isascii() and text.isalnum():
        return text.lower()
    raise ValueError(f"{text!r}: a key is SPACE or one letter or digit")


def parse_record_bytes(texts) -> list[tuple[int, int, int]]:
    """`LINE:OFFSET=VALUE`, numbers decimal or `0x` hex, comma-separated or
    repeated: one byte of roster line 1-8's `CHRDAT` record each.  Whether the
    offset lies inside the record is `check_staging`'s and `stage_record`'s
    to say, since the record's size is the installed title's.  A number is `0`,
    a decimal with no leading zero, or `0x` hex; a leading zero (`010`), `_`,
    a sign and `0b`/`0o` are blocked rather than read as some other base.  A
    byte named twice takes its last value, because the stages run in order."""
    out = []
    for text in texts:
        for item in text.split(","):
            where, sep, value = item.partition("=")
            parts = where.split(":")
            if not sep or len(parts) != 2 or not value.strip():
                raise ValueError(f"{item!r}: a record byte is LINE:OFFSET=VALUE")
            numbers = [p.strip() for p in (*parts, value)]
            for n in numbers:
                if not _RECORD_NUMBER.fullmatch(n):
                    raise ValueError(f"{item!r}: {n!r} is not a number "
                                     "(decimal without a leading zero, or 0x hex)")
            line, offset, byte = (int(n, 0) for n in numbers)
            if not 1 <= line <= 8 or offset < 0 or not 0 <= byte <= 0xFF:
                raise ValueError(f"{item!r}: the line is 1 to 8, the offset "
                                 "not negative, the value one byte")
            out.append((line, offset, byte))
    return out


def temple_staging_rejection(args, steps: list[Step]) -> str | None:
    """Why a run's staging does not fit its `temple raise`, or None: such a
    run stages record bytes only through `--stage-record`, and only the
    fields of `TEMPLE_STAGE_FIELDS`, the payment's gold and the constitution
    that stays above the minimum after the raise's one-point loss."""
    if not any(s.kind == "temple" for s in steps):
        return None
    for option in ("xp", "add_node", "stage_control", "stage_side", "stage_var",
                   "stage_place"):
        if getattr(args, option, None):
            return (f"a run with temple raise stages only gold and constitution "
                    f"with --stage-record, not --{option.replace('_', '-')}")
    for line, offset, _ in parse_record_bytes(getattr(args, "stage_record", []) or []):
        if offset not in TEMPLE_STAGE_FIELDS:
            return (f"a run with temple raise stages only gold (0x08E, 0x08F) and "
                    f"constitution (0x014); --stage-record {line}:{offset:#05x} is "
                    "neither")
    return None


def parse_var(text: str) -> tuple[int, int]:
    """`ADDRESS=VALUE`: a script-variable word, the address hex with or without
    `$` or `0x`, the value decimal or `0x` hex.  Whether the address lies in the
    title's array is `check_staging`'s and `stage_var`'s to say."""
    where, sep, value = text.partition("=")
    where = where.strip().removeprefix("$").removeprefix("0x").removeprefix("0X")
    value = value.strip()
    if (not sep or not re.fullmatch(r"[0-9A-Fa-f]{1,4}", where)
            or not _RECORD_NUMBER.fullmatch(value)):
        raise ValueError(f"{text!r}: a variable is ADDRESS=VALUE (address hex, "
                         "value decimal without a leading zero, or 0x hex)")
    number = int(value, 0)
    if not 0 <= number <= 0xFFFF:
        raise ValueError(f"{text!r}: the value is one word, 0 to 0xFFFF")
    return int(where, 16), number


def parse_place(text: str) -> tuple[int, int, int]:
    """`X,Y,FACING`: a square of 0 to 15 each way and a facing of 0 to 3 (N E S W)."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 3 or not all(_RECORD_NUMBER.fullmatch(p) for p in parts):
        raise ValueError(f"{text!r}: a place is X,Y,FACING (decimal or 0x hex)")
    x, y, facing = (int(p, 0) for p in parts)
    if not (0 <= x <= 15 and 0 <= y <= 15 and 0 <= facing <= 3):
        raise ValueError(f"{text!r}: x and y are 0 to 15, facing 0 to 3 (N E S W)")
    return x, y, facing


def parse_node(text: str) -> tuple[int, bytes]:
    """`LINE=ID:MINUTES:DATA:FLAG`, numbers decimal or `0x` hex: a node's five bytes."""
    line, sep, rest = text.partition("=")
    parts = rest.split(":")
    if not sep or not re.fullmatch(r"[1-8]", line.strip()) or len(parts) != 4:
        raise ValueError(f"not a node: {text!r} (LINE=ID:MINUTES:DATA:FLAG)")
    eid, minutes, data, flag = (int(p, 0) for p in parts)
    if not (0 <= eid <= 0xFF and 0 <= minutes <= 0xFFFF and 0 <= data <= 0xFF
            and 0 <= flag <= 0xFF):
        raise ValueError(f"node out of range: {text!r}")
    return int(line), bytes((eid, minutes & 0xFF, minutes >> 8, data, flag))










def clock_total(digits: tuple[int, ...]) -> int:
    """Minutes from the clock digits: sub-minute, units, tens, hour, day, month.

    Months are counted as 30 days, the digit's own limit, so a difference of
    two readings is exact within a year.
    """
    _, units, tens, hour, day, month = digits[:6]
    return (((month * 30) + day) * 24 + hour) * 60 + tens * 10 + units


def read_place(savgam: bytes) -> dict:
    """Area, square, facing and whether the party has set out, or the error."""
    try:
        s = world_state.from_dos(savgam)
    except Exception as e:  # noqa: BLE001 -- reported, the clock still reads
        return {"error": f"{type(e).__name__}: {e}"}
    return {"area": s.area, "x": s.x, "y": s.y, "facing": s.facing,
            "set_out": s.set_out}


#: The eight thief skills in the order the record holds them.
THIEF_FIELDS = ("thief_pick_pockets", "thief_open_locks", "thief_find_traps",
                "thief_move_silently", "thief_hide_in_shadows",
                "thief_hear_noise", "thief_climb_walls", "thief_read_languages")


def item_dict(item) -> dict:
    """One item as `read` reports it; a scroll's three spell ids are in
    `charges`, `effect` and `power` (`amiga_pod.unbundle`)."""
    return {"type_index": item.get("type_index"),
            "spells": [item.get("charges"), item.get("effect"), item.get("power")],
            "readied": item.get("readied"), "quantity": item.get("quantity"),
            "weight": item.get("weight")}


def read_pod_slot(folder: pathlib.Path, letter: str) -> dict:
    """A Pools of Darkness slot: the clock, the square, and every character's
    nodes, experience, thief skills, item count, encumbrance, movement, items,
    the record byte `POD_BOOK_126` (spell id 126's book byte), the three
    level-drain marks and the ready-to-train byte at 0x1EC, read through
    `world_state.pod_from_dos` and `dos_codec.read_party`."""
    savgam = (folder / f"SAVGAM{letter}.PTY").read_bytes()
    state = world_state.pod_from_dos(savgam, source=str(folder))
    out = {"slot": letter, "clock": list(state.clock),
           "clock_minutes": clock_total(state.clock),
           "place": {"x": state.x, "y": state.y, "facing": state.facing,
                     "in_dungeon": state.in_dungeon,
                     "dungeon_map": state.dungeon_map, "mode": state.mode},
           "vault_bytes": ((folder / f"VAULT{letter}.DAT").stat().st_size
                           if (folder / f"VAULT{letter}.DAT").is_file() else None),
           "characters": []}
    vault_path = folder / f"VAULT{letter}.DAT"
    if vault_path.is_file():
        v = dos_codec.pod_vault_from_dos(vault_path.read_bytes())
        out["vault"] = {"platinum": v.platinum, "gems": v.gems,
                        "jewelry": v.jewelry,
                        "items": [item_dict(dos_codec.DosItem(r))
                                 for r in v.items]}
    for c in dos_codec.read_party(folder, letter):
        out["characters"].append({
            "name": c.name, "file": pathlib.Path(c.source).name,
            "experience": c.get("experience"),
            "nodes": [node_dict(e) for e in c.effects],
            "thief": {f: c.get(f) for f in THIEF_FIELDS},
            "item_count": c.get("item_count"),
            "encumbrance": c.get("encumbrance"),
            "movement": c.get("movement"),
            "movement_current": c.get("movement_current"),
            "book_0x130": c.to_bytes()[POD_BOOK_126],
            "highest_class_levels": list(c.raw("highest_class_levels")),
            "highest_experience": c.get("highest_experience"),
            "highest_hp_max": c.get("highest_hp_max"),
            "ready_to_train": c.get("ready_to_train"),
            "items": [item_dict(i) for i in c.items]})
    return out


def read_slot(folder: pathlib.Path, letter: str) -> dict:
    """The clock, the place and every character's nodes and experience in one slot.

    A folder holding `SAVGAM<letter>.PTY` is Pools of Darkness and is read by
    `read_pod_slot`.
    """
    if (folder / f"SAVGAM{letter}.PTY").is_file():
        return read_pod_slot(folder, letter)
    savgam = (folder / f"SAVGAM{letter}.DAT").read_bytes()
    digits = world_state.from_dos(savgam).clock
    out = {"slot": letter, "clock": list(digits),
           "clock_minutes": clock_total(digits), "place": read_place(savgam),
           "characters": []}
    for n in range(1, 9):
        path = folder / f"CHRDAT{letter}{n}.SAV"
        if not path.is_file():
            continue
        c = dos_codec.read_character(path)
        control = treasure_share = None
        if "field_83_87" in c.fields:
            control_raw = c.raw("field_83_87")
            control_index = 1 if len(control_raw) == 5 else 0
            control = control_raw[control_index]
            treasure_share = control_raw[control_index + 1]
        # None, not 0, in a title that has not mapped the byte.
        own = {n: c.get(n) if n in c.fields else None
               for n in ("creature_type", "turn_class", "movement")}
        out["characters"].append({
            **own,
            "status_bytes": (list(c.raw("field_10c_10f"))
                             if "field_10c_10f" in c.fields else None),
            "name": c.name, "file": path.name,
            "experience": c.get("experience") if "experience" in c.fields else None,
            "control": control, "treasure_share": treasure_share,
            "nodes": [node_dict(e) for e in c.effects]})
    return out


def compare_nodes(before: dict, after: dict) -> list[dict]:
    """Each node of `before`, matched by character name and id in `after`.

    Two nodes of one id on one character are matched in file order.  A node
    only `after` holds is listed with `before` None.
    """
    rows = []
    after_by = {c["name"]: list(c["nodes"]) for c in after["characters"]}
    for c in before["characters"]:
        left = after_by.get(c["name"])
        for node in c["nodes"]:
            match = None
            if left is not None:
                for i, cand in enumerate(left):
                    if cand["id"] == node["id"]:
                        match = left.pop(i)
                        break
            rows.append({
                "name": c["name"], "id": node["id"],
                "before": node["minutes"], "data_before": node["data"],
                "after": None if match is None else match["minutes"],
                "data_after": None if match is None else match["data"],
                "lost": None if match is None else node["minutes"] - match["minutes"],
                "character_present": left is not None,
            })
    for name, nodes in after_by.items():
        for node in nodes:
            rows.append({"name": name, "id": node["id"], "before": None,
                         "data_before": None, "after": node["minutes"],
                         "data_after": node["data"], "lost": None,
                         "character_present": True})
    return rows


def compare_experience(before: dict, after: dict) -> list[dict]:
    """Each character's experience in `before` and `after`, matched by name."""
    after_by = {c["name"]: c.get("experience") for c in after["characters"]}
    rows = []
    for c in before["characters"]:
        was, now = c.get("experience"), after_by.get(c["name"])
        rows.append({"name": c["name"], "before": was, "after": now,
                     "gained": None if was is None or now is None else now - was})
    return rows


#: What `compare_members` sets side by side for each Pools of Darkness character.
MEMBER_FIELDS = ("thief", "item_count", "encumbrance", "movement",
                 "movement_current", "book_0x130", "items")


def compare_members(before: dict, after: dict) -> list[dict]:
    """Each character's `MEMBER_FIELDS` in `before` and `after`, matched by name,
    with the names of the fields that differ.  Empty for a title whose
    reading has none of them."""
    after_by = {c["name"]: c for c in after["characters"]}
    rows = []
    for c in before["characters"]:
        if "thief" not in c:
            continue
        now = after_by.get(c["name"])
        row = {"name": c["name"], "present": now is not None, "changed": []}
        for f in MEMBER_FIELDS:
            row[f] = {"before": c[f], "after": None if now is None else now.get(f)}
            if now is not None and now.get(f) != c[f]:
                row["changed"].append(f)
        rows.append(row)
    return rows


#: The control byte the game writes for a raised companion.
ANIMATED_CONTROL = 0xB3


def animated_members(steps: list["Step"], expects: list["Expect"],
                     slot: dict) -> set[str]:
    """The members this run raised, upper-cased: those whose id-32 `--expect`
    the resave `slot` accepts, and only when a `cast N ANIMATE-DEAD` step is in
    the run.  A refuted expectation exempts nobody."""
    if not any(s.kind == "cast" and s.name == "ANIMATE-DEAD" for s in steps):
        return set()
    return {e.name for e in expects
            if e.id == 32 and judge(e, slot)["verdict"] == "accepts"}


def _control_reset_reason(before: dict, after: dict, title: str | None) -> str | None:
    """Why the game reset `before`'s 0xB3 control to 0 in `after`, when a charm
    or `title`'s Fear node it held has gone; None when the change is anything else."""
    if before.get("control") != ANIMATED_CONTROL or after.get("control") != 0:
        return None
    held = {n["id"] for n in before.get("nodes", [])}
    left = {n["id"] for n in after.get("nodes", [])}
    fear = effects.FEAR_IDS.get(CONVERT_TITLE_KEYS.get(title), frozenset())
    for node_id, reason in [(effects.CHARM_ID, "charm ended"),
                            *((i, "fear ended") for i in sorted(fear))]:
        if node_id in held and node_id not in left:
            return reason
    return None


def compare_shares(before: dict, after: dict,
                   animated: frozenset[str] | set[str] = frozenset(),
                   title: str | None = None) -> list[dict]:
    """Each character's `control` and `treasure_share` bytes in `before` and
    `after`, matched by name.  A row with either byte unequal fails the run
    (`read_step`/`describe`), except that a member in `animated` may change
    control to `ANIMATED_CONTROL` with its share unchanged; that row records
    `control_changed`.  A member that held `ANIMATED_CONTROL` and a charm or
    `title` Fear node in `before`, and holds control 0, that node's id absent and the
    same share in `after`, matches too, recording why."""
    after_by = {c["name"]: c for c in after["characters"]}
    rows = []
    for c in before["characters"]:
        if c.get("control") is None and c.get("treasure_share") is None:
            continue
        now = after_by.get(c["name"])
        row = {"name": c["name"], "present": now is not None,
               "control_before": c.get("control"),
               "control_after": None if now is None else now.get("control"),
               "share_before": c.get("treasure_share"),
               "share_after": None if now is None else now.get("treasure_share")}
        row["matches"] = (now is not None
                          and row["control_before"] == row["control_after"]
                          and row["share_before"] == row["share_after"])
        if (not row["matches"] and now is not None and c["name"].upper() in animated
                and row["control_after"] == ANIMATED_CONTROL
                and row["control_before"] != ANIMATED_CONTROL
                and row["share_before"] == row["share_after"]):
            row["matches"] = True
            row["control_changed"] = {c["name"]: [row["control_before"],
                                                  row["control_after"]],
                                      "reason": "animated"}
        if (not row["matches"] and now is not None
                and c["name"].upper() not in animated):
            reason = _control_reset_reason(c, now, title)
            if reason and row["share_before"] == row["share_after"]:
                row["matches"] = True
                row["control_changed"] = {c["name"]: [row["control_before"],
                                                      row["control_after"]],
                                          "reason": reason}
        rows.append(row)
    return rows


def judge(expect: Expect, after: dict) -> dict:
    """Whether `after` holds the node `expect` names, with its minutes and data."""
    who = [c for c in after["characters"] if c["name"].upper() == expect.name]
    base = {"expect": dataclasses.asdict(expect)}
    if not who:
        return {**base, "verdict": "refutes", "why": f"no {expect.name} in the resave"}
    nodes = [n for n in who[0]["nodes"] if n["id"] == expect.id]
    if not nodes:
        return {**base, "verdict": "refutes",
                "why": f"{expect.name} holds no node with id {expect.id}"}
    for n in nodes:
        if n["minutes"] == expect.minutes and (
                expect.data is None or n["data"] == expect.data):
            return {**base, "verdict": "accepts", "found": n}
    return {**base, "verdict": "refutes", "found": nodes,
            "why": f"{expect.name}'s id {expect.id} node holds "
                   + ", ".join(f"{n['minutes']} minutes data {n['data']:02X}"
                               for n in nodes)}



# --------------------------------------------------------------------------
# The conversion: a C64 party, staged, through Save As DOS
# --------------------------------------------------------------------------


def c64_base(title: str, override: str | None = None) -> pathlib.Path | None:
    """The C64 disk `--fixture-row` stages into; None means the committed fixture."""
    if override:
        return pathlib.Path(override)
    if title not in C64_BASES:
        return None
    from tools.registry import specimens
    return specimens.tree_root() / "por-c64" / C64_BASES[title]


def staged_disk(base: pathlib.Path, title: str,
                rows: list[tuple[int, int, int, int, int]]) -> tuple[bytes, dict]:
    """`base` with `rows` written into its save payload, and what was staged.

    Each row's minutes left are read at the save's own clock
    (`effects.remaining_minutes`), which is what the conversion turns into a
    node's minutes.
    """
    from goldbox import c64_save, effects
    from goldbox.d64 import D64, attach_load_address, split_load_address
    container = {"curse": c64_save.CURSE_OF_THE_AZURE_BONDS,
                 "ssb": c64_save.SECRET_OF_THE_SILVER_BLADES,
                 "pool": c64_save.POOL_OF_RADIANCE}[title]
    image = D64.open(str(base))
    load, body = split_load_address(image.read_file(container.save_file))
    body = bytearray(body)
    clock = tuple(body[container.clock + i] for i in range(dos_savegame.CLOCK_DIGITS))
    minutes = effects.clock_minutes(clock)
    for row in rows:
        effects.write_effect(body, *row)
    image.write_file_inplace(container.save_file, attach_load_address(load, bytes(body)))
    return image.to_bytes(), {
        "base": str(base), "clock": list(clock), "clock_minutes": minutes,
        "minutes_left": [effects.remaining_minutes(r[3], minutes) for r in rows]}


def parse_name(text: str) -> tuple[int, str]:
    """`POSITION=NAME` as `(position, name)`: the name the player would type
    into the Shorten window's box for the party member at that position."""
    position, sep, name = text.partition("=")
    if not sep or not re.fullmatch(r"\d+", position):
        raise ValueError(f"not POSITION=NAME: {text!r} (say 0=Wren)")
    if not name or any(not 0x20 <= ord(ch) <= 0x7E for ch in name):
        raise ValueError(f"--name {text!r}: a name is one or more printable "
                         "ASCII characters")
    return int(position), name


def parse_names(texts: list[str], title: str) -> dict[int, str]:
    """`--name` values as the `{position: name}` `prepare_save_as` takes,
    blocking a repeated position or a name over the DOS field's width."""
    from editor import saveplan
    width = saveplan.name_width("dos", CONVERT_TITLE_KEYS[title])
    names: dict[int, str] = {}
    for text in texts:
        position, name = parse_name(text)
        if position in names:
            raise ValueError(f"--name gives position {position} twice")
        if len(name) > width:
            raise ValueError(f"--name {text!r}: {len(name)} characters, over "
                             f"the {width} the DOS {title} name field holds")
        names[position] = name
    return names


def _save_as_dos(party, out: pathlib.Path, title: str, report: dict,
                 names: dict[int, str] | None = None) -> dict:
    """Save As DOS of `party` into `out/source`, filling in `report`.

    The route is the editor's own, `prepare_save_as` then `publish`, as
    `tests/convert/test_runningeffects.py`'s `_dos_plan` prepares it.
    `prepare_save_as` blocks a conversion that would drop a field, which is
    reported as `stopped` and ends the run before any boot.  Shared by
    `build_source` (a staged C64 party) and `build_saveas_source` (any save
    `editor.convert.Source.detect` accepts): both build `party` and a `report`
    of their own and hand them here for the rest of the route.
    """
    from editor import saveplan
    from editor.convert import Source
    from tools.convert import convertdrops

    source = Source.of_snapshot(saveplan.prepare(party))
    assets = saveplan.resolve_assets(source, "dos",
                                     game_files=convertdrops.game_files,
                                     dos_folder=dosbox.find_game(TITLES[title].stem))
    dest = out / "source"
    if names and max(names) >= len(party.members):
        return {**report, "stopped": f"--name position {max(names)} is not a "
                f"member of a party of {len(party.members)}"}
    try:
        plan = saveplan.prepare_save_as(party, "dos", dest, assets,
                                        **({"names": names} if names else {}))
    except saveplan.DroppedFields as e:
        return {**report, "stopped": str(e)}
    except saveplan.NamesDoNotFit as e:
        return {**report, "stopped": "no --name for " + "; ".join(
            f"position {p} ({n!r}, {e.width} fit)" for p, n in e.unfit)}
    report["dropped"] = list(plan.report.dropped)
    report["losses"] = list(plan.report.losses)
    saveplan.publish(plan, party)
    report["files"] = sorted(p.name for p in dest.iterdir())
    report["nodes"] = {
        p.name: [node_dict(p.read_bytes()[i:i + dos_codec.EFFECT_SIZE])
                 for i in range(0, p.stat().st_size - dos_codec.EFFECT_SIZE + 1,
                                dos_codec.EFFECT_SIZE)]
        for p in sorted(dest.iterdir())
        if p.suffix.upper() in EFFECT_SUFFIXES and p.stat().st_size}
    report["read"] = {x: read_slot(dest, x) for x in slots_in(dest)}
    return report


def build_source(rows: list[tuple[int, int, int, int, int]], out: pathlib.Path,
                 title: str = "pool", base: str | None = None) -> dict:
    """Stage `rows` into a C64 party and Save As DOS into `out/source`."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from editor import roster
    from goldbox import effects
    from goldbox.c64_port import POOL_OF_RADIANCE
    from goldbox.savegame import SaveGame0, SaveGame1

    disk = out / "source.d64"
    report: dict = {"rows": [list(r) for r in rows], "disk": disk.name}
    where = c64_base(title, base)
    if where is None:
        fixtures = REPO / "tests" / "fixtures"
        payload = bytearray(SaveGame0.from_prg(
            (fixtures / "savedgame0.bin").read_bytes()).to_bytes())
        save1 = SaveGame1.from_prg((fixtures / "savedgame1.bin").read_bytes()).to_bytes()
        for row in rows:
            effects.write_effect(payload, *row)
        disk.write_bytes(dos_codec.save_disk(bytes(payload), save1,
                                             POOL_OF_RADIANCE).to_bytes())
        report["base"] = "tests/fixtures/savedgame0.bin"
    else:
        data, staged = staged_disk(where, title, rows)
        disk.write_bytes(data)
        report.update(staged)
    party = roster.Party(str(disk))
    return _save_as_dos(party, out, title, report)


#: `Source.key` for a party staged from a C64 disk, one of the three titles
#: `--convert` accepts; the same map `staged_disk` uses for its own container.
CONVERT_TITLE_KEYS = {"pool": "pool-of-radiance",
                      "curse": "curse-of-the-azure-bonds",
                      "ssb": "secret-of-the-silver-blades"}


def build_saveas_source(path: str | pathlib.Path, slot: str, out: pathlib.Path,
                        title: str, names: dict[int, str] | None = None) -> dict:
    """Copy `path` into `out` and Save As DOS whatever save `Source.detect`
    finds there at `slot`, blocking a source whose title is not `title`.

    `path` is a C64 disk image or an Amiga `.adf` holding any save
    `editor.convert.Source.detect` reads -- a Curse or Silver Blades save from
    either port, or an Amiga Pool of Radiance one.  A Pools of Darkness source
    is blocked: `--amiga-slot` converts it through the Convert window's own
    route.  `names` maps a party position to the name chosen for that member,
    as the Shorten window hands them to `prepare_save_as`; without one, a name
    too long for DOS raises `saveplan.NamesDoNotFit`.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from editor import roster
    from editor.convert import Source

    src = pathlib.Path(path)
    data = src.read_bytes()
    copy = out / ("source" + src.suffix.lower())
    copy.write_bytes(data)
    report: dict = {"source_path": str(src),
                    "source_sha256": hashlib.sha256(data).hexdigest(),
                    "convert_slot": slot, "disk": copy.name}
    key = CONVERT_TITLE_KEYS[title]
    source = Source.detect(copy, slot=slot)
    if source.key != key:
        return {**report, "stopped": f"{path} holds {source.key!r}, not "
                f"{title}'s {key!r}"}
    party = roster.Party(source)
    return _save_as_dos(party, out, title, report, names)


# --------------------------------------------------------------------------
# The conversion: an Amiga Pools of Darkness saved game, through Convert
# --------------------------------------------------------------------------


def parse_amiga_slot(text: str) -> str:
    """`SavGamA.pty`, `savgama.pty` or `A`: the Amiga slot letter."""
    m = re.fullmatch(r"(?:savgam)?([a-j])(?:\.pty)?", text.strip(), re.IGNORECASE)
    if m is None:
        raise ValueError(f"not an Amiga Pools of Darkness slot: {text!r} "
                         "(say SavGamA.pty or A)")
    return m.group(1).upper()


def amiga_image(disk: str) -> tuple[str, bytes]:
    """`disk` as `(label, bytes)`: a path to an `.adf`, or the end of exactly
    one `tools/amiga/amigasaves.py` label, such as
    `Pools Of Darkness.zip!Pools of Darkness3.adf`.  Read only."""
    path = pathlib.Path(disk)
    if path.is_file():
        return str(path), path.read_bytes()
    from tools.amiga import amigasaves
    hits = [(label, data) for label, data in amigasaves.images()
            if label.endswith(disk)]
    if len(hits) != 1:
        raise FileNotFoundError(
            f"{len(hits)} Amiga disk images end with {disk!r}; one is wanted"
            + (": " + ", ".join(label for label, _ in hits) if hits else
               " (set $AMIGA_DISKS or pass a path)"))
    return hits[0]


@contextlib.contextmanager
def flag_on(name: str):
    """`name` set to `1` for the block, and put back as it was afterwards."""
    was = os.environ.get(name)
    os.environ[name] = "1"
    try:
        yield
    finally:
        if was is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = was


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{record.name}: {record.getMessage()}")


def build_amiga_source(disk: str, slot: str, out: pathlib.Path) -> dict:
    """Convert Amiga slot `slot` of `disk` to a DOS save folder in `out/source`.

    The route is the Convert window's: `Source.detect` on the disk, the one
    DOS direction `destinations_for` offers with `WISH_EXPERIMENTAL_POD_CONVERT`
    set, `saveplan.rehearse`, then the direction's `write` into the folder.
    The disk is copied to `out/source.adf` and never written.  A warning the
    conversion logs (a spell id the DOS book does not hold, say) is listed in
    `warnings`, since it reaches neither `dropped` nor `losses`.  A conversion
    that raises is reported as `stopped`.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from editor import convert, saveplan

    letter = parse_amiga_slot(slot)
    label, data = amiga_image(disk)
    adf = out / "source.adf"
    adf.write_bytes(data)
    report: dict = {"disk": label, "adf_sha256": hashlib.sha256(data).hexdigest(),
                    "amiga_slot": f"SavGam{letter}.pty",
                    "flag": f"{convert.POD_CONVERT_ENV}=1"}
    collect = _Collect()
    wish_log = logging.getLogger("wish")
    # The GUI's debug log parks this logger above CRITICAL while it is off,
    # and a level filters before any handler, so lower it for the run.
    was_level = wish_log.level
    if not was_level or was_level > logging.WARNING:
        wish_log.setLevel(logging.WARNING)
    wish_log.addHandler(collect)
    try:
        with flag_on(convert.POD_CONVERT_ENV):
            source = convert.Source.detect(adf, slot=letter)
            if source.key != "pools-of-darkness" or letter not in (
                    source.available_slots or [source.slot]):
                return {**report, "stopped": f"{label} holds no Pools of Darkness "
                        f"slot {letter} (it holds {source.available_slots})"}
            directions = [d for d in convert.destinations_for(source)
                          if d.destination_port == "dos"]
            if len(directions) != 1:
                return {**report, "stopped": f"{len(directions)} DOS directions "
                        "are offered for this disk; one is wanted"}
            rehearsal, wrote = saveplan.rehearse(directions[0], source,
                                                 saveplan.Assets())
            dest = out / "source"
            dest.mkdir(parents=True, exist_ok=True)
            directions[0].write(rehearsal, dest)
    except Exception as e:  # noqa: BLE001 -- recorded, and the run stops before a boot
        return {**report, "stopped": f"{type(e).__name__}: {e}",
                "warnings": collect.lines}
    finally:
        wish_log.removeHandler(collect)
        wish_log.setLevel(was_level)
    report["direction"] = type(directions[0]).__name__
    report["dos_slot"] = wrote
    report["dropped"] = list(rehearsal.report.dropped)
    report["losses"] = list(rehearsal.report.losses)
    # The writer runs twice, rehearsing and then writing, so each line is
    # listed once.
    report["warnings"] = list(dict.fromkeys(collect.lines))
    report["files"] = sorted(p.name for p in dest.iterdir())
    report["read"] = {wrote: read_slot(dest, wrote)}
    return report


# --------------------------------------------------------------------------
# The driven part
# --------------------------------------------------------------------------


def hold_still(session, quiet: float, timeout: float,
               clock=None) -> "dosbox.Screen | None":
    """The screen once it has held unchanged for `quiet` seconds, or None when
    it is still changing after `timeout`.

    Unlike `Session.settle`, which hands back the last frame on a timeout,
    this says whether the screen ever held still.
    """
    clock = clock or time.monotonic
    end = clock() + timeout
    last = session.capture()
    since = clock()
    while True:
        if clock() - since >= quiet:
            return last
        if clock() >= end:
            return None
        time.sleep(0.15)
        now = session.capture()
        if now.px != last.px:
            last, since = now, clock()


def boot_session(session, timeout: float = 30.0, clock=None) -> None:
    """`session.boot(fresh=False)`, waiting out a start-up text screen.

    DOSBox-X shows the DOS prompt's text screen, which is not line-doubled,
    while a launcher such as Pools of Darkness' `START.BAT` runs, and
    `XSession.boot`'s closing settle can grab it.  The window is chosen by
    then, so a `NotLineDoubled` there is waited out until the game's own
    line-doubled screen shows, for `timeout` seconds at most, and the screen
    is then settled as the boot would have.
    """
    try:
        session.boot(fresh=False)
        return
    except dosboxx.NotLineDoubled as e:
        first = e
    clock = clock or time.monotonic
    end = clock() + timeout
    while clock() < end:
        try:
            session.capture()
        except dosboxx.NotLineDoubled:
            time.sleep(0.5)
            continue
        session.settle()
        return
    raise dosboxx.NotLineDoubled(f"still no line-doubled screen {timeout:.0f} s "
                                 f"after the boot's settle saw: {first}")


class Driver:
    """The steps, on one booted session of a DOS Gold Box title.

    Every screen the driver waits at is logged with its `bar_signature`,
    `Screen.glyphs(BAR)` and whole-frame digest beside a PNG, which is what a
    later classifier row is written from.  The party menu, the map and the
    camp bar are learnt off the screen when they are reached, not compared
    with digests measured elsewhere, except for Silver Blades, whose screens
    `route_silver_blades.BARS` already classifies.
    """

    def __init__(self, session, note, slot: str, title: str = "pool",
                 party_size: int = 6, deadline: Deadline | None = None,
                 encounters: dosnoencounters.NoEncounters | None = None):
        self.s = session
        #: The `--no-encounters` switch, or None: random encounters stay on.
        self.encounters = encounters
        #: The run's route window, or None: nothing then limits a wait.
        self.deadline = deadline
        #: Why the last failure capture failed, or None.
        self.capture_error: str | None = None
        self.note = note
        self.slot = slot
        self.title = TITLES[title]
        self.keys = self.title.rest_keys()
        self.game = (dosnoencounters.SuppressedPool(session, encounters)
                     if encounters is not None
                     else dosbox.PoolOfRadiance(session))
        self.camp_sig: str | None = None
        self.world_ink: str | None = None
        self.world_sig: str | None = None
        self.party_sig: str | None = None
        #: The party's place: `boot`, `map`, `party` or `camp`.
        self.where = "boot"
        #: The roster line the party menu's highlight is on, counted from 1.
        self.line = 1
        self.party_size = max(1, party_size)
        #: True after a random event's `GO`: the party is on the map, not in camp.
        self.left_camp = False
        #: Every random event answered, in order; the summary lists them.
        self.events: list[dict] = []
        self.n = 0
        self._ssb = None
        #: Pools of Darkness' party-menu rows once a save is loaded.
        self.pod_rows = dict(POD_MENU_AFTER)
        #: Silver Blades' party-menu rows once a save is loaded.
        self.ssb_rows = dict(route_silver_blades.MENU_AFTER)
        #: Each roster line's sheet digest, once shown: two lines must never
        #: show the same sheet.
        self.sheets: dict[int, str] = {}
        #: Curse's `START.EXE` data segment, read once for `change`.
        self._class_ds: bytes | None = None
        #: Set by `run`: the X keysym `fight` presses once at the first
        #: command bar, or None.
        self.first_bar_key: str | None = None
        #: Set by `run` for `--intervene`: `fight` presses Alt+X once.
        self.intervene = False
        #: The `fight` steps begun so far; the first-bar key and Alt+X are
        #: the first fight's only.
        self.fights = 0
        #: The game's data segment, once a fight's combatants have read true.
        self.combat_ds: int | None = None
        #: The title's text font, once `display` has read it.
        self._font: dict[bytes, str] | None = None
        #: True from a `scribe` until a step that is not in `SCRIBE_KEEPS`
        #: begins, or a `rest` reports it: the scribe is still pending in camp.
        self.scribing = False
        #: When the driver was made, which is when the boot was over.
        self.began = time.time()
        #: What `snapshot` recorded of the driver's own place, by name.
        self._places: dict[str, dict] = {}
        #: The screen digest a snapshot taken after a `press` held, by name.
        self._screens: dict[str, str] = {}
        #: Set by `run` when a `vault` step follows: `begin` then takes
        #: Pools of Darkness' Elminster menu as its end instead of stopping.
        self.elminster_ok = False
        #: Pool's party place from memory (`pool_place`), for a walk whose
        #: status line hides the `x,y`; None without a debugger.
        self.place_reader: Callable[[], dict] | None = (
            self._memory_place if title == "pool" and hasattr(session, "attach")
            else None)
        self._live: dosnoencounters.LiveVariables | None = None

    # -- evidence ----------------------------------------------------------

    def shot(self, label: str) -> str:
        self.n += 1
        name = f"{self.n:03d}-{label}"
        self.s.shot(name, allow_blank=True)
        screen = self.s.capture()
        self.note(event="screen", shot=f"{name}.png", bar=bar_signature(screen),
                  glyphs=screen.glyphs(dosbox.BAR), digest=screen.digest())
        return name

    def fail(self, label: str, why: str) -> StepFailed:
        """The failure `why`, with a shot of the screen it happened at.

        The capture cannot raise: one that fails is recorded beside the reason
        and never replaces it.
        """
        try:
            name = self.shot(f"lost-{label}")
        except Exception as e:  # noqa: BLE001 -- the reason is what must survive
            self.capture_error = f"{type(e).__name__}: {e}"
            try:
                self.note(event="failure_capture_error", label=label,
                          error=self.capture_error)
            except Exception:  # noqa: BLE001
                pass
            return StepFailed(f"{why}; no failure capture ({self.capture_error})")
        return StepFailed(f"{why}; see {name}.png")

    def check_deadline(self, label: str) -> None:
        if self.deadline is not None:
            self.deadline.check(label)

    def bounded(self, wait: float, label: str) -> float:
        """`wait`, cut to what the route window has left."""
        if self.deadline is None:
            return wait
        return self.deadline.bound(wait, label)

    # -- helpers -----------------------------------------------------------

    @property
    def ssb(self) -> route_silver_blades.Route:
        """`route_silver_blades`'s Silver Blades route, numbering its shots with ours."""
        if self._ssb is None:
            self._ssb = route_silver_blades.Route(self.s, self.note)
            self._ssb.shot = self.shot
        return self._ssb

    def text(self, quiet: float = 0.5) -> str:
        return self.s.settle(quiet=quiet, timeout=20.0).digest(TEXT_WINDOW)

    def press_changes(self, key: str, tries: int = 2, wait: float = 5.0) -> bool:
        """Press `key` until the text window changes, at most `tries` times.

        Each press is given `wait` seconds to show before the next, so a key
        the game was merely slow to draw is not pressed twice.
        """
        before = self.text()
        for _ in range(tries):
            self.s.key(key)
            if self.s.wait_for(lambda sc: sc.digest(TEXT_WINDOW) != before, wait):
                self.text()
                return True
        return False

    def press_screen_changes(self, key: str, tries: int = 2,
                             wait: float = 10.0) -> bool:
        """Press `key` until the whole frame differs from before the first press.

        For the party menu and the prompts it opens, which do not animate.  A
        slot letter is pressed once only (`tries=1`): a second one landing on
        the party menu would be a command there -- `E` is exit to DOS in Curse.
        """
        before = self.s.capture().digest()
        for _ in range(tries):
            self.s.key(key)
            if self.s.wait_for(lambda sc: sc.digest() != before, wait):
                return True
        return False

    def save_path(self, letter: str) -> pathlib.Path:
        """The saved game a `save` step is believed by, in this title's suffix."""
        if self.title.suffix == ".DAT":
            return self.s.save_file(letter)
        return self.s.save_dir / f"SAVGAM{letter.upper()}{self.title.suffix}"

    def pod_menu(self, row: int, label: str) -> None:
        """Pools of Darkness' party menu: highlight `row`, pick it, and see
        the screen change."""
        before = self.s.capture().digest()
        got = self.s.walk_highlight(POD_MENU_RECT, row, key="Down")
        if got != row:
            raise self.fail(f"menu-{label}", f"the party menu's highlight reached "
                            f"row {got}, not {row}")
        self.s.key("Return")
        if not self.s.wait_for(lambda sc: sc.digest() != before, 20.0):
            raise self.fail(f"menu-{label}", f"row {row} of the party menu "
                            "changed nothing")

    def on_party_menu(self, screen=None) -> bool:
        screen = screen if screen is not None else self.s.capture()
        return self.party_sig is not None and bar_signature(screen) == self.party_sig

    def wait_party_menu(self, timeout: float) -> bool:
        return self.s.wait_for(self.on_party_menu, timeout)

    def in_camp(self, screen=None) -> bool:
        screen = screen if screen is not None else self.s.capture()
        return self.camp_sig is not None and bar_signature(screen) == self.camp_sig

    def wait_camp(self, timeout: float, hold: float = 1.0) -> bool:
        """Wait for the camp bar, and for it to still be there `hold` later."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.check_deadline("wait-camp")
            if self.in_camp():
                time.sleep(hold)
                if self.in_camp():
                    return True
            time.sleep(0.3)
        return False

    def on_world(self, screen=None) -> bool:
        screen = screen if screen is not None else self.s.capture()
        return self.world_ink is not None and screen.ink(dosbox.BAR) == self.world_ink

    def wait_file(self, path: pathlib.Path, was: bytes | None, label: str) -> None:
        deadline = time.time() + 60.0
        while not (path.is_file() and path.read_bytes() != was):
            if time.time() > deadline:
                raise self.fail(label, f"{path.name} never changed")
            self.check_deadline(label)
            time.sleep(0.3)
        dosbox.settle_files(self.s.save_dir, quiet=1.0,
                            timeout=self.bounded(30.0, label))

    def after_rest(self, timeout: float, in_step: str) -> str | None:
        """Wait out a rest: the camp bar, or Pool's `GO STAY` answered with GO.

        Nothing but `GO` is ever pressed at the event.  A third event, any
        screen that is neither the camp bar, the event nor (after an event)
        the map, or a text window that stops changing for `REST_STALL`
        seconds away from the camp bar, ends the run.  In Curse, a message
        over the one-button continue bar `CURSE_CONTINUE_BAR` ends the wait
        with nothing pressed and returns `"message"` (Tilverton's Royal
        Guards: `ECL01` entry 2 sets the rest interruption everywhere west of
        x 5 or north of y 13).
        """
        answered = 0
        while True:
            deadline = time.time() + self.bounded(timeout, "rest-end")
            screen = None
            last_text, changed = None, time.time()
            while time.time() < deadline:
                self.check_deadline("rest-end")
                screen = self.s.capture()
                if answered == 0 and self.in_camp(screen):
                    time.sleep(1.0)
                    if self.in_camp():
                        return
                elif answered and self.on_world(screen):
                    time.sleep(1.0)
                    if self.on_world():
                        self.left_camp = True
                        return
                if self.title.watch and bar_signature(screen) == WATCH_BAR:
                    break
                if (self.title.key == "curse" and answered == 0
                        and screen.glyphs(dosbox.BAR) == CURSE_CONTINUE_BAR):
                    return "message"
                text, now = screen.digest(TEXT_WINDOW), time.time()
                if text != last_text:
                    last_text, changed = text, now
                elif now - changed > REST_STALL:
                    raise self.fail(
                        "rest-end", f"nothing under the viewport changed for "
                        f"{REST_STALL:.0f} seconds and the camp bar is not back "
                        "(a message, a fight, or the game stopped)")
                time.sleep(0.3)
            else:
                raise self.fail(
                    "rest-end", "the camp bar never came back after resting "
                    "(interrupted, or a screen this driver does not know)")
            if answered >= MAX_EVENTS:
                raise self.fail("rest-events", f"another random event after "
                                f"{MAX_EVENTS} were answered")
            shot = self.shot(f"event-{answered + 1}")
            event = {"kind": "go_stay", "step": in_step, "shot": f"{shot}.png",
                     "bar": WATCH_BAR, "text": screen.digest(TEXT_WINDOW),
                     "answered": WATCH_GO.upper()}
            self.events.append(event)
            self.note(event="random", **event)
            self.s.key(WATCH_GO)
            answered += 1
            timeout = 60.0

    def ensure_camp(self) -> None:
        """Camp again when a random event's GO left the party on the map."""
        if self.left_camp:
            self.camp()

    def journal(self, label: str) -> bool:
        """Answer Pools of Darkness' journal question if it is showing.

        Shot first, answered by `dospod.answer_journal`, and listed in the
        summary's `events` as `journal`.  A question still showing after its
        answers stops the run with a `lost-journal-*.png`.  Other titles, and
        any other screen, get nothing pressed.
        """
        if self.title.key != "darkness" or not dospod.journal_question(self.s.capture()):
            return False
        shot = self.shot(f"journal-{label}")
        try:
            dospod.answer_journal(self.s)
        except TimeoutError as e:
            raise self.fail(f"journal-{label}", str(e)) from None
        event = {"kind": "journal", "step": label, "shot": f"{shot}.png",
                 "answered": dospod.JOURNAL_ANSWER.upper()}
        self.events.append(event)
        self.note(event="question", **event)
        return True

    def yes_no(self, label: str, limit: int | None = None) -> int:
        """Decline every Pools of Darkness `YES NO` bar showing, in turn.

        Each is shot, gets `POD_DECLINE` (pressed a second time only if the
        text window did not change), is waited out, and is listed in `events` as
        `yes_no`.  A bar still showing after `POD_YES_NO_ROUNDS` (or `limit`),
        or one `N` does not change, stops the run; a second `N` goes out only if
        the same bar and text are still showing when the first has had its 10
        seconds.  `Y` is never pressed.  Other titles get nothing pressed.  Returns how many were declined.
        """
        if self.title.key != "darkness":
            return 0
        declined = 0
        cap = POD_YES_NO_ROUNDS if limit is None else min(POD_YES_NO_ROUNDS, limit)
        while bar_signature(self.s.capture()) == POD_YES_NO_BAR:
            if declined >= cap:
                if cap < POD_YES_NO_ROUNDS:
                    raise self.fail("begin-interstitials", f"a YES NO bar is "
                                    f"showing after {POD_INTERSTITIALS} screens "
                                    "were answered")
                raise self.fail(f"yes-no-{label}", f"a YES NO bar is still showing "
                                f"after {declined} were declined")
            shot = self.shot(f"yes-no-{label}")
            # The text window and bar, not the whole frame, which a portrait
            # may animate.  The next question's text differs from this one's
            # even where its bar and highlight are the same.
            before = self.s.capture().digest(TEXT_WINDOW)
            for attempt in range(2):
                if attempt:
                    # A slow redraw must not get a second `N` it was not
                    # meant for: it would decline the next dialog unseen, or
                    # land on the map as a command key.
                    now = self.s.capture()
                    if (bar_signature(now) != POD_YES_NO_BAR
                            or now.digest(TEXT_WINDOW) != before):
                        break
                self.s.key(POD_DECLINE)
                if self.s.wait_for(lambda sc: sc.digest(TEXT_WINDOW) != before, 10.0):
                    break
            else:
                raise self.fail(f"yes-no-{label}", "NO changed nothing on the "
                                "YES NO bar")
            self.s.settle(quiet=1.0, timeout=60.0)
            event = {"kind": "yes_no", "step": label, "shot": f"{shot}.png",
                     "bar": POD_YES_NO_BAR, "answered": POD_DECLINE.upper()}
            self.events.append(event)
            self.note(event="question", **event)
            declined += 1
        return declined

    def press_continue(self, label: str, limit: int | None = None) -> int:
        """Continue past every Pools of Darkness story dialog showing, in turn.

        Each is shot, gets `POD_CONTINUE`, is waited out, and is listed in
        `events` as `press_continue`.  A sixth in a row, `limit` of them, or one
        `Return` does not change, stops the run.  A second `Return` goes out
        only if the same screen is still showing when the first has had its 10
        seconds; anything else is left to the caller's loop.  Other titles get
        nothing pressed.  Returns how many were answered.
        """
        if self.title.key != "darkness":
            return 0
        answered = 0
        cap = POD_CONTINUE_ROUNDS if limit is None else min(POD_CONTINUE_ROUNDS, limit)
        while bar_signature(self.s.capture()) == POD_CONTINUE_BAR:
            if answered >= cap:
                if cap < POD_CONTINUE_ROUNDS:
                    raise self.fail("begin-interstitials", f"a continue screen "
                                    f"is showing after {POD_INTERSTITIALS} "
                                    "screens were answered")
                raise self.fail(f"continue-{label}", f"a continue screen is still "
                                f"showing after {answered} were answered")
            shot = self.shot(f"continue-{label}")
            before = self.s.capture().digest(TEXT_WINDOW)
            for attempt in range(2):
                if attempt:
                    # A slow redraw, or a next screen whose text window has
                    # the same digest, must not get a key it was not meant for.
                    now = self.s.capture()
                    if (bar_signature(now) != POD_CONTINUE_BAR
                            or now.digest(TEXT_WINDOW) != before):
                        break
                self.s.key(POD_CONTINUE)
                if self.s.wait_for(lambda sc: sc.digest(TEXT_WINDOW) != before, 10.0):
                    break
            else:
                raise self.fail(f"continue-{label}", "Return changed nothing on "
                                "the continue screen")
            self.s.settle(quiet=1.0, timeout=60.0)
            event = {"kind": "press_continue", "step": label, "shot": f"{shot}.png",
                     "bar": POD_CONTINUE_BAR, "answered": POD_CONTINUE}
            self.events.append(event)
            self.note(event="question", **event)
            answered += 1
        return answered

    def press_continue_screens(self, screen, bar, label, rounds=None):
        """Return past `bar`'s `PRESS <ENTER>/<RETURN> TO CONTINUE` screens, one
        at a time, at most `rounds` (default `CONTINUE_ROUNDS`), shared by
        Curse's BEGIN, Pool's load and a `walk` step.

        Nothing is pressed when `bar` is not showing, so a screen that has
        already advanced is untouched.  Each Return pressed is recorded in
        `events` as `press_continue`.  Returns the settled screen.
        """
        rounds = CONTINUE_ROUNDS if rounds is None else rounds
        for _ in range(rounds):
            if screen.glyphs(dosbox.BAR) != bar:
                return screen
            shot = self.shot(f"continue-{label}")
            self.s.key(POD_CONTINUE)
            screen = self.s.settle(quiet=1.0, timeout=60.0)
            event = {"kind": "press_continue", "step": label, "shot": f"{shot}.png",
                     "bar": bar, "answered": POD_CONTINUE}
            self.events.append(event)
            self.note(event="question", **event)
        if screen.glyphs(dosbox.BAR) == bar:
            raise self.fail(f"{label}-continue", "a continue screen is still showing "
                            f"after {rounds} were answered")
        return screen

    def record_world(self, screen) -> None:
        self.game.record_map(screen)
        self.world_sig = bar_signature(screen)
        self.world_ink = screen.ink(dosbox.BAR)

    def bar_named(self, screen) -> str:
        """The command bar for a failure message: its words, read with the
        title's font when that can be read, and its `bar_signature`."""
        sig = bar_signature(screen)
        try:
            words = text_row(screen, BAR_ROW, self.display_font()).strip()
        except StepFailed:
            return f"the bar is {sig}"
        return f"the bar reads {words!r} ({sig})"

    def _pool_landed(self, screen) -> dict:
        """Pool's load when the screen past the continue prompts is no measured
        map bar: the party menu, read as text, is where a save made there
        loads, and the party is left on it for `begin`; anything else stops
        the run naming its bar.  Nothing is pressed either way, and the map
        `PoolOfRadiance.load_game` recorded off this screen is forgotten, so
        no later wait compares with it."""
        self.game.world_bar = self.game.world_glyphs = self.game.world_word = None
        font = self.display_font()
        menu = party_menu_entries(screen, font)
        if menu is None:
            raise self.fail("load-screen", f"slot {self.slot} loaded onto a screen "
                            "that is neither a measured map bar of POOL_MAP_BARS "
                            f"nor the party menu: {self.bar_named(screen)}")
        roster = party_roster(screen, font)
        if not roster:
            raise self.fail("load", f"slot {self.slot} loaded no party: the "
                            "party menu draws no roster")
        self.party_sig = bar_signature(screen)
        self.party_size = len(roster)
        self.line = 1
        self.where = "party"
        self.shot("loaded-party-menu")
        self.note(event="landed", step="load", where="party", functions=menu,
                  roster=roster)
        return {"slot": self.slot, "landed": "party", "party_menu": self.party_sig,
                "functions": menu, "roster": roster}

    # -- the steps ---------------------------------------------------------

    def load(self) -> dict:
        if self.title.key == "ssb":
            return self._load_ssb()
        if self.title.key == "darkness":
            return self._load_pod()
        self.game.to_main_menu()
        self.shot("menu")
        if self.title.key == "pool":
            try:
                self.game.load_game(self.slot)
            except TimeoutError as e:
                raise self.fail("load", str(e)) from None
            screen = self.press_continue_screens(self.s.capture(), POOL_CONTINUE_BAR, "load",
                                                 POOL_LOAD_CONTINUE_ROUNDS)
            kind = pool_map_kind(screen)
            if kind is None:
                return self._pool_landed(screen)
            self.record_world(screen)
            self.shot("loaded")
            self.where = "map"
            return {"slot": self.slot, "landed": "map", "status": self.game.status(),
                    "map_bar": self.world_sig, "map_kind": kind}
        self.s.settle(quiet=0.6, timeout=20.0)
        if not self.press_screen_changes(PARTY_LOAD):
            raise self.fail("load", "LOAD SAVED GAME did not open the slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("load-which")
        if not self.press_screen_changes(self.slot.lower(), tries=1, wait=30.0):
            raise self.fail("load", f"slot {self.slot} never loaded")
        screen = self.s.settle(quiet=1.0, timeout=90.0)
        if bar_signature(screen) != CURSE_PARTY_BAR:
            self.shot("lost-load")
            raise self.fail("load", f"slot {self.slot} did not leave the party "
                            f"menu's bar ({CURSE_PARTY_BAR}) showing: "
                            f"{bar_signature(screen)}")
        self.check_party_drawn(screen)
        self.party_sig = bar_signature(screen)
        self.shot("loaded")
        self.where = "party"
        return {"slot": self.slot, "party_menu": self.party_sig}

    def check_party_drawn(self, screen: dosbox.Screen) -> None:
        """A loaded party menu draws a highlighted name at the roster; the empty
        menu draws none, though its command bar is the same."""
        if (roster_line(screen, "party", self.party_size) is None
                or roster_name(screen, "party", 1) == BLANK_NAME):
            raise self.fail("load", f"slot {self.slot} loaded no party: the "
                            "party menu draws no roster")

    def _load_ssb(self) -> dict:
        path = self.save_path(self.slot)
        self.ssb_rows = route_silver_blades.menu_after(
            path.read_bytes() if path.is_file() else None)
        self.ssb.to_party_menu(deadline=self.deadline)
        self.ssb.menu(SSB_LOAD_ROW, "load")
        if not self.s.wait_for(lambda sc: self.ssb.bar(sc) != "party_menu", 20.0):
            raise self.fail("load", f"row {SSB_LOAD_ROW} of the party menu did "
                            "not open a slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("load-which")
        if not self.press_screen_changes(self.slot.lower(), tries=1, wait=30.0):
            raise self.fail("load", f"slot {self.slot} never loaded")
        screen = self.ssb.wait_bar("party_menu", timeout=90.0, deadline=self.deadline)
        self.check_party_drawn(screen)
        self.party_sig = bar_signature(screen)
        self.shot("loaded")
        self.where = "party"
        return {"slot": self.slot, "party_menu": self.party_sig,
                "menu_rows": self.ssb_rows}

    def _load_pod(self) -> dict:
        """Past the titles to the party menu, `Load Saved Game`, then `POOLS`
        at `LOAD FROM WHERE?` and the slot letter, each pressed once and given
        30 seconds, so a key meant for one screen never lands on the next."""
        path = self.save_path(self.slot)
        self.pod_rows = pod_menu_after(path.read_bytes() if path.is_file() else None)
        answered = dospod.to_party_menu(self.s, deadline=self.deadline)
        self.shot("menu")
        self.pod_menu(POD_LOAD_ROW, "load")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("load-from")
        if not self.press_screen_changes(POD_LOAD_FROM, tries=1, wait=30.0):
            raise self.fail("load-from", "POOLS at LOAD FROM WHERE? did not "
                            "open the slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("load-which")
        if not self.press_screen_changes(self.slot.lower(), tries=1, wait=30.0):
            raise self.fail("load", f"slot {self.slot} never loaded")
        screen = self.s.settle(quiet=1.0, timeout=90.0)
        self.party_sig = bar_signature(screen)
        self.shot("loaded")
        self.where = "party"
        return {"slot": self.slot, "party_menu": self.party_sig,
                "questions_answered": len(answered), "menu_rows": self.pod_rows}

    def begin(self) -> dict:
        if self.where != "party":
            if self.title.key == "pool" and self.where == "map":
                raise StepFailed("begin needs the party menu, and this load put "
                                 "the party on the map")
            raise StepFailed("begin needs the party menu")
        if self.title.key == "ssb":
            self.ssb.menu(self.ssb_rows["begin"], "begin")
            self.ssb.intro(deadline=self.deadline)
        elif self.title.key == "darkness":
            self.pod_menu(self.pod_rows["begin"], "begin")
        else:
            if self.title.key == "pool":
                screen = self.s.settle(quiet=0.6, timeout=20.0)
                menu = party_menu_entries(screen, self.display_font())
                if menu is None or PARTY_BEGIN_ENTRY not in menu:
                    raise self.fail("begin-menu", f"not the party menu offering "
                                    f"{PARTY_BEGIN_ENTRY}: {self.bar_named(screen)}, "
                                    f"the functions {menu}")
            if not self.press_screen_changes(PARTY_BEGIN, tries=1, wait=30.0):
                raise self.fail("begin", "BEGIN ADVENTURING did not leave the party menu")
        screen = self.s.settle(quiet=1.0, timeout=60.0)
        if self.title.key == "curse":
            screen = self.press_continue_screens(screen, CURSE_CONTINUE_BAR, "begin")
        elif self.title.key == "pool":
            screen = self.press_continue_screens(screen, POOL_CONTINUE_BAR, "begin",
                                                 POOL_LOAD_CONTINUE_ROUNDS)
        # Pools of Darkness asks its journal question between the party menu
        # and the map, every time the party begins, and its arrival may ask a
        # YES NO question after that.
        answered = 0

        def interstitials(screen):
            nonlocal answered
            while True:
                # The bound is on screens, so each helper gets what is left of it.
                if POD_INTERSTITIALS > answered:
                    got = int(self.journal("begin"))
                else:
                    got = 0
                got += self.yes_no("begin", POD_INTERSTITIALS - answered - got)
                got += self.press_continue("begin", POD_INTERSTITIALS - answered - got)
                if not got:
                    return screen
                answered += got
                screen = self.s.settle(quiet=1.0, timeout=60.0)

        screen = interstitials(screen)
        if (self.title.key == "darkness"
                and bar_signature(screen) == POD_ELMINSTER_BAR):
            if self.elminster_ok:
                self.shot("elminster")
                self.where = "elminster"
                return {"map_bar": None, "map_kind": "elminster",
                        "bar": POD_ELMINSTER_BAR}
            # The destination menu behind MOVE ON is unmeasured, so a start
            # there is recognised and stopped at, with nothing pressed.
            self.shot("town-screen")
            raise self.fail("begin-screen", "the party starts at Elminster's "
                            "menu in Limbo, which this driver leaves only for "
                            "the vault (load begin vault); use the party-menu "
                            "steps (load 'view 1' 'save D' read) otherwise")
        if self.on_party_menu(screen):
            raise self.fail("begin", "the party menu is still showing")
        kind = None
        if self.title.key == "darkness":
            kind = next((k for k, bar in POD_MAP_BARS.items()
                         if bar_signature(screen) == bar), None)
            if kind is None:
                if not POD_MAP_BARS:
                    raise self.fail("begin-screen", "no Pools of Darkness map bar "
                                    "has been measured yet (POD_MAP_BARS), so the "
                                    "screen Begin reached is not taken for the map")
                raise self.fail("begin-screen", "the screen Begin reached is not "
                                "a measured map bar of POD_MAP_BARS (a story "
                                "screen or a message this driver does not know)")
            self.note(event="map_bar", map=kind, bar=POD_MAP_BARS[kind])
        elif self.title.key == "pool":
            kind = pool_map_kind(screen)
            if kind is None:
                raise self.fail("begin-screen", "the screen BEGIN ADVENTURING "
                                "reached is not a measured map bar of "
                                f"POOL_MAP_BARS: {self.bar_named(screen)}")
            self.note(event="map_bar", map=kind, bar=POOL_MAP_BARS[kind])
        self.record_world(screen)
        self.shot("map")
        self.where = "map"
        return {"map_bar": self.world_sig, "map_kind": kind}

    def bar_text(self, screen) -> list[str]:
        """The command bar's words, read with the title's font."""
        return text_row(screen, BAR_ROW, self.display_font()).split()

    def press_bar(self, key: str, screen, label: str, *, page: bool = False):
        """Press `key` and wait for the bar to change, or with `page` for the
        list above it to; the settled screen and its bar's words."""
        ink, rows = screen.ink(dosbox.BAR), screen.digest(VAULT_LIST_RECT)
        self.s.key(key)
        if page:
            changed = self.s.wait_for(lambda sc: sc.digest(VAULT_LIST_RECT) != rows,
                                      self.bounded(20.0, label))
        else:
            changed = self.s.wait_while_ink(dosbox.BAR, ink, self.bounded(20.0, label))
        if not changed:
            raise self.fail(label, f"{key} changed nothing: {self.bar_named(screen)}")
        screen = self.s.settle(quiet=1.0, timeout=self.bounded(30.0, label))
        return screen, self.bar_text(screen)

    def installed_vault(self) -> dict:
        """The installed `VAULT<L>.DAT` as the game will read it: absent is
        an empty vault (`GAME.OVR` 0x138FA finds no file and reads nothing)."""
        path = self.s.save_dir / f"VAULT{self.slot}.DAT"
        if not path.is_file():
            return {"file": None, "items": 0, "platinum": 0, "gems": 0, "jewelry": 0}
        v = dos_codec.pod_vault_from_dos(path.read_bytes())
        return {"file": path.name, "items": len(v.items), "platinum": v.platinum,
                "gems": v.gems, "jewelry": v.jewelry}

    def vault_pages(self, screen, words: list[str]) -> list[dict]:
        """Every page of the vault's item list, read as text, turned with
        `NEXT` while the bar offers it; a page reading as the one before
        ends the reading."""
        font = self.display_font()
        limit = vault_page_limit(self.held_vault()["items"])
        pages: list[dict] = []
        while True:
            rows = [text_row(screen, r, font, VAULT_TEXT_COLUMNS).strip()
                    for r in VAULT_ITEM_ROWS]
            if pages and rows == pages[-1]["rows"]:
                break
            pages.append({"shot": self.shot(f"vault-items-{len(pages) + 1}"),
                          "bar": words, "rows": rows,
                          "items": [r for r in rows if r]})
            if "NEXT" not in words:
                break
            if len(pages) >= limit:
                raise self.fail("vault-pages", f"the vault's list still offers "
                                f"NEXT after {limit} pages, all that its "
                                f"{self.held_vault()['items']} items fill")
            screen, words = self.press_bar(ITEMS_NEXT, screen, "vault-next", page=True)
        return pages

    def vault(self) -> dict:
        """Pools of Darkness, at Elminster's menu: `STORAGE`, the vault's
        items listed through `TAKE`, and `EXIT` back to the menu."""
        if self.title.key != "darkness" or self.where != "elminster":
            raise StepFailed("vault needs Elminster's menu in Limbo, which "
                             "begin reaches for a party saved in area 18")
        expected = self.installed_vault()
        screen = self.s.settle(quiet=0.6, timeout=self.bounded(30.0, "vault-settle"))
        menu = self.bar_text(screen)
        if bar_signature(screen) != POD_ELMINSTER_BAR:
            raise self.fail("vault-menu", f"Elminster's menu is not showing: "
                            f"{self.bar_named(screen)}")
        if "STORAGE" not in menu:
            raise self.fail("vault-storage", f"Elminster's menu reads {menu} with "
                            f"no STORAGE: variable ${POD_STORAGE_VAR:02X} is 1; "
                            f"stage --stage-var {POD_STORAGE_VAR:02X}=0")
        screen, words = self.press_bar(ELMINSTER_STORAGE, screen, "vault-open")
        if not is_vault_bar(words):
            raise self.fail("vault-open", f"STORAGE did not open the vault: "
                            f"{self.bar_named(screen)}")
        bar = words
        self.shot("vault")
        prompt, pages = False, []
        if "TAKE" in bar:
            screen, words = self.press_bar(VAULT_TAKE, screen, "vault-take")
            if tuple(words) == VAULT_TAKE_PROMPT:
                prompt = True
                self.shot("vault-take")
                screen, words = self.press_bar(VAULT_TAKE_ITEMS, screen,
                                               "vault-take-items")
            if is_vault_bar(words) or tuple(words) == VAULT_TAKE_PROMPT:
                raise self.fail("vault-list", f"TAKE opened no item list: "
                                f"{self.bar_named(screen)}")
            pages = self.vault_pages(screen, words)
            screen = self.s.capture()
            if "EXIT" not in self.bar_text(screen):
                raise self.fail("vault-list-exit", f"the vault's list offers no "
                                f"EXIT: {self.bar_named(screen)}")
            screen, words = self.press_bar(VAULT_EXIT, screen, "vault-list-exit")
            if tuple(words) == VAULT_TAKE_PROMPT:
                screen, words = self.press_bar(VAULT_EXIT, screen, "vault-take-exit")
            if not is_vault_bar(words):
                raise self.fail("vault-back", f"leaving the list did not bring the "
                                f"vault back: {self.bar_named(screen)}")
        screen, words = self.press_bar(VAULT_EXIT, screen, "vault-exit")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == POD_ELMINSTER_BAR,
                               self.bounded(30.0, "vault-exit")):
            raise self.fail("vault-exit", f"EXIT did not bring Elminster's menu "
                            f"back: {self.bar_named(self.s.capture())}")
        dosbox.settle_files(self.s.save_dir, quiet=1.0,
                            timeout=self.bounded(30.0, "vault-file"))
        self.shot("vault-left")
        written = tmpvault(self.s.save_dir)
        names = (written or {}).get("names", [])
        check = vault_window_check([p["items"] for p in pages], names)
        listed = len(names) if check["covered"] else None
        return {"menu": menu, "vault_bar": bar, "take_prompt": prompt,
                "pages": pages, "window": check, "listed": listed,
                "expected": expected,
                "matches": check["covered"] and listed == expected["items"],
                "tmpvault": written}

    def held_vault(self) -> dict:
        """The vault the game holds now: the `TMPVAULT.DAT` this boot's last
        exit from the vault wrote, which the loader reads in place of the
        slot's file while it is there (`GAME.OVR` 0x1379B), or else the
        installed `VAULT<L>.DAT`."""
        written = tmpvault(self.s.save_dir)
        if written is not None and "error" not in written:
            return {"file": written["file"],
                    **{k: written[k] for k in ("items", "platinum", "gems", "jewelry")}}
        return self.installed_vault()

    def deposit(self, line: int, row: int) -> dict:
        """Pools of Darkness, at Elminster's menu: `STORAGE`, roster line
        `line` highlighted, `ITEMS`, row `row` highlighted and `DEPOSIT`d,
        `EXIT` twice back to the menu; then the vault read back as `vault`
        reads it.  The run stops before `D` when the row is readied or the
        list's last, and when the list does not lose exactly that row."""
        if self.title.key != "darkness" or self.where != "elminster":
            raise StepFailed("deposit needs Elminster's menu in Limbo, which "
                             "the vault step leaves the party at")
        label = f"deposit-{line}-{row}"
        before = self.held_vault()
        font = self.display_font()
        screen = self.s.settle(quiet=0.6, timeout=self.bounded(30.0, f"{label}-settle"))
        if bar_signature(screen) != POD_ELMINSTER_BAR:
            raise self.fail(f"{label}-menu", f"Elminster's menu is not showing: "
                            f"{self.bar_named(screen)}")
        if "STORAGE" not in self.bar_text(screen):
            raise self.fail(f"{label}-storage", "Elminster's menu offers no STORAGE")
        screen, words = self.press_bar(ELMINSTER_STORAGE, screen, f"{label}-open")
        if not is_vault_bar(words):
            raise self.fail(f"{label}-open", f"STORAGE did not open the vault: "
                            f"{self.bar_named(screen)}")
        picked = self.pick_line(line, VAULT_ROSTER, f"{label}-member")
        screen = self.s.settle(quiet=0.6, timeout=self.bounded(30.0, f"{label}-member"))
        words = self.bar_text(screen)
        if "ITEMS" not in words:
            raise self.fail(f"{label}-items", f"the vault bar offers no ITEMS for "
                            f"line {line}, who has no items: {words}")
        screen, words = self.press_bar(VAULT_ITEMS, screen, f"{label}-items")
        if not on_items_list(screen) or "DEPOSIT" not in words:
            raise self.fail(f"{label}-items", f"ITEMS opened no list with DEPOSIT: "
                            f"{self.bar_named(screen)}")
        head = text_row(screen, VAULT_ITEMS_HEAD_ROW, font, VAULT_TEXT_COLUMNS).strip()
        owner = head[:-len(VAULT_ITEMS_HEAD)] if head.endswith(VAULT_ITEMS_HEAD) else None
        moved = self.pick_item(row, f"{label}-select")
        screen = self.s.settle(quiet=0.6, timeout=self.bounded(30.0, f"{label}-select"))
        rows_before = item_rows(screen)
        ready, name = vault_item_entry(text_row(
            screen, ITEM_TEXT_ROW + row - 1, font, VAULT_TEXT_COLUMNS))
        shot_before = self.shot(f"{label}-before")
        if ready is not False:
            raise self.fail(f"{label}-ready", f"row {row} ({name}) is "
                            + ("readied, and the game deposits only an item "
                               "that is not" if ready else "not read as YES or NO"))
        if rows_before is None or row >= rows_before:
            raise self.fail(f"{label}-rows", f"row {row} is the last of the "
                            f"{rows_before} rows the list draws; what DEPOSIT "
                            "does with the last item is not measured")
        self.s.key(VAULT_DEPOSIT)
        self.s.wait_for(lambda sc: item_rows(sc) != rows_before,
                        self.bounded(10.0, f"{label}-deposit"))
        screen = self.s.settle(quiet=0.8, timeout=self.bounded(30.0, f"{label}-deposit"))
        rows_after = item_rows(screen)
        shot_after = self.shot(f"{label}-after")
        if rows_after != rows_before - 1:
            raise self.fail(f"{label}-deposit", f"DEPOSIT left {rows_after} rows "
                            f"of {rows_before}")
        screen, words = self.press_bar(VAULT_ITEMS_EXIT, screen, f"{label}-list-exit")
        if not is_vault_bar(words):
            raise self.fail(f"{label}-back", f"leaving the list did not bring the "
                            f"vault back: {self.bar_named(screen)}")
        screen, words = self.press_bar(VAULT_EXIT, screen, f"{label}-exit")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == POD_ELMINSTER_BAR,
                               self.bounded(30.0, f"{label}-exit")):
            raise self.fail(f"{label}-exit", f"EXIT did not bring Elminster's menu "
                            f"back: {self.bar_named(self.s.capture())}")
        dosbox.settle_files(self.s.save_dir, quiet=1.0,
                            timeout=self.bounded(30.0, f"{label}-file"))
        written = tmpvault(self.s.save_dir)
        readback = self.vault()
        coins = ("platinum", "gems", "jewelry")
        names = (written or {}).get("names") or []
        why = None
        if written is None or "error" in written:
            why = f"leaving the vault wrote no readable {TMPVAULT}: {written}"
        elif written["items"] != before["items"] + 1:
            why = (f"{TMPVAULT} holds {written['items']} items after one deposit "
                   f"into {before['items']}")
        elif not same_name(name, names[-1]):
            why = f"{TMPVAULT}'s last item is {names[-1]}, not the deposited {name}"
        elif any(written[k] != before[k] for k in coins):
            why = (f"{TMPVAULT}'s coins {[written[k] for k in coins]} moved from "
                   f"{[before[k] for k in coins]}")
        elif readback["listed"] != written["items"]:
            why = (f"the vault listed {readback['listed']} items where "
                   f"{TMPVAULT} holds {written['items']}")
        return {"line": line, "row": row, "owner": owner, "item": name,
                "member_presses": picked["presses"], "row_presses": moved["presses"],
                "rows_before": rows_before, "rows_after": rows_after,
                "before": before, "tmpvault": written, "readback": readback,
                "shots": [shot_before, shot_after], "why": why}

    def elminster_camp(self) -> dict:
        """Camp from Elminster's menu: `REST` runs `PROGRAM 9`, the camp loop
        (`GAME.OVR` 0x21FF calls 0x2108, which calls it at 0x104F1)."""
        screen = self.s.settle(quiet=0.6, timeout=self.bounded(30.0, "camp-settle"))
        if bar_signature(screen) != POD_ELMINSTER_BAR:
            raise self.fail("camp-elminster", f"Elminster's menu is not showing: "
                            f"{self.bar_named(screen)}")
        screen, words = self.press_bar(ELMINSTER_REST, screen, "camp-elminster")
        if not words or words[0] != "SAVE" or words[-1] != "EXIT":
            raise self.fail("camp-elminster", f"REST did not open the camp bar: "
                            f"{self.bar_named(screen)}")
        self.camp_sig = bar_signature(screen)
        self.left_camp = False
        self.where = "camp"
        self.shot("camp")
        return {"camp_bar": self.camp_sig, "from": "elminster", "words": words}

    def camp(self) -> dict:
        if self.where == "elminster":
            return self.elminster_camp()
        # `E` at Curse's and Pool's party menu is exit to DOS, so it is never
        # pressed there; in Pool it goes out only on a measured map bar.  The
        # screen is judged once settled, and Pool's is given `CAMP_MAP_WAIT`
        # for its map bar, so a frame caught mid-redraw does not stop the run.
        screen = self.s.settle(quiet=0.6, timeout=self.bounded(30.0, "camp-settle"))
        if (self.title.key == "pool" and pool_map_kind(screen) is None
                and not self.on_party_menu(screen)
                and self.s.wait_for(lambda sc: pool_map_kind(sc) is not None,
                                    self.bounded(CAMP_MAP_WAIT, "camp-map"))):
            screen = self.s.settle(quiet=0.6, timeout=self.bounded(30.0, "camp-settle"))
        if self.on_party_menu(screen):
            hint = ("; a Pool save made at the party menu loads there, and "
                    "`begin` after `load` leaves it" if self.title.key == "pool" else "")
            raise self.fail("camp", f"the party menu is showing, not the map{hint}")
        if self.title.key == "pool" and pool_map_kind(screen) is None:
            raise self.fail("camp", "ENCAMP is pressed only on a measured map bar "
                            f"of POOL_MAP_BARS: {self.bar_named(screen)}")
        world = self.game.world_bar or self.game.bar()
        for _ in range(2):
            self.s.key(ENCAMP)
            if not self.s.wait_while_ink(dosbox.BAR, world, 30.0):
                raise self.fail("camp", "ENCAMP did not change the command bar")
            screen = self.s.settle(quiet=1.5, timeout=30.0)
            if self.world_sig is None or bar_signature(screen) != self.world_sig:
                break
        else:
            raise self.fail("camp", "the map's own bar is still showing after ENCAMP")
        self.camp_sig = bar_signature(screen)
        self.world_ink = world
        self.left_camp = False
        self.where = "camp"
        self.shot("camp")
        return {"camp_bar": self.camp_sig}

    def leave(self) -> dict:
        """Curse and Silver Blades: the camp bar's `Exit`, back to the map.

        `CAMP_EXIT` is pressed only while the camp bar shows, twice at most,
        and the step is believed when the map's bar is back (`on_world`, or
        the map word `game.on_map` compares, which Curse's cursor leaves
        alone).
        """
        if self.title.key not in LEAVE_TITLES:
            raise StepFailed(f"leave is driven in {', '.join(sorted(LEAVE_TITLES))} "
                             f"only, not {self.title.key}")
        if self.where != "camp" or self.camp_sig is None:
            raise StepFailed("leave needs camp first")
        presses = 0
        for _ in range(2):
            screen = self.s.capture()
            if not self.in_camp(screen):
                break
            self.s.key(CAMP_EXIT)
            presses += 1
            self.s.wait_while_ink(dosbox.BAR, screen.ink(dosbox.BAR),
                                  self.bounded(15.0, "leave-camp"))
        screen = self.s.settle(quiet=1.0, timeout=30.0)
        if self.in_camp(screen):
            raise self.fail("leave-camp", f"the camp bar still shows after "
                            f"{presses} presses of Exit")
        if not (self.on_world(screen) or self.game.on_map(screen)):
            raise self.fail("leave-map", "Exit left camp for a screen that is "
                            "not the map")
        if not self.on_world(screen):
            self.record_world(screen)
        self.where = "map"
        self.shot("left-camp")
        return {"presses": presses, "map_bar": self.world_sig}

    def map_status(self, label: str, screens: list[dict]) -> tuple[str, str | None]:
        """The settled map's status line and its `x,y` square, with a shot,
        appended to `screens`; a screen that is not the map stops the run."""
        screen = self.s.settle(quiet=0.6, timeout=30.0)
        if not self.on_world(screen):
            raise self.fail(label, "the map bar did not return (combat or "
                            "an unknown screen)")
        status = self.game.status()
        column = status_column(self.title.key)
        # Only Pool's line is known to print `x,y facing clock`, so only Pool
        # can tell a missing `x,y` from a square; other titles read it as before.
        square = (map_square if self.title.key == "pool" else status_square)(
            screen, column)
        entry = {"shot": self.shot(label), "bar": bar_signature(screen),
                 "status": status, "square": square}
        # Each read halts the game, and a debugger that does not answer costs
        # retries: read the origin once as the baseline, then only a screen
        # whose line hides the square.
        if self.place_reader is not None and (
                square is None or label in ("walk-before", "turn-before")):
            entry["place"] = self.party_place(label)
        screens.append(entry)
        return status, square

    def _memory_place(self) -> dict:
        """Pool's `POOL_PLACE` through the debugger, at one halt; the data
        segment is the one `LiveVariables` proves by its clock digits."""
        if self._live is None:
            self._live = dosnoencounters.LiveVariables(self.s, dosnoencounters.POOL)
        with self._live as live:
            raw = self.s.read((live.ds, POOL_PLACE), 5)
            area = self.s.read((live.ds, POOL_AREA), 1)
        place = pool_place(raw)
        if place is None:
            raise ValueError(f"DS:{POOL_PLACE:04X} reads {raw.hex()}, no square")
        return {**place, "area": area[0], "raw": raw.hex(), "ds": f"{live.ds:04X}"}

    def party_place(self, label: str) -> dict | None:
        """The party's place from memory (`place_reader`), logged as `place`,
        or None when it did not read, logged as `place-unread`."""
        try:
            place = self.place_reader()
        except (dosnoencounters.SwitchError, dosboxx.NotHalted, RuntimeError,
                ValueError, OSError) as e:
            self.note(event="place-unread", label=label,
                      why=f"{type(e).__name__}: {e}")
            return None
        self.note(event="place", label=label, **place)
        return place

    @staticmethod
    def same_place(origin: dict | None, screens: list[dict]) -> bool | None:
        """For the latest reading: whether memory shows the party on
        `origin`'s square, or None when either place is unread."""
        place = screens[-1].get("place") if screens else None
        if origin is None or place is None:
            return None
        return (place["x"], place["y"]) == (origin["x"], origin["y"])

    def settle_after_turns(self, label: str, origin: str, screens: list[dict]) -> None:
        """Wait for the `x,y` to read again after turns that hid it; it must
        equal `origin`, and one that never reads fails `walk-status`."""
        column = status_column(self.title.key)
        self.s.wait_for(lambda s: map_square(s, column) is not None,
                        self.bounded(10.0, label))
        _, square = self.map_status(label, screens)
        if square is None:
            raise self.fail("walk-status", "the status line had no x,y after "
                            "the turns, so they were not shown to leave the "
                            "square")
        if square != origin:
            raise self.fail(label, "the square changed on a turn")

    def press_walk_stories(self, label: str) -> dosbox.Screen:
        """Return past the title's `WALK_CONTINUE_BARS` story boxes a step
        landed on, `WALK_CONTINUE_ROUNDS` at most, each logged as
        `press_continue`; returns the settled screen after them.  Nothing is
        pressed on any other screen, so combat or an unknown screen is left
        for the caller to stop at."""
        screen = self.s.settle(quiet=0.6, timeout=30.0)
        bar = WALK_CONTINUE_BARS.get(self.title.key)
        if bar is None:
            return screen
        return self.press_continue_screens(screen, bar, label, WALK_CONTINUE_ROUNDS)

    def walk(self, route: str) -> dict:
        """From the loaded Pool or Curse map, turn around and step one square.

        A step is believed only when the `x,y` on the status line changes:
        the clock on the same line ticks on a wall's bump, and a line drawn
        for the first time differs from a blank one, so the whole strip says
        nothing about a step.  A blank line is never the starting reading.
        A story box the step lands on is answered with `Return`
        (`press_walk_stories`) before the map bar is looked for.
        """
        if self.title.key in MOVE_KEYS and self.where == "map" and route == "1":
            return self._walk_one()
        if (self.title.key == "pool" and self.where == "map"
                and route not in WALKS["pool"] and POOL_WALK_LETTERS.fullmatch(route)):
            return self._walk_letters(route)
        if self.title.key not in ("pool", "curse") or self.where != "map" \
                or route not in WALKS[self.title.key]:
            raise StepFailed("walk MI needs a Pool of Radiance or Curse map; "
                            "walk I needs Pool of Radiance")

        screens: list[dict] = []

        def record(label: str) -> tuple[str, str | None]:
            return self.map_status(label, screens)

        before, origin = record("walk-before")
        origin_place = screens[-1].get("place")
        # Pool's memory read stands in for a line that hides the `x,y`.
        if origin is None and origin_place is None:
            raise self.fail("walk-status", "the status line is blank on the map, "
                            "so there is no starting square (a shop or an "
                            "arrival draws it later)")
        hidden = False
        for n in (1, 2) if route == "MI" else ():
            label = f"walk-turn-{n}"
            if not self.game.turn_right():
                raise self.fail(label, "the map bar did not return "
                                "after turning (combat or an unknown screen)")
            _, square = record(label)
            if origin is None:
                # A line square cannot be compared with a memory origin.
                if square is not None:
                    screens[-1]["place"] = self.party_place(label)
                if self.hidden_turn(label, origin_place, screens):
                    raise self.fail("walk-status", "memory did not read after "
                                    "the turn, so it was not shown to leave "
                                    "the square")
            elif square is None:
                hidden = self.hidden_turn(label, origin_place, screens) or hidden
            elif square != origin:
                raise self.fail(label, "the square changed on a turn")
        if hidden:
            self.settle_after_turns("walk-turns-after", origin, screens)
        stepped = self.game.step()
        screen = self.press_walk_stories("walk-step")
        if not stepped and not self.on_world(screen):
            raise self.fail("walk-step", "the map bar did not return after the "
                            "step (combat or an unknown screen)")
        after, square = record("walk-step")
        # A line without the `x,y` after the step, or a walk that began without
        # one, is read from memory.
        if origin is None and square is not None and self.place_reader is not None:
            screens[-1]["place"] = self.party_place("walk-step")
        same = (self.same_place(origin_place, screens)
                if square is None or origin is None else square == origin)
        if same is None:
            raise self.fail("walk-status", "the status line was blank after the step")
        if same:
            raise self.fail("walk-blocked", "the settled status did not change "
                            "after Up: the x,y square is the same (a blocked "
                            "step; a clock tick is not a step)")
        return {"route": route, "map_bar": self.world_sig,
                "status_before": before, "status_after": after,
                "square_before": origin, "square_after": square,
                "place_before": origin_place,
                "place_after": screens[-1].get("place"),
                "screens": screens}

    def _walk_letters(self, route: str) -> dict:
        """Pool: `I` steps forward, `J` turns left and `K` turns right, in turn.

        Each move is judged from the party's place in memory (`POOL_PLACE`
        and `POOL_AREA`, `place_reader`): a step must change the square or
        the area, and a turn must leave both alone, so an area changes only
        on the step that crosses into the next one.  A story box a step lands
        on gets `Return` (`press_walk_stories`).  The last step may end on a
        screen that is not the map, such as the temple's `DO YOU SEEK
        HEALING?`; its text is kept as `arrival` and the party's place is
        `arrival` for the next step.  On any earlier move a screen that is
        not the map stops the run.
        """
        if self.place_reader is None:
            raise StepFailed("a walk of I, J and K moves reads the party's square "
                             "from memory, which needs the DOSBox-X debugger")
        screens: list[dict] = []
        self.map_status("walk-before", screens)
        here = screens[-1].get("place")
        if here is None:
            raise self.fail("walk-status", "the party's square did not read from "
                            "memory before the walk")
        moves: list[dict] = []
        arrival = None
        for n, letter in enumerate(route, 1):
            label = f"walk-{n}-{letter}"
            if letter == "I":
                back = self.game.step()
                screen = self.press_walk_stories(label)
                if not back and not self.on_world(screen):
                    if n < len(route):
                        raise self.fail(label, "the map bar did not return after "
                                        "the step (combat or an unknown screen)")
                    arrival = self.screen_text(screen)
            elif not (self.game.turn_left() if letter == "J" else self.game.turn_right()):
                raise self.fail(label, "the map bar did not return after turning "
                                "(combat or an unknown screen)")
            shot = self.shot(label)
            place = self.party_place(label)
            if place is None:
                raise self.fail("walk-status", f"the party's square did not read "
                                f"from memory after move {n} ({letter})")
            before = (here["x"], here["y"], here["area"])
            after = (place["x"], place["y"], place["area"])
            if letter == "I" and after == before:
                raise self.fail("walk-blocked", f"move {n} (I) left the party on "
                                f"{before[0]},{before[1]} in area {before[2]}: a "
                                "blocked step")
            if letter != "I" and after != before:
                raise self.fail(label, f"the square changed on a turn: move {n} "
                                f"({letter}) went from {before} to {after}")
            moves.append({"move": letter, "before": list(before), "after": list(after),
                          "facing": place["facing"], "crossed": after[2] != before[2],
                          "shot": shot})
            here = place
        if arrival is not None:
            self.where = "arrival"
        return {"route": route, "moves": moves,
                "place_before": screens[0].get("place"), "place_after": here,
                "crossings": [i for i, m in enumerate(moves, 1) if m["crossed"]],
                "arrival": arrival, "screens": screens}

    # -- Pool's temple -----------------------------------------------------------

    def temple_raise(self, line: int) -> dict:
        """Buy RAISE DEAD at Pool's temple for roster line `line`, from the
        arrival question a walk ended on, and leave to the map.

        `YES` to `DO YOU SEEK HEALING?`; line `line` highlighted at the
        temple bar (`POOL_ROSTER_NEXT`); its sheet read for money (`VIEW`,
        `Escape`); `HEAL`, the service list read and its highlight moved
        with `dosbox.LIST_DOWN` onto `RAISE DEAD`, read after each press;
        `HEAL` there; the price read off `PAY FOR CURE YES NO`; `YES`, and
        the message window watched until the list has held
        `TEMPLE_RESULT_HOLD` seconds; then the list's `EXIT`, the sheet read
        again, and the temple's `EXIT` to the map.  `outcome` is no-money by
        the message the window drew (`TEMPLE_OUTCOMES`); alive when no such
        message came, the roster line's hit points read `TEMPLE_RAISED_HP`
        after and the sheet's money changed; and unknown otherwise.  The
        game draws no message for a raise and rolls nothing, so there is
        no failed outcome to read.  Each key goes only to the screen it
        belongs to; any other screen stops the run with nothing more
        pressed.
        """
        if self.title.key != "pool":
            raise StepFailed("temple raise is driven in pool only")
        if self.where != "arrival":
            raise StepFailed("temple raise begins at the temple's arrival "
                             "question, where a walk to the temple ends")
        font = self.display_font()
        shots: list[str] = []
        here = self.screen_text(self.s.settle(quiet=0.6, timeout=self.bounded(
            20.0, "temple-arrival")))
        if TEMPLE_ARRIVAL not in here["text"] or here["bar"] != "YES NO":
            raise self.fail("temple-arrival", f"not the temple's arrival "
                            f"question: {here}")
        shots.append(self.shot("temple-arrival"))
        screen = self._temple_key(TEMPLE_YES, lambda t: t["bar"] == TEMPLE_BAR,
                                  "temple-bar")
        self.where = "temple"
        moved = self.pick_line(line, "camp", "temple-select", POOL_ROSTER_NEXT)
        screen = self.s.settle(quiet=0.6, timeout=self.bounded(20.0, "temple-select"))
        name = text_row(screen, 3 + line, font, range(17, 33)).strip()
        roster_before = text_row(screen, 3 + line, font, range(17, 39)).strip()
        shots.append(self.shot("temple-bar"))
        money_before = self._temple_sheet(name, "temple-sheet-before", shots)
        screen = self._temple_key(TEMPLE_HEAL, lambda t: t["bar"] == TEMPLE_LIST_BAR,
                                  "temple-list")
        services = [text_row(screen, r, font, range(1, 39)).strip()
                    for r in TEMPLE_LIST_ROWS]
        title = text_row(screen, TEMPLE_TITLE_ROW, font, range(1, 39)).strip()
        if not title.startswith(f"{name},"):
            raise self.fail("temple-list", f"the service list is not {name}'s: "
                            f"{title!r}")
        if TEMPLE_RAISE not in services:
            raise self.fail("temple-list", f"no {TEMPLE_RAISE} row: {services}")
        presses = self._temple_highlight(services.index(TEMPLE_RAISE))
        shots.append(self.shot("temple-raise-row"))
        screen = self._temple_key(TEMPLE_HEAL, lambda t: t["bar"] != TEMPLE_LIST_BAR,
                                  "temple-price")
        asked = self.screen_text(screen)
        shots.append(self.shot("temple-price"))
        price = TEMPLE_PRICE.search(asked["text"])
        if asked["bar"] != TEMPLE_PRICE_BAR or price is None:
            raise self.fail("temple-price", f"{TEMPLE_RAISE} gave no price: {asked}")
        self.s.key(TEMPLE_YES)
        messages = self._temple_messages(asked["text"])
        shots.append(self.shot("temple-result"))
        screen = self._temple_key(TEMPLE_EXIT, lambda t: t["bar"] == TEMPLE_BAR,
                                  "temple-bar-after")
        roster_after = text_row(screen, 3 + line, font, range(17, 39)).strip()
        money_after = self._temple_sheet(name, "temple-sheet-after", shots)
        hp_after = roster_after.split()[-1] if roster_after else ""
        outcome = next((o for want, o in TEMPLE_OUTCOMES
                        if any(want in m for m in messages)), None)
        if outcome is None:
            outcome = ("alive" if hp_after == str(TEMPLE_RAISED_HP)
                       and money_after != money_before else "unknown")
        self.s.key(TEMPLE_EXIT)
        if not self.s.wait_for(self.on_world, self.bounded(20.0, "temple-leave")):
            left = self.screen_text(self.s.capture())
            raise self.fail("temple-leave", f"EXIT did not bring the map back: {left}")
        self.where = "map"
        shots.append(self.shot("temple-left"))
        return {"member": name, "line": line, "line_presses": moved["presses"],
                "services": services, "list_presses": presses,
                "price": int(price.group(1)), "price_coin": price.group(2),
                "price_text": asked["text"], "messages": messages,
                "outcome": outcome, "gold_before": money_before.get("GOLD", 0),
                "gold_after": money_after.get("GOLD", 0),
                "money_before": money_before, "money_after": money_after,
                "roster_before": roster_before, "roster_after": roster_after,
                "shots": shots}

    def _temple_key(self, key: str, arrived, label: str):
        """Press `key` and wait for the screen whose `screen_text` `arrived`
        accepts; the settled screen, or the run stops at `label`."""
        self.s.key(key)
        if not self.s.wait_for(lambda sc: arrived(self.screen_text(sc)),
                               self.bounded(20.0, label)):
            raise self.fail(label, f"{key} did not bring the next temple screen: "
                            f"{self.screen_text(self.s.capture())}")
        return self.s.settle(quiet=0.6, timeout=self.bounded(20.0, label))

    def _temple_sheet(self, name: str, label: str, shots: list[str]) -> dict[str, int]:
        """From the temple bar, `VIEW` the highlighted member, check the sheet
        is `name`'s, read its money (`SHEET_MONEY`) and go back."""
        font = self.display_font()
        screen = self._temple_key(
            TEMPLE_VIEW, lambda t: t["bar"] != TEMPLE_BAR and t["bar"].startswith("VIEW"),
            label)
        shots.append(self.shot(label))
        if text_row(screen, 1, font, range(1, 26)).strip() != name:
            raise self.fail(label, f"the sheet is not {name}'s")
        money = {coin: int(n) for r in SHEET_MONEY_ROWS
                 for coin, n in SHEET_MONEY.findall(text_row(screen, r, font, range(1, 27)))}
        self._temple_key(TEMPLE_SHEET_BACK, lambda t: t["bar"] == TEMPLE_BAR,
                         f"{label}-back")
        return money

    def _temple_highlight(self, row: int) -> int:
        """Move the service list's highlight onto `row` with `dosbox.LIST_DOWN`,
        reading it after each press; the presses."""
        presses = 0
        here = self.s.capture().highlight_row(TEMPLE_LIST_RECT)
        while here != row:
            if here is None or presses > len(TEMPLE_LIST_ROWS):
                raise self.fail("temple-row", f"the list's highlight is on row "
                                f"{here}, not {row}, after {presses} presses")
            self.s.key(dosbox.LIST_DOWN)
            presses += 1
            was = here
            self.s.wait_for(lambda sc, was=was: sc.highlight_row(TEMPLE_LIST_RECT) != was,
                            self.bounded(5.0, "temple-row"))
            here = self.s.capture().highlight_row(TEMPLE_LIST_RECT)
            if here == was:
                raise self.fail("temple-row", f"{dosbox.LIST_DOWN} did not move "
                                f"the list's highlight off row {here}")
        return presses

    def _temple_messages(self, price: str) -> list[str]:
        """The texts the message window draws after `YES` at the price, in
        order, until the service list has held `TEMPLE_RESULT_HOLD` seconds
        with the window clear, within `TEMPLE_RESULT_SECONDS`."""
        seen: list[str] = []
        end = time.time() + self.bounded(TEMPLE_RESULT_SECONDS, "temple-result")
        held_since = None
        while time.time() < end:
            now = self.screen_text(self.s.capture())
            if now["text"] and now["text"] != price and (not seen or seen[-1] != now["text"]):
                seen.append(now["text"])
                self.note(event="temple-message", text=now["text"], bar=now["bar"])
            if now["bar"] == TEMPLE_LIST_BAR and not now["text"]:
                held_since = held_since or time.time()
                if time.time() - held_since >= TEMPLE_RESULT_HOLD:
                    return seen
            else:
                held_since = None
            time.sleep(0.1)
        raise self.fail("temple-result", f"the service list did not come back "
                        f"clear after YES; drawn: {seen}")

    def screen_text(self, screen) -> dict:
        """The text window's rows and the bar of `screen`, read with the
        title's font, blank rows left out."""
        font = self.display_font()
        rows = [text_row(screen, r, font, range(1, 39)).strip()
                for r in POOL_MESSAGE_ROWS]
        return {"text": " ".join(r for r in rows if r),
                "bar": text_row(screen, BAR_ROW, font).strip()}

    def hidden_turn(self, label: str, origin_place: dict | None,
                    screens: list[dict]) -> bool:
        """A turn whose status line has no `x,y`: False when memory shows the
        party still on `origin_place`'s square, True when the square is
        unknown; memory showing another square fails `label`."""
        same = self.same_place(origin_place, screens)
        if same is False:
            place = screens[-1]["place"]
            raise self.fail(label, f"the square changed on a turn (memory reads "
                            f"{place['x']},{place['y']}, it was "
                            f"{origin_place['x']},{origin_place['y']})")
        return same is None

    def _walk_one(self) -> dict:
        """Press MOVE, step one square forward, and press EXIT back to the map.

        The keys are `MOVE_KEYS`' for the title: Silver Blades leaves move mode
        with `e`, Pools of Darkness with `Escape`.

        The party is already facing as it was saved, so the first try is
        `Up`; past a wall it turns right and tries again, three turns at most.
        A step is believed only when the `x,y` on the status line changes,
        and a key that moved the roster highlight instead stops the run.
        """
        screens: list[dict] = []
        column = status_column(self.title.key)
        enter, leave = MOVE_KEYS[self.title.key]
        map_screen = self.s.capture()
        if not self.on_world(map_screen):
            raise self.fail("walk-before", "the map bar is not showing")
        line = roster_line(map_screen, "camp", self.party_size)
        if line is None:
            raise self.fail("walk-roster", "no highlighted roster line on the "
                            "map to tell a roster move from a step")
        map_bar = self.world_sig
        try:
            self.s.key(enter)
            if not self.s.wait_while_ink(dosbox.BAR, self.world_ink, 15.0):
                raise self.fail("walk-move", f"the map bar did not change after "
                                f"{enter} (no move mode)")
            settled = self.s.settle(quiet=0.6, timeout=30.0)
            if bar_signature(settled) == self.world_sig:
                raise self.fail("walk-move", f"the map bar did not change after "
                                f"{enter} (no move mode)")
            move_bar = bar_signature(settled)
            self.game.record_map(settled)
            origin = status_square(settled, column)
            screens.append({"shot": self.shot("walk-move"), "bar": move_bar,
                            "square": origin})

            def settle(label: str) -> str | None:
                screen = self.s.settle(quiet=0.6, timeout=30.0)
                if bar_signature(screen) != move_bar:
                    raise self.fail(label, "the move bar did not return (combat "
                                    "or an unknown screen)")
                if roster_line(screen, "camp", self.party_size) != line:
                    raise self.fail("walk-roster", "the roster highlight moved: "
                                    "the key went to the roster selector")
                square = status_square(screen, column)
                screens.append({"shot": self.shot(label), "bar": move_bar,
                                "square": square})
                return square

            if origin is None:
                # Move mode draws no status line on entry; the first turn
                # does, and four turns bring the party back to its facing.
                for n in range(1, 5):
                    label = f"walk-circle-{n}"
                    if not self.game.turn_right():
                        raise self.fail(label, "the move bar did not return "
                                        "after turning")
                    square = settle(label)
                    if square is None:
                        raise self.fail("walk-status", "the status line stayed "
                                        "blank after a turn")
                    if origin is None:
                        origin = square
                    elif square != origin:
                        raise self.fail(label, "the square changed on a turn")

            turns = 0
            for attempt in range(4):
                label = f"walk-step-{attempt + 1}"
                if not self.game.step():
                    raise self.fail(label, "the move bar did not return after "
                                    "the step (combat or an unknown screen)")
                square = settle(label)
                if square is None:
                    raise self.fail("walk-status", "the status line was blank "
                                    "after the step")
                if square != origin:
                    break
                if attempt == 3:
                    raise self.fail("walk-blocked", "no facing let the party "
                                    "step (the square never changed)")
                label = f"walk-turn-{attempt + 1}"
                if not self.game.turn_right():
                    raise self.fail(label, "the move bar did not return after "
                                    "turning")
                if settle(label) != origin:
                    raise self.fail(label, "the square changed on a turn")
                turns += 1
            if bar_signature(self.s.capture()) != move_bar:
                raise self.fail("walk-back", "not at the move bar to leave it")
            self.s.key(leave)
            if not self.s.wait_until_ink(dosbox.BAR, self.world_ink, 15.0):
                raise self.fail("walk-back", f"{leave} did not return "
                                "to the map bar")
            back = self.s.settle(quiet=0.6, timeout=30.0)
            screens.append({"shot": self.shot("walk-back"),
                            "bar": bar_signature(back)})
            return {"route": "1", "map_bar": map_bar, "move_bar": move_bar,
                    "turns": turns, "square_before": origin,
                    "square_after": square,
                    "status_before": map_screen.ink(dosbox.STATUS),
                    "status_after": back.ink(dosbox.STATUS),
                    "roster_line": line, "screens": screens}
        finally:
            self.game.record_map(map_screen)

    def turn(self, presses: int) -> dict:
        """Turn right `presses` times on the map and prove no square changed.

        The control of a walk: a turn moves the facing and never the square,
        so a run whose `read` then shows the saved place unchanged has shown
        that the walk's change was the step.  The party is left on the map, so
        `camp`, `save` and `read` may follow.
        """
        if self.where != "map":
            raise StepFailed("turn needs the loaded map")
        if self.title.key in ("pool", "curse"):
            return self._turn_pool(presses)
        if self.title.key in MOVE_KEYS:
            return self._turn_move(presses)
        raise StepFailed(f"turn is not driven in {self.title.key}")

    def _turn_pool(self, presses: int) -> dict:
        screens: list[dict] = []
        _, origin = self.map_status("turn-before", screens)
        if origin is None:
            raise self.fail("walk-status", "the status line is blank on the map, "
                            "so there is no starting square (a shop or an "
                            "arrival draws it later)")
        origin_place = screens[-1].get("place")
        hidden = False
        for n in range(1, presses + 1):
            label = f"walk-turn-{n}"
            self.check_deadline(label)
            if not self.game.turn_right():
                raise self.fail(label, "the map bar did not return after "
                                "turning (combat or an unknown screen)")
            _, square = self.map_status(label, screens)
            if square is None:
                hidden = self.hidden_turn(label, origin_place, screens) or hidden
            elif square != origin:
                raise self.fail(label, "the square changed on a turn")
        if hidden:
            self.settle_after_turns("walk-turns-after", origin, screens)
        return {"route": "turn", "turns": presses, "map_bar": self.world_sig,
                "square_before": origin, "square_after": origin,
                "place_before": origin_place,
                "place_after": screens[-1].get("place"),
                "screens": screens}

    def _turn_move(self, presses: int) -> dict:
        """Press MOVE, turn `presses` times, press EXIT (`MOVE_KEYS`' for the title).

        Move mode draws no status line on entry, so when it is blank the first
        turn's reading is the baseline and only the turns after it are
        compared; one turn alone then proves nothing and stops the run.
        """
        screens: list[dict] = []
        column = status_column(self.title.key)
        enter, leave = MOVE_KEYS[self.title.key]
        map_screen = self.s.capture()
        if not self.on_world(map_screen):
            raise self.fail("walk-before", "the map bar is not showing")
        line = roster_line(map_screen, "camp", self.party_size)
        if line is None:
            raise self.fail("walk-roster", "no highlighted roster line on the "
                            "map to tell a roster move from a turn")
        map_bar = self.world_sig
        try:
            self.s.key(enter)
            if not self.s.wait_while_ink(dosbox.BAR, self.world_ink, 15.0):
                raise self.fail("walk-move", f"the map bar did not change after "
                                f"{enter} (no move mode)")
            settled = self.s.settle(quiet=0.6, timeout=30.0)
            if bar_signature(settled) == self.world_sig:
                raise self.fail("walk-move", f"the map bar did not change after "
                                f"{enter} (no move mode)")
            move_bar = bar_signature(settled)
            self.game.record_map(settled)
            origin = status_square(settled, column)
            screens.append({"shot": self.shot("walk-move"), "bar": move_bar,
                            "square": origin})
            compared = 0
            for n in range(1, presses + 1):
                label = f"walk-turn-{n}"
                self.check_deadline(label)
                if not self.game.turn_right():
                    raise self.fail(label, "the move bar did not return after "
                                    "turning")
                screen = self.s.settle(quiet=0.6, timeout=30.0)
                if bar_signature(screen) != move_bar:
                    raise self.fail(label, "the move bar did not return (combat "
                                    "or an unknown screen)")
                if roster_line(screen, "camp", self.party_size) != line:
                    raise self.fail("walk-roster", "the roster highlight moved: "
                                    "the key went to the roster selector")
                square = status_square(screen, column)
                screens.append({"shot": self.shot(label), "bar": move_bar,
                                "square": square})
                if square is None:
                    raise self.fail("walk-status", "the status line was blank "
                                    "after a turn")
                if origin is None:
                    origin = square
                elif square != origin:
                    raise self.fail(label, "the square changed on a turn")
                else:
                    compared += 1
            if not compared:
                raise self.fail("walk-status", "the status line was blank on "
                                "entering move mode, so one turn gives a starting "
                                "square and nothing to compare it with; ask for "
                                "two turns or more")
            if bar_signature(self.s.capture()) != move_bar:
                raise self.fail("walk-back", "not at the move bar to leave it")
            self.s.key(leave)
            if not self.s.wait_until_ink(dosbox.BAR, self.world_ink, 15.0):
                raise self.fail("walk-back", f"{leave} did not return "
                                "to the map bar")
            back = self.s.settle(quiet=0.6, timeout=30.0)
            screens.append({"shot": self.shot("walk-back"),
                            "bar": bar_signature(back)})
            return {"route": "turn", "turns": presses, "map_bar": map_bar,
                    "move_bar": move_bar, "square_before": origin,
                    "square_after": origin, "roster_line": line,
                    "screens": screens}
        finally:
            self.game.record_map(map_screen)

    # -- a fight ----------------------------------------------------------------

    def fight(self, seconds: int = 0, first_bar: bool = False) -> dict:
        """Walk until a fight starts, and fight it to its end with `QUICK`.

        The walk (`Explorer`) steps in move mode in Silver Blades and at the
        map bar in Curse, and a step is believed only when the status line's
        square changes.  Every bar the walk or the fight shows is answered by
        `FIGHT_KEYS`, and each kind of bar is shot the first time it shows.
        At each command bar the debugger reads who acts (`combat_memory`) and
        the step logs a `bar` event; at the first it also logs `placement`,
        every combatant's square, side, quickfight and control, and presses
        `first_bar_key` once instead of `QUICK`, so the next reading of the
        bar is logged as a bar of its own.  The bar after that key reads every
        record again (`after-first-bar-key`), which is where a key that
        changed a quickfight byte shows.  With `intervene` Alt+X is pressed
        once at that bar (at the first without a first-bar key) and a command
        bar coming back fails the step; the defeat screen fails it at once.
        The step ends when the map bar has
        held `FIGHT_SETTLED` seconds after the fight, with the party left on
        the map; `seconds` bounds walk and fight together.  Pool walks and
        answers its bars its own way (`_pool_fight`).

        With `first_bar` the step ends at the first command bar, once the
        placement and who acts are logged and the bar shot, pressing nothing
        there; the fight is left running, so only `shot` and `read` may come after it.
        """
        key = self.title.key
        if key not in FIGHT_TITLES:
            raise StepFailed(f"fight is driven in {', '.join(sorted(FIGHT_TITLES))} "
                             f"only, not {key}")
        if self.where != "map":
            raise StepFailed("fight needs the map")
        if not hasattr(self.s, "attach"):
            raise StepFailed("fight reads the combatants through the DOSBox-X "
                             "debugger, and this session has none")
        if key == "pool":
            return self._pool_fight(seconds, first_bar)
        map_screen = self.s.capture()
        if not self.on_world(map_screen):
            raise self.fail("fight-before", "the map bar is not showing")
        budget = float(seconds or FIGHT_SECONDS)
        end = time.time() + self.bounded(budget, "fight")
        self.fights += 1
        first_fight = self.fights == 1
        column = status_column(key)
        enter, leave = MOVE_KEYS.get(key, (None, None))
        walker = Explorer()
        state = self._fight_state(first_fight, enter)
        if first_bar:
            state.update(first_bar_key=None, intervene=False, stop_at_first=True)
        try:
            while True:
                self.check_deadline("fight")
                if time.time() > end:
                    raise self.fail("fight-budget", self._fight_short(budget, walker, state))
                try:
                    if self._fight_tick(walker, column, enter, state):
                        break
                except dosboxx.NotLineDoubled:
                    # A grab torn between two blits of an animation, in any
                    # wait of the tick; the next one is whole.  Where the walk
                    # stood is read again.
                    state["torn"] += 1
                    walker.square = None
                    time.sleep(0.25)
            if state["stopped"]:
                self.where = "pressed"
                return self._first_bar_result(state, {
                    "walked": walker.steps, "walked_before_fight": state["met_after"],
                    "squares": len(walker.visits), "bumps": walker.bumps})
            last = self.s.capture()
            if enter and bar_signature(last) == state["walking"]:
                self.s.key(leave)
                if not self.s.wait_until_ink(dosbox.BAR, self.world_ink, 15.0):
                    raise self.fail("fight-back", f"{leave} did not return to "
                                    "the map bar after the fight")
        finally:
            self.game.record_map(map_screen)
        self.where = "map"
        self._fight_shot("fight-end")
        bars = state["bars"]
        return {"fight": self.fights,
                "walked": walker.steps, "walked_before_fight": state["met_after"],
                "squares": len(walker.visits), "bumps": walker.bumps,
                "presses": state["presses"], "encounters": state["encounters"],
                "bars": len(bars),
                "actors": [b["actor"]["name"] if b["actor"] else None for b in bars],
                "placement": state["placement"],
                "first_bar_key": state["first_bar_key"] if state["key_pressed"] else None,
                "handed_back": state["handed_back"],
                "handed_back_to": self._handed_back_to(state),
                "before_hand_back": state["before_hand_back"],
                "combat_probes": state["probes"],
                "intervened": state["intervened"],
                "after_first_bar_key": state["after_key"],
                "ds": None if state["ds"] is None else f"{state['ds']:04X}",
                "torn_frames": state["torn"], "loose_frames": state["loose"],
                "repeated_bars": state["repeats"],
                "screens": state["kinds"]}

    def _first_bar_result(self, state: dict, walk: dict) -> dict:
        """What `fight first-bar` records: the walk, the placement, who acts
        at the first command bar, and its shot."""
        bars = state["bars"]
        return {"fight": self.fights, "first_bar": True, **walk,
                "presses": state["presses"], "encounters": state["encounters"],
                "bars": len(bars),
                "actor": bars[0]["actor"] if bars else None,
                "placement": state["placement"],
                "first_bar_shot": state["first_bar_shot"],
                "ds": None if state["ds"] is None else f"{state['ds']:04X}",
                "torn_frames": state["torn"], "loose_frames": state["loose"],
                "screens": state["kinds"]}

    def _pool_fight(self, seconds: int, first_bar: bool) -> dict:
        """Pool's `fight`: walk with `dosfightwatch.walk_to_encounter` until a
        fight bar shows, then answer each bar by `PoolOfRadiance.COMBAT_KEYS`
        (its digests, `bar_kind`), logging the command bars as `fight` does
        (`_command_bar`).  The fight is over once the map bar has held
        `FIGHT_SETTLED` seconds; with `first_bar` the step ends at the first
        command bar instead.  A bar with no key that holds `FIGHT_PATIENCE`
        seconds stops the run, as does the map coming back before any
        command bar in a `first_bar` step.
        """
        map_screen = self.s.capture()
        if not self.on_world(map_screen):
            raise self.fail("fight-before", "the map bar is not showing")
        budget = float(seconds or FIGHT_SECONDS)
        end = time.time() + self.bounded(budget, "fight")
        self.fights += 1
        try:
            walk = dosfightwatch.walk_to_encounter(self.game, POOL_FIGHT_WALK_STEPS)
            self.note(event="fight-walk", **walk)
            if not walk["met"]:
                raise self.fail("fight-walk", f"no encounter: {walk.get('why')}")
            state = self._fight_state(True, None)
            state.update(first_bar_key=None, intervene=False, hand_back=False,
                         met=True, met_after=walk["walked"],
                         stop_at_first=first_bar)
            while not state["stopped"]:
                self.check_deadline("fight")
                if time.time() > end:
                    raise self.fail("fight-budget", self._fight_short(
                        budget, Explorer(), state))
                if self._pool_fight_tick(state, first_bar):
                    break
        finally:
            self.game.record_map(map_screen)
        moved = {"walked": walk["walked"], "blocked": walk["blocked"],
                 "prompts": walk["prompts"], "walked_before_fight": walk["walked"]}
        if state["stopped"]:
            self.where = "pressed"
            return self._first_bar_result(state, moved)
        self.where = "map"
        self._fight_shot("fight-end")
        bars = state["bars"]
        return {"fight": self.fights, **moved,
                "presses": state["presses"], "encounters": state["encounters"],
                "bars": len(bars),
                "actors": [b["actor"]["name"] if b["actor"] else None for b in bars],
                "placement": state["placement"],
                "ds": None if state["ds"] is None else f"{state['ds']:04X}",
                "torn_frames": state["torn"], "loose_frames": state["loose"],
                "repeated_bars": state["repeats"], "screens": state["kinds"]}

    def _pool_fight_tick(self, state: dict, first_bar: bool) -> bool:
        """One look at a Pool fight and one answer; True once the map bar
        has held `FIGHT_SETTLED` seconds."""
        screen = self._look(state)
        glyphs = screen.glyphs(dosbox.BAR)
        if glyphs == self.game.world_glyphs:
            if first_bar:
                raise self.fail("fight-first-bar", "the map came back before "
                                "any command bar")
            state["unknown_since"] = None
            state["back_since"] = state["back_since"] or time.time()
            if time.time() - state["back_since"] >= FIGHT_SETTLED:
                return True
            time.sleep(0.25)
            return False
        state["back_since"] = None
        kind = self.game.bar_kind(screen)
        self._first_sight(kind, glyphs, screen, state)
        if kind == "command":
            state["unknown_since"] = None
            self._command_bar(glyphs, state)
            return False
        key = self.game.COMBAT_KEYS.get(kind or "")
        if key is None:
            if kind == "blank":
                state["last_bar"] = None
            state["unknown_since"] = state["unknown_since"] or time.time()
            if time.time() - state["unknown_since"] >= FIGHT_PATIENCE:
                raise self.fail(f"fight-unknown-{glyphs}",
                                f"a bar with no key ({kind or 'unclassified'}) "
                                f"stayed {FIGHT_PATIENCE:.0f} s")
            time.sleep(0.25)
            return False
        state["unknown_since"] = None
        state["last_bar"] = None
        if kind == "encounter":
            state["encounters"] += 1
        self._answer(key, glyphs, kind, state)
        return False

    def _fight_state(self, first_fight: bool, enter: str | None) -> dict:
        """What `_fight_tick` keeps across one fight's looks, fresh."""
        state: dict = {"met": False, "met_after": None, "bars": [],
                       "placement": None, "after_key": None, "records": {},
                       "kinds": {}, "encounters": 0, "presses": 0,
                       "key_pressed": False, "intervened": False, "after_intervene": None,
                       "ds": None, "torn": 0, "loose": 0,
                       "last_bar": None, "repeats": 0, "unknown_shots": 0,
                       "back_since": None, "unknown_since": None,
                       "walking": None if enter else self.world_sig,
                       "first_bar_key": self.first_bar_key if first_fight else None,
                       "intervene": self.intervene and first_fight,
                       "hand_back": not first_fight, "handed_back": False,
                       "before_hand_back": None, "begun": False,
                       "stale_window": None, "probed_at": None, "probes": 0,
                       "stop_at_first": False, "stopped": False,
                       "first_bar_shot": None}
        if not first_fight:
            # What the last fight left in the combat window, so that a fight
            # with no encounter menu and no command bar is still seen to begin.
            state["stale_window"] = self._combat_window_raw()
        return state

    def _combat_window_raw(self) -> bytes | None:
        """`combat_window`'s bytes under the `DS` an earlier fight read true,
        in one halt, or None when there is none or the read is blocked."""
        if self.combat_ds is None:
            return None
        lo, n = combat_window(COMBAT_LAYOUTS[self.title.key])
        if not self.s.attach():
            return None
        try:
            return self.s.read((self.combat_ds, lo), n)
        except (dosboxx.NotHalted, RuntimeError, ValueError):
            return None
        finally:
            self.s.run()

    def _combat_begun(self, state: dict) -> bool:
        """Whether this fight's combat has begun: the encounter menu was
        answered, the placement was read, or the combat window differs from
        what the last fight left (`stale_window`) and reads as a fight.  The
        window is read at most every `COMBAT_PROBE_SECONDS`, each read logged
        as `combat-probe`; a fight with no window to compare never probes."""
        if state["begun"] or state["encounters"] > 0 or state["placement"] is not None:
            return True
        if state["stale_window"] is None:
            return False
        now = time.time()
        if state["probed_at"] is not None and now - state["probed_at"] < COMBAT_PROBE_SECONDS:
            return False
        state["probed_at"] = now
        state["probes"] += 1
        raw = self._combat_window_raw()
        why = None
        if raw is None:
            why = "unread"
        elif raw == state["stale_window"]:
            why = "unchanged"
        else:
            lo, _ = combat_window(COMBAT_LAYOUTS[self.title.key])
            try:
                read_combat(raw, lo, COMBAT_LAYOUTS[self.title.key])
            except CombatUnread as e:
                why = f"not a fight: {e}"
        state["begun"] = why is None
        self.note(event="combat-probe", begun=state["begun"], why=why)
        return state["begun"]

    def _before_hand_back(self, kind: str | None, state: dict) -> None:
        """Every combatant's side, quickfight and control as they stand before
        `HAND_BACK`, logged as `before-hand-back` and kept for the result.  A
        read that fails is logged as `before-hand-back-unread` and the fight
        goes on."""
        try:
            snap = self.combat_memory(True, state["records"])
        except StepFailed as e:
            state["before_hand_back"] = None
            self.note(event="before-hand-back-unread", kind=kind, why=str(e))
            return
        state["ds"] = snap["ds"]
        state["before_hand_back"] = [{k: c.get(k) for k in PLACEMENT_FIELDS}
                                     for c in snap["combatants"]]
        self.note(event="before-hand-back", kind=kind,
                  combatants=state["before_hand_back"])

    @staticmethod
    def _handed_back_to(state: dict) -> list[str] | None:
        """The party members `HAND_BACK` applies to, those whose control byte
        read below 0x80 at the fight's placement; None when it was not
        pressed or no command bar was read after it."""
        if not state["handed_back"] or state["placement"] is None:
            return None
        return [c["name"] for c in state["placement"]
                if c.get("party") and c.get("control") is not None
                and c["control"] < 0x80]

    # -- Prayer's combat handlers ------------------------------------------------

    def prayer_watch(self, node: int) -> dict:
        """Walk to a fight and log Prayer's handlers as the attacks roll.

        `node` is the effect id under test, 49 or (Pool only) 35.  Pool walks
        with `dosfightwatch.walk_to_encounter` and arms at the encounter menu;
        Curse and Silver Blades walk as `fight` does and arm at the first
        command bar, once `placement` is logged (`_prayer_walk`).  There the
        debugger reads every member's nodes and Prayer's handler table, then
        breaks on the stubs; once a stub's far jump names the overlay segment
        the four routines are armed there (`dosfightwatch.PrayerWatch`, with
        the title's `PRAYER_LAYOUTS`).  Each halt is logged as a `prayer-halt`
        event.  The step ends after one party attack round (id 49; in Curse and
        Silver Blades a monster's attack must also have reached the penalty),
        three quiet party attacks (id 35) or `PRAYER_FIGHT_SECONDS` of fight,
        and the run is `conclusive: False` when no member carried the node when
        the watch was armed or at the stop.  The emulator is left running
        mid-fight, so only `shot`, `press` and `read` may follow.
        """
        why = prayer_watch_rejection(self.title.key, node)
        if why:
            raise StepFailed(why)
        if self.where != "map":
            raise StepFailed("prayer-watch needs the map")
        if not hasattr(self.s, "attach"):
            raise StepFailed("prayer-watch reads the game through the DOSBox-X "
                             "debugger, and this session has none")
        source = pathlib.Path(self.s.source)
        image, _ = unexepack.unpack((source / "START.EXE").read_bytes())
        later = self.title.key != "pool"
        watch = dosfightwatch.PrayerWatch(self.s, (source / "GAME.OVR").read_bytes(),
                                          image, note=self.note, node_id=node,
                                          title=self.title.key, until_penalty=later)
        # Keys are pressed from here on, so wherever the step ends the party's
        # place is unknown to the steps after it.
        self.where = "pressed"
        if later:
            walk, state = self._prayer_walk()
            self.note(event="prayer-walk", **walk)
            self.shot("prayer-first-bar")
            if time.time() - self.began > PRAYER_BOOT_SECONDS:
                raise self.fail("prayer-boot", f"the first command bar came after "
                                f"{PRAYER_BOOT_SECONDS} s")
            # The `DS` the placement read true holds the handler table too.
            watch.ds = self.combat_ds
            fight_end = time.time() + self.bounded(PRAYER_FIGHT_SECONDS, "prayer-watch")
            return self._prayer_fight(watch, node, walk, fight_end,
                                      self._prayer_idle(state), "first-bar")
        walk = dosfightwatch.walk_to_encounter(self.game, PRAYER_WALK_STEPS)
        self.note(event="prayer-walk", **walk)
        if not walk["met"]:
            raise self.fail("prayer-walk", f"no encounter: {walk.get('why')}")
        self.shot("prayer-encounter")
        if time.time() - self.began > PRAYER_BOOT_SECONDS:
            raise self.fail("prayer-boot", f"the encounter menu came after "
                            f"{PRAYER_BOOT_SECONDS} s")
        fight_end = time.time() + self.bounded(PRAYER_FIGHT_SECONDS, "prayer-watch")
        world_since: list[float | None] = [None]

        def idle() -> bool:
            """Answer the fight's bar; True once the map has held `FIGHT_SETTLED`."""
            screen, kind = dosfightwatch._grab(self.game)
            if screen is None:
                return False
            if screen.glyphs(dosbox.BAR) == self.game.world_glyphs:
                world_since[0] = world_since[0] or time.time()
                return time.time() - world_since[0] > FIGHT_SETTLED
            world_since[0] = None
            key = self.game.COMBAT_KEYS.get(kind or "")
            if key:
                self.s.key(key)
                time.sleep(0.6)
            return False

        return self._prayer_fight(watch, node, walk, fight_end, idle, "encounter")

    def _prayer_walk(self) -> tuple[dict, dict]:
        """Curse and Silver Blades: walk as `fight` does (`Explorer`, bars
        answered by `FIGHT_KEYS`) until its first command bar has logged
        `placement`, within `FIGHT_SECONDS`.  Returns the walk and the fight's
        state, which `_prayer_idle` goes on with."""
        key = self.title.key
        map_screen = self.s.capture()
        if not self.on_world(map_screen):
            raise self.fail("prayer-before", "the map bar is not showing")
        self.fights += 1
        column = status_column(key)
        enter, _ = MOVE_KEYS.get(key, (None, None))
        walker = Explorer()
        state = self._fight_state(self.fights == 1, enter)
        # Nothing but QUICK is pressed at a command bar while Prayer is watched.
        state.update(first_bar_key=None, intervene=False)
        end = time.time() + self.bounded(FIGHT_SECONDS, "prayer-watch")
        try:
            while state["placement"] is None:
                self.check_deadline("prayer-watch")
                if time.time() > end:
                    raise self.fail("prayer-walk",
                                    self._fight_short(FIGHT_SECONDS, walker, state))
                try:
                    if self._fight_tick(walker, column, enter, state):
                        raise self.fail("prayer-walk", "the fight ended before "
                                        "any command bar")
                except dosboxx.NotLineDoubled:
                    state["torn"] += 1
                    walker.square = None
                    time.sleep(0.25)
        finally:
            self.game.record_map(map_screen)
        return {"met": True, "walked": walker.steps,
                "walked_before_fight": state["met_after"],
                "squares": len(walker.visits), "bumps": walker.bumps,
                "encounters": state["encounters"], "presses": state["presses"],
                "ds": None if state["ds"] is None else f"{state['ds']:04X}"}, state

    def _prayer_idle(self, state: dict):
        """Curse and Silver Blades: one look at the screen during the watched
        fight, answering its bar by `FIGHT_KEYS`; True once the map (or Silver
        Blades' move bar) has held `FIGHT_SETTLED` seconds, or at the defeat
        screen.  No debugger read: the watch owns every halt."""
        since: list[float | None] = [None]

        def idle() -> bool:
            try:
                screen = self._look(state)
            except dosboxx.NotLineDoubled:
                return False
            walking = (state["walking"] is not None
                       and bar_signature(screen) == state["walking"])
            if walking or self.on_world(screen):
                since[0] = since[0] or time.time()
                return time.time() - since[0] >= FIGHT_SETTLED
            since[0] = None
            glyphs = screen.glyphs(dosbox.BAR)
            if (glyphs, screen.glyphs(PARTY_DESTROYED_LINE)) == PARTY_DESTROYED:
                self.note(event="fight-outcome", outcome="destroyed")
                return True
            key = FIGHT_KEYS.get(fight_bar_kind(screen) or "")
            if key:
                self.s.key(key)
                time.sleep(0.6)
            return False
        return idle

    def _prayer_fight(self, watch, node: int, walk: dict, fight_end: float,
                      idle, where: str) -> dict:
        """Attach, read the party (logged as read at `where`), arm, and follow
        the fight to `watch`'s stop, answering bars with `idle`; the
        breakpoints come off on every exit."""
        began = time.time()
        try:
            resolved = watch.attach()
            self.note(event="prayer-table", **resolved)
            at_encounter = watch.party()
            self.note(event="prayer-party", where=where, party=at_encounter)
            watch.load = watch.stub_load()
            armed = watch.arm()
            self.note(event="prayer-armed", **armed)
            stop = watch.run_fight(max(1.0, fight_end - began), idle)
        except (dosboxx.NotHalted, dosfightwatch.PrayerWatchError) as e:
            raise self.fail("prayer-arm", str(e)) from e
        finally:
            # Breakpoints left armed would halt the emulator with nobody
            # driving it, so this runs on every exit.
            at_stop = watch.finish()
        self.note(event="prayer-party", where="stop", party=at_stop)
        self.shot("prayer-stop")
        result = watch.summary(node, at_encounter, at_stop)
        return {**result, "stop": stop, "walk": walk,
                "fight_seconds": round(time.time() - began, 1),
                "arm": armed["armed"]}

    def _look(self, state: dict) -> dosbox.Screen:
        """The screen, halved by `loose_halve` when DOSBox-X's grab is torn.

        An animated picture (Silver Blades' archway at 3,0 of area 16) tears
        every grab, and `XSession.capture` then blocks all of them, so the
        bar under it would never be answered.  The rows `fight` reads are
        still while the picture moves.
        """
        try:
            return self.s.capture()
        except dosboxx.NotLineDoubled:
            raw = self.s.grab()
            if raw is None:
                raise
            state["loose"] += 1
            return loose_halve(raw)

    def _fight_tick(self, walker: Explorer, column: int, enter: str | None,
                    state: dict) -> bool:
        """One look at the screen and one answer to it; True once the fight is over."""
        screen = self._look(state)
        walking = (state["walking"] is not None
                   and bar_signature(screen) == state["walking"])
        if walking or self.on_world(screen):
            state["unknown_since"] = None
            if state["met"]:
                state["back_since"] = state["back_since"] or time.time()
                if time.time() - state["back_since"] >= FIGHT_SETTLED:
                    return True
                time.sleep(0.25)
            elif not walking:
                self._enter_move(enter, state)
            else:
                self._explore(walker, column, state)
            return False
        state["back_since"] = None
        kind = fight_bar_kind(screen)
        glyphs = screen.glyphs(dosbox.BAR)
        self._first_sight(kind, glyphs, screen, state)
        combat = kind == "command" or (
            state["hand_back"] and not state["handed_back"]
            and kind in HAND_BACK_AFTER_ENCOUNTER and self._combat_begun(state))
        if (state["hand_back"] and not state["handed_back"] and combat
                and (glyphs, screen.glyphs(PARTY_DESTROYED_LINE)) != PARTY_DESTROYED):
            self._before_hand_back(kind, state)
            self.s.key(HAND_BACK)
            state["presses"] += 1
            state["handed_back"] = True
            state["last_bar"] = None
            self.note(event="hand-back", key=HAND_BACK, kind=kind,
                      shot=self._fight_shot("hand-back"))
            time.sleep(1.0)
            return False
        if kind in (None, "blank"):
            if kind == "blank":
                # A monster's turn or an animation between two bars: the
                # next command bar is a new turn even if it looks the same.
                state["last_bar"] = None
            if kind is None:
                if (glyphs, screen.glyphs(PARTY_DESTROYED_LINE)) == PARTY_DESTROYED:
                    self.note(event="fight-outcome", outcome="destroyed")
                    raise self.fail("fight-destroyed", "the party was destroyed")
                state["unknown_since"] = state["unknown_since"] or time.time()
                if time.time() - state["unknown_since"] >= FIGHT_PATIENCE:
                    words = [len(w) for w in bar_words(screen)]
                    raise self.fail(f"fight-unknown-{glyphs}",
                                    f"a bar nobody has classified ({words} cells "
                                    f"per word) stayed {FIGHT_PATIENCE:.0f} s")
            time.sleep(0.25)
            return False
        state["unknown_since"] = None
        if kind in ("command", "encounter") and not state["met"]:
            state["met"] = True
            state["met_after"] = walker.steps
        if kind == "command":
            self._command_bar(glyphs, state)
            return state["stopped"]
        if kind == "encounter":
            state["encounters"] += 1
        state["last_bar"] = None
        if (kind == "continue_battle" and state["intervened"]
                and state["after_intervene"] is None):
            # The fight's end after the cheat: every side-1 record and the
            # computer-controlled member as the game leaves them.  The fight
            # is already won, so a read that fails is logged and the prompt
            # still answered.
            try:
                snap = self.combat_memory(True, state["records"])
            except StepFailed as e:
                state["after_intervene"] = []
                self.note(event="after-intervene-unread", why=str(e))
            else:
                state["after_intervene"] = [
                    {k: c.get(k) for k in PLACEMENT_FIELDS}
                    for c in snap["combatants"]]
                self.note(event="after-intervene", combatants=state["after_intervene"])
        self._answer(FIGHT_KEYS[kind], glyphs, kind, state)
        return False

    def _fight_short(self, budget: float, walker: Explorer, state: dict) -> str:
        if state["met"]:
            return (f"the fight was still going after {budget:.0f} s "
                    f"({len(state['bars'])} command bars)")
        return (f"no fight in {budget:.0f} s: {walker.steps} steps over "
                f"{len(walker.visits)} squares, {walker.bumps} into walls")

    def _enter_move(self, enter: str | None, state: dict) -> None:
        """Silver Blades: from the map bar into move mode, whose bar the walk
        then steps at (`game.move` waits for it)."""
        if enter is None:
            raise self.fail("fight-walk", "the map bar showed but the walk has "
                            "no bar recorded to step at")
        self.s.key(enter)
        state["presses"] += 1
        if not self.s.wait_while_ink(dosbox.BAR, self.world_ink, 15.0):
            raise self.fail("fight-move", f"the map bar did not change after "
                            f"{enter} (no move mode)")
        settled = self.s.settle(quiet=0.6, timeout=30.0)
        if self.on_world(settled):
            raise self.fail("fight-move", f"the map bar came back after {enter}")
        if fight_bar_kind(settled) is not None and fight_bar_kind(settled) != "blank":
            return
        # Any settled bar nothing classifies is taken as move mode's.
        state["walking"] = bar_signature(settled)
        self.game.record_map(settled)

    def _explore(self, walker: Explorer, column: int, state: dict) -> None:
        """One move of the walk: read the square, or turn and step once.

        A turn or step whose bar does not come back leaves the square
        unknown, so the next move reads it again; the loop in `fight` answers
        whatever showed instead.
        """
        if walker.square is None:
            square = status_square(self.s.settle(quiet=0.6, timeout=30.0), column)
            if square is not None:
                walker.at(square)
                return
            # Move mode draws no status line on entry; a turn draws it.
            walker.turned("Right")
            state["presses"] += 1
            self.game.move("Right")
            return
        d = walker.choose()
        for k in walker.turn_keys(d):
            walker.turned(k)
            state["presses"] += 1
            if not self.game.move(k):
                walker.square = None
                return
        state["presses"] += 1
        walker.stepping()
        if not self.game.move("Up"):
            walker.square = None
            return
        moved = walker.stepped(status_square(self.s.settle(quiet=0.4, timeout=20.0),
                                             column))
        if moved and walker.steps % 25 == 0:
            self.note(event="fight-walk", steps=walker.steps,
                      squares=len(walker.visits), bumps=walker.bumps)

    def _first_sight(self, kind: str | None, glyphs: str, screen, state: dict) -> None:
        """Log a bar the first time its digest shows in this fight, and shoot
        it, except past `FIGHT_UNKNOWN_SHOTS` unclassified ones."""
        if glyphs in state["kinds"]:
            return
        state["kinds"][glyphs] = kind
        shot = None
        if kind is not None or state["unknown_shots"] < FIGHT_UNKNOWN_SHOTS:
            state["unknown_shots"] += kind is None
            shot = self._fight_shot("fight-" + (kind or "unknown"))
        self.note(event="fight-screen", kind=kind, glyphs=glyphs,
                  signature=bar_signature(screen),
                  words=[len(w) for w in bar_words(screen)], shot=shot)

    def _fight_shot(self, label: str) -> str | None:
        """`shot`, or None when DOSBox-X's grab of the frame tore: a picture
        is evidence, and a torn one must not stop the fight."""
        try:
            return f"{self.shot(label)}.png"
        except dosboxx.NotLineDoubled:
            return None

    def _answer(self, key: str, glyphs: str, kind: str, state: dict) -> None:
        """Press `key` until the bar changes, `FIGHT_PRESSES` times at most."""
        for _ in range(FIGHT_PRESSES):
            self.s.key(key)
            state["presses"] += 1
            if self.s.wait_while_glyphs(dosbox.BAR, glyphs, timeout=FIGHT_DWELL):
                return
        raise self.fail(f"fight-{kind}", f"{key} changed nothing at the {kind} "
                        f"bar in {FIGHT_PRESSES} presses")

    def _command_bar(self, glyphs: str, state: dict) -> None:
        """Log who acts, and at the first bar where everyone stands; then press
        `QUICK`, or the first-bar key once, or with `intervene` Alt+X once.

        Every look at a command bar reads who acts.  The same bar digest with
        the same acting record as the last one logged is the same turn, whose
        `QUICK` the game did not take: it is pressed again and counted in
        `repeats`, and no second `bar` is logged.  The next member's bar can
        look the same, and its acting record tells it apart.  The bar after
        the first-bar key is logged again, since a key was pressed at it.
        """
        if state["intervened"]:
            raise self.fail("fight-intervene", "Alt+X did not end the fight: a "
                            "command bar came back")
        first = not state["bars"]
        after_key = state["key_pressed"] and state["after_key"] is None
        if first:
            state["first_bar_shot"] = self._fight_shot("fight-first-bar")
        snap = self.combat_memory(first or after_key, state["records"])
        state["ds"] = snap["ds"]
        actor = next((c for c in snap["combatants"] if c["index"] == snap["selected"]),
                     None)
        turn = (glyphs, tuple(snap["selected_pointer"]))
        if turn == state["last_bar"]:
            state["repeats"] += 1
            self.s.key(FIGHT_KEYS["command"])
            state["presses"] += 1
            self.s.wait_while_glyphs(dosbox.BAR, glyphs, timeout=FIGHT_DWELL)
            return
        state["last_bar"] = turn
        bar = {"bar": glyphs, "actor": None if actor is None else {
            "name": actor["name"], "index": actor["index"],
            "position": actor["position"], "party": actor.get("party")}}
        self.note(event="bar", **bar)
        state["bars"].append(bar)
        public = [{k: c.get(k) for k in PLACEMENT_FIELDS} for c in snap["combatants"]]
        if first:
            state["placement"] = public
            self.note(event="placement", combatants=public, ds=f"{snap['ds']:04X}",
                      selected=snap["selected"])
            if state["stop_at_first"]:
                state["stopped"] = True
                return
            if state["first_bar_key"] is not None:
                self.s.key(state["first_bar_key"])
                state["presses"] += 1
                state["key_pressed"] = True
                state["last_bar"] = None
                time.sleep(1.0)
                self.note(event="first-bar-key", key=state["first_bar_key"],
                          shot=self._fight_shot("first-bar-key"))
                return
        elif after_key:
            state["after_key"] = public
            self.note(event="after-first-bar-key", combatants=public)
        if state["intervene"]:
            # Only the bar after the first-bar key, or the first bar without
            # one, gets here.
            self.s.key("alt+x")
            state["presses"] += 1
            state["intervened"] = True
            state["last_bar"] = None
            time.sleep(1.0)
            self.note(event="intervene", actor=bar["actor"],
                      shot=self._fight_shot("intervene"))
            self.s.wait_while_glyphs(dosbox.BAR, glyphs, timeout=FIGHT_DWELL)
            return
        self.s.key(FIGHT_KEYS["command"])
        state["presses"] += 1
        self.s.wait_while_glyphs(dosbox.BAR, glyphs, timeout=FIGHT_DWELL)

    def combat_memory(self, records: bool, known: dict | None = None) -> dict:
        """The fight's combatants, read through the debugger at a command bar.

        Halts the emulator with Alt+Pause, reads `combat_window` from the
        game's `DS` and, with `records`, every combatant's record and the
        party list, then resumes it.  Without `records` only a combatant not
        in `known` (record pointer to its decoded record, which this fills)
        is read.  The `DS` a halt reports is the game's only if the window
        reads as a fight: a count and a record pointer per combatant
        (`read_combat`), at least one record holding a name, and a party
        member among them or the acting record one of them.  A window that
        does not, or a read the debugger
        blocks, is read again after a fresh halt with the `DS` read afresh,
        `FIGHT_PRESSES` times at most; a `DS` that read true once is kept.
        Each blocked read is logged (`fight-memory-unread`) and named when
        the run stops, since a halt can land where `DS` is not the game's.
        A record whose name is not a name is logged (`fight-odd-record`)
        and kept with `name` None.
        """
        layout = COMBAT_LAYOUTS[self.title.key]
        lo, n = combat_window(layout)
        known = known if known is not None else {}
        whys: list[str] = []
        for _ in range(FIGHT_PRESSES):
            if not self.s.attach():
                whys.append("the debugger did not answer Alt+Pause")
                continue
            ds = None
            try:
                ds = (self.combat_ds if self.combat_ds is not None
                      else self.s.regs("DS")["DS"])
                snap = read_combat(self.s.read((ds, lo), n), lo, layout)
                raw: dict[tuple[int, int], bytes] = {}
                size = max(layout.hp_at, layout.next_at + 3) + 1

                def record(ptr: tuple[int, int]) -> bytes:
                    if ptr not in raw:
                        raw[ptr] = self.s.read(ptr, size)
                    return raw[ptr]

                # Decoded here and kept in `known` only once the window has
                # read as a fight, so a wrong DS leaves nothing behind.
                read_now: dict[tuple[int, int], dict] = {}
                for c in snap["combatants"]:
                    ptr = tuple(c["pointer"])
                    if records or ptr not in known:
                        read_now[ptr] = combatant_record(record(ptr), layout)
                    c.update(read_now.get(ptr) or known[ptr])
                if not any(c["name"] is not None for c in snap["combatants"]):
                    raise CombatUnread("no combatant's record holds a name")
                if records:
                    # The list from `party_at` holds every combatant, the
                    # party's first: the setup walks it through `next_at`
                    # giving entry i to the i-th record (Silver Blades
                    # 0xFDF1-0x10000), allies and monsters after the party.
                    party: list[tuple[int, int]] = []
                    ptr = tuple(snap["party_head"])
                    while (ptr != (0, 0) and ptr not in party
                           and len(party) < self.party_size):
                        party.append(ptr)
                        ptr = far_pointer(record(ptr)[layout.next_at:layout.next_at + 4])
                    for c in snap["combatants"]:
                        ptr = tuple(c["pointer"])
                        c["party"] = ptr in party
                        c["slot"] = party.index(ptr) if ptr in party else None
                        read_now[ptr] = {**c_record(read_now, known, ptr),
                                         "party": c["party"], "slot": c["slot"]}
                if snap["selected"] is None and not any(
                        c.get("party") for c in snap["combatants"]):
                    raise CombatUnread("no combatant is in the party and none is "
                                       "the one acting")
                for ptr, rec in read_now.items():
                    if rec["name"] is None and ptr not in known:
                        self.note(event="fight-odd-record", pointer=list(ptr),
                                  raw_name=rec["raw_name"])
                known.update(read_now)
            except (CombatUnread, dosboxx.NotHalted, RuntimeError, ValueError) as e:
                # A wrong DS reads garbage pointers, which the debugger may
                # block (`NotHalted`, a short dump) as well as misread.
                whys.append(f"DS {'unread' if ds is None else f'{ds:04X}'}: "
                            f"{type(e).__name__}: {e}")
                self.note(event="fight-memory-unread", why=whys[-1])
                self.combat_ds = None
                continue
            finally:
                self.s.run()
            self.combat_ds = ds
            snap["ds"] = ds
            return snap
        raise self.fail("fight-memory", f"the combatants never read as a fight "
                        f"({'; '.join(whys) or 'the debugger never halted'})")

    def pick_line(self, line: int, where: str, label: str,
                  next_key: str = POD_ROSTER_NEXT) -> dict:
        """Move Pools of Darkness' roster highlight onto line `line`, from 1.

        Read, never counted: the highlight is the white roster line
        (`roster_line`), and `POD_ROSTER_NEXT` moves it one member on and
        wraps.  A press is believed only when the white line moves; a
        whole-frame digest is not enough, because the camp picture animates
        by itself.  Two presses in a row that leave it where it was, or more
        than `POD_PICK_ROUNDS` presses a member, stop the run.
        """
        size = self.party_size
        if not 1 <= line <= size:
            raise StepFailed(f"line {line} is not in a party of {size}")
        here = roster_line(self.s.capture(), where, size)
        if here is None:
            raise self.fail(label, "no roster line is drawn highlighted")
        presses = still = 0
        while here != line:
            if presses >= POD_PICK_ROUNDS * size:
                raise self.fail(label, f"{presses} presses of {next_key} "
                                f"never brought the highlight to line {line}")
            self.s.key(next_key)
            presses += 1
            was = here
            self.s.wait_for(lambda sc, was=was: roster_line(sc, where, size) != was,
                            5.0)
            here = roster_line(self.s.capture(), where, size)
            if here is None:
                raise self.fail(label, "the roster highlight went away")
            still = still + 1 if here == was else 0
            if still >= 2:
                raise self.fail(label, f"{next_key} did not move the "
                                f"roster highlight off line {here}")
        self.line = line
        return {"presses": presses}

    def check_sheet(self, screen, line: int, want: str, label: str,
                    got: str | None = None, name: list[str] | None = None) -> dict:
        """The sheet on `screen` is roster line `line`'s: its name cells match
        the roster's, and no other line's sheet has had this frame.  `got` is
        the sheet's name when the caller read it over fewer cells than
        `sheet_name` does.  `name` is the roster's cells (`name_cells`): a
        sheet that draws them followed by `(NPC)` (`sheet_header`) is the
        member's too, and the result's `header` says so."""
        if want == BLANK_NAME:
            raise self.fail(label, f"roster line {line} has no name drawn")
        got = sheet_name(screen) if got is None else got
        header, why = None, ""
        if got != want and name:
            try:
                header = sheet_header(screen, name, self.display_font())
            except StepFailed as e:
                why = f"; its header was not read: {e}"
        if got != want and header is None:
            raise self.fail(label, f"the sheet's name is not roster line {line}'s "
                            f"(sheet {got}, roster {want}){why}")
        digest = screen.digest()
        other = next((n for n, d in self.sheets.items() if d == digest and n != line),
                     None)
        if other is not None:
            raise self.fail(label, f"line {line}'s sheet is the same frame as "
                            f"line {other}'s")
        self.sheets[line] = digest
        return {"name": want, "header": header, "digest": digest,
                "sheet_bar": bar_signature(screen)}

    def open_sheet(self, line: int) -> dict:
        """Camp: roster line `line` highlighted, `VIEW`, and the sheet checked.

        The sheet's bar is read for whether it offers the heal and the cure
        (`sheet_offers`); the result and the `sheet` event carry both.
        """
        if self.title.key not in CAMP_SHEETS or self.camp_sig is None:
            raise StepFailed("sheet needs the camp of Curse, Silver Blades or "
                             "Pools of Darkness first")
        self.ensure_camp()
        moved = self.pick_line(line, "camp", f"select-{line}",
                               CAMP_ROSTER_NEXT[self.title.key])
        roster = self.s.capture()
        want, name = roster_name(roster, "camp", line), name_cells(roster, "camp", line)
        self.shot(f"line-{line}")
        # `V` is keyed by nothing on the sheet's bar, so a second one is inert.
        for _ in range(2):
            self.s.key(VIEW)
            if self.s.wait_for(lambda sc: not self.in_camp(sc), 15.0):
                break
        else:
            raise self.fail(f"sheet-{line}", "the camp bar is still showing "
                            "after VIEW")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        checked = self.check_sheet(screen, line, want, f"sheet-{line}-name",
                                   name=name)
        words = bar_words(screen)
        offers = sheet_offers(words, self.title.key)
        shot = self.shot(f"sheet-{line}")
        self.note(event="sheet", line=line, shot=f"{shot}.png",
                  words=[len(w) for w in words],
                  heal_offered=None if offers is None else offers["heal"],
                  cure_offered=None if offers is None else offers["cure"])
        return {"line": line, **moved, "sheet": shot, **checked,
                "words": [len(w) for w in words],
                "heal_offered": None if offers is None else offers["heal"],
                "cure_offered": None if offers is None else offers["cure"]}

    def item_pages(self, label: str) -> list[dict]:
        """From a sheet: `ITEMS`, then every page shot, turning with `Next`
        until it changes nothing or brings back the first page;
        `ITEMS_PAGES` pages that are all different stop the run."""
        if not self.press_screen_changes(SHEET_ITEMS, tries=1, wait=15.0):
            raise self.fail(label, "ITEMS changed nothing on the sheet (the "
                            "sheet offers ITEMS only to a character carrying "
                            "something, GAME.OVR 0x245D6)")
        pages: list[dict] = []
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        first = screen.digest()
        while True:
            pages.append({"shot": self.shot(f"{label}-{len(pages) + 1}"),
                          "bar": bar_signature(screen), "digest": screen.digest()})
            if len(pages) >= ITEMS_PAGES:
                raise self.fail(f"{label}-pages", f"{ITEMS_PAGES} pages and "
                                "Next still turns another")
            before = screen.digest()
            self.s.key(ITEMS_NEXT)
            if not self.s.wait_for(lambda sc: sc.digest() != before, 5.0):
                break
            screen = self.s.settle(quiet=0.8, timeout=30.0)
            if screen.digest() == first:
                break
        return pages

    def back_to_party(self, label: str, tries: int = 3) -> None:
        """`Exit` until the party menu is back, looking before every press,
        so that no `E` ever lands on the party menu itself."""
        for _ in range(tries):
            if self.on_party_menu(self.s.settle(quiet=0.6, timeout=20.0)):
                return
            self.s.key(LEAVE)
        if not self.wait_party_menu(15.0):
            raise self.fail(label, f"the party menu never came back after "
                            f"{tries} presses of Exit")

    def view(self, line: int) -> dict:
        """Party menu, roster line `line`'s sheet, and back to the party menu.

        Pools of Darkness and Silver Blades open `PICK CHARACTER` first (`View
        Character`, then `Down` to the member and the select key); Curse picks
        with `End` on the party menu itself and `v` views.  Pools of Darkness
        pages `ITEMS`; neither of the others does, as neither's `ITEMS` key is
        measured in this driver.  Nothing here writes a file.
        """
        if self.where != "party" or self.title.key not in VIEWS:
            raise StepFailed("view is the party-menu command of Pool, Curse, "
                             "Silver Blades and Pools of Darkness")
        if self.party_sig is None:
            raise StepFailed("view needs the party menu learnt by load or add")
        if self.title.key == "pool":
            return self._view_pool(line)
        if self.title.key == "curse":
            return self._view_curse(line)
        if self.title.key == "ssb":
            return self._view_ssb(line)
        return self._view_pod(line)

    def add(self, name: str) -> dict:
        """Pool's party menu: `ADD CHARACTER TO PARTY`, the list's row that
        reads `name` picked, and `EXIT` back to the party menu.

        From the boot the title screens are pressed past first, as `load`
        does.  Every screen is read as text with the title's font before a
        key is pressed at it, and one that is not the screen the key belongs
        to stops the run with nothing more pressed: the party menu must offer
        `ADD CHARACTER TO PARTY`, and `a` must open `ADD A CHARACTER: ADD
        EXIT` listing `name` unpicked.  The highlight is walked there with
        `End`, reading it after each press, and `Return` is believed only
        when the row redraws as `* NAME`, the game's mark that it read the
        file; `name` is believed added only when the party menu's roster
        draws it after `EXIT`, since a blocked add is starred too.  A list
        too long for one screen is not paged: `N` and `P` are unmeasured
        here.
        """
        if self.title.key not in ADD_TITLES:
            raise StepFailed(f"add is driven in {', '.join(sorted(ADD_TITLES))} only")
        label = "add-" + re.sub(r"\W+", "-", name).strip("-")
        font = self.display_font()
        if self.where == "boot":
            try:
                self.game.to_main_menu()
            except TimeoutError as e:
                raise self.fail(label, str(e)) from None
        elif self.where != "party":
            raise StepFailed("add needs the party menu, before any load")
        screen = self.s.settle(quiet=0.6, timeout=20.0)
        menu = party_menu_entries(screen, font)
        if menu is None or PARTY_ADD_ENTRY not in menu:
            raise self.fail(f"{label}-menu", f"not the party menu offering "
                            f"{PARTY_ADD_ENTRY}: the bar reads "
                            f"{text_row(screen, BAR_ROW, font).strip()!r}, the "
                            f"functions {menu}")
        self.party_sig = bar_signature(screen)
        self.where = "party"
        menu_shot = self.shot(f"{label}-menu")
        if not self.press_screen_changes(PARTY_ADD, tries=1, wait=15.0):
            raise self.fail(f"{label}-list", f"{PARTY_ADD_ENTRY} changed nothing")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        entries = add_entries(screen, font)
        if entries is None:
            raise self.fail(f"{label}-list", f"{PARTY_ADD_ENTRY} put up a bar reading "
                            f"{text_row(screen, BAR_ROW, font).strip()!r}, not "
                            f"{ADD_LIST_BAR!r}")
        list_shot = self.shot(f"{label}-list")
        if name not in entries:
            full = len(entries) >= ADD_LIST[3] // CELL
            raise self.fail(f"{label}-absent", f"{name} is not on the list {entries}"
                            + ("; the list fills its window and its other pages "
                               "are not driven" if full else ""))
        row = entries.index(name)
        presses = self._add_walk(row, len(entries), label)
        screen = self.s.capture()
        now = add_entries(screen, font)
        if now is None or screen.highlight_row(ADD_LIST) != row or now[row] != name:
            raise self.fail(f"{label}-row", f"the list does not show {name} "
                            "highlighted and unpicked before the pick")
        self.s.key(ADD_PICK)
        mark = ADD_MARK + name
        if not self.s.wait_for(lambda sc: (add_entries(sc, font) or [])[row:row + 1]
                               == [mark], ADD_PICK_SECONDS):
            raise self.fail(f"{label}-pick", f"the row never redrew as {mark!r}: "
                            "the game did not read the file")
        picked = add_entries(self.s.settle(quiet=0.8, timeout=30.0), font)
        picked_shot = self.shot(f"{label}-picked")
        if picked is None:
            raise self.fail(f"{label}-picked", "the list went away after the pick")
        self.s.key(ADD_LEAVE)
        if not self.wait_party_menu(15.0):
            raise self.fail(f"{label}-back", "the party menu did not come back "
                            "after EXIT")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        roster = party_roster(screen, font)
        roster_shot = self.shot(f"{label}-roster")
        if name not in roster:
            raise self.fail(f"{label}-roster", f"the game read {name}'s file and "
                            f"left him out of the party: the roster is {roster}")
        self.party_size = len(roster)
        self.line = roster_line(screen, "party", self.party_size) or 1
        self.note(event="added", name=name, roster=roster)
        return {"name": name, "list": entries, "row": row + 1, "presses": presses,
                "picked": picked, "roster": roster, "party_menu": self.party_sig,
                "menu_shot": menu_shot, "list_shot": list_shot,
                "picked_shot": picked_shot, "roster_shot": roster_shot}

    def _add_walk(self, row: int, rows: int, label: str) -> int:
        """`ADD_LIST_DOWN` until the list's highlight is on `row`, reading it
        after each press; two presses that leave it still, or more than two
        rounds of the list, stop the run."""
        here = self.s.capture().highlight_row(ADD_LIST)
        presses = still = 0
        while here != row:
            self.check_deadline(f"{label}-walk")
            if here is None:
                raise self.fail(f"{label}-walk", "no list row is drawn highlighted")
            if presses >= 2 * rows:
                raise self.fail(f"{label}-walk", f"{presses} presses of "
                                f"{ADD_LIST_DOWN} never reached row {row + 1}")
            self.s.key(ADD_LIST_DOWN)
            presses += 1
            was = here
            self.s.wait_for(lambda sc, was=was: sc.highlight_row(ADD_LIST) != was, 5.0)
            here = self.s.capture().highlight_row(ADD_LIST)
            still = still + 1 if here == was else 0
            if still >= 2:
                raise self.fail(f"{label}-walk", f"{ADD_LIST_DOWN} did not move the "
                                f"highlight off row {here + 1}")
        return presses

    def _view_pool(self, line: int) -> dict:
        """Pool's party menu: `End` to roster line `line`, `VIEW CHARACTER`,
        the sheet read as text, then its `ITEMS` list when the sheet offers
        it, and `Escape` back to the sheet and to the party menu.

        The sheet is believed only when its name row reads line `line`'s name
        (or that name and `(NPC)`), the list only when its title reads
        `<NAME>'S ITEMS`; `encumbrance` is the figure the sheet draws.  A list
        that fills its window stops the step, its next page being unmeasured.
        """
        font = self.display_font()
        label = f"view-{line}"
        screen = self.s.capture()
        menu = party_menu_entries(screen, font)
        if not self.on_party_menu(screen) or menu is None or PARTY_VIEW_ENTRY not in menu:
            raise self.fail(f"{label}-menu", f"not the party menu offering "
                            f"{PARTY_VIEW_ENTRY}: {menu}")
        moved = self.pick_line(line, "party", f"{label}-select", POOL_ROSTER_NEXT)
        roster = party_roster(self.s.capture(), font)
        if len(roster) < line:
            raise self.fail(f"{label}-name", f"roster line {line} has no name drawn")
        want = roster[line - 1]
        self.s.key(VIEW)

        def bar_opens(sc, head):
            return text_row(sc, BAR_ROW, font).strip().startswith(head)

        if not self.s.wait_for(lambda sc: bar_opens(sc, POOL_SHEET_BAR_HEAD), 15.0):
            raise self.fail(f"{label}-open", "VIEW CHARACTER did not open a sheet")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        got = text_row(screen, 1, font, range(1, 27)).strip()
        if got not in (want, f"{want} {NPC_HEADER}"):
            raise self.fail(f"{label}-name", f"the sheet's name is {got!r}, roster "
                            f"line {line} is {want!r}")
        checked = self.check_sheet(screen, line, want, f"{label}-name", got=want)
        sheet_bar = text_row(screen, BAR_ROW, font).strip()
        sheet_text = [text_row(screen, r, font, DISPLAY_COLUMNS) for r in POOL_SHEET_ROWS]
        found = next((m for m in map(POOL_ENCUMBRANCE.search, sheet_text) if m), None)
        sheet_shot = self.shot(f"{label}-sheet")
        if found is None:
            raise self.fail(f"{label}-sheet", "the sheet draws no ENCUMBRANCE row "
                            "the step can read")
        offered = "ITEMS" in re.split(r"[^A-Z]+", sheet_bar)
        items = items_shot = None
        if offered:
            self.s.key(SHEET_ITEMS)
            if not self.s.wait_for(lambda sc: bar_opens(sc, POOL_ITEMS_BAR_HEAD), 15.0):
                raise self.fail(f"{label}-items", "ITEMS did not open the list")
            listed = self.s.settle(quiet=0.8, timeout=30.0)
            head = text_row(listed, 1, font, DISPLAY_COLUMNS).strip()
            if head != want + POOL_ITEMS_TITLE:
                raise self.fail(f"{label}-items", f"the list's title reads {head!r}")
            try:
                items = pool_item_list(listed, font)
            except ValueError as e:
                raise self.fail(f"{label}-items", str(e)) from None
            items_shot = self.shot(f"{label}-items")
            if len(items) >= ITEM_ROWS:
                raise self.fail(f"{label}-items", f"the list fills its {ITEM_ROWS} "
                                "rows and its next page is unmeasured")
            self.s.key("Escape")
            if not self.s.wait_for(lambda sc: bar_opens(sc, POOL_SHEET_BAR_HEAD), 15.0):
                raise self.fail(f"{label}-sheet-back", "the sheet did not return "
                                "after Escape")
        self.s.key("Escape")
        if not self.wait_party_menu(15.0):
            raise self.fail(f"{label}-back", "the party menu did not return after "
                            "Escape")
        self.shot(f"{label}-back")
        self.note(event="sheet", line=line, name=want,
                  encumbrance=int(found.group(1)),
                  items=None if items is None else [i["name"] for i in items])
        return {"line": line, **moved, **checked, "sheet": sheet_shot,
                "sheet_bar_text": sheet_bar, "sheet_text": sheet_text,
                "encumbrance": int(found.group(1)),
                "items_offered": offered, "items": items, "items_shot": items_shot}

    def _view_curse(self, line: int) -> dict:
        """No menu first: `End` moves the party menu's highlight and `v` opens
        the sheet, one press each, in three foundation boots.  The
        key back, `e`, is `dossheetread`'s default and unmeasured here."""
        moved = self.pick_line(line, "party", f"view-{line}-select", ROSTER_NEXT)
        roster = self.s.capture()
        want, name = roster_name(roster, "party", line), name_cells(roster, "party", line)
        self.shot(f"view-line-{line}")
        if not self.press_screen_changes(VIEW, tries=1, wait=15.0):
            raise self.fail(f"view-{line}", "VIEW changed nothing on the party menu")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        checked = self.check_sheet(screen, line, want, f"view-{line}-name", name=name)
        sheet = self.shot(f"view-{line}-sheet")
        self.back_to_party(f"view-{line}-back")
        self.shot(f"view-{line}-back")
        return {"line": line, **moved, "sheet": sheet, **checked, "pages": []}

    def _view_ssb(self, line: int) -> dict:
        """`VIEW CHARACTER` (row 3, or 5 with training on the menu), `PICK
        CHARACTER` (`Down` moves its highlight),
        then `s`, both answered in three foundation boots; `Return` also opens
        the sheet, unmeasured.  The sheet is judged by its name: its bar is not
        in `route_silver_blades.BARS`, so nothing here waits for a sheet bar."""
        got = self._ssb_sheet(line, "view")
        self.back_to_party(f"view-{line}-back")
        self.shot(f"view-{line}-back")
        return {**got, "pages": []}

    def _ssb_sheet(self, line: int, verb: str) -> dict:
        """Silver Blades' party menu to roster line `line`'s sheet, as `view`
        opens it, leaving the sheet showing; shots and failures are labelled
        by `verb`."""
        self.ssb.menu(self.ssb_rows["view"], f"{verb}-{line}")
        self.ssb.wait_bar("pick_character", 20.0)
        pick = self.shot(f"pick-{line}")
        moved = self.pick_line(line, "party", f"pick-{line}-select", POD_ROSTER_NEXT)
        roster = self.s.capture()
        want, name = roster_name(roster, "party", line), name_cells(roster, "party", line)
        self.shot(f"{verb}-line-{line}")
        if not self.press_screen_changes(POD_PICK, tries=2, wait=15.0):
            raise self.fail(f"{verb}-{line}", "SELECT at PICK CHARACTER changed nothing")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        checked = self.check_sheet(screen, line, want, f"{verb}-{line}-name", name=name)
        sheet = self.shot(f"{verb}-{line}-sheet")
        return {"line": line, "pick": pick, **moved, "sheet": sheet, **checked}

    def _view_pod(self, line: int) -> dict:
        """Pools of Darkness: `View Character`, `PICK CHARACTER` over the roster
        (`GAME.OVR` 0x14536 via 0x26E25); `Down` moves the highlight a member on
        and `S` views that character (0x2452E), whose `Exit` returns to the
        party menu."""
        self.pod_menu(self.pod_rows["view"], f"view-{line}")
        screen = self.s.settle(quiet=0.6, timeout=20.0)
        if self.on_party_menu(screen):
            raise self.fail(f"pick-{line}", "View Character left the party menu "
                            "showing")
        if roster_line(screen, "party", self.party_size) is None:
            raise self.fail(f"pick-{line}", "View Character did not open a roster "
                            "with a highlighted line (PICK CHARACTER)")
        pick = self.shot(f"pick-{line}")
        moved = self.pick_line(line, "party", f"pick-{line}-select")
        roster = self.s.capture()
        want, name = roster_name(roster, "party", line), name_cells(roster, "party", line)
        self.shot(f"view-line-{line}")
        # A second `S` goes out only if the first changed nothing in its 15
        # seconds, since the first key after a redraw can be dropped; on a
        # sheet it would open SPELLS, which the name check below stops at.
        if not self.press_screen_changes(POD_PICK, tries=2, wait=15.0):
            raise self.fail(f"view-{line}", "SELECT at PICK CHARACTER changed nothing")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        checked = self.check_sheet(screen, line, want, f"view-{line}-name", name=name)
        sheet = self.shot(f"view-{line}-sheet")
        pages = self.item_pages(f"view-{line}-items")
        self.back_to_party(f"view-{line}-back")
        self.shot(f"view-{line}-back")
        return {"line": line, "pick": pick, **moved, "sheet": sheet, **checked,
                "pages": pages}

    def back_to_camp(self, label: str, tries: int = 3) -> None:
        """`Exit` until the camp bar is back, looking before every press:
        `Exit` on the camp bar itself breaks camp, and on the journal
        question it would be typed as an answer."""
        for _ in range(tries):
            if self.in_camp(self.s.settle(quiet=0.6, timeout=20.0)):
                return
            if self.journal(label):
                raise self.fail(label, "the journal question interrupted the "
                                "step and was answered; the party is out of camp")
            self.s.key(LEAVE)
        if not self.wait_camp(timeout=15.0):
            raise self.fail(label, f"the camp bar never came back after "
                            f"{tries} presses of Exit")

    def pool_sheet_words(self, screen) -> str | None:
        """Pool's sheet bar on `screen` read with the title's font, when it
        reads as `POOL_SHEET_BAR_TEXT`; None for any other bar, or when the
        font cannot be read."""
        try:
            font = self.display_font()
        except StepFailed:
            return None
        text = text_row(screen, BAR_ROW, font).strip()
        return text if POOL_SHEET_BAR_TEXT.fullmatch(text) else None

    def on_pool_sheet(self, screen) -> bool:
        """Whether `screen` shows a Pool sheet bar: a measured
        `POOL_SHEET_BARS` digest, or any class's bar by its words."""
        return (bar_signature(screen) in POOL_SHEET_BARS.values()
                or self.pool_sheet_words(screen) is not None)

    def pool_sheet_offers_items(self, screen) -> bool:
        """Whether Pool's sheet bar on `screen` offers `ITEMS`: by its
        `POOL_SHEET_BARS` entry when measured, else by its words."""
        sig = bar_signature(screen)
        known = [k for k, v in POOL_SHEET_BARS.items() if v == sig]
        if known:
            return not set(known) & set(POOL_SHEET_NO_ITEMS)
        return "ITEMS" in (self.pool_sheet_words(screen) or "").replace(":", " ").split()

    def pool_sheet(self, line: int) -> dict:
        """Pool: roster line `line`'s sheet from the map, shot, and back on the
        map bar.  Only `End`, `v` and `Escape` are pressed, and the highlight
        is read on the map alone, where `roster_line` is right."""
        if self.title.key != "pool" or self.where != "map":
            raise StepFailed("sheet needs Pool's loaded map")
        start = bar_signature(self.s.capture())
        if start not in POOL_MAP_BARS.values():
            raise self.fail(f"sheet-{line}-map", "the map bar is not showing")
        map_kind = next(k for k, bar in POOL_MAP_BARS.items() if bar == start)
        moved = self.pick_line(line, "camp", f"sheet-{line}-select", POOL_ROSTER_NEXT)
        name = roster_cells(self.s.capture(), line)
        if not name:
            raise self.fail(f"sheet-{line}-name", f"roster line {line} has no name drawn")
        self.s.key(VIEW)
        if not self.s.wait_for(self.on_pool_sheet, 15.0):
            raise self.fail(f"sheet-{line}-open", "VIEW did not open the sheet bar")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        # An NPC's sheet draws ` (NPC)` after the name, so the name is
        # compared over its own cells and the blank one after it.
        count = min(len(name) + 1, POD_NAME_CELLS)
        want = _cell_digest((name + [_BLANK_CELL])[:count])
        got = _cell_digest(_cells(screen, *POD_SHEET_NAME, count))
        checked = self.check_sheet(screen, line, want, f"sheet-{line}-name", got=got)
        sheet = self.shot(f"sheet-{line}")
        self.s.key("Escape")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == start, 15.0):
            raise self.fail(f"sheet-{line}-back", "the map bar did not return "
                            "after Escape")
        back = self.s.capture()
        if roster_line(back, "camp", self.party_size) != line:
            raise self.fail(f"sheet-{line}-back", "the highlight is not on the "
                            "member the sheet showed")
        self.shot(f"sheet-{line}-back")
        return {"line": line, "map_kind": map_kind, **moved, "sheet": sheet, **checked}

    def sheet(self, line: int) -> dict:
        """Roster line `line`'s sheet from camp, shot, and back to camp."""
        if self.title.key == "pool":
            return self.pool_sheet(line)
        got = self.open_sheet(line)
        self.back_to_camp(f"sheet-{line}-back")
        return got

    def heal(self, line: int) -> dict:
        """Roster line `line` lays on hands: `HEAL` (`LAY`) on his camp sheet,
        `SELECT` at `HEAL WHOM?`, and back to camp.

        The target is the member the prompt opens on (Curse's is the party's
        first).  The game adds the timer to the paladin whoever the target
        is.  The step is believed only when the sheet comes back without the
        word, which is the game's own reading that the use is spent.
        """
        return self._sheet_act(line, "heal")

    def cure(self, line: int) -> dict:
        """Roster line `line` cures disease: `CURE` on his camp sheet, `SELECT`
        at `CURE WHOM?`, `YES` to `CURE ANYWAY` if it is asked, and back to
        camp.  The sheet must come back, with or without `CURE` (it stays
        while uses are left)."""
        return self._sheet_act(line, "cure")

    def _sheet_act(self, line: int, act: str) -> dict:
        word = "LAY" if act == "heal" and self.title.key == "darkness" else act.upper()
        got = self.open_sheet(line)
        label = f"{act}-{line}"
        before = bar_words(self.s.capture())
        at = acted_word(before, self.title.key, act)
        if not got[f"{act}_offered"] or at is None:
            raise self.fail(label, f"roster line {line}'s sheet does not offer "
                            f"{word}, so it is not pressed")
        without = before[:at] + before[at + 1:]
        if not self.press_screen_changes(SHEET_KEYS[self.title.key][act], tries=1,
                                         wait=15.0):
            raise self.fail(label, f"{word} changed nothing on the sheet")
        prompt = self.s.settle(quiet=0.8, timeout=30.0)
        prompt_shot = self.shot(f"{label}-prompt")
        if bar_words(prompt) in (before, without):
            raise self.fail(label, f"{word} left a sheet bar showing, not the "
                            f"{word} WHOM? prompt")
        self.s.key(PICK_SELECT)
        answered: list[str] = []
        end = time.time() + self.bounded(SHEET_BACK_SECONDS, label)
        while True:
            self.check_deadline(label)
            screen = self.s.settle(quiet=0.8, timeout=30.0)
            words = bar_words(screen)
            if words == without or (act == "cure" and words == before):
                break
            if act == "heal" and words == before:
                raise self.fail(label, f"the sheet came back still offering {word}: "
                                "SELECT did not spend the use")
            if act == "cure" and not answered and yes_no_words(words):
                self.shot(f"{label}-anyway")
                self.s.key(CURE_ANYWAY)
                answered.append(CURE_ANYWAY)
                continue
            if time.time() > end:
                raise self.fail(label, f"the sheet never came back after SELECT at "
                                f"{word} WHOM?")
            time.sleep(0.3)
        after = sheet_offers(words, self.title.key) or {}
        back = self.shot(f"{label}-sheet-after")
        self.back_to_camp(f"{label}-back")
        return {**got, "act": act, "prompt": prompt_shot, "answered": answered,
                "sheet_after": back, "words_after": [len(w) for w in words],
                "heal_offered_after": after.get("heal"),
                "cure_offered_after": after.get("cure")}

    def pool_items(self, line: int) -> dict:
        """Pool: roster line `line`'s `ITEMS` list from camp, and back to camp.

        `End` to the line, `v`, `i`, then `Escape` twice; never `e`, which on
        Pool's camp bar is Exit.  Only the list's first screen is read: Pool's
        paging key and row key are unmeasured, so a list that fills the
        readable rows stops the run instead of guessing.  `marked` is the
        rows (from 1) whose cell at `POOL_ITEM_MARK_X` is `POOL_ITEM_MARK`.
        """
        if self.title.key != "pool" or self.camp_sig is None:
            raise StepFailed("items needs Pool camp first")
        self.ensure_camp()
        label = f"items-{line}"
        moved = self.pick_line(line, "camp", f"{label}-select", POOL_ROSTER_NEXT)
        name = roster_cells(self.s.capture(), line)
        if not name:
            raise self.fail(f"{label}-name", f"roster line {line} has no name drawn")
        self.s.key(VIEW)
        if not self.s.wait_for(self.on_pool_sheet, 15.0):
            raise self.fail(f"{label}-open", "VIEW did not open the sheet bar")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        count = min(len(name) + 1, POD_NAME_CELLS)
        want = _cell_digest((name + [_BLANK_CELL])[:count])
        got = _cell_digest(_cells(screen, *POD_SHEET_NAME, count))
        checked = self.check_sheet(screen, line, want, f"{label}-name", got=got)
        sheet_bar = bar_signature(screen)
        if not self.pool_sheet_offers_items(screen):
            raise self.fail(f"{label}-sheet", f"roster line {line}'s sheet offers no ITEMS")
        self.shot(f"{label}-sheet")
        self.s.key(SHEET_ITEMS)
        if not self.s.wait_for(on_items_list, 15.0):
            raise self.fail(f"{label}-list", "ITEMS did not open Pool's list bar")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        if not on_items_list(screen):
            raise self.fail(f"{label}-list", "the list bar did not stay")
        rows = item_rows(screen)
        if not rows or rows >= ITEM_ROWS:
            raise self.fail(f"{label}-rows", f"the list reads {rows} rows; one that "
                            f"fills {ITEM_ROWS} may have a next page, unmeasured")
        marked = [k + 1 for k in range(rows) if hashlib.sha1(screen.glyphs(
            (POOL_ITEM_MARK_X, 40 + CELL * k, CELL, CELL)).encode()
        ).hexdigest()[:16] == POOL_ITEM_MARK]
        list_shot = self.shot(f"{label}-list")
        self.s.key("Escape")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == sheet_bar, 15.0):
            raise self.fail(f"{label}-sheet-back", "the sheet did not return after Escape")
        self.s.key("Escape")
        if not self.wait_camp(timeout=15.0):
            raise self.fail(f"{label}-back", "the camp bar did not return after the "
                            "second Escape")
        return {"line": line, **moved, **checked, "list_shot": list_shot, "rows": rows,
                "marked": marked}

    def items(self, line: int) -> dict:
        """Roster line `line`'s `ITEMS` from its sheet, every page shot.

        `Next` is pressed until it changes nothing or brings back the first
        page; `ITEMS_PAGES` pages that are all different stop the run.
        """
        if self.title.key == "pool":
            return self.pool_items(line)
        got = self.open_sheet(line)
        pages = self.item_pages(f"items-{line}")
        self.back_to_camp(f"items-{line}-back")
        return {**got, "pages": pages}

    def pick_item(self, row: int, label: str) -> dict:
        """Move the `ITEMS` highlight onto row `row` (from 1), from where it is.

        Read, never counted, as `pick_line` does: `item_highlight` after every
        `ITEM_NEXT_ROW`, and a press is believed only when it moves.  The
        list opens on row 1 (37 of 37 captures).  Only forward is pressed:
        whether the highlight wraps is unmeasured.  Two presses in a row that
        leave it where it was, or more than `2 * ITEM_ROWS` presses, stop the
        run.
        """
        rows = item_rows(self.s.capture())
        here = item_highlight(self.s.capture())
        if rows is None or here is None:
            raise self.fail(label, "no ITEMS row is drawn highlighted")
        if row > rows:
            raise self.fail(label, f"row {row} is past the list's {rows} rows")
        want = row - 1
        if here > want:
            raise self.fail(label, f"the highlight is on row {here + 1}, past "
                            f"row {row}, and only {ITEM_NEXT_ROW} is pressed")
        presses = still = 0
        while here != want:
            if presses >= 2 * ITEM_ROWS:
                raise self.fail(label, f"{presses} presses of {ITEM_NEXT_ROW} "
                                f"never brought the highlight to row {row}")
            self.s.key(ITEM_NEXT_ROW)
            presses += 1
            was = here
            self.s.wait_for(lambda sc, was=was: item_highlight(sc) != was, 5.0)
            here = item_highlight(self.s.capture())
            if here is None:
                raise self.fail(label, "the ITEMS highlight went away")
            still = still + 1 if here == was else 0
            if still >= 2:
                raise self.fail(label, f"{ITEM_NEXT_ROW} did not move the ITEMS "
                                f"highlight off row {here + 1}")
        return {"presses": presses}

    def _item_command(self, line: int, row: int, key: str, verb: str,
                      grow: int) -> dict:
        """Member `line`'s `ITEMS`, row `row` highlighted, `key` pressed once,
        and the rows counted before and after; back to camp.

        With `grow` (`halve`), a list under `ITEM_ROWS` rows must gain a row
        and keep its highlight, or the run stops on the `ITEMS` screen, before
        any save.  `join` only records: whether a scroll joins is what the run
        is for.
        """
        got = self.open_sheet(line)
        label = f"{verb}-{line}-{row}"
        if not self.press_screen_changes(SHEET_ITEMS, tries=1, wait=15.0):
            raise self.fail(label, "ITEMS changed nothing on the sheet")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        moved = self.pick_item(row, f"{label}-select")
        self.shot(f"{label}-before")
        rows_before = item_rows(self.s.capture())
        highlight_before = item_highlight(self.s.capture())
        if grow and rows_before == ITEM_ROWS:
            raise self.fail(f"{label}-rows", f"the list already draws {ITEM_ROWS} "
                            f"rows, and what {verb} does to a full list is not "
                            f"measured, so {key} is not pressed")
        self.s.key(key)
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        rows_after, highlight_after = item_rows(screen), item_highlight(screen)
        after = self.shot(f"{label}-after")
        if grow and rows_before < ITEM_ROWS and (
                rows_after != rows_before + grow
                or highlight_after != highlight_before):
            raise self.fail(f"{label}-rows", f"{verb} left {rows_after} rows with "
                            f"the highlight on {highlight_after}, from {rows_before} "
                            f"rows with it on {highlight_before}")
        self.back_to_camp(f"{label}-back")
        return {**got, "row": row, "presses": moved["presses"],
                "rows_before": rows_before, "rows_after": rows_after,
                "highlight_before": highlight_before,
                "highlight_after": highlight_after, "after": after}

    def halve(self, line: int, row: int) -> dict:
        """`HALVE` member `line`'s item `row`; a new row must appear after it."""
        return self._item_command(line, row, ITEM_HALVE, "halve", grow=1)

    def join(self, line: int, row: int) -> dict:
        """`JOIN` member `line`'s item `row`; the row counts are recorded.

        Measured: JOIN acts at once with no prompt, and the row counts before
        and after.  Not measured: which row JOIN merges the item with, so this
        does not check the pair; the live run records it.  Silver Blades'
        is driven from the party menu (`_ssb_item_command`).
        """
        if JOIN_WHERE.get(self.title.key) == "party":
            return self._ssb_item_command(line, row, ITEM_JOIN, "join")
        return self._item_command(line, row, ITEM_JOIN, "join", grow=0)

    def trade(self, line: int, row: int, to: int) -> dict:
        """Silver Blades: `TRADE` member `line`'s item `row` to line `to`."""
        if self.title.key != "ssb":
            raise StepFailed("trade is driven in Silver Blades only")
        return self._ssb_item_command(line, row, ITEM_TRADE, "trade", to=to)

    def item_texts(self, screen) -> list[str]:
        """The `ITEMS` rows on `screen` as text, read with the title's font,
        runs of spaces as one: `NO 20 ARROWS`, `NO BUNDLE OF 2 SCROLLS`."""
        font = self.display_font()
        return [" ".join(text_row(screen, ITEM_TEXT_ROW + k, font,
                                  DISPLAY_COLUMNS).split())
                for k in range(item_rows(screen) or 0)]

    def _ssb_item_command(self, line: int, row: int, key: str, verb: str,
                          to: int | None = None) -> dict:
        """Silver Blades' party menu: line `line`'s `ITEMS`, row `row`
        highlighted, `key` pressed once, the rows counted and read before and
        after, and `Exit` back to the party menu.

        `TRADE` (`to`) picks line `to` at `TRADE WITH WHOM?` (`SSB_TRADE_BAR`)
        with `Down`, reading the highlight after each press, and `SELECT`;
        the trader's list must come back, and any other screen stops the run
        with nothing more pressed.  Neither verb judges what the game did:
        that is what the run records.
        """
        if self.where != "party":
            raise StepFailed(f"{verb} needs Silver Blades' party menu, before begin")
        label = f"{verb}-{line}-{row}" + (f"-{to}" if to else "")
        got = self._ssb_sheet(line, verb)
        if not self.press_screen_changes(SHEET_ITEMS, tries=1, wait=15.0):
            raise self.fail(label, "ITEMS changed nothing on the sheet (the sheet "
                            "offers ITEMS only to a character carrying something)")
        if not self.s.wait_for(on_items_list, 15.0):
            raise self.fail(label, "ITEMS did not open the list")
        self.s.settle(quiet=0.8, timeout=30.0)
        moved = self.pick_item(row, f"{label}-select")
        screen = self.s.capture()
        before = {"rows_before": item_rows(screen),
                  "highlight_before": item_highlight(screen),
                  "texts_before": self.item_texts(screen),
                  "before": self.shot(f"{label}-before")}
        self.s.key(key)
        traded = {}
        if to is not None:
            traded = self._trade_to(to, label)
        if not self.s.wait_for(on_items_list, 15.0):
            raise self.fail(f"{label}-after", "the ITEMS list did not come back")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        if not on_items_list(screen):
            raise self.fail(f"{label}-after", "the ITEMS list did not stay")
        after = {"rows_after": item_rows(screen),
                 "highlight_after": item_highlight(screen),
                 "texts_after": self.item_texts(screen),
                 "after": self.shot(f"{label}-after")}
        self.back_to_party(f"{label}-back")
        self.note(event=verb, line=line, row=row, to=to,
                  texts_before=before["texts_before"], texts_after=after["texts_after"])
        return {**got, "row": row, "presses": moved["presses"], **before, **after,
                **traded}

    def _trade_to(self, to: int, label: str) -> dict:
        """At `TRADE WITH WHOM?`: line `to` highlighted and `SELECT`."""
        if not self.s.wait_for(lambda sc: bar_signature(sc) == SSB_TRADE_BAR, 15.0):
            screen = self.s.capture()
            raise self.fail(f"{label}-whom", "TRADE did not ask TRADE WITH WHOM?; the "
                            f"bar reads {text_row(screen, BAR_ROW, self.display_font())!r}")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        names = party_roster(screen, self.display_font())
        moved = self.pick_line(to, "party", f"{label}-whom", POD_ROSTER_NEXT)
        whom = self.shot(f"{label}-whom")
        self.s.key(PICK_SELECT)
        return {"to": to, "to_name": names[to - 1] if to <= len(names) else None,
                "whom": whom, "whom_presses": moved["presses"]}

    def memorize(self, line: int) -> dict:
        """Roster line `line`'s grimoire from camp, every page shot and read,
        and back to camp with nothing memorized.

        `Magic` is pressed a second time only while the camp bar is still
        showing, and `Memorize` once: a second one on the grimoire would
        memorize the highlighted spell.  `lists_126` is whether any page draws
        the `MONSTER SUMMONING` row, id 126, which the game lists only when
        record byte `POD_BOOK_126` is set.
        """
        if self.title.key != "darkness" or self.camp_sig is None:
            raise StepFailed("memorize needs Pools of Darkness' camp first")
        self.ensure_camp()
        label = f"memorize-{line}"
        moved = self.pick_line(line, "camp", f"{label}-select")
        name = roster_cells(self.s.capture(), line)
        self.shot(f"{label}-line")
        for _ in range(2):
            self.s.key(POD_MAGIC)
            if self.s.wait_for(lambda sc: bar_signature(sc) == POD_MAGIC_BAR, 15.0):
                break
            if not self.in_camp():
                raise self.fail(f"{label}-magic", "MAGIC opened a screen that is not "
                                "the Magic bar")
        else:
            raise self.fail(f"{label}-magic", "the camp bar is still showing after "
                            "MAGIC")
        magic = self.shot(f"{label}-magic")
        self.s.key(POD_MEMORIZE)
        if not self.s.wait_for(on_grimoire, 20.0):
            raise self.fail(f"{label}-open", "MEMORIZE did not open a grimoire (a "
                            "character with no spell to memorize, or a screen this "
                            "driver does not know)")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        if not grimoire_is_for(screen, name):
            raise self.fail(f"{label}-name", f"the grimoire's title is not roster "
                            f"line {line}'s name")
        pages = self.grimoire_pages(label, screen)
        self.back_from_magic(f"{label}-back")
        back = self.shot(f"{label}-back")
        rows = [r for p in pages for r in p["rows"]]
        return {"line": line, **moved, "magic": magic, "pages": pages, "back": back,
                "lists_126": SPELL_126_ROW in rows,
                "ninth_level": ninth_level(pages[-1]["rows"])}

    def grimoire_pages(self, label: str, screen) -> list[dict]:
        """Every page of the open grimoire, turned with `Next` until the bar
        stops offering it.

        A `Next` that changes nothing on a bar that offers `NEXT` is pressed
        once more, since a swallowed key would otherwise end the list early
        and hide the rows after it; a second one that changes nothing, a page
        that is not the grimoire, or `GRIMOIRE_PAGES` pages, stop the run.
        """
        pages: list[dict] = []
        while True:
            pages.append({"shot": self.shot(f"{label}-page-{len(pages) + 1}"),
                          "bar": bar_signature(screen), "digest": screen.digest(),
                          "rows": grimoire_rows(screen)})
            offers_next = bar_signature(screen) in POD_GRIMOIRE_NEXT_BARS
            if not offers_next:
                return pages
            if len(pages) >= GRIMOIRE_PAGES:
                raise self.fail(f"{label}-pages", f"{GRIMOIRE_PAGES} pages and the "
                                "bar still offers NEXT")
            before = screen.digest()
            for _ in range(2):
                self.s.key(POD_GRIMOIRE_NEXT)
                if self.s.wait_for(lambda sc: sc.digest() != before, 5.0):
                    break
            else:
                raise self.fail(f"{label}-next", "NEXT changed nothing on a page "
                                "whose bar offers it")
            screen = self.s.settle(quiet=0.8, timeout=30.0)
            if not on_grimoire(screen):
                raise self.fail(f"{label}-next", "NEXT left the grimoire")

    def back_from_magic(self, label: str, tries: int = 4) -> None:
        """`Exit` from the grimoire to the Magic bar and from there to camp,
        looking before every press: it is never pressed on the camp bar, which
        it would break, nor on any screen other than those two."""
        for _ in range(tries):
            screen = self.s.capture()
            if self.in_camp(screen):
                return
            bar = bar_signature(screen)
            if not (on_grimoire(screen) or bar == POD_MAGIC_BAR):
                raise self.fail(label, "a screen that is neither the grimoire, the "
                                "Magic bar nor camp")
            self.s.key(LEAVE)
            self.s.wait_for(lambda sc: bar_signature(sc) != bar, 10.0)
        if not self.wait_camp(timeout=15.0):
            raise self.fail(label, f"the camp bar never came back after {tries} "
                            "presses of Exit")

    def zero_rest_time(self, limit: int = 120) -> int:
        """Select days and press subtract until three presses change nothing.

        With days at zero the first subtract zeroes the whole time; with days
        above it each press takes one off and the next zeroes the rest.
        Three quiet presses in a row, not one, so a swallowed key is not
        read as the time having reached zero.
        """
        if not self.press_changes(self.keys.days):
            raise self.fail("rest-days", "the days field did not take the highlight")
        before, still, presses = self.text(), 0, 0
        while still < 3:
            if presses >= limit:
                raise self.fail("rest-zero", f"{limit} presses of Dec never settled")
            self.s.key(self.keys.dec)
            presses += 1
            now = self.text()
            still = still + 1 if now == before else 0
            before = now
        return presses

    def set_rest_time(self, minutes: int) -> dict:
        """From the days field at zero: days, then hours, then fives of minutes."""
        days, hours, fives = rest_presses(minutes)
        for _ in range(days):
            if not self.press_changes(self.keys.inc):
                raise self.fail("rest-inc-days", "Inc on days changed nothing")
        if not self.press_changes(self.keys.hours):
            raise self.fail("rest-hours", "the hours field did not take the highlight")
        for _ in range(hours):
            if not self.press_changes(self.keys.inc):
                raise self.fail("rest-inc-hours", "Inc on hours changed nothing")
        if not self.press_changes(self.keys.mins):
            raise self.fail("rest-mins", "the minutes field did not take the highlight")
        for _ in range(fives):
            if not self.press_changes(self.keys.inc):
                raise self.fail("rest-inc-mins", "Inc on minutes changed nothing")
        return {"days": days, "hours": hours, "fives": fives}

    def step_begins(self, kind: str) -> None:
        """Forget a pending scribe when a step that may leave camp begins."""
        if kind not in SCRIBE_KEEPS:
            self.scribing = False

    def rest(self, minutes: int) -> dict:
        """Rest for `minutes`, or until an event ends it early.

        When the returned `ended_by_message` is true, `"asked"` is the
        minutes requested, not how long the party actually rested -- that
        duration is in the clock of the next save, per `rest_message`.
        `scribe_pending` is whether a `scribe` was still pending in this camp
        when the rest began, which is when the rest can finish it.
        """
        if self.camp_sig is None:
            raise StepFailed("rest needs camp first")
        pending = self.scribing and not self.left_camp
        self.scribing = False
        self.ensure_camp()
        if not self.press_changes(CAMP_REST, wait=10.0):
            raise self.fail("rest-menu", "REST did not open the rest menu")
        self.shot("rest-menu")
        zeroed = self.zero_rest_time()
        self.shot("rest-zero")
        presses = self.set_rest_time(minutes)
        self.shot("rest-set")
        self.s.key(self.keys.go)
        passes = minutes // REST_STEP
        ended = self.after_rest(60.0 + 2.0 * passes, f"rest {minutes}m")
        if ended == "message":
            self.rest_message()
        self.shot("rested")
        return {"asked": minutes, "zero_presses": zeroed, **presses,
                "left_camp": self.left_camp, "ended_by_message": ended == "message",
                "scribe_pending": pending}

    def rest_message(self) -> None:
        """Curse: `Return` past the continue screens that ended a rest, the map
        bar required, and `ENCAMP` again, so the step always ends in camp.  How
        long the party rested is in the clock of the next save, not here."""
        screen = self.press_continue_screens(self.s.capture(), CURSE_CONTINUE_BAR, "rest")
        if not (self.on_world(screen)
                or self.s.wait_for(self.on_world, self.bounded(30.0, "rest-map"))):
            raise self.fail("rest-map", "the map bar did not come back after the "
                            "message that ended the rest")
        self.camp()

    def display_font(self) -> dict[bytes, str]:
        """The title's text font, read from its archives once; a title with
        no archive or no font block is a `StepFailed`."""
        if self._font is None:
            try:
                self._font = load_font(self.title.find_game())
            except (OSError, dos_savegame.DosSaveError) as e:
                raise StepFailed(f"the driver cannot read {self.title.key}'s text font "
                                 f"(block {FONT_BLOCK} of 8X8D*.DAX): {e}") from None
        return self._font

    def leave_display(self) -> str | None:
        """From the Display list to the Magic bar: `DISPLAY_LEAVE`'s keys for
        the bar showing, the second only while the list still shows.  The
        key that brought the Magic bar back, or None; nothing is pressed on
        a bar that is not a Display bar."""
        shown = bar_signature(self.s.capture())
        bar = DISPLAY_BARS.get(shown)
        if bar is None:
            return None
        for tried, key in enumerate(DISPLAY_LEAVE[bar]):
            if tried and bar_signature(self.s.capture()) != shown:
                return None
            self.s.key(key)
            if self.s.wait_for(lambda sc: bar_signature(sc) == POOL_MAGIC_BAR, 15.0):
                return key
        return None

    def display_failed(self, label: str, why: str) -> StepFailed:
        """The failure `why`, shot where it happened, after which the list is
        left for camp when a Display bar is still showing, so the run does
        not stop on the list."""
        failed = self.fail(label, why)
        if self.leave_display() is not None:
            self.s.key("e")
            self.wait_camp(timeout=15.0)
        return failed

    def display(self) -> dict:
        """Camp `MAGIC > DISPLAY`: every page of the list of spells in
        effect read as text, and back through the Magic bar to camp.

        `members` is each member's name with the effect names listed under
        it, as the game draws them.  In Curse and Silver Blades the list must
        name `party_size` members.  In Pool the pass is its `party_size` name rows on
        its one page, and the text is a report: a missing font
        leaves `members` None with `font_error` set.  `n` turns a page while
        the bar is ` NEXT EXIT`, until a page adds no line to the merged list
        (`merge_pages`).  The list is left by `leave_display`, and `e` is
        pressed only on the Magic bar.
        """
        if self.title.key not in DISPLAY_TITLES:
            raise StepFailed(f"display is driven in {', '.join(sorted(DISPLAY_TITLES))} "
                             f"only, not {self.title.key}")
        if self.camp_sig is None:
            raise StepFailed("display needs camp first")
        pool = self.title.key == "pool"
        font, font_error = None, None
        try:
            font = self.display_font()
        except StepFailed as e:
            if not pool:
                raise
            font_error = str(e)
        self.ensure_camp()
        self.s.key("m")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == POOL_MAGIC_BAR, 15.0):
            raise self.fail("display-magic", "MAGIC bar did not open")
        magic = self.shot("display-magic")
        self.s.key("d")
        if not self.s.wait_for(lambda sc: bar_signature(sc) in DISPLAY_BARS, 15.0):
            raise self.fail("display-page", "DISPLAY page did not open")
        screen = self.s.settle(quiet=0.6, timeout=20.0)
        if bar_signature(screen) not in DISPLAY_BARS:
            raise self.fail("display-page", "DISPLAY page changed unexpectedly")
        visible = None
        if pool:
            visible = sum(not screen.flat((8, y, 8, 8)) for y in POOL_DISPLAY_NAME_ROWS)
            if visible != self.party_size:
                raise self.display_failed(
                    "display-members", f"DISPLAY showed {visible} member rows, not "
                    f"{self.party_size}")

        def read(sc) -> list[str]:
            return display_lines(sc, font) if font is not None else []

        pages = [{"shot": self.shot("display-page"), "bar": DISPLAY_BARS[bar_signature(screen)],
                  "lines": read(screen)}]
        lines = merge_pages([p["lines"] for p in pages])
        stopped = None
        while pages[-1]["bar"] == "next":
            if len(pages) >= DISPLAY_PAGES:
                raise self.display_failed("display-pages", f"{DISPLAY_PAGES} pages and "
                                          "the bar still offers NEXT")
            before = screen.digest()
            self.s.key(dosbox.LIST_PAGE_DOWN)
            if not self.s.wait_for(lambda sc: sc.digest() != before, 10.0):
                raise self.display_failed("display-next", "NEXT changed nothing on a "
                                          "page whose bar offers it")
            screen = self.s.settle(quiet=0.6, timeout=20.0)
            bar = DISPLAY_BARS.get(bar_signature(screen))
            if bar not in ("next", "prev"):
                raise self.display_failed("display-next", "NEXT left the paged DISPLAY "
                                          "list")
            pages.append({"shot": self.shot(f"display-page-{len(pages) + 1}"),
                          "bar": bar, "lines": read(screen)})
            merged = merge_pages([p["lines"] for p in pages])
            if font is not None and len(merged) == len(lines):
                stopped = "no new line"
                lines = merged
                break
            lines = merged
        members, read_error = None, None
        if font is not None:
            try:
                members = display_members(lines)
            except ValueError as e:
                if not pool:
                    raise self.display_failed("display-read", str(e)) from None
                read_error = str(e)
            if not pool and len(members) != self.party_size:
                raise self.display_failed("display-members", f"DISPLAY named "
                                          f"{len(members)} members, not the party's "
                                          f"{self.party_size}")
        left_with = self.leave_display()
        if left_with is None:
            raise self.fail("display-back-magic", "Magic bar did not return after DISPLAY")
        self.shot("display-back-magic")
        self.s.key("e")
        if not self.wait_camp(timeout=15.0):
            raise self.fail("display-back-camp", "camp bar did not return after Magic")
        camp = self.shot("display-back-camp")
        return {"magic_shot": magic, "display_shot": pages[0]["shot"],
                "pages": pages, "lines": lines, "members": members,
                "unreadable": [line for line in lines if "?" in line],
                "stopped": stopped, "font_error": font_error, "read_error": read_error,
                "left_with": left_with, "camp_shot": camp,
                "visible_members": visible if visible is not None else len(members),
                "back_in_camp": True}

    def cast(self, line: int, spell: str, target: int | None = None) -> dict:
        """Roster line `line` casts `spell` in camp, on roster line `target`
        when the game asks for one, and the party is back in camp.

        The screens are `dosbox.PoolOfRadiance.cast`'s, which Curse and Silver
        Blades share but for the camp bar (the one `camp` recorded), with the
        spell list read as text with the title's font (`cast_list`) and each
        title's keys (`CAMP_ROSTER_NEXT`, `CAST_LIST_DOWN`, `CAST_SELECT`);
        Pool's camp bar stays the measured `PoolOfRadiance.CAMP_BAR`;
        any screen it does not know stops the run with a `lost-cast-*` shot
        and nothing more pressed.
        """
        key = self.title.key
        if key not in CAST_TITLES:
            raise StepFailed(f"cast is driven in {', '.join(sorted(CAST_TITLES))} "
                             f"only, not {key}")
        if self.camp_sig is None:
            raise StepFailed("cast needs camp first")
        if target and not 1 <= target <= self.party_size:
            raise StepFailed(f"cast target line {target} is not in a party of "
                             f"{self.party_size}; nothing is pressed")
        font = self.display_font()
        self.ensure_camp()
        label = f"cast-{line}"
        roster_next = CAMP_ROSTER_NEXT.get(key, POOL_ROSTER_NEXT)
        moved = self.pick_line(line, "camp", f"{label}-select", roster_next)
        name = roster_text(self.s.capture(), line, font)
        self.shot(f"{label}-line")
        if not name or "?" in name:
            raise self.fail(label, f"roster line {line}'s name does not read: {name!r}")
        try:
            got = self.game.cast(spell_key(spell), target or None,
                                 read=lambda sc: cast_list(sc, font),
                                 party_size=self.party_size, caster=name, shot=self.shot,
                                 camp_bar=None if key == "pool" else self.camp_sig,
                                 list_down=CAST_LIST_DOWN[key],
                                 target_next=roster_next, select=CAST_SELECT[key])
        except dosbox.WrongCaster as e:
            raise self.fail(label, f"roster line {line}'s list: {e}") from None
        except TimeoutError as e:
            raise self.fail(label, str(e)) from None
        if not self.wait_camp(timeout=15.0):
            raise self.fail(f"{label}-back", "the camp bar did not stay after EXIT")
        return {"line": line, **moved, "name": name, **got,
                "back": self.shot(f"{label}-back")}

    def _scribe_state(self, screen, font: dict[bytes, str]) -> str | None:
        """Which screen of the scribe route `screen` is: `list`, `chosen`,
        `confirm`, `magic`, `camp`, or None for any other."""
        kind = scribe_screen(screen, font)
        if kind is not None:
            return kind
        if bar_signature(screen) == POOL_MAGIC_BAR:
            return "magic"
        if self.in_camp(screen):
            return "camp"
        return None

    def _scribe_advance(self, key: str, here: str, want: tuple[str, ...],
                        font: dict[bytes, str], label: str, what: str) -> str:
        """Press `key` at the `here` screen until one of `want` shows.

        Pressed a second time only while `here` still shows, since the first
        key after a redraw can be lost; any other screen stops the run with
        nothing more pressed.
        """
        for _ in range(2):
            if self._scribe_state(self.s.capture(), font) != here:
                raise self.fail(label, f"{what}: the {here} screen is not showing")
            self.s.key(key)
            if self.s.wait_for(lambda sc: self._scribe_state(sc, font) in want,
                               self.bounded(15.0, label)):
                return self._scribe_state(self.s.settle(quiet=0.6, timeout=20.0), font)
            now = self._scribe_state(self.s.capture(), font)
            if now in want:
                return now
            if now != here:
                raise self.fail(label, f"{what} put up a screen that is not "
                                f"{' or '.join(want)} ({now or 'unknown'})")
        raise self.fail(label, f"{what} changed nothing")

    def _scribe_open(self, font: dict[bytes, str], label: str) -> None:
        """`SCRIBE` on the Magic bar until the scroll list shows.

        The message window is watched while the list is awaited: a line the
        game draws there is kept, and a line it clears shows the key was
        taken.  Curse with no scroll listing a spell clears `THE PARTY MAKES
        CAMP...`, draws nothing a capture saw, and stays on the Magic bar
        (`SCRIBE_NONE` is its string).  The first key can be lost while an
        unrelated line changes in that window, so a second press goes out
        whenever the Magic bar still shows; the step fails only when that one
        opens no list either, with any words drawn.  Any other screen stops
        the run with nothing more pressed.
        """
        drawn: list[str] = []
        cleared = False
        for _ in range(2):
            before = self.s.capture()
            if self._scribe_state(before, font) != "magic":
                raise self.fail(label, "SCRIBE: the magic screen is not showing")
            was = message_lines(before, font)

            def seen(sc, was=was) -> bool:
                nonlocal cleared
                if self._scribe_state(sc, font) == "list":
                    return True
                for k, line in enumerate(message_lines(sc, font)):
                    if line and line != was[k] and line not in drawn:
                        drawn.append(line)
                    elif was[k] and not line:
                        cleared = True
                return False

            self.s.key(MAGIC_SCRIBE)
            if self.s.wait_for(seen, self.bounded(15.0, label)):
                self.s.settle(quiet=0.6, timeout=20.0)
                return
            now = self.s.capture()
            if seen(now):
                self.s.settle(quiet=0.6, timeout=20.0)
                return
            state = self._scribe_state(now, font)
            if state != "magic":
                raise self.fail(label, f"SCRIBE put up a screen that is not the "
                                f"scroll list ({state or 'unknown'})"
                                + (f"; the game drew: {' / '.join(drawn)}"
                                   if drawn else ""))
        if not (drawn or cleared):
            raise self.fail(label, "SCRIBE changed nothing")
        said = " ".join(drawn)
        if drawn and SCRIBE_NONE not in said:
            raise self.fail(label, f"SCRIBE opened no scroll list: the game drew "
                            f"{said!r}")
        what = (f"drew {said!r}" if drawn else
                "cleared the message window and drew nothing")
        hint = ("; in Curse a scroll whose name is hidden likely lists nothing "
                "until Read Magic is in effect on the character"
                if self.title.key == "curse" else "")
        raise self.fail(f"{label}-none", f"SCRIBE opened no scroll list: the game "
                        f"{what}.  No scroll of this character lists a spell the "
                        f"game lets it scribe{hint}")

    def _scribe_walk(self, row: int, font: dict[bytes, str], label: str) -> int:
        """Move the scroll list's highlight onto list row `row`, reading it
        after each press of the title's `SCRIBE_LIST_DOWN`, which wraps."""
        key = SCRIBE_LIST_DOWN[self.title.key]
        screen = self.s.capture()
        here, presses, stuck = screen.highlight_row(SCRIBE_LIST), 0, 0
        while here != row:
            if here is None:
                raise self.fail(label, "the scroll list shows no highlighted row")
            if presses > SCRIBE_LIST[3] // CELL or stuck >= 2:
                unmeasured = (" (Silver Blades' Down is unmeasured on this list and "
                              "may not wrap there)" if self.title.key == "ssb" else "")
                raise self.fail(label, f"{presses} presses of {key} never brought the "
                                f"highlight to list row {row}{unmeasured}")
            was = here
            self.s.key(key)
            presses += 1
            self.s.wait_for(lambda sc: sc.highlight_row(SCRIBE_LIST) != was,
                            self.bounded(5.0, label))
            screen = self.s.capture()
            if scribe_screen(screen, font) != "list":
                raise self.fail(label, f"{key} left the scroll list")
            here = screen.highlight_row(SCRIBE_LIST)
            stuck = stuck + 1 if here == was else 0
        return presses

    def _scribe_pick(self, row: int, font: dict[bytes, str], label: str) -> int:
        """`SCRIBE` on list row `row`, believed only when that row redraws as
        `*SPELL`.  Each key is sent only while the list shows with that row
        highlighted and unmarked; the second only when no text row changed
        after the first, neither while it was awaited nor on a reading taken
        after, since a changed text row without the mark is the game blocking
        (`You already know that spell`, `You can not scribe that spell`),
        whose words the failure carries.  A frame that changes only outside
        the text (the camp picture, Silver Blades' pointer) is not a rejection.
        A rejection drawn and gone between two readings is not seen: then the
        second key blocks again, and the failure says that neither a mark
        nor a change was seen, which may be such a rejection.  Returns the keys
        sent.
        """
        def entry(sc) -> dict | None:
            return next((e for e in scribe_entries(sc, font) if e["row"] == row), None)

        def untouched(sc) -> bool:
            e = entry(sc)
            return (scribe_screen(sc, font) == "list" and e is not None
                    and not e["marked"] and sc.highlight_row(SCRIBE_LIST) == row)

        def marked(sc) -> bool:
            e = entry(sc)
            return scribe_screen(sc, font) == "list" and e is not None and e["marked"]

        for sent in (1, 2):
            before = self.s.capture()
            if not untouched(before):
                raise self.fail(label, "the spell's row is no longer highlighted and "
                                "unmarked on the scroll list; nothing more is pressed")
            changed: list[list[str]] = []

            def seen(sc, before=before, changed=changed) -> bool:
                if marked(sc):
                    return True
                if not changed and sc.digest() != before.digest():
                    words = changed_rows(before, sc, font)
                    if words:
                        changed.append(words)
                return False

            self.s.key(SCRIBE_PICK)
            if self.s.wait_for(seen, self.bounded(SCRIBE_PICK_SECONDS, label)):
                return sent
            if not changed and seen(self.s.capture()):
                return sent
            if changed:
                raise self.fail(f"{label}-blocked", "SCRIBE did not mark the spell and "
                                f"the screen changed: {' / '.join(changed[0])}")
        raise self.fail(label, "two presses of SCRIBE brought no mark and no change "
                        "was seen, possibly a rejection drawn and gone between readings")

    def scribe(self, line: int, spell: str) -> dict:
        """Roster line `line` picks `spell` from his scrolls in camp `MAGIC >
        SCRIBE`, confirms it, and the party is back in camp, still camped, so
        a `rest` next finishes the scribe and a camp `save` keeps it pending.

        The scroll list is read as text with the title's font; its title must
        be line `line`'s name, and `spell` must be on it unmarked.  The
        highlight is walked onto the spell's row and `SCRIBE` pressed
        (`_scribe_pick`); the list's `EXIT`, the chosen spells' `EXIT` (the
        page is read and must list the spell marked), `YES` at `SCRIBE THESE
        SPELLS?`, and the Magic bar's `EXIT`.  Every key is pressed at a screen
        the step has recognised, and a second one only while that screen still
        shows: `EXIT` is exit to DOS on Pool's camp bar.
        """
        if self.title.key not in SCRIBE_TITLES:
            raise StepFailed(f"scribe is driven in {', '.join(sorted(SCRIBE_TITLES))} "
                             f"only, not {self.title.key}")
        if self.camp_sig is None:
            raise StepFailed("scribe needs camp first")
        font = self.display_font()
        self.ensure_camp()
        label = f"scribe-{line}"
        moved = self.pick_line(line, "camp", f"{label}-select",
                               CAMP_ROSTER_NEXT.get(self.title.key, POOL_ROSTER_NEXT))
        name = roster_text(self.s.capture(), line, font)
        self.shot(f"{label}-line")
        for _ in range(2):
            self.s.key(POD_MAGIC)
            if self.s.wait_for(lambda sc: bar_signature(sc) == POOL_MAGIC_BAR, 15.0):
                break
            if not self.in_camp():
                raise self.fail(f"{label}-magic", "MAGIC opened a screen that is not "
                                "the Magic bar")
        else:
            raise self.fail(f"{label}-magic", "the camp bar is still showing after MAGIC")
        magic = self.shot(f"{label}-magic")
        self._scribe_open(font, f"{label}-list")
        screen = self.s.settle(quiet=0.8, timeout=20.0)
        head = text_row(screen, SCRIBE_HEAD_ROW, font, DISPLAY_COLUMNS).strip()
        listed = scribe_entries(screen, font)
        list_shot = self.shot(f"{label}-list")
        if not name or not head.startswith(f"{name}'S "):
            raise self.fail(f"{label}-name", f"the scroll list is {head!r}, not roster "
                            f"line {line}'s ({name!r})")
        hits = [e for e in listed if spell_key(e["spell"]) == spell_key(spell)]
        if not hits:
            raise self.fail(f"{label}-spell", f"{spell} is not on the scroll list: "
                            f"{[e['spell'] for e in listed]}")
        entry = hits[0]
        if entry["marked"]:
            raise self.fail(f"{label}-spell", f"{spell} is already drawn "
                            f"{SCRIBE_MARK}, being scribed; nothing is pressed")
        walked = self._scribe_walk(entry["row"], font, f"{label}-walk")
        picked = self._scribe_pick(entry["row"], font, f"{label}-pick")
        marked = self.shot(f"{label}-marked")
        after_list = scribe_entries(self.s.capture(), font)
        chosen, chosen_shot = None, None
        now = self._scribe_advance(SCRIBE_LEAVE, "list", ("chosen", "confirm"), font,
                                   f"{label}-exit", "EXIT on the scroll list")
        if now == "chosen":
            chosen = scribe_entries(self.s.capture(), font)
            chosen_shot = self.shot(f"{label}-chosen")
            if not any(spell_key(e["spell"]) == spell_key(spell) and e["marked"]
                       for e in chosen):
                raise self.fail(f"{label}-chosen", f"the chosen spells do not list "
                                f"{SCRIBE_MARK}{spell}: {chosen}")
            self._scribe_advance(SCRIBE_LEAVE, "chosen", ("confirm",), font,
                                 f"{label}-chosen-exit", "EXIT on the chosen spells")
        confirm = self.shot(f"{label}-confirm")
        self._scribe_advance(SCRIBE_YES, "confirm", ("magic",), font,
                             f"{label}-yes", "YES")
        back_magic = self.shot(f"{label}-back-magic")
        self._scribe_advance(LEAVE, "magic", ("camp",), font, f"{label}-camp",
                             "EXIT on the Magic bar")
        if not self.wait_camp(timeout=15.0):
            raise self.fail(f"{label}-camp", "the camp bar did not stay after EXIT")
        self.scribing = True
        return {"line": line, **moved, "name": name, "spell": spell,
                "head": head, "list": listed, "list_after_pick": after_list,
                "chosen": chosen, "walk_presses": walked, "pick_presses": picked,
                "shots": {"magic": magic, "list": list_shot, "marked": marked,
                          "chosen": chosen_shot, "confirm": confirm,
                          "back_magic": back_magic, "camp": self.shot(f"{label}-back")}}

    #: A snapshot after a `press` is taken only once the screen has held
    #: unchanged this long, within `SNAPSHOT_STILL_SECONDS`.
    SNAPSHOT_QUIET = 1.5
    SNAPSHOT_STILL_SECONDS = 30.0

    def snapshot(self, name: str) -> dict:
        """Save the whole machine under `name`; DOSBox-X only.

        After a `press` the screen may still be drawing, so the snapshot waits
        for it to hold still (`hold_still`) and fails rather than save a
        machine mid-transition; a screen that changes while the state is
        written fails it too.  That screen's digest is kept, and a `restore`
        of the name must bring the same screen back.
        """
        self.need_snapshots("snapshot")
        before = None
        if self.where == "pressed":
            before = hold_still(self.s, self.SNAPSHOT_QUIET,
                                self.SNAPSHOT_STILL_SECONDS)
            if before is None:
                raise self.fail(f"snapshot-{name}", "the screen was still changing "
                                f"after {self.SNAPSHOT_STILL_SECONDS:.0f} s, so the "
                                "machine would be saved mid-transition")
        path = self.s.snapshot(name)
        self._places[name] = self._place()
        got = {"name": name, "path": str(path)}
        if before is not None:
            after = self.s.capture()
            if after.px != before.px:
                raise self.fail(f"snapshot-{name}", "the screen changed while the "
                                "snapshot was written")
            self._screens[name] = got["screen"] = before.digest()
        self.note(event="snapshot", **got)
        return got

    def restore(self, name: str) -> dict:
        """Put the machine back as `snapshot NAME` left it.

        The game's `SAVE` files stay as they are, so the files changed since
        the snapshot are logged and returned; the driver's idea of where the
        party is goes back with the machine.
        """
        self.need_snapshots("restore")
        changed = self.s.restore(name)
        self.s.settle()
        got = {"name": name, "changed_saves": changed}
        if name in self._screens:
            got["screen"] = self.s.capture().digest()
            if got["screen"] != self._screens[name]:
                raise self.fail(f"restore-{name}", f"the screen after the restore "
                                f"({got['screen']}) is not the one snapshot {name} "
                                f"held ({self._screens[name]})")
        if self.encounters is not None:
            # The machine holds the original gate values again.
            self.encounters.reset()
            self.note(event="no-encounters-reset", name=name)
        if name in self._places:
            for attr, value in self._places[name].items():
                setattr(self, attr, dict(value) if isinstance(value, dict) else value)
        self.note(event="restore", **got)
        return got

    #: What a restore puts back with the machine.  `combat_ds` and `sheets` are
    #: caches read off the timeline being left, so they go back to what the
    #: snapshot held; `fights` must, or the first-fight keys are skipped.
    PLACE_ATTRS = ("where", "line", "left_camp", "scribing", "fights", "combat_ds",
                   "sheets")

    def _place(self) -> dict:
        return {a: (dict(v) if isinstance(v := getattr(self, a), dict) else v)
                for a in self.PLACE_ATTRS}

    def need_snapshots(self, verb: str) -> None:
        if not hasattr(self.s, "snapshot"):
            raise StepFailed(f"{verb} needs DOSBox-X: DOSBox 0.74 has no save states")

    def _check_save(self) -> None:
        """Stop the run while `--no-encounters` could have changed the save."""
        if self.encounters is not None:
            try:
                self.encounters.check_save()
            except dosnoencounters.SaveBlocked as e:
                raise StepFailed(f"save stopped: {e}") from e

    def save(self, letter: str) -> dict:
        self._check_save()
        if self.where == "party":
            return self.party_save(letter)
        if self.camp_sig is None:
            raise StepFailed("save needs camp first")
        self.ensure_camp()
        path = self.save_path(letter)
        was = path.read_bytes() if path.is_file() else None
        camp_ink = self.s.capture().ink(dosbox.BAR)
        self.s.key(CAMP_SAVE)
        if not self.s.wait_while_ink(dosbox.BAR, camp_ink, 30.0):
            raise self.fail("save-which", "SAVE did not open the slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("save-which")
        self.s.key(letter.lower())
        self.wait_file(path, was, "save-file")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("saved")
        self.s.key(QUIT_NO)
        back = self.wait_camp(timeout=15.0)
        self.shot("after-save")
        return {"slot": letter, "file": path.name, "size": path.stat().st_size,
                "back_in_camp": back}

    def party_save(self, letter: str) -> dict:
        """`SAVE CURRENT GAME` at the party menu, back to the party menu.

        A `QUIT TO DOS` question after it, if Curse asks one, is declined:
        `n` is none of Curse's party-menu letters.
        """
        path = self.save_path(letter)
        was = path.read_bytes() if path.is_file() else None
        if self.title.key == "ssb":
            self.ssb.menu(self.ssb_rows["save"], "save")
            self.ssb.wait_bar("save_which")
        elif self.title.key == "darkness":
            self.pod_menu(self.pod_rows["save"], "save")
        elif not self.press_screen_changes(PARTY_SAVE):
            raise self.fail("save-which", "SAVE CURRENT GAME did not open the slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("save-which")
        self.s.key(letter.lower())
        self.wait_file(path, was, "save-file")
        back = self.wait_party_menu(15.0)
        if not back and self.title.key != "ssb":
            self.shot("after-save-question")
            self.s.key(QUIT_NO)
            back = self.wait_party_menu(15.0)
        self.shot("saved")
        if not back:
            raise self.fail("save-back", "the party menu never came back after saving")
        return {"slot": letter, "file": path.name, "size": path.stat().st_size,
                "at": "party menu"}

    def press(self, key: str) -> dict:
        """One key, pressed blind for a capture: the PNG is the reading."""
        if key.lower() in (CAMP_SAVE, PARTY_SAVE):
            self._check_save()
        self.s.key(key)
        self.s.settle(quiet=0.8, timeout=30.0)
        self.where = "pressed"
        return {"key": key, "shot": self.shot(f"press-{key}")}

    def train(self, line: int) -> dict:
        """Roster line `line`'s `TRAIN CHARACTER`, accepted, back to the party menu.

        `End` wraps, and the highlight stays where the last command left it,
        so the presses are `(line - here) % party size`
        (`docs/194-the-dos-training-ladder.md`).  A `t` that leaves the screen
        as it was is the school blocking; there is no message to read.
        """
        if self.where != "party" or self.title.key != "curse":
            raise StepFailed("train is Curse's party-menu command")
        for _ in range((line - self.line) % self.party_size):
            if not self.s.press_until_change(ROSTER_NEXT):
                raise self.fail("train-line", "End did not move the roster highlight")
        self.line = line
        self.shot(f"train-line-{line}")
        before = self.s.settle(quiet=0.6, timeout=20.0).digest()
        offered = False
        for _ in range(2):
            self.s.key(PARTY_TRAIN)
            if self.s.settle(quiet=0.8, timeout=20.0).digest() != before:
                offered = True
                break
        if not offered:
            raise self.fail("train-blocked", f"TRAIN CHARACTER changed nothing for "
                            f"line {line} (the school blocks him, or the hall "
                            "is shut: stage --hall)")
        self.shot("train-offer")
        self.s.key(TRAIN_YES)
        self.s.settle(quiet=0.8, timeout=30.0)
        self.shot("trained")
        pressed = []
        for i in range(8):
            if self.on_party_menu(self.s.settle(quiet=0.8, timeout=30.0)):
                return {"line": line, "after": pressed}
            key = AFTER_TRAIN[i % len(AFTER_TRAIN)]
            self.s.key(key)
            pressed.append(key)
            self.shot(f"after-train-{key}")
        raise self.fail("train-back", "the party menu never came back after training")

    def class_segment(self) -> bytes:
        """Curse's `START.EXE` data segment, from the game this session runs."""
        if self._class_ds is None:
            self._class_ds = class_tables((self.s.source / "START.EXE").read_bytes())
        return self._class_ds

    def change(self, line: int, wanted: str) -> dict:
        """Roster line `line`'s `HUMAN CHANGE CLASSES` to `wanted`, back to the
        party menu.

        Which row holds `wanted` comes from the engine's own test run over
        his installed record and `START.EXE`'s tables (`class_choices`), and
        is checked on the screen before anything is taken: the rows `End`
        reaches from where the list opens must be exactly as many as the
        classes the test allows, or the run stops with the list showing.  The
        game then prints its message and returns to the party menu on its own
        (0x3BE60, a timed wait), with no `YES NO` in the routine.
        """
        if self.where != "party" or self.title.key != "curse":
            raise StepFailed("change is Curse's party-menu command")
        label = f"change-{line}"
        record = self.s.save_dir / f"CHRDAT{self.slot}{line}.SAV"
        if not record.is_file():
            raise StepFailed(f"line {line} has no {record.name} to read his classes from")
        choices = class_choices(record.read_bytes(), self.class_segment())
        names = [name for _, name in choices]
        self.note(event="class_choices", line=line, choices=names)
        if not names:
            raise StepFailed(f"line {line} is not offered HUMAN CHANGE CLASSES: he is "
                             "not human, has changed class before, or qualifies "
                             "for no class")
        if wanted not in names:
            raise StepFailed(f"line {line} may not change to {wanted}: the engine's "
                             f"test allows {', '.join(names)}")
        moved = self.pick_line(line, "party", f"{label}-select", ROSTER_NEXT)
        self.shot(f"{label}-line")
        if not self.press_screen_changes(PARTY_CHANGE, tries=1, wait=15.0):
            raise self.fail(label, f"HUMAN CHANGE CLASSES changed nothing for line "
                            f"{line} (the hall is shut: stage --hall)")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        base = screen.highlight_row(CHANGE_LIST)
        if base is None or self.on_party_menu(screen):
            raise self.fail(label, "no class list with a highlighted row opened")
        self.shot(f"{label}-list")
        rows, stuck = [base], 0
        while len(rows) <= CHANGE_ROWS:
            self.s.key(dosbox.LIST_DOWN)
            now = self.s.settle(quiet=0.5, timeout=20.0).highlight_row(CHANGE_LIST)
            if now == base:
                break
            if now is None or now == rows[-1]:
                stuck += 1
                if now is None or stuck >= 2:
                    break
                continue
            stuck = 0
            rows.append(now)
        if rows != list(range(base, base + len(rows))) or len(rows) != len(names):
            raise self.fail(label, f"the list's highlight reached rows {rows} from "
                            f"row {base}, not the {len(names)} consecutive rows of "
                            f"{', '.join(names)}")
        want = base + names.index(wanted)
        here = self.s.capture().highlight_row(CHANGE_LIST)
        key = dosbox.LIST_DOWN if here is not None and here <= want else dosbox.LIST_UP
        if self.s.walk_highlight(CHANGE_LIST, want, key=key) != want:
            raise self.fail(label, f"the list's highlight never reached row {want}")
        picked = self.shot(f"{label}-{wanted.lower()}")
        self.s.key(PICK_SELECT)
        if not self.wait_party_menu(60.0):
            raise self.fail(f"{label}-back", "the party menu never came back after "
                            f"SELECT on {wanted}")
        self.shot(f"{label}-back")
        return {"line": line, **moved, "class": wanted, "choices": names,
                "rows": rows, "row": want, "picked": picked}


@contextlib.contextmanager
def deferred_sigterm():
    """Hold SIGTERM back for the body; a signal that arrived is delivered after it."""
    if not hasattr(signal, "pthread_sigmask"):
        yield
        return
    old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


def run(args, clock=time.monotonic) -> int:
    """`_run`, with the evidence log closed on every way out, including an early raise.

    The wrapper's SIGTERM is turned into `Terminated` for the length of the
    run, so the evidence is kept where the default action would end the
    process without it.  A second signal is ignored: the cleanup is what the
    first one asked for.
    """
    def on_term(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise Terminated(f"signal {signum}")

    try:
        previous = signal.signal(signal.SIGTERM, on_term)
    except ValueError:      # not the main thread: nothing to install
        previous = None
    try:
        with contextlib.ExitStack() as outer:
            return _run(args, outer, clock)
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def _run(args, outer: contextlib.ExitStack, clock=time.monotonic) -> int:
    deadline = Deadline(clock, getattr(args, "deadline", None) or DEADLINE_SECONDS)
    git = evidence.git_state(REPO)
    title = TITLES[args.title]
    out = (pathlib.Path(args.out) if args.out
           else evidence.default_out(args.issue, args.run, git["sha"]))
    scratch.ensure(out)
    log = outer.enter_context((out / "run.jsonl").open("a"))

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    steps = [parse_step(s) for s in args.steps]
    expects = [parse_expect(e) for e in args.expect]
    summary: dict = {"title": args.title, "slot": args.slot.upper(),
                     "steps": args.steps, **git, "completed": False}
    no_encounters = bool(getattr(args, "no_encounters", False))
    encounters = None
    if no_encounters:
        summary["no_encounters"] = True
    note(event="start", out=str(out), **summary)

    def write_summary():
        summary["elapsed_seconds"] = round(clock() - deadline.begun, 1)
        if encounters is not None:
            summary["no_encounters_report"] = encounters.report()
        (out / "summary.json").write_text(json.dumps(summary, indent=2))

    save = pathlib.Path(args.save) if args.save else None
    if args.fixture_row:
        shutil.rmtree(out / "source", ignore_errors=True)
        built = build_source([parse_row(r) for r in args.fixture_row], out,
                             args.title, getattr(args, "c64_save", None))
        summary["source"] = built
        note(event="converted", **{k: v for k, v in built.items() if k != "read"})
        if "stopped" in built or built["dropped"] or built["losses"]:
            summary["lost"] = "the conversion dropped or lost a field"
            write_summary()
            return 1
        save = out / "source"
    elif getattr(args, "amiga_slot", None):
        shutil.rmtree(out / "source", ignore_errors=True)
        built = build_amiga_source(args.amiga_disk, args.amiga_slot, out)
        summary["source"] = built
        note(event="converted", **{k: v for k, v in built.items() if k != "read"})
        if "stopped" in built or built["dropped"] or built["losses"]:
            summary["lost"] = "the conversion stopped, dropped or lost something"
            write_summary()
            return 1
        save = out / "source"
    elif getattr(args, "convert", None):
        shutil.rmtree(out / "source", ignore_errors=True)
        chosen = parse_names(args.name, args.title) if args.name else None
        built = build_saveas_source(args.convert, args.convert_slot.upper(), out,
                                    args.title, chosen)
        summary["source"] = built
        note(event="converted", **{k: v for k, v in built.items() if k != "read"})
        if "stopped" in built or built["dropped"] or built["losses"]:
            summary["lost"] = "the conversion stopped, dropped or lost something"
            write_summary()
            return 1
        save = out / "source"
    if not steps:
        summary["completed"] = True
        write_summary()
        return 0

    letter = args.slot.upper()
    from_slot = (source_slot(save, getattr(args, "from_slot", None))
                 if save is not None else None)
    if from_slot not in (None, letter):
        raise ValueError(f"{args.title} loads the party its SAVGAM{from_slot} "
                         f"names: pass --slot {from_slot}")
    if save is not None and containers_in(save)[from_slot] != title.suffix:
        raise ValueError(f"{save} holds SAVGAM{from_slot}"
                         f"{containers_in(save)[from_slot]}, not the "
                         f"SAVGAM{from_slot}{title.suffix} {args.title} loads")
    if save is not None:
        check_staging(args, save, from_slot)
    added = [s.name for s in steps if s.kind == "add"]
    if added:
        check_exports(title.find_game() / "SAVE", added)
    saved: list[str] = []
    with contextlib.ExitStack() as stack:
        # Every callback runs even when an earlier one raises: a failed close
        # must not leave a slot leased.
        game = title.find_game()
        # A SIGTERM between the lease and its release callback would leave the
        # slot leased: hold it back until the callback is registered.
        # A `fight` reads the combatants through the debugger, so its run
        # boots DOSBox-X from that pool, whose captures `XSession` halves back
        # to DOSBox 0.74's 320x200.
        # A Pool walk or turn reads the party's square from memory when the
        # status line hides it (`POOL_PLACE`), so it boots DOSBox-X too.
        debugger = (any(s.kind in ("fight", "prayer-watch") for s in steps)
                    or no_encounters
                    or (args.title == "pool"
                        and any(s.kind in ("walk", "turn") for s in steps)))
        # `snapshot` and `restore` are DOSBox-X save states, so such a run boots
        # `SnapshotSession` too.
        snapshots = any(s.kind in ("snapshot", "restore") for s in steps)
        with deferred_sigterm():
            slot = (dosboxx.claim if debugger or snapshots else dosbox.claim)(args.note)
            stack.callback(slot.release)
        launch = launch_args(
            title, debugger and getattr(args, "intervene", False))
        if debugger or snapshots:
            x_class = dossnapshot.SnapshotSession if snapshots else dosboxx.XSession
            session = x_class(slot, game, **launch)
        else:
            session = dosbox.Session(slot, game, **launch)
        stack.callback(session.close)

        def keep_evidence():
            write_summary()
            try:
                kept = out / "shots"
                kept.mkdir(exist_ok=True)
                for png in sorted((session.dir / "shots").glob("*.png")):
                    shutil.copy(png, kept / png.name)
                if saved and "read" not in summary:
                    resave = out / "resave"
                    shutil.rmtree(resave, ignore_errors=True)
                    shutil.copytree(session.save_dir, resave)
            except OSError as e:
                print(f"could not keep the evidence: {e}", file=sys.stderr)
            write_summary()

        stack.callback(keep_evidence)
        d: Driver | None = None
        try:
            session.stage(fresh=True)
            shots = session.dir / "shots"
            shutil.rmtree(shots, ignore_errors=True)
            shots.mkdir(parents=True)
            if save is not None:
                took = install(save, session.save_dir, letter, from_slot)
            else:
                # The staged tree's `SAVE` is the archives' play directory;
                # a run with no save starts from an empty one, as `install` does.
                for old in session.save_dir.glob("*"):
                    if old.is_file():
                        old.unlink()
                took = {"from_slot": None, "as_slot": None, "files": []}
            staged = stage(session.save_dir, letter, args)
            if added:
                summary["exports"] = stage_exports(session.save_dir,
                                                   game / "SAVE")
                staged.append({"exports": summary["exports"]["files"]})
            installed = out / "installed"
            shutil.rmtree(installed, ignore_errors=True)
            shutil.copytree(session.save_dir, installed)
            summary["installed"] = took
            summary["staged"] = staged
            note(event="staged", **took, stages=staged)
            if no_encounters:
                installed_save = (session.save_dir
                                  / f"SAVGAM{letter}{title.suffix}")
                if args.title == "ssb" and not installed_save.is_file():
                    raise ValueError("--no-encounters on Silver Blades checks "
                                     "the live variables against the "
                                     "installed save, and none is installed")
                encounters = dosnoencounters.NoEncounters(
                    session, NO_ENCOUNTER_TITLES[args.title],
                    installed_save.read_bytes() if installed_save.is_file()
                    else None,
                    log=lambda line: note(event="no-encounters", note=line),
                    speculative=bool(getattr(args, "speculative_encounters",
                                             False)))
                encounters.on()
            boot_session(session)
            size = sum(1 for f in took.get("files", []) if f.endswith(".SAV")) or 6
            d = Driver(session, note, letter, args.title, party_size=size,
                       deadline=deadline, encounters=encounters)
            if getattr(args, "first_bar_key", None) is not None:
                d.first_bar_key = parse_key(args.first_bar_key)
            d.intervene = bool(getattr(args, "intervene", False))
            d.elminster_ok = any(s.kind == "vault" for s in steps)
            # Only a walk or a turn compares squares, so only they pay for
            # the halts of a memory read.
            if not any(s.kind in ("walk", "turn") for s in steps):
                d.place_reader = None
            summary["events"] = getattr(d, "events", [])
            results = []
            for step in steps:
                deadline.check(step.text)
                note(event="step", step=step.text)
                d.step_begins(step.kind)
                # Before every step but a capture of what `press` left.
                if d.where != "pressed":
                    d.journal(re.sub(r"\W+", "-", step.text))
                    d.yes_no(re.sub(r"\W+", "-", step.text))
                    d.press_continue(re.sub(r"\W+", "-", step.text))
                if step.kind == "load":
                    r = d.load()
                elif step.kind == "begin":
                    r = d.begin()
                elif step.kind == "camp":
                    r = d.camp()
                elif step.kind == "vault":
                    r = d.vault()
                elif step.kind == "deposit":
                    r = d.deposit(step.line, step.row)
                elif step.kind == "leave":
                    r = d.leave()
                elif step.kind == "walk":
                    r = d.walk(step.key)
                elif step.kind == "turn":
                    r = d.turn(step.line)
                elif step.kind == "rest":
                    r = d.rest(step.minutes)
                elif step.kind == "display":
                    r = d.display()
                elif step.kind == "cast":
                    r = d.cast(step.line, step.name, step.row or None)
                elif step.kind == "scribe":
                    r = d.scribe(step.line, step.name)
                elif step.kind == "save":
                    r = d.save(step.letter)
                    saved.append(step.letter)
                elif step.kind == "train":
                    r = d.train(step.line)
                elif step.kind == "change":
                    r = d.change(step.line, step.name)
                elif step.kind == "sheet":
                    r = d.sheet(step.line)
                elif step.kind == "heal":
                    r = d.heal(step.line)
                elif step.kind == "cure":
                    r = d.cure(step.line)
                elif step.kind == "items":
                    r = d.items(step.line)
                elif step.kind == "halve":
                    r = d.halve(step.line, step.row)
                elif step.kind == "join":
                    r = d.join(step.line, step.row)
                elif step.kind == "trade":
                    r = d.trade(step.line, step.row, step.to)
                elif step.kind == "view":
                    r = d.view(step.line)
                elif step.kind == "add":
                    r = d.add(step.name)
                elif step.kind == "memorize":
                    r = d.memorize(step.line)
                elif step.kind == "shot":
                    r = {"shot": d.shot(step.name)}
                elif step.kind == "fight":
                    r = d.fight(step.seconds, step.name == FIRST_BAR)
                elif step.kind == "prayer-watch":
                    r = d.prayer_watch(step.node)
                elif step.kind == "temple":
                    r = d.temple_raise(step.line)
                elif step.kind == "press":
                    r = d.press(step.key)
                elif step.kind == "snapshot":
                    r = d.snapshot(step.name)
                elif step.kind == "restore":
                    r = d.restore(step.name)
                else:
                    r = read_step(session.save_dir, out, letter, saved, steps, expects,
                                  [parse_var(v) for v in getattr(args, "stage_var", []) or []],
                                  args.title)
                    summary["read"] = r
                results.append({"step": step.text, **r})
                note(event="done", step=step.text,
                     **{k: v for k, v in r.items() if k != "slots"})
            summary["results"] = results
            unproved = (walk_verdict(steps, summary.get("read"))
                       or share_verdict(summary.get("read"))
                       or expect_verdict(summary.get("read"))
                       or stored_verdict(results, summary.get("read")))
            doubtful = inconclusive_watch(results)
            if unproved:
                summary["lost"] = unproved
                note(event="lost", why=unproved)
            elif doubtful:
                summary["inconclusive"] = doubtful
                note(event="inconclusive", why=doubtful)
            else:
                summary["completed"] = True
        except (StepFailed, route_silver_blades.RouteLost) as e:
            summary["lost"] = str(e)
            note(event="lost", why=str(e))
        except (KeyboardInterrupt, SystemExit) as e:
            # Recorded and passed on: the ExitStack still writes the summary.
            why = f"{type(e).__name__}({str(e)!r})"
            summary["lost"] = why
            note(event="lost", why=why)
            raise
        except (TimeoutError, dosbox.DosboxUnavailable, dosbox.BlankCapture,
                Terminated) as e:
            why = f"{type(e).__name__}: {e}"
            if isinstance(e, Terminated):
                why = f"Terminated({str(e)!r})"
            if d is not None:
                why = str(d.fail("timeout", why))
            summary["lost"] = why
            note(event="lost", why=why)
        except Exception as e:  # noqa: BLE001 -- a harness crash still ends with `lost`
            traceback.print_exc()
            why = f"{type(e).__name__}: {e}"
            if d is not None:
                why = str(d.fail("error", why))
            summary["lost"] = why
            note(event="lost", why=why)
        if d is not None and getattr(d, "capture_error", None):
            summary["failure_capture_error"] = d.capture_error
    if summary["completed"]:
        return 0
    return 2 if summary.get("inconclusive") and "lost" not in summary else 1


#: Silver Blades' wandering-fight gate and the area whose script (`ECL10`) reads it.
WANDER_GATE = 0x4C2D
GATE_AREA = 16


def check_gate(args, save: pathlib.Path, from_slot: str | None) -> None:
    """Block a `--stage-var` outside the title's array, and a Silver Blades
    `fight` or `prayer-watch` in area 16 whose gate word would not be 1: a
    successful roll there is a compliment, never a fight."""
    staged = [parse_var(t) for t in getattr(args, "stage_var", []) or []]
    fights = any(parse_step(s).kind in ("fight", "prayer-watch")
                 for s in getattr(args, "steps", []))
    if not staged and not (args.title == "ssb" and fights):
        return
    if args.title == "darkness":
        pty = save / f"SAVGAM{from_slot}.PTY"
        if not pty.is_file():
            raise ValueError(f"--stage-var needs a SAVGAM{from_slot}.PTY holding "
                             "the variable array; there is none here")
        for address, value in staged:
            dos_savegame.pod_var_offset(address)
            if value > 0xFF:
                raise ValueError(f"--stage-var {address:02X}={value}: a Pools of "
                                 "Darkness variable is one byte")
        return
    savgam = save / f"SAVGAM{from_slot}.DAT"
    if staged and not savgam.is_file():
        raise ValueError(f"--stage-var needs a SAVGAM{from_slot}.DAT holding the "
                         f"script-variable array; {args.title} has none here")
    if not savgam.is_file():
        return
    data = savgam.read_bytes()
    container = dos_savegame.container_for(len(data))
    for address, _ in staged:
        dos_savegame.word_offset(dos_savegame.pool_address(address, container), container)
    if args.title != "ssb" or not fights:
        return
    if dos_savegame.current_area(data) != GATE_AREA:
        return
    gate = dos_savegame.word(data, dos_savegame.pool_address(WANDER_GATE, container),
                             container)
    for address, value in staged:
        if address == WANDER_GATE:
            gate = value
    if gate != 1:
        raise ValueError(f"a Silver Blades fight in area {GATE_AREA} needs "
                         f"--stage-var {WANDER_GATE:04X}=1: with the gate at "
                         f"{gate} a wandering roll there gives no fight")


def check_vault(args, save: pathlib.Path, from_slot: str | None) -> None:
    """Block a `vault` step whose installed save, with its `--stage-var`
    bytes, would not begin at Elminster's menu with `STORAGE` on it:
    variable `POD_AREA_VAR` must read `ELMINSTER_AREA` and `POD_STORAGE_VAR`
    must not read 1."""
    if not any(parse_step(t).kind == "vault" for t in getattr(args, "steps", [])):
        return
    if args.title != "darkness" or from_slot is None:
        raise ValueError("vault needs a Pools of Darkness save with a SAVGAM<slot>.PTY")
    pty = save / f"SAVGAM{from_slot}.PTY"
    if not pty.is_file():
        raise ValueError(f"vault needs a Pools of Darkness SAVGAM{from_slot}.PTY")
    data = bytearray(pty.read_bytes())
    for address, value in (parse_var(t) for t in getattr(args, "stage_var", []) or []):
        dos_savegame.put_pod_var(data, address, value)
    area = dos_savegame.pod_var(bytes(data), POD_AREA_VAR)
    if area != ELMINSTER_AREA:
        raise ValueError(f"vault opens at Elminster's menu, area {ELMINSTER_AREA}; "
                         f"{pty.name} names area {area} in variable "
                         f"${POD_AREA_VAR:02X}")
    if dos_savegame.pod_var(bytes(data), POD_STORAGE_VAR) == 1:
        raise ValueError(f"vault needs STORAGE on Elminster's menu, which variable "
                         f"${POD_STORAGE_VAR:02X} = 1 takes off: stage --stage-var "
                         f"{POD_STORAGE_VAR:02X}=0")


def check_staging(args, save: pathlib.Path, from_slot: str | None) -> None:
    """Block a stage the installed save cannot take, before a slot is claimed.

    `--hall` is measured for the titles in `HALL_TITLES`
    (`docs/194-the-dos-training-ladder.md`); another title's `SAVGAM` is not
    known to hold the hall word at that offset.  `--xp` and `--add-node` need
    the line's own `CHRDAT` file.
    """
    if getattr(args, "hall", False) and args.title not in HALL_TITLES:
        raise ValueError(f"--hall is measured for {', '.join(sorted(HALL_TITLES))} "
                         f"only, not {args.title}")
    if getattr(args, "hall", False):
        word = save / f"SAVGAM{from_slot}.DAT"
        if word.is_file() and word.stat().st_size < HALL_WORD + 2:
            raise ValueError(f"{word.name} is {word.stat().st_size} bytes, too "
                             f"short for the hall word at {HALL_WORD:#x}")
    check_gate(args, save, from_slot)
    check_vault(args, save, from_slot)
    if getattr(args, "stage_place", None) and args.title == "darkness":
        parse_place(args.stage_place)
        pty = save / f"SAVGAM{from_slot}.PTY"
        if not pty.is_file():
            raise ValueError(f"--stage-place needs a SAVGAM{from_slot}.PTY holding "
                             "the square; there is none here")
        if not dos_savegame.pod_in_dungeon(pty.read_bytes()):
            raise ValueError(f"--stage-place: {pty.name} was saved in the "
                             "wilderness; a place can be staged in a dungeon only")
    elif getattr(args, "stage_place", None):
        parse_place(args.stage_place)
        savgam = save / f"SAVGAM{from_slot}.DAT"
        if not savgam.is_file():
            raise ValueError(f"--stage-place needs a SAVGAM{from_slot}.DAT holding "
                             f"the square; {args.title} has none here")
        data = savgam.read_bytes()
        try:
            dos_savegame.container_for(len(data))
        except dos_savegame.DosSaveError as e:
            raise ValueError(f"--stage-place: {savgam.name} is not a known saved-game "
                             f"size ({e})") from e
        if dos_savegame.outdoors(data):
            raise ValueError(f"--stage-place: {savgam.name} was saved outdoors, where "
                             "the square is not read")
    names = {p.name.upper() for p in save.iterdir()}
    records = parse_record_bytes(getattr(args, "stage_record", []) or [])
    lines = ([parse_xp(t)[0] for t in getattr(args, "xp", []) or []]
             + [parse_node(t)[0] for t in getattr(args, "add_node", []) or []]
             + [parse_control(t)[0] for t in getattr(args, "stage_control", []) or []]
             + [parse_side(t)[0] for t in getattr(args, "stage_side", []) or []]
             + [r[0] for r in records])
    for line in lines:
        want = f"CHRDAT{from_slot}{line}.SAV"
        if want not in names:
            raise ValueError(f"line {line} has no {want} in {save}")
    for line, offset, _ in records:
        record = next(p for p in save.iterdir()
                      if p.name.upper() == f"CHRDAT{from_slot}{line}.SAV")
        if offset >= record.stat().st_size:
            raise ValueError(f"--stage-record offset {offset:#x} is outside "
                             f"{record.name}, which is {record.stat().st_size} bytes")


def charlist_names(folder: pathlib.Path) -> list[str]:
    """The names `folder`'s `CHARLIST.TXT` lists, upper case, or [] without
    one; a `folder` that is not a directory is a ValueError naming it."""
    if not folder.is_dir():
        raise ValueError(f"add needs the title's save folder, and {folder} is "
                         "not a directory")
    path = next((p for p in folder.iterdir() if p.name.upper() == CHARLIST), None)
    if path is None:
        return []
    return [line.strip().upper() for line in
            path.read_bytes().decode("ascii", "replace").splitlines() if line.strip()]


def check_exports(folder: pathlib.Path, names: list[str]) -> None:
    """Block an `add` whose name `folder`'s `CHARLIST.TXT` does not list, or
    lists more than once (the step would not know which row to pick), before
    a slot is claimed."""
    listed = charlist_names(folder)
    for name in names:
        if name not in listed:
            raise ValueError(f"add {name}: {folder / CHARLIST} lists "
                             f"{listed or 'nothing'}")
        if listed.count(name) > 1:
            raise ValueError(f"add {name}: {folder / CHARLIST} lists it "
                             f"{listed.count(name)} times")


def stage_exports(save_dir: pathlib.Path, folder: pathlib.Path) -> dict:
    """Copy every exported character of `folder` (`EXPORT_SUFFIXES`, not a
    saved game's `CHRDAT` file) and its `CHARLIST.TXT` into `save_dir`."""
    files = []
    for p in sorted(folder.iterdir()):
        name = p.name.upper()
        if not p.is_file() or name.startswith("CHRDAT"):
            continue
        if name == CHARLIST or p.suffix.upper() in EXPORT_SUFFIXES:
            (save_dir / name).write_bytes(p.read_bytes())
            files.append(name)
    return {"from": str(folder), "files": files, "listed": charlist_names(folder)}


def stage(save_dir: pathlib.Path, letter: str, args) -> list[dict]:
    """The `--hall`, `--xp`, `--add-node`, `--stage-control`, `--stage-side`,
    `--stage-record`, `--stage-var` and `--stage-place` stages, in that order."""
    done = []
    if getattr(args, "hall", False):
        done.append(stage_hall(save_dir, letter))
    for text in getattr(args, "xp", []) or []:
        done.append(stage_xp(save_dir, letter, *parse_xp(text)))
    for text in getattr(args, "add_node", []) or []:
        done.append(stage_node(save_dir, letter, *parse_node(text)))
    for text in getattr(args, "stage_control", []) or []:
        done.append(stage_control(save_dir, letter, *parse_control(text)))
    for text in getattr(args, "stage_side", []) or []:
        done.append(stage_side(save_dir, letter, *parse_side(text)))
    for line, offset, value in parse_record_bytes(getattr(args, "stage_record", []) or []):
        done.append(stage_record(save_dir, letter, line, offset, value))
    pod = getattr(args, "title", None) == "darkness"
    for text in getattr(args, "stage_var", []) or []:
        done.append((stage_pod_var if pod else stage_var)(save_dir, letter,
                                                          *parse_var(text)))
    if getattr(args, "stage_place", None):
        done.append((stage_pod_place if pod else stage_place)(
            save_dir, letter, *parse_place(args.stage_place)))
    return done


def stage_pod_var(save_dir: pathlib.Path, letter: str, index: int, value: int) -> dict:
    """Write `value` into Pools of Darkness variable `index` (1-based, as the
    scripts number it) of `SAVGAM<letter>.PTY`: one byte, at `index - 1`."""
    path = save_dir / f"SAVGAM{letter.upper()}.PTY"
    data = bytearray(path.read_bytes())
    if not 0 <= value <= 0xFF:
        raise ValueError(f"value {value} is not one byte")
    offset = dos_savegame.pod_var_offset(index)
    before = data[offset]
    dos_savegame.put_pod_var(data, index, value)
    path.write_bytes(bytes(data))
    return {"stage": "var", "file": path.name, "address": f"{index:#04x}",
            "offset": hex(offset), "before": f"{before:02x}",
            "after": f"{data[offset]:02x}"}


def stage_pod_place(save_dir: pathlib.Path, letter: str, x: int, y: int,
                    facing: int) -> dict:
    """Put the party on square `x`,`y` facing `facing` (0 N, 1 E, 2 S, 3 W)
    of `SAVGAM<letter>.PTY`, a save made in a dungeon; only the three square
    bytes at 1024-1026 change."""
    path = save_dir / f"SAVGAM{letter.upper()}.PTY"
    data = bytearray(path.read_bytes())
    if not (0 <= x <= 15 and 0 <= y <= 15 and 0 <= facing <= 3):
        raise ValueError(f"place {x},{y},{facing}: x and y are 0 to 15, facing 0 to 3")
    if not dos_savegame.pod_in_dungeon(bytes(data)):
        raise ValueError(f"{path.name} was saved in the wilderness; a place can be "
                         "staged in a dungeon save only")
    before = list(dos_savegame.position(bytes(data)))
    dos_savegame.put_position(data, x, y, facing)
    path.write_bytes(bytes(data))
    return {"stage": "place", "file": path.name, "before": before,
            "after": [x, y, facing]}


def place_changed(before: dict, after: dict) -> bool:
    """Whether the square or the map differs between two slots' places."""
    a, b = before.get("place") or {}, after.get("place") or {}
    keys = ("x", "y", "area") if "area" in a else ("x", "y", "dungeon_map")
    return any(a.get(k) != b.get(k) for k in keys)


def prayer_watch_rejection(title: str, node: int) -> str | None:
    """Why `prayer-watch node` cannot run in `title`, or None."""
    nodes = PRAYER_WATCH_NODES.get(title)
    if nodes is None:
        return (f"prayer-watch is driven in {', '.join(sorted(PRAYER_WATCH_NODES))} "
                f"only, not {title}")
    if node not in nodes:
        return (f"prayer-watch {node} is driven in pool only: id 35 is Prayer's "
                f"+1 half there, and a {title} Prayer is id 49")
    return None


def inconclusive_watch(results: list[dict]) -> str | None:
    """Why a `prayer-watch` in the results cannot be called a pass or a fail, or None.

    The run is neither: its tested node was gone before the fight, so what the
    handlers did says nothing about a converted Prayer.
    """
    why = [f"{r['step']}: {'; '.join(r['why'])}" for r in results
           if r.get("conclusive") is False]
    return " | ".join(why) or None


def share_verdict(read: dict | None) -> str | None:
    """Why a saved character's control or treasure-share byte no longer
    matches what was installed, or None.

    `compare_shares` runs on every read step; this is what fails the run when
    either byte drifted between the installed slot and the engine-written one.
    """
    if read is None:
        return None
    for x, slot in (read.get("slots") or {}).items():
        for row in slot.get("shares", []):
            if row["present"] and not row["matches"]:
                return (f"{row['name']}'s control or treasure_share changed in "
                        f"slot {x}: control {row['control_before']} -> "
                        f"{row['control_after']}, share {row['share_before']} -> "
                        f"{row['share_after']}")
    return None


def expect_verdict(read: dict | None) -> str | None:
    """Why each `--expect` the run stated was refuted by the last saved slot, or None."""
    refuted = []
    for v in (read or {}).get("verdicts", []):
        if v["verdict"] == "refutes":
            e = v["expect"]
            data = "" if e.get("data") is None else f":{e['data']}"
            refuted.append(f"expectation {e['name']}:{e['id']}:{e['minutes']}{data} "
                           f"refuted: {v['why']}")
    return "; ".join(refuted) or None


def vault_verdict(results: list[dict], read: dict | None) -> str | None:
    """Why a run with a `vault` step has not shown the vault it installed, or
    None: the list must count the installed file's items, leaving must have
    written `TMPVAULT.DAT` holding them and its coins, and the last saved
    slot's vault, when a save followed, must hold the same."""
    got = next((r for r in results if r.get("step") == "vault"), None)
    if got is None:
        return None
    want = got["expected"]
    tmp = got.get("tmpvault")
    if tmp is None:
        return f"leaving the vault wrote no {TMPVAULT}"
    if not got["matches"]:
        window = got.get("window") or {}
        if "page" in window:
            return (f"page {window['page']} of the vault's list reads "
                    f"{window['read']}, not the names {tmp['file']} caches, "
                    f"{window['names']}")
        return (f"the vault listed {got['listed']} items where the installed "
                f"{want['file'] or 'slot (no vault file)'} holds {want['items']}")
    keys = ("items", "platinum", "gems", "jewelry")
    if "error" in tmp or any(tmp[k] != want[k] for k in keys):
        return (f"{tmp['file']} does not hold the installed vault: "
                f"{tmp.get('error') or {k: tmp[k] for k in keys}} against "
                f"{ {k: want[k] for k in keys} }")
    if not read or not read.get("saved"):
        return None
    last = read["saved"][-1]
    saved = (read.get("slots") or {}).get(last, {}).get("vault")
    if saved is None:
        return f"slot {last} was saved with no VAULT{last}.DAT"
    held = {"items": len(saved["items"]), **{k: saved[k] for k in keys[1:]}}
    if held != {k: want[k] for k in keys}:
        return f"VAULT{last}.DAT holds {held}, not the installed {want}"
    return None


def deposit_verdict(results: list[dict], read: dict | None) -> str | None:
    """Why a run with `deposit` steps has not shown the game storing each
    item, or None: each step's own check (`Driver.deposit`), and the last
    saved slot's vault, when a save followed, holding what the last deposit
    left in `TMPVAULT.DAT`."""
    deposits = [r for r in results if str(r.get("step", "")).split()[:1] == ["deposit"]]
    if not deposits:
        return None
    for r in deposits:
        if r.get("why"):
            return f"{r['step']}: {r['why']}"
    if not read or not read.get("saved"):
        return None
    last = read["saved"][-1]
    saved = (read.get("slots") or {}).get(last, {}).get("vault")
    if saved is None:
        return f"slot {last} was saved with no VAULT{last}.DAT"
    keys = ("platinum", "gems", "jewelry")
    want = deposits[-1]["tmpvault"]
    held = {"items": len(saved["items"]), **{k: saved[k] for k in keys}}
    if held != {"items": want["items"], **{k: want[k] for k in keys}}:
        return (f"VAULT{last}.DAT holds {held}, not the {want['items']} items "
                f"the last deposit left")
    return None


def stored_verdict(results: list[dict], read: dict | None) -> str | None:
    """`vault_verdict`, or with deposits its listing and file checks alone
    (the saved vault no longer holds the installed one) and then
    `deposit_verdict`."""
    if not any(str(r.get("step", "")).split()[:1] == ["deposit"] for r in results):
        return vault_verdict(results, read)
    return vault_verdict(results, None) or deposit_verdict(results, read)


def walk_verdict(steps: list[Step], read: dict | None) -> str | None:
    """Why a run that asked for a walk or a turn has not shown it, or None.

    The proof is the place decoded from the game-written save, the same in
    every title: after a walk the last save the run made must not be at the
    square the installed one was; after `turn` steps alone, the control, it
    must be.  A place that was not computed proves nothing.
    """
    walked = any(s.kind == "walk" for s in steps)
    if not walked and not any(s.kind == "turn" for s in steps):
        return None
    asked = "a walk" if walked else "a turn"
    if read is None:
        return (f"{asked} was asked and no read step decoded a saved place, so "
                "nothing shows " + ("the party moved" if walked else "it did not move"))
    slots = read.get("slots") or {}
    order = [x for x in read.get("saved") or [] if x in slots] or list(slots)
    if not order:
        return (f"{asked} was asked and no saved slot was read, so nothing shows "
                + ("the party moved" if walked else "it did not move"))
    last = order[-1]
    slot = slots[last]
    if "place_changed" not in slot or "x" not in (slot.get("place") or {}):
        return (f"{asked} was asked and slot {last}'s place was not computed "
                f"({(slot.get('place') or {}).get('error', 'no place read')})")
    if walked and not slot["place_changed"]:
        return (f"the walk did not move the party: the game-written slot {last} "
                "is at the square the installed slot was")
    if not walked and slot["place_changed"]:
        return (f"the turn moved the party: the game-written slot {last} is not "
                "at the square the installed slot was")
    return None


def read_step(save_dir: pathlib.Path, out: pathlib.Path, letter: str,
              saved: list[str], steps: list[Step], expects: list[Expect],
              staged_vars: list[tuple[int, int]] | None = None,
              title: str | None = None) -> dict:
    """Copy `SAVE/` out and decode the installed slot against each saved one,
    and report each `--stage-var` word as the last saved slot holds it."""
    resave = out / "resave"
    shutil.rmtree(resave, ignore_errors=True)
    shutil.copytree(save_dir, resave)
    before = read_slot(out / "installed", letter)
    asked = sum(s.minutes for s in steps if s.kind == "rest")
    result: dict = {"installed": before, "rested_minutes": asked, "slots": {},
                    "saved": list(saved)}
    previous = before
    for x in saved:
        after = read_slot(resave, x)
        animated = animated_members(steps, expects, after)
        result["slots"][x] = {
            **after,
            "clock_advanced": after["clock_minutes"] - before["clock_minutes"],
            "clock_since_previous": after["clock_minutes"] - previous["clock_minutes"],
            "compare": compare_nodes(before, after),
            "experience": compare_experience(before, after),
            "members": compare_members(before, after),
            "shares": compare_shares(before, after, animated, title),
        }
        if any(st.kind in ("walk", "turn") for st in steps):
            result["slots"][x]["place_changed"] = place_changed(before, after)
        previous = after
    if saved and staged_vars and title == "darkness":
        data = (resave / f"SAVGAM{saved[-1]}.PTY").read_bytes()
        result["staged_vars"] = {
            f"{address:02X}": {"slot": saved[-1], "staged": value,
                               "saved": dos_savegame.pod_var(data, address)}
            for address, value in staged_vars}
    elif saved and staged_vars:
        data = (resave / f"SAVGAM{saved[-1]}.DAT").read_bytes()
        container = dos_savegame.container_for(len(data))
        result["staged_vars"] = {
            f"{address:04X}": {"slot": saved[-1], "staged": value,
                               "saved": dos_savegame.word(
                                   data, dos_savegame.pool_address(address, container),
                                   container)}
            for address, value in staged_vars}
    for row in result.get("staged_vars", {}).values():
        row["held"] = row["staged"] == row["saved"]
    if saved and expects:
        result["verdicts"] = [judge(e, result["slots"][saved[-1]]) for e in expects]
    for line in describe(result):
        print(line, flush=True)
    return result


def describe(result: dict) -> list[str]:
    """The reading, one line per fact, for the terminal."""
    lines = []
    for x, s in result["slots"].items():
        lines.append(f"slot {x}: clock advanced {s['clock_advanced']} minutes "
                     f"(rested {result['rested_minutes']}), "
                     f"{s.get('clock_since_previous', s['clock_advanced'])} since "
                     "the save before it")
        place = s.get("place") or {}
        if "place_changed" in s:
            was = (result.get("installed") or {}).get("place") or {}
            lines.append(f"  moved from {was.get('x')},{was.get('y')} to "
                         f"{place.get('x')},{place.get('y')}"
                         if s["place_changed"] else "  did not move")
        if "area" in place:
            lines.append(f"  area {place['area']} at {place['x']},{place['y']} "
                         f"facing {place['facing']}, set out {place['set_out']}")
        elif "dungeon_map" in place:
            lines.append(f"  map {place['dungeon_map']} at {place['x']},{place['y']} "
                         f"facing {place['facing']}, in a dungeon {place['in_dungeon']}")
        for row in s.get("members", []):
            if not row["present"]:
                lines.append(f"  {row['name']}: not in the resave")
                continue
            lines.append(
                f"  {row['name']}: pick pockets {row['thief']['after']['thief_pick_pockets']}"
                f", {row['item_count']['after']} items ({len(row['items']['after'])} "
                f"read), encumbrance {row['encumbrance']['after']}, movement "
                f"{row['movement']['after']}, moving "
                f"{row['movement_current']['after']}, byte 0x130 "
                f"{row['book_0x130']['after']}; "
                + ("unchanged" if not row["changed"] else
                   "changed: " + ", ".join(row["changed"])))
        for row in s["compare"]:
            if row["before"] is None:
                lines.append(f"  {row['name']} id {row['id']}: new node, "
                             f"{row['after']} minutes")
            elif row["after"] is None:
                lines.append(f"  {row['name']} id {row['id']}: {row['before']} "
                             f"minutes before, no node after")
            else:
                lines.append(f"  {row['name']} id {row['id']}: {row['before']} -> "
                             f"{row['after']} minutes (lost {row['lost']}), data "
                             f"{row['data_before']:02X} -> {row['data_after']:02X}")
        for row in s.get("experience", []):
            if row["gained"]:
                lines.append(f"  {row['name']} experience {row['before']} -> "
                             f"{row['after']} ({row['gained']:+d})")
    for v in result.get("verdicts", []):
        e = v["expect"]
        lines.append(f"expect {e['name']} id {e['id']} at {e['minutes']} minutes: "
                     f"{v['verdict']}" + (f" ({v['why']})" if "why" in v else ""))
    for address, row in (result.get("staged_vars") or {}).items():
        if not row["held"]:
            lines.append(f"staged variable ${address}: staged {row['staged']}, "
                         f"slot {row['slot']} holds {row['saved']}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", choices=sorted(TITLES), default="pool")
    # One source is required, except by a run whose first step is `add`,
    # which drives the party menu before any load.
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--save", help="a DOS save folder Wish wrote, a SAVGAM?.DAT "
                                    "(or .PTY and VAULT?.DAT) and its CHRDAT files")
    src.add_argument("--fixture-row", action="append", default=[],
                     metavar="SLOT=ID:OWNER:DURATION:MAGNITUDE",
                     help="hex; stage this effect row into a C64 party and "
                          "convert it with Save As DOS first (repeatable)")
    src.add_argument("--amiga-slot", default=None, metavar="SavGamA.pty",
                     help="darkness: convert this slot of --amiga-disk to DOS "
                          "through the Convert window's route first")
    src.add_argument("--convert", default=None, metavar="PATH",
                     help="a C64 .D64 or Amiga .adf holding a pool, curse or "
                          "ssb save; convert it with Save As DOS first "
                          "(not darkness: use --amiga-slot)")
    ap.add_argument("--name", action="append", default=[], metavar="POSITION=NAME",
                    help="with --convert: the name for the party member at "
                         "POSITION (0 is the first), as the Shorten window "
                         "would give it; repeatable")
    ap.add_argument("--amiga-disk", default=None,
                    help="with --amiga-slot: an .adf path, or the end of one "
                         "Amiga disk label ('Pools Of Darkness.zip!Pools of "
                         "Darkness3.adf')")
    ap.add_argument("--convert-slot", default="A",
                    help="with --convert: the source's own save slot letter "
                         "(default A)")
    ap.add_argument("--c64-save", default=None,
                    help="with --fixture-row: the C64 disk to stage into, "
                         "instead of the title's own (C64_BASES)")
    ap.add_argument("--from-slot", default=None,
                    help="with --save: which slot of the folder to install, "
                         "when it holds more than one")
    ap.add_argument("--slot", default="A", help="the letter to install and load as")
    ap.add_argument("--steps", nargs="*", default=[], help=STEP_HELP)
    ap.add_argument("--hall", action="store_true",
                    help="open every school: SAVGAM+0xD51 = 0x00FF before the boot")
    ap.add_argument("--xp", action="append", default=[], metavar="LINE=VALUE",
                    help="stage roster line LINE's experience before the boot")
    ap.add_argument("--add-node", action="append", default=[],
                    metavar="LINE=ID:MINUTES:DATA:FLAG",
                    help="append an effect node to roster line LINE before the boot")
    ap.add_argument("--stage-control", action="append", default=[],
                    metavar="LINE=CONTROL[:SHARE]",
                    help="stage roster line LINE's field_83_87 control byte, "
                         "and optionally the treasure-share byte after it, "
                         "before the boot")
    ap.add_argument("--stage-side", action="append", default=[],
                    metavar="LINE=SIDE[:QUICKFIGHT]",
                    help="stage roster line LINE's combat side byte (1 is the "
                         "enemy's) and optionally the quickfight byte after it, "
                         "after --stage-control, before the boot")
    ap.add_argument("--stage-record", action="append", default=[],
                    metavar="LINE:OFFSET=VALUE",
                    help="stage one byte of roster line LINE's CHRDAT record "
                         "(decimal or 0x hex, comma-separated or repeated), "
                         "after --stage-side, before the boot")
    ap.add_argument("--stage-var", action="append", default=[], metavar="ADDRESS=VALUE",
                    help="stage one script-variable word of SAVGAM (the title's own "
                         "hex address, decimal or 0x hex value), after "
                         "--stage-record, before the boot; in darkness one byte "
                         "of SAVGAM<L>.PTY by its 1-based hex index (A2=0 puts "
                         "STORAGE on Elminster's menu); a Silver Blades fight in "
                         "area 16 needs 4C2D=1")
    ap.add_argument("--stage-place", default=None, metavar="X,Y,FACING",
                    help="stage the party's square and facing (0 to 15, facing 0 "
                         "to 3 = N E S W) in an indoor SAVGAM, or a dungeon "
                         "SAVGAM<L>.PTY in darkness, after --stage-var, "
                         "before the boot")
    ap.add_argument("--first-bar-key", default=None, metavar="KEY",
                    help="SPACE or one letter or digit, pressed once at the "
                         "first command bar of the first fight instead of "
                         "QUICK (curse and ssb, with a fight step)")
    ap.add_argument("--intervene", action="store_true",
                    help="start the game as `START.EXE X Gem` and press its own "
                         "Alt+X once at the bar after the first-bar key (at the "
                         "first bar without one), which kills the monsters and "
                         "ends the fight in the party's favour (ssb, with a "
                         "fight step)")
    ap.add_argument("--no-encounters", action="store_true",
                    help="write the running area's encounter gate through the "
                         "DOSBox-X debugger before every move key, and stop "
                         "any save step; for driver and automapper testing, "
                         "never for a run that proves a conversion")
    ap.add_argument("--speculative-encounters", action="store_true",
                    help="with --no-encounters, use Silver Blades' data-segment "
                         "offsets, which were not read in a running game")
    ap.add_argument("--expect", action="append", default=[],
                    metavar="NAME:ID:MINUTES[:DATA]",
                    help="a node the last saved slot must hold (repeatable)")
    ap.add_argument("--issue", default="661")
    ap.add_argument("--run", default="run", help="the run's name in the evidence path")
    ap.add_argument("--out", default=None,
                    help="evidence directory (default ~/.cache/wish/acceptance/"
                         "<issue>/<sha>-<run>)")
    ap.add_argument("--note", default="dosacceptance")
    ap.add_argument("--deadline", type=float, default=DEADLINE_SECONDS,
                    help=f"seconds the whole run may take, {CLEANUP_SECONDS:.0f} "
                         "of them kept for the cleanup; wrap the command in "
                         f"`timeout -k 30` (a bare `timeout` sends SIGTERM only) "
                         f"set at least {WRAPPER_MARGIN:.0f} s longer")
    args = ap.parse_args(argv)
    try:
        for s in args.steps:
            parse_step(s)
        for e in args.expect:
            parse_expect(e)
        for r in args.fixture_row:
            parse_row(r)
        for x in args.xp:
            parse_xp(x)
        for n in args.add_node:
            parse_node(n)
        for c in args.stage_control:
            parse_control(c)
        for c in args.stage_side:
            parse_side(c)
        parse_record_bytes(args.stage_record)
        for v in args.stage_var:
            parse_var(v)
        if getattr(args, "stage_place", None):
            parse_place(args.stage_place)
        validate_steps([parse_step(s) for s in args.steps], args.title)
        why = temple_staging_rejection(args, [parse_step(s) for s in args.steps])
        if why:
            raise ValueError(why)
        if not (args.save or args.fixture_row or args.amiga_slot or args.convert):
            parsed = [parse_step(s) for s in args.steps]
            if not parsed or parsed[0].kind != "add":
                raise ValueError("one of --save, --fixture-row, --amiga-slot or "
                                 "--convert is required, except by a run that "
                                 "begins with add")
            staging = ("hall", "xp", "add_node", "stage_control", "stage_side",
                       "stage_record", "stage_var", "stage_place", "expect")
            if any(getattr(args, a, None) for a in staging):
                raise ValueError("a run with no save has nothing to stage or expect")
            if args.from_slot or args.first_bar_key is not None:
                raise ValueError("--from-slot picks a slot of a save and "
                                 "--first-bar-key is pressed in a fight; a run "
                                 "with no save has neither")
            if any(p.kind == "read" for p in parsed):
                raise ValueError("read compares the installed slot with the saved "
                                 "one, and a run with no save installs none")
        if args.first_bar_key is not None:
            parse_key(args.first_bar_key)
            if not any(parse_step(s).kind == "fight" and parse_step(s).name != FIRST_BAR
                       for s in getattr(args, "steps", [])):
                raise ValueError("--first-bar-key is pressed in a fight: add a "
                                 f"fight step other than fight {FIRST_BAR}")
        if args.speculative_encounters and not args.no_encounters:
            raise ValueError("--speculative-encounters goes with --no-encounters")
        if args.no_encounters and args.title == "ssb" \
                and not args.speculative_encounters:
            raise ValueError("--no-encounters on Silver Blades needs "
                             "--speculative-encounters: its offsets were not "
                             "read in a running game")
        if args.no_encounters and args.title not in NO_ENCOUNTER_TITLES:
            raise ValueError(f"--no-encounters is for "
                             f"{', '.join(sorted(NO_ENCOUNTER_TITLES))} only, "
                             f"not {args.title}")
        if args.intervene:
            if args.title not in CHEAT_ARGS:
                raise ValueError(f"--intervene is measured for "
                                 f"{', '.join(sorted(CHEAT_ARGS))} only, not {args.title}")
            if not any(parse_step(s).kind == "fight" and parse_step(s).name != FIRST_BAR
                       for s in args.steps):
                raise ValueError("--intervene is pressed in a fight: add a fight "
                                 f"step other than fight {FIRST_BAR}")
        if args.hall and args.title not in HALL_TITLES:
            raise ValueError(f"--hall is measured for {', '.join(sorted(HALL_TITLES))} "
                             f"only, not {args.title}")
        if args.fixture_row and args.title == "darkness":
            raise ValueError("--fixture-row converts a C64 party, and Pools of "
                             "Darkness has no C64 port: use --amiga-slot")
        if args.amiga_slot:
            if args.title != "darkness":
                raise ValueError("--amiga-slot converts a Pools of Darkness save: "
                                 "pass --title darkness")
            if not args.amiga_disk:
                raise ValueError("--amiga-slot needs --amiga-disk")
            parse_amiga_slot(args.amiga_slot)
        if args.convert:
            if args.title == "darkness":
                raise ValueError("--convert converts a pool, curse or ssb save: "
                                 "Pools of Darkness has none of those; use "
                                 "--amiga-slot")
            if not re.fullmatch(r"[A-Ja-j]", args.convert_slot):
                raise ValueError("--convert-slot is one letter, A to J")
            parse_names(args.name, args.title)
        elif args.name:
            raise ValueError("--name goes with --convert")
    except ValueError as e:
        ap.error(str(e))
    if not re.fullmatch(r"[A-Ja-j]", args.slot):
        ap.error("--slot is one letter, A to J")
    if args.from_slot and not re.fullmatch(r"[A-Ja-j]", args.from_slot):
        ap.error("--from-slot is one letter, A to J")
    if not re.fullmatch(r"[\w-]+", args.run) or not re.fullmatch(r"[\w-]+", args.issue):
        ap.error("--issue and --run are simple names")
    try:
        return run(args)
    except ValueError as e:
        ap.error(str(e))


if __name__ == "__main__":
    raise SystemExit(main())
