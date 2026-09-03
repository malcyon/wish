# Condition badges

**Donald chose the icons and they are built.** Nine badges, all from
game-icons.net under CC BY 3.0, each verbatim from the artist's own SVG —
`#4 (Condition badges on the roster card)` carries his first table and his
wording, and `#142 (The party effects line is computed every poll and shown
nowhere)` the two glyphs and the two groupings that finished it. What is below
is the reasoning they were chosen against and the record of what was measured;
the shipped set is the first table.

**The same badge is drawn in two places** — on a roster card for a spell that
landed on one character, and on the automapper's bottom strip for one that
landed on the whole party. `automap/live.py`'s `badges()` is the single
function both go through, so the same spell cannot become two pictures.

## What ships

| badge | covers | glyph | artist | 13 px |
|---|---|---|---|---|
| dead or dying | hit points at 0 | `death-skull` | sbed | 1 piece, 103 |
| levels drained | record `0x0A1` | `oppression` | Lorc | 6 pieces, 63 |
| hasted | 39 | `running-ninja` | Darkzaitzev | 2 pieces, 27 |
| blessed | 1, 35, 49 | `healing-shield` | Delapouite | 1 piece, 71 |
| warded | 8, 9, 17, 28, 41, 45, 46, 89 | `embrassed-energy` | Lorc | 4 pieces, 43 |
| invisible | 25 | `eyelashes` | Delapouite | see below |
| strengthened | 12, 38 | `strong` | Lorc | 1 piece, 55 |
| silenced | 21 | `mute` | Delapouite | 1 piece, 85 |
| slowed | 42 | `snail` | Lorc | 2 pieces, 66 |
| quickfight | roster `+0x0C` bit 7 | `sparkling-sabre` | Lorc | 2 pieces, 51 |

Quickfight is not a condition and keeps its own row; it is here because Donald
settled its glyph in the same breath, to stop two running figures landing on
one card.

`mute` is the second-solidest glyph in the set — one piece and 85 ink at 13 px,
behind only `death-skull` — but what survives is the silhouette and not the
subject: magnified, it reads as a shape rather than legibly as a silenced
face. `snail`'s shell is unmistakable at 13 px. The numbers come from
`tools/inkcount.py` and the pictures from `tools/iconsheet.py`.

**`invisible` drew nothing at 13 px, and was replaced.** 816 ink pixels at
128 px against 5,000–9,500 for the rest of the set: it was a **dashed**
outline of a person, and the dashes fell below a pixel long before 13 —
on the card it was a pale smudge beside seven solid glyphs, not a badge.
Donald chose `eyelashes` (Delapouite) in its place — *"how about this one for
invisibility?"* — and it reads as a closed eye. `oppression`,
`embrassed-energy`, `running-ninja` and `sparkling-sabre` all come apart into
two to six pieces at 13 px and are legible only as a general shape. The sheet
is `tools/iconsheet.py`, which carries all ten, and a magnified render is
`work/eyelashes-13px-x6.png` (lost with `work/` — `#136 (Thirty-two cited
write-ups are gone, because the knowledge base pointed into gitignored
scratch)`; re-render it with
`tools/iconsheet.py`).

**`eyelashes` is a genuine improvement, and it is worth saying by how much
depending on how you count.** Counting any pixel the antialiased fill touches
at all, it is 81 ink pixels in one connected piece — comparable to
`running-ninja`'s 67 and nowhere near `invisible`'s 55 by the same loose
count. Counting the way the rest of this table does — a pixel at least half
covered, pieces 8-connected — it comes out at 3 pieces and 16 ink pixels,
because eyelashes is itself drawn in thin strokes and much of a lash's length
does not reach half coverage at this size. That is the same failure mode
that killed `invisible`, to a lesser degree: a fine line is exactly what a
50%-coverage threshold is worst at counting, even where a human eye reads the
antialiased blur as one continuous stroke. The picture is the fairer judge
here than either count — see it before choosing another glyph.

**The measurement is the same rig the rest of this file uses** — ink is a pixel
at least half covered, pieces are 8-connected blobs — and it agrees pixel for
pixel with Qt's own SVG renderer reading the same `d`, at 13, 26, 128 and
512 px, for all ten. `tests/test_conditionbadges.py` keeps it that way, and
the rig is `tools/inkcount.py`, which reproduces every number in the table
above.

