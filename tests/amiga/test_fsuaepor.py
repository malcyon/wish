"""The pure parts of `tools/amiga/fsuaepor.py`, and what its recorded run shows.

The name-field and capture helpers need nothing. The last three tests read the
`por-amiga-ff-names` specimen -- the party panel and character sheet Amiga
Pool of Radiance drew in FS-UAE -- and skip when the specimen tree does not
have it, which is what CI does.
"""

from __future__ import annotations

import pytest

from goldbox import amiga_savegame
from goldbox.amiga_adf import AmigaDisk
from tools.amiga import amiganamespaces, fsuaepor


def test_parse_name_reads_python_escapes_as_single_bytes():
    assert fsuaepor.parse_name(r"MARY\xffSUE") == b"MARY\xffSUE"
    assert fsuaepor.parse_name("A  B") == b"A  B"


def test_set_name_changes_the_name_field_and_nothing_else():
    record = bytes(range(256)) + bytes(32)
    after = fsuaepor.set_name(record, b"J. R")
    assert after[:16] == b"J. R" + bytes(12)
    assert after[16:] == record[16:]
    assert len(after) == len(record)


def test_set_name_refuses_a_name_with_no_room_for_its_nul():
    with pytest.raises(ValueError):
        fsuaepor.set_name(bytes(288), b"ABCDEFGHIJKLMNOP")


def test_name_of_stops_at_the_first_nul_and_keeps_the_residue():
    field = b"MARYSUEFOX\x00x\x00\x00\x00\x00"
    name, whole = fsuaepor.name_of(field + bytes(272))
    assert name == b"MARYSUEFOX"
    assert whole == field


def test_drop_slot_removes_the_files_and_the_letter():
    disk = AmigaDisk.blank("poolgame")
    disk.make_dir("save")
    for name in ("CHRDATD1.sav", "CHRDATD1.itm", "savgamD.dat",
                 "CHRDATE1.sav", "savgamE.dat"):
        disk.write_file(f"save/{name}", b"x")
    disk.write_file("save/save", amiga_savegame.slot_list_bytes("DE"))
    gone = fsuaepor.drop_slot(disk, "D")
    assert gone == ["CHRDATD1.itm", "CHRDATD1.sav", "savgamD.dat"]
    assert amiga_savegame.read_slot_list(disk) == ["E"]
    assert disk.read_file("save/CHRDATE1.sav") == b"x"


class _Picture:
    """A grab with ink at the given columns on every row."""

    def __init__(self, inked: set[int]):
        self.inked = inked

    def getpixel(self, at):
        return (255, 255, 255) if at[0] in self.inked else (0, 0, 0)


def test_glyph_runs_and_blank_cells_on_a_drawn_row():
    # Two 10-pixel glyphs with a 2-pixel gap, then one blank 12-pixel cell.
    inked = set(range(0, 10)) | set(range(12, 22)) | set(range(36, 46))
    runs = fsuaepor.glyph_runs(_Picture(inked), (0, 4), (0, 60),
                               fsuaepor.white_ink)
    assert runs == [(0, 10), (12, 22), (36, 46)]
    assert fsuaepor.blank_cells(runs, 12) == [0, 1]


def _capture(name: str):
    image = pytest.importorskip("PIL.Image")
    where = amiganamespaces.specimen(amiganamespaces.WATCHED_SPECIMEN)
    if where is None:
        pytest.skip(f"No {amiganamespaces.WATCHED_SPECIMEN} in the specimen "
                    f"tree here.")
    return image.open(where / name).convert("RGB")


def _panel(picture):
    """The three rows as runs: the selected row is white, the rest green."""
    return ([fsuaepor.glyph_runs(picture, fsuaepor.PANEL_ROWS[0],
                                 fsuaepor.PANEL_COLUMNS, fsuaepor.white_ink)]
            + [fsuaepor.glyph_runs(picture, rows, fsuaepor.PANEL_COLUMNS,
                                   fsuaepor.green_ink)
               for rows in fsuaepor.PANEL_ROWS[1:]])


def _pitch(runs_of_a_space_space_b) -> float:
    """One character cell, from `A  B`: B starts three cells after A."""
    first, last = runs_of_a_space_space_b[0], runs_of_a_space_space_b[-1]
    return (last[0] - first[0]) / 3


