"""Fakes shared by the Amiga tests, imported by name because a second `conftest` module collides with the suite's."""

from __future__ import annotations


def fake_savecount_builder():
    """Build a fake private `savecount.py` under `directory/ssb/analysis`.

    `refuse` makes `with_count` raise `SaveCountError`; `sibling` makes the module
    import a second module from the same directory, as a real helper might.
    """
    def build(directory, *, refuse=False, sibling=False):
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
            f"    if {refuse!r}:\n        raise SaveCountError('refused')\n"
            f"    return slot + {suffix} + str(n).encode()\n")
    return build


fake_savecount = fake_savecount_builder()
