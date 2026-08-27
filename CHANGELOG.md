# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-08-26

### Added

- File > Open remembers the folder your last save came from, and starts there next time instead of wherever the dialog was last left.

### Changed

- Character editor reorganised onto tabs -- Stats, Inventory and Spells -- with the roster and combat icon shown above them, so the window no longer has to be as wide.

### Fixed

- Live automapper reads party stats and runs its five live actions (heal, store/restore spells, identify, quickfight) from the correct memory on Curse of the Azure Bonds and Secret of the Silver Blades, instead of Pool of Radiance's addresses.
- Fast Travel now confirms the game running in the emulator is the one believed before acting, instead of trusting a saved preference that could be stale or wrong.
- Character editor's header no longer draws on top of itself when the window is narrowed, and the window now fits a 1280x720 screen at any interface font size.
- Automapper window now fits a 1280x720 screen at a larger interface font too, instead of growing past it.
- Roster's Name column stays within its width limit instead of growing past it; a long name is shortened with an ellipsis instead.
- Roster's horizontal scroll bar no longer hides the last character's row.
- Roster shows the open title's own race and class names, instead of always showing Pool of Radiance's.
- A Silver Blades ranger's spellbook is no longer greyed out as if he knows no spells.
- Live roster no longer misreads party stats off a full-screen picture on Silver Blades; it holds its last good reading instead.
- Character editor's Spells tab now names every spell on Curse of the Azure Bonds and Secret of the Silver Blades, instead of leaving them unlabelled.
- Exporting a Curse or Silver Blades character to YAML no longer stops partway through the spellbook.
- Spells tab's "Castable per level" field no longer reads as all zeros for a spellcaster; it was showing a clipped tail of the real value.

## [0.1.0] - 2026-08-23

### Added

- Live automapper that attaches to a running VICE emulator and draws the map as you walk it.
- Fog of war, revealing the area as you explore, which can be turned off.
- Notes pinned to any square, nine types, kept per area and per game.
- Combat view showing the whole battlefield with hit points in each square.
- Party panel showing HP, XP, AC, THAC0, readied items, active effects and level-up.
- Quest log showing your commissions from the council and their progress.
- Fast Travel to visited areas.
- Party actions: heal, store and restore memorized spells, identify items, toggle quickfight.
- Character editor for `.D64` save disks, needing no emulator.
- Editing of abilities, hit points, experience, levels, money, saving throws and thief skills.
- Editing of the spellbook and of memorized spells.
- Editing of inventory and item traits.
- Combat icon editor.
- Level up, which rolls hit points, updates saving throws, spell capacity and thief skills, heals to full, and picks the class with the highest experience limit for multi-class characters.
- Preview of changes before writing, and a backup of the disk on every save.
- `wish` command, opening the window on a save disk given one.
- `wish export` and `wish import`, round-tripping a party through YAML.
- `wish --svg`, rendering a map to SVG offline.
- `wish --forget`, clearing remembered squares while keeping notes.
- Support for Pool of Radiance.
- Partial support for Curse of the Azure Bonds and Secrets of the Silver Blades, where character editing should work but bugs are expected.

[Unreleased]: https://github.com/malcyon/wish/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/malcyon/wish/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/malcyon/wish/releases/tag/v0.1.0
