# editor

Tests for the character editor in `editor/`, its binding and window, and how it behaves for each title.

| file | purpose |
|---|---|
| `test_dualclasscombo.py` | Checks that the editor's Class combo and a conversion agree on the class of a dual-classed Curse character. |
| `test_editor.py` | Checks the editor's file handling, binding and window headless: read-only fields, editing and writing back, items, effects, icons and the roster. |
| `test_saveplan.py` | Checks that an unsaved DOS, Amiga or C64 edit reaches a conversion through `editor/saveplan.py`'s snapshot, that preparing one writes no file and moves no baseline, that a party with nothing edited snapshots the saved game it was read from, and that only the open slot's own folder, disk or `SAVGAM` file is answered from the snapshot. |
| `test_savepublish.py` | Checks that a Save As prepares a native copy or a conversion in memory, refuses one whose accounting names a dropped field and one whose output comes back holding a name or a value the sheet does not, refuses a destination named wrongly or standing in the save or the game data it reads, publishes it at a chosen image filename or into a new save folder with a backup of anything it replaced, and puts the destination back when publication or adoption fails. |
| `test_pertitle_ui.py` | Checks that the editor's race, item and caster tables follow the open title, that its map and tools glob the title asked for, and that a synthetic party exists for every title. |