def test_the_panel_draws_ff_as_one_blank_cell_like_a_space():
    """Slot C loaded, before any save: `MARY<FF>SUE`, `A  B`, `J. R`.

    The gap in `MARY SUE` is one cell and the gap in `A  B` two, so `$FF` is
    drawn exactly as a space is, and nothing is drawn in its place.
    """
    mary, a_b, j_r = _panel(_capture("boot1-loaded-c-panel.png"))
    pitch = _pitch(a_b)
    assert fsuaepor.blank_cells(mary, pitch) == [1]
    assert fsuaepor.blank_cells(a_b, pitch) == [2]
    assert fsuaepor.blank_cells(j_r, pitch) == [0, 1]


@pytest.mark.parametrize("name", ["boot1-after-g-h-panel.png",
                                  "boot2-loaded-h-panel.png"])
def test_after_two_saves_ff_is_still_drawn_and_the_spaces_are_gone(name):
    """After G and H in one boot, and again after a cold boot loaded H."""
    pitch = _pitch(_panel(_capture("boot1-loaded-c-panel.png"))[1])
    mary, a_b, j_r = _panel(_capture(name))
    assert fsuaepor.blank_cells(mary, pitch) == [1]
    assert len(a_b) == 1 and len(j_r) == 1


@pytest.mark.parametrize("name", ["boot1-sheet-c1.png", "boot2-sheet-h1.png"])
def test_the_sheet_draws_ff_as_a_blank_cell(name):
    pitch = _pitch(_panel(_capture("boot1-loaded-c-panel.png"))[1])
    runs = fsuaepor.glyph_runs(_capture(name), fsuaepor.SHEET_NAME_ROWS,
                               fsuaepor.SHEET_NAME_COLUMNS, fsuaepor.green_ink)
    assert fsuaepor.blank_cells(runs, pitch).count(1) == 1
    assert sum(fsuaepor.blank_cells(runs, pitch)) == 1


def test_curse_disks_come_out_of_the_registry_in_drive_order():
    try:
        disks = fsuaepor.curse_disks()
    except SystemExit as exc:
        pytest.skip(str(exc))
    assert [AmigaDisk(d).volume_name for d in disks] == ["CurseA", "CurseB"]


def _argv(run, floppy=None, swap=None):
    drives, swaps = fsuaepor.default_images(run, floppy, swap)
    return fsuaepor.fsuae_argv(run, drives, swaps, "720x568",
                               run / "kick.rom"), drives, swaps


def _touch(run, *names):
    for name in names:
        (run / name).write_bytes(b"")


def test_a_pools_of_darkness_run_puts_disk_3_in_df1(tmp_path):
    _touch(tmp_path, "pod1.adf", "pod2.adf", "pod3.adf")
    argv, drives, swaps = _argv(tmp_path)
    assert (drives, swaps) == ([tmp_path / "pod1.adf", tmp_path / "pod3.adf"],
                               [tmp_path / "pod2.adf"])
    assert f"--floppy_drive_0={tmp_path / 'pod1.adf'}" in argv
    assert f"--floppy_drive_1={tmp_path / 'pod3.adf'}" in argv
    assert not any(a.startswith("--floppy_drive_2") for a in argv)


def test_only_pools_of_darkness_and_an_explicit_swap_get_a_swap_list(tmp_path):
    pod = tmp_path / "pod"
    pod.mkdir()
    _touch(pod, "pod1.adf", "pod2.adf", "pod3.adf")
    argv, _, _ = _argv(pod)
    assert [a for a in argv if a.startswith("--floppy_image_")] == [
        f"--floppy_image_{i}={pod / name}"
        for i, name in enumerate(("pod1.adf", "pod3.adf", "pod2.adf"))]
    por = tmp_path / "por"
    por.mkdir()
    _touch(por, "por1.adf", "por2.adf", "poolsave.adf")
    argv, _, _ = _argv(por)
    assert argv == ["fs-uae", f"--base_dir={por / 'base'}", "--amiga_model=A500",
                    f"--kickstart_file={por / 'kick.rom'}",
                    f"--floppy_drive_0={por / 'por1.adf'}",
                    f"--floppy_drive_1={por / 'por2.adf'}",
                    f"--floppy_drive_2={por / 'poolsave.adf'}",
                    "--writable_floppy_images=1", "--floppy_drive_speed=0",
                    "--fullscreen=0", "--window_width=720", "--window_height=568",
                    "--automatic_input_grab=0", "--initial_input_grab=0",
                    "--volume=0", "--joystick_port_1=none"]
    argv, _, _ = _argv(por, floppy=["por1.adf"], swap=["por2.adf"])
    assert [a for a in argv if a.startswith("--floppy_image_")] == [
        f"--floppy_image_0={por / 'por1.adf'}", f"--floppy_image_1={por / 'por2.adf'}"]


