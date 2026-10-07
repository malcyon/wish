from __future__ import annotations

"""The Pools of Darkness folder row in File > Preferences > Game disks.

The row exists only while `WISH_EXPERIMENTAL_AMIGA_FSUAE` is on, counts the
title's loose `.adf` images by the volume names `automap.maps` recognises, and
is what lets a window holding another title switch to Pools of Darkness when
the machine turns out to be running it. The disks here are synthetic and hold
no game data.
"""

import struct

import pytest
from gamedata import synthetic_geo

from automap import c64, paths
from automap.area import RESIDENT_GEO
from automap.config import Settings
from automap.maps import AMIGA_ONLY_TITLES
from automap.target import MemoryTarget
from goldbox import c64_port
from goldbox.amiga_adf import AmigaDisk
from goldbox.geo import (
    BARRIERS,
    GRID,
    SOLID,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
    Geo,
)
from wish import backends as bk
from wish import preferences
from wish.preferences import PreferencesDialog, title_folder_report
from wish.window import SWITCHED_TITLE

POD = AMIGA_ONLY_TITLES[0]
POOL = c64_port.POOL_OF_RADIANCE

pytestmark = pytest.mark.usefixtures("no_registry")

#: What the row's line says when a folder is set and holds no Pools of
#: Darkness disk image, as the player reads it.
NONE_FOUND = "None; no .adf disk images here"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    monkeypatch.delenv("POR_DISKS", raising=False)
    monkeypatch.delenv(bk.AMIGA_FSUAE_ENV, raising=False)
    monkeypatch.delenv(bk.AMIGA_WINUAE_ENV, raising=False)
    monkeypatch.delenv("WISH_EXPERIMENTAL_POD_CONVERT", raising=False)
    preferences._scan.cache_clear()


@pytest.fixture
def amiga_on(monkeypatch):
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, "1")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def nowhere(tmp_path, monkeypatch):
    empty = tmp_path / "empty-home"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "_home", lambda: empty)
    monkeypatch.chdir(empty)


def window(app, **kw):
    from wish.session import Session
    from wish.window import WishWindow
    kw.setdefault("maps", {})
    win = WishWindow(None, session=Session(find=lambda pref=None: None), **kw)
    win.announce = lambda title, text: None
    return win


def glib(maps: dict[int, bytes]) -> bytes:
    """A `GEO.GLB`: the index block, then one block per map."""
    ids = sorted(maps)
    index = struct.pack(">H", len(ids)) + b"".join(
        struct.pack(">HH", ident, n + 1) for n, ident in enumerate(ids))
    blocks = [index] + [maps[i] for i in ids]
    body = b"".join(blocks)
    head = (b"GLIB" + struct.pack(">I", len(body))
            + struct.pack(">HH", len(blocks), 0) + b"GEO ")
    offsets, at = [], len(head) + 4 * (len(blocks) + 1)
    for block in blocks:
        offsets.append(at)
        at += len(block)
    offsets.append(at)
    return head + b"".join(struct.pack(">I", o) for o in offsets) + body


def adf(folder, filename: str, volume: str, geo: Geo | None = None):
    """A blank Amiga disk named `volume`, with one map under `DISK3` if given."""
    image = AmigaDisk.blank(volume)
    if geo is not None:
        image.make_dir("DISK3")
        image.write_file("DISK3/GEO.GLB", glib({0x24: geo.to_bytes()}))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_bytes(image.to_bytes())
    return folder


def walled_geo(art: int = 1, rooms: int = 4) -> Geo:
    planes = bytearray(synthetic_geo())
    for y in range(GRID):
        for x in range(GRID):
            at = y * GRID + x
            if x % rooms == 0 and x:
                planes[WALLS_SOUTH_WEST + at] |= art
                planes[WALLS_NORTH_EAST + at - 1] |= art
                planes[BARRIERS + at] |= SOLID << 6
    return Geo(bytes(planes))


