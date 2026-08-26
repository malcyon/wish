# Condition badges on the roster card — a plan

**Blocked on Donald: he picks the icons.** Nothing here is built and nothing is
added to `ui/icons.py` until the sheet at the foot of this file comes back with
a column filled in.

The roster card badges two conditions today — dead or dying, and levels drained.
`docs/109-icon-choices.md` recorded a third row as **blocked**: "roster —
poisoned, paralysed — the effect codes are not decoded". That is out of date.
The codes are decoded, 66 of the 129 names in `goldbox/traits.py` are CONFIRMED, and
the question is no longer *what can we show* but *what is worth showing*.

## Three findings, and they narrow the choosing

**1. Ids 64 and up are the monster side of the table and cannot be true of a
player character.** 64–70 are the graded melee poison and paralysis families,
carried by SNAKE, POISONOUS FROG, THRI-KREEN and GHOUL; 73–88 are attack forms
— rear claw rake, blood drain, petrifying gaze, breath weapons; 90–127 are
monster defences — regeneration, immunities, half damage from a damage type. A
handler for one of these reads fields a `MON*` record carries and a player
record does not: `attack_forms` at `0x0D9` is `02 00 01 00 02 00 00 00` in every
player character we hold. CONFIRMED, from the carrier census in `goldbox/traits.py`.

**One exception, and it is a real one: 89, displaced.** TYRANITHRAXUS carries it
*and so does the player's own CLOAK OF DISPLACEMENT*, as a passive item power
(`+14` = 89, `+15` = `$85`). A player character genuinely can be displaced.

Level drain, 85 and 86, is the other apparent exception and is not one: it is
something done *to* a character, but the resulting state lives in its own pair
at `0x0A1`/`0x0A2` and is what the existing drained badge already reads.

So the candidate set is the spell effects, 1–63, plus 89. Nineteen of those have
a name good enough to badge; the sheet below is those nineteen.

**2. A badge must read the four `SAVEDGAME0` arrays, not the trait slots.** This
is the load-bearing one and it is stronger than "the traits carry no duration".

`P3-EFFECTS.D64` was saved with **twenty-six spells running** and every
character's ten trait slots at `0x0AD` came out byte-identical to how they went
in — elf seed 107, half-elf seed 124, nothing else (`docs/133-active-effects.md`).
A cast spell does not reach `0x0AD` at all. A badge sourced from the trait block
would therefore be **blank on the one save in the project where every badge
should have been lit**.

The list that does move is the save's four 64-entry arrays — `$4900` id,
`$4940` owner, `$4980` duration, `$4B80` magnitude. Read the id array, filter on
the owner byte matching this character's slot, and name the id through
`goldbox/traits.py`. `LIBRARY $4028` reads the arrays first and falls back to the
character's own slots, so one code table serves both and nothing new is needed
to name them.

**The honest limit, stated plainly: the badge can say *running*, not *how
long*.** The duration byte is a count in bits 0–5 and a **unit in bits 6–7 that
is not decoded**, so "8" on a badge could be 8 rounds, turns or hours. Show the
name and no number until `docs/133-active-effects.md`'s one experiment — cast,
save, camp a known interval, save, difference the arrays — has been run. A
trait-sourced badge, if one is ever wanted for a passive item power, cannot say
even that much: a trait slot has no duration field and never expires.

**3. The size is 13 px** — `panel.ICON_SIZE`, the roster card, the one place in
the program still drawing at 13. So the rule in `docs/109-icon-choices.md`
binds: **one connected silhouette, every feature about 64 units of the 640 box or
larger**, with the amendment `person-running` earned — *unexpected* separation is
the failure, and a glyph whose parts are what the thing looks like passes anyway.

## The two collisions, resolved

**`person-running` is quickfight's.** It is on the roster card already, at the
same 13 px, so hasted cannot have it. Hasted takes **`forward-fast`** — 75 px of
ink at 13, one piece, the densest candidate measured and the one that reads as
speed without reading as a person.

**Mirror Image (28) and displaced (89) both want a doubled figure**, and only
one of them can have it. They are also the same idea to a player — *the blow
misses because you are not where you look*. The recommendation is that neither
gets a doubled figure and both fold into one **warded** badge with the defensive
group. If Donald wants them apart: `clone` to Mirror Image, where two offset
squares are literally the spell, and `circle-half-stroke` to displaced.

## Measured, not judged by name

Every glyph below was rasterised from `svgs-full/` at 13 px and counted, ink
being a pixel at least half covered. The rig reproduces this project's published
numbers exactly — `gem` regular at 13 gives 36 px, one piece, holes 16/3/2, and
`hat-wizard` gives two pieces of 28 and 18.

**What Font Awesome Free does not have**, said once so nobody re-searches it:

* **no evil/good pair.** Nothing distinguishes Protection from Evil (8) from
  Protection from Good (9) at any size. Either they share a glyph and the
  tooltip says which, or they fold into the warded badge.
* **nothing for poisoned.** `skull-crossbones` comes apart at 13 and a skull
  already means dead on this card. Moot for now — 55 is PROBABLE, has no C64
  carrier and cannot be promoted by looking.
* **the pious glyphs mostly fail.** `hands-praying` is two blobs of 34 (it also
  reads as leaves — `docs/109`), `hand-sparkles` is three pieces,
  `wand-magic-sparkles` five.

