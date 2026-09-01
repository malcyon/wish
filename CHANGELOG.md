# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Combat messages now show what the dice actually did underneath the game's own line -- the d20 rolled, what was needed to hit, and the damage. ([#139](https://github.com/malcyon/wish/issues/139))
- Inventory's weight column can now be edited directly, in pounds.

### Changed

- Heal Party and the Fast Travel dropdown are now refused during a fight, the same as Store/Restore Spells and Identify; Heal Party's message now names who was healed instead of giving a bare count. ([#146](https://github.com/malcyon/wish/issues/146))
- Combat messages are now shown in ordinary sentence case, instead of the game's own all-capitals shouting.
- Sleeping and held or paralysed enemies are now marked gold on the combat view, the same as helpless ones, and the tooltip names which condition applies.
- The Commissions panel is now called the Quest Log, and its "Commissions completed" line now reads "Quests completed".

### Removed

- Renaming a character, which could fail silently and leave the save unchanged with no visible error. ([#145](https://github.com/malcyon/wish/issues/145))

### Fixed

- Character editor's Combat box now shows the number on the character sheet for THAC0 and armour class, instead of the raw stored byte. ([#149](https://github.com/malcyon/wish/issues/149))
- Automapper reconnects to the emulator after losing it mid-session, instead of needing Wish restarted. ([#151](https://github.com/malcyon/wish/issues/151))
- Fast Travel into New Phlan no longer draws it with the wall art of the area you warped from. ([#156](https://github.com/malcyon/wish/issues/156))
- Fast Travel and Return no longer flicker off for a second while the party stands still; a click now waits briefly for the game to be ready instead. ([#152](https://github.com/malcyon/wish/issues/152))
- Round counter shown beside combat messages now resets at the start of each fight, instead of climbing across every fight in the session.

## [0.1.2] - 2026-08-30


### Changed

- Refactored UI layout.
- Combat icon editor now uses dropdowns to limit choices to the 8 hardware-supported colors, replacing the free color picker.


### Fixed

- Refused experience point totals that exceed the 3-byte limit supported by DOS saves. ([#111](https://github.com/malcyon/wish/issues/111))
- Fixed an issue where the loaded-files cache wouldn't rebuild if the template stayed in the same area. ([#121](https://github.com/malcyon/wish/issues/121))
- Fixed the conversion report to correctly account for SAVEDGAME1 instead of only SAVEDGAME0. ([#120](https://github.com/malcyon/wish/issues/120))
- Ensured a new character's icon colors are written explicitly, avoiding cases where the figure was painted the combat floor's grey color. ([#112](https://github.com/malcyon/wish/issues/112))
- Allowed select_row to read cursors at specific columns in the automapper. ([#124](https://github.com/malcyon/wish/issues/124))
- Fixed combat icon rendering and dropdown synchronization artifacts.

## [0.1.1] - 2026-08-26

### Added

- File > Open remembers the folder your last save came from, and starts there next time instead of wherever the dialog was last left. ([#66](https://github.com/malcyon/wish/issues/66))

### Changed

- Character editor reorganised onto tabs -- Stats, Inventory and Spells -- with the roster and combat icon shown above them, so the window no longer has to be as wide. ([#43](https://github.com/malcyon/wish/issues/43))

### Fixed

- Live automapper's five actions -- heal, store and restore memorised spells, identify items, turn quickfight off -- now act on the open title's own memory on Curse of the Azure Bonds and Secret of the Silver Blades, instead of Pool of Radiance's. ([#29](https://github.com/malcyon/wish/issues/29))
- Fast Travel now confirms the game running in the emulator is the one believed before acting, instead of trusting a saved preference that could be stale or wrong. ([#21](https://github.com/malcyon/wish/issues/21))
- Automapper window now fits a 1280x720 screen at a larger interface font too, instead of growing past it. ([#77](https://github.com/malcyon/wish/issues/77))
- Roster shows the open title's own race and class names, instead of always showing Pool of Radiance's. ([#78](https://github.com/malcyon/wish/issues/78))
- A Silver Blades ranger's spellbook is no longer greyed out as if he knows no spells. ([#86](https://github.com/malcyon/wish/issues/86))
- Live roster no longer shows wrong hit points when the game puts a picture over the whole screen; it keeps its last good reading until the party is readable again. ([#82](https://github.com/malcyon/wish/issues/82))
- Character editor's Spells tab now names every spell on Curse of the Azure Bonds and Secret of the Silver Blades, instead of leaving them unlabelled. ([#80](https://github.com/malcyon/wish/issues/80))
- Exporting a Curse or Silver Blades character to YAML no longer stops partway through the spellbook. ([#85](https://github.com/malcyon/wish/issues/85))
- Spells tab's "Castable per level" field no longer reads as all zeros for a spellcaster; it was showing a clipped tail of the real value. ([#42](https://github.com/malcyon/wish/issues/42))

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

[Unreleased]: https://github.com/malcyon/wish/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/malcyon/wish/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/malcyon/wish/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/malcyon/wish/releases/tag/v0.1.0
