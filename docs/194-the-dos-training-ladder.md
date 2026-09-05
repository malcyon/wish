# The DOS training ladder

**How a DOS Pool of Radiance party is levelled through the game's own four
training schools, without playing the game for hours.** The C64 side has had
this since `#10 (Finish the high-level test party)` drove twenty-nine
level-ups through the training hall; this is the DOS half, and it is what
every DOS measurement about a levelled character now rests on.

`tools/dosladder.py` is the tool. `docs/90-specimens.md` says what is in the
specimen tree; this says how the records in it were made and which numbers are
the engine's.

## What is ours and what is the engine's

`.claude/rules/testing.md` draws the line and everything below keeps to it.

| written before the boot, by us | computed by the engine, in front of us |
|---|---|
| `experience` (`0x0AC`, three bytes little-endian) | `level`, and the per-class array behind `class_levels` |
| `gold` (`0x08E`, a word) and `encumbrance` (`0x102`) moved with it | `hp_max`, `hp_rolled`, THAC0, saving throws, spell slots, thief skills |
| — | the experience the trainer **leaves behind** |
| — | which spell a magic-user is offered, and gets |

Editing an input and watching the game compute from it is a valid experiment:
the engine does not care how a byte got there. Reading back a stored value we
wrote and calling it the game's arithmetic is not. So a finding about
`hp_rolled` from these specimens stands; a finding about how much experience a
level costs, from a record we staged at 300,000, does not.

## The hall, and the four schools

Area 11 has no map of its own -- it reuses New Phlan's `GEO00` -- so the
schools are New Phlan's own squares under a second script. The table is
`ECL0B`'s, read on the C64 (`docs/50-experiments.md`, P18) and confirmed
square by square against the player's own DOS `GEO00` at run time by
`dosladder.check_hall`, which refuses to walk if they disagree.

| square | script id | what it is |
|---|---|---|
| (5,0) | 12 | clerics' school |
| (6,0) | 11 | the sign: magic users east, clerics west |
| (7,0) | 13 | magic users' school |
| (8,0) | 16 | **fighters' school** |
| (9,0) | 17 | **thieves' school** |
| (6,1), (6,2) | 10 | the lobby |
| (7,1), (7,2), (8,2), (9,2) | 14 | the duelling arena |
| (8,1) | 15 | the sign: FIGHTERS |
| (9,1) | 18 | the sign: ROGUES |

**The fighters' and thieves' schools are not off the (6,0) corridor.** An
earlier run looked for them there, found a wall stepping east from (7,0), and
recorded the east side as unmapped. They are off the other corridor:
`(6,0) (6,1) (7,1) (8,1) (8,0)` for fighters, and `(8,1) (9,1) (9,0)` for
thieves. The tool computes both with a breadth-first search over the thirteen
squares, so the route is arithmetic rather than a remembered key list, and
`tests/test_dosladder.py` checks every route against `goldbox.geo`'s own
`walkable_route` with no emulator in sight.

**Stepping through (7,1) or any arena square fires an offer** that holds the
command bar. `Return` then `n` clears it. Anything driving this has to notice
a step that did not bring the map's bar back rather than pressing on.

## Getting into the hall, and getting back to the map

A save made **outside** the hall is put down at `(7,2)` facing west and steps
in: entering `(6,2)` fires script 10 and loads area 11. A save cannot be
dropped on `(6,2)` itself, because `ECL0B` dispatches on the *departing*
square's attribute byte -- the same reason a fasttravel cannot enter area 11.

A save made **inside** the hall needs none of that. The trainer's own save
records area 11 and the school square, and reloading it puts the party back
where it stood, so a ladder that feeds itself never walks in again.

**A save the trainer wrote loads back to the party menu, not the map.**
`SAVE CURRENT GAME` is a party-menu command and the game returns you to where
you saved from, so a run whose input is its own last rung starts at
`CHOOSE A FUNCTION` and every movement key it presses goes into a menu that
ignores it. `b` is BEGIN ADVENTURING there and nothing at all on the map, so
pressing it and watching the command bar is both the test and the fix. One
boot was spent on this: the log said "step to (6,0)" fourteen times and every
screenshot was the same menu.

