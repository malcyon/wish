"""`tools/dos/dosparty.Driver.type` sends each character of a name as the X
keysym the DOSBox window needs, punctuation included."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.dos import dosparty  # noqa: E402


class _Session:
    def __init__(self):
        self.keys = []

    def key(self, key):
        self.keys.append(key)

    def settle(self, **_kwargs):
        pass

    def shot(self, *_args, **_kwargs):
        pass

    def capture(self):
        class _Screen:
            @staticmethod
            def digest():
                return "d"
        return _Screen()


def _typed(text, monkeypatch, tmp_path):
    monkeypatch.setattr(dosparty.time, "sleep", lambda _s: None)
    session = _Session()
    dosparty.Driver(session, tmp_path).type(text, "name")
    return session.keys


def test_punctuation_is_sent_as_its_keysym(monkeypatch, tmp_path):
    assert _typed("A.B", monkeypatch, tmp_path) == ["A", "period", "B"]
    assert _typed(". * , ? / : ;", monkeypatch, tmp_path) == [
        "period", "space", "asterisk", "space", "comma", "space", "question",
        "space", "slash", "space", "colon", "space", "semicolon"]
    assert _typed("[\\]^_`", monkeypatch, tmp_path) == [
        "bracketleft", "backslash", "bracketright", "asciicircum",
        "underscore", "grave"]


def test_letters_and_spaces_type_as_before(monkeypatch, tmp_path):
    assert _typed("wren a1", monkeypatch, tmp_path) == [
        "w", "r", "e", "n", "space", "a", "1"]
