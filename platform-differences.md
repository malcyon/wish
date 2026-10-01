# How the Commodore 64, DOS and Amiga versions of the Gold Box games differ

Pool of Radiance, Curse of the Azure Bonds, Secret of the Silver Blades and Pools of Darkness were each released on more than one computer, and the versions do not play identically. This page lists the differences a player meets: numbers and rules that come out differently, screens and menus that say something else, maps that are not the same, and bugs that one version has and another does not.

Pools of Darkness has no Commodore 64 version. It exists on DOS and the Amiga only. The other three games exist on all three computers.

Where a claim could mislead a player it carries a grade: **CONFIRMED** (reproduced in the running game or proven from the program code beyond argument), **PROBABLE** (read from the code or seen once, not yet reproduced) or **UNKNOWN** (nobody has looked, or the evidence disagrees). A claim with no grade is CONFIRMED by the page it links.

## The short version

- **The Commodore 64 is the odd one out more often than not.** Its low-level magic-users and thieves hit a point less easily, hands out a spell or two that the rule book does not, hides coordinates on some screens, and has the smallest limits for running effects.
- **DOS and the Amiga mostly agree with each other.** Where they differ it is usually in what they save, what they ask for at start-up, or what they draw.
- **The Amiga versions are the least explored.** Several rules are unread on the Amiga, and this page says UNKNOWN rather than guess.
- **Pool of Radiance and Pools of Darkness have overland maps the party walks square by square; Curse travels town to town by menu.** Pool of Radiance is also the only game that draws a face on the character sheet.
- **Each version has bugs the others lack.** The last table lists them.

## Combat numbers

### THAC0

