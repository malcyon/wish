"""Secret of the Silver Blades: pins, preparation, its route and the journal answerer."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
from typing import Any

from automap import gamedisks
from goldbox import amiga_adf, amiga_savegame
from tools.amiga import amigabladesjournal, staging
from tools.amiga.route import effect_fields
from tools.amiga.staging import _entry, _verified_disk, sha256
from tools.amiga.winuaesession import HOLDER, RouteError
from tools.registry import scratch

DISK_B_SHA256 = "d7caf68c3333b44a4ca2951b8d51f388e4bfd7a8bafa4fd8a7fca37aa639b468"
# The slot letter the game is offered on its own boot disk; side A ships only A.
SLOT_LETTER = "C"
JOIN_SHA256 = "38c11440e578227c1a240b740f362b1b69943d9897f42dc35ac39b17508872dc"
TITLE = "secret-of-the-silver-blades"


def _inventory(save: amiga_savegame.AmigaSavegame, *, require_joined: bool = True
               ) -> dict[str, Any]:
    members = []
    for person in save.characters:
        items = [
            {"type": item.get("type_index"), "plus": item.get("plus"),
             "quantity": item.get("quantity"), "names": [
                 item.get("name1"), item.get("name2"), item.get("name3")],
             "text": item.text}
            for item in person.items
        ]
        members.append({"name": person.name, "count": len(items), "items": items})
    guy = next((member for member in members
                if member["name"].upper() == "GUY DE VALOIS"), None)
    if guy is None:
        raise RouteError("Guy de Valois is absent from the converted Amiga party")
    arrows = [item for item in guy["items"]
              if item["type"] == 0x1E and item["plus"] == 1]
    joined_ok = (guy["count"] == 13 and len(arrows) == 1
                 and arrows[0]["quantity"] == 35)
    if require_joined and not joined_ok:
        raise RouteError(
            "Guy's converted inventory is not 13 items and one +1 arrow stack of 35")
    return {"members": members, "guy_index": members.index(guy),
            "joined_inventory_expected": joined_ok}


def find_disk_b() -> pathlib.Path:
    """The registered Silver Blades disk B, found by its pinned hash."""
    for root in gamedisks.candidates("amiga"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.adf")):
            if path.stat().st_size == 901120 and sha256(path) == DISK_B_SHA256:
                return path
    raise RouteError("registered Silver Blades disk B was not found by its SHA-256")


def prepare(source: pathlib.Path, run_id: str) -> pathlib.Path:
    """Publish the C64 JOIN party as an immutable ADF and stage a private DF0."""
    if not HOLDER.fullmatch(run_id):
        raise RouteError("run id must use letters, digits, dot, underscore or hyphen")
    source = source.expanduser().resolve()
    if sha256(source) != JOIN_SHA256:
        raise RouteError(f"JOIN source SHA-256 differs: {sha256(source)}")
    boot_source = amigabladesjournal.find_disk()
    if sha256(boot_source) != staging.SOURCE_SHA256:
        raise RouteError("registered Silver Blades side A differs from the measured build")
    run = scratch.cache_dir("acceptance", "672", run_id)
    df0 = scratch.cache_dir("amigaacceptance", run_id, "boot-with-slot.adf")
    if run.exists() or df0.exists():
        raise RouteError(f"run or staged DF0 already exists: {run}, {df0}")
    disk_b_source = find_disk_b()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from editor import roster, saveplan  # noqa: PLC0415
    from editor.convert import Source  # noqa: PLC0415
    from tools.convert import convertdrops  # noqa: PLC0415

    party = roster.Party(str(source))
    snapshot = saveplan.prepare(party)
    if snapshot is None:
        raise RouteError("the JOIN disk has no saved party")
    assets = saveplan.resolve_assets(Source.of_snapshot(snapshot), "amiga",
                                     game_files=convertdrops.game_files)
    published = run / "SECRETSAVE-published.adf"
    plan = saveplan.prepare_save_as(party, "amiga", published, assets)
    if plan.destination.slot != "A":
        raise RouteError(f"Save As selected slot {plan.destination.slot!r}, not A")
    if plan.report is None or plan.report.dropped or plan.report.losses:
        raise RouteError("Save As reports dropped fields or losses")

    scratch.ensure(run)
    saveplan.publish(plan, party)
    disk = _verified_disk(published)
    if disk.volume_name != "SECRETSAVE":
        raise RouteError(f"published volume is {disk.volume_name!r}, not SECRETSAVE")
    files = [path for path, _ in disk.walk()]
    if files != ["/SAVE/savgamA.sav"]:
        raise RouteError(f"published save disk has unexpected files: {files}")
    save = amiga_savegame.read_slot(disk, "A", TITLE)
    inventory = _inventory(save)
    state = amiga_savegame.state_from_savegame(save)
    slot = disk.read_file("/SAVE/savgamA.sav")
    stage = staging.stage_embedded_boot_disk(boot_source, slot, SLOT_LETTER, df0)
    df1 = run / "disk-b-working.adf"
    with disk_b_source.open("rb") as reader, df1.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    if sha256(source) != JOIN_SHA256:
        raise RouteError("JOIN source changed during preparation")
    if sha256(boot_source) != staging.SOURCE_SHA256:
        raise RouteError("registered boot disk changed during preparation")
    if sha256(df1) != DISK_B_SHA256 or sha256(disk_b_source) != DISK_B_SHA256:
        raise RouteError("working DF1 differs from the pinned disk B")
    published.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    manifest = {
        "source": _entry(source), "boot_source": _entry(boot_source),
        "df0": _entry(df0), "published_df1": _entry(published),
        "disk_b_source": _entry(disk_b_source), "df1": _entry(df1),
        "slot_letter": SLOT_LETTER, "slot_sha256": hashlib.sha256(slot).hexdigest(),
        "stage": stage, "inventory_a": inventory,
        "state_a": {"area": state.area, "x": state.x, "y": state.y,
                    "facing": state.facing},
        "dropped": list(plan.report.dropped), "losses": list(plan.report.losses),
    }
    manifest_path = run / "prepare.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest_path


# `title` is the screen the route starts from: the version line over the
# PLAY / DEMO / QUIT bar, which takes `P` and ignores RETURN. Left alone, the
# attract loop moves on from it to the story intro and the credits.
ROUTE = (
    ("P", "party_menu"), ("L", "load_picker"), (SLOT_LETTER, "loaded_menu"),
    ("V", "sheet"), ("I", "items"), ("E", "sheet"), ("E", "loaded_menu"),
    ("S", "save_picker"),
)


MIN_WAIT_OVERRIDES = {"load_picker": 20.0, "loaded_menu": 20.0}
DEFAULT_MIN_WAIT = 15.0

# The two saves the accept route writes, on slots the game's own disk never ships.
MENU_SAVE_LETTER = "B"
CAMP_SAVE_LETTER = "D"

# (key, state reached, kind). `write` saves, `answer` runs the journal answerer
# instead of pressing a key, `move` is a movement key. Silver Blades takes no
# RETURN after the camp save's letter, and RETURN at EXIT GAME is unmeasured, so
# the route never presses either.
ACCEPT_ROUTE = (
    *((key, state, "key") for key, state in ROUTE),
    (MENU_SAVE_LETTER, "loaded_menu", "write"),
    ("B", "journal", "key"),
    (None, "world", "answer"),
    ("NP8", "world", "move"), ("NP8", "world", "move"),
    ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
    (CAMP_SAVE_LETTER, "exit_game", "write"),
    ("N", "camp", "key"),
)
# The world bar is one state reached two ways, so its wait after a move has its own key.
ACCEPT_MIN_WAITS = {
    "loaded_menu": 20.0, "journal": 45.0, "world": 20.0, "world_after_move": 5.0,
    "camp": 10.0, "camp_save_picker": 10.0, "exit_game": 20.0,
}
JOURNAL_SCRIPT = pathlib.Path(__file__).with_name("amigabladesjournal.py")


def default_min_waits(route=ROUTE) -> dict[str, float]:
    """Minimum seconds to sit on each state before its screen is captured."""
    return {state: MIN_WAIT_OVERRIDES.get(state, DEFAULT_MIN_WAIT)
            for _, state in route}


def _slot_reading(fetched: amiga_adf.AmigaDisk, letter: str) -> dict[str, Any]:
    """Read one save slot off a fetched boot disk with the existing readers.

    Returns `missing`, or `decode_error`, or the digest, place, member names and
    inventory; `decode_error` still carries the digest.
    """
    try:
        raw = fetched.read_file(f"/SAVE/savgam{letter}.sav")
    except amiga_adf.AmigaDiskError:
        return {"missing": True, "sha256": None}
    reading: dict[str, Any] = {"sha256": hashlib.sha256(raw).hexdigest()}
    try:
        saved = amiga_savegame.read_slot(fetched, letter, TITLE)
        state = amiga_savegame.state_from_savegame(saved)
        inventory = _inventory(saved, require_joined=False)
    except BaseException as exc:
        reading["decode_error"] = f"{type(exc).__name__}: {exc}"
        return reading
    reading["place"] = {"area": state.area, "x": state.x, "y": state.y,
                        "facing": state.facing}
    reading["names"] = [member["name"] for member in inventory["members"]]
    reading["inventory"] = inventory
    reading["effects"] = {member.name: [list(effect_fields(node)) for node in member.effects]
                          for member in saved.characters}
    return reading


def _silver_blades_problems(reading: dict[str, Any], slot: str) -> list[str]:
    """Guy's 13 items and one stack of 35 arrows, the joined party Silver Blades' run prepares."""
    if reading["inventory"]["joined_inventory_expected"]:
        return []
    return [f"{slot} is not Guy with 13 items and one +1 arrow stack of 35"]


#: The private screen reader, imported the way `amigabladesjournal._blades_modules`
#: does, then asked for its own template file.  It prints `ok` and nothing else, so
#: no template content can reach a log.
JOURNAL_READER_CHECK = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "import amiga_tables, screen; screen.load_digits(); print('ok')")


def _journal_reader_failure(journal_python: str, analysis: pathlib.Path) -> str:
    """Why the private reader cannot load its template file, or "" when it can."""
    try:
        proc = subprocess.run([journal_python, "-c", JOURNAL_READER_CHECK, str(analysis)],
                              capture_output=True, text=True, errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"the journal interpreter {journal_python!r} did not run the reader check: {exc}"
    stdout, stderr = (part.decode(errors="replace") if isinstance(part, bytes) else part or ""
                      for part in (proc.stdout, proc.stderr))
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if proc.returncode == 0 and lines[-1:] == ["ok"]:
        return ""
    what = f"exit {proc.returncode}" if proc.returncode else "exit 0 but no ok line"
    return (f"the private journal reader failed its template check ({what})"
            + (_stderr_tail(stderr) or "; no stderr"))


def journal_preflight(journal_python: str) -> None:
    """Refuse before the lane is claimed unless the private reader's imports and template file load.

    The reader check runs before the numpy check is judged so that a missing dependency, which
    also fails the reader, is reported as itself.
    """
    analysis = amigabladesjournal.wheel_repo() / "ssb" / "analysis"
    reader_failure = _journal_reader_failure(journal_python, analysis) if analysis.is_dir() else ""
    try:
        proc = subprocess.run([journal_python, "-c", "import numpy, PIL"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RouteError(f"the journal interpreter {journal_python!r} did not run: {exc}") from exc
    if proc.returncode:
        raise RouteError(f"the journal interpreter {journal_python!r} cannot import numpy and PIL")
    if not analysis.is_dir():
        raise RouteError(f"{analysis} is not a directory, so the journal cannot be answered")
    if reader_failure:
        raise RouteError(reader_failure)


def run_journal_answer(journal_python: str, holder: str, adf: pathlib.Path,
                       timeout: float, script: pathlib.Path = JOURNAL_SCRIPT
                       ) -> tuple[int, str]:
    """Run the answerer in its own interpreter; its exit code and last line of stdout.

    A subprocess, because numpy and Pillow live in `journal_python` and this
    driver imports neither. Nothing else it prints is kept.
    """
    try:
        proc = subprocess.run(
            [journal_python, str(script), "--holder", holder, "--adf", str(adf)],
            capture_output=True, text=True, errors="replace", timeout=timeout,
            env=dict(os.environ, SSH_ASKPASS_REQUIRE="never"))
    except subprocess.TimeoutExpired as exc:
        raise RouteError(f"the journal answerer exceeded its {timeout:.0f}s limit") from exc
    lines = proc.stdout.strip().splitlines()
    line = lines[-1].strip() if lines else ""
    if proc.returncode and line != "no challenge on screen":
        raise RouteError(f"the journal answerer ended {proc.returncode}: {line[:STDERR_LINE_CHARS]!r}"
                         + _stderr_tail(proc.stderr))
    return proc.returncode, line


STDERR_LINES = 5
STDERR_LINE_CHARS = 250


def _stderr_tail(stderr: str) -> str:
    """The answerer's last lines of stderr for an error message: at most 5 lines of 250 characters.

    Without them the cause (a missing table, a failed import) is only in a log nobody opens.
    """
    lines = [line.strip() for line in stderr.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    return "; stderr: " + " | ".join(line[:STDERR_LINE_CHARS] for line in lines[-STDERR_LINES:])


# (screen, action, waiting_for, limit): on a known screen that is not the wanted one,
# do `action` once per wait, `limit` times at most, while waiting for one of the
# states in `waiting_for` (None: any). `credits` is left with ESC, `continue` takes
# RETURN, and the journal challenge goes to the answerer; the last two only when accepting.
SILVER_BLADES_INTERSTITIALS = (
    ("credits", ("keys", "ESC"), frozenset({"title"}), 1),
    ("continue", ("keys", "RET"), None, 1),
    ("journal", ("answer",), frozenset({"exit_game"}), 1),
)
