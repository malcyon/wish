# The differential rewrite, and the fields it cannot promise

Editing a DOS character today means converting the save to the C64, editing it,
and converting it back -- two conversions, and every field either of them
cannot carry perfectly is a field the player loses on the way there and back.
`#511 (Open a DOS save folder and an Amiga save disk in the Character Editor,
so editing a DOS character does not mean two conversions)` removes them, and
this page is the measurement its first stage rests on.

The editor's sheet binds to the C64 record and will keep doing so. What
changes is what happens when the player presses Save on a DOS or Amiga party.
**Nothing converts the character back.** The port's own writer renders the
character twice -- once from the record as it was read, once from the record as
the sheet left it -- and only the field spans where the two renderings disagree
are copied onto the bytes the engine wrote. `goldbox/rewrite.py` is that, and
`tools/convert/rewritecensus.py` is what measured it.

Two things follow. A save with no edit in it is byte-identical **by
construction**, because a span the two renderings agree about is never copied.
And an untouched field keeps the engine's own bytes whatever the writer would
have made of them -- which matters, because the writer and the engine do not
agree about everything, and the rest of this page is where.

## What was measured, and on what

664 characters, every one this machine can reach: 79 DOS save folders (72
specimens under `$WISH_SPECIMENS`, 7 save directories in the DOS archives), 15
Amiga `.adf` images and 14 loose Amiga Curse and Silver Blades saved games.

| port | title | characters |
|---|---|---|
| DOS | Pool of Radiance | 216 |
| DOS | Curse of the Azure Bonds | 96 |
| DOS | Secret of the Silver Blades | 78 |
| Amiga | Pool of Radiance | 130 |
| Amiga | Curse of the Azure Bonds | 52 |
| Amiga | Secret of the Silver Blades | 92 |

Nothing was skipped: the tool reports what it could not read and reported
nothing. **Pools of Darkness is out of the census** for two independent
reasons -- the five `pod-dos` specimens hold no `CHRDAT??.SAV` at all, and the
title has no C64 port, so `c64_port.by_key` refuses it and the editor will not
open one.

Two measurements were taken of each character.

**The no-op rewrite.** Rewrite it with nothing edited and compare with the
bytes it came from. **664 of 664 came back byte for byte** -- record, item
file and effect file, all three, `tools/convert/rewritecensus.py --no-op`.
CONFIRMED. The effect file is compared because it was not before: the sweep
returned it unread, so "byte for byte" covered two of the three things a save
is made of.

**The round trip of the unedited character.** Convert it to the C64 record the
sheet edits, render it straight back through the port's own writer, and
compare field by field with the record the engine wrote. A field that differs
here is one an edit to which would replace the engine's answer with the
writer's.

The second measurement is the census, and two further columns make it usable.
**Rendered** says whether the writer produced more than one value for that span
across every character of that title: a span it rendered *one* value for over
all 216 DOS Pool of Radiance characters is one the two renderings a rewrite
compares can never disagree about, so no edit can move it, however far it is
from the engine's byte. **Writer says** is the writer's own account of where it
takes the field from, `goldbox.dos_codec.write_targets`.

## The census

### DOS Pool of Radiance -- 216 characters

| field | characters | rendered | writer says |
|---|---|---|---|
| `portrait_body` | 204 | one value | zero |
| `portrait_head` | 204 | one value | zero |
| `heap_104` | 179 | one value | zero |
| `effect_chain` | 135 | one value | zero |
| `thac0_current` | 130 | varies | from neutral |
| `encumbrance` | 85 | varies | derived |
| `item_chain` | 67 | one value | zero |
| `save_breath` | 63 | varies | from neutral |
| `save_paralysis` | 58 | varies | from neutral |
| `save_petrification` | 58 | varies | from neutral |
| `save_spell` | 58 | varies | from neutral |
| `save_wands` | 58 | varies | from neutral |
| `hands_used` | 50 | one value | zero |
| `attack_level` | 18 | one value | from neutral |
| `item_count` | 1 | varies | computed |

