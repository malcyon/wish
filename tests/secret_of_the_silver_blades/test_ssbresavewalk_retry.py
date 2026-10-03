"""The Silver Blades resave walk takes its step from a snapshot and retries."""
import pytest

from tools.secret_of_the_silver_blades import ssbresavewalk


class FakeSession:
    """Meets a fight on the first `fights` attempts, then walks."""

    save_disk = "/slot/SIDE0.D64"

    def __init__(self, fights: int, retries: int = 3):
        self.fights = fights
        self.retries = retries
        self.attempts = 0
        self.restores = 0
        self.attached = []
        self.walk_retries = 0
        self.walk_refused = None
        self.pos = 5
        self.events = []
        self.in_combat = False

    def square(self):
        return self.pos

    def attach(self, path):
        self.attached.append(path)
        self.events.append("attach")

    def walk_with_retry(self, moves, retries=3, force_restores=0):
        self.walk_retries = 0
        self.asked_forced = force_restores
        self.fights = max(self.fights, force_restores)
        self.events.append("walk")
        if self.in_combat:
            self.walk_refused = "the game is already in combat"
            return False
        for attempt in range(retries + 1):
            self.attempts += 1
            if self.attempts > self.fights:
                self.pos += 1
                return True
            self.restores += 1
            self.walk_retries = attempt + 1
        self.walk_refused = f"an encounter began on each attempt at {moves!r}"
        return False


def test_a_lost_fight_restores_and_the_retry_walks():
    sess = FakeSession(fights=1)
    moved, restores = ssbresavewalk.walk_square(sess, "I")
    assert (moved, restores) == (True, 1)
    assert sess.attached == [sess.save_disk]


def test_a_walk_with_no_fight_restores_nothing_and_attaches_nothing():
    sess = FakeSession(fights=0)
    assert ssbresavewalk.walk_square(sess, "I") == (True, 0)
    assert sess.attached == []


def test_a_walk_that_fails_every_retry_stops_with_the_reason():
    sess = FakeSession(fights=99)
    with pytest.raises(RuntimeError, match="walk I stopped: an encounter began on each attempt"):
        ssbresavewalk.walk_square(sess, "I")
    assert sess.attached == []


def test_the_disk_is_attached_once_and_only_after_the_walk_that_restored():
    sess = FakeSession(fights=2)
    ssbresavewalk.walk_square(sess, "I")
    assert sess.events == ["walk", "attach"]


def test_a_walk_begun_in_combat_reports_that_and_attaches_nothing():
    sess = FakeSession(fights=0)
    sess.in_combat = True
    with pytest.raises(RuntimeError, match="already in combat") as e:
        ssbresavewalk.walk_square(sess, "I")
    assert "every time" not in str(e.value)
    assert sess.attached == []


def test_a_forced_restore_restores_once_and_walks_the_leg_again():
    sess = FakeSession(fights=0)
    moved, restores = ssbresavewalk.walk_square(sess, "I", force_restore=True)
    assert (moved, restores) == (True, 1)
    assert sess.asked_forced == 1
    assert sess.attached == [sess.save_disk]


def test_the_force_restore_option_is_off_by_default():
    sess = FakeSession(fights=0)
    ssbresavewalk.walk_square(sess, "I")
    assert sess.restores == 0
    assert not getattr(sess, "asked_forced", 0)
