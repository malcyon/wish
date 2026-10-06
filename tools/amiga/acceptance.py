#!/usr/bin/env python3
"""Prepare, measure and accept one Amiga title's load, inspect, move, save and read-back run under WinUAE.

`prepare --published-disk-one --stage-place X,Y,F` (Curse and Silver Blades)
puts the party on square X,Y facing F (0 N, 1 E, 2 S, 3 W) in the loaded slot
of working DF0 and nothing else: only the three square bytes change, the area
and the wall byte are left for the engine to recompute on the first step. It
is blocked, before any run folder exists, for a value out of range (x and y 0 to
15) or a slot saved outdoors. The manifest records the change as `staged_place`
and expects that square on load; the registered published image and the source
pins still describe the unstaged Save As output, and `measure` and `accept`
re-derive the staged DF0 from it, blocking any other difference.
"""

from __future__ import annotations

import argparse
import base64
import copy
import functools
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import stat
import sys
import time
import uuid
from collections.abc import Mapping
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import amiga_adf, amiga_savegame, areas, dos_codec, geo  # noqa: E402
from tools.amiga import (  # noqa: E402
    amigabladesjournal,
    route_camp,
    route_silver_blades,
)
from tools.amiga.route import (  # noqa: E402
    ISSUE,
    TITLE_LIMIT,
    AmigaTitle,
    check_expect,
    parse_expect,
)
from tools.amiga.route_curse import (  # noqa: E402
    CURSE,
    CURSE_DISK_B_SHA256,
    CURSE_KEY,
    CURSE_SOURCES,
    _prepare_curse,
)
from tools.amiga.route_darkness import (  # noqa: E402
    DARKNESS,
    DARKNESS_DISK1_SHA256,
    DARKNESS_DISK2_SHA256,
    DARKNESS_DISK3_SHA256,
    DARKNESS_RELOAD,
    DARKNESS_UNSTARTED,
    DARKNESS_UNSTARTED_LOADED,
    DARKNESS_VAULT,
    DARKNESS_VOLUME,
    VAULT_PAGES,
    _prepare_darkness,
    _prepare_darkness_reload,
    published_reload_title,
    published_title,
    vault_steps,
    vault_title,
)
from tools.amiga.route_pool import (  # noqa: E402
    POOL,
    POOL_SOURCES,
    _prepare_pool,
    pool_camp_title,
    pool_title_for,
)
from tools.amiga.route_silver_blades import (  # noqa: E402
    ACCEPT_ROUTE,
    CAMP_SAVE_LETTER,
    LOAD_MESSAGE,
    MENU_SAVE_LETTER,
    ROUTE,
    SILVER_BLADES_INTERSTITIALS,
    SLOT_LETTER,
    SUBSTITUTE_TITLE_MODE,
    _silver_blades_problems,
    _slot_reading,
    journal_preflight,
    run_journal_answer,
)
from tools.amiga.screens import PixelGuards, _guards, _has_rule  # noqa: E402
from tools.amiga.staging import (  # noqa: E402
    StageError,
    _entry,
    _find_images,
    _verified_disk,
    replace_file_in_place,
    sha256,
    stage_place,
)
from tools.amiga.winuaesession import (  # noqa: E402
    HOLDER,
    SHOT_SECONDS,
    RouteError,
    WinGuest,
    terminating,
)
from tools.registry import evidence, scratch, specimens  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PUBLISHED_ISSUE = "677"
#: A run folder's ticket: a bare number, or a Plane `WISH-N`. The source pins of
#: `PUBLISHED_SOURCES_BY_ISSUE` are keyed by the number alone.
ISSUE_ARGUMENT = re.compile(r"\d+|WISH-\d+")
#: The manifest modes of a Pools of Darkness run on a disk 3 that Wish wrote.
PUBLISHED_DISK_THREE_MODE = "published_disk_three"
PUBLISHED_DISK_THREE_RELOAD_MODE = "published_disk_three_reload"
#: Pinned Save As sources a published disk-one run may start from, as a set of SHA-256 values per
#: title and port. The Silver Blades pair and the Curse C64 pair each hold one party of share 0 and
#: one of share 1.
PUBLISHED_SOURCES = {
    ("ssb", "c64"): frozenset({
        "38c11440e578227c1a240b740f362b1b69943d9897f42dc35ac39b17508872dc",
        "bacfa0d95954aacaabfe61d871ef39d989d70a11f9b125ca6a2d51ee41519240",
    }),
    ("ssb", "dos"): frozenset({"b3515793dada24b6a85061f5c2fdc5555a45df40381ee0009e9fd54ba381fb72"}),
    ("curse", "c64"): frozenset({
        "fdf74e5ff41fe0f90f8f9b150d966df276c4dc4e5ecd6829efee2fee9019acc1",
        "8fefc9d73136b0db87e4996e5cc24855a4cb32e1c4db15a668814363d4bdb076",
    }),
    ("curse", "dos"): frozenset({"4e911c12a449a4ff1694aab6d918f120c176df66483e32428cb50454db8b03df"}),
}
#: Pinned Save As sources per issue a published disk-one run may be filed under.
PUBLISHED_SOURCES_BY_ISSUE = {
    PUBLISHED_ISSUE: PUBLISHED_SOURCES,
    "640": {
        ("curse", "c64"): frozenset({"97099201a9c77ae43ab7d4605fd7a9dab2864333a5239177a41c5658e997007b"}),
        ("ssb", "c64"): frozenset({"5bb68551effa8a0d37ebc5f103a664e71505a798190d14ba8efa7730dd30e8a9"}),
    },
    # The joined C64 party (Guy de Valois, a paladin whose HEAL is unspent) and the game-written
    # spent or healed saves of both titles: the Silver Blades C64 save after his HEAL expired,
    # and the DOS slot D and C64 saves each route starts from.
    "628": {
        ("ssb", "c64"): frozenset({
            route_silver_blades.JOIN_SHA256,
            "8246b96031f6c89e24ca5b096608b779b361e0413be85647d68c27b0ffa61a62",
        }),
        ("ssb", "dos"): frozenset({"73bf301c77280eb39218fc7f6e9176cee15560585e7d20016adfd756a52b9269"}),
        ("curse", "dos"): frozenset({"28cacbb27d4aff5bfef4c3e11a94e35d5d0bac2aa6180c394d784f7ec97e8789"}),
        ("curse", "c64"): frozenset({"e99bb2be9c1a1a2c5f815f4fac436d7cc0a4ac3c511e7ad0a9ae1e5e7436684a"}),
    },
    # The C64 Curse party that fled the tavern brawl under Bless, a camp Prayer and Detect
    # Magic, reloaded and resaved by the game: TRAVIS and LEDERA, with four members left behind.
    "666": {
        ("curse", "c64"): frozenset({"9facc90c1f7cefdb909368b6db5b8135960631244ac259d21fab65d681352041"}),
    },
    # The game-written Silver Blades C64 hold resave whose sixth member, MORGAINE, is
    # feebleminded; the game-written Curse C64 save of Feeblemind cast on its first member,
    # MATHEW; and the Wish-staged, edited Curse C64 copy with six running-spell rows
    # (`WISH_STAGED_SOURCES`).
    "661": {
        ("ssb", "c64"): frozenset({"1e5a51d1d630b518306ae9772b85de61715384ac674077fafb79f54c613e1e16"}),
        ("curse", "c64"): frozenset({
            "9f7217a53ffe162bad585bfdf93a938929165ed2e5d2552287127c79696471a9",
            "f156738583fd49be75b7d481b47080e6708dbc83a7cdfe8bf3533c6fa8806696"}),
    },
    # The game-written C64 Curse save of the strength-spell ladder, reloaded and resaved, and the
    # DOS Silver Blades save of Slow Poison cast on a poisoned companion, resaved while it runs.
    "667": {
        ("curse", "c64"): frozenset({"ff3228edf42aa56a0fbf5159e8354358a38673115216a1b6c7f3439cae2686f2"}),
        ("ssb", "dos"): frozenset({"91a136ce86b34267b81d1ddd1d5037ce54d1a7d5b7e63732dddcb0af3070921b"}),
    },
    # The game-written DOS Pools of Darkness saves the Save As to the Amiga disk 3 route starts
    # from: slot C after Lay on Hands and a one-hour rest, then the seven-member vault party, the
    # overland party and the party the DOS game created itself.
    "2": {
        ("darkness", "dos"): frozenset({
            "ee979bf89164742816841c9ad2dc5a550f35b3a52eec2ad3fae138c9a1653918",
            "416df285086ae434bbad4efcd2943bb419b94b287d2382fe9f5706bbb15ed371",
            "ed4a9f68f9e2f9064d229872bce0a2f87e017c8865123159f9af54a6d8a25bb8",
            "e913382f73be2ace0c95642d8a7742f5478ade09302f0abfe46f6259db30c11c"}),
    },
    # The DOS Silver Blades save with the Quarter Staff in the joined party's lists, which the
    # leave-behind and joined-scroll Save As route converts to the Amiga.
    "4": {
        ("ssb", "dos"): frozenset({"31add9859ac5cca469b7eef575ac91ecbdda2fcb49f10a174b3ccc081f4e4e0f"}),
    },
    # The two DOS saves the Character Editor's Save As converts to the Amiga: the Curse party
    # with a dual-classed member and the Silver Blades party joined by arrow.
    "22": {
        ("curse", "dos"): frozenset({"4e911c12a449a4ff1694aab6d918f120c176df66483e32428cb50454db8b03df"}),
        ("ssb", "dos"): frozenset({"b3515793dada24b6a85061f5c2fdc5555a45df40381ee0009e9fd54ba381fb72"}),
    },
}


#: Pinned sources that Wish edited rather than the game wrote; a run from one says so in its
#: preserved specimen.
WISH_STAGED_SOURCES = frozenset({"f156738583fd49be75b7d481b47080e6708dbc83a7cdfe8bf3533c6fa8806696"})


def _source_pins(issue: str, name: str, port: str) -> frozenset:
    """The allowed source hashes for a title and port; a bare string counts as a set of one."""
    pins = PUBLISHED_SOURCES_BY_ISSUE[issue].get((name, port), frozenset())
    return frozenset({pins}) if isinstance(pins, str) else frozenset(pins)


PUBLISHED_ISSUE_TEXT = {
    PUBLISHED_ISSUE: (
        "#677 (Save As to the Amiga puts a Curse or Silver Blades party on a separate "
        "save disk that the game never reads while its own disk A is in DF0)"),
    "640": ("#640 (A Curse or Silver Blades party saved before BEGIN ADVENTURING "
            "cannot be converted at all)"),
    "628": ("#628 (The neutral vocabulary has no field for a paladin's lay-on-hands uses, "
            "so a converted paladin loses them)"),
    "666": ("#666 (A C64 party under a camp Prayer loses it on the way to DOS or the Amiga, "
            "because nothing converts the save's party-wide effect rows)"),
    "661": ("WISH-7 (A C64 party under a running spell loses it on the way to DOS or the Amiga "
            "with no line anywhere, because the C64 reader reads only the paladin's rows out of "
            "the effect arrays)"),
    "667": ("#667 (A DOS party under Prayer, the strength and charisma spells, Mirror Image or "
            "an effect with no C64 spell row is still blocked when saved as a C64 save, because "
            "only the ordinary caster-level spells convert)"),
    "22": ("WISH-22 (Validate Character Editor Open, Save and Save As across C64, DOS and "
           "Amiga)"),
}
PUBLISHED_DISKS = {
    "ssb": ("2f9ae86494561231dd1d70b350ae07b959c9f62642b64e9d4b57ffd23686ace4",
            route_silver_blades.DISK_B_SHA256, "/Secret", "Secret 1"),
    "curse": ("4bfb64d1ebcf53867b941412ce04eb248b43dadebe34769f73ffa1aa609002ed",
              CURSE_DISK_B_SHA256, "/Curse", "CurseA"),
}

# Single grabs every ~8-10 s in all against a bar that held still for at least 24 s.
TITLE_POLL = 2.0
MEASURE_BOOT_POLL = 10.0
MEASURE_TITLE_SPAN = 120.0
GUARD_POLL = 5.0
GUARD_LIMIT = 120.0
# A key pressed while the disk is being written is swallowed, so the screen
# after the write gets the same long first wait as the load picker.
POST_WRITE_WAIT = 20.0
#: Each lane's boot log; `winuae.ps1 start` makes the lane folder WinUAE's data folder and deletes the old log.
BOOT_LOG = r"C:\Amiga\lanes\{lane}\winuaebootlog.txt"

#: The most draws one boot may make; the route's own camp save is the first.
RULEBOOK_DRAWS_MAX = 15
#: Seconds one draw's question may take to answer, for the deadline check; measured answers ran 48 to 114 s.
DRAW_ANSWER_SECONDS = 120.0


class DrawCounter:
    """Stages the next camp save's question in the running game, through the private helper.

    `target` is an `AmigaTarget`. `lane_check` proves this run still holds the WinUAE lane and
    raises when it does not; it runs before every write.
    """

    def __init__(self, target: Any, savecount: Any, lane_check: Callable[[], Any],
                 drawseed: Any = None) -> None:
        self.target, self.savecount, self.lane_check = target, savecount, lane_check
        self.drawseed = drawseed
        self.base: int | None = None

    def locate(self) -> None:
        """Find the running game once; a title that is not there fails here, before any save."""
        from tools.amiga.amigatarget import A4_BIAS  # noqa: PLC0415

        if self.base is None:
            self.base = self.target.locate() + A4_BIAS

    def stage(self, record: int | None = None) -> None:
        """Stage the next question; with `record`, also make the draw give that rule-book record."""
        self.locate()
        try:
            self.lane_check()
        except Exception as exc:
            raise RouteError(f"the lane claim was not confirmed: {type(exc).__name__}: {exc}") from exc
        self.savecount.stage_live(self.target.read, self.target.write, self.base)
        if record is not None:
            # `stage_live` has already written by now; harmless, because a failure here ends the run.
            try:
                self.drawseed.stage_draw(self.target.read, self.target.write, self.base, record)
            except Exception as exc:
                raise RouteError(f"drawseed stage_draw failed: {type(exc).__name__}") from None

    def drawn(self) -> int:
        """The rule-book record the game's last draw gave, from the private helper.

        Read after EXIT GAME; the first live run confirms the state still reads correctly then.
        Any helper failure is reduced to its type, so no helper message reaches the run's error.
        """
        try:
            return self.drawseed.drawn(self.target.read, self.base)
        except Exception as exc:
            raise RouteError(f"drawseed drawn failed: {type(exc).__name__}") from None


    def reader_index(self, record: int) -> int:
        """The table index the journal reader reports for rule-book record `record`."""
        try:
            return self.drawseed.reader_index(record)
        except Exception as exc:
            raise RouteError(f"drawseed reader_index failed: {type(exc).__name__}") from None


