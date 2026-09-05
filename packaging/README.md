# packaging

What `wish.spec` and a release build reach for, beyond the source tree itself.

| file | purpose |
|---|---|
| `wish_main.py` | PyInstaller's entry script -- a plain script `Analysis` can start from, since the relative imports in `wish/__main__.py` only work inside the package. Repairs Windows' console stream for the `wish export`/`wish import` subcommands. |
| `geniconset.py` | Renders `assets/logo/mark.svg` into `assets/wish.icns`, the same way `tools/genicons.py` renders the `.ico` and the Linux hicolor tree -- every size straight off the vector, never a scaled copy of another size. `--check` fails if the committed file has drifted from the drawing. No macOS build reads it yet; `wish.spec` has no `BUNDLE` step, so this is committed and waiting for the day one exists -- `docs/132-logo.md`. |

Neither file is a package member in the Python sense -- there is no
`__init__.py`, and PyInstaller reads `wish_main.py` as a file path rather than
importing it. `tests/test_packaging.py` and `tests/test_geniconset.py` both
load their target by file path for the same reason: `import packaging.x`
resolves to the unrelated PyPI package of that name.
