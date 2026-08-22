# A logo, and an icon Windows will show

**Status: plan. Nothing is drawn, nothing is wired.** Task **P74**. Donald —
*"We need an icon for the app that Windows will show in the task bar. Until I
can hire an artist, we can use something from Font Awesome."*

---

## The verdict

* **The interim glyph is `wizard-hat`, and it is *ours*, not Font Awesome's.**
  It already ships in `ui/icons.py`, it already passes the 13-pixel sheet that
  [`109-icon-choices.md`](109-icon-choices.md) judges every glyph on, and being
  ours it carries no licence obligation at all. Wish is a spell; the hat is the
  spellcaster.
* **Font Awesome as an app icon is legal today and still the wrong choice.**
  CC BY 4.0 is satisfied by the credit already in the README and in
  Help > About — the attribution does not have to be *on* the icon. But CC BY
  grants no exclusivity, so a logo built on it is a logo anyone else may also
  ship. §3.
* **Generate the icon files at build time; commit no rasters.** `ui/icons.py`
  is vector source and `ui/iconpaint.py` already renders it, so a `.ico` is a
  30-line generator rather than a drawing. §5.
* **The no-images rule is not what blocks this.** `.svg`, `.ico` and `.icns` are
  *not* in `FORBIDDEN_SUFFIXES` — only `.png`, `.jpg`, `.gif`, `.bmp` and
  `.webp` are. The rule blocks the README's two screenshots and nothing else we
  need. §5.
* **The README screenshots are broken on GitHub right now**, whatever is decided
  about the rule: `images/` is untracked, so both `<img src="images/…">` tags
  point at nothing a stranger can fetch. §5.

---

## 1. Every asset, with real sizes

This is the table to hand an artist. One master vector; everything else is a
size-tuned export from it, and the small ones are **tuned, not scaled** — see
§2.

| asset | pixel sizes | format | background | has to survive |
|---|---|---|---|---|
| **master** | 1024×1024, drawn on a 640-unit grid to match `ui/icons.py` | SVG, filled paths, **no strokes** | transparent | being the only source of everything below |
| **Windows `.ico`** | 16, 20, 24, 32, 40, 48, 64, 256 | ICO — 32-bit BGRA BMP for ≤64, PNG for 256 | transparent | 16 px against a dark *and* a light taskbar |
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

Eight entries, PNG-compressed at 256, come to roughly 100 KB.

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
and the icon reads as a shark's fin.

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

---

## 3. The Font Awesome interim, and the attribution question

This project already carries Font Awesome Free 7.3.1 path data in `ui/icons.py`
under **CC BY 4.0**, licence text in
[`licences/fontawesome-LICENSE.txt`](licences/fontawesome-LICENSE.txt), credited
in the README's *Credits* and in `wish/about.py`.

**What CC BY 4.0 obliges, for an application icon.** Wherever the work is
distributed: name the creator (Fonticons, Inc.), name the licence, link to it,
link to the source, and say if you changed it. It does **not** have to appear on
the icon or in the icon file — "any reasonable manner for the medium" is the
licence's own wording, and a credit in an About box is the accepted form for
software. **wish already discharges this**, in two places. Shipping a Font
Awesome glyph as `wish.exe`'s icon would be compliant with no further work.

Two reasons to use our own drawing anyway:

1. **CC BY grants no exclusivity.** Anyone may ship the identical mark under the
   identical terms. A logo is the one asset where that is the point.
2. **The obligation follows the artefact forever.** A `.ico` embedded as a
   Windows resource has nowhere to carry a credit, so the credit lives in a
   dialog the user must open — defensible, but it has to be defended again at
   every new place the mark appears: a store listing, a `.desktop` file, a
   favicon, a screenshot in someone else's article.

And note the set's own trap, already recorded in `ui/icons.py`: **the brands are
off limits** — the licence forbids brand-logo use and the set ships
`wizards-of-the-coast`.

### The recommendation: `wizard-hat`

Ours, drawn here, in `ui/icons.py` under `OURS`. Cone joined to brim, one
silhouette, so it cannot come apart; it survives 13 px on the sheet and is
already painted by `ui/iconpaint.py` at every size the program uses.

It suits the name. Wish is the ninth-level spell, and the hat is the only glyph
in the set that says *magic* without saying *combat* — and the program is a
character editor first. Set it **knocked out of a filled tile**, not floating on
transparency, for the reason in §2.

Everything already available, judged as a logo:

| candidate | source | as an app icon |
|---|---|---|
| **`wizard-hat`** | ours | **recommended** — distinctive, one mass, no licence |
| `sword` | ours | says combat; the program does not do combat |
| `swords` | ours | reads as a starburst at small sizes, and already means "encounter" on the map |
| `chest`, `hood` | ours | fine glyphs, poor identities — a chest is a file manager, a hood is a VPN |
| `location-dot` | Font Awesome | the best FA pick if Donald wants FA specifically: it says *map*, and its counter is the 64-unit floor the whole rule was set from |
| `hat-wizard` | Font Awesome | **do not** — this is the glyph 109 rejected; its brim separates at 13 px |

**When the artist is hired**, the brief is §1 plus §2, and the one thing to buy
that a cheap job will skip: **hand-tuned 16, 24 and 32**, not exports of the
1024. That is most of the work and all of the difference.

