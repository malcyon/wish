# ui

Shared widget-level helpers both GUIs use: the app icon, icon painting, the
Font Awesome set. Neither `editor/` nor `automap/` owns them — icon drawing is
pure geometry and belongs to both, so it lives here rather than forcing the
editor to import from a package named after the emulator.

| file | purpose |
|---|---|
| `__init__.py` | The package docstring recording that rule, and why it exists: `tests/test_wish.py::test_editor_imports_nothing_live` greps every file in `editor/` for the word `automap`, so shared drawing code cannot live there. |
| `appicon.py` | The application's own icon — Font Awesome's `hat-wizard` on a filled tile — drawn from the same path data, so the taskbar icon, the About picture and the `.ico` PyInstaller embeds cannot drift apart. The tile is there because a bare silhouette on transparency vanishes on half of all taskbars, and the hat is painted light rather than cut out so it has a ground on both sides of every edge. |
| `iconpaint.py` | Turns `ui/icons.py` path data into a cached `QPainterPath` Qt can paint. Kept apart from the table so that stays importable with no display, and apart from the widgets so the map and the roster draw the same glyph the same way. Uses **winding** fill, not Qt's odd-even default, or `location-dot`'s counter and `hood`'s face come out as solid blobs. |
| `icons.py` | The small vector icons the program draws, as SVG path data with no Qt in the file. Paths rather than a bundled font because the map draws with `QPainter` and not `QIcon`, because a path scales into whatever box it is given, because `render.py`'s `to_svg` then gets the notes for free, and because it costs 12 KB of source rather than a 405 KB binary the packaging has to know about. |
