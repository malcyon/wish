# How the Commodore 64, DOS and Amiga versions of the Gold Box games differ

The four games this project covers, Pool of Radiance, Curse of the Azure Bonds, Secret of the Silver Blades and Pools of Darkness, were not ported identically, and this page lists every difference between the ports that Wish has found or had to account for, described by what a player sees.

Every claim carries the project's own grade: **CONFIRMED** (reproduced in the running game or proven from the code beyond argument), **PROBABLE** (read from the code or seen once, not yet reproduced) or **UNKNOWN** (nobody has looked, or the evidence disagrees). A claim with no grade beside it is CONFIRMED by the document it links. The evidence is in [`docs/`](docs/README.md); this page links the page that has it and never repeats a table from the games.

## The short version

- **Pools of Darkness has no Commodore 64 version.** It exists on DOS and the Amiga only. The other three games exist on all three platforms.
- **Most numbers that differ are small, and each port rebuilds some of them itself.** A converted character can show a THAC0, a saving throw or a movement rate that differs by a point or two until the destination game recomputes it, usually at the start of the next fight or when the party is loaded.
- **The Commodore 64 is the outlier more often than not.** It lists the party and a character's items in the opposite order from DOS and the Amiga, keeps a few values (turn undead strength, a strength flag, the constitution bonus to saving throws) in the record where the other ports derive them, and has the smallest limits: one byte of effect duration, 64 running effects for the whole party, 10 trait slots a character and three bytes of experience.
- **Each port keeps some things the others have no place for.** Wish keeps all of those it can and tells the player in the Save As window when one cannot be kept. The section "What a conversion costs a player" lists them.
- **Only Pool of Radiance draws a portrait on the character sheet.** Curse, Silver Blades and Pools of Darkness never show a face there on any port Wish has examined.
- **Pool of Radiance is the only game with a square-by-square overland map.** Curse travels by choosing places from a menu, and Silver Blades and Pools of Darkness have no overland screen that Wish has seen draw a travel grid.

## What exists, and what Wish does with it

| Game | Commodore 64 | DOS | Amiga |
|---|---|---|---|
| Pool of Radiance | Eight game sides plus a boot disk and the player's save disk | Yes | Two floppies, a game disk and a data disk |
| Curse of the Azure Bonds | Six sides | Yes | Boot disk, a second disk of data, and an optional save disk |
| Secret of the Silver Blades | Six sides, three double-sided disks | Yes | Two disks |
| Pools of Darkness | No release | Yes | Three disks, the third holds the save drawer |

Disk counts are from [`docs/00-overview.md`](docs/00-overview.md), [`docs/121-silver-blades.md`](docs/121-silver-blades.md), [`docs/191-the-amiga-save-disk.md`](docs/191-the-amiga-save-disk.md) and #194 (Import and export a Pools of Darkness save between DOS and the Amiga), where Donald states that DOS and the Amiga are the only two ports Pools of Darkness has.

| What Wish can do | Commodore 64 | DOS | Amiga |
|---|---|---|---|
| Open, edit and save characters | Pool of Radiance, Curse, Silver Blades | All four | All four |
| Convert a party to another platform with Save As | Pool of Radiance, Curse, Silver Blades, in every direction among the three platforms | The same three titles | The same three titles |
| Follow the running game on the automapper | Yes, through VICE; the Commodore 64 Ultimate hardware is behind an experimental setting | No backend exists | Behind an experimental setting; Curse, Silver Blades and Pools of Darkness, not Pool of Radiance |
| Level up a character from the live automapper's roster card | Pool of Radiance, Curse, Silver Blades, using each Commodore 64 trainer's own rules | Not offered | Not offered |

