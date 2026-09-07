# A converted party in Amiga Curse and Amiga Silver Blades

`goldbox.amiga.write_later` turns a neutral Curse or Silver Blades character
into an Amiga block. Until 2026-09-07 every check on it was this project's own
reader re-parsing this project's own writer's bytes — 59 blocks round-tripping
and 150 field comparisons against the Amiga's own twins — and neither engine had
ever seen one. `.claude/rules/conversions.md`: *a conversion is not proven until
it runs.*

**Both games loaded a converted party, drew it, and wrote it back.** Two WinUAE
runs on 2026-09-07, VM lease and WinUAE lane `wish384`, for
`#384 (Write an Amiga Curse or Silver Blades character, so a C64 or DOS party
has an Amiga to arrive on)`. What follows is what the engines drew and what
their own resaves hold.

## What was put in front of them

| | Amiga Silver Blades | Amiga Curse |
|---|---|---|
| source | `WISH-SPEC-ssb-d-engine-resave.D64`, written by the **C64 engine** | `WISH-SPEC-curse-52-dialog-converted-resave.D64`, same |
| the party | Guy de Valois, MORGAINE, DOMINIC, MALACHITE, EPONA, PAINE | MATHEW, PHILIPPE, SHARA, LEDERA, TRAVIS, MARK |
| first character | Guy de Valois, **12 items and 1 effect** | MATHEW, **4 items and 1 effect** |
| our saved game | `SAVE/savgamB.sav`, 8073 bytes | `SAVE/savgamB.dat`, 15717 bytes |
| the engine's | `savgamD.sav` and `savgamC.sav`, **8073 both** | `savgamC.dat`, **15717** |

**The item-carrying character is deliberately first, and that is the whole
design of the run.** `write_later` writes a **boolean** chain head — 1 or 0
according to whether a node follows — where `write_por` writes NULL, because
these two loaders `tst.l` the head and read a node only when it is non-zero
(`/Curse` `0x25056`, `/Secret` `0x268C0`). A wrong head does not spoil one
character: every character is read off one file descriptor in sequence, so the
stream would be left mid-block and **everybody after the bad one** would be read
out of the wrong bytes. Both C64 saves keep their only item-carrying character
last, where nothing is behind him to be corrupted, so
`tools/amigalaterproof.py build --first <name>` moves him to the front.

## What the games drew

**The party panel lists all six, on both titles, with the right numbers.**
Silver Blades: AC 6/7/6/7/7/6 and HP 95/35/78/58/91/74. Curse: AC 7/7/7/8/7/7
and HP 49/27/29/28/34/51. Every one of those twenty-four figures is what the
converted record holds — armour class as the stored `60 − AC` at the title's own
offset, hit points at `hp_max`. **Five characters behind a twelve-node item
chain and four characters behind a four-node one drew their own names and their
own numbers**, which is what a desynchronised loader could not do.

**The ITEMS screen names every item.** Guy de Valois' twelve, in the order the
C64 record keeps them and with the C64's own names beside them:

| the Amiga drew | the C64 record holds |
|---|---|
| `NO MAGE SCROLL 3 SPELLS` | MAGE SCROLL 3 SPELLS, not readied |
| `NO 30 ARROWS +1` | ARROW +1, quantity 30 |
| `NO LEATHER ARMOR +1` | LEATHER ARMOR +1 |
| `NO SCALE MAIL +2` | SCALE MAIL +2 |
| `NO GAUNTLETS OF OGRE POWER` | GAUNTLETS OF OGRE POWER |
| `NO WAND OF ICE STORM` | WAND OF ICE STORM |
| `NO BRACERS AC 6` | BRACERS AC 6 |
| `NO HALBERD +2` | HALBERD +2 |
| `NO MACE +1` | MACE +1 |
| `NO LONG SWORD +1` | LONG SWORD +1 |
| `NO SHIELD +2` | SHIELD +2 |
| `NO PLATE MAIL +1` | PLATE MAIL +1 |

Twelve of twelve, in order, with the ready column and the quantity right.
MATHEW's four in Curse are the same result: `BATTLE AXE`,
`TWO-HANDED SWORD`, `10 ARROWS`, `LEATHER ARMOR`, against the C64's BATTLE AXE,
TWO-HANDED SWORD, ARROW(S) quantity 10, LEATHER ARMOR.

**And the display buffer really can be left NUL**, which the issue had as
PROBABLE from Amiga Pool of Radiance only. Every one of those sixteen item
nodes went in with 42 NUL bytes where the game's own nodes carry a rendered
line, and every column on the screen came out of a field: the ready column from
`readied`, the count from `quantity`, the name from the three name-table
indices. The engine then **wrote the line back into the node** — Guy's twelve
came out of the camp save reading `' No\t Mage Scroll 3 Spells '` and the rest
— exactly the composer-and-cache `docs/182-amiga-por-in-the-running-game.md` §2
watched in Pool of Radiance, now measured on the 70-byte Silver Blades node and
the 66-byte Curse one. A save made without opening ITEMS first came back still
NUL, so the moment the line is written is the drawing rather than the load or
the save, on these two titles as well.

