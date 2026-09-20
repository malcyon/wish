"""Helpers `test_packaging` shares with the test files that reuse them."""
from __future__ import annotations

import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = ROOT / "wish.spec"


class _Fake:
    """Whatever PyInstaller would have built, recorded rather than built."""

    def __init__(self, kind, args, kwargs):
        self.kind, self.args, self.kwargs = kind, args, kwargs
        self.name = kwargs.get("name")
        # COLLECT reads these off the EXEs it is given.
        self.contents_directory = "_internal"
        self.dependencies = []
        self.toc = []
        self.append_pkg = True
        # Analysis exposes these; a list is TOC-like enough for the spec.
        self.pure = []
        self.scripts = []
        self.binaries = []
        self.datas = []


def _run_spec(platform: str) -> dict[str, list[_Fake]]:
    """Execute wish.spec as PyInstaller would, on the platform named."""
    built: dict[str, list[_Fake]] = {}

    def maker(kind):
        def make(*args, **kwargs):
            built.setdefault(kind, []).append(_Fake(kind, args, kwargs))
            return built[kind][-1]
        return make

    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_submodules = lambda name: [name]
    saved = {k: sys.modules.get(k) for k in
             ("PyInstaller", "PyInstaller.utils", "PyInstaller.utils.hooks")}
    sys.modules.setdefault("PyInstaller", types.ModuleType("PyInstaller"))
    sys.modules.setdefault("PyInstaller.utils", types.ModuleType("PyInstaller.utils"))
    sys.modules["PyInstaller.utils.hooks"] = hooks

    real_platform = sys.platform
    try:
        sys.platform = platform
        env = {name: maker(name)
               for name in ("Analysis", "EXE", "PYZ", "COLLECT", "MERGE")}
        exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), env)
    finally:
        sys.platform = real_platform
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return built