def machine(resident: Geo) -> MemoryTarget:
    blocks = {0xD011: bytes([0x1B]), 0xD018: bytes([0x15]), 0xDD00: bytes([0x17]),
              c64.DEFAULT.live_position: bytes((4, 5, 0)),
              RESIDENT_GEO: resident.to_bytes()}
    return MemoryTarget(blocks)


def ticked(binding, times: int = 24):
    for _ in range(times):
        binding.tick()
    return binding


def pool_folder(tmp_path, geo: Geo):
    """A Pool of Radiance C64 disk with one readable map."""
    from gamedata import _disk_with
    folder = tmp_path / "por"
    folder.mkdir()
    (folder / "POOL1.D64").write_bytes(_disk_with([(b"GEO00", geo.to_bytes())]))
    return folder


# --- the row exists only behind the flag -------------------------------------

def test_the_row_is_absent_by_default(app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert POD.key not in dialog.game_folder_edits
        assert set(dialog.game_folder_edits) == {
            g.key for g in preferences.GAME_FOLDER_TITLES}
        assert dialog.findChild(preferences.QLineEdit,
                                "game_folder_edit_pools_of_darkness") is None
        assert preferences.game_folder_titles() == preferences.GAME_FOLDER_TITLES
    finally:
        win.close()


@pytest.mark.parametrize("value", ["0", "off", "false", "no", "", "junk"])
def test_a_forgotten_setting_does_not_add_the_row(app, tmp_path, monkeypatch,
                                                  value):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, value)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert POD.key not in dialog.game_folder_edits
        assert dialog.findChild(preferences.QLineEdit,
                                "game_folder_edit_pools_of_darkness") is None
    finally:
        win.close()


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_the_flag_adds_the_row_after_silver_blades(app, tmp_path, monkeypatch,
                                                   value):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, value)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert list(dialog.game_folder_edits) == [
            g.key for g in preferences.GAME_FOLDER_TITLES] + [POD.key]
        label = dialog.findChild(preferences.QLabel,
                                 "game_folder_label_pools_of_darkness")
        assert label.text() == "Pools of Darkness"
        edit = dialog.game_folder_edits[POD.key]
        assert edit.placeholderText() == preferences.FOLDER_PLACEHOLDER
        group = dialog.ui.game_folder_group_pools_of_darkness
        silver = dialog.ui.game_folder_note_secret_of_the_silver_blades
        layout = dialog.ui.disks_group_layout
        assert (layout.indexOf(group)
                == layout.indexOf(silver) + 1)
    finally:
        win.close()


# --- the Fast travel page exists only behind the flag --------------------------

def travel_tab_texts(dialog):
    tabs = dialog.travel_tabs
    return [tabs.tabText(i) for i in range(tabs.count())]


