"""Pool of Radiance: pins, readers and the description of its load, save and read-back route."""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import re
from collections.abc import Callable
from typing import Any

from goldbox import amiga_adf, amiga_por, amiga_savegame, areas, geo
from goldbox.geo import load_geo_files
from tools.amiga import amigaporslot
from tools.amiga.route import ISSUE, AmigaTitle, RouteError, effect_fields
from tools.amiga.staging import _prepare_from, _Sources

POOL_DISK1_SHA256 = "6ad445f5715d021d560ddcf003e78153003315af016a19dbc4b56d55d3019d4c"
POOL_DISK2_SHA256 = "4c9d42c8880e94827b7e0e886aed1ad7884c83ed90d8495ac83bc53ab908c6ca"
POOL_SPECIMEN_SHA256 = "20ef29b226180a9544efb47aa14f6ec26675f115efd765b6138716b23a81d77b"
POOL_SPECIMEN = ("por-amiga", "WISH-SPEC-por-52-c64toamiga-walk-resave",
                 "pulled-after-stop.adf")
POOL_VOLUME = "POOLSAVE"
POOL_LOADED = "A"
# The specimen's own camp save, made after the same about-face and one step.
POOL_LATER = "B"

_POOL_SAVED_GAME = re.compile(r"savgam([A-Z])\.dat", re.IGNORECASE)


def _pool_name(name: str) -> str:
    """A member's name as the game saves it: the specimen's own slot B drops the space that slot A keeps."""
    return name.replace(" ", "")


# The DOS `read_slot` keys, each at its DOS Pool record offset: the Amiga record
# is read through `amiga_por_offset`, never at a copied number.
_POOL_MEMBER_BYTES = (("control", 0x084), ("treasure_share", 0x085), ("creature_type", 0x09F),
                      ("turn_class", 0x076), ("movement", 0x072))
_POOL_STATUS_BYTES = 0x10C
#: The seven two-byte big-endian coin counts, each at its DOS offset (`dos_port`'s copper to
#: jewelry, 0x088-0x094); gold is the field `staging.POR_STAGE_FIELDS` writes.
_POOL_COINS = (("copper", 0x088), ("silver", 0x08A), ("electrum", 0x08C), ("gold", 0x08E),
               ("platinum", 0x090), ("gems", 0x092), ("jewelry", 0x094))


def _pool_member_bytes(raw: bytes) -> dict[str, Any]:
    """The status, control, treasure share, creature type, turn class, movement, gold and coins of one Amiga record."""
    at = amiga_por.amiga_por_offset(_POOL_STATUS_BYTES)
    reading: dict[str, Any] = {"status_bytes": list(raw[at:at + 4])}
    for key, dos_offset in _POOL_MEMBER_BYTES:
        reading[key] = raw[amiga_por.amiga_por_offset(dos_offset)]
    money = {}
    for coin, dos_offset in _POOL_COINS:
        coin_at = amiga_por.amiga_por_offset(dos_offset)
        money[coin] = int.from_bytes(raw[coin_at:coin_at + 2], "big")
    reading["gold"] = money["gold"]
    reading["money"] = money
    return reading


def _pool_read_slot(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, Any]:
    """One Pool save slot in the root of a fetched POOLSAVE disk: `missing`, `decode_error`, or place and names."""
    try:
        raw = disk.read_file(f"/savgam{letter}.dat")
    except amiga_adf.AmigaDiskError:
        return {"missing": True, "sha256": None}
    reading: dict[str, Any] = {"sha256": hashlib.sha256(raw).hexdigest()}
    try:
        party, save = amiga_savegame.read_por_slot(disk, letter, drawer="")
        state = amiga_savegame.por_state_from_amiga(save)
        names = [_pool_name(member.name) for member in party]
        place = {"area": state.area, "x": state.x, "y": state.y, "facing": state.facing}
        characters = amiga_savegame.read_por_characters(disk, letter, drawer="")
        effects = {_pool_name(char.name): [list(effect_fields(node)) for node in char.effects]
                  for char in characters}
        members = [{"name": _pool_name(char.name), **_pool_member_bytes(char.raw)}
                   for char in characters]
    except Exception as exc:  # noqa: BLE001 - every reader failure is the verdict's `decode_error`
        reading["decode_error"] = f"{type(exc).__name__}: {exc}"
        return reading
    reading["names"] = names
    reading["place"] = place
    reading["effects"] = effects
    reading["members"] = members
    return reading