- **Pool of Radiance.** A magic-user of level 1 to 5 and a thief of level 1 to 4 have THAC0 20 on DOS and the Amiga and THAC0 21 on the Commodore 64, so they hit one point more easily on the first two. Clerics and fighters are the same on all three ([`docs/135-levelling.md`](docs/135-levelling.md), [`docs/182-amiga-por-in-the-running-game.md`](docs/182-amiga-por-in-the-running-game.md)).
- **Curse and Silver Blades.** The tables differ again. A thief of level 1 to 4 has 20 on DOS and 21 on the Commodore 64. A fighter, paladin or ranger of level 2 has 20 on DOS and 19 on the Commodore 64 (PROBABLE as something a player sees, because the difference is in the tables and no level 2 DOS fighter has been examined). A high-level magic-user has 17 on DOS and 16 on the Commodore 64 (Curse levels 11 and 12, Silver Blades levels 11 to 15).
- **DOS never lets a character's THAC0 be better than 20.** The game rebuilds it when a character loads and reads a row for every class the character lacks, so a pure magic-user of level 1 to 5 in DOS Curse or DOS Silver Blades has 20 where the game's own table says 21. This is listed as bug 16 in [`goldbox-bugs.md`](goldbox-bugs.md) ([`docs/210-the-later-titles-dos-thac0.md`](docs/210-the-later-titles-dos-thac0.md), [`docs/224`](docs/224-the-dos-thac0-floor.md)).
- **The Amiga rebuilds THAC0 as well.** Amiga Pool of Radiance rebuilds the base value when a character loads (a low-level magic-user's 39 became 40). Amiga Curse recomputes the current THAC0 from the readied weapon on load, but a stored base of 39 survived a load and save there; its program's import and training loops write 40. Amiga Silver Blades has the same loops (PROBABLE, read and not watched), and Pools of Darkness is UNKNOWN ([`docs/182-amiga-por-in-the-running-game.md`](docs/182-amiga-por-in-the-running-game.md), [`docs/224-the-dos-thac0-floor.md`](docs/224-the-dos-thac0-floor.md)).
- **The Commodore 64 recomputes THAC0 at the start of every fight** from the base value, strength and, in Pool of Radiance, the weapon in hand. Until the first fight the sheet may show an older number ([`docs/205-the-c64-thac0-rebuild.md`](docs/205-the-c64-thac0-rebuild.md)).
- **Strength above 18 is scored on a separate scale on the Commodore 64.** The game indexes strength 19 and over as the score plus 5, up to 30, so strength 21 gives +4 to hit and +9 damage there. The three Commodore 64 games share the routine, and Silver Blades' to-hit table has not been read.

### Backstab

The multiplier is not shown on any sheet. It is worked out from the thief's level ([`docs/225-the-dos-backstab-multiplier.md`](docs/225-the-dos-backstab-multiplier.md)).

| Version | Backstab multiplier |
|---|---|
| Pool of Radiance, DOS and Amiga | Thief level divided by 4 (dropping the remainder), plus 2, so it rises at levels 4, 8 and 12 |
| Curse and Silver Blades, DOS and Amiga | The same, using one level less, so it rises at levels 5, 9 and 13. A thief who regained the class counts the regained level. Confirmed for DOS; the Amiga code is read but not run |
| Pools of Darkness, DOS and Amiga | The higher of the current and former thief level, with the multiplier capped at 5 |
| Every Commodore 64 game | One level less than the thief level, divided by 4, plus 2. Silver Blades caps the level at 14 first |

- **The penalty to hit on a backstab is 2 on the Commodore 64 and in Pool of Radiance on DOS and the Amiga, and 4 in the later DOS and Amiga games** (CONFIRMED from the program code, not watched in play).
- **Nobody has measured backstab damage in play on any version.**
- **In DOS Pool of Radiance a thief's abilities depend on the thief level and not on the class.** A character with a thief level and a fighter-only class plays as a thief, and the game has no Find Traps command ([`docs/221-thief-abilities-in-dos-pool-of-radiance.md`](docs/221-thief-abilities-in-dos-pool-of-radiance.md)).

### Thief skills

The percentages are never drawn on a sheet. A player meets them as locks that open or fail and as sneaking that works or does not ([`docs/125-bug-notes.md`](docs/125-bug-notes.md), notes N21 to N23).

- **Pool of Radiance.** The Commodore 64's racial table is one entry short, so gnome, half-elf, halfling and half-orc thieves get a neighbouring race's adjustments. A Commodore 64 halfling or half-elf thief moves silently 5 points better than on DOS, and the Commodore 64 ignores dexterity for thief skills. DOS does use dexterity, with two mistakes: dexterity 10 gives -19 to pick pockets where the rules give -10, and dexterity 16 gives -5 to open locks where the rules give +5. A DOS thief with dexterity 16 opens locks ten points worse than a Commodore 64 thief.
- **Curse.** Both versions use the same tables, but DOS Curse adds a stray value (observed as +7) to all eight skills, so a DOS Curse thief is seven points better at everything than the tables say. The Commodore 64 does not.
- **Silver Blades.** The Commodore 64 gives every thief the next race's row, and a halfling gets dexterity penalties instead of a bonus, ending with 0% move silently at level 1 and dexterity 17. This is bug 13 in [`goldbox-bugs.md`](goldbox-bugs.md). Whether DOS Silver Blades does the same is UNKNOWN.
- **Amiga Pool of Radiance appears to follow the DOS rules** (PROBABLE, two characters).

### Saving throws and racial traits

- **The constitution bonus for dwarves, gnomes and halflings reaches the saves in different ways.** DOS Pool of Radiance and Curse apply it when the save is rolled (constitution times 2, divided by 7 and dropping the remainder, nothing below constitution 4). The Commodore 64 builds it into the saves shown on the sheet: all five in Pool of Radiance, three in Curse, and the dwarf only in Silver Blades. DOS Silver Blades has the effect but no saving throw consults it, so a Silver Blades halfling or dwarf there gains nothing from it (CONFIRMED from the code, not watched in play) ([`docs/189-effect-97-from-the-code.md`](docs/189-effect-97-from-the-code.md), [`docs/230-who-reads-a-dos-effect-node.md`](docs/230-who-reads-a-dos-effect-node.md)).
- **The racial effects a character starts with differ by game and version.** A DOS dwarf has four in Pool of Radiance, three in Curse and three in a different order in Silver Blades. The Commodore 64 Pool of Radiance gives effects only to elves and half-elves. A Silver Blades halfling has a different one on the Commodore 64 than on DOS ([`docs/200-innate-effect-seeding.md`](docs/200-innate-effect-seeding.md)).
- **Silver Blades halflings are protected differently.** On the Commodore 64 the halfling's effect cancels Ray of Enfeeblement, Feeblemind and Fear. On DOS it cancels Fear only (not watched in play).
- **Infravision.** On the Commodore 64 in Pool of Radiance and Curse, dwarves, elves, gnomes, half-elves and half-orcs see 60 feet in the dark, halflings 30 feet and humans none. All six Commodore 64 Silver Blades characters examined have none, including the dwarf, and the right value is UNKNOWN.
- **DOS Curse ignores a regained class when it works out saving throws.** This is bug 19 in [`goldbox-bugs.md`](goldbox-bugs.md).

## Spells

- **Spells 1 to 56 are the same spells in the same order in every game and version.** After 56 the versions diverge: DOS uses further numbers for effects that magic items produce, and the Commodore 64 uses the same numbers for pieces of combat messages (PROBABLE, [`docs/128-guide-and-scripting.md`](docs/128-guide-and-scripting.md)).
- **Wisdom bonus spells for clerics.** Commodore 64 Pool of Radiance gives a cleric of wisdom 12 one extra first-level spell and wisdom 13 two, which is one more than the rule book. DOS Pool of Radiance gives one at 13 and two from 14. Curse and Silver Blades give one extra per point of wisdom from 13 up to 19. Pools of Darkness uses Curse's table from 13 to 18, and 19 gives what 18 gives. The Amiga Pool of Radiance table is unread ([`docs/125-bug-notes.md`](docs/125-bug-notes.md), note N13).
- **A ranger or paladin of level 11 in Curse has different spells on the Commodore 64 and on DOS.** On the Commodore 64 a level 11 ranger can memorise one first-level magic-user spell where DOS offers two, and a level 11 paladin has a second-level cleric slot that the game never lets them fill, where DOS grants those spells. These are bugs 14 and 15 in [`goldbox-bugs.md`](goldbox-bugs.md).
- **The Silver Blades magic-user chooses spells differently on the Commodore 64.** The menu is built from a table that disagrees with the other two games at levels 11, 13 and 15, asks for intelligence 12 for sixth-level spells and 14 for seventh-level, and never offers one druid spell. A Silver Blades cleric needs wisdom 17 for the level 11 spells ([`docs/135-levelling.md`](docs/135-levelling.md)).
- **Pools of Darkness spell slots.** Its cleric spell levels 8 and 9 stay empty, and its creation menus offer fewer choices than the other games: six races, with the elf offered 7 classes, the half-elf 13, the dwarf, gnome and halfling 3 each and the human 6. No race can be a druid or a monk, and a paladin can only be lawful good ([`docs/228-pools-of-darkness-spells-and-creation.md`](docs/228-pools-of-darkness-spells-and-creation.md)). The Amiga creation menu is unread.
- **Mirror Image in DOS Curse** loses an image only once for every sixteen attacks it absorbs, so it lasts far longer than its image count suggests. DOS Silver Blades and the Commodore 64 count correctly, and the Amiga is unread (bug 17 in [`goldbox-bugs.md`](goldbox-bugs.md)).
- **How many spells a Pool of Radiance character can memorise** is capped differently by each version's records (21 on DOS, 81 on the Commodore 64). Whether anyone can reach more than 21 in play is UNKNOWN.

## Training, classes and experience

| | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| Who can be a paladin, ranger or dual-class | Nobody | Paladin and ranger exist, and a human may change class once | As Curse |
| How a level is gained | At a training hall (the Commodore 64) or by walking to one of four schools (DOS) | One press of the training command raises every class that is ready | As Curse |
| Cost | 1000 gold | 1000 gold | The Commodore 64 trainer takes no money (UNKNOWN whether a script charges first) |

- **Training in the wrong order throws away a level in Commodore 64 Pool of Radiance.** A multi-class character who trains a class before the one the game expects loses a level they had earned (bug 8 in [`goldbox-bugs.md`](goldbox-bugs.md)).
- **The Commodore 64 Curse trainer says UNABLE TO ADVANCE** where Pool of Radiance says LOW EXPERIENCE OR WRONG CLASS. A refused press costs nothing. Curse and Silver Blades roll the hit die twice and keep the better (PROBABLE). A dual-classed character gains no hit points until the new class passes the old class's level, and pays 1000 gold for each level gained ([`docs/172-curse-trainer.md`](docs/172-curse-trainer.md), [`docs/192-curse-dual-class.md`](docs/192-curse-dual-class.md)).
- **After training, experience is left one point short of the next level's threshold** (CONFIRMED on 42 of 42 DOS trainings). Whether DOS and the Commodore 64 charge a multi-class character the same experience is UNKNOWN: one Commodore 64 sample disagrees with the DOS rule.
- **Curse asks for the code wheel when you train on DOS.** Silver Blades on DOS asks nothing when you change class.
- **A human changes class once only.** The Commodore 64 prints UNABLE TO CHANGE CLASS on a second try, and DOS stops showing the menu line. The requirements are a human, prime requisites of 15 or more in the old class, 17 or more in the new class, and level 2 or more. The old class never trains again. In DOS Curse, choosing HUMAN CHANGE CLASS at level 0 likely stops the game with a runtime error (PROBABLE).
- **When a dual-classed character catches up, the two versions record it differently.** The Commodore 64 gives back the old class and the sheet shows both, for example FIGHTER/PALADIN. DOS keeps working from both sets of levels at each use and shows only the new class. A regained paladin or ranger in Curse gets a class combination the Commodore 64's own name table cannot name ([`docs/176-changing-class-twice.md`](docs/176-changing-class-twice.md), [`docs/209-the-regained-dual-class-on-dos.md`](docs/209-the-regained-dual-class-on-dos.md), [`docs/214-the-regained-dual-class-on-the-c64.md`](docs/214-the-regained-dual-class-on-the-c64.md)).
- **Race limits cost levels on the Commodore 64.** A non-human's racial level limit is lowered by one level when the prime requisite is exactly 17 and by two when it is below 17 ([`docs/135-levelling.md`](docs/135-levelling.md)).

### Paladins

- **Lay on hands exists in Curse and Silver Blades only.** It lasts a day on every version.
- **Cure disease lasts a week on DOS and the Amiga (10080 minutes), and ends at the seventh midnight on the Commodore 64.** The uses a day are 1, 2 and 3 on both versions up to level 15. At level 16 DOS gives 4 and the Commodore 64 3 ([`docs/231-where-lay-on-hands-lives.md`](docs/231-where-lay-on-hands-lives.md), [`docs/234-a-paladins-cure-disease-across-dos-and-the-c64.md`](docs/234-a-paladins-cure-disease-across-dos-and-the-c64.md)).
- **A regained paladin loses cure disease on the way into Silver Blades.** A human who regains paladin in DOS Curse and is brought into Silver Blades with the game's own character import finds the ability gone (bug 18 in [`goldbox-bugs.md`](goldbox-bugs.md)).

### Turning undead

- **Clerics and paladins turn on different tables in each game.** A paladin turns as a cleric two levels weaker. Pool of Radiance uses a table, and Curse and Silver Blades use arithmetic.
- **DOS groups a cleric's level when they turn** (1 to 8 as it stands, 9 to 13 as 9, higher as 10) and reads the row from the undead creature. The Commodore 64 uses a turning strength stored for the cleric, and offers the TURN command only when it is above zero ([`docs/178-turning-undead.md`](docs/178-turning-undead.md)). Nobody has watched a cleric turn real undead on every version.

### Experience

- **The experience for a kill** is a base value plus an amount for each hit point of the monster in Pool of Radiance on the Commodore 64 and DOS. Pools of Darkness and Treasures of the Savage Frontier give the base only ([`docs/215-the-dos-experience-award-and-the-scroll-bundle.md`](docs/215-the-dos-experience-award-and-the-scroll-bundle.md)).

## Spells and effects that last

- **How long a spell lasts is counted differently.** The Commodore 64 stores a count up to 63 with a unit of a minute, ten minutes, an hour or a day, and ages it by the clock's digits rather than by elapsed minutes. DOS and the Amiga count minutes. A duration of zero means permanent on DOS and never ages on the Commodore 64 ([`docs/133-active-effects.md`](docs/133-active-effects.md), [`docs/202-the-amiga-effect-node-pad.md`](docs/202-the-amiga-effect-node-pad.md)).
- **The Commodore 64 has room for 64 running effects across the whole party and ten permanent trait slots for each character.** DOS and the Amiga keep a list for each character with no fixed limit, so a long run of camp buffs (eleven Blesses on a party of six is 66 effects) fits there and not on the Commodore 64. When a member leaves, the Commodore 64 keeps their effects and DOS and the Amiga drop them ([`docs/226-the-c64-running-effect-crosswalk.md`](docs/226-the-c64-running-effect-crosswalk.md)).
- **Dispel Magic behaves differently.** On the Commodore 64 it can never remove an effect held in a trait slot. DOS rolls against each effect separately, and two Blessings on one character change only the odds of dispelling.
- **Effects have different numbers in each game,** and the second half, which holds monster abilities, is not shared. Some names inherited from Pool of Radiance do nothing in Curse: a few "breath weapon" and "boulder" effects end in a no-operation ([`docs/222-naming-curses-effect-codes-from-their-handlers.md`](docs/222-naming-curses-effect-codes-from-their-handlers.md)).
- **Ability scores in the later Commodore 64 games have a permanent score and a score in force.** The sheet shows the one in force, and Silver Blades marks an ability that differs with a plus. Pool of Radiance has a single value. DOS keeps the pair for every later game ([`docs/201-the-two-ability-arrays.md`](docs/201-the-two-ability-arrays.md), [`docs/204-the-dos-ability-pair.md`](docs/204-the-dos-ability-pair.md)).

## Items, weight and movement

- **Every game and version limits a character to 16 items.** The game refuses a 17th with the word "Overloaded", which also appears when the load is too heavy. Pools of Darkness skips the count test when the character already holds an item with the same effect (SPECULATIVE what that allows) ([`docs/173-carrying-limits.md`](docs/173-carrying-limits.md)).
- **Weight bands and movement differ at five edges.** The weights 512, 768 and 1024 fall in the heavier band on the Commodore 64 and the lighter on DOS. Strength 3 to 7 reduces a DOS character's allowance and not a Commodore 64 character's. Strength 19 allows 4000 on DOS and 4500 on the Commodore 64. DOS weighs a stack by its whole count and the Commodore 64 by the low part of it. Light magic armour adds 3 on DOS when its base is 9 or less. On 222 DOS characters the two rules never disagreed in play.
- **The dagger cannot be thrown on DOS, and can on the Commodore 64.** The DOS dagger has a rate of fire of 0 and range 1. The Commodore 64's has rate 2 and range 4 and is flagged as thrown. A dart can only be thrown on DOS, and fires several times a round on the Commodore 64. This is read from the item data and the DOS guide and has not been watched in play ([`docs/125-bug-notes.md`](docs/125-bug-notes.md), R51).
- **Silver Blades scrolls.** On DOS a joined bundle of scrolls is one item holding up to ten scrolls, which saves slots. On the Commodore 64 each scroll takes its own slot.
- **The Commodore 64 disks hold five Rings of Fire Resistance.** One of them is flattened and grants no resistance. It is PROBABLE that a player cannot reach it ([`docs/183-the-two-rings-of-fire-resistance.md`](docs/183-the-two-rings-of-fire-resistance.md)).
- **The bag of holding discount exists in DOS Pool of Radiance.** Curse has the code and no way to reach it, and Silver Blades has none ([`docs/125-bug-notes.md`](docs/125-bug-notes.md), N24).
- **A character's items are listed from opposite ends.** The Commodore 64 draws the last slot first, and DOS and the Amiga draw the first item on top.

## Party, companions and treasure

- **A party is six player characters plus companions,** up to eight members in Pool of Radiance on the Commodore 64, DOS and the Amiga (seven members have been loaded, walked and saved on the Amiga; an eighth there is PROBABLE). The later games' limits above six are PROBABLE.
- **The Commodore 64 builds its party list from the other end than DOS and the Amiga,** so the same party reads in the opposite order.
- **A companion's share of the treasure is worked out differently.** DOS, Amiga Pool of Radiance and DOS Curse and Silver Blades give a companion a fraction of each pile. The Commodore 64 rolls once for each monster killed, with a chance that grows with the party's size. The Amiga's later games are unread ([`docs/232`](docs/232-the-c64-control-byte-per-title.md)).
- **A companion's morale is capped at 100 in the five later Commodore 64 games and not in Pool of Radiance.** Only Pool of Radiance flags a character as having an altered ability.
- **Names.** Amiga Pool of Radiance deletes an ordinary space from a character's name each time it saves, so a name typed into RENAME loses its spaces within a save or two (9 of 9 names with spaces lost them, none of 26 without). A name made with CREATE NEW CHARACTER keeps its spaces, because the game stores a space there as a different byte it never strips. A name can be 15 characters on DOS and the Amiga. The Commodore 64 draws lower-case letters in a name as punctuation: "Guy de Valois" shows as garbage. On the Amiga the full stop, asterisk, comma, question mark, slash, colon and semicolon are also deleted from Pool of Radiance names ([`docs/206-three-amiga-questions.md`](docs/206-three-amiga-questions.md), #308 (Does Amiga Pool of Radiance drop the space out of a character's name when it saves?)).

