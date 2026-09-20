# curse_of_the_azure_bonds

Tests for Curse of the Azure Bonds: its C64 disks, saves, tables and level-up rules, and the tools under `tools/curse_of_the_azure_bonds/`.

| file | purpose |
|---|---|
| `test_curse.py` | Checks the Curse save layout and title key, its maps and combat icons, the editor's and the export's reading of a Curse save, and the cleric grant table. |
| `test_curseabilities.py` | Checks that a C64 Curse record's second ability array reads as a named dictionary and writes back without an error. |
| `test_cursedualtrain.py` | Checks what Curse's trainer does to a dual-classed character, replayed from the four routines, and that `goldbox/levelup.py` plans the same. |
| `test_curselevels.py` | Checks Curse's ceilings, racial limits, THAC0, experience, hit dice and spell slots against the game's own tables and the shipped records. |
| `test_curselive.py` | Checks the addresses a live Curse session measured, the code paths that use them, and the walked route replayed through `GEO01`. |
| `test_curseload.py` | Checks the disk repair and the two causes that can be shown without an emulator when a Curse save disk will not load in a driven session. |
| `test_cursememorize.py` | Checks the key-list expansion and the per-press log of the DOS Curse `MEMORIZE` page-turn driver against a fake session, including the stop after two screens with no highlight on them. |
| `test_cursepaladin.py` | Checks which record offsets `tools/curse_of_the_azure_bonds/cursepaladin.py` reads and stages, on a save disk built here from zeroes. |
| `test_curserun.py` | Checks that a Curse session mounts the saved side before entering and leaves an invalid side to the disk prompt. |
| `test_cursespellslots.py` | Checks the spell slots a conversion writes for a Curse magic-user, cleric, paladin and ranger from the game's own tables. |
| `test_cursethac0.py` | Checks against the player's own disks what Curse's overlays do with the stored THAC0, and what the tool stages. |
| `test_cursethiefskills.py` | Checks where a DOS Curse thief's seven extra skill points come from in the engines, and that a conversion no longer copies them into another title's record. |
| `test_cursetrainer.py` | Checks Curse's saving throws, hit dice, attacks, spell slot rows and level-up behaviour against the trainer read out of `GEN` and the shipped party. |
| `test_cursewarp.py` | Checks that `tools/curse_of_the_azure_bonds/cursewarp.py` sends its stuck-screen Escape only when the machine is idle in a key wait. |
| `test_cursewheel.py` | Checks that `tools/curse_of_the_azure_bonds/cursewheel.py` recognises DOS Curse's code-wheel prompt from frames built here and answers it. |
| `test_curtraitnames.py` | Checks that Curse's effect-code names come from Curse's own tables and differ from Pool of Radiance's where the data disagrees. |