### DOS Curse of the Azure Bonds -- 96 characters

| field | characters | rendered | writer says |
|---|---|---|---|
| `unnamed_0ab` | 94 | varies | derived |
| `heap_104` | 70 | one value | zero |
| `effect_chain` | 52 | one value | zero |
| `save_petrification` | 24 | varies | from neutral |
| `thac0_current` | 19 | varies | from neutral |
| the eight `thief_*` | 14 each | varies | from neutral |
| `save_paralysis`, `save_spell`, `save_wands` | 13 each | varies | from neutral |
| `thac0_base` | 11 | varies | from neutral |
| `name_text` | 5 | varies | from neutral |
| `char_class` | 4 | varies | from neutral |
| `item_chain` | 4 | one value | zero |
| `attack_level` | 2 | varies | from neutral |
| `encumbrance` | 2 | varies | derived |
| `hands_used` | 2 | one value | zero |
| `save_breath` | 2 | varies | from neutral |
| `spells_castable_cleric`, `spells_castable_magic_user` | 1 each | varies | from neutral |

### DOS Secret of the Silver Blades -- 78 characters

| field | characters | rendered | writer says |
|---|---|---|---|
| `unnamed_0ab` | 78 | varies | derived |
| `heap_104` | 60 | one value | zero |
| `effect_chain` | 33 | one value | zero |
| `save_paralysis` | 26 | varies | from neutral |
| `save_breath`, `save_petrification`, `save_spell`, `save_wands` | 13 each | varies | from neutral |
| `name_text` | 10 | varies | from neutral |
| `name_length` | 6 | varies | from neutral |
| `item_chain` | 4 | one value | zero |
| the three `spells_castable_*`, `thac0_base`, `thac0_current` | 1 each | varies | from neutral |

### Amiga Pool of Radiance -- 130 characters

Every field has an Amiga span. `field_83_87` used to have none, because the
second insertion had not been located inside the run it straddles and
`amiga_por_offset` refused it; the insertion is now located (the money pad at
0x089), so the field is a five-byte span at 0x084 and no port has an unplaced
field.

| field | characters | rendered | writer says |
|---|---|---|---|
| `heap_104` | 75 | one value | zero |
| `attack_level` | 61 | one value | from neutral |
| `effect_chain` | 56 | one value | zero |
| `item_chain` | 26 | one value | zero |
| `hands_used` | 25 | one value | zero |
| the five `save_*` | 22 each | varies | from neutral |
| `thac0_current` | 12 | varies | from neutral |
| `thac0_base` | 8 | one value | from neutral |
| four `thief_*` | 6 each | varies | from neutral |
| `thief_read_languages` | 4 | one value | from neutral |
| `encumbrance` | 2 | varies | derived |
| `thief_find_traps` | 2 | varies | from neutral |
| `name` | 1 | varies | from neutral |

### Amiga Curse of the Azure Bonds -- 52 characters

| field | characters | rendered | writer says |
|---|---|---|---|
| `unnamed_0ab` | 42 | varies | derived |
| `effect_chain` | 34 | varies | zero |
| `heap_104` | 32 | one value | zero |
| `item_chain` | 18 | varies | zero |
| `hands_used` | 16 | one value | zero |
| `save_paralysis` | 16 | varies | from neutral |
| `save_spell`, `save_wands`, the eight `thief_*` | 12 each | varies | from neutral |
| `spells_castable_magic_user` | 7 | varies | from neutral |
| `save_petrification` | 6 | varies | from neutral |
| `thac0_current` | 4 | varies | from neutral |
| `spells_castable_cleric` | 3 | varies | from neutral |
| `thac0_base` | 2 | varies | from neutral |
| `encumbrance` | 1 | varies | derived |

### Amiga Secret of the Silver Blades -- 92 characters