**Five badged effect ids are PROBABLE rather than CONFIRMED, and that is
deliberate.** The two groupings this document used to leave open are settled:
the 10' radius pair **45/46** joins *warded* and **49 Prayer** joins *blessed*,
both on Donald's ruling of 2026-09-01 — *"I do agree that protection from evil
and good 10ft radius fits well with embraced energy."* **21 Silence 15' Radius**
and **42 slowed** took `mute` and `snail` in the same breath.

What changed the reasoning is not the grades — all five are still PROBABLE —
but where the badges are drawn. Every one of the five is a spell that lands on
the **whole party**, and none of the five has been watched landing there. No
save this project holds carries a party-wide effect: the only effect in any
fixture is id 73 with owner `0x00`, which is a character. Nor can one be cast
by any party on any disk here — **the highest cleric is level 2**, and the
lowest of the five, 21 Silence 15' Radius, is a level 3 cleric's.
`automap/live.py`'s `PROBABLE_BADGED` is the list of the five, and the test
refuses a sixth: a PROBABLE id gets a picture only because somebody chose it.

**The argument that used to be here was that the row would be permanently
empty without them, and it is no longer true.** Two spells have since been
cast in the running game on `#142 (The party effects line is computed every
poll and shown nowhere)`, and both light the row off ids that were already
CONFIRMED: **1 Bless** and **35 `under an allied Prayer`**. The five stay
because Donald chose them and because an id with no glyph is drawn nowhere,
not because the row needs them to have anything to show.

**What counts as "on the party" is not the owner byte alone.** Bless writes one
row per character, each owner byte holding that character's own slot and no
`$FF` row at all; Prayer writes one row with owner `$FF` and nothing per
character. So the row draws the union: an `$FF` owner byte, or an effect every
standing character is carrying. A card and the row still share `badges()`, so
Bless is the same shield either way.

**Casting Prayer did not promote 49.** What it writes is **35**, which was
already CONFIRMED and already in the *blessed* row — so the shield was the
right picture, and 49 remains a name nobody has watched the game write.
Silence, 15' Radius cast outside a fight wrote no effect row at all, so 21 is
unwatched too. And **45 and 46 cannot come from a cleric in this title at
all**: with a level 5 cleric the 3rd-level book is ANIMATE DEAD, CURE
BLINDNESS, CAUSE BLINDNESS, CURE DISEASE, CAUSE DISEASE, DISPEL MAGIC, PRAYER,
REMOVE CURSE, BESTOW CURSE, and the only Protection from Evil and Protection
from Good in it are the single-target 1st-level pair. Whether a magic-user
reaches the 10' radius versions is untested.

**A party effect no badge covers is drawn nowhere**, and that is the honest
consequence of a set graded from the spell table rather than from anything
watched. `BottomStrip` puts such an id in the debug log — once per id, not five
times a second — so whoever comes to choose a glyph for it has a trail.

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
* **`ui/icons.py`** gained `GAME_ICONS`, the paths verbatim — eight then,
  ten since `mute` and `snail` — and
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
  only sideways, so a card with every badge lit has the same
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

## Which title's ids these are

**Pool of Radiance's, and Curse of the Azure Bonds shares them.** Curse seeds
every racial trait code Pool of Radiance does, on the race each name demands
(`goldbox/traits.py`, `#186 (The character sheet gives a Silver Blades elf a
Pool of Radiance ability)`), so one table serves both — and a title nobody has
read gets the same one, which is what `traits.for_game` already does.

**Secret of the Silver Blades draws no badges at all.** Sixteen of the
seventeen ids in the table above are unnamed in
`goldbox/traits.py:NAMES_SILVER_BLADES`; only 45 is established, and it is
what `GEN $0FF0` writes for a paladin. Drawing a running ninja for effect 39
on that title would be a picture asserting "hasted" over a tooltip reading
`Trait 39` — an inferred meaning in front of a player, which is the fault
`#196 (The automapper's condition badges name a Silver Blades trait with Pool
of Radiance's meaning)` was filed for. Which codes earn a glyph is per title
just as much as what the glyph is called, so `automap/live.py:BADGE_TABLES`
gives Silver Blades an empty set rather than a guessed one.

Nothing is hidden by that: `Snapshot.unbadged_party_effects` is every party
effect no glyph covers, and `automap/panel.py` puts them in the debug log —
which on Silver Blades is all of them, and is the honest amount the program
can say.

**What would fill the set in**: a Silver Blades save taken with spells
running, read the way `P3-EFFECTS.D64` was for Pool of Radiance — 26 spells
cast, each naming the code it had just written, seventeen ids promoted at once
(`docs/90-specimens.md`).
