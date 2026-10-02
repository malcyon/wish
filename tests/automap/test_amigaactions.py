"""The Amiga Action buttons, against a fake party and a bytearray target."""

import importlib
from types import SimpleNamespace

import pytest

from automap import actions as engine
from automap import amigaactions as aa

BASE = 0x1000


class Spot(SimpleNamespace):
    pass


class Member:
    def __init__(self, name, address, hp, hp_max, memorised=b"", nodes=(),
                 quickfight=False):
        self.name, self.address = name, address
        self.hp, self.hp_max = hp, hp_max
        self._mem, self._nodes, self.quickfight = memorised, nodes, quickfight

    def memorised(self):
        return self._mem

    def items(self):
        return self._nodes


class Target:
    def __init__(self, can_write=True, size=0x2000):
        self.mem = bytearray(size)
        self.can_write = can_write

    def read(self, addr, length):
        return bytes(self.mem[addr:addr + length])

    def write(self, addr, data):
        self.mem[addr:addr + len(data)] = data


class Forward:
    """What the action bar hands `legality`: only `read`, and `.target`."""

    def __init__(self, target):
        self.target = target

    def read(self, addr, length):
        return self.target.read(addr, length)


ALL = frozenset({"heal", "store-spells", "restore-spells", "identify",
                 "clear-quickfight"})


def make_row(confirmed=ALL, combat_legal=frozenset(),
             title="Curse of the Azure Bonds", **spots):
    row = SimpleNamespace(
        title=title, confirmed=confirmed, combat_legal=combat_legal, combat_value=2,
        hp=Spot(offset=0x10, length=1, mask=0xFF),
        memorised=Spot(offset=0x20, length=4, mask=0xFF),
        quickfight=Spot(offset=0x30, length=1, mask=0x80),
        hidden=Spot(offset=6, length=1, mask=0x07))
    for field, spot in spots.items():
        setattr(row, field, spot)
    return row


@pytest.fixture
def world(monkeypatch):
    """A fake `amigaparty`: one row, a mode byte, and a party."""
    w = SimpleNamespace(row=make_row(), mode=0, members=[], target=Target())
    fake = SimpleNamespace(
        row_for=lambda t: w.row,
        mode=lambda t: w.mode,
        read_party=lambda t: tuple(w.members) or None)
    monkeypatch.setattr(aa, "_parties", lambda: fake)

    def no_c64(*a, **k):
        raise AssertionError("a C64 address was consulted")

    monkeypatch.setattr(engine.c64, "machine_for", no_c64)
    monkeypatch.setattr(engine, "read_party", no_c64)
    return w


@pytest.fixture
def store(tmp_path):
    return engine.SpellStore(tmp_path / "spells.json")


def acts(store, key="curse-of-the-azure-bonds"):
    return {a.name: a for a in aa.actions(store, key)}


def test_the_five_come_in_the_c64_order(store):
    assert [a.name for a in aa.actions(store, "pool-of-radiance")] == [
        a.name for a in engine.actions(store)]


def test_each_is_a_subclass_with_the_c64_text(store):
    for mine, theirs in zip(aa.actions(store, "pool-of-radiance"),
                            engine.actions(store)):
        assert isinstance(mine, type(theirs))
        assert (mine.label, mine.description, mine.confirm) == (
            theirs.label, theirs.description, theirs.confirm)


def test_heal_writes_at_record_plus_offset_and_skips_the_dead(world, store):
    world.members = [Member("A", BASE, 3, 9), Member("B", BASE + 0x100, 0, 9),
                     Member("C", BASE + 0x200, 9, 9)]
    out = acts(store)["heal"].apply(world.target)
    assert out.ok and out.writes == ((BASE + 0x10, b"\x09"),)
    assert world.target.mem[BASE + 0x10] == 9
    assert world.target.mem[BASE + 0x110] == 0
    assert out.message == "Healed A up to full."
    assert any("B is at 0" in n for n in out.notes)


def test_heal_with_everyone_full_says_what_the_c64_says(world, store):
    world.members = [Member("A", BASE, 9, 9)]
    out = acts(store)["heal"].apply(world.target)
    assert out.message == "All party members are at full health."


def test_store_then_restore_round_trips_the_raw_span(world, store):
    world.members = [Member("A", BASE, 5, 9, memorised=b"\x01\x02\x03\x04")]
    a = acts(store)
    assert a["store-spells"].apply(world.target).message == "Saved spell state."
    world.members = [Member("A", BASE, 5, 9, memorised=b"\x00\x00\x00\x00")]
    out = a["restore-spells"].apply(world.target)
    assert out.writes == ((BASE + 0x20, b"\x01\x02\x03\x04"),)
    assert out.message == "Restored spell state."
    assert store.get("amiga/curse-of-the-azure-bonds", "A") == b"\x01\x02\x03\x04"


