"""Helpers `test_doswriter` shares with the test files that reuse them."""
from __future__ import annotations

from support.dossave import (
    _save_dir,
)


def _item_granted_specimen():
    """The engine-written DOS record of a readied magical item, or None.

    `$WISH_SPECIMENS`' `por-item-granted`: THRENDER GRONE's flail was given
    effect byte 61 and power byte `0x80` in a staged copy of the shipped
    party, readied through the game's own `VIEW > ITEMS > READY`, and the
    party saved to slot D **by the game**, which is what wrote the `.SPC`.
    `tools/dos/dosspcexpiry.py ready` regenerates it in about five minutes.

    Staging the item's two bytes and then reading what the engine computed
    from them is the experiment `.claude/rules/testing.md` calls valid: the
    engine does not care how a byte got into its input.  What is being read
    back is the engine's own output.
    """
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.registry import specimens

    for entry in specimens.list_specimens():
        if entry.get("name") == "por-item-granted":
            for path in entry["_files"]:
                if path.name.endswith(".SAV"):
                    return path
    return None


def _portrait_tables():
    """The creation menu out of the game directory the DOS saves sit in.

    `None` when the saves are somewhere else -- Steam redirects them out of
    the game folder -- in which case the portrait pair stays masked and the
    round trip says nothing about it, which is the honest outcome rather than
    a skip of the whole test.
    """
    from goldbox import portraits

    where = _save_dir()
    if where is None:
        return None
    for root in (where, *where.parents):
        if (root / "START.EXE").exists() and list(root.glob("HEAD[0-9].DAX")):
            try:
                return portraits.tables_from_dos(root)
            except portraits.PortraitError:
                return None
    return None
