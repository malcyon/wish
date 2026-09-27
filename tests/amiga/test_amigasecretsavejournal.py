"""What the driver reports when the journal answerer's subprocess fails."""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from tests.amiga import test_amigasecretsaveaccept as accept
from tools.amiga import route_silver_blades, winuaesession

clock = accept.clock
readings = accept.readings


def _run(tmp_path, body):
    script = tmp_path / "fake_answerer.py"
    script.write_text(body)
    return route_silver_blades.run_journal_answer(sys.executable, "h", tmp_path / "a", 60, script=script)


def _failure(tmp_path, body) -> str:
    with pytest.raises(winuaesession.RouteError) as info:
        _run(tmp_path, body)
    return str(info.value)


def test_a_failing_answerer_puts_its_last_stderr_lines_and_exit_code_in_the_error(tmp_path):
    message = _failure(
        tmp_path,
        "import sys\nsys.stderr.write('Traceback\\nMissingTableError: no such table\\n')\n"
        "raise SystemExit(3)\n")
    assert "ended 3" in message and "MissingTableError: no such table" in message


def test_a_clean_answerer_is_unchanged(tmp_path):
    assert _run(tmp_path, "print('answered')\n") == (0, "answered")


def test_the_no_challenge_exit_still_returns_for_the_retry_loop(tmp_path):
    assert _run(tmp_path, "print('no challenge on screen')\nraise SystemExit(1)\n") == (
        1, "no challenge on screen")


def test_many_and_long_stderr_lines_stay_inside_the_bound(tmp_path):
    message = _failure(
        tmp_path,
        "import sys\nfor i in range(50): sys.stderr.write(f'line{i} ' + 'x' * 5000 + '\\n')\n"
        "raise SystemExit(2)\n")
    assert "line49 " in message and "line44 " not in message and "line45 " in message
    assert len(message) < 1500 and "x" * 251 not in message


def test_stderr_that_is_not_utf8_does_not_raise(tmp_path):
    message = _failure(
        tmp_path,
        "import sys\nsys.stderr.buffer.write(b'bad \\xff\\xfe byte\\n')\nraise SystemExit(4)\n")
    assert "ended 4" in message and "byte" in message


def test_blank_stderr_adds_no_suffix():
    assert route_silver_blades._stderr_tail("\n  \n") == ""


def test_blank_lines_between_real_lines_are_dropped_before_the_last_five_are_kept():
    text = "".join(f"\n  \nreal{i}\n" for i in range(8))
    tail = route_silver_blades._stderr_tail(text)
    assert tail == "; stderr: " + " | ".join(f"real{i}" for i in range(3, 8))


def test_a_huge_last_stdout_line_stays_inside_the_bound(tmp_path):
    message = _failure(
        tmp_path,
        "import sys\nprint('y' * 100000)\nsys.stderr.write('e' * 5000 + '\\n')\n"
        "raise SystemExit(2)\n")
    bound = (len("the journal answerer ended 2: ''") + route_silver_blades.STDERR_LINE_CHARS
             + len("; stderr: ") + route_silver_blades.STDERR_LINE_CHARS)
    assert len(message) <= bound and len(message) < 1500


def test_run_answer_records_a_failed_answer_and_the_error_reaches_the_summary(
        tmp_path, clock, readings):
    script = tmp_path / "fake_answerer.py"
    script.write_text("import sys\nsys.stderr.write('MissingTable: gone\\n')\nraise SystemExit(5)\n")

    def answer(holder, adf, timeout):
        return route_silver_blades.run_journal_answer(sys.executable, holder, adf, timeout, script=script)

    _, result = accept._accept(tmp_path, clock, answer=answer)
    failed = [e for e in result["events"] if "answer_failed" in e]
    assert len(failed) == 1 and "MissingTable: gone" in failed[0]["answer_failed"]
    assert "ended 5" in result["error"] and "MissingTable: gone" in result["error"]
    recorded = [e for e in accept._events(tmp_path) if e.get("event") == "answer"]
    assert "MissingTable: gone" in recorded[-1]["error"]


def test_the_silver_blades_route_imports_without_the_generic_runners():
    program = (
        "import sys; import tools.amiga.route_silver_blades; "
        "sys.exit(int(any(name in sys.modules for name in ("
        "'tools.amiga.amigasecretsave', 'tools.amiga.amigafoundation', "
        "'tools.amiga.screens'))))")
    done = subprocess.run([sys.executable, "-c", program],
                          cwd=pathlib.Path(__file__).resolve().parents[2])
    assert done.returncode == 0
