# Memory regions

**Generated** by `tools/genmemory.py` from `por/memory.py` — do not edit.

Every address this project has named, in one place. It answers "what is at
`$4BC2`" without grepping, which is what it exists for;
[40-memory-map.md](40-memory-map.md) holds the *reasoning* and the game's own
string tables.

Addresses are **live** addresses. `SAVEDGAME0` is a verbatim image of
`$4900`–`$64FF` and `SAVEDGAME1` of `$8300`–`$8AFF`, so anything marked as saved
is also a file offset once the base is subtracted. Everything else means what it
says only while the overlay that owns it is resident.

| where | what | saved in | confidence | notes |
|---|---|---|---|---|
| `$037E`–`$037F` | **camera origin** | — | CONFIRMED | top-left square of the 7 x 7 combat window; centred on the acting combatant |
| `$03DE`–`$03E0` | **SETNAM arguments** | — | CONFIRMED | length, then the filename's address in $03DF/$03E0 |
| `$0400`–`$07FF` | **the resident GEO** | — | CONFIRMED | the map the game is drawing, unrelocated -- the file loads at $0400 and in the world the screen has moved to $CC00 |
| `$0400`–`$07FF` | **SQRPACI<nn>** | — | CONFIRMED | the combat-map descriptor page: $0580 tile remap, the parameter block below, and code from $0680. Not a map itself, which is why scoring it as a GEO gave chance |
| `$0600`–`$0613` | **combat-view parameters** | — | CONFIRMED | $0600 glyph table (18 bytes a tile: 9 screen codes, 9 colours), $0602 the map, $0604 the position table, $0606 combatant count, $0607 row stride, $0610/$0611 maximum camera origin, $0612/$0613 maximum square x and y. COM.PREP $08C6 derives the clamps as $0612 - 6, the view being 7 squares ($061A) |
| `$2B80`–`$2C07` | **LINKER** | — | CONFIRMED | the outer loop: read $6E11, load that overlay at $0800, call it, repeat |
| `$2C48` | **LIBRARY** | — | CONFIRMED | resident base. Its declared $1000 is a lie, as every overlay's is; the rest load at $0800 |
| `$3243`–`$327B` | **race names** | — | CONFIRMED | NUL-separated, 1-based: DWARF=1 ... HUMAN=7 MONSTER=8. Reasoning in docs/40-memory-map.md |
| `$327C`–`$3287` | **gender names** | — | CONFIRMED | MALE, FEMALE |
| `$3288`–`$32B2` | **class names** | — | CONFIRMED | 0-based: CLERIC=0 DRUID=1 FIGHTER=2 ... Entries 13, 14 and 15 all point at MAGIC-USER, which is why a paladin displays as one |
| `$32B3`–`$332A` | **alignment names** | — | CONFIRMED | the record's 0x0D8 is a 0-based index into exactly this list |
| `$332B`–`$3346` | **ability labels** | — | CONFIRMED | AGE STR INT WIS DEX CON CHR |
| `$3347`–`$3376` | **money labels** | — | CONFIRMED |  |
| `$3E0B` | **party-list print routine** | — | CONFIRMED | prints name, AC and hit points and nothing else, which is why there is no stored status field |
| `$40EA`–`$4149` | **data-file name stems** | — | CONFIRMED | GDRIVE00, SQRPACI00, GEO00 at $40FC... templates copied elsewhere to build a filename, never patched in place |
| `$4900`–`$493F` | **effect ids** | SAVEDGAME0 | PROBABLE | 64 timed effects; 0 means the slot is free. Expiry clears only the id, so filter on it or you will show effects that have already ended |
| `$4940`–`$497F` | **effect owner** | SAVEDGAME0 | PROBABLE | 0-7 a party member by slot, 8+ a monster, $FF the whole party. This encoding is what led to the combatant table |
| `$4980`–`$49BF` | **effect duration** | SAVEDGAME0 | PROBABLE | bits 6-7 select the time unit |
| `$49C0` | **party x** | SAVEDGAME0 | CONFIRMED | lags a move; the game's own status line is authoritative |
| `$49C1` | **party y** | SAVEDGAME0 | CONFIRMED |  |
| `$49C2` | **party facing** | SAVEDGAME0 | CONFIRMED | 0 north, 1 east, 2 south, 3 west |
| `$49C6`–`$49CB` | **clock** | SAVEDGAME0 | CONFIRMED | six digits, not three: limits 0A 0A 06 18 1E 0C at $A83C. $49C7 minutes, $49C8 tens of minutes, $49C9 the HOUR -- DUNGEON $09F7 prints those three -- then $49CA and $49CB carry the day and the month. Read as plain 'minutes' for a while, which made PORSAVE11 come out at 27:27 |
| `$49E7`–`$49E9` | **wall slot pinned** | SAVEDGAME0 | PROBABLE | one flag per wall slot: do not relocate its screen codes |
| `$49F0`–`$49F1` | **previous square** | SAVEDGAME0 | PROBABLE | the square occupied before the last move; tracked from the walk saves, never confirmed against the game's own use |
| `$49FC` | **party count** | SAVEDGAME0 | PROBABLE | CAMP increments and decrements it |
| `$49FD`–`$49FE` | **wall colour by roofed bit** | SAVEDGAME0 | PROBABLE | a two-entry table indexed by the roofed bit of the square you stand on; every ECL writes both |
| `$4A00`–`$4A1F` | **per-script scratch** | SAVEDGAME0 | PROBABLE | zeroed by DUNGEON $202A whenever the resident ECL changes, so nothing here survives leaving an area. $4A07 is 'staying at the inn' in ECL00 and something else in seven other scripts |
| `$4A20`–`$4B7F` | **persistent flags** | SAVEDGAME0 | UNKNOWN | survives an area change, unlike $4A00-$4A1F. Largely unread |
| `$4B80`–`$4BBF` | **effect magnitude** | SAVEDGAME0 | CONFIRMED | the fourth of the four parallel effect arrays: how much, for whatever the id means. ENLARGE on a character with strength 18/98 wrote $E2, which is $80 \| 98 -- the strength to put back. Not zero in every save after all: PORSAVE13 carries 1 in six slots that nobody had looked at |
| `$4BC0`–`$4BD8` | **loaded-files cache** | SAVEDGAME0 | CONFIRMED | one entry per data-file type, mirroring $6E13 in a running game. Bit 7 is a reload marker, not data -- mask it |
| `$4BC2` | **current GEO** | SAVEDGAME0 | CONFIRMED | the map the party is on, and the answer to the question that stood open longest. All ten New Phlan saves read $00; PORSAVE13, in the slums, reads $14 |
| `$4BE0`–`$4CFF` | **combat icon table** | SAVEDGAME0 | CONFIRMED | 8 entries of 36 bytes, ending exactly at $4D00. Record offset 0x220 for each character |
| `$4D00`–`$58FF` | **character slots** | SAVEDGAME0 | CONFIRMED | TWELVE slots of $100, not eight: 0-7 the party, 8-11 combat. A slot holds only the first 256 bytes of a 580-byte record |
| `$5900`–`$64FF` | **item area** | SAVEDGAME0 | CONFIRMED | one $100 block per slot, 16 items of 16 bytes. Ends exactly at $6500, which is where SAVEDGAME0 ends -- the arithmetic only closes at twelve slots. A live poke here is reverted: this is a copy fed from a master elsewhere |
| `$6B00`–`$6D43` | **the resident character record** | — | CONFIRMED | a fixed base, which is why absolute operands name record offsets directly and why disassembly cracked so much |
| `$6C00`–`$6C1F` | **the resident roster block** | — | CONFIRMED |  |
| `$6D7C`–`$6D8B` | **the resident item** | — | CONFIRMED | its ITEMS type record at $6D8C |
| `$6E11` | **MODE** | — | CONFIRMED | which overlay is running: 0 GEN, 1 DUNGEON, 2 COMBAT, 3 INIT, 4 COM.PREP, 5 POST.COM, 8 FINAL, 9 CAMP. This is the flag to gate on, not the screen |
| `$6E13`–`$6E2B` | **loaded-files cache, live** | — | CONFIRMED | what $4BC0 is a copy of |
| `$8300`–`$83FF` | **party roster** | SAVEDGAME1 | CONFIRMED | eight 32-byte blocks of derived combat values. These same bytes are record offsets 0x100-0x11F -- an export and the roster agree in 31 of 32, differing only at 0x10D |
| `$8400`–`$8AFF` | **ANIMATE00 and a bitmap buffer** | SAVEDGAME1 | CONFIRMED | not save data at all: resident code and graphics scratch that happened to be in memory when the range was dumped |
| `$8B00`–`$8BFF` | **combatant positions** | — | PROBABLE | x, y, index*4\|pose, 0 per combatant; $FF $FF means off the map. Reads all ZERO outside combat, not $FF, so gate on MODE or you will draw 64 combatants at (0,0) |
| `$8C00`–`$91AF` | **the combat map** | — | CONFIRMED | one byte per square at $8C00 + y*stride + x, 56 x 26 with stride 56 in the fights seen. Bit 7 means a combatant stands there; mask & $7F for the terrain, 0 = floor. Outside combat this is LIBRARY's file staging buffer and holds graphics, so gate on MODE. Read the shape from $0607/$0612/$0613, not from constants |
| `$A380`–`$A3BF` | **initiative** | — | PROBABLE | scanned for the maximum with ties broken randomly; the round ends when all 64 are zero |
| `$CC00`–`$CFE7` | **screen** | — | CONFIRMED | in the world. Recompute it from $D018 and $DD00 every read -- it is $0400 at boot |
