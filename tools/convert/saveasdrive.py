"""Publish a conversion through the editor's Save As route, for the developer tools.

Opens `source` as the editor does, resolves the destination's game data, then
calls `saveplan.prepare_save_as` and `saveplan.publish`, so what the tool boots
is the rehearsed bytes Save As publishes and not what `File > Convert...`
writes. It does not call `check_not_alias`, flush edits or confirm a replacement:
the destination is always a new dated folder under `folder`, so it can neither
be the source nor replace a file. No dialog exists here, so a rejection is
returned as `report["stopped"]` with the exception's own words. Imports of `editor` are lazy so a caller can point
`sys.path` at another checkout first.
"""
from __future__ import annotations

import datetime
import pathlib
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

#: The file a Save As writes for a destination that is a single image.
IMAGE_NAMES = {"c64": "WISHSAVE.D64", "amiga": "POOLSAVE.ADF"}


def destination_path(port: str, folder: pathlib.Path) -> pathlib.Path:
    """Where a tool's Save As lands: a dated folder under `folder`, holding
    the image, or being the DOS save folder itself. A folder already there
    from an earlier run is left alone and the next free `-2`, `-3`... is used,
    so a re-run into the same `folder` never meets a non-empty target."""
    stem = f"wish-{datetime.date.today().isoformat()}"
    dated = pathlib.Path(folder) / stem
    n = 1
    while dated.exists():
        n += 1
        dated = pathlib.Path(folder) / f"{stem}-{n}"
    return dated if port == "dos" else dated / IMAGE_NAMES[port]


#: The `--leave` value that ticks rows top-down until the count reaches zero.
LEAVE_AUTO = "auto"


class LeaveChoiceError(Exception):
    """The left-behind window could not be completed as asked; `record` is
    what had been ticked and read when it stopped."""

    record: dict = {}