def test_a_c64_list_is_never_restored_on_the_amiga(world, store):
    store.put("", "A", b"\x09\x09\x09\x09")
    world.members = [Member("A", BASE, 5, 9, memorised=b"\x00\x00\x00\x00")]
    out = acts(store)["restore-spells"].apply(world.target)
    assert out.writes == () and any("nothing stored for A" in n for n in out.notes)


def test_identify_clears_only_the_hidden_bits(world, store):
    node = bytearray(16)
    node[6] = 0x87                       # readied + all three hidden bits
    clean = bytearray(16)
    clean[6] = 0x80
    world.members = [Member("A", BASE, 5, 9,
                            nodes=((0x300, bytes(node)), (0x320, bytes(clean))))]
    out = acts(store)["identify"].apply(world.target)
    assert out.writes == ((0x306, b"\x80"),)
    assert out.message == "Identified 1 item."


def test_clear_quickfight_clears_only_its_bit(world, store):
    world.target.mem[BASE + 0x30] = 0xFF
    world.members = [Member("A", BASE, 5, 9, quickfight=True),
                     Member("B", BASE + 0x100, 5, 9)]
    out = acts(store)["clear-quickfight"].apply(world.target)
    assert out.writes == ((BASE + 0x30, b"\x7f"),)


@pytest.mark.parametrize("name", sorted(ALL))
def test_combat_stops_each_action_that_is_not_combat_legal(world, store, name):
    world.mode = 2
    verdict = acts(store)[name].legality(world.target)
    assert not verdict
    assert verdict.reason == f"{acts(store)[name].label} is refused during a fight"
    assert not acts(store)[name].apply(world.target).ok


def test_the_row_can_mark_an_action_combat_legal(world, store):
    world.row = make_row(combat_legal=frozenset({"clear-quickfight"}))
    world.mode = 2
    assert acts(store)["clear-quickfight"].legality(world.target)
    assert not acts(store)["heal"].legality(world.target)


@pytest.mark.parametrize("name", sorted(ALL))
def test_an_unconfirmed_action_is_not_built(world, store, name):
    world.row = make_row(confirmed=ALL - {name})
    assert acts(store)[name].legality(world.target).reason == aa.NOT_BUILT


@pytest.mark.parametrize("name", sorted(ALL))
def test_a_title_with_no_row_is_not_built(world, store, name):
    world.row = None
    verdict = acts(store)[name].legality(world.target)
    assert not verdict and verdict.reason == aa.NOT_BUILT


def test_without_amigaparty_everything_is_not_built(monkeypatch, store):
    monkeypatch.setattr(aa, "_parties", lambda: None)
    for a in aa.actions(store, "pool-of-radiance"):
        assert a.legality(Target()).reason == aa.NOT_BUILT


def test_a_target_that_cannot_write_disables_all_but_save_spells(world, store):
    world.target.can_write = False
    for name, action in acts(store).items():
        assert bool(action.legality(world.target)) == (name == "store-spells")
    # The bar hands `legality` a reads-only wrapper; `can_write` is looked up
    # on the real target underneath.
    assert acts(store)["store-spells"].legality(Forward(world.target))
    assert not acts(store)["heal"].legality(Forward(world.target))
    assert acts(store)["heal"].legality(Forward(Target()))


def test_an_unreadable_mode_refuses(world, store):
    world.mode = None
    assert acts(store)["heal"].legality(world.target).reason == (
        "the machine is not readable right now")


def test_pools_of_darkness_never_gets_c64_addresses(world, store):
    # `machine_for` and `read_party` in the engine raise (the fixture), and
    # None there would mean Pool of Radiance.
    world.row = make_row(title="Pools of Darkness")
    world.members = [Member("A", BASE, 3, 9)]
    for action in aa.actions(store, "pools-of-darkness"):
        assert action.game is None
        with pytest.raises(AttributeError):
            action.descriptor
        action.legality(world.target)
    out = acts(store, "pools-of-darkness")["heal"].apply(world.target)
    assert out.ok and out.writes == ((BASE + 0x10, b"\x09"),)


def test_the_watcher_fires_once_when_combat_ends(world, store):
    world.target.mem[BASE + 0x30] = 0x80
    world.members = [Member("A", BASE, 5, 9, quickfight=True)]
    watcher = aa.AmigaQuickfightWatcher(
        aa.AmigaClearQuickfight("curse-of-the-azure-bonds"), enabled=True)
    fired = []
    for mode in (0, 2, 2, 0, 0):
        world.mode = mode
        fired.append(watcher.poll(world.target))
    assert [o is not None for o in fired] == [False, False, False, True, False]
    assert world.target.mem[BASE + 0x30] == 0


def test_a_disabled_watcher_never_fires(world, store):
    watcher = aa.AmigaQuickfightWatcher(
        aa.AmigaClearQuickfight("curse-of-the-azure-bonds"))
    for mode in (2, 0):
        world.mode = mode
        assert watcher.poll(world.target) is None