| field | characters | rendered | writer says |
|---|---|---|---|
| `unnamed_0ab` | 83 | varies | derived |
| `heap_104` | 67 | one value | zero |
| `effect_chain` | 42 | varies | zero |
| `save_paralysis` | 30 | varies | from neutral |
| `save_spell`, `save_wands` | 20 each | varies | from neutral |
| `name` | 12 | varies | from neutral |
| `save_breath`, `save_petrification`, the three `spells_castable_*` | 4 each | varies | from neutral |
| `item_chain` | 2 | varies | zero |

## What the differences are, sorted

**The live heap, and it costs nothing.** `heap_104`, `item_chain`,
`effect_chain` and `hands_used` are addresses and combat state the engine
allocates on load; the writer puts zero there and says so. On DOS and Amiga
Pool of Radiance the writer rendered one value for all of them across every
character, so no edit on the sheet can move them and the engine's own pointers
survive any save. **On the two later Amiga titles `effect_chain` and
`item_chain` do vary**, because `AmigaCharacter.block_bytes` makes each chain
head non-zero exactly when a node follows -- which is the loader's own test and
is the right value, not a stale one.

**The sheet portrait, on DOS Pool of Radiance, 204 of 216.** The rewrite passes
no portrait tables, because opening a save must not need the player's C64 game
disks, so the writer leaves `portrait_head` and `portrait_body` zero. One value
across all 216, so no edit reaches them and every character keeps its own face.
The cost is that the portrait cannot be edited on a DOS party, not that it is
lost.

**The recomputes: the five saving throws, `thac0_base`, `thac0_current`, the
eight thief skills, the `spells_castable_*` arrays, `attack_level`,
`char_class`.** These are fields the writer computes from the class levels and
the ability scores through the destination's own tables rather than copying.
Where they differ, the engine's stored byte and our recompute disagree --
usually because the engine wrote the value at a different moment in the
character's life and never refreshed it (`docs/205-the-c64-thac0-rebuild.md`
and `docs/210-the-later-titles-dos-thac0.md` are the two worked cases). The
differential keeps the engine's byte until the player edits something the
recompute depends on, and then the writer's answer lands.

**`encumbrance`, and `item_count`.** Both are computed rather than copied, and
both are meant to be recomputed after an item or money edit. `item_count`
differs from the engine's byte on exactly 1 of 216 DOS Pool of Radiance
characters, which is a record whose stored count and item file disagree --
ours is the file's.

**Neither may be taken from the writer, and that is the one place the
differential is not enough.** Both count what the character carries, and both
renderings see only the sixteen items the C64 record has slots for. On a
character carrying twenty, a player who deletes one item makes the two
renderings say sixteen and fifteen, the differing span is copied, and the
record then says fifteen over an item file of nineteen nodes -- and every
reader trusts the count (`dos_codec.read_character`, `amiga_por.por_character`),
so the next read returns fifteen items and the other four are gone. So
`goldbox.rewrite` writes the count from the nodes it actually wrote, and only
when that number changed, which leaves the stale-count record above untouched
by a save with no edit in it.

Encumbrance is the same arithmetic and the fix is measured rather than
chosen. The one character on this machine carrying more than sixteen items is
`WISH-SPEC-por-item-twenty/G` WISHFTR, 20 items: its stored encumbrance is
**180**, its money is 140, and the weight of all twenty items is 40 -- so the
engine's own total counts the four the sheet cannot see, where the sixteen
visible ones sum to 172. The rewrite therefore adds the hidden items' weight
back to the encumbrance the writer computed, whenever it copies that span at
all. Sample size one, because there is one such character; the direction is
corroborated by the engine's own routine, which walks the item chain and not
the first sixteen of it (`.claude/rules/testing.md`, the encumbrance
identity).

**`unnamed_0ab`, the identity byte, and it is the one to argue about.**
`goldbox.dos_codec.identity_byte` digests every *other* byte of the record, so
**any edit at all moves it** on the two later titles, which are the ones that
write it. It differs from the engine's byte on 94 of 96 DOS Curse, 78 of 78 DOS
Silver Blades, 42 of 52 Amiga Curse and 83 of 92 Amiga Silver Blades
characters, because the engine drew its byte at random at creation and ours is
a digest. The engine reads it for one thing: telling two characters of the same
name apart when one is being added to the party. So the cost of moving it is
that two same-named characters whose bytes were distinct could collide, at
about one chance in 256 per edit; the benefit is that the same save converts to
the same bytes twice running. **This is a question for Stage 2, not a defect**:
the alternative -- never copying this span, so the engine's own random byte
survives every edit -- is a one-line change and a decision about what the byte
is for.

