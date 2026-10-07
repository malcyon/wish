"""The Amiga harness reads and scripts a Pools of Darkness vault past 200 items."""
from __future__ import annotations

import struct

from goldbox import amiga_savegame
from tools.amiga import podsavegame, route_darkness


def _vault(nodes: int, count: int | None = None) -> bytes:
    head = bytes(amiga_savegame.POD_VAULT_HEADER) + struct.pack(
        ">HH", amiga_savegame.POD_VAULT_MARKER, nodes if count is None else count)
    return head + bytes(nodes * amiga_savegame.POD_ITEM_BYTES)


def _check(monkeypatch, blob: bytes) -> int:
    monkeypatch.setattr(podsavegame, "vaults", lambda: {"VaultA.DAT": [("x", blob)]})
    return podsavegame.main(["--vault", "--check"])


def test_a_250_item_vault_passes_check(monkeypatch):
    assert _check(monkeypatch, _vault(250)) == 0


def test_the_padded_and_the_pool_sized_vault_pass_check(monkeypatch):
    assert _check(monkeypatch, _vault(200)) == 0
    assert _check(monkeypatch, _vault(amiga_savegame.POD_POOL_NODES)) == 0


def test_a_malformed_or_oversized_vault_still_fails_check(monkeypatch):
    assert _check(monkeypatch, _vault(250) + b"\0") == 1
    assert _check(monkeypatch, _vault(amiga_savegame.POD_POOL_NODES + 1)) == 1
    assert _check(monkeypatch, _vault(250, count=251)) == 1


# Measured on the Amiga (WISH-6 measure2 run): press 20 highlights row 21, press 21 scrolls the
# list by one row, and 39 presses reach the last of 40 items, so one NP2 per row holds past row 21.
def test_vault_steps_for_250_items_press_np2_249_times():
    steps = route_darkness.vault_steps(250, True)
    assert [s[0] for s in steps].count("NP2") == 249
