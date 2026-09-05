from __future__ import annotations

"""What a title says about itself, read off its own disks with no emulator.

`#31 (Cold-read Curse and Silver Blades for the fields the editor shows)` is
eight cells of `docs/139-per-title-validation.md`'s matrix that needed no
running machine, only somebody to open the files. This module holds the ones
that had no test anywhere: the per-race trait seeds, Silver Blades' item type
table, the four active-effect arrays, and Silver Blades' level tables.

**Every address here runs at `$0800`, and every PRG header on these files
disagrees.** `GEN` declares `$1000` in Pool of Radiance, `$1220` in Curse and
`$4000` in Silver Blades; `CAMP` declares `$1000`, `$3000` and `$4000`. `$0800`
is where `LINKER` puts an overlay it dispatches to, and the operands settle it:
Silver Blades' `GEN $18C9` reads its own scratch at `$1BFD`, Curse's `CAMP
$2A25` calls `$1CE9` -- addresses inside the file at `$0800` and outside it at
the header's. Seven citations in this repository were written at the header base
and are corrected in `goldbox/layout.py`.

The finders live in `tools/coldread.py` rather than here, because the point of
them is that they can be run against Champions of Krynn, Death Knights of Krynn
or Gateway to the Savage Frontier without anyone writing them a second time.

Nothing here reads a committed fixture and everything skips when the player has
no disks -- and the Curse half skips on a machine where `COAB_DISKS` is unset
and the disks are somewhere `tests/gamedata.py:curse_dir` does not look.
"""


import pathlib

import pytest
from conftest import load_tools_module

coldread = load_tools_module("coldread")

from goldbox import games, items, traits  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tests import gamedata  # noqa: E402
from tests.test_silverblades import ssb_dir  # noqa: E402

POOL = games.POOL_OF_RADIANCE
CURSE = games.CURSE_OF_THE_AZURE_BONDS
SSB = games.SECRET_OF_THE_SILVER_BLADES

BASE = coldread.GEN_BASE


def _root(game):
    """The directory holding a title's disks, or skip.

    Each title is found the way the rest of the suite finds it, so a machine
    with one game and not another runs exactly the tests it can.
    """
    if game is POOL:
        where = gamedata.disk_dir()
        env = "POR_DISKS"
    elif game is CURSE:
        where = gamedata.curse_dir()
        env = gamedata.CURSE_ENV
    else:
        where = ssb_dir()
        env = "SSB_DISKS"
    if where is None:
        pytest.skip(f"needs the {game.title} disks; set {env}")
    return str(where)


def _gen(game) -> bytes:
    return coldread.overlay(game, b"GEN", _root(game))


def _at(body, address, count):
    return coldread.table(body, BASE, address, count)


# --- the overlay base, which six citations got wrong -------------------------

#: Every spellbook-width address `goldbox/layout.py` cites, with the opcodes it
#: says are there. Each was written at the overlay's PRG header base until
#: 2026-09-02 -- `GEN $41DC` where the byte is at `$09DC` -- and the way that
#: went unnoticed for so long is that nothing ever looked. This looks.
CITED = (
    (POOL, b"GEN", 0x216B, "BD786B", "the 32-byte copy that is not proof"),
    (CURSE, b"GEN", 0x220F, "BD787C", "the same copy in Curse"),
    (CURSE, b"GEN", 0x232A, "AD817C09E0", "the four druid spells ORed in"),
    (CURSE, b"CAMP", 0x2A25, "A0008C", "the memorise walk"),
    (SSB, b"GEN", 0x09DC, "9D787C", "the sixteen-byte clear"),
    (SSB, b"GEN", 0x18C9, "BD787C", "the sixteen-byte walk"),
    (SSB, b"CAMP", 0x2871, "207814", "the memorise walk"),
)


@pytest.mark.parametrize("game,file,address,opcodes,what", CITED,
                         ids=[f"{g.key[:6]}-{f.decode()}-{a:04X}"
                              for g, f, a, _o, _w in CITED])
def test_a_cited_address_holds_the_instruction_it_is_cited_for(
        game, file, address, opcodes, what):
    """Every address in the spellbook-width paragraph, checked against the bytes.

    Not a byte dump and not a restatement of the code: each row is a claim
    somebody made in prose about where a routine is, and this is the claim
    being true. It fails on any of the seven addresses those citations carried
    before `#31` -- `$41DC` holds `$1F 0F 08`, not `STA $7C78,X`.
    """
    body = coldread.overlay(game, file, _root(game))
    want = bytes.fromhex(opcodes)
    got = coldread.table(body, BASE, address, len(want))
    assert bytes(got) == want, (
        f"{game.title} {file.decode()} ${address:04X} ({what}) holds "
        + " ".join(f"{b:02x}" for b in got))


# --- A15: the per-race trait seeds -------------------------------------------

