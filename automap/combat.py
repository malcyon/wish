"""The fight: what the machine holds while a battle runs, and where to draw it.

No Qt in here, the same way `live.py` and `render.py` have none. The window
paints what `battlefield` yields and the tests assert on it against captured
bytes.

**Everything is gated on `$6E11 == 2`.** `LINKER`, the 136-byte resident at
`$2B80`, is the outer loop: read `$6E11`, load that overlay at `$0800`, call it,
repeat -- `0` GEN, `1` DUNGEON, **`2` COMBAT**, `3` INIT, `4` COM.PREP,
`5` POST.COM, `8` FINAL, `9` CAMP. The gate is not an optimisation: outside
combat `$8B00` is a graphics buffer, and in a captured world snapshot it reads
`00 00 FF FF ...`, so an ungated reader draws combatants stacked at (0,0).

**The shape is read, never assumed.** `SQRPACI<nn>` supplies a parameter block
at `$0600` and the two combat files seen do not agree: `SQRPACI01` has a row
bounds 55 x 25, `SQRPACI00` bounds 17 x 35 -- and 18 x 36 squares is exactly
the 648 bytes that sit in front of the glyph table in a `SQRDATA` file.
`COM.PREP $08C6` derives the camera clamps from the same bytes, which is what
proves the reading. The write-up, `work/reports/combat-terrain.md`, is lost.
"""

from __future__ import annotations

from dataclasses import dataclass

from goldbox import monster
from goldbox.layout import RECORD_SIZE
from goldbox.record import CharacterRecord, FieldNotStored
from goldbox.savegame import (
    RECORD_SLOT_COUNT,
    ROSTER_STRIDE,
    SAVE0_LOAD_ADDRESS,
    SAVE1_LOAD_ADDRESS,
    SLOT_AREA_BASE,
    SLOT_STRIDE,
    RosterBlock,
    looks_occupied,
)
from goldbox.traits import NAMES, traits

from .live import active_effects
from .render import Hatch, Label, Line, Rect, hatch_lines

# Which overlay is running. LINKER's own dispatch byte.
MODE = 0x6E11
COMBAT = 2

# The parameter block SQRPACI loads at $0400; $0600 is its +0x200.
PARAMS = 0x0600
PARAMS_LEN = 0x14
P_MAP = 0x02              # the combat map, one byte a square
P_POSITIONS = 0x04        # the combatant table
P_COUNT = 0x06            # how many combatants the table holds
P_STRIDE = 0x07           # NOT the row stride -- see `Shape` below
P_MAX_X = 0x12            # last square, not the width
P_MAX_Y = 0x13

CAMERA = 0x037E           # top-left square of the window the game draws
VIEW = 7                  # squares across, from COM.PREP $08C6 LDA #$07

INITIATIVE = 0xA380       # one byte a combatant; all zero ends the round

# The roster runs on past the party's eight blocks in combat: 64 blocks of $20
# fill $8300-$8AFF and the position table begins at $8B00, immediately after.
ROSTER = SAVE1_LOAD_ADDRESS
POSITION_STRIDE = 4
OFF_MAP = 0xFF
FIRST_MONSTER = 8         # 0-7 the party in save-slot order, the same encoding
                          # the effects owner byte uses

# A monster's record is loaded into one of the twelve record slots, and several
# monsters share one: eight GOBLIN GUARDs in a slums encounter all named slot 8.
RECORDS = SLOT_AREA_BASE
RECORD_STRIDE = SLOT_STRIDE
RECORD_COUNT = RECORD_SLOT_COUNT
ROSTER_RECORD_SLOT = 0x0D

# The record slots are inside the save image, and so are the four 64-entry
# effect arrays at its head, so **one range covers both**: read from $4900
# rather than from $4D00 and the conditions arrive with the records for $400
# more bytes and not one more block. That matters because the cost of a read is
# the round trip -- a sixth range would be free on `ViceTarget`, which stops the
# machine once for the whole burst, and a whole extra trip on a backend that
# only has `read`.
SAVE_HEAD = SAVE0_LOAD_ADDRESS
RECORDS_AT = RECORDS - SAVE0_LOAD_ADDRESS                 # $400
SAVE_HEAD_LEN = RECORDS_AT + RECORD_COUNT * RECORD_STRIDE

# `goldbox/traits.py` 31, PROBABLE. **Per-monster, so it cannot come from the
# record**: eight GOBLIN GUARDs share record slot 8, and a condition written in
# that record's trait slots would be true of all eight at once. The effect
# arrays key on the combatant index instead -- 0-7 the party, 8 upward the
# monsters -- which is the one place a single monster can be named.
HELPLESS = 31