def test_serve_hands_swap_to_default_images(tmp_path, monkeypatch):
    seen = {}

    def stop(run, floppy, swap):
        seen.update(run=run, floppy=floppy, swap=swap)
        raise SystemExit("stop before any process starts")
    monkeypatch.setattr(fsuaepor, "default_images", stop)
    monkeypatch.setattr(fsuaepor.subprocess, "Popen",
                        lambda *a, **k: type("P", (), dict(pid=0))())
    monkeypatch.setattr(fsuaepor.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):
        fsuaepor.main(["serve", "--run", str(tmp_path), "--display", ":9",
                       "--floppy", "a.adf", "--swap", "b.adf"])
    assert (seen["floppy"], seen["swap"]) == (["a.adf"], ["b.adf"])


def _pc(name: str, status=(0, 0), active=1) -> bytes:
    record = bytearray(0x200)
    record[0x60:0x60 + len(name)] = name.encode()
    record[0x5E], record[0x5F] = status
    record[0x184] = active
    return bytes(record)


def _disk3(pcs: list[str], others=("VaultA.DAT", "SavGamA.pty")) -> AmigaDisk:
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir("Save")
    for name in [*others, *pcs]:
        disk.write_file(f"Save/{name}", b"x")
    return disk


def test_the_picker_rows_are_the_pc_files_in_directory_order():
    disk = _disk3(["ONE.pc", "TWO.pc", "THREE.pc"])
    expected = [e.name for e in disk.entries(disk.lookup("Save").block)
                if e.name.endswith(".pc")]
    assert len(expected) == 3
    assert fsuaepor.picker_rows(disk) == expected
    assert "VaultA.DAT" not in expected


def _bar(y=428, colour=(85, 238, 238)):
    from PIL import Image

    image = Image.new("RGB", (800, 600))
    image.paste(colour, (100, y, 300, y + 14))
    return image


def _screens(monkeypatch, calls, before, after=None):
    """`grab` gives `before` in turn, then repeats the last; after a key, `after`."""
    from PIL import Image

    queue = list(before)

    def grab(display):
        keys_sent = sum(c[0] == "key" for c in calls)
        if keys_sent:
            # Each key leaves a new screen, so a key that "took" is visible.
            return after or Image.new("RGB", (800, 600), (9, 9, keys_sent))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    ticks = iter(range(0, 10**6, 2))
    monkeypatch.setattr(fsuaepor, "grab", grab)
    monkeypatch.setattr(fsuaepor, "window_up", lambda display: True)
    monkeypatch.setattr(fsuaepor, "_now", lambda: next(ticks))


def _run(tmp_path, monkeypatch, before, after=None, limit=300):
    disk = _disk3(["ONE.pc"])
    adf = tmp_path / "pod3.adf"
    disk.save(adf)
    calls: list[tuple] = []
    monkeypatch.setattr(fsuaepor, "keys",
                        lambda a: calls.append(("key", tuple(a.key))))
    monkeypatch.setattr(fsuaepor, "shot",
                        lambda a: calls.append(("shot", a.path.name)))
    monkeypatch.setattr(fsuaepor, "_wait", lambda s: None)
    _screens(monkeypatch, calls, before, after)
    args = type("A", (), dict(display=":9", adf=str(adf), out=str(tmp_path / "s"),
                              boot=limit, payload=["ONE.pc"]))
    return calls, args


def test_the_title_bar_is_cyan_ink_in_the_bottom_band():
    from PIL import Image

    assert not fsuaepor.title_bar_up(Image.new("RGB", (800, 600)))
    assert fsuaepor.title_bar_up(_bar())
    assert not fsuaepor.title_bar_up(_bar(y=120))
    assert not fsuaepor.title_bar_up(_bar(colour=(136, 136, 136)))


