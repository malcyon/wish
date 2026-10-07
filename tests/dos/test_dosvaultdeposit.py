"""The DOS Pools of Darkness `deposit` step and the vault list's page bound.

`deposit MEMBER ROW` has the game itself put an item into Elminster's vault:
`STORAGE`, the member highlighted on the vault screen's roster, `ITEMS`, the
row highlighted and `D`.  The fake below plays the screens a live run drew
(`acceptance/WISH-6/05b3c16d26-b3-deposit1`), and the recorded-screen tests
read those captures where this machine has them.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
from test_dosacceptance import (
    _BAR_INK,
    _CYAN,
    _FONT,
    _FONT_BLOCK,
    _NAME_INK,
    _WHITE,
    FakeVault,
    H,
    W,
    _draw,
    _vault_file,
    _with_roster,
)

from tools.dos import acceptance as da
from tools.dos import dosbox, screens

_ITEMS_BAR = "READY TRADE DEPOSIT HALVE JOIN EXIT"


def _bar_frame(text: str) -> dosbox.Screen:
    px = bytearray(W * H * 3)
    _draw(px, _FONT_BLOCK, da.BAR_ROW, 0, text, _BAR_INK)
    return dosbox.Screen(W, H, bytes(px))


@pytest.fixture(autouse=True)
def _measured(monkeypatch):
    """No waiting, and the fake's Elminster menu and `READY` bar head stand
    in for the measured signatures."""
    monkeypatch.setattr(da.time, "sleep", lambda s: None)
    monkeypatch.setattr(dosbox, "settle_files", lambda *a, **k: True)
    monkeypatch.setattr(da, "POD_ELMINSTER_BAR", screens.bar_signature(
        _bar_frame("HEAL TRAIN STORAGE REST MOVE ON")))
    monkeypatch.setattr(screens, "ITEMS_BAR_HEAD", screens.bar_signature(
        _bar_frame(_ITEMS_BAR), screens.ITEMS_BAR_HEAD_CELLS))


def _record(name: str) -> bytes:
    """A 63-byte vault record caching `name` as the game draws it."""
    raw = name.encode()
    return (bytes((len(raw),)) + raw).ljust(63, b"\0")


HILDE = [("QUARTER STAFF +3", True), ("WAND OF FIREBALLS", False),
         ("WAND OF MAGIC MISSILES", False), ("NECKLACE OF MISSILES", True)]


class FakeDeposit(FakeVault):
    """`FakeVault` with the member's side the live run drew: the roster where
    camp draws it, `Down` moving its white line a member on; `ITEMS` on the
    bar only for a member who has items; `I` opening his list under
    `READY TRADE DEPOSIT HALVE JOIN EXIT`, headed `<NAME>'S ITEMS`, a row
    `YES  NAME` or `NO   NAME`, `Down` moving the highlight; `D` taking an
    unreadied row off the list and appending it to the vault (unless
    `dead_deposit`), a readied row staying; `E` back to the vault.  The vault
    is held in memory, and leaving the vault writes it as `TMPVAULT.DAT`.
    `phantoms` adds rows the list draws past the vault's records."""

    def __init__(self, tmp, vault, members, *, dead_deposit=False, phantoms=0, **kw):
        super().__init__(tmp, vault, **kw)
        self.members = {n: list(rows) for n, rows in members.items()}
        self.store = bytearray(vault if vault is not None else bytes(12))
        self.dead_deposit, self.phantoms, self.item_row = dead_deposit, phantoms, 0

    def records(self) -> list[bytes]:
        return [bytes(self.store[12 + 63 * k:12 + 63 * (k + 1)])
                for k in range((len(self.store) - 12) // 63)]

    def stored(self) -> tuple[int, int]:
        return len(self.records()) + self.phantoms, sum(self.store[:12])

    def key(self, k, gap=0.0):
        m = self.mode
        if m == "vault" and k in ("Down", "Up"):
            self.keys.append(k)
            self._roster(k)
        elif m == "vault" and k == "i" and self.members.get(self.line):
            self.keys.append(k)
            self.mode, self.item_row = "vitems", 0
        elif m == "vault" and k == "e":
            self.keys.append(k)
            (self.save_dir / "TMPVAULT.DAT").write_bytes(bytes(self.store))
            self.mode = "town"
        elif m == "vitems":
            self.keys.append(k)
            rows = self.members[self.line]
            if k == "Down":
                self.item_row = min(self.item_row + 1, len(rows) - 1)
            elif k == "d" and not self.dead_deposit and not rows[self.item_row][1]:
                name, _ = rows.pop(self.item_row)
                self.store += _record(name)
                self.item_row = min(self.item_row, len(rows) - 1)
            elif k == "e":
                self.mode = "vault"
        else:
            super().key(k, gap)

    def bar_text(self) -> str:
        if self.mode == "vault":
            items, _ = self.stored()
            return ("VIEW " + ("TAKE " if items else "") + "POOL MONEY "
                    + ("ITEMS " if self.members.get(self.line) else "") + "EXIT")
        return super().bar_text()

    def capture(self):
        if self.mode == "vitems":
            px = bytearray(W * H * 3)
            _draw(px, _FONT_BLOCK, da.BAR_ROW, 0, _ITEMS_BAR, _BAR_INK)
            _draw(px, _FONT_BLOCK, da.VAULT_ITEMS_HEAD_ROW, 1, f"MEMBER {self.line}'S ITEMS",
                  _NAME_INK)
            for i, (name, ready) in enumerate(self.members[self.line]):
                text = ("YES  " if ready else "NO   ") + name
                _draw(px, _FONT_BLOCK, da.ITEM_TEXT_ROW + i, 2, text, _CYAN)
                if i == self.item_row:
                    y = (da.ITEM_TEXT_ROW + i) * 8 + 7
                    for x in range(16, 16 + 8 * len(text)):
                        px[(y * W + x) * 3:(y * W + x) * 3 + 3] = _WHITE
            return dosbox.Screen(W, H, bytes(px))
        if self.mode == "vlist":
            px = bytearray(W * H * 3)
            _draw(px, _FONT_BLOCK, da.BAR_ROW, 0, self.bar_text(), _BAR_INK)
            names = [da.record_name(r) for r in self.records()]
            names += [f"PHANTOM {n}" for n in range(self.phantoms)]
            first = self.top()
            for i, name in enumerate(names[first:first + da.VAULT_WINDOW]):
                _draw(px, _FONT_BLOCK, 1 + i, 1, name, _NAME_INK)
            return dosbox.Screen(W, H, bytes(px))
        frame = super().capture()
        if self.mode == "vault":
            return _with_roster(frame, da.VAULT_ROSTER, self.size, self.line)
        return frame


def _driver(tmp_path, vault, members=None, **kw):
    game = FakeDeposit(tmp_path, vault, {5: HILDE} if members is None else members, **kw)
    d = da.Driver(game, lambda **k: None, "A", "darkness", party_size=game.size)
    d._font = _FONT
    d.elminster_ok = True
    d.load()
    d.begin()
    game.keys.clear()
    return game, d


# -- the step list ---------------------------------------------------------------


def test_deposit_parses_and_comes_after_vault_in_darkness_only():
    steps = [da.parse_step(t) for t in ("load", "begin", "vault", "deposit 5 2",
                                        "deposit 1 18", "camp", "save D", "read")]
    da.validate_steps(steps, "darkness")
    assert (steps[3].kind, steps[3].line, steps[3].row) == ("deposit", 5, 2)
    for bad, title, match in (
            (("load", "begin", "deposit 5 2"), "darkness", "comes after vault"),
            (("load", "begin", "vault", "camp", "deposit 5 2"), "darkness",
             "comes after vault"),
            (("load", "begin", "deposit 5 2"), "ssb", "darkness only")):
        with pytest.raises(ValueError, match=match):
            da.validate_steps([da.parse_step(t) for t in bad], title)
    for text in ("deposit 5 0", "deposit 5 19"):
        with pytest.raises(ValueError, match="rows 1 to 18"):
            da.parse_step(text)
    for text in ("deposit 9 2", "deposit 5", "deposit five 2"):
        with pytest.raises(ValueError, match="not a step"):
            da.parse_step(text)


# -- the list's page bound -------------------------------------------------------


@pytest.mark.parametrize("records, pages", [(0, 1), (1, 1), (22, 1), (23, 2), (40, 2),
                                            (264, 12), (265, 13), (387, 18), (448, 21)])
def test_the_page_bound_is_the_pages_the_vault_fills(records, pages):
    assert da.vault_page_limit(records) == pages


def test_a_387_item_vault_lists_to_its_last_page(tmp_path):
    """Past the 264 rows twelve pages held: the list reads to the end."""
    game, d = _driver(tmp_path, _vault_file(387, (1, 0, 0)))
    got = d.vault()
    assert len(got["pages"]) == 18 and got["listed"] == 387 and got["matches"]


def test_a_list_still_offering_next_past_the_vault_stops(tmp_path):
    """A list drawing 30 rows the 40-record file does not hold stops at the
    second page, all that 40 records fill."""
    game, d = _driver(tmp_path, _vault_file(40, (1750, 495, 82)), phantoms=30)
    with pytest.raises(da.StepFailed, match="NEXT after 2 pages, all that its 40 "
                                            "items fill.*lost-vault-pages"):
        d.vault()


# -- the deposit -----------------------------------------------------------------


def test_deposit_stores_the_row_and_reads_the_vault_back(tmp_path):
    game, d = _driver(tmp_path, _vault_file(40, (1750, 495, 82)))
    d.vault()
    game.keys.clear()
    got = d.deposit(5, 2)
    assert game.keys[:9] == ["s", "Down", "Down", "Down", "Down", "i", "Down", "d", "e"]
    assert game.keys[9] == "e" and game.keys[10:] == ["s", "t", "i", "n", "e", "e", "e"]
    assert got["why"] is None and d.where == "elminster" and game.mode == "town"
    assert got["owner"] == "MEMBER 5" and got["item"] == "WAND OF FIREBALLS"
    assert (got["member_presses"], got["row_presses"]) == (4, 1)
    assert (got["rows_before"], got["rows_after"]) == (4, 3)
    assert got["before"]["items"] == 40 and got["before"]["file"] == "TMPVAULT.DAT"
    assert got["tmpvault"]["items"] == 41
    assert got["tmpvault"]["names"][-1] == "WAND OF FIREBALLS"
    assert got["readback"]["listed"] == 41 and got["readback"]["window"]["covered"]
    assert [n for n, _ in game.members[5]] == [
        "QUARTER STAFF +3", "WAND OF MAGIC MISSILES", "NECKLACE OF MISSILES"]
    results = [{"step": "vault", **_first_vault(tmp_path)}, {"step": "deposit 5 2", **got}]
    assert da.stored_verdict(results, None) is None
    d.camp()
    d.save("D")
    saved = (game.save_dir / "VAULTD.DAT").read_bytes()
    assert len(saved) == 12 + 63 * 41 and saved[-63:] == _record("WAND OF FIREBALLS")


def _first_vault(tmp_path):
    """A passing `vault` result for the verdict, from a fresh fake."""
    (tmp_path / "first").mkdir()
    _, d = _driver(tmp_path / "first", _vault_file(40, (1750, 495, 82)))
    return d.vault()


def test_a_second_deposit_counts_from_the_first(tmp_path):
    game, d = _driver(tmp_path, _vault_file(3))
    d.vault()
    first = d.deposit(5, 2)
    second = d.deposit(5, 2)
    assert (first["before"]["items"], first["tmpvault"]["items"]) == (3, 4)
    assert (second["before"]["items"], second["tmpvault"]["items"]) == (4, 5)
    assert second["item"] == "WAND OF MAGIC MISSILES" and second["why"] is None


def test_a_readied_row_is_not_deposited(tmp_path):
    game, d = _driver(tmp_path, _vault_file(3))
    d.vault()
    game.keys.clear()
    with pytest.raises(da.StepFailed, match="QUARTER STAFF \\+3\\) is readied"):
        d.deposit(5, 1)
    assert "d" not in game.keys


def test_the_last_row_is_not_deposited(tmp_path):
    game, d = _driver(tmp_path, _vault_file(3), {2: [("DAGGER +4", False)]})
    d.vault()
    game.keys.clear()
    with pytest.raises(da.StepFailed, match="draws 1 rows"):
        d.deposit(2, 1)
    assert "d" not in game.keys


def test_a_member_with_nothing_offers_no_items(tmp_path):
    game, d = _driver(tmp_path, _vault_file(3))
    d.vault()
    with pytest.raises(da.StepFailed, match="no ITEMS for line 3"):
        d.deposit(3, 1)


def test_a_deposit_the_game_does_not_make_stops(tmp_path):
    game, d = _driver(tmp_path, _vault_file(3), dead_deposit=True)
    d.vault()
    with pytest.raises(da.StepFailed, match="DEPOSIT left 4 rows of 4"):
        d.deposit(5, 2)


def test_deposit_needs_elminsters_menu(tmp_path):
    game, d = _driver(tmp_path, _vault_file(3))
    d.where = "camp"
    with pytest.raises(da.StepFailed, match="Elminster's menu"):
        d.deposit(5, 2)


# -- the verdicts ----------------------------------------------------------------


def _deposit_result(why=None, items=41, coins=(1750, 495, 82)):
    return {"step": "deposit 5 2", "why": why,
            "tmpvault": {"items": items, "platinum": coins[0], "gems": coins[1],
                         "jewelry": coins[2]}}


def _vault_ok():
    want = {"file": "VAULTD.DAT", "items": 40, "platinum": 1750, "gems": 495,
            "jewelry": 82}
    return {"step": "vault", "listed": 40, "expected": want, "matches": True,
            "tmpvault": {"file": "TMPVAULT.DAT", **{k: v for k, v in want.items()
                                                     if k != "file"}}}


def _read(items, coins=(1750, 495, 82)):
    return {"saved": ["D"], "slots": {"D": {"vault": {
        "platinum": coins[0], "gems": coins[1], "jewelry": coins[2],
        "items": [{}] * items}}}}


def test_the_deposit_verdicts():
    assert da.deposit_verdict([_vault_ok()], _read(40)) is None
    assert da.deposit_verdict([_vault_ok(), _deposit_result()], _read(41)) is None
    assert da.deposit_verdict([_deposit_result("TMPVAULT.DAT holds 40")], None) == (
        "deposit 5 2: TMPVAULT.DAT holds 40")
    assert "VAULTD.DAT holds" in da.deposit_verdict([_deposit_result()], _read(40))
    assert "VAULTD.DAT holds" in da.deposit_verdict(
        [_deposit_result()], _read(41, (0, 495, 82)))
    lost = {"saved": ["D"], "slots": {"D": {}}}
    assert "no VAULTD.DAT" in da.deposit_verdict([_deposit_result()], lost)
    # Without a deposit the stored verdict is the vault's; with one, the saved
    # vault holds the deposit's count rather than the installed one.
    assert da.stored_verdict([_vault_ok()], _read(41)) == da.vault_verdict(
        [_vault_ok()], _read(41))
    assert da.stored_verdict([_vault_ok(), _deposit_result()], _read(41)) is None
    assert "VAULTD.DAT holds" in da.stored_verdict([_vault_ok(), _deposit_result()],
                                                   _read(40))


def test_a_vault_row_reads_its_ready_column_and_name():
    assert da.vault_item_entry(" NO   WAND OF FIREBALLS") == (False, "WAND OF FIREBALLS")
    assert da.vault_item_entry("YES  QUARTER STAFF +3") == (True, "QUARTER STAFF +3")
    assert da.vault_item_entry("??   WAND") == (None, "??   WAND")
    assert da.vault_item_entry("") == (None, "")


# -- the live run's screens ------------------------------------------------------

_LIVE = "05b3c16d26-b3-deposit1"
_EXPLORE_READY = "05b3c16d26-b3-explore1"
_EXPLORE_ROSTER = "05b3c16d26-b3-explore2"


def _shot(run: str, name: str) -> dosbox.Screen:
    from tools.registry.scratch import cache_dir
    shot = cache_dir("acceptance", "WISH-6", run, "shots", f"{name}.png")
    if not shot.exists() or shutil.which("convert") is None:
        pytest.skip(f"the captured screen {run}/{name} is not on this machine")
    return dosbox.Screen.from_ppm(subprocess.run(
        ["convert", str(shot), "-depth", "8", "ppm:-"], check=True,
        capture_output=True).stdout)


@pytest.fixture
def pod_font():
    try:
        return da.load_font(da.TITLES["darkness"].find_game())
    except Exception as e:  # no disks on this machine
        pytest.skip(f"Pools of Darkness' font is not on this machine: {e}")


@pytest.mark.parametrize("name, line", [("007-vault", 1), ("013-press-Down", 2),
                                        ("016-press-Down", 5)])
def test_the_vault_screen_draws_the_roster_where_camp_does(name, line):
    screen = _shot(_EXPLORE_ROSTER, name)
    assert screens.roster_line(screen, da.VAULT_ROSTER, 6) == line


def test_the_live_deposit_took_the_row_off_the_list(pod_font, monkeypatch):
    monkeypatch.undo()
    before = _shot(_LIVE, "012-deposit-5-2-before")
    after = _shot(_LIVE, "013-deposit-5-2-after")
    assert screens.on_items_list(before) and screens.on_items_list(after)
    assert da.text_row(before, da.BAR_ROW, pod_font).split() == _ITEMS_BAR.split()
    head = da.text_row(before, da.VAULT_ITEMS_HEAD_ROW, pod_font, da.VAULT_TEXT_COLUMNS)
    assert head.strip() == "HILDE" + da.VAULT_ITEMS_HEAD
    assert (screens.item_rows(before), screens.item_highlight(before)) == (14, 1)
    assert (screens.item_rows(after), screens.item_highlight(after)) == (13, 1)
    row = da.ITEM_TEXT_ROW + 1
    assert da.vault_item_entry(da.text_row(before, row, pod_font, da.VAULT_TEXT_COLUMNS)) == (
        False, "WAND OF FIREBALLS")
    assert da.vault_item_entry(da.text_row(after, row, pod_font, da.VAULT_TEXT_COLUMNS)) == (
        False, "WAND OF MAGIC MISSILES")


def test_d_on_a_readied_row_left_the_list_as_it_was(pod_font, monkeypatch):
    monkeypatch.undo()
    before = _shot(_EXPLORE_READY, "013-press-i")
    after = _shot(_EXPLORE_READY, "014-press-d")
    row = da.text_row(before, da.ITEM_TEXT_ROW, pod_font, da.VAULT_TEXT_COLUMNS)
    assert da.vault_item_entry(row) == (True, "EYES OF CHARMING")
    assert screens.item_rows(before) == screens.item_rows(after) == 10


def test_the_live_runs_files_hold_the_deposit():
    """The game's own `VAULTD.DAT` after the deposit: 41 records, the last
    being Hilde's second item from her installed `.THG` in every byte but
    the cached name (0x00-0x18 here) and the list pointer (0x2A-0x2D)."""
    from tools.registry.scratch import cache_dir
    run = pathlib.Path(cache_dir("acceptance", "WISH-6", _LIVE))
    vault, thg = run / "resave" / "VAULTD.DAT", run / "installed" / "CHRDATD5.THG"
    if not vault.is_file() or not thg.is_file():
        pytest.skip("the live deposit run is not on this machine")
    data, item = vault.read_bytes(), thg.read_bytes()[63:126]
    assert len(data) == 12 + 63 * 41
    last = data[-63:]
    assert last[0x19:0x2A] == item[0x19:0x2A] and last[0x2E:] == item[0x2E:]
    assert da.record_name(last) == "WAND OF FIREBALLS"
