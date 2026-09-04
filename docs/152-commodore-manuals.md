# The Commodore manuals

Three original Commodore manuals are on this machine. They are the authority
for what the *hardware* does — where the screen is, what the sixteen colour
codes are, which byte is which opcode — as against what *the game* does, which
is what the rest of this knowledge base measures.

**This page is the only place that names a path.** Everywhere else cites a
manual, a section and a page, so that a citation survives the files moving
again — which they already did once, from `~/Downloads` on 2026-09-04.

## The three

| manual | published | edition | pages | text layer |
|---|---|---|---|---|
| *Commodore 64 User's Guide* | Commodore Business Machines, Inc. | First Edition, Eighth Printing — 1984; © 1982. ISBN 0-672-22010-5 | 184 PDF / ~168 printed | **none** — a page scan |
| *Commodore 64 Programmer's Reference Guide* | Commodore Business Machines, Inc. | FIRST EDITION, EIGHTH PRINTING — 1983; © 1982. ISBN 0-672-22056-3 | 518 PDF / ~493 printed | **none** — a page scan |
| *Commodore 1541 Disk Drive User's Guide*, "A Friendly Introduction to Your 1541 Disk Drive" | Commodore Business Machines Electronics Ltd. | no edition or printing statement; the copyright line reads September 1982 | 80 PDF / ~74 printed | **OCR, and it works** |

Every line above was read rather than inferred: the title and publisher off the
title page, the edition, printing and copyright off its verso, the ISBN off the
back cover. The Programmer's Reference Guide's own introduction titles it the
*Commodore 64/Executive 64 Programmer's Reference Guide*; the title page and
the cover both say Commodore 64.

**Which of the three can be grepped is the difference between a cheap search
and an expensive one.** The two C64 guides have no text layer at all —
`pdftotext` returns 20 bytes for twenty pages — so they must be read as page
images, from the contents list and the index rather than by sweeping. The 1541
guide has an OCR layer and `pdftotext -f N -l M` reads it for nothing.

## Where they are, and why there

    /mnt/media/roms/c64/manuals/commodore_64_users_guide.pdf
    /mnt/media/roms/c64/manuals/commodore_64_programmers_reference_guide.pdf
    /mnt/media/roms/c64/manuals/Commodore_1541_Disk_Drive_Users_Guide_1982-09_Commodore.pdf

`/mnt/media/roms/c64/` is where this machine keeps its C64 library — the same
directory `gamedisks.toml` and `automap.paths.find_disks()` search for game
disks. A manual sits beside the disks it documents rather than in a downloads
folder that gets cleared.

**It is read-only to this project.** Nothing here writes there. Anything that
needs to extract from a PDF copies into `work/` first.

## They are not in the repository, and must never be

`AGENTS.md` bans committing the game's manuals. These are Commodore's hardware
manuals rather than SSI's game manuals, and the same principle governs:
**describe, cite, measure and generate; do not copy.** So no page image, no
transcribed table, no PDF, no renamed slice of one, and not as a test fixture.

Quoting what a finding needs is commentary and is fine — a register address, a
colour number, one row of a table, a short phrase. Reproducing the screen-code
table or the opcode matrix is not, however convenient it would be to have here.

## What each is good for

**User's Guide** — the two tables the combat-icon work rests on.

| section | printed pages | what |
|---|---|---|
| Appendix E, Screen Display Codes | 132–134 | screen codes 0–127, and the rule that 128–255 are the reversed images of 0–127 |
| Appendix F, ASCII and CHR$ Codes | 135–137 | the *other* encoding, which is not the same table |
| Appendix G, Screen and Color Memory Maps | 138–139 | screen memory 1024–2023, colour memory 55296–56295, and the sixteen colour codes |
| Chapter 5, Advanced Color and Graphic Commands | 55–66 | the same ground in prose, for the reader who wants why |

**Programmer's Reference Guide** — the machine, and the processor.

| section | printed pages | what |
|---|---|---|
| Ch. 3, Graphics Locations | 101–106 | screen memory moved by the top four bits of `$D018`; the 16K VIC bank chosen by bits 0–1 of CIA 2 port A at `$DD00`; colour RAM at `$D800`, which **cannot** move; the VIC's 47 registers at `$D000`–`$D02E` |
| Ch. 5, Memory Management | 260–267 | LORAM, HIRAM and CHAREN in the 6510's on-chip port at `$0001`, and what each configuration puts where |
| Ch. 5, MCS6510 instruction set | 232–259 | every instruction with its **hex opcode**, byte count and cycles (235–253), then the mode/cycle matrix (254–259) |
| Ch. 5, The KERNAL | 268–306 | the jump table, the callable routines and the error codes |
| Ch. 5, Commodore 64 Memory Map | 310–319 | zero page and the KERNAL's variables, address by address, with names |
| Ch. 5, the region summary | 320 | the whole 64K in nine rows — see below |
| Ch. 5, Input/Output Assignments | 320–334 | every I/O register by address |
| Appendix G, VIC Chip Register Map | 391–393 | `$D000`–`$D02E`, one row a register |
| Appendix L / N / O | 402–418 / 436–456 / 457–481 | the 6510, VIC-II and SID datasheets |