#: What `GEN` seeds each race's first trait slots with, per title, read out of
#: the tables the seeding instruction points at. The count differs -- one slot
#: in Pool of Radiance, three in Curse, two in Silver Blades -- which is why
#: `tools/coldread.py` counts them rather than assuming.
SEEDS = {
    POOL.key: {2: [107], 4: [124]},
    CURSE.key: {1: [26, 47, 97], 2: [107], 3: [18, 48, 97], 4: [124]},
    SSB.key: {1: [95], 2: [18], 3: [26, 47], 4: [48, 7], 5: [92]},
}


@pytest.mark.parametrize("game", [POOL, CURSE, SSB],
                         ids=lambda g: g.key)
def test_the_race_that_gets_a_trait_at_creation_is_the_titles_own(game):
    """Each title seeds `0x0AD` from a race-indexed table, and they differ.

    Not a byte dump: the table address is *found*, by the read that uses it,
    so this fails if a title stops seeding traits that way rather than if a
    number moves.
    """
    gen = _gen(game)
    where, tables = coldread.trait_seeds(gen, game, BASE)
    assert where is not None, f"{game.title} seeds no trait from the race byte"
    want = SEEDS[game.key]
    got = {}
    for code in dict(game.races or ()):
        row = [_at(gen, a, code + 1)[code] for a in tables]
        if any(row):
            got[code] = [v for v in row if v]
    for code, codes in want.items():
        assert got.get(code) == codes, (code, got.get(code), codes)


def test_curse_seeds_the_races_pool_of_radiance_already_named():
    """Curse shares the trait namespace, and the seeds are what says so.

    Every code Curse writes lands on the race `goldbox/traits.py`'s name
    demands -- including 47 and 97, which name three races between them, and
    which no coincidence would put on the dwarf and the gnome and nowhere else.
    """
    gen = _gen(CURSE)
    _, tables = coldread.trait_seeds(gen, CURSE, BASE)
    dwarf = [_at(gen, a, 2)[1] for a in tables]
    gnome = [_at(gen, a, 4)[3] for a in tables]
    assert traits.NAMES[dwarf[0]][0].startswith("dwarf ")
    assert traits.NAMES[gnome[0]][0].startswith("gnome ")
    for shared in (dwarf[1], gnome[2]):
        assert "dwarf" in traits.NAMES[shared][0]
    assert traits.NAMES[_at(gen, tables[0], 3)[2]][0].startswith("elf")
    assert traits.NAMES[_at(gen, tables[0], 5)[4]][0].startswith("half-elf")


def test_silver_blades_seeds_an_elf_a_code_that_is_not_an_elfs():
    """The counterexample that makes the namespace per title -- see #186.

    An elf's racial ability is the 90% resistance to sleep and charm in every
    edition of the rules and in both earlier titles. Silver Blades seeds its
    elf 95 and its half-elf 18, and Pool of Radiance's table calls those two
    something else entirely, which is *why* Silver Blades needed a table of
    its own.

    This docstring used to say the test would go red the day that table was
    written. It did not and could not: the assertion is against the flat
    `traits.NAMES`, which is Pool of Radiance's table by definition and does
    not move when a per-title one is added. Corrected in the code review of
    #186 on 2026-09-02. What the test still pins is the fact the split rests
    on -- that Silver Blades seeds these two codes and that Pool of Radiance
    means something else by them -- so it earns its place; it is simply not
    the guard the old sentence claimed.
    """
    gen = _gen(SSB)
    _, tables = coldread.trait_seeds(gen, SSB, BASE)
    elf = _at(gen, tables[0], 2)[1]
    half_elf = _at(gen, tables[0], 3)[2]
    assert (elf, half_elf) == (95, 18)
    assert "elf" not in traits.NAMES[elf][0]
    assert "half-elf" not in traits.NAMES[half_elf][0]


@pytest.mark.parametrize("game,paladin,ranger",
                         [(CURSE, 45, 134), (SSB, 45, 105)],
                         ids=lambda v: getattr(v, "key", str(v)))
def test_the_paladin_and_the_ranger_are_given_a_trait_for_their_class(
        game, paladin, ranger):
    """A paladin's is the same code in both titles and a ranger's is not."""
    assert dict(coldread.class_seeds(_gen(game), game, BASE)) == {
        "paladin": paladin, "ranger": ranger}


def test_the_shipped_silver_blades_party_carries_what_the_seed_tables_write():
    """Six characters, the only Silver Blades specimens anybody has.

    MALACHITE is race 3 and carries the two codes race 3 is seeded with; the
    paladin and the ranger carry their class codes in the tenth slot. That is
    the corroboration the tables need -- a table read out of code and never
    seen on a character is a reading, not a measurement.
    """
    from tests.test_silverblades import _party

    gen = _gen(SSB)
    _, tables = coldread.trait_seeds(gen, SSB, BASE)
    sg0, _sg1 = _party()
    seen = 0
    for slot in sg0.characters:
        record = slot.record
        race = record.get("race")
        want = [v for v in (_at(gen, a, race + 1)[race] for a in tables) if v]
        carried = [v for v in record.slice(0x0AD, 10) if v]
        for code in want:
            assert code in carried, (record.name, code, carried)
            seen += 1
        if record.get("level_paladin"):
            assert 45 in carried, record.name
            seen += 1
        if record.get("level_ranger"):
            assert 105 in carried, record.name
            seen += 1
    assert seen >= 4, f"only {seen} seeded codes on the whole party"