# `goldbox/traits.py` 52, PROBABLE, and 53, CONFIRMED. A Sleep cast on a slums
# orc ambush wrote 53 on all five sleeping orcs and not 31 -- so 31 alone was
# the wrong trigger. All three are states a creature cannot defend itself in.
HELD_OR_PARALYSED = 52
SLEEPING = 53

# Ascending, so a combatant carrying more than one reads out in a fixed order.
HELPLESS_TRAITS = (HELPLESS, HELD_OR_PARALYSED, SLEEPING)

# The tooltip's wording for each of `HELPLESS_TRAITS`, taken from
# `goldbox/traits.py`'s own name and capitalised -- one table, so the word and
# the id cannot drift apart.
HELPLESS_LABELS = {code: NAMES[code][0][0].upper() + NAMES[code][0][1:]
                   for code in HELPLESS_TRAITS}

# Drawing. The combat grid is 56 squares across where the area map is 16, so the
# cell shrinks to fit rather than the window growing to 1900 pixels.
CELL_MAX = 30
CELL_MIN = 12
TARGET_WIDTH = 560
MARGIN = 20
PAD = 3                   # squares of ground kept around the action
LEAST = 12                # ...and never a view smaller than this

# How solid rock is drawn. `FILL` is the old flat tint, only darker; `HATCH`
# and `CROSS` are the pen, one set of 45-degree strokes or two, with the heavy
# outline an ink-and-pen cartographer puts round a mass of rock and no line
# between one rock square and the next.
FILL, HATCH, CROSS = "fill", "hatch", "cross"
SHADING = HATCH


@dataclass(frozen=True)
class Shape:
    """The map's geometry, as the `$0600` block gives it."""

    map_base: int
    stride: int
    width: int
    height: int
    positions: int
    count: int

    @property
    def length(self) -> int:
        """Bytes to read: rows are `stride` apart, so the last one ends there."""
        return self.stride * self.height

    def index(self, x: int, y: int) -> int:
        return y * self.stride + x

    def holds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height


def shape_from_params(block: bytes) -> Shape | None:
    """The shape, or None if these bytes cannot be a parameter block.

    Validate before trust: `$0600` is ordinary RAM and holds something else
    entirely between fights -- in a captured world snapshot it reads
    `00 08 00 00 00 8c ...`, whose map base is zero.
    """
    if len(block) < PARAMS_LEN:
        return None
    word = lambda at: block[at] | (block[at + 1] << 8)          # noqa: E731
    # The row stride is `$0612 + 1`, not `$0607`. `GDRIVE00 $C3AF` is
    # `LDX $0612 / INX / STX $4B` -- the renderer derives it from the maximum
    # square. In a fight the two agree at 56 and the difference never shows;
    # on the overland map `$0607` is 20 against a true 18, and reading it there
    # shears every row two squares further along than the one before.
    shape = Shape(map_base=word(P_MAP), stride=block[P_MAX_X] + 1,
                  width=block[P_MAX_X] + 1, height=block[P_MAX_Y] + 1,
                  positions=word(P_POSITIONS), count=block[P_COUNT])
    if not (shape.map_base and shape.positions and shape.count):
        return None
    if not (0 < shape.width <= shape.stride <= 0x100):
        return None
    if not (0 < shape.height <= 0x100 and shape.count <= 0x100):
        return None
    return shape