def _pool_slot_letters(disk: amiga_adf.AmigaDisk) -> list[str]:
    letters = []
    for entry in disk.entries():
        found = _POOL_SAVED_GAME.fullmatch(entry.name)
        if found and not entry.is_dir:
            letters.append(found.group(1).upper())
    return sorted(letters)


def _pool_slot_files(disk: amiga_adf.AmigaDisk, letter: str) -> dict[str, bytes]:
    """The slot's saved game and its character, item and effect files, which a later save must leave alone."""
    mine = re.compile(rf"(savgam{letter}\.dat|CHRDAT{letter}[0-9]\.(sav|itm|spc))",
                      re.IGNORECASE)
    return {entry.name: disk.read_file(f"/{entry.name}")
            for entry in disk.entries() if not entry.is_dir and mine.fullmatch(entry.name)}


#: Pages of `PRESS <RETURN> OR BUTTON TO CONTINUE` answered while waiting for the map: the
#: eight of Rolf's opening tour, which a party that has not taken it meets after the load, and
#: two more, so that a page that never turns still stops the run.
POOL_CONTINUE_PAGES = 10
#: Where Rolf's tour leaves the party: the DOS game's own save after it reads area 0, 0,4
#: facing west, as the C64 game's does.
POOL_TOUR_END = {"area": 0, "x": 0, "y": 4, "facing": geo.WEST}

# Section 3 of the plan for Pool of Radiance. `RET` at the first screen is the
# `wheel` interstitial below, which takes RETURN on this image. No route step
# presses RET after C or D, and none presses Y.
_POOL_LOAD = (
    ("RET", "party_menu", "key"), ("L", "save_path", "key"), ("RET", "load_picker", "key"),
    ("A", "world", "key"), ("V", "sheet", "key"), ("E", "world", "key"),
)
POOL = AmigaTitle(
    issue=ISSUE,
    mounted=("disk1", "disk2", "save"),
    options=("nr_floppies=3", "floppy2type=0"),
    save_disk="save",
    read_slot=_pool_read_slot, slot_letters=_pool_slot_letters, slot_files=_pool_slot_files,
    route=(
        *_POOL_LOAD,
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("C", "quit_prompt", "write"), ("N", "camp", "key"),
        ("E", "world", "key"), ("NP2", "world", "turn"), ("NP8", "world", "move"),
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("D", "quit_prompt", "write"), ("N", "camp", "key"),
    ),
    # Stops before C, at the camp's save picker.
    measure_route=(
        ("RET", "title", "key"), ("RET", "party_menu", "key"), ("L", "save_path", "key"),
        ("RET", "load_picker", "key"), ("A", "world", "key"), ("V", "sheet", "key"),
        ("E", "world", "key"), ("NP2", "world", "turn"), ("NP8", "world", "move"),
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
    ),
    boot_span=150.0,
    # The title wait runs twice: from the start to the code wheel, while the AmigaDOS window
    # shows `type mes` and `program` loads, and from the wheel's RETURN through the intro
    # pages to the title. No key shortens the first, and the driver presses none in the
    # second. On a loaded VM the first took more than 182 s
    # and the second more than 186 s, where most boots take under 110 s for each.
    title_limit=300.0,
    control_letter="C", after_letter="D", kept_letters=(POOL_LATER,), turn="about",
    strict=frozenset({"party_menu", "load_picker", "sheet", "world", "camp_save_picker"}),
    min_waits={"party_menu": 20.0, "load_picker": 10.0, "world": 20.0,
               "world_after_move": 5.0, "camp": 10.0, "camp_save_picker": 10.0,
               "quit_prompt": 20.0},
    interstitials=(
        ("wheel", ("keys", "RET"), frozenset({"title"}), 1),
        ("save_path", ("keys", "RET"), frozenset({"camp_save_picker"}), 1),
    ),
    # ECL14 $994F-$995D: COMPARE [$C04D], 1 then NEWECL 0, with no write to the party's square,
    # so a step east off the Slums lands in New Phlan on the wrapped square, still facing east.
    edge_exits={(20, geo.EAST): 0},
)


