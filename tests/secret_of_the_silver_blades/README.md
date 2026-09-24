# secret_of_the_silver_blades

Tests for Secret of the Silver Blades: its C64 disks, saves, tables and level-up rules, and the tools under `tools/secret_of_the_silver_blades/`.

| file | purpose |
|---|---|
| `test_silverblades.py` | Checks the Silver Blades sides, maps, spell tables, items, icons and spellbook layout, and the trainer's grant routines, against the player's disks and shipped party. |
| `test_ssbdossaves.py` | Checks that a C64 party converted to DOS gets the saving throws DOS Silver Blades' own load-time rebuild leaves, against the rule, the table in `START.EXE`, every engine-written record and the engine's own resave. |
| `test_ssbeditorpath.py` | Checks that the editor opens, edits and writes back a Silver Blades save the game wrote, and that a party will not cross into the wrong title's disk. |
| `test_ssblevels.py` | Checks Silver Blades' ceilings, experience bar, THAC0 and racial rows, and that the six shipped saves reproduce without disks. |
| `test_ssblive.py` | Checks the maps and walked route a live Silver Blades session recorded, and how an import rewrites the race byte and where the shipped casters' spellbooks end. |
| `test_ssbtrainer.py` | Checks that one press of Silver Blades' trainer reproduces through the level-up plan, including its spell menu and wisdom gate. |
| `test_ssbtrainerinputs.py` | Checks the three trainer inputs `tools/secret_of_the_silver_blades/ssbtrainerinputs.py` reads off the disks against Curse's copies and the game's own records. |
| `test_ssbtrainpress.py` | Checks that a staged training press writes the party list's own current hit points beside the record page, so a save taken between presses cannot hold more hit points than the record's maximum. |
| `test_ssbtraitnames.py` | Checks the Silver Blades effect-code table and the trait names the picker offers for it. |
| `test_ssbwarp.py` | Checks that `tools/secret_of_the_silver_blades/ssbwarp.py` does not send Escape while a load is still running. |
