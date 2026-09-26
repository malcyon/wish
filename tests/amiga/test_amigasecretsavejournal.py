"""What the driver reports when the journal answerer's subprocess fails."""

from __future__ import annotations

import sys

import pytest

from tools.amiga import amigasecretsave as drive


def _run(tmp_path, body):
    script = tmp_path / "fake_answerer.py"
    script.write_text(body)
    return drive.run_journal_answer(sys.executable, "h", tmp_path / "a", 60, script=script)


def _failure(tmp_path, body) -> str:
    with pytest.raises(drive.RouteError) as info:
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
