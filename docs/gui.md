# Desktop GUI (PySide6)

ThesisAgents ships an optional desktop interface built on
[PySide6](https://doc.qt.io/qtforpython-6/). It wraps the existing
CLI flow (search → results table → export) in a window so users who
don't want a terminal can still drive the project.

## Install

The GUI is gated behind a separate extra to avoid forcing PySide6
(~80 MB) on CLI / MCP users who don't need it:

```powershell
pip install thesisagents[gui]
```

If you also want the rich-tier enrichment path:

```powershell
pip install thesisagents[gui,intelligence,mcp]
```

## Launch

Three equivalent entry points:

```powershell
thesisagents-gui                    # PyPI console script
thesisagents gui                    # CLI subcommand
py -m thesisagents gui              # module entry, useful while developing
```

The Windows release `.exe` also accepts `thesisagents.exe gui` —
the bundle includes PySide6 and the source plugins so no extra
install is needed.

## Window layout

The window has a sidebar on the left and one page at a time on the right.
The sidebar lists the three steps of the workflow, **Search**, **Enrich**
and **Deck**, with **Settings** pinned at the bottom. Each page opens with
its title and a one-line subtitle saying what the step does.

- After a search, the Enrich and Deck entries show the number of papers
  waiting for them (`Enrich · 25`), so you can see that the next step has
  data without opening it.
- `Ctrl+1` … `Ctrl+4` switch to Search, Enrich, Deck and Settings.
- While a search, an enrichment run or an export is working, the status
  bar at the bottom shows `Working…` and a moving progress bar. The page
  that started the work keeps its own detailed status line.
- The pages with results (Search, Enrich, Deck) split into a controls
  side and a results side. The controls scroll on their own, and the
  page's main buttons stay pinned below them, so **Search** or
  **Export** never scrolls out of reach. How the two sides are arranged
  depends on the window width, see "Responsive layout & HiDPI" below.

All four pages are functional in this release.

### Search

The core search → export flow.

- **Query** — keyword string (UTF-8; CJK works).
- **Sources** — one check box per source, pre-selected to the CLI's
  default set (`DEFAULT_SOURCES`, currently all fifteen). The boxes
  re-flow into as many columns as the controls side has room for.
  Sources that need a key or a browser (`ieee`, `springer`, `core`,
  `scholar`) only return results once the matching value is set in
  **Settings**, otherwise the status line marks them disabled.
- **Slide language** — picks the language for any `.pptx` exported
  from this run. Defaults to English.
- **Max results per source** — 1 … 200 (same as the CLI `--max`).
- **Year from / Year to** — leave at `—` to disable.
- **Top-tier venues only** — mirrors the CLI's default; un-tick to
  keep every result.

The controls are grouped in three cards: **What to search** (query and
sources), **Filters** (slide language, max results, years, top-tier
venues) and **Snowball and library**.

Press **Search**, or Enter in the query field. The query runs on a worker
thread so the UI stays responsive. The status bar shows the progress
indicator and the results table populates when the run finishes.
Double-click a row to open the paper's page in your browser (only
`http` / `https` links are opened, a link of any other kind from a
source record is ignored).

When the run finishes the status line reports the number of papers and
what each source returned, for example
`Found 25 paper(s). Sources: arxiv 23, openalex 25, dblp 0, ieee (failed), springer (disabled)`.
A source marked failed, rate limited or disabled contributed nothing
for a reason other than the topic, so check it before concluding the
topic has few papers.

The last column, **Suggestion**, shows the advisory recommendation the
search recorded for each paper: keep, review or prune. Hover any cell
of a row to see why: the score split into relevance, recency and
citations, a sentence per contribution, and the rule that triggered the
recommendation. The column is advice. Every result stays in the table
and in the export, and a low citation count alone never produces a
recommendation. The rules are listed in [`cli.md`](cli.md) "Ranking
diagnostics".

**Citation snowball** expands the top results along their citation
links before they are shown: *References* adds the papers they cite,
*Cited by* the papers that cite them, *Both* does both. It is off by
default and uses the CLI's bounds (the top 5 results, one step, at
most 20 new papers). The papers it finds are appended to the table
and the status line adds `Snowball: 3 new.` Same as the CLI
`--snowball` flag, see [`cli.md`](cli.md) "Citation snowballing".