def test_the_travel_page_is_absent_by_default(app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert POD.title not in travel_tab_texts(dialog)
        assert POD.key not in dialog.travel_tables
        assert preferences.travel_titles() == preferences.TRAVEL_TITLES
        assert dialog.findChild(preferences.QTableWidget,
                                "travel_table_pools_of_darkness") is None
    finally:
        win.close()


@pytest.mark.parametrize("env", [bk.AMIGA_FSUAE_ENV, bk.AMIGA_WINUAE_ENV])
@pytest.mark.parametrize("value", ["0", "off"])
def test_a_forgotten_setting_does_not_add_the_travel_page(
        app, tmp_path, monkeypatch, env, value):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv(env, value)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert POD.title not in travel_tab_texts(dialog)
        assert POD.key not in dialog.travel_tables
    finally:
        win.close()


def test_the_conversion_flag_alone_does_not_add_the_travel_page(
        app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv("WISH_EXPERIMENTAL_POD_CONVERT", "1")
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert POD.key in dialog.game_folder_edits
        assert POD.title not in travel_tab_texts(dialog)
        assert POD.key not in dialog.travel_tables
    finally:
        win.close()


@pytest.mark.parametrize("env", [bk.AMIGA_FSUAE_ENV, bk.AMIGA_WINUAE_ENV])
def test_the_flag_adds_the_travel_page_after_silver_blades(
        app, tmp_path, monkeypatch, env):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv(env, "1")
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert travel_tab_texts(dialog) == [
            g.title for g in preferences.TRAVEL_TITLES] + [POD.title]
        assert POD.key in dialog.travel_tables
    finally:
        win.close()


def test_the_travel_page_lists_only_destinations(app, tmp_path, monkeypatch,
                                                 amiga_on):
    from goldbox import areas

    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        listed = {row.id for row in dialog.travel_rows[POD.key]}
        assert listed == {a.id for a in areas.areas_for_title(POD.title)
                          if a.fasttravelable}
        assert 84 not in listed
        assert dialog.travel_tables[POD.key].rowCount() == len(listed)
        assert dialog.travel_ticked(POD) == []
    finally:
        win.close()


def test_a_pools_of_darkness_window_opens_on_its_page(app, tmp_path,
                                                      monkeypatch, amiga_on):
    nowhere(tmp_path, monkeypatch)
    win = window(app, title=POD.title)
    try:
        dialog = PreferencesDialog(win)
        assert dialog.travel_tabs.tabText(
            dialog.travel_tabs.currentIndex()) == POD.title
    finally:
        win.close()


def test_ticking_a_pools_of_darkness_area_files_it_under_its_key(
        app, tmp_path, monkeypatch, amiga_on):
    from PyQt6.QtCore import Qt

    from goldbox import areas

    nowhere(tmp_path, monkeypatch)
    aerie = next(a for a in areas.areas_for_title(POD.title) if a.id == 33)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        table = dialog.travel_tables[POD.key]
        row = next(i for i, a in enumerate(dialog.travel_rows[POD.key])
                   if a.id == aerie.id)
        table.item(row, 0).setCheckState(Qt.CheckState.Checked)
        assert win.settings.fast_travel_targets == {POD.key: [33]}
        assert Settings.load().chosen_areas(POD) == (33,)
        assert dialog.travel_notes[POD.key].text() == (
            "1 area in the Fast Travel list.")
    finally:
        win.close()


# --- what the row's line says -------------------------------------------------

def test_the_line_counts_the_pools_of_darkness_images(app, tmp_path,
                                                      monkeypatch, amiga_on):
    nowhere(tmp_path, monkeypatch)
    folder = tmp_path / "pod"
    adf(folder, "a.adf", "POD 1")
    assert title_folder_report(str(folder), POD) == "1 disk"
    adf(folder, "b.adf", "POD 2")
    adf(folder, "c.ADF", "Pools Of Darkness 1")
    assert title_folder_report(str(folder), POD) == "3 disks"

    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        dialog.set_game_folder(POD, str(folder))
        assert dialog.game_folder_reports[POD.key].text() == "3 disks"
        assert not dialog.game_folder_reports[POD.key].isHidden()
    finally:
        win.close()


def test_a_folder_with_no_pools_of_darkness_image_says_none(app, tmp_path,
                                                            monkeypatch,
                                                            amiga_on):
    nowhere(tmp_path, monkeypatch)
    folder = tmp_path / "elsewhere"
    adf(folder, "pool.adf", "poolgame")             # Pool of Radiance's disk
    (folder / "notes.adf").write_bytes(b"not a disk")
    (folder / "POOL1.D64").write_bytes(b"")
    assert title_folder_report(str(folder), POD) == "none; no .adf disk images here"
    assert title_folder_report(str(tmp_path / "missing"), POD) == (
        "none; no .adf disk images here")

    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert dialog.game_folder_reports[POD.key].isHidden()   # nothing typed
        dialog.set_game_folder(POD, str(folder))
        assert dialog.game_folder_reports[POD.key].text() == NONE_FOUND
    finally:
        win.close()


def test_the_other_rows_lines_are_unchanged(tmp_path):
    folder = tmp_path / "none"
    folder.mkdir()
    assert title_folder_report(str(folder), POOL) == (
        f"none; no {preferences._pretty(POOL.disk_glob)} here")


def test_the_titles_line_names_the_pools_of_darkness_disks(tmp_path,
                                                           monkeypatch,
                                                           amiga_on):
    nowhere(tmp_path, monkeypatch)
    folder = tmp_path / "pod"
    adf(folder, "a.adf", "POD 1")
    adf(folder, "b.adf", "POD 2")
    rows = dict(preferences.report(Settings(), flag=str(folder)))
    assert rows["Titles"] == "Pools of Darkness (2 disks)"


def test_the_titles_line_ignores_adf_images_while_the_flag_is_off(tmp_path,
                                                                  monkeypatch):
    nowhere(tmp_path, monkeypatch)
    folder = tmp_path / "pod"
    adf(folder, "a.adf", "POD 1")
    rows = dict(preferences.report(Settings(), flag=str(folder)))
    assert "Pools of Darkness" not in rows["Titles"]


# --- saving the setting -------------------------------------------------------

def test_the_folder_is_saved_under_the_titles_key(app, tmp_path, monkeypatch,
                                                  amiga_on):
    nowhere(tmp_path, monkeypatch)
    folder = tmp_path / "pod"
    adf(folder, "a.adf", "POD 1")
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        dialog.set_game_folder(POD, str(folder))
        assert win.settings.game_folders == {POD.key: str(folder)}
        assert Settings.load().game_folders == {POD.key: str(folder)}

        reopened = PreferencesDialog(win)
        assert reopened.game_folder_edits[POD.key].text() == str(folder)

        dialog.set_game_folder(POD, "")
        assert Settings.load().game_folders == {}
    finally:
        win.close()


def test_the_folder_resolves_for_the_title(tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    folder = tmp_path / "pod"
    settings = Settings(game_folders={POD.key: str(folder)})
    assert paths.resolve_disks(game=POD, settings=settings) == (
        folder, paths.GAME_PREFERENCE)
    assert paths.resolve_disks(game=POOL, settings=settings) == (
        None, paths.NOWHERE)
    # No folder set: a title with no C64 pattern searches nothing.
    assert paths.resolve_disks(game=POD, settings=Settings()) == (
        None, paths.NOWHERE)


# --- switching to Pools of Darkness from its folder ---------------------------

def test_a_window_holding_pool_of_radiance_switches_to_pools_of_darkness(
        app, tmp_path, monkeypatch, amiga_on):
    nowhere(tmp_path, monkeypatch)
    pod_geo = walled_geo(art=5, rooms=3)
    por = pool_folder(tmp_path, walled_geo(art=1))
    pod = adf(tmp_path / "pod", "d3.adf", "POD 3", pod_geo)
    settings = Settings(game_folders={POOL.key: str(por), POD.key: str(pod)})

    win = window(app, maps=None, settings=settings)
    try:
        assert win.map.state.title == POOL.title
        win.mapper.target = machine(pod_geo)
        ticked(win.map)

        assert win.map.state.title == POD.title
        assert str(win.disks) == str(pod)
        assert win.disks_source == paths.GAME_PREFERENCE
        assert "GEO24" in win.mapper._maps
        said = [line.split("  ", 1)[-1] for line in win.map.messages.lines()]
        assert SWITCHED_TITLE.format(title=POD.title) in said

        # The switch survives a reload: the window keeps its title.
        win.reload_disks()
        assert win.map.state.title == POD.title
        assert str(win.disks) == str(pod)

        # Preferences over the switched window reports that folder.
        dialog = PreferencesDialog(win)
        assert dialog.ui.report_in_use.text() == str(pod)
        assert dialog.ui.report_titles.text() == "Pools of Darkness (1 disk)"
        assert dialog.game_folder_reports[POD.key].text() == "1 disk"

        # Clearing the row while on it does not take the window down.
        dialog.set_game_folder(POD, "")
        assert win.disks is None
    finally:
        win.close()


def test_without_the_flag_the_window_does_not_switch(app, tmp_path,
                                                     monkeypatch):
    from automap.window import WRONG_GAME
    nowhere(tmp_path, monkeypatch)
    pod_geo = walled_geo(art=5, rooms=3)
    por = pool_folder(tmp_path, walled_geo(art=1))
    pod = adf(tmp_path / "pod", "d3.adf", "POD 3", pod_geo)
    settings = Settings(game_folders={POOL.key: str(por), POD.key: str(pod)})

    win = window(app, maps=None, settings=settings)
    try:
        assert win.map.other_maps() == {}
        win.mapper.target = machine(pod_geo)
        ticked(win.map)
        assert win.map.state.title == POOL.title
        assert WRONG_GAME in [line.split("  ", 1)[-1]
                              for line in win.map.messages.lines()]
    finally:
        win.close()


# --- starting with only the Pools of Darkness folder set ---------------------

def _only_pod(tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    pod = adf(tmp_path / "pod", "d3.adf", "POD 3", walled_geo(art=5, rooms=3))
    return Settings(game_folders={POD.key: str(pod)}), pod


def test_the_folder_answers_with_no_title_when_asked_for(tmp_path, monkeypatch):
    settings, pod = _only_pod(tmp_path, monkeypatch)
    assert paths.resolve_disks(game=None, settings=settings,
                               also=AMIGA_ONLY_TITLES) == (
        pod, paths.GAME_PREFERENCE)
    assert paths.resolve_disks(game=None, settings=settings) == (
        None, paths.NOWHERE)


def test_a_pool_of_radiance_row_still_answers_first(tmp_path, monkeypatch):
    settings, pod = _only_pod(tmp_path, monkeypatch)
    por = pool_folder(tmp_path, walled_geo(art=1))
    settings.game_folders[POOL.key] = str(por)
    assert paths.resolve_disks(game=None, settings=settings,
                               also=AMIGA_ONLY_TITLES) == (
        por, paths.GAME_PREFERENCE)


def test_the_titles_to_try_come_from_the_flag(monkeypatch):
    assert bk.amiga_only_titles() == ()
    for off in ("", "0", "off"):
        monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, off)
        assert bk.amiga_only_titles() == ()
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, "1")
    assert bk.amiga_only_titles() == AMIGA_ONLY_TITLES


def test_a_winuae_only_player_gets_the_pod_folder_and_its_maps(
        app, tmp_path, monkeypatch):
    settings, pod = _only_pod(tmp_path, monkeypatch)
    monkeypatch.delenv(bk.AMIGA_FSUAE_ENV, raising=False)
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, "1")
    assert bk.amiga_only_titles() == AMIGA_ONLY_TITLES
    win = window(app, maps=None, settings=settings)
    try:
        assert win.map.state.title == POD.title
        assert "GEO24" in win.mapper._maps
    finally:
        win.close()


def test_a_winuae_only_player_gets_the_pod_folder_row(
        app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.delenv(bk.AMIGA_FSUAE_ENV, raising=False)
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, "1")
    assert preferences.game_folder_titles() == (
        preferences.GAME_FOLDER_TITLES + AMIGA_ONLY_TITLES)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert POD.key in dialog.game_folder_edits
        assert dialog.findChild(preferences.QLabel,
                                "game_folder_label_pools_of_darkness") is not None
    finally:
        win.close()


def test_a_window_with_only_the_pod_folder_names_its_title(
        app, tmp_path, monkeypatch, amiga_on):
    settings, pod = _only_pod(tmp_path, monkeypatch)
    win = window(app, maps=None, settings=settings)
    try:
        assert win.map.state.title == POD.title
        assert "GEO24" in win.mapper._maps
        assert str(win.disks) == str(pod)
        win.reload_disks()
        assert win.map.state.title == POD.title
        assert "GEO24" in win.mapper._maps
    finally:
        win.close()


@pytest.mark.parametrize("value", [None, "", "0", "off"])
def test_without_the_flag_the_pod_folder_is_not_taken(
        app, tmp_path, monkeypatch, value):
    settings, _pod = _only_pod(tmp_path, monkeypatch)
    if value is not None:
        monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, value)
    win = window(app, maps=None, settings=settings)
    try:
        assert win.disks is None
        assert win.mapper._maps == {}
        assert win.map.state.title != POD.title
    finally:
        win.close()