@dataclass(frozen=True)
class Combatant:
    """One entry of the position table, with its roster block and record.

    `record` is None when the slot it names holds nothing readable, which is an
    ordinary state mid-load rather than an error. Everything the tooltip shows
    is optional for the same reason: a field we have not read is left out.
    """

    index: int
    x: int
    y: int
    slot: int
    pose: int
    on_map: bool
    initiative: int
    hp: int | None = None
    hp_max: int | None = None
    armour_class: int | None = None
    thac0: int | None = None
    movement: int | None = None
    record: CharacterRecord | None = None
    #: Which of `HELPLESS_TRAITS` (31, 52, 53) is on this combatant's index
    #: right now, empty if none. Recomputed from the `$4900` arrays every poll
    #: and never carried forward, so it goes the moment the game clears the id.
    helpless: frozenset[int] = frozenset()

    @property
    def is_party(self) -> bool:
        return self.index < FIRST_MONSTER

    @property
    def name(self) -> str:
        return self.record.name if self.record is not None else f"#{self.index}"

    @property
    def alive(self) -> bool:
        return bool(self.hp)

    @property
    def dimmed(self) -> bool:
        """Dead, or gone from the map. Drawn faint rather than removed, so you
        can see what happened."""
        return not self.alive or not self.on_map

    @property
    def square(self) -> tuple[int, int]:
        return self.x, self.y

    @property
    def kind(self) -> str:
        """How the square is filled: the party green, an enemy red, and a
        helpless enemy yellow.

        **The party keeps its green when it is helpless.** The fill says which
        side a square is on before it says anything else, and a yellow party
        square would read as a third side; the tooltip carries the condition
        for both.
        """
        if self.is_party:
            base = "party"
        elif self.helpless:
            base = "helpless"
        else:
            base = "enemy"
        return f"{base}-dim" if self.dimmed else base

    @property
    def hp_text(self) -> str:
        return "?" if self.hp is None else str(self.hp)

    def lines(self) -> list[str]:
        """The tooltip, as text. **Only what is decoded.**

        A field we cannot read is missing from the list rather than guessed at,
        and a trait code with no name shows its number so that an unnamed code
        is visibly unnamed.
        """
        head = f"{self.index}. {self.name}  ({self.x},{self.y})"
        out = [head] if self.on_map else [f"{self.index}. {self.name}  (off the map)"]
        if self.hp is not None:
            out.append(f"{self.hp} / {self.hp_max} hp"
                       if self.hp_max else f"{self.hp} hp")
        combat = []
        if self.armour_class is not None:
            combat.append(f"AC {self.armour_class}")
        if self.thac0 is not None:
            combat.append(f"THAC0 {self.thac0}")
        if self.movement is not None:
            combat.append(f"move {self.movement}")
        if combat:
            out.append("   ".join(combat))
        for code in sorted(self.helpless):
            out.append(HELPLESS_LABELS[code])
        if not self.alive:
            out.append("dead or gone from the fight")
        if self.record is None:
            return out

        dice = self.record.get("level")
        if dice:
            out.append(f"level {dice}" if self.is_party else f"{dice} hit dice")
        for attack in monster.attacks(self.record):
            out.append(attack.text)
        saves = monster.saving_throws(self.record)
        if any(n for _, n in saves):
            out.append("saves " + " / ".join(str(n) for _, n in saves)
                       + "  (paralysis, petrification, wands, breath, spell)")
        if not self.is_party and self.hp_max:
            award = monster.experience_award(self.record, self.hp_max)
            if award:
                out.append(f"{award} experience")
        # `item_effects` is the layout's name for the ten trait slots; the
        # codes mean one thing on a monster and another on an item.
        for trait in traits(self.record.get_raw("item_effects")):
            if not trait.is_fill:
                out.append(trait.label)
        return out


@dataclass(frozen=True)
class Battle:
    """One reading of a fight in progress."""

    shape: Shape
    terrain: bytes
    combatants: tuple[Combatant, ...]
    camera: tuple[int, int]

    def square(self, x: int, y: int) -> int:
        """The terrain code, with the occupancy bit masked off.

        `$C086 BPL` branches past the glyph lookup when bit 7 is set and draws
        a combatant instead, so bit 7 is occupancy and bits 0-6 are the ground.
        """
        if not self.shape.holds(x, y):
            return 0
        return self.terrain[self.shape.index(x, y)] & 0x7F

    def occupied(self, x: int, y: int) -> bool:
        if not self.shape.holds(x, y):
            return False
        return bool(self.terrain[self.shape.index(x, y)] & 0x80)

    @property
    def party(self) -> tuple[Combatant, ...]:
        return tuple(c for c in self.combatants if c.is_party)

    @property
    def enemies(self) -> tuple[Combatant, ...]:
        return tuple(c for c in self.combatants if not c.is_party)

    def at(self, x: int, y: int) -> Combatant | None:
        for c in self.combatants:
            if c.square == (x, y):
                return c
        return None

    @property
    def round_over(self) -> bool:
        """Every initiative byte spent. Nobody left who may still act."""
        return not any(c.initiative for c in self.combatants)


# -- reading a running machine ----------------------------------------------

def _record(window: bytes) -> CharacterRecord | None:
    if not looks_occupied(window):
        return None
    try:
        return CharacterRecord(window + bytes(RECORD_SIZE - len(window)),
                               stored_size=len(window))
    except (ValueError, FieldNotStored):
        return None


