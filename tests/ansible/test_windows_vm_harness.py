"""Checks the Windows guest harness replacement call."""

from pathlib import Path

HARNESS = (Path(__file__).resolve().parents[2] / "ansible" / "roles"
           / "windows-vm" / "tasks" / "harness.yml")


def test_replace_uses_null_backup_path():
    """An existing guest file can be replaced without an invalid backup path."""
    text = HARNESS.read_text()
    assert "[IO.File]::Replace($tmp, $f.dst, [NullString]::Value)" in text