def test_heal_writes_a_wide_field_big_endian_and_never_past_the_ceiling(world, store):
    world.row = make_row(hp=Spot(offset=0x10, length=2, mask=0xFFFF))
    world.members = [Member("A", BASE, 3, 300)]
    out = acts(store)["heal"].apply(world.target)
    assert out.writes == ((BASE + 0x10, (300).to_bytes(2, "big")),)
    # A maximum above what two bytes hold is clamped to the ceiling.
    world.members = [Member("A", BASE, 3, 70000)]
    out = acts(store)["heal"].apply(world.target)
    assert out.writes == ((BASE + 0x10, b"\xff\xff"),)
    assert out.notes == ()


def test_a_partial_mask_on_an_overwritten_field_is_refused(world, store):
    for field, name in (("hp", "heal"), ("memorised", "restore-spells")):
        world.row = make_row(**{field: Spot(offset=0x10, length=1, mask=0x0F)})
        assert acts(store)[name].legality(world.target).reason == aa.NOT_BUILT
    world.row = make_row(hp=None)
    assert acts(store)["heal"].legality(world.target).reason == aa.NOT_BUILT


def test_restore_with_nothing_to_change_is_a_no_op(world, store):
    store.put("amiga/curse-of-the-azure-bonds", "A", b"\x01\x02")
    world.members = [Member("A", BASE, 5, 9, memorised=b"\x01\x02\x00\x00")]
    out = acts(store)["restore-spells"].apply(world.target)
    assert out.ok and out.writes == ()
    assert out.message == "Spellcasters have already memorized their spells."


def test_restore_skips_a_list_longer_than_the_record_without_a_note(world, store):
    store.put("amiga/curse-of-the-azure-bonds", "A", bytes(9))
    world.members = [Member("A", BASE, 5, 9, memorised=bytes(4))]
    out = acts(store)["restore-spells"].apply(world.target)
    assert out.writes == () and out.notes == ()


def test_identify_with_nothing_hidden_says_so(world, store):
    clean = bytes(16)
    world.members = [Member("A", BASE, 5, 9, nodes=((0x300, clean),))]
    out = acts(store)["identify"].apply(world.target)
    assert out.ok and out.writes == () and out.message == "No items to identify."


def test_identify_skips_a_node_too_short_and_goes_on(world, store):
    good = bytearray(16)
    good[6] = 0x01
    world.members = [Member("A", BASE, 5, 9,
                            nodes=((0x300, b"\x00\x00"), (0x320, bytes(good))))]
    out = acts(store)["identify"].apply(world.target)
    assert out.writes == ((0x326, b"\x00"),)


def test_a_key_for_another_title_than_the_target_is_not_built(world, store):
    world.members = [Member("A", BASE, 3, 9, memorised=bytes(4))]
    for action in aa.actions(store, "secret-of-the-silver-blades"):
        assert action.legality(world.target).reason == aa.NOT_BUILT
        action.run(world.target)
    assert world.target.mem[BASE + 0x10] == 0
    assert store.get("amiga/secret-of-the-silver-blades", "A") is None


def test_mode_is_read_through_the_unwrapped_target(world, store, monkeypatch):
    seen = []
    fake = aa._parties()
    monkeypatch.setattr(aa, "_parties", lambda: SimpleNamespace(
        row_for=fake.row_for, read_party=fake.read_party,
        mode=lambda t: seen.append(t) or 0))
    assert acts(store)["heal"].legality(Forward(world.target))
    assert seen == [world.target]


@pytest.fixture
def fresh_import(monkeypatch):
    monkeypatch.setattr(aa, "_cached", aa._UNSET)
    monkeypatch.setattr(aa, "_logged", False)
    return monkeypatch


def test_a_missing_amigaparty_is_none_and_is_looked_for_once(fresh_import):
    calls = []

    def fail(name):
        calls.append(name)
        raise ModuleNotFoundError(name=name)

    fresh_import.setattr(importlib, "import_module", fail)
    assert aa._parties() is None and aa._parties() is None
    assert calls == ["automap.amigaparty"]


def test_a_module_not_found_for_another_module_is_raised(fresh_import, caplog):
    def fail(name):
        raise ModuleNotFoundError(name="elsewhere")

    fresh_import.setattr(importlib, "import_module", fail)
    for _ in range(2):
        with pytest.raises(ModuleNotFoundError):
            aa._parties()
    assert len(caplog.records) == 1


def test_an_import_error_is_raised_and_logged_once(fresh_import, caplog):
    def fail(name):
        raise ImportError("cannot import name")

    fresh_import.setattr(importlib, "import_module", fail)
    for _ in range(2):
        with pytest.raises(ImportError):
            aa._parties()
    assert len(caplog.records) == 1
