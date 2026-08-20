# Pool of Radiance (C64) — Overview

SSI, 1988. Eight disk sides plus a boot disk and a user-created save disk. This project
reverse engineers enough of the game to build a **character editor**; it is not a port and
not a full disassembly.

## Disks on this machine

`/mnt/media/roms/c64/Pool of Radiance Disks/`

| Image | Role |
|---|---|
| `POOL1.D64` … `POOL8.D64` | game sides 1–8, swapped in-game with Alt+N via the fliplist |
| `POOLBOOT.D64` | separate booter (`POOL BOOTER`, `POOLRA`–`POOLRE`) |
| `PORSAVE.D64` | **save disk** — the target of this project. Six characters, nothing readied |
| `PORSAVE2.D64` | the same party after shopping — banded mail, shields, leather. The pair that located armour class and THAC0 |
| `PORSAVE3.D64` | a later state of the same party |
| `PORSAVE4.D64` | MALCYON with DEX edited 16 → 18; the save that proved AC is cached, not recomputed |
| `PORSAVE5.D64` … `PORSAVE9.D64` | leaving the inn, then the controlled walk that located the party's position |
| `PORSAVE10.D64` | eight full 580-byte exports and no `SAVEDGAME0` — the roster disk that gave the size flag |
| `PORSAVE11.D64` | the latest state: wounded characters, a full inventory, and the only roster page of ours that differs from the shopping trip's |
| `POOL1.D64.orig` | pristine copy of side 1 |
| `Pool of Radiance.vfl` | VICE fliplist covering all sides |

Two more disks came from outside the project and live in `~/Downloads`:

| Image | Role |
|---|---|
| `npc_party.d64` | a save found online: three player characters and five NPCs, levels 4–8. One character's experience is a saturated `$FFFFFF` where its shipped record holds 0, so an editor has been near it — but the five NPCs are the game's own `MON*` records, played with rather than rewritten. The only specimen with eight slots filled, characters above level 1, and spells memorised |
| `poolce.d64` | "POR EDITOR V5", a listable 1989 BASIC character editor plus its readme. Corroborates our record layout offset for offset, and carries the item name table and 162 complete item records |

Both are described in `docs/90-specimens.md`.

`POOL1.D64` has been written to by the game (it contains a saved character, `\x01BRUTUS`),
so **diff against `POOL1.D64.orig`**, never against `POOL1.D64`.

## How a session runs

Launched by `~/.local/bin/pool-of-radiance`, which runs the VICE Flatpak (`x64sc`) with the
fliplist preloaded and autostarts `POOL1.D64`.

**JiffyDOS:** this VICE install has JiffyDOS. The game asks at launch whether to disable its
own fastloader — answer **`Y`**. JiffyDOS does the fast loading; leaving the game's loader on
conflicts with it, and the failure mode looks like a bad disk image rather than a loader clash.

`POR_DEBUG=1` additionally enables VICE's binary monitor on `127.0.0.1:6502` and grants the
Flatpak network access. See `docs/40-memory-map.md`.

## Code organisation on disk

Side 1 holds ~100 PRG files. The game is heavily **overlaid** — it loads code and data on
demand rather than holding everything resident. Relevant groupings:

- **code overlays**: `BOOT`, `INIT`, `LIBRARY`, `CAMP`, `COMBAT`, `DUNGEON`, `POST.COM`,
  `COM.PREP`, `LOAD/SAVE`, `MDRIVER`, `LINKER`
- **data**: `ECL*` (encounter/event scripts), `GEO*` (geometry/maps), `PIC*`, `HEAD*`, `BODY*`,
  `SPRITE*`, `COMPIC*`, `WALLSET*`/`WALLDEF*` (graphics), `MON*` (monsters),
  `ITEMFILE*` / `ITEMS` / `ITEMNAMES`, `SPELLE*` / `SPELLN*` (spells), `CHARSET`, `MUSIC`

Only `LOAD/SAVE`, `CAMP` and `INIT` matter for a character editor. The rest is out of scope.

Note: the *game data* files are reported elsewhere to be ByteKiller-compressed. The **save
data is not** — it is stored uncompressed, which is why this project is tractable.

## Two files a save disk holds

A save disk carries `SAVEDGAME0` (a verbatim image of `$4900`–`$64FF`) and
`SAVEDGAME1` (`$8300`–`$8AFF`). Both matter, and neither is what its name
suggests. `SAVEDGAME0` holds the character *records* **and** the party's place in
the world — where it is standing, which way it faces. `SAVEDGAME1` holds the
numbers the game *derives* — armour class, THAC0, current hit points, movement —
and nothing about the world at all. A tool that reads only `SAVEDGAME0` will find, as the author of
the 1989 editor did, that AC and THAC0 appear to be nowhere at all.

Exported characters are a third thing: a single `\x01NAME` PRG holding the
580-byte record on its own, loading at `$6B00`. An export has no roster block.
