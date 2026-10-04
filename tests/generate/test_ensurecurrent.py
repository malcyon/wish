from __future__ import annotations

import os

from tools.generate import genui

BODY = "class Ui:\n    pass\n"


def _pair(tmp_path, header):
    ui = tmp_path / "form.ui"
    py = tmp_path / "ui_form.py"
    ui.write_text("<ui/>", encoding="utf-8")
    py.write_text(f"# {header}\n\n{BODY}", encoding="utf-8")
    os.utime(py, (1000, 1000))
    os.utime(ui, (2000, 2000))
    return ui, py


def _count(monkeypatch, output):
    calls = []

    def fake(ui):
        calls.append(ui)
        return output

    monkeypatch.setattr(genui, "compile_ui", fake)
    return calls


def test_a_header_only_difference_is_not_written(tmp_path, monkeypatch):
    ui, py = _pair(tmp_path, "old header")
    before = py.read_bytes()
    calls = _count(monkeypatch, f"# other machine\n\n{BODY}")

    assert genui.ensure_current(ui, py) == []
    assert py.read_bytes() == before
    assert genui.ensure_current(ui, py) == []
    assert len(calls) == 1


def test_a_widget_difference_is_written_and_named(tmp_path, monkeypatch):
    ui, py = _pair(tmp_path, "old header")
    new = "# h\n\nclass Ui:\n    x = 1\n"
    _count(monkeypatch, new)

    assert genui.ensure_current(ui, py) == [ui]
    assert py.read_text(encoding="utf-8") == new


def test_startup_names_the_rewritten_form(tmp_path, monkeypatch, capsys):
    import wish.window
    from wish.__main__ import main

    ui = tmp_path / "window.ui"
    monkeypatch.setattr(genui, "ensure_current", lambda: [ui])
    monkeypatch.setattr(wish.window, "run", lambda *a, **k: 0)
    assert main(["--disks", str(tmp_path)]) == 0
    assert "window.ui changed; recompiled the form" in capsys.readouterr().out


def test_startup_is_silent_when_nothing_was_rewritten(tmp_path, monkeypatch, capsys):
    import wish.window
    from wish.__main__ import main

    monkeypatch.setattr(genui, "ensure_current", lambda: [])
    monkeypatch.setattr(wish.window, "run", lambda *a, **k: 0)
    assert main(["--disks", str(tmp_path)]) == 0
    assert "recompiled" not in capsys.readouterr().out