# --- A12: Silver Blades' item type table -------------------------------------

#: AD&D 1st edition damage, `(vs medium, vs large)`. Transcribed from the rules
#: and *not* from any of the three games, so a title agreeing with it is a
#: title agreeing with something outside this repository.
ADND_DAMAGE = {
    "BATTLE AXE": ("1d8", "1d8"), "DAGGER": ("1d4", "1d3"),
    "LONG SWORD": ("1d8", "1d12"), "SHORT SWORD": ("1d6", "1d8"),
    "TWO-HANDED SWORD": ("1d10", "3d6"), "MACE": ("1d6+1", "1d6"),
    "MORNING STAR": ("2d4", "1d6+1"), "FLAIL": ("1d6+1", "2d4"),
    "HALBERD": ("1d10", "2d6"), "SPEAR": ("1d6", "1d8"),
    "DART": ("1d3", "1d2"), "HAND AXE": ("1d6", "1d4"),
    "BROAD SWORD": ("2d4", "1d6+1"), "QUARTER STAFF": ("1d6", "1d6"),
    "PIKE": ("1d6", "1d12"), "SCIMITAR": ("1d8", "1d8"),
    "TRIDENT": ("1d6+1", "3d4"), "BARDICHE": ("2d4", "3d4"),
    "GLAIVE": ("1d6", "1d10"), "JAVELIN": ("1d6", "1d6"),
    "CLUB": ("1d6", "1d3"), "BASTARD SWORD": ("2d4", "2d8"),
    # Added 2026-09-02. Its absence meant the comparison never reached
    # `KNOWN_DIFFERENT`, so the one named exception was skipped rather than
    # counted -- the rounding-away this table exists to prevent, and what made
    # "42 of 43" really 41.
    "HAMMER": ("1d4+1", "1d4"),
}

#: The armour class each suit grants, same source.
ADND_ARMOUR = {"LEATHER ARMOR": 8, "PADDED ARMOR": 8, "STUDDED LEATHER": 7,
               "RING MAIL": 7, "SCALE MAIL": 6, "CHAIN MAIL": 5,
               "SPLINT MAIL": 4, "BANDED MAIL": 4, "PLATE MAIL": 3,
               "BANDED ARMOR": 4, "SPLINT ARMOR": 4, "PLATE ARMOR": 3,
               "CHAIN ARMOR": 5, "SCALE ARMOR": 6, "RING ARMOR": 7,
               "ELFIN CHAIN": 5}

#: Named exceptions, **keyed on the item's whole name** rather than on the
#: stripped one, because the difference is not a property of the weapon.
#:
#: Silver Blades gives `HAMMER +4` 1d4+1 against large opponents where the
#: Players Handbook gives 1d4. Its plain `HAMMER`, `HAMMER +1` and `HAMMER +2`
#: all read 1d4+1 against small and medium and 1d4 against large, as do every
#: hammer in the two earlier titles -- so keying this on the stripped name, as
#: it was until 2026-09-02, would stop checking four items to excuse one.
#:
#: This exception never actually ran before that date: `HAMMER` was not a key
#: in `ADND_DAMAGE`, so the comparison skipped every hammer in all three
#: titles and the exception it named was rounded away by omission. Adding the
#: key is what surfaced the real difference, and it is narrower than the one
#: recorded here.
KNOWN_DIFFERENT = {(SSB.key, "HAMMER +4")}


def _plain(name: str) -> str:
    """A magical item's base name: `LONG SWORD +2` is a long sword."""
    for stop in (" +", " -", " VS", " OF"):
        cut = name.find(stop)
        if cut > 0:
            name = name[:cut]
    return name.strip()


def _item_tables(game):
    """This title's item names, its type table and its template lists."""
    root = pathlib.Path(_root(game))
    names = types = None
    templates = {}
    for path in sorted(root.glob(game.disk_glob)):
        try:
            image = D64.open(str(path))
        except Exception:
            continue
        if names is None and image.find(b"ITEMNAMES") is not None:
            names = items.load_item_names(image, game)
        if types is None and image.find(items.ITEM_TYPES_FILE) is not None:
            types = items.load_item_types(image)
    if names is None or types is None:
        pytest.skip(f"no {game.title} side here carries the item tables")
    for path in sorted(root.glob(game.disk_glob)):
        try:
            templates.update(items.load_item_templates(D64.open(str(path)),
                                                       names, game=game))
        except Exception:
            continue
    return names, types, templates


