"""The camp transition waits for the camp bar itself, not a fixed settle (#621).

`tools/c64/route_pool.py`'s `open_items()` used to select ENCAMP, `sess.settle(2)`,
then try `select_bar("VIEW")` -- at most about 22 seconds before giving up.
`VIEW` is on the world bar as well as the camp bar, so nothing checked whether
CAMP had actually loaded. On a slot with no JiffyDOS the `CAMP` overlay can
take longer than that, and the driver tried `VIEW` on the still-showing world
bar and failed with "VIEW could not be selected in camp" -- a false negative
in the driver, not a game rejection (`~/.cache/wish/acceptance/621/
e5edca2eb2-gauntlets-live/`).

Nothing here needs an emulator: `FakeSession` and `FakeLog` are fixed answers,
the pattern `tests/c64/test_savecheck_move_subbar.py` uses.
"""

from __future__ import annotations

import pytest

from tools.c64 import route_pool
from tools.c64 import session as S
from tools.c64.runlog import Log

WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
CHARACTER = "ROLAND"


class FakeScreen:
    def __init__(self, row24: str):
        self.row24 = row24

    def row(self, r: int) -> str:
        if r == 0:
            return " " * S.PARTY_COLUMN + f"{CHARACTER:<16}AC HP"
        if r == 1:
            return CHARACTER
        if r == 24:
            return self.row24
        return ""

    def rows(self):
        return [self.row(r) for r in range(25)]

    def text(self) -> str:
        return "\n".join(self.rows())

    def contains(self, needle: str) -> bool:
        return needle in self.row24


class FakeLog(Log):
    def __init__(self):
        self.said: list[str] = []
        self.emitted: list[tuple[str, dict]] = []

    def say(self, *a) -> None:
        self.said.append(" ".join(str(x) for x in a))

    def emit(self, kind, **kw) -> None:
        self.emitted.append((kind, kw))


class FakeSession:
    """Answers `select_bar` and `wait_text` the way a real `Session` would,
    with the camp bar's arrival controlled by the test."""

    def __init__(self, camp_appears: bool):
        self.camp_appears = camp_appears
        self.current_bar = WORLD_BAR
        self.select_bar_calls: list[str] = []
        self.wait_text_calls: list[tuple[object, float]] = []
        self.settle_calls = 0

    def select_party(self, at: int) -> bool:
        return True

    def screen(self):
        return FakeScreen(self.current_bar)

    def party_rows(self, s):
        return [0]

    def select_bar(self, label: str, timeout: float = 20.0) -> bool:
        self.select_bar_calls.append(label)
        if label == "VIEW":
            # `wait_sheet_bar` reads the screen directly rather than through
            # `wait_text`, so the fake screen has to show the sheet's own bar
            # once VIEW is chosen, the way the real game would.
            self.current_bar = S.SHEET_BAR + "ITEMS SPELLS TRADE DROP EXIT"
        return True

    def wait_text(self, needle, timeout: float = 180.0):
        self.wait_text_calls.append((needle, timeout))
        if needle == route_pool.CAMP_BAR:
            if not self.camp_appears:
                return None, None
            self.current_bar = route_pool.CAMP_BAR
            return needle, FakeScreen(self.current_bar)
        # The sheet bar and the item label: always up once the camp bar is.
        return needle, FakeScreen(self.current_bar)

    def settle(self, seconds: float = 6.0) -> None:
        self.settle_calls += 1

    def leave_sheet(self) -> None:
        pass


def test_open_items_waits_for_the_camp_bar_before_trying_view():
    """`VIEW` is only selected after the camp bar has actually appeared."""
    sess = FakeSession(camp_appears=True)
    log = FakeLog()

    ok = route_pool.open_items(sess, log, CHARACTER, "CLOAK", "ready")

    assert ok is True
    assert sess.select_bar_calls[0] == "ENCAMP"
    # The camp-bar wait sits strictly between the ENCAMP select and the VIEW
    # select -- proof the driver checks readiness rather than guessing.
    assert sess.select_bar_calls[1] == "VIEW"
    needles = [n for n, _t in sess.wait_text_calls]
    assert route_pool.CAMP_BAR in needles
    camp_wait_timeout = next(t for n, t in sess.wait_text_calls
                             if n == route_pool.CAMP_BAR)
    assert camp_wait_timeout >= 90


