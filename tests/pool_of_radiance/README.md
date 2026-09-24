# pool_of_radiance

Tests for Pool of Radiance: its fight driver, the messages and icons it draws, and the tools under `tools/pool_of_radiance/`.

| file | purpose |
|---|---|
| `test_combatdrive.py` | Checks the classifier for Pool of Radiance's row-24 fight bars and the loop over it, on a fake session that records its keys. |
| `test_dirtenicon.py` | Checks that `tools/pool_of_radiance/dirtenicon.py` repairs one empty NPC icon on a copy, changes only his icon bytes and refuses unsupported sources. |
| `test_fleedrive.py` | Checks that a party running away from a fight is recognised and driven to the map edge, on a fake session. |
| `test_monstermsg.py` | Checks the table of monster-attack messages and the call sites `tools/pool_of_radiance/monstermsg.py` reads from the game, and its replay of a monster's block. |
| `test_ohlowatch.py` | Checks that `tools/pool_of_radiance/ohlowatch.py`'s `rows` mode returns Quest Log rows from an all-zero memory window. |
| `test_outdoorwalk.py` | Checks that `tools/pool_of_radiance/outdoorwalk.py` raises when the world bar never appears after BEGIN ADVENTURING, with a fake session whose wait times out. |
| `test_pordossaves.py` | Checks that a C64 party converted to DOS gets the saving throws DOS Pool of Radiance's own load-time rebuild leaves, against the rule, the table in `START.EXE`, every engine-written record and the engine's own dwarves. |
| `test_worldtiles.py` | Checks the three cell rules of `tools/pool_of_radiance/worldtiles.py` on glyphs built here. |
