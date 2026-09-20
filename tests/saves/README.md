# saves

Tests for the save containers and their readers: the D64 disk image, the C64 container, the saved-game and world-state models, and the YAML form of a save.

| file | purpose |
|---|---|
| `test_binary_roundtrip.py` | Checks that every binary reader hands back what it was given, and refuses a truncated, mis-sized or missing file. |
| `test_c64container.py` | Checks that `goldbox/c64_save.py`'s `C64Container` is one class with six rows and refuses a title whose payload map nobody has measured instead of answering with Pool of Radiance's. |
| `test_d64.py` | Checks `goldbox/d64.py`'s sector geometry, directory parsing and file reading, on a disk built from the committed fixtures and on a real `POOL1`. |
| `test_d64_blank.py` | Checks that `D64.blank` and `D64.write_file` build a valid 1541 image whose directory, chain and free-block count agree with what was written. |
| `test_d64_variants.py` | Checks that `goldbox/d64.py` opens the 40- and 42-track images with their error maps, refuses every write to them and still refuses a size it does not know. |
| `test_savegame.py` | Checks `goldbox/savegame.py`'s slot model, where a save's party is eight slots of `$100`, against a real six-character save. |
| `test_world_state.py` | Checks that `goldbox/world_state.py`'s `WorldState` reads a title's own C64 and DOS specimens to the same answer and carries the five fields added over `PorSaveState`, and that `pod_from_dos` reads a synthetic Pools of Darkness container into `PodWorldState`. |
| `test_yaml_dualclass.py` | Checks that a dual-classed character's former class exports to YAML and that the importer refuses each value it cannot trust. |
| `test_yaml_io.py` | Checks that exporting a save to YAML and importing it unchanged reproduces the file byte for byte, and that an edit changes exactly the bytes it names. |