def test_a_pool_of_radiance_folder_added_later_moves_the_window(
        app, tmp_path, monkeypatch, amiga_on):
    settings, pod = _only_pod(tmp_path, monkeypatch)
    por = pool_folder(tmp_path, walled_geo(art=1))
    win = window(app, maps=None, settings=settings)
    try:
        assert win.map.state.title == POD.title
        settings.game_folders[POOL.key] = str(por)
        win.reload_disks()
        assert win.map.state.title == POOL.title
        assert str(win.disks) == str(por)
    finally:
        win.close()


def test_the_dialog_reports_the_folder_the_window_uses(
        app, tmp_path, monkeypatch, amiga_on):
    settings, pod = _only_pod(tmp_path, monkeypatch)
    win = window(app, maps=None, settings=settings)
    try:
        rows = dict(preferences.report(settings))
        assert rows["In use"] == str(win.disks) == str(pod)
    finally:
        win.close()


def test_the_titles_line_of_a_pools_window_names_adf_images(
        tmp_path, monkeypatch, amiga_on):
    nowhere(tmp_path, monkeypatch)
    empty = tmp_path / "empty"
    empty.mkdir()
    rows = dict(preferences.report(Settings(), flag=str(empty), game=POD))
    assert rows["Titles"] == "none; no .adf disk images here"
    rows = dict(preferences.report(Settings(), game=POD))
    assert rows["Titles"] == "none; nowhere with .adf disk images in it was found"