## Resting, encounters and fleeing

- **Camping in the Slums.** In Commodore 64 Pool of Radiance a rest in the Slums is never interrupted unless you have murdered the fortune teller (37 two-hour rests rolled no check). On DOS a rest is checked every two hours at a 24% chance, with no murder needed. The Amiga's Slums script is DOS's byte for byte, so it should behave like DOS, but nobody has rested there on an Amiga (PROBABLE) ([`docs/207-c64-rest-interruption.md`](docs/207-c64-rest-interruption.md), bug 12 in [`goldbox-bugs.md`](goldbox-bugs.md)).
- **In New Phlan every street rest is interrupted** on the versions checked, and the City Watch asks whether to GO or STAY. Choosing STAY starts a fight.
- **A scripted event can turn a rest into a fight in Silver Blades,** for example the Black Circle's attack on the town during an eight-hour rest, seen on the Commodore 64.
- **Fleeing.** All three Commodore 64 games print THE PARTY RUNS AWAY through the same code, and Silver Blades' encounter menu says YOU FLEE where the others say THE PARTY FLEES. Characters left behind are dropped from the party. DOS Curse has the same three cases with the messages "Got Away" and "Escape is blocked". Only Pool of Radiance's has been seen on a screen (#445 (The game's third fight outcome, THE PARTY RUNS AWAY, has never been seen on a screen)).
- **Losing a fight on the Commodore 64 stops at THE PARTY HAS LOST with no prompt.** Whether DOS does the same is unmeasured.
- **QUICK is never cleared after a fight in Commodore 64 Pool of Radiance** (bug 3 in [`goldbox-bugs.md`](goldbox-bugs.md)).

## Maps and travel

### Dungeon and town maps

The maps are the same grid on every version: 16 squares by 16. A few differ in a way a player can meet ([`docs/88-map-files.md`](docs/88-map-files.md), [`docs/145-dos-decode-kit.md`](docs/145-dos-decode-kit.md)).

| Game | Result of comparing the versions |
|---|---|
| Pool of Radiance | Two of 29 maps differ on the Commodore 64: one in a script number and one wall edge, and one wilderness cave in which three squares are roofed on the Commodore 64 and open elsewhere. The DOS and Amiga maps are identical |
| Curse | Three of 16 maps differ on the Commodore 64 by two details each, and DOS and the Amiga agree. In one a wall edge is solid on the Commodore 64 and open elsewhere, which makes a one-way door. In another a one-way passage runs the other way. In the third a wall is drawn from a different piece. Two squares on the Commodore 64 have no event attached where the other versions have one |
| Silver Blades | All 17 maps are identical on the three versions |
| Pools of Darkness | The DOS and Amiga maps are identical |

- **Which scripts exist differs.** The Commodore 64 Curse has three scripts that DOS lacks and DOS has one that the Commodore 64 lacks. What they do is unread (#443 (Three of Curse's sixteen maps differ between the C64 and the Amiga, and nobody has looked at how)).
- **Commodore 64 Pool of Radiance has an attract-mode demo script that DOS lacks** ([`docs/128-guide-and-scripting.md`](docs/128-guide-and-scripting.md)).

### Overland travel

| Game | What a player sees |
|---|---|
| Pool of Radiance | A map of squares, moved in eight directions, with a time cost for each step. The world is about 40 by 32 squares. Each version draws it differently (below) |
| Curse | A full-screen picture of the Dalelands and a menu: ENTER CITY, JOURNEY ON, CAMP and later SEARCH AREA. JOURNEY ON lists the neighbouring places. The mode bar reads TRAIL, WILDERNESS or BY BOAT, and a leg costs days (trail 2, wilderness 4, boat 1). There is no square, facing or compass, and the seventh leg asks the code wheel. CONFIRMED on the Commodore 64, PROBABLE on DOS from the program code, UNKNOWN on the Amiga |
| Silver Blades | No overland screen was found. Leaving New Verdigris asks YOU ARE LEAVING THE TOWN. DO YOU CONTINUE? and then INSERT SIDE B, and the party appears in an ordinary map (one route, on the Commodore 64) |
| Pools of Darkness | A walkable overland grid 38 squares wide and 15 high. The keypad's 1 to 9 move the party one square at a time in any of eight directions, with no turning, and stepping onto a place such as Mulmaster asks DO YOU ENTER? CONFIRMED on the Amiga, with the grid size read from the program code; the DOS version has not been examined |

Evidence: [`docs/113-world-map.md`](docs/113-world-map.md), [`docs/217-drawing-the-wilderness.md`](docs/217-drawing-the-wilderness.md), [`docs/141`](docs/141-dos-savegame.md).

Pool of Radiance's overland on each version:

- **Commodore 64.** The overland is drawn with the same square engine as combat, in tiles three characters across. Keys are the digits 1 to 8, clockwise from north, and the prompt reads "1-8, RETURN OR BUTTON". The status line shows the word OUTDOORS where the facing letter goes. A game saved outdoors does not remember the heading.
- **DOS.** The arrow keys move the party directly. The status line shows the world position as two numbers, a facing letter and the time, and the terrain is probably drawn from one of the DOS tile files (PROBABLE).
- **Amiga.** Movement is absolute, the facing is the direction of the last step, and the keys are the top-row digits. How the terrain is drawn is UNKNOWN.
- **A step costs about twelve hours on every version.**
- **Saving.** You can save outdoors on the Commodore 64 and the Amiga from ENCAMP, SAVE. You cannot save in the middle of a wilderness encounter on the Commodore 64, because the combat bar has no ENCAMP.
- **Reloading on the road re-shows hidden places on the Commodore 64,** for example the nomad camp, because loading skips the paint. For DOS and the Amiga this is UNKNOWN (bug 10 in [`goldbox-bugs.md`](goldbox-bugs.md)).

## What the screens and menus show

- **The status line.** The Commodore 64 prints facing, time and square, for example "E 16:48  5,2". DOS and the Amiga print square, facing and time, for example "5,9 W 00:04", and pad the hour to two digits (PROBABLE; read from quoted lines).
- **The Commodore 64 prints no square** in the Slums, in Curse area 3, in the Kobold Caves and in eleven of Silver Blades' 22 areas. Whether DOS or the Amiga ever leave it out is UNKNOWN ([`docs/138-multiple-games.md`](docs/138-multiple-games.md)).
- **Keys indoors.** On the Commodore 64: I forward, J and K turn, M steps back one square. On Amiga Pool of Radiance: the top-row digits 4, 6 and 8. On Amiga Curse and Silver Blades: the numeric keypad only, 8 forward, 4 and 6 to turn, 2 to about-face. The DOS keys are not recorded.
- **The character sheet.** Commodore 64 Pool of Radiance shows VIEW with ITEMS, SPELLS, TRADE, DROP and EXIT. Curse adds CURE and HEAL for a paladin. Silver Blades shows a bare EXIT for a character with nothing to list. Amiga Pool of Radiance shows View, Items, Trade, Drop, Rename and Exit, with gold, encumbrance and movement in the right-hand third where the other versions put a face ([`docs/182-amiga-por-in-the-running-game.md`](docs/182-amiga-por-in-the-running-game.md)).
- **Commissions.** Only Pool of Radiance has the council's commissions. Curse and Silver Blades have no equivalent ([`docs/103-quest-log-panel.md`](docs/103-quest-log-panel.md)).
- **Portraits.** Only Pool of Radiance draws a face on the sheet. The creation menu offers 14 heads and 12 bodies in the same order everywhere. The Amiga's eighth body is a different drawing, a knight in mail behind a blue shield, where the other versions draw a bare chest under a cloak. Curse and Silver Blades on the Commodore 64 draw no face (Silver Blades shows a money panel in the space). For DOS Curse and DOS Silver Blades it is UNKNOWN, and Pools of Darkness shows none on either version (PROBABLE). Whether Amiga Pool of Radiance draws one for a character created with a portrait is UNKNOWN ([`docs/188-the-sheet-portrait-per-title.md`](docs/188-the-sheet-portrait-per-title.md)).
- **Combat figures.** The figure that stands for a character on the combat map is drawn differently on each version ([`docs/168-dos-dax-and-combat-icons.md`](docs/168-dos-dax-and-combat-icons.md), [`docs/193-a-dos-figure-on-the-c64.md`](docs/193-a-dos-figure-on-the-c64.md), [`docs/199-amiga-combat-icons.md`](docs/199-amiga-combat-icons.md)).

| | Commodore 64 | DOS | Amiga |
|---|---|---|---|
| Look | A block of three by three characters (24 by 24 pixels), one of eight colours for each of seven parts, a fixed light red face and a black outline | 24 by 24 pixels in 16 colours, with a main and a highlight colour for six parts, and a plume or hat always magenta | The same pixels as DOS apart from a plume highlight, where about 42 to 50 pixels differ and how they look is UNKNOWN |
| Choices | 28 weapons and 14 heads at the small size, 35 and 23 at the large | 14 heads and 32 bodies in two sizes | As DOS |

- **The Commodore 64's figures are redrawings, so a heads-and-bodies choice does not look the same.** The size is chosen from the race and never changes, so figures of mixed sizes appear in one party.
- **Silver Blades redrew two pieces of art** (a large head and a small body) on DOS and the Amiga, and three glyphs on the Commodore 64. Curse's Commodore 64 art is Pool of Radiance's.
- **All three versions draw two poses for a figure,** READY and ACTION. On the Commodore 64 nobody has caught the ACTION pose on the combat map ([`docs/186-ready-and-action.md`](docs/186-ready-and-action.md)).
- **Pools of Darkness on the Amiga gives each character a default figure** by size, sex and class.

## Start-up, saving and protection

- **Copy protection differs on every version.** The Commodore 64 Pool of Radiance asks for a code word. The Commodore 64 Curse asks questions from the printed code wheel, and about 1.6% of its challenges (161 of 10,296) have no answer on that wheel, so the game calls you wrong when you are right. DOS Curse shows a rune-alignment wheel before the main menu and its wheel is correct (bug 1 in [`goldbox-bugs.md`](goldbox-bugs.md)).
- **Silver Blades on the Commodore 64 never asks,** because the check is dead code in the releases examined. The Amiga Silver Blades asks a journal word and a rule-book question when you BEGIN ADVENTURING.
- **The Amiga releases examined differ.** The Amiga Pool of Radiance accepts a bare RETURN at the wheel, and Amiga Curse asks the wheel. These are properties of the particular releases, and the general case is UNKNOWN.
- **The DOS versions have a command-line cheat** that the Commodore 64 Pool of Radiance and Curse do not contain. The Commodore 64 Silver Blades was not searched ([`docs/126-forum-findings.md`](docs/126-forum-findings.md)).
- **The Commodore 64 asks "DISABLE FASTLOADER (Y/N)?" at start-up.** On an unmodified machine, answering N loads 39 seconds faster (199.6 seconds against 238.6), and with JiffyDOS it makes no difference ([`docs/131-fastloader.md`](docs/131-fastloader.md)).
- **Saving on the Amiga.** Pool of Radiance asks "PATH FOR SAVE RETURN = POOLSAVE:", and a bare RETURN uses a disk named POOLSAVE. Curse and Silver Blades never ask. They save on the disk you started from, and look at the first drive and then the second, never the third. On the Amiga Curse boot disk, LOAD SAVED GAME loads the party kept on that disk, not a save on a separate disk ([`docs/191`](docs/191-the-amiga-save-disk.md)).
- **Silver Blades on the Commodore 64 has no list of saved games.** LOAD SAVED GAME loads the party straight away.
- **Quitting.** Amiga Pool of Radiance offers QUIT TO WORKBENCH, and Amiga Silver Blades' EXIT GAME ends at AmigaDOS with "Please re-boot your system."

## Bugs that exist on one version only

[`goldbox-bugs.md`](goldbox-bugs.md) has the full list. Those that depend on the version:

| Bug | Where |
|---|---|
| The code wheel cannot answer 1.6% of its questions | Commodore 64 Curse only |
| Camping in the Slums is safe until the fortune teller is murdered | Commodore 64 Pool of Radiance. DOS behaves differently, and the Amiga's script is DOS's (not watched) |
| QUICK is never cleared after a fight, the hedge maze's safer squares are as dangerous as the rest, training in the wrong order loses a level, reloading on the road shows undiscovered places | Commodore 64 Pool of Radiance |
| Every weapon in Tilverton's shop costs three platinum | DOS Curse. The Commodore 64 cannot say |
| Every thief gets another race's skill adjustments | Commodore 64 Silver Blades |
| A level 11 ranger memorises one first-level spell, a level 11 paladin has a slot they can never fill | Commodore 64 Curse |
| A low-level magic-user hits one point more easily than the table says | DOS Curse and DOS Silver Blades |
| Mirror Image loses an image only every sixteen attacks | DOS Curse |
| Saving throws ignore a regained class | DOS Curse |
| A regained paladin loses cure disease on entering Silver Blades | Between DOS Curse and DOS Silver Blades |
| A cleric of wisdom 12 or 13 gets a spell the rule book does not give | Commodore 64 Pool of Radiance |
| All thief skills carry a stray +7 | DOS Curse |
| The racial thief table is one entry short | Commodore 64 Pool of Radiance |
| Three Curse maps have a one-way door or a missing event square | Commodore 64 Curse |
| Spaces are deleted from names | Amiga Pool of Radiance |
| Losing a fight stops with no prompt | Commodore 64 (DOS unmeasured) |

## Not yet known

- How DOS and the Amiga draw the Pool of Radiance overland, and what the Amiga uses for terrain.
- Pools of Darkness' overland on DOS, and any Silver Blades route other than the New Verdigris exit.
- The Amiga's rules for Mirror Image, thief skills, the wisdom table, resting in the Slums and the Pools of Darkness THAC0.
- Whether Amiga Curse, Silver Blades and Pools of Darkness delete spaces from names.
- What a character created with a portrait looks like on the Amiga Pool of Radiance sheet.
- The damage of a backstab on any version.
- Whether the Commodore 64 Silver Blades disks contain the command-line cheats the DOS versions have.

The evidence for each claim is in the [`docs/`](docs/README.md) page linked beside it.
