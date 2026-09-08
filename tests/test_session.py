"""The driver's own console, which must never be able to stop a drive.

`#380 (The session driver sometimes fails BEGIN ADVENTURING within 0.2s of the
picker loading, well inside its own 30s wait)` is a run that stopped on the
party-creation menu with the party loaded, the roster correct and the highlight
exactly where the game draws it. Nothing had been pressed. `Session.log` is
called from inside `select_row`, `attach` and `handle_prompt`, it was a bare
`print`, and a `print` to a pipe whose reader has exited raises
`BrokenPipeError` -- which comes out of `select_row` as a driver failure on
whatever screen the game happened to be showing.
"""

import pytest
from conftest import load_tools_module

session = load_tools_module("session")


class DeadPipe:
    def write(self, *a):
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self):
        raise BrokenPipeError(32, "Broken pipe")


@pytest.fixture
def talking_again():
    """Put the class-wide flag back, whatever the test does to it."""
    yield
    session.Session._talking = True


def test_a_console_that_has_gone_does_not_raise_into_the_driver(
        monkeypatch, talking_again):
    monkeypatch.setattr(session.sys, "stdout", DeadPipe())
    session.Session.log("  prompt -> SIDE3.D64")      # must not raise
    assert session.Session._talking is False


def test_nothing_is_said_after_the_console_has_gone(monkeypatch, talking_again):
    """Once is enough. A driver logs on every prompt and every menu step, and
    a thousand caught exceptions is a thousand round trips to a dead pipe."""
    said = []

    class Counting:
        def write(self, s):
            said.append(s)
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self):
            raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(session.sys, "stdout", Counting())
    for _ in range(5):
        session.Session.log("  answered the prompt with space")
    assert len(said) == 1, said


def test_a_live_console_still_hears_everything(monkeypatch, capsys,
                                               talking_again):
    session.Session.log("  attached SIDE0.D64")
    session.Session.log("  the confirm prompt came up 0.0s after the settle")
    out = capsys.readouterr().out
    assert "attached SIDE0.D64" in out
    assert "the confirm prompt came up" in out
