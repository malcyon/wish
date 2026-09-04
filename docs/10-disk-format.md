# 1541 D64 container format

Verified empirically against `POOL1.D64.orig` and the player's fifteen `PORSAVE*.D64` saves
(all 174848 bytes, 35 tracks).

Commodore documented most of this, and where it did the page is cited inline: the *Commodore
1541 Disk Drive User's Guide*, September 1982 — Appendix D "Disk formats", pp. 64–68, for the
BAM, the directory and the file layouts, Appendix B, pp. 52–56, for the error codes, and
`docs/152-commodore-manuals.md` for where the manual is kept and how its page numbers run.
Nothing below rests on it: every number here was measured first, and the citations say which of
them Commodore agreed with. Two places where it disagrees are marked as such.

## Geometry

Tracks are numbered from 1. Sectors per track:

| Tracks | Sectors |
|---|---|
| 1–17 | 21 |
| 18–24 | 19 |
| 25–30 | 18 |
| 31–35 | 17 |
| 36–42 | 17 |

Byte offset of (track, sector) = `(sum of sector counts for tracks 1..track-1 + sector) * 256`.

**Commodore prints the first four bands twice** — Table 6.1 on p. 28 and "Block distribution by
track" on p. 65 — and its specification page (p. 3) gives 174848 bytes per diskette and 683
blocks, 664 of them free on a blank disk. Three numbers this page measured separately.
**The guide is 35 tracks throughout**, so the last row of the table above is outside anything
Commodore documented — a 1541 can be driven past track 35 by software that knows how, and the
guide never mentions it.

## Six variants, and only one of them writable

`goldbox/d64.py` accepts **six** sizes and refuses anything else — a size we cannot name is a
file we cannot claim to understand. Tracks 1–35 sit at the same offsets in every variant,
which is why a 40-track image is readable by code that only knows about 35.

| Size | Tracks | Error bytes | Seen here |
|---|---|---|---|
| 174848 | 35 | no | every save disk this project writes |
| 175531 | 35 | yes | Curse side 4 |
| 196608 | 40 | no | — |
| 197376 | 40 | yes | Champions of Krynn side A |
| 205312 | 42 | no | unseen |
| 206114 | 42 | yes | unseen |

**Error bytes are advisory and the reader does not act on them.** One byte per sector
appended after the sector data, `1` meaning "read cleanly". On the specimens held they mark
*padding*, not damage: all 85 sectors on Champions of Krynn side A's tracks 36–40 carry
code 3, and no sector chain on that disk leaves track 35. They are exposed through
`D64.error_code` and nothing else consults them.

**Code 3 is DOS error 21, "no sync character".** The map is an emulator convention rather than
Commodore's — byte 1 is "no error", bytes 2 to 11 are DOS errors 20 to 29 in order (VICE manual
§17.5.4) — and this page glossed code 3 as "no header found" until 2026-09-04, which is error 20
and one row up. The correction is in the padding's favour: Appendix B, p. 53, puts error 21 down
to an "unformatted or improperly seated diskette", where error 20 wants "an illegal block number,
or the header has been destroyed".

**Only the plain 174848-byte image is writable**, enforced by `ReadOnlyImageError` on
`write_sector`, `write_file_inplace` and `save`. The other variants are rips of other
people's disks rather than save disks, and their directories are not always the drive's own
work — Death Knights of Krynn's carries PETSCII art in the entries and a zero block count
against every real file, which a rewrite that trusts the directory would corrupt. The same
disk's BAM header is hand-written too: `2F` at byte 164 and `41 0D` at 165–166, where a
formatted disk has a shifted space and `2A`. Three editor disks here have `A0 A0` there instead,
so "is the DOS type `2A`?" separates a drive's work from somebody's build script on 9 of the 79
images on this machine.

## Directory

Chain starts at **track 18, sector 1** — which is also what the BAM's first two bytes point at,
and what Appendix D gives on p. 67. Each 256-byte directory sector:

```
0..1    next (track, sector); track == 0 means end of chain
2..     8 entries of 32 bytes
```

**End of chain is signalled by track == 0 only — never by the sector byte.** On `PORSAVE.D64`
the directory terminator is `00 FF`: track 0, sector 0xFF. The "last valid byte index"
convention from data sectors leaks into the directory link too, so any code that treats a
sector value of 0 as the terminator will mis-walk the chain.

Entry fields used here. Appendix D, p. 67, has the same ones, and gives the type byte as
`128 + type` with type 2 = PROGram, so a closed PRG is `0x82`:

```
+0      file type   (0x82 = PRG, 0x00 = unused slot)
+1..2   first (track, sector) of the file
+3..18  name, 16 bytes, padded with 0xA0
+28..29 block count, little endian
```

**Do not sanitise names.** Real filenames on the save disk contain a leading `0x01` control
byte — a saved character is `\x01BRUTUS`, not `.BRUTUS`. Community notes describe copied
characters needing a name starting with `&`; the same mechanism, a non-printable/marker prefix
distinguishing character files from ordinary ones.

## File data sectors

```
0..1    next (track, sector)
2..255  payload
```

When next-track is `0`, next-**sector** is the index of the **last valid byte**, so that final
sector's payload is `bytes[2 : next_sector + 1]`.

**The User's Guide does not document this**, so there is no point looking: its sequential and
program file layouts (p. 66) describe every block as a two-byte link and 254 bytes of data and
say nothing about the last one. The closest it comes is BLOCK-WRITE on p. 30, where "a pointer
in the DOS keeps track of how many characters there are" and "that pointer is recorded on the
disk".

## PRG load address

Every PRG's first two bytes are a little-endian load address. All three files on the save disk
are PRGs, so their raw contents are 2 bytes longer than the data they represent.

## The BAM — track 18 sector 0

```
0..1    link to the first directory sector: 18, 1
2       DOS version, 0x41 = 'A'
3       unused, 0
4..     four bytes per track, tracks 1..35:
            +0  free blocks on the track
            +1..3  bitmap, little endian, bit N = sector N; a SET bit is FREE
0x90    disk name, 16 bytes, padded with 0xA0
0xA0    0xA0 0xA0
0xA2    disk id, 2 bytes
0xA4    0xA0
0xA5    DOS type, "2A"
0xA7    0xA0 x 4
0xAB    zero to the end of the sector
```

Rebuilding all 35 track entries from the sector counts reproduces that sector byte for byte on
all fifteen of the player's `PORSAVE*.D64` saves. A blank 35-track disk reports **664** blocks
free, which is every sector but track 18's nineteen — the drive leaves the directory track out
of the count and so does `D64.blocks_free`, and the User's Guide's specification page (p. 3)
gives the same 683 and 664.

**Appendix D agrees on the first four bytes and on the bitmap** (p. 65): bytes 0,1 are printed
as `18,01`, byte 2 as decimal 65 — "ASCII character A indicating 4040 format" — byte 3 as a null
flag, bytes 4–143 as the bit map for tracks 1–35, and a **set** bit as an available block.

**Its directory-header table, p. 66, is the one place the manual will mislead you.** It gives
the disk name as bytes 144–161, two wider than the sixteen the drive fills — the extra pair is
the `A0 A0` listed at `0xA0` above, so nobody is ever wrong by it. Then it prints "165—166" for
the `2A` and "166—167" for the shifted spaces after it, overlapping byte 166 with itself, and
"177—255" for the nulls, leaving 168–176 described by nothing at all.

The disks settle it. `tools/bamsweep.py` reads bytes 144–255 of track 18 sector 0 on every image
it is given; over the **79** `.d64` files on this machine the shifted spaces are bytes
**167–170** on 73 and the nulls run from **171** on 79 of 79. All six exceptions are cracked or
hand-built images whose header was rewritten — five Champions of Krynn sides carry `00` at both
160–161 and 167–170, and `POOLBOOT.D64` carries `A0 00 00 00` — and none is a disk a drive
formatted. So the printed ranges are a typesetting slip from 1982 and the layout above is what
the 1541 writes.

## Building a disk from nothing

`D64.blank()` formats an image; `D64.write_file()` allocates blocks, writes the sector chain
and links a directory entry, growing the directory chain when eight entries are not enough.
Written for #118, so a DOS save can be imported without a `.d64` the player already had.

**Neither the disk name nor the placement of a file's blocks is something the game insists on.**
Thirteen of the fifteen save disks are named `" "` and two `"BLANK"`; thirteen space a file's
blocks six sectors apart and two space them ten. All fifteen are saves the player made with the
game itself, so the game reads all of it. `FILE_INTERLEAVE` is 6 and both are parameters.

The allocation rule, which reproduces the thirteen clean specimens exactly:

| | |
|---|---|
| track order | 17 down to 1, then 19 up to 35; track 18 is never given to a file |
| first block | the lowest free sector on the first track that has one |
| each block after | `(previous + 6) mod sectors on the track`, then step forward one sector at a time until a free one |
| a full track | carry the running sector number onto the next track rather than restarting at 0 |
| directory chain | the same rule with an interleave of **3**, on track 18 |

The track carry is what puts `SAVEDGAME0`'s spill from track 17 sector 19 onto track 16 sector
**4**, and it is the part a plausible-looking allocator gets wrong.

**Do not take the manual's one sentence on this as the rule.** P. 28 says "Track 18 is used for
the directory, and the DOS fills up the diskette from the center outward", having said two lines
earlier that track 1 is at the outside and track 35 at the centre. Read literally that is
backwards, and read charitably — outward from track 18 — it describes only the first leg, 17 down
to 1. It says nothing about the second leg, 19 up to 35, which is where a save lands once the
outer half is full, and nothing about the interleave, which appears nowhere in the guide.

**Verified against the drive's own work.** Read `SAVEDGAME1` and `SAVEDGAME0` off `PORSAVE13.D64`
and write them onto a blank built here, in that order: the two images differ in **432 bytes and
no others**, and those 432 are exactly the two files' final-sector slack — 236 after
`SAVEDGAME1`'s last 18 payload bytes, 196 after `SAVEDGAME0`'s last 58. BAM, directory, both
sector chains and every payload byte match. `tests/test_d64_blank.py` computes the slack from
the chain lengths rather than from the number 432, and skips where there are no disks.
Interleave 3 for the directory likewise reproduces all thirteen directory sectors of
`POOL1.D64.orig`'s 103-entry directory.

**An unused sector reads as 256 zero bytes** — all 643 of them on `PORSAVE13.D64`, and every
unused sector on fourteen of the fifteen disks. The one exception holds the tail of something
scratched on `PORSAVE.D64`, which is what a 1541 does: it frees a block without wiping it.
`D64.blank()` zero-fills.

**Eight 32-byte slots starting two bytes in would need 258 bytes and a sector is 256.** The last
two bytes of every slot are the next slot's first two, which nothing uses — except slot 0's,
which are the sector's link. Appendix D lays the eight out as bytes 2–31, 34–63, 66–95 and so on
to 226–255 (p. 67): thirty bytes each, with the same two-byte gaps. A write that clears a whole 32 bytes wipes the *next* sector's link
when it fills slot 7, and the rest of the directory disappears. `ENTRY_FIELDS` is 30 for that
reason.

**A file is never grown or replaced.** `write_file` refuses a name already in the directory and
nothing scratches a file, so no block is ever freed. 144 files is the limit: eighteen directory
sectors, because sector 0 of track 18 is the BAM — and 144 per diskette is what the User's Guide
puts on its specification page (p. 3) and in its opening paragraph on p. 2.

## Rewriting a file in place

The other writer: rewrite a save **at the same block count**, reusing the existing sector chain.

**Final-sector slack matters.** The bytes after the payload in a file's last sector hold
leftover garbage from whatever previously occupied those sectors. A rewrite must touch only
`[2 : 2+payload_len]` plus the link bytes, leaving the slack alone — otherwise "write the same
content back" fails to be byte-identical. A same-block-count-but-shorter write therefore leaves
stale bytes in the tail, which is correct 1541 behaviour and not a bug. The User's Guide says as
much of the drive's own block deallocation: BLOCK-FREE, p. 31, "doesn't really erase any data
from the disk — just frees the entry, in this case just in the BAM", and it calls SCRATCH the
same thing for a whole file.

## A second opinion on a disk

`goldbox/d64.py` is the reader this project uses, but VICE ships the reference tool and the
Flatpak will run it: `flatpak run --command=c1541 net.sf.VICE`. It reaches `/mnt/media` and
`$HOME` (the Flatpak grants `filesystems=home`), so a `list`, `extract` or `validate` on any
image here is one command away when a parse looks wrong.

## Observations across both images

- Directory `block_count` equalled the true chain length and `ceil(len/254)` for all 106 files
  across both images, so the field is trustworthy — but chain walking should still follow the
  links (with loop detection) rather than trust it.
- `POOL1.D64.orig`: 103 entries, all type `0x82` (closed PRG), disk name `DISK A SIDE 1`, id `S1`.
- `PORSAVE.D64`: disk name `BLANK`, id `00`.
- **No file on the game disk has a non-printable name byte.** The `0x01` prefix is a *save-disk
  character-file* convention, not a general game-disk one.