**Library** names a literature library, an SQLite file that keeps
papers between sessions (see [`cli.md`](cli.md) "Literature
library"). Type a path or press **Browse…**. A file that does not
exist yet is created the first time papers are added to it.

- **Add results to the library**, when ticked, merges each search
  into the file, snowball finds and their citation links included.
  The status line adds `Library: 4 added, 21 already there.` A paper
  the library already holds is merged, not duplicated. Ticked with
  no library file, the search does not start and the status line
  asks for the file.
- **Search library** fills the table from the library instead of
  the network. The query field is the library query (empty lists
  the most recently seen papers), and max results and the year
  range apply. The status line reads `12 of 132 library papers.`
  The papers then behave like search results: they can be
  exported, enriched and built into a deck.
- With a library file set, **Export…** here and the Deck page's
  export keep their DOI / URL checks in it, so an identifier that
  verified is not checked again for 30 days.

Press **Export…**, pick an output directory, and the standard
`.pptx` + `.xlsx` + `.bib` triple lands there.

### Settings

Interface language, theme, style, API keys, contact email, cookies file and
Chrome profile directory are stored locally via Qt's
[`QSettings`](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QSettings.html)
(Windows registry, macOS plist, Linux ini). Saving a value also
exports the matching environment variable into the current process,
so the source plugins pick it up without a shell restart.

Fields:

| UI label | Env var written |
|---|---|
| Anthropic API key | `ANTHROPIC_API_KEY` |
| Semantic Scholar API key | `THESISAGENTS_S2_API_KEY` |
| NCBI / PubMed API key | `THESISAGENTS_NCBI_API_KEY` |
| IEEE Xplore API key | `THESISAGENTS_IEEE_API_KEY` |
| Springer Nature API key | `THESISAGENTS_SPRINGER_API_KEY` |
| Crossref Plus token | `THESISAGENTS_CROSSREF_PLUS_TOKEN` |
| CORE.ac.uk API key | `THESISAGENTS_CORE_API_KEY` |
| Contact email | `THESISAGENTS_CONTACT_EMAIL` |
| PDF cookies file | `THESISAGENTS_PDF_COOKIES_FILE` |
| Chrome profile directory | `THESISAGENTS_CHROME_PROFILE_DIR` |

Empty values clear the corresponding env var. **Restart the app**
to refresh fetcher singletons that cached the env value at
construction time.

**Theme** picks how the app looks: *Follow the system* (the default),
*Light* or *Dark*. It is applied the moment you press **Save**, with no
restart, and *Follow the system* keeps tracking the operating system
when you switch it between light and dark while the app is open. The app
theme is separate from the Deck page's **Dark mode** check box, which
decides how the exported `.pptx` looks.

**Style** picks the visual language, also applied on **Save** (QSettings
key `ui/style`), and works with either theme:

| Style | Look |
|---|---|
| *Classic* (the default) | A navy sidebar and white cards with a thin border. The sidebar uses the deck's navy and the accent is the deck's highlight blue, so the app and its decks look like one product. |
| *Material 3* | Google's Material 3 design system: tonal surfaces generated from one blue seed colour, borderless filled cards, a pill-shaped highlight on the active sidebar entry, fully rounded buttons with tonal secondary buttons, and regular-weight page titles. |

Both styles are drawn by the app's own stylesheet
(`thesisagents/gui/theme.py`), so neither needs an extra package. Every
palette is tested for WCAG AA contrast (4.5:1) on body, secondary,
sidebar and button text.

On a wide window the cards sit in two columns (interface and browser
access on the left, API keys on the right). On a compact window they
stack.

### Enrich

Drives the per-paper PDF + LLM enrichment step through the Python
pipeline. The Search page emits a `collection_ready` signal as soon as
the results table populates. The Enrich page catches it and lists one
row per paper with three columns:

- **Title**, shortened to 80 characters.
- **PDF**, a tick when the paper has a `pdf_url` on file (lifted by
  Unpaywall / S2 / arXiv / CORE.ac.uk), a dash otherwise. A paper
  with no PDF link is skipped.
- **Status**, pending, then done, skipped or failed with the first 60
  characters of the error.

Pick the summary language and, optionally, the model, then press
**Enrich**. The button needs an Anthropic API key in **Settings**,
and without one the status line points there. Papers are enriched one
at a time on a worker thread (each call already takes several seconds,
running them in parallel would only hit the rate limit). A failed paper
keeps its search record, so the Deck page still renders it in the
lightweight tier.

When the run finishes the enriched collection is sent to the Deck
page, so its **Export** picks up the rich-tier layout automatically.
Without an API key, the LLM-as-agent path (an MCP-aware LLM authoring
the summaries) runs outside the GUI, see the main README.

### Deck

The pre-export deck-shaping controls, in three cards: **Output**
(directory, filename stem, deck language), **Formats** (one check box
per export format, re-flowed to the available width) and **Options**.
They wire `ExportOptions` fields behind Qt widgets:

- **Dark mode** checkbox — unchecked (default) ships the light
  navy-band deck (white slides, navy header band with a white title,
  navy cover panel). Tick it for the dark OLED / low-light variant
  (slide bg `#12151B`, body text `#E5E7EB`, brighter blue accent
  `#60A5FA`, lightened navy band / cover / table fills). Mirrors the
  CLI `--dark-mode` flag.
- **Max slides per paper** — integer spinner. Defaults to 25;
  `0` means unlimited.
- **Include abstract** checkbox — when off, the deck skips the
  abstract slide entirely (useful for an "executive overview only"
  variant).
- **Verify DOIs and URLs before export** checkbox, ticked by default.
  The export first looks up every paper's DOI at doi.org and requests
  every URL once, and a wrong or unreachable identifier stops the
  export with the failed papers listed in the status line. Untick it
  only when working offline. Mirrors the CLI `--no-verify-identifiers`
  flag. The Search page's one-button Export always runs the check.
- **Template (.pptx)** and **Template config** build the deck on your
  own PowerPoint template instead of the built-in design, and apply
  a TOML / JSON file of overrides to it (layout per kind of slide,
  fonts, colours, chrome). Both are empty by default. They mirror the
  CLI `--pptx-template` and `--pptx-template-config` flags. The
  template is checked before anything is rendered, and one that does
  not meet the template contract stops the export with every problem
  in the status line. To read the same report at leisure, run
  `thesisagents validate-template FILE`. Contract:
  [`pptx_templates.md`](pptx_templates.md).

The PPTX inspector / editor surface (drives `pptx_inspect` /
`pptx_update_slide` / `pptx_reorder_slides` / `pptx_delete_slide` /
`pptx_add_slide`) is wired to the same shape names the exporter
produces — `title`, `meta`, `body`, `kpi`, `rq_question`, `figure`,
`accent_top`, `accent_left` — so the editor list view labels each
slide by its semantic role rather than by raw shape index.

## i18n

The UI ships in **all 14 languages** that the slide-deck exporter
supports: English, 繁體中文, 简体中文, 日本語, Español, Français,
Deutsch, 한국어, Português, Русский, Italiano, Tiếng Việt, हिन्दी,
Bahasa Indonesia.

Pick the language under **Settings → Interface language** (the
dropdown shows each language in its own script). Restart the app
to apply.

First-run behaviour: if no language is saved yet, the app reads
the OS locale via `QLocale().name()` and maps it to the closest
supported code (e.g. `zh_TW` → `zh-tw`, `es_ES` → `es`,
`zh-Hant-TW` → `zh-tw`). Unsupported locales fall back to English.

Two separate i18n tables live in the repo:

- `thesisagents/gui/i18n.py` — UI labels (this page).
- `thesisagents/exporters/i18n.py` — slide-deck output strings.

They're kept in lockstep by `tests/gui/test_i18n.py::test_supported
_languages_match_deck_table`. Adding a key is a single-file change;
the per-key, per-language coverage test catches any missing entry
at PR time.

## Responsive layout & HiDPI

The window sorts its width into three size classes and re-arranges every
page when the class changes (`thesisagents/gui/widgets/responsive.py`):

| Window width | Sidebar | Controls and results | Form labels |
|---|---|---|---|
| below 760 px (compact) | icons only, labels in tooltips | controls above results | above their fields |
| 760 – 1179 px (medium) | icons and labels | controls above results, split by a draggable handle | beside their fields when the card has room |
| 1180 px and up (expanded) | icons and labels | controls in a 420 px column beside the results | above their fields while the column is narrow |

- The ☰ button at the top of the sidebar collapses or expands it by hand
  at any width. Crossing a size class applies that class's default again.
- Form labels follow the width of their own card, not of the window: a
  card narrower than 460 px puts each label above its field, so long
  labels in German or Russian do not squeeze the fields.
- Groups of check boxes (sources, export formats) re-flow into as many
  aligned columns as fit.
- On a compact window the Search results hide the Authors and DOI
  columns so the title stays readable. Both are still in every export.
- The window has a minimum size of 640×480 and a default of 1280×800.
- Closing the window saves its size, position and maximised state
  (QSettings key `window/geometry`); the next launch restores them,
  moving the window back on-screen if its monitor is gone.
- HiDPI scaling is enabled at boot via
  `QT_ENABLE_HIGHDPI_SCALING=1` and
  `QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough`. Both are set
  *before* `QApplication` is constructed, which is the only safe
  time to pin them.
- The default font is bumped to point size 10 (Qt's platform
  default is 8 on some Windows machines) so CJK glyphs stay
  readable on dense screens. The font family list includes
  Windows-shipped CJK / Devanagari fallbacks (Microsoft JhengHei
  UI, Yu Gothic UI, Malgun Gothic, Nirmala UI) so a missing glyph
  in the primary font cascades cleanly rather than rendering a
  tofu box.
- Sidebar icons, check marks and arrows are drawn at run time in the
  theme's colours (`thesisagents/gui/icons.py`), at twice their size for
  sharp rendering at 200 % scaling. No SVG plug-in is needed, so a
  packaged build cannot lose them.

## Threading model

Every backend call runs off the main thread:

- `AsyncWorker` wraps a coroutine factory and calls `asyncio.run`
  inside `QRunnable.run` — used for `run_search`, single-paper
  fetches, anything that touches `httpx.AsyncClient`.
- `BlockingWorker` wraps a plain function — used for
  `export_collection`, which renders the `.pptx` via python-pptx.

Both emit `finished(object)` / `failed(object)` signals on
completion; the receiving slot lives on the main thread so it can
update widgets safely.

## Testing the GUI

The test suite under `tests/gui/` uses `pytest-qt` (installed by
the `[dev]` extra). It mocks the backend so no live HTTP is made:

```powershell
pip install -e ".[dev]"
py -m pytest tests/gui/
```

Tests fall into four families: i18n coverage, Qt model behaviour,
page-level wiring (a search button click populates the table, the
export button stays disabled until results arrive, settings round-trip
through QSettings), and the adaptive shell (`test_responsive.py`,
`test_theme_and_shell.py`: size classes, sidebar collapse, split
orientation, re-flowing grids, theme contrast, busy indicator).

## Known limitations

- The snowball on the Search page always uses the default bounds (top
  5 results, one step, 20 new papers). Other bounds, and a relevance
  floor, are CLI (`--snowball-*`) and MCP (`snowball`) options.
- A library is searched from the Search page. There is no view of its
  runs, citation links or statistics in the GUI: use the MCP
  `library_stats` tool or the Python API.
- The Deck page does not preview a template check. A template that
  cannot be used is reported when the export starts.
- The Settings page does not validate keys against the live API —
  validation would leak the key into HTTP logs and slow down save.
  An invalid key surfaces later as a `ConfigError` / 401 from the
  relevant source plugin.
- Changing the interface language still needs a restart. The theme
  applies at once.
- A running search, enrichment or export cannot be cancelled from the
  GUI yet.

Planned GUI work is tracked in `progress.md` (items #19 – #28).
