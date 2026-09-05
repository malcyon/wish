# Changing class twice

**A character can change class exactly once, and no engine-written record can
ever hold two former classes.** All four ports asked -- Curse of the Azure
Bonds and Secret of the Silver Blades, on the C64 and on DOS -- refuse a
second `HUMAN CHANGE CLASS`, and each refuses by reading the very field the
first change wrote. So `neutral.former_levels`, which maps a class name to the
level it was left at, is more general than any port needs, and the
platform-limit rule of `.claude/rules/conversions.md` has nothing to bite on
here: there is no case where a conversion has two former classes and one slot
to put them in.

Measured for `#256 (The neutral record has nowhere to put a dual-classed
character's former levels)` on 2026-09-05.

## The four gates

| port | where | the test | what the player sees |
|---|---|---|---|
| Curse, C64 | `GEN $2393` | `LDA $7CBA / BNE` -- `dual_class_level` non-zero | `UNABLE TO CHANGE CLASS.` |
| Silver Blades, C64 | `GEN $1F88` | the same two instructions | `UNABLE TO CHANGE CLASS.` |
| Curse, DOS | `GAME.OVR 0x20243` | the former-class reader must return `0x11` | the menu line is **not drawn** |
| Silver Blades, DOS | `GAME.OVR 0x3CDAF` | the same reader, inside the command | the command does nothing |

**CONFIRMED in all four**, from the bytecode; **CONFIRMED in the running game**
for the two DOS titles, where the drives below are the evidence. The C64 half
has no replay behind it -- see "What is not settled".

## The C64: one comparison, and one writer

Curse's `HUMAN CHANGE CLASS` handler is `GEN $2377`. It picks a character
(`$237E`), loads that character's record into the working area at `$7C00`
(`$2384`), and then tests four things in a row, any of which sends it to the
message:

```
$2387  LDA $7C72 / CMP #$07 / BNE $239F      race, and 7 is human
$238E  JSR $23FC / BCC $239F                 the old class's prime requisites, >= 15
$2393  LDA $7CBA / BNE $239F                 dual_class_level -- already dual-classed
$2398  LDA $7CA0 / CMP #$02 / BCS $23AE      level 2 or better
$239F  LDY #$1F / JMP $17FD                  message 31
```

`$7CBA` is record offset `0x0BA`, `dual_class_level`; `$7CA0` is `level` and
`$7C72` is `race`. Message 31 is `UNABLE TO CHANGE CLASS.`, read out of the
pointer pair at `GEN $2C3B`/`$2C64` -- the same table whose entry 27 is the
trainer's `UNABLE TO ADVANCE` that `docs/172-curse-trainer.md` names.

Secret of the Silver Blades is the same routine at `GEN $1F6C`, with `CMP #$06`
for human because that title numbers races differently (`#237 (The DOS race table is one table for four titles, and it is wrong for two of them)`), and the same
`LDA $7CBA / BNE` at `$1F88`. Its message 31 is the same sentence.

**The flag is never cleared.** Sweeping every file on all six Curse sides for
an absolute-mode instruction naming `$7CBA` finds **one store**, `GEN $23D2`,
which writes the old class's level; and every other reference is a load. Silver
Blades is the same, one store at `GEN $1FBD`. `GEN $20A3`, the routine that
gives a dual-classed character the old class back once the new one passes it,
writes `class_levels[old]` and ORs the old class bit into `class_bits` and
**leaves `$7CBA` alone**:

```
$20A3  LDA $7CBA / BEQ $20C2         not dual-classed, nothing to do
$20A8  CMP $7CA0 / BCS $20C2         the new class has not passed the old level yet
$20AD  LDX $7CB9 / STA $7CC9,X       class_levels[old] = the old level
$20B3  LDA $0B82,X / ORA $7CEB / STA $7CEB
```

So the refusal is permanent: a character who has changed class once is refused
for the rest of the game, and there is no state in which the pair at `0x0B9`
and `0x0BA` describes anything but the single class he left.

The value written can never be zero, because `$2398` requires `level` >= 2 and
a human cannot be multi-classed, so the class level the change stores is at
least 2.

## DOS Curse: the menu item goes away, per character

Curse's party-menu builder at `GAME.OVR 0x201FF` sets the enable byte of each
of the thirteen items. `Human Change Classes` is item 4, at DS `0x624`, and it
takes three conditions:

```
02021B  cmp word es:[di+0x550], 0     ; the training hall's maximum level
020221  ja  0x2022a
020223  cmp byte [0x75a1], 0          ; or the free-training flag
020228  je  0x2024c                   ; neither -> disabled
02022A  push [0x6522]/[0x6520]        ; the currently selected character
020232  lcall 0xfe:0x3e               ; is he human?
020237  or al, al / je 0x2024c
02023B  push [0x6522]/[0x6520]
020243  lcall 0xfe:0x43               ; which class was he -- 0x11 if none
020248  cmp al, 0x11 / je enable
020252  mov [0x624], al
```

`es:[di+0x550]` is file offset `0xD51` of `SAVGAM<slot>.DAT`, which
`#234 (A dual-classed Curse or Silver Blades character converted to DOS loses
the class he trained out of)` established is the hall's maximum level in Pool
of Radiance, Curse and Silver Blades alike.

**It is a property of the selected character, not of the party**, and the
engine says so itself: the routine at `0x2039E`, which runs when the roster
highlight moves, computes that same boolean before the move and again after,
XORs the two, and rebuilds the menu when they differ. Pressing `H` when the
flag is zero does nothing at all -- `0x2048A cmp byte [0x624], 0 / je` skips
the call, with no message.

### Watched, six characters, one save

`tools/dualclassagain.py dos --game CURSE --party work/curse/234-curse-dualclassed`
loads the save DEMELTINA was dual-classed in on `#234 (A dual-classed Curse or Silver Blades character converted to DOS loses the class he trained out of)` and photographs the
party menu once per character, moving the roster highlight with `End`. The
records were read at `goldbox/dos_layout.py`'s own offsets from the same files.

| roster | race | class now | `former_class_levels` | `HUMAN CHANGE CLASSES` |
|---|---|---|---|---|
| DEMELTINA | human | cleric 1 | **paladin 5** | **absent** |
| ARGORA | human | ranger 5 | all zero | present |
| RWELLYN | human | ranger 5 | all zero | present |
| FLORENTZ | human | cleric 5 | all zero | present |
| ORATISI NOMOON | **elf** | multi 4/3/4 | all zero | **absent** |
| BRYTWYN | human | magic-user 5 | all zero | present |

Six for six, and both of the code's two conditions are visible in one sweep:
the line is missing for the one dual-classed human and for the one non-human,
and present for the other four. `TRAIN CHARACTER` is in all seven shots, so the
hall word did its work throughout. The seventh shot, taken after the highlight
wrapped back to DEMELTINA, is pixel-identical to the first.

## DOS Silver Blades: the item stays, and the command does nothing

Silver Blades' menu builder at `GAME.OVR 0x1D7B5` sets `Human Change Classes`
(DS `0x791`) from the hall word alone -- **no race test and no dual-class
test** -- so the line is drawn for every character. The gate moved into the
command itself, at the head of the routine at `0x3CD94`:

```
03CD9F  push [0x7d3a]/[0x7d38]        ; the current character
03CDA7  call 0x3cb94                  ; is he human?
03CDAD  je  refuse
03CDAF  push [0x7d3a]/[0x7d38]
03CDB8  call 0x3ca98                  ; which class was he
03CDBB  cmp al, 0x11 / je proceed
03CDBF  refuse: format the name, append the string at cs:0xf09, print, return
```

The string at `cs:0xf09` is ` doesn't qualify.`, seventeen bytes, and the same
string is used by the other refusal in the same routine -- the one taken when
the eligible-class list comes out empty.

### Watched, one action apart

Two slots of the same tree, `work/curse/234-ssb-dualclassed`, differing by the
one `HUMAN CHANGE CLASSES` `#234 (A dual-classed Curse or Silver Blades character converted to DOS loses the class he trained out of)` drove: slot C is PAINE the human ranger 8
with an all-zero former array, slot D is PAINE the magic-user 1 with
`former_class_levels[ranger] = 8`. The same six keys in each run.

| slot | PAINE | after `SELECT` |
|---|---|---|
| C, before | ranger 8, former array all zero | `PICK NEW CLASS: FIGHTER, MAGIC-USER` |
| D, after | magic-user 1, former ranger 8 | back to the party menu, nothing drawn |