**The name, folded to capitals.** `dos_codec.c64_name` upper-cases a name on
the way into the C64 record, because a lower-case letter is not a letter in the
C64's own character set. A DOS or Amiga character called `Guy de Valois`
therefore renders as `GUY DE VALOIS`, and an edit to the name would write the
capitals. It reached 5 of 96 DOS Curse, 10 of 78 DOS Silver Blades, 12 of 92
Amiga Silver Blades and 1 of 130 Amiga Pool of Radiance characters -- the ones
with a lower-case letter or a space in the name. The sheet's name field is
disabled, so no player can reach this today.

## The read-only candidates for Stage 2

A field belongs on this list when it both differs from the engine's bytes and
the writer rendered more than one value for it, which is the necessary
condition for an edit to be able to move it. It is a candidate list rather than
a verdict: rendering more than one value across characters does not prove the
*sheet* can reach it, only that the writer's output depends on its input.

| port and title | candidates |
|---|---|
| DOS Pool of Radiance | `encumbrance`, `item_count`, `save_breath`, `save_paralysis`, `save_petrification`, `save_spell`, `save_wands`, `thac0_current` |
| DOS Curse of the Azure Bonds | `attack_level`, `char_class`, `encumbrance`, `name_text`, the five `save_*`, `spells_castable_cleric`, `spells_castable_magic_user`, `thac0_base`, `thac0_current`, the eight `thief_*`, `unnamed_0ab` |
| DOS Secret of the Silver Blades | `name_length`, `name_text`, the five `save_*`, the three `spells_castable_*`, `thac0_base`, `thac0_current`, `unnamed_0ab` |
| Amiga Pool of Radiance | `encumbrance`, `name`, the five `save_*`, `thac0_current`, five `thief_*` |
| Amiga Curse of the Azure Bonds | `effect_chain`, `encumbrance`, `item_chain`, the four `save_*`, `spells_castable_cleric`, `spells_castable_magic_user`, `thac0_base`, `thac0_current`, the eight `thief_*`, `unnamed_0ab` |
| Amiga Secret of the Silver Blades | `effect_chain`, `item_chain`, `name`, the five `save_*`, the three `spells_castable_*`, `unnamed_0ab` |

**Most of them are not fields the sheet edits directly**, and that is the
distinction Stage 2 has to make: the saving throws, the thief skills and the
THAC0 pair are recomputed from class and ability, so what a player edits is the
class level or the score, and the recompute is the thing whose answer replaces
the engine's. Marking the *recomputed* field read-only does nothing, because
nobody types into it. What has to be decided is whether an edit to a class
level on a DOS party is allowed to rewrite five saving throws the engine has
been happy with.

## The fields an edit cannot reach at all, measured

The table above is about fields whose *engine* bytes a rewrite would replace.
This one is the other question, and it is the one the editor needs: **which
fields of the C64 record can a player type into and lose?** It is measured
rather than inferred -- `tools/convert/rewritecensus.py --read-only` adds one
to each field of the record in turn, at its first byte and at its last,
rewrites, and reports whether a byte of the save moved. 12 characters of each
port and title, 72 in all.

DOS Pool of Radiance is the baseline row and the other five are written
against it, which is shorter than six lists and says the same thing.