@pytest.mark.parametrize("game", [POOL, CURSE, SSB], ids=lambda g: g.key)
def test_a_titles_item_types_decode_to_the_rulebooks_numbers(game):
    """`ITEMS` read through the unmodified decoder, against AD&D, per title.

    Each title's *own* templates name its *own* type indices, which is the
    part that cannot be converted across: type 54 is scale mail in Pool of
    Radiance and Curse and the CANARY in Silver Blades. So this asks each game
    the same question in its own vocabulary and counts the answers.
    """
    names, types, templates = _item_tables(game)
    checked, wrong = 0, []
    for name, raw in sorted(templates.items()):
        kind = types.get(raw[0])
        if kind is None:
            continue
        base = _plain(name)
        if base in ADND_DAMAGE:
            checked += 1
            got = (kind.damage_vs_medium, kind.damage_vs_large)
            if got != ADND_DAMAGE[base] and (game.key, name) not in KNOWN_DIFFERENT:
                wrong.append((name, got, ADND_DAMAGE[base]))
        elif base in ADND_ARMOUR:
            checked += 1
            if kind.armour_class != ADND_ARMOUR[base] or kind.is_shield:
                wrong.append((name, kind.armour_class, ADND_ARMOUR[base]))
    assert checked >= 40, f"only {checked} of {game.title}'s items were named"
    assert not wrong, wrong


def test_silver_blades_item_types_say_which_classes_may_use_them():
    """The usage byte, on the two items whose answer is not a guess.

    A scroll is the discriminator: the game ships one for each caster and they
    do not overlap, so a usage byte read at the wrong offset cannot produce
    both.
    """
    _names, types, templates = _item_tables(SSB)
    by_name = {n: types.get(r[0]) for n, r in templates.items()}
    mage = next(v for k, v in by_name.items() if k.startswith("MAGE SCROLL"))
    cleric = next(v for k, v in by_name.items() if k.startswith("CLER SCROLL"))
    assert "magic-user" in mage.usable_by and "cleric" not in mage.usable_by
    assert mage.usable_by != cleric.usable_by
    assert cleric.usable_by == ["cleric"]


# --- A16: the four active-effect arrays --------------------------------------

#: `CAMP` touches all four arrays in all three titles and `DUNGEON` touches the
#: duration in all three -- 15 of 15 across the matrix. Two witnesses rather
#: than a count, because each is a different *use*: `CAMP` renumbers an owner
#: when a character changes slot and `DUNGEON` ticks a duration down as the
#: party walks. Nine other overlays reference the arrays too and are not
#: asserted, because which ones do is a per-title accident and this is not.
EFFECT_WITNESSES = {"id": ("CAMP",), "owner": ("CAMP",),
                    "duration": ("CAMP", "DUNGEON"), "magnitude": ("CAMP",)}


@pytest.mark.parametrize("game", [POOL, CURSE, SSB], ids=lambda g: g.key)
def test_the_effect_arrays_sit_where_the_save_image_puts_them(game):
    """Payload `$000`, `$040`, `$080`, `$280`, in every title.

    `automap/live.py` reads them at those offsets whatever the title, which is
    right by construction and had been measured on one game. A shipped party
    cannot corroborate it -- every slot in one is zero -- so the evidence is
    the overlays that touch each array at this title's own load address.
    """
    from automap import live

    assert (live.EFFECT_ID_OFFSET, live.EFFECT_OWNER_OFFSET,
            live.EFFECT_DURATION_OFFSET, live.EFFECT_MAGNITUDE_OFFSET) == \
        tuple(offset for _, offset in coldread.EFFECT_ARRAYS)
    users = coldread.effect_users(game, _root(game))
    for label, offset in coldread.EFFECT_ARRAYS:
        key = f"{label} ${game.save_load_address + offset:04X}"
        for want in EFFECT_WITNESSES[label]:
            assert any(hit.startswith(want + " ") for hit in users[key]), (
                f"{game.title}: no {want} reference to the {label} array")


@pytest.mark.parametrize("game", [POOL, CURSE, SSB], ids=lambda g: g.key)
def test_camp_renumbers_sixty_four_effect_owners_in_every_title(game):
    """One routine, three titles, and `LDX #$3F` is the array's own length.

    `LDX #$3F / LDA <owner>,X / CMP / BNE / LDA / STA <owner>,X / DEX / BPL`
    is instruction for instruction the same in all three; only the absolute
    operands move with the title's save base. That is what says
    `EFFECT_SLOTS` is 64 in the later titles rather than assumed to be.
    """
    from automap import live

    body = coldread.overlay(game, b"CAMP", _root(game))
    owner = game.save_load_address + 0x040
    read = bytes([0xBD, owner & 0xFF, owner >> 8])
    at = coldread.sites(body, read, BASE)
    assert at, f"{game.title}'s CAMP does not index the owner array"
    for address in at:
        head = body[address - BASE - 2:address - BASE]
        if head == bytes([0xA2, live.EFFECT_SLOTS - 1]):
            tail = body[address - BASE + 3:address - BASE + 17]
            assert bytes([0x9D, owner & 0xFF, owner >> 8]) in tail, tail.hex()
            assert bytes([0xCA, 0x10]) in tail, tail.hex()      # DEX / BPL
            return
    pytest.fail(f"{game.title}'s CAMP has no LDX #$3F before the owner read")


# --- A6 and A7: Silver Blades' level tables ----------------------------------

