# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-23

The first release. A save editor and live automapper for the Commodore 64
version of *Pool of Radiance* (SSI, 1988), built by reverse engineering the
game's own data.

### Added

#### Live automapper

Attaches to a running VICE emulator and draws the map as you walk it.

- Reveals the area as you explore, with fog of war you can turn off
- Notes pinned to any square, nine types, kept per area and per game
- Combat view showing the whole battlefield with hit points in each square
- Party panel: HP, XP, AC, THAC0, readied items, active effects, level-up
- Quest log showing your commissions from the council and their progress
- Fast Travel to visited areas
- Party actions: heal, store and restore memorized spells, identify items,
  toggle quickfight

#### Character editor

Opens a `.D64` save disk or a standalone `.chr` export. No emulator needed.

- Abilities, hit points, experience, levels, money, saving throws, thief skills
- Spellbook and memorized spells
- Inventory and item traits
- Combat icon editor
- Level up: rolls hit points, updates saving throws, spell capacity and thief
  skills, heals to full, and picks the class with the highest experience limit
  for multi-class characters
- Preview changes before writing, and a backup of the disk on every save

#### CLI tool

```
wish [SAVE.D64]              open the window
wish export SAVE.D64 -o party.yaml
wish import party.yaml -o NEW.D64
wish --svg GEO00 out.svg     render a map offline
wish --forget AREA           clear remembered squares, keeping notes
```

### Game support

| Game | State |
|---|---|
| Pool of Radiance | Works well |
| Curse of the Azure Bonds | Character editing should work; expect bugs |
| Secrets of the Silver Blades | Barely tested; work ongoing |
| Pools of Darkness | Does not work — needs Amiga support |

[Unreleased]: https://github.com/malcyon/wish/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/malcyon/wish/releases/tag/v0.1.0
