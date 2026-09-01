# Condition badges on the roster card

**Donald chose the icons and they are built.** Seven badges, all from
game-icons.net under CC BY 3.0, each verbatim from the artist's own SVG —
`#4 (Condition badges on the roster card)` carries his table and his wording.
What is below is the reasoning they were chosen against and the record of what
was measured; the shipped set is the first table.

## What ships

| badge | covers | glyph | artist | 13 px |
|---|---|---|---|---|
| dead or dying | hit points at 0 | `death-skull` | sbed | 1 piece, 103 |
| levels drained | record `0x0A1` | `oppression` | Lorc | 6 pieces, 63 |
| hasted | 39 | `running-ninja` | Darkzaitzev | 2 pieces, 27 |
| blessed | 1, 35 | `healing-shield` | Delapouite | 1 piece, 71 |
| warded | 8, 9, 17, 28, 41, 89 | `embrassed-energy` | Lorc | 4 pieces, 43 |
| invisible | 25 | `invisible` | Delapouite | **0 pieces, 0** |
| strengthened | 12, 38 | `strong` | Lorc | 1 piece, 55 |
| quickfight | roster `+0x0C` bit 7 | `sparkling-sabre` | Lorc | 2 pieces, 51 |

Quickfight is not a condition and keeps its own row; it is here because Donald
settled its glyph in the same breath, to stop two running figures landing on
one card.

**`invisible` draws nothing at 13 px.** 816 ink pixels at 128 px against
5,000–9,500 for the rest of the set: it is a fine-line drawing and the lines
fall below a pixel long before 13. Reported, not fixed — a replacement is
Donald's to choose, and `CLAUDE.md`'s Art section forbids nudging the artist's
geometry until it survives. `oppression`, `embrassed-energy`,
`running-ninja` and `sparkling-sabre` all come apart into two to six pieces at
13 px and are legible only as a general shape. The sheet is
`tools/iconsheet.py`, which now carries all eight.

**The measurement is the same rig the rest of this file uses** — ink is a pixel
at least half covered, pieces are 8-connected blobs — and it agrees pixel for
pixel with Qt's own SVG renderer reading the same `d`, at 13, 26 and 128 px,
for all eight. `tests/test_conditionbadges.py` keeps it that way.

**Every badged effect id is CONFIRMED in `goldbox/traits.py`.** Two groupings
this document once left open stay open, because their ids are PROBABLE: the
10' radius pair **45/46** could join *warded* and **49 Prayer** could join
*blessed*, and neither is decided here. `#142 (The party effects line is
computed every poll and shown nowhere)` is where they matter.

## Where the plan started

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

## The two collisions, and how they went

**A running figure cannot mean both quickfight and hasted at 13 px.** The
recommendation below was that hasted take `forward-fast` and quickfight keep
`person-running`. Donald settled it the other way: hasted is
`running-ninja` and **quickfight is `sparkling-sabre`** — *"For the quickfight
icon, use this one: Sparkling sabre"*. `person-running` is no longer drawn
anywhere.

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

## The sheet Donald decided from

All nineteen player-facing spell effects, whether or not they are worth badging.
`13 px` is pieces then ink for the recommendation, which was Font Awesome
throughout. **None of these recommendations was taken**: Donald replaced the
set with game-icons.net, and the last column says which badge each effect
ended up under. It is kept because it is the measurement record — the numbers
are what made the case that fifteen badges is worse than five.

| id | effect | recommended (not taken) | 13 px | alternative | badge it ended up under |
|---|---|---|---|---|---|
| 1 | Bless | `dove` | 1, 59 | `star` | blessed |
| 5 | Detect Magic | `magnifying-glass` | 1, 36 | `star` | — |
| 8 | Protection from Evil | `shield-halved` | 1, 52 | `circle-half-stroke` | warded |
| 9 | Protection from Good | `shield-halved` | 1, 52 | — none distinguishes it | warded |
| 10 | Resist Cold | `snowflake` | 1, 57 | `icicles` | — |
| 12 | Enlarge | `maximize` | 1, 61 | `arrows-up-down-left-right` | strengthened |
| 14 | Friends | `face-smile` | 1, 80 | `handshake` | — |
| 17 | Shield | `shield` | 1, 67 | `shield-halved` | warded |
| 19 | Find Traps | `triangle-exclamation` | 1, 56 | `magnifying-glass` | — |
| 20 | Resist Fire | `fire` | 1, 56 | `fire-flame-curved` | — |
| 24 | sees invisible | `glasses` | 1, 51 | `eye` (2 pieces — the iris) | — |
| 25 | invisible | `eye-slash` | 2, 56 | `ghost` (1, 62) | invisible |
| 28 | Mirror Image | `clone` | 2, 71 | `copy` | warded |
| 35 | allied Prayer | `place-of-worship` | 1, 66 | `church` | blessed |
| 37 | blinking | `right-left` | 2, 46 | `bolt` (1, 41) | — |
| 38 | extra strength | `dumbbell` | 1, 45 | `weight-hanging` | strengthened |
| 39 | hasted | `forward-fast` | 1, 75 | `gauge-high` | hasted |
| 41 | Prot. from Normal Missiles | `umbrella` | 1, 52 | `shield-halved` | warded |
| 89 | displaced | `circle-half-stroke` | 1, 70 | `object-ungroup` (2 pieces) | warded |