Others measured and rejected outright: `expand` (4 pieces), `binoculars` (5),
`land-mine-on` (4), `arrow-up-right-dots` (11), `wind` (3), `shuffle` (3),
`users` (4), `user-group` (3), `hand-fist` (2), `sun` (2),
`up-right-and-down-left-from-center` (2).

## The decision sheet

All nineteen player-facing spell effects, whether or not they are worth badging.
`13 px` is pieces then ink for the recommendation. **Donald's column is blank.**

| id | effect | recommended | 13 px | alternative | Donald |
|---|---|---|---|---|---|
| 1 | Bless | `dove` | 1, 59 | `star` | |
| 5 | Detect Magic | `magnifying-glass` | 1, 36 | `star` | |
| 8 | Protection from Evil | `shield-halved` | 1, 52 | `circle-half-stroke` | |
| 9 | Protection from Good | `shield-halved` | 1, 52 | — none distinguishes it | |
| 10 | Resist Cold | `snowflake` | 1, 57 | `icicles` | |
| 12 | Enlarge | `maximize` | 1, 61 | `arrows-up-down-left-right` | |
| 14 | Friends | `face-smile` | 1, 80 | `handshake` | |
| 17 | Shield | `shield` | 1, 67 | `shield-halved` | |
| 19 | Find Traps | `triangle-exclamation` | 1, 56 | `magnifying-glass` | |
| 20 | Resist Fire | `fire` | 1, 56 | `fire-flame-curved` | |
| 24 | sees invisible | `glasses` | 1, 51 | `eye` (2 pieces — the iris) | |
| 25 | invisible | `eye-slash` | 2, 56 | `ghost` (1, 62) | |
| 28 | Mirror Image | `clone` | 2, 71 | `copy` | |
| 35 | allied Prayer | `place-of-worship` | 1, 66 | `church` | |
| 37 | blinking | `right-left` | 2, 46 | `bolt` (1, 41) | |
| 38 | extra strength | `dumbbell` | 1, 45 | `weight-hanging` | |
| 39 | hasted | `forward-fast` | 1, 75 | `gauge-high` | |
| 41 | Prot. from Normal Missiles | `umbrella` | 1, 52 | `shield-halved` | |
| 89 | displaced | `circle-half-stroke` | 1, 70 | `object-ungroup` (2 pieces) | |

Three recommendations are two-piece and deliberately so, by the
`person-running` amendment: `eye-slash`'s slash is a separate bar and is the
whole meaning, `clone`'s second square is the mirror image, `right-left`'s two
arrows are the blink. Two carry a caution at 26 px rather than 13 — `umbrella`
and `handshake` each split into two pieces there — which matters only if a badge
is ever drawn on the map, and it is not.

## The default set — five new badges, not nineteen

A card with fifteen badges is worse than a card with three: the point of a badge
is that a glance finds the one character who is in trouble. So badge only what
**changes what the player should do this turn**, and group the rest.

| badge | covers | glyph |
|---|---|---|
| dead or dying | — | `skull` — **already built** |
| levels drained | — | down arrow — **already built** |
| **hasted** | 39 | `forward-fast` |
| **blessed** | 1, 35 | `dove` |
| **warded** | 8, 9, 17, 28, 41, 89 | `shield-halved` |
| **invisible** | 25 | `eye-slash` |
| **strengthened** | 12, 38 | `dumbbell` |

Everything else — Detect Magic, Find Traps, Resist Cold, Resist Fire, Friends,
sees invisible, blinking — is real, is nameable, and goes in the card's tooltip
as text rather than on its face. They are situational or they are the state of
a spell the player just cast deliberately and has not forgotten about.

Grouping is what makes *warded* worth having: six ids, one glyph, and the
tooltip lists which. It also disposes of the Mirror Image / displaced collision
without choosing between them.

## The work, in order

1. **`goldbox/effects.py`**, per `docs/133-active-effects.md`: the four array
   addresses, the `Effect` record, the owner encoding. Transport-free, in `goldbox/`
   because `editor/` may not import `automap/` and `tests/test_wish.py` greps
   the source to enforce it. This is a prerequisite shared with the effects
   editor and should be built once.
2. **`conditions` reads the arrays**, filtered by owner, and its docstring stops
   saying a poisoned icon would be an invented mapping. It would not be — 66 of
   129 names are CONFIRMED and the two lists share one namespace.
3. **The icons**, once Donald has picked: added to `ui/icons.py` verbatim from
   `svgs-full/solid/`, never redrawn, never nudged to fit 13 px. If a chosen
   glyph does not survive, the answer is a different glyph — `CLAUDE.md`, Art.
4. **A test per badge at 13 px**, the way `test_the_hood_keeps_its_face` pins
   `hood`: pieces and ink, so a Font Awesome upgrade that redraws a path fails
   the build instead of shipping mush.

## What this plan does not do

* **No duration on the badge.** Not until bits 6–7 of the duration byte are
  decoded. A number over an unnamed unit is worse than no number.
* **No badge for a trait-slot effect.** Nothing a player character carries at
  `0x0AD` in any save we hold is worth a badge: the seeds are racial (107, 124)
  and the passive item powers are already visible on the item.
* **No icon added to `ui/icons.py` by this plan.** That file belongs to P77 and
  to whoever is holding it; the choosing comes first.