def _leave_through_window(window: Any, overflow: Any, game: Any,
                          ticks: Sequence[str], source: Any = None,
                          assets: Any = None) -> "tuple[dict, dict]":
    """Open the editor's own left-behind window for `overflow`, tick the rows
    named in `ticks` (or `LEAVE_AUTO`), and return its choice and a record of
    what was ticked and what the window said.

    The window is reached through `window._choose_left_behind`, so its item
    and spell names come from the same place as in the editor; only `exec` is
    replaced, by the ticking."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QDialog, QDialogButtonBox

    from editor import leavebehind

    dialog_class = leavebehind.LeaveBehindDialog
    column = leavebehind.NAME_COLUMN
    record: dict = {"overflow": True,
                    "accept_label": window._save_as_label()}
    failure: list[str] = []

    def rows(dialog):
        found = []

        def walk(item):
            if item.data(column, leavebehind.PICK_ROLE) is not None:
                found.append(item)
            for n in range(item.childCount()):
                walk(item.child(n))

        for n in range(dialog.tree.topLevelItemCount()):
            walk(dialog.tree.topLevelItem(n))
        return found

    def tick(row):
        row.setCheckState(column, Qt.CheckState.Checked)
        record["ticked"].append({
            "member": row.data(column, leavebehind.PICK_ROLE)[0],
            "text": row.text(column)})

    def run(dialog):
        label = dialog.ui.items_remaining_label
        ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        record["label_before"] = label.text()
        record["ticked"] = []
        candidates = rows(dialog)
        if list(ticks) == [LEAVE_AUTO]:
            done = leavebehind.ITEMS_REMAINING.format(n=0)
            for row in candidates:
                if label.text() == done:
                    break
                tick(row)
        else:
            for name in ticks:
                match = next(
                    (r for r in candidates if r.text(column) == name
                     and r.checkState(column) == Qt.CheckState.Unchecked),
                    None)
                if match is None:
                    failure.append(f"no row in the window shows {name!r}")
                    return QDialog.DialogCode.Rejected
                tick(match)
        record["label_after"] = label.text()
        record["ok_enabled"] = ok.isEnabled()
        if not ok.isEnabled():
            failure.append("OK is disabled after ticking: the window still "
                           f"reads {label.text()!r}")
            return QDialog.DialogCode.Rejected
        return QDialog.DialogCode.Accepted

    original = dialog_class.exec
    dialog_class.exec = run
    try:
        choice = window._choose_left_behind(
            overflow, game, record["accept_label"], source=source,
            assets=assets)
    finally:
        dialog_class.exec = original
    if failure or choice is None:
        stop = LeaveChoiceError(
            failure[0] if failure else "the left-behind window was not accepted")
        stop.record = record
        raise stop
    return choice, record


def save_as(window: Any, source: "str | pathlib.Path", port: str,
            folder: "str | pathlib.Path", *,
            c64_folder: "str | pathlib.Path | None" = None,
            dos_folder: "str | pathlib.Path | None" = None,
            amiga_disk: "str | pathlib.Path | None" = None,
            amiga_disk_one: "str | pathlib.Path | None" = None,
            amiga_disk_three: "str | pathlib.Path | None" = None,
            source_slot: "str | None" = None,
            edits: "Callable[[Any], None] | None" = None,
            names: "Mapping[int, str] | None" = None,
            leave: "Mapping[int, Collection[int]] | None" = None,
            leave_effects: "Mapping[int, Collection[int]] | None" = None,
            leave_ticks: "Sequence[str] | None" = None
            ) -> dict:
    """Open `source`, Save As it to `port` under `folder`, and say what landed.

    `window` is an `EditorBinding`, whose `game_files_for` finds the game data
    a route needs. The report carries `written` (paths), `slot`, `losses`,
    `dropped`, `warnings`, `left_behind` and `unjoined` (the joined scrolls an Amiga
    destination took apart to stay within the loader's limit) from the
    conversion's accounting, or
    `stopped` -- the exception's class and text -- when Save As blocked or
    failed.

    `source_slot` names which of a DOS folder's or an Amiga disk's several
    saved games to read, the same letter `editor.convert.Source.detect`
    itself takes; `None` keeps its own default, the alphabetically first slot
    the source holds.

    `amiga_disk_three` is the Pools of Darkness disk 3 an Amiga destination
    writes its slot onto; with none named, `saveplan.resolve_assets` looks
    for one the way the editor does.

    `edits` is called with the opened `Party` before Save As prepares its
    output, so a caller can change a member's record or items the way the
    sheet does and the change reaches the written save.

    `names` is the `{position: name}` a player would choose in the Shorten
    window, handed to `prepare_save_as`. A name too long for the destination
    with no choice for it is blocked as `NamesDoNotFit`, and the report then
    also carries `unfit` (`[position, name]` for each) and `width`, so a caller
    can see which names needed a choice and not only that Save As blocked.

    `leave` is the `{member: pack positions}` a player would tick in the
    window that opens when a pack needs more than the C64's sixteen slots. A
    party still over is blocked as `JoinedScrollsDoNotFit`, or for a Silver
    Blades party over the Amiga's joined-scroll limit as
    `AmigaJoinedScrollsDoNotFit`.

    `leave_ticks` is what a player would tick in that same window, as the text
    its rows show, or `[LEAVE_AUTO]`. When the party is over and no `leave`
    is given, the editor's own window is opened for it, those rows are ticked,
    and Save As is run again with the window's choice; the report carries
    `leave_dialog` (`overflow`, `accept_label`, `ticked`, `label_before`,
    `label_after`, `ok_enabled`); a run whose party never overflowed reports
    `{"overflow": false, "ticked": []}`. A
    row that is missing, or an OK that stays disabled, is `stopped` as
    `LeaveChoiceError`.

    `leave_effects` is the `{member: running-effect indices}` a player would
    tick in the window that opens when the party's running effects need more
    rows than the C64's shared table holds. A party still over is blocked as
    `EffectsDoNotFit`, and the report then also carries `effects_needed`,
    `effects_limit` and `effect_entries` (`[member, index, effect id,
    minutes]` for each effect that can be left out).
    """
    from editor import saveplan
    from editor.convert import Source
    from editor.roster import Party
    from goldbox import amiga_savegame, dos_codec

    report: dict = {"source": str(source), "to": port, "folder": str(folder)}
    if leave_ticks:
        # Overwritten when the window opens, so a run that never needed it
        # still says it ticked nothing.
        report["leave_dialog"] = {"overflow": False, "ticked": []}
    path = destination_path(port, pathlib.Path(folder))
    report["destination"] = str(path)
    try:
        detected = Source.detect(source, slot=source_slot)
        party = Party(detected)
        if edits is not None:
            edits(party)
        assets = saveplan.resolve_assets(
            Source.of_snapshot(saveplan.prepare(party)), port,
            game_files=window.game_files_for, c64_folder=c64_folder,
            dos_folder=dos_folder, amiga_disk=amiga_disk,
            amiga_disk_one=amiga_disk_one, amiga_disk_three=amiga_disk_three)
        plan = saveplan.prepare_save_as(
            party, port, path, assets,
            **({"names": names} if names is not None else {}),
            **({"leave": leave} if leave else {}),
            **({"leave_effects": leave_effects} if leave_effects else {}))
        report["losses"] = saveplan.losses(plan.report) if plan.report else []
        report["dropped"] = list(getattr(plan.report, "dropped", []) or [])
        report["left_behind"] = list(
            getattr(plan.report, "left_behind", []) or [])
        report["unjoined"] = list(getattr(plan.report, "unjoined", []) or [])
        report["warnings"] = [
            str(x) for x in getattr(plan.report, "warnings", []) or []]
        published = saveplan.publish(plan, party, assets=assets)
    except Exception as exc:
        if isinstance(exc, saveplan.NamesDoNotFit):
            report["unfit"] = [[position, name] for position, name in exc.unfit]
            report["width"] = exc.width
        if isinstance(exc, dos_codec.EffectsDoNotFit):
            over = exc.overflow
            report["effects_needed"] = over.needed
            report["effects_limit"] = over.limit
            report["effect_entries"] = [list(e) for e in over.entries]
        if (leave_ticks and not leave and isinstance(
                exc, (dos_codec.JoinedScrollsDoNotFit,
                      amiga_savegame.AmigaJoinedScrollsDoNotFit))):
            try:
                from editor import convert as convert_mod
                snapshot = Source.of_snapshot(saveplan.prepare(party))
                game = saveplan.route(snapshot, port).destination_game
                choice, record = _leave_through_window(
                    window, convert_mod.overflow_of(exc), game, leave_ticks,
                    source=snapshot, assets=assets)
            except LeaveChoiceError as stop:
                exc = stop
                report["leave_dialog"] = stop.record
            else:
                again = save_as(
                    window, source, port, folder, c64_folder=c64_folder,
                    dos_folder=dos_folder, amiga_disk=amiga_disk,
                    amiga_disk_one=amiga_disk_one,
                    amiga_disk_three=amiga_disk_three, source_slot=source_slot,
                    edits=edits, names=names, leave=choice, leave_effects=leave_effects)
                again["leave_dialog"] = record
                return again
        report["stopped"] = [type(exc).__name__, str(exc)]
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report
    report["slot"] = plan.destination.slot
    report["written"] = [str(p) for p in published.written]
    return report
