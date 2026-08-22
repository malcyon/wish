# 1541 D64 container format

Verified empirically against `PORSAVE.D64` and `POOL1.D64.orig` (both 174848 bytes, 35 tracks).

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

## Six variants, and only one of them writable

`por/d64.py` accepts **six** sizes and refuses anything else — a size we cannot name is a
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
code 3 (no header found) and no sector chain on that disk leaves track 35. They are exposed
through `D64.error_code` and nothing else consults them.

**Only the plain 174848-byte image is writable**, enforced by `ReadOnlyImageError` on
`write_sector`, `write_file_inplace` and `save`. The other variants are rips of other
people's disks rather than save disks, and their directories are not always the drive's own
work — Death Knights of Krynn's carries PETSCII art in the entries and a zero block count
against every real file, which a rewrite that trusts the directory would corrupt.

## Directory

Chain starts at **track 18, sector 1**. Each 256-byte directory sector:

```
0..1    next (track, sector); track == 0 means end of chain
2..     8 entries of 32 bytes
```

**End of chain is signalled by track == 0 only — never by the sector byte.** On `PORSAVE.D64`
the directory terminator is `00 FF`: track 0, sector 0xFF. The "last valid byte index"
convention from data sectors leaks into the directory link too, so any code that treats a
sector value of 0 as the terminator will mis-walk the chain.

Entry fields used here:

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

## PRG load address

Every PRG's first two bytes are a little-endian load address. All three files on the save disk
are PRGs, so their raw contents are 2 bytes longer than the data they represent.

## Writing

For this project we only ever rewrite a save **in place, at the same block count**, reusing
the existing sector chain. That avoids BAM allocation entirely. Growing or deleting files is
deliberately not implemented.

**Final-sector slack matters.** The bytes after the payload in a file's last sector hold
leftover garbage from whatever previously occupied those sectors. A rewrite must touch only
`[2 : 2+payload_len]` plus the link bytes, leaving the slack alone — otherwise "write the same
content back" fails to be byte-identical. A same-block-count-but-shorter write therefore leaves
stale bytes in the tail, which is correct 1541 behaviour and not a bug.

## A second opinion on a disk

`por/d64.py` is the reader this project uses, but VICE ships the reference tool and the
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