def test_the_titles_line_of_a_c64_window_keeps_its_patterns(
        tmp_path, monkeypatch, amiga_on):
    nowhere(tmp_path, monkeypatch)
    empty = tmp_path / "empty"
    empty.mkdir()
    glob = preferences._pretty(POOL.disk_glob)
    rows = dict(preferences.report(Settings(), flag=str(empty), game=POOL))
    assert rows["Titles"] == f"none; no {glob} here"
    rows = dict(preferences.report(Settings(), game=POOL))
    assert rows["Titles"] == f"none; nowhere with {glob} in it was found"


def test_the_dialog_capitalises_the_composed_titles_line(
        app, tmp_path, monkeypatch, amiga_on):
    nowhere(tmp_path, monkeypatch)
    empty = tmp_path / "empty"
    empty.mkdir()
    win = window(app)
    try:
        win.disks_flag = str(empty)
        win._title = POD.title
        dialog = PreferencesDialog(win)
        dialog.refresh()
        assert dialog.report_rows["Titles"].text() == NONE_FOUND
    finally:
        win.close()


# --- the conversion flag keeps the row too ------------------------------------

POD_CONVERT_ENV = "WISH_EXPERIMENTAL_POD_CONVERT"


def dos_install(folder, launcher="START.BAT", config="POOL4.CFG"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / launcher).write_bytes(b"")
    (folder / config).write_bytes(b"")
    return folder


