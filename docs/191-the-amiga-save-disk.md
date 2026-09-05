# The Amiga save disk

What a player is handed when a party is converted to Amiga Pool of Radiance:
an 880K floppy named `POOLSAVE` with the party on it and **no game code at
all**. Put it in any drive beside the game disk, choose `LOAD SAVED GAME`, and
answer `PATH FOR SAVE  RETURN = POOLSAVE:` with a bare RETURN.

Written for `#36 (Write an Amiga disk image, not just the character files)`
and measured on 2026-09-05 in three WinUAE runs; `docs/143-winuae-debugger.md`
§1 is the procedure and `work/issue36/` holds the screenshots.
`docs/182-amiga-por-in-the-running-game.md` is the companion for the other
route -- a copy of the player's own game disk with a slot written into its
`save` drawer -- which still works and is what `tools/toamigapor.py --out`
produces.

## 1. The prompt's default is a volume name, and that is the whole design

**CONFIRMED, from the game's own code and then from the running game.**
`/program` on disk 1 carries the prompt twice and the pieces of every filename
beside it:

| offset in `/program` | string |
|---|---|
| 122608 | `file not found,check your save path` |
| 122644 | `path for save return = poolsave:` |
| 122754 | `poolgame:intro` |
| 182294, 182558 | `Put save disk in any drive` |
| 182498, 182504 | `save`, `save` |
| 182512 | `Load Which Game: ` |
| 182530, 182538 | `savgam`, `.dat` |
| 182670 | `A B C D E F G H I J` |
| 182822 | `CHRDAT` |

Three things follow, and the third is the one that makes a save disk possible.

* **The game disk is a different volume.** `AmigaDisk.volume_name` reads disk
  1 as `poolgame`, and the game names `poolgame:intro` when it wants a file
  off it. So `POOLSAVE:` was never a path on the game disk, and a bare RETURN
  there raises Kickstart's *please insert volume POOLSAVE* requester --
  `docs/124-amiga-port.md` §1.8 had to type `SAVE/` instead.
* **"Any drive" is what the game means.** `Put save disk in any drive` sits
  beside both the load and the save path. Measured on two: the save disk
  loaded from **DF2** in runs 1 and 2 and from **DF1** in run 3, with the
  game's disk 2 in the other slot each time.
* **The path is a prefix, concatenated with a bare filename.** Answering
  `SAVE/` opens `SAVE/save`, which is where disk 1 keeps its ten-byte slot
  list. Answering `POOLSAVE:` opens `POOLSAVE:save`, a file called `save` in
  the **root** of the volume. There is no drawer on a save disk.

## 2. What is on one

`goldbox.amiga.make_por_save_disk` formats it with `AmigaDisk.blank` and puts
these in the root. A six-character slot takes 54 blocks of the 1758 a floppy
has, so nine slots would fit before anybody had to think about room.

| file | what it is |
|---|---|
| `save` | the ten-byte slot list, one letter per byte, indexed by letter |
| `savgam<L>.dat` | 13,141 bytes: the map, the party's square and the clock |
| `CHRDAT<L><n>.sav` | the 288-byte record, one to six |
| `CHRDAT<L><n>.itm` | the item chain, where the character owns anything |
| `CHRDAT<L><n>.spc` | the effect chain, likewise |
| `charlist.txt` | zero bytes, as disk 1 ships it |

**`savgam<L>.dat` used to be copied off the player's disk 1, and is now built
from the save being converted.** This section said it "cannot be made from a
converted party"; that was true when it was written and stopped being true on
2026-09-05, when `#316 (Write the Amiga Pool of Radiance saved game from the
source save, so a converted party arrives where it was standing)` landed. All
13,141 bytes come from the C64 or DOS save, with a declared reason for every
byte left zero, and the party arrives on its own square at its own clock --
[`196-the-amiga-saved-game-built.md`](196-the-amiga-saved-game-built.md).

**What a conversion reads is disk 2 rather than disk 1.** The one thing no
character record holds is the area's own 7680-byte ECL script, which is live on
load, and the Amiga keeps every area's in a single `ecl.dax` on the `POOLDATA`
volume. `tools/toamigapor.py --data-disk` names it. `--container <letter>`
still copies a saved game off a disk and is now an experiment rather than a
conversion: it puts the party in somebody else's place on purpose, and the run
says so.

`charlist.txt` is there because the game opens it by name and
`file not found,check your save path` is what a player would otherwise meet
the first time they used `ADD CHARACTER TO PARTY`. It costs one block. That
this is what happens without it is **SPECULATIVE**: the menu was never opened
on a save disk, and the experiment is to build one with the file left out,
boot, and choose `ADD CHARACTER TO PARTY`.