Three recommendations are two-piece and deliberately so, by the
`person-running` amendment: `eye-slash`'s slash is a separate bar and is the
whole meaning, `clone`'s second square is the mirror image, `right-left`'s two
arrows are the blink. Two carry a caution at 26 px rather than 13 — `umbrella`
and `handshake` each split into two pieces there — which matters only if a badge
is ever drawn on the map, and it is not.

## Five new badges, not nineteen — and why the groups are what they are

A card with fifteen badges is worse than a card with three: the point of a badge
is that a glance finds the one character who is in trouble. So badge only what
**changes what the player should do this turn**, and group the rest. This is
the grouping the built set uses; only the glyphs changed.

Everything else — Detect Magic, Find Traps, Resist Cold, Resist Fire, Friends,
sees invisible, blinking — is real, is nameable, and is not badged. They are
situational or they are the state of a spell the player just cast deliberately
and has not forgotten about.

Grouping is what makes *warded* worth having: six ids, one glyph, and the
tooltip names which of them is up. It also disposes of the Mirror Image /
displaced collision without choosing between them.

## What was built

* **`automap/live.py`** carries `CONDITION_BADGES`, the table above as
  `(glyph, ids)`, and `Character.conditions` reads it against the effect ids
  already filtered to that character by `characters()`. No new decoding was
  needed: `active_effects` had read the four arrays since
  `docs/133-active-effects.md`.
* **`ui/icons.py`** gained `GAME_ICONS`, the eight paths verbatim, and
  `ARTISTS` beside them so an attribution file can be generated from what
  ships. game-icons.net draws on a **512** box where Font Awesome draws on 640,
  so `box(name)` was added and `ui/iconpaint.py` and `automap/render.py` scale
  by it; nothing was rescaled into a common box on the way in, because a
  rescaled path can no longer be diffed against the artist's file.
* **`commands()` grew into a full path parser** — relative forms, `H`/`V`,
  smooth cubics and elliptical arcs, none of which Font Awesome's `svgs-full`
  emits and all of which these artists use. It grew rather than the icons being
  redrawn into a simpler `d`: redrawing somebody's art is the one thing
  `CLAUDE.md`'s Art section forbids. `Q` and `T` are raised rather than guessed
  at.
* **The card did not get any taller.** `IconRow` is a fixed 13 high and grows
  only sideways, so a card with all seven badges lit has the same
  `sizeHint` and `minimumSizeHint` height as a bare one — 58 and 43 here, and
  the window's own minimum stayed 477. That matters because
  `#135 (The automapper's roster column does not scroll, so a full party puts a
  944px floor under the window)` is open, and eight cards each gaining a row is
  exactly the shape that would have made it worse.

## What this does not do

* **No duration on the badge.** Not until bits 6–7 of the duration byte are
  decoded. A number over an unnamed unit is worse than no number.
* **No badge for a trait-slot effect.** Nothing a player character carries at
  `0x0AD` in any save we hold is worth a badge: the seeds are racial (107, 124)
  and the passive item powers are already visible on the item.
* **No `THIRD_PARTY_LICENSES.md`.** `ui.icons.ARTISTS` is the truth it should
  be generated from; writing it is `#4 (Condition badges on the roster card)`'s
  fourth piece and waits on the Note-icon decision, since the file has to list
  exactly what ships.
* **Nothing measured in the running game.** The suite runs offscreen against
  synthesised effect arrays. No save this project holds has a spell running on
  a character, so the only badges a live poll has ever lit are the two the record
  carries — `P3-EFFECTS.D64` would have shown all five and went with `work/`
  (#136).
