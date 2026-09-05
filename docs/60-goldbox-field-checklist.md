# Gold Box character record — field checklist (what *ought* to be in the C64 record)

Research pass. Purpose: give Phase 2 differential diffing a target list —
"we should expect to find X, Y, Z somewhere in these 580 bytes" — and, for each field,
the cheapest single in-game action that moves it in isolation.

**This is a checklist of field *semantics*, not an offset map.** The DOS, Amiga, Apple and
C64 releases have different record layouts. Where offsets appear below they are tagged with
the platform they came from and a confidence label.

## Confidence labels used throughout

| Label | Meaning |
|---|---|
| `CONFIRMED-C64` | Observed directly in our own 580-byte specimen and semantically unambiguous. |
| `CORROBORATED-C64` | Claimed by a C64-native third-party tool **and** consistent with our specimen. Still unverified by controlled in-game experiment. |
| `TOOL-CLAIM-C64` | Claimed by a C64-native third-party tool, not yet checkable against our specimen (field is zero / character has none). |
| `DOS-DOC` | Documented and corroborated for the **DOS** build. Tells us the field *exists*; the offset does **not** transfer. |
| `INFERENCE` | My reasoning from the specimen or from cross-platform structure. Treat as a hypothesis to be tested. |
| `WEAK` | Stated once, by one person, unsourced. |

---

## How this pass turned out

This document is a **research snapshot**, written before most of the work was
done. It is kept as written because its value is the reasoning and the source
appraisal, not the field table — but a reader should know which of its bets came
in. Where it and the rest of the knowledge base disagree, the other documents
win; `docs/80-fields-wanted.md` is the current field list and
`docs/20-character-record.md` is generated from the code.

**It was right about the things that mattered most.**

* Item names really are **three vocabulary token bytes** read high-address to
  low, indexing a shared 255-entry table. That is exactly the encoding, and this
  document predicted it before a single item had been decoded.
* Memorised spells really are **a list of spell ids, not flags**. Found at record
  offset `0x020`.
* Max and current hit points really are **separate**, and the editor readme's
  temple remark really was the clue it looked like.
* Saving throws, movement base, HP rolled and the money layout all landed exactly
  where it said.
* The `base`/`current` twin pattern it warned about is real, and it did bite:
  armour class is a **cached** value that goes stale after an ability edit.

**Where it was wrong or incomplete.**

* It assumed the whole record was the unit of study. Several of the fields it
  hunts for are **not in the character record at all** — the current armour
  class, THAC0, hit points, movement and damage bonus live in the `SAVEDGAME1`
  roster blocks. That is also why the 1989 editor's author could
  never find AC or THAC0: he was editing an export, which has no roster block.
* Per-class levels are at `0xC9`–`0xCC`, not `0xCA`–`0xD1`. The DOS eight-byte
  array really is eight wide, but the C64 **indexes it by `class_bits` bit
  position** and DOS indexes it by the class enum — so the two ports hold the
  same array permuted, and a converter must permute it back.
* `0xA0` is character level after all, and the doubt recorded in §5 was
  misplaced — see the correction there.
* The item slot geometry it distrusted is correct: 16-byte records, and in a
  save they sit in the item area at `$5900` rather than inline.
* Its guess that `0x71` is THAC0-base was right, and was wrongly written off
  here for a while. `0x71` is the **base** THAC0 and roster byte `+0x0E` is the
  **current** one, both stored as `60 - value`.
* **Its §2.13 field-order hypothesis is the one that paid best.** "The C64
  record is the DOS record with the same field sequence and different region
  sizes" is now demonstrated over the whole record: anchoring on fields both
  ports have CONFIRMED gives a piecewise offset map with a handful of deltas
  (+4, +`0x2D`, +`0x2E`, +`0x33`, +`0x38`, −2), and the DOS names then say what
  the C64's unnamed bytes are. That is how `0x0D7` was named. See
  [127-community-formats.md](127-community-formats.md) §3.

**Closed since this pass, from its own list:** attacks per round (`0x0D9`–`0x0E0`,
two independent derivations), active magical effects (`0x0AD`, a ten-slot list
whose 129-code namespace is now named — [128](128-guide-and-scripting.md)), the
level-drain pair (`0x0A1`/`0x0A2`, read off the drain and restoration routines),
damage, and the portrait head/body.

Order number is `0x10D`, PROBABLE — the one byte where an export and the roster
block disagree.

**Still open from its list:** status (`0x100` is the candidate and four sources
now disagree about it, the newest *weakening* the case) and encumbrance, which
DOS keeps as a `u16` at its `0x102` and which nothing on the C64 has been
matched to.

## 0. The evidence base (read this before trusting anything below)

Three sources actually carry weight, and they are unequal.