---

## 4. Where each asset is used, and what changes

| place | mechanism | file |
|---|---|---|
| the Windows exe, Explorer, a pinned shortcut | PyInstaller `EXE(..., icon="build/icons/wish.ico")` | `wish.spec` |
| the taskbar button and title bar of a running window | `app.setWindowIcon(QIcon(...))`, with a pixmap added per size so Qt picks rather than scales | `wish/window.py::run` |
| the taskbar *grouping*, on Windows | `SetCurrentProcessExplicitAppUserModelID` before the first window, or Windows may group and pin the button wrongly | `wish/window.py::run` |
| the panel icon on Linux | `app.setDesktopFileName("wish")` — GNOME and KDE match a window to its `.desktop` by app id, and show a generic icon without it. There is no `.desktop` file in the tree today and the Linux artefact is a tarball, so this is speculative until we package | `wish/window.py::run`, plus a new `packaging/wish.desktop` |
| Help > About | `QMessageBox.about` cannot take a picture. It becomes a `QMessageBox` built by hand with `setIconPixmap(icon_pixmap("wizard-hat", 64, colour))` | `wish/about.py` |
| the README | an `<img>` at the top, above the two screenshots | `README.md` — **Donald's; ask** |
| the icon files themselves | a generator, offscreen, in the shape of `tools/iconsheet.py` | new `tools/genicons.py` |
| CI | run the generator before `pyinstaller` | `.github/workflows/release.yml` |

---

## 5. Where the artefacts live — and the no-images rule

**The rule is narrower than it looks.** `tests/test_repository_contents.py`'s
`FORBIDDEN_SUFFIXES` blocks `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp` and
`.pdf`. It does **not** block `.svg`, `.ico` or `.icns`. So the artist's master
vector, and a built `.ico`, can be committed today with no change to the rule at
all. What the rule blocks is PNG — which is to say the README's screenshots and
the Linux hicolor set.

**Recommendation, in three parts.**

1. **Generate the icons; commit nothing rendered.** `tools/genicons.py`, with
   `QT_QPA_PLATFORM=offscreen` exactly as `tools/iconsheet.py` does it, renders
   `ui/icons.py` into `build/icons/wish.ico`, the hicolor PNGs and a macOS
   `.iconset`. One source of truth, no rasters in the tree, no rule change, and
   the icon can never drift from the glyph the program paints. `build/` joins
   `.gitignore`. The `.ico` writer is `Pillow` — a build-time dependency only,
   in the same place `pyinstaller` already is, not in `[gui]`.
2. **Commit the artist's master as SVG** when there is one, in `assets/`. Legal
   under the rule as it stands; it is the drawing, and the generator's input.
3. **Host the README screenshots outside the repository.** GitHub serves
   anything dropped into an issue comment from its user-content CDN
   indefinitely; point the two `<img>` tags at absolute URLs. This costs
   nothing, renders for a stranger, needs no rule change — and avoids a second
   problem that is *not* mechanical:

**The automapper screenshot is a rendering of a GEO file.** It shows the shape
of Phlan's streets, drawn from SSI's own map data. The character-editor
screenshot shows the player's own party and is ours; that one is unambiguous.
The rule that blocks both was aimed at the game's art, and on the automapper
shot it is arguably aimed correctly. That is a judgment for Donald, not for the
test, and hosting the images elsewhere sidesteps having to make it in the
repository's history.

**If Donald would rather have the screenshots in the tree**, the smallest honest
change is a named directory with a per-file allowlist, in the exact shape of
`ALLOWED_FIXTURES`: `assets/` exempt from `FORBIDDEN_SUFFIXES`, and a second
test asserting every file under `assets/` is on a list naming what it is and why
it is ours. **Do not exempt a directory without the per-file list.** The reason
the current rule works is that it is not a judgment call, and an unlisted
exemption turns it back into one.

**Either way, fix the README's tags.** `images/` is untracked — `git status`
shows `?? images/` — so both screenshots are broken links on GitHub today and
always have been. Report the wording; the file is Donald's.

---

## 6. What it costs

| work | cost | when |
|---|---|---|
| `tools/genicons.py` + `.ico` + `wish.spec` wiring | half a day | now — this is what puts an icon on the taskbar |
| `setWindowIcon`, the app-user-model id, `setDesktopFileName` | an hour | now, same change |
| About dialog picture | an hour, and it makes `about.py` a hand-built `QMessageBox` | with the above, or never; it is decoration |
| README lockup from the same glyph | an hour, once, in Inkscape or by hand in SVG | when the README is next touched |
| hicolor PNGs and a `.desktop` | an hour | **wait** — there is no Linux package to install them into |
| `.icns` and a macOS bundle | a day, and a Mac to test on | **wait** — nothing ships for macOS |
| the artist | a real commission: master, plus hand-tuned 16/24/32, plus the lockup | when there is money |

**What can wait:** everything except the `.ico` and `setWindowIcon`. Those two
are the whole of Donald's ask, they are half a day, and they need no artist and
no decision about the rule.

**What cannot be checked from here:** that the icon actually appears on the
Windows taskbar. That is a row for
[`122-release-testing.md`](122-release-testing.md)'s Windows column, and it now
has somebody who can tick it.
