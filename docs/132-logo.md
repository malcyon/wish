# A logo, and an icon Windows will show

**Status: built and wired, with a stand-in for the current glyph.** Task
**P74**. Donald — *"We need an icon for the app that Windows will show in the
task bar. Until I can hire an artist, we can use something from Font
Awesome."* That mark was Font Awesome's `hat-wizard`; it shipped from
2026-08 until `#167 (Replace the remaining Font Awesome icons with game-icons.net ones)`, when Donald asked for a different stand-in from his
game-icons.net archive while an artist is commissioned: *"I am paying an
artist to create an app logo and icon. In the meantime, please use
`pointy-hat`."*

The mark is `pointy-hat` (Lorc, game-icons.net) on an indigo tile. It is
generated from `ui/icons.py`, so it cannot drift from the glyph the program
paints, and there is no artist to wait for. §5 is what shipped, §6 is
`pointy-hat`'s own geometry and why it is left alone, and §1 and §2 are the
brief for the artist, when there is one. Most of what follows was written
against `hat-wizard` and is kept as the record of that decision -- the
sections that describe *today's* glyph rather than the brief are marked.

---

## The verdict

* **The glyph is `pointy-hat`** (Lorc, game-icons.net, CC BY 3.0), path data
  verbatim from the artist's own SVG, in `ui/icons.py` under `GAME_ICONS`. A
  peaked hat with a folded, curling brim. Wish is a spell; the hat is the
  spellcaster. **This is a stand-in**, not the chosen mark -- see the intro.
* **game-icons.net as an app icon is legal**, the same way Font Awesome was:
  CC BY 3.0 is satisfied by the credit in the README and in Help > About, and
  the attribution does not have to be *on* the icon. What CC BY does not grant
  is exclusivity: this is a mark anyone else may also ship. §3.
* **The drawing is not modified.** It is recoloured and placed on a tile, and
  the path data is Lorc's, point for point, at every size. §6.
* **The silhouette comes apart at 32px and up, and that is measured, not a
  fault.** `pointy-hat` carries fold lines as fine strokes; at 16--24px they
  are too fine to survive rasterising and the hat reads as one piece, and from
  32px up they resolve into three. §6.
* **What it looks like at 16 px, honestly.** A pale, curved cone over a
  scalloped brim, inside a rounded indigo square -- narrower at the top,
  flaring through the lower two-thirds. It reads as a hat at 16 and is
  unmistakable from 32 up. Checked by rendering, not assumed.

---

## 1. Which pixel sizes, and which of them matter

Donald asked. Every size the program or a packager actually asks for, and
whether anything is lost by getting it wrong.

| size | where it is used | does it matter |
|---|---|---|
| **16** | Windows title bar, Alt-Tab, Explorer's List and Details views, the taskbar with small buttons on | **yes** — the smallest anyone ever sees, and the first one to look at |
| **20** | Windows' 16 px slots at 125 % display scaling | on a scaled laptop screen, yes; nothing else asks for it |
| **22** | GNOME's panel, via the hicolor theme | on GNOME, yes; no Windows path wants it |
| **24** | Windows' 16 px slots at 150 %; KDE's panel, via hicolor | yes, for those two |
| **32** | the Windows taskbar button at 100 %, and the desktop shortcut | **yes** — with 16, the pair that matter most |
| **40** | Windows' 32 px slots at 250 % scaling | rarely; conventional, and cheap to render |
| **48** | Explorer's Medium and Large icon views, the shell's default shortcut size, hicolor | yes — this is the icon in a folder window |
| **64** | Windows' 32 at 200 % scaling, hicolor, **and Help > About on a 1× display** | yes |
| **128** | Help > About on a 2× display, and hicolor's large slot | yes on a HiDPI screen |
| **192** | Help > About on a 3× display | painted on demand by `appicon.pixmap`; nothing is stored |
| **256** | Explorer's Extra Large view and the file's Properties sheet, hicolor, and `assets/wish.png` for a README | yes, and it is the one size anyone looks at closely |

The two committed containers do not hold the same list, and that is deliberate:
`wish.ico` carries 16, 20, 24, 32, 40, 48, 64 and 256 because those are the
sizes Windows asks for, and the hicolor tree carries 16, 22, 24, 32, 48, 64,
128 and 256 because those are the freedesktop directories. 22 means nothing to
Windows; 20 and 40 mean nothing to GNOME. `appicon.WINDOW_SIZES` — what Qt gets
for the running window — is the union of the useful ones.