SSB_EXPERIENCE = 0x162D          # 6 rows x 19 entries x 3 bytes, big-endian
SSB_XP_ROW = 0x39
SSB_XP_LEVELS = 19
SSB_HIT_DIE = 0x1845
SSB_LAST_ROLLED = 0x184D
SSB_FLAT = 0x1855
SSB_SAVE_ROW = 0x1148            # 4 classes x 5 columns, level 1
SSB_SAVE_MASKS = 0x115C          # 4 classes x 5 columns x 5 bytes
SSB_THAC0 = (0x106F, 0x107F, 0x108F)     # magic-user, cleric, thief
SSB_CLASSES = ("magic-user", "cleric", "thief", "fighter", "paladin", "ranger")


def _ssb_experience(gen, row):
    at = SSB_EXPERIENCE - BASE + row * SSB_XP_ROW
    return [int.from_bytes(gen[at + k * 3:at + k * 3 + 3], "big")
            for k in range(SSB_XP_LEVELS)]


def test_silver_blades_experience_is_curses_table_carried_on():
    """78 values, and every one of them Curse's -- which is the check.

    `goldbox/levels.py` holds Curse's thirteen rows; Silver Blades' `GEN` has
    nineteen. Where they overlap they agree exactly, on all six classes, so a
    character imported from Curse means the same number of experience points
    after the import as before it.
    """
    from goldbox import levels

    gen = _gen(SSB)
    checked = 0
    for row, name in enumerate(SSB_CLASSES):
        values = _ssb_experience(gen, row)
        assert values == sorted(values) and values[0] == 0, name
        for entry in levels.table(name, CURSE.key):
            if entry.level == 1:
                continue
            assert values[entry.level - 1] == entry.experience, (name,
                                                                 entry.level)
            checked += 1
    assert checked == 61, (
        f"{checked} thresholds were comparable, not the 61 Curse's six rows "
        "hold above level 1")


def test_the_fighters_eleventh_threshold_is_the_same_on_a_second_rip():
    """749937 is SSI's number, not a bit rot in one Curse image.

    `goldbox/levels.py` records the Curse fighter's eleventh threshold as
    749937 where 750001 is expected, one `$40` bit down in `0B 71 B1`, and
    says a damaged image cannot be ruled out because only one of the player's
    Curse rips carries `GEN`. Silver Blades' `GEN` is a different file on a
    different release and carries the same number, which settles it.
    """
    from goldbox import levels

    assert _ssb_experience(_gen(SSB), 3)[10] == 749_937
    assert levels.table("fighter", CURSE.key)[10].experience == 749_937


def test_silver_blades_raises_every_ceiling_curse_set():
    """15, 15, 18, 15 and 15 for both of the classes Curse added.

    Read beside the array it caps -- `LDA $7CC9,X / CMP $17D0,X / BCS` -- so
    the table is tied to the eight bytes an editor would write, and the `BCS`
    is what tells it from the two attacks-per-round bands that compare the
    same array against a different table.
    """
    from goldbox import levels

    gen = _gen(SSB)
    where = coldread.class_ceilings(gen, SSB, BASE)
    assert where == 0x17D0
    caps = _at(gen, where, 8)
    assert caps == [15, 15, 18, 15, 0, 0, 15, 15]
    for bit, name in ((0, "magic-user"), (1, "cleric"), (2, "thief"),
                      (3, "fighter"), (6, "paladin"), (7, "ranger")):
        assert caps[bit] > levels.ceiling(name, CURSE.key), name


def test_silver_blades_racial_limits_are_the_rulebooks_under_its_own_races():
    """The third independent source for `RACES_SILVER_BLADES`.

    `goldbox/games.py` has that table from the label pool and from the Curse
    import's own arithmetic. Here it is again from a table neither of those
    touches: race 1's row is an elf's limits, race 3's a dwarf's, and the
    routine refuses to look up race 6 at all, which is the human rule.
    """
    gen = _gen(SSB)
    where, guard = coldread.racial_limits(gen, SSB, BASE)
    assert (where, guard) == (0x17E0, 6)
    rows = {code: _at(gen, where + (code - 1) * 8, 8)
            for code in range(1, guard)}
    assert rows[1] == [11, 0, 99, 7, 0, 0, 0, 0]        # elf
    assert rows[2] == [8, 5, 99, 8, 0, 0, 0, 8]         # half-elf, ranger 8
    assert rows[3] == [0, 0, 99, 9, 0, 0, 0, 0]         # dwarf
    assert rows[4] == rows[5] == [0, 0, 99, 6, 0, 0, 0, 0]   # gnome, halfling
    assert dict(SSB.races)[6] == "human"


def test_silver_blades_hit_dice_are_the_rulebooks():
    """Three eight-byte arrays: the die, the last rolled level, the flat tail.

    d4, d8, d6 and d10 with +1, +2, +2 and +3 are AD&D's, and the paladin's
    d10 +3 and the ranger's d8 +2 are the two rows Pool of Radiance has no
    opinion on.
    """
    gen = _gen(SSB)
    assert _at(gen, SSB_HIT_DIE, 8) == [4, 8, 6, 10, 10, 0, 10, 8]
    assert _at(gen, SSB_FLAT, 8) == [1, 2, 2, 3, 2, 0, 3, 2]
    assert _at(gen, SSB_LAST_ROLLED, 8) == [12, 10, 11, 10, 10, 0, 10, 11]