_ABOUT_STEP = ("NP2", "world", "turn")


def _without_turn(route: tuple) -> tuple:
    return tuple(step for step in route if step != _ABOUT_STEP)


#: The same route for a party that walks out the way it faces, with no turn about.
POOL_FORWARD = dataclasses.replace(
    POOL, route=_without_turn(POOL.route), measure_route=_without_turn(POOL.measure_route),
    turn=None)

#: RETURN on a `PRESS <RETURN> OR BUTTON TO CONTINUE` page while waiting for the map, for a
#: manifest whose party meets Rolf's tour; no other run presses it, so a page met anywhere
#: else stops the run rather than being answered.
_TOUR_CONTINUE = ("continue", ("keys", "RET"), frozenset({"world"}), POOL_CONTINUE_PAGES)


def _with_tour(title: AmigaTitle) -> AmigaTitle:
    return dataclasses.replace(title, interstitials=(*title.interstitials, _TOUR_CONTINUE))


#: `POOL` and `POOL_FORWARD` for a party that plays Rolf's tour before the map.
POOL_TOUR = _with_tour(POOL)
POOL_FORWARD_TOUR = _with_tour(POOL_FORWARD)


#: The after slot of a Pool camp run whose camp steps press `D`, which is the rest menu's days
#: field and the magic menu's Display: a slot letter is pressed only to save it.
POOL_CAMP_AFTER = "F"


def pool_camp_title(title: AmigaTitle, keys: tuple[str, ...]) -> AmigaTitle:
    """`title` (a Pool route) saving its after slot to `POOL_CAMP_AFTER` when `keys` press its after letter.

    `keys` are the keys the run's camp steps press. Any other route is returned as it is.
    """
    if title.after_letter not in {key.upper() for key in keys}:
        return title
    route = tuple((POOL_CAMP_AFTER, state, kind)
                  if kind == "write" and key == title.after_letter else (key, state, kind)
                  for key, state, kind in title.route)
    return dataclasses.replace(title, route=route, after_letter=POOL_CAMP_AFTER)


def _walkable(walls: geo.Geo, x: int, y: int, direction: int) -> bool:
    """No wall on the edge, or a door standing open; a solid wall and a locked door are not."""
    return (walls.wall(x, y, direction) == 0
            or walls.barrier(x, y, direction) == geo.PASSABLE)


def _disk_geo(name: str) -> geo.Geo:
    from automap.paths import (
        tool_disks,  # noqa: PLC0415 - the player's disks, only when asked
    )
    from tools.areas import geomap  # noqa: PLC0415
    root = tool_disks()
    if root is None:
        raise RouteError(f"the game disks are not found, so the wall data {name} cannot be read "
                         "and the route's step cannot be checked")
    for path in geomap.game_disks(root):
        found = load_geo_files(path)
        if name in found:
            return found[name]
    raise RouteError(f"the wall data {name} is not on the game disks, so the route's "
                     "step cannot be checked")


def pool_turns_about(place: dict, *,
                     load_geo: Callable[[str], geo.Geo] | None = None) -> bool:
    """Whether the route turns the party about before its one step, from the start square's own walls.

    The route turns about unless that edge is closed and the edge the party
    faces is open. An area with more than one map cannot say which the game
    loaded, so it keeps the turn about.
    """
    try:
        number, x, y, facing = place["area"], place["x"], place["y"], place["facing"]
    except (KeyError, TypeError) as exc:
        raise RouteError(f"the recorded place {place!r} lacks an area, x, y or facing") from exc
    area = areas.area_in(number, areas.POOL_OF_RADIANCE)
    if area is None or area.geo is None:
        return True
    walls = (load_geo or _disk_geo)(area.geo)
    if _walkable(walls, x, y, geo.OPPOSITE[facing]):
        return True
    if _walkable(walls, x, y, facing):
        return False
    raise RouteError(f"area {place['area']} ({x},{y}) has no open edge ahead or behind "
                     f"facing {facing}, so the route has no step to take")


