# editor

The character editor GUI. Opens a `.D64` and writes it back; imports nothing
from `automap/`, so it works with no emulator installed anywhere —
`tests/test_wish.py::test_editor_imports_nothing_live` greps every file here to
keep that true.

The character sheet's own form moved into `wish/window.ui`, the single
unified layout — see `docs/146-unified-ui.md`. There is no standalone
`python -m editor` any more; this package is the sheet's logic and dialogs,
opened from `wish/window.py`.

| file | purpose |
|---|---|
| `__init__.py` | Empty. |
| `binding.py` | Which widget edits which record field, and which fields must not be edited. Widgets bind by `objectName` (`field_strength` edits the `strength` entry in `goldbox/layout.py`), and read-only is *computed* from three sources the project already maintains — the game recomputes it, we do not understand it, or the write would be silently dropped — so the list cannot go stale. |
| `changes.py` | What a save would write, phrased exactly as `wish --dry-run` prints it. Compares against the bytes as read rather than against a dirty flag, so a value typed and typed back counts as no change. |
| `dosimport.py` | **Off unless `WISH_EXPERIMENTAL_DOS_IMPORT=1`** — the menu entry is not built otherwise, because this direction still drops the portrait and the clock. The window over `goldbox/dos.py`: turning a DOS save into a C64 one with the losses named first. **No template** (#118) — the `.d64` is built from nothing, so the window asks for a DOS folder, a slot and where to put the result, and the import refuses outright when the player's game disks cannot be found rather than inventing the bytes only they can supply. The conversion is rehearsed in memory and what it cannot carry is on screen before there is a button to press; the bottom row names the `.d64` Convert will write, so Convert converts and there is no Save As after it. |
| `dosimport.ui` | The Qt Designer form for the DOS import dialog. Compiled to `ui_dosimport.py` by `tools/genui.py`. |
| `effects.py` | The ten trait slots at `0x0AD` spelled out on the character sheet, coloured by confidence and named the way the open title names them. The codes themselves stay in `goldbox/traits.py` so the sheet and the combat tooltip cannot become two tables. Shown, not edited. |
| `enums.py` | Fields whose numbers have names, taken from `goldbox/yaml_io.py` so the CLI and the GUI cannot drift. Race and class are *functions* of the title, not constants, because the lists differ between the six games. |
| `exports.py` | **Off unless `WISH_EXPERIMENTAL_EXPORT=1`** -- the Export submenu is not built otherwise, because every string in the file is an unapproved placeholder. The windows over `goldbox.dos.write_dos_save` and `goldbox.amiga.export_party`: a C64 party written out to a DOS save directory or to Amiga `.pc` files. An export has no backup behind it -- it writes into a folder the editor does not own -- so the guarantee is the other one: the conversion is rehearsed into a scratch directory, and the pane names every file the write would replace and every one it would remove (#68) before the button exists to press. |
| `exports.ui` | The Qt Designer form for the export dialog. Compiled to `ui_exports.py` by `tools/genui.py`. |
| `files.py` | Opening and saving, and not losing anybody's save disk. The editor writes back over the file you opened, which is only defensible because the write is atomic (temp file, fsync, rename) and a timestamped backup is taken every time into a folder that is named rather than guessed. |
| `iconwidget.py` | The combat-icon editor, promoted onto the form as class `IconEditor`. Draws the genuine article — two stacked 3x3 poses of `CHARPIC00` glyphs in multicolour text mode — and offers the sixteen C64 colours and nothing else, because a general colour dialog would offer colours the machine cannot show. |
| `inventory.py` | The sixteen item slots one character carries, with names spelled out. Items live in `SAVEDGAME0`, not in the record, so a `.chr` export has none. Adding an item means copying one of the 163 real templates off the game disks, never filling in fields, so the bytes we do not understand keep sane values. |
| `inventory.ui` | The Qt Designer form for the "Add an item" dialog. Compiled to `ui_inventory.py` by `tools/genui.py`. |
| `palette.py` | The sixteen colours a C64 has, and no others. |
| `partspicker.py` | Pick an icon the way the game's own ICON menu does — a weapon and a head — with each option rendered as the icon you would end up with, so you choose a result rather than a number. Replaces a per-cell glyph picker that could build a figure with two heads and no legs. |
| `partspicker.ui` | The Qt Designer form for the icon parts picker. Compiled to `ui_partspicker.py` by `tools/genui.py`. |
| `roster.py` | The party list, and the three kinds of file it can come from. Shows name, armour class and current hit points — exactly what the game's own party list prints, established by disassembling all 64 call sites into its string printer. Which title a disk is stays a `Party.game`; no filename is spelled out here. |
| `rosterview.py` | The party list's widget, promoted onto the form as class `RosterView`. The one thing in the header that gives width up: above its floor it is exactly its five columns at their contents, below it `Name` absorbs the shortfall and elides, and only when `Name` has nothing left does the table scroll. The floor is a constant and not a font metric, because the header does not scroll and so the roster's minimum is a floor under the whole window -- which is what used to make that floor follow the UI font (#71, #41). |
| `spellwidget.py` | Spells by name: the spellbook a character knows (`0x078`) and what is memorised (`0x020`), two shapes behind one three-method interface so the window handles them generically. Neither consistency rule is enforced — the capacity is shown beside the list and an unknown spell is coloured, and the edit goes through either way. |
| `ui_dosimport.py` | **Generated** from `dosimport.ui` by `tools/genui.py` (which is `pyuic6`). Never edit it; `--check` fails CI if it is out of step with the `.ui`. |
| `ui_exports.py` | **Generated** from `exports.ui`, the same way. |
| `ui_inventory.py` | **Generated** from `inventory.ui`, the same way. |
| `ui_partspicker.py` | **Generated** from `partspicker.ui`, the same way. |
| `window.py` | Binds the character sheet's widgets — now part of `wish/window.ui` — to `goldbox/layout.py` fields. Finds them by `objectName`, so the form can be rearranged, regrouped or relabelled in Qt Designer without a line of this file changing. `EditorBinding` and `RowSplitter` are what `wish/window.py` imports from it. |
