# An Amiga Curse or Silver Blades party, into the neutral record and back into a saved game

Steps 3 and 4 of `#28 (Decode an Amiga saved game, not just a character file)`.
Step 3 is done and rests on the code; step 4 is done as far as bytes can take
it and **stops one measurement short**, which is at the end of this page.

`docs/165-amiga-savegame.md` has the container and `docs/166-amiga-records-from-the-code.md`
the record. Everything here is a file offset into `/Curse` on Curse of the
Azure Bonds disk 1 or `/Secret` on Secret of the Silver Blades disk 1, read
with `tools/amiga68k.py` and `tools/amigaenum.py`.

## The status word: both later Amiga titles number the nine states DOS's way

**CONFIRMED, two binaries, two different mechanisms and three independent
measurements.** `goldbox/neutral.py`'s `STATUS_NAMES` is the Amiga's table as
well, so `status` crosses by name with nothing to translate — which is not
what `#235 (Two unattributed DOS byte ranges in the combat tail are dropped
converting to C64, and nobody knows what they hold)` found between DOS and the
C64, where the two enumerations agree
nowhere but "okay" and two values are swapped outright.

The byte is the **first byte of `field_10c_10f`** in both titles, the same
field DOS Pool of Radiance keeps its status in at `0x10C`:

| | status byte | the byte after it | DOS offset |
|---|---|---|---|
| Amiga Curse | `0x19A` | `0x19B` | `0x195` |
| Amiga Silver Blades | `0x143` | `0x144` | `0x1A6` |

Three routines agree that those are separate fields rather than one four-byte
block: each title's record unpacker copies them **one byte at a time** where it
uses a `movmem` for a run (`tools/amigaunpack.py`), and the panel routine below
reads each on its own.

### 1. The party panel indexes a nine-entry table with it

`/Secret` `0x196EA`, and `/Curse` `0x1A38E` is the same routine compiled twice:

```
tst.b   $144(a2)          ; $19b(a2) in /Curse
bne     -> "(Helpless)" / "(Casting)"
move.b  $143(a2), d0      ; $19a(a2) in /Curse
```

Silver Blades scales the byte to a longword and reads a `char *` table at file
offset `0x4F9B8` — `Okay`, `Animated`, `tempgone`, `Running`, `Unconscious`,
`Dying`, `Dead`, `Petrified`, `Gone`. Curse hands the byte to a helper at
`0x352E8` that fetches block `status + 0x2C` of text library `0x13`, which is
`DISKA/STRINGS.GLB`: blocks 44 to 52 are the same nine states in the same
order, with DOS's own `Stoned` where `/Secret` says `Petrified`, and block 53
is `Battle Axe`, so the run ends where it should.

`tools/amigaenum.py` reads both back; `tests/test_amiga.py` asserts both.

### 2. Every constant either binary stores in the byte is inside the nine

`move.b #n, status(An)` finds `1, 4, 5, 6, 7, 8` in `/Curse` and `3, 4, 5, 6`
in `/Secret`, and both also clear it. Eight of the nine values are written
somewhere; only `tempgone` (2) never is. Nothing outside `0`-`8` is ever
stored, which is what says the table has nine entries and not more — the
pointer array itself does not delimit, since entry 9 is simply the next string
in the pool.

### 3. The engine's own consistency rule names the byte after it

`/Curse` `0x1B776` and `/Secret` `0x1ABB6`, again the same routine:

```
tst.b   $19a(a2)          ; status
beq     -> ordinary
cmpi.b  #$1, $19a(a2)     ; animated counts as ordinary too
beq     -> ordinary
clr.b   $19b(a2)          ; the flag
clr.b   $1a9(a2)          ; hp_current
```

So `field_10c_10f`'s second byte is **cleared whenever the status leaves okay
or animated**, and the panel draws the status word only where it is zero. That
is DOS Pool of Radiance's `active` flag's polarity at DOS's own offset, and the
neutral read carries it as `active` at **PROBABLE**: what is CONFIRMED is the
rule above, and what is inferred is that this is the same concept as "the game
has taken this character out of the party". It reads 1 in 10 of 10 characters
in the two saved games, which is the ordinary state and says nothing either
way.

**And a third byte gets a shape.** `field_10c_10f`'s byte 2 — Amiga Curse
`0x19C`, Silver Blades `0x145` — is read **only while the game mode is 5
(combat)** and used as an index: `/Curse` `0x1B794` into a byte array at
`g3E2A`, `/Secret` `0x1ABD4` into a *word* array at `g5436`, where it
decrements the entry. So it is a combat-roster index rather than the constant
DOS's own records make it look like. `docs/141-dos-savegame.md`'s DOS `0x10E`
at the same offset is now CONFIRMED as **the combat side**, 0 the party's and
1 the enemy's, indexing a two-entry per-side count that a combatant's defeat
decrements ([`docs/169-dos-combat-side.md`](169-dos-combat-side.md)) — the
same shape as this Amiga index, and why it reads zero in every
engine-written player record: a fight the party lost is never saved.
PROBABLE as "an index into a per-combatant array",
CONFIRMED as "read only in combat".