def pool_title_for(manifest: dict, *,
                   load_geo: Callable[[str], geo.Geo] | None = None) -> AmigaTitle:
    """The route this manifest's start square needs, blocking a recorded `turn_about` its walls contradict.

    A manifest with no `turn_about` predates the choice and keeps the turn about. An
    `opening_tour` manifest gets the route that answers the tour's pages, and must start at
    `POOL_TOUR_END`.
    """
    tour = manifest.get("opening_tour", False)
    if not isinstance(tour, bool):
        raise RouteError("the manifest opening_tour is not a boolean")
    if tour and manifest.get("state_a") != POOL_TOUR_END:
        raise RouteError("the manifest opening_tour disagrees with its recorded place")
    if "turn_about" not in manifest:
        if tour:
            raise RouteError("the manifest has an opening_tour but no turn_about")
        return POOL
    turn_about = manifest["turn_about"]
    if not isinstance(turn_about, bool):
        raise RouteError("the manifest turn_about is not a boolean")
    if "state_a" not in manifest:
        raise RouteError("the manifest has a turn_about but no state_a to check it against")
    if turn_about != pool_turns_about(manifest["state_a"], load_geo=load_geo):
        raise RouteError("the manifest turn_about disagrees with its recorded place")
    if tour:
        return POOL_TOUR if turn_about else POOL_FORWARD_TOUR
    return POOL if turn_about else POOL_FORWARD


#: Where the temple walk starts: the Slums square a converted WISH-303 party stands on, the C64
#: temple route's first square.
POOL_TEMPLE_START = {"area": 20, "x": 15, "y": 4, "facing": geo.WEST}
#: Where the party stands after the raise, read from the game-written slot D of the measured run:
#: the temple's square in New Phlan, facing north.
POOL_TEMPLE_SQUARE = {"area": 0, "x": 1, "y": 3, "facing": geo.NORTH}
#: The temple's price for RAISE DEAD, read on its price screen (`temple_price`'s guard holds it).
POOL_RAISE_PRICE = 5500
#: The service list's rows above RAISE DEAD, each one `NP2` down from CURE BLINDNESS.
_RAISE_ROW = 6
#: Right, right, east into New Phlan, east, left, north onto the temple: `NP6` turns right and
#: `NP4` left (measured), `NP8` steps.
_TEMPLE_WALK = (
    ("NP6", "world", "turn"), ("NP6", "world", "turn"), ("NP8", "world", "move"),
    ("NP8", "world", "move"), ("NP4", "world", "turn"), ("NP8", "temple_greeting", "move"),
)
#: YES to the greeting, HEAL on the bar, down to RAISE DEAD, HEAL buys it, YES pays, EXIT the list
#: and EXIT the temple. The list after YES shows RAISE DEAD highlighted, as before HEAL.
_TEMPLE_RAISE = (
    ("Y", "temple", "key"), ("H", "temple_services", "key"),
    *((("NP2", "temple_services", "key"),) * (_RAISE_ROW - 1)),
    ("NP2", "temple_raise_row", "key"), ("H", "temple_price", "key"),
    ("Y", "temple_raise_row", "key"), ("E", "temple", "key"), ("E", "world", "key"),
)
_TEMPLE_STATES = frozenset({"temple_greeting", "temple", "temple_services", "temple_raise_row",
                            "temple_price"})
_CAMP_SAVE = (("E", "camp", "key"), ("S", "camp_save_picker", "key"))