def test_silver_blades_thac0_is_the_rulebooks_and_the_fighter_is_computed():
    """Three packed rows and one rule.

    Each row is exactly `ceiling + 1` bytes -- sixteen for the magic-user and
    the cleric, nineteen for the thief, whose ceiling is 18 -- so the rows are
    packed rather than strided, and a thief at 17 reads its own table and not
    the next one. The stored byte is `60 - THAC0`, the family's encoding.
    """
    gen = _gen(SSB)
    magic_user, cleric, thief = (
        [60 - v for v in _at(gen, where, width)[1:]]
        for where, width in zip(SSB_THAC0, (16, 16, 19)))
    assert magic_user == [21] * 5 + [19] * 5 + [16] * 5
    assert cleric == [20] * 3 + [18] * 3 + [16] * 3 + [14] * 3 + [12] * 3
    assert thief == [21] * 4 + [19] * 4 + [16] * 4 + [14] * 4 + [12] * 2
    assert coldread.fighter_thac0_is_computed(gen, SSB, BASE)


def _ssb_improvement(gen, cls, column, level):
    """The game's own loop: two bits a level out of a 40-bit word.

    **All five mask bytes, not four.** The fifth carries the thief's level
    17-18 improvements -- with only four bytes the helper reproduces all six
    shipped characters because no shipped thief is above level 8, which is
    exactly the "plausible and wrong" failure that #187 (Silver Blades
    characters are shown Pool of Radiance's level progression) found in it.
    """
    mask = _at(gen, SSB_SAVE_MASKS + cls * 25 + column * 5, 5)
    word = sum(b << (8 * i) for i, b in enumerate(mask))
    total = 0
    for _ in range(level):
        low, word = word & 1, word >> 1
        high, word = word & 1, word >> 1
        total += (low << 1) | high
    return total


def _ssb_saves(gen, class_levels, race, constitution, paladin):
    """Silver Blades' five stored saves, by its own rule.

    Fill with 20, take the best column across every class held, improve a
    paladin's by 2, and take `constitution * 2 / 7` off the poison, wand and
    spell columns for **race 3 alone** -- Pool of Radiance gives that to the
    dwarf, the gnome and the halfling and to all five columns.
    """
    out = [20] * 5
    for cls in range(3, -1, -1):
        level = class_levels.get(cls, 0)
        if not level:
            continue
        for column in range(4, -1, -1):
            value = (_at(gen, SSB_SAVE_ROW + cls * 5 + column, 1)[0]
                     - _ssb_improvement(gen, cls, column, level))
            out[column] = min(out[column], value)
    if paladin:
        out = [max(0, v - 2) for v in out]
    if race == 3:
        bonus = constitution * 2 // 7
        for column in (0, 2, 4):
            out[column] = max(0, out[column] - bonus)
    return out


def test_silver_blades_saving_throws_reproduce_ssis_own_party():
    """Six of six, and two of the six are the cases that discriminate.

    GUY DE VALOIS is the paladin, so his row is the fighter's less two;
    MALACHITE is the dwarf, so three of his five carry the constitution bonus.
    A rule that got either wrong would still fit the other four.
    """
    from tests.test_silverblades import _party

    gen = _gen(SSB)
    sg0, _sg1 = _party()
    checked = 0
    for slot in sg0.characters:
        record = slot.record
        levels_by_slot = {}
        for index, field in enumerate(("level_magic_user", "level_cleric",
                                       "level_thief")):
            if record.get(field):
                levels_by_slot[index] = record.get(field)
        fighting = max(record.get(f) or 0 for f in
                       ("level_fighter", "level_knight", "level_paladin",
                        "level_ranger"))
        if fighting:
            levels_by_slot[3] = fighting
        got = _ssb_saves(gen, levels_by_slot, record.get("race"),
                         record.get("constitution"),
                         record.get("level_paladin"))
        stored = [record.get(f) for f in
                  ("save_paralysis", "save_petrification", "save_wands",
                   "save_breath", "save_spell")]
        assert got == stored, (record.name, got, stored)
        checked += 1
    assert checked == 6, f"the shipped party is six characters, not {checked}"


def test_only_the_dwarf_gets_silver_blades_constitution_save_bonus():
    """The rule the derivation above rests on, from the instructions.

    `LDA <race> / CMP #$03 / BNE` gates the whole routine on race 3, and the
    `DEX / DEX` at the bottom of its loop is what makes it every other column
    -- 4, 2 and 0, the spell, wand and poison saves.
    """
    gen = _gen(SSB)
    page = coldread.staging(SSB) >> 8
    gate = bytes([0xAD, coldread.RACE, page, 0xC9, 0x03, 0xD0])
    at = coldread.sites(gen, gate, BASE)
    assert len(at) == 1, f"{len(at)} routines gate on race 3"
    body = gen[at[0] - BASE:at[0] - BASE + 0x2C]
    assert bytes([0x9D, 0x9A, page]) in body, "it does not write the saves"
    assert bytes([0xCA, 0xCA]) in body, "it does not step two columns at a time"


