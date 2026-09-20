# pool_of_radiance

Tests for Pool of Radiance: its fight driver, the messages and icons it draws, and the tools under `tools/pool_of_radiance/`.

| file | purpose |
|---|---|
| `test_combatdrive.py` | Checks the classifier for Pool of Radiance's row-24 fight bars and the loop over it, on a fake session that records its keys. |
| `test_dirtenicon.py` | Checks that `tools/pool_of_radiance/dirtenicon.py` repairs one empty NPC icon on a copy, changes only his icon bytes and refuses unsupported sources. |
| `test_fleedrive.py` | Checks that a party running away from a fight is recognised and driven to the map edge, on a fake session. |
| `test_monstermsg.py` | Checks the table of monster-attack messages and the call sites `tools/pool_of_radiance/monstermsg.py` reads from the game, and its replay of a monster's block. |
| `test_ohlowatch.py` | Checks that `tools/pool_of_radiance/ohlowatch.py`'s `rows` mode returns Quest Log rows from an all-zero memory window. |
| `test_worldtiles.py` | Checks the three cell rules of `tools/pool_of_radiance/worldtiles.py` on glyphs built here. |
