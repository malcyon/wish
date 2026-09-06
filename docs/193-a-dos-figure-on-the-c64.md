# A DOS character's combat figure, on the C64

DOS keeps a character's combat figure as a body, a head, a size and six colour
pairs. The C64 keeps eighteen screen codes and eighteen colours out of its own
character set. Neither side stores the other's, and the two sets of art are
different drawings of the same vocabulary — an archer, a flail, a mace with a
round head, a robed caster. This is what each side holds, how one becomes the
other, and what a converted party looked like in a fight.

Taken for `#130 (A converted DOS party arrives with six identical combat
figures, not its own)`. The destination end is
`docs/186-ready-and-action.md` and `docs/174-combat-figures-in-the-running-game.md`;
the code is `goldbox/iconparts.py`, the table is `tools/iconproposal.yaml` and
the tools are `tools/dosfigures.py`, `tools/dosiconstage.py` and
`tools/dosmixedicon.py`.

## What the DOS record holds, per character

| offset | field | what | range seen |
|---|---|---|---|
| `0x0BD` | `icon_head` | index into `CHEAD.DAX` | 0-13 |
| `0x0BE` | `icon_body` | index into `CBODY.DAX` | 0-31 |
| `0x0C0` | `size` | 1 small, 2 medium — picks `CHEADS`/`CBODYS` or `CHEADT`/`CBODYT` | 1, 2 |
| `0x0C1`-`0x0C6` | `icon_colours` | six pairs of 4-bit EGA indices, low nibble the main colour | see below |
| `0x06C` | `icon_dimension` | the combat footprint, 1 for every player character | 1 |

**It varies across a party — CONFIRMED, 33 of 46 parties.** Every `.SAV` and
`.CHA` reachable on this machine was read: 303 records that parse as a Gold Box
character record, grouped into the 46 six-or-seven character parties they
belong to.

| | parties | what |
|---|---|---|
| the head/body pair differs within the party | 33 | ordinary played parties across all six titles |
| all six the same | 13 | 8 are parties **this project** wrote or rolled, 5 are `Default files/Saves` sets |

So a real DOS party names six different figures and the conversion had six
different figures to write. That is what makes this a defect rather than a
description of the source.

**Our own clean party is not one of them, and that matters.**
`WISH-SPEC-por-party-l1` — the six characters
`#249 (Build a DOS party from creation and level it ourselves, so DOS
measurements rest on records we watched being written)` rolled in the game's
own creation screens — holds `icon_head` 0 and `icon_body` 0 for all six,
because the driver never entered the creation screens' icon step. Converting it
would produce six identical figures **correctly**, and no run over it could
tell the fix from the defect. `tools/dosiconstage.py` exists for that reason:
it writes six deliberately different figures into a staged copy, which is
editing an *input* and then watching the game compute from it.

The colour set `91 A2 B3 C4 E6 F7` is what 42 of the 54 shipped records across
the four titles carry; the six that differ are the six played Pools of Darkness
characters.

## What each side can draw, in numbers

Donald asked the two questions this table answers — differing amounts of
colours, differing amounts of pixels.

| | DOS | C64 |
|---|---|---|
| pixels a pose | 24 x 24, one colour each | 24 x 24 in three 8-wide multicolour cells, so 12 x 24 double-wide pixels |
| colours a cell | — | 4: three shared, one the cell's own |
| colours the character chooses | 6 parts x 2 (main, highlight) out of EGA's 16 | 7 parts x 1 out of the VIC-II's low three bits, so 8 |
| the parts | body, arm, leg, hair-and-face, shield, weapon | WEAPON BODY CAP HAIR SHIELD ARM LEG |
| fixed by the game | outline, and the hat or plume (pixel values 5 and 13, which the recolour lookup never touches, so a DOS hat is always magenta) | face light red, outline black, floor dark grey, all set by `COM.PREP` |
| options | 14 heads and 32 bodies, at each of two sizes | 28 small weapons, 14 small heads, 35 large weapons, 23 large heads |

## The mapping is a look, not a table anybody can derive

Rendering every option of both ports to a 24x24 ink mask and scoring every
pairing with a Jaccard overlap over ±2 rows and ±1 column, the same index is
the best match 1 of 32 times for small bodies and 2 of 32 for large ones —
chance, and two of those are ties the sort decides. The highest overlap of all
1120 large body-to-weapon pairings is **0.782**, between the two ports' plain
unarmed figures, where the same art rendered twice would be above 0.95. So the
C64's figures are a redrawing rather than the DOS bitmaps at another
resolution, and best-matching is not a bijection: 21 of the 35 C64 large
weapons are nobody's best match while weapon 11 wins seven. `tools/iconcorrespond.py`
is the measurement.

