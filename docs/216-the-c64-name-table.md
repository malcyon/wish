# The `+$C00` name table is the save disk's directory, not the party's

Curse of the Azure Bonds and Secret of the Silver Blades keep what looks like
a second copy of the party's names, sixteen bytes per entry at payload
`+$C00` -- `$5700` in memory, since both save files load at `$4B00`. Pool of
Radiance has nothing there.

**It is a scratch buffer that the save file happens to enclose.** `GEN` clears
all 256 bytes of it and refills them from the save disk's own **directory**
before every one of its three reads, so the bytes a save carries there are
overwritten before any code looks at them. Nothing a player can reach ever
draws a stored entry.

This is the answer to
`#435 (A rename in Wish leaves the C64 name table holding the old name on
Curse and Silver Blades, and nobody knows what reads it)`: Wish's editor
writes only the 256 bytes of each save slot, so a rename leaves the table
holding the old name, and that costs a player nothing.

## What the six code sites do

`tools/c64nametable.py sites --title <key>` finds them in that title's own
`GEN`, which `LINKER` runs at `$0800` whatever the two-byte header claims.
Six sites in each title and no others; the addressing mode and the loop around
each operand are what tell them apart.

| Curse | Silver Blades | what it does |
|---|---|---|
| `$19F4` | `$2709` | `STA $5700,Y` -- clears all 256 bytes |
| `$1A44`, `$1A54` | `$2590`, `$25A0` | `STA $5700,X` -- copies a filename out of a directory line, terminated by `"` or at sixteen bytes |
| `$1B3F`, `$1B4E` | `$1C94`, `$1CA3` | `CMP $5700,X` -- walks entries 15 down to 0 looking for the working record's name at `$7C00` |
| `$1D0B` | `$23C8` | `LDA $5700,X` -- copies one entry into the text buffer at `$7A00`, behind the prefix byte, to make a filename |

The routine that fills it -- Curse `$1999`, Silver Blades `$24EC` -- takes a
prefix byte, calls the clear, `SETNAM`s a one-byte name of `"$"`, `SETLFS 1,8,0`,
opens the directory and reads it line by line. A line whose byte 8 is the
prefix is one of this game's characters, and the name at byte 9 is copied into
the next entry, up to sixteen. It returns the count.

**Every read is inside a routine that has just called it**: Curse `$1AB7`
before `$1ABA`, `$1BE1` before `$1BFD`/`$1C34`, `$1B7F` before `$1B85`; Silver
Blades `$1C43` before `$1C46`, `$20C1` before `$20D5`/`$2104`, `$25D9` before
`$25DF`. So the buffer is never read holding what a save put there.

## The prefix byte, and the `ADD FROM:` bar

A character saved on its own stands on the save disk as a file named after the
character with **one byte in front of it**: `$01` for Pool of Radiance, `$02`
for Curse, `$05` for Silver Blades. `GEN` carries the byte in the `S0:`
template it sends to delete a character file before rewriting one, which is
where `tools/c64nametable.py` reads it rather than trusting a table.

`ADD CHARACTER TO PARTY` opens with a bar naming the games it will read the
disk as -- `ADD FROM: CURSE POOL HILLSFAR EXIT` in Curse,
`ADD FROM: SECRET CURSE EXIT` in Silver Blades -- and the answer is which
prefix byte the directory scan filters on. That is the same mechanism
`docs/116-second-game.md` §4 describes for importing a Pool of Radiance
character into Curse.

## What was measured, and where

**CONFIRMED in the running game**, VICE pool slot 0, 2026-09-08,
`tools/c64nametable.py run`, which reads `$5700`-`$57FF` out of the machine
rather than off a screen.

| run | the disk | after `LOAD SAVED GAME` | after the add list was drawn |
|---|---|---|---|
| `work/issue435/curse3` | `WISH-SPEC-curse-party-with-items`: six party records, six stored entries naming them, and four `\x02` files called `ARDEN`, `BRISA`, `KORDAN`, `ELVYN` | `PALADIN RANGER F/T CLERIC FEMALE MAGE MALE ELF MAGE` -- the stored table, byte for byte | `ARDEN BRISA KORDAN ELVYN` and the rest zero; the screen listed those four and nothing else |
| `work/issue435/ssb2` | `work/issue33/edited.D64`: Wish renamed `MORGAINE` to `BRIGHID` in the record and left the table saying `MORGAINE` | `Guy de Valois  PAINE EPONA MALACHITE DOMINIC MORGAINE` -- the stale entry present | after `REMOVE CHARACTER FROM PARTY > BRIGHID` wrote `\x05BRIGHID` to the disk, the buffer was all zeros, then `BRIGHID`; the screen listed `BRIGHID` and not `MORGAINE` |

**And the engine stores the buffer as though it were a record.**
`work/issue435/ssb3` repeated the second run and then took
`SAVE CURRENT GAME`. The party it saved is five characters -- Guy de Valois,
PAINE, EPONA, MALACHITE, DOMINIC -- and the `+$C00` table in the `SAVEDBASH`
it wrote holds **one** entry, `BRIGHID`, who is not in the party. A record
would not do that; a buffer left where the save happens to reach does.

## What this supersedes

`docs/116-second-game.md` calls the Curse table "in slot order" and
`docs/175-silver-blades-save-conversion.md` asks whether Silver Blades keys it
in marching order instead. **Neither is a rule of the title.** The stored
order is the order the character files stood in the directory at the last
scan, and the ssb3 save above shows it need not have as many entries as the
party has members.

`goldbox.c64_save.C64Container.names_in_marching_order` therefore describes two
disks rather than an engine, and no experiment on the running game can settle
what it claims, because the game never reads the stored order.
`goldbox/dos_codec.py` still fills the table when it converts a DOS party, which is
right for the same reason the identity byte is written: the bytes are there,
they cost nothing, and a reader outside the game -- Wish's own roster list --
has something sensible to show.

**PROBABLE, not confirmed, and this is what would settle it**: create six
characters in the game, save them to a blank save disk in an order that is
neither the party's slot order nor its reverse, form the party, take
`SAVE CURRENT GAME`, and read `+$C00` out of the resulting file. If the entries
come back in the order the files were written rather than in either party
order, the field comes off.

## The one thing a rename can still be seen to do

A character who has ever been taken out of the party stands on the save disk
as a file of their own. Renaming that character in Wish renames the record and
not the file, so `ADD CHARACTER TO PARTY` still lists the old name, and adding
it brings back the copy the file holds rather than the renamed character.
Wish does not read or write those files at all, which is a gap rather than
something the rename broke -- but it is the only route by which an old name
survives a rename, and it goes through the directory rather than through
`+$C00`.