## 3. What the game did with one

The party is the C64 specimen `por-party-twin-pair`, converted by
`tools/toamigapor.py --c64` into slot `B`.

| step | what the screen said |
|---|---|
| `LOAD SAVED GAME`, RETURN at the path prompt | `LOAD WHICH GAME: B` |
| `B` | `MALCYON 8/4  TWIN 8/4  ROLAND 10/7  LADY KATHERINE 8/5  MAGNUS 9/9  BRUTUS 9/11`, at `0,4 W 05:48` |
| `VIEW` | `MALCYON`, `MALE ELF AGE 176`, `NEUTRAL GOOD`, `MAGIC-USER`, `STR 15 INT 17 WIS 15 DEX 16 CON 13 CHA 15`, `GOLD 60`, `LEVEL 1 EXP 0`, `AC 8 THAC0 20 ENCUMBRANCE 60`, `HP 4 DAMAGE 1D2 MOVEMENT 12`, `STATUS OKAY` |
| `ENCAMP` ▸ `SAVE` ▸ `C` | the game wrote a slot onto the disk we formatted |
| reboot, `LOAD SAVED GAME`, RETURN | `LOAD WHICH GAME: B C` |
| `C` | the same six, and `LADYKATHERINE` without her space |

`0,4 W 05:48` is what the container holds rather than a guess: the square
block of `savgamB.dat` reads x 0, y 4, facing 6, and the clock bytes at
`$49C6`-`$49C9` give 05:48. So the party is ours and the place is the game's,
which is what `--container` is for.

MALCYON's eleven sheet values are the same eleven
`docs/182-amiga-por-in-the-running-game.md` §3 read off the game-disk route,
and each matches the C64 record it came from.

## 4. The engine wrote into a filesystem we formatted, and it still verifies

This is the half no offline test could reach. The game's own SAVE allocated
blocks out of **our** bitmap, threaded ten new files and a `savgamC.dat` into
**our** root block's hash chains, and rewrote the slot list.

| | before the engine saved | after |
|---|---|---|
| `save` | `' B        '` | `' BC       '` |
| free blocks | 1704 | 1656 |
| `AmigaDisk.verify()` | `[]` | `[]` |

`' BC       '` is the array `goldbox.amiga.slot_list_bytes` writes -- `B` in
byte 1, `C` in byte 2, byte 0 still a space because no `A` was ever on this
disk. That is the same shape `#109 (A save slot written onto an Amiga disk is
not offered by the game's picker)` measured on a game disk, on a disk where
the gap is at the front rather than in the middle.

**And the engine allocates the other way round from us.** Ours went 1757,
1755, 1753, downwards from the end; the engine's slot C landed at 882, 884,
886, upwards from the root at 880, and it moved `save` itself from 1759 to
904. **This does not contradict** `#36 (Write an Amiga disk image, not just
the character files)`'s 2026-08-26 finding that our allocator must count
*down*: that was about a cracked **game** disk, whose loader reads blocks the
bitmap says are free and hangs on a white screen when something else is in
them. A save disk has no loader on it, and AmigaDOS's own writer went low with
no trouble.

## 5. The engine changed the same 57 bytes it changes on a game disk

`tools/porslotdiff.py --drawer ''` on our slot `B` against the engine's slot
`C`, over the six 288-byte records:

| field | bytes differing |
|---|---|
| `heap_104` | 15 |
| `effect_chain` | 12 |
| `name_text` | 10 |
| `party_order` | 5 |
| `thac0_base` | 3 |
| `attack_level`, `thac0_current` | 1 each |
| LADY KATHERINE's five `thief_*` | 1 each |
| MAGNUS's five `save_*` | 1 each |

**57 of 1728, and it is the same list, the same characters and the same
numbers as `docs/182-amiga-por-in-the-running-game.md` §4 records for the
game-disk route.** So the disk a slot is written onto changes nothing about
what the engine does with the party: the two routes are one conversion,
differing only in what the files land on. `name_text` is
`#308 (Does Amiga Pool of Radiance drop the space out of a character's name
when it saves?)` reproduced a third time.

Measured before the boot, and stronger than the screens: **the eleven slot
files are byte-identical between the two builds** -- `savgamB.dat` and all ten
`CHRDATB*` -- with only the slot list differing, and correctly, since the game
disk already had `A` on it.

## 6. What this does not establish

* **A one-drive Amiga.** The save disk was found in DF1 and in DF2, both times
  with the game disk in DF0. A machine with a single drive has to swap disks
  at the prompt, and nothing here drives that. The experiment is a run with
  `nr_floppies=1` and a `-s floppy0=` eject between the prompt and the answer.
