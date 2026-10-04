"""Fakes shared by the Amiga tests, imported by name because a second `conftest` module collides with the suite's."""

from __future__ import annotations

import types

from tools.amiga.winuaesession import WinGuest


class WinuaeLaneNames:
    """The `WinGuest` calls `run_recon` makes that touch no lane: where a disk lives, and the silence proof."""

    remote_path = staticmethod(WinGuest.remote_path)
    silence = staticmethod(WinGuest.silence)


def fake_savecount_builder():
    """Build a fake private `savecount.py` under `directory/ssb/analysis`.

    `fail` makes `with_count` raise `SaveCountError`; `sibling` makes the module
    import a second module from the same directory, as a real helper might.
    """
    def build(directory, *, fail=False, sibling=False):
        analysis = directory / "ssb" / "analysis"
        analysis.mkdir(parents=True)
        head = ""
        if sibling:
            (analysis / "savecount_sibling.py").write_text("SUFFIX = b'|count='\n")
            head = "import savecount_sibling\n"
        suffix = "savecount_sibling.SUFFIX" if sibling else "b'|count='"
        (analysis / "savecount.py").write_text(
            head + "class SaveCountError(ValueError):\n    pass\n\n"
            "def with_count(slot, n):\n"
            f"    if {fail!r}:\n        raise SaveCountError('private-detail')\n"
            f"    return slot + {suffix} + str(n).encode()\n")
    return build


fake_savecount = fake_savecount_builder()



class FakeGameMemory:
    """A stand-in for `AmigaTarget`: `locate` (counted, or raising `error`), `read` and `write`."""

    BASE = 0x40000

    def __init__(self, error=None):
        self.error, self.locates = error, 0

    def locate(self):
        self.locates += 1
        if self.error:
            raise self.error
        return self.BASE

    def read(self, addr, length):
        return bytes(length)

    def write(self, addr, data):
        pass


def fake_stage_helper(memory, log, *, fail_at=None, message="blocked by the helper",
                      raises=None):
    """A fake private helper: `stage_live` records its arguments and appends to `log`.

    `fail_at` is the call number that raises the helper's own error, `helper.SaveCountError`,
    with `message`; `raises` is another exception raised on the first call.
    """
    class SaveCountError(ValueError):
        pass

    def stage_live(read_memory, write_memory, a4):
        helper.calls.append((read_memory, write_memory, a4))
        log.append("stage")
        if raises is not None:
            raise raises
        if fail_at == len(helper.calls):
            raise SaveCountError(message)
        helper.armed = True

    helper = types.SimpleNamespace(stage_live=stage_live, SaveCountError=SaveCountError,
                                   calls=[], armed=True)
    return helper
