# Disks, files, and how to triage them

## The 1541 D64 container

Verified empirically against two 174848-byte, 35-track images.

Sectors per track: 21 for tracks 1-17, 19 for 18-24, 18 for 25-30, 17 for
31-35. Byte offset of `(track, sector)` is `(sum of sector counts for tracks
1..track-1 + sector) * 256`.

**Directory.** Chain starts at track 18, sector 1. Each 256-byte sector holds a
2-byte link then eight 32-byte entries.

```
+0      file type   (0x82 = closed PRG, 0x00 = unused slot)
+1..2   first (track, sector)
+3..18  name, 16 bytes, padded with 0xA0
+28..29 block count, little endian
```

**End of the directory chain is signalled by track == 0 only — never by the
sector byte.** A real save disk terminates with `00 FF`: track 0, sector 0xFF.
The "last valid byte index" convention from data sectors leaks into the
directory link, so code that treats sector 0 as the terminator mis-walks the
chain.

**Data sectors.** 2-byte link then payload. When next-track is 0, next-*sector*
is the index of the **last valid byte**, so the final payload is
`bytes[2 : next_sector + 1]`.

**PRG load address.** Every PRG's first two bytes are a little-endian load
address, so raw contents are two bytes longer than the data they represent.
This is free information about where a file is *meant* to go — and for overlays
it is a lie (see `live-memory.md`), but for data files it is usually true.

**Do not sanitise filenames.** A saved character on a Gold Box save disk carries
a leading non-printable marker byte — `$01` in Pool of Radiance, `$02` in Curse.
The name is `\x01BRUTUS`, not `.BRUTUS`. No file on a *game* disk has a
non-printable name byte; the marker is a save-disk convention.

**Writing.** Rewrite in place, at the same block count, reusing the existing
sector chain — that avoids BAM allocation entirely. Touch only
`[2 : 2+payload_len]` plus the link bytes: the slack after the payload in the
last sector holds leftover garbage from whatever occupied those sectors before,
and disturbing it breaks byte-identical round-tripping. A shorter write at the
same block count therefore leaves stale bytes in the tail. That is correct 1541
behaviour, not a bug.

Directory `block_count` matched the true chain length for all 106 files across
two images, so the field is trustworthy — but walk the links anyway, with loop
detection.

## Triaging the file inventory

Group every file by name stem and record size, count and load address. Two
measurements do most of the work.

**Size uniformity.** A set of fixed-size maps looks like *many files, one size*.
In Pool of Radiance `GEO` is 29 files all exactly 1024 bytes, all loading at
`$0400`; nothing else on the disks has that shape (`SQRDATA` three files of two
sizes, `WALLDEF` nineteen of nineteen, `SECSET` eight of five).

**Shannon entropy per byte**, averaged by family. This tells you which families
are even candidates for decoding:

| Entropy | What it is |
|---|---|
| 1.2-1.3 | save games and character exports |
| 1.67 | monster records |
| 2.2-2.5 | item tables |
| **3.36** | **the map family — the lowest-entropy undecoded family on the disks** |
| 4.4-4.7 | character sets, sprites, combat pictures |
| 4.9-5.2 | wall definitions, spell name tables, portrait art |
| 6.2-6.9 | compressed data or 6502 code |

**Attack the lowest-entropy undecoded family first.** Anything above ~6 is
compressed or code and will not yield to statistics.

A caution the log paid for: after three failed readings, the map family was
written off and a graphics family pointed at instead. That was an
over-correction. **The failures were failures of reading, not evidence against
the file.** Entropy put it back in the frame and the format then fell in one
step.

## Families you will meet, by name

| Stem | What it is |
|---|---|
| `GEO*` | map geometry — four planes, see `maps.md` |
| `ECL*` | encounter/event scripts — bytecode for the Gold Box VM |
| `MON*` | monsters, **in the character-record layout** — which is why the race table ends `MONSTER` |
| `ITEMS`, `ITEMFILE*`, `ITEMNAMES` | item type table, per-area item lists, the shared word table |
| `SPELLN*`, `SPELLE*` | spell names and spell effect code |
| `WALLSET*`, `WALLDEF*` | wall graphics: character shapes, and the tiles built from them |
| `SQRPACI*`, `SQRDATA*` | combat-map descriptors and overland data |
| `PIC*`, `HEAD*`, `BODY*`, `CHARPIC*`, `COMPIC*`, `SPRITE*` | art |
| `BOOT`, `INIT`, `LIBRARY`, `LINKER`, `CAMP`, `COMBAT`, `DUNGEON`, `GEN`, `POST.COM`, `COM.PREP` | code overlays |

For a character editor only the loader, camp and init overlays matter. Say so
in the plan and stay out of the rest.

**Game data may be compressed; save data is not.** That asymmetry is what makes
this work tractable — a save is a raw memory image.

## Negative results worth not repeating

Four readings of the map family were ruled out before the right one:

* walls as set bits, in either polarity — connectivity scores nothing once you
  control for density with a shuffled null model;
* the file as a screen picture of tiles — horizontal run lengths are 1.3 to 1.9,
  far too short for a tiled image;
* four bytes per square as N/E/S/W — no assignment makes neighbouring squares
  agree about the wall between them, best score 0.3 where a correct one scores
  near 1.0;
* filtering by squares the party is known to have walked — one file passes,
  which is exactly the rate chance predicts across 29 files.

**Blind statistics on 1024 bytes will not name a square.** What settled it was
a reimplementation of a sibling game found in source, plus a self-check
(reciprocity) that needs no ground truth. Search for somebody's reimplementation
before searching for documentation: nobody wrote the 1988 format down in prose
anywhere, and it survives only as code.