* **Whether `charlist.txt` is needed**, §2.
* **A save disk carrying more than one party.** Nine more slots fit and none
  was written. `write_por_slot(disk, letter, ..., drawer="")` is the call, and
  the run above proved the second letter lands in its own byte -- but the
  engine wrote that one, not us.
* **Any Amiga title but Pool of Radiance**, and Pools of Darkness in
  particular does **not** work this way. Its executable builds a save path out
  of `DF0:`, `SAVE` and `DISKA` at file offset 260206, and the requester
  beside it at 259918 reads `Insert %s and Press a Key`, `Disk %c`,
  `SAVE Disk`, `the Disk`, `'%s' not found`. There is no `path for save`
  prompt anywhere in it and no volume name to answer with: it asks for a disk
  by **drive** and looks in a `SAVE` drawer on it, which is where disk 3 keeps
  `SAVGAMA.PTY` and the vault. So step 3 of
  `#36 (Write an Amiga disk image, not just the character files)`'s order of
  work -- `tools/toamiga.py` emitting a disk rather than loose `.pc` files --
  needs its own measurement and cannot borrow this one. **PROBABLE**, from the
  strings; nothing has been booted.

  (`Place Secret save disk in DF0:` also appears in that executable, at
  152872, and is *not* this: `docs/124-amiga-port.md` §1.2 has it as the
  Silver Blades **import** route, beside `/Secret Drawer/SAVE` and
  `DF0:SAVE`.)

  Curse of the Azure Bonds ships a separate save disk of its own, 1804 blocks
  with fourteen `.cha` files (`docs/124-amiga-port.md` §1.6). It has not been
  built or booted either, and nothing here says which of the two mechanisms it
  uses.

## 7. Reproducing it

```sh
export SSH_ASKPASS_REQUIRE=never
winvm acquire wish36
ps='powershell -NoProfile -ExecutionPolicy Bypass -File C:\Amiga\winuae.ps1'
winvm ssh "$ps claim -Holder por36"

# Since #316 the disk on the command line is **disk 2**, whose ecl.dax the
# area's script is read out of; the saved game is built rather than copied.
tools/toamigapor.py work/issue36/por2.adf --to B \
    --save-disk work/issue36/poolsave-B.adf \
    --c64 ~/wish-specimens/por-c64/WISH-SPEC-por-party-twin-pair.d64

winvm ssh 'powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path C:\Amiga\Disks\i36"'
for f in por1.adf por2.adf poolsave-B.adf; do
    scp -o BatchMode=yes work/issue36/$f donald@192.168.123.50:"C:/Amiga/Disks/i36/$f"
done
winvm ssh "$ps start -Holder por36 -log -f C:\Amiga\configs\goldbox-a500.uae \
    -s nr_floppies=3 -s floppy2type=0 \
    -s floppy0=C:\Amiga\Disks\i36\por1.adf \
    -s floppy1=C:\Amiga\Disks\i36\por2.adf \
    -s floppy2=C:\Amiga\Disks\i36\poolsave-B.adf"

# 55s to the code wheel, RET; 50s to the title, RET; 45s to the menu.
tools/amigadrive.py --holder por36 keys L
tools/amigadrive.py --holder por36 keys RET     # the default, POOLSAVE:
tools/amigadrive.py --holder por36 keys B
winvm shot work/issue36/loaded.png
```

Four things cost time on the way.

* **`nr_floppies=3` has to be passed**, and so does `floppy2type=0`.
  `tools/goldbox-a500.uae` ships two drives, and `-s` overrides are the way to
  a third without editing the committed config.
* **A key pressed while a disk is loading is swallowed with no sign.** Take a
  screenshot after every step rather than batching a sequence across a load.
* **`SAVE` asks `QUIT TO WORKBENCH  YES  NO` when it is finished.** Answer
  `N`. It is not a failure and it is not a confirmation of the save.
* **Delete the images you copied into the guest, release the lane and release
  the lease.** `winuae.ps1 release -Holder <id>`, then `winvm release <tag>`;
  a lease left held is a lease nobody else can take.

## 8. What is left

The library can now hand a player a save disk, and `tools/toamigapor.py` is
the way to ask for one. Putting it behind `File ▸ Export` belongs to
`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)`. **The dialog has to ask for the player's Amiga disk 2**, not disk
1: since `#316 (Write the Amiga Pool of Radiance saved game from the source
save, so a converted party arrives where it was standing)` the saved game is
built from the save being converted, and the only thing read off an Amiga disk
is the area's script out of `ecl.dax`.
