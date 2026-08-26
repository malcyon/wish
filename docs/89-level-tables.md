# Level progression

**Generated** by `tools/genlevels.py` from `goldbox/levels.py` — do not edit.

What each class needs to advance and what it gets. Pool of Radiance stops well
short of the rulebook — a fighter at 8, a cleric at 6 — because it was built to
hand its party on to *Curse of the Azure Bonds*.

**THAC0 is verified against the game**, which caught two errors in the published
table it came from: magic-user and thief level 1 are **21**, not 20. Rows the
game itself confirms are marked ✓; `tests/test_levels.py` asserts them against
every character record we hold.

**The saving throws are the game's own too.** Pool of Radiance does not
tabulate them: `GEN $1F44` cuts a level-1 row at `$1FA2` by two per-column
bitmasks, and `$2359` then takes `constitution * 2 / 7` off all five columns
for a dwarf, gnome or halfling. That is why two level-1 fighters read
`(14,15,16,17,17)` and `(11,12,13,14,14)` — the second is a dwarf — and it is
what settles the fighter's level-4 breath save at **15** where AD&D says 16.
`tests/test_levels.py` re-expands every row off the player's own `GEN`.


## cleric

| level | experience | hit dice | max hp | THAC0 | attacks | saves | spells |
|---|---|---|---|---|---|---|---|
| 1 | 0 | 1d8 | 8 | 20 ✓ | 1 | 10 / 13 / 14 / 16 / 15 | 1 |
| 2 | 1,501 | 2d8 | 16 | 20 | 1 | 10 / 13 / 14 / 16 / 15 | 2 |
| 3 | 3,001 | 3d8 | 24 | 20 | 1 | 10 / 13 / 14 / 16 / 15 | 2/1 |
| 4 | 6,001 | 4d8 | 32 | 18 | 1 | 9 / 12 / 13 / 15 / 14 | 3/2 |
| 5 | 13,001 | 5d8 | 40 | 18 | 1 | 9 / 12 / 13 / 15 / 14 | 3/3/1 |
| 6 | 27,501 | 6d8 | 48 | 18 ✓ | 1 | 9 / 12 / 13 / 15 / 14 | 3/3/2 |

## fighter

| level | experience | hit dice | max hp | THAC0 | attacks | saves |
|---|---|---|---|---|---|---|
| 1 | 0 | 1d10 | 10 | 20 ✓ | 1 | 14 / 15 / 16 / 17 / 17 |
| 2 | 2,001 | 2d10 | 20 | 19 | 1 | 14 / 15 / 16 / 17 / 17 |
| 3 | 4,001 | 3d10 | 30 | 18 | 1 | 13 / 14 / 15 / 16 / 16 |
| 4 | 8,001 | 4d10 | 40 | 17 | 1 | 13 / 14 / 15 / 15 / 16 |
| 5 | 18,001 | 5d10 | 50 | 16 | 1 | 11 / 12 / 13 / 13 / 14 |
| 6 | 35,001 | 6d10 | 60 | 15 | 1 | 11 / 12 / 13 / 13 / 14 |
| 7 | 70,001 | 7d10 | 70 | 14 ✓ | 3/2 | 10 / 11 / 12 / 12 / 13 |
| 8 | 125,001 | 8d10 | 80 | 13 ✓ | 3/2 | 10 / 11 / 12 / 12 / 13 |

## magic-user

| level | experience | hit dice | max hp | THAC0 | attacks | saves | spells |
|---|---|---|---|---|---|---|---|
| 1 | 0 | 1d4 | 4 | 21 ✓ | 1 | 14 / 13 / 11 / 15 / 12 | 1 |
| 2 | 2,501 | 2d4 | 8 | 21 | 1 | 14 / 13 / 11 / 15 / 12 | 2 |
| 3 | 5,001 | 3d4 | 12 | 21 | 1 | 14 / 13 / 11 / 15 / 12 | 2/1 |
| 4 | 10,001 | 4d4 | 16 | 21 | 1 | 14 / 13 / 11 / 15 / 12 | 3/2 |
| 5 | 22,501 | 5d4 | 20 | 21 | 1 | 14 / 13 / 11 / 15 / 12 | 4/2/1 |
| 6 | 40,001 | 6d4 | 24 | 19 ✓ | 1 | 13 / 11 / 9 / 13 / 10 | 4/2/2 |

## thief

| level | experience | hit dice | max hp | THAC0 | attacks | saves |
|---|---|---|---|---|---|---|
| 1 | 0 | 1d6 | 6 | 21 ✓ | 1 | 13 / 12 / 14 / 16 / 15 |
| 2 | 1,251 | 2d6 | 12 | 21 | 1 | 13 / 12 / 14 / 16 / 15 |
| 3 | 2,501 | 3d6 | 18 | 21 | 1 | 13 / 12 / 14 / 16 / 15 |
| 4 | 5,001 | 4d6 | 24 | 21 | 1 | 13 / 12 / 14 / 16 / 15 |
| 5 | 10,001 | 5d6 | 30 | 19 | 1 | 12 / 11 / 12 / 15 / 13 |
| 6 | 20,001 | 6d6 | 36 | 19 | 1 | 12 / 11 / 12 / 15 / 13 |
| 7 | 42,501 | 7d6 | 42 | 19 | 1 | 12 / 11 / 12 / 15 / 13 |
| 8 | 70,001 | 8d6 | 48 | 19 | 1 | 12 / 11 / 12 / 15 / 13 |
| 9 | 110,001 | 9d6 | 54 | 16 | 1 | 11 / 10 / 10 / 14 / 11 |