#: Pool's accept route for a party standing on `POOL_TEMPLE_START` whose first member is dead: the
#: load and sheet, camp save C before any move, the walk to the temple, RAISE DEAD for the first
#: member (the one the temple serves), the sheet again, and camp save D.
POOL_TEMPLE = dataclasses.replace(
    POOL,
    route=(
        *_POOL_LOAD, *_CAMP_SAVE, ("C", "quit_prompt", "write"), ("N", "camp", "key"),
        ("E", "world", "key"), *_TEMPLE_WALK, *_TEMPLE_RAISE,
        ("V", "sheet", "key"), ("E", "world", "key"),
        *_CAMP_SAVE, ("D", "quit_prompt", "write"), ("N", "camp", "key"),
    ),
    measure_route=(
        ("RET", "title", "key"), *_POOL_LOAD, *_TEMPLE_WALK, *_TEMPLE_RAISE,
        ("V", "sheet", "key"), ("E", "world", "key"), *_CAMP_SAVE,
    ),
    turn=None, strict=POOL.strict | _TEMPLE_STATES)


def pool_temple_title(manifest: dict) -> AmigaTitle:
    """`POOL_TEMPLE`, blocked for a manifest whose party does not start where its walk does."""
    if manifest.get("state_a") != POOL_TEMPLE_START:
        raise RouteError(f"the temple walk starts at {POOL_TEMPLE_START}, not at "
                         f"{manifest.get('state_a')}")
    return POOL_TEMPLE


#: Each coin's value in copper pieces: platinum 5 gold, gold 20 silver, electrum half a gold.
#: Two raises fit it: 6,000 gold paid 5,500 and got 100 platinum back, and 6,000 gold with 102
#: silver got 101 platinum and no silver, where only 17 to 20 silver to the gold makes 505.
COPPER_PER = {"copper": 1, "silver": 10, "electrum": 100, "gold": 200, "platinum": 1000}
#: Gems and jewelry, which a payment does not count and left alone in both raises.
_COINS_KEPT = ("gems", "jewelry")


def purse_in_gold(money: dict[str, int]) -> int:
    """A purse's coins in whole gold pieces, rounded down, as the temple counts them."""
    return sum(money[coin] * per for coin, per in COPPER_PER.items()) // COPPER_PER["gold"]


def temple_payment(b: dict[str, Any], d: dict[str, Any], member: str, *,
                   staged_gold: int) -> tuple[bool, str]:
    """Whether `member` paid `POOL_RAISE_PRICE` between slot readings `b` and `d`, and why not.

    The game counts the payer's own coins in whole gold pieces (`purse_in_gold`), takes the price,
    and writes the change back as platinum, so the part of a gold piece below the change is
    lost (two raises measured). Paid means: slot `b` holds `staged_gold` gold, his coins in gold
    fell by exactly the price, his gems and jewelry did not change, and no other member's purse
    did. A purse with copper or electrum, or with silver other than the 0 or 102 measured, fails
    because the temple's rate for those coins is not known.
    """
    def purses(reading: dict[str, Any]) -> dict[str, dict[str, int] | None]:
        return {m.get("name"): m.get("money") for m in reading.get("members", [])}

    before, after = purses(b), purses(d)
    mine_before, mine_after = before.get(member), after.get(member)
    if mine_before is None or mine_after is None:
        return False, f"{member}'s purse was not read in both slots"
    if mine_before["gold"] != staged_gold:
        return False, f"{member} held {mine_before['gold']} gold before, not the staged {staged_gold}"
    for coin, measured in (("copper", (0,)), ("electrum", (0,)), ("silver", (0, 102))):
        if mine_before[coin] not in measured:
            return False, f"the temple's rate for {coin} is not measured"
    held_before, held_after = purse_in_gold(mine_before), purse_in_gold(mine_after)
    coins = ", ".join(f"{coin} {mine_after[coin]}" for coin in COPPER_PER if mine_after[coin])
    if held_before - held_after != POOL_RAISE_PRICE:
        return False, (f"{member} held {held_before} gold in coins and then {held_after} "
                       f"({coins or 'no coins'}), expected {held_before - POOL_RAISE_PRICE} "
                       f"after paying {POOL_RAISE_PRICE}")
    moved = [coin for coin in _COINS_KEPT if mine_before[coin] != mine_after[coin]]
    if moved:
        return False, f"{member}'s {', '.join(moved)} changed"
    others = sorted(name for name in set(before) | set(after)
                    if name != member and before.get(name) != after.get(name))
    if others:
        return False, f"the purse of {', '.join(others)} changed"
    return True, f"{member} paid {POOL_RAISE_PRICE} and holds {coins or 'no coins'}"