def test_open_items_fails_cleanly_when_the_camp_bar_never_appears():
    """No camp bar within the timeout: `VIEW` is never tried, and the driver
    reports why instead of pressing on against the wrong screen."""
    sess = FakeSession(camp_appears=False)
    log = FakeLog()

    ok = route_pool.open_items(sess, log, CHARACTER, "CLOAK", "ready")

    assert ok is False
    assert "ENCAMP" in sess.select_bar_calls
    assert "VIEW" not in sess.select_bar_calls
    assert any("camp bar never appeared" in s for s in log.said)


def test_ready_capture_keeps_the_first_blank_row_and_the_returned_list(monkeypatch):
    """One fire can blank the target row before the unchanged list returns."""
    monkeypatch.setattr(route_pool.time, "sleep", lambda _: None)

    class ItemScreen:
        def __init__(self, target):
            self.target = target
            self.colours = bytearray([5] * 1000)
            self.colours[6 * 40 + route_pool.ITEM_NAME_COLUMN] = 1

        def row(self, n):
            return {5: " NO CLOAK", 6: self.target, 7: " NO BOOTS",
                    24: "READY TRADE DROP EXIT"}.get(n, "")

        def rows(self):
            return [self.row(n) for n in range(25)]

    listed = ItemScreen("YES GAUNTLETS OF OGRE POWER")
    blank = ItemScreen("")

    class Session:
        def __init__(self):
            self.keys = []
            self.kbd = self
            self.screens = iter((listed, None, blank, listed, listed))

        def screen(self):
            return listed

        def key(self, name, *timing):
            self.keys.append(name)

    sess = Session()
    checkpoints = []

    def sample(stage, predicate):
        screen = next(sess.screens)
        if stage is not None and predicate(screen):
            checkpoints.append((stage, screen.row(6), tuple(sess.keys)))
        return screen

    log = FakeLog()
    flipped = route_pool.toggle_item(
        sess, log, "GAUNTLETS", "ready", sample=sample)

    assert flipped is True  # Existing screen-change report; no state claim.
    assert next(kw for kind, kw in log.emitted if kind == "screen"
                and kw["tag"] == "ready-after")["screen_changed"] is True
    assert sess.keys == ["KP_0"]
    assert [(stage, row) for stage, row, _ in checkpoints] == [
        ("before", "YES GAUNTLETS OF OGRE POWER"),
        ("change", ""),
        ("stable", "YES GAUNTLETS OF OGRE POWER"),
    ]
    assert checkpoints[0][2] == ()
    assert all(keys == ("KP_0",) for _, _, keys in checkpoints[1:])

    stuck = Session()
    stuck.screens = iter([listed, *([blank] * 20), blank])
    stuck_stages = []

    def stuck_sample(stage, predicate):
        screen = next(stuck.screens)
        if stage is not None and predicate(screen):
            stuck_stages.append(stage)
        return screen

    assert route_pool.toggle_item(
        stuck, FakeLog(), "GAUNTLETS", "ready", sample=stuck_sample) is True
    assert stuck.keys == ["KP_0"]
    assert stuck_stages == ["before", "change", "timeout"]

    changed = ItemScreen(" NO GAUNTLETS OF OGRE POWER")

    class NormalSession(Session):
        def __init__(self):
            super().__init__()
            self.screens = iter((listed, listed, changed))

        def screen(self):
            return next(self.screens, changed)

    normal = NormalSession()
    assert route_pool.toggle_item(normal, FakeLog(), "GAUNTLETS", "ready") is True
    assert normal.keys == ["KP_0"]


# --- Caster: the combat cast, with and without a target prompt -------------------

