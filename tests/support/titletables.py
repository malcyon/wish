"""Helpers `test_titletables` shares with the test files that reuse them."""
from __future__ import annotations

import functools
import pathlib

import gamedata
import pytest

from automap import gamedisks
from goldbox import c64_port, items
from goldbox.d64 import D64
from support.silverblades import ssb_dir

COK = c64_port.CHAMPIONS_OF_KRYNN
DKK = c64_port.DEATH_KNIGHTS_OF_KRYNN


def _roots(*entries):
    """Every folder `gamedisks.yaml` lists for these entries, in that order (#575).

    No search of the home directory: a machine says where its disks are in the
    registry, and `$COK_DISKS` and its siblings still win over it.
    """
    out = []
    for name in entries:
        for path in gamedisks.candidates(name):
            if path not in out:
                out.append(path)
    return out


def _champions_roots():
    return _roots("champions-of-krynn", "pool-of-radiance",
                  "curse-of-the-azure-bonds", "secret-of-the-silver-blades")


def _death_knights_roots():
    return gamedisks.candidates("death-knights-of-krynn")


@functools.lru_cache(maxsize=1)
def _champions_side_a():
    """The Champions of Krynn side carrying `ITEMNAMES`, or None.

    Identified by content. Champions and Death Knights of Krynn ship the same
    seven Krynn race labels, so the race table cannot tell them apart; the coin
    names can, because Death Knights makes every coin STEEL.
    """
    for root in _champions_roots():
        for pattern in ("*.[dD]64", "*/*.[dD]64", "*/*/*.[dD]64"):
            try:
                paths = sorted(root.glob(pattern))
            except OSError:
                continue
            for path in paths:
                try:
                    disk = D64.open(path)
                except Exception:
                    continue
                if disk.find(b"ITEMNAMES") is None or disk.find(b"LIBRARY") is None:
                    continue
                try:
                    names = items.load_item_names(str(path), COK)
                except Exception:
                    continue
                if names.get(145) == "KENDER" and names.get(174) == "SILVER":
                    return path
    return None


@functools.lru_cache(maxsize=1)
def _death_knights_side():
    """The Death Knights of Krynn side carrying `ITEMNAMES`, or None."""
    for root in _death_knights_roots():
        for pattern in ("*.[dD]64", "*/*.[dD]64", "*/*/*.[dD]64"):
            try:
                paths = sorted(root.glob(pattern))
            except OSError:
                continue
            for path in paths:
                try:
                    disk = D64.open(path)
                except Exception:
                    continue
                if disk.find(b"ITEMNAMES") is None:
                    continue
                try:
                    names = items.load_item_names(str(path), DKK)
                except Exception:
                    continue
                if names.get(145) == "KENDER" and names.get(174) == "STEEL":
                    return path
    return None


def champions_disk() -> pathlib.Path:
    path = _champions_side_a()
    if path is None:
        gamedata.require_registered("champions-of-krynn")
        pytest.skip("needs a Champions of Krynn side carrying ITEMNAMES; "
                    "set COK_DISKS or add the champions-of-krynn entry "
                    "to gamedisks.yaml")
    return path


def death_knights_disk() -> pathlib.Path:
    path = _death_knights_side()
    if path is None:
        gamedata.require_registered("death-knights-of-krynn")
        pytest.skip("needs a Death Knights of Krynn side carrying ITEMNAMES, "
                    "beside a champions-of-krynn candidate; set COK_DISKS or "
                    "add the entry to gamedisks.yaml")
    return path


def silver_blades_disk(stem_file: bytes = b"LIBRARY") -> pathlib.Path:
    where = ssb_dir()
    if where is None:
        pytest.skip("needs the Silver Blades disks; set SSB_DISKS")
    for path in sorted(where.glob("SILVER*.[dD]64")):
        try:
            disk = D64.open(path)
        except Exception:
            continue
        if disk.find(stem_file) is not None:
            return path
    pytest.skip(f"no Silver Blades side here carries {stem_file!r}")