def _load_drawseed() -> Any:
    """The private repository's `drawseed` module, loaded by path; failures name no message."""
    path = amigabladesjournal.wheel_repo() / "ssb" / "analysis" / "drawseed.py"
    if not path.is_file():
        raise RouteError(f"{path} is missing; ${amigabladesjournal.ENV} names the "
                         "private repository that holds it")
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("drawseed", path)
        if spec is None or spec.loader is None:
            raise RouteError(f"{path} cannot be loaded as a module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except RouteError:
        raise
    except (Exception, SystemExit) as exc:
        raise RouteError(f"{path} failed to load: {type(exc).__name__}") from None
    finally:
        sys.path.remove(str(path.parent))
    return module


def _keep_tally_lines() -> list[str]:
    """The answerer's kept tally lines so far, or none when it keeps no captures."""
    keep = os.environ.get(route_silver_blades.KEEP_ENV)
    tally = pathlib.Path(keep) / amigabladesjournal.TALLY if keep else None
    if tally is None or not tally.is_file():
        return []
    return [x for x in tally.read_text(encoding="utf-8").splitlines() if x.strip()]


def _reader_index(before: list[str], after: list[str]) -> int | None:
    """The table index the reader gave the one capture kept since `before`, else None."""
    if len(after) != len(before) + 1:
        return None
    try:
        value = json.loads(after[-1]).get("record")
    except ValueError:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


#: The snapshot a walk retry restores; a `--camp` step may not use the name.
WALK_LEG = "walk-leg"


class GuardMissed(RouteError):
    """A guarded state's screen did not match within its limit."""


def _walk_leg(steps: Any) -> tuple[int, int] | None:
    """The 1-based first and last step of the contiguous `turn`/`move` run that starts the walk."""
    walking = [n for n, step in enumerate(steps, 1) if step[2] in ("turn", "move")]
    if not walking:
        return None
    end = walking[0]
    while end < len(steps) and steps[end][2] in ("turn", "move"):
        end += 1
    return walking[0], end


def check_marks(marks: Mapping[int, tuple[tuple[str, str], ...]], steps: Any) -> None:
    """Block machine steps that cannot run: a restore before its snapshot, one after a save, one off the route."""
    taken: dict[str, bool] = {}
    if any(not 0 <= index <= len(steps) for index in marks):
        raise RouteError("a snapshot or restore step falls outside the route")
    if marks.get(0):
        raise RouteError("a snapshot or restore step cannot come before the first route step: "
                         "no screen has been reached to put back")
    for index in range(len(steps) + 1):
        for verb, called in marks.get(index, ()):
            name = called.lower()
            if verb == "snapshot":
                taken[name] = False
            elif verb != "restore":
                raise RouteError(f"{verb!r} is not a snapshot or restore step")
            elif name not in taken:
                raise RouteError(f"restore {called}: no snapshot {called!r} was taken before it")
            elif taken[name]:
                raise RouteError(
                    f"restore {called}: a game save came between its snapshot and it, and a "
                    f"restore puts the machine back while the save stays on the disk image, "
                    f"so the run would no longer be one consistent game")
        if index < len(steps) and steps[index][2] == "write":
            taken = dict.fromkeys(taken, True)


def _step_wait(min_waits: dict[str, float], state: str, kind: str) -> float:
    return min_waits.get(state, POST_WRITE_WAIT if kind == "write" else 0)


def _check_draws_fit(draws: int, steps: Any, min_waits: dict[str, float],
                     deadline_seconds: float) -> None:
    """Block a run whose draws cannot fit the route time, by the steps' minimum waits.

    The route itself is estimated by the sum of its minimum waits, and each further draw by
    its three steps' waits plus `DRAW_ANSWER_SECONDS`; the route time is the deadline less
    its cleanup reserve.
    """
    route = sum(_step_wait(min_waits, state, kind) for _, state, kind in steps)
    each = sum(_step_wait(min_waits, state, kind) for _, state, kind in steps[-3:]
               ) + DRAW_ANSWER_SECONDS
    needed = route + (draws - 1) * each
    available = deadline_seconds - min(300.0, deadline_seconds / 2)
    if needed > available:
        raise RouteError(f"{draws} rulebook draws need about {needed:.0f}s of route time "
                         f"and the deadline leaves {available:.0f}s")


def _diagnose_bytes(guest: Any, holder: str, address: int, length: int,
                    limit: Callable[[float], float]) -> tuple[bytes, list[dict[str, Any]]]:
    from automap.amiga import parse_memory_dump  # noqa: PLC0415

    reads = []
    data: dict[int, int] = {}
    for line_address in range(address & ~15, address + length, 16):
        receipt = guest.diagnose(holder, "DBG", "m", address=line_address,
                                 timeout=limit(20))
        reads.append(receipt)
        data.update(parse_memory_dump(receipt["reply"]))
    try:
        return bytes(data[n] for n in range(address, address + length)), reads
    except KeyError as exc:
        raise RouteError(f"Exec memory reply omitted {exc.args[0]:#x}") from exc


def _exec_sample(guest: Any, holder: str,
                 limit: Callable[[float], float]) -> dict[str, Any]:
    ptr, ptr_reads = _diagnose_bytes(guest, holder, 4, 4, limit)
    base = int.from_bytes(ptr, "big")
    if not base or base > 0xFFFFFFFF - 0x120:
        raise RouteError(f"ExecBase pointer is invalid: {base:#x}")
    values, value_reads = _diagnose_bytes(guest, holder, base + 0x114, 12, limit)
    return {"execbase": base, "this_task": int.from_bytes(values[:4], "big"),
            "idle": int.from_bytes(values[4:8], "big"),
            "disp": int.from_bytes(values[8:], "big"),
            "replies": ptr_reads + value_reads}


def _shot_source(guest: Any) -> dict[str, Any]:
    """Where the guest's last frame came from (`source`, `pid`, `counter`), for the grab events."""
    return dict(getattr(guest, "last_shot", None) or {})


def _white_screen(path: pathlib.Path) -> bool:
    from PIL import Image  # noqa: PLC0415

    with Image.open(path) as image:
        return all(low >= 245 for low, _ in image.convert("RGB").getextrema())


def _wait_option(wait_lane: float) -> dict[str, float]:
    """The `wait` a WinUAE `claim` takes; none when no wait was asked for, which is every other lane."""
    return {"wait": wait_lane} if wait_lane > 0 else {}


def _run_diagnose(manifest_path: pathlib.Path, manifest: dict, title: AmigaTitle,
                  disks: dict, guest: Any, guard: Any, holder: str,
                  audio_proof: pathlib.Path | None, attempt: str, deadline: float,
                  boot_limit: float, wait_lane: float = 0.0) -> dict[str, Any]:
    """Boot the published title without game input and preserve each read and cleanup receipt."""
    out = manifest_path.parent / attempt
    out.mkdir(parents=False, exist_ok=False)
    shots = scratch.ensure(out / "shots")
    remotes = {key: guest.remote_path(title.issue, holder, key) for key in title.disk_keys}
    result: dict[str, Any] = {
        **evidence.git_state(REPO), "argv": sys.argv[1:], "diagnose": True,
        "accept": False, "measure": False, "success": False, "completed": False,
        "holder": holder, "input": str(manifest_path), "remotes": remotes,
        "events": [], "fetched": {}, "error": "", "deadline_seconds": deadline,
        "boot_limit_seconds": boot_limit,
    }
    begun = time.monotonic()
    end = begun + deadline
    claimed = started = stopped = config_staged = False

    def limit(seconds: float) -> float:
        left = end - time.monotonic()
        if left <= 0:
            raise RouteError("diagnose total deadline reached")
        return min(seconds, left)

    def cleanup_limit(seconds: float, minimum: float = 5.0) -> float:
        left = end - time.monotonic()
        if left < minimum:
            if left < 1:
                result["cleanup_after_deadline"] = True
            return min(seconds, minimum)
        return min(seconds, left)

    try:
        receipt = guest.claim(holder, timeout=30 if wait_lane > 0 else limit(30),
                              **_wait_option(wait_lane))
        if receipt != f"ok claimed by {holder}":
            raise RouteError(f"claim was not new: {receipt!r}")
        if wait_lane > 0:
            # The wait for a lane is not part of the run: the deadline starts at the grant.
            begun = time.monotonic()
            end = begun + deadline
        claimed = True
        result["claim"] = receipt
        for key, path in disks.items():
            guest.put(path, remotes[key], timeout=limit(90))
        config_staged = True
        result["remote_config_path"] = WinGuest.private_config_path(holder)
        result["config"] = guest.stage_private_config(holder, timeout=limit(60))
        if not guest.silence(audio_proof):
            raise RouteError("the Windows VM audio mute proof expired before WinUAE start")
        started = True
        result["start"] = guest.start(
            holder, *(None if key is None else remotes[key] for key in title.mounted),
            timeout=limit(60), options=title.options, config=result["config"]["path"])
        result["lane"] = guest.lane(holder, timeout=limit(30))
        boot_started = time.monotonic()
        # Stop, two disk fetches, boot-log fetch, config removal and release each
        # have their own bounded call; keep their full allowance after the boot.
        boot_end = min(boot_started + boot_limit, end - 240)
        if boot_end <= boot_started:
            raise RouteError("diagnose has no time left for a boot and cleanup")

        def boot_limit_for(seconds: float) -> float:
            left = min(boot_end, end) - time.monotonic()
            if left <= 0:
                raise RouteError("diagnose boot deadline reached during a read")
            return min(seconds, left)

        result["readback"] = {
            key: guest.diagnose(holder, "CFG", key, timeout=boot_limit_for(20))
            for key in ("gfx_api", "floppy0", "floppy1")}
        expected = {"gfx_api": "directdraw", "floppy0": remotes["df0"].replace("/", "\\"),
                    "floppy1": remotes["df1"].replace("/", "\\")}
        for key, wanted in expected.items():
            if result["readback"][key]["reply"] != f"200 \n{wanted}":
                raise RouteError(f"guest {key} readback differs from the private run")
        n = 0
        sampled = False
        while time.monotonic() < boot_end:
            name = f"00-boot-{n:02d}"
            raw, crop = shots / f"{name}.raw.png", shots / f"{name}.png"
            remaining = boot_end - time.monotonic()
            if remaining <= 0:
                break
            shown = guest.grab(name, raw, crop, timeout=boot_limit_for(min(SHOT_SECONDS, remaining)))
            event = {"state": name, "raw": str(raw), "raw_sha256": sha256(raw),
                     "crop": str(crop) if shown else None, **_shot_source(guest)}
            if shown:
                event["crop_sha256"] = sha256(crop)
                if guard("title", crop):
                    event["recognized"] = "title"
                    result["events"].append(event)
                    result["completed"] = True
                    break
                for other in getattr(guard, "rules", {}):
                    if other != "title" and guard(other, crop):
                        event["recognized"] = other
                        if other != "credits":
                            result["events"].append(event)
                            raise RouteError(f"recognized {other} before the title")
                        break
            result["events"].append(event)
            elapsed = time.monotonic() - boot_started
            if shown and elapsed >= 120 and not sampled and _white_screen(crop):
                sampled = True
                result["white_probe"] = {"elapsed_seconds": elapsed,
                                         "status": guest.status(timeout=boot_limit_for(20))}
                first = _exec_sample(guest, holder, boot_limit_for)
                result["white_probe"]["first"] = first
                time.sleep(min(1, boot_limit_for(1)))
                second = _exec_sample(guest, holder, boot_limit_for)
                result["white_probe"]["second"] = second
            n += 1
            time.sleep(min(TITLE_POLL, max(0, boot_end - time.monotonic())))
        if not result["completed"]:
            raise RouteError(f"title screen was not recognized within {boot_limit:.0f}s")
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if started:
            try:
                result["stop"] = guest.stop(holder, timeout=cleanup_limit(30, minimum=20))
                stopped = True
            except BaseException as exc:
                result["stop_error"] = f"{type(exc).__name__}: {exc}"
        if claimed:
            for key, remote in remotes.items():
                local = out / f"fetched-{key}.adf"
                try:
                    guest.get(remote, local, timeout=cleanup_limit(60))
                    result["fetched"][key] = _entry(local)
                except BaseException as exc:
                    result[f"fetch_{key}_error"] = f"{type(exc).__name__}: {exc}"
            if started:
                try:
                    if "lane" not in result:
                        raise RouteError("the lane is unknown, so its boot log cannot be read")
                    bootlog = out / "winuaebootlog.txt"
                    result["boot_log_fresh"] = False
                    guest.get(BOOT_LOG.format(lane=result["lane"]), bootlog,
                              timeout=cleanup_limit(30))
                    result["boot_log"] = _entry(bootlog)
                    content = bootlog.read_text(errors="replace")
                    # `start` deleted the lane's previous log, so one that is there now is this launch's.
                    result["boot_log_fresh"] = True
                    result["boot_log_matches_start"] = all(
                        path in content for path in (
                            result["config"]["path"],
                            remotes["df0"].replace("/", "\\"),
                            remotes["df1"].replace("/", "\\")))
                    if not result["boot_log_matches_start"]:
                        result["boot_log_error"] = "boot log names another launch"
                    result["gfx_api_rejected"] = bool(re.search(
                        r"Unknown value .* for option 'gfx_api'",
                        content, re.IGNORECASE))
                except BaseException as exc:
                    result["boot_log_error"] = f"{type(exc).__name__}: {exc}"
            if config_staged:
                try:
                    result["config_removed"] = guest.remove_private_config(holder,
                                                                             timeout=cleanup_limit(30))
                except BaseException as exc:
                    result["config_remove_error"] = f"{type(exc).__name__}: {exc}"
            if not started or stopped:
                try:
                    result["release"] = guest.release(holder, timeout=cleanup_limit(30))
                except BaseException as exc:
                    result["release_error"] = f"{type(exc).__name__}: {exc}"
        for key, path in disks.items():
            result[f"{key}_local_unchanged"] = sha256(path) == manifest["disks"][key]["sha256"]
            if key in result["fetched"]:
                result[f"{key}_fetched_unchanged"] = (
                    result["fetched"][key]["sha256"] == manifest["disks"][key]["sha256"])
        result["remote_config_dirty"] = config_staged and not bool(result.get("config_removed"))
        result["success"] = bool(result["completed"] and not result["error"] and stopped
                                 and result.get("release") and result.get("config_removed")
                                 and result.get("boot_log_fresh")
                                 and result.get("boot_log_matches_start")
                                 and not result.get("gfx_api_rejected")
                                 and all(result.get(f"{key}_fetched_unchanged") for key in disks))
        result["elapsed_seconds"] = time.monotonic() - begun
        (out / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result

# A state the guard map has must match or the run stops; the rest are measured
# by settling a capture and are marked unguarded.
IDENTITY_MESSAGES = {"sheet": "sheet shows another member",
                     "loaded_menu": "loaded_menu shows another party"}

def _input(manifest: dict, name: str) -> pathlib.Path:
    entry = manifest[name]
    path = pathlib.Path(entry["path"])
    if not path.is_file() or sha256(path) != entry["sha256"]:
        raise RouteError(f"{name} is missing or changed from preparation")
    return path


def _published_files_preserved(manifest: dict, title: AmigaTitle, fetched: amiga_adf.AmigaDisk) -> bool:
    """Whether the fetched DF0 holds every file it started with, the game having added only its two saves.

    What it started with is the published image, or working DF0 when a place was staged
    into its loaded slot.
    """
    start = (manifest["disks"]["df0"] if "staged_place" in manifest
             else manifest["registered"]["published"])
    before_files = _disk_files(_verified_disk(pathlib.Path(start["path"])))
    after_files = _disk_files(fetched)
    extension = "dat" if manifest["title"] == "curse" else "sav"
    writable = {f"/save/savgam{c}.{extension}".lower()
                for c in (title.control_letter, title.after_letter)}
    return (set(after_files) == set(before_files) | writable and
            all(after_files.get(path) == data for path, data in before_files.items()
                if path not in writable))


def _no_problems(reading: dict[str, Any], slot: str) -> list[str]:
    return []


def menu_save_problems(manifest: dict, reading: dict[str, Any], *, letter: str = "B",
                       check_place: bool = True, names: list[str] | None = None,
                       extra_problems: Any = _silver_blades_problems) -> list[str]:
    """What a save left different from the prepared party; empty means it matches.

    `names` replaces the inventory's member names as what the save must hold, and
    `extra_problems(reading, slot)` adds a title's own checks.
    """
    slot = f"slot {letter}"
    if reading.get("missing"):
        return [f"{slot} was not written"]
    if "decode_error" in reading:
        return [f"{slot} does not decode: {reading['decode_error']}"]
    problems = []
    if check_place and reading["place"] != manifest["state_a"]:
        problems.append(
            f"{slot} place {reading['place']} differs from {manifest['state_a']}")
    wanted = names if names is not None else [
        member["name"] for member in manifest["inventory_a"]["members"]]
    if reading["names"] != wanted:
        problems.append(f"{slot} members {reading['names']} differ from {wanted}")
    problems += extra_problems(reading, slot)
    return problems


def _span(a: dict, b: dict) -> str:
    """`3,5 to 3,7`; the area and facing are named only when they differ."""
    if a["area"] == b["area"] and a["facing"] == b["facing"]:
        return f"{a['x']},{a['y']} to {b['x']},{b['y']}"
    return (f"area {a['area']} {a['x']},{a['y']} facing {a['facing']} to "
            f"area {b['area']} {b['x']},{b['y']} facing {b['facing']}")


def _unreadable(letter: str, reading: dict[str, Any]) -> str:
    return f"slot {letter}: " + ("was not written" if reading.get("missing")
                                 else "does not decode")


def walk_verdict(before: dict, b: dict[str, Any], d: dict[str, Any],
                 squares: int, *, control: str = "B", after: str = "D",
                 turn: str | None = None,
                 edge_exits: Mapping[tuple[int, int], int] | None = None) -> dict[str, Any]:
    """Judge the two saves: `control`, saved before the walk, must be `before`; `after` must be `squares` on.

    The step routine wraps at 0 and 15, so `after` is compared modulo 16 along the
    control's facing, or along the opposite facing when `turn` is "about". The
    screen never judges movement. A step off the 16x16 map enters the area `edge_exits` names for
    the area and facing, on the wrapped square, and `area_crossed` records it; with no row
    the prediction stays in the starting area.
    """
    verdicts: list[str] = []
    b_place, d_place = b.get("place"), d.get("place")
    b_ok = d_ok = walk_blocked = walk_partial = False
    if b_place is None:
        verdicts.append(_unreadable(control, b))
    elif b_place == before:
        b_ok = True
        verdicts.append(f"slot {control}: did not move")
    else:
        verdicts.append(f"slot {control}: moved from {_span(before, b_place)}, "
                        f"expected the prepared place")
    base = b_place or before
    squares_moved = None
    area_crossed = None
    if d_place is None:
        verdicts.append(_unreadable(after, d))
    else:
        facing = geo.OPPOSITE[base["facing"]] if turn == "about" else base["facing"]
        dx, dy = geo.STEP[facing]
        area, x, y = base["area"], base["x"], base["y"]
        for _ in range(squares):
            x, y = x + dx, y + dy
            if not (0 <= x < 16 and 0 <= y < 16):
                area = (edge_exits or {}).get((area, facing), area)
            x, y = x % 16, y % 16
        expected = dict(base, area=area, facing=facing, x=x, y=y)
        crossed = area != base["area"]
        if d_place["area"] == base["area"] and d_place["facing"] == facing:
            along = (d_place["x"] - base["x"]) * dx + (d_place["y"] - base["y"]) * dy
            across = (d_place["x"] - base["x"]) * dy + (d_place["y"] - base["y"]) * dx
            # A wrapped step and a full lap cannot be told apart on 16 squares.
            if across == 0 or (across % 16 == 0):
                squares_moved = along % 16
        if crossed and d_place == expected:
            squares_moved = squares
            area_crossed = {"from": base["area"], "to": area}
        same_square = (d_place["area"], d_place["x"], d_place["y"]) == (
            base["area"], base["x"], base["y"])
        if turn == "about" and d_place == expected:
            d_ok = True
            unit = "square" if squares == 1 else "squares"
            verdicts.append(f"slot {after}: moved {squares} {unit} from "
                            f"{_span(base, d_place)}")
        elif d_place == base or (turn == "about" and same_square):
            d_ok = squares == 0 and turn is None
            # The party did not move although steps were asked for; a wall and an
            # unregistered key press read identically here, so this is not proof of a wall.
            walk_blocked = squares != 0
            verdicts.append(f"slot {after}: did not move")
        elif d_place == expected:
            d_ok = True
            unit = "square" if squares == 1 else "squares"
            verdicts.append(f"slot {after}: moved {squares} {unit} from "
                            f"{_span(base, d_place)}")
        else:
            # Gaining some squares along the planned line and then stopping is a walk that
            # happened and met a wall; any other landing is still a failure.
            walk_partial = (turn is None and squares_moved is not None
                            and 0 < squares_moved < squares)
            verdicts.append(f"slot {after}: moved from {_span(base, d_place)}, "
                            f"expected {expected['x']},{expected['y']}")
    return {"verdicts": verdicts, "b_ok": b_ok, "d_ok": d_ok, "walk_blocked": walk_blocked,
            "walk_partial": walk_partial, "squares_requested": squares,
            "place_changed": None if d_place is None else d_place != base,
            "squares_moved": squares_moved,
            "area_crossed": area_crossed}


_ACCEPT_ONLY = frozenset({"continue", "journal"})


def place_state(place: dict[str, Any]) -> str:
    """The guard-map key for a decoded place; the area is left out because the screen does not show it."""
    return f"place_x{place['x']}_y{place['y']}_f{place['facing']}"


def _title_inputs(manifest: dict, title: AmigaTitle) -> tuple[dict, dict, str]:
    """The manifest's disks and registered images, each checked, and its loaded letter."""
    try:
        disks = {key: _input(manifest["disks"], key) for key in title.disk_keys}
        registered = {key: _input(manifest["registered"], key) for key in manifest["registered"]}
        loaded = manifest["loaded_letter"]
        manifest["state_a"], manifest["names_a"]  # noqa: B018
    except KeyError as exc:
        raise RouteError(f"the manifest lacks {exc.args[0]!r}") from exc
    if len({p.resolve() for p in (*disks.values(), *registered.values())}) != (
            len(disks) + len(registered)):
        raise RouteError("the manifest's disks and registered images must be separate files")
    if loaded in (title.control_letter, title.after_letter):
        raise RouteError(f"save letter {loaded} would overwrite the prepared slot")
    return disks, registered, loaded


def menu_save_verdict(result: dict[str, Any], originals: tuple[str, ...]) -> bool:
    """A guarded run passes when the game wrote slot B as prepared and touched nothing else."""
    return bool(
        not result["error"] and not result["menu_save_problems"]
        and result.get("slot_unchanged") and result.get("slot_a_unchanged")
        and result.get("df1_unchanged") and result.get("published_unchanged")
        and result.get("working_unchanged")
        and all(result.get(f"{name}_unchanged") for name in originals)
        # The write to slot B is the point of the run, so DF0 must have changed.
        and result.get("df0_unchanged") is False)


CLOCK_UNPROVABLE = "unprovable: rest wraps the day"


def _clock_advanced(before: str, after: str, rest: int = 0) -> bool:
    """Accept a short forward interval beyond `rest` minutes, including a midnight rollover.

    The saved clock shows no day, so a rest is judged modulo one day.
    """
    try:
        start_h, start_m = (int(part) for part in before.split(":"))
        end_h, end_m = (int(part) for part in after.split(":"))
    except (AttributeError, TypeError, ValueError):
        return False
    if not all(0 <= h < 24 and 0 <= m < 60 for h, m in ((start_h, start_m),
                                                      (end_h, end_m))):
        return False
    elapsed = ((end_h * 60 + end_m) - (start_h * 60 + start_m) - rest) % (24 * 60)
    return 0 < elapsed <= 120


def _read_title(title: AmigaTitle, manifest: dict, result: dict[str, Any],
                out: pathlib.Path, disks: dict[str, pathlib.Path],
                registered: dict[str, pathlib.Path], kept_before: dict[str, dict],
                loaded: str, accept: bool, measure: bool, steps: tuple,
                reload: bool = False) -> None:
    """Compare the fetched disks with the manifest, read the saves and set `success`."""
    result["registered_unchanged"] = {
        key: sha256(path) == manifest["registered"][key]["sha256"]
        for key, path in registered.items()}
    result["working_unchanged"] = {
        key: sha256(path) == manifest["disks"][key]["sha256"] for key, path in disks.items()}
    result["disks_unchanged"] = {
        key: entry["sha256"] == manifest["disks"][key]["sha256"]
        for key, entry in result["fetched"].items()}
    if reload:
        _read_reload(title, manifest, result, out, kept_before, loaded)
        return
    if title.save_disk in result["fetched"]:
        try:
            fetched = _verified_disk(out / f"fetched-{title.save_disk}.adf")
            control = title.read_slot(fetched, title.control_letter)
            result["control_sha256"] = control.get("sha256")
            if not measure:
                result["menu_save_problems"] = menu_save_problems(
                    manifest, control, letter=title.control_letter,
                    names=manifest["names_a"], extra_problems=_no_problems)
            if accept:
                after = title.read_slot(fetched, title.after_letter)
                result["after_sha256"] = after.get("sha256")
                result["camp_save_problems"] = menu_save_problems(
                    manifest, after, letter=title.after_letter, check_place=False,
                    names=manifest["names_a"], extra_problems=_no_problems)
                squares = sum(1 for *_, kind in steps if kind == "move")
                walk = walk_verdict(manifest["state_a"], control, after, squares,
                                    control=title.control_letter, after=title.after_letter,
                                    turn=title.turn, edge_exits=title.edge_exits)
                verdicts = list(walk["verdicts"])
                expected = manifest.get("expected_after")
                result["expected_after_matches"] = None
                if expected is not None:
                    matches = after.get("place") == expected
                    result["expected_after_matches"] = matches
                    verdicts.append(
                        f"slot {title.after_letter} "
                        f"{'matches' if matches else 'differs from'} "
                        f"the game's own save after the same walk")
                result["walk"] = walk
                result["read"] = {
                    "place_before": manifest["state_a"], "menu_save": control.get("place"),
                    "place_after": after.get("place"),
                    "place_changed": walk["place_changed"],
                    "squares_moved": walk["squares_moved"], "verdicts": verdicts}
                # Evidence only: each saved member's effect rows, [id, minutes, data, flag].
                if "effects" in control or "effects" in after:
                    result["read"]["effects"] = {
                        title.control_letter: control.get("effects"),
                        title.after_letter: after.get("effects")}
                result["kept_unchanged"] = {
                    c: title.slot_files(fetched, c) == before
                    for c, before in kept_before.items()}
                allowed = {*kept_before, title.control_letter, title.after_letter}
                result["extra_saves"] = sorted(set(title.slot_letters(fetched)) - allowed)
                if manifest.get("mode") == "published_disk_one":
                    result["published_files_preserved"] = _published_files_preserved(
                        manifest, title, fetched)
                    result["control_clock_matches"] = control.get("clock") == manifest["clock_a"]
                    rested = route_camp.rest_minutes(tuple(manifest.get("camp", ())))
                    # A rest of r leaves the clock at r plus a short walk, modulo a day, so this
                    # stays necessary when the rest is too long for the clock to prove it.
                    result["after_clock_advanced"] = _clock_advanced(
                        manifest["clock_a"], after.get("clock"), rested)
                    if rested >= route_camp.CLOCK_BLIND_REST:
                        result["clock_check"] = CLOCK_UNPROVABLE
                    else:
                        result["clock_check"] = ("advanced" if result["after_clock_advanced"]
                                                 else "not advanced")
        except BaseException as exc:
            result["fetched_save_error"] = f"{type(exc).__name__}: {exc}"
    every_disk_fetched = set(result["fetched"]) == set(title.disk_keys)
    if measure:
        result["success"] = bool(
            result.get("route_changed") and not result["error"] and every_disk_fetched
            and all(result["disks_unchanged"].values())
            and result.get("control_sha256", "absent") is None)
        return
    result.setdefault("menu_save_problems",
                      [f"slot {title.control_letter} was not read from the fetched save disk"])
    result.setdefault("read", {"verdicts": [
        f"slots {title.control_letter} and {title.after_letter} were not read from the "
        f"fetched save disk"]})
    others = [k for k in title.disk_keys if k != title.save_disk]
    rest = bool(
        not result["error"] and result["completed"] and not result["unguarded"]
        and every_disk_fetched and all(result["registered_unchanged"].values())
        and all(result["working_unchanged"].values())
        # The game writes to the save disk, and to nothing else.
        and result["disks_unchanged"].get(title.save_disk) is False
        and all(result["disks_unchanged"].get(k) for k in others)
        and result["menu_save_problems"] == []
        and result.get("camp_save_problems") == []
        and result.get("walk", {}).get("b_ok")
        and result.get("expected_after_matches") is not False
        and bool(result.get("kept_unchanged")) == bool(kept_before)
        and all(result.get("kept_unchanged", {}).values())
        and result.get("extra_saves") == [])
    if manifest.get("mode") == "published_disk_one":
        rest = bool(rest and result.get("published_files_preserved")
                    and result.get("control_clock_matches")
                    and result.get("after_clock_advanced"))
    if "camp" in manifest:
        sheets = result.get("camp_sheets", [])
        displays = result.get("camp_displays", [])
        result["read"]["verdicts"].extend(_camp_verdicts(sheets))
        result["read"]["verdicts"].extend(_display_verdicts(displays))
        result["read"]["verdicts"].extend(_join_verdicts(result.get("camp_joins", [])))
        # A sheet with neither bar is a member with no HEAL to show, such as a ranger; a
        # `heal` step's own sheets are states that must match, so HEAL is never read that way.
        # An effects list is read by its identity rule, so one without a rule reads nothing.
        rest = bool(rest and all(entry["identity_checked"] for entry in (*sheets, *displays)))
        if result.get("clock_check") == CLOCK_UNPROVABLE:
            # The clock only rules a rest out, so a sheet after the last rest must show it.
            shown = len(sheets) - result.get("sheets_before_last_rest", len(sheets))
            result["read"]["verdicts"].append(
                "the clock cannot prove this rest; " + (
                    f"{shown} sheet(s) recorded after the last rest" if shown > 0
                    else "no sheet was recorded after the last rest, so the rest is unproven"))
            rest = bool(rest and shown > 0)
    if "load_message" in result:
        result["read"]["verdicts"].append(_load_message_verdict(result["load_message"]))
    d_ok = bool(result.get("walk", {}).get("d_ok"))
    result["success"] = rest and d_ok
    walk = result.get("walk", {})
    result["substitute_walk_blocked"] = bool(
        "substitute" in manifest and (walk.get("walk_blocked") or walk.get("walk_partial")))
    result["passed_except_walk"] = bool(result["substitute_walk_blocked"] and rest)
    if result["substitute_walk_blocked"] and result.get("read"):
        clause = "; every other check passed" if result["passed_except_walk"] else ""
        if walk.get("walk_partial"):
            what = (f"the substituted party moved {walk['squares_moved']} of "
                    f"{walk['squares_requested']} squares and then stopped, which may be a wall")
        else:
            what = ("the substituted party did not move from its own square, "
                    "which may face a wall")
        result["read"]["verdicts"].append(f"slot {title.after_letter}: {what}{clause}")


def _display_verdicts(displays: list[dict[str, Any]]) -> list[str]:
    """One line per effects list the run reached: whether its identity rule was checked.

    A list whose bar offered a further page gets a second line: only its first page was read.
    """
    lines = []
    for entry in displays:
        lines.append(f"{entry['shot']}: the effects list " + (
            "matches the identity rule cut for this party" if entry["identity_checked"]
            else "has no identity rule, so nothing checked what it lists"))
        if entry.get("more_pages"):
            lines.append(f"{entry['shot']}: the bar reads NEXT EXIT, so the list has a further "
                         "page; the display check covered page 1 only")
    return lines


def _join_verdicts(joins: list[dict[str, Any]]) -> list[str]:
    """One line per JOIN the run pressed: the message a rule matched, and whose rows followed."""
    lines = []
    for entry in joins:
        if entry.get("message"):
            said = f"JOIN answered {route_camp.JOIN_MESSAGES[entry['message']]!r}"
        elif entry.get("messages_ruled"):
            said = "no JOIN message rule matched"
        else:
            said = "the guard map holds no JOIN message rule, so the message line was not read"
        joined = entry.get("joined")
        rows = "" if joined is None else "; the redrawn list " + (
            "matches the identity rule cut for this party" if joined["identity_checked"]
            else "has no identity rule, so nothing checked its rows")
        lines.append(f"{entry.get('shot', 'a join')}: {said}{rows}")
    return lines


def _load_message_verdict(entry: dict[str, Any]) -> str:
    """Whether SCROLLS DROPPED! was drawn after the load, or why it was not read."""
    if not entry["guarded"]:
        return "the guard map holds no SCROLLS DROPPED! rule, so the load message was not read"
    if entry["shown"]:
        return f"SCROLLS DROPPED! was drawn after the load ({entry['shot']})"
    return f"SCROLLS DROPPED! was not drawn on any of {entry['grabs']} grabs after the load"


def _camp_verdicts(sheets: list[dict[str, Any]]) -> list[str]:
    """One line per camp sheet the run reached: whether its bar offered HEAL."""
    lines = []
    for entry in sheets:
        offered = {True: "offers HEAL", False: "does not offer HEAL",
                   None: "shows neither the HEAL bar nor the spent bar the guard map holds"
                   }[entry["heal_offered"]]
        checked = "" if entry["identity_checked"] else "; no identity rule checked whose sheet it is"
        lines.append(f"{entry['shot']}: the sheet {offered}{checked}")
    return lines


def _place_text(place: dict[str, Any]) -> str:
    return f"area {place['area']} {place['x']},{place['y']} facing {place['facing']}"


def _read_reload(title: AmigaTitle, manifest: dict, result: dict[str, Any],
                 out: pathlib.Path, kept_before: dict[str, dict], loaded: str) -> None:
    """Judge a run that only loads: no slot changed, and the screen shows the loaded slot's place and not the other's."""
    place, other = manifest["state_a"], manifest["other_place"]
    seen = result.get("reload", {})
    if title.save_disk in result["fetched"]:
        try:
            fetched = _verified_disk(out / f"fetched-{title.save_disk}.adf")
            result["kept_unchanged"] = {
                c: title.slot_files(fetched, c) == before for c, before in kept_before.items()}
            result["extra_saves"] = sorted(set(title.slot_letters(fetched)) - set(kept_before))
        except BaseException as exc:
            result["fetched_save_error"] = f"{type(exc).__name__}: {exc}"
    verdicts = [
        f"slot {loaded}: reloaded at {_place_text(place)}" if seen.get("shown") is True
        else f"slot {loaded}: {_place_text(place)} is not on the screen"]
    other_letter = manifest["other_letter"]
    if seen.get("other_shown") is None:
        verdicts.append(f"slot {other_letter}: {_place_text(other)} was not compared with the screen")
    elif seen["other_shown"]:
        verdicts.append(f"slot {other_letter}: {_place_text(other)} is also on the screen")
    else:
        verdicts.append(f"slot {other_letter}: {_place_text(other)} is not on the screen")
    result["read"] = {"loaded_letter": loaded, "place_loaded": place, "other_place": other,
                      "verdicts": verdicts}
    result["success"] = bool(
        not result["error"] and result["completed"] and not result["unguarded"]
        and set(result["fetched"]) == set(title.disk_keys)
        and all(result["registered_unchanged"].values())
        and all(result["working_unchanged"].values())
        # The reload writes nothing, so every disk, the save disk included, comes back as it went in.
        and all(result["disks_unchanged"].get(k) for k in title.disk_keys)
        and bool(result.get("kept_unchanged")) and all(result["kept_unchanged"].values())
        and result.get("extra_saves") == []
        and seen.get("shown") is True and seen.get("other_shown") is False)


_FULL_TITLES = {"pool": "Pool of Radiance", "curse": "Curse of the Azure Bonds",
                "ssb": "Secret of the Silver Blades"}
#: A cited issue: a GitHub `#N (title)`, a Plane `WISH-N (title)`, or the Markdown link
#: `[WISH-N (title)](url)` that `planeread.py --cite` prints.
SPECIMEN_ISSUE = re.compile(
    r"(?:#(\d+)|WISH-(\d+)) \(.+\)|\[WISH-(\d+) \(.+\)\]\(\S+\)")
#: How `--specimen-issue` must be written, for the errors that block it.
SPECIMEN_ISSUE_FORMS = '"#N (title)" or "WISH-N (title)", or planeread.py --cite\'s link'


def _issue_token(issue: str) -> str:
    """The specimen-name token of a cited issue: `631` for `#631 (...)`, `plane-7` for `WISH-7 (...)` or its link.

    The two trackers number apart, so a Plane ticket's token carries its tracker.
    """
    found = SPECIMEN_ISSUE.fullmatch(issue)
    if found is None:
        raise RouteError(f"{issue!r} is not {SPECIMEN_ISSUE_FORMS}")
    # One ticket, one token: `WISH-007` and `WISH-7` are the same ticket.
    if found.group(1):
        return str(int(found.group(1)))
    return f"plane-{int(found.group(2) or found.group(3))}"


def _slug(value: str) -> str:
    # Base32 is reversible and uses only the specimen registry's lowercase slug alphabet.
    return base64.b32encode(value.encode()).decode().rstrip("=").lower()


def _register_fetched(specimen_name: str, full_title: str, issue: str, what: str,
                      fetched: pathlib.Path) -> dict[str, str]:
    """Add a fetched save disk to the specimen tree, or find the identical one already there."""
    root = specimens.tree_root()
    source_hash = sha256(fetched)
    source = str(fetched.resolve())
    existing = next((entry for entry in specimens.list_specimens(root)
                     if entry.get("name") == specimen_name and entry.get("platform") == "amiga"
                     and entry.get("title") == full_title), None)
    if existing is None:
        directory = specimens.add(
            "amiga", specimen_name, [fetched], title=full_title, issue=issue,
            made_by="WinUAE, driven by tools/amiga/acceptance.py", what=what,
            command=" ".join(sys.argv), root=root)
    else:
        if (existing.get("source") != source or
                existing.get("sha256", {}).get(fetched.name) != source_hash):
            raise RouteError(f"specimen name collision: {specimen_name}")
        directory = existing["_provenance"].parent
    saved = directory / fetched.name
    if sha256(saved) != source_hash:
        raise RouteError("preserved specimen differs from fetched DF0")
    return {"path": str(saved), "sha256": source_hash,
            "provenance": str(directory / specimens.PROVENANCE_NAME)}


def _preserve_published(manifest_path: pathlib.Path, attempt: str, name: str,
                        fetched: pathlib.Path, issue: str = PUBLISHED_ISSUE,
                        staged: dict[str, Any] | None = None,
                        source_sha256: str | None = None) -> dict[str, str]:
    """Register a successful game's fetched DF0 before its lane is released.

    `staged` is the manifest's `staged_place`; the provenance then says Wish changed the
    loaded slot's square before the game loaded it. A `source_sha256` in
    `WISH_STAGED_SOURCES` makes it say the source was edited by Wish, not game-written.
    """
    run_id = manifest_path.parent.name
    if source_sha256 in WISH_STAGED_SOURCES:
        what = (f"Run {run_id!r}, attempt {attempt!r}: loaded the party of the Wish-staged "
                f"C64 source (SHA-256 {source_sha256}), an edited copy of a published save "
                "that the game did not write, and the game walked and saved slots C and F")
    else:
        what = (f"Run {run_id!r}, attempt {attempt!r}: loaded the published disk-one "
                "party, walked and saved slots C and F in game")
    if staged is not None:
        what += (f". Before the run Wish staged the loaded slot {staged['slot']} with "
                 f"`prepare --stage-place`: the party's x,y,facing went from "
                 f"{staged['before']} to {staged['after']} and nothing else in the image "
                 "changed")
    return _register_fetched(
        f"wish-{issue}-{name}-{_slug(run_id)}-{_slug(attempt)}", _FULL_TITLES[name],
        PUBLISHED_ISSUE_TEXT[issue], what, fetched)


def _preserve_substituted(manifest_path: pathlib.Path, manifest: dict, attempt: str,
                          title: AmigaTitle, issue: str, fetched: pathlib.Path) -> dict[str, str]:
    """Register the save disk of a successful substituted run.

    The game wrote the control and after slots; Wish wrote the loaded slot by importing
    the substitute's, so the provenance says so. Only claims the run's success test checks:
    the kept slots and the loaded slot are unchanged and no other save letter appeared.
    """
    run_id = manifest_path.parent.name
    number = _issue_token(issue)
    sub, pinned = manifest["substitute"], manifest["registered"]["specimen"]
    kept = ", ".join(title.kept_letters)
    what = (
        f"Run {run_id!r}, attempt {attempt!r}: the save disk fetched after the game loaded "
        f"slot {manifest['loaded_letter']}, saved slot {title.control_letter}, walked and "
        f"saved slot {title.after_letter}. The game wrote slots {title.control_letter} and "
        f"{title.after_letter}. Slot {manifest['loaded_letter']} was written by Wish: it is "
        f"slot {sub['letter']} of {sub['path']} (SHA-256 {sub['sha256']} as recorded when "
        f"`prepare --substitute` imported it; the run did not hash it again), imported into a copy of the pinned specimen {pinned['path']} "
        f"(SHA-256 {pinned['sha256']}). Slots {kept} are that specimen's own; the run found "
        f"them and slot {manifest['loaded_letter']} unchanged and no other save letter. "
        "Files outside the slots were not checked.")
    return _register_fetched(
        f"wish-{number}-{manifest['title']}-{_slug(run_id)}-{_slug(attempt)}",
        _FULL_TITLES[manifest["title"]], issue, what, fetched)


def _preserve_published_disk_three(
        manifest_path: pathlib.Path, manifest: dict, attempt: str, title: AmigaTitle, issue: str,
        fetched: pathlib.Path) -> dict[str, str]:
    """Register the disk 3 of a successful published disk 3 accept run.

    The game wrote the control and after slots; Wish wrote the loaded slot's two files, so the
    provenance says so, and only claims what the run's success test checks.
    """
    run_id = manifest_path.parent.name
    letter = manifest["loaded_letter"]
    what = (
        f"Run {run_id!r}, attempt {attempt!r}: the disk 3 fetched after the game loaded slot "
        f"{letter}, saved slot {title.control_letter}, walked and saved slot {title.after_letter}. "
        f"The game wrote slots {title.control_letter} and {title.after_letter}. Wish wrote "
        f"SavGam{letter}.pty and Vault{letter}.DAT by converting the DOS save "
        f"{manifest['registered']['source']['path']} (SHA-256 {manifest['source_sha256']}) onto a "
        f"copy of the registered disk 3, and every other file is that disk's own.")
    return _register_fetched(
        f"wish-{_issue_token(issue)}-darkness-{_slug(run_id)}-{_slug(attempt)}",
        "Pools of Darkness", issue, what, fetched)


def _preserve_staged(manifest_path: pathlib.Path, manifest: dict, attempt: str,
                     issue: str, fetched: pathlib.Path) -> dict[str, str]:
    """Register the boot disk of a successful Silver Blades accept staged with `--staged-from`.

    Wish built the input and staged its slot; the game wrote slots B and D. Only claims the
    run's success test checks: the staged slot is unchanged and no other save letter appeared.
    """
    run_id = manifest_path.parent.name
    number = _issue_token(issue)
    source, joined = manifest["source"], manifest["staged_from"]
    what = (
        f"Run {run_id!r}, attempt {attempt!r}: the boot disk fetched after the game loaded "
        f"slot {manifest['slot_letter']}, saved slot {MENU_SAVE_LETTER}, walked and saved "
        f"slot {CAMP_SAVE_LETTER}. The game wrote slots {MENU_SAVE_LETTER} and "
        f"{CAMP_SAVE_LETTER}. Slot {manifest['slot_letter']} was written by Wish from the "
        f"Wish-staged C64 source {source['path']} (SHA-256 {source['sha256']}), an "
        f"effect-array derivative of the JOIN disk {joined['path']} (SHA-256 "
        f"{joined['sha256']} as recorded when `prepare --staged-from` read it; the run did not "
        f"hash it again) with active rows {manifest['active_rows']}, converted by Save As "
        f"and staged into DF0 as {json.dumps(manifest['stage'], sort_keys=True)} "
        f"(slot SHA-256 {manifest['slot_sha256']}"
        + (f", save count {manifest['save_count']}" if "save_count" in manifest else "")
        + f"). The run found slot {manifest['slot_letter']} unchanged and no other save "
        "letter. Files outside the slots were not checked.")
    return _register_fetched(
        f"wish-{number}-ssb-{_slug(run_id)}-{_slug(attempt)}", _FULL_TITLES["ssb"], issue,
        what, fetched)


class _LaneWatch:
    """Wraps the lane so that an error can be tied to the call `route_limit` cut short."""

    SLACK = 1.0

    def __init__(self, guest: Any) -> None:
        self._guest = guest
        self.shortened: float | None = None
        self._failed: tuple[BaseException, float, float] | None = None

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._guest, name)
        if not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            limit, self.shortened, self._failed = self.shortened, None, None
            began = time.monotonic()
            try:
                return attr(*args, **kwargs)
            except BaseException as exc:
                if limit is not None and kwargs.get("timeout") == limit:
                    self._failed = (exc, limit, time.monotonic() - began)
                raise
        return call

    def timed_out(self, exc: BaseException) -> bool:
        """True when `exc` came from the shortened call and it used the time it was given."""
        if self._failed is None or self._failed[0] is not exc:
            return False
        _, limit, used = self._failed
        return used >= limit - min(self.SLACK, limit / 2)


def run_recon(manifest_path: pathlib.Path, *, guest: Any, guard: Any = None,
              holder: str, audio_proof: pathlib.Path | None, attempt: str = "recon1",
              deadline_seconds: float = 1800,
              route: tuple[tuple[str, str], ...] = ROUTE,
              write_keys: tuple[str, ...] = ("B",),
              min_waits: dict[str, float] | None = None,
              measure: bool = False, accept: bool = False,
              identity: Any = None, journal_python: str | None = None,
              answer: Any = None, preflight: Any = None,
              title: AmigaTitle | None = None, reload: bool = False,
              published_disk_one: bool = False, published_name: str | None = None,
              preserve_specimen: bool = False, specimen_issue: str | None = None,
              diagnose: bool = False, boot_limit: float = 300, wait_lane: float = 0.0,
              rulebook_draws: int | None = None, target: Any = None,
              lane_check: Callable[[], Any] | None = None,
              rulebook_records: list[int] | None = None,
              marks: Mapping[int, tuple[tuple[str, str], ...]] | None = None,
              walk_retry: int = 0) -> dict[str, Any]:
    """Walk the route, stopping at the first unrecognised state, and fetch both disks.

    A guarded state is found by polling single grabs until its static box
    matches, so an animated screen needs no settling. Guarded mode needs a
    guard for `title` and every route state, and presses the first write key
    after the route. Measure mode takes any subset of guards, settles the
    screens it has none for, presses no write key and nothing after the route,
    and stops at the first unrecognised guarded state or at the first key that
    leaves the screen unchanged.

    `accept` walks `ACCEPT_ROUTE` after the same guarded route: a menu save to
    slot B, BEGIN, the journal answer, two squares, a camp save to slot D. A
    state the guard map lacks is settled, marked unguarded and makes the run a
    measuring one; the route states never fall back. It reads slots B and D
    back, and `answer(journal_python, holder, adf, timeout)` stands in for the
    answerer's subprocess.

    `rulebook_draws` (Silver Blades accept only) makes that many camp saves in one boot: the
    route's own, then each further one after the private helper's `stage_live` has run on
    `target` (an `AmigaTarget`), once `lane_check` has confirmed the lane claim. A draw that
    reaches EXIT GAME with no question fails the run; `result["rulebook"]` lists each. The
    run is blocked before the claim when the deadline cannot cover the draws.
    `rulebook_records` gives one record number per further draw: the private `drawseed` helper
    stages each before its camp save, and after the answer its `drawn` is logged beside the
    reader's kept-capture index; a draw that is not the staged record, no single kept capture,
    or a reader index other than the helper's `reader_index` for `drawn`, fails the run.

    `marks` maps a route index to the machine steps that fire before that step: `("snapshot",
    NAME)` saves the whole machine through the WinUAE pipe and `("restore", NAME)` puts it back,
    so a bad encounter costs one leg and not the run. An index equal to the route's length fires
    after the last step. A restore with no snapshot before it, or with a game save between the
    two, is blocked before the claim, since the save stays on the disk image while memory goes
    back. A restore puts the run's own record of camp sheets, effects lists and JOIN results back
    as the snapshot found it, and waits for the screen the snapshot was taken on before the next
    key goes out; a snapshot is therefore blocked at index 0, where no screen has been reached.
    Names match without regard to case, as the guest's files do. A `--camp` list's `snapshot
    NAME` and `restore NAME` steps become marks.

    `walk_retry` (accept only) takes a snapshot named `walk-leg` before the route's first `turn`
    or `move` step, requires each step of that leg to match its guard, and on a miss, such as an
    encounter screen, restores the snapshot and walks the leg again, at most `walk_retry` times;
    a further miss stops the run. Each retry is listed in `result["walk_retries"]`. No game save
    falls inside a leg, so a restore never strands one on the disk image.

    `preserve_specimen` registers the fetched save disk of a run that succeeded by its own
    verdict, before `--expect` is judged, so a run that later fails `--expect` still leaves its
    specimen behind.

    `reload` runs a title with no save letters: it loads the manifest's `loaded_letter`, walks
    the route, then waits for the screen to show that slot's place (`place_state` of `state_a`)
    and not the other slot's (`other_place`), and writes nothing.

    With a `title`, the route, the disks, the interstitials and the readings come
    from its description, and the run is exactly one of `accept`, `measure` and `reload`;
    without one every line is Silver Blades'. The manifest of a title is
    `{"disks": {key: {path, sha256}}, "registered": {key: {path, sha256}},
    "loaded_letter", "state_a", "names_a"}` and optionally `"expected_after"`.
    """
    if guard is None and not measure:
        raise RouteError("a screen guard is required unless measuring")
    preserve_message = "specimen preservation requires a published disk-one or substituted accept"
    staged_message = preserve_message + " or a Silver Blades accept staged with --staged-from"
    if preserve_specimen and not accept:
        raise RouteError(preserve_message)
    if specimen_issue is not None and (not preserve_specimen or published_disk_one):
        raise RouteError("--specimen-issue goes with a substituted or staged --preserve-specimen only")
    if title is not None:
        if not isinstance(title, AmigaTitle):
            raise RouteError("title must be an AmigaTitle")
        if reload and (accept or measure):
            raise RouteError("reload is a mode of its own, apart from accept and measure")
        if not reload and not diagnose and accept == measure:
            raise RouteError("a title run is either accept or measure")
        if not diagnose and reload != (title.control_letter is None):
            raise RouteError("only a title with no save letters is reloaded, and it runs only "
                             "as a reload")
        if route != ROUTE or write_keys != ("B",):
            raise RouteError("a title brings its own route and write keys")
    if reload and title is None:
        raise RouteError("reload needs a title")
    counter = None
    if rulebook_draws is not None:
        if not accept or title is not None:
            raise RouteError("rulebook draws are for the Silver Blades accept route")
        if not 1 <= rulebook_draws <= RULEBOOK_DRAWS_MAX:
            raise RouteError(f"rulebook draws are 1 to {RULEBOOK_DRAWS_MAX}")
        if rulebook_draws > 1:
            if target is None or lane_check is None:
                raise RouteError("rulebook draws need a memory target and a lane check")
            savecount = route_silver_blades._load_savecount()
            if not (hasattr(savecount, "stage_live") and hasattr(savecount, "SaveCountError")):
                raise RouteError("the private savecount module lacks stage_live or SaveCountError")
            drawseed = None
            if rulebook_records is not None:
                if len(rulebook_records) != rulebook_draws - 1:
                    raise RouteError("rulebook records need one number per further draw")
                if not os.environ.get(route_silver_blades.KEEP_ENV):
                    raise RouteError(f"rulebook records need ${route_silver_blades.KEEP_ENV} "
                                     "set, so the reader's record can be compared")
                drawseed = _load_drawseed()
                if not all(hasattr(drawseed, n) for n in ("stage_draw", "drawn", "reader_index", "DrawSeedError")):
                    raise RouteError("the private drawseed module lacks stage_draw, drawn, "
                                     "reader_index or DrawSeedError")
            counter = DrawCounter(target, savecount, lane_check, drawseed)
        elif rulebook_records is not None:
            raise RouteError("rulebook records need more than one draw")
    elif rulebook_records is not None:
        raise RouteError("rulebook records need rulebook draws")
    if accept or reload:
        if measure:
            raise RouteError("accept and measure are separate modes")
        if title is None:
            if route != ROUTE:
                raise RouteError("accept walks its own route")
            for letter in (MENU_SAVE_LETTER, CAMP_SAVE_LETTER):
                if letter in (SLOT_LETTER, "A"):
                    raise RouteError(f"save letter {letter} would overwrite the prepared slot")
        identity_states = (IDENTITY_MESSAGES if title is None else
                           [s for s in IDENTITY_MESSAGES
                            if s in {state for _, state, _ in title.route}])
        if identity_states and (
                identity is None or not all(_has_rule(identity, s) for s in identity_states)):
            raise RouteError(f"identity map lacks {sorted(identity_states)}")
        if accept and title is None and not journal_python and answer is None:
            raise RouteError("accept needs a journal interpreter")
    if diagnose:
        if (accept or measure or reload or not published_disk_one or published_name != "ssb"
                or title is None or boot_limit <= 0 or boot_limit > 300
                or deadline_seconds > 600 or deadline_seconds <= boot_limit):
            raise RouteError("diagnose needs the published Silver Blades title and bounded limits")
        if not _guards(guard, "title"):
            raise RouteError("diagnose needs a title screen guard")
    if not measure and not diagnose:
        needed = (("title", *(s for _, s in route)) if title is None
                  else ("title", *sorted(title.strict)))
        missing = [s for s in dict.fromkeys(needed) if not _guards(guard, s)]
        if missing:
            raise RouteError(f"screen guard map lacks {missing}")
    if title is not None and measure:
        # Measure mode settles a state with no guard rule and goes on, so a DF0 insert would
        # swap the disk on an unrecognised screen.
        steps = title.measure_route
        for (key, _, kind), (_, before, _) in zip(steps[1:], steps):
            if kind == "insert" and key[0] == 0 and not _guards(guard, before):
                raise RouteError(f"screen guard map lacks {before!r}: a DF0 insert needs a "
                                 f"guard on the prompt before it")
        for screen, action, _, _ in title.interstitials:
            if action[0] == "insert" and action[1] == 0 and not _guards(guard, screen):
                raise RouteError(f"screen guard map lacks {screen!r}: a DF0 insert needs a "
                                 f"guard on the prompt")
    if accept and journal_python is not None and (
            title is None or published_disk_one or _substitute_mode(manifest_path)):
        (preflight or journal_preflight)(journal_python)
    min_waits = {**(title.min_waits if title else {}), **(min_waits or {})}
    if counter is not None:
        _check_draws_fit(rulebook_draws, ACCEPT_ROUTE, min_waits, deadline_seconds)
    write_keys = tuple(k.upper() for k in write_keys)
    if not all(write_keys):
        raise RouteError("write keys must not contain an empty entry")
    if measure and title is None:
        if not route:
            raise RouteError("measure mode needs at least one route step")
        # Measuring never writes, whatever the caller listed as write keys.
        write_keys = tuple(dict.fromkeys(write_keys + ("B",)))
    if not HOLDER.fullmatch(holder) or not HOLDER.fullmatch(attempt):
        raise RouteError("holder and attempt must use simple lane-safe names")
    if deadline_seconds <= 0:
        raise RouteError("reconnaissance deadline must be positive")
    if audio_proof is not None:
        audio_proof = pathlib.Path(audio_proof)
    if not guest.silence(audio_proof):
        raise RouteError("the Windows VM audio mute has not been verified")
    manifest_path = pathlib.Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if published_disk_one:
        if published_name is None:
            raise RouteError("published disk-one mode needs its CLI title")
        manifest, expected_title = _published_manifest(manifest_path, published_name)
        if (title is None or title.issue != expected_title.issue or
                title.route != expected_title.route or
                title.mounted != expected_title.mounted or
                title.save_disk != expected_title.save_disk):
            raise RouteError("the selected title route differs from the published manifest")
    elif manifest.get("mode") == "published_disk_one":
        raise RouteError("a published disk-one manifest needs --published-disk-one")
    elif manifest.get("mode") in (PUBLISHED_DISK_THREE_MODE, PUBLISHED_DISK_THREE_RELOAD_MODE):
        expected_title = published_darkness_title(manifest_path, manifest.get("title"))
        if title != expected_title:
            raise RouteError("the selected title route differs from the published disk 3 manifest")
        if "camp" in manifest:
            if not accept:
                raise RouteError("camp steps are driven on an accept run only")
            title = accept_title(title, manifest)
    elif manifest.get("mode") == SUBSTITUTE_TITLE_MODE:
        expected_title = route_silver_blades.title_for_substitute(manifest)
        if (title is None or title.issue != expected_title.issue or
                title.route != expected_title.route or
                title.mounted != expected_title.mounted or
                title.save_disk != expected_title.save_disk):
            raise RouteError("a substitute prepared as a title run needs its own title's route")
        if "camp" in manifest:
            if not accept:
                raise RouteError("camp steps are driven on an accept run only")
            title = accept_title(title, manifest)
    elif "camp" in manifest:
        if title is None or not accept or manifest.get("title") not in CAMP_TITLES:
            raise RouteError("camp steps are driven on a published accept, or a Pools of "
                             "Darkness or Pool of Radiance accept, only")
        title = accept_title(title, manifest)
    if preserve_specimen and "substitute" in manifest and manifest.get("title") == "darkness":
        raise RouteError("a Pools of Darkness substitute has no registered specimen to preserve")
    if preserve_specimen and manifest.get("mode") == PUBLISHED_DISK_THREE_MODE:
        if specimen_issue is None or not SPECIMEN_ISSUE.fullmatch(specimen_issue):
            raise RouteError("a published disk 3 --preserve-specimen needs --specimen-issue "
                             f"{SPECIMEN_ISSUE_FORMS} naming its issue")
    elif preserve_specimen and title is None and not published_disk_one:
        if "staged_from" not in manifest:
            raise RouteError(staged_message)
        if specimen_issue is None or not SPECIMEN_ISSUE.fullmatch(specimen_issue):
            raise RouteError(staged_message + ", and a staged one needs --specimen-issue "
                             f"{SPECIMEN_ISSUE_FORMS} naming its issue")
    elif preserve_specimen and not published_disk_one:
        if ("substitute" not in manifest or manifest.get("title") not in _FULL_TITLES
                or "specimen" not in manifest.get("registered", {})
                or specimen_issue is None or not SPECIMEN_ISSUE.fullmatch(specimen_issue)):
            raise RouteError(preserve_message + ", and a substituted one needs --specimen-issue "
                             f"{SPECIMEN_ISSUE_FORMS} naming its issue")
    if title is POOL:
        title = pool_title_for(manifest)
    if title is not None:
        disks, registered, letter = _title_inputs(manifest, title)
        originals: dict[str, pathlib.Path] = {}
        save_before = _verified_disk(disks[title.save_disk])
        present = title.slot_letters(save_before)
        if letter not in present:
            raise RouteError(f"the save disk holds no slot {letter} to load")
        for taken in (title.control_letter, title.after_letter):
            if taken is not None and taken in present:
                raise RouteError(f"slot {taken} already exists on the save disk")
        if reload:
            try:
                wanted = [place_state(manifest["state_a"]), place_state(manifest["other_place"])]
                other = manifest["other_letter"]
            except KeyError as exc:
                raise RouteError(f"the manifest lacks {exc.args[0]!r}") from exc
            except TypeError as exc:
                raise RouteError("the manifest's reload place is not a mapping") from exc
            if other not in present:
                raise RouteError(f"the save disk holds no slot {other} to compare")
            missing = [k for k in wanted if not _guards(guard, k)]
            if missing:
                raise RouteError(f"screen guard map lacks {missing}")
        kept_before = {c: title.slot_files(save_before, c)
                       for c in (*title.kept_letters, letter)}
        if published_disk_one:
            # A staged place changes working DF0, and `_published_manifest` has checked how.
            df0_expected = (manifest["disks"]["df0"]["sha256"] if "staged_place" in manifest
                            else manifest["registered"]["published"]["sha256"])
            if sha256(disks["df0"]) != df0_expected:
                raise RouteError("working DF0 differs from the exact published image")
            if sha256(disks["df1"]) != manifest["registered"]["disk_two"]["sha256"]:
                raise RouteError("working DF1 differs from registered disk 2")
        if diagnose:
            return _run_diagnose(manifest_path, manifest, title, disks, guest, guard,
                                 holder, audio_proof, attempt, deadline_seconds, boot_limit,
                                 wait_lane)
    else:
        originals = {name: _input(manifest, name)
                     for name in ("source", "substitute", "boot_source", "disk_b_source")
                     if name in manifest}
        if accept and "boot_source" not in originals:
            raise RouteError("the manifest names no boot_source for the journal answerer")
        df0 = _input(manifest, "df0")
        published = _input(manifest, "published_df1")
        df1 = _input(manifest, "df1")
        if len({df0.resolve(), published.resolve(), df1.resolve()}) != 3:
            raise RouteError("DF0, published DF1 and working DF1 must be separate files")
        letter = manifest["slot_letter"]
        # A substitute's slot may sit under another letter on the disk it came from.
        slot = _verified_disk(published).read_file(
            f"/SAVE/savgam{manifest.get('published_letter', 'A')}.sav")
        # A save count edits only the staged slot, so the published one has its own digest.
        published_sha = manifest.get("published_slot_sha256", manifest["slot_sha256"])
        if hashlib.sha256(slot).hexdigest() != published_sha:
            raise RouteError("the published slot differs from the manifest")
        df0_disk = _verified_disk(df0)
        staged = df0_disk.read_file(f"/SAVE/savgam{letter}.sav")
        if hashlib.sha256(staged).hexdigest() != manifest["slot_sha256"]:
            raise RouteError(f"DF0 /SAVE/savgam{letter}.sav is not Wish's published slot")
        df1_disk = _verified_disk(df1)
        if df1_disk.volume_name != "Secret 2":
            raise RouteError("working DF1 is not disk B, volume 'Secret 2'")
        if sha256(df1) != manifest["disk_b_source"]["sha256"]:
            raise RouteError("working DF1 differs from the registered disk B")
    out = manifest_path.parent / attempt
    out.mkdir(parents=False, exist_ok=False)
    shots = scratch.ensure(out / "shots")
    runlog = (out / "run.jsonl").open("a", encoding="utf-8")
    if title is None:
        remotes = {key: guest.remote_path("672", holder, key) for key in ("df0", "df1")}
        local_disks = {"df0": df0, "df1": df1}
    else:
        remotes = {key: guest.remote_path(title.issue, holder, key) for key in title.disk_keys}
        local_disks = disks
    result: dict[str, Any] = {
        **evidence.git_state(REPO), "argv": sys.argv[1:],
        "success": False, "holder": holder, "input": str(manifest_path),
        "events": [], "error": "", "fetched": {},
        "deadline_seconds": deadline_seconds, "measure": measure,
        "accept": accept, "completed": False, "lost": None, "unguarded": [],
    }
    if title is not None:
        result["remotes"] = remotes
        result["interstitials_without_guard"] = sorted(
            {screen for screen, *_ in title.interstitials if not _has_rule(guard, screen)})
        steps = title.route
        strict_states = {"title", *title.strict}
        table = title.interstitials
    else:
        result["remote_df0"], result["remote_df1"] = remotes["df0"], remotes["df1"]
        steps = ACCEPT_ROUTE if accept else (
            *((k, s, "key") for k, s in route), (write_keys[0], "loaded_menu", "write"))
        strict_states = {"title", *(s for _, s in ROUTE)}
        table = SILVER_BLADES_INTERSTITIALS
    if walk_retry < 0:
        raise RouteError("walk retries cannot be negative")
    if walk_retry and not accept:
        raise RouteError("walk retries belong to an accept run")
    if walk_retry:
        result["walk_retries"] = []
    marks = {**(marks or {})}
    if title is not None and "camp" in manifest and accept:
        for index, pairs in route_camp.camp_marks(
                title, tuple(manifest["camp"]), len(manifest["names_a"]),
                name=manifest["title"]).items():
            marks[index] = (*pairs, *marks.get(index, ()))
    if any(name.lower() == WALK_LEG for pairs in marks.values() for _, name in pairs):
        raise RouteError(f"the snapshot name {WALK_LEG} is the walk retry's own")
    if marks:
        if measure or reload:
            raise RouteError("snapshot and restore steps belong to an accept run")
        check_marks(marks, steps)
    if (marks or walk_retry) and not getattr(guest, "can_snapshot", True):
        raise RouteError("this run needs a machine snapshot, which this emulator lane cannot take yet")
    previous_state = previous_world = ""
    #: What the run had seen when each snapshot was taken, put back by its restore: the machine
    #: goes back, the run's own record of it must too.
    seen: dict[str, dict[str, Any]] = {}
    memory = ("camp_sheets", "camp_displays", "camp_joins", "sheets_before_last_rest")

    def machine_step(verb: str, name: str, n: int) -> None:
        """Save the machine under `name`, or put it back as that left it and on its screen."""
        nonlocal previous_state, previous_world
        receipt = getattr(guest, verb)(name, holder)
        key = name.lower()
        if verb == "snapshot":
            seen[key] = {"state": previous_state, "world": previous_world,
                         "result": {k: copy.deepcopy(result[k]) for k in memory if k in result}}
        else:
            was = seen[key]
            previous_state, previous_world = was["state"], was["world"]
            for field in memory:
                result.pop(field, None)
            result.update(copy.deepcopy(was["result"]))
        result["events"].append({verb: name, "step": n})
        fields = {"name": name, "step": n, "receipt": str(receipt)}
        if verb == "restore":
            fields["disk_image"] = ("a game save made in between would stay on the disk image "
                                    "while memory went back; none was made")
        log(verb, **fields)
        if verb == "restore" and previous_state:
            # The next key goes out on the screen the snapshot was taken on, not on a guess.
            # Strict wherever the state has a guard: a restore that landed on another screen
            # must stop the run, not be settled and typed into.
            try:
                reach(previous_state, f"{n:02d}-{previous_state}-after-restore", 0, strict=True)
            except RouteError as exc:
                raise RouteError(f"after restoring {name}: {exc}") from exc

    title_limit = title.title_limit if title else TITLE_LIMIT
    boot_span = title.boot_span if title else MEASURE_TITLE_SPAN
    if counter is not None:
        result["rulebook"] = []
    landed: dict[str, Any] = {"state": None}
    # Silver Blades' loader may print SCROLLS DROPPED! as it loads, so its load is watched.
    silver_blades = (title is None or published_name == "ssb"
                     or manifest.get("mode") == SUBSTITUTE_TITLE_MODE)
    if accept and answer is None and journal_python is not None:
        answer = functools.partial(run_journal_answer, journal_python)
    claimed = start_attempted = copied = stopped = False
    begun = time.monotonic()
    cleanup_window = min(300.0, deadline_seconds / 2)
    route_end = begun + deadline_seconds - cleanup_window
    total_end = begun + deadline_seconds
    cleanup_scale = cleanup_window / 300.0
    route_note = (f"route time of {deadline_seconds - cleanup_window:.0f}s: the "
                  f"{deadline_seconds:.0f}s deadline less a {cleanup_window:.0f}s cleanup reserve")
    watch = _LaneWatch(guest)
    guest = watch

    def log(event: str, **fields: Any) -> None:
        runlog.write(json.dumps({"event": event, "t": time.time(), **fields},
                                sort_keys=True) + "\n")
        runlog.flush()

    if title is not None:
        log("interstitials_without_guard", screens=result["interstitials_without_guard"])

    def route_limit(cap: float) -> float:
        left = route_end - time.monotonic()
        if left <= 0:
            raise RouteError(f"the {route_note} ran out before the next route action")
        watch.shortened = min(cap, left) if left < cap else None
        return min(cap, left)

    def cleanup_limit(cap: float) -> float:
        left = total_end - time.monotonic()
        if left <= 0:
            raise RouteError("reconnaissance deadline reached during cleanup")
        return min(cap * cleanup_scale, left)

    def capture(state: str, *, check: bool = True,
                cleanup: bool = False, settle: bool = True) -> str:
        """Capture `state` and return its crop's hash; "" when a grab found no window."""
        raw, cropped = shots / f"{state}.raw.png", shots / f"{state}.png"
        if settle:
            limit = cleanup_limit(90) if cleanup else route_limit(120)
            guest.capture(state, raw, cropped, timeout=limit)
        else:
            cropped.unlink(missing_ok=True)
            if not guest.grab(state, raw, cropped, timeout=route_limit(SHOT_SECONDS)):
                result["events"].append({"state": state, "raw": str(raw),
                                         "sha256": sha256(raw), "crop": None, **_shot_source(guest)})
                log("grab", state=state, raw=str(raw), crop=None, **_shot_source(guest))
                return ""
        digest = sha256(cropped)
        result["events"].append({"state": state, "raw": str(raw),
                                 "crop": str(cropped), "sha256": sha256(raw),
                                 "crop_sha256": digest, **_shot_source(guest)})
        log("settled" if settle else "grab", state=state, raw=str(raw),
            crop=str(cropped), crop_sha256=digest, **_shot_source(guest))
        if check and not guard(state, cropped):
            raise RouteError(f"{state} screen was not recognized; kept {raw}")
        return digest

    def wait(seconds: float) -> None:
        if seconds > 0:
            if route_end - time.monotonic() < seconds:
                raise RouteError(f"the {route_note} cannot cover a {seconds:g}s minimum wait")
            time.sleep(seconds)

    def check_identity(state: str, crop: pathlib.Path) -> None:
        if identity is not None and _has_rule(identity, state) and not identity(state, crop):
            raise RouteError(IDENTITY_MESSAGES.get(
                state, f"{state} shows a party other than the prepared party"))

    #: The message rules tested on every grab while one state is reached, and the first that
    #: matched, kept under its own name because the next grab overwrites the crop.
    messages: dict[str, Any] = {"watch": (), "seen": None, "shot": None, "grabs": 0}

    def watch_messages(states: tuple[str, ...]) -> None:
        messages.update(watch=states, seen=None, shot=None, grabs=0)

    def look_for_messages(crop: pathlib.Path, name: str) -> None:
        if not messages["watch"]:
            return
        messages["grabs"] += 1
        if messages["seen"] is not None:
            return
        for state in messages["watch"]:
            if _has_rule(guard, state) and guard(state, crop):
                kept = shots / f"{name}-{state}.png"
                shutil.copyfile(crop, kept)
                messages.update(seen=state, shot=str(kept))
                log("message", state=state, name=name, shot=str(kept))
                return

    def observe(state: str, name: str, crop: pathlib.Path) -> None:
        """Record a camp screen: whether a sheet offers HEAL, and whose identity rule was checked.

        Sheets, effects lists and item lists each record whether the identity
        map held a rule for their state.
        """
        if route_camp.is_display(state):
            entry = {"state": state, "shot": name, "identity_checked": _has_rule(identity, state),
                     # None: the guard map holds no rule for a bar that offers a further page.
                     "more_pages": (bool(guard(route_camp.DISPLAY_MORE, crop))
                                    if _has_rule(guard, route_camp.DISPLAY_MORE) else None)}
            result.setdefault("camp_displays", []).append(entry)
            log("camp_display", **entry)
            return
        if route_camp.is_items(state):
            entry = {"state": state, "shot": name, "identity_checked": _has_rule(identity, state)}
            result.setdefault("camp_item_lists", []).append(entry)
            log("camp_item_list", **entry)
            return
        if route_camp.is_join(state):
            # The message is whatever a message rule matched on this grab or an earlier one.
            entry = {"state": state, "shot": name, "message": messages["seen"],
                     "message_shot": messages["shot"],
                     "messages_ruled": [m for m in route_camp.JOIN_MESSAGES
                                        if _has_rule(guard, m)]}
            result.setdefault("camp_joins", []).append(entry)
            log("camp_join", **entry)
            return
        if route_camp.is_joined(state):
            entry = {"state": state, "shot": name,
                     "identity_checked": _has_rule(identity, state)}
            result.setdefault("camp_joins", [{}])[-1]["joined"] = entry
            log("camp_joined", **entry)
            return
        if not route_camp.is_sheet(state):
            return
        offered = None
        if _has_rule(guard, route_camp.SHEET_HEAL) and guard(route_camp.SHEET_HEAL, crop):
            offered = True
        elif _has_rule(guard, route_camp.SHEET_SPENT) and guard(route_camp.SHEET_SPENT, crop):
            offered = False
        entry = {"state": state, "shot": name, "heal_offered": offered,
                 "identity_checked": _has_rule(identity, state)}
        result.setdefault("camp_sheets", []).append(entry)
        log("camp_sheet", **entry)

    def run_title_answer() -> None:
        """Answer a challenge screen with X and RET while its guard matches, three rounds at most."""
        if not _has_rule(guard, "journal"):
            raise RouteError("screen guard map lacks ['journal']")
        for round_ in range(4):
            name = f"journal-{round_}"
            # "" is a frame not shown yet (no window, or hires), not an empty screen.
            while not capture(name, check=False, settle=False):
                wait(GUARD_POLL)
            if not guard("journal", shots / f"{name}.png"):
                return
            if round_ == 3:
                raise RouteError("the journal challenge is still on screen after three answers")
            for key in ("X", "RET"):
                guest.press(holder, key, timeout=route_limit(30))
                result["events"].append({"answer_key": key, "round": round_ + 1})
                log("answer", key=key, round=round_ + 1)
            wait(GUARD_POLL)

    def run_answer() -> None:
        """Run the journal answerer, again while it sees no challenge, until GUARD_LIMIT."""
        if title is not None and answer is None:
            return run_title_answer()
        started = time.monotonic()
        # A title run's DF0 is the boot disk with the loaded slot on it.
        adf = (disks["df0"] if title is not None else originals["boot_source"])
        while True:
            try:
                code, line = answer(holder, adf, route_limit(180))
            except RouteError as exc:
                result["events"].append({"answer_failed": str(exc)})
                log("answer", error=str(exc))
                raise
            result["events"].append({"answer": line, "exit_code": code})
            log("answer", exit_code=code, line=line)
            if code == 0 and line == "answered":
                return
            if line != "no challenge on screen":
                raise RouteError(f"the journal answerer ended {code}: {line!r}")
            if time.monotonic() - started >= GUARD_LIMIT:
                raise RouteError(f"no journal challenge on screen within {GUARD_LIMIT:.0f}s")
            wait(GUARD_POLL)

    inserts_done: dict[str, int] = {}

    def keep_interstitial(crop: pathlib.Path, screen: str, n: int) -> None:
        """Copy the matched crop and its raw grab under their own names, before the screen is acted on.

        Only a run of several draws keeps them; a failed copy is logged and the run goes on.
        The next grab of the same state overwrites `crop`, so without this the screen that
        was answered is gone by the time anybody wants to see it.
        """
        try:
            while (kept := shots / f"{crop.stem}-{screen}-{n}.png").exists():
                n += 1
            shutil.copyfile(crop, kept)
            raw = crop.with_name(f"{crop.stem}.raw.png")
            if raw.exists():
                shutil.copyfile(raw, kept.with_name(f"{kept.stem}.raw.png"))
        except OSError as exc:
            log("interstitial_keep_error", screen=screen, error=f"{type(exc).__name__}: {exc}")
            return
        log("interstitial_kept", screen=screen, crop=str(kept))

    def interstitial(state: str, crop: pathlib.Path, done: dict[str, int],
                     inserts_only: bool = False) -> bool:
        """Act on a known screen that is not the wanted one, by the title's table.

        An `insert` row's limit counts across the whole run, since the disk stays in the drive.
        `inserts_only` leaves the key and answer rows alone, for a measure run that writes nothing.
        """
        for screen, action, waiting_for, limit in table:
            if (title is None and not accept and screen in _ACCEPT_ONLY) or (
                    title is not None and measure and action[0] == "answer") or (
                    inserts_only and action[0] != "insert"):
                continue
            count = inserts_done if action[0] == "insert" else done
            if (count.get(screen, 0) >= limit or not _has_rule(guard, screen)
                    or (waiting_for is not None and state not in waiting_for)
                    or not guard(screen, crop)):
                continue
            count[screen] = count.get(screen, 0) + 1
            if counter is not None:
                keep_interstitial(crop, screen, count[screen])
            if action[0] == "answer":
                result["events"].append({"interstitial": screen})
                log("interstitial", screen=screen, key=None)
                run_answer()
            elif action[0] == "insert":
                _, drive, disk_key, key = action
                insert(drive, disk_key, screen)
                press_key(screen, key)
            else:
                names = (action[1],) if isinstance(action[1], str) else action[1]
                for key in names:
                    press_key(screen, key)
            return True
        return False

    def press_key(screen: str, key: str) -> None:
        guest.press(holder, key, timeout=route_limit(30))
        result["events"].append({"interstitial": screen, "key": key})
        log("interstitial", screen=screen, key=key)

    def insert(drive: int, disk_key: str, why: Any) -> None:
        entry = (manifest if title is None else manifest["disks"])[disk_key]
        try:
            receipt = guest.insert(holder, drive, remotes[disk_key], timeout=route_limit(60),
                                   sha256=entry["sha256"])
        except BaseException as exc:
            result["events"].append({"insert": disk_key, "drive": drive, "for": why,
                                     "error": str(exc),
                                     "receipt": getattr(exc, "receipt", None)})
            raise
        result["events"].append({"insert": disk_key, "drive": drive, "for": why,
                                 "receipt": receipt})
        log("insert", disk=disk_key, drive=drive, receipt=receipt)

    def settle_unguarded(state: str, name: str) -> str:
        """One settled capture of a state nobody has measured, marked as such."""
        digest = capture(name, check=False)
        result["events"][-1]["recognized"] = False
        if state not in result["unguarded"]:
            result["unguarded"].append(state)
        return digest

    def recognise(state: str, crop: pathlib.Path, done: dict[str, int]) -> str | None:
        """The state, or `party_menu` once `credits` is behind it, that the crop matches."""
        wanted = [state]
        if "credits" in done and _has_rule(guard, "party_menu"):
            wanted.append("party_menu")
        return next((s for s in wanted if guard(s, crop)), None)

    def until_guard(state: str, name: str, first_wait: float,
                    poll: float, limit: float, *, strict: bool = True) -> str:
        """Wait, then grab every `poll` seconds until the guard matches; keep the last crop.

        A state that is not `strict` and never matches falls back to a settled capture.
        """
        wait(first_wait)
        started = time.monotonic()
        done: dict[str, int] = {}
        crop = shots / f"{name}.png"
        while True:
            digest = capture(name, check=False, settle=False)
            if digest:
                look_for_messages(crop, name)
                hit = recognise(state, crop, done)
                if hit:
                    check_identity(hit, crop)
                    observe(hit, name, crop)
                    landed["state"] = hit
                    result["events"][-1]["recognized"] = hit
                    log("recognized", state=hit, name=name)
                    return digest
                if interstitial(state, crop, done):
                    # The limit measures waiting for the screen, not the time spent acting on
                    # a screen; each interstitial row's count and the route deadline bound it.
                    started = time.monotonic()
            if time.monotonic() - started >= limit:
                if not strict:
                    return settle_unguarded(state, name)
                missing = result.get("interstitials_without_guard")
                raise GuardMissed(f"{state} screen was not recognized within {limit:.0f}s;"
                                 f" kept {crop}"
                                 + (f"; the guard map has no rule for {missing}" if missing else ""))
            wait(poll)

    def reach(state: str, name: str, first_wait: float, *, strict: bool) -> str:
        if _guards(guard, state):
            limit = title.wait_limits.get(state, GUARD_LIMIT) if title else GUARD_LIMIT
            return until_guard(state, name, first_wait, GUARD_POLL, limit, strict=strict)
        wait(first_wait)
        done: dict[str, int] = {}
        digest = settle_unguarded(state, name)
        for again in range(1, 4):
            if not interstitial(state, shots / f"{name}.png", done, inserts_only=measure):
                break
            wait(first_wait)
            digest = settle_unguarded(state, f"{name}-after-{again}")
        return digest

    def perform(key: Any, kind: str, state: str, n: int) -> None:
        """Press one route step's key, after putting a disk in the drive when it is an `insert`."""
        if kind == "insert":
            drive, disk_key, key = key
            insert(drive, disk_key, n)
        guest.press(holder, key, timeout=route_limit(30))
        result["events"].append({"key": key, "step": n})
        log("write" if kind == "write" else "key", key=key, step=n, state=state)

    def measure_boot() -> str:
        """Capture the boot, keeping each distinct frame, until the title or a fixed span.

        With a `title` guard, single grabs every TITLE_POLL seconds act on the title's
        own interstitial table, as accept mode's boot wait does, until a grab recognises
        `title` (or `party_menu`, once `credits` is behind it), or the wait fails after
        TITLE_LIMIT. Without one, settled captures every MEASURE_BOOT_POLL seconds end
        after MEASURE_TITLE_SPAN.
        """
        title = _guards(guard, "title")
        started, last, n = time.monotonic(), "", 0
        done: dict[str, int] = {}
        while True:
            name = f"00-boot-{n:02d}"
            digest = capture(name, check=False, settle=not title)
            event = result["events"][-1]
            if title and digest:
                crop = shots / f"{name}.png"
                hit = recognise("title", crop, done)
                if hit:
                    event["recognized"] = hit
                    landed["state"] = hit
                    return digest
                interstitial("title", crop, done)
            if digest and digest == last:
                for path in (shots / f"{name}.raw.png", shots / f"{name}.png"):
                    path.unlink(missing_ok=True)
                event["kept"] = False
            elif digest:
                last, n = digest, n + 1
            elapsed = time.monotonic() - started
            if title and elapsed >= title_limit:
                raise RouteError(
                    f"title screen was not recognized within {title_limit:.0f}s")
            if not title and elapsed >= boot_span:
                return last
            wait(TITLE_POLL if title else MEASURE_BOOT_POLL)

    def rulebook_draws_after_route() -> None:
        """Each further draw: stage the question, camp-save to slot D, answer it, camp again."""
        save, write, back = steps[-3:]
        n = len(steps)
        for draw in range(2, rulebook_draws + 1):
            record = {"draw": draw, "asked": False, "answer": None, "exit_game": False}
            staged = None if rulebook_records is None else rulebook_records[draw - 2]
            if staged is not None:
                record.update(staged=staged, drawn=None, reader=None)
            result["rulebook"].append(record)
            tally_before = _keep_tally_lines()
            try:
                counter.stage(staged)
            except counter.savecount.SaveCountError as exc:
                # The helper's own message can carry private detail, so only its type is kept.
                log("draw_error", draw=draw, error=type(exc).__name__)
                raise RouteError(f"draw {draw}: {type(exc).__name__}") from None
            except Exception as exc:
                log("draw_error", draw=draw, error=type(exc).__name__)
                raise
            first = len(result["events"])

            def note_draw(record: dict = record, first: int = first) -> None:
                events = result["events"][first:]
                record["asked"] = any(
                    e.get("interstitial") == "journal" and "key" not in e for e in events)
                record["answer"] = next(
                    (e["answer"] for e in reversed(events) if "answer" in e), None)

            try:
                for key, state, kind in (save, write, back):
                    n += 1
                    perform(key, kind, state, n)
                    reach(state, f"{n:02d}-{state}", _step_wait(min_waits, state, kind),
                          strict=True)
                    note_draw()
                    if state == "exit_game":
                        record["exit_game"] = True
                        if not record["asked"]:
                            raise RouteError(f"draw {draw} reached exit_game with no question")
                if staged is not None:
                    record["drawn"] = counter.drawn()
                    record["reader"] = _reader_index(tally_before, _keep_tally_lines())
                    if record["drawn"] != staged:
                        raise RouteError(f"draw {draw}: the game's draw is not the staged record")
                    if record["reader"] is None:
                        raise RouteError(f"draw {draw}: the reader kept no single capture to compare")
                    if record["reader"] != counter.reader_index(record["drawn"]):
                        raise RouteError(f"draw {draw}: the reader disagrees with the game's draw")
            finally:
                note_draw()
                log("draw", **record)

    try:
        receipt = guest.claim(holder, timeout=30 if wait_lane > 0 else route_limit(30),
                              **_wait_option(wait_lane))
        if receipt != f"ok claimed by {holder}":
            raise RouteError(f"claim was not new: {receipt!r}; already yours is not a lane grant")
        if wait_lane > 0:
            # The wait for a lane is not part of the run: the deadline starts at the grant.
            begun = time.monotonic()
            route_end = begun + deadline_seconds - cleanup_window
            total_end = begun + deadline_seconds
        result["claim"] = receipt
        log("claim", receipt=receipt)
        claimed = True
        for name, local in local_disks.items():
            guest.put(local, remotes[name], timeout=route_limit(90))
        copied = True
        if not guest.silence(audio_proof):
            raise RouteError("the Windows VM audio mute proof expired before WinUAE start")
        start_attempted = True
        if title is None:
            result["start"] = guest.start(holder, remotes["df0"], remotes["df1"],
                                          timeout=route_limit(60))
        else:
            result["start"] = guest.start(
                holder, *(None if key is None else remotes[key] for key in title.mounted),
                timeout=route_limit(60), options=title.options)
        log("start", receipt=result["start"])
        if measure:
            previous = measure_boot()
            changed = True
            steps_m = route if title is None else title.measure_route
            skip = 0
            if landed["state"] == "title":
                skip = next((i for i, s in enumerate(steps_m, 1) if s[1] == "title"), 0)
            elif landed["state"] == "party_menu" and steps_m and steps_m[0][1] == "party_menu":
                # Leaving the credits with ESC can land on the party menu, which `P` opens.
                skip = 1
            for n, step in enumerate(steps_m, 1):
                if n <= skip:
                    result["events"].append({"skipped": step[0], "step": n})
                    continue
                if title is None:
                    (key, state), kind = step, "key"
                    if key.upper() in write_keys:
                        result["events"].append({"skipped_write_key": key, "step": n})
                        changed = False
                        break
                    guest.press(holder, key, timeout=route_limit(30))
                    result["events"].append({"key": key, "step": n})
                else:
                    key, state, kind = step
                    if kind in ("write", "answer"):
                        # The measured route ends where the run would first write or answer.
                        result["events"].append({"skipped_write_key": key, "step": n})
                        break
                    perform(key, kind, state, n)
                name = f"{n:02d}-{state}"
                if title is not None:
                    digest = reach(state, name, min_waits.get(state, 0), strict=True)
                elif _guards(guard, state):
                    digest = until_guard(state, name, min_waits.get(state, 0),
                                         GUARD_POLL, GUARD_LIMIT)
                else:
                    wait(min_waits.get(state, 0))
                    digest = capture(name, check=False)
                if digest == previous:
                    result["events"].append({"unchanged": key, "step": n})
                    changed = False
                    break
                previous = digest
            result["route_changed"] = changed
        else:
            until_guard("title", "title", 0, TITLE_POLL, title_limit)
            # Leaving the credits with ESC can land on the party menu, which `P` opens.
            skip_first = landed["state"] == "party_menu" and steps[0][1] == "party_menu"
            previous_world = ""
            previous_state = ""
            leg = _walk_leg(steps) if walk_retry else None
            resumed = False
            n = 0
            while n < len(steps):
                n += 1
                key, state, kind = steps[n - 1]
                in_leg = leg is not None and leg[0] <= n <= leg[1]
                if resumed and n == leg[0]:
                    resumed = False
                else:
                    for verb, mark_name in marks.get(n - 1, ()):
                        machine_step(verb, mark_name, n)
                    if in_leg and n == leg[0]:
                        machine_step("snapshot", WALK_LEG, n)
                try:
                    if n == 1 and skip_first:
                        result["events"].append({"skipped": key, "step": n})
                        continue
                    if kind == "answer":
                        run_answer()
                    else:
                        perform(key, kind, state, n)
                    name = (f"{n:02d}-post_write" if kind == "write" and state == "loaded_menu"
                            else f"{n:02d}-{state}")
                    if kind == "move":
                        first_wait = min_waits.get("world_after_move", 0)
                    elif kind == "write":
                        first_wait = min_waits.get(state, POST_WRITE_WAIT)
                    else:
                        first_wait = min_waits.get(state, 0)
                    loading = (silver_blades and kind == "key" and state == "loaded_menu"
                               and previous_state == "load_picker")
                    if loading:
                        watch_messages((LOAD_MESSAGE,))
                    elif route_camp.is_join(state):
                        watch_messages(tuple(route_camp.JOIN_MESSAGES))
                    digest = reach(state, name, first_wait,
                                   strict=not accept or state in strict_states or in_leg)
                    if loading:
                        guarded = _has_rule(guard, LOAD_MESSAGE)
                        result["load_message"] = {
                            "state": LOAD_MESSAGE, "guarded": guarded, "grabs": messages["grabs"],
                            "shown": (messages["seen"] is not None) if guarded else None,
                            "shot": messages["shot"]}
                        log("load_message", **result["load_message"])
                    watch_messages(())
                    if route_camp.is_join(state):
                        # JOIN's message is gone after its delay; the list it redrew is read now.
                        after = route_camp.joined_after(state)
                        reach(after, f"{n:02d}-{after}",
                              min_waits.get(after, route_camp.JOINED_WAIT),
                              strict=not accept or after in strict_states)
                    if (key, state, previous_state) == (
                            route_camp.REST_GO, route_camp.CAMP, route_camp.REST_MENU):
                        # A sheet counts as showing a rest's result only if it comes after it.
                        result["sheets_before_last_rest"] = len(result.get("camp_sheets", []))
                    previous_state = state
                    if kind == "move":
                        # Evidence only: the two saves judge the walk, never the picture.
                        result["events"][-1]["crop_changed"] = digest != previous_world
                    if state == "world":
                        previous_world = digest
                        if counter is not None:
                            counter.locate()
                except GuardMissed as exc:
                    if not in_leg:
                        raise
                    if len(result["walk_retries"]) >= walk_retry:
                        raise RouteError(f"step {n} ({state}) after {walk_retry} walk "
                                         f"retries: {exc}") from exc
                    result["walk_retries"].append(
                        {"attempt": len(result["walk_retries"]) + 1, "step": n, "error": str(exc)})
                    log("walk_retry", step=n, error=str(exc))
                    machine_step("restore", WALK_LEG, leg[0])
                    resumed = True
                    n = leg[0] - 1
            for verb, mark_name in marks.get(len(steps), ()):
                machine_step(verb, mark_name, len(steps) + 1)
            if counter is not None:
                rulebook_draws_after_route()
            if reload:
                # The world bar matched before this point, so the place needs no first wait.
                place, other = manifest["state_a"], manifest["other_place"]
                name = f"{len(steps) + 1:02d}-place"
                shown = result["reload"] = {
                    "letter": letter, "place": place, "shown": False,
                    "other_letter": manifest["other_letter"], "other_place": other,
                    "other_shown": None}
                digest = until_guard(place_state(place), name, 0, GUARD_POLL, GUARD_LIMIT)
                crop = shots / f"{name}.png"
                shown.update(shown=True, other_shown=bool(guard(place_state(other), crop)),
                             crop=str(crop), crop_sha256=digest)
                log("reload", **shown)
            result["completed"] = True
    except BaseException as exc:
        if (isinstance(exc, (RouteError, OSError)) and "route time" not in str(exc)
                and watch.timed_out(exc)):
            # A lane call cut short by the route time reports its own few seconds as a timeout.
            result["error_cause"] = f"{type(exc).__name__}: {exc}"
            timed_out = RouteError(f"the {route_note} ran out during a lane call")
            timed_out.__cause__ = exc
            exc = timed_out
        result["error"] = f"{type(exc).__name__}: {exc}"
        if not isinstance(exc, (RouteError, OSError, ValueError)):
            result["lost"] = result["error"]
            log("lost", reason=result["lost"])
        if start_attempted:
            try:
                capture("failure", check=False, cleanup=True)
            except BaseException as shot_error:
                result["failure_capture_error"] = f"{type(shot_error).__name__}: {shot_error}"
    finally:
        if start_attempted:
            try:
                result["stop"] = guest.stop(holder, timeout=cleanup_limit(30))
                stopped = True
                log("stop", receipt=result["stop"])
            except BaseException as exc:
                result["stop_error"] = f"{type(exc).__name__}: {exc}"
        if copied:
            for name, remote in remotes.items():
                local = out / f"fetched-{name}.adf"
                try:
                    guest.get(remote, local, timeout=cleanup_limit(60))
                    result["fetched"][name] = _entry(local)
                    log("fetch", disk=name, **result["fetched"][name])
                except BaseException as exc:
                    result[f"fetch_{name}_error"] = f"{type(exc).__name__}: {exc}"
        if preserve_specimen and title is not None:
            try:
                _read_title(title, manifest, result, out, disks, registered,
                            kept_before, letter, accept, measure, steps, reload)
                if result["success"]:
                    if not stopped:
                        raise RouteError("guest did not stop before specimen preservation")
                    fetched = out / f"fetched-{title.save_disk}.adf"
                    result["specimen"] = (
                        _preserve_published(manifest_path, attempt, published_name, fetched,
                                            manifest.get("issue", PUBLISHED_ISSUE),
                                            manifest.get("staged_place"),
                                            manifest.get("source_sha256"))
                        if published_disk_one else _preserve_published_disk_three(
                            manifest_path, manifest, attempt, title, specimen_issue, fetched)
                        if manifest.get("mode") == PUBLISHED_DISK_THREE_MODE else
                        _preserve_substituted(
                            manifest_path, manifest, attempt, title, specimen_issue, fetched))
                    problems = specimens.check_specimens(specimens.tree_root())
                    if problems:
                        raise RouteError("specimen check failed: " + "; ".join(problems))
                    log("specimen", **result["specimen"])
            except BaseException as exc:
                result["specimen_error"] = f"{type(exc).__name__}: {exc}"
                result["success"] = False
                log("specimen_error", error=result["specimen_error"])
        if claimed and (not start_attempted or stopped):
            try:
                result["release"] = guest.release(
                    holder, timeout=cleanup_limit(30))
                log("release", receipt=result["release"])
            except BaseException as exc:
                result["release_error"] = f"{type(exc).__name__}: {exc}"
                if preserve_specimen:
                    result["success"] = False
        if title is None:
            result["published_unchanged"] = sha256(published) == manifest[
                "published_df1"]["sha256"]
            result["working_unchanged"] = sha256(df1) == manifest["df1"]["sha256"]
            for name, path in originals.items():
                result[f"{name}_unchanged"] = sha256(path) == manifest[name]["sha256"]
            if "df0" in result["fetched"]:
                result["df0_unchanged"] = result["fetched"]["df0"]["sha256"] == manifest[
                    "df0"]["sha256"]
            if "df1" in result["fetched"]:
                result["df1_unchanged"] = result["fetched"]["df1"]["sha256"] == manifest[
                    "df1"]["sha256"]
            if "df0" in result["fetched"]:
                # The game saves to the boot disk it found its SAVE drawer on.
                try:
                    fetched = _verified_disk(out / "fetched-df0.adf")
                    # The game loads the staged slot, which a save count edits away from
                    # the published one, so the staged file is what must survive.
                    result["slot_unchanged"] = (
                        fetched.read_file(f"/SAVE/savgam{letter}.sav") == staged)
                    result["slot_a_unchanged"] = (
                        fetched.read_file("/SAVE/savgamA.sav")
                        == df0_disk.read_file("/SAVE/savgamA.sav"))
                    reading = _slot_reading(fetched, "B")
                    result["slot_b_sha256"] = reading.get("sha256")
                    if "decode_error" in reading:
                        result["slot_b_decode_error"] = reading["decode_error"]
                    elif "inventory" in reading:
                        result["slot_b"] = {"inventory": reading["inventory"],
                                            "state": reading["place"]}
                    # Only the pinned JOIN party must keep Guy's joined inventory.
                    party_problems = (_no_problems if "substitute" in manifest
                                      else _silver_blades_problems)
                    if not measure:
                        result["menu_save_problems"] = menu_save_problems(
                            manifest, reading, extra_problems=party_problems)
                    if accept:
                        slot_d = _slot_reading(fetched, CAMP_SAVE_LETTER)
                        result["slot_d_sha256"] = slot_d.get("sha256")
                        result["camp_save_problems"] = menu_save_problems(
                            manifest, slot_d, letter=CAMP_SAVE_LETTER, check_place=False,
                            extra_problems=party_problems)
                        squares = sum(1 for *_, kind in steps if kind == "move")
                        walk = walk_verdict(manifest["state_a"], reading, slot_d, squares)
                        result["walk"] = walk
                        result["read"] = {
                            "place_before": manifest["state_a"],
                            "menu_save": reading.get("place"),
                            "place_after": slot_d.get("place"),
                            "place_changed": walk["place_changed"],
                            "squares_moved": walk["squares_moved"],
                            "verdicts": walk["verdicts"],
                            # Evidence only: each saved member's effect rows.
                            "effects": {MENU_SAVE_LETTER: reading.get("effects"),
                                        CAMP_SAVE_LETTER: slot_d.get("effects")},
                        }
                        log("read", **result["read"])
                        allowed = {f"savgam{c}.sav".lower()
                                   for c in ("A", letter, MENU_SAVE_LETTER, CAMP_SAVE_LETTER)}
                        result["extra_saves"] = sorted(
                            e.name for e in fetched.entries(fetched.lookup("/SAVE").block)
                            if e.name.lower().startswith("savgam")
                            and e.name.lower() not in allowed)
                except BaseException as exc:
                    result["fetched_df0_error"] = f"{type(exc).__name__}: {exc}"
            if not measure:
                result.setdefault("menu_save_problems",
                                  ["slot B was not read from the fetched boot disk"])
                result["success"] = menu_save_verdict(result, tuple(originals))
                if accept:
                    result["read"] = result.get("read") or {
                        "verdicts": ["slots B and D were not read from the fetched boot disk"]}
                    result["success"] = bool(
                        result["success"] and result["completed"] and not result["unguarded"]
                        and result.get("walk", {}).get("b_ok")
                        and result.get("walk", {}).get("d_ok")
                        and result.get("camp_save_problems") == []
                        and result.get("extra_saves") == [])
            else:
                result["success"] = bool(
                    result.get("route_changed") and not result["error"]
                    and result.get("df0_unchanged") and result.get("df1_unchanged")
                    and result.get("slot_b_sha256", "absent") is None)
        elif not preserve_specimen:
            _read_title(title, manifest, result, out, disks, registered,
                        kept_before, letter, accept, measure, steps, reload)
        if preserve_specimen and title is None:
            try:
                if result["success"] and "release_error" not in result:
                    if not stopped:
                        raise RouteError("guest did not stop before specimen preservation")
                    result["specimen"] = _preserve_staged(
                        manifest_path, manifest, attempt, specimen_issue,
                        out / "fetched-df0.adf")
                    problems = specimens.check_specimens(specimens.tree_root())
                    if problems:
                        raise RouteError("specimen check failed: " + "; ".join(problems))
                    log("specimen", **result["specimen"])
                elif result["success"]:
                    result["success"] = False
            except BaseException as exc:
                result["specimen_error"] = f"{type(exc).__name__}: {exc}"
                result["success"] = False
                log("specimen_error", error=result["specimen_error"])
        result["elapsed_seconds"] = time.monotonic() - begun
        (out / "summary.json").write_text(json.dumps(result, indent=2,
                                                     sort_keys=True) + "\n")
        runlog.close()
    return result


TITLES: dict[str, AmigaTitle] = {"pool": POOL, "curse": CURSE, "darkness": DARKNESS,
                                 "darkness-reload": DARKNESS_RELOAD,
                                 "darkness-unstarted": DARKNESS_UNSTARTED,
                                 "darkness-vault": DARKNESS_VAULT}

_PREPARE = {"pool": _prepare_pool, "curse": _prepare_curse, "darkness": _prepare_darkness,
            "darkness-reload": _prepare_darkness_reload,
            "darkness-unstarted": functools.partial(
                _prepare_darkness, loaded=DARKNESS_UNSTARTED_LOADED),
            "darkness-vault": _prepare_darkness}


def _name(title: AmigaTitle) -> str:
    for name, known in TITLES.items():
        if known is title:
            return name
    raise RouteError("that is not one of this module's titles")


#: Titles with a slot importer for their own save format.
_SUBSTITUTABLE = frozenset(
    {"darkness", "darkness-vault", *(source.name for source in (POOL_SOURCES, CURSE_SOURCES)
                   if source.import_slot is not None)})


#: The titles whose own accept route (not a published one) takes camp steps from its manifest.
CAMP_TITLES = frozenset({"darkness", "pool"})


def prepare(title: AmigaTitle, run_id: str, *, specimen: pathlib.Path | None = None,
            specimen_sha256: str | None = None, accept_summary: pathlib.Path | None = None,
            substitute: pathlib.Path | None = None, substitute_letter: str = "A",
            camp: tuple[str, ...] = (), issue: str | None = None,
            vault_pages: int | None = None) -> pathlib.Path:
    """Copy the title's registered images and specimen into a run folder, write `prepare.json`, and return it.

    Blocks when any pinned hash differs, the loaded slot does not decode, or a
    save letter the run writes already exists. Nothing registered is written.
    `darkness-reload` prepares from a game-written disk 3, so it requires `specimen`,
    `specimen_sha256` and `accept_summary`, and the other titles block the last two.
    `substitute`, only on a title in `_SUBSTITUTABLE`, replaces the route's
    loaded slot with `substitute_letter`'s slot from that disk; every other
    file, and the specimen's own pin, are unaffected.
    `camp` (a title in `CAMP_TITLES` only) is a list of camp steps
    (`route_camp.validate_steps`) the accept route drives between camping and
    the camp save, kept in the manifest. `issue`, on any title, puts the run
    folder under that issue's number rather than this module's. `vault_pages`
    (`darkness-vault` only, default `VAULT_PAGES`) is the number of stored-items pages the
    run turns to, kept in the manifest for accept and measure.
    """
    if not HOLDER.fullmatch(run_id):
        raise RouteError("run id must use letters, digits, dot, underscore or hyphen")
    name = _name(title)
    reload = name == "darkness-reload"
    given = (specimen, specimen_sha256, accept_summary)
    if reload and not all(given):
        raise RouteError("darkness-reload needs the disk 3, its SHA-256 and the accept summary")
    if not reload and (specimen_sha256 or accept_summary):
        raise RouteError(f"{name} takes no disk 3 hash or accept summary")
    if substitute is not None and name not in _SUBSTITUTABLE:
        raise RouteError(f"{name} takes no substitute slot")
    if camp and name not in CAMP_TITLES:
        raise RouteError(f"{name} takes camp steps only on a published prepare")
    if vault_pages is not None and name != "darkness-vault":
        raise RouteError(f"{name} takes no vault page count")
    if name == "darkness-vault":
        vault_pages = VAULT_PAGES if vault_pages is None else vault_pages
        vault_steps(vault_pages)
    if issue is not None and not ISSUE_ARGUMENT.fullmatch(issue):
        raise RouteError("the issue is a number or WISH-N")
    if camp:
        camp = route_camp.normalise(tuple(camp))
        route_camp.validate_steps(camp, name=name)
    run = scratch.cache_dir("acceptance", issue or ISSUE, run_id)
    if run.exists():
        raise RouteError(f"run folder already exists: {run}")
    if reload:
        manifest = _PREPARE[name](run, specimen, specimen_sha256, accept_summary)
    elif name in _SUBSTITUTABLE:
        manifest = _PREPARE[name](run, specimen, substitute=substitute,
                                  substitute_letter=substitute_letter)
    else:
        manifest = _PREPARE[name](run, specimen)
    if camp:
        try:
            _camp_title(name, pool_title_for(manifest) if title is POOL else title,
                        list(camp), manifest["names_a"])
        except RouteError:
            # The party is read only once the disks are copied, so a rejection takes the folder
            # with it and a corrected retry can use the same run id.
            shutil.rmtree(run)
            raise
        manifest["camp"] = list(camp)
    if vault_pages is not None:
        manifest["vault_pages"] = vault_pages
    path = run / "prepare.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def _disk_files(disk: amiga_adf.AmigaDisk) -> dict[str, bytes]:
    return {path.lower(): disk.read_file(path) for path, _ in disk.walk()}


def _published_title(name: str, letter: str, *, issue: str = PUBLISHED_ISSUE,
                     turn_about: bool | None = None,
                     items_screen: bool = True,
                     opening_scene: bool = False) -> AmigaTitle:
    if name == "curse":
        from tools.amiga.route_curse import published_title  # noqa: PLC0415
        return published_title(letter, issue=issue, turn_about=turn_about)
    if name == "ssb":
        return route_silver_blades.published_title(
            letter, issue=issue, turn_about=turn_about, items_screen=items_screen,
            opening_scene=opening_scene)
    raise RouteError("published disk one is only for Curse and Silver Blades")


def _items_screen(name: str, reading: dict) -> bool:
    """Whether the route visits the items screen: only Silver Blades' sheet ever lacks the button.

    The button is absent for a character with nothing, and the sheet the route
    opens is the party's first member, GUY DE VALOIS, first in the saved order too.
    """
    return name != "ssb" or reading["inventory"]["members"][0]["count"] > 0


def _opening_scene(name: str, reading: dict | None) -> bool:
    """Whether the party has not set out, so the game shows its opening scene before the world.

    The game decides by the save's set-out flag, which `reading["not_set_out"]` carries. The
    start square does not tell: a party that has set out can be saved standing on it.
    """
    return name == "ssb" and bool(reading and reading.get("not_set_out"))


#: The published Curse C64 source's start: a wall stands ahead to the west, so the party turns and
#: walks back east over (6,13) to (7,13).
CURSE_WALLED_WEST = {"area": 1, "x": 5, "y": 13, "facing": geo.WEST}


def _turn_about(name: str, letter: str, place: dict | None) -> bool:
    """Whether the route turns the party about before walking out of its square.

    That is the start square, or `CURSE_WALLED_WEST` for Curse, where a wall stands ahead. A
    Silver Blades party on its start square never turns, because north of it is a wall.
    """
    if name == "ssb":
        start = areas.start_of(areas.SECRET_OF_THE_SILVER_BLADES)
        if place == {"area": start.area, "x": start.arrival.x, "y": start.arrival.y,
                     "facing": start.arrival.facing}:
            return False
    if letter == "D":
        return True
    if name != "curse":
        return False
    start = areas.start_of(areas.CURSE_OF_THE_AZURE_BONDS)
    return place in ({"area": start.area, "x": start.arrival.x, "y": start.arrival.y,
                      "facing": start.arrival.facing}, CURSE_WALLED_WEST)


def _camp_title(name: str, title: AmigaTitle, camp: Any, names: list) -> AmigaTitle:
    """The route with a manifest's camp steps before its camp save.

    A published Silver Blades or Curse route, or Pools of Darkness' or Pool of Radiance's own
    accept route. A Pool run whose steps press its after letter saves that slot elsewhere
    (`route_pool.pool_camp_title`).
    """
    route_camp.sheet_lines(name)
    if not isinstance(camp, list) or not all(isinstance(t, str) for t in camp):
        raise RouteError("the manifest camp steps are not a list of strings")
    tokens = tuple(camp)
    if route_camp.normalise(tokens) != tokens:
        raise RouteError("the manifest camp steps are not in their normal form")
    if name == "pool":
        route_camp.validate_steps(tokens, len(names), name=name)
        game, _ = route_camp.split_machine_steps(tokens)
        title = pool_camp_title(title, tuple(
            key for key, _, _ in route_camp.steps_for(game, name, len(names))))
    return route_camp.camp_title(title, tokens, len(names), name=name)


def accept_title(title: AmigaTitle, manifest: dict) -> AmigaTitle:
    """The route a title's own accept run drives for `manifest`.

    Pool's comes from its start square (`pool_title_for`); a manifest with camp steps puts them
    before the camp save. Published disk-one runs build theirs from their own manifest.
    """
    if title is POOL:
        title = pool_title_for(manifest)
    if "camp" in manifest:
        title = _camp_title(manifest["title"], title, manifest["camp"], manifest["names_a"])
    return title


def _vault_title_for(manifest_path: pathlib.Path) -> AmigaTitle:
    """The `darkness-vault` route for the page count its manifest recorded."""
    try:
        manifest = json.loads(pathlib.Path(manifest_path).read_text())
    except (OSError, ValueError) as exc:
        raise RouteError(f"the manifest {manifest_path} cannot be read: {exc}") from exc
    return vault_title(manifest.get("vault_pages", VAULT_PAGES))


def _substitute_mode(manifest_path: pathlib.Path) -> bool:
    """Whether the manifest at `manifest_path` is a Silver Blades substitute prepared as a title run."""
    try:
        manifest = json.loads(pathlib.Path(manifest_path).read_text())
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and manifest.get("mode") == SUBSTITUTE_TITLE_MODE


def _container_key(name: str) -> str:
    return CURSE_KEY if name == "curse" else route_silver_blades.TITLE


def _check_staged_place(name: str, letter: str, slot_path: str, staged: Any,
                        published: amiga_adf.AmigaDisk, working_path: pathlib.Path) -> None:
    """Re-derive a `--stage-place` change from the published disk and compare it to working DF0.

    Working DF0 must be the published image with the one slot's three square
    bytes changed as the manifest records, and nothing else.
    """
    try:
        after = staged["after"]
        before = staged["before"]
        if staged["slot"] != slot_path or len(after) != 3:
            raise RouteError("the manifest's staged place names another slot")
        derived, change = stage_place(published.read_file(slot_path), _container_key(name), *after)
    except (KeyError, TypeError) as exc:
        raise RouteError(f"the manifest's staged place is malformed: {exc!r}") from exc
    except StageError as exc:
        raise RouteError(f"the manifest's staged place: {exc}") from exc
    if change["before"] != before or change["after"] != after:
        raise RouteError("the manifest's staged place differs from the published slot")
    working = _verified_disk(working_path)
    old, new = _disk_files(published), _disk_files(working)
    if (new.get(slot_path) != derived or set(new) != set(old) or
            any(new[key] != value for key, value in old.items() if key != slot_path) or
            set(p.lower() for p, _ in working.walk_dirs()) !=
            set(p.lower() for p, _ in published.walk_dirs()) or
            working.to_bytes()[:1024] != published.to_bytes()[:1024]):
        raise RouteError("working DF0 differs from the published image by more than "
                         "the staged place")
    # The per-file check above gives the reason; this one also covers the bytes outside
    # any file, such as a free sector, that only a rebuild of the whole image can see.
    rebuilt = amiga_adf.AmigaDisk(published.to_bytes())
    replace_file_in_place(rebuilt, slot_path, derived)
    if hashlib.sha256(rebuilt.to_bytes()).hexdigest() != sha256(working_path):
        raise RouteError("working DF0 is not the published image with the staged place "
                         "and nothing else, byte for byte")


def _published_manifest(path: pathlib.Path, name: str) -> tuple[dict, AmigaTitle]:
    manifest = json.loads(path.read_text())
    if manifest.get("mode") != "published_disk_one" or manifest.get("issue") not in PUBLISHED_SOURCES_BY_ISSUE:
        raise RouteError("the manifest is not a published disk-one run")
    if manifest.get("title") != name:
        raise RouteError("the CLI title differs from the published manifest")
    port, letter = manifest["source_port"], manifest["loaded_letter"]
    if port not in ("c64", "dos") or letter != ("A" if port == "c64" else "D"):
        raise RouteError("the published source port and slot letter disagree")
    if manifest.get("source_sha256") not in _source_pins(manifest["issue"], name, port):
        raise RouteError("the manifest source differs from the pinned specimen")
    turn_about = manifest.get("turn_about", letter == "D")
    if not isinstance(turn_about, bool):
        raise RouteError("the manifest turn_about is not a boolean")
    if "turn_about" in manifest and turn_about != _turn_about(name, letter,
                                                              manifest.get("state_a")):
        raise RouteError("the manifest turn_about disagrees with its recorded place")
    if name != "ssb" and "items_screen" in manifest:
        raise RouteError("only a Silver Blades manifest records items_screen")
    items_screen = manifest.get("items_screen", True)
    if not isinstance(items_screen, bool):
        raise RouteError("the manifest items_screen is not a boolean")
    recorded = None
    if name == "ssb":
        recorded = _published_title(name, letter, issue=manifest["issue"]).read_slot(
            _verified_disk(_input(manifest["registered"], "published")), letter)
        if "inventory" not in recorded:
            cause = ("is missing" if recorded.get("missing") else
                     f"does not decode: {recorded.get('decode_error', 'no inventory')}")
            raise RouteError(f"the published slot {cause}, so items_screen cannot be checked")
    opening_scene = _opening_scene(name, recorded)
    if manifest.get("opening_scene", opening_scene) != opening_scene:
        raise RouteError("the manifest opening_scene disagrees with the published slot")
    title = _published_title(name, letter, issue=manifest["issue"], turn_about=turn_about,
                             items_screen=items_screen, opening_scene=opening_scene)
    if "camp" in manifest:
        title = _camp_title(name, title, manifest["camp"], manifest["names_a"])
    for key in ("source", "report", "published", "disk_one", "disk_two"):
        _input(manifest["registered"], key)
    if name == "ssb":
        if items_screen != _items_screen(name, recorded):
            raise RouteError("the manifest items_screen disagrees with the published slot")
    disk1_pin, disk2_pin, executable, volume = PUBLISHED_DISKS[name]
    if (manifest["registered"]["disk_one"]["sha256"] != disk1_pin or
            manifest["registered"]["disk_two"]["sha256"] != disk2_pin):
        raise RouteError("the registered disks differ from the title's pins")
    staged = manifest.get("staged_place")
    if staged is None and (manifest["disks"]["df0"]["sha256"]
                           != manifest["registered"]["published"]["sha256"]):
        raise RouteError("working DF0 is not the exact published image")
    if manifest["disks"]["df1"]["sha256"] != disk2_pin:
        raise RouteError("working DF1 differs from the pinned disk 2")
    report = json.loads(_input(manifest["registered"], "report").read_text())
    if (report.get("specimen_sha256") != manifest["source_sha256"] or
            pathlib.Path(report.get("specimen", "")) !=
            pathlib.Path(manifest["registered"]["source"]["path"]) or
            pathlib.Path(report.get("amiga_disk1", "")) !=
            pathlib.Path(manifest["registered"]["disk_one"]["path"]) or
            pathlib.Path(report.get("amiga_disk2", "")) !=
            pathlib.Path(manifest["registered"]["disk_two"]["path"]) or
            report.get("written") != report.get("save_as", {}).get("written") or
            len(report.get("written", [])) != 1 or
            pathlib.Path(report["written"][0]).name != "POOLSAVE.ADF" or
            pathlib.Path(report.get("save_as", {}).get("destination", "")) !=
            pathlib.Path(report["written"][0]) or
            manifest.get("published_source", {
                "path": report["written"][0],
                "sha256": manifest["registered"]["published"]["sha256"],
            }) != {
                "path": report["written"][0],
                "sha256": manifest["registered"]["published"]["sha256"],
            } or
            report.get("save_as", {}).get("slot") != letter or
            report.get("save_as", {}).get("to") != "amiga" or
            report.get("save_as", {}).get("stopped") or
            report.get("save_as", {}).get("losses") or
            report.get("save_as", {}).get("dropped") or
            report.get("written_sha256") != {"POOLSAVE.ADF": manifest["registered"]["published"]["sha256"]}):
        raise RouteError("the Save As report differs from the published manifest")
    published = _verified_disk(_input(manifest["registered"], "published"))
    original = _verified_disk(_input(manifest["registered"], "disk_one"))
    if published.volume_name != volume or original.volume_name != volume:
        raise RouteError("the published image is not the title's disk 1")
    slot_path = f"/SAVE/savgam{letter}.{'dat' if name == 'curse' else 'sav'}".lower()
    old, new = _disk_files(original), _disk_files(published)
    if (set(new) != set(old) | {slot_path} or
            any(new.get(key) != value for key, value in old.items() if key != slot_path) or
            set(path.lower() for path, _ in published.walk_dirs()) !=
            set(path.lower() for path, _ in original.walk_dirs()) or
            published.to_bytes()[:1024] != original.to_bytes()[:1024] or
            executable.lower() not in new or "/save/spindisk" not in new):
        raise RouteError("the published image differs from disk 1 outside the converted slot")
    if new[slot_path] == old.get(slot_path):
        raise RouteError("the published slot was not converted")
    working = published
    if staged is not None:
        working_path = _input(manifest["disks"], "df0")
        _check_staged_place(name, letter, slot_path, staged, published, working_path)
        working = _verified_disk(working_path)
    # A staged place is what the game loads, so it is the place the run expects.
    reading = title.read_slot(working, letter)
    if (reading.get("place") != manifest["state_a"] or
            reading.get("names") != manifest["names_a"] or
            reading.get("clock") != manifest["clock_a"]):
        raise RouteError("the published slot differs from the prepared party")
    return manifest, title


def prepare_published(name: str, run_id: str, report_path: pathlib.Path,
                      issue: str = PUBLISHED_ISSUE, camp: tuple[str, ...] = (),
                      place: tuple[int, int, int] | None = None) -> pathlib.Path:
    """Preserve and check the exact Save As disk one before any guest run.

    `camp` is a list of camp steps (`route_camp.validate_steps`) the accept
    route drives between camping and the camp save; it is kept in the manifest
    in its normal form, so measure and accept both rebuild the same route.
    `place` is `(x, y, facing)`: working DF0 holds the published image with only
    the loaded slot's square changed, and the manifest records the change as
    `staged_place` and expects that square on load. The registered published
    image and the source pins are untouched. Blocked before any run folder is
    made when the values are out of range or the slot was saved outdoors.
    """
    if not HOLDER.fullmatch(run_id):
        raise RouteError("run id must use letters, digits, dot, underscore or hyphen")
    if name not in PUBLISHED_DISKS:
        raise RouteError("published disk one is only for Curse and Silver Blades")
    if issue not in PUBLISHED_SOURCES_BY_ISSUE:
        raise RouteError(f"published disk one has no pinned sources for issue {issue}")
    report_path = pathlib.Path(report_path)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    outcome = report.get("save_as", {})
    if (outcome.get("stopped") or outcome.get("losses") or outcome.get("dropped") or
            report.get("written") != outcome.get("written") or
            len(report.get("written", [])) != 1 or
            outcome.get("to") != "amiga"):
        raise RouteError("Save As did not publish one lossless Amiga image")
    port = "c64" if report.get("c64_disks_dir") else "dos"
    letter = "A" if port == "c64" else "D"
    if outcome.get("slot") != letter:
        raise RouteError("Save As reported the wrong source slot letter")
    source = pathlib.Path(report["specimen"])
    image = pathlib.Path(report["written"][0])
    disk1 = pathlib.Path(report["amiga_disk1"])
    disk2 = pathlib.Path(report["amiga_disk2"])
    pins = _source_pins(issue, name, port)
    if not pins:
        raise RouteError(f"issue {issue} pins no {port} source for {name}")
    source_pin = report.get("specimen_sha256")
    disk1_pin, disk2_pin, _executable, _volume = PUBLISHED_DISKS[name]
    if (source != pathlib.Path(outcome.get("source", "")) or
            source_pin not in pins or sha256(source) != source_pin):
        raise RouteError("the Save As source differs from the pinned specimen")
    if sha256(disk1) != disk1_pin or sha256(disk2) != disk2_pin:
        raise RouteError("the Save As game disks differ from the registered pins")
    image_sha = sha256(image)
    if (report.get("written_sha256") != {image.name: image_sha} or
            image.name != "POOLSAVE.ADF" or
            pathlib.Path(outcome.get("destination", "")) != image):
        raise RouteError("the Save As image differs from its report")
    disk = _verified_disk(image)
    reading = _published_title(name, letter, issue=issue).read_slot(disk, letter)
    if "place" not in reading or "clock" not in reading:
        raise RouteError(f"published slot {letter} does not decode: {reading}")
    slot_path = f"/SAVE/savgam{letter}.{'dat' if name == 'curse' else 'sav'}".lower()
    staged = None
    staged_disk = None
    if place is not None:
        try:
            data, change = stage_place(disk.read_file(slot_path), _container_key(name), *place)
        except (StageError, amiga_adf.AmigaDiskError) as exc:
            raise RouteError(f"--stage-place: {exc}") from exc
        staged = {"slot": slot_path, **change}
        staged_disk = amiga_adf.AmigaDisk(disk.to_bytes())
        try:
            replace_file_in_place(staged_disk, slot_path, data)
        except StageError as exc:
            raise RouteError(f"--stage-place: {exc}") from exc
        reading = _published_title(name, letter, issue=issue).read_slot(staged_disk, letter)
        if reading.get("place", {}).get("facing") != place[2]:
            raise RouteError("--stage-place: the staged slot does not read back the place")
    # The way out of the start square depends on where the party stands, not on the port:
    # Curse's start square faces a wall to the east, and CURSE_WALLED_WEST faces one to the west.
    turn_about = _turn_about(name, letter, reading["place"])
    items_screen = _items_screen(name, reading)
    opening_scene = _opening_scene(name, reading)
    title = _published_title(name, letter, issue=issue, turn_about=turn_about,
                             items_screen=items_screen, opening_scene=opening_scene)
    if camp:
        camp = route_camp.normalise(tuple(camp))
        _camp_title(name, title, list(camp), reading["names"])
    original = _verified_disk(disk1)
    old, new = _disk_files(original), _disk_files(disk)
    executable, volume = PUBLISHED_DISKS[name][2:]
    if (disk.volume_name != volume or original.volume_name != volume or
            set(new) != set(old) | {slot_path} or
            any(new.get(key) != value for key, value in old.items() if key != slot_path) or
            set(path.lower() for path, _ in disk.walk_dirs()) !=
            set(path.lower() for path, _ in original.walk_dirs()) or
            disk.to_bytes()[:1024] != original.to_bytes()[:1024] or
            executable.lower() not in new or "/save/spindisk" not in new or
            new[slot_path] == old.get(slot_path)):
        raise RouteError("the published image differs from disk 1 outside the converted slot")
    present = title.slot_letters(disk)
    if letter not in present or any(c in present for c in ("C", "F")):
        raise RouteError("the published image lacks its slot or already holds a save target")
    run = scratch.cache_dir("acceptance", issue, run_id)
    if run.exists():
        raise RouteError(f"run folder already exists: {run}")
    scratch.ensure(run)
    published = run / "published.adf"
    df0 = run / "df0.adf"
    df1 = run / "df1.adf"
    report_copy = run / "saveas-report.json"
    for src, dst in ((image, published), (image, df0), (disk2, df1)):
        with src.open("rb") as reader, dst.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
    if staged_disk is not None:
        df0.write_bytes(staged_disk.to_bytes())
    report_copy.write_bytes(report_bytes)
    published.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    report_copy.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    if (sha256(published) != image_sha or sha256(df1) != disk2_pin or
            (staged is None and sha256(df0) != image_sha)):
        raise RouteError("a copied acceptance disk differs from its input")
    manifest = {
        "mode": "published_disk_one", "issue": issue,
        "turn_about": turn_about,
        "title": name, "source_port": port, "source_sha256": source_pin,
        "loaded_letter": letter, "names_a": reading["names"],
        "state_a": reading["place"], "clock_a": reading["clock"],
        "expected_after": None,
        "published_source": {"path": str(image), "sha256": image_sha},
        "disks": {"df0": _entry(df0), "df1": _entry(df1)},
        "registered": {"source": _entry(source), "report": _entry(report_copy),
                       "published": _entry(published), "disk_one": _entry(disk1),
                       "disk_two": _entry(disk2)},
    }
    if name == "ssb":
        manifest["items_screen"] = items_screen
        manifest["opening_scene"] = opening_scene
    if camp:
        manifest["camp"] = list(camp)
    if staged is not None:
        manifest["staged_place"] = staged
    path = run / "prepare.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    _published_manifest(path, name)
    return path


def _pin_key(issue: str) -> str:
    """The `PUBLISHED_SOURCES_BY_ISSUE` key of a run folder's ticket: its number."""
    if not ISSUE_ARGUMENT.fullmatch(issue):
        raise RouteError("the issue is a number or WISH-N")
    return issue.removeprefix("WISH-")


def _wish_issue(issue: str) -> str:
    """`WISH-N` for an issue given as `N` or `WISH-N`, so both name one run folder."""
    if not ISSUE_ARGUMENT.fullmatch(issue):
        raise RouteError("the issue is a number or WISH-N")
    return "WISH-" + issue.removeprefix("WISH-")


def _darkness_pins(issue: str) -> frozenset:
    """The DOS sources a ticket pins for Pools of Darkness; none when it has no row."""
    key = _pin_key(issue)
    return _source_pins(key, "darkness", "dos") if key in PUBLISHED_SOURCES_BY_ISSUE else frozenset()


def _slot_paths(letter: str) -> tuple[str, str]:
    """Lower-cased paths of the two files a Pools of Darkness slot is written to."""
    return (amiga_savegame.pod_slot_path(letter).lower(),
            amiga_savegame.pod_vault_path(letter).lower())


def _darkness_disk_three_title(manifest: dict, disk: amiga_adf.AmigaDisk) -> AmigaTitle:
    """The route a published or reloaded disk 3 allows, from the letters the disk holds."""
    letter = manifest["loaded_letter"]
    present = DARKNESS.slot_letters(disk)
    if letter not in present:
        raise RouteError(f"the disk 3 holds no slot {letter} to load")
    if manifest.get("mode") == PUBLISHED_DISK_THREE_RELOAD_MODE:
        title = published_reload_title(letter, present)
        recorded = {"kept_letters": list(title.kept_letters)}
    else:
        title = published_title(letter, present)
        recorded = {"control_letter": title.control_letter, "after_letter": title.after_letter,
                    "kept_letters": list(title.kept_letters)}
    if any(manifest.get(key) != value for key, value in recorded.items()):
        raise RouteError("the manifest's save letters differ from the letters its disk 3 holds")
    return title


def published_darkness_title(manifest_path: pathlib.Path, name: str) -> AmigaTitle | None:
    """The route a Pools of Darkness manifest on a published disk 3 names, or None for any other manifest."""
    try:
        manifest = json.loads(pathlib.Path(manifest_path).read_text())
    except (OSError, ValueError):
        return None
    mode = manifest.get("mode") if isinstance(manifest, dict) else None
    if mode not in (PUBLISHED_DISK_THREE_MODE, PUBLISHED_DISK_THREE_RELOAD_MODE):
        return None
    if manifest.get("title") != name:
        raise RouteError("the CLI title differs from the published disk 3 manifest")
    try:
        if mode == PUBLISHED_DISK_THREE_MODE:
            pins = _darkness_pins(str(manifest["issue"]))
            if manifest["source_sha256"] not in pins:
                raise RouteError("the manifest source differs from the pinned specimen")
        return _darkness_disk_three_title(manifest, _verified_disk(_input(manifest["disks"], "disk3")))
    except KeyError as exc:
        raise RouteError(f"the manifest lacks {exc.args[0]!r}") from exc


def _remove_run_folder(run: pathlib.Path) -> None:
    """Delete a run folder whose copies were made read-only; a failure to delete is raised.

    Windows will not unlink a read-only file, so the bit is cleared and the unlink retried.
    """
    def clear_and_retry(function, path, error):
        os.chmod(path, stat.S_IWRITE)
        function(path)

    shutil.rmtree(run, onexc=clear_and_retry)


def prepare_published_disk_three(run_id: str, report_path: pathlib.Path, issue: str,
                                 camp: tuple[str, ...] = ()) -> pathlib.Path:
    """Preserve and check a disk 3 that Save As wrote from a DOS Pools of Darkness slot, before any guest run.

    The published image must be the registered disk 3 in every file but the loaded slot's
    `SavGam<L>.pty` and `Vault<L>.DAT`, and both must be on it. The report's DOS source is pinned
    by SHA-256 under `issue` in `PUBLISHED_SOURCES_BY_ISSUE`. The loaded letter is the report's
    slot; the control and after letters are two the image does not hold and every other held
    letter is kept. `camp` is a list of camp steps, as for `prepare_published`. Nothing registered
    is written, and an error leaves no run folder. `issue` names the run folder as `WISH-N`,
    whether it is given as `N` or `WISH-N`.
    """
    if not HOLDER.fullmatch(run_id):
        raise RouteError("run id must use letters, digits, dot, underscore or hyphen")
    issue = _wish_issue(issue)
    pins = _darkness_pins(issue)
    if not pins:
        raise RouteError(f"issue {issue} pins no dos source for darkness")
    report_path = pathlib.Path(report_path)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    outcome = report.get("save_as", {})
    if (outcome.get("stopped") or outcome.get("losses") or outcome.get("dropped") or
            report.get("written") != outcome.get("written") or
            len(report.get("written", [])) != 1 or outcome.get("to") != "amiga"):
        raise RouteError("Save As did not publish one lossless Amiga image")
    letter = outcome.get("slot")
    if not isinstance(letter, str) or not re.fullmatch(r"[A-J]", letter):
        raise RouteError("Save As reported no source slot letter")
    source = pathlib.Path(report["specimen"])
    image = pathlib.Path(report["written"][0])
    disk3 = pathlib.Path(report["amiga_disk3"])
    source_pin = report.get("specimen_sha256")
    if (source != pathlib.Path(outcome.get("source", "")) or
            source_pin not in pins or sha256(source) != source_pin):
        raise RouteError("the Save As source differs from the pinned specimen")
    if sha256(disk3) != DARKNESS_DISK3_SHA256:
        raise RouteError("the Save As disk 3 differs from the registered pin")
    image_sha = sha256(image)
    if (report.get("written_sha256") != {image.name: image_sha} or
            pathlib.Path(outcome.get("destination", "")) != image):
        raise RouteError("the Save As image differs from its report")
    published = _verified_disk(image)
    registered = _verified_disk(disk3)
    if published.volume_name != DARKNESS_VOLUME or registered.volume_name != DARKNESS_VOLUME:
        raise RouteError(f"the published image is not a {DARKNESS_VOLUME} disk")
    old, new = _disk_files(registered), _disk_files(published)
    slot_paths = _slot_paths(letter)
    if (set(new) != set(old) | set(slot_paths) or
            any(new.get(key) != value for key, value in old.items() if key not in slot_paths) or
            set(path.lower() for path, _ in published.walk_dirs()) !=
            set(path.lower() for path, _ in registered.walk_dirs()) or
            published.to_bytes()[:1024] != registered.to_bytes()[:1024]):
        raise RouteError("the published image differs from disk 3 outside the converted slot")
    if new[slot_paths[0]] == old.get(slot_paths[0]):
        raise RouteError("the published slot was not converted")
    # The vault the converter writes (`PodDosToAmiga.rehearse`): the DOS vault beside the source, or
    # an empty one when the slot has none.
    dos_vault = source.parent / f"VAULT{letter}.DAT"
    converted_vault = amiga_savegame.pod_vault_to_amiga(
        dos_codec.pod_vault_from_dos(dos_vault.read_bytes()) if dos_vault.is_file()
        else dos_codec.EMPTY_POD_VAULT)
    if new[slot_paths[1]] != converted_vault:
        raise RouteError(f"vault {letter} is not the vault converted from the DOS source")
    reading = DARKNESS.read_slot(published, letter)
    if "place" not in reading:
        raise RouteError(f"published slot {letter} does not decode: {reading}")
    present = DARKNESS.slot_letters(published)
    title = published_title(letter, present)
    if camp:
        camp = route_camp.normalise(tuple(camp))
        _camp_title("darkness", title, list(camp), reading["names"])
    wanted = {"disk1": DARKNESS_DISK1_SHA256, "disk2": DARKNESS_DISK2_SHA256}
    images = _find_images(wanted)
    run = scratch.cache_dir("acceptance", issue, run_id)
    if run.exists():
        raise RouteError(f"run folder already exists: {run}")
    scratch.ensure(run)
    try:
        disks: dict[str, dict[str, str]] = {}
        for key, data in (("disk1", images["disk1"][1]), ("disk2", images["disk2"][1]),
                          ("disk3", image.read_bytes())):
            working = run / f"{key}.adf"
            working.write_bytes(data)
            disks[key] = _entry(working)
        published_copy = run / "published.adf"
        report_copy = run / "saveas-report.json"
        shutil.copyfile(image, published_copy)
        report_copy.write_bytes(report_bytes)
        published_copy.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        report_copy.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        if (any(disks[key]["sha256"] != pinned for key, pinned in wanted.items()) or
                disks["disk3"]["sha256"] != image_sha or sha256(published_copy) != image_sha):
            raise RouteError("a working copy differs from its input")
        after = _find_images(wanted)
        if any(hashlib.sha256(after[key][1]).hexdigest() != pinned for key, pinned in wanted.items()):
            raise RouteError("a registered image changed during preparation")
    except BaseException:
        _remove_run_folder(run)
        raise
    manifest = {
        "mode": PUBLISHED_DISK_THREE_MODE, "issue": issue, "title": "darkness",
        "source_port": "dos", "source_sha256": source_pin,
        "loaded_letter": letter, "names_a": reading["names"], "state_a": reading["place"],
        "control_letter": title.control_letter, "after_letter": title.after_letter,
        "kept_letters": list(title.kept_letters),
        "expected_after": None,
        "disks": disks,
        "registered": {"source": _entry(source), "report": _entry(report_copy),
                       "published": _entry(published_copy), "disk_three": _entry(disk3)},
        "sources": {key: {"label": images[key][0], "sha256": wanted[key]} for key in wanted},
    }
    if camp:
        manifest["camp"] = list(camp)
    path = run / "prepare.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    published_darkness_title(path, "darkness")
    return path


def prepare_published_disk_three_reload(
        run_id: str, published_manifest: pathlib.Path, fetched: pathlib.Path, fetched_sha256: str,
        accept_summary: pathlib.Path, issue: str | None = None) -> pathlib.Path:
    """Prepare a reload run on the disk 3 a successful published disk 3 accept run fetched.

    `published_manifest` is that run's `prepare.json`. Blocks a file that does not hash to
    `fetched_sha256`, a summary that is not a successful accept run whose fetched disk 3 has that
    hash, a disk that is not the published image plus exactly the control and after saves, saves
    that do not decode to the loaded party, and two saves at one place. The reload loads the after
    slot and compares the control slot's place; every other held slot is kept.
    """
    if not HOLDER.fullmatch(run_id):
        raise RouteError("run id must use letters, digits, dot, underscore or hyphen")
    issue = issue or json.loads(pathlib.Path(published_manifest).read_text()).get("issue")
    if not isinstance(issue, str):
        raise RouteError("the issue is a number or WISH-N")
    issue = _wish_issue(issue)
    published_manifest, fetched, accept_summary = (
        pathlib.Path(p) for p in (published_manifest, fetched, accept_summary))
    for path in (fetched, accept_summary):
        if not path.is_file():
            raise RouteError(f"the file {path} is missing")
    first = published_darkness_title(published_manifest, "darkness")
    if first is None:
        raise RouteError("the manifest is not a published disk 3 run")
    manifest = json.loads(published_manifest.read_text())
    if sha256(fetched) != fetched_sha256:
        raise RouteError(f"the disk 3 SHA-256 differs: {sha256(fetched)}")
    try:
        summary = json.loads(accept_summary.read_text())
        summary_sha = summary["fetched"]["disk3"]["sha256"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RouteError(f"the accept summary {accept_summary} is unreadable: {exc}") from exc
    if summary.get("success") is not True or summary.get("accept") is not True:
        raise RouteError("the summary is not a successful accept run")
    if summary_sha != fetched_sha256:
        raise RouteError("the summary's fetched disk 3 is another disk")
    save = _verified_disk(fetched)
    if save.volume_name != DARKNESS_VOLUME:
        raise RouteError(f"disk 3 is not a verified {DARKNESS_VOLUME} disk")
    published = _verified_disk(_input(manifest["registered"], "published"))
    control, after = first.control_letter, first.after_letter
    written = {c: DARKNESS.slot_files(save, c) for c in (control, after)}
    added = {f"/save/{name}".lower() for files in written.values() for name in files}
    have, before = _disk_files(save), _disk_files(published)
    # The game writes the loaded slot's vault over the vault file of each new letter, so those two
    # files are compared as vaults below and not byte for byte.
    rewritten = {_slot_paths(c)[1] for c in (control, after)}
    if len(added) != 2 or set(have) != set(before) | added or any(
            have[name] != data for name, data in before.items() if name not in rewritten):
        raise RouteError(f"disk 3 is not the published disk 3 plus slots {control} and {after}")
    loaded_vault = amiga_savegame.pod_read_vault(published, manifest["loaded_letter"])
    for c in (control, after):
        if amiga_savegame.pod_read_vault(save, c) != loaded_vault:
            raise RouteError(f"vault {c} is not the loaded slot's vault")
    reading = {c: DARKNESS.read_slot(save, c) for c in (control, after)}
    for c, one in reading.items():
        if "place" not in one:
            raise RouteError(f"slot {c} does not decode: {one}")
        if one["names"] != manifest["names_a"]:
            raise RouteError(f"slot {c} names another party than slot {manifest['loaded_letter']}")
    if reading[control]["place"] == reading[after]["place"]:
        raise RouteError(f"slots {control} and {after} are at one place, which the screen "
                         "cannot tell apart")
    present = DARKNESS.slot_letters(save)
    reload_title = published_reload_title(after, present)
    run = scratch.cache_dir("acceptance", issue, run_id)
    if run.exists():
        raise RouteError(f"run folder already exists: {run}")
    wanted = {"disk1": DARKNESS_DISK1_SHA256, "disk2": DARKNESS_DISK2_SHA256}
    images = _find_images(wanted)
    scratch.ensure(run)
    disks: dict[str, dict[str, str]] = {}
    for key in wanted:
        working = run / f"{key}.adf"
        working.write_bytes(images[key][1])
        disks[key] = _entry(working)
    working = run / "disk3.adf"
    shutil.copyfile(fetched, working)
    disks["disk3"] = _entry(working)
    if any(disks[key]["sha256"] != pinned for key, pinned in wanted.items()):
        raise RouteError("a working copy differs from the pinned disk")
    if disks["disk3"]["sha256"] != fetched_sha256 or sha256(fetched) != fetched_sha256:
        raise RouteError("the working disk 3 differs from the input")
    result = {
        "mode": PUBLISHED_DISK_THREE_RELOAD_MODE, "issue": issue, "title": "darkness-reload",
        "disks": disks,
        "registered": {"accept_disk3": _entry(fetched),
                       "published": manifest["registered"]["published"]},
        "sources": {key: {"label": images[key][0], "sha256": wanted[key]} for key in wanted},
        "loaded_letter": after, "state_a": reading[after]["place"],
        "names_a": reading[after]["names"],
        "other_letter": control, "other_place": reading[control]["place"],
        "kept_letters": list(reload_title.kept_letters),
        "slot_sha256": {c: one["sha256"] for c, one in reading.items()},
        "vault_sha256": {c: hashlib.sha256(have[_slot_paths(c)[1]]).hexdigest()
                         for c in (control, after)},
        "accept_summary": _entry(accept_summary),
        "published_manifest": _entry(published_manifest),
    }
    path = run / "prepare.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    published_darkness_title(path, "darkness-reload")
    return path


def _summary(result: dict[str, Any], manifest: pathlib.Path, attempt: str) -> str:
    path = str(manifest.parent / attempt / "summary.json")
    if result.get("diagnose"):
        error = next((result[key] for key in (
            "error", "stop_error", "fetch_df0_error", "fetch_df1_error",
            "boot_log_error", "config_remove_error", "release_error")
            if result.get(key)), "")
        if not error and not result["success"]:
            error = f"diagnostic failed; see {path}"
    else:
        error = (result["error"] or result.get("specimen_error") or
                 result.get("release_error") or "")
    summary = {"success": result["success"], "error": error,
               "unguarded": result.get("unguarded", []),
               "summary": path}
    if result.get("release_error"):
        summary["release_error"] = result["release_error"]
    if result.get("error_cause"):
        summary["error_cause"] = result["error_cause"]
    if result.get("diagnose"):
        summary["remote_config_dirty"] = result.get("remote_config_dirty", False)
        if result.get("remote_config_path"):
            summary["remote_config_path"] = result["remote_config_path"]
        if result.get("config_remove_error"):
            summary["config_remove_error"] = result["config_remove_error"]
    return json.dumps(summary,
                      sort_keys=True)


def expect_verdict(title: AmigaTitle, manifest: pathlib.Path, attempt: str,
                   expect: tuple[str, int, int, int]) -> tuple[bool, str]:
    """Read the route's later slot off the run's fetched save disk and check `expect` against it.

    Re-opens `<manifest.parent>/<attempt>/fetched-<save_disk>.adf`, which
    `run_recon` writes for every attempt that reached the fetch step, and
    reads `title.after_letter` -- the camp-save slot the accept route writes
    after its walk. Refutes, naming why, when that file is missing or the
    slot holds no matching node. Returns `(accepted, verdict line)`.
    """
    fetched = manifest.parent / attempt / f"fetched-{title.save_disk}.adf"
    if not fetched.is_file():
        name, eid, minutes, _data = expect
        return False, f"expect {name} id {eid} at {minutes} minutes: refutes (no fetched save disk)"
    reading = title.read_slot(_verified_disk(fetched), title.after_letter)
    return check_expect(reading, expect)


def parse_route(text: str) -> tuple[tuple[str, str], ...]:
    """Read `KEY:state,KEY:state` into a route."""
    steps = []
    for part in text.split(","):
        key, sep, state = part.strip().partition(":")
        if not sep or not key or not state:
            raise RouteError(f"route step {part!r} is not KEY:state")
        steps.append((key.upper(), state))
    return tuple(steps)


def parse_write_keys(text: str) -> tuple[str, ...]:
    """Read `KEY,KEY` into upper-case write keys; an empty entry is an error."""
    keys = tuple(k.strip().upper() for k in text.split(","))
    if not all(keys):
        raise RouteError(f"write keys {text!r} contain an empty entry")
    return keys


def _record_numbers(text: str) -> list[int]:
    try:
        return [int(part) for part in text.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError("record numbers are comma-separated integers") from None


def parse_place(text: str) -> tuple[int, int, int]:
    """`X,Y,FACING`: a square of 0 to 15 each way and a facing of 0 to 3 (N E S W)."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 3 or not all(re.fullmatch(r"(0[xX][0-9a-fA-F]+|\d+)", p) for p in parts):
        raise RouteError(f"{text!r}: a place is X,Y,FACING (decimal or 0x hex)")
    x, y, facing = (int(p, 0) for p in parts)
    if not (0 <= x <= 15 and 0 <= y <= 15 and 0 <= facing <= 3):
        raise RouteError(f"{text!r}: x and y are 0 to 15, facing 0 to 3 (N E S W)")
    return x, y, facing


def _camp_steps(text: str, name: str) -> tuple[str, ...]:
    """`--camp`'s steps for title `name`, in their normal form."""
    return route_camp.normalise(route_camp.parse_steps(text, name))


EMULATORS = ("winuae", "fsuae")


def _guest_for(args: argparse.Namespace) -> Any:
    """The lane a command runs in: the Windows VM's WinUAE, or an FS-UAE in an instance-pool slot."""
    if getattr(args, "emulator", "winuae") == "winuae":
        return WinGuest()
    from tools.amiga import fsuaesession  # noqa: PLC0415

    return fsuaesession.FsuaeGuest(game=f"amiga-{args.title}",
                                   first_key_after=fsuaesession.FIRST_KEY_AFTER.get(args.title))


def _check_emulator(args: argparse.Namespace) -> None:
    """Stop an FS-UAE command that needs something only the WinUAE lane has, before any slot is claimed."""
    if getattr(args, "emulator", "winuae") != "fsuae":
        return
    if getattr(args, "wait_lane", 0) > 0:
        raise RouteError("--wait-lane waits for a WinUAE lane, so it needs --emulator winuae")
    if getattr(args, "rulebook_draws", None) is not None or getattr(args, "rulebook_records", None) is not None:
        raise RouteError("--rulebook-draws reads the game's memory through WinUAE's pipe, so it needs "
                         "--emulator winuae")
    if getattr(args, "journal_python", None):
        raise RouteError("the Silver Blades journal answerer has no FS-UAE route yet, so a Silver Blades "
                         "accept needs --emulator winuae")


def _draw_options(args: argparse.Namespace, holder: str) -> dict[str, Any]:
    """`run_recon`'s rulebook keywords, with the memory target only when there is more than one draw."""
    draws = getattr(args, "rulebook_draws", None)
    records = getattr(args, "rulebook_records", None)
    if records is not None and draws is None:
        raise RouteError("--rulebook-records goes with --rulebook-draws")
    if draws is None:
        return {}
    if draws < 2:
        return {"rulebook_draws": draws, **({} if records is None else {"rulebook_records": records})}
    from automap import amiga  # noqa: PLC0415

    pipe = amiga.WinuaePipe(holder=holder)
    return {"rulebook_draws": draws,
            **({} if records is None else {"rulebook_records": records}),
            "target": amiga.AmigaTarget(pipe, amiga.MACHINES["secret-of-the-silver-blades"]),
            "lane_check": lambda: pipe.drives(holder)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    choices = sorted((*TITLES, "ssb"))

    def common(p: argparse.ArgumentParser, emulator: bool = True) -> None:
        p.add_argument("--title", required=True, choices=choices)
        p.add_argument("--manifest", required=True, type=pathlib.Path)
        if emulator:
            p.add_argument("--emulator", choices=EMULATORS, default="winuae",
                           help="winuae runs in one of the Windows VM's WinUAE lanes; fsuae runs in an "
                                "instance-pool slot")
        p.add_argument("--audio-proof", type=pathlib.Path, default=None,
                       help="the Windows VM's audio mute proof; required with --emulator winuae "
                            "and not accepted with fsuae")
        p.add_argument("--attempt")
        p.add_argument("--holder", default=None)
        p.add_argument("--deadline", type=float, default=1800,
                       help="seconds for the whole run; the route gets this less "
                            "min(300, deadline/2), which is kept for cleanup")
        p.add_argument("--published-disk-one", action="store_true")
        p.add_argument("--wait-lane", type=float, default=0, metavar="SECONDS",
                       help="winuae only: keep asking for a lane for this long while every lane is "
                            "held, before --deadline starts counting (default 0, fail at once)")

    p = sub.add_parser("prepare", help="copy the registered images and the specimen into a run folder")
    p.add_argument("--title", required=True, choices=choices)
    p.add_argument("--run-id", required=True)
    p.add_argument("--published-disk-one", action="store_true")
    p.add_argument("--published-disk-three", action="store_true",
                   help="Pools of Darkness only: prepare from a disk 3 Save As wrote, or with "
                        "--title darkness-reload from the disk 3 such a run fetched")
    p.add_argument("--published-manifest", type=pathlib.Path, default=None,
                   help="darkness-reload with --published-disk-three: the published accept "
                        "run's prepare.json")
    p.add_argument("--saveas-report", type=pathlib.Path)
    p.add_argument("--camp", default="",
                   help="published Silver Blades and Curse, a Silver Blades --substitute, "
                        "Pools of Darkness or Pool of "
                        "Radiance: camp steps driven before the camp save, as "
                        "'view;heal;rest 1h' (view, view N, heal, heal N, rest DURATION, and "
                        "for Curse display; Pool takes items N, rest DURATION and display)")
    p.add_argument("--stage-place", default=None, metavar="X,Y,F",
                   help="published Silver Blades and Curse only: put the party on square X,Y "
                        "facing F (0 N, 1 E, 2 S, 3 W) in working DF0's loaded slot")
    p.add_argument("--source", type=pathlib.Path)
    p.add_argument("--staged-from", type=pathlib.Path)
    p.add_argument("--issue", help="the run folder's ticket: a number, or WISH-N; a published disk 3 "
                   "run files either under WISH-N")
    p.add_argument("--save-count", type=int, default=None,
                   help="Silver Blades only: a value for the private helper that stages the prepared slot")
    p.add_argument("--disk3", type=pathlib.Path, default=None,
                   help="darkness-reload only: the game-written disk 3 an accept run fetched")
    p.add_argument("--disk3-sha256", default=None, help="darkness-reload only: that disk's SHA-256")
    p.add_argument("--accept-summary", type=pathlib.Path, default=None,
                   help="darkness-reload only: that accept run's summary.json")
    p.add_argument("--substitute", type=pathlib.Path, default=None,
                   help="a disk holding a party some other tool wrote, such as a Save As "
                        "Amiga output, whose --substitute-letter slot replaces the route's "
                        "loaded slot; Pool, Curse, Pools of Darkness and Silver Blades accept "
                        "this, Silver Blades in place of --source")
    p.add_argument("--vault-pages", type=int, default=None,
                   help="darkness-vault only: stored-items pages the run turns to (default 2)")
    p.add_argument("--substitute-letter", default="A",
                   help="the slot to read off --substitute (default A)")
    m = sub.add_parser("measure", help="boot and press the route up to the first save; writes nothing")
    common(m)
    m.add_argument("--guards", type=pathlib.Path, default=None,
                   help="screen guard JSON; a route state it holds must match, and the boot waits for its title")
    m.add_argument("--route", help="Silver Blades only: KEY:state,KEY:state; default is the built-in route")
    m.add_argument("--write-keys", help="Silver Blades only: comma-separated keys that write; default B")
    a = sub.add_parser("accept", help="guarded load, sheet, two saves around a walk and the read-back")
    common(a)
    a.add_argument("--guards", required=True, type=pathlib.Path)
    a.add_argument("--identity", required=True, type=pathlib.Path)
    a.add_argument("--expect", default=None,
                   help="NAME:ID:MINUTES:DATA, checked against the route's later slot")
    a.add_argument("--journal-python")
    a.add_argument("--walk-retry", type=int, default=0, metavar="N",
                   help="snapshot before the first turn or move step, and on a screen the guard "
                        "does not match restore it and walk again, at most N times")
    a.add_argument("--rulebook-draws", type=int, default=None,
                   help=f"Silver Blades only: camp saves to make in this boot, 1 to {RULEBOOK_DRAWS_MAX}")
    a.add_argument("--rulebook-records", type=_record_numbers, default=None,
                   help="Silver Blades only: comma-separated rule-book record numbers, one per "
                        "camp save after the first, staged before each")
    a.add_argument("--preserve-specimen", action="store_true",
                   help="register and check a successful published, substituted or staged game's "
                        "fetched save disk before release; it follows the run's own success "
                        "verdict, not --expect")
    a.add_argument("--specimen-issue", default=None,
                   help="a substituted or staged --preserve-specimen: the issue the specimen is "
                        "for, as \"#N (title)\", \"WISH-N (title)\", or the link "
                        "planeread.py WISH-N --cite prints")
    r = sub.add_parser("reload", help="guarded load of a game-written slot and a check of the place "
                                      "on screen; writes nothing")
    common(r)
    r.add_argument("--guards", required=True, type=pathlib.Path)
    r.add_argument("--identity", required=True, type=pathlib.Path)
    d = sub.add_parser("diagnose", help="guarded title-only boot of the published Silver Blades image")
    common(d, emulator=False)
    d.set_defaults(deadline=600)
    d.add_argument("--guards", required=True, type=pathlib.Path)
    d.add_argument("--boot-limit", type=float, default=300)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        try:
            args.camp = _camp_steps(args.camp, args.title) if args.camp else ()
        except RouteError as exc:
            parser.error(f"argument --camp: {exc}")
    else:
        emulator = getattr(args, "emulator", "winuae")
        if emulator == "winuae" and args.audio_proof is None:
            parser.error("--audio-proof is required with --emulator winuae")
        if emulator == "fsuae" and args.audio_proof is not None:
            parser.error("--audio-proof belongs to --emulator winuae; an FS-UAE run proves its "
                         "silence from the emulator's own environment")
    try:
        silver_blades = args.title == "ssb"
        if args.command == "diagnose" and (not silver_blades or not args.published_disk_one
                                           or args.deadline > 600 or args.boot_limit > 300):
            raise RouteError("diagnose needs published Silver Blades and bounded limits")
        if args.command == "prepare" and args.published_disk_three:
            if args.published_disk_one:
                raise RouteError("--published-disk-one and --published-disk-three are two routes")
            if any((args.source, args.staged_from, args.substitute, args.stage_place,
                    args.save_count is not None)):
                raise RouteError("a published disk 3 takes only its Save As report")
            if args.title == "darkness":
                if args.saveas_report is None:
                    raise RouteError("a published disk 3 needs --saveas-report")
                if any((args.disk3, args.disk3_sha256, args.accept_summary,
                        args.published_manifest)):
                    raise RouteError("a published disk 3 takes only a Save As report")
                with terminating():
                    print(prepare_published_disk_three(
                        args.run_id, args.saveas_report, args.issue or ISSUE, camp=args.camp))
                return 0
            if args.title == "darkness-reload":
                if args.saveas_report is not None or args.camp:
                    raise RouteError("a published disk 3 reload takes no Save As report or camp steps")
                if not all((args.disk3, args.disk3_sha256, args.accept_summary,
                            args.published_manifest)):
                    raise RouteError("a published disk 3 reload needs --published-manifest, "
                                     "--disk3, --disk3-sha256 and --accept-summary")
                with terminating():
                    print(prepare_published_disk_three_reload(
                        args.run_id, args.published_manifest, args.disk3, args.disk3_sha256,
                        args.accept_summary, args.issue))
                return 0
            raise RouteError("--published-disk-three is for Pools of Darkness only")
        if args.command == "prepare" and args.published_manifest is not None:
            raise RouteError("--published-manifest requires --published-disk-three")
        if args.published_disk_one:
            if args.command == "reload":
                raise RouteError("published disk one has no reload route")
            if args.command == "prepare":
                if args.saveas_report is None:
                    raise RouteError("published disk one needs --saveas-report")
                place = parse_place(args.stage_place) if args.stage_place is not None else None
                if any((args.source, args.staged_from, args.disk3,
                        args.disk3_sha256, args.accept_summary, args.substitute,
                        args.save_count is not None)):
                    raise RouteError("published disk one takes only a Save As report")
                print(prepare_published(args.title, args.run_id, args.saveas_report,
                                        args.issue or PUBLISHED_ISSUE, camp=args.camp, place=place))
                return 0
            if args.title not in PUBLISHED_DISKS:
                raise RouteError("published disk one is only for Curse and Silver Blades")
            if args.command == "measure" and (args.route or args.write_keys):
                raise RouteError("published disk one uses its source-specific route")
        elif args.command == "prepare" and args.saveas_report is not None:
            raise RouteError("--saveas-report requires --published-disk-one or "
                             "--published-disk-three")
        elif (args.command == "prepare" and args.camp and args.title not in CAMP_TITLES
              and not (silver_blades and args.substitute is not None)):
            raise RouteError("--camp requires --published-disk-one, --title darkness or "
                             "--title pool; --title ssb also takes it with --substitute")
        elif args.command == "prepare" and args.stage_place is not None:
            raise RouteError("--stage-place requires --published-disk-one")
        if args.command == "reload" and silver_blades:
            raise RouteError("Silver Blades has no reload route")
        if args.title == "darkness-unstarted" and args.command in ("accept", "reload"):
            raise RouteError("darkness-unstarted only measures: its route has no write step "
                             "and no walk")
        if args.command == "prepare":
            if silver_blades:
                if (args.source is None) == (args.substitute is None):
                    raise RouteError("Silver Blades prepare requires --source or --substitute")
                if args.substitute is not None and (
                        args.staged_from is not None or args.save_count is not None):
                    raise RouteError("--staged-from and --save-count go with --source, not "
                                     "--substitute")
                if args.source is not None and args.substitute_letter != "A":
                    raise RouteError("--substitute-letter goes with --substitute")
                if (args.disk3 is not None or args.disk3_sha256 is not None
                        or args.accept_summary is not None):
                    raise RouteError("Silver Blades prepare takes no title-only options")
            elif (args.source is not None or args.staged_from is not None
                  or args.save_count is not None):
                raise RouteError("--source, --staged-from and --save-count require --title ssb")
        elif not silver_blades and args.attempt is None:
            raise RouteError("--attempt is required for this title")
        if (args.command == "measure" and not silver_blades
                and (args.route is not None or args.write_keys is not None)):
            raise RouteError("--route and --write-keys require --title ssb")
        if args.command == "accept":
            if silver_blades and args.journal_python is None:
                raise RouteError("Silver Blades accept requires --journal-python")
            if not silver_blades and args.journal_python is not None:
                raise RouteError("--journal-python requires --title ssb")
            if ((args.rulebook_draws is not None or args.rulebook_records is not None)
                    and (not silver_blades or args.published_disk_one)):
                raise RouteError("--rulebook-draws requires --title ssb without "
                                 "--published-disk-one")
        expect = parse_expect(args.expect) if getattr(args, "expect", None) else None
        _check_emulator(args)
        with terminating():
            if args.command == "prepare":
                if silver_blades and args.substitute is not None:
                    print(route_silver_blades.prepare_substitute(
                        args.substitute, args.run_id, letter=args.substitute_letter,
                        issue=args.issue or "672",
                        **({"camp": args.camp} if args.camp else {})))
                    return 0
                if silver_blades:
                    print(route_silver_blades.prepare(
                        args.source, args.run_id, staged_from=args.staged_from,
                        issue=args.issue or "672",
                        **({} if args.save_count is None else {"save_count": args.save_count})))
                    return 0
                print(prepare(TITLES[args.title], args.run_id, specimen=args.disk3,
                              specimen_sha256=args.disk3_sha256,
                              accept_summary=args.accept_summary,
                              substitute=args.substitute,
                              substitute_letter=args.substitute_letter,
                              camp=args.camp, issue=args.issue,
                              vault_pages=args.vault_pages))
                return 0
            if args.published_disk_one:
                manifest, title = _published_manifest(args.manifest, args.title)
            else:
                title = None if silver_blades else TITLES[args.title]
                if args.title == "darkness-vault":
                    title = _vault_title_for(args.manifest)
                if args.title in ("darkness", "darkness-reload"):
                    title = published_darkness_title(args.manifest, args.title) or title
            # A Silver Blades substitute prepared with camp steps, or whose party has not set out,
            # runs as a title; any other Silver Blades manifest runs the legacy route.
            substituted = bool(silver_blades and not args.published_disk_one
                               and _substitute_mode(args.manifest))
            if substituted:
                if args.command == "measure" and (args.route or args.write_keys):
                    raise RouteError("a substitute prepared as a title run uses its own route")
                title = route_silver_blades.title_for_substitute(json.loads(args.manifest.read_text()))
            legacy = silver_blades and not args.published_disk_one and not substituted
            attempt = args.attempt or ("recon1" if args.command == "measure" else
                                       "gfx705-directdraw1" if args.command == "diagnose" else
                                       "accept1")
            holder_issue = manifest.get("issue", PUBLISHED_ISSUE) if args.published_disk_one else (
                "672" if silver_blades else ISSUE)
            holder = args.holder or f"wish{holder_issue}-{uuid.uuid4().hex[:12]}"
            if args.command == "diagnose":
                result = run_recon(
                    args.manifest, guest=WinGuest(), holder=holder,
                    audio_proof=args.audio_proof, attempt=attempt,
                    guard=PixelGuards(args.guards), deadline_seconds=args.deadline,
                    boot_limit=args.boot_limit, diagnose=True, title=title,
                    wait_lane=args.wait_lane,
                    published_disk_one=True, published_name=args.title)
            elif args.command == "measure":
                route = (parse_route(args.route) if args.route else route_silver_blades.ROUTE)
                write_keys = parse_write_keys(
                    args.write_keys if args.write_keys is not None else "B") if legacy else None
                result = run_recon(
                    args.manifest, guest=_guest_for(args), holder=holder,
                    audio_proof=args.audio_proof, attempt=attempt,
                    guard=PixelGuards(args.guards) if args.guards else None,
                    deadline_seconds=args.deadline, measure=True, title=title,
                    wait_lane=args.wait_lane,
                    published_disk_one=args.published_disk_one,
                    published_name=args.title if args.published_disk_one else None,
                    **({"route": route,
                        "write_keys": write_keys,
                        "min_waits": route_silver_blades.default_min_waits(route)}
                       if legacy else {}))
            else:
                result = run_recon(
                    args.manifest, guest=_guest_for(args), guard=PixelGuards(args.guards),
                    identity=PixelGuards(args.identity), holder=holder,
                    audio_proof=args.audio_proof, attempt=attempt,
                    deadline_seconds=args.deadline, title=title, wait_lane=args.wait_lane,
                    published_disk_one=args.published_disk_one,
                    published_name=args.title if args.published_disk_one else None,
                    journal_python=getattr(args, "journal_python", None),
                    walk_retry=getattr(args, "walk_retry", 0),
                    **_draw_options(args, holder),
                    preserve_specimen=getattr(args, "preserve_specimen", False),
                    specimen_issue=getattr(args, "specimen_issue", None),
                    **({"accept": True,
                        "min_waits": {**route_silver_blades.default_min_waits(),
                                      **route_silver_blades.ACCEPT_MIN_WAITS}}
                       if legacy else
                       {"reload" if args.command == "reload" else "accept": True}))
            if silver_blades and args.command == "measure":
                measured = {"success": result["success"], "error": result["error"],
                            "summary": str(args.manifest.parent / attempt / "summary.json")}
                if result.get("error_cause"):
                    measured["error_cause"] = result["error_cause"]
                print(json.dumps(measured, sort_keys=True))
            else:
                print(_summary(result, args.manifest, attempt))
            for line in result.get("read", {}).get("verdicts", []):
                print(line)
            success = result["success"]
            if args.command == "accept" and expect is not None:
                if legacy:
                    accepted, line = route_silver_blades.expect_verdict(
                        args.manifest, attempt, expect)
                else:
                    try:
                        judged = title if args.published_disk_one else accept_title(
                            title, json.loads(args.manifest.read_text()))
                    except RouteError as exc:
                        name, eid, minutes, _data = expect
                        accepted, line = False, (
                            f"expect {name} id {eid} at {minutes} minutes: refutes (the "
                            f"route this manifest names cannot be built: {exc})")
                    else:
                        accepted, line = expect_verdict(judged, args.manifest, attempt, expect)
                print(line)
                success = success and accepted
            return 0 if success else 1
    except (RouteError, OSError, ValueError) as exc:
        print(f"acceptance: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