Every one of them is **rendered from the vector at its own size**, never
downscaled from a bigger one.

---

## 1b. Every asset, with real sizes

This is the table to hand an artist. One master vector; everything else is a
size-tuned export from it, and the small ones are **tuned, not scaled** — see
§2.

| asset | pixel sizes | format | background | has to survive |
|---|---|---|---|---|
| **master** | 1024×1024, drawn on a 640-unit grid to match `ui/icons.py` | SVG, filled paths, **no strokes** | transparent | being the only source of everything below |
| **Windows `.ico`** | 16, 20, 24, 32, 40, 48, 64, 256 | ICO — 32-bit BGRA DIB for ≤64, PNG for 256 | transparent | 16 px against a dark *and* a light taskbar |
| **macOS `.icns`** | 16, 32, 64, 128, 256, 512, 1024 (16/32/128/256/512 each ×1 and @2x) | ICNS built from an `.iconset` directory | transparent, glyph inside Apple's rounded square: 824×824 centred in 1024, corner radius ≈185 | the Dock's own drop shadow, which eats the outer edge |
| **Linux hicolor** | 16, 22, 24, 32, 48, 64, 128, 256, plus one `scalable` | PNG per size + SVG | transparent | GNOME's 22 and KDE's 24, which are nobody's export defaults |
| **About dialog** | 64 logical → 64, 128, 192 px for 1×, 2×, 3× | `QPixmap` painted from the vector | the dialog's own ground, light theme and dark | sitting beside three lines of text without shouting |
| **README lockup** | 1200×300, displayed at `width=400` | SVG preferred, PNG fallback | transparent | GitHub's light **and** dark reading themes |
| **GitHub social preview** | 1280×640, safe area 1120×560 | PNG | opaque | being cropped by Slack, Twitter and Discord cards |

### Why those `.ico` entries

A `.ico` is a container. Windows picks the entry nearest the size it wants and
**bilinearly scales when it has to** — a 256 squeezed to 16 is mush, which is
the entire reason a hand-tuned 16 goes in the file.

| size | where Windows uses it |
|---|---|
| **16** | title bar, Alt-Tab, Explorer's List and Details views, the taskbar when "use small taskbar buttons" is on |
| **20, 24, 40** | the same slots at 125 %, 150 % and 250 % display scaling — Windows does not round to 16 or 32, it asks for these |
| **32** | the taskbar button at 100 % scaling and the desktop shortcut. With 16, the pair that matters most |
| **48** | Explorer's Medium and Large icon views, and the shell's default shortcut size |
| **64** | 32 at 200 % scaling |
| **256** | Explorer's Extra Large view, the file's Properties sheet, and anything that shows the exe big |

**Windows takes the taskbar icon from the executable's resource, not from Qt.**
`QApplication.setWindowIcon` sets the title bar, Alt-Tab and the taskbar button
of a *running* window; a pinned shortcut, and the file in Explorer, use the
`.ico` PyInstaller embedded. Both are needed and they must be the same drawing.

---

## 2. What a 16×16 icon can be

State this in the brief, because at 16 pixels almost nothing survives and an
artist asked for a scene will deliver one.

`109-icon-choices.md` already derived the rule the hard way, from a magnified
sheet: **one connected silhouette, every feature at least about 64 units in the
640 box** — a tenth of the width, which is 1.6 px at 16. The failure that kills
a glyph is *separation*, not mush: `hat-wizard`'s brim stops touching its cone
and the icon reads as a shark's fin. That was the app icon's own glyph until
`#167 (Replace the remaining Font Awesome icons with game-icons.net ones)`; the current one, `pointy-hat`, keeps to one piece at 16--24 for the
same reason -- §6.

