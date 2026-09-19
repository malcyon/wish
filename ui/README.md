# ui

Shared widget-level helpers both GUIs use — the app icon, icon painting and the icons the program draws — kept here because icon drawing is pure geometry and `editor/` may not import from a package named after the emulator.

| file | purpose |
|---|---|
| `__init__.py` | The package docstring recording that rule: `tests/test_wish.py::test_editor_imports_nothing_live` greps every file in `editor/` for the word `automap`, so shared drawing code cannot live there. |
| `appicon.py` | The application's own icon — game-icons.net's `pointy-hat` (Lorc) on a filled tile — drawn from the same path data as everything else, so the taskbar icon, the About picture and the `.ico` PyInstaller embeds cannot drift apart; the tile exists because a bare silhouette on transparency vanishes on half of all taskbars, and the hat is painted light rather than cut out so it has a ground on both sides of every edge. |
| `iconpaint.py` | Turns `ui/icons.py` path data into a cached `QPainterPath` Qt can paint, kept apart from the table so that stays importable with no display and apart from the widgets so the map and the roster draw the same glyph the same way; it uses winding fill, not Qt's odd-even default, or `position-marker`'s counter and `hood`'s face come out as solid blobs. |
| `icons.py` | The small vector icons the program draws, as SVG path data with no Qt in the file (paths rather than a bundled font, because the map draws with `QPainter` and not `QIcon`, a path scales into any box, and `render.py`'s `to_svg` then gets the notes for free), plus the parser that reads it and `ARTISTS`, which records who drew each game-icons.net glyph so an attribution file can be generated from what ships; game-icons.net's glyphs are on a 512 canvas and Font Awesome's on a 640 one, kept verbatim rather than rescaled so a committed path can be diffed against the artist's file, and `box(name)` makes them come out the same size beside each other. |