## Driving the party menu

**The roster highlight survives the menu closing, and `End` wraps.** A school
opened after another school opens with the highlight where the last one left
it, not on the first character, and `End` from the sixth line goes back to the
first. So the count from any line to any other is `(want - here) % 6`, tracked
across the whole boot. A run that assumed the highlight reset trained whoever
was two lines below the previous trainee, and every one of those was refused
because it was the wrong class for that school -- which looks exactly like the
game refusing a legitimate request.

**A `t` that leaves the screen exactly as it was is a refusal.** There is no
message left on a settled screen. A `t` that changes it is
`<NAME> WILL BECOME: A LEVEL n <CLASS>` over `DO YOU WISH TO TRAIN? YES NO`,
and `y` accepts.

**A magic-user chooses a spell before the menu comes back.** The screen is
`<NAME>'S SPELLS TO CHOOSE FROM` with `CHOOSE SPELL: LEARN` on the bar, and
until it is answered every later keypress lands in it -- which is what made a
`SAVE CURRENT GAME` write nothing and a `BEGIN ADVENTURING` never reach the
map, two failures whose visible symptom was a hang three actions later. `l`
takes the highlighted spell.

## The word at `0xD51` is the school's class filter

**CONFIRMED**, four schools and two controls, every value written by the
engine's own `SAVE CURRENT GAME` with the party standing in the school.

| where the party stood | word at `0xD51` | hex | class bit |
|---|---|---|---|
| magic users' school (7,0) | 113 | `0x71` | 1, magic-user |
| clerics' school (5,0) | 114 | `0x72` | 2, cleric |
| thieves' school (9,0) | 116 | `0x74` | 4, thief |
| fighters' school (8,0) | 120 | `0x78` | 8, fighter |
| New Phlan, outside the hall | 0 | | none |

That is `0x70 | class_bit`, and the bits are `goldbox.games.CLASS_BITS_CLASSIC`
-- the same four values the C64 writes into `$6DA8`, which
`docs/50-experiments.md` P18 read out of `ECL0B`.

`docs/117-save-conversion.md` and `docs/176-changing-class-twice.md` call this
word "the training hall's maximum level", from Curse of the Azure Bonds' and
Silver Blades' loaders. **The gate they found is untouched** -- the loader's
test is `cmp word es:[di+0x550], 0`, which cannot tell a maximum level from a
class mask, and poking the word non-zero still puts TRAIN CHARACTER in the
party menu wherever the party stands. What the six Pool of Radiance saves
settle is what the *engine writes* there. Curse and Silver Blades are not
measured: that needs a party standing in one of their halls when the engine
saves.

## The experience clamp, and why a rung is a boot

**The trainer clamps experience whether or not it trains**, measured in
`#249 (Build a DOS party from creation and level it ourselves, so DOS
measurements rest on records we watched being written)`. The rule, **CONFIRMED on 42 of 42
trainings** across six characters and nine rungs, single-class and
multi-class:

> Take the levels the character had **when `TRAIN` was pressed**. For each of
> its classes, look up the experience threshold **two** levels above that
> class's level. The trainer leaves the largest of those, less one.

For a single-class character that is one point short of its next level, which
is why nobody can train twice on one staging. For a multi-class character it
is the largest of its classes' caps, and *not* the class it just trained:
WISHHEL, a cleric 2 / fighter 1 / magic-user 1 trained to fighter 2, came out
holding 6,000 -- one below cleric level 4's 6,001, the largest of 6,000
(cleric), 4,000 (fighter) and 5,000 (magic-user).

**At a class's ceiling the clamp does nothing.** WISHCLE trained cleric 5 to 6,
where there is no threshold two levels above, and her experience came back out
at the 300,000 that went in -- three rungs running, including two where the
school refused her outright. `dosladder.clamp_cap` returns None for that case
rather than guessing.

`tools/dosladder.py --audit <run>` prints the prediction against what the
engine left, one row per training, and names any that disagree.

**So a rung is a boot.** Install, load, walk, train at up to four schools,
save, tear down, and stage the next level's experience into the records the
game has just written. About four and a half minutes each.