def helpless_indices(save_head: bytes) -> dict[int, frozenset[int]]:
    """Which of `HELPLESS_TRAITS` is on which combatant right now, by index.

    Read out of the four `$4900` arrays every poll and never remembered: the
    game clears the id when the condition ends (`docs/133-active-effects.md`),
    and a set carried forward would keep a monster gold after it woke up.

    The owner byte is the combat combatant index -- 0-7 the party in save-slot
    order, 8 upward the monsters, `$FF` the whole party -- which is why this can
    say *which* GOBLIN GUARD is helpless where the shared record cannot.
    `$FF` is dropped rather than trusted: no index reaches it, and a
    party-wide helplessness is not a thing any spell does.
    """
    out: dict[int, set[int]] = {}
    for effect in active_effects(save_head):
        if effect.id in HELPLESS_TRAITS and not effect.party_wide:
            out.setdefault(effect.owner, set()).add(effect.id)
    return {owner: frozenset(codes) for owner, codes in out.items()}


def _combatant(index: int, positions: bytes, roster: bytes, records: bytes,
               initiative: bytes, shape: Shape, previous: Battle | None,
               helpless: dict[int, frozenset[int]] = {}) -> Combatant | None:
    at = index * POSITION_STRIDE
    x, y, packed = positions[at], positions[at + 1], positions[at + 2]
    on_map = x != OFF_MAP and y != OFF_MAP
    if on_map and not shape.holds(x, y):
        return None                      # not a square; do not draw it anywhere
    if not on_map:
        # Dead or fled. Keep it where it last stood so it can be dimmed rather
        # than vanishing -- but only if we saw it there, never invented.
        was = next((c for c in previous.combatants if c.index == index), None) \
            if previous else None
        if was is None or not was.on_map:
            return None
        x, y, packed = was.x, was.y, (was.slot << 2) | was.pose

    block = RosterBlock(bytearray(roster), index)
    if not block.occupied:
        return None
    slot = block.raw[ROSTER_RECORD_SLOT]
    record = None
    if slot < RECORD_COUNT:
        base = slot * RECORD_STRIDE
        record = _record(records[base:base + RECORD_STRIDE])
    hp_max = None
    if record is not None:
        try:
            hp_max = record.get("hp_max")
        except (FieldNotStored, KeyError):
            hp_max = None
    return Combatant(
        index=index, x=x, y=y, slot=packed >> 2, pose=packed & 0x03,
        on_map=on_map, initiative=initiative[index] if index < len(initiative) else 0,
        hp=block.hit_points, hp_max=hp_max,
        armour_class=block.armour_class, thac0=block.thac0,
        movement=block.movement, record=record,
        helpless=helpless.get(index, frozenset()))


def _blocks(target, blocks) -> list[bytes]:
    """One burst where the backend can do that; see `live.read_blocks`."""
    burst = getattr(target, "read_blocks", None)
    if burst is not None:
        return list(burst(blocks))
    return [target.read(addr, length) for addr, length in blocks]


def read_battle(target, previous: Battle | None = None) -> Battle | None:
    """The fight in progress, or None when there is not one.

    Two bursts, because the map's address and length are in the first one: the
    mode byte, the parameter block and the camera, then the map, the roster,
    the positions, the initiative bytes and the head of the save image, which
    carries the effect arrays and the twelve record slots together. The cost of
    a read is the round trip and not the bytes -- ~14.3 ms either way under
    VICE -- so the number that matters is two.

    `previous` is last poll's battle, and supplies the last known square of a
    combatant that has left the map.
    """
    if target is None:
        return None
    mode, params, camera = _blocks(target, ((MODE, 1), (PARAMS, PARAMS_LEN),
                                            (CAMERA, 2)))
    if not mode or mode[0] != COMBAT:
        return None
    shape = shape_from_params(params)
    if shape is None:
        return None
    terrain, roster, positions, initiative, save_head = _blocks(target, (
        (shape.map_base, shape.length),
        (ROSTER, shape.count * ROSTER_STRIDE),
        (shape.positions, shape.count * POSITION_STRIDE),
        (INITIATIVE, shape.count),
        (SAVE_HEAD, SAVE_HEAD_LEN)))
    if len(terrain) < shape.length or len(save_head) < SAVE_HEAD_LEN:
        return None
    records = save_head[RECORDS_AT:]
    helpless = helpless_indices(save_head)
    people = []
    for i in range(shape.count):
        who = _combatant(i, positions, roster, records, initiative, shape,
                         previous, helpless)
        if who is not None:
            people.append(who)
    return Battle(shape=shape, terrain=bytes(terrain),
                  combatants=tuple(people),
                  camera=(camera[0], camera[1]))


# -- geometry ----------------------------------------------------------------