**So the 46 rows are a judgement, and they live in `tools/iconproposal.yaml`,
which Donald edits by hand.** `tools/iconproposal.py` draws them;
`goldbox.iconparts.dos_icon_tables` reads the same file at run time, so his
next edit reaches the conversion with no regeneration step and nothing to keep
in step. The file is outside the package and a frozen build does not carry it,
which is `#315 (A frozen Wish cannot convert a combat figure, because the
table it needs lives outside the package)`.

## Composing the icon

`IconParts.dos_icon(head, body, size, colours)` applies the C64 weapon option
the table names for `icon_body`, then the head option it names for
`icon_head`, exactly as the game's own `ENCAMP > ALTER > ICON` menu applies
them — including the rule at `$B209` that stops a cap or hair glyph painting
over a head cell the weapon already filled, and the rule at `$B26F`/`$B29B`
that preserves cells 0, 1, 9 and 10 when the weapon changes.

**All 896 combinations — 32 bodies x 14 heads x two sizes — compose a shape the
menu can reach.** Checked against `IconParts.legal_shapes()`, which is every
shape any sequence of menu choices produces, in `tests/test_dosicon.py`.

### A small character sometimes wears a large option

The C64 offers a small character 28 weapons and 14 heads against a large one's
35 and 23, and the table lands past the small lists in nine places:

| | rows | DOS options |
|---|---|---|
| weapon rows only the large list holds | 6 of 32 | bodies 16, 27, 28, 29, 30, 31 — the crossbow and the five robed figures |
| head rows only the large list holds | 3 of 14 | heads 2, 8, 10 — the plumed helmet, the long hair down the back and the banded helmet |

Both counts are read out of the table rather than written down here, by
`tools/dosmixedicon.py`, so they follow Donald's next edit instead of going
stale beside it. The rows above are the table as he committed it on
2026-09-05.

Those are composed from the large list, which is a mixed icon and one the
game's own menus reach: `SPELLN64` has no store to the record's size byte, so
choosing SIZE only switches which list this session offers, and HOGARTH on the
player's own disks carries such a mix already. **Every head option starts at
cell 1 in both lists**, so a large head on a small figure sits where a head
always sits; what differs between the lists is the art, a small head being
drawn lower in its cell to meet a shorter body.

`tools/dosfigures.py --mixed-png` draws all nine of those on a small figure,
with four small options above them to compare against, which is the picture to
judge them on. They read as complete figures; whether they are the right ones
is Donald's, and the code uses whatever `tools/iconproposal.yaml` says.

**No Pool of Radiance party on this machine wears one, so one had to be
staged.** `tools/dosmixedicon.py --census` read every `.SAV` and `.CHA` under
`~/dos_por_play/SAVE`, `~/wish-specimens/por-dos` and `~/Downloads/fr-archives`:
**2 of 372 records** are small characters already on a large-only row, and both
are the same *Pools of Darkness* character, ABAGAIL, in two copies of one
party. So the question cannot be settled by finding a specimen. `--stage`
copies a party out and rewrites the `icon_head` and `icon_body` of its small
characters only, leaving `size` and the colours alone.

**Staged onto slot J's two small characters and read in the game's own icon
editor, both compose and both draw.** `tools/iconswing.py --camp --who N` takes
the party to `ENCAMP > ALTER > ICON`, where the game draws four 3x3 figures
under `NEW`/`OLD` and `READY`/`ACTION`:

| who | DOS head, body | C64 weapon, head | the editor's four blocks |
|---|---|---|---|
| THRENDER GRONE | 2, 16 | 28, 21 — both large-only | all four exactly slot 5, poses 0 and 1, 9 of 9 glyphs, colours matching |
| PHINEAS | 8, 27 | 34, 17 — both large-only | all four exactly slot 0, poses 0 and 1, 9 of 9 glyphs, colours matching |

Eight blocks, every one naming exactly one of sixteen candidates. `work/`'s
`i130mix0-zoom.png` and `i130mix5-zoom.png` are the two figures at six times,
cropped off the screen rather than drawn from a sheet: a purple hood over a
pink face with a crossbow held level, and a robed figure with long hair and its
arms out. **In both the head sits on the shoulders and nothing floats, is cut
off or overlaps.** A mixed figure reads as a slightly tall-headed one rather
than a broken one.