The positive control in the *same* save is EPONA, a human fighter 8 who has
never dual-classed: selecting her in slot D gives
`PICK NEW CLASS: MAGIC-USER, THIEF`. So the keys reach the command and the
command works; it is PAINE it will not run for.

**The refusal is silent in practice.** Twenty-five consecutive frames captured
as fast as the harness can take them, starting about a tenth of a second after
the key, are all the party menu; ` doesn't qualify.` never appeared in any of
them. **PROBABLE** that the message is printed and overwritten faster than a
capture; what would settle it is a breakpoint on `0x3CDDF` in a debugger, or
counting the frames a *known* refusal draws for -- Guy de Valois, a paladin 8
with no eligible class, takes the same path and is equally silent here.

## No record anywhere holds two

`tools/dualclassdos.py census` over every DOS character record on this machine:
98 distinct records, 62 of them in the three shapes that have a former array
(Curse 24, Silver Blades 12, the 510-byte shape 26).

| former classes in one record | records |
|---|---|
| none | 59 |
| exactly one | 3 (ABAGAIL, PAINE-in-Pools-of-Darkness, OUGO) |
| **two or more** | **0** |

Those three come from downloaded archives and have no chain of custody
(`.claude/rules/testing.md`), so they are a count rather than evidence about
the engine. The two records this project watched being written -- DEMELTINA and
PAINE -- hold exactly one each.

## The specimens

Both parties were rescued into `$WISH_SPECIMENS` before the run directories
could be lost, since `work/` is gitignored and has been lost twice.
`tools/specimens.py check` passes on 37 specimens.

| specimen | what |
|---|---|
| `curse-234-party-dualclassed` | the whole six-character DOS Curse party DEMELTINA was dual-classed in, not just her record -- the elf and the four untouched humans are what make the menu sweep a measurement |
| `ssb-234-party-pair` | both DOS Silver Blades parties, slot C before PAINE's change and slot D after, in one specimen because the pair is the evidence |

Neither carries a byte we wrote: the `0xD51` poke is made on a staged copy at
run time and never on the specimen.

## What a conversion can meet

**One former class, or none.** `goldbox/neutral.py`'s `former_levels` is a
dict, so it can carry more, and the writers already refuse more than one; that
refusal is a guard against a file we do not understand rather than a case the
game produces. Nothing has to be built for `.claude/rules/conversions.md`'s
"a destination that genuinely holds fewer things than the source" on account of
former classes.

**One shape a bad file could take, and the reader already warns about it.** DOS
stores the level twice -- `former_level` and the array entry -- and the gate
reads only the array. A file with `former_level` set and the array zeroed would
pass the gate, and a change of class would then leave the two disagreeing.
`goldbox/dos.py`'s reader compares them and warns, naming both numbers, which
is the right behaviour for exactly this. **SPECULATIVE** that any real file
does it; what would produce one is a cross-title import that copies one and not
the other, and the experiment is to read Silver Blades' Curse-party importer
for whether it copies `0x111` as well as `0x0E6`.

## What is not settled

**The C64 has never been replayed.** The gates above are read out of `GEN` and
the message index resolves to `UNABLE TO CHANGE CLASS.`, but no C64 session has
pressed `HUMAN CHANGE CLASS` on an already dual-classed character.
`WISH-SPEC-curse-dual-classed` is the specimen and it would take one drive --
except that on 2026-09-05 **no Curse save disk could be loaded through the
front end in a pooled session at all**. That is not the specimen:
`WISH-SPEC-curse-h-engine-resave` and `#18 (Measure Curse's trainer so Level Up works there)`'s own `work/issue18/train1.D64`,
which that session did load, fail the same way, and the attach itself is proven
working because `ADD CHARACTER TO PARTY` asks for `INSERT SIDE # 1` once the
save disk is in the drive. `GEN $1F42` is the load and `$3159` is what fails;
nobody has read `$3159`. The whole list of what was tried is in
`tools/dualclassagain.py`'s docstring.

**Gateway to the Savage Frontier** carries the same store (`GEN $23D3`, from
`#224 (0x0B9 and 0x0BA are documented both as an NPC marker and as the dual-class slot)`) and its gate was not read. The question asked about two titles.

**What the C64 does when the gate is removed** is unmeasured.
`tools/dualclassagain.py c64 --gate-off` writes `NOP NOP` over `GEN $2396` and
would answer it; the interest is only in confirming that the branch is what
produces the message, since the state it would create is one no player reaches.
