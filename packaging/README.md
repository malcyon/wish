# packaging

What `wish.spec` and a release build reach for, beyond the source tree itself.

| file | purpose |
|---|---|
| `wish_main.py` | PyInstaller's entry script — a simple script `Analysis` can start from, since the relative imports in `wish/__main__.py` only work inside the package — that repairs Windows' console stream for the `wish export`/`wish import` subcommands. |
| `geniconset.py` | Makes `assets/wish.icns` from the artist's files under `assets/logo/`, as `tools/generate/genicons.py` makes the `.ico` and the Linux hicolor tree — every size from his smallest PNG no smaller than it, the SVG only at 512 and 1024, never a scaled copy of another size of ours — with `--check` failing if the committed file has drifted from the drawing (`docs/132-logo.md`). |

Neither file is a package member (there is no `__init__.py`, and PyInstaller reads `wish_main.py` as a file path), so `tests/wish/test_packaging.py` and `tests/generate/test_geniconset.py` load their target by file path, because `import packaging.x` resolves to the unrelated PyPI package of that name.