class _Mon:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr, length):
        return bytes(length)

    def resume(self):
        pass


class _Me:
    name = "BAKSHI "
    index = 1
    x = y = 3


class _CastSession:
    """Records the keys a cast sends; the spell list shows PRAYER and the
    targeting bar appears only when `asks_target`."""

    def __init__(self, asks_target=False, bar_returns=True):
        self.asks_target = asks_target
        self.bar_returns = bar_returns
        self.calls: list[tuple] = []

    def mon(self, timeout=5.0):
        return _Mon()

    def combat_bar(self, word, timeout=5.0):
        self.calls.append(("bar", word))
        return True

    def select_bar(self, word, timeout=5.0):
        self.calls.append(("select", word))
        return True

    def wait_text(self, text, timeout=5.0):
        self.calls.append(("wait", text))
        found = text == "PRAYER" or (text == "TARGET" and self.asks_target)
        return (0 if found else None), None

    def await_bar(self, kinds, timeout=6.0):
        self.calls.append(("await", kinds))
        return object() if self.bar_returns else None

    def screen(self):
        return self

    def row(self, r):
        return "PRAYER" if r == 5 else ""

    def handle_prompt(self):
        self.calls.append(("prompt",))

    def press_kernal(self, key):
        self.calls.append(("kernal", key))

    def battle(self):
        return self

    def acting(self, b):
        return _Me()


@pytest.fixture
def cast_patches(monkeypatch):
    monkeypatch.setattr(route_pool.time, "sleep", lambda s: None)
    monkeypatch.setattr(route_pool, "sheet_rows", lambda sess: [])
    monkeypatch.setattr(route_pool, "item_highlight", lambda s, rows: 5)
    monkeypatch.setattr(route_pool, "press_select",
                        lambda sess: sess.calls.append(("pick",)))


def test_caster_casts_a_party_spell_without_aiming(cast_patches):
    sess, log = _CastSession(), FakeLog()
    caster = route_pool.Caster(log, [("BAKSHI", "PRAYER", None)])
    assert caster.cast(sess, sess, _Me(), "PRAYER", None) is True
    assert sess.calls[:4] == [("bar", "CAST"), ("wait", "PRAYER"),
                              ("select", "CAST"), ("pick",)]
    assert ("bar", "TARGET") not in sess.calls
    assert ("bar", "NEXT") not in sess.calls
    assert caster.casts[0]["spell"] == "PRAYER"
    assert caster.casts[0]["target"] is None


def test_caster_backs_out_when_a_party_spell_asks_for_a_target(cast_patches):
    sess = _CastSession(asks_target=True)
    caster = route_pool.Caster(FakeLog(), [("BAKSHI", "PRAYER", None)])
    assert caster.cast(sess, sess, _Me(), "PRAYER", None) is False
    assert ("bar", "EXIT") in sess.calls
    assert sess.calls[-1] == ("await", (route_pool.S.BAR_COMMAND,))
    assert caster.casts == []


def test_caster_fails_when_the_combat_bar_never_comes_back(cast_patches):
    sess = _CastSession(asks_target=True, bar_returns=False)
    caster = route_pool.Caster(FakeLog(), [("BAKSHI", "PRAYER", None)])
    with pytest.raises(RuntimeError, match="combat bar did not come back"):
        caster.cast(sess, sess, _Me(), "PRAYER", None)
    assert sess.calls.count(("bar", "EXIT")) == route_pool.Caster.BACK_OUT_PRESSES


def test_caster_drops_a_failed_cast_and_leaves_the_turn_to_the_other_tactic(
        cast_patches):
    sess = _CastSession(asks_target=True)
    caster = route_pool.Caster(FakeLog(), [("BAKSHI", "PRAYER", None)],
                               otherwise=lambda s, state: "FLEE")
    assert caster(sess, "bar") == "FLEE"
    assert caster.queue == []
    assert caster(sess, "bar") == "FLEE"
    assert sess.calls.count(("select", "CAST")) == 1