### The colours

The low nibble of each pair, in the order the engine's own recolour lookup uses
them — `GAME.OVR:0x1E55C` reads the table at `ds:0x3CF5`, `0A 01 02 03 04 06
07`, so `0x0C1` is the body, `0x0C2` the arm, `0x0C3` the leg, `0x0C4` the hair
and face, `0x0C5` the shield and `0x0C6` the weapon.

**One of the two nibbles has to be dropped**, and that is the machine rather
than an omission: a C64 multicolour cell owns one colour, its low three bits,
and the other three are shared by the whole screen. Which one to keep is the
question the next section measures. The C64's CAP has no DOS pair at all, so it
takes purple, which is where a DOS hat's fixed magenta lands.

Four of the sixteen EGA colours are not sent to their nearest by RGB, because
the C64's eight contain no brown and no grey: brown becomes yellow, light grey
white, dark grey black and light red red. That is in the YAML with the rest.

**Those two non-nearest rows are what makes the choice of nibble invisible for
most characters.** The shipped set `91 A2 B3 C4 E6 F7` pairs blue with light
blue, green with light green, cyan with light cyan, red with light red, brown
with yellow and light grey with white -- and the table sends both halves of
every one of those six pairs to the same C64 colour. Over the 296 records
censused, 222 have no pair whose two nibbles land on different C64 colours.

**For the other 74 the low nibble is the minority colour on two parts, and that
is a decision rather than a defect.** Counting every pixel of every option
(`tools/dosnibbles.py`):

| part | main pixels | highlight pixels | highlight share |
|---|---|---|---|
| body | 2095 | 785 | 27% |
| arm | 1478 | 1238 | 46% |
| leg | 1358 | 2005 | 60% |
| hair | 576 | 1661 | 74% |
| shield | 260 | 650 | 71% |
| weapon | 475 | 469 | 50% |

Per option the two extremes are unanimous: the highlight covers more of the leg
in 32 of the 32 bodies and more of the shield in 8 of the 8 that carry one.
Hair's 74% is not a case for the highlight -- value 12 is the face, which the
C64 draws in fixed light red from `$D022`. So a repainted character's shield and
legs arrive in his DOS *rim* colour rather than his DOS *field* colour. MAGNUS
on the player's own DOS disks carries shield pair `E8`, drawn yellow with a dark
rim in DOS, and converts to a black shield.

## What a converted party looks like in a fight

Two runs, on two parties, and the second is the one taken against Donald's
final table.

### Against the final table: six figures, and the engine drew all six

Donald finished the table by hand on 2026-09-05 (`ee704a1`), moving most of the
46 rows and dropping every alternative. What it stands at now: **32 weapon rows
onto 26 distinct C64 options and 14 head rows onto 12**, with C64 weapon 5
taking DOS bodies 10, 12, 13 and 14, weapon 27 taking 6, 9 and 15, weapon 3
taking 21 and 24, and C64 head 2 taking DOS heads 1, 4 and 6. The collisions
are the table's, not the reader's: three DOS maces genuinely land on the one
C64 mace.

The party is `~/dos_por_play/SAVE` slot J, six played characters in The Slums —
untrusted as evidence *about the game* and adequate as *input to a conversion*.
It is the party on this machine with the most to say: six different
`icon_head`/`icon_body` pairs, and two of the six small.

| C64 slot | who | DOS body, head, size | C64 weapon, head |
|---|---|---|---|
| 5 | THRENDER GRONE | 3, 11, small | 23, 6 |
| 4 | BAKSHI | 17, 9, large | 2, 4 |
| 3 | RHIANNON | 24, 10, large | 3, 15 |
| 2 | BROTHER SEAN | 26, 5, large | 20, 1 |
| 1 | DARKSTAR | 29, 9, large | 32, 4 |
| 0 | PHINEAS | 5, 13, large | 21, 7 |

Six distinct sets of eighteen codes, and the conversion wrote them itself: the
tool composes the same six a second time and compares against the finished
payload, 6 of 6 agreeing byte for byte.

The party walked nine steps out of camp and was ambushed. `tools/savecheck.py
--icon` read the floor at the first command bar and scored every 3x3 block
against both poses of all eight save slots:

| drawn at | who the combatant table names | matched | glyphs | colours |
|---|---|---|---|---|
| 10,7 | DARKSTAR | exactly slot 1, pose 0 | 9 of 9 | matched |
| 10,10 | PHINEAS | exactly slot 0, pose 0 | 9 of 9 | matched |
| 13,4 | BAKSHI | exactly slot 4, pose 0 | 9 of 9 | matched |
| 13,10 | RHIANNON | exactly slot 3, pose 0 | 9 of 9 | matched |
| 13,13 | BROTHER SEAN | exactly slot 2, pose 0 | 9 of 9 | matched |
| 13,19 | THRENDER GRONE | exactly slot 5, pose 0 | 9 of 9 | matched |

**Six of six, each naming one of sixteen candidates, and the slot it names is
the one `marching_slot` put that character in.** Thirteen figures were on the
floor and seven were distinct: six party figures and one monster design, seven
kobolds drawn alike.

The fight then ran 80 more command bars with a reading at each. **411
party-figure readings over 81 bars, and every one of the 411 named exactly one
slot out of sixteen, and named the slot the engine's own combatant table put
that character in.** None named two, none named none, none named the wrong one.

| | readings |
|---|---|
| 3x3 blocks scored, party and monsters together | 1024 |
| of them a party member, by the combatant table | 411 |
| naming exactly one slot on 9 of 9 glyph bitmaps | 411 |
| naming none, or more than one | 0 |
| naming a slot the combatant table disagrees with | 0 |

Per character: PHINEAS 78, RHIANNON 75, BROTHER SEAN 75, BAKSHI 70, DARKSTAR
69, THRENDER GRONE 44 — the last is smaller because he left the drawn window
sooner, not because a reading failed.

That is a stronger reading than the earlier run could take. There, two of the
six named the same DOS body and head, so their eighteen codes were identical by
construction and 53 readings named both of them; here all six differ and every
reading resolves.

**The colours agreed on 366 of the 411, and the other 45 are the reader rather
than the game.** Those 45 are exactly the 45 where the engine drew the figure
mirrored — 411 of 411, mirrored and colourless are the same readings — and
`figure_reading` mirrors the glyphs but compares the colour block unmirrored.
`docs/174-combat-figures-in-the-running-game.md` has the mirroring rule; it is
per cell and by the cell's own colour bit 3.

And the control: each figure's colour block was also compared against the
creation default, which is the icon the conversion used to write into all six
slots — `pose match [False, False]` on every one of the six, so nobody arrived
wearing the figure this whole ticket was filed about.

### The earlier run, on a staged clean party

The party is `WISH-SPEC-por-party-l1-intown` with six figures staged into it:
an archer, a sword and shield, a robed staff, a raised axe, a crossbow and a
flail, three of them repainted. Converted with `tools/dosfigures.py`, which
hands `goldbox.dos.new_save` the option tables themselves and lets the shipped
conversion compose the six icons; it then composes them a second time and
compares, so the run is a check on `convert_save` rather than on the tool.
Until the wiring landed on 2026-09-05 the tool wrote the six icons over the
table itself, which proved the composition and not the button.

**Six characters, six distinct icons**, where the conversion as it stood when
this was taken wrote one into all six.

| slot | who | DOS body, head, size | C64 weapon, head |
|---|---|---|---|
| 5 | WISHFTR | 1, 0, large | 26, 7 |
| 4 | WISHCLE | 24, 3, large | 3, 3 |
| 3 | WISHMAG | 28, 6, large | 31, 14 |
| 2 | WISHTHI | 9, 2, small | 8, 16 (a large-only head) |
| 1 | WISHDWF | 16, 13, small | 28 (a large-only weapon), 13 |
| 0 | WISHHEL | 3, 5, large | 23, 5 |

### In the game's own icon editor

`tools/iconswing.py --camp --who N` takes the party to
`ENCAMP > ALTER > ICON` for the Nth character, which draws four 3x3 figures
under `NEW`/`OLD` and `READY`/`ACTION`, and scores every 3x3 block of nine
consecutive screen codes on that screen against both poses of all eight save
slots — sixteen candidates. Six runs, one per character:

| party position | matched | glyphs | colours |
|---|---|---|---|
| 1st, WISHFTR | exactly slot 5, poses 0 and 1 | 9 of 9 | matched |
| 2nd, WISHCLE | exactly slot 4, poses 0 and 1 | 9 of 9 | matched |
| 3rd, WISHMAG | exactly slot 3, poses 0 and 1 | 9 of 9 | matched |
| 4th, WISHTHI | exactly slot 2, poses 0 and 1 | 9 of 9 | matched |
| 5th, WISHDWF | exactly slot 1, poses 0 and 1 | 9 of 9 | matched |
| 6th, WISHHEL | exactly slot 0, poses 0 and 1 | 9 of 9 | matched |

