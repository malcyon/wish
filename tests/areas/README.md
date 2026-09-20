# areas

Tests for areas, maps and travel: the area tables, the map geometry and world map, Fast Travel, and the tools under `tools/areas/`.

| file | purpose |
|---|---|
| `test_areas.py` | Checks the area table in `goldbox/areas.py` for its rows, maps, names and shared Curse maps. |
| `test_areatable.py` | Checks the three shipped area tables against the player's disks by re-deriving them from the game's own `ECL` scripts. |
| `test_eclexitkinds.py` | Checks the exit classifier of `tools/areas/eclexitkinds.py` on scripts built here, and its totals over the thirty area scripts. |
| `test_exitreentry.py` | Checks the push order and address convention of the hand-built stack in `tools/areas/exitreentry.py`, against a fake monitor. |
| `test_exitroute.py` | Checks the route printing of `tools/areas/exitroute.py` on statements built here and on two exits from the disks. |
| `test_fasttravel.py` | Checks that the Fast Travel row waits out a momentarily unsafe machine instead of greying the button. |
| `test_fasttravelrun.py` | Checks the judgement logic of `tools/areas/fasttravelrun.py` against a fake monitor. |
| `test_geo.py` | Checks `goldbox/geo.py`'s reading of a GEO map: its planes, edges, doors, wallsets and rendering, and that every GEO file on the disks parses. |
| `test_newecl.py` | Checks that the `NEWECL` addresses `FastTravel` writes match what each title's own disks say. |
| `test_p20.py` | Checks where Fast Travel lands a party in an area with no arrival square, and which areas it refuses. |
| `test_p3.py` | Checks that the wilderness sites on the disks still hold their undiscovered artwork and that the three windows have the documented sizes. |
| `test_pertitlefasttravel.py` | Checks what Fast Travel does in Curse and Silver Blades, on tables and fakes with no disks. |
| `test_questflags.py` | Checks the quest-flag map's pinned counts and that the side-quest table agrees with the script bytecode it describes. |
| `test_reentrypoints.py` | Checks that the five re-entry addresses of `tools/areas/reentrypoints.py` still agree with the bytes on the player's disks. |
| `test_restinterrupt.py` | Checks the C64 rest-interruption gate in `CAMP`, `DUNGEON` and the area scripts against the player's disks. |
| `test_world.py` | Checks `goldbox/world.py`'s reading of the `SQRDATA` world map: sizes, glyph tables, window seams and coordinates. |
