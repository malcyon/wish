"""The application: one window over the file editor and the live map.

`editor/` and `automap/` are libraries of widgets; this package owns the window,
the single live connection and the choice of backend. The direction of the
imports is the point -- `wish` may import both, `editor` imports neither, and
`goldbox/` stays transport-free. That is the project's first decision, in
`docs/README.md`: the character editor is a file tool and never talks to a
running machine.
"""


def _find_version() -> str:
    """The version, from the build, the installed metadata, or neither.

    `_version.py` is written by hatch-vcs at build time and is what a frozen
    build reads; a plain `pip install` has only the metadata; a source checkout
    that was never built has neither and says so rather than inventing a
    number.
    """
    try:
        from ._version import __version__ as v
        return v
    except ImportError:
        pass
    from importlib.metadata import PackageNotFoundError, version
    try:
        # The distribution, not the command: `wish` was taken on PyPI, so the
        # name here is `wish-goldbox` and must track `pyproject.toml`. It has
        # been wrong twice; `tests/test_packaging.py` now checks it.
        return version("wish-goldbox")
    except PackageNotFoundError:
        return "0.0.0+unknown"


__version__ = _find_version()
