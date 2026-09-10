# The regained dual class on the C64, and the mask Curse cannot name

`#409 (A regained dual-classed paladin or ranger has a class mask Curse's own
table cannot name, so Wish shows him a class he is not)`, the C64 half.
`docs/209-the-regained-dual-class-on-dos.md` is the other one, and the two
ports do not agree.

**In one line: a C64 Curse paladin can change class and get the paladin back,
the mask that leaves is one `GEN $1951` has no code for, and the game's own
character sheet calls him `CLERIC/PALADIN` — both classes, the way it draws a
multi-classed character.**

## What the engine wrote

Driven on 2026-09-08 with `tools/cursepaladin.py` off
`WISH-SPEC-curse-trained-party`, on a pooled VICE slot, twice from the same
staged disk.

| | MATHEW | MARK |
|---|---|---|
| before | human paladin 6, lawful good, `class_bits` `$40` | human paladin 5, lawful good, `class_bits` `$40` |
| `HUMAN CHANGE CLASSES` to | FIGHTER | CLERIC |
| after the change | `class_bits` `$08`, `level_fighter` 1, `dual_class_slot` **6**, `dual_class_level` 6, `char_class` 6, `level` 1, experience 0 | `class_bits` `$02`, `level_cleric` 1, `dual_class_slot` **6**, `dual_class_level` 5, `char_class` 5, `level` 1, experience 0 |
| after one training | fighter 7 | cleric 6 |
| **`class_bits` `0x0EB`** | **`$48`** fighter + paladin | **`$42`** cleric + paladin |
| `level_paladin` `0x0CF` | 6, restored | 5, restored |
| `char_class` `0x073` | 6 | 5 |
| `thac0_base` `0x071` | 46 | 44 |
| the sheet's class line | `FIGHTER/PALADIN`, `LEVEL 7/6` | `CLERIC/PALADIN`, `LEVEL 6/5` |

**Reproduced, 2 of 2**: a second boot from the same staged disk gave every
field identically except `hp_rolled`, 47 against 45 and 41 against 43 — the
hit die, which is the only random part of a training.

SHARA, an untouched human cleric 6 in the same party and the same boot, draws
`CLERIC` and `LEVEL 6`, so the two-class line is not something the sheet gives
everybody.

**What was staged, and it is named in the run's own log.** MARK's wisdom, 16 to
18, in both ability arrays, because `GEN $2442` wants 17 in the new class's
prime requisite. **MATHEW needed nothing**: strength 18 already clears the
fighter's 17. Then, after the change and before the training, the new class's
level array entry, `level`, experience and platinum — which turns six presses
into one, `GEN $2086` clamping the experience after every one. Everything in
the table's lower half is the engine's own.

## Which pairs a player can reach, and it is decided by alignment

`GEN $2377` is the handler; `docs/176-changing-class-twice.md` has its four
gates. What decides the *pairs* is one table and two thresholds.

**`GEN $23F3`, nine bytes, indexed by `alignment` at `0x0D8`**, handed to the
class picker at `$0ABA`:

| alignment | mask | offered |
|---|---|---|
| 0 lawful good | `$CB` | magic-user, cleric, fighter, paladin, ranger |
| 3 neutral good, 6 chaotic good | `$8F` | magic-user, cleric, thief, fighter, ranger |
| the other six | `$0F` | magic-user, cleric, thief, fighter |

The picker drops any entry sharing a bit with his current `class_bits`
(`$0AE1 AND $7CEB`) and any his race cannot have (`$0AD0`/`$0AD6`; paladin and
ranger are human-only). **CONFIRMED twice in the running game**: PHILIPPE, a
lawful-good magic-user, was offered CLERIC, FIGHTER, PALADIN and RANGER
(`docs/172-curse-trainer.md`), and MATHEW, a lawful-good paladin, was offered
CLERIC, FIGHTER, RANGER and MAGIC-USER.

**Two ability thresholds, and both are 1st edition's.** `GEN $23FC` walks the
*old* class's prime requisites at 15, before the pick; `GEN $2442` walks the
*new* class's at **17**, after it — by which point `$0B4D` has rewritten the
level array from the new mask, so the scan for "the highest non-zero class
slot" finds the new class. The three tables at `$242A`, `$2432` and `$243A`
give the paladin strength and wisdom and the ranger strength, intelligence and
wisdom, and the six-by-eight table of minimums at `$246D` is the rulebook's to
the byte (paladin charisma 17, ranger constitution 14).

So of the seven pairs `GEN $1951` cannot name:

| pair | mask | route |
|---|---|---|
| cleric + paladin | `$42` | **driven** — a lawful-good paladin takes CLERIC (wisdom 17) |
| fighter + paladin | `$48` | **driven** — a lawful-good paladin takes FIGHTER (strength 17) |
| magic-user + paladin | `$41` | a paladin takes MAGIC-USER, or a lawful-good magic-user takes PALADIN, which is an offer PHILIPPE actually got |
| fighter + ranger | `$88` | a good ranger takes FIGHTER, or a good fighter takes RANGER |
| magic-user + ranger | `$81` | a good ranger takes MAGIC-USER |
| thief + ranger | `$84` | a neutral- or chaotic-good ranger takes THIEF, `$8F` carrying `$04` |
| thief + paladin | `$44` | **no route through this menu.** A paladin is lawful good and `$CB` has no thief bit, so he is never offered THIEF. The other direction would need a lawful-good thief; the creation-time filter has not been read, so that half is PROBABLE rather than CONFIRMED |

Two are CONFIRMED by a record the engine wrote; the other four are
PROBABLE — the table, the thresholds and the regain are the same code for all
of them, and nobody has driven one.

## The regain itself, and `dual_class_slot` 6

`GEN $20A3` has no class test in it:

```
$20A3  LDA $7CBA / BEQ         not dual-classed
$20A8  CMP $7CA0 / BCS         the new class has not passed the old level
$20AD  LDX $7CB9 / STA $7CC9,X class_levels[old] = the old level
$20B3  LDA $0B82,X / ORA $7CEB / STA $7CEB
```

`$0B82` is `01 02 04 08 10 20 40 80`, so the paladin's slot 6 gives `$40` back
and the ranger's slot 7 `$80`. **`dual_class_slot` at `0x0B9` can hold 6**;
until this run the only value anybody had seen there was 0, PHILIPPE's
magic-user.

## Nothing on the C64 reads `char_class`

`tools/absrefsweep.py` over all 412 files on the six Curse sides finds
**one** absolute-mode reference to `$7C73` in the whole title, and it is a
store: `GEN $194D`. There is no load anywhere, so the byte is invisible to the
C64 game and matters only to Wish and to a conversion.

What it holds for a dual-classed character is two instructions:

```
$1939  LDA $7CBA / BNE $194B    dual_class_level; non-zero means dual-classed
$194B  LDX #$03
$194D  STA $7C73               ... and A is still dual_class_level
```

**So every dual-classed C64 Curse character stores the level he left his old
class at**, whatever his classes. MATHEW's 6 and MARK's 5 are that, and MARK's
5 is also the magic-user's class code — which is how a cleric/paladin comes to
show as a magic-user in Wish's Class box.

## What Wish shows today

| | MATHEW `$48` | MARK `$42` |
|---|---|---|
| roster column, `editor/roster.py`'s `class_name` | `72` | `66` |
| Class box, `editor/window.py`'s `_char_class_shown` | THIEF | MAGIC-USER |
| `goldbox.c64_port.classes_to_names` | fighter, paladin | cleric, paladin |

`editor/enums.py`'s `class_bit_names` builds the sixteen combinations of the
classic four and then adds `$40` and `$80` alone, on the reasoning that "a
paladin, a ranger or a Knight of Solamnia is single-class". This is the case
that is not. **It has no row for `$82` either** — cleric + ranger, which
`GEN $1951` *does* name (code 10) — so that mask shows as `130`, and the Class
box then calls it `cleric/magic-user`, because `editor/enums.py`'s
`CHAR_CLASS` is Pool of Radiance's code table and Curse's code 10 is not Pool
of Radiance's.

**What the Class box and the roster column should say is Donald's**, and the
three candidates are both classes (what the C64 sheet draws), the class he
changed into (what the DOS engine stores, `docs/209-the-regained-dual-class-on-
dos.md`), or something else. Only what they show today is certainly wrong.

## What is not settled

* **The creation-time alignment filter has not been read**, so "a lawful-good
  thief cannot exist" rests on the change routine's table and on the rulebook
  rather than on the game's own creation screen. It is the only thing between
  `$44` and PROBABLE-unreachable. The experiment: find what creation ANDs the
  alignment against — it is not `GEN $23F3`, whose only reader is `$23B7`, and
  not `$0ABA`, whose only caller is `$23BA`.
* **No ranger has been driven.** Both driven characters are paladins, so the
  `$80` half of the family is read out of `$0B82` and `$23F3` and not watched.
* **Whether a converted `$42` record loads and draws the same sheet** — this
  page's records were made in the game, not converted into it.
