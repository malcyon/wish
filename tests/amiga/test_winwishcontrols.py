"""`winwish.py click --controls-after`: every control of a type, dumped in the click's own task."""

from __future__ import annotations

import base64
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tests.amiga.test_winwish import FakeRun, _ui_reply  # noqa: E402
from tools.amiga import winwish  # noqa: E402


def _inner(**kw):
    return winwish.ui_inner(r"C:\b", "click", ("Save", "Save As C64"), "MenuItem",
                            r"C:\o.txt", controls_after=r"C:\o.dump.txt", **kw)


def test_the_dump_is_taken_after_the_last_click_and_its_sleep_and_before_the_answer():
    inner = _inner()
    use = inner.index("Use-Control $hit[0]")
    sleep = inner.index("Start-Sleep -Milliseconds 400", use)
    assert sleep < inner.index("$dump = New-Object") < inner.index("$answer = @('ok')")
    assert "Move-Item -Force 'C:\\o.dump.txt.tmp' 'C:\\o.dump.txt'" in inner


def test_a_dump_line_carries_runtime_id_offscreen_and_rectangle_and_the_type_filter():
    inner = _inner()
    assert "GetRuntimeId()" in inner
    assert "IsOffscreen" in inner
    assert "BoundingRectangle" in inner
    assert "(Get-Kind $e) -ne $kind" in inner


def test_no_controls_after_means_no_dump():
    inner = winwish.ui_inner(r"C:\b", "click", ("File",), None, r"C:\o.txt")
    assert "$dump = New-Object" not in inner


@pytest.mark.parametrize("action", ["controls", "close"])
def test_controls_after_is_for_a_click_only(action):
    with pytest.raises(winwish.WinwishError, match="only a click"):
        winwish.ui_inner(r"C:\b", action, (), None, r"C:\o.txt", controls_after=r"C:\o.d")


def test_the_ssh_script_copies_the_dump_back_whole_only_when_asked():
    assert winwish.DUMP_BEGIN not in winwish.ui_script("abc", 30)
    script = winwish.ui_script("abc", 30, dump=True)
    assert script.index(winwish.UI_END) < script.index(winwish.DUMP_BEGIN)
    assert "ReadAllBytes('C:\\Users\\Public\\wish-ui-abc.dump.txt')" in script
    assert "wish-ui-abc.dump.txt" in script.split("} finally {")[1]


def test_a_long_dump_comes_back_uncut_and_is_written_to_the_file(tmp_path):
    rows = [f"MenuItem|Save As C64...||enabled=True||42.{i}|offscreen=False|0 0 10 10"
            for i in range(51)]
    body = "\n".join(rows) + "\n"
    assert len(body) > 200 * 10
    reply = _ui_reply("ok", "Save As C64... -> invoked") + "\n".join(
        ["", winwish.DUMP_BEGIN, base64.b64encode(body.encode(), altchars=None).decode(),
         winwish.DUMP_END])
    run = FakeRun([(lambda a: a[1] == "ps" and "wish-ui-" in a[2], 0, reply)])
    out = tmp_path / "sub" / "menu.txt"
    rc = winwish.main(["click", "--holder", "h", "Save", "--type", "MenuItem",
                       "--controls-after", str(out)], guest=winwish.Guest(run))
    assert rc == 0
    assert out.read_text() == body
    ps = next(c[2] for c in run.calls if c[1] == "ps" and "wish-ui-" in c[2])
    assert winwish.DUMP_BEGIN in ps


def test_a_reply_without_the_dump_is_an_error(tmp_path, capsys):
    run = FakeRun([(lambda a: a[1] == "ps" and "wish-ui-" in a[2], 0,
                    _ui_reply("ok", "Save -> invoked"))])
    rc = winwish.main(["click", "--holder", "h", "Save", "--controls-after",
                       str(tmp_path / "d.txt")], guest=winwish.Guest(run))
    assert rc == 1
    assert "controls dump" in capsys.readouterr().err
    assert not (tmp_path / "d.txt").exists()


def test_controls_after_and_expand_do_not_go_together(tmp_path):
    rc = winwish.main(["click", "--holder", "h", "Save", "--expand", "--controls-after",
                       str(tmp_path / "d.txt")], guest=winwish.Guest(FakeRun()))
    assert rc == 1


def _get_controls_body(inner: str) -> str:
    start = inner.index("function Get-Controls {")
    return inner[start:inner.index("function Get-Kind", start)]


def test_the_control_search_lists_one_runtime_id_once_and_keeps_an_element_without_one():
    body = _get_controls_body(_inner())
    assert "GetRuntimeId()" in body
    assert "$seen.ContainsKey($rid)" in body
    assert "catch { $rid = $null }" in body
    assert "if ($rid)" in body
    # The top-level window and every descendant go through the same dedupe.
    assert "[void]$found.Add($top)" not in body
    assert body.count("[void]$found.Add($e)") == 1
    assert "& $keep $top" in body
    assert "& $keep $e" in body


def test_two_runtime_ids_with_one_name_are_still_ambiguous():
    inner = _inner()
    assert "$hit.Count -gt 1" in inner
    assert "controls match" in inner


def test_controls_and_the_dump_print_the_same_fields_per_line():
    controls = winwish.ui_inner(r"C:\b", "controls", (), None, r"C:\o.txt")
    branch = controls[controls.index("-eq 'controls'"):]
    branch = branch[:branch.index("} else {")]
    for field in ("GetRuntimeId()", "IsOffscreen", "BoundingRectangle"):
        assert field not in branch
    assert "Get-Detail $e" in branch
    assert "Get-Detail $e" in _inner()
    function = _get_detail_body(controls)
    for field in ("GetRuntimeId()", "IsOffscreen", "BoundingRectangle"):
        assert field in function