Training costs a flat **1000 gp** at every level, which is what `#10 (Finish
the high-level test party)` measured across twenty-nine C64 levels.

**The clamp trims a surplus rather than charging a price.** Staged at exactly
one level's threshold plus 7 -- 20,008 against thief level 6's 20,001, and
18,008 against fighter level 5's 18,001 -- both characters trained, gained a
level, paid the 1000 gp, and came back out holding the experience they went in
with. `WISH-SPEC-por-party-ladder-rung8` is that experiment, and
`--xp-mode threshold` is how to repeat it.

**A multi-class character is not asked for a multiple of the threshold.** The
same run trained a fighter 6 / thief 6 dwarf on a single thief's threshold and
a three-class half-elf on a single fighter's. That refutes the reading in
`docs/50-experiments.md` P18, which took a C64 drop of 2,502 as "twice the
thief's level-2 threshold, the price of one level for a two-class character".

**One thing the two ports disagree about, and it is not settled.** P18's LADY
KATHERINE -- magic-user 1 / thief 1 on the C64, trained thief to 2 -- came out
on 2,500 where the DOS rule above predicts 5,000. One sample on each port, so
this is UNKNOWN: what would settle it is one more C64 multi-class training
with the two classes at different levels, on a party nobody has edited since.

## What the records say about the two ports

`tools/dosladder.py --audit` also prints `thac0_base` for every level the
engine wrote, against `goldbox/levels.py`. Fighters and clerics agree exactly.
**Magic-users at levels 1-5 and thieves at levels 1-4 do not**: DOS stores 40,
which is THAC0 20, where the C64's own table at `GEN $1F1F` holds 39, which is
21. The thief's stored value steps to 41 at level 5 on both ports, so the DOS
engine is maintaining the field rather than ignoring it.
`#318 (DOS gives a low-level magic-user or thief THAC0 20 where the C64 gives
21, and our table holds only the C64's)` has the measurement and what it
would mean for a converted or Wish-levelled character.

## The party the ladder made

Nine boots, forty-two trainings, from the six characters `tools/dosparty.py`
rolled in the game's own creation screens.

| slot | name | race | classes at the end | HP | rolled |
|---|---|---|---|---|---|
| 1 | WISHFTR | human | fighter **8**, the ceiling | 59 | 51 |
| 2 | WISHCLE | human | cleric **6**, the ceiling | 23 | 23 |
| 3 | WISHMAG | elf | magic-user **6**, the ceiling | 16 | 16 |
| 4 | WISHTHI | halfling | thief **9**, the ceiling | 31 | 22 |
| 5 | WISHDWF | dwarf | fighter 6 / thief 6 | 47 | 26 |
| 6 | WISHHEL | half-elf | cleric 5 / fighter 5 / magic-user 4 | 22 | 22 |

Every rung is its own specimen, each holding the whole slot --
`SAVGAM<letter>.DAT`, six `.SAV`, four `.SPC` -- plus the run's own
`run.jsonl`, so the climb can be re-derived rung by rung with no emulator.
In the order they were made: `WISH-SPEC-por-party-ladder-rung0` through
`rung7`, then `WISH-SPEC-por-party-ladder`, which is the last rung of the
flat-staged climb and the name `tests/test_dosladder.py` points at, and then
`rung8`, the threshold-staged rung and the newest state -- the one the table
above describes.

## Running it

    tools/dosladder.py --party $WISH_SPECIMENS/por-dos/WISH-SPEC-por-party-l1-intown \
        --enter 7,2,W --rungs 6 --xp 300000 --gold 20000 \
        --out work/issue249/ladder

Each rung writes `before/` and `after/` snapshots of the whole `SAVE`
directory, a `run.jsonl` with one line per step, prompt, training and save,
and a screenshot of every frame it acted on. `--xp-mode threshold` stages one
level's worth plus a margin instead of a flat number, which is what tells the
clamp apart from a price.

**A specimen dies with the emulator slot that made it.** `work/` is gitignored
and has been lost twice; copy a rung worth keeping into `$WISH_SPECIMENS` with
`tools/specimens.py add` before the slot goes down.