def test_no_key_is_sent_before_the_title_bar_is_up(tmp_path, monkeypatch):
    black = _bar(colour=(0, 0, 0))
    calls, args = _run(tmp_path, monkeypatch, [black, black, _bar(), _bar()])
    seen = []
    real = fsuaepor.grab

    def counting(display):
        image = real(display)
        seen.append(fsuaepor.title_bar_up(image))
        return image

    monkeypatch.setattr(fsuaepor, "grab", counting)
    assert fsuaepor.pod_panel(args) == 0
    first_key = next(i for i, c in enumerate(calls) if c[0] == "key")
    assert calls[first_key] == ("key", ("p",))
    assert seen[:4] == [False, False, True, True]
    assert first_key > 0
    assert calls[first_key - 1][0] == "shot"      # the title shot, then `p`


def test_the_script_stops_with_no_key_when_the_bar_never_comes(tmp_path, monkeypatch):
    calls, args = _run(tmp_path, monkeypatch, [_bar(colour=(0, 0, 0))], limit=10)
    with pytest.raises(SystemExit) as exc:
        fsuaepor.pod_panel(args)
    assert "no key sent" in str(exc.value)
    assert [c for c in calls if c[0] == "key"] == []
    assert any("no-title-bar" in c[1] for c in calls if c[0] == "shot")


def test_a_dead_emulator_stops_the_wait_early_with_no_key(tmp_path, monkeypatch):
    calls, args = _run(tmp_path, monkeypatch, [_bar(colour=(0, 0, 0))], limit=300)
    clock = []
    real_now = fsuaepor._now

    def now():
        clock.append(real_now())
        return clock[-1]

    monkeypatch.setattr(fsuaepor, "_now", now)
    monkeypatch.setattr(fsuaepor, "window_up", lambda display: False)
    with pytest.raises(SystemExit) as exc:
        fsuaepor.pod_panel(args)
    assert "no window" in str(exc.value)
    assert [c for c in calls if c[0] == "key"] == []
    assert clock[-1] - clock[0] < 60