def test_a_silver_blades_party_has_level_tables_and_its_trainer_is_still_unread():
    """`goldbox/levels.py` has Silver Blades' own tables now (#187), and its
    trainer is still refused -- the constitution hit-point bonus, the
    thief-skill racial adjustment, the wisdom bonus spells and the turning
    table remain unread or unattributed.

    This test used to assert the opposite: that Silver Blades fell back to
    Pool of Radiance's tables entirely, with a docstring saying the day the
    tables landed the assertion would go red. It did, which was the point --
    see #187 (Silver Blades characters are shown Pool of Radiance's level
    progression).
    """
    from goldbox import levels

    assert levels.for_game(SSB).key == levels.SECRET_OF_THE_SILVER_BLADES.key
    assert not levels.trainer_measured(SSB)


# --- #187: every literal `goldbox/levels.py` holds for Silver Blades, ------
# --- checked against `GEN` row by row rather than only against Curse's -----
# --- overlapping levels (the test above the A6/A7 section already does that)

def test_silver_blades_experience_matches_the_modules_own_table():
    """All 93 rows (15+15+18+15+15+15), not just the 61 shared with Curse."""
    from goldbox import levels

    gen = _gen(SSB)
    tables = levels.SECRET_OF_THE_SILVER_BLADES
    checked = 0
    for row, name in enumerate(SSB_CLASSES):
        values = _ssb_experience(gen, row)
        for entry in tables.table(name):
            assert values[entry.level - 1] == entry.experience, (name,
                                                                 entry.level)
            checked += 1
    assert checked == 93, checked


def test_silver_blades_thac0_matches_the_modules_own_table():
    """The three packed rows and the computed fighter group, against the
    rows `SECRET_OF_THE_SILVER_BLADES` actually holds."""
    from goldbox import levels

    gen = _gen(SSB)
    tables = levels.SECRET_OF_THE_SILVER_BLADES
    checked = 0
    for name, where in zip(("magic-user", "cleric", "thief"), SSB_THAC0):
        for entry in tables.table(name):
            assert 60 - _at(gen, where + entry.level, 1)[0] == entry.thac0, (
                name, entry.level)
            checked += 1
    for name in ("fighter", "paladin", "ranger"):
        for entry in tables.table(name):
            assert entry.thac0 == 21 - entry.level, (name, entry.level)
            checked += 1
    assert checked == 15 + 15 + 18 + 15 + 15 + 15
    assert coldread.fighter_thac0_is_computed(gen, SSB, BASE)


def test_silver_blades_saves_match_the_modules_own_table():
    """Every level to every class's ceiling, the five-byte mask expansion
    against the row `SECRET_OF_THE_SILVER_BLADES` holds -- not only the six
    shipped characters, which never reach a thief past level 8."""
    from goldbox import levels

    gen = _gen(SSB)
    tables = levels.SECRET_OF_THE_SILVER_BLADES
    cls_index = {"magic-user": 0, "cleric": 1, "thief": 2, "fighter": 3}
    checked = 0
    for name in ("magic-user", "cleric", "thief"):
        cls = cls_index[name]
        for entry in tables.table(name):
            got = tuple(
                _at(gen, SSB_SAVE_ROW + cls * 5 + column, 1)[0]
                - _ssb_improvement(gen, cls, column, entry.level)
                for column in range(5))
            assert got == entry.saves, (name, entry.level)
            checked += 1
    cls = cls_index["fighter"]
    for entry in tables.table("fighter"):
        got = tuple(
            _at(gen, SSB_SAVE_ROW + cls * 5 + column, 1)[0]
            - _ssb_improvement(gen, cls, column, entry.level)
            for column in range(5))
        assert got == entry.saves, entry.level
        checked += 1
    for paladin_entry, fighter_entry in zip(tables.table("paladin"),
                                            tables.table("fighter")):
        assert paladin_entry.saves == tuple(
            v - 2 for v in fighter_entry.saves), paladin_entry.level
        checked += 1
    for ranger_entry, fighter_entry in zip(tables.table("ranger"),
                                           tables.table("fighter")):
        assert ranger_entry.saves == fighter_entry.saves, ranger_entry.level
        checked += 1
    assert checked == 15 + 15 + 18 + 15 + 15 + 15


def test_silver_blades_hit_dice_match_the_three_arrays_through_the_module():
    """The shape of `test_curse_hit_dice_come_from_the_games_three_arrays`,
    for the six Silver Blades classes."""
    from goldbox import levels

    gen = _gen(SSB)
    tables = levels.SECRET_OF_THE_SILVER_BLADES
    die = _at(gen, SSB_HIT_DIE, 8)
    stop = _at(gen, SSB_LAST_ROLLED, 8)
    flat = _at(gen, SSB_FLAT, 8)
    bits = {"magic-user": 0, "cleric": 1, "thief": 2, "fighter": 3,
           "paladin": 6, "ranger": 7}
    for name, bit in bits.items():
        roll_to = stop[bit] - 1
        for entry in tables.table(name):
            level = entry.level
            expect = (min(level, roll_to) * die[bit]
                     + max(0, level - roll_to) * flat[bit])
            assert entry.hp_max == expect, (name, level)