def _get_detail_body(script):
    start = script.index("function Get-Detail")
    return script[start:script.index("\n  }", start)]


def test_each_detail_read_has_its_own_try_catch_and_an_empty_field_on_failure():
    function = _get_detail_body(_inner())
    for read in ("$e.GetRuntimeId()", "$e.Current.IsOffscreen", "$e.Current.BoundingRectangle"):
        guarded = [ln for ln in function.splitlines() if read in ln]
        assert len(guarded) == 1, read
        line = guarded[0].strip()
        assert line.startswith("try {") and "} catch {" in line, read
        assert line.endswith("= '' }"), read


# -- click --automation-id ... --pick: choose an item from a combo box's popup ------------

def _pick(**kw):
    return winwish.ui_inner(r"C:\b", "click", ("ft_combo",), None, r"C:\o.txt",
                            automation_id="ft_combo", pick="Tilverton streets", **kw)


def test_pick_opens_the_combo_selects_the_item_and_collapses_it_in_one_script():
    inner = _pick()
    body = inner[inner.index("function Pick-Item"):inner.index("$names.Count -eq 0")]
    assert inner.count("function Pick-Item") == 1
    assert "$item = 'Tilverton streets'" in inner
    expand = body.index("ExpandCollapsePattern]::Pattern")
    find = body.index("-eq 'ListItem' -and $_.Current.Name -eq $item")
    select = body.index("SelectionItemPattern]::Pattern")
    assert expand < body.index(".Expand()") < find < select < body.index(".Select()")
    assert "InvokePattern" in body and body.index("$p.Invoke()") > select
    assert body.index(".Collapse()") > body.index(".Select()")
    # The popup's items are gone once the task ends, so the combo is addressed by id here.
    assert "$_.Current.AutomationId -eq $name" in inner
    assert "Pick-Item $hit[0]" in inner and "Use-Control $hit[0]" not in inner


def test_pick_snapshots_the_list_items_before_expand_and_matches_only_new_ones():
    inner = _pick()
    body = inner[inner.index("function Pick-Item"):inner.index("$names.Count -eq 0")]
    snapshot = body.index("$before[")
    assert snapshot < body.index(".Expand()") < body.index("-not $before.ContainsKey(")
    assert "GetRuntimeId()" in body[snapshot:body.index(".Expand()")]
    assert "-eq 'ListItem' -and $_.Current.Name -eq $item -and -not $before.ContainsKey" in body


def test_pick_wait_counts_the_tree_walk_and_stays_inside_the_task_budget():
    inner = _pick()
    body = inner[inner.index("function Pick-Item"):inner.index("$names.Count -eq 0")]
    assert "Stopwatch" in body and f"TotalSeconds -gt {winwish.UI_WAIT}" in body
    assert 2 * winwish.UI_WAIT < winwish.ui_timeout(0, "click")


@pytest.mark.parametrize("extra", [{"shot_after": "x.png"}, {"controls_after": "x.txt"}])
def test_ui_inner_pick_rejects_shot_and_controls_after(extra):
    with pytest.raises(winwish.WinwishError, match="--pick"):
        winwish.ui_inner(r"C:\b", "click", ("ft_combo",), None, r"C:\o.txt",
                         automation_id="ft_combo", pick="a", **extra)


def test_pick_sends_nothing_to_the_desktop_and_keeps_the_runtime_id_dedupe():
    inner = _pick()
    for banned in ("SetForegroundWindow", "SetFocus", "SendKeys", "mouse_event", "SendInput",
                   "SetCursorPos", "CopyFromScreen"):
        assert banned not in inner
    assert "$seen.ContainsKey($rid)" in inner


def test_pick_needs_a_click_by_automation_id_and_no_expand():
    def build(action="click", names=("ft_combo",), **kw):
        return winwish.ui_inner(r"C:\b", action, names, None, r"C:\o.txt", pick="a", **kw)

    for call in (lambda: build(names=("x",)),
                 lambda: build(automation_id="ft_combo", expand=True),
                 lambda: build("controls", automation_id="ft_combo")):
        with pytest.raises(winwish.WinwishError, match="--pick"):
            call()


def test_the_cli_pick_sends_one_script_and_prints_its_answer(capsys):
    run = FakeRun([(lambda a: a[1] == "ps", 0, _ui_reply("ok", "ft_combo -> selected Tilverton streets"))])
    argv = ["click", "--holder", "h", "--automation-id", "ft_combo", "--pick", "Tilverton streets"]
    assert winwish.main(argv, winwish.Guest(run)) == 0
    assert "selected Tilverton streets" in capsys.readouterr().out
    assert len([c for c in run.calls if c[1] == "put"]) == 1


@pytest.mark.parametrize("extra", [["--expand"], ["--shot-after", "x.png"], ["--controls-after", "x.txt"]])
def test_the_cli_pick_does_not_mix_with_the_other_click_forms(extra, capsys):
    run = FakeRun()
    argv = ["click", "--holder", "h", "--automation-id", "ft_combo", "--pick", "a", *extra]
    assert winwish.main(argv, winwish.Guest(run)) == 1
    assert run.calls == [] and "--pick" in capsys.readouterr().err
