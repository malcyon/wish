"""A paladin's sheet that never opened is a failed step, not a `False` answer.

`#699`: two live runs of `curedrive.py run --who MARK --script "read;sheet"`
failed to open MARK's individual sheet (a stale `bank_ids` cache made the
underlying screen unreadable, `tests/c64/test_screenbank.py`'s
`test_a_transport_failure_asking_for_the_banks_is_not_remembered`), yet both
runs still logged `{"event": "sheet", "cure_offered": false}` and exited 0.
`Run.open_sheet` already refuses a screen that is not the sheet and returns
`None` -- what was missing is that `Run.sheet` and `Run.cure` took that `None`
as a negative answer instead of a failure.  Nothing here needs an emulator.
"""

import io

from conftest import load_tools_module

CD = load_tools_module("curedrive")


def _bare_run(who: str = "MARK") -> "CD.Run":
    run = CD.Run.__new__(CD.Run)
    run.log_file = io.StringIO()
    run.who = who
    run.n = 0
    run.out = None
    return run


def _events(run: "CD.Run") -> list[dict]:
    import json
    return [json.loads(line) for line in run.log_file.getvalue().splitlines()]


def test_a_sheet_that_never_opened_raises_and_logs_no_cure_offered():
    run = _bare_run()
    run.open_sheet = lambda: None
    run.shot = lambda tag: tag
    run.close_sheet = lambda: None
    run.row24 = lambda: ""

    try:
        run.sheet()
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    events = _events(run)
    assert all("cure_offered" not in e for e in events)
    assert any(e["event"] == "sheet-not-opened" for e in events)


def test_cure_on_a_sheet_that_never_opened_raises_and_logs_no_verdict():
    run = _bare_run()
    run.open_sheet = lambda: None
    run.shot = lambda tag: tag
    run.close_sheet = lambda: None
    run.row24 = lambda: ""

    try:
        run.cure()
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    events = _events(run)
    assert not any(e["event"] == "cure-not-offered" for e in events)
    assert any(e["event"] == "sheet-not-opened" for e in events)


def test_cure_on_a_genuinely_opened_sheet_without_cure_still_logs_not_offered():
    run = _bare_run()
    run.open_sheet = lambda: "VIEW:ITEMS EXIT"
    run.shot = lambda tag: tag
    run.close_sheet = lambda: None
    run.row24 = lambda: ""

    result = run.cure()

    assert result == {"cured": False, "bar": "VIEW:ITEMS EXIT"}
    events = _events(run)
    assert any(e["event"] == "cure-not-offered" for e in events)
    assert not any(e["event"] == "sheet-not-opened" for e in events)