def test_silver_blades_attacks_match_the_modules_own_bands():
    """`$13EF` and `$13F7` pinned, and `level >= n` -- not `level > n` --
    against the rows the module holds for the three fighting classes."""
    gen = _gen(SSB)
    from goldbox import levels

    tables = levels.SECRET_OF_THE_SILVER_BLADES
    three_to_two = _at(gen, 0x13EF, 8)
    two_attacks = _at(gen, 0x13F7, 8)
    assert three_to_two == [99, 99, 99, 7, 7, 99, 7, 8]
    assert two_attacks == [99, 99, 99, 13, 99, 99, 13, 15]
    bits = {"fighter": 3, "paladin": 6, "ranger": 7}
    for name, bit in bits.items():
        a, b = three_to_two[bit], two_attacks[bit]
        for entry in tables.table(name):
            expect = 1 if entry.level < a else 1.5 if entry.level < b else 2
            assert entry.attacks == expect, (name, entry.level)


def test_silver_blades_ceilings_and_racial_limits_match_the_module():
    """`$17D0` against `ceilings`, `$17E0` rows 1-5 against `racial_limits`,
    and row 6 (human) asserted to be the synthesised row rather than read."""
    from goldbox import levels

    gen = _gen(SSB)
    tables = levels.SECRET_OF_THE_SILVER_BLADES
    order = tables.class_order
    caps = _at(gen, 0x17D0, 8)
    for bit, name in enumerate(order):
        if name is None:
            continue
        assert caps[bit] == tables.ceiling(name), name
    where, guard = coldread.racial_limits(gen, SSB, BASE)
    assert (where, guard) == (0x17E0, 6)
    rows = dict(tables.racial_limits)
    for code in range(1, guard):
        assert rows[code] == tuple(_at(gen, where + (code - 1) * 8, 8)), code
    # Row 6, the human, is not read: $178A refuses to index race 6 at all.
    assert rows[6] == (levels.UNLIMITED, levels.UNLIMITED, levels.UNLIMITED,
                       levels.UNLIMITED, 0, 0, levels.UNLIMITED,
                       levels.UNLIMITED)


def test_the_shipped_partys_saves_reproduce_through_the_module():
    """The same six characters as
    `test_silver_blades_saving_throws_reproduce_ssis_own_party` above, now
    through `goldbox/levels.py:saving_throws` -- what the character sheet and
    `goldbox/levelup.py` actually call -- rather than a hand-rolled
    reproduction of the GEN masks."""
    from goldbox import levels
    from tests.test_silverblades import _party

    sg0, _sg1 = _party()
    checked = 0
    for slot in sg0.characters:
        record = slot.record
        class_levels = {}
        for field, name in (("level_magic_user", "magic-user"),
                            ("level_cleric", "cleric"),
                            ("level_thief", "thief"),
                            ("level_fighter", "fighter"),
                            ("level_paladin", "paladin"),
                            ("level_ranger", "ranger")):
            level = record.get(field)
            if level:
                class_levels[name] = level
        stored = tuple(record.get(f) for f in
                       ("save_paralysis", "save_petrification", "save_wands",
                        "save_breath", "save_spell"))
        got = levels.saving_throws(class_levels, record.get("race"),
                                   record.get("constitution"), game=SSB)
        assert got == stored, (record.name, got, stored)
        checked += 1
    assert checked == 6, f"the shipped party is six characters, not {checked}"


def test_the_shipped_partys_cards_read_silver_blades_thresholds():
    """MORGAINE, DOMINIC and EPONA each hold a level Pool of Radiance's tables
    have no room for -- this is the test that fails if `automap/live.py`
    passes `game` to `_classes` but `characters` forgets to pass it on."""
    from automap import live
    from tests.test_silverblades import _party

    sg0, sg1 = _party()
    characters = {c.name: c for c in live.characters(sg0, sg1)}

    morgaine = next(c for c in characters["MORGAINE"].classes
                    if c.name == "magic-user")
    assert morgaine.next_threshold == 250001 and not morgaine.at_ceiling

    dominic = next(c for c in characters["DOMINIC"].classes
                  if c.name == "cleric")
    assert dominic.next_threshold == 225001 and not dominic.at_ceiling

    epona = next(c for c in characters["EPONA"].classes
                if c.name == "fighter")
    assert epona.next_threshold == 250001 and not epona.at_ceiling

    # MALACHITE is the control: Pool of Radiance and Silver Blades agree at
    # thief 8 / fighter 7, so this was already right before #187.
    malachite = {c.name: c for c in characters["MALACHITE"].classes}
    assert malachite["thief"].next_threshold == 110001
    assert malachite["fighter"].next_threshold == 125001