| reads at 16 | does not |
|---|---|
| one bold silhouette with a strong outline — a cone, a key, an arrow | two or more separate parts (FA's `wand-sparkles` becomes three loose dots) |
| a filled tile with the shape knocked out of it | a shape on transparency, which is grey pixels on an unknown ground |
| at most one or two interior holes, each ≥10 % of the box | fine interior detail, hatching, texture |
| two colours and the background | gradients, shadows, bevels — all of which eat the one pixel of edge |
| a single letterform, if it is heavy | any word, any number of two digits |
| asymmetry that survives a squint | a perspective view of anything |

Two more the artist will not think of: it has to read **against both a dark and
a light taskbar**, so the silhouette cannot depend on being dark; and it has to
be recognisable **in monochrome**, because Windows renders it that way in some
places and screen readers describe it in none.

**"Knocked out" turned out to want one amendment.** Cutting the shape out of
the tile leaves the taskbar showing through the shape, so on a dark desktop a
dark tile carries a dark hole and there is nothing to see. What ships fills the
hat with paper instead: the same silhouette, with a ground guaranteed on both
sides of every edge, and it still reads greyscale.

---

## 3. The attribution question

This project carries game-icons.net path data -- `pointy-hat` among them --
under **CC BY 3.0**, attribution generated into `THIRD_PARTY_LICENSES.md` from
`ui.icons.ARTISTS`, and credited in the README's *Credits* and in
`wish/about.py`.

It carried Font Awesome Free 7.3.1 under **CC BY 4.0** until 2026-09-01, when
`#167 (Replace the remaining Font Awesome icons with game-icons.net ones)` replaced the last glyph anything drew. `fontawesome-LICENSE.txt` went
with it; `git log -- fontawesome-LICENSE.txt` has the file.

**What CC BY obliges, for an application icon.** Wherever the work is
distributed: name the creator (Lorc, for `pointy-hat`), name the licence, link
to it, link to the source, and say if you changed it. It does **not** have to
appear on the icon or in the icon file — "any reasonable manner for the
medium" is the licence's own wording, and a credit in an About box is the
accepted form for software. **wish already discharges this**, in two places.
There is no "changed the drawing" clause to answer, because the drawing is not
changed: the glyph is recoloured and placed, and the path data is Lorc's,
point for point.

Two costs, accepted rather than avoided:

1. **CC BY grants no exclusivity.** Anyone may ship the identical mark under the
   identical terms. A logo is the one asset where that is the point.
2. **The obligation follows the artefact forever.** A `.ico` embedded as a
   Windows resource has nowhere to carry a credit, so the credit lives in a
   dialog the user must open — defensible, but it has to be defended again at
   every new place the mark appears: a store listing, a `.desktop` file, a
   favicon, a screenshot in someone else's article.

And note Font Awesome's own trap, already recorded in `ui/icons.py`: **the
brands are off limits** — the licence forbids brand-logo use and the set ships
`wizards-of-the-coast`. game-icons.net carries no such set.

### Why `pointy-hat`, for now

Donald asked for it by name, as the stand-in while an artist is commissioned
-- see the intro. The reasoning that chose the *idea* of a wizard's hat still
holds: Wish is the ninth-level spell, and a hat is the one thing that says
*magic* without saying *combat* — and the program is a character editor
first. Whether the final mark keeps that idea is the artist's call, not this
document's.

`hat-wizard`, the previous stand-in, is the glyph
[`109-icon-choices.md`](109-icon-choices.md) rejected for the map's
magic-user badge, and that rejection stands where it was made: **the map's
magic-user icon is still `wizard-hat`, ours**, because at 13 px in a map cell
`hat-wizard`'s brim comes away and the glyph is a fin. An app icon is a
different job — 16 is the smallest it is ever drawn, it sits on its own tile
rather than beside a wall, and the sizes that matter most are 32 and up. §6
covers `pointy-hat`'s own geometry at those sizes.

Everything already available, judged as a logo:

| candidate | source | as an app icon |
|---|---|---|
| `hat-wizard` | Font Awesome | **chosen, 2026-08 -- superseded by `pointy-hat` on `#167 (Replace the remaining Font Awesome icons with game-icons.net ones)`** — Donald's call; drawn as Fonticons drew it, §6 as it was |
| `wizard-hat` | ours | the previous mark, and still the map's magic-user glyph |
| `sword` | ours | says combat; the program does not do combat |
| `swords` | ours | reads as a starburst at small sizes, and already means "encounter" on the map |
| `chest`, `hood` | ours | fine glyphs, poor identities — a chest is a file manager, a hood is a VPN |
| `location-dot` | Font Awesome | the other FA pick: it says *map*, and its counter is the 64-unit floor the whole rule was set from |

**When the artist is hired**, the brief is §1 plus §2, and the one thing to buy
that a cheap job will skip: **hand-tuned 16, 24 and 32**, not exports of the
1024. That is most of the work and all of the difference.

---

## 4. Where each asset is used

| place | mechanism | file |
|---|---|---|
| the Windows exe, Explorer, a pinned shortcut | `EXE(..., icon="assets/wish.ico")` | `wish.spec` |
| the taskbar button and title bar of a running window | `app.setWindowIcon(app_icon())`, a pixmap per size so Qt picks rather than scales | `wish/window.py::dress` |
| the taskbar *grouping* on Windows | `SetCurrentProcessExplicitAppUserModelID` before the first window, or a Python-hosted window can group and pin under the interpreter | `wish/window.py::dress` |
| the panel icon on Linux | `app.setDesktopFileName("wish")` — GNOME and KDE match a window to its `.desktop` by app id, and a Wayland window gets a generic icon without it. There is still no `.desktop` file and the Linux artefact is a tarball, so the hicolor PNGs sit under `assets/` waiting for a package | `wish/window.py::dress` |
| Help > About | a hand-built `QMessageBox` with `setIconPixmap(appicon.pixmap(64))`; `QMessageBox.about` paints the platform's information icon and takes no picture | `wish/about.py` |
| the README | an `<img>` at the top — **Donald's file; ask** | `README.md` |
| the icon files themselves | a generator, offscreen, in the shape of `tools/iconsheet.py` | `tools/genicons.py` |

---

## 5. What was built

**The drawing** is `ui/appicon.py`, beside `iconpaint.py` because it is the same
job: `icons.py` path data turned into pixels. `pointy-hat` on a rounded tile,
`#2b3a67` behind `#f7f9fb`, the glyph inset 10 % of the side and centred on its
own ink rather than on its canvas -- which `paint()` never reads as a
constant, so the same code drew `hat-wizard`'s 640 box correctly and draws
`pointy-hat`'s 512 correctly too. Indigo rather than the interface's
near-black `#16202b`: a near-black tile is invisible on Windows' dark
taskbar, and being visible against an unknown ground is the whole reason to
have a tile.

**The generator** is `tools/genicons.py`, offscreen through `ui.iconpaint`
exactly as `tools/iconsheet.py` renders the sheet. Every size is rendered from
the vector; nothing is a downscale of anything. It writes:

| file | what |
|---|---|
| `assets/wish.ico` | 16, 20, 24, 32, 40, 48, 64, 256 — DIB below 256, PNG at 256, 48 KB |
| `assets/icons/hicolor/{N}x{N}/apps/wish.png` | 16, 22, 24, 32, 48, 64, 128, 256 |
| `assets/wish.png` | 256, for a README |

The `.ico` container is written here in `struct` rather than by Pillow. Not for
the fun of it: a `.ico` wants a DIB for the small entries and a PNG for the 256,
and every library that writes one makes that choice for the whole file at once.
Thirty lines buys the mix the shell documents and leaves the generator needing
nothing Qt does not already provide.

**The output is committed.** PyInstaller wants the `.ico` to exist when it reads
`wish.spec`, so generating it in CI would mean a build step before every build;
committing it keeps the release a single command. `tests/test_appicon.py`
re-renders every artefact and compares, so a change to the path data that
nobody regenerated fails the build instead of shipping the old drawing.

**The comparison is pixels within a tolerance**, and it took two goes to get
there. It was **bytes**, and CI went red on every runner: a PNG's bytes are
libpng's and zlib's, `ldd libQt6Gui.so.6` resolves both to the *host's* copies
on Linux, and the Windows wheel bundles its own. Qt promises the pixels, not
the file. So it became **exact pixels**, and that went red too, on all four
runners at once — 8 of 65536 pixels at 256, 8 of 484 at 22, 1 of 4096 at 64,
every one of them out by 1 of 255. Qt's rasteriser does not round the last bit
of an antialiased edge the same way on every host either.

So the comparison allows **2 of 255 on any channel, and 10 % of the pixels
touched at all** — `genicons.TOLERANCE` and `genicons.MOST`. Both bounds are
measured, not chosen:

| perturbation | worst pixel | pixels moved |
|---|---|---|
| the CI rounding noise | 1 of 255 | up to 1.65 % of a square |
| `INSET` 0.10 → 0.1001 | 4 of 255 at 24, 12 at 256 | 4.5 % at 24 |
| `RADIUS` 0.18 → 0.1801 | 3 of 255 at 20, 127 at 256 | 5.0 % at 20 |
| one path point moved by 1/640 | 2 of 255 at 16, 35 at 256 | 1.5 % at 20 |
| a colour changed by one unit of 255 | 6 of 255 | **70 % at every size** |

The magnitude bound has six times the room the noise needs and still catches
every edit above at one size or another; the 10 % bound is what catches the
last row, where a great many pixels move by very little. `tools/genicons.py
--check` uses the same `differences()` and prints both numbers.
`test_the_comparison_still_catches_a_change_to_the_drawing` re-runs the first
three rows as a test, so the tolerance cannot quietly widen.

**The tests measure the drawing, not the file list.** The tile is checked to be
opaque on all four sides and rounded at the corners, the hat is checked to clear
the edge at 16, its widest row is checked to be well below the apex and at
least 8 px across so the brim reads, and the 16 stored in the `.ico` is
compared against a fresh 16 to prove it is not a squeezed 256.
`test_the_hat_stays_pointy_hats_own_shape_at_every_size` is §6 as an
assertion: one piece from 16 to 24, three from 32 to 256, measured against
`pointy-hat`'s own fold lines rather than `hat-wizard`'s cone-and-bar.

**The no-images rule is gone**, so none of this needed working around. Donald,
2026-08: *"You need to remove that test that blocks all pngs. We don't need
that."* `tests/test_repository_contents.py` still refuses disk images,
executables, audio and PDFs, which is the part that was ever about the game.

### Still not done

* **No `.desktop` file and no macOS bundle.** The hicolor PNGs are generated and
  committed, but nothing installs them: the Linux artefact is a tarball. Wire
  them up when there is a package. `.icns` waits for a Mac to test on.
* **No README lockup.** A mark plus the word, 1200×300, is an artist's job or an
  hour in Inkscape; `assets/wish.png` is the mark alone in the meantime.
* **Nobody has seen it on a Windows taskbar.** That is a row for
  [`122-release-testing.md`](122-release-testing.md)'s Windows column, and it
  now has somebody who can tick it.

---

## 6. `pointy-hat`'s own geometry, and why it is left alone

**This section describes the current glyph.** §6 used to be about
`hat-wizard`'s cone-and-bar, kept below for the record.

Lorc draws `pointy-hat` with fold lines as separate strokes -- the brim's
curl, a crease down the crown -- fine enough that at 16--24px they do not
survive rasterising and the silhouette measures as **one** connected piece.
From 32px up there is room to resolve them, and it measures as **three**:
the main hat body, and two slivers where a fold line's antialiasing clears
the paper-versus-tile threshold on both sides. Measured with
`tools/genicons.py`'s own renderer, not assumed from the path.

**It is shipped that way regardless**, for the same reason `hat-wizard` was:
Donald — *"Is the agent modifying the art? We don't want to change the art.
We should not be changing the art."* — and the rule in `.claude/rules/art.md`:
an icon from somebody else's set is drawn the way they drew it, and if it does
not work at a size the answer is a different icon, or not using it at that
size — never nudging the geometry. Recolouring it and putting it on a tile is
composition; moving a point is making art.

So `ui/appicon.py` has no size-dependent geometry at all — `glyph()` hands
back `painter_path("pointy-hat")` and that is the whole of it — and
`tests/test_appicon.py::test_the_hat_stays_pointy_hats_own_shape_at_every_size`
holds it there: one piece at 16, 20, 22 and 24, three from 32 to 256.

If 16 px is one day judged unacceptable, the remedy is a different mark — not
an edited one. It reads at 16 today: see the verdict at the top.

### As it was: `hat-wizard`'s brim

Font Awesome drew `hat-wizard` as three subpaths: the cone, with a four-point
sparkle notched out of its foot; a second sparkle; and the brim, a rounded bar.
**The bar never touched the cone.** The cone's last point was `y=464.1` and the
bar started at `y=512`, so there were 48 units of nothing between them — 7.5 %
of the drawing's height, at every size. That was the drawing, not a defect: a
hat resting on a table.

Rasterised on the tile, with the glyph inset 10 %, the gap was `0.077 × size`
pixels — 1.2 px at 16, 1.7 at 22, 2.5 at 32 and rising. At 16 and 20 it was
tight enough that the rows either side of it were part-covered, so the gap
read as a smudge rather than as a line.

One finding from those experiments is worth keeping regardless of the glyph:
filling a sparkle or a fold line in, for a cleaner small silhouette, is
**actively worse** -- a notch or a crease is not decoration, and without it a
glyph loses exactly the feature that keeps it from reading as a blob or a
fin.
