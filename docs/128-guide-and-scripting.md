# The DOS guide and the UA scripting files

Two community sources, mined for what a C64 project can use.

* **`por-guide.txt`** — *AD&D Forgotten Realms Vol. I: Pool of Radiance,
  Exhaustive Game Information*, v2.00 (2 April 2026), by **Stephen S. Lee**
  (`ssjlee9`), on GameFAQs, CC BY-NC 4.0. Written for **PC v1.3**. Sections
  12-13 are not a walkthrough at all: they are a reverse engineering of the DOS
  build, with the character record, the item and effect tables, the ECL
  instruction set, a 229-entry script-flag map and a bug list.
* **`GoldBox/`** — a community archive by **Draxinusom**: ImHex binary patterns
  for the whole Gold Box family (`GB_GEO`, `GB_CHR`, `GB_ITM-*`, `GB_EXE`,
  `GB_VLT`, `GB_UA_SCRIPT`), plus `GB_UA_SCRIPT.xlsx` / `SCRIPT.GLB` for
  *Unlimited Adventures* and `GB_Palette.xlsm`.

Working copies under `work/scratch-guide/` (gitignored). Assertions harvested
from both live in [`../tests/test_uascript.py`](../tests/test_uascript.py),
which reads the player's disks and skips without them.

**Everything below is DOS work until a C64 file says otherwise.** Where a claim
has been checked against our own disks the check is named; where it has not, it
is PROBABLE at best.

---

## Lead: the guide's GBVM address list *is* our character record

Guide §12.4.2 lists the GBVM addresses the ECL scripts name. Our own
(now-lost) `work/reports/quest-flags.md` §7 established that **the ECL bytecode, absolute
operands included, is one artefact shared by every port** — the Amiga `ecl.dax`
unpacks to the C64's own scripts, and DOS and C64 *Curse* differ only in a
script's 2-byte header. So an address the DOS scripts use is an address our
scripts use, and the character record answers to a fixed `$6B00`.

That turns §12.4.2 into a field list for `goldbox/layout.py`. Twenty entries land on
fields we already had, at the same offsets, which is corroboration we did not
have before. **Six land inside gaps.** All six were then checked against the
`MON*` records on the player's disks:

| offset | our name before | what it is | evidence |
|---|---|---|---|
| `0x0D7` | `gap_0d7` | **creature type** — humanoid, undead, giant, regenerating… | CONFIRMED. 116 `MON*` records take 13 distinct values and every one is inside the DOS enumeration; TROLL reads 10 (regenerating), MUMMY 4 (undead). 5, 6 and 13 never occur — the same three the enumeration omits |
| `0x0F7`-`0x0F8` | inside `gap_0f4` | **experience awarded for defeating** (u16) | CONFIRMED. GOBLIN GUARD 10, HOBGOBLIN 20, OGRE 90 — the AD&D 1e values exactly. Zero in every player export |
| `0x0F9` | inside `gap_0f4` | **bonus experience per hit point** | CONFIRMED. 1, 2, 5 for the three above — again the published table |
| `0x10C` | inside `gap_101` | **combat behaviour**: 0 allied and controlled, 128 allied and uncontrolled, 129 hostile | CONFIRMED. 115 of 116 `MON*` records read 129; one reads 128 |
| `0x0B8` | `flags_0b8` | bit 7 not-a-PC (which we had), **bits 0-6 morale** | PROBABLE. 111 monsters read `$FF`, five read 178; the DOS rule is `(value - 128) / 2` for an NPC's morale |
| `0x100` | `roster_in_use` | **status**: 0 out of play, 1 okay, 128 + status otherwise | PROBABLE, and richer than "in use". Every `MON*` reads 1; every save slot reads 0 |

Two more come from the DOS record layout rather than the GBVM list, and the
disks agree:

* **`0x0A1`/`0x0A2` read `$FF` on every monster.** The DOS record says
  "normally 0 for PCs, 255 for anything else" of exactly those two fields. Our
  `levels_drained` / `hp_lost_to_drain` naming survives, with the sentinel
  explained. CONFIRMED.
