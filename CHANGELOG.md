# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Character Editor opens DOS saved games (Open DOS folder… on the Open button's arrow) and Amiga save disks as well as C64 disks, and writes your edits back into the save it opened. ([#511](https://github.com/malcyon/wish/issues/511))
- Save As on the Save button's arrow, or File ▸ Save As…, writes the open party with any unsaved edits as a C64 disk, a DOS save folder or an Amiga disk, for Pool of Radiance, Curse of the Azure Bonds and Secret of the Silver Blades; not every route has been played in the game yet, so expect bugs. ([#511](https://github.com/malcyon/wish/issues/511), [#512](https://github.com/malcyon/wish/issues/512))
- Amiga disks formatted with the Fast File System, the international or directory-cache modes, or long file names now open and save. ([#809](https://github.com/malcyon/wish/issues/809))
- Save As opens a Choose character names window when a name would be cut, erased or drawn differently in the destination game, so you pick the name each character gets. ([#619](https://github.com/malcyon/wish/issues/619))
- Save As asks which items to leave behind when a pack does not fit the destination, and which running spells to leave out when a party has more than the C64 can hold. ([#432](https://github.com/malcyon/wish/issues/432), [#736](https://github.com/malcyon/wish/issues/736))
- Joined scrolls convert between DOS, Amiga and C64 saves. ([#432](https://github.com/malcyon/wish/issues/432), [WISH-4 (A joined scroll in a DOS Silver Blades save shifts everything after it out of the character's pack)](http://plane.morton.lan/wish/projects/9c5c054c-223b-4c0e-b996-2139a5ba25e8/issues/19d4d59d-df0e-4262-93fa-03c8b26429d0))
- Save As to DOS checks that the DOS game folder is the title's own, fills it in from Preferences when that folder holds the title's DOS files, and stays unavailable until the matching folder is chosen. ([WISH-277 (Save As to DOS writes a save the game cannot load when the player picks another title's DOS folder, with no warning)](http://plane.morton.lan/wish/projects/9c5c054c-223b-4c0e-b996-2139a5ba25e8/issues/7fb6d146-febd-4522-bc28-d0b87c52c31a))
- A party under a running spell keeps it, with its remaining time, when saved to another platform, for spells such as Bless, Detect Magic, Prayer, Haste, Strength and Slow Poison; an effect the destination game has no row for still stops the save. ([#600](https://github.com/malcyon/wish/issues/600), [#656](https://github.com/malcyon/wish/issues/656), [#661](https://github.com/malcyon/wish/issues/661), [#666](https://github.com/malcyon/wish/issues/666), [#667](https://github.com/malcyon/wish/issues/667), [WISH-7 (A C64 party under a running spell loses it on the way to DOS or the Amiga with no line anywhere, because the C64 reader reads only the paladin's rows out of the effect arrays)](http://plane.morton.lan/wish/projects/9c5c054c-223b-4c0e-b996-2139a5ba25e8/issues/3208ae51-0656-4de3-b99e-db7f760a8c3d), [WISH-8 (A DOS party under Prayer, the strength and charisma spells, Mirror Image or an effect with no C64 spell row still fails to save as a C64 save, because only the ordinary caster-level spells convert)](http://plane.morton.lan/wish/projects/9c5c054c-223b-4c0e-b996-2139a5ba25e8/issues/7ecacba8-4bcb-4850-9c80-fd6f61197112))
- A paladin's Lay on Hands, and a former paladin's Cure Disease, convert between C64, DOS and Amiga saves. ([#626](https://github.com/malcyon/wish/issues/626), [#628](https://github.com/malcyon/wish/issues/628), [#649](https://github.com/malcyon/wish/issues/649), [#652](https://github.com/malcyon/wish/issues/652), [#658](https://github.com/malcyon/wish/issues/658))
- A Curse of the Azure Bonds or Secret of the Silver Blades party that has not set out yet converts between C64, DOS and Amiga saves and starts the story at its beginning. ([#640](https://github.com/malcyon/wish/issues/640), [#653](https://github.com/malcyon/wish/issues/653))
- Parties of up to eight members open and convert whole, so a seventh or eighth companion is no longer left out. ([#641](https://github.com/malcyon/wish/issues/641), [#655](https://github.com/malcyon/wish/issues/655), [#664](https://github.com/malcyon/wish/issues/664), [#689](https://github.com/malcyon/wish/issues/689))
- A zombie raised with Animate Dead, a charmed companion, a Training Hall hireling's treasure share and Curse's undead turning convert between C64, DOS and Amiga saves. ([#700](https://github.com/malcyon/wish/issues/700), [#667](https://github.com/malcyon/wish/issues/667), [#743](https://github.com/malcyon/wish/issues/743), [#744](https://github.com/malcyon/wish/issues/744), [#758](https://github.com/malcyon/wish/issues/758))
- Character sheet shows Control (Player-controlled or Game-controlled), Morale for companions and Abilities altered, in place of one raw flags byte. ([#623](https://github.com/malcyon/wish/issues/623), [#647](https://github.com/malcyon/wish/issues/647), [#654](https://github.com/malcyon/wish/issues/654))
- Thief skills box shows a thief's Backstab multiplier for the platform of the open save. ([#607](https://github.com/malcyon/wish/issues/607))
- Misc box shows a Turns as: row naming the table a character turns undead on, for the titles and platforms that have one. ([#789](https://github.com/malcyon/wish/issues/789))
- Automapper draws Pool of Radiance's wilderness from your own game disks, with the party's marker, the outdoor coordinate and region on the status line, and Full View and Area View choices. ([#11](https://github.com/malcyon/wish/issues/11))
- Automapper draws Curse of the Azure Bonds' world map as the game's places and roads, with the party's place named, instead of leaving the last area's map and marker on screen. ([#804](https://github.com/malcyon/wish/issues/804))
- Secret of the Silver Blades party cards show condition badges for hasted, blessed, warded, invisible, strengthened, silenced and slowed characters. ([#563](https://github.com/malcyon/wish/issues/563))
- Fast Travel in Pool of Radiance leaves an area through its own exit, so the area's own exit script runs; when the destination is not one of that area's doors it walks the party out through a door that cannot start a fight and finishes the trip, and says so when every way out can start a fight. ([#207](https://github.com/malcyon/wish/issues/207))
- Fast Travel lists Curse of the Azure Bonds' and Secret of the Silver Blades' areas by name, with unnamed areas shown as Area N after the named ones. ([#15](https://github.com/malcyon/wish/issues/15))
- Character Traits names Secret of the Silver Blades' and Curse of the Azure Bonds' effects instead of listing most of them by number. ([#497](https://github.com/malcyon/wish/issues/497), [#561](https://github.com/malcyon/wish/issues/561))

### Changed

- Character sheet's Roster box is now Misc, and shows a character's condition in words and his damage as the game prints it, without the raw tail bytes. ([#761](https://github.com/malcyon/wish/issues/761))
- Inventory lists a character's items from the highest filled slot down, the order the games list them. ([#795](https://github.com/malcyon/wish/issues/795), [#792](https://github.com/malcyon/wish/issues/792))
- Preview changes lines open with a capital letter, and a retired C64 item slot that is filled again reads as an addition. ([#674](https://github.com/malcyon/wish/issues/674), [#673](https://github.com/malcyon/wish/issues/673))
- The C64 emulator choice is now named VICE (C64), keeping a choice saved under the old name. ([#37](https://github.com/malcyon/wish/issues/37))

### Removed

- File ▸ Import ▸ DOS save folder is gone; open the DOS folder in the editor and use Save As C64 instead. ([#52](https://github.com/malcyon/wish/issues/52), [#511](https://github.com/malcyon/wish/issues/511))

### Fixed

- A Secret of the Silver Blades save made before the party has set out now converts to the start of the story, instead of failing to convert. ([#535](https://github.com/malcyon/wish/issues/535))
- A Curse of the Azure Bonds magic-user or cleric converted from Commodore 64 to DOS or Amiga now arrives able to memorise the right number of spells for its level, instead of none. ([#547](https://github.com/malcyon/wish/issues/547))
- Secret of the Silver Blades casters now show their correct spell capacity when their DOS save is open in Character Editor. ([#572](https://github.com/malcyon/wish/issues/572))
- A Curse of the Azure Bonds or Secret of the Silver Blades magic-user converted from Commodore 64 to DOS or Amiga now arrives with the engine's correct THAC0. ([#608](https://github.com/malcyon/wish/issues/608))
- DOS and Amiga conversions now retain a paladin's remaining Cure Disease uses and a running spell's remaining duration. ([#600](https://github.com/malcyon/wish/issues/600))
- A C64 character's emptied item slots no longer show a leftover item in the editor or convert as if still held. ([#672](https://github.com/malcyon/wish/issues/672))
- Saving an edit to a Pool of Radiance character's items or strength on a C64 disk now updates his movement to match, instead of keeping the old value that decides who gets away from a fight. ([#741](https://github.com/malcyon/wish/issues/741))
- A Pool of Radiance character converted to the C64 arrives with the movement and THAC0 the game works out from his armour, load and readied weapon, instead of copied values. ([#740](https://github.com/malcyon/wish/issues/740), [#405](https://github.com/malcyon/wish/issues/405))
- A pack converted to the C64 reads top to bottom in the same order as on DOS, instead of reversed. ([#792](https://github.com/malcyon/wish/issues/792))
- A character with more experience than the C64 can hold, 16,777,215, now converts to the C64 with his experience capped there, instead of stopping the save. ([#597](https://github.com/malcyon/wish/issues/597))
- Secret of the Silver Blades scrolls show their spells in the editor, and a scroll's tooltip no longer lists charges, effect and power lines that hold its spells. ([#764](https://github.com/malcyon/wish/issues/764), [#766](https://github.com/malcyon/wish/issues/766))
- The editor names the spell a Curse of the Azure Bonds or Secret of the Silver Blades wand or potion casts, and the effect of a Curse or Silver Blades item that has no spell, instead of reading them with Pool of Radiance's numbering. ([#765](https://github.com/malcyon/wish/issues/765), [WISH-15 (The editor names the wrong effect for a Curse or Silver Blades wand or potion, because it reads the effect byte with Pool of Radiance's numbering)](http://plane.morton.lan/wish/projects/9c5c054c-223b-4c0e-b996-2139a5ba25e8/issues/bb92746c-3a8b-4ff0-bccf-f822629fcb97))
- Secret of the Silver Blades' Bestow Curse is named in the spellbook. ([#746](https://github.com/malcyon/wish/issues/746))
- A DOS scroll saved while its spell is still being scribed shows that spell in the editor and converts to the C64 as an ordinary scroll. ([#745](https://github.com/malcyon/wish/issues/745), [WISH-11 (A DOS scroll saved while its spell is being scribed shows as an item-only effect in the editor and converts to the C64 with a byte the C64 never writes)](http://plane.morton.lan/wish/projects/9c5c054c-223b-4c0e-b996-2139a5ba25e8/issues/81f8ca77-c4f6-4282-9ca2-c5e4cfef7464))
- A Curse of the Azure Bonds or Secret of the Silver Blades character-only disk is no longer taken for Pool of Radiance, which could zero a Curse cleric's second set of ability scores when his spells were saved. ([#553](https://github.com/malcyon/wish/issues/553))
- A Curse of the Azure Bonds paladin or ranger shows his real spell capacity in the editor instead of nothing, and a Silver Blades ranger's capacity line stays hidden until he has a slot in that class. ([#552](https://github.com/malcyon/wish/issues/552), [#603](https://github.com/malcyon/wish/issues/603))
- Character Traits no longer warns falsely about missing handlers and monster attacks on Silver Blades and Curse spell effects. ([#562](https://github.com/malcyon/wish/issues/562))
- The combat view and combat messages read Curse of the Azure Bonds' and Secret of the Silver Blades' own memory instead of Pool of Radiance's. ([#39](https://github.com/malcyon/wish/issues/39))
- The automapper marker follows a Curse of the Azure Bonds party into a new area such as the sewers, instead of staying on the square it left. ([#805](https://github.com/malcyon/wish/issues/805))
- The automapper marker sits on a Secret of the Silver Blades party's square in The Ruins, and faces the way the party faces. ([#804](https://github.com/malcyon/wish/issues/804))
- Clear Automap Memory clears the explored squares of every area of the current game, including areas whose notes were saved before notes were kept per game. ([#663](https://github.com/malcyon/wish/issues/663))
- The automapper keeps the squares you have explored when Wish crashes or is closed without warning, because it saves them as soon as a step reveals a new one. ([#37](https://github.com/malcyon/wish/issues/37))
- The Heal party tooltip spells conscious correctly. ([#37](https://github.com/malcyon/wish/issues/37))

## [0.1.4] - 2026-09-13

### Added

- Character Traits can now be edited, and the editor shows the active effects currently running on a save. ([#13](https://github.com/malcyon/wish/issues/13))
- Level Up now supports Curse of the Azure Bonds, including training every eligible class together. ([#18](https://github.com/malcyon/wish/issues/18), [#415](https://github.com/malcyon/wish/issues/415))
- The roster now shows a human dual-class character's former class and level. ([#256](https://github.com/malcyon/wish/issues/256))

### Changed

- Combat squares now show a health bar instead of a hit-point number. ([#345](https://github.com/malcyon/wish/issues/345))
- The Quest Log puts completed commissions and side quests under Completed, below active quests. ([#530](https://github.com/malcyon/wish/issues/530))
- Character editor lists known races, classes and alignments by name, without their stored code in front. ([#531](https://github.com/malcyon/wish/issues/531))
- Backup settings now explain how to use one folder for all save backups or a folder beside each save.

### Fixed

- Closing the character editor with unsaved edits now asks whether to save them. ([#489](https://github.com/malcyon/wish/issues/489))
- Imported DOS parties now keep their location and clock. ([#352](https://github.com/malcyon/wish/issues/352))
- Imported DOS characters now keep their correct abilities and THAC0. ([#404](https://github.com/malcyon/wish/issues/404), [#405](https://github.com/malcyon/wish/issues/405))
- Imported DOS characters now keep their fighting level and saving throws. ([#527](https://github.com/malcyon/wish/issues/527))
- Level Up restores one drained level for every training step. ([#526](https://github.com/malcyon/wish/issues/526))
- Joined NPCs no longer appear as drained 255 levels. ([#532](https://github.com/malcyon/wish/issues/532))
- Pool of Radiance DOS imports now prepare empty party slots for companions, so DIRTEN receives a combat figure when he joins. ([#533](https://github.com/malcyon/wish/issues/533))
- Imported Pool of Radiance DOS characters retain all 21 memorised spells. ([#508](https://github.com/malcyon/wish/issues/508), [#509](https://github.com/malcyon/wish/issues/509))
- DOS imports retain each character's treasure share. ([#529](https://github.com/malcyon/wish/issues/529))
- A Curse character disk with a parked character no longer opens as empty. ([#456](https://github.com/malcyon/wish/issues/456))
- Curse's Class list now shows the character's actual class, including regained dual-class combinations, instead of a stale or unrelated class. ([#356](https://github.com/malcyon/wish/issues/356), [#409](https://github.com/malcyon/wish/issues/409))
- Character-sheet tooltips no longer expose technical save details. ([#419](https://github.com/malcyon/wish/issues/419))
- The empty roster no longer leaves most of the editor header blank. ([#471](https://github.com/malcyon/wish/issues/471))
- Combat messages follow the newest line, unless you scroll back to read earlier messages. ([#349](https://github.com/malcyon/wish/issues/349))
- Combat messages now warn when the game's fastest combat speed makes the log incomplete. ([#425](https://github.com/malcyon/wish/issues/425))

## [0.1.3] - 2026-09-06

### Added

- File ▸ Import converts a DOS save to a Commodore 64 save for Pool of Radiance, Curse of the Azure Bonds and Secret of the Silver Blades. ([#131](https://github.com/malcyon/wish/issues/131))
- Combat messages now show the player's dice rolls. ([#139](https://github.com/malcyon/wish/issues/139))
- Inventory's weight column can now be edited.
- The Quest Log now tracks the Ohlo's potion side quest in the Slums. ([#158](https://github.com/malcyon/wish/issues/158))
- Wish now remembers where your save disks are, so you don't have to navigate to it every time. ([#66](https://github.com/malcyon/wish/issues/66))
- Updated map notes to use icons from [game-icons.net](https://game-icons.net)  ([#166](https://github.com/malcyon/wish/issues/166))
- The Automap's left and ride side panels can now be resized. ([#162](https://github.com/malcyon/wish/issues/162))
- Added original Wish logo and mark by artist Dustin Geddy Parker. ([#9](https://github.com/malcyon/wish/issues/9), [#169](https://github.com/malcyon/wish/issues/169))

### Changed

- Disable the Heal and Fast Travel buttons during combat. No cheating! Also, Heal Party's message now names who was healed ([#146](https://github.com/malcyon/wish/issues/146))
- Switched combat messages to lowercase.
- Sleeping, held, and paralysed enemies now have yellow squares on the combat map, so you know who's affected.
- Renamed Commissions panel to Quest Log.
- Fixed the Level Up button crowding out other UI elements on the Roster. ([#168](https://github.com/malcyon/wish/issues/168), [#161](https://github.com/malcyon/wish/issues/161))
- Made the top panel on the character editor resizable. ([#97](https://github.com/malcyon/wish/issues/97))
- Updated the names of the condition icons on the roster.([#196](https://github.com/malcyon/wish/issues/196))

### Removed

- Removed the ability to rename a character. ([#145](https://github.com/malcyon/wish/issues/145))

### Fixed

- Character editor's Combat box now shows the number on the character sheet for THAC0 and armour class, instead of the raw stored byte. ([#149](https://github.com/malcyon/wish/issues/149))
- Automapper reconnects to the emulator after losing it mid-session, instead of needing Wish restarted. ([#151](https://github.com/malcyon/wish/issues/151))
- Fast Travel into New Phlan no longer draws it with the wall art of the area you warped from. ([#156](https://github.com/malcyon/wish/issues/156))
- Fast Travel and Return no longer flicker off for a second while the party stands still; a click now waits briefly for the game to be ready instead. ([#152](https://github.com/malcyon/wish/issues/152))
- Round counter shown beside combat messages now resets at the start of each fight, instead of climbing across every fight in the session.
- THAC0, armour class and four other Combat and Stats fields now show blank on a save slot too small to carry them, instead of a wrong number. ([#150](https://github.com/malcyon/wish/issues/150))
- Combat icons converted from DOS now show the correct colors and shape. ([#130](https://github.com/malcyon/wish/issues/130), [#267](https://github.com/malcyon/wish/issues/267))
- Two characters converted from DOS with the same name both convert now, instead of the second failing to convert. ([#216](https://github.com/malcyon/wish/issues/216))
- A dual-classed Curse of the Azure Bonds character no longer imports with a false warning that its record is corrupt. ([#229](https://github.com/malcyon/wish/issues/229))
- A converted dwarf, gnome or halfling keeps his constitution bonus to saving throws now, instead of arriving three or four points worse. ([#311](https://github.com/malcyon/wish/issues/311))
- A converted cleric or paladin can turn undead on the Commodore 64 now, instead of arriving with the ability switched off. ([#288](https://github.com/malcyon/wish/issues/288))
- A converted Curse of the Azure Bonds party no longer has its last two quest flags reset to unstarted. ([#289](https://github.com/malcyon/wish/issues/289))
- Importing to Curse of the Azure Bonds or Secret of the Silver Blades no longer warns about a missing sheet portrait; neither title's character sheet ever draws one. ([#300](https://github.com/malcyon/wish/issues/300), [#329](https://github.com/malcyon/wish/issues/329))
- The import pane no longer reports a missing portrait twice in two different wordings, and no longer heads an empty list with "Wish cannot currently convert these fields." ([#314](https://github.com/malcyon/wish/issues/314), [#338](https://github.com/malcyon/wish/issues/338))
- Import no longer shows a memory address, an internal issue number or a raw file offset when it explains why a save could not be read or a field could not be converted. ([#176](https://github.com/malcyon/wish/issues/176), [#195](https://github.com/malcyon/wish/issues/195), [#244](https://github.com/malcyon/wish/issues/244))
- A DOS save made before the party set out -- Curse of the Azure Bonds' opening area, or before Pool of Radiance's party has left the training hall -- now converts to the start of the story, instead of failing to convert. ([#301](https://github.com/malcyon/wish/issues/301), [#326](https://github.com/malcyon/wish/issues/326))
- A Curse of the Azure Bonds paladin or Secret of the Silver Blades ranger now shows a class letter and a working experience bar on its roster card, instead of a bare "?". ([#197](https://github.com/malcyon/wish/issues/197))
- Secret of the Silver Blades characters show their own experience progress on the roster card now, instead of Pool of Radiance's. ([#187](https://github.com/malcyon/wish/issues/187))
- A Curse of the Azure Bonds cleric's spell capacity is computed from Curse's own wisdom bonus now, instead of Pool of Radiance's. ([#231](https://github.com/malcyon/wish/issues/231))
- A Curse of the Azure Bonds magic-user levelling up is no longer offered Animate Dead, which the game's own trainer never grants. ([#223](https://github.com/malcyon/wish/issues/223))
- The automapper and the character editor list the party in the game's own order now, instead of backwards. ([#160](https://github.com/malcyon/wish/issues/160))
- The automapper's roster column scrolls now, instead of forcing the window taller for a full party of eight. ([#135](https://github.com/malcyon/wish/issues/135))
- The Automap tab's seen-square count keeps counting while you stay on the map, instead of only updating when you switch tabs and back. ([#239](https://github.com/malcyon/wish/issues/239))
- Warping out of Valhingen Graveyard or Valjevo Castle no longer leaves two wall pieces drawn wrong. ([#179](https://github.com/malcyon/wish/issues/179))
- Fast Travel to the wilderness puts the party on the square that window actually leads to now, instead of wherever it last stood outdoors. ([#178](https://github.com/malcyon/wish/issues/178))
- Fast Travel's Messages tooltip no longer shows a memory address. ([#263](https://github.com/malcyon/wish/issues/263))

## [0.1.2] - 2026-08-30


### Changed

- Refactored UI layout.
- Combat icon editor now uses dropdowns to limit choices to the 8 hardware-supported colors, replacing the free color picker.


### Fixed

- Experience point totals that exceed the 3-byte limit supported by DOS saves are no longer accepted. ([#111](https://github.com/malcyon/wish/issues/111))
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

[Unreleased]: https://github.com/malcyon/wish/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/malcyon/wish/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/malcyon/wish/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/malcyon/wish/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/malcyon/wish/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/malcyon/wish/releases/tag/v0.1.0