| port and title | read-only on all 12 | writable on some characters and not others |
|---|---|---|
| DOS Pool of Radiance | 29: `attack_level`, `char_class`, `dual_class_level`, `dual_class_slot`, `flags_0b8`, `infravision`, `item_effects`, `level_knight`, `missile_attack_adjustment`, `portrait_body`, `portrait_head`, `spells_known_high`, `strength_bonus_flag`, `strength_index`, `thac0_base`, `turn_class`, `turn_power`, and the twelve `gap_*` and `region_*` runs | 9: `thac0`, the eight `thief_*` |
| DOS Curse of the Azure Bonds | 28: that list without `dual_class_level`, `dual_class_slot` and `spells_known_high`, and with `gap_06c` and `identity_pair` | 11: `dual_class_slot`, `level_paladin`, `spells_castable`, the eight `thief_*` |
| DOS Secret of the Silver Blades | 27: DOS Curse's without `gap_01b` | 3: `dual_class_slot`, `level_ranger`, `spells_castable` |
| Amiga Pool of Radiance | 28: DOS Pool of Radiance's without `portrait_head` and `portrait_body`, and with `treasure_share` | 9: `thac0`, the eight `thief_*` |
| Amiga Curse of the Azure Bonds | 29: DOS Curse's with `dual_class_slot` | 1: `spells_castable` |
| Amiga Secret of the Silver Blades | 28: DOS Silver Blades' with `dual_class_slot` | 1: `spells_castable` |

**The sheet portrait is read-only on five of the six**, and writable only on
Amiga Pool of Radiance. That is the same fact as the census's `portrait_head`
and `portrait_body` rows read from the other end: the rewrite passes no
portrait tables, so the writer renders zero for both whatever the sheet says.

**A field writable for one character and not another is the class showing
through**, not an inconsistency: `level_paladin` moves on a DOS Curse paladin
and nothing else, the eight `thief_*` fields move on a thief, and
`spells_castable` moves on a caster.

**Nothing in this measurement was refused for an illegal value**: 0 of 72
characters had a field where every fuzz raised something other than the
rewrite's own refusal. The fuzz is +1 on one byte, so it is a lower bound on
what a player can reach -- a field it could not move is read-only for that
value, and a field it moved is writable for certain.

**An edit that reaches nothing is refused rather than written.**
`goldbox.rewrite.patch` raises `RewriteError` when the two records differ, the
item file did not change, and no span of the port's record moved. Before that,
such an edit was written as a save that changed nothing and reported no
trouble, so the player's value came back unedited on the next read with
nothing anywhere saying why. `RewrittenDos.moved` and `.unplaced` are the
other half of it: what landed, and what this port's span map has no offset for
at all.

## What was not established

* **Nothing here was loaded in a running game.** Bytes matching is necessary
  and not sufficient (`.claude/rules/conversions.md`). Nothing on this page
  proves a rewritten save boots; the no-op case writes the same bytes, so it
  cannot fail, but an edited one has not been through DOSBox or WinUAE.
* **The effect files are returned exactly as read**, on all three ports. The
  sheet's ten trait slots are not wired to the DOS effect nodes, so nothing
  can edit them yet; that is the plan's Stage 5.
* **The Amiga Curse item node has no measured size on some titles.**
  `AmigaDeltas.item_size` is `None` where no specimen carries an item, and
  the rewrite then has no item spans to compare. No specimen in the census hit
  that, so it is untested rather than broken.
* **A character carrying more than sixteen items** keeps the ones past the
  sixteenth exactly as read, because the C64 record has sixteen slots and the
  sheet shows no more. One DOS specimen carries 20, and it drove that rule and
  the count and encumbrance arithmetic above. What the player sees is that the
  extra items are neither shown nor lost. **No Amiga character on this machine
  carries more than sixteen**, so the Amiga half of that rule is held up by
  generated records rather than by any save an engine wrote.
* **A slot whose item is replaced gets a freshly rendered node**, because
  patching the old node would leave the deleted item's engine-only bytes --
  its cached display line and its chain pointer -- under the new item's name.
  The test is the first four bytes of the C64 block, `type_index` and the
  three name words. **Whether the engine repaints that cached line when it
  loads a save is unconfirmed**: the line is known to go stale in saves the
  engine itself wrote, which is why no reader here trusts it, but nobody has
  watched a running game redraw one.
* **`.CHA` exports were not swept.** The census reads save slots, which is what
  the editor will open.