- **Pools of Darkness conversion is partial.** The only route is Amiga to DOS, offered by File > Convert behind an experimental setting. DOS to Amiga does not exist, and the Convert window answers "Pools of Darkness saves are not yet supported." for everything else ([`docs/235-destination-game-acceptance-runs.md`](docs/235-destination-game-acceptance-runs.md), #194 (Import and export a Pools of Darkness save between DOS and the Amiga), #651 (Convert a Pools of Darkness party's item vault between DOS and the Amiga along with its saved game)).
- **Gateway to the Savage Frontier and Treasures of the Savage Frontier exist on DOS only.** Their character records are read through Curse's and Pools of Darkness' layouts, which is why a record's size cannot name its title. Wish does not claim to support them ([`docs/145-dos-decode-kit.md`](docs/145-dos-decode-kit.md)).
- **Champions of Krynn and Death Knights of Krynn have Commodore 64 table rows in the code and are not supported** (#604 (Spell capacity for Champions of Krynn falls back to Pool of Radiance's numbers instead of answering that it has no table)).
- **No other platform has been touched.** Apple II, Macintosh and PC-98 appear in the project only as columns in a community photograph of Pool of Radiance's creation menu ([`docs/188-the-sheet-portrait-per-title.md`](docs/188-the-sheet-portrait-per-title.md)). [`docs/236-requirements-for-adding-a-new-platform.md`](docs/236-requirements-for-adding-a-new-platform.md) lists what a new platform would need first.

## Saves

### How each port stores a saved game

| | Commodore 64 | DOS | Amiga |
|---|---|---|---|
| Container | A 1541 disk image. Writing needs the standard 35-track image; the 40- and 42-track and error-table variants Wish reads are read-only | A folder of files | A floppy disk image (ADF) with a save drawer |
| Pool of Radiance | One save file plus a second file holding the roster; a character parked outside the party is its own file | A saved-game file per slot plus one character file, one item file and one effect file per character | A saved-game file per slot (ten slots, letters A to J) plus a character, item and effect file per character |
| Curse and Silver Blades | One save file holds everything; parked characters are separate files | As Pool of Radiance, with different file suffixes for items and effects in each title | The party sits inside the saved game, with no separate character files |
| Pools of Darkness | Does not exist | A saved-game file plus a vault file | Character files in the save drawer, a saved-game file and a vault file |

[`docs/10-disk-format.md`](docs/10-disk-format.md), [`docs/30-savegame-layout.md`](docs/30-savegame-layout.md), [`docs/141-dos-savegame.md`](docs/141-dos-savegame.md), [`docs/165-amiga-savegame.md`](docs/165-amiga-savegame.md), [`docs/191-the-amiga-save-disk.md`](docs/191-the-amiga-save-disk.md) and [`docs/116-second-game.md`](docs/116-second-game.md) have the layouts.

- **DOS characters are bigger in each later game.** The character record is 285 bytes in Pool of Radiance, 422 in Curse, 439 in Silver Blades and 510 in Pools of Darkness, and every title has its own file suffix for items and effects.
- **The Commodore 64 save disk has to be a disk the game can write.** A disk copied while the game still has its save file open cannot be loaded (#298 (A save disk copied out of an emulator slot before the drive closes the file cannot be loaded by the game)).
- **The Silver Blades save is not picked from a list on the Commodore 64.** LOAD SAVED GAME loads the party directly.
- **A DOS save folder can hold more character files than the party has.** The game loads only as many as the saved game's party size says, and Wish does the same (#689 (Wish would open a DOS party as every character file in the folder, not as many as the save's party size counts)). A DOS folder copied without its item files opens with every pack empty, and nothing warns the player (#738 (A DOS save folder copied without its item files converts every character with an empty pack and no warning)).
- **Pool of Radiance and Curse on DOS save the current area's whole script inside the saved game; Silver Blades does not, and the game reloads it.** This is invisible to a player but is why a DOS Pool of Radiance save is 13137 bytes and a DOS Silver Blades save 5469.

### Where the game looks for a save

- **Amiga Pool of Radiance** asks "PATH FOR SAVE RETURN = POOLSAVE:". A bare RETURN uses a separate disk named POOLSAVE in any drive, and the save drawer on the game disk also works.
- **Amiga Curse and Silver Blades** never ask. They read the save drawer of the disk they booted from, then the first drive, then the second, and never the third. A party converted to either game has to be written into the save drawer of a copy of the player's own first disk, not onto a separate save disk (#541 (WinUAE's LOAD SAVED GAME on the Amiga Curse of the Azure Bonds boot disk loads its own bundled party, not the save on the third floppy), #677 (Save As to the Amiga puts a Curse or Silver Blades party on a separate save disk that the game never reads while its own disk A is in DF0)). This is CONFIRMED from the code and by live runs of the converted route.
- **Amiga Pools of Darkness** looks in the save drawer beside the game, then the first and second drives, and asks for "Disk 3" only when all three fail. It needs two marker files in the drawer or the player is asked for a disk (PROBABLE; read from the code, not booted).
- **An Amiga disk with several saved games** converts the slot the player picks in File > Convert (#372 (An Amiga disk with more than one saved game converts its first slot, whichever one the player meant)).
- **Whether a physical write-protect tab matters on real hardware is UNKNOWN.** The project has only run the games in emulators.

### Limits that differ

| Limit | Commodore 64 | DOS | Amiga |
|---|---|---|---|
| Characters in the party | Six player characters in eight slots (the other slots hold companions and scratch space) | Pool of Radiance holds eight; the later games' loaders are PROBABLE at eight | Pool of Radiance holds eight in code, and seven loaded live; the later titles have no cap in code (PROBABLE) |
| Name length | 18 bytes in the record; the longest in the saves Wish has is 15 | 15 characters | 15 characters |
| Experience | Three bytes, at most 16,777,215 | Four bytes in every title | Four bytes |
| Running effects | One shared table of 64 rows for the whole party | A list per character with no count limit | A list per character with no count limit |
| Trait slots | Ten per character, which never expire | None; every effect has a duration | None |
| Memorised spells in the record | 81 in Pool of Radiance, 74 in Silver Blades | 21 in Pool of Radiance, 84 in Curse, 75 in Silver Blades, 141 in Pools of Darkness | Per title |
| Items | 16 slots | 16, and the game refuses a 17th with the word "Overloaded" | 16, same |
| Effect duration | One byte: a count up to 63 and a unit of a minute, ten minutes, an hour or a day | Minutes in a 16-bit number | Minutes in a 16-bit number |

- **A DOS character with more than 16 items is read and written back intact.** Pools of Darkness has an exemption from the item count test for a matching held item whose effect is unmeasured (SPECULATIVE). See [`docs/173-carrying-limits.md`](docs/173-carrying-limits.md).
- **A joined stack of scrolls is one item on DOS and the Amiga and several on the Commodore 64.** In Silver Blades a DOS item can hold up to ten scrolls, so a DOS Silver Blades party can overflow the Commodore 64's 16 slots, and the Save As window asks the player which items or scrolls to leave behind (#432 (A joined scroll in a DOS Silver Blades save shifts everything after it out of the character's pack)).
- **Eleven camp Bless spells on a party of six are 66 running effects.** That fits DOS and the Amiga and does not fit the Commodore 64's 64 rows, so the Save As window asks which effects to leave behind (#727 (Can a Pool of Radiance party carry more running effects than the C64's 64 shared effect rows hold?), #736 (Saving a DOS Pool of Radiance party with more than 64 running effects as a C64 save is refused, though a few camp casts reach that count)). A DOS party under Prayer, the strength and charisma spells or Mirror Image is still refused when saved as a Commodore 64 save, because the C64 has no spell row for them (#667 (A DOS party under Prayer, the strength and charisma spells, Mirror Image or an effect with no C64 spell row is still refused when saved as a C64 save, because only the ordinary caster-level spells convert)).
- **Whether a Pool of Radiance character can ever memorise more than 21 spells is UNKNOWN** (#510 (Can a Pool of Radiance character memorise more than the 21 spells its DOS record allots?)).

### Order

- **The Commodore 64 lists the party from the highest occupied slot down.** DOS and the Amiga list the first character file first. A conversion reverses the order so the front rank stays at the front (#101 (A converted DOS party is listed in the reverse of its DOS order), #106 (A C64 party exported to DOS marches in the reverse of its C64 order), #385 (A C64 party converted to an Amiga disk marches in the reverse of its C64 order)). The Commodore 64 packs the party down to the first slot with ORDER and leaves a gap with DROP, and no byte in a record says where a character stands in the party ([`docs/30-savegame-layout.md`](docs/30-savegame-layout.md)).
- **A character's items are drawn in opposite orders too.** The Commodore 64 draws its slot 15 first, DOS and the Amiga draw the first stored item on top. The Character Editor uses each game's own order (#792 (A character's items converted between DOS and the C64 are listed in reverse order, because the two games draw the stored order from opposite ends), #795 (The editor's Items tab lists a character's items in the reverse of the game's order, because it draws the C64 slots from 0 up and the game draws them from 15 down)).

### Names

- **The Commodore 64 draws lower case as punctuation.** A name typed as "Guy de Valois" shows as garbage, so Wish folds names to capitals when it writes a Commodore 64 record. DOS keeps the spelling exactly (#290 (A character named in lower case draws as punctuation on the C64, and only the DOS import folds the name), #638 (Save As refuses a C64 character whose name has lower-case letters, though the DOS save keeps the name exactly)).
- **Amiga Pool of Radiance deletes spaces from a name the first time it saves.** Of nine names with spaces, nine lost them; none of 26 without spaces changed. The game's own creation screen stores a space in a form that survives, which is what Wish writes. The Save As window warns that GUY DE VALOIS will become GUYDEVALOIS (#308 (Does Amiga Pool of Radiance drop the space out of a character's name when it saves?), [`docs/206-three-amiga-questions.md`](docs/206-three-amiga-questions.md)). Whether Amiga Curse, Silver Blades and Pools of Darkness do the same is UNKNOWN.
- **A few more punctuation characters are removed or drawn as other glyphs on some ports.** On the Amiga, the full stop, asterisk, comma, question mark, slash, colon and semicolon are deleted from Pool of Radiance names on save. On the Commodore 64 a comma in a Curse or Silver Blades name breaks the parked character's file name. Silver Blades and Pools of Darkness are partly assumed.
- **A name over the destination's width is cut, and Wish says so.** The Save As window offers the player a names window that asks for shorter names (#625 (A DOS character's name saved in place, past the destination's fifteen characters, is silently truncated with no report at all), #619 (A name cut to the destination's width and a value clamped into a narrower field reach report.warnings only, so no caller can see the loss)).

### The saved game around the party