def test_caster_gives_other_members_turns_to_the_other_tactic(cast_patches):
    seen = []
    sess = _CastSession()
    sess.name = "SEAN"
    caster = route_pool.Caster(
        FakeLog(), [("OTHER", "PRAYER", None)],
        otherwise=lambda s, state: seen.append(state) or "FLEE")
    assert caster(sess, "bar") == "FLEE"
    assert seen == ["bar"]
    assert caster.queue == [("OTHER", "PRAYER", None)]


def test_caster_casts_on_the_named_members_turn_and_returns_cast(cast_patches):
    sess = _CastSession()
    caster = route_pool.Caster(FakeLog(), [("BAKSHI", "PRAYER", None)],
                               otherwise=lambda s, state: "FLEE")
    assert caster(sess, "bar") == "CAST"
    assert caster.queue == []


def _roster(statuses):
    from goldbox import savegame
    page = bytearray(savegame.ROSTER_STRIDE * savegame.ROSTER_COUNT)
    for slot, status in enumerate(statuses):
        page[slot * savegame.ROSTER_STRIDE] = status
    return bytes(page)


def _last_caster(monkeypatch, statuses, waited):
    from tools.pool_of_radiance import fleedrive
    monkeypatch.setattr(fleedrive, "roster_page",
                        lambda sess: _roster(statuses))
    return route_pool.Caster(
        FakeLog(), [("BAKSHI", "PRAYER", None)],
        otherwise=lambda s, state: "OTHER",
        wait=lambda s, state: waited.append(state) or "WAIT", last=True)


def test_last_caster_waits_while_another_member_is_still_standing(
        cast_patches, monkeypatch):
    waited, sess = [], _CastSession()
    caster = _last_caster(monkeypatch, [0x01, 0x01, 0x86, 0x01], waited)
    assert caster(sess, "bar") == "WAIT"
    assert waited == ["bar"]
    assert ("bar", "CAST") not in sess.calls
    assert caster.queue == [("BAKSHI", "PRAYER", None)]


def test_last_caster_casts_once_every_other_member_is_running_or_down(
        cast_patches, monkeypatch):
    waited, sess = [], _CastSession()
    caster = _last_caster(monkeypatch, [0x86, 0x01, 0x84, 0x86, 0], waited)
    assert caster(sess, "bar") == "CAST"
    assert waited == []
    assert ("bar", "CAST") in sess.calls


def test_last_caster_counts_a_dead_member_without_bit_7_as_gone(
        cast_patches, monkeypatch):
    waited, sess = [], _CastSession()
    caster = _last_caster(monkeypatch, [0x86, 0x03, 0x04, 0x05, 0x07, 0x02],
                          waited)
    assert caster(sess, "bar") == "CAST"
    assert waited == []


def test_last_caster_waits_for_a_member_who_is_ok_or_running_unmarked(
        cast_patches, monkeypatch):
    waited, sess = [], _CastSession()
    caster = _last_caster(monkeypatch, [0x86, 0x03, 0x06], waited)
    assert caster(sess, "bar") == "WAIT"


def test_last_caster_logs_every_status_once_the_wait_runs_long(
        cast_patches, monkeypatch):
    waited, sess = [], _CastSession()
    caster = _last_caster(monkeypatch, [0x01, 0x01, 0x03], waited)
    for _ in range(route_pool.Caster.WAIT_REPORT_TURNS - 1):
        caster(sess, "bar")
    assert not [e for e in caster.log.emitted if e[0] == "cast-wait"]
    caster(sess, "bar")
    kind, fields = [e for e in caster.log.emitted if e[0] == "cast-wait"][0]
    assert fields["statuses"][:3] == ["01", "01", "03"]
    assert fields["words"][2] == "$03 DEAD"


def test_down_words_name_every_status_that_takes_a_member_out_of_the_fight():
    assert route_pool.Caster.down_words() == {2, 3, 4, 5, 7}
    assert route_pool.Caster.down_words(gone=False) == {3, 4, 5, 7}