## What reaches the neutral record

`goldbox.amiga.to_neutral` now takes an `AmigaCharacter` as well and hands it
to `to_neutral_later`, which reads the record through
`goldbox/dos_layout.py`'s table **for that title**, at each field's own
confidence grade. It does not go through `goldbox.dos.to_neutral` the way the
Amiga Pool of Radiance reader does: that one raises `WrongTitleError` for
anything but Pool of Radiance, because no other pair of ports has been measured
against each other (`#53 (Read and write DOS saves for Curse, Silver Blades and
Pools of Darkness)`).

`goldbox.amiga.later_field_disposition` states what becomes of **every** field
of the title's DOS table, and `tests/test_amiga.py` fails if one is named
nowhere. All 21 specimens on this machine read without an exception: the
fifteen Curse records and the six Silver Blades ones.

Carried by a rule rather than a copy:

| neutral field | how |
|---|---|
| `name` | the sixteen NUL-padded bytes, where DOS has a count byte and fifteen |
| `spells_known` | Curse's 100 one-byte flags; Silver Blades' 15 bytes of bitmask, least significant bit first |
| `spells_memorised` | the non-zero ids reversed, DOS's own order |
| `levels` | `class_levels` permuted from class number to class name, eight slots on Curse and seven on Silver Blades |
| `former_levels` | `former_class_levels` permuted the same way, **non-zero entries only** — `{}` for a character who never dual-classed, not eight zero entries (`#256 (The neutral record has nowhere to put a dual-classed character's former levels)`) |
| `spells_castable` | each array at the **Amiga's** width — six bytes on Curse where DOS spends five, seven on Silver Blades |
| `size_small` | the size byte less one |
| `status` | a name out of `STATUS_NAMES`, above |
| `active` | the flag above, PROBABLE |
| `granted_effects` | every effect node at duration zero, each re-cut to the nine bytes a DOS `.SPC` record holds |
| `inventory` | each 66- or 70-byte item node re-cut to DOS's 63 and projected onto the shared sixteen |

### What it cannot say, and it is a classification rather than a byte

**Which effect records are innate and which an item granted.**
`goldbox.dos.INNATE_EFFECTS` is Pool of Radiance's id space and must not be
applied here: 107 is an elf in Curse where Silver Blades' PAINE carries 105 for
a ranger, so the two later titles do not share one namespace even with each
other. So everything at duration zero goes into `granted_effects` whole, graded
**PROBABLE**, and the read carries a warning saying so. GALAIN's single node is
id 107 — an elf, and therefore racial rather than an item's grant, which is
exactly the misfiling the warning is about.

**What would settle it**: the routine each title runs when a character is
created, which is where a racial effect is added. `/Curse`'s import of a Pool
of Radiance `.spc` keeps exactly eighteen ids and that list is already in
`goldbox/dos.py`; the equivalent for a Curse character created in Curse has not
been read.

### The two fields the read drops with a reason

**`former_class_levels` is no longer here.** Until `#256 (The neutral record
has nowhere to put a dual-classed character's former levels)`'s first step it
was dropped outright, saying there was nowhere to put it; `goldbox/neutral.py`
now has `former_levels`, and it is read into that, non-zero entries only --
see the table above. The byte after `level` was an unnamed gap until the same
step named it `former_level`; `later_field_disposition` now accounts for it
as one more field the array's permutation already covers, without this
reader reading it a second time -- that is the DOS reader's own disagreement
check, on `goldbox/dos.py`'s side of the pair.

* **`portrait_head` and `portrait_body`** — a position in the Amiga's own
  creation menu. `#57 (Convert the character portrait across ports)` read DOS's menu tables out of `START.EXE` and that is
  what let the portrait cross; nobody has read `/Curse`'s or `/Secret`'s.
* **`spells_castable_unattributed`** — Silver Blades' fourth slot array, which
  no character of either port sets a byte of.

The rest of the drop list is live heap state and combat icon art, and
`goldbox.amiga.LATER_DROPPED` names each one.

## Writing: what the format takes, and what nobody has watched it take

### The chain pointer is a boolean, and getting it wrong desynchronises the file

**CONFIRMED from the loader, both titles** — `/Curse` `0x25056`, `/Secret`
`0x268C0`:

```
read(fd, record, 0x1AC)          ; 0x154 in /Secret
tst.l   $152(a0)                 ; $fe(a0) in /Secret -- the item chain head
beq     no items
alloc(&record[0x152], 0x42)      ; overwrites the value it just tested
read(fd, record[0x152], 0x42)
a3 = record[0x152]
loop:
tst.l   $2a(a3)                  ; the node's own next pointer
beq     done
alloc(&a3[0x2a], 0x42); read(...); a3 = a3->next
```

and the effect chain the same way from `$F2(a0)` / `$96(a0)`, ten bytes a node,
next at node offset 6. **The stored pointer's value is never dereferenced**:
`alloc` overwrites it before the `read` that fills the node. `item_count` at
record `0x150` / `0x0FC` is not consulted by the loader at all.

So a saved game must carry a non-zero head where nodes follow and a zero one
where they do not. This is not cosmetic: every character is read from one file
descriptor in sequence, so a head left NULL in front of a node that is really
there leaves the stream mid-block and every later character in the party comes
off it misaligned. It is the **opposite** of the Pool of Radiance rule, where
`.itm` and `.spc` are separate files and the chain is rebuilt from the file's
length, so `write_por` writes NULL and this must not.

Corroborated on **21 of 21 records** off the shipped disks, independently of
the code: a non-zero head exactly when a node follows, a non-zero `next` on
every node but the last, and zero on the last. The addresses step by 66 along
an item chain and by 10 along an effect chain, which is what a heap of those
node sizes looks like.

`goldbox.amiga.AmigaCharacter.block_bytes` sets the three chain fields and
`item_count` to match what actually follows, and leaves a field whose truth
already matches alone — so a block read out of a saved game and written back is
byte for byte the block that came in.

### Two more things the loader does that a writer can rely on

* **`clr.l $192(a0)` and `clr.l $18E(a0)` after the chains** (`/Curse`
  `0x251AC`). Those two longwords are Amiga Curse's `heap_104`, and the record
  unpacker leaves them zero as well — two routines agreeing that zero is the
  right thing to write.
* **Silver Blades drops scroll spells past a cap of 120 at load time**
  (`/Secret` `0x269C2`, against a party-wide sum from `0x23AC8` of `quantity`
  over every item whose type index is `0x49`). A party over the cap loses them
  silently. CONFIRMED as a cap and a discard; what a player sees is UNKNOWN.

### The party region

`tools/amigasavegame.py`'s `rebuild` writes a new party into a saved game. The
party region is the **last** thing in a Curse or Silver Blades file — both
specimens end exactly where the last block does — so the output is the header
up to the count, the count as a `u16be`, and the blocks. Two bytes in front of
the count move and no others: the party-size word `$503E`, kept truthful so the file does not contradict itself. Both loaders
clear that word and count the party themselves, so nothing reads it.

`rebuild(parse(data)) == data` on both saved games and on the synthetic ones
`tests/test_amigasavegame.py` builds from the map. A party one character
shorter shortens the file by exactly that character's block; stripping a
character's items zeroes the head the loader tests.

**Nothing in front of the count is touched**, which is the rule
`.claude/rules/conversions.md` asks for: the variable array, the staged area
script and the square block are the caller's own save, and this changes only
the region it can account for byte by byte. It is an edit of a player's own
saved game, not a converted save built on somebody else's template.

## What step 4 cannot claim, and the gate

**No Amiga Curse or Silver Blades saved game this project wrote has ever been
loaded by the game.** Nothing has been read on either title's screen since
GALAIN's character sheet.

What is established: the format takes it. There is no checksum, no length
field and no signature anywhere in either loader; the party count is trusted;
the block sizes are constants; and the three fields the loader does test are
set correctly and measured correctly on 21 records. What is **not** established
is that the engine runs it — and the three faults this project has already
shipped past every byte-level check that existed (an AC of 9 drawn as 51, a
dropped combat tail, a garbage weapon line) are the reason that distinction is
kept.

**So a WinUAE target is the gate, and it is now the only thing between step 4
and done.** `docs/143-winuae-debugger.md` says what one takes.
`#108 (Amiga Curse asks its code wheel, so the title cannot be driven
unattended)` is closed, so Curse boots, answers its own protection prompt and
loads; what was never found is the key that moves the party, since the `4`/`6`/`8`
that work in Amiga Pool of Radiance do nothing in Curse. The run: boot Curse on
a writable copy, load `SAVE/savgamA.dat`, save it back to a second slot through
the game's own `ENCAMP / SAVE`, then write our own rebuild of that same party
onto the disk, load it, and photograph one character sheet and the party panel.
A party that loads and draws the same sheet is what turns this page's last
section from an argument into a measurement.