**(a) A C64-native Pool of Radiance character editor exists, and it is BASIC.**
"Pool of Radiance Editor v5" by Steve Krulewitz / "Cracked 1" (later edited by Philipp Garcia),
distributed as `poolce.d64` on CSDb. It contains `POR EDITOR V5` (PRG, tokenised BASIC, listable)
and `POR EDIT DOCS` (SEQ, author's readme). It operates on exactly the artefact we already have:
a removed/exported single-character file, `LOAD"<CHR(1)>name",8,1`, which lands at **$6B00**, and
it saves back the range $6B00–$6D44. Every field it edits is a literal `POKE ad+N`, where
`ad = 27392 = $6B00`. **This is direct C64 evidence, not DOS material.**
Caveat: it is a hobbyist tool from ~1989 with visible bugs (see §5), and it is evidence of what
its author *believed*, corroborated where our specimen agrees.

**(b) Gold Box Companion's `formats.zip`** — Joonas Rissanen's per-game character-record field
lists for all 12 Gold Box titles, plus `Offsets compared.txt`, a cross-game field/offset matrix.
This is the best *semantic* catalogue in existence: it names ~120 distinct per-character fields.
It is **DOS-only** and it is derived from live DOS memory. `Offsets compared.txt` is itself the
proof that layouts move between titles — PoR, CotAB and SotSB agree on almost no offset — which
is exactly why we should assume the C64 build moves them again.

**(c) Our own specimen** (`.BRUTUS`, 580 bytes, from `PORSAVE.D64`), read-only during this pass.

Things that turned out to be **dead ends**: the amiga-dev.wikidot Pool of Radiance project page
is a stub (compression only, "Data File Format: Undetermined at this time", last edited 2012);
Lemon64's threads name tools but publish no offsets; Simeon Pilgrim's work is a DOS/Apple
CotAB reimplementation, useful for *concepts* (he named the "save bonus" item field) but not for
C64 PoR layout.

### Re-obtaining the primary artefacts

```
https://gbc.zorbus.net/formats.zip     # GBC character-record field lists (DOS)
https://gbc.zorbus.net/hackdocs.zip    # FRUA file formats (DOS)
https://csdb.dk/getinternalfile.php/62150/poolce.zip   # the C64 editor + its readme
```

`poolce.zip` contains one `.d64`; the BASIC program is the PRG `POR EDITOR V5` (dir entry track 17
sector 0) and the readme is the SEQ `POR EDIT DOCS`. Detokenise the PRG to read the offsets.

---

## 1. The field checklist

Every entry: what it means, expected width/range, and **the cheapest in-game action that changes
it and as little else as possible**. The last column is the point of this document.

### A note on generating specimens

The single most useful mechanic we have: **`REMOVE` a character from the party writes a complete
580-byte character file to the save disk.** Diffing two such files is far cleaner than diffing
`SAVEDGAME0`, because it removes all party-context noise. Verified: our `.BRUTUS` file and the
`$4D00` slot inside `SAVEDGAME0` differ in exactly 44 bytes, and **all 44 are in two regions
that are populated in the exported file and zero in the in-save slot** — the item area
(`0x100`, `0x10D`–`0x11B`) and a 36-byte icon block (`0x220`–`0x243`). Everything else is
byte-identical. (`INFERENCE` from one specimen — and **since withdrawn**: the 44 bytes were
an artefact of reading 580 contiguous bytes out of a `$100` slot and running off its end. See
[30-savegame-layout.md](30-savegame-layout.md).)

### 1.1 Identity

| Field | Meaning / encoding | Width | Cheapest isolating action | Confidence |
|---|---|---|---|---|
| Name | ASCII/PETSCII, NUL-padded, **no length prefix** on C64 (DOS uses len+15). Editor enforces max 19 chars and zero-fills to 20. | 20 B | Create two characters identical but for name. Use a name with lowercase/punctuation to settle **PETSCII vs ASCII** — `A`–`Z` are $41–$5A in both, so `BRUTUS` cannot distinguish them. | `CONFIRMED-C64` |
| Race | Small enum. DOS: 1 dwarf, 2 elf, 3 gnome, 4 half-elf, 5 halfling, 6 half-orc, 7 human, 0 monster. C64 editor uses the same 1..7 ordering (it lists "monster" as 8). | 1 B | Create two characters differing only in race. | `CORROBORATED-C64` (specimen = 7, human) |
| Class | Enum including multiclass combos: 0 cleric, 1 druid, 2 fighter, 3 paladin, 4 ranger, 5 mage, 6 thief, 7 monk, 8 cl/fi, 9 cl/fi/mu, A cl/ra, B cl/mu, C cl/th, D fi/mu, E fi/th, F fi/mu/th, 10 mu/th, 11 monster. | 1 B | Create two characters differing only in class. | `CORROBORATED-C64` (specimen = 2, fighter) |
| Gender | 0 male, 1 female. | 1 B | Create two characters differing only in gender. | `DOS-DOC` |
| Alignment | 0 LG, 1 LN, 2 LE, 3 NG, 4 TN, 5 NE, 6 CG, 7 CN, 8 CE. | 1 B | Create two characters differing only in alignment. | `DOS-DOC` |
| Age | Years, 16-bit LE. Rolled at creation from race. | 2 B | **Cast Haste** — AD&D 1e ages the target one year, and Gold Box implements it. Cheapest true single-field delta in the game. Otherwise create two characters of different race. | `CORROBORATED-C64` (specimen = 21) |
| "Type" | **Creature type** — humanoid, undead, giant, regenerating, … It is `0x0D7`, and it is 0 in all 79 C64 player records because a player is not a monster. 116 `MON*` records take 13 distinct values, every one inside the DOS enumeration; TROLL reads 10 (regenerating), MUMMY 4 (undead). | 1 B | read a `MON*` file | **CONFIRMED-C64** |
| NPC flag | **`0x0B8` bit 7.** Every read of `$6BB8` in the overlays tests it; the party-count routine tallies player characters with it and enforces `CMP #$06`, which is the six-PC limit; NPC money is zeroed on it. The eight `$FF` bytes that correlate with it are fill residue, not the flag. | 1 bit | already done | **CONFIRMED-C64** |

### 1.2 Abilities

| Field | Meaning / encoding | Width | Cheapest isolating action | Confidence |
|---|---|---|---|---|
| STR, INT, WIS, DEX, CON, CHA (current) | 3–18 normally, 1 byte each, in that fixed order. | 6 × 1 B | Re-roll at creation; or drink a **Potion of Giant Strength** (changes *current* STR only — this is how you find out whether a separate "original" copy exists). | `CONFIRMED-C64` |
| Exceptional STR percentile | 1–100 for STR 18 (00 = 18/00 = best, stored as 100 or 0 depending on game — verify); 0 when not applicable. | 1 B | **Gauntlets of Ogre Power** set STR 18/00. Or re-roll. | `CONFIRMED-C64` (specimen = 98 → "18/98") |
| "Original" ability copies | PoR-DOS **does not have them**; every later Gold Box game does (CotAB onward store original+current pairs, interleaved). Whether C64 PoR has them is open. | 0 or 6–7 B | Drink a strength potion, save, and see whether one byte or two move. | `DOS-DOC` + `INFERENCE` |

### 1.3 Class, level, experience

| Field | Meaning / encoding | Width | Cheapest isolating action | Confidence |
|---|---|---|---|---|
| Per-class level | **Eight separate bytes**, one per class (cleric, druid, fighter, paladin, ranger, mage, thief, monk), all present regardless of class; a fighter has 1 in the fighter byte and 0 elsewhere. This is how multiclass is represented. | 8 B | Train one level at the Training Hall. Not isolated (HP/THAC0/saves/slots all move) — but that is *useful*: it identifies the whole derived cluster in one shot. | `DOS-DOC` + `INFERENCE` (specimen has a lone `01` where a fighter slot would fall) |
| ~~"Level highest 1" / "2"~~ | **There is no "highest level attained".** `0x0A0` is the current level and the drain state is its own pair beside it, so the scheme is current-plus-delta rather than current-and-true. That is why no "true level" was ever found. | — | — | **refuted** |
| Drained levels / drained HP | `0x0A1` / `0x0A2`, read off the routines: `SPELLE02` computes `hp_max / total levels`, loops that many times doing `DEC $6B76 / DEC $6BED / INC $6BA2 / DEC $6C19`, then `INC $6BA1`; `RESTORATION` in `SPELLE04` reverses it exactly. Both read `$FF` on every monster, which the DOS record explains as "normally 0 for PCs, 255 for anything else". | 2 B | still wanted: a character actually drained in play | **CONFIRMED-C64** |
| "Level undead" | Effective level for turning undead. | 1 B | Train a cleric. | `DOS-DOC` |
| Experience points | Must exceed 65535 (PoR caps around 11–16M in practice; the C64 editor's "max" pokes three bytes to $FF). So **24-bit minimum, plausibly 32-bit LE**. | 3–4 B | Kill exactly one weak monster (one kobold) and camp-save. XP is split across the party, so all party members move together — do it with a **one-character party** to keep it clean. | `TOOL-CLAIM-C64` (specimen XP = 0, fresh character) |
| "Highest experience" | Present from PoD onward, not in PoR-DOS. | 0–4 B | — | `DOS-DOC` |
| XP award / XP bonus per HP | Only meaningful for monsters/NPC records. | 3 B | Ignore for PCs. | `DOS-DOC` |
| "Able to train" flag | Set when enough XP for the next level. | 1 B | Cross a level threshold without training. | `DOS-DOC` (SotSB+; may not exist in PoR) |

### 1.4 Combat statistics

| Field | Meaning / encoding | Width | Cheapest isolating action | Confidence |
|---|---|---|---|---|
| HP maximum | 1 byte (PoR levels cap well under 255). | 1 B | Train one level. | `CORROBORATED-C64` (specimen = 11) |
| HP rolled | The raw die total *before* CON bonus. Max HP = rolled + CON bonus × level. | 1 B | Train one level. Cross-check arithmetic: our specimen shows a value of 9 with CON 16 (+2) and max HP 11 — consistent. | `INFERENCE` (strong) |
| HP current | Separate from max. | 1 B | **Take exactly one point of damage, then camp-save.** The single cleanest experiment in this document: exactly one byte should move. | `DOS-DOC` + editor readme ("to get the hitpoints you changed… go to a healing temple") implies max and current are separate on C64 too |
| THAC0 base and THAC0 current | Stored, **not derived at display time**. Base changes on level-up, current additionally reflects readied weapon/STR/effects. | 2 × 1 B | Ready and unready a magic weapon → current moves, base does not. | `DOS-DOC`; our specimen has a suggestive `0x28` (=40) immediately before the race byte, exactly where DOS puts THAC0-base. 40 = 2×20; the doubling is unexplained. `INFERENCE`, verify. |
| AC base / AC current / AC behind | Base is `0x0E1` and current is roster `+0x0F`, both `60 - AC`. **"AC behind" does not transfer.** DOS spends its third byte on rear armour class; the C64 spends the byte at the aligned offset (roster `+0x10`) on the **armour's own contribution, `48 + bonus`** — measured by putting armour on: none 48, leather 50, banded mail 54, the AD&D bonuses 0, 2 and 6 exactly. The DOS alignment is exact and the DOS reading is still wrong here; see [127](127-community-formats.md) §4 for why an alignment is a hypothesis and a measurement is evidence. | 2 × 1 B on C64 | done | **CONFIRMED-C64** |
| Attacks per round | `0x0D9`–`0x0E0` is the whole attack block: two attack forms as four parallel two-entry arrays (attacks doubled, dice, die, modifier), proved from `COMBAT $0CAD`'s stride-2 indexing. Every C64 player reads `2 0 1 0 2 0 0 0` — one attack, 1d2 unarmed. The DOS record spells the same eight bytes out column-first in the same order; both readings are right. | 8 B | done | **CONFIRMED-C64** |
| Unarmed damage: rolls / dice / modifier (×2 sets) | The same eight bytes above. The "current" set that reflects the readied weapon is roster `+0x11`–`+0x18`: attacks remaining ×2, then dice, sides and damage bonus for the two attack forms. `+0x15` is *primary attack die sides*, which is exactly why this project called it `EQUIPMENT` for years — it rises with what is readied. | 8 + 9 B | done | **CONFIRMED-C64** (record), PROBABLE (roster) |
| Saving throws ×5 | Explicit stored numbers at `0x09A`–`0x09E` — but **the rule that produces them is now known**: the class-table row for the character's level, taking the best number in each column across every class held, minus the AD&D constitution bonus when the character is a dwarf, gnome or halfling. **78 of 79 distinct C64 records satisfy it exactly**; the one miss is a hand-authored NPC. LADY KATHERINE (magic-user 1 / thief 1) reads `13 12 11 15 12`, which is neither class's row but the column-wise minimum of the two. | 5 B | done | **CONFIRMED-C64** ([127](127-community-formats.md) §1) |
| Save bonus | Flat bonus from e.g. a Ring of Protection. | 1 B | Ready a ring of protection. | `DOS-DOC` |
| Magic resistance | Percentage. Absent from PoR-DOS; appears from SotSB. | 0–1 B | — | `DOS-DOC` |
| Movement base / movement current | Base 12 for an unencumbered human. Current drops with encumbrance and armour. | 2 × 1 B | **Pick up 500 coins.** Current moves, base does not. (Our specimen has `0C` = 12 exactly where DOS puts movement base.) | `INFERENCE` (strong) |
| Encumbrance | Total carried weight, 16-bit, in coins (10 coins = 1 lb). | 2 B | Pick up a known number of coins. | `DOS-DOC` |
| Status | 0 okay, 1 animated, 2 tempgone, 3 running, 4 unconscious, 5 dying, 6 dead, 7 stoned, 8 gone. | 1 B | Drop a character to 0 HP. | `DOS-DOC` |
| Enabled / hostile / quickfight | Party-slot bookkeeping flags. | 3 × 1 B | Toggle quickfight in camp — should be a one-byte, one-character delta. | `DOS-DOC` |
| "Modified" flag | Present in PoR/CotAB/SotSB/GttSF; likely a dirty bit. | 1 B | — | `DOS-DOC` |

### 1.5 Thief skills

| Field | Meaning / encoding | Width | Cheapest isolating action | Confidence |
|---|---|---|---|---|
| Pick pockets, open locks, find/remove traps, move silently, hide in shadows, hear noise, climb walls, read languages | Eight consecutive percentage bytes, 0 for non-thieves. | 8 B | Create a thief, `REMOVE` them, and diff against a fighter — eight adjacent non-zero bytes in an otherwise-zero run. Trivially identifiable. | `DOS-DOC`; all-zero in our fighter specimen, consistent |

### 1.6 Money and valuables

| Field | Meaning / encoding | Width | Cheapest isolating action | Confidence |
|---|---|---|---|---|
| Copper, Silver, Electrum, Gold, Platinum | **Five separate 16-bit LE counters**, one per coin type, stored per character (not per party). The C64 editor exposes all five, in that order, at 2-byte spacing. | 5 × 2 B | In camp, use money-sharing / drop exactly 1 platinum. Or buy a torch. | `CORROBORATED-C64` — our specimen holds 120 in the byte pair the editor calls "gold", zero in the other four; consistent with a freshly-created character |
| Gems | **A count of gems**, not a value. Gems are unappraised until sold. | 2 B | Sell one gem at a shop. | `TOOL-CLAIM-C64` |
| Jewelry | Likewise a count. | 2 B | Sell one piece. | `TOOL-CLAIM-C64` |

### 1.7 Spells

| Field | Meaning / encoding | Width | Cheapest isolating action | Confidence |
|---|---|---|---|---|
| Spells **known** | One byte per spell in the game's spell list — PoR-DOS uses 55 bytes covering cleric 1–3 and mage 1–3, in a fixed published order (bless, curse, cure light wounds, … / burning hands, charm person, …). A mage's known spells are a subset; clerics know all. | ~7–55 B | **Scribe one scroll** into a mage's book, or learn one new spell on level-up. One byte, 0 → 1. | `DOS-DOC` |
| Spells **memorized** | Found at `0x020`, a list of ids packed **forward** in descending spell id where DOS fills its 21 slots in reverse. `goldbox/layout.py` declares 16 and the DOS record allots 21 — 21 is also the C64 ceiling (a cleric 6 with wisdom 18 gets 13 slots and a magic-user 6 gets 8, and one character can be both), so 16 may be five short. The most anybody has used is 13, so nothing held contradicts either width. | 16 or 21 B | a cleric/magic-user with more than sixteen spells memorised | **CONFIRMED-C64** as a field, PROBABLE as 16 |
| Castable slots per level | `0x0EE`–`0x0F0`, one byte per spell level, **cleric in the high nibble, magic-user in the low** — the C64 nibble-packs what DOS spends six bytes on. Settled by TANARAKIS (cleric 1 / magic-user 1) on SSI's own shipped party reading `$31`: no single-class specimen could distinguish the packing from two separate bytes. `0x0F1`–`0x0F3` are zero in all 79 records, as expected for a game that stops at third-level spells. | 3 B used of 6 | done | **CONFIRMED-C64** |
| Active magical effects | **Inline, at `0x0AD`, ten slots of one effect code each.** Not a linked list and not a party pool — the C64 dropped DOS's `ADDR_Effect` pointer for a fixed array. `GEN $0BF3` seeds it per race from a table indexed by the race byte, which is why an elf is born carrying 107 and a half-elf 124. **The namespace is named**: 129 codes, 44 CONFIRMED against `MON*` carriers and the *Monster Manual*, 84 PROBABLE from the DOS guide. `goldbox/traits.py`. | 10 B | done | **CONFIRMED-C64** |

### 1.8 Inventory and equipment

| Field | Meaning / encoding | Width | Cheapest isolating action | Confidence |
|---|---|---|---|---|
| Number of items | Count of carried items. | 1 B | Buy a torch. | `INFERENCE` (our specimen holds `01`, and the specimen carries exactly one item's worth of data) |
| Item entries | On DOS these are *pointers* into a separately allocated item chain (63-byte item records). On C64 the item data is **inline in the exported character file** — the C64 editor treats the item area as fixed-size 16-byte slots. | ~15–16 slots | **Buy one distinctive item** (a Long Sword — name token 36 — is ideal because the token value is predictable) and diff. | `TOOL-CLAIM-C64` |
| Item name | **Three vocabulary token bytes** indexing a shared 255-entry name-component table ("Battle Axe", "Hand Axe", …, "Mail", "Padded", …, "+1".."+5", "of", …). DOS reads them high-address→low; the C64 editor does the same. This is the same vocabulary on both platforms — the C64 editor's `DATA` list and marainein's DOS list are the same 255 strings in the same order. | 3 B | As above. | `CORROBORATED-C64` (vocabularies match) |
| Item bonus ("+N") | The `+3` of a Long Sword +3. Wands are stored as +10 for reasons nobody has explained. | 1 B | Buy a +1 weapon, or use the editor's own "+5" trick as a cross-check. | `DOS-DOC` + `TOOL-CLAIM-C64` |
| Readied / equipped flag | C64 editor writes `$80` for readied, `$00` for not. DOS has a "readied" byte plus a separate per-slot equipped-pointer set (weapon, shield, armor, gauntlets, helm, belt, robe, cloak, boots, ring 1, ring 2, arrow, bolt). | 1 B (+ slot table) | **Ready then unready one item.** | `TOOL-CLAIM-C64` |
| Quantity / stack size | For arrows, quarrels, darts. | 1–2 B | Buy 20 arrows, fire one. | `TOOL-CLAIM-C64` |
| Charges | Wands, staves. | 1 B | Use a wand once. | `TOOL-CLAIM-C64` |
| Cursed flag, hidden-name bits, weight, value | DOS item record carries all of these; the hidden-name byte's low 3 bits control which of the three name components are concealed until identified. | 1 B each + 2 B each | Buy an unidentified item. | `DOS-DOC` |
| Item limits | A cap on how many items the character may carry. | 1 B | — | `DOS-DOC` |

### 1.9 Presentation

| Field | Meaning / encoding | Width | Cheapest isolating action | Confidence |
|---|---|---|---|---|
| Combat icon: shape, size, dimensions | DOS keeps `icon head`, `icon body`, `icon size`, `icon dimensions` as small enums. | ~4 B | Use `ALTER` in camp. | `DOS-DOC` |
| Icon colours (body, arm, leg, hair/face, shield, weapon) | DOS packs two colour nibbles per byte, 6 bytes. On the **C64 this is raw screen+colour data**: the 36 bytes at the end of our exported specimen are C64 screen codes ($20 space, $A0 reversed space, $86–$8B) and colour-RAM values ($06 blue, $07 yellow, $08 orange, $0E light blue, $0F grey) — and the *identical* pattern appears in the `SAVEDGAME0` party header at `$4BE0`, followed by six 28-byte repeats of a default icon at `$4C04`, `$4C20`, `$4C3C`, … one per party slot. | ~36 B on C64 | Use `ALTER` in camp to change one icon colour. Should move one or two bytes in that block. | `INFERENCE` (strong — the byte values are unmistakably C64 screen/colour codes) |
| Portrait head / body | Only PoR-DOS has these two. | 2 B | — | `DOS-DOC` |
| Order number | The character's marching/party order. | 1 B | Use `ORDER` in camp to swap two characters. One byte each, two characters. Very clean. | `DOS-DOC` |

---

## 2. Encoding notes (how Gold Box is known to store things)

These are structural habits that hold across the whole series and are therefore reasonable
priors for the C64 build. Each is `DOS-DOC` unless marked.

1. **Money is five separate coin counters**, not a single value: copper, silver, electrum, gold,
   platinum, each an independent 16-bit little-endian count, held *per character*. Gems and
   jewelry are two further 16-bit **counts** (of objects, not of value). Krynn games substitute
   steel/bronze; Buck Rogers uses a single "credit" counter. `CORROBORATED-C64`.
2. **Levels are stored per class, in a fixed eight-byte array** (cleric, druid, fighter, paladin,
   ranger, mage, thief, monk), regardless of the character's actual class. Multiclass is just
   two non-zero entries. The single `class` byte separately encodes which combination it is.
3. **Dual-class** (human) needs a second array — "former level cleric/fighter/…" — which exists
   from CotAB onward. PoR-DOS **does not have it**, consistent with PoR not supporting dual-class.
   Do not expect it in C64 PoR.
4. **Exceptional strength is a separate percentile byte** immediately after CHA, not encoded into
   the STR byte. `CONFIRMED-C64`.
5. **THAC0 is stored, not derived** — and stored twice, "base" and "current". Same pattern for AC
   (base / current / behind), movement (base / current), attacks, and damage dice. Whenever you
   find one of these, look for its twin: an editor that writes only one of the pair produces a
   value that reverts the moment the game recomputes.
6. **Saving throws are five explicit stored bytes**, not computed from class and level. This makes
   them an excellent fingerprint: a level-1 fighter is 14,15,16,17,17; a level-1 mage is
   14,13,11,15,12; a level-1 cleric is 10,13,14,16,15.
7. **Damage is stored as (rolls, dice, modifier) triples, twice over** — Gold Box supports two
   attack forms per character, so every damage-related field appears as a pair.
8. **Spells known and spells memorized are different structures.** "Known" is a flag per spell in
   a fixed published spell order; "memorized" is a list of spell IDs occupying a fixed number of
   slots (21 in PoR-DOS, 84 in CotAB). Slot counts per spell level are yet another small array.
9. **Item names are three tokens from a 255-entry vocabulary**, read from the highest of the three
   bytes down. The vocabulary is shared between DOS PoR and C64 PoR — verified by comparing the
   C64 editor's embedded `DATA` table against marainein's published DOS list: same 255 strings,
   same order, including the blanks at 62/63 and the trailing oddities ("+3 vs Undead", "Cursed").
   Tokens 162–166 are "+1".."+5". `CORROBORATED-C64`.
10. **DOS records are full of 4-byte far pointers** (effects address, items address, next character
    address, combat address, and thirteen equipped-slot pointers). These are memory addresses and
    are meaningless in a file. On the C64 either they are absent, or 2 bytes, or present and
    zeroed. Our specimen has a long zero run exactly where the DOS pointer block falls, which is
    consistent with "present but zeroed on export" — but that is an `INFERENCE`, and it matters,
    because a byte that is always zero is invisible to differential diffing.
11. **Byte order is little-endian on both platforms**, so 16-bit values need no re-thinking.
12. **The name field differs structurally**: DOS is length-prefixed (1 + 15); C64 is a flat
    20-byte NUL-padded buffer with no length byte. This alone shifts every subsequent DOS offset
    by +4 and is the reason the published DOS offsets are useless here. `CONFIRMED-C64`.
13. **Field *order* appears to be preserved across platforms even though offsets are not.** In our
    specimen the sequence `THAC0-base, race, class, age(16-bit), HP-max` appears contiguously in
    exactly the DOS order, as does `save×5, movement-base, level`. The regions *between* those
    landmarks are sized differently (the C64 spell area is much larger than DOS PoR's). Working
    hypothesis: **the C64 record is the DOS record with the same field sequence and different
    region sizes.** If that holds, the DOS field list is not just a checklist but an ordering
    prior — which makes gap-filling between confirmed landmarks a legitimate technique.
    `INFERENCE`, and the single most valuable thing to test in Phase 2.

---

## 3. C64-specific offsets found during this pass

Offsets are byte positions inside the 580-byte exported character record (which the game loads at
`$6B00`, so record offset N = `$6B00 + N`). **All of these still require in-game verification**;
they are listed because they are C64 evidence, not DOS evidence.

| Offset | Field | Source | Specimen value | Confidence |
|---|---|---|---|---|
| `0x00`–`0x13` | Name, 20 B NUL-padded | already known + editor | `BRUTUS` | `CONFIRMED-C64` |
| `0x14`–`0x19` | STR, INT, WIS, DEX, CON, CHA | already known + editor | 18,16,13,14,16,13 | `CONFIRMED-C64` |
| `0x1A` | Exceptional STR percentile | already known + editor | 98 | `CONFIRMED-C64` |
| `0x71` | THAC0 base | position matches DOS ordering | 40 | **CONFIRMED.** The guess was right and this row said "WRONG" for a while, on the reasoning that MALCYON's sheet showed THAC0 20 where the byte reads 39. Both are true: the encoding is `60 - value`, so 40 is THAC0 20. `0x71` is the **base** and roster `+0x0E` is the **current**; the record and the roster each hold one |
| `0x72` | Race | editor | 7 = human | `CORROBORATED-C64` |
| `0x73` | Class | editor | 2 = fighter | `CORROBORATED-C64` |
| `0x74`–`0x75` | Age, 16-bit LE | editor | 21 | `CORROBORATED-C64` |
| `0x76` | HP maximum | editor | 11 | `CORROBORATED-C64` |
| `0x9A`–`0x9E` | Saving throws ×5 | inference | 14,15,16,17,17 (exact fighter-L1 table) | `INFERENCE` (strong) |
| `0x9F` | Movement base | inference | 12 | `INFERENCE` (strong) |
| `0xA0` | **Character level** | editor | 1 | **CONFIRMED-C64.** The doubt was misplaced: on `npc_party.d64` it reads 4, 6, 7 and 8 and equals the per-class level for all eight characters. Every specimen available during this pass was level 1, which is why it looked like a constant |
| `0xBB`,`0xBD`,`0xBF`,`0xC1`,`0xC3` | Copper, silver, electrum, gold, platinum — 16-bit LE each | editor | 0,0,0,**120**,0 | `CORROBORATED-C64` |
| `0xC5`,`0xC7` | Gems, jewelry — 16-bit LE counts | editor | 0,0 | `TOOL-CLAIM-C64` |
| `0xC9`–`0xCC` | Per-class level array — magic-user, cleric, thief, fighter, in `class_bits` order | inference, then confirmed | lone `01` at `0xCC` (fighter) | **CONFIRMED-C64.** Four entries, not eight, and the order follows the bitmask at `0x0EB` rather than the DOS class enum |
| `0xE8`–`0xEA` | Experience, 24-bit LE (editor's "set max" writes `FF FF FF` here) | editor | 0 | `TOOL-CLAIM-C64` |
| `0xED` | HP rolled | inference | 9, and 9 + CON-16 bonus (2) = 11 = HP max ✓ | `INFERENCE` (strong), and the DOS record's `HP_Base` sits at the aligned offset |
| `0xFE`–`0xFF` | ~~Icon colours?~~ **Portrait head and body** — indices into the `HEAD*` and `BODY*` files | later work | `0x2D`, `0x07` | **CONFIRMED-C64.** The colour reading was a coincidence: 8 and 7 are also C64 colour codes |
| `0x100` | ~~Number of items~~ **status** — roster `+0x00`, and record `0x100`–`0x11F` *is* the `SAVEDGAME1` roster block | later work | 1, and `85` on a character knocked down in a driven fight | **CONFIRMED.** Not the item count and not "in use": the game's own seven names, `LIBRARY $38BE` and [`128`](128-guide-and-scripting.md) |
| `0x10D`–`0x11B` | Item data (present in exported file, zero in the in-save slot) | specimen | see below | `INFERENCE` |
| `0x110` + 16·n | Item slots | editor | — | **CONFIRMED**, and the editor was right. 16-byte records; name words at `+3`/`+2`/`+1` (noun, qualifier, suffix), bonus `+4`, readied bit 7 of `+6`, weight `+8`–`+9` in tenths of a pound, quantity `+10`, cost `+11`–`+12` 16-bit. In a *save* the items live in the item area at `$5900` + slot × `$100`, not inline in the record |
| `0x220`–`0x243` | Combat icon: 36 B of C64 screen codes + colour-RAM values; same pattern appears at `$4BE0` in `SAVEDGAME0`, with six per-slot copies following | specimen | `E4 A0 02 6B 04 05 …` | `INFERENCE` (strong) |

### Non-zero bytes in the specimen that nothing above explained — all resolved

These were the highest-information diffing targets, because they were
demonstrably *used*. Every one has since been named:

| byte | value | what it turned out to be |
|---|---|---|
| `0x99` | 01 | **size**, small versus large. Sits at DOS `ICO_Dimension`'s offset and carries `ICO_Size`'s meaning, one lower: 0 for every dwarf, gnome and halfling and 1 for every elf, half-elf and human, in all 79 records |
| `0xD8` | 03 | **alignment**, a 0-based index into the game's own table at `$32B3` |
| `0xD9`, `0xDB`, `0xDD` | 02, 01, 02 | the **attack block** at `0xD9`–`0xE0` — one attack, 1d2 unarmed |
| `0xE1` | 50 | **base armour class**, `60 - AC` = 10 |
| `0xE2` | 22 | **effective strength** — the exceptional-strength bands collapsed to one number. (DOS spends the aligned byte on a boolean `STR_Bonus` instead; two different fields) |
| `0xE6`–`0xE7` | 57 D1 | still **UNKNOWN**, and the one entry here that has not closed. Non-zero and high-entropy in every player character. The DOS record has a single high-entropy per-character byte immediately before experience, which its community documentation calls `MON_Index`, so both ports carry it |
| `0xEB` | 08 | **`class_bits`** — magic-user 1, cleric 2, thief 4, fighter 8 |
| `0x10D`–`0x11B` | — | the **roster block**, not item data: `0x10D` party order, `0x10E` current THAC0, `0x10F` current AC, `0x119` current hit points, `0x11B` encumbered movement |

The old reading of `0x10D`–`0x110` as item name tokens 8 / 42 / 51 / 48 was a
coincidence of plausible values — the items are at `0x120`, sixteen 16-byte
records ending exactly where the combat icon begins at `0x220`.

---

## 4. High-value early targets, ranked

Ranked by *ease of unambiguous verification*, not by usefulness in the final editor. The whole
point is to build a chain of results each of which cannot be misread.

**Outcome.** Targets 1, 3, 5, 7, 8, 9 and 10 are done, though rarely by the route
proposed here — comparing *different characters* turned out to beat before-and-after diffing for
most of them, and the checksum question answered itself when thirteen edited fields were accepted
without complaint. Target 2 (HP current, via one point of damage) and target 6 (order number) are
the two that have still never been attempted, and target 2 is now the single cheapest unrun
experiment on the list.

1. **Platinum (or any one coin type).** Already located to a specific byte pair by a C64 tool, and
   the gold counter is corroborated by our specimen. Pure integer, no derived stats, no
   recomputation on load, and the character sheet prints it. This was the first edit to prove,
   and it was the right one. Verification is visual and total.
2. **HP current, via one point of damage.** One byte, one action, and it distinguishes current from
   max — which is the pattern (`base`/`current` twins) that will bite us everywhere else if we get
   it wrong. Do this before touching anything derived.
3. **Memorized spells, via memorising exactly one spell in camp.** A byte goes 0 → *spell ID*, and
   repeating with different spells reads out the whole ID table for free. Cheap, isolated, and it
   maps a large region (~86 bytes on C64 vs 21 on DOS PoR) that is otherwise entirely dark because
   our only specimen is a fighter.
4. **Thief skills, via `REMOVE`-ing a thief and diffing against a fighter.** Eight adjacent non-zero
   bytes in a sea of zeros. Self-labelling. Also confirms or destroys the field-order hypothesis
   (§2.13) in one measurement, because it pins a second landmark cluster.
5. **AC, via ready/unready a shield.** Distinguishes AC-base from AC-current from AC-behind, and
   tells us whether readying rewrites cached combat stats — which determines whether our editor
   can safely change armour at all.
6. **Order number, via `ORDER` in camp.** One byte per character, two characters, nothing else
   should move. A good sanity check that our diff tooling is not producing noise.
7. **One item purchase (a Long Sword).** Resolves the item record structure, which is the largest
   unmapped region and the one the C64 editor's own claims fail on.
8. **Experience, via killing one monster with a one-character party.** Slightly awkward (XP is
   shared, and combat also moves HP) but it is the field users most want to edit, and 24-bit XP
   has a distinctive multi-byte carry signature.
9. **Ability scores.** Already located; deliberately *not* first, because the interesting question
   is not where STR is but whether the game caches STR-derived hit/damage bonuses elsewhere. Answer
   that with a Potion of Giant Strength diff before writing to STR.
10. **Checksum probe.** Worth doing before trusting any write. Corrupt one
    byte inside the 36-byte icon block at `0x220` — it is demonstrably per-character, demonstrably
    cosmetic, and if the game loads and renders a wrong-coloured icon we have both "no checksum"
    and a confirmed field in one experiment.

---

## 5. Known unreliable — do not chase these

- **Published Gold Box hex-editing offsets (STR at 0x70, class at 0x75, etc.).** DOS only, and
  the C64 layout is its own thing — the DOS documents are a checklist of *which fields exist*,
  never of where they are. Restating because it is the single most common way to waste a day.
  The name field alone differs structurally (§2.12).
- **`Offsets compared.txt` as a "Gold Box layout".** It is twelve *different* layouts side by side.
  PoR, CotAB and SotSB share almost no offset. Read it as a field *catalogue*.
- **The C64 editor's class table is wrong *in part*.** Its `DATA` lists classes 3, 4 and 5 all as
  "magic-user"; by the DOS enum (which its other entries match exactly) they are paladin, ranger
  and mage. But its **multi-class half is right**: codes 8–16 agree with all four multi-class
  values we later derived independently from the bitmask at `0x0EB`, and that table is now the
  documented enumeration. So: take the editor's *offsets* seriously, its multi-class labels
  seriously, and its single-class labels with suspicion.
- **The C64 editor's item slot geometry: half right, and this document was right to distrust
  it.** Items are 16-byte records — that part the editor got correct. But its *base* is wrong,
  and so was the resolution written here earlier. In an export the sixteen item records run
  from **`0x120`** to `0x21F`, ending exactly where the combat icon begins at `0x220`. The
  editor scans from `0x110`, sixteen bytes early, which is precisely the discrepancy this
  section originally flagged between its two loops. Confirmed by finding BRUTUS's banded mail,
  shield and long sword at `0x120` and nothing coherent at `0x110`. In a *save slot* the items
  are elsewhere again, in a separate area at `$5900` + slot × `$100`.
- **The C64 editor writes 581 bytes, not 580.** It saves `$6B00`–`$6D44` inclusive. Our specimen's
  payload is 580 bytes (`$6B00`–`$6D43`). Probably an off-by-one in the editor, but if a
  580-vs-581 discrepancy ever shows up in our own round-trips, this is the precedent.
- **The editor's own readme admits it could not work out THAC0 and AC**, and that its XP handling
  was "too complicated" so it just writes `FF FF FF`. Its silence on a field is not evidence the
  field is absent — and in this case its silence turned out to be *informative*: both fields are
  in the `SAVEDGAME1` roster block, which an exported character does not carry, so no amount of
  work on the export could ever have found them. AC is roster byte `+0x0F` and THAC0 is `+0x0E`,
  both stored as `60 - value`.
- ~~**"Level" as a single byte at `0xA0`.**~~ **Resolved: the editor was right, and this warning
  was wrong.** `0xA0` is character level. On `npc_party.d64` it reads 4, 6, 7 and 8 and matches
  the per-class array for all eight characters. The per-class array does also exist, at
  `0xC9`–`0xCC`; the two are not alternatives. Whether editing `0xA0` alone does anything visible
  is still untested. `wish` keeps the two in step: editing `levels:` carries `0xA0` with it,
  and an explicit `level:` wins.
- **amiga-dev.wikidot's Pool of Radiance project.** Explicitly says "Data File Format: Undetermined
  at this time", last edited 2012. It documents ByteKiller decompression and nothing else. There is
  still no *published* Amiga character-record layout anywhere — **but this project has since
  derived one**: the Amiga record is DOS-**ordered** and **big-endian**, and the Amiga
  `ecl.dax` unpacks to the C64's own scripts. See
  [124-amiga-port.md](124-amiga-port.md). Structure transfers from the Amiga; bytes do not.
- **`CHRDAT?#.*` / `SAVGAM?.DAT` filenames as *C64* names.** Still contradicted by direct
  observation — our C64 save disk uses `SAVEDGAME0` / `SAVEDGAME1` / `<$01>NAME`. What has
  changed is that the names are no longer unsourced: they are the **DOS** release's real
  filenames, read off Donald's own DOS saves, and the engine's own format strings
  `CHRDAT%s%d.SAV` / `SAVGAM%s.DAT` are in the Gold Box Companion binary. The
  write-up that found them, `work/reports/dos-saves.md`, is lost. Right names, wrong port.
- **The Lemon64 claim that "file TEST will be saved as UEST".** One forum post, about a different
  editor release, unexplained. If real it is a filename-mangling bug in that tool, not a property
  of the save format. `WEAK`.
- **A "random treasure generator" producing items absent from the data files.** Stated in GBC's
  item-list notes as the author's "best guess". Interesting, unverified, and irrelevant to us
  unless an item token turns up that we cannot map. `WEAK`.

---

## 6. Sources

- [Gold Box Companion (gbc.zorbus.net)](https://gbc.zorbus.net/) — Joonas Rissanen's tool and
  download index. **High value.** The site itself is thin on detail; its linked archives are the
  substance. Actively maintained through 2021.
- [`formats.zip`](https://gbc.zorbus.net/formats.zip) — per-game character-record field lists for
  all 12 Gold Box games, `Offsets compared.txt`, "still unknown offsets" tables, effect lists, item
  lists. **The single best source in this pass.** DOS-only, derived from live memory, internally
  consistent, and honest about what it does not know. Trustworthy as a semantic catalogue; the
  offsets are DOS.
- [`hackdocs.zip`](https://gbc.zorbus.net/hackdocs.zip) — FRUA file-format documentation from the
  "Hacking UA" community (57 text files: `ITEM.TXT`, `SPELBOOK.TXT`, `SAVGAM.TXT`, `MONSTDAT.TXT`,
  …). Good on FRUA, and FRUA is the closest published relative of the engine, but it is a later
  DOS product; treat as background.
- [Pool of Radiance Character Editor, CSDb release 68820](https://csdb.dk/release/?id=68820) —
  direct download [`poolce.zip`](https://csdb.dk/getinternalfile.php/62150/poolce.zip). **The most
  important find of this pass**: a C64-native, listable BASIC editor that operates on the exact
  580-byte exported record we hold, plus its author's readme. Hobbyist work with visible bugs, but
  every offset in §3 tagged `CORROBORATED-C64` agrees with our specimen, which is strong
  independent confirmation.
- [amiga-dev.wikidot.com — Pool of Radiance project](http://amiga-dev.wikidot.com/project:pool-of-radiance)
  — Richard Tew's reverse-engineering project page. **Low value**: compression routine only, record
  format explicitly undetermined, dormant since 2012.
- [Simeon Pilgrim — Curse of the Azure Bonds project](https://simeonpilgrim.com/blog/curse-of-the-azure-bonds)
  and [github.com/simeonpilgrim/coab](https://github.com/simeonpilgrim/coab) — a .NET
  reimplementation of CotAB built from IDA analysis of the DOS build. Serious, credible work, and
  the origin of some field names other sources reuse (e.g. the item "save bonus" field). Wrong
  game and wrong platform for our offsets, but the right place to look for *engine behaviour*
  questions ("does the game recompute AC on load?").
- [Gold Box Games Forums — "Hacking UA" board](https://forums.goldbox.games/index.php?board=8.0)
  (formerly `ua.reonis.com`) — where the item-format work quoted inside `formats.zip` originated
  (marainein's PoR `.ITM` breakdown, David Knott's `item.dat` format). Primary community source;
  individual posts vary in reliability, and the useful parts are already distilled into
  `formats.zip`.
- [Lemon64 — Pool of Radiance Cheat Help](https://www.lemon64.com/forum/viewtopic.php?t=86685) and
  [Pool of Radiance Char Editor](https://www.lemon64.com/forum/viewtopic.php?t=35270) — pointed us
  at the CSDb editor. No technical content beyond that. Low value on their own.
- Our own `PORSAVE.D64` (`.BRUTUS`, `SAVEDGAME0`) — read-only during this pass. Every
  `CONFIRMED-C64` / `INFERENCE` claim above is checkable directly against it.

## 7. What the web does *not* have

**There is no published C64 Pool of Radiance character-record layout**, and
that changes how we should budget effort. There is no Amiga one either. What exists is (a) an excellent
DOS field catalogue, (b) one 1989 C64 BASIC editor whose author documented roughly twenty offsets
and admitted he could not work out several more, and (c) our own disk. Everything beyond that has
to come from controlled experiment. The good news is that (b) plus our specimen already agree on
every field they overlap on, which is the strongest possible signal that the differential approach
will work — and that the DOS field *ordering* is a usable prior for guessing where to
look next.

**That last sentence is the one to keep, and it came in.** Three further DOS
sources have arrived since this pass and none of them names a C64 offset — but
used as a *lens* on the field ordering, together they named `0x0D7`, corroborated
the attack block and base armour class, said what the eight bytes after
roster `+0x10` are, settled the saving-throw rule and half the thief-skill one,
and supplied the 127-entry effect namespace. They have their own write-ups:

| source | doc |
|---|---|
| the Gold Box forums — playtester mode, DOS area tables, tooling | [126-forum-findings.md](126-forum-findings.md) |
| `GB_FileFormat.xlsx` / `GB_Extract.xlsx`, the ten-title format workbooks | [127-community-formats.md](127-community-formats.md) |
| Stephen S. Lee's DOS guide and Draxinusom's ImHex patterns | [128-guide-and-scripting.md](128-guide-and-scripting.md) |

Both of the "needed a browser" items §8 of `126` lists as unreachable have since
been obtained.