* **`0x0D9`-`0x0E0` is eight fields, not four two-entry arrays.** DOS order is
  primary attacks ×2, secondary attacks ×2, primary dice, secondary dice,
  primary sides, secondary sides, primary bonus, secondary bonus. TROLL reads
  `04 02 01 02 04 06 04 00` = two 1d4+4 claws and one 2d6 bite, which is the
  Monster Manual. That is the same decode `goldbox/layout.py` already records, seen
  column-first instead of row-first; both readings are right and the DOS one is
  the engine's own.

### The class-level array is permuted between the ports

DOS orders `0x0C9`-`0x0D0` cleric, druid, fighter, paladin, ranger, magic-user,
thief, monk. **The C64 orders it magic-user, cleric, thief, fighter, druid,
monk, paladin, ranger** — which is `goldbox.items.CLASS_USAGE_BITS`, i.e. the bit
order of the item-usability mask `CLASSRESTRICTION`. So the C64 indexes the
level array by `class_bits` bit position and DOS does not.

CONFIRMED from `party6_savedgame0.bin`: a magic-user's level sits at index 0, a
cleric's at 1, a fighter's at 3, and Lady Katherine (magic-user/thief) carries
both 0 and 2. That promotes four PROBABLE labels in `goldbox/layout.py` and gives
them a reason. Two consequences:

* **`0x0CD` is the druid slot in Pool of Radiance, not the knight slot.** The
  Krynn games put the knight there. `0x0CE` is monk. Both unused here.
* **A DOS→C64 save conversion must permute this array.** `docs/117` should say
  so.

### The rest of the record

The DOS record is 285 bytes and ours is 580, so it is not a relabelling. But
the *field order* is the same from `LVL_Sweep` onward, and once the money block
is aligned the two run in step. That makes these PROBABLE readings of gaps we
have never opened, offered as a work list rather than as findings:

| C64 offset | DOS field | note |
|---|---|---|
| `0x0B7` | unknown, "always 255 for monsters" | `$FF` in all five C64 `MON*` records too; both ports fill it and neither reads it |
| `0x0B9`-`0x0BA` | unknown, "always 0 for monsters" | **settled since, and not by them**: the dual-classed human's old class slot and old level, written by Curse, Silver Blades and Gateway and unreferenced in Pool of Radiance (`#224`). Their "always 0 for monsters" is the one place the ports differ — the C64's monster records hold `$FF` here, 70 of 70 in Curse |
| `0x0E2` | strength-bonus-applies flag | we call it `strength_index` |
| `0x0ED` | maximum hit points before Constitution and `M`odify | we call it `hp_rolled`; the reading matches |
| `0x0EE`-`0x0F3` | three cleric then three magic-user spell counts | on the C64 these are **nibble-packed**, cleric high, magic-user low (`goldbox/layout.py` already has this) — another place the C64 halved a DOS field |
| `0x110` | current 60 − armour class **from behind** | see below |
| `0x111`-`0x118` | current attack form, eight fields mirroring `0x0D9` | see below |