**The character sheets.** Guy de Valois: `MALE 20 YEARS`, `LAWFUL GOOD`,
`HUMAN`, `PALADIN`, `LEVEL 8`, `HIT POINTS 95/95`, `EXPERIENCE 202750`,
`STR 18(00) INT 14 WIS 18 DEX 18 CON 18 CHA 17`, `ARMOR CLASS 6`, `THAC0 10`,
`DAMAGE 1D2+6`, `ENCUMBRANCE 1490`, `MOVEMENT 12`, and a `CURE` button beside
`ITEMS` and `HEAL` — `paladin_cures` converted. MATHEW in Curse:
`MALE HUMAN AGE 20`, `LAWFUL GOOD`, `MAGIC-USER`, `STR 18(00)`,
`PLATINUM 288`, `LEVEL 1`, `EXP 0`, `MAX HP 49`, `AC 7`, `THAC0 18`,
`ENCUMBRANCE 803`, `MOVEMENT 12`, `STATUS OKAY`.

**The character *after* the one with the items**, which is where a bad chain head
shows first. MORGAINE, second in the Silver Blades party: `FEMALE 27 YEARS`,
`TRUE NEUTRAL`, `HUMAN`, `MAGIC-USER`, `LEVEL 9`, `HIT POINTS 35/35`,
`STR 17 INT 18 WIS 14 DEX 17 CON 16 CHA 16`, `ARMOR CLASS 7`, `THAC0 18`,
`ENCUMBRANCE 0`, `MOVEMENT 12` — and **no `ITEMS` button**, which is the loader
agreeing with the zero item-chain head she was written with. MALACHITE, fourth,
with three effect nodes and no items: `MALE 60 YEARS`, `NEUTRAL GOOD`, `DWARF`,
`FIGHTER/THIEF`, `LEVEL 7/8`, `HIT POINTS 58/58`, `EXPERIENCE 102500`,
`STR 18(05)`, `GOLD 4`, `AC 7`, `THAC0 13`, `ENCUMBRANCE 4`.

**How a second character's sheet is reached, because it is not obvious and it
differs between the two titles.** Amiga Silver Blades' **camp** screen moves the
party-panel highlight on cursor **down**, and `VIEW` then draws whoever is
highlighted; the party menu, the adventuring bar and the sheet itself all ignore
the key. **Amiga Curse does not do this at all** — its camp screen, party menu
and bar all ignore cursor down — so on that title only the first character's
sheet can be drawn with the keys `tools/winuae.ps1` has, and the five behind him
were read off the party panel instead.

## The engine's own resave, which is the strongest of it

Each party was written back by the game and compared with what we wrote, masked
by the lists the writers **declare** —
`goldbox.amiga.LATER_WRITE_UNSOURCED`, `LATER_ITEM_WRITE_UNSOURCED`,
`LATER_EFFECT_WRITE_UNSOURCED` and `goldbox.dos`'s six, mapped through the
title's shift map — and never by whatever happened to differ.
`tools/amigalaterproof.py diff` is the comparison.

| | bytes of party block | identical | inside the declared lists | outside them |
|---|---|---|---|---|
| Silver Blades, saved from the party menu with no script run | 2930 | 2859 | 66 | **5** |
| Silver Blades, saved from camp after the opening scene | 2930 | 2610 | 303 | 17 |
| Curse, saved from camp | 2892 | 2763 | 121 | **8** |

**Every block came back the length it went in**, and so did every file: 8073
against 8073 and 15717 against 15717, with the same six people in the same
order and the same item and effect counts. `tools/amigasavegame.py`'s every
internal check is clean on all three engine-written files, `rebuild(parse(f))
== f` included.

### What is outside the lists, and none of it is a byte the writer got wrong

**`party_order`, five characters of six on both titles.** We write 0 for
everybody and the engine wrote 0, 1, 2, 3, 4, 5 — the first character's own 0 is
why it is five and not six. This is the combat-icon slot rather than the
marching order (`#305 (Two DOS record bytes have one name from Pool of Radiance
and another from the Curse decompilation)`), `goldbox/dos_layout.py` reads the allocation loop out of
the shipped overlays, and this run is the demonstration that the **Amiga** engine
allocates it on load too. Nothing a player can see: the sheet, the panel and the
figure all draw from the engine's own number. It is
`#282 (party_order (record 0x10D) is gated the same way as #281's four bytes,
and never delivered from a real C64 save)`, whose open question was whether a
caller that does not renumber shows the byte anywhere. On this destination it
does not.

