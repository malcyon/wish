"""Helpers `test_podamiga` shares with the test files that reuse them."""
from __future__ import annotations


def pc_bytes() -> dict[str, bytes]:
    """Every `Save/*.pc` on an Amiga disk we can see, by file name.

    `tools/amiga/amigasaves.py`'s `images` is the shared discovery -- it opens
    loose `.adf` files and the Gold Box zips inside an Amiga ROM library --
    and this narrows to the `.pc` files, which its own `specimens` does not
    yield: that one keeps to the 288-byte Pool of Radiance record.

    **They are not loose files on any machine**, so they are read out of the
    disk images rather than skipping.

    Returns empty rather than skipping, so a caller that has its own
    fallback can use one.
    """
    from automap import gamedisks
    from goldbox.amiga_adf import AmigaDisk, AmigaDiskError
    from tools.amiga import amigasaves

    if not gamedisks.candidates("amiga"):
        return {}
    out: dict[str, bytes] = {}
    for _label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
            entries = list(disk.walk())
        except (AmigaDiskError, ValueError):
            continue
        for path, _entry in entries:
            if not path.lower().endswith(".pc"):
                continue
            try:
                out.setdefault(path.rsplit("/", 1)[-1], disk.read_file(path))
            except AmigaDiskError:
                continue
    return out