def test_window_up_reads_xdotool_search(monkeypatch):
    out = {"v": "12345\n"}
    monkeypatch.setattr(fsuaepor.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": out["v"]})())
    assert fsuaepor.window_up(":9")
    out["v"] = ""
    assert not fsuaepor.window_up(":9")


def test_window_up_is_false_when_the_search_times_out(monkeypatch):
    def hung(*a, **k):
        raise fsuaepor.subprocess.TimeoutExpired("xdotool", k["timeout"])

    monkeypatch.setattr(fsuaepor.subprocess, "run", hung)
    assert fsuaepor.window_up(":9") is False


def test_one_missed_window_search_does_not_end_the_wait(tmp_path, monkeypatch):
    calls, args = _run(tmp_path, monkeypatch,
                       [_bar(colour=(0, 0, 0))] * 12 + [_bar()], limit=300)
    answers = iter([False, True] + [True] * 50)
    monkeypatch.setattr(fsuaepor, "window_up", lambda display: next(answers))
    assert fsuaepor.pod_panel(args) == 0


def test_two_missed_window_searches_in_a_row_stop_the_wait(tmp_path, monkeypatch):
    calls, args = _run(tmp_path, monkeypatch,
                       [_bar(colour=(0, 0, 0))] * 40 + [_bar()], limit=300)
    answers = iter([False, False] + [True] * 50)
    monkeypatch.setattr(fsuaepor, "window_up", lambda display: next(answers))
    with pytest.raises(SystemExit, match="no window"):
        fsuaepor.pod_panel(args)
    assert [c for c in calls if c[0] == "key"] == []


def test_a_miss_then_a_hit_then_a_miss_does_not_add_up(tmp_path, monkeypatch):
    calls, args = _run(tmp_path, monkeypatch,
                       [_bar(colour=(0, 0, 0))] * 16 + [_bar()], limit=300)
    answers = iter([False, True, False, True] + [True] * 50)
    monkeypatch.setattr(fsuaepor, "window_up", lambda display: next(answers))
    assert fsuaepor.pod_panel(args) == 0


def _picker_run(tmp_path, monkeypatch, screen, payloads):
    """Run `pod_panel` on a two-row picker; `screen(keys, polls)` is each grab.

    `keys` are the keys sent so far, `polls` the waits since the last key.
    """
    disk = _disk3(["ONE.pc", "TWO.pc"])
    adf = tmp_path / "pod3.adf"
    disk.save(adf)
    events: list[str] = []
    state = {"keys": [], "polls": 0}

    def send(a):
        events.append(a.key[0])
        state["keys"].append(a.key[0])
        state["polls"] = 0

    def wait(seconds):
        events.append("wait")
        state["polls"] += 1

    monkeypatch.setattr(fsuaepor, "keys", send)
    monkeypatch.setattr(fsuaepor, "shot", lambda a: events.append("shot:" + a.path.name))
    monkeypatch.setattr(fsuaepor, "_wait", wait)
    monkeypatch.setattr(fsuaepor, "window_up", lambda display: True)
    ticks = iter(range(0, 10**6, 2))
    monkeypatch.setattr(fsuaepor, "_now", lambda: next(ticks))
    monkeypatch.setattr(fsuaepor, "grab", lambda display: _bar() if not state["keys"]
                        else screen(state["keys"], state["polls"]))
    args = type("A", (), dict(display=":9", adf=str(adf), out=str(tmp_path / "s"),
                              boot=300, payload=payloads))
    return events, args


def _distinct(n):
    from PIL import Image
    return Image.new("RGB", (800, 600), (9, 9, n % 250))


def _payload_a(keys):
    """True once the picker's `a` for a payload (the second `a`) was the last key."""
    return keys[-1] == "a" and keys.count("a") >= 2


def test_no_down_is_sent_until_the_screen_stops_changing_after_an_a(
        tmp_path, monkeypatch):
    def screen(keys, polls):
        if _payload_a(keys):
            return _distinct(polls) if polls < 5 else _distinct(200)
        return _distinct(len(keys) * 10)

    events, args = _picker_run(tmp_path, monkeypatch, screen, ["ONE.pc", "TWO.pc"])
    assert fsuaepor.pod_panel(args) == 0
    picker_a = [i for i, e in enumerate(events) if e == "a"][1]
    next_down = next(i for i, e in enumerate(events) if e == "Down" and i > picker_a)
    assert events[picker_a:next_down].count("wait") >= 6


def test_a_screen_that_never_settles_stops_the_run_with_a_shot(
        tmp_path, monkeypatch):
    counter = iter(range(10**6))

    def screen(keys, polls):
        return _distinct(next(counter)) if _payload_a(keys) else _distinct(len(keys) * 10)

    events, args = _picker_run(tmp_path, monkeypatch, screen, ["ONE.pc", "TWO.pc"])
    with pytest.raises(SystemExit, match="still changing"):
        fsuaepor.pod_panel(args)
    assert "Down" not in events
    assert events[-1].startswith("shot:") and "still-adding" in events[-1]


def test_a_down_that_changes_nothing_stops_before_the_next_a(tmp_path, monkeypatch):
    def screen(keys, polls):
        return _distinct(len([k for k in keys if k != "Down"]) * 10)

    events, args = _picker_run(tmp_path, monkeypatch, screen, ["ONE.pc"])
    args.payload = [fsuaepor.picker_rows(AmigaDisk(open(args.adf, "rb").read()))[1]]
    with pytest.raises(SystemExit, match="did not change"):
        fsuaepor.pod_panel(args)
    assert any("down-ignored" in e for e in events)
    assert events.count("a") == 1      # ADD CHARACTER's own, never the payload's


def test_grab_gives_a_readable_stop_for_a_hung_or_dead_display(monkeypatch):
    seen = {}

    def hung(*a, **k):
        seen.update(k)
        raise fsuaepor.subprocess.TimeoutExpired("import", k["timeout"])

    monkeypatch.setattr(fsuaepor.subprocess, "run", hung)
    with pytest.raises(SystemExit, match="not answering"):
        fsuaepor.grab(":9")
    assert seen["timeout"] == fsuaepor.GRAB_TIMEOUT

    def dead(*a, **k):
        raise fsuaepor.subprocess.CalledProcessError(1, "import")

    monkeypatch.setattr(fsuaepor.subprocess, "run", dead)
    with pytest.raises(SystemExit, match="X server is gone"):
        fsuaepor.grab(":9")


def test_a_zero_boot_still_succeeds_when_the_bar_is_up(tmp_path, monkeypatch):
    calls, args = _run(tmp_path, monkeypatch, [_bar()], limit=0)
    assert fsuaepor.pod_panel(args) == 0


def test_the_script_stops_when_p_changes_nothing(tmp_path, monkeypatch):
    calls, args = _run(tmp_path, monkeypatch, [_bar()], after=_bar())
    with pytest.raises(SystemExit):
        fsuaepor.pod_panel(args)
    assert [c for c in calls if c[0] == "key"] == [("key", ("p",))]
    assert any("play-ignored" in c[1] for c in calls if c[0] == "shot")


def test_the_panel_script_reaches_each_row_and_never_ends_the_session(
        tmp_path, monkeypatch):
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir("Save")
    for n in range(14):
        disk.write_file(f"Save/{n:02d}.pc", b"x")
    names = fsuaepor.picker_rows(disk)
    adf = tmp_path / "pod3.adf"
    disk.save(adf)
    calls: list[tuple] = []
    monkeypatch.setattr(fsuaepor, "keys",
                        lambda a: calls.append(("key", tuple(a.key))))
    monkeypatch.setattr(fsuaepor, "shot",
                        lambda a: calls.append(("shot", a.path.name)))
    monkeypatch.setattr(fsuaepor, "_wait", lambda s: None)
    _screens(monkeypatch, calls, [_bar(), _bar()])
    args = type("A", (), dict(display=":9", adf=str(adf), out=str(tmp_path / "s"),
                              boot=300, payload=[names[4], names[11], names[13]]))
    assert fsuaepor.pod_panel(args) == 0
    pressed = [c[1][0] for c in calls if c[0] == "key"]
    assert "Up" not in pressed and "y" not in pressed
    assert not any(a == b == "e" for a, b in zip(pressed, pressed[1:]))
    adds = [i for i, c in enumerate(calls) if c == ("key", ("a",))]
    assert len(adds) == 4      # ADD CHARACTER's own `a`, then three payloads
    downs = [sum(c == ("key", ("Down",)) for c in calls[lo:hi])
             for lo, hi in zip(adds[:-1], adds[1:])]
    assert downs == [4, 7, 2]
    for i in adds[1:]:
        assert calls[i + 1][0] == "shot"
    for i, c in enumerate(calls):
        if c == ("key", ("v",)):
            assert calls[i + 1][0] == "shot"


def test_pod_stage_leaves_only_the_payloads_in_the_save_drawer(
        tmp_path, monkeypatch, capsys):
    disk3 = _disk3(["OLD.pc"])
    disk3.save(tmp_path / "src3.adf")
    disks = [b"one", b"two", (tmp_path / "src3.adf").read_bytes()]
    payload = tmp_path / "outofparty.pc"
    payload.write_bytes(_pc("CLARISSA", active=0))
    monkeypatch.setattr(fsuaepor, "pod_disks", lambda: disks)
    out = tmp_path / "run"
    assert fsuaepor.pod_stage(type("A", (), dict(out=str(out), pc=[str(payload)]))) == 0
    staged = AmigaDisk((out / "pod3.adf").read_bytes())
    assert fsuaepor.picker_rows(staged) == ["outofparty.pc"]
    assert staged.read_file("Save/VaultA.DAT") == b"x"
    assert staged.read_file("Save/SavGamA.pty") == b"x"
    assert (out / "pod1.adf").read_bytes() == b"one"
    line = next(t for t in capsys.readouterr().out.splitlines() if t.startswith("row"))
    assert "row 1" in line and "'CLARISSA'" in line and "0x184 00" in line


def test_pod_disks_come_out_of_the_registry_in_drive_order():
    try:
        disks = fsuaepor.pod_disks()
    except SystemExit as exc:
        pytest.skip(str(exc))
    first, second, third = (AmigaDisk(d) for d in disks)
    assert [d.volume_name for d in (first, second, third)] == ["POD 1", "POD 2", "POD 3"]
    assert fsuaepor.picker_rows(third)
    assert first.read_file("Pools of Darkness")


def test_pod_panel_names_the_picker_rows_for_a_payload_not_on_the_disk(tmp_path):
    disk = _disk3(["ONE.pc"])
    adf = tmp_path / "pod3.adf"
    disk.save(adf)
    args = type("A", (), dict(display=":9", adf=str(adf), out=str(tmp_path / "s"),
                              boot=0, payload=["MISSING.pc"]))
    with pytest.raises(SystemExit) as exc:
        fsuaepor.pod_panel(args)
    assert "MISSING.pc" in str(exc.value) and "ONE.pc" in str(exc.value)