- **The clock.** The Commodore 64 and DOS Pool of Radiance keep six clock digits; Pools of Darkness has a seventh, the year, and its overflow ages the party (PROBABLE for the digits above the minutes). Saving costs no time on DOS. A step of overland travel costs about twelve hours on all three ports.
- **A party that has not set out.** A party saved before BEGIN ADVENTURING is told apart by an empty script buffer and never by its area number, because area 0 is New Phlan in Pool of Radiance and is not a place in Curse or Silver Blades. Wish converts such a Pool of Radiance party to New Phlan. A Curse or Silver Blades party that has not set out is written as a party-menu save, so the opening scene and its experience award still play on the other platform ([`docs/185-a-party-that-has-not-set-out.md`](docs/185-a-party-that-has-not-set-out.md), #653 (Converting an Amiga Curse or Silver Blades party that has not yet set out to the C64 or DOS lands it already adventuring, so the opening experience award never happens)).
- **Commodore 64 saves hold two things the others have no place for.** A table saying which overlay files are in memory, which Wish writes for the player, and a one-frame picture buffer that the game never reads back, so zeroing it loses nothing ([`docs/140-loaded-files-cache.md`](docs/140-loaded-files-cache.md), [`docs/181-curse-picture-buffer.md`](docs/181-curse-picture-buffer.md)).
- **The Commodore 64 caches a character's armour class, THAC0, hit points and movement in a roster block** and updates them only when equipment changes. DOS and the Amiga recompute them when a save is loaded ([`docs/30-savegame-layout.md`](docs/30-savegame-layout.md)).
- **The Commodore 64 name table in a Curse or Silver Blades save is a copy of the disk's directory and is never read back,** so a stale entry costs nothing ([`docs/216-the-c64-name-table.md`](docs/216-the-c64-name-table.md)).

## What a conversion costs a player

Wish moves a party between platforms of the same game with Save As, and it moves characters only that way: moving a character between games is the games' own Add Character menus' job. A conversion is refused rather than allowed to lose something silently, and the window reports each remaining loss in words. The differences below are the reasons. Each is CONFIRMED unless marked.

| What the player has | What happens on the other platform |
|---|---|
| A cleric or paladin who turns undead | The Commodore 64 stores the caster's turning strength and shows the TURN command only when it is non-zero. DOS and the Amiga store only the undead target's row. Wish computes the Commodore 64 strength on the way in and writes zero into the DOS byte on the way out ([`docs/178-turning-undead.md`](docs/178-turning-undead.md), #288 (A converted cleric or paladin arrives on the C64 unable to turn undead, because DOS keeps no turning byte and nothing computes one), #297 (A cleric converted from the C64 to DOS is given an undead's turning row, because the DOS writer puts turn_power in the undead's byte)). |
| A paladin's lay on hands and cure disease | See "Paladins" below. |
| A character wearing Gauntlets of Ogre Power | DOS stores the old strength in the effect, and the Commodore 64 stores it in an effect row. Wish mirrors both (#694 (A DOS Pool of Radiance character wearing Gauntlets of Ogre Power loses his real strength for good once converted to C64 and un-readied)). |
| A Dwarf, gnome or halfling | The constitution bonus to saving throws is applied at roll time on DOS and baked into the five stored saves on the Commodore 64. Wish recomputes the stored saves for the Commodore 64 (#311 (A DOS dwarf, gnome or halfling converted to the C64 loses his constitution bonus to saving throws, because the C64 keeps it inside the five stored bytes), #344 (A converted Silver Blades dwarf, gnome or halfling keeps DOS's saving throws, because that title's racial bonus has never been watched in the game)). |
| A thief | Skill percentages are recomputed for the destination (see "Thief skills"). |
| A magic-user or thief of low level | THAC0 differs by a point between ports and is recomputed (see "THAC0"). |
| A strength over 18 | The Commodore 64 uses a separate stored index and strength bonus flag, which Wish writes so the sheet is right before the first fight (#277 (A DOS character converted to the C64 loses the strength bonus to hit and damage, because 0x0E3 is written zero), #782 (A Curse or Silver Blades character stronger than 18 converts to the C64 with the stored strength index too low until his first fight), #787 (A C64 conversion shows the wrong THAC0 on the sheet for strength 19 and over, or 3 to 7, until the first fight, because the to-hit table it adds has no rows there)). |
| A dual-classed human | The Commodore 64 and DOS record the old class differently (see "Classes, levelling and the trainer"). |
| A companion | The Commodore 64 and DOS use the same bit for "the engine drives this character" with different byte layouts, and a companion's treasure share is computed by different rules (see "Companions and treasure"). |
| A chosen combat figure | Redrawn by a hand-judged table, not recomputed (see "Combat figures"). |
| A character's sheet portrait | Pool of Radiance only (see "Portraits"). |
| Experience above 16,777,215 | Clamped on the way to the Commodore 64, which has three bytes ([`docs/117-save-conversion.md`](docs/117-save-conversion.md), #597 (Can a DOS Curse or Silver Blades character hold more experience than the C64's three bytes?)). |
| A character's remaining effect duration and a paladin's cure-disease uses | Several states cannot be held exactly on the Commodore 64 and are written with an adjustment row or reported ([`docs/234-a-paladins-cure-disease-across-dos-and-the-c64.md`](docs/234-a-paladins-cure-disease-across-dos-and-the-c64.md), #600 (The neutral record has no field for an effect's remaining duration or a paladin's cure-disease uses, so a converted character loses both), #649 (Converting a dual-classed DOS Curse of the Azure Bonds character to C64 loses his leftover paladin cure-disease use)). |
| A Pools of Darkness character moved between DOS and the Amiga | The two ports number the +3 long sword's item type differently (105 on the Amiga, 73 on DOS, where 73 is a scroll case on the Amiga), and Wish swaps them. A scroll case is a chained bundle on the Amiga and separate items on DOS (#678 (A Pools of Darkness character converted from the Amiga to DOS loses his readied +3 long sword's attack, because the two ports number its item type differently)). |
| A Pools of Darkness vault | Not converted yet (#651 (Convert a Pools of Darkness party's item vault between DOS and the Amiga along with its saved game)). |
| A DOS scroll saved while its spell was being scribed | Shown as an item-only effect in the editor and written to the Commodore 64 with a byte that port never writes (#745 (A DOS scroll saved while its spell is being scribed shows as an item-only effect in the editor and converts to the C64 with a byte the C64 never writes)). |
| A Training Hall hireling in Pool of Radiance | Its treasure share has a bit set that other ports do not store, and Save As refuses it today (#743 (Save As refuses a Pool of Radiance party with a Training Hall hireling between the C64 and DOS or the Amiga, because the hireling's treasure share has bit 2 set), #744 (A DOS or Amiga Pool of Radiance save with a Training Hall hireling will not open in the Character Editor)). |

The Save As window lists the files it needs from the player: the title's own Commodore 64 disks when the destination is a Commodore 64 save (for combat figure tables), the DOS game folder when the destination is DOS, and the Amiga game disks when the destination is an Amiga save. Pools of Darkness DOS needs none. The routes are in [`docs/227-editor-open-save-as.md`](docs/227-editor-open-save-as.md) and [`docs/235-destination-game-acceptance-runs.md`](docs/235-destination-game-acceptance-runs.md).

## Rules and numbers

### THAC0

- **Pool of Radiance, DOS and Amiga against the Commodore 64.** A magic-user at levels 1 to 5 and a thief at levels 1 to 4 hit one point more easily on DOS and the Amiga: THAC0 20 where the Commodore 64 gives 21. Clerics and fighters are identical. The Amiga engine rewrites the Commodore 64's stored value to the DOS one when it loads the character. CONFIRMED on 190 of 190 DOS records and on three Amiga characters. Wish writes the destination's value ([`docs/135-levelling.md`](docs/135-levelling.md), [`docs/182-amiga-por-in-the-running-game.md`](docs/182-amiga-por-in-the-running-game.md), #318 (DOS gives a low-level magic-user or thief THAC0 20 where the C64 gives 21, and our table holds only the C64's), #366 (A converted magic-user or thief arrives with the other port's THAC0, because the two ports ship different tables and the conversion copies the byte)).
- **Curse and Silver Blades have different tables again.** DOS gives a thief of level 1 to 4 THAC0 20 against the Commodore 64's 21. A fighter, paladin or ranger of level 2 stores 20 on DOS and 19 on the Commodore 64 (confirmed in the bytes, PROBABLE as something a player sees, since no level-2 DOS fighter exists on the machines that checked). A magic-user at the top bands stores 17 on DOS against 16.
- **On DOS the lowest THAC0 a character can have is 20.** Entry 0 of each class's row is a real THAC0, and the rebuild that runs when the character loads reads it for every class the character lacks. A pure magic-user of level 1 to 5 therefore comes out at 20 on DOS and at 21 on the Commodore 64, which is a defect of DOS Curse and DOS Silver Blades listed in [`goldbox-bugs.md`](goldbox-bugs.md) ([`docs/210-the-later-titles-dos-thac0.md`](docs/210-the-later-titles-dos-thac0.md), [`docs/224-the-dos-thac0-floor.md`](docs/224-the-dos-thac0-floor.md), #608 (Curse's DOS engine writes THAC0 20 for a magic-user at levels 1-5 where our table holds 21, so a converted magic-user arrives one point worse to hit)).
- **Amiga Curse recomputes THAC0 on load as well,** and a converted Curse character showed a different stored value afterwards (#402 (Amiga Curse recomputes thac0_current and a roster_tail byte on load, and no declared list says so)). Whether Amiga Silver Blades does is UNKNOWN. The Pools of Darkness table has not been read for this.
- **The Commodore 64 rebuilds THAC0 at the start of every fight,** from the base value, strength and, in Pool of Radiance, the readied weapon. Until the first fight the sheet shows the stored byte. DOS derives the number when it draws the sheet ([`docs/205-the-c64-thac0-rebuild.md`](docs/205-the-c64-thac0-rebuild.md)).
- **The Commodore 64 treats strength above 18 as a separate index.** The index is the score below 18, runs 19 to 23 for 18/xx, and above 18 is strength plus 5, capped at 30. So strength 21 gives +4 to hit and +9 damage there. The three titles share the routine, and Silver Blades' to-hit table has not been read.

### Backstab

No port stores the backstab multiplier, so Wish derives it for the Character Editor (#607 (Show a thief's backstab bonus in the Character Editor), [`docs/225-the-dos-backstab-multiplier.md`](docs/225-the-dos-backstab-multiplier.md)).

| Port and game | Multiplier |
|---|---|
| Pool of Radiance, DOS and Amiga | Thief level divided by 4, plus 2, with steps at levels 4, 8 and 12 |
| Curse and Silver Blades, DOS and Amiga | The same formula using one less level, with steps at 5, 9 and 13, counting a regained thief class. Confirmed for DOS; the Amiga instructions are read but its regain helper is not |
| Pools of Darkness, DOS and Amiga | The larger of the current and former level, with the multiplier capped at 5 |
| Every Commodore 64 title | Thief level less 1, divided by 4, plus 2. Silver Blades and Death Knights cap the level at 14 first |

- **The to-hit penalty on a backstab is 2 on the Commodore 64 and on Amiga Pool of Radiance and 4 in the later DOS and Amiga titles.** Whether DOS Pool of Radiance uses 2 or 4 is UNKNOWN, because two project documents grade it differently.
- **No port's backstab damage has been measured in play.**
- **Thief abilities in DOS Pool of Radiance depend on the thief level, not on the class mask.** A record with a thief level and a fighter-only mask plays as a thief, and there is no Find Traps command ([`docs/221-thief-abilities-in-dos-pool-of-radiance.md`](docs/221-thief-abilities-in-dos-pool-of-radiance.md)).

### Thief skills

The percentages are never drawn on any sheet, so a player sees them only as locks that open or fail and as sneaking that works or does not ([`docs/125-bug-notes.md`](docs/125-bug-notes.md), notes N21 to N23).

- **Pool of Radiance, Commodore 64.** The racial table is one byte short, so the gnome, half-elf, halfling and half-orc rows are displaced. A Commodore 64 halfling or half-elf thief moves silently 5 points better than on DOS, and the Commodore 64 ignores dexterity for thief skills while DOS adds a dexterity block of 11 rows.
- **Pool of Radiance, DOS.** The dexterity block has two errors against the rules. Dexterity 10 gives -19 to pick pockets where the rules give -10, and dexterity 16 gives -5 to open locks where the rules give +5. A DOS thief at dexterity 16 opens locks ten points worse than a Commodore 64 thief.
- **Curse.** Both ports have the same tables, but DOS Curse adds a leftover byte from its own stack (observed as +7) to all eight skills (#437 (A Curse thief's stored skills sit seven points above the rows the engine's own tables give), #440 (A Curse thief converted between DOS and the C64 arrives seven points off, because DOS stores a stack leftover in all eight skill columns)). The Commodore 64 does not. A Curse thief therefore changes by seven points in each skill when converted, and Wish removes or adds the amount.
- **Silver Blades, Commodore 64.** Every thief gets the next race's skill row, and a halfling gets dexterity-table penalties, ending with 0% move silently at level 1 and dexterity 17 ([`goldbox-bugs.md`](goldbox-bugs.md) bug 13). Whether DOS Silver Blades indexes the same way is UNKNOWN.
- **Amiga Pool of Radiance appears to follow the DOS rule** (PROBABLE, two records).
- **Wish recomputes skills for the destination in Pool of Radiance and Curse** (#431 (A converted halfling thief keeps the other port's skill percentages, because the two ports ship different halfling rows)). Silver Blades is not on that rule.

### Racial effects and saving throws

- **Race numbering is different in every game.** Human is race 7 in Pool of Radiance, Curse and Gateway, and 6 in Silver Blades. Half-orc is missing from Curse's and Silver Blades' creation menus. Wish converts by race name. The Commodore 64 Curse label table prints HUMAN for both 6 and 7, where DOS Curse names 6 half-orc ([`docs/125-bug-notes.md`](docs/125-bug-notes.md) N4, #237 (The DOS race table is one table for four titles, and it is wrong for two of them)).
- **The racial effect records differ by game and port.** For example, a DOS dwarf holds four effects in Pool of Radiance, three in Curse and three in a different order in Silver Blades, and the Commodore 64 Pool of Radiance seeds only an elf's and a half-elf's. A DOS halfling holds two effects in Pool of Radiance and one in Curse and Silver Blades, while Commodore 64 Silver Blades gives a halfling a different effect (92) from DOS (97). The Commodore 64 recomputes class innate effects every time; DOS neither reseeds nor strips them ([`docs/200-innate-effect-seeding.md`](docs/200-innate-effect-seeding.md), #293 (A converted Silver Blades dwarf, elf or gnome gets another race's innate combat effect, because RACE_COMBAT_EFFECTS is keyed by Pool of Radiance's race numbers), #490 (A converted dwarf, gnome or halfling gets the wrong racial effect records in DOS, because the writer's table is Pool of Radiance's or the C64's rather than that title's own)).
- **The constitution bonus to saving throws is applied differently.** DOS Pool of Radiance and Curse store the unadjusted class row and apply the bonus (constitution times 2, integer-divided by 7, nothing below 4) at roll time through an effect. The Commodore 64 bakes it into the stored saves: all five columns in Pool of Radiance, three in Curse, and the dwarf only in Silver Blades. DOS Silver Blades has the effect but no saving throw asks for it, so a DOS-born Silver Blades halfling or dwarf gains nothing from it (CONFIRMED from the code, not watched) ([`docs/189-effect-97-from-the-code.md`](docs/189-effect-97-from-the-code.md), [`docs/230-who-reads-a-dos-effect-node.md`](docs/230-who-reads-a-dos-effect-node.md)).
- **Silver Blades' halfling immunity differs.** On the Commodore 64 the halfling effect cancels Ray of Enfeeblement, Feeblemind and Fear. On DOS it cancels Fear only (not watched in play).
- **Infravision.** Commodore 64 Pool of Radiance and Curse seed 60 feet for dwarf, elf, gnome, half-elf and half-orc, 30 feet for a halfling and none for a human. All six Commodore 64 Silver Blades records hold zero, including the dwarf, and the correct value is UNKNOWN (#287 (A converted Silver Blades human sees in the dark, because the infravision table is keyed by Pool of Radiance's race numbers), #392 (A converted halfling gets sixty feet of infravision, where the C64's own generator gives him thirty)).
- **Saving throws that DOS Curse ignores.** DOS Curse's saving throw routine does not look at a regained class, an error listed in [`goldbox-bugs.md`](goldbox-bugs.md) as bug 19.

### Spells and spell slots

- **Spells 1 to 56 are the same spells in every game and port.** After 56 the ports diverge: DOS carries item-invoked effects up to 67, and the Commodore 64 uses the same ids for combat message fragments (PROBABLE, [`docs/128-guide-and-scripting.md`](docs/128-guide-and-scripting.md)).
- **Who stores spell slots differs.** DOS rebuilds them when a character loads. The Amiga does not. The Commodore 64 Curse and Silver Blades never store capacity and rebuild it each time the sheet is drawn. Commodore 64 Pool of Radiance stores it. Wish needs a slot table for the title to write a caster's slots, and a Silver Blades caster written without one has none (#603 (A converted Silver Blades caster arrives with no spell slots at all, because our table has no rows for that title), #508 (A converted magic-user loses memorised spells on the way to DOS, because our table says a title has fewer slots than the engine gives it), #548 (What do Curse's spell-slot arrays hold for a paladin, a ranger or a druid, which nothing on this machine can reach?), [`docs/164-ssb-spell-slot-block.md`](docs/164-ssb-spell-slot-block.md)).
- **Wisdom bonus spells for clerics.** Commodore 64 Pool of Radiance grants a first-level spell at wisdom 12 and two at 13, one more than DOS (one at 13, two from 14) and one more than the rule book. Curse and Silver Blades give one per wisdom point from 13 up to 19. Pools of Darkness uses Curse's table from 13 to 18 and gives 19 what 18 gives. The Amiga Pool of Radiance table is unread, and Wish keeps the Commodore 64 numbers for it ([`docs/125-bug-notes.md`](docs/125-bug-notes.md) N13, #557 (The editor gives a DOS Pool of Radiance cleric with wisdom 12 or 13 a spell slot the game does not), #559 (A converted DOS Pool of Radiance cleric with wisdom 12 or 13 arrives on the C64 one first-level spell short)).
- **Curse's ranger and paladin at level 11 differ between ports.** On the Commodore 64 a level-11 ranger can memorise one first-level magic-user spell, where DOS offers two, and a level-11 paladin has a second-level cleric slot he can never fill, where DOS grants those spells every load. Wish keeps DOS's numbers when converting ([`goldbox-bugs.md`](goldbox-bugs.md) bugs 14 and 15, #551 (The C64 and DOS builds of Curse disagree on a paladin 11's granted spells and a ranger 11's spell slots)).
- **The trainer on the Commodore 64 picks new spells differently in each title.** A magic-user chooses from a menu in all three. Silver Blades reads a table that disagrees with the other two at levels 11, 13 and 15, asks for intelligence 12 for sixth-level and 14 for seventh-level spells, and never offers one druid spell. A Silver Blades cleric needs wisdom 17 for the level-11 row ([`docs/135-levelling.md`](docs/135-levelling.md), #89 (Silver Blades' trainer grants spells from a table, and goldbox/levelup.py offers them from a menu)).
- **Pools of Darkness stores spell slots as running totals** where Curse and Silver Blades store differences. Its cleric spell levels 8 and 9 stay zero ([`docs/228-pools-of-darkness-spells-and-creation.md`](docs/228-pools-of-darkness-spells-and-creation.md)). The Amiga stores its spellbook as a 16-byte mask where DOS spends one byte per spell (#461 (One Pools of Darkness spellbook byte holds 8 where every other spellbook byte in 476 records holds 1)).
- **Restoration.** The Commodore 64 Pool of Radiance spellbook has no bit for it, and DOS sets that byte for clerics. Wish treats it as derived and reports no loss (#411 (Nobody knows whether a converted cleric loses Restoration, because the spellbook field is one bit short of the game's own spell list)).
- **The Silver Blades scroll bundle.** DOS Silver Blades can join scrolls into one item. The Commodore 64 gives each its own slot ([`docs/215-the-dos-experience-award-and-the-scroll-bundle.md`](docs/215-the-dos-experience-award-and-the-scroll-bundle.md)).

### Classes, levelling and the trainer

| | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| Classes available | No paladin, ranger or dual-classing | Paladin and ranger added, and a human may change class once | As Curse |
| Level ceilings (magic-user, cleric, thief, fighter, then paladin and ranger) | 6, 6, 9, 8 | 11, 10, 12, 12, 11, 11 | Its own table |
| Training cost on the Commodore 64 | 1000 gold | 1000 gold | The trainer takes no money (UNKNOWN whether a script charges first) |
| Classes raised per press | One | Every ready class | Every ready class |

- **Training is a walk to a school on DOS Pool of Radiance** and a trainer on the Commodore 64 ([`docs/194-the-dos-training-ladder.md`](docs/194-the-dos-training-ladder.md)).
- **On the Commodore 64, training in the wrong order throws away a level a multi-class character has earned** in Pool of Radiance ([`goldbox-bugs.md`](goldbox-bugs.md) bug 8). Curse and Silver Blades raise all ready classes on one press. Curse's refusal reads UNABLE TO ADVANCE where Pool of Radiance reads LOW EXPERIENCE OR WRONG CLASS. Curse rolls the hit die twice and keeps the better, and a dual-classed character gains no hit points until the new class passes the old level.
- **After training, experience is left one below a threshold,** CONFIRMED on 42 of 42 DOS trainings. Whether DOS and the Commodore 64 take the same experience cost from a multi-class character is UNKNOWN (one Commodore 64 sample disagrees with the DOS rule).
- **Dual-classing.** All four of Commodore 64 and DOS Curse and Silver Blades refuse a second change of class: the Commodore 64 prints UNABLE TO CHANGE CLASS and DOS stops drawing the menu line. The rules are human only, old class prime requisites 15 or more, new class 17 or more, and level 2 or more. The old class never trains again. When the new class passes the old level, the Commodore 64 writes the old level back into its slot and sets the old class's bit in the class mask, so a regained paladin draws as "FIGHTER/PALADIN"; DOS never rewrites the slot and derives everything from both arrays on each use ([`docs/176-changing-class-twice.md`](docs/176-changing-class-twice.md), [`docs/209-the-regained-dual-class-on-dos.md`](docs/209-the-regained-dual-class-on-dos.md), [`docs/214-the-regained-dual-class-on-the-c64.md`](docs/214-the-regained-dual-class-on-the-c64.md)).
- **A regained Curse paladin or ranger carries a class mask Curse's own table cannot name.** Wish shows the class he actually has (#409 (A regained dual-classed paladin or ranger has a class mask Curse's own table cannot name, so Wish shows him a class he is not)). DOS stores only the new class code.
- **The Commodore 64 Curse trainer writes the wrong value into the class code byte,** so a trained character reads class code 0 (cleric) there and a dual-classed one holds his old level. The game never reads the byte, so a player sees nothing, but Wish computes the code from the class mask when it converts ([`docs/187-the-class-code-byte.md`](docs/187-the-class-code-byte.md)).
- **A DOS paladin and ranger share one class-mask bit.** The Commodore 64 ranger has its own.
- **Curse's DOS "change class" at level 0 divides by zero and the game likely stops with a runtime error** (PROBABLE).

### Paladins

- **Lay on hands exists in Curse and Silver Blades only.** On the Commodore 64 it is a record byte plus a one-day effect row. On DOS and the Amiga it is only an effect that lasts 1440 minutes. Amiga Silver Blades and Pools of Darkness use the effect number Curse uses, though they have no handler for it ([`docs/231-where-lay-on-hands-lives.md`](docs/231-where-lay-on-hands-lives.md), #628 (The neutral vocabulary has no field for a paladin's lay-on-hands uses, so a converted paladin loses them)).
- **Cure disease** is a record byte plus a row on the Commodore 64 and a counter plus an effect on DOS and the Amiga lasting 10080 minutes. The Commodore 64 ends it at the seventh midnight. The uses a day are 1, 2 and 3 on both ports up to level 15, and at level 16 DOS gives 4 and the Commodore 64 3. One state the Commodore 64 cannot hold exactly (one use left, no effect) is written with an adjustment row. Silver Blades converts exactly ([`docs/234-a-paladins-cure-disease-across-dos-and-the-c64.md`](docs/234-a-paladins-cure-disease-across-dos-and-the-c64.md), #652 (Converting a C64 Curse or Silver Blades former paladin to DOS before he regains the class takes away his cure-disease uses for good), #658 (Converting a DOS Curse or Silver Blades party with a paladin who has regained the class to the C64 writes his cure-disease uses as zero with no loss line)).
- **Protection from Evil.** The Commodore 64 Curse seeds a paladin's as trait 45, and DOS and the Amiga as effect 8. Wish converts 45 to 8 for a paladin and not for a cleric (whose 45 is a cast spell) (#481 (A C64 Curse paladin converted to DOS loses Protection from Evil for good, because the C64 seeds it as trait 45 and DOS writes it as effect 8), #484 (Does C64 Silver Blades seed a paladin's Protection from Evil as trait 45, the way Curse does, so that direction loses it converting to DOS too?), #624 (A C64 paladin saved as an Amiga Curse or Silver Blades save gets Protection from Evil, 10' Radius instead of Protection from Evil, with no report)). Whether Commodore 64 Silver Blades seeds it the same way is UNKNOWN.

### Experience

- **Commodore 64 experience is three bytes; DOS and the Amiga use four.** A DOS value above 16,777,215 is clamped on its way to the Commodore 64 ([`docs/117-save-conversion.md`](docs/117-save-conversion.md), #597 (Can a DOS Curse or Silver Blades character hold more experience than the C64's three bytes?)).
- **The experience for killing a monster** is a base plus a number per hit point on the Commodore 64 and DOS Pool of Radiance, and only a base in Pools of Darkness and Treasures ([`docs/215-the-dos-experience-award-and-the-scroll-bundle.md`](docs/215-the-dos-experience-award-and-the-scroll-bundle.md)).

### Effects, traits and durations

- **The Commodore 64 keeps running effects in four parallel 64-slot tables for the whole party, plus ten trait slots a character** that never expire and that Dispel Magic can never reach. DOS keeps a list of nodes per character with a minute count and rolls Dispel per node. The Amiga's node is ten bytes with a 16-bit big-endian minute count and one unused padding byte ([`docs/133-active-effects.md`](docs/133-active-effects.md), [`docs/202-the-amiga-effect-node-pad.md`](docs/202-the-amiga-effect-node-pad.md), [`docs/226-the-c64-running-effect-crosswalk.md`](docs/226-the-c64-running-effect-crosswalk.md)).
- **A duration of zero means permanent on DOS and never ages on the Commodore 64.** Commodore 64 durations age by wrapped digits of the clock, not by elapsed minutes (#500 (What unit is an active effect's duration in, and what do bits 6-7 of the duration byte select?)).
- **Two DOS Bless nodes only change Dispel's odds,** while the Commodore 64 holds one row per spell and owner.
- **When a party member leaves, the Commodore 64 keeps his effect rows and DOS and the Amiga free them.**
- **Effect numbers differ by game.** Pool of Radiance has 139 on the Commodore 64, Curse 146, Silver Blades 113, and Pools of Darkness 126 on DOS. The spell half is mostly shared and the monster-special half is not. Curse's own handlers contradict six inherited names, and some "breath weapon" ids do nothing (#497 (The trait picker offers a Secret of the Silver Blades character six names, and nobody has ruled on whether it should offer Pool of Radiance's 129), #561 (A Curse of the Azure Bonds character's traits are named from Pool of Radiance's table, which disagrees with Curse's own data about eight codes), #609 (Six of Curse of the Azure Bonds' inherited effect names disagree with its own combat handlers), [`docs/222-naming-curses-effect-codes-from-their-handlers.md`](docs/222-naming-curses-effect-codes-from-their-handlers.md)).
- **Ability scores.** Pool of Radiance stores one value per ability on every port. The later Commodore 64 games store a permanent array and an in-force array, and the sheet draws the in-force one (Silver Blades marks a differing ability with a plus). The later DOS games store a pair of bytes per ability, with the percentile of exceptional strength stored in the opposite order. Wish keeps the two halves apart so a temporary boost or drain stays temporary after a conversion ([`docs/201-the-two-ability-arrays.md`](docs/201-the-two-ability-arrays.md), [`docs/204-the-dos-ability-pair.md`](docs/204-the-dos-ability-pair.md), #404 (A converted Curse or Silver Blades character keeps a temporary strength boost or drain for good, because the two halves of the DOS ability pair are crossed)).
- **Ring of Fire Resistance.** The Commodore 64 disks hold five ring records. Four grant the resistance and one is flattened and grants nothing, which a player probably cannot reach (PROBABLE). Wish uses a working copy ([`docs/183-the-two-rings-of-fire-resistance.md`](docs/183-the-two-rings-of-fire-resistance.md), #285 (The C64's Ring of Fire Resistance grants nothing, and Wish should repair it on conversion and on an editor save)).
- **Mirror Image on DOS Curse** loses an image only once per sixteen absorbed attacks, so it lasts much longer than the image count suggests. DOS Silver Blades and the Commodore 64 count correctly. The Amiga is unread ([`goldbox-bugs.md`](goldbox-bugs.md) bug 17).

### Items, weight and movement

- **Item records are 63 bytes on DOS in three titles and 67 in Silver Blades.** The Amiga records are 65 bytes in Pool of Radiance, 66 in Curse, 70 in Silver Blades and 20 in Pools of Darkness.
- **A zero item type means different things.** On the Commodore 64 it is an empty slot, which the game itself leaves behind when it merges a stack. On DOS Pool of Radiance it is a real item without a name at seven treasure squares, and the Character Editor still hides it (#672 (A C64 item slot the game emptied by zeroing its type byte, as JOIN does to the stack it merges away, reads in Wish as a live item), #798 (The Character Editor hides a DOS Pool item whose type byte is 0, and an added item may overwrite it)).
- **Wands, potions and scrolls number their effects per game.** The editor names a Curse or Silver Blades wand or potion with Pool of Radiance's table (#765 (The editor names the wrong effect for a Curse or Silver Blades wand or potion, because it reads the effect byte with Pool of Radiance's numbering)). Silver Blades scrolls do not use the scroll location code (#764 (The editor shows a Silver Blades scroll's spells as Charges, Effect and Power, because its scrolls do not use the scroll location code)).
- **A shop purchase leaves stored encumbrance one purchase behind on DOS Pool of Radiance and Curse,** which no player sees because the sheet recomputes ([`docs/213-the-dos-shopping-trip.md`](docs/213-the-dos-shopping-trip.md), [`docs/125-bug-notes.md`](docs/125-bug-notes.md) N19).
- **Weight bands and movement differ at five edges.** The exact boundaries (512, 768 and 1024 fall in the heavier band on the Commodore 64 and the lighter on DOS), the allowance for strength 3 to 7 (DOS subtracts, the Commodore 64 does not), for strength 19 (4000 on DOS, 4500 on the Commodore 64), stack weight (DOS uses 16 bits, the Commodore 64 the low byte) and light magic armour (DOS adds 3 when the base is 9 or less). On 222 DOS records the rules never disagreed ([`docs/173-carrying-limits.md`](docs/173-carrying-limits.md), #740 (A Pool of Radiance character converted to the C64 can carry a movement value the C64 game would not compute for him)).
- **Pool of Radiance applies a bag-of-holding discount on DOS.** Curse ships the code and can never reach it, and Silver Blades has none ([`docs/125-bug-notes.md`](docs/125-bug-notes.md) N24).
- **The DOS dagger cannot be thrown and the Commodore 64 dagger can** (rate of fire 0 and range 1 against 2 and 4). The dart is thrown-only on DOS. Confirmed in the item bytes, never watched in play ([`docs/125-bug-notes.md`](docs/125-bug-notes.md) R51).

### Companions and treasure

- **A companion is a character the engine drives.** The Commodore 64 uses one bit of its control byte for this, and DOS and the Amiga use the same bit in a different byte layout, in a five-byte run (Pool of Radiance and Curse) or four-byte run (Silver Blades). The Commodore 64's morale is capped at 100 in the five later titles and not in Pool of Radiance, and only Pool of Radiance has an "ability altered" flag there ([`docs/232-the-c64-control-byte-per-title.md`](docs/232-the-c64-control-byte-per-title.md)).
- **A character the game has taken over** (Charm, Animate Dead) is encoded differently on DOS and the Commodore 64, and a conversion can mistake him for a companion, with no report (#720 (A Pool of Radiance player character the engine has taken over converts between DOS and the C64 as a companion, because both readers take the control byte's bit 7 for a companion)).
- **Treasure share.** On DOS, Amiga Pool of Radiance and DOS Curse and Silver Blades a companion takes a fraction of each pile, with the share in the low three bits. On the Commodore 64 the game rolls once per defeated monster with a chance that depends on party size, and the share is the low two bits. A share byte of 255 is 7 parts on DOS and 3 on the Commodore 64. Commodore 64 Silver Blades gives a share of 0 if a demo flag is zero (PROBABLE). The Amiga Curse, Silver Blades and Pools of Darkness rules are not read (`goldbox/treasuresplit.py`, #529 (A converted character's treasure share resets to the engine's default, because the neutral record has no field for it), #639 (A C64 Curse or Silver Blades character converted to DOS or the Amiga loses his treasure share)).
- **The Commodore 64 shows TURN on the combat bar from a stored byte,** so a fighter given a turning value there would be offered it. DOS works the command out from the cleric level when it is pressed.

### Resting and encounters

- **Camping in the Slums.** On the Commodore 64 Pool of Radiance a rest in the Slums is never interrupted unless the player has murdered the fortune teller. Thirty-seven two-hour rests rolled no check. The DOS script differs in ten bytes, including the two that make the check, and a DOS rest in the Slums is checked every two hours at 24% with no murder. The Amiga script has not been checked ([`docs/207-c64-rest-interruption.md`](docs/207-c64-rest-interruption.md), [`goldbox-bugs.md`](goldbox-bugs.md) bug 12).
- **In New Phlan every street rest is interrupted** on both ports; the Commodore 64 City Watch asks GO or STAY, and STAY starts a fight (#777 (The C64 Pool rest step does not notice the New Phlan city watch interrupting a street rest)).
- **A scripted event can turn a Silver Blades rest into a fight on the Commodore 64** (observed at eight hours in the Black Circle's town, #780 (The C64 Curse and Silver Blades rest step does not handle a rest a scripted event turns into a fight)).
- **Random encounter size on the Commodore 64 Pool of Radiance** is computed from the party's THAC0, hit points, armour class and its clerics and magic-users ([`docs/114-party-strength.md`](docs/114-party-strength.md)). DOS is not documented.
- **Fleeing.** All three Commodore 64 games print THE PARTY RUNS AWAY on the same code path, and Silver Blades' encounter menu says YOU FLEE where the others say THE PARTY FLEES. Characters left behind are removed from the party in memory and not on the save disk. DOS Curse has the same three clauses with different messages. Only Pool of Radiance's has been seen on a screen (#445 (The game's third fight outcome, THE PARTY RUNS AWAY, has never been seen on a screen), #648 (See THE PARTY RUNS AWAY on a Curse or Silver Blades screen, and confirm the mercy heal on the losing side of a fight)).
- **Losing a fight on the Commodore 64 stops at THE PARTY HAS LOST with no prompt.** Donald ruled this intentional; whether DOS does the same is unmeasured.

## Maps and travel

### The map files

- **A map is the same on all three ports.** It is a 16 by 16 grid with four layers: wall art, wall art for the other two sides, square attributes (roofed, script) and barriers ([`docs/88-map-files.md`](docs/88-map-files.md)). Only the container differs: a file per area on the Commodore 64, one file of blocks on DOS, and a packed index on the Amiga. Silver Blades and Curse keep theirs on the Amiga's second disk.
- **Maps that differ between ports, found by comparing them.**

| Game | Maps | Result |
|---|---|---|
| Pool of Radiance | 29 | Two differ on the Commodore 64: one by 2 bytes (a script number and one wall edge) and one by 6 (a wilderness cave whose five square attributes change, roofing three squares). The Amiga and DOS copies are identical |
| Curse | 16 | Three differ on the Commodore 64 by 2 bytes each. In one a south edge is solid on the Commodore 64 and passable elsewhere, which makes a one-way door; in another a one-way passage runs the other way; in the third a wall is drawn from a different piece. Two squares have no script on the Commodore 64 where the other ports have one, so the event is still in the script but the Commodore 64 cannot reach it. DOS and the Amiga agree |
| Silver Blades | 17 | All identical on the three ports |
| Pools of Darkness | 32 | DOS and Amiga are byte-identical |

Evidence: #443 (Three of Curse's sixteen maps differ between the C64 and the Amiga, and nobody has looked at how), #447 (The map tolerance is wider than the gap between two of Silver Blades' own maps), [`docs/145-dos-decode-kit.md`](docs/145-dos-decode-kit.md). The Commodore 64 ships three Curse scripts that DOS lacks and DOS ships one the Commodore 64 lacks. What they do is unread.

### Overland travel

| Game | What the player sees | Status |
|---|---|---|
| Pool of Radiance | A map of squares drawn with the combat engine, moved eight ways. The world is about 40 by 32 squares, cut into three overlapping windows of 18 by 36 squares, and the three ports show it differently (below) | CONFIRMED on the Commodore 64 and the Amiga, PROBABLE on DOS |
| Curse | A full-screen picture of the Dalelands with a menu: ENTER CITY, JOURNEY ON, CAMP, and later SEARCH AREA. JOURNEY ON lists neighbouring places. The mode bar reads TRAIL, WILDERNESS or BY BOAT, and a leg costs days (trail x2, wilderness x4, boat x1). There is no square, facing or compass, and the seventh leg asks the code wheel | CONFIRMED on the Commodore 64, PROBABLE on DOS from the decompile, UNKNOWN on the Amiga |
| Silver Blades | None found. Leaving New Verdigris asks YOU ARE LEAVING THE TOWN. DO YOU CONTINUE?, then INSERT SIDE B, and arrives in an ordinary map | One route on the Commodore 64 only |
| Pools of Darkness | Probably 16 by 16 maps with the interface in a wilderness mode, not a travel grid | PROBABLE, from code and two Amiga saves |
| Gateway (DOS) | Six wilderness blocks with no walls | Read from the data |

Evidence: [`docs/113-world-map.md`](docs/113-world-map.md), [`docs/137-wilderness-automap.md`](docs/137-wilderness-automap.md), [`docs/217-drawing-the-wilderness.md`](docs/217-drawing-the-wilderness.md), [`docs/141-dos-savegame.md`](docs/141-dos-savegame.md), [`docs/196-the-amiga-saved-game-built.md`](docs/196-the-amiga-saved-game-built.md) and #804 (Check the automapper's outdoor travel in Curse, Silver Blades and Pools of Darkness, and make it work in any title where it does not).

How Pool of Radiance's overland differs between ports:

- **Commodore 64.** The overland is the combat square engine reading three data files. Each square indexes one of 120 three-by-three character tiles. The game shows five tiles by five and the heading is not saved, so a save made outdoors does not remember which way the party faces. Keys are the digits 1 to 8, north clockwise, and the move bar reads "1-8, RETURN OR BUTTON". The status line shows the word OUTDOORS where the facing letter goes.
- **DOS.** There are no square data files. The windows are three ordinary map areas, and the arrow keys move the party directly. The terrain art is probably one of the DOS tile files (PROBABLE). The status line shows the world position as two numbers, a facing letter and the time.
- **Amiga.** The same three windows come from the game's script file. A converted outdoor Commodore 64 party loaded, drew the overland and walked. Movement is absolute with the facing the direction of the last step, and the keys are the top-row digits. Where the Amiga keeps its terrain tiles is UNKNOWN.
- **A save made outdoors works** on the Commodore 64 and the Amiga through ENCAMP > SAVE. A save made in the middle of a wilderness encounter is impossible on the Commodore 64, because the combat bar has no ENCAMP.
- **After loading a save made on the road, the Commodore 64 re-shows hidden places** such as the nomad camp, because load skips the paint ([`goldbox-bugs.md`](goldbox-bugs.md) bug 10, #49 (Does a hidden site stay painted on the travel map after a reload?)). DOS and the Amiga are UNKNOWN.

### The status line and the keys

- **Layout.** The Commodore 64 prints facing, time and square ("E 16:48  5,2"). DOS and the Amiga print square, facing and time ("5,9 W 00:04") and pad the hour to two digits (PROBABLE; read from quoted lines).
- **The Commodore 64 prints no square** in the Slums, in Curse area 3, in the Kobold Caves and in eleven of Silver Blades' 22 areas, and the facing letter is read from a different place there. Whether DOS or the Amiga ever omit it is UNKNOWN (#681 (A driven Curse or Silver Blades session reports the party's facing from the wrong byte wherever the status line draws no square), #742 (The C64 session's walk_one resends a key and reports no move in any area whose status line shows no square)).
- **Movement keys indoors.** Commodore 64: I forward, J and K turn, M steps back one square. Amiga Pool of Radiance: the top-row digits 4, 6 and 8. Amiga Curse and Silver Blades: numeric keypad only, with 8 forward, 4 and 6 turn and 2 about-face. DOS indoor keys are not recorded.
- **Silver Blades' Commodore 64 status line lags one step behind the game's memory.** Pool of Radiance's is the other way round ([`docs/144-decoding-a-new-title.md`](docs/144-decoding-a-new-title.md)).

### The character sheet and menus

- **Commodore 64 Pool of Radiance:** VIEW with ITEMS, SPELLS, TRADE, DROP and EXIT. **Curse** adds CURE and HEAL for a paladin. **Silver Blades** shows a bare EXIT for a character with nothing to list.
- **Amiga Pool of Radiance:** View, Items, Trade, Drop, Rename and Exit, with gold, encumbrance and movement in the right-hand third, where the other ports put a face. A character who owns nothing gets no Items entry ([`docs/182-amiga-por-in-the-running-game.md`](docs/182-amiga-por-in-the-running-game.md)).
- **Commodore 64 Silver Blades has no save picker; it loads the party directly.**
- **Commodore 64 Silver Blades and Curse show the disk-swap prompts** "INSERT SIDE B, AND PRESS ANY KEY" and similar. Pool of Radiance asks for sides 2 and 3 and for the player's save disk.
- **Commissions.** Only Pool of Radiance has the council's commissions. Curse and Silver Blades have no equivalent in their scripts ([`docs/103-quest-log-panel.md`](docs/103-quest-log-panel.md), #40 (Is there a commissions equivalent in Curse or Silver Blades?)).

## Drawing the characters

### Combat figures

The figure standing for a character on the combat map is stored three different ways ([`docs/168-dos-dax-and-combat-icons.md`](docs/168-dos-dax-and-combat-icons.md), [`docs/193-a-dos-figure-on-the-c64.md`](docs/193-a-dos-figure-on-the-c64.md), [`docs/199-amiga-combat-icons.md`](docs/199-amiga-combat-icons.md)).

| | Commodore 64 | DOS | Amiga |
|---|---|---|---|
| Storage | Eighteen screen codes and eighteen colours in a 36-byte entry per slot | A head, a body, a size and six colour pairs | DOS's own numbers (Curse and Silver Blades) with the art redrawn |
| Look | A three-by-three block of characters (24 by 24 pixels as 12 by 24 double-wide); one of eight colours for each of seven parts; face fixed light red, outline black | 24 by 24 pixels in 16 colours; a main and highlight colour for six parts; a plume or hat is always magenta | The same pixels as DOS apart from a plume highlight (about 42 to 50 pixels differ, and how it looks is UNKNOWN) |
| Options | 28 weapons and 14 heads at the small size, 35 and 23 at the large | 14 heads and 32 bodies in two sizes | As DOS |

- **A conversion between the Commodore 64 and the other two is a hand-judged table of 46 rows, not a calculation.** The Commodore 64 figures are redrawings, and the best same-index match is chance level. A DOS figure that Wish recognises on the Commodore 64 names one slot exactly (24 of 24 in the game) ([`tools/icons/iconproposal.yaml`](tools/icons/iconproposal.yaml)).
- **The Commodore 64 cannot keep DOS's highlight colours,** and chooses the figure's size from the race and never writes it back, so figures of mixed sizes exist.
- **Silver Blades redrew two pieces of art** (a head at the large size and a body at the small size) on DOS and the Amiga, and three glyphs on the Commodore 64. Curse's Commodore 64 art equals Pool of Radiance's. A Silver Blades figure round-trips through the Commodore 64 only with per-title table rows (#452 (A Silver Blades combat figure does not survive a round trip through the C64, because the reverse table has no per-title rows), #335 (Two combat-figure rows describe Pool of Radiance's art, and Silver Blades draws those two options differently)).
- **A DOS party member on the enemy side** has a yellow name on the party panel and is counted as an enemy. The Commodore 64 keeps that fact in bits of another byte ([`docs/169-dos-combat-side.md`](docs/169-dos-combat-side.md)).
- **All three ports draw two poses** for each figure, READY and ACTION. On the Commodore 64 the ACTION pose is fetched once per turn and nobody has caught it on the map ([`docs/186-ready-and-action.md`](docs/186-ready-and-action.md)).
- **A joined NPC on the Commodore 64 can have an all-zero figure.** The editor draws a black rectangle, and what the game draws is unmeasured (#533 (A joined NPC has no combat icon, and the editor draws the absence as a black rectangle)).
- **Amiga Pools of Darkness picks a default figure at creation** by size, sex and class, and a chosen figure is kept in a conversion (#612 (A chosen combat icon on an Amiga Pools of Darkness character converts to the engine's default, since the neutral record has no field for it)).

### Portraits

- **Only Pool of Radiance has a face on the sheet.** The creation menu offers 14 heads and 12 bodies in the same order on every port ([`docs/188-the-sheet-portrait-per-title.md`](docs/188-the-sheet-portrait-per-title.md)). The Commodore 64 stores a picture file number and DOS and the Amiga store a menu position, which a conversion maps.
- **The Amiga draws the menu's eighth body differently:** a knight in mail behind a blue shield, where the other ports draw a bare chest under a cloak. A conversion would otherwise change the body (#480 (An Amiga character whose body is the menu's eighth arrives on the C64 or DOS wearing a different body, because the Amiga reader uses the C64 and DOS menu)).
- **Curse and Silver Blades on the Commodore 64 draw no face.** Silver Blades shows a money panel there and Curse leaves the space blank. DOS Curse and Silver Blades are UNKNOWN (every record is zero, which fits "none" without proving it). Pools of Darkness has none on either port (PROBABLE).
- **Amiga Pool of Radiance:** the sheet code calls the portrait routine, so it may draw a face for a character who has one. The characters examined all had zero portrait bytes, so what a real one looks like is UNKNOWN ([`docs/206-three-amiga-questions.md`](docs/206-three-amiga-questions.md)).
- **A converted Commodore 64 character with no portrait** arrives on DOS or the Amiga wearing the menu's first head (#503 (A C64 character with no sheet portrait arrives in DOS or on the Amiga wearing the menu's first head)).

## Protection, start-up and the disks

- **Copy protection is different on every port.** The Commodore 64 Pool of Radiance asks for a code word. The Commodore 64 Curse asks questions from a printed code wheel, and about 1.6% of its challenges (161 of 10,296) have no answer on that wheel, so the game calls a player wrong when he is right. DOS Curse shows a rune-alignment wheel before the main menu and again when you train, and its wheel is correct ([`goldbox-bugs.md`](goldbox-bugs.md) bug 1, #537 (tools/cursewheel.py never recognises a real DOS Curse code-wheel screenshot, so its own command line refuses every prompt)).
- **Commodore 64 Silver Blades never asks** because the check is dead code in the release the project has. The Amiga Silver Blades asks a journal word and a rule-book question when you BEGIN ADVENTURING (#331 (Amiga Silver Blades asks a journal word before it will adventure, so the title cannot be driven past its party menu), #371 (The Silver Blades journal reader misreads a 6 as an 8, so a boot is spent on a question the disk can answer), #449 (The journal reader's rule-book half has never been read off a screen, so 20 of its 50 challenges are untested live)).
- **The Amiga rips differ.** The Amiga Pool of Radiance release the project holds accepts a bare RETURN at the wheel; Amiga Curse asks the wheel and accepted one answer taken from the Commodore 64 tables (#108 (Amiga Curse asks its code wheel, so the title cannot be driven unattended)). These are properties of those releases and the general case is UNKNOWN. Most Commodore 64 disks the project holds are cracked releases, and the Ultimate hardware tests used original, code-wheel protected disks ([`docs/197-duplicating-the-c64u-hang.md`](docs/197-duplicating-the-c64u-hang.md)).
- **The DOS builds have a command-line cheat** that the Commodore 64 builds of Pool of Radiance and Curse do not contain (checked there, not in Silver Blades) ([`docs/126-forum-findings.md`](docs/126-forum-findings.md)).
- **The Commodore 64 asks "DISABLE FASTLOADER (Y/N)?" at start-up.** On an unmodified machine answering N is 39 seconds faster to load (199.6 s against 238.6 s), and with JiffyDOS it makes no difference ([`docs/131-fastloader.md`](docs/131-fastloader.md)).
- **The Amiga Curse boot disk's LOAD SAVED GAME loads its own bundled party** from the first disk's save drawer when the player's own save is on another disk (#541 (WinUAE's LOAD SAVED GAME on the Amiga Curse of the Azure Bonds boot disk loads its own bundled party, not the save on the third floppy)).
- **The Amiga ports quit differently.** Pool of Radiance offers QUIT TO WORKBENCH, and Silver Blades' EXIT GAME ends at AmigaDOS with "Please re-boot your system."

## Bugs that exist on one port only

[`goldbox-bugs.md`](goldbox-bugs.md) is the full list. The entries below that depend on the port:

| Bug | Where |
|---|---|
| The code wheel cannot answer 1.6% of its questions | Commodore 64 Curse only |
| Slums camping is safe until the fortune teller is murdered | Commodore 64 Pool of Radiance; DOS differs; the Amiga is unchecked |
| QUICK is never cleared when a fight ends, the hedge maze's safer squares are as dangerous as the rest, training in the wrong order loses a level, undiscovered places appear after reloading on the road | Commodore 64 Pool of Radiance |
| Every weapon in Tilverton's shop costs three platinum | DOS Curse; the Commodore 64 cannot say |
| Every thief gets another race's skill adjustments | Commodore 64 Silver Blades |
| Ranger 11 gets one first-level magic-user spell, paladin 11 has an unfillable slot | Commodore 64 Curse only |
| A low-level magic-user hits one point more easily | DOS Curse and DOS Silver Blades |
| Mirror Image loses an image only every sixteen attacks | DOS Curse |
| A regained paladin loses cure disease through Silver Blades' import | Between DOS Curse and DOS Silver Blades |
| Saving throws ignore a regained class | DOS Curse |
| The Commodore 64 wisdom-12 cleric gets a spell the rule book does not give | Commodore 64 Pool of Radiance |
| Thief skills carry a leftover stack byte | DOS Curse |
| The Commodore 64 racial thief table is one byte short | Commodore 64 Pool of Radiance |
| A joined scroll in a DOS save shifts the character's pack | DOS Silver Blades |
| Amiga Pool of Radiance deletes spaces from names on save | Amiga Pool of Radiance |
| Three Curse maps have a one-way door or a missing script square | Commodore 64 Curse |

## What the live automapper needs on each port

- **Commodore 64 through VICE.** The map is matched against the disk's maps by comparing the 1024 bytes in memory (differing by up to 32 is accepted), and the position comes from the status line, with fallbacks. The roster, five actions, Fast Travel, combat view, combat log and roll reader all read Commodore 64 memory. Combat addresses differ between Pool of Radiance and the later two games ([`docs/101-combat-view.md`](docs/101-combat-view.md), [`docs/212-the-live-tab-per-title.md`](docs/212-the-live-tab-per-title.md)).
- **Condition badges.** Silver Blades draws seven groups with two codes left out, and Curse shares Pool of Radiance's ([`docs/136-condition-badges.md`](docs/136-condition-badges.md)).
- **Fast Travel** has an area table for all three Commodore 64 games and works on Curse and Silver Blades ([`docs/138-multiple-games.md`](docs/138-multiple-games.md)). The overland map in the window is drawn for Pool of Radiance only.
- **The Commodore 64 Ultimate** halts the machine on every memory read, and a read during a disk load can hang it. Wish skips reads while the serial bus looks busy, and the whole backend sits behind an experimental setting ([`docs/161-c64-ultimate.md`](docs/161-c64-ultimate.md), #286 (Pool of Radiance on the C64 Ultimate sometimes hangs on a disk load), #375 (Wish has to work around the Ultimate freezing the C64 mid-load, which hangs the game while the automapper follows along)).
- **The Amiga** has no fixed addresses because the system relocates the game on every load. The backend finds them from a string in the game and works for Curse, Silver Blades and Pools of Darkness; Pool of Radiance's many-part executable has no row. A poll costs 10 to 22 seconds through the WinUAE console, about 2 milliseconds through its named pipe and 10 to 20 milliseconds through a patched FS-UAE on Linux. The roster, actions and combat readers are not built for the Amiga ([`docs/124-amiga-port.md`](docs/124-amiga-port.md), [`docs/165-amiga-savegame.md`](docs/165-amiga-savegame.md)).
- **DOS** has no live backend. A DOS game can be driven in DOSBox for testing, and DOSBox-X has a debugger for memory ([`docs/142-dosbox-x-debugger.md`](docs/142-dosbox-x-debugger.md)).

## What nobody has confirmed

- How DOS and the Amiga draw the Pool of Radiance overland, and where the Amiga keeps its terrain tiles.
- Any travel on Pools of Darkness in a running game, and any Silver Blades route other than the New Verdigris exit.
- The Amiga's rules for Mirror Image, thief tables, the Slums rest, the wisdom table and Pools of Darkness' THAC0.
- Whether Amiga Curse, Silver Blades and Pools of Darkness strip spaces from names on save.
- What the Commodore 64 lets a player type as the longest name.
- Whether a DOS Curse or Silver Blades character can hold more experience than the Commodore 64's three bytes in play.
- What a character with a real portrait looks like on the Amiga Pool of Radiance sheet.
- Whether a real write-protected Amiga or Commodore 64 save disk behaves like the emulators.
- Whether a converted cleric loses Restoration on the Amiga.
- The live damage of a backstab on any port.
- Whether the Commodore 64 Silver Blades disks contain the command-line cheats the DOS builds have.