def temple_verdict(before: dict, b: dict[str, Any], d: dict[str, Any], member: str, *,
                   staged_gold: int, control: str = "C", after: str = "D") -> dict[str, Any]:
    """Judge a temple run's saves: `control` unmoved at `before`; `after` on the temple square with `member` raised.

    Raised is what the game writes for a living character: status byte 0, a control byte below
    `$80` (the player's), no effect node 32, and the temple paid (`temple_payment`) out of the
    `staged_gold` he held in slot `control`. The keys match `walk_verdict`'s, so the run's
    other checks read it the same way.
    """
    verdicts: list[str] = []
    b_place, d_place = b.get("place"), d.get("place")
    b_ok = b_place == before
    verdicts.append(f"slot {control}: " + ("did not move" if b_ok else
                    "was not read" if b_place is None else
                    f"stands at {b_place}, expected {before}"))
    d_ok = False
    raised = None
    if d_place is None:
        verdicts.append(f"slot {after}: was not read")
    else:
        rows = [m for m in d.get("members", []) if m.get("name") == member]
        if len(rows) != 1:
            verdicts.append(f"slot {after}: holds {len(rows)} members named {member}")
        else:
            row = rows[0]
            nodes = [n for n in (d.get("effects") or {}).get(member, []) if n and n[0] == 32]
            paid, payment = temple_payment(b, d, member, staged_gold=staged_gold)
            raised = {"status": row["status_bytes"][0], "control": row["control"],
                      "node_32": bool(nodes), "gold": row.get("gold"),
                      "platinum": (row.get("money") or {}).get("platinum"), "paid": paid}
            alive = (raised["status"] == 0 and raised["control"] < 0x80 and not nodes
                     and paid)
            at_temple = d_place == POOL_TEMPLE_SQUARE
            d_ok = alive and at_temple
            verdicts.append(
                f"slot {after}: " + ("at the temple" if at_temple else
                                     f"stands at {d_place}, not the temple {POOL_TEMPLE_SQUARE}")
                + f"; {member} " + ("raised" if alive else
                                    f"not raised (status {raised['status']}, control "
                                    f"{raised['control']:#04x}, node 32 {raised['node_32']})")
                + f"; {payment}")
    return {"verdicts": verdicts, "b_ok": b_ok, "d_ok": d_ok, "walk_blocked": False,
            "walk_partial": False, "squares_requested": sum(
                1 for *_, kind in _TEMPLE_WALK if kind == "move"),
            "place_changed": None if d_place is None else d_place != before,
            "squares_moved": None,
            "area_crossed": None if d_place is None or b_place is None
            or d_place["area"] == b_place["area"]
            else {"from": b_place["area"], "to": d_place["area"]},
            "raised": raised}


#: The longest walk `POOL_ENCOUNTER` takes before it gives up: steps pressed, not squares gained.
ENCOUNTER_MOVES = 40
#: NP8 steps; a step that leaves the world screen as it was met a wall, and `NP4` turns left.
#: A right turn on the first wall west of `POOL_TEMPLE_START` walks the party back east into New
#: Phlan, where it meets no random encounter (measured), so the walk turns left.
ENCOUNTER_STEP = ("NP8", "NP4", ENCOUNTER_MOVES)

#: RETURN on `YOU ARE SURPRISED BY ...` over a `PRESS <RETURN>` bar, met in place of the
#: encounter menu when the monsters surprise the party; the fight opens without the menu, so the
#: walk then finds the first command bar itself and COMBAT is never pressed.
_SURPRISED = ("surprised", ("keys", "RET"), frozenset({"encounter"}), 1)

