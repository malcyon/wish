# editor

Tests for the character editor in `editor/`, its binding and window, and how it behaves for each title.

| file | purpose |
|---|---|
| `test_dualclasscombo.py` | Checks that the editor's Class combo and a conversion agree on the class of a dual-classed Curse character. |
| `test_editor.py` | Checks the editor's file handling, binding and window headless: read-only fields, editing and writing back, items, effects, icons and the roster. |
| `test_pertitle_ui.py` | Checks that the editor's race, item and caster tables follow the open title, that its map and tools glob the title asked for, and that a synthetic party exists for every title. |
