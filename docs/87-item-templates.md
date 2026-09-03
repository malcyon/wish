# Item templates

**Generated** — run `python3 tools/gentemplates.py`. Every distinct item
record on the eight game disks, read out of the `ITEMFILE*` shop and
encounter lists.

Name any of these as a `template:` in a `wish` item entry and the whole
16-byte record is copied, then your fields are applied over it:

```yaml
      - template: LONG SWORD +1
        readied: true
```

This is the right way to add a magical item. Building one from `words`
and `type` leaves the bytes we do not understand at zero; a template
brings whatever the game actually puts there — including the effect
bytes at `+13`–`+15`, which on a scroll are its spells.

163 items.

| Item | Cost | Weight | Effect |
|---|---|---|---|
| ARROW(S) | 0 gp | 0.4 lb | 1d6 damage (1d6 vs large); fighter |
| ARROW(S) +1 | 100 gp | 0.4 lb | 1d6 damage (1d6 vs large); fighter |
| AWL PIKE | 3 gp | 8.0 lb | 1d6 damage (1d12 vs large); fighter |
| BANDED MAIL | 90 gp | 35.0 lb | AC 4; cleric, fighter |
| BANDED MAIL +1 | 3000 gp | 35.0 lb | AC 4; cleric, fighter |
| BARDICHE | 7 gp | 12.5 lb | 2d4 damage (3d4 vs large); fighter |
| BASTARD SWORD | 25 gp | 10.0 lb | 2d4 damage (2d8 vs large); fighter |
| BATTLE AXE | 5 gp | 7.5 lb | 1d8 damage (1d8 vs large); fighter |
| BEC DE CORBIN | 6 gp | 10.0 lb | 1d8 damage (1d6 vs large); fighter |
| BILL-GUISARME | 6 gp | 15.0 lb | 2d4 damage (1d10 vs large); fighter |
| BO STICK | 1 gp | 1.5 lb | 1d6 damage (1d3 vs large); fighter |
| BRACERS AC4 | 18000 gp | 0.0 lb | AC 10; magic-user, cleric, thief, fighter |
| BRASS DRAGON FIGURINE | 75 gp | 0.0 lb | magic-user, cleric, thief, fighter |
| BRASS KEY | 1 gp | 0.0 lb | magic-user, cleric, thief, fighter |
| BRASS MIRROR | 10 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| BROAD SWORD | 10 gp | 7.5 lb | 2d4 damage (1d6+1 vs large); thief, fighter |
| BROAD SWORD -2 CURSED | 0 gp | 7.5 lb | 2d4 damage (1d6+1 vs large); thief, fighter |
| CHAIN MAIL | 75 gp | 30.0 lb | AC 5; cleric, fighter |
| CHAIN MAIL +1 | 3500 gp | 30.0 lb | AC 5; cleric, fighter |
| CHAIN(S) OF BONE | 0 gp | 15.0 lb | magic-user, cleric, thief, fighter |
| CLERICAL SCROLL OF RESTORATION | 1800 gp | 1.0 lb | cleric |
| CLERICAL SCROLL WITH 2 SPELLS | 7500 gp | 2.5 lb | cleric |
| CLERICAL SCROLL WITH 3 SPELLS | 4500 gp | 2.5 lb | cleric |
| CLOAK OF DISPLACEMENT | 17500 gp | 3.0 lb | AC +0; magic-user, cleric, thief, fighter |
| CLUB | 1 gp | 3.0 lb | 1d6 damage (1d3 vs large); range 4; cleric, thief, fighter |
| COMPOSITE LONG BOW | 100 gp | 8.0 lb | 1d6 damage (1d6 vs large); range 22; fighter |
| COMPOSITE SHORT BOW | 75 gp | 5.0 lb | 1d6 damage (1d6 vs large); range 19; fighter |
| COPPER BRAZIER | 1 gp | 70.0 lb | magic-user, cleric, thief, fighter |
| CURSED NECKLACE | 20 gp | 0.0 lb | AC +0; magic-user, cleric, thief, fighter |
| DAGGER | 2 gp | 1.0 lb | 1d4 damage (1d3 vs large); range 4; magic-user, thief, fighter |
| DAGGER +1 | 500 gp | 1.0 lb | 1d4 damage (1d3 vs large); range 4; magic-user, thief, fighter |
| DART | 0 gp | 0.5 lb | 1d3 damage (1d2 vs large); range 6; magic-user, thief, fighter |
| DIAMOND NECKLACE | 50000 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| DUST COVERED BOOTS | 0 gp | 10.0 lb | magic-user, cleric, thief, fighter |
| DUST OF DISAPPEARANCE | 8000 gp | 2.0 lb | magic-user, cleric, thief, fighter |
| EFREETI BOTTLE | 35000 gp | 0.0 lb | magic-user, cleric, thief, fighter |
| ELECTRUM DECANTER | 15 gp | 10.0 lb | magic-user, cleric, thief, fighter |
| EMERALD BROACH | 8000 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| FAUCHARD | 3 gp | 6.0 lb | 1d6 damage (1d8 vs large); fighter |
| FAUCHARD-FORK | 8 gp | 8.0 lb | 1d8 damage (1d10 vs large); fighter |
| FINE COMPOSITE LONG BOW | 25000 gp | 6.0 lb | 1d6 damage (1d6 vs large); range 20; fighter |
| FINE OPAL PENDANT | 28500 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| FINE TAPESTRY | 5000 gp | 80.0 lb | magic-user, cleric, thief, fighter |
| FLAIL | 3 gp | 15.0 lb | 1d6+1 damage (2d4 vs large); cleric, fighter |
| FLASK OF OIL | 1 gp | 3.0 lb | 2d6 damage (2d6 vs large); range 4; magic-user, cleric, thief, fighter |
| FUNGUS COVERED TAPESTRY | 2 gp | 120.0 lb | magic-user, cleric, thief, fighter |
| GAUNTLETS OF OGRE POWER | 15000 gp | 4.0 lb | magic-user, cleric, thief, fighter |
| GLAIVE | 6 gp | 7.5 lb | 1d6 damage (1d10 vs large); fighter |
| GLAIVE-GUISARME | 10 gp | 10.0 lb | 2d4 damage (2d6 vs large); fighter |
| GOLD BANDED WAND | 100 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| GOLD CHAIN(S) | 100 gp | 0.0 lb | magic-user, cleric, thief, fighter |
| GOLD LIGHTNING FIGURINE | 650 gp | 0.0 lb | magic-user, cleric, thief, fighter |
| GOLD SCARAB | 4500 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| GOLD STATUETTE | 500 gp | 5.0 lb | magic-user, cleric, thief, fighter |
| GUISARME | 5 gp | 8.0 lb | 2d4 damage (1d8 vs large); fighter |
| GUISARME-VOULGE | 7 gp | 15.0 lb | 2d4 damage (2d4 vs large); fighter |
| HALBERD | 9 gp | 17.5 lb | 1d10 damage (2d6 vs large); fighter |
| HAMMER | 1 gp | 5.0 lb | 1d4+1 damage (1d4 vs large); range 4; cleric, fighter |
| HAMMER +1 | 2500 gp | 5.0 lb | 1d4+1 damage (1d4 vs large); range 4; cleric, fighter |
| HAMMER +3 | 11787 gp | 5.0 lb | 1d4+1 damage (1d4 vs large); range 4; cleric, fighter |
| HAND AXE | 1 gp | 5.0 lb | 1d6 damage (1d4 vs large); range 4; fighter |
| HAND AXE +1 | 1750 gp | 5.0 lb | 1d6 damage (1d4 vs large); range 4; fighter |
| HEAVY CROSSBOW | 20 gp | 8.0 lb | 1d6 damage (1d6 vs large); range 20; fighter |
| HUGE TAPESTRY | 300 gp | 80.0 lb | magic-user, cleric, thief, fighter |
| INCENSE | 1 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| IRON HOLY SYMBOL OF TEMPUS | 2 gp | 4.0 lb | magic-user, cleric, thief, fighter |
| JAVELIN | 0 gp | 2.0 lb | 1d6 damage (1d6 vs large); range 7; fighter |
| JEWEL STUDDED BOWL | 300 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| JEWELLED DRAGON STATUETTE | 350 gp | 2.0 lb | magic-user, cleric, thief, fighter |
| JEWELLED SILVER WINGS | 1050 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| JO STICK | 1 gp | 4.0 lb | 1d6 damage (1d4 vs large); fighter |
| LEATHER ARMOR | 5 gp | 15.0 lb | AC 8; cleric, thief, fighter |
| LEATHER ARMOR +4 | 15000 gp | 15.0 lb | AC 8; cleric, thief, fighter |
| LEATHER HOLY SYMBOL | 0 gp | 25.6 lb | magic-user, cleric, thief, fighter |
| LIGHT CROSSBOW | 12 gp | 5.0 lb | 1d4 damage (1d4 vs large); range 19; fighter |
| LONG BOW | 60 gp | 10.0 lb | 1d6 damage (1d6 vs large); range 22; fighter |
| LONG SWORD | 15 gp | 6.0 lb | 1d8 damage (1d12 vs large); thief, fighter |
| LONG SWORD +1 | 2000 gp | 6.0 lb | 1d8 damage (1d12 vs large); thief, fighter |
| LONG SWORD +2 | 4000 gp | 6.0 lb | 1d8 damage (1d12 vs large); thief, fighter |
| LONG SWORD +2 ,FLAMETONGUE | 4500 gp | 6.0 lb | 1d8 damage (1d12 vs large); thief, fighter |
| LONG SWORD +3 | 7000 gp | 6.0 lb | 1d8 damage (1d12 vs large); thief, fighter |
| LUCERN HAMMER | 7 gp | 15.0 lb | 2d4 damage (1d6 vs large); fighter |
| MACE | 8 gp | 10.0 lb | 1d6+1 damage (1d6 vs large); cleric, fighter |
| MACE +1 | 3000 gp | 10.0 lb | 1d6+1 damage (1d6 vs large); cleric, fighter |
| MACE +2 | 4500 gp | 10.0 lb | 1d6+1 damage (1d6 vs large); cleric, fighter |
| MANUAL OF BODILY HEALTH | 50000 gp | 20.0 lb | magic-user, cleric, thief, fighter |
| MILITARY FORK | 4 gp | 7.5 lb | 1d8 damage (2d4 vs large); fighter |
| MILITARY PICK | 8 gp | 6.0 lb | 1d6+1 damage (2d4 vs large); fighter |
| MORNING STAR | 5 gp | 12.5 lb | 2d4 damage (1d6+1 vs large); fighter |
| MORNING STAR +1 | 3000 gp | 12.5 lb | 2d4 damage (1d6+1 vs large); fighter |
| MU SCROLL WITH 1 SPELL | 300 gp | 1.0 lb | magic-user |
| MU SCROLL WITH 3 SPELLS | 2100 gp | 2.5 lb | magic-user |
| PADDED ARMOR | 4 gp | 10.0 lb | AC 8; cleric, fighter |
| PARTISAN | 10 gp | 8.0 lb | 1d6 damage (1d6+1 vs large); fighter |
| PASS | 0 gp | 0.0 lb | AC 0; no class may use it |
| PEARL NECKLACE | 400 gp | 0.0 lb | magic-user, cleric, thief, fighter |
| PLATE MAIL | 400 gp | 45.0 lb | AC 3; cleric, fighter |
| PLATE MAIL +2 | 10500 gp | 45.0 lb | AC 3; cleric, fighter |
| PLATINUM SPHERE | 18500 gp | 3.0 lb | magic-user, cleric, thief, fighter |
| POTION EXTRA HEALING | 800 gp | 2.5 lb | magic-user, cleric, thief, fighter |
| POTION OF GIANT STRENGTH | 500 gp | 2.5 lb | magic-user, cleric, thief, fighter |
| POTION OF HEALING | 200 gp | 2.5 lb | magic-user, cleric, thief, fighter |
| POTION OF SPEED | 600 gp | 2.5 lb | magic-user, cleric, thief, fighter |
| QUARREL(S) | 0 gp | 0.3 lb | 1d4 damage (1d4 vs large); fighter |
| QUARTER STAFF | 1 gp | 5.0 lb | 1d6 damage (1d6 vs large); magic-user, cleric, fighter |
| QUARTER STAFF +1 | 1000 gp | 5.0 lb | 1d6 damage (1d6 vs large); magic-user, cleric, fighter |
| RANSEUR | 4 gp | 5.0 lb | 2d4 damage (2d4 vs large); fighter |
| RING | 1 gp | 0.0 lb | magic-user, cleric, thief, fighter |
| RING MAIL | 30 gp | 25.0 lb | AC 7; cleric, fighter |
| RING OF FEATHER FALLING | 5000 gp | 0.0 lb | magic-user, cleric, thief, fighter |
| RING OF FIRE RESISTANCE | 5000 gp | 0.1 lb | magic-user, cleric, thief, fighter |
| RING OF PROTECTION +1 | 10000 gp | 0.0 lb | AC +0; magic-user, cleric, thief, fighter |
| ROTTING LEATHER SADDLE | 1 gp | 25.0 lb | magic-user, cleric, thief, fighter |
| ROTTING RUG | 1 gp | 100.0 lb | magic-user, cleric, thief, fighter |
| SCALE ARMOR | 0 gp | 40.0 lb | AC 6; cleric, fighter |
| SCALE MAIL | 45 gp | 40.0 lb | AC 6; cleric, fighter |
| SCIMITAR | 15 gp | 4.0 lb | 1d8 damage (1d8 vs large); fighter |
| SCIMITAR +1 | 2000 gp | 4.0 lb | 1d8 damage (1d8 vs large); fighter |
| SHEET(S) OF GOLD | 3 gp | 0.0 lb | magic-user, cleric, thief, fighter |
| SHIELD | 15 gp | 10.0 lb | AC +1; cleric, fighter |
| SHIELD +1 | 2500 gp | 15.0 lb | AC +1; cleric, fighter |
| SHIELD +2 | 5000 gp | 5.0 lb | AC +1; cleric, fighter |
| SHORT BOW | 15 gp | 5.0 lb | 1d6 damage (1d6 vs large); range 16; fighter |
| SHORT BOW +1 | 3500 gp | 5.0 lb | 1d6 damage (1d6 vs large); range 16; fighter |
| SHORT SWORD | 8 gp | 3.5 lb | 1d6 damage (1d8 vs large); thief, fighter |
| SHORT SWORD +1 | 2000 gp | 3.5 lb | 1d6 damage (1d8 vs large); thief, fighter |
| SHORT SWORD +2 | 4000 gp | 3.5 lb | 1d6 damage (1d8 vs large); thief, fighter |
| SILVER ARROW(S) | 20 gp | 0.4 lb | 1d6 damage (1d6 vs large); fighter |
| SILVER BASTARD SWORD | 250 gp | 10.0 lb | 2d4 damage (2d8 vs large); fighter |
| SILVER BROAD SWORD | 100 gp | 7.5 lb | 2d4 damage (1d6+1 vs large); thief, fighter |
| SILVER BROOCH | 2 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| SILVER CHAIN MAIL | 750 gp | 30.0 lb | AC 5; cleric, fighter |
| SILVER DAGGER | 20 gp | 1.0 lb | 1d4 damage (1d3 vs large); range 4; magic-user, thief, fighter |
| SILVER DRAGON STATUETTE | 2500 gp | 2.0 lb | magic-user, cleric, thief, fighter |
| SILVER HOLY SYMBOL OF SUNE | 50 gp | 4.0 lb | magic-user, cleric, thief, fighter |
| SILVER LONG SWORD | 150 gp | 6.0 lb | 1d8 damage (1d12 vs large); thief, fighter |
| SILVER MACE | 80 gp | 10.0 lb | 1d6+1 damage (1d6 vs large); cleric, fighter |
| SILVER MIRROR | 20 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| SILVER PLATE MAIL | 4000 gp | 45.0 lb | AC 3; cleric, fighter |
| SILVER QUARREL(S) | 20 gp | 0.3 lb | 1d4 damage (1d4 vs large); fighter |
| SILVER RING | 90 gp | 0.0 lb | magic-user, cleric, thief, fighter |
| SILVER SCARAB | 100 gp | 1.0 lb | magic-user, cleric, thief, fighter |
| SILVER SHORT SWORD | 80 gp | 3.5 lb | 1d6 damage (1d8 vs large); thief, fighter |
| SILVER TWO-HANDED SWORD | 300 gp | 25.0 lb | 1d10 damage (3d6 vs large); fighter |
| SLING | 0 gp | 0.2 lb | 1d4+1 damage (1d6+1 vs large); range 21; thief, fighter |
| SLING OF SEEKING +2 | 7000 gp | 1.0 lb | 1d4+1 damage (1d6+1 vs large); range 21; thief, fighter |
| SPEAR | 1 gp | 5.0 lb | 1d6 damage (1d8 vs large); range 4; fighter |
| SPEAR +1 | 3000 gp | 4.0 lb | 1d6 damage (1d8 vs large); range 4; fighter |
| SPETUM | 3 gp | 5.0 lb | 1d6+1 damage (2d6 vs large); fighter |
| SPLINT MAIL | 80 gp | 40.0 lb | AC 4; cleric, fighter |
| STONE STATUETTE | 30 gp | 25.0 lb | magic-user, cleric, thief, fighter |
| STUDDED LEATHER ARMOR | 15 gp | 20.0 lb | AC 7; cleric, fighter |
| TAPESTRY | 250 gp | 50.0 lb | magic-user, cleric, thief, fighter |
| TRIDENT | 4 gp | 5.0 lb | 1d6+1 damage (3d4 vs large); fighter |
| TWO-HANDED SWORD | 30 gp | 25.0 lb | 1d10 damage (3d6 vs large); fighter |
| TWO-HANDED SWORD +1 +3 VS UNDEAD | 3500 gp | 25.0 lb | 1d10 damage (3d6 vs large); fighter |
| TWO-HANDED SWORD +2 | 4000 gp | 9.0 lb | 1d10 damage (3d6 vs large); fighter |
| VIAL OF HOLY WATER | 25 gp | 1.0 lb | 1d1-1 damage (1d1-1 vs large); range 4; magic-user, cleric, thief, fighter |
| VOULGE | 2 gp | 12.5 lb | 2d4 damage (2d4 vs large); fighter |
| WAND OF LIGHTNING BOLT | 900 gp | 3.0 lb | magic-user |
| WAND OF MAGIC MISSILES | 35000 gp | 3.0 lb | magic-user, cleric, thief, fighter |
| WOOD HOLY SYMBOL | 500 gp | 2.0 lb | magic-user, cleric, thief, fighter |
| WOODEN HOLY SYMBOL OF TYR | 1 gp | 3.0 lb | magic-user, cleric, thief, fighter |