#: Pool's first-bar run: the load and sheet, a walk until the encounter menu, COMBAT, and the
#: first command bar, whose crop is the battlefield. It saves nothing.
POOL_ENCOUNTER = dataclasses.replace(
    POOL,
    route=(*_POOL_LOAD, (ENCOUNTER_STEP, "encounter", "until_encounter"),
           ("C", "combat_bar", "key")),
    measure_route=(("RET", "title", "key"), *_POOL_LOAD,
                   (ENCOUNTER_STEP, "encounter", "until_encounter"), ("C", "combat_bar", "key")),
    interstitials=(*POOL.interstitials, _SURPRISED),
    control_letter=None, after_letter=None, turn=None,
    strict=POOL.strict | {"encounter", "combat_bar"},
    min_waits={**POOL.min_waits, "combat_bar": 5.0})

#: Out of the temple for a party saved on `POOL_TEMPLE_SQUARE`: a step north re-enters the temple
#: and its greeting (measured), so turn about, step south through the door the party came in by,
#: and turn right to face west, where `ENCOUNTER_STEP` walks back towards the Slums.
_TEMPLE_LEAVE = (_ABOUT_STEP, ("NP8", "world", "move"), ("NP6", "world", "turn"))

#: `POOL_ENCOUNTER` for a party saved at the temple after its raise.
POOL_ENCOUNTER_FROM_TEMPLE = dataclasses.replace(
    POOL_ENCOUNTER,
    route=(*_POOL_LOAD, *_TEMPLE_LEAVE, *POOL_ENCOUNTER.route[len(_POOL_LOAD):]),
    measure_route=(("RET", "title", "key"), *_POOL_LOAD, *_TEMPLE_LEAVE,
                   *POOL_ENCOUNTER.measure_route[1 + len(_POOL_LOAD):]))


def pool_encounter_title(manifest: dict) -> AmigaTitle:
    """The fight route for `manifest`'s start square: out of the temple first when the party stands there."""
    if manifest.get("state_a") == POOL_TEMPLE_SQUARE:
        return POOL_ENCOUNTER_FROM_TEMPLE
    return POOL_ENCOUNTER


POOL_SOURCES = _Sources("pool", POOL, POOL_SPECIMEN, POOL_SPECIMEN_SHA256, POOL_VOLUME,
                        POOL_LOADED, POOL_LATER,
                        {"disk1": POOL_DISK1_SHA256, "disk2": POOL_DISK2_SHA256},
                        amigaporslot.import_slot)


def _pool_loaded_clock(manifest: dict) -> tuple[int, ...]:
    """The clock digits of the slot the run loads, read from the prepared save disk."""
    disk = amiga_adf.AmigaDisk.open(pathlib.Path(manifest["disks"]["save"]["path"]))
    raw = disk.read_file(f"/savgam{manifest['loaded_letter']}.dat")
    return tuple(amiga_savegame.por_state_from_amiga(raw).clock)


def _tour_pending(manifest: dict) -> bool:
    """Whether the loaded party stands on New Phlan's arrival square at clock zero, so the game plays Rolf's tour.

    Untested for a never-played slot whose party has already taken the tour, such as a
    converted save: the game would show no tour, the menu save would stand on the arrival
    square rather than `POOL_TOUR_END`, and the place check would fail the run rather than
    pass it wrongly.
    """
    start = areas.start_of(areas.POOL_OF_RADIANCE)
    arrival = {"area": start.area, "x": start.arrival.x, "y": start.arrival.y,
               "facing": start.arrival.facing}
    return manifest["state_a"] == arrival and not any(_pool_loaded_clock(manifest))


def _prepare_pool(run: pathlib.Path, specimen: pathlib.Path | None, *,
                  substitute: pathlib.Path | None = None, substitute_letter: str = "A"
                  ) -> dict[str, Any]:
    """The run folder's manifest; a party that has not taken Rolf's tour is judged from where it ends.

    The route answers the tour's pages before the map, so the menu save and the walk start at
    `POOL_TOUR_END`; `loaded_place` keeps the slot's own square.
    """
    manifest = _prepare_from(POOL_SOURCES, run, specimen,
                             substitute=substitute, substitute_letter=substitute_letter)
    if _tour_pending(manifest):
        manifest["opening_tour"] = True
        manifest["loaded_place"] = manifest["state_a"]
        manifest["state_a"] = dict(POOL_TOUR_END)
    manifest["turn_about"] = pool_turns_about(manifest["state_a"])
    return manifest