**24 blocks, every one naming exactly one of sixteen candidates, and the slot
it names is the one `marching_slot` put that character in.** The two `READY`
blocks match the icon's first nine codes and the two `ACTION` blocks its second
nine, with mode byte 9 recorded on every reading.

That is the check `#184 (A converted combat icon's colours are proven in the
game and its shapes are not)` could not make on a converted disk, because until
now every slot held the same icon and a match against one slot was a match
against all six.

### On the combat floor

The party above cannot be fought: it stands in New Phlan, which has no
wandering monsters, and `tools/iconswing.py` walked it 60 steps for **no
encounter in 60 steps**. So the fight was driven on a second converted party —
`~/dos_por_play/SAVE` slot B, six played characters in a dungeon, whose
provenance is untrusted as evidence *about the game* and adequate as *input to
a conversion*. Two of its six name the same DOS body and head and differ only
in colour, which is the interesting case.

35 command bars, all with the mode byte at 2. Of 376 3x3 blocks read across
them — party and monsters together — **177 matched a save icon's nine glyph
bitmaps exactly, and all six slots appear**:

| readings naming | count | which |
|---|---|---|
| exactly one slot | 124 | slot 1 thirty times, slot 2 thirty-five, slot 3 thirty-five, slot 5 twenty-four |
| two slots | 53 | always slots 0 and 4, the pair whose DOS records name the same body 24 and head 0 |

The 53 are the conversion being faithful rather than the reading failing: those
two characters' eighteen codes are identical by construction and only their
colours differ, and the colour half separated them on 7 of the 53. The engine
read all six slots' icons nine bytes a pose before the first command bar, which
is what `docs/186-ready-and-action.md` describes it doing.

## What is not converted, and why

* **The highlight nibble** — six values, one a part. A C64 cell has one colour
  of its own; the other three in a multicolour cell belong to the whole screen.
* **The exact silhouette.** The C64's figures are its own art. A DOS
  sling-and-shield becomes the closest C64 figure because the C64 has no such
  figure; three DOS maces land on the one C64 mace.
* **`icon_dimension`** is not a loss at all: it is the combat footprint, it is
  1 for every player character in every record read, and DOS creation writes
  the 1 back.

## Reproducing it

The four sheets Donald judges the rows on, and the party that proved them:

```sh
for k in weapon head; do for s in small large; do
    tools/iconproposal.py --kind $k --size $s --png work/issue130/$k-$s.png
done; done
tools/dosfigures.py --folder ~/dos_por_play/SAVE --slot J \
    --out work/issue130/PLAYJ.D64 --png work/issue130/playj.png
POR_HEADLESS=1 tools/savecheck.py --disk work/issue130/PLAYJ.D64 \
    --icon --fight --steps 60
```

The nine mixed rows, which no Pool of Radiance party here wears:

```sh
tools/dosmixedicon.py --census
tools/dosmixedicon.py --stage work/issue130/mixedparty \
    --from ~/dos_por_play/SAVE --slot J
tools/dosfigures.py --folder work/issue130/mixedparty --slot J \
    --out work/issue130/MIXEDJ.D64 --png work/issue130/mixedj.png
POR_HEADLESS=1 tools/iconswing.py --disk work/issue130/MIXEDJ.D64 \
    --camp --who 0 --tag mix0
```

The earlier run, on the staged clean party:

```sh
cp ~/wish-specimens/por-dos/WISH-SPEC-por-party-l1-intown/* work/issue130/dosparty/
tools/dosiconstage.py --folder work/issue130/dosparty --slot E
tools/dosfigures.py --folder work/issue130/dosparty --slot E \
    --out work/issue130/FIGURES.D64 --png work/issue130/converted-party.png
tools/dosfigures.py --mixed-png work/issue130/mixed-size.png
tools/dosnibbles.py --per-option
for w in 0 1 2 3 4 5; do
    POR_HEADLESS=1 tools/iconswing.py --disk work/issue130/FIGURES.D64 \
        --camp --who $w --tag who$w
done
```

**`tools/iconswing.py` claims its own pool slot**, so it is run directly rather
than inside `tools/instance.py claim`; wrapping it takes two slots and leaves
the inner one running when the outer `timeout` fires.
