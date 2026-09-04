# What the DOS engine tests to expire a `.SPC` effect record

The question behind `#232 (An item-granted effect is dropped on the way
through the neutral record, with no report)`: when DOS Pool of Radiance
decides that an effect record has run out, what does it look at? Answered by
reading the engine's own expiry routine out of `GAME.OVR` and then watching
it run under DOSBox-X.

**The answer -- CONFIRMED, by the code and by the running game: the
sixteen-bit little-endian duration at record bytes 1-2, and nothing else.
Zero is never counted down and never removed. Anything else is counted down
as the clock advances and the record is removed on the step that reaches it.**
The id is not consulted, there is no table of permanent ids, and bytes 3-4
are not read on that path. `goldbox.dos.to_neutral`'s reading of bytes 1-2 as
the permanence test is the engine's own.

Grades follow `docs/50-experiments.md`'s scale. "The build" is the 1.3
`GAME.OVR` in the player's copy of *Forgotten Realms: The Archives*.

## The expiry routine

`GAME.OVR` file offset `0x23DCC`-`0x240BB`, the first routine of the overlay
unit with stub segment `0x8C`. It is the twin of `coab`'s
`ovr021.CheckAffectsTimingOut` (Curse's decompiled engine, `work/coab/`,
`github.com/simeonpilgrim/coab`), and it goes:

1. outside camp (`[0x49F3] != 2`) mark every party slot as needing a pass;
2. scale the elapsed count through the seven-entry table
   `10, 10, 6, 24, 30, 12, 256` at `DS:0x363A` -- the same table `coab` calls
   `timeScales`, and finding it fixed the data segment at `0xC7C`;
3. for each party member (chain through the record's `0x104` next pointer,
   head at `[0x5D96]`), follow the far pointer at record `0x7F` down the
   effect nodes and, per node, in steps of at most ten minutes:

```
23F52  cmp word ptr es:[di+1], 0    ; the duration word
23F57  jne 23F6D                    ; nonzero: count it down below
23F59  ...                          ; zero: step to the next node, untouched
23F6D  mov al,[bp-3] ; xor ah,ah    ; this pass's step, 1..10 minutes
23F75  cmp ax, word ptr es:[di+1]
23F79  jae 23FA6                    ; step >= remaining: remove the node
23F83  sub word ptr es:[di+1], ax   ; step <  remaining: subtract
23FCA  lcall 0xB0:0x2A              ; remove_affect(node, node.id, player)
```

Two consequences a reader needs. **A running record never reaches zero on its
own** -- the step that would take it there removes it instead, so a saved
record at `00 00` was written that way, not counted down to it. And **only
four places in the whole binary read the duration word at all** (a scan for
every `es:[reg+1]` word access in `GAME.OVR` and in the unpacked
`START.EXE`, each hit then read as code): this routine, `add_affect`
writing it, the spell-apply routine deciding whether a new cast replaces an
old node (`0x2C5BD`), and one nibble-packed special case (`0x104D8`).
Nothing removes nodes by comparing the id against a list. CONFIRMED.

## `add_affect`, and what each byte of the record is

`GAME.OVR:0x2BD3C`, overlay unit `0xB0`, public entry `0x52`. `GetMem(9)`,
appended to the end of the chain at record `0x7F`, next pointer zeroed. Its
five arguments land in the record as:

| byte | argument | what it is |
|---|---|---|
| 0 | type | the effect id, `goldbox/traits.py`'s namespace |
| 1-2 | minutes | the duration, `u16le`; **0 = permanent** |
| 3 | data | a per-effect value: `0xFF` for a racial bonus, `0x0C` for an item-granted one, the caster's level for a spell, the strength being replaced for a strength item |
| 4 | flag | **a boolean the engine reads back** -- whether removing the node must also run the effect's handler (`coab`'s `callAffectTable`). Not payload |
| 5-8 | -- | next, live on the heap, rebuilt on load (`goldbox/dos.py`'s `EFFECT_NEXT_NULL`) |

`INNATE_PAYLOAD`'s `00 00 FF 00` is therefore duration 0, data `0xFF`,
flag 0, which is what character creation passes for every racial id.

**Every call site, read for its pushed arguments** (38 far calls to
`0xB0:0x52` in `GAME.OVR`, none in the resident code):

| path | type | duration | data | flag | record written |
|---|---|---|---|---|---|
| character creation, racial (`0x1A14D`-`0x1A288`) | 90, 97, 26, 47, 18, 48, 107, 124 | 0 | `FF` | 0 | `id 00 00 FF 00` |
| **readying a magical item** (`0x11B35`, `remove=0`) | the item's byte `0x3D` | **0** | **`0C`** | 0 | **`id 00 00 0C 00`** |
| a strength item (`0x11CF5`) | 38 | 0 | the value `0xB0:0x7A` hands back beside the new 18/00 | 1 | `26 00 00 vv 01` |
| a condition in combat (`0xFDB8`, `0xFE49`, `0x100E2`, `0x10210`, `0x10561`, `0x105EE`) | 31, 98, 55, 58 | 0 | `FF` | 0 | `id 00 00 FF 00` |
| a long condition (`0xEE13`, `0xEED8`, `0x11092`) | 7, 62, 50 | 43200, 60, 14400 | `FF` | 1 | |
| a cast spell, the generic path (`0x27A7B` via `0xB0:0x84`) | the spell row's affect id | `fixed + perLevel x level` from the spell table | caster level, or a level the caller passes -- two callers pass `0xFF`, both with flag 1 | passed in | e.g. `BLESS 01 02 00 01 00` |

Un-readying the item calls `remove_affect` with the same byte `0x3D`
(`0x11B61`). The ready path is gated on byte `0x3E` of the item being
`>= 0x80` (`0x22334`, `0x22514`) -- bit 7 is "magical", the low seven bits
select the kind of grant and zero means "grant byte `0x3D`", as in `coab`'s
`calc_items_effects`. CONFIRMED for the gate and the arguments; PROBABLE that
the low bits map exactly as Curse's do, since only the zero case was run.

**The three Amiga item specimens match these shapes byte for byte.** Their
ten-byte nodes (`work/p105/saves/`, a rebuilt corpus): CONJURER
`3D 00 0000 0C 00` and MAGICIAN `59 00 0000 0C 00` are the item path; ADDERLY
`26 00 0000 5C 01` is the strength-item path, flag 1 and all, which makes
"92 is the strength the girdle replaced" PROBABLE rather than SPECULATIVE.

## Watched in the running game

`tools/dosspcexpiry.py`, DOSBox-X with the debugger, the chains read off the
heap through record `0x7F` before and after.

| run | before | after | grade |
|---|---|---|---|
| `chain --slot J --steps 4`: the shipped party, `BLESS` at 2 minutes on all six, racial records on four | clock minute 6; 6 x `1 dur=2`, 8 x racial `dur=0` | clock minute 8; **every `BLESS` gone, every zero-duration node untouched**, two humans left with a NULL head | CONFIRMED |
| `ready --slot J --char 1 --item 1 --effect 61 --power 0x80`: THRENDER GRONE's unreadied flail given `0x3D = 61`, `0x3E = 0x80` in the staged copy, then `VIEW > ITEMS > READY` | chain ends `1 dur=2` | chain ends **`61 dur=0 data=0C flag=0`**; the engine's own save to slot D writes `CHRDATD1.SPC` ending `3D 00 00 0C 00 00 00 00 00` | CONFIRMED -- the DOS item-granted specimen the issue lacked, engine-written |
| `chain --slot A --steps 12`: SILAS's `05 00 00 FF 00` and `2D 00 00 FF 00` | clock minute 2 | clock minute 5, both untouched | CONFIRMED that the engine keeps them; see below for what they are |

## What SILAS is, and is not

SILAS -- `CHRDATA6.SAV`, a human fighter/thief carrying Detect Magic (5) and
Protection from Evil 10' Radius (45) at `00 00 FF 00` -- was the
counter-example that stopped the carrying half of `#232 (An item-granted
effect is dropped on the way through the neutral record, with no report)`.
Donald settled his provenance on 2026-09-04: every record in
`~/dos_por_play/SAVE/` is to be treated as edited, and those two files are
that set. The code agrees, independently: on this build the shape
`00 00 FF 00` (duration 0, data `FF`, flag 0) is written for exactly twelve
ids -- the eight racial ones at creation and the four combat conditions 31,
55, 58, 98 -- and by no spell path, because the spell table gives cleric
Detect Magic a fixed 10 minutes and the magic-user Detect Magic (11) and
Protection from Evil 10' Radius (52) `2 x caster level` with a scroll cast
substituting level 6 (`START.EXE` `0xBA:0x26C2`, gated on `[0x6DBF]`). An id
outside those twelve in that shape was not written by this engine.
CONFIRMED for the twelve; the rule is a property of one build.

So SILAS proves nothing about permanence except the thing the running game
showed: the engine treats whatever is at duration zero as permanent,
including an editor's Detect Magic.

## Negative results

* **No table of permanent ids exists in the engine.** The hypothesis
  from `#84 (Roll a gnome in DOS and read the two innate effect ids nobody
  has seen)`'s comment predicted one; the expiry routine consults none, and
  no `remove_affect` caller walks a chain against a list. The lists that do
  exist are ours (`INNATE_EFFECTS`) and Curse's importer's.
* **The ECL VM adds no effects.** None of the 38 `add_affect` call sites
  falls in the VM's overlay unit (`GAME.OVR` `0xD46`-`0x4253`).
* **`MON*SPC.DAX`, the authored NPC effect files, were not read**:
  `goldbox.dos_savegame.dax_unpack` rejects their blocks ("copy of 7 bytes at
  62 runs 2 past the end"), so whether an authored NPC effect can carry a
  zero duration is UNKNOWN. Settle it by reading those blocks with a codec
  that tolerates the overrun, or by recruiting an NPC in the game and reading
  his chain with `tools/dosspcexpiry.py chain`.
* **`START.EXE` is EXEPACK-compressed.** The overlay descriptors looked
  unaligned and no data-segment offset could be found until it was expanded
  (`tools/unexepack.py`); the "file = 0x200 + seg x 16 + off" rule in
  `docs/145-dos-decode-kit.md` holds only for the first few hundred bytes.

## What the conversion should do with this

Reported for `goldbox/neutral.py` and `goldbox.dos.to_neutral`, which
another agent holds tonight.

1. **Duration zero is the discriminator, on both ports.** The carrying half
   of `#232` can be built as specified: a neutral field holding the whole
   record for every non-innate `.SPC` node at duration zero, written back by
   `goldbox.dos.write` and `goldbox.amiga.write_por`. A nonzero duration is a
   running spell and stays unreported under Donald's 2026-08-27 ruling.
2. **Carry all four payload bytes, and name byte 4 a flag.** A strength
   item's node is `26 00 00 vv 01`; writing it back with byte 4 zero would
   stop the engine restoring the old strength when the girdle comes off.
   `INNATE_PAYLOAD`'s docstring should say byte 4 is `callAffectTable`.
3. **Do not derive a `.SPC` record from the item that granted it.** The
   engine keys the node on the item's byte `0x3D`, so a converted character
   who arrives with the ring readied and no node has the ring and not the
   resistance until he takes it off and puts it back on. The node and the
   readied item travel together.
4. **A specimen is now available that no editor touched:**
   `work/issue232/ready4/ready.json` records the six `.SPC` files the engine
   wrote to slot D, the first ending in `3D 00 00 0C 00` beside the racial
   and `BLESS` records, and `tools/dosspcexpiry.py ready` regenerates the
   run in four minutes.
