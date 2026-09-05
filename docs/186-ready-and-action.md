# The combat icon's second pose: READY and ACTION

An icon is eighteen `CHARPIC00` screen codes and eighteen colours. Nine of each
draw the figure that stands on the combat floor;
`docs/174-combat-figures-in-the-running-game.md` proved those in the running
game and closed by saying the other nine had never been seen. This is where
they go, what the game calls them, and where a player looks at them. Taken for
`#184 (A converted combat icon's colours are proven in the game and its shapes
are not)`; the file-level side of the icon is `goldbox/icons.py`, and the tool
is `tools/iconswing.py`.

## The game's own words for the two poses

ENCAMP > ALTER > ICON draws four 3x3 figures under the labels `NEW` and `OLD`,
each pair headed **`READY`** and **`ACTION`**, with `ICON:PARTS COLOR SIZE EXIT`
on row 24. `NEW` is the icon being edited and `OLD` is the icon as it was, so a
player sees both poses of both, side by side, without a fight.

**So the first nine codes are the READY pose and the second nine are the ACTION
pose** -- the figure in the act of striking, its weapon arm extended. That is
the game's naming, read off its own screen, and it is what to call these in
prose and in an editor.

## Where the eighteen codes go

**`COM.PREP $122C` expands every icon before a fight.** It points `$07/$08` at
`$4BE0` -- `LDA #$E0 / STA $07`, `LDA #$4B / STA $08` -- points `$9E/$9F` at
`$9BE8`, sets a slot counter to 7, and per slot reads **eighteen** screen codes.
Each goes through `$1284`, which shifts the code left three times into a 16-bit
value, adds `$8C00` and copies eight bytes: `CHARPIC00` is staged at `$8C00`
when `COM.PREP` runs, so that is `CHARPIC00[code * 8]`. The eighteen colour
bytes are copied after them.

**The table it builds is at `$9BE8`: 18 glyphs of 8 bytes then 18 colour bytes,
162 bytes a slot, eight slots, ending at `$A0F7`.** Both poses of every icon in
the save are in it before the first command bar. CONFIRMED from the routine and
from the engine's own reads below.

| what | where |
|---|---|
| the icon, as saved | `$4BE0 + slot * 36`: 18 codes, then 18 colours |
| the READY glyphs, expanded | `$9BE8 + slot * 162 + 0`, 72 bytes |
| the ACTION glyphs, expanded | `$9BE8 + slot * 162 + 72`, 72 bytes |
| the 18 colours, copied | `$9BE8 + slot * 162 + 144` |

## What the engine reads, counted

VICE load checkpoints, armed before the encounter and counted for the whole
fight, on the six-different-icons disk `tools/iconpoke.py` writes.

| window | slots watched | loads each | when |
|---|---|---|---|
| `$4BE0 + slot * 36 + 0..8`, the READY codes | 0-5 | 9 | before the first command bar |
| `$4BE0 + slot * 36 + 9..17`, the ACTION codes | 0-5 | 9 | before the first command bar |

**Exactly one read of every byte of every icon, and not one more in 42 turns of
fighting**, in each of two fights. So a pose byte that changes during a fight
does not send the engine back to the save's icon table: it works from `$9BE8`.

The expanded table itself, read at every command bar of a 15-turn fight and
scored against the disk's own codes through `CHARPIC00`:

| compared | comparisons | equal |
|---|---|---|
| the first nine expanded glyphs against the save's codes 0-8 | 15 x 6 x 9 | 810 of 810 |
| the second nine against the save's codes 9-17 | 15 x 6 x 9 | 810 of 810 |
| the eighteen colours after them against the icon's own | 15 x 6 | 90 of 90 |

**A refuted hypothesis.** The pose byte's other value draws the READY figure
turned left to right (`docs/174`), and the obvious place to build a mirrored
copy is the ACTION block. The engine does not do that: the ACTION bitmaps were
still the icon's own at every bar, including bars where four of the six party
members carried pose byte 2.

## The ACTION pose is fetched once per turn, for whoever is acting

Checkpoints on `$9BE8 + slot * 162 + 72..143` fire on a frame nobody could
photograph. Over 15 turns they counted 768 loads, arriving in blocks of exactly
72 -- one whole pose -- and matched against the combatant the camera was centred
on, which is the one acting:

**10 of 12 turn transitions read the ACTION block of the character who had just
taken the turn**, attributed by the address the checkpoint sat on. The two that
named nobody are both the same character, whose block had been read 42 times --
a partial block -- before the first bar and not since.

So the ACTION pose is fetched while a character takes its turn and is gone by
the time the game asks for the next command. That is why no reading taken at a
command bar has ever caught it on the combat floor: 405 readings in `docs/174`
and 252 more here, all the READY pose or its mirror.

## What is proven, and where

| the nine | proven where | evidence |
|---|---|---|
| READY, codes 0-8 | the combat floor, mode byte 2 | 657 figure readings, 9 of 9 glyphs, exactly one of 32 candidates each |
| ACTION, codes 9-17 | the icon editor in camp, mode byte 9 | 4 blocks x 9 glyphs, exactly one of 24 candidates each, on two disks |
| both | the engine's expanded table | 1620 of 1620 glyph comparisons, 90 of 90 colour blocks |

The editor renumbers exactly as a fight does -- its four blocks were drawn from
codes `$60`, `$69`, `$72` and `$7B`, four runs of nine, and its character set is
at `$D000`, RAM under I/O, so it needs the `ram` bank like the combat one
(`#265 (The combat-icon glyph check reads VIC registers instead of the character
set, and half of it passes anyway)`). None of the icon's own codes is anywhere
on that screen, which is why a first pass searching for them found nothing.

On the converted disk every block matched all six slots at 9 of 9, colours
included, which is as far as attribution can go while the conversion writes one
icon into all six -- `#130 (A converted DOS party arrives with six identical
combat figures, not its own)`.

## What is not established

**How long the ACTION pose is on the combat floor, and what puts it there.** The
72 bytes are fetched; the destination has not been read at the moment of the
fetch. Catching it needs a capture raced from outside rather than a reading
taken when the game stops to ask for a command. Nothing about a conversion waits
on that: all eighteen codes are read, expanded correctly and drawn.

## Reproducing it

```sh
tools/iconpoke.py --disk work/issue184/SIX.D64          # six different figures
POR_HEADLESS=1 tools/iconswing.py --disk work/issue184/SIX.D64
POR_HEADLESS=1 tools/iconswing.py --disk work/issue184/SIX.D64 --camp
```

The first drives a fight with `Session.melee_turn`, so the party strikes rather
than passing, and counts the engine's reads of both poses at both levels. The
second takes the game to its own icon editor and scores every 3x3 block on the
screen against the save's icons.