**`thac0_current` and one byte of `roster_tail`, Curse only.** MATHEW went in
with `thac0_current` 0x2F and came back 0x2A; PHILIPPE 0x29 and came back 0x28;
MATHEW's `roster_tail+5` — one of the eight running attack-form bytes — 0x08 and
came back 0x02. The sheet drew `THAC0 18`, which is 0x2A, so the engine's number
is the one a player reads. Both fields are derived from the readied weapon and
the engine recomputes them on load, which is what changing a stored value proves;
neither is on a declared list yet, which is why the diff reports them.
`#402 (Amiga Curse recomputes thac0_current and a roster_tail byte on
load, and no declared list says so)` carries that.

**Experience, in the camp save only**, and it is the game rather than the
conversion: Silver Blades' opening scene awards experience before the party ever
reaches the adventuring bar, so all six gained some between the load and the
save. That is why the party-menu save is the one to read the writer against —
`LOAD SAVED GAME`, then `SAVE CURRENT GAME`, with no `BEGIN ADVENTURING` in
between, runs no script at all.

### What the engine did inside the lists

The same three things `docs/124-amiga-port.md` §1.12a found for Amiga Pool of
Radiance, and for the same reason — they are live heap:

* **the chain heads and the `next` pointers became real Amiga addresses.** Our
  boolean `1` at MALACHITE's first effect node's `next` came back
  `0x0000C6E8`-something, and the last node's `next` came back `0` because that
  is what a terminator is;
* **`heap_104` and the item nodes' `next`** the same way;
* **the display line**, above.

## The byte nobody has attributed, and what this run says about it

`#387 (The Amiga Silver Blades effect node keeps a byte DOS has not got, and a
converted character loses it)` is offset 1 of an effect node — `0x2E` on Guy de
Valois' effect `0x08` and `0x64` on MALACHITE's `0x2F` in the party SSI shipped,
zero in their DOS twins, and written zero by this writer because nothing in the
neutral record can source it.

**The engine loaded five nodes with zero there, and wrote zero back, twice.**
Guy's one and MALACHITE's three and PAINE's one, across both the camp save and
the party-menu save. Nothing about any of those characters came out wrong on
screen. So the byte is not derived on load, not repaired, and not consulted by
anything the load path touches — which is the control
`docs/202-the-amiga-effect-node-pad.md` reads out of the executable as an
alignment pad.

## What is still not proven

* **A fight.** Nothing here entered combat, so the combat figure, the attack
  arithmetic and the item bonuses in a real round are untested on either title.
  The figure is dropped and reported anyway.
* **A character carrying nothing, in the running game.** The empty case has a
  test (`tests/test_amigalaterwrite.py`) and the party panel drew five of them,
  but no character with an empty inventory has had his own ITEMS screen opened
  — which is how `#62 (A converted character who owns nothing gets a corrupt
  sheet, and DOS then invents a garbage item)` was found on the DOS side.
* **Sixteen items.** The extreme case is tested and was not run; twelve is the
  most any engine has drawn from this writer.
* **Curse's second character's sheet**, for the harness reason above.

## Reproducing it

```sh
tools/amigalaterproof.py build \
    --source ~/wish-specimens/por-c64/WISH-SPEC-ssb-d-engine-resave.D64 \
    --into work/384/ssb-src.adf --from A --to B \
    --first 'Guy de Valois' --out work/384/ssb-first.adf
# copy ssb-first.adf to the guest, boot it, and drive:
#   RET  P  L  B          -- credits, PLAY, LOAD SAVED GAME, our slot
#   V  I  E  E            -- the sheet, ITEMS, back out twice
#   S  D                  -- SAVE CURRENT GAME into slot D, the clean resave
tools/amigalaterproof.py diff --ours work/384/ssb-first.adf --ours-slot B \
    --theirs work/384/ssb-resaved.adf --theirs-slot D
```

Amiga Curse is the same with `P` twice, `tools/amigacursewheel.py` for the code
wheel, and `.dat` in place of `.sav`; Amiga Silver Blades' `BEGIN ADVENTURING`
wants `tools/amigabladesjournal.py`, and **both of those tools need
`/usr/bin/python3`** rather than this project's virtual environment, because
they reach into the separate private repository and it imports `numpy`.
`docs/124-amiga-port.md` §1.11 and §1.11a have the rest of each route, and
`docs/143-winuae-debugger.md` has the VM.

The three engine-written saved games are specimens:
`WISH-SPEC-ssb-amiga-converted-menu-resave`,
`WISH-SPEC-ssb-amiga-converted-items-drawn` and
`WISH-SPEC-coab-amiga-converted-resave`. The second is the first Amiga Silver
Blades item node anybody has had — all six characters SSI shipped on that disk
carry none — so the 70-byte node rested entirely on two routines in `/Secret`
until this run.