def test_the_row_is_absent_with_neither_flag(app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    win = window(app)
    try:
        assert POD.key not in PreferencesDialog(win).game_folder_edits
    finally:
        win.close()


@pytest.mark.parametrize("value", ["0", "off", "false", "no", "", "junk"])
def test_a_forgotten_conversion_setting_does_not_add_the_row(
        app, tmp_path, monkeypatch, value):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv(POD_CONVERT_ENV, value)
    win = window(app)
    try:
        assert POD.key not in PreferencesDialog(win).game_folder_edits
        assert preferences.game_folder_titles() == preferences.GAME_FOLDER_TITLES
    finally:
        win.close()


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_the_conversion_flag_alone_adds_the_row(app, tmp_path, monkeypatch,
                                                value):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv(POD_CONVERT_ENV, value)
    win = window(app)
    try:
        dialog = PreferencesDialog(win)
        assert POD.key in dialog.game_folder_edits
        assert dialog.findChild(preferences.QLineEdit,
                                "game_folder_edit_pools_of_darkness")
    finally:
        win.close()


def test_the_dos_install_note_is_not_worded_yet():
    assert preferences.DOS_INSTALL_NOTE == ""


def test_the_report_for_each_kind_of_folder(tmp_path):
    only_dos = dos_install(tmp_path / "dos")
    assert title_folder_report(str(only_dos), POD) == ""

    only_images = tmp_path / "images"
    adf(only_images, "a.adf", "POD 1")
    assert title_folder_report(str(only_images), POD) == "1 disk"

    both = dos_install(tmp_path / "both")
    adf(both, "a.adf", "POD 1")
    adf(both, "b.adf", "POD 2")
    assert title_folder_report(str(both), POD) == "2 disks"

    neither = tmp_path / "neither"
    neither.mkdir()
    assert title_folder_report(str(neither), POD) == (
        "none; no .adf disk images here")


def test_another_titles_dos_install_counts_as_neither(tmp_path):
    curse = dos_install(tmp_path / "curse", "START.EXE", "CURSE.CFG")
    assert title_folder_report(str(curse), POD) == (
        "none; no .adf disk images here")
    assert title_folder_report(str(curse), POOL) == (
        f"none; no {preferences._pretty(POOL.disk_glob)} here")


def test_the_titles_line_names_the_title_for_a_dos_install(tmp_path,
                                                           monkeypatch):
    nowhere(tmp_path, monkeypatch)
    folder = dos_install(tmp_path / "dos")
    rows = dict(preferences.report(Settings(), flag=str(folder), game=POD))
    assert rows["Titles"] == POD.title


def test_the_titles_line_and_the_row_agree_on_a_dos_install(tmp_path,
                                                            monkeypatch):
    nowhere(tmp_path, monkeypatch)
    folder = dos_install(tmp_path / "dos")
    assert preferences._is_dos_install(folder, POD)
    assert title_folder_report(str(folder), POD) == preferences.DOS_INSTALL_NOTE
    assert not preferences._is_dos_install(folder, POOL)


def test_the_titles_line_of_an_empty_folder_is_unchanged(tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    empty = tmp_path / "empty"
    empty.mkdir()
    rows = dict(preferences.report(Settings(), flag=str(empty), game=POD))
    assert rows["Titles"] == "none; no .adf disk images here"


def test_the_titles_line_of_an_amiga_folder_is_unchanged(tmp_path, monkeypatch,
                                                         amiga_on):
    nowhere(tmp_path, monkeypatch)
    folder = tmp_path / "pod"
    adf(folder, "a.adf", "POD 1")
    rows = dict(preferences.report(Settings(), flag=str(folder), game=POD))
    assert rows["Titles"] == "Pools of Darkness (1 disk)"


def test_another_titles_dos_install_does_not_name_the_title(tmp_path,
                                                            monkeypatch):
    nowhere(tmp_path, monkeypatch)
    curse = dos_install(tmp_path / "curse", "START.EXE", "CURSE.CFG")
    rows = dict(preferences.report(Settings(), flag=str(curse), game=POD))
    assert rows["Titles"] == "Curse of the Azure Bonds"


@pytest.mark.parametrize("game", [None, POOL])
def test_the_titles_line_names_a_dos_install_on_any_title(tmp_path, monkeypatch,
                                                          amiga_on, game):
    nowhere(tmp_path, monkeypatch)
    folder = dos_install(tmp_path / "dos")
    rows = dict(preferences.report(Settings(), flag=str(folder), game=game))
    assert rows["Titles"] == POD.title


def test_another_titles_dos_install_is_not_named_with_no_title(tmp_path,
                                                               monkeypatch):
    nowhere(tmp_path, monkeypatch)
    curse = dos_install(tmp_path / "curse", "START.EXE", "CURSE.CFG")
    rows = dict(preferences.report(Settings(), flag=str(curse)))
    assert POD.title not in rows["Titles"]


@pytest.mark.parametrize("value", ["0", "off", "", "junk"])
def test_a_forgotten_conversion_setting_adds_no_title_to_try(monkeypatch, value):
    monkeypatch.setenv(POD_CONVERT_ENV, value)
    assert bk.amiga_only_titles() == ()


def test_the_conversion_flag_alone_makes_the_pools_folder_the_one_in_use(
        app, tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv(POD_CONVERT_ENV, "1")
    folder = dos_install(tmp_path / "DARKNESS")
    settings = Settings(game_folders={POD.key: str(folder)})
    assert bk.amiga_only_titles() == AMIGA_ONLY_TITLES
    rows = dict(preferences.report(settings))
    assert rows["In use"] == str(folder)
    assert rows["Titles"] == POD.title
    win = window(app, maps=None, settings=settings)
    try:
        assert str(win.disks) == str(folder)
        assert str(win.editor.disks) == str(folder)
    finally:
        win.close()


def test_the_conversion_flag_alone_shows_no_amiga_titles_in_the_scan(
        tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv(POD_CONVERT_ENV, "1")
    folder = tmp_path / "pod"
    adf(folder, "a.adf", "POD 1")
    assert preferences._scan(str(folder), bk.amiga_enabled())["titles"] == []


CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS


def curse_dos_install(folder):
    return dos_install(folder, "START.EXE", "CURSE.CFG")


@pytest.mark.parametrize("game", [None, CURSE])
def test_the_titles_line_names_a_curse_dos_install(tmp_path, monkeypatch, game):
    nowhere(tmp_path, monkeypatch)
    folder = curse_dos_install(tmp_path / "curse")
    rows = dict(preferences.report(Settings(), flag=str(folder), game=game))
    assert rows["Titles"] == CURSE.title


def test_a_curse_dos_install_row_has_the_empty_note(tmp_path):
    folder = curse_dos_install(tmp_path / "curse")
    assert preferences._is_dos_install(folder, CURSE)
    assert title_folder_report(str(folder), CURSE) == preferences.DOS_INSTALL_NOTE


def test_a_curse_dos_install_in_another_titles_row_does_not_claim_it(tmp_path):
    folder = curse_dos_install(tmp_path / "curse")
    assert not preferences._is_dos_install(folder, POOL)
    assert title_folder_report(str(folder), POOL) == (
        f"none; no {preferences._pretty(POOL.disk_glob)} here")
    assert title_folder_report(str(folder), POD) == (
        "none; no .adf disk images here")


def test_a_c64_disk_folder_keeps_its_disk_count(tmp_path, monkeypatch):
    nowhere(tmp_path, monkeypatch)
    folder = pool_folder(tmp_path, walled_geo(art=1))
    assert title_folder_report(str(folder), POOL) == "1 disk"
    rows = dict(preferences.report(Settings(), flag=str(folder), game=POOL))
    assert rows["Titles"] == f"{POOL.title} (1 disk)"


def test_a_pools_of_darkness_dos_install_is_still_named_alone(tmp_path,
                                                              monkeypatch,
                                                              amiga_on):
    nowhere(tmp_path, monkeypatch)
    folder = dos_install(tmp_path / "dos")
    rows = dict(preferences.report(Settings(), flag=str(folder), game=CURSE))
    assert rows["Titles"] == POD.title
    assert title_folder_report(str(folder), POD) == preferences.DOS_INSTALL_NOTE


@pytest.mark.parametrize("game", [None, POOL])
def test_with_both_flags_off_a_pools_dos_install_is_not_named(tmp_path,
                                                              monkeypatch,
                                                              game):
    nowhere(tmp_path, monkeypatch)
    folder = dos_install(tmp_path / "dos")
    rows = dict(preferences.report(Settings(), flag=str(folder), game=game))
    assert POD.title not in rows["Titles"]


@pytest.mark.parametrize("env", [bk.AMIGA_FSUAE_ENV, bk.AMIGA_WINUAE_ENV,
                                 POD_CONVERT_ENV])
@pytest.mark.parametrize("game", [None, POOL])
def test_with_either_flag_on_a_pools_dos_install_is_named(tmp_path, monkeypatch,
                                                          env, game):
    nowhere(tmp_path, monkeypatch)
    monkeypatch.setenv(env, "1")
    folder = dos_install(tmp_path / "dos")
    rows = dict(preferences.report(Settings(), flag=str(folder), game=game))
    assert rows["Titles"] == POD.title
