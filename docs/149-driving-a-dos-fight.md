# Driving a fight in DOSBox

How a Pool of Radiance fight is answered and finished under DOSBox 0.74 with
no debugger, no memory read, and nothing anywhere that reads a word off the
screen. `docs/70-driving-the-game.md` is the same subject on the C64 under
VICE, where the machine's memory is readable and the answers come out quite
differently.

The code is `tools/dosfightrun.py` and the `fight()` end of
`tools/dosbox.py`'s `PoolOfRadiance`. The work is `#114 (Drive a fight in
DOSBox, so a converted save can be checked past loading)`.

## Ground truth is the files, and experience is the only field that says it

**Experience rising is the one signal that names the party as the killer.**
`CHRDAT<slot><n>.SAV` offset `0x0AC`, three bytes little-endian. It is paid
for monsters defeated, and monsters do not kill each other -- so a rise could
not have come from anybody else. That is the DOS answer to `#163 (A fight
nobody in the party fought is reported as one they did)`, whose C64 message
band prints `HITS` and `MISSES` for both sides in the same words and so names
nobody at all.

**Hit points falling is the same trap in a new place and is never proof.**
`0x11B` going down says the monsters struck the party. A party member who
swings and misses lowers nothing, and a party that stands still and is beaten
on lowers plenty. `tools/dosfightrun.py` reports it and never cites it, and
`test_hit_points_falling_is_never_proof_that_the_party_fought` pins that.

## The bars, by the glyphs of the bottom row

`Screen.glyphs(BAR)` -- the bottom text row with every pixel that is not the
strip's own background colour counted as a glyph. **The words below were read
once, by a person, off the PNG each row names.** Nothing in the driver ever
matches them; it compares digests, and a digest cannot be misread, only
unequal.

| glyphs of `BAR` | the words on it | what it is | the driver presses |
|---|---|---|---|
| `158ce64b7cdf4362` | `AREA CAST VIEW ENCAMP SEARCH LOOK` | the world bar, whose return is how a fight is known to be over | nothing; this is the end |
| `327fcbaaeb46c2fb` | `COMBAT WAIT FLEE ADVANCE` | the encounter menu | `c` |
| `e5b3317d2142242d` | `A BATTLE BEGINS...` | a message occupying the bar row, shown when the party surprises the monsters | nothing |
| `f399fe870112b71a` | *(one flat colour)* | the bar row caught mid-redraw | nothing |
| *(no fixed digest -- recognised by its prefix, below)* | `MOVE VIEW AIM USE ... QUICK DONE` | one character's turn | `q` |
| `c545a9ecbcaa33dc` | `CONTINUE BATTLE : YES NO` | asked once the fight can be called off | `n` |
| `f1672ba1064bf2b1` | `PRESS <ENTER>/<RETURN> TO CONTINUE` | under `THE PARTY HAS WON.` and the experience share | `Return` |
| `39afdcc0f8704784` | `VIEW TAKE POOL SHARE EXIT` | the treasure the fight left behind | `e` |
| `c576b6838d2e460b` | `YES NO`, under `THERE IS STILL TREASURE LEFT. DO YOU WANT TO GO BACK AND CLAIM YOUR TREASURE?` | asked because the driver leaves the treasure where it lies | `n` |

Measured on DOSBox 0.74-3, `machine=vga`, `scaler=none`, `output=surface`,
`cycles=fixed 20000`, against the Forgotten Realms Archives Collection Two
copy of `POOLRAD`. What would move them is a different `machine=`, a
different scaler, or a different release of the game -- not a different host,
since `output=surface` with `scaler=none` is the VGA framebuffer pixel for
pixel.

## `ink` cannot read a combat bar, and read every one of them the same

This is the defect the first driven fight found, and it is the reason
`Screen.glyphs` exists.

`Screen.ink` calls a pixel lit when its three channels sum over 120. That
works on the world and camp screens, whose paper is black. **The combat
screen's paper is `#555555`**, which sums to 255 -- so every pixel of the bar
strip is "lit", and every bar drawn on that screen hashes to the sha1 of 2240
ones, `02d05064ee41da5f`. It is not a bar at all.

Two entries went into the first table that way, and neither carried any
information about the words above it:

| what was recorded | what the number actually is |
|---|---|
| `02d05064ee41da5f` as `MOVE VIEW AIM USE QUICK DONE` | the whole strip above the threshold |
| `f399fe870112b71a` as an empty bar | the whole strip below it |