**`goldbox/savegame.py`'s roster names look wrong.** It calls roster `+0x10`
`ARMOUR_BONUS`, `+0x11` unknown, `+0x15` `EQUIPMENT` ("rises with what is
readied") and `+0x17` `DAMAGE_BONUS`. Against the monster records those are:
`+0x10` = 60 − rear armour class (TROLL 54 → AC 6, against 56 → AC 4 from the
front), `+0x11`/`+0x12` = attacks remaining ×2, `+0x13`-`+0x18` = current dice,
sides and damage bonus for the two attack forms. `+0x15` is *primary attack die
sides*, which is exactly why it rises with what is readied, and `+0x17` really
is the damage bonus. PROBABLE, and worth a pass by whoever owns that file.

---

## The ECL instruction set: sixty-two for sixty-two

Guide §12.3.3 lists the same 62 opcodes we derived from the VM's own dispatch
tables in `DUNGEON` (the write-up, `work/reports/ecl-opcodes.md`, is lost), with the same mnemonics and
the same operand counts. No disagreement anywhere. The guide adds semantics we
had not derived:

| opcode | what the guide adds |
|---|---|
| `$05 SUB` | the **subtrahend comes first**: the result is `var2 - var1` |
| `$06 DIV` | dividend first; the remainder is discarded (kept in *Curse*); no division-by-zero trap |
| `$08 RANDOM` | 0 to `var` **inclusive**, capped at 255 |
| `$0A LOADCHAR` | index ≥ 128 puts monster `index - 128` on the party's side; zeroing `$6B00` and `$6C00` afterwards removes it. Pool of Radiance has no `DUMP`, which is how it manages without one |
| `$1F` | **unimplemented.** Our table called it `ADDRESSOF`, a name inherited from the `coab` table. No Pool of Radiance script uses it — our own sweep counts 0 references — so the name was a guess and is withdrawn (P57); the opcode table, `work/reports/ecl-opcodes.md`, is lost, but it left `$1F` unnamed before it went |
| `$24 COMBAT` | the whole side-channel: `$6DC6` morale, `$6DC7` result (0 won, 128 lost, 129 ran), `$6DC8` kills, `$6DE2` temple instead, `$6E6C` shop instead, `$6E70`-`$6E72` THAC0 and movement modifiers |
| `$27 TREASURE` | last operand: 0-127 a treasure list, 128-254 that many minus 128 random magic items, 255 none |
| `$2D CALL` | the five recognised targets, all no-ops otherwise: `$2C90` redraw, `$8000` clone duel, `$8001` monster fight, `$BA03` sound, `$C018` refresh wall, `$C01E` step forward ignoring barriers |
| `$2E DAMAGE` | the full bit layout of `<attack>` and `<var>`: bit 128 single roll, bit 64 whole party, bit 32 no save, low 5 bits save bonus, `var` low 3 bits the save type |
| `$34 ECLCLOCK` | **broken**: it advances by the value of an uninitialised byte, not by its operand. Fixed in *Curse*. Used once in the whole game |
| `$38 PROGRAM` | 0 training hall (class mask in `$6DA8`), 8 win game, 9 camp; anything else a no-op |
| `$3B SPELL` | **never does anything.** Fixed in *Curse*. Used once |

Two structural facts worth carrying:

* **Every script begins with five entry addresses**, and the guide names them:
  `vm_run_1` (a step), `search_location` (a step or `L`ook), `pre_camp_check`,
  `camp_interrupted`, `initial_entry` (after loading a script or a game). We
  have been calling the last one "entry 4".
* **The script region is `$9900`-`$B6FF`, 7680 bytes**, and scripts routinely
  come close to it. Same base as ours.

### A latent bug, from the other side

The guide lists six opcodes a false `IF` fails to skip: `SETUPMON`, `VERTMENU`,
`ONGOTO`, `ONGOSUB`, `HORIZMENU`, `ADDNPC`. We found three from a different
direction — `$1625`, the VM's operand-count table, disagrees with its own
handlers for `SETUPMON`, `ENCMENU` and `ADDNPC`. The two lists overlap on two
entries and are otherwise complementary: the guide's four extras are the
variable-length opcodes, whose length the skip routine cannot know at all.

Neither list fires: no shipped script puts an `IF*` immediately before any of
them. **The union is seven opcodes** -- `SETUPMON`, `ENCMENU`, `ADDNPC`,
`VERTMENU`, `ONGOTO`, `ONGOSUB`, `HORIZMENU` -- and it is filed as `N2` in
`docs/125-bug-notes.md`, a latent engine defect with two independent
derivations.

---

## The script-flag map: our boundaries, their meanings

Guide §12.4.1 names 229 addresses in `$4A00`-`$4AF9`. Our
(now-lost) `work/reports/quest-flags.md` derived the same region from the C64 bytecode
without it. The agreement is exact where it can be:

| claim | ours | theirs |
|---|---|---|
| lower boundary of the persistent block | `$4A20`, from `DUNGEON $202A` zeroing `$4A00`-`$4A1F` | "`$4A00`…`$4A1F` are reset to 0 every time a new ECL script is loaded" |
| upper boundary | `$4AF8` — no operand in thirty scripts names anything above it | highest named flag is `$4AF8`; `$4AF9`…`$4AFF` "unknown" |
| unreferenced gaps | `$4A53`-`$4A58`, `$4A6E`-`$4A71`, `$4A79`-`$4A7B`, `$4AA3`-`$4AA5`, `$4ADC`-`$4ADF` | the same five ranges, all "unused" |
| `$4A72` | "exists only as the casualty" of a bug in `ECL07 $A81C` | "mistakenly set in Valjevo Castle Inner Tower; never checked" |
| `$4A6D` bit 4 | can never be set, because `OR [$4A6D], 16, [$4A72]` writes to the wrong place | bit 16 is "Tyranthraxus defeated"; §13.2 lists "the game script does not properly flag Tyranthraxus as defeated" |
| `$4A90`-`$4A95` | graveyard paid-so-far, proven as a table interior | "`$4A8F`…`$4A95` Valhingen Graveyard undead kill reward trackers" — one byte wider |

**The Tyranthraxus row is the single strongest corroboration in either source.**
Two people, two ports, two methods, one flag.

What the guide adds is the part we could not get from bytecode: **what each flag
means in the story.** Our report attributes 172 addresses to scripts; the guide
names 229 in English. Merging them is a cheap, high-value job for whoever next
touches `goldbox/commissions.py` or the Quest Log. It also fills `$4A00`-`$4A1F`,
the per-script scratch page, which we deliberately left alone: the guide lists
each of those 32 bytes with the different meaning every area gives it.

DOS stores these as 16-bit words (save offset `(addr - $4A00) * 2 + 0x201`); the
C64 stores them as bytes. Addresses transfer, widths do not.

---

## The area table: five names and one deletion

Guide §12.3.1 lists every script by number. Against `goldbox/areas.py`:

| id | ours | the guide | verdict |
|---|---|---|---|
| 3 | Valjevo Castle, a floor | Valjevo Castle (Northwest and Southeast) | name it |
| 4 | Valjevo Castle, a floor | Valjevo Castle (Northeast) | name it |
| 5 | Valjevo Castle, a floor | **Valjevo Castle Hedge Maze** | name it |
| 6 | Valjevo Castle, a floor | Valjevo Castle (Southwest) | name it |
| 7 | Valjevo Castle, the pool | Valjevo Castle (Inner Tower) | both fine |
| 11 | the arena | **Civilized Area (Training Hall)** | ours was wrong, and is fixed (P61). `ECL0B` prints "the room is filled with duelling pairs" — that is the training hall's practice floor, not Podol Plaza's arena |
| 19 | Cave of Diogenes | Silver Dragon Lair | same place; Diogenes is the dragon |
| 24 | Temple of Bane | **Wealthy Area** (with the Temple of Bane as its second map) | ours names the wrong one of its two maps |
| 30 (`ECL1E`) | unnamed; we found it is the attract-mode demo | **script 30 does not exist on DOS** | see below |

It also explains our doubled maps outright. DOS numbers maps and scripts in one
space, and three maps have no script of their own:

| map | belongs to script |
|---|---|
| `GEO1E` (30) | 16, Lizardman Keep — it is the **catacombs** |
| `GEO1F` (31) | 24, Wealthy Area — it is the **Temple of Bane** |
| `GEO20` (32) | 29, Kuto's Well — it is the **catacombs** |

Which settles `ECL1E`. DOS has no script 30; the number is a map. **The C64 port
put a script there, and it is the attract-mode demo** — a port-specific addition
in a slot the original numbering left free. That is a better answer than "an
unnamed area" and it is consistent with everything we already found.

Arithmetic check: 33 numbered slots, minus 12 which does not exist, minus 8, 11
and 19 which are scripts with no map of their own, is 29 — the number of `GEO`
files on our disks.

---

## Items: two new fields in `ITEMS`, and a rule we got by accident

`GB_ITM-Base.hexpat` describes the base-item table as **128 records of 16
bytes**, which is our `ITEMS` exactly, and names two bytes `goldbox/items.py` does
not:

| offset | field | checked on our disks |
|---|---|---|
| `+7` | **damage type**: 0 slashing, 1 piercing, 128 bludgeoning | CONFIRMED. Only those three values occur. Clubs, maces, flails, hammers, morning stars and both quarterstaves read 128; daggers, darts and javelins read 1 |
| `+14` | **weapon flags**: bit 0 needs arrows, bit 1 ranged, bit 2 add strength bonus, bit 3 multi-shot, bit 4 throwable, bit 7 needs bolts | CONFIRMED. Every weapon with a range carries bit 1 or bit 4; the bows carry bit 0; one record carries bit 7; the **sling** carries bit 1 with neither launch bit nor the thrown bit, which is the case the pattern says the encoding exists to express |

`+8` is 0 or 128 and both sources call it unknown. `+15` is zero throughout.

**The protection byte is `60 - AC` with bit 7 set, not a nibble.**
`goldbox/items.py` reads body armour as `12 - (byte & 0x0F)` under a `0xB0` mask and
a shield as `byte & 0x0F` under `0x80`. The engine's rule is `bit 7 = it grants
protection` and the low **seven** bits hold the same biased `60 - value` the
record uses for THAC0 and armour class everywhere else. The two agree on every
armour on the disks — plate `$B9` → AC 3 through leather `$B4` → AC 8 — and
diverge at AC 13 or worse, or at a shield bonus above 15. The general rule is
the one to keep. `tests/test_uascript.py` asserts they still agree.

The 16-byte C64 item record is the DOS 17-byte record with one byte removed:
DOS keeps *equipped*, *name-hiding flags* and *cursed* as three separate bytes
at `+6`, `+7`, `+8`; the C64 packs equipped and the hiding flags into `+6` and
keeps cursed at `+7`. Everything from `+8` on is DOS shifted down by one, which
is why `goldbox/items.py`'s existing offsets all line up.

### The effect table is ours

Guide §12.2.3 enumerates **127 effect ids**. That is the namespace our
`work/reports/effects.md` decoded structurally without ever getting names for
the monster half; the write-up is lost, though a fuller live table of the
same namespace's meanings is `goldbox/traits.py`. Three spot checks, all from `goldbox/items.py`'s own notes:

| our note | the guide |
|---|---|
| "85 … 'drains one level' on a wight" | 85 melee level-draining attack (1 level) |
| "the gauntlets carry 38" | 38 extra strength |
| "the ring 61" | 61 wearing Ring of Fire Resistance |
| "the cloak 89" | 89 displaced |

Four for four. **Transcribing that list is the single cheapest large win
available from either source** — it names the whole `0x0AD` trait region and the
item `+14` namespace at once, and the split we observed (spell effects below 64,
monster traits from 64) is visible in the guide's own ordering. Our range runs
to 139 and the guide's stops at 127; the tail needs checking.

---

## Spells: our grouping confirmed, our tail is different

`GB_ENUM.cs`'s `SPL_NAME01` gives ids 1-56 for the DOS build, and the group
boundaries are `goldbox.spells.SPELL_GROUPS` byte for byte — cleric 1 at 1-8,
magic-user 1 at 9-21, cleric 2 at 22-28, magic-user 2 at 29-35, cleric 3 at
36-44, magic-user 3 at 45-55, Restoration at 56. CONFIRMED, independently.

**Past 56 the ports part company.** DOS continues to 67 with item-invoked
effects — Potion of Speed, Javelin of Lightning, Wand of Paralyzation, Manual of
Bodily Health. The C64's `SPELLN00` continues instead with combat message
fragments: `IS CHARMED`, `TURNS TO STONE`, `POINTS OF DAMAGE`. Read off the
player's disks and asserted. So a DOS memorised-spell byte in 57-67 has no C64
spell id, which matters to `docs/117`.

The guide's §8 spell descriptions and §7.8-7.13 (THAC0, armour class, saving
throws, turning, morale, party strength) are prose versions of the tables we
have generated; the class sections' experience thresholds and level caps match
`docs/89-level-tables.md` exactly where checked (cleric 1,501 / 3,001 / 6,001 /
13,001 / 27,501, cap 6; spells per level 1, 2, 2·1, 3·2, 3·3·1, 3·3·2).
Training is 1000 gold or 200 platinum a level, in New Phlan only.

---

## Commissions: ten for ten

`goldbox.commissions.MAJOR` — the ten quests that advance the tracker — is
`{0, 1, 10, 11, 12, 13, 15, 16, 17, 21}`. The guide lists the same ten in
English: slums, Sokal Keep, the Podol Plaza auction, Kovel Mansion, nomads,
kobolds, the river, lizardmen, the graveyard, Norris the Gray. Exact match, and
we derived ours from bytecode.

**Lead on ledger 22**, the one entry `goldbox/commissions.py` has as `(None, None)`.
The guide lists a "clear Podal Plaza" reward that is distinct from commission 4
(discover the auction item = our ledger 10) and pays the same 200 platinum and
250 gold as the other clearance rewards. That is the shape of a ledger entry
nothing offers. Worth one `TREASURE` cross-reference in `ECL12` to settle.

The guide also gives every commission's exact reward in coins, gems, jewelry and
experience. Those are `TREASURE` operands in our decoded scripts, so the whole
list is checkable mechanically — a good self-contained job.

---

## Candidate rumours for `docs/125-bug-notes.md`

**Filed** as `R40`-`R51` in [`125-bug-notes.md`](125-bug-notes.md) (P59),
together with the `STING` negative. All are DOS reports, none has been
reproduced on the C64 unless noted, and **none may be promoted into
`goldbox-bugs.md`** without our own reproduction.

**Confirmed present on our disks already:**

1. **The bec de corbin is flagged slashing** (`ITEMS` +7 = 0). AD&D makes it a
   bashing or piercing weapon. Read straight off `ITEMS`.
2. **The military fork, ranseur and trident are flagged slashing** too. Same
   byte, same check.

**Engine and script defects that should transfer, because the bytecode does:**

3. `$23 SURPRISE` applies its four modifiers to the wrong sides; harmless with
   no modifiers, which is the usual case.
4. `$22 PARTYSURPRISE` does nothing special for a ranger and mis-sets one of
   its two variables.
5. `$28 ROB` never restores the item-loss chance while walking one character's
   inventory, so putting heavy items first sharply reduces theft. It also
   steals equipped items.
6. `$34 ECLCLOCK` advances the clock by an uninitialised byte.
7. `$3B SPELL` is a no-op.
8. A false `IF` fails to skip eight opcodes (above). Latent; nothing fires it.
9. Valjevo Castle Inner Tower never flags Tyranthraxus as defeated — already
   ours, from `ECL07 $A81C`.
10. Sokal Keep's dead elf guard, Podol Plaza's twice-lootable buccaneer, the
    Cadorna family treasure openable twice, Valhingen Graveyard's transposed
    treasures at locations 12 and 24, Stojanow Gate's alarm that starts nothing.
    All script-level, all checkable statically against our own decode.
11. Going south from Wealthy Area (4,15) crashes; fleeing the bugbear patrol
    after the tower guards crashes. Worth trying on the C64.

**Exploits:**

12. Targeted damage spells raise the dead: a dead character has 0 hit points and
    a spell doing under 10 leaves them dying rather than dead. Still present in
    *Curse*, gone in *Silver Blades*.
13. The item-duplication loop through save-and-reload in the training hall.
14. Constitution 22 or 0 gives out-of-range hit points per level.

**A negative worth recording:** the DOS cheat mode, started with the argument
`STING` (Ctrl-C quit, Alt-X win combat, `J` free training, protection bypassed),
**has no C64 counterpart.** The literal `STING` appears on all eight `POOL`
disks and every occurrence is inside the word `CASTING`. Checked.

---

## What Unlimited Adventures actually gives us: less than hoped

**`SCRIPT.GLB` is not a scripting VM.** It is the *design tool's* user interface,
serialised: an `HLIB` container of 58 records, 15 of them empty, each a stack of
pages of form fields, with a field's `Store: u8` / `Store: u16` / `Store: Bit` property naming
the byte or bit of the record the field edits. `GB_UA_SCRIPT.xlsx` decodes it
completely — field types, property types, validation checks, control types,
every enumeration, and a bit-by-bit map of the 20-byte event record for 38 event
types. `UA-SCRIPT_ChangeLog.txt` is a mod's change list against it.

So UA is **not** a Rosetta stone for our ECL opcodes, because UA does not use
ECL. SSI replaced the bytecode with a fixed-form 20-byte event record per map
square, and the map file carries the events and strings itself (`GB_GEO.hexpat`
treats UA's `GEO###.DAT` as an entirely separate 12962-byte format). UA's 38
event types are a level *above* our opcodes: `Combat` is `LOADMON` + `SETUPMON`
+ `COMBAT`, `Question_List` is `VERTMENU`, `Chain` is `GOSUB`.

Three things do transfer, and they are worth having:

* **The biased encoding is named and generic.** The editor's `SetACTHAC0`
  control "converts AC/THAC0 value saved to/displayed from Gold Box's standard
  format (base 60)". Our `60 - value` is the family's own convention, described
  as such by two sources.
* **The condition vocabulary matches our quest flags.** UA's `CONDITIONTYPE`
  offers quest complete / failed / in progress, special item true / false, day,
  night, facing, searching, class in party, race in party — which is the set of
  tests our ECL scripts hand-assemble out of `AND` and `IF<>` against
  `$4A20`-`$4AF8`. It is a good vocabulary for a quest panel.
* **A cost vocabulary.** `COSTFACTOR` — free, ÷100 … ×100 — is how UA expresses
  a shop or training price. `TrainingHall` drops ÷3 and ÷1.5 from the list "so
  the numbers divide cleanly", which incidentally says the base training cost is
  1000, matching the guide.

**`GB_Palette.xlsm`** is two 256-entry RGB tables, EGA and VGA. No use to a C64
project except one thing: the character record's icon-colour nibbles index
*this* palette on DOS and the VIC-II palette on ours, so it is the conversion
table `docs/117` would need if it ever carried icon colours across.

---

## The ImHex patterns: what they cover

`ImHex-Patterns.zip` extracts to seven `.hexpat` files and six `.cs` includes.
Each supports all ten Gold Box titles by detecting the game from file size, and
each is a working parser, which makes it a more precise statement of a format
than prose.

| pattern | covers | to us |
|---|---|---|
| `GB_GEO` | maps for all ten titles | **our four-plane decode, confirmed.** Cell data "split into 4 blocks, with each cell having 1 byte in each block"; plane 0 north/east wall nibbles, plane 1 south/west, plane 2 event id in bits 0-6 and indoors in bit 7, plane 3 two bits per direction. Wall nibble 1-15 selects one of three wall sets of five slices — our `SLICES_PER_WALLSET = 5` — and "wall sets are specified in the ECL file". The guide's §12.2.5.1 prose describes the same file as an array of 4-byte records, which is wrong; the pattern is right and agrees with us |
| `GB_CHR` | character and monster records, all ten titles | the DOS 285-byte record in full, used above |
| `GB_ITM-Base` | the 128 × 16 base-item table | used above |
| `GB_ITM-Record` | carried-item records: 17 bytes standard, 63 in a DOS save | used above |
| `GB_EXE` | **~50 rule tables inside the DOS executable** | a checklist of tables to look for on our disks: XP per level, spells per level, THAC0 per level, base saves per level, hit-dice type and count per class, class money, class item mask, class alignment, race ability minima and maxima, race age ranges and per-class age formulas, race class lists, thief skill per level, thief skill Dexterity and race modifiers, Constitution HP modifier, turn-undead table, random-item array, money conversion, time conversion, and a 16-byte `SpellBase` record (class, level, range base and per-level, duration base and per-level, combat area, camp area, save action, save type, **effect id**, castable where, casting time, AI priority, AI minimum targets). Our own `ECL65` spell table is 67 records of **7** bytes, so the C64 compressed this — the DOS field list is the menu of what our five undecoded bytes could be |
| `GB_VLT` | the vault | **Pool of Radiance and Curse have no vault.** Nothing to do |
| `GB_UA_SCRIPT` | `SCRIPT.GLB` | above |

Barrier value 3, which `goldbox/geo.py` calls `WIZARD_LOCKED`, is "hard-to-open
barred door" in the guide and "locked, unpickable" in the pattern. Neither
source connects it to a wizard lock. The name is ours and should probably go.

---

## What is not here

* **The guide's §12.6** — 5,500 lines of DOS executable and overlay code
  analysis, address by address. Read past for structure only. Nothing in it is a
  C64 address and translating it is not worth the time; it is a place to look
  something up, not to mine.
* **§10.2, the bestiary** — 1,900 lines of per-monster statistics. Our `MON*`
  records carry the same numbers and we can read them, so the guide's value here
  is only its names and its notes on which monsters are miscategorised.
* **§14.1 journal entries, §6 walkthrough detail** — the game's own text and
  somebody else's writing. Out of scope by the repository rules.
* **`GB_Extract.xlsx`, `GB_FileFormat.xlsx`, `GB_CopyProtection.xlsx`** — in the
  same archive, assigned to another agent.
* **`GB_ENUM_IMG.cs`** — 911 lines of DOS image-asset names. Not read.