The region summary on p. 320 is the one page to know, because every overlay
load address in [40-memory-map.md](40-memory-map.md) lands in one of its rows:
screen memory `$0400`–`$07FF` with the video matrix at `$0400`–`$07E7`, normal
BASIC program space `$0800`–`$9FFF`, BASIC ROM `$A000`–`$BFFF` "(or 8K RAM)",
plain RAM `$C000`–`$CFFF`, I/O and colour RAM `$D000`–`$DFFF`, KERNAL ROM
`$E000`–`$FFFF` "(or 8K RAM)".

**1541 User's Guide** — only its drive-side chapters add anything.
`docs/10-disk-format.md` is ahead of it on the BAM, the directory, the geometry
and the interleave, all measured off real disks. What it has that we do not is
the drive's own side: `M-R`/`M-W`/`M-E`, the U-vector table, and the causes
behind error codes 20–74. Its printed page is PDF page − 6.

## Reading a page

Both C64 guides carry front matter the printed numbering does not count, so a
contents entry is not a PDF page. **Add the offset, do not hunt:**

| manual | PDF page = |
|---|---|
| User's Guide | printed page + 16 (PDF 148 is printed 132) |
| Programmer's Reference Guide | printed page + 22 (PDF 257 is printed 235) |
| 1541 User's Guide | printed page + 6 |

**The Programmer's Reference Guide is 173 MB and cannot be opened directly** —
a reader that renders pages refuses it over 100 MB. Cut the range out first,
into `work/` or a scratch directory, and read that:

    gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -dFirstPage=257 -dLastPage=259 \
       -sOutputFile=work/prg-235-237.pdf \
       /mnt/media/roms/c64/manuals/commodore_64_programmers_reference_guide.pdf

Three pages come out at about a megabyte. The other two guides open whole.

## What we checked against them

Four claims this project already made, re-derived from the manuals on
2026-09-04. All four agreed, so all four are corroboration rather than
correction.

* **CONFIRMED — the sixteen colour names in `goldbox/icons.py` are right, 16 of
  16.** `C64_COLOURS` matches Appendix G, p. 139 in order and in meaning; the
  manual spells 11, 12 and 15 `GRAY 1`, `GRAY 2` and `GRAY 3` where we write
  dark grey, grey and light grey, which is the conventional reading of the same
  three codes and not a disagreement.
* **CONFIRMED — `automap.screen.screen_address` computes the screen base the
  way the hardware does.** `bank = (~dd00 & 3) * 0x4000` reproduces all four
  rows of the bank table on p. 101 (value 3 selects bank 0 at `$0000`, value 0
  selects bank 3 at `$C000`), and `((d018 >> 4) & 0xF) * 0x400` reproduces all
  sixteen rows of the screen-memory table on p. 102.
* **CONFIRMED — `$F6` is `INC $nn,X`.** The `docs/148-d6502.md` bug was found
  by a capstone sweep; the INC table on p. 243 gives Zero Page `E6`, **Zero
  Page,X `F6`**, Absolute `EE`, Absolute,X `FE`. Two independent sources now,
  one of them Commodore's own.
* **CONFIRMED — screen codes 32–63 are the ASCII characters of the same
  value**, and 128–255 are the reversed images of 0–127, which is exactly the
  `& 0x7F` in `automap/screen.py`'s decoder. Appendix E, pp. 132–134.

## What they do not cover, so nobody looks again

* **Nothing about the game.** No SSI title existed when any of the three was
  printed, and no address in `$4900`–`$8AFF` means anything to Commodore. The
  manuals bound the *machine*; the overlay map is ours to measure.
* **No PETSCII-to-screen-code conversion table.** The User's Guide prints the
  two encodings as separate appendices (E and F) and never puts them side by
  side, so the relation is ours to derive.
* **`docs/109-icon-choices.md` and `docs/111-map-shading.md` take no citation
  from any of the three.** Both are about our own drawing — Font Awesome and
  game-icons.net glyphs, and hatching in Qt and SVG — and nothing in them is a
  claim about a C64. Checked, on the guess that the combat-icon colours would
  appear there; they do not, they are in `goldbox/icons.py`.
* **Nothing in `docs/100-live-view.md` either.** Every address on that page is
  in the game's own RAM.