What a player would never see but a driver did: **the driver pressed `QUICK`
at `CONTINUE BATTLE : YES NO`**, because that prompt is drawn on the same grey
paper and hashed to the same number as a character's command bar. `q` is not
`YES` and not `NO`, so nothing moved, and it pressed `q` again every second
and a half until its budget ran out with the party standing in a finished
fight.

`glyphs` measures the paper instead of assuming it -- whatever colour the
strip has most of -- and calls everything else a glyph. It keeps the property
`ink` was written for, since the world bar's white-then-green recolour leaves
the same pixels not-background; and on all six bars whose paper is black the
two agree exactly, which is why the movement and camp paths were left on
`ink`.

## What `QUICK` does

**`q` at a combat command bar resolves that character's turn, and the fight
goes on to the next combatant.** It is not a menu and it is not a whole-fight
switch that the driver presses once: the command bar comes back, for the next
character, and `q` is pressed again. What that means for the driver is the
good outcome anyway -- `fight()` is a loop of one keypress, with no need to
know where anybody stands.

The DOS first-letter hotkeys are what make this clean. `e`, `s` and `l`
already selected ENCAMP, SAVE and LOAD on the world and camp bars, `c` selects
COMBAT and `q` selects QUICK, and none of it needs the C64's highlight walk --
so the "did the walk land on DONE or QUICK" confound that made `#126 (The
emulator harness cannot drive a fight, so no conversion has ever been proven
in combat)` hard does not exist here.

## A command bar has no fixed digest, and that cost a run too

There is no one hash for "a character's turn". What the bar carries depends on
who is acting: a fighter is offered `MOVE VIEW AIM USE QUICK DONE`, and a
cleric `MOVE VIEW AIM USE CAST TURN QUICK DONE`. Those are different bars by
any whole-strip hash, and a driver holding a list of whole-strip hashes met
the cleric's, did not recognise it, and stood at it.

**The first seventeen characters are the same for every variant** --
`MOVE VIEW AIM USE`, the leftmost 136 pixels -- and they differ from every
other bar in the table above. So that is what a command bar is recognised by:
`PoolOfRadiance.COMBAT_BARS`, whose entries are `(width, digest, label)` and
are walked widest-first by `bar_kind` -- so a prefix is only ever reached after
the whole strip has failed to match,
because a bar caught mid-redraw is one flat colour and so has a flat prefix
too.

**`MOVE` dropping off once a character's movement is spent would move that
prefix**, and no run has seen that bar yet. `fight()` gives up after a minute
at a bar it does not know, with a screenshot named for the digest, rather than
pressing at it or standing there until its budget runs out -- so the day it
happens, the evidence needed to add the row is already on disk.

## Three things that are not true under DOSBox, each of which cost a run

**The encounter menu takes first letters and nothing else.** `q`, `Return`,
`Escape`, `e` and `n` were each pressed at `COMBAT WAIT FLEE ADVANCE`, eight
seconds apart, for two minutes: the bar never moved. `c` opened the fight at
once. A capture run whose ladder does not carry `c` sits at that menu until
its budget runs out, which is exactly what the first one did.

**The picture never holds still, so `settle()` must not be called in a
fight.** With nobody acting and no key pressed, 165 pixels of the treasure
screen moved between eight consecutive captures -- the chest and its contents
animate on their own. `Session.settle()` waits for two identical frames and
would wait for ever, and so would any rule of the form "the frame has not
changed for N seconds". This is the blink hazard the C64 side predicted, and
it is real; it is measured here rather than assumed.

**The command bar does not change when a turn passes.** Every character's turn
shows the same `MOVE VIEW AIM USE QUICK DONE`, so its ink is identical from
one turn to the next -- only the panel on the right names who is acting, and
the panel names monsters too. So a keypress in a fight cannot be confirmed by
effect on the bar at all. A ladder that waited for the bar to move before
advancing crawled at one useful keypress every forty seconds.

`fight()` therefore does not confirm a press; it **rate limits** one. It sends
one key, watches the bar for `dwell` seconds, and goes round whether it moved
or not. That is safe only because of the rule beside it: **a bar the driver
does not recognise is pressed at not at all**, so every key it sends lands on
a bar that carries it, and a repeat is at worst `QUICK` given twice to
successive characters. The C64 side measured the other policy: asking a bar
for a word that is not on it spins to the full timeout, 441 of 605 seconds of
one fight.

## The end of a fight is not the win message

There are five screens between the last blow and the map, and a driver that
stopped at any of them would leave the party standing at a prompt for ever:

1. `CONTINUE BATTLE : YES NO` -- `n`
2. `THE PARTY HAS WON.` with the experience share, and
   `PRESS <ENTER>/<RETURN> TO CONTINUE` -- `Return`
3. the treasure bar `VIEW TAKE POOL SHARE EXIT` -- `e` for EXIT
4. `THERE IS STILL TREASURE LEFT. DO YOU WANT TO GO BACK AND CLAIM YOUR
   TREASURE?` with `YES NO` -- `n`, which is the answer that matches having
   just exited
5. the world bar

Each of the last two was found by a run that stopped at it. `fight()` returns True only when the world
bar recorded at load time has come back **and held** -- one frame of it is not
enough, because the bar blanks and redraws between screens.

`EXIT` is what the driver presses at the treasure, never `TAKE`: the party's
items are not what any of this measures, and taking one would move a record
the diff reads.

## What three driven fights did

Slot J's level-one party, in the Slums, three consecutive wandering fights in
one session, `tools/dosfightrun.py fight --save J --rounds 3`. `fight()`
returned True on all three, and every one of them was fought: `save_game` to a
scratch slot either side, and the files read back.

| | steps walked to the encounter | experience | `$4ABB`, the Slums fight count |
|---|---|---|---|
| fight 1 | 9 | 48 -> 68 for four of the six | 3 -> 4 |
| fight 2 | 11 | 68 -> 81 | 4 -> 5 |
| fight 3 | 7 | 81 -> 94 | 5 -> 6 |

Experience rose in every fight, which is what says the party did the killing.
Hit points are reported and not cited: RHIANNON went to 0 in the first fight
and stayed there, earning nothing in the two after it, which is the clearest
illustration of why the field says nothing about who struck whom.

**The Slums encounter counter behaved exactly as `ECL14` says it should**:
`word($4ABB)` rose by one per fight, three times, never by two and never by
none. That confirms on DOS what was CONFIRMED on the C64 -- the same script,
the same increment -- and it is a second, independent "the fight ended" signal
beside the world bar coming back.

## What a fight moves in a character record

The union of every byte that differed either side of the three fights, in the
engine's **own** records, named by `goldbox/dos_layout.py`:

| field | offsets |
|---|---|
| `effect_chain` | `0x07F`, `0x081`, `0x082` |
| `experience` | `0x0AC` |
| `item_count` | `0x0C7` |
| `item_chain` | `0x0C8`-`0x0D7` |
| `hands_used` | `0x100` |
| `encumbrance` | `0x102` |
| `field_10c_10f` | `0x10C`, `0x10D`, `0x10F` |
| `roster_tail` | `0x113`, `0x117` |
| `hp_current` | `0x11B` |

Three of those -- `effect_chain`, `item_chain` and `hands_used` -- are entries
on `#69 (No WRITE_UNSOURCED zero has been tested during combat)`'s list, and
this is the first time any of them has been watched across a fight rather than
across a `VIEW` on the world map. It does not answer `#69 (No
WRITE_UNSOURCED zero has been tested during combat)`, because the party here
was the engine's own rather than a converted one; it says where that
comparison has to look.

## The quickfight bit is not at `0x10E`

`#114 (Drive a fight in DOSBox, so a converted save can be checked past
loading)`'s plan proposed DOS `0x10E` as the twin of the C64 roster's `+0x0C`
-- the flag `goldbox-bugs.md` bug 3 says QUICK sets and nothing ever clears --
by the -2 displacement in `docs/117-save-conversion.md`, PROBABLE on alignment
alone.

**It is refuted.** `QUICK` was pressed for every character of every one of the
three fights, and `0x10E` read `00` in all eighteen records afterwards. Its
neighbours `0x10C`, `0x10D` and `0x10F` all moved, so the record was being
written; that byte was not. Either the DOS port keeps no such persistent flag,
or it keeps it somewhere nobody has found.

## The save is seven files, and the one the harness watched is not the last

`save_game` waits for `SAVGAM<slot>.DAT` to change on disk, which is what
makes a save verified by effect rather than by sleeping. It is not enough on
its own: the six `CHRDAT<slot><n>.SAV` records are written **1 to 11
milliseconds after** it -- measured on both scratch slots of three runs -- so
a caller that read experience the moment `save_game` returned was racing the
game for it.

Nothing has lost that race, and eleven milliseconds is not a margin to rely
on. `save_game` now waits for the whole save directory to go quiet before it
reads anything back.