def extent(battle: Battle, pad: int = PAD,
           least: int = LEAST) -> tuple[int, int, int, int]:
    """The part of the map worth drawing, as (x, y, width, height).

    Both maps seen are 56 x 26 with the fight in a corner, so drawing all 1456
    squares would spend the whole window on empty ground. The box covers every
    combatant and the 7 x 7 window the game itself is showing, padded, and is
    never smaller than `least` squares a side.
    """
    xs = [c.x for c in battle.combatants] + [battle.camera[0],
                                             battle.camera[0] + VIEW - 1]
    ys = [c.y for c in battle.combatants] + [battle.camera[1],
                                             battle.camera[1] + VIEW - 1]
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    w, h = max(x1 - x0 + 1, least), max(y1 - y0 + 1, least)
    w, h = min(w, battle.shape.width), min(h, battle.shape.height)
    x0 = max(0, min(x0, battle.shape.width - w))
    y0 = max(0, min(y0, battle.shape.height - h))
    return x0, y0, w, h


def cell_for(width: int) -> int:
    """How big a square can be and still fit the window."""
    return max(CELL_MIN, min(CELL_MAX, TARGET_WIDTH // max(1, width)))


def _rock(battle: Battle, box, cell: int, margin: int, shading: str):
    """Solid rock: the fill for every impassable square, then its outline.

    Fills first and outlines afterwards, because a stroke sits astride the line
    it is drawn on and the next square's fill would paint over half of it.

    The outline is drawn only where rock meets ground, so a mass of rock is one
    heavy shape rather than a grid of squares -- which is the difference between
    a map somebody inked and a map something tiled.
    """
    x0, y0, w, h = box
    at = lambda x, y: (margin + (x - x0) * cell,           # noqa: E731
                       margin + (y - y0) * cell)
    rock = [(x, y) for y in range(y0, y0 + h) for x in range(x0, x0 + w)
            if battle.square(x, y)]

    for x, y in rock:
        left, top = at(x, y)
        if shading == FILL:
            yield Rect(left, top, cell, cell, "block")
        else:
            yield Hatch(left, top, cell, cell, "block",
                        hatch_lines(left, top, cell, cell,
                                    cross=shading == CROSS))
    if shading == FILL:
        return

    for x, y in rock:
        left, top = at(x, y)
        right, bottom = left + cell, top + cell
        if not battle.square(x, y - 1):
            yield Line(left, top, right, top, "rock-edge")
        if not battle.square(x, y + 1):
            yield Line(left, bottom, right, bottom, "rock-edge")
        if not battle.square(x - 1, y):
            yield Line(left, top, left, bottom, "rock-edge")
        if not battle.square(x + 1, y):
            yield Line(right, top, right, bottom, "rock-edge")


def battlefield(battle: Battle, box=None, cell: int | None = None,
                margin: int = MARGIN, shading: str = SHADING):
    """Every primitive for one fight: ground, then combatants.

    Terrain is drawn as **wall or not wall** and nothing finer. The glyphs at
    `$91B0` say what each code looks like on the C64's own screen, but nothing
    here has been checked against them, and a map that invented a diagonal
    would be worse than one that draws a block.
    """
    x0, y0, w, h = box or extent(battle)
    cell = cell or cell_for(w)
    yield from _rock(battle, (x0, y0, w, h), cell, margin, shading)

    cx, cy = battle.camera
    yield Rect(margin + (cx - x0) * cell, margin + (cy - y0) * cell,
               VIEW * cell, VIEW * cell, "camera")

    for who in battle.combatants:
        if not (x0 <= who.x < x0 + w and y0 <= who.y < y0 + h):
            continue
        left = margin + (who.x - x0) * cell
        top = margin + (who.y - y0) * cell
        yield Rect(left + 1, top + 1, cell - 2, cell - 2, who.kind)
        if who.initiative and not who.dimmed:
            # Still has initiative to spend, so it may still act this round.
            # $A380 counts down and the round ends when all 64 are zero.
            yield Rect(left - 1, top - 1, cell + 2, cell + 2, "ready")
        # Hit points are written in the paper colour on the green and the
        # red, which have the contrast for it. The helpless yellow does not --
        # nothing that still reads as yellow does -- so its digits are inked.
        if who.dimmed:
            ink = "hp-dim"
        elif who.kind == "helpless":
            ink = "hp-ink"
        else:
            ink = "hp"
        yield Label(left + cell / 2, top + cell / 2, who.hp_text, ink)


def square_at(px: float, py: float, box, cell: int,
              margin: int = MARGIN) -> tuple[int, int] | None:
    """Which square a point in the canvas is over. For the tooltip."""
    x0, y0, w, h = box
    x = int((px - margin) // cell)
    y = int((py - margin) // cell)
    if 0 <= x < w and 0 <= y < h:
        return x0 + x, y0 + y
    return None
