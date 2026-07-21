# RetroVault — Implementation Plans

_Plans for the priority additions from `competitive-research-and-ideas.md`._
_Status refreshed 2026-07-20 against branch `feat/cover-art-scraping` (commit `b327db0`)._

**Shipped so far:** PR 0 (`merge_scan`), #6 emulator auto-detect wiring, #1a scraper backend,
#5 play-time tracking, #4 favorites/collections, #2b detail panel, #8a RetroArch-first
controller routing, and #1b scrape UI (on `feat/cover-art-scraping`, with
libretro-thumbnails as the default no-credentials provider).
**Still open:** #2 grid view, #3 couch mode, #7 RetroAchievements, #8b RetroArch
provisioning, the ScreenScraper credentials UI, and the fixes in the
["Codebase review findings"](#9-codebase-review-findings-2026-07-20) section below.

## Architectural notes that shape every plan

- **Library entries are plain dicts** — `{name, path, system, ext}` built in
  `core/library.py:scan_roms()` and persisted to `library.json` via `save_library()`.
  Adding per-game data (artwork paths, favorite flag, play time) means widening this dict
  and preserving it across rescans (rescan currently rebuilds from scratch and would drop
  any added fields — see "Preserving game data across rescans" below).
- **The library view is a `QTableView`** over `LibraryModel` (a `QAbstractTableModel`) filtered
  by `LibraryFilterProxyModel`, wired in `ui/main_window.py:_build_body()`.
- **Config schema changes go through `core/config.py`** — add keys to `DEFAULT_CONFIG` and a
  `setdefault`/`_deep_merge` line in `migrate_config()` so existing installs upgrade cleanly.
- **App data paths live in `core/paths.py`** — add new dirs (e.g. `MEDIA_DIR`) there.
- **Controller input is fully built** — `input/` package + `ui/controller_nav.py`,
  `main_menu.py`, `onscreen_keyboard.py`. New views must implement the same nav pattern
  (`_nav_column`, `_move_*_selection`) that `main_window.py` uses.

### Preserving game data across rescans (shared prerequisite) — ✅ IMPLEMENTED

**Status: done — shipped as PR 0.** `merge_scan(old, new)` exists in
`core/library.py` (keyed by `path`, generic over any non-`SCAN_FIELDS` key), is wired into
`main_window._scan_finished()`, and has 8 passing tests in `tests/test_library.py`.
**Ship it as PR 0 before delegating anything else** — features 1, 4, 5, and 7 all assume it.

Because `merge_scan` preserves *every* key outside `SCAN_FIELDS = (name, path, system, ext)`
generically, **new enrichment fields need no registration** — agents adding fields below just
write them onto the entry dict and they survive rescans automatically.

### Library entry schema (the cross-PR contract)

All PRs below read/write the same plain-dict entries persisted to `library.json`. Every field
except the scan-owned four is optional — always read with `.get()` and treat a missing key as
the default:

| Field | Type | Written by | Read by |
|-------|------|-----------|---------|
| `name`, `path`, `system`, `ext` | scan-owned | `scan_roms` | everyone |
| `favorite` | bool (default False) | #4 | #4 filter, #2b panel |
| `last_played` | ISO-8601 str | #5 | #4 "Recently Played" |
| `play_seconds`, `play_count` | int (default 0) | #5 | #2b panel, optional column |
| `media` | `{"boxart"\|"logo"\|"screenshot": abs path str}` | #1 | #2 grid, #2b panel |
| `metadata` | `{"synopsis","genre","players","rating","year"}` | #1 | #2b panel |
| `ra_game_id`, `ra_total`, `ra_earned` | int | #7 | #2b panel |

---

## 1. Metadata + artwork scraping (foundation) — ✅ mostly shipped

**Status:** 1a (backend) merged as PR #5; 1b (UI) shipped on `feat/cover-art-scraping`.
The implementation diverged from this plan in one good way: the **default provider is
libretro-thumbnails** (`LibretroThumbnailsClient` in `providers/scraper.py`) — name-matched
box art, no account needed — with the planned `ScreenScraperClient` also implemented and
selectable via `config["scraper"]["provider"] = "screenscraper"`. `ScrapeWorker`
(`ui/scrape_worker.py`) runs the batch off-thread with progress + cooperative cancel, wired
to a top-bar "SCRAPE ART" button and a MENU entry.

**Remaining gaps:**
- `ui/settings_dialog.py` has **no scraper section** — ScreenScraper credentials/region and
  the provider choice can only be set by hand-editing `config.json`. Add a Scraper tab
  (provider combo, username/password, region) following the dialog's controller-nav pattern.
- "Force refresh" is dead config: `ScrapeWorker(force=...)` exists but
  `on_scrape_artwork` never passes it. Add a re-scrape path (e.g. a second MENU entry or a
  modifier prompt) so users can replace bad matches.
- Text metadata (synopsis/genre/players/rating/year) only comes from ScreenScraper; the
  detail panel renders mostly empty fields for libretro-scraped libraries. Once the
  credentials UI exists, document the trade-off in the wizard/settings.

**Goal (original):** fetch box art, title logo, screenshot, and text metadata (synopsis,
genre, players, rating, year) per game and cache them locally.

**New files**
- `core/media.py` — media cache paths + helpers (`media_paths_for(rom)`, `has_media(rom)`).
- `providers/scraper.py` — a `Scraper` protocol plus a `ScreenScraperClient` implementation.
  Keep the network client behind an interface so IGDB/TheGamesDB can be added later and so tests
  can inject a fake.
- `data/scraper.json` (optional) — endpoint config / per-system platform IDs.

**Files to touch**
- `core/paths.py` — add `MEDIA_DIR = APP_DIR / "media"` and create it in `init_app_dirs()`.
- `core/config.py` — add a `"scraper"` block to `DEFAULT_CONFIG`
  (`{"provider": "screenscraper", "username": "", "password": "", "region": "us", "enabled": false}`)
  and a `migrate_config` merge line. Credentials are user-supplied (ScreenScraper requires an account).
- `core/library.py` — library entries gain a `media` dict (`{"boxart": path, "logo": path,
  "screenshot": path}`) and a `metadata` dict. Populated by the scrape step, preserved by `merge_scan`.

**Approach**
- ScreenScraper API: hash-based lookup (CRC/MD5 of the ROM) with a name-based fallback. Map each
  RetroVault system id to the ScreenScraper platform id in `data/scraper.json`.
- Run scraping off the UI thread. **Gap in the original plan:** `WorkerThread` in
  `ui/main_window.py` only has `succeeded`/`failed` signals — no progress. Either extend it with
  a `progress = Signal(int, int)` (done, total) or add a dedicated `ScrapeWorker(QThread)`.
  It also needs a cooperative cancel flag checked between games: `closeEvent` only gives workers
  `quit(); wait(500)`, which a multi-minute scrape will blow through. Respect ScreenScraper's
  rate/thread limits (their free tier caps concurrent threads — read the quota from the API
  response and throttle). Note hashing cost: PSX images are hundreds of MB; hash lazily/stream
  and prefer name lookup for oversized files.
- Cache images to `MEDIA_DIR/<system>/<rom-stem>.<kind>.png`; store the resolved path on the entry.
  Skip games that already have cached media unless "force refresh" is chosen.
- Fail soft: a game with no scrape result keeps working as a plain list entry.

**UI**
- Add "SCRAPE ARTWORK" as a menu action (`_menu_actions()`) and a top-bar button.
- Add scraper credentials fields to `ui/settings_dialog.py`.

**Testing**
- Unit-test `ScreenScraperClient` against recorded/fixture JSON responses (no live network in CI).
- Test the system→platform-id mapping and the cache path builder.
- Test `merge_scan` preserves `media`/`metadata` across a rescan.

**Split for delegation:** ship as **two PRs**. PR 1a = backend only (`core/media.py`,
`providers/scraper.py`, `data/scraper.json`, `core/paths.py`, `core/config.py`) — touches no UI
files, fully parallel-safe. PR 1b = UI wiring (menu action, worker + progress, settings fields)
after 1a merges.

**Effort:** L (largest item). **Blocks:** #2 real art, #2b detail panel content.

---

## 2. Cover-art grid view — ⬜ open (next big visual win)

**Goal:** a box-art grid alongside the current list; this is the single biggest visual win.

**Status update:** the model side is already half done — `LibraryModel` now returns a
`DecorationRole` box-art icon (with `QPixmapCache` + a transparent placeholder, see
`ui/library_model.py:_boxart_icon`). The grid work is now mostly the view/stack/nav wiring
below; note `BOXART_THUMB` is list-sized (34×46) so the grid needs its own larger thumb size
(and distinct cache keys, e.g. `rv_boxart_grid::<path>`).

**New files**
- `ui/grid_view.py` — a `QListView` in `IconMode` (or a `QTableView` with a custom
  `QStyledItemDelegate` that paints artwork + label). Reuse the **existing** `LibraryModel` and
  `LibraryFilterProxyModel` — just add a `DecorationRole` branch returning the cached box art
  `QPixmap` (fallback: a generated placeholder tile with the system color already in the model).

**Files to touch**
- `ui/library_model.py` — add `Qt.ItemDataRole.DecorationRole` handling in `data()` that loads/
  caches the box-art pixmap for the row (lazy, with a small `QPixmapCache`). No new model needed.
- `ui/main_window.py`:
  - In `_build_body()`, stack a `QListView` grid and the existing `QTableView` in a `QStackedWidget`.
  - Add a list/grid toggle button to the top bar; persist the choice in config (`"view_mode"`).
  - **Share one selection model** so everything keeps working regardless of active view:
    `grid.setModel(self.proxy)` then `grid.setSelectionModel(self.table.selectionModel())`.
    `_selected_rom`, `_selected_proxy_row`, `_save_launch_view`/`_restore_launch_view`, and the
    launch handlers all go through that selection model and need no per-view branches.
  - The remaining `self.table`-specific calls (`scrollTo`, `setFocus`,
    `verticalScrollBar` in the launch-view save/restore) should route through a small
    `_active_view()` helper returning whichever view the stack is showing.
  - Point the grid's selection, `doubleClicked`, and context menu at the **same** handlers
    (`on_launch_selected`, `_open_context_menu`).
  - Extend controller nav: `_move_table_selection` currently steps ±1 row; the grid needs
    left/right within a row and up/down by a full row. Add `_grid_columns()` and route
    `_nav_move` through it when the grid is active.

**Testing**
- Model test: `DecorationRole` returns a pixmap (or placeholder) for a row with/without media.
- View-toggle test: switching modes preserves the current selection and filter.

**Effort:** M. **Depends on:** #1 for real art (ships with placeholders before then).

---

## 2b. Game detail panel — ✅ shipped (PR #8 + sync fixes on `feat/cover-art-scraping`)

**Goal:** somewhere to *show* what #1 scrapes and #7 fetches. The original plan referenced a
"detail panel" from #1 and #7 but never planned one — without it, scraped synopsis/genre/ratings
and achievement counts have no home.

**New files**
- `ui/detail_panel.py` — a widget (right side of the body splitter, collapsible) showing box art,
  name, system, `metadata` fields (synopsis, genre, players, rating, year), play time
  (`play_seconds`/`play_count`, from #5), and `ra_earned / ra_total` when present (#7).
  Everything read with `.get()`; renders sensibly when only scan fields exist.

**Files to touch**
- `ui/main_window.py` — instantiate in `_build_body()`, update on selection change
  (connect to the shared selection model's `currentRowChanged`), add a show/hide toggle.

**Testing**
- Panel renders without error for a bare entry (no media/metadata) and a fully enriched one.

**Effort:** S. **Depends on:** nothing to build (degrades gracefully); #1/#5/#7 fill it in.

---

## 3. Controller-first fullscreen "couch" mode — ⬜ open

**Goal:** a distraction-free fullscreen experience that feels like a console — the payoff for the
controller work already on this branch.

**What already exists (reuse, don't rebuild)**
- `apply_window_mode()` already implements `desktop`/`fullscreen`/`kiosk` and `restore_foreground()`.
- Full controller stack + `MainMenuDialog` + `OnScreenKeyboard` + launch handoff
  (`LaunchCoordinator`) already suspend/resume the pad around emulator runs.

**Files to touch**
- `ui/main_window.py` — add a controller-reachable "toggle fullscreen" action to `_menu_actions()`
  and a keyboard shortcut. When entering fullscreen couch mode, hide the mouse cursor and grow
  fonts/art tiles (a `couch` property on the central widget the stylesheet keys off).
- The grid (#2) should be the default view in couch mode — big boxes read well on a TV.
- Add a visible on-screen hint bar ("A: Launch  B: Back  Menu: Options") bound to the current
  `accept_button` config so the labels match the user's pad.

**New (small)**
- `ui/hint_bar.py` — a thin widget showing current controller bindings; updates when the
  `controller.accept_button` config changes.

**Testing**
- Verify `apply_window_mode("fullscreen")` + couch property yields the enlarged layout headlessly
  (widget property assertions, no real screen).
- Existing controller-nav tests extended for the grid movement added in #2.

**Effort:** S–M (mostly polish on top of finished plumbing).

---

## 4. Favorites, Recently Played, and Collections — ✅ shipped (PR #7)

**Goal:** universally expected quality-of-life organization.

**Leftovers from this feature (see also findings §9):**
- The `hidden: true` flag idea below was **not** implemented — `_remove_rom()` still
  un-removes itself on the next rescan (finding G3).
- Collections/remove/open-location remain mouse-only; only favorite-toggle got a MENU
  entry (finding C1).
- Recently Played goes stale while you sit in it (finding G4).

**Files to touch**
- `core/library.py` — entries gain `favorite: bool` (preserved by `merge_scan` automatically;
  `last_played` is written by #5). Collections are a separate list, not per-entry.
  **Decision (pinned so agents don't have to ask): use a new `collections.json`**
  (`[{"name": "RPGs", "paths": [...]}, ...]`) with load/save helpers in `core/library.py`,
  not a config block — collections are library data, not settings.
- `core/paths.py` — `COLLECTIONS_FILE = APP_DIR / "collections.json"`.
- `ui/library_model.py` — **correction to the original plan:** the sidebar is NOT in the model
  layer; it is a `QListWidget` built in `main_window._refresh_sidebar()`, and the proxy filters on
  a plain `system_key` string. So: extend `LibraryFilterProxyModel` to accept sentinel filter keys
  (`"__favorites__"`, `"__recent__"`, `"collection:<name>"`) in `set_system_filter` /
  `filterAcceptsRow` (favorite flag truthy; `last_played` present, sorted/limited desc;
  path in the named collection).
- `ui/main_window.py`:
  - `_refresh_sidebar()` — prepend `★ Favorites` / `Recently Played` / one item per collection
    above `ALL GAMES`, with the sentinel strings as their `UserRole` data (the existing
    `_on_sidebar_changed` then just works).
  - `_open_context_menu()` — add "Toggle favorite" and "Add to collection ▶", then `save_library()`.
  - **Controller reachability (gap):** the context menu is mouse-only and the `Action` enum
    (`input/actions.py`) has no spare face button. Minimum viable: add a "Toggle Favorite
    (selected game)" entry to `_menu_actions()` so it's reachable via the MENU button. A dedicated
    pad binding (new `Action` member + router/backend mapping) can be a follow-up.
- Optional, same PR or follow-up: `_remove_rom()` currently drops the entry, but the next rescan
  re-adds it. A `hidden: true` enrichment flag (filtered out in `filterAcceptsRow`) would make
  removal stick across rescans for free, courtesy of `merge_scan`.

**Testing**
- Proxy filter tests for the three sentinel keys.
- `merge_scan` preserves `favorite` (already covered by `tests/test_library.py`).

**Effort:** M. **Depends on:** PR 0 (`merge_scan`, done).

---

## 5. Play-time tracking — ✅ shipped (PR #6)

**Goal:** log hours per game (Playnite's most-loved feature).
Implemented as planned: `session_finished` on `LaunchCoordinator`, `MIN_PLAY_SECONDS`
short-session guard, `_on_play_session_finished` in `main_window.py`.

**Where it hooks in cleanly**
- `LaunchCoordinator` already brackets the emulator run: `input_disabled(True)` fires at launch,
  `finished` fires on emulator exit (`ui/main_window.py:_on_launch_session_finished`). That pair is
  your start/stop clock — no process polling needed.

**Files to touch**
- `ui/launch_overlay.py` — **gap in the original plan:** `LaunchCoordinator.finished` is a
  bare `Signal()` carrying neither elapsed time nor which ROM ran. `launch(rom, config)` already
  receives the rom, so: record `time.monotonic()` and the rom's `path` at launch, and add a new
  `session_finished = Signal(object)` emitting `{"rom_path": ..., "elapsed_seconds": ...}`
  alongside the existing `finished` (don't change `finished`'s signature — existing connections
  in `main_window` and tests rely on it).
- `ui/main_window.py` — connect `session_finished` to a new handler that finds the entry by
  `rom_path`, adds elapsed to `play_seconds`, bumps `play_count`, sets `last_played`
  (ISO-8601, UTC), then `save_library(self.library)` and refreshes the model row.
- `core/library.py` — `play_seconds`/`play_count` fields (preserved by `merge_scan`).
- `ui/library_model.py` — optional "Time Played" column / detail-panel line.

**Edge cases**
- Discard implausibly short sessions (< a few seconds = a failed launch) so misfires don't pollute
  stats. This also covers the un-waitable win32 ShellExecute path, where `LaunchSession` emits
  `exited(0)` immediately (elapsed ≈ 0 → dropped; `last_played` may still be set). The legacy
  fallback path (`launch_coordinator is None`) is fire-and-forget and can't be timed —
  acceptable; only the coordinator path tracks time.

**Testing**
- Feed a fake start/stop delta and assert `play_seconds` accumulates and short sessions are dropped.

**Effort:** S. **Depends on:** `merge_scan` prerequisite.

---

## 6. Auto-detect installed emulators on first run — ✅ shipped (PR #4)

**Goal:** first-run Easy Mode pre-fills emulator profiles instead of only linking downloads.

**What already exists**
- `providers/discovery.py` already does the hard part: `discover_emulators(config)` scans PATH,
  known Windows install paths, and flatpak; `apply_detection()` fills empty emulator slots from the
  results. This is done — it just needs to be surfaced in the setup flow.

**Files to touch**
- `ui/setup_wizard.py` — add a "Detect installed emulators" step early in Easy Mode: run
  `discover_emulators` in a `WorkerThread`, show found/not-found per system, and offer to apply
  (`apply_detection`) before falling back to the download-link path for the ones not found.
- `ui/settings_dialog.py` — a "Re-detect" button for the emulators page.

**Testing**
- Discovery already testable with a fake registry; add a wizard-level test that applying detection
  populates slots and marks systems configured (`is_emulator_configured`).

**Effort:** S (integration, not new logic). **High value for how little work remains.**

---

## 7. RetroAchievements integration — ⬜ open

**Goal:** show achievement counts per game; a strong retro-community draw.
The `rom_hashes()` helper in `providers/scraper.py` (CRC32/MD5 with a size cap) is a
starting point, but note RA uses **per-console** hashing rules, not whole-file hashes,
for several systems.

**New files**
- `providers/retroachievements.py` — client for the RetroAchievements web API
  (`GetGameList`/hash lookup + `GetUserProgress`). Interface-based like the scraper (#1) for testing.
- `data/retroachievements.json` — RetroVault-system → RA console-id map.

**Files to touch**
- `core/config.py` — `"retroachievements"` block (`{"enabled": false, "username": "", "api_key": ""}`)
  + migrate line. User supplies credentials.
- `core/library.py` — optional `ra_game_id`, `ra_total`, `ra_earned` fields (preserved by `merge_scan`).
- `ui/detail_panel.py` (#2b) — show "12 / 40 achievements" when `ra_total` is present.
- `ui/settings_dialog.py` — RA credentials fields.

**Notes**
- Match games to RA by ROM hash (RA uses per-console hashing rules; implement the common ones:
  NES/SNES/GB/GBA/N64/Genesis/PSX are all supported by RA). Name fallback where hashing is complex.
- This is additive metadata; the detail panel (#2b) is where the counts display, but the client
  itself is independent.

**Effort:** M–L. **Sequence last** among these — it's the most niche and benefits from the
detail panel (#2b).

---

## Remaining-work roadmap (refreshed 2026-07-20)

Waves A–E, F-part (1b), plus #8a all merged; the historical wave tables were removed —
see git history (`PR #3–#11`) for what landed where. What follows is the plan for what's
left, ordered so each wave builds on the previous one. The "Rules for every delegated PR"
below still apply to all of it.

**Wave R1 — correctness and robustness first (small, independent, high value):**

| PR | Item | Files | Effort |
|----|------|-------|--------|
| R1a | G1 `.bin` collision + cue/bin dedupe | `core/library.py` (scan), `data/systems.json`, tests | S–M |
| R1b | G2 atomic JSON persistence | `core/library.py`, `core/config.py` (shared helper in `core/paths.py` or new `core/jsonio.py`), tests | S |
| R1c | G4 Recently-Played staleness + C3 router dead code | `ui/main_window.py`, `input/router.py`, tests | S |
| R1d | C1 controller-reachable game options | `ui/main_window.py`, `input/actions.py`, `input/router.py`, tests | M |

All four are independent of each other and of the feature work; R1a/R1b are pure-core and
fully parallel-safe. R1c and R1d both touch `ui/main_window.py` in different functions.

**Wave R2 — the remaining headline features:**

| PR | Item | Depends on | Files |
|----|------|-----------|-------|
| R2a | #2 grid view | — (DecorationRole already done) | `ui/grid_view.py` (new), `ui/library_model.py`, `ui/main_window.py` (`_build_body`, nav) |
| R2b | #1 leftovers: scraper settings UI + force refresh | — | `ui/settings_dialog.py`, `ui/main_window.py` (one menu entry) |
| R2c | C2 controller status indicator | — | `input/router.py`, `ui/main_window.py` (status bar) |

R2a and R2b/R2c can run in parallel (different files except trivial `main_window` spots).

**Wave R3 — polish and long tail:**

| PR | Item | Depends on |
|----|------|-----------|
| R3a | #3 couch mode + hint bar | R2a (grid is the couch default) |
| R3b | G3 move-resilient `merge_scan` + `hidden` flag | — |
| R3c | #7 RetroAchievements | detail panel (done); scraper provider pattern to copy |
| R3d | #8b auto-provision RetroArch + cores | pinned artifacts + core downloader |

### Rules for every delegated PR

- Branch from `main`; one PR per row above; don't touch files another in-flight wave-mate
  owns beyond the noted one-liners.
- Library entries: read every enrichment field with `.get()`; never assume presence. New fields
  survive rescans automatically via `merge_scan` — no registration step.
- Config changes: add to `DEFAULT_CONFIG` **and** `migrate_config()` in `core/config.py`.
- New views/dialogs must implement the controller-nav pattern (see `ui/controller_nav.py` and
  existing dialogs) and keep tests headless (see existing `tests/test_*_nav.py` for the pattern;
  CI skips Windows-only tests on Linux).
- No live network in CI — providers get fixture-based tests behind an injectable interface.

## Effort summary

| # | Feature | Effort | Status / key dependency |
|---|---------|--------|-------------------------|
| 0 | `merge_scan` prerequisite | — | ✅ done (PR #3) |
| 6 | Auto-detect emulators | — | ✅ done (PR #4) |
| 1a | Scraper backend | — | ✅ done (PR #5) |
| 1b | Scraper UI wiring | — | ✅ done (`feat/cover-art-scraping`) |
| 2b | Detail panel | — | ✅ done (PR #8) |
| 4 | Favorites / collections | — | ✅ done (PR #7) |
| 5 | Play-time tracking | — | ✅ done (PR #6) |
| 8a | RetroArch default for controller mode | — | ✅ done (PR #11) |
| G1 | `.bin` collision / cue-bin dedupe | S–M | open — scan correctness |
| G2 | Atomic JSON writes | S | open — data safety |
| G4+C3 | Recent-view staleness + router cleanup | S | open |
| C1 | Controller-reachable game options | M | open |
| 1-rem | Scraper settings UI + force refresh | S | open |
| C2 | Controller status indicator | S | open |
| 2 | Cover-art grid view | M | open — DecorationRole done |
| 3 | Couch/fullscreen mode | S–M | open — needs #2 |
| G3 | Move-resilient merge + `hidden` flag | S–M | open |
| 7 | RetroAchievements | M–L | open |
| 8b | Auto-provision RetroArch + cores | L | open — pinned artifacts |

---

## 8. Seamless controller support — RetroArch-first

**Goal:** the controller works in emulators without the user hand-mapping each one.

**Decision (validated on real hardware):** make **RetroArch the default backbone for
controller-first play**, because its centralized controller autoconfig is the reliable,
low-maintenance path. Keep the curated standalones as the opt-out.

### What the live testing established

- **SDL env injection (`SDL_GAMECONTROLLERCONFIG`) does NOT work for standalone emulators.**
  mGBA (and its class) bind by *raw SDL joystick button index* in their own config, not via
  SDL's GameController mapping, so the env var is ignored. This approach was prototyped and
  **parked** (closed PR).
- **Writing the emulator's own config DOES work** (proven: writing `keyA=1, keyB=0, keyUp=11…`
  into mGBA's `config.ini` from the pad's SDL mapping made Pokémon Crystal fully playable). But
  it's a *per-emulator, format-specific, version-fragile* treadmill (each of mGBA/DuckStation/
  RMG/Snes9x has its own format; emulators rewrite their config on exit). Kept as an optional
  **Lever 3** convenience, not the strategy.
- **RetroArch autoconfig** covers all systems with one setup and near-zero maintenance — the
  right default.

### 8a — RetroArch as the default for controller mode ✅ (this PR)

**Done.** `core/launch.py:use_retroarch_for(config, system_key)` centralizes the backend
decision: the explicit `use_retroarch` toggle keeps its meaning; otherwise
`controller.prefer_retroarch` (new config key, default on) routes through RetroArch **only when
a real RetroArch binary and a core for the system exist**, falling back to the standalone
otherwise. `validate_launch`/`build_launch_command` both route through it. Inert until RetroArch
is set up, so a fresh install keeps its standalones. Tests in `tests/test_retroarch_preference.py`.

### 8b — Auto-provision RetroArch + cores (the remaining work)

**Why it's a separate PR:** it needs *verified external artifacts* — a pinned RetroArch Windows
build (url + sha256) and libretro **core** downloads — which must be fetched and checksummed
deliberately, not fabricated.

**Files to touch**
- `data/emulators/retroarch.json` — the Windows `install` strategy is currently `"unavailable"`;
  add a pinned `download` strategy (url/sha256/archive/exe) like the other emulators.
- `providers/installer.py` / a new `providers/cores.py` — **core provisioning is net-new**: no
  libretro-core download logic exists today. Download cores from the libretro buildbot
  (`https://buildbot.libretro.com/nightly/<platform>/latest/<core>.dll.zip`) into a managed
  cores dir, verify, and point RetroArch's `core_path` at it (write RetroArch's `retroarch.cfg`).
  The system→core map already exists in `retroarch.json` and `DEFAULT_CONFIG["retroarch_cores"]`.
- `ui/setup_wizard.py` — offer "install RetroArch for seamless controllers" in Easy Mode; on
  success set `retroarch_path` + `use_retroarch`/leave `prefer_retroarch` on. Reuse the existing
  `discover_emulators` detection to skip install when RetroArch is already present.

**Notes**
- Keep N64 flexible: `mupen64plus_next` is the one core clearly behind its standalone (RMG), so
  allow the standalone to remain for n64.
- All downloads behind the existing installer's checksum discipline; no live network in CI
  (fixture/opener injection like `providers/manifest.py`).

**Effort:** L. **Depends on:** pinned artifacts + a core downloader.

---

## 9. Codebase review findings (2026-07-20)

A focused review of controller handling and game management on `feat/cover-art-scraping`.
Ordered by impact within each group. IDs (G# / C#) are referenced from the roadmap above.

> **Status (2026-07-21):** G1, G3, G4, G5, C1, C2, C3, C5 are **implemented, tested, and
> committed** on branch `fix/review-findings` (commits `cd65846`, `dc367bd`, `07f4163`,
> `82abe0d`, `476501a`; full suite 369 green). Remaining: **G2** (atomic writes — parked
> until the library holds stats worth protecting) and the documented non-goals **C4/C6**.
> See §10 for the plans each change followed.

### Game management

**G1 — `.bin` extension collision + multi-track disc pollution (correctness bug).**
`scan_roms()` (`core/library.py`) builds a flat `ext_to_system` dict, so an extension can
belong to only one system — and both `psx` (`.bin`, `.cue`, `.iso`, `.img`) and `genesis`
(`.bin`, ...) claim `.bin` in `data/systems.json`. Genesis iterates later, so **every `.bin`
file is classified as Genesis**, including PSX disc images. Separately, a multi-track PSX
dump (one `.cue` + N `.bin` tracks) creates N+1 library entries, all junk except the cue.
Fix in `scan_roms`:
- When a `.cue` exists, index the cue and **skip any `.bin`/`.img`/`.iso` it references**
  (parse `FILE "..."` lines; cheap and offline). A standalone `.bin` with a sibling `.cue`
  of the same stem can also be skipped without parsing.
- For genuinely ambiguous extensions, allow `ext_to_system` to hold a list and disambiguate:
  a `.bin` referenced by a cue or > ~16 MB is PSX; otherwise Genesis. Pin the heuristic in
  tests. (Longer term: `.m3u` playlist support for multi-disc games.)

**G2 — non-atomic JSON writes risk wiping user data (robustness).**
`save_library`, `save_collections` (`core/library.py`) and `save_config` (`core/config.py`)
all do `open(path, "w")` + `json.dump`. A crash or power loss mid-write (a real scenario on
a Raspberry Pi couch box) truncates the file; on next start `load_library()` swallows the
parse error and returns `[]`, and the next save **permanently erases favorites, play time,
and scraped metadata**. Library writes happen constantly (every favorite toggle, every play
session). Fix: one shared helper — write to `path.with_suffix(".tmp")`, `os.replace()` onto
the target (atomic on Windows and POSIX), and keep a `.bak` of the last good version that
`load_library` falls back to instead of returning `[]`.

**G3 — enrichment doesn't survive file moves; removal doesn't stick.**
`merge_scan` keys strictly by absolute path, so reorganizing a ROM folder (or renaming a
file) silently drops that game's favorites/play time/artwork. Add a fallback match for
entries whose path vanished: same `ext` + file size (cheap, already stat-able during scan),
or name as a weaker tiebreak. Related: `_remove_rom()` still physically drops the entry, so
the next rescan resurrects it — implement the `hidden: true` flag filtered out in
`filterAcceptsRow` (idea already pinned in §4, never built). Both belong in one PR since
both touch the scan/merge path.

**G4 — Recently Played view goes stale while selected.**
`LibraryFilterProxyModel._compute_recent()` runs only inside `set_system_filter`, i.e. when
the sidebar row is (re)selected. Finish a play session while sitting in "Recently Played"
and the just-played game neither appears nor re-sorts (`_on_play_session_finished` emits
`dataChanged` but never re-filters). Fix: in `_on_play_session_finished`, if
`self.proxy.system_key == RECENT_FILTER`, call `self.proxy.set_system_filter(RECENT_FILTER)`
after persisting.

**G5 — scan/scrape race can clobber edits (minor, guard-level fix).**
`ScrapeWorker` snapshots `list(library)` and `_scrape_finished` replaces `self.library`
wholesale. A rescan (or a `_remove_rom`) completing while a multi-minute scrape runs is
overwritten when the scrape lands. Cheapest fix: disable SCAN ROMS while a scrape is
running (mirror of the existing `scrape_btn` guard), or merge the worker's result by path
instead of replacing the list.

### Controller handling

The input stack itself (`input/` + `controller_nav.py`) is in good shape: pure state
machine, injectable clock, hysteresis, hotplug rescan, modal delegation. The gaps are all
at the "reachability" layer above it.

**C1 — context-menu actions are unreachable from the couch (biggest gap).**
`_open_context_menu` (launch / open location / remove / favorites / collections) is
mouse-only. From the pad, only favorite-toggle is reachable (via MENU). A kiosk user cannot
manage collections or remove a game at all. Fix: a controller-navigable **Game Options**
dialog reusing `MainMenuDialog`, listing the same actions the context menu offers for the
selected game. Reaching it: the state machine's `_button_map` maps neither `BTN_FACE_WEST`
nor `BTN_FACE_NORTH` — add `Action.OPTIONS` bound to face-west (X on Xbox), route it in
`_on_controller_action`, and keep a MENU entry as fallback. This also gives future actions
(e.g. "View details") a natural home.

**C2 — no visible controller status.**
`Backend.is_connected()` exists but nothing surfaces it — a dead battery or a pad that
failed to enumerate looks identical to a working setup until buttons do nothing. Fix: the
router checks `backend.is_connected()` on a slow cadence (every ~1 s of ticks) and emits a
`connection_changed(bool)` signal; `MainWindow` shows a permanent status-bar indicator
("🎮 connected" / greyed) plus a transient message on change. Headless-testable with a fake
backend.

**C3 — dead code in `ControllerRouter`.**
`set_target()`, `route_action()`'s `_last_target` bookkeeping, and `_resolve_target()` are
written but unused: nothing calls `set_target`, and `_last_target` is never read (modal
delegation happens in `MainWindow._on_controller_action` instead). Either delete the
target-resolution layer (preferred — the modal-delegation pattern won) or move the modal
check into the router where this machinery intended it to live. Small cleanup, do it
alongside G4's PR.

**C4 — single-device assumptions (accepted, documented).**
`SdlBackend` opens the first recognized device only; a second pad is ignored until the
first disconnects. Fine for a frontend (menus need one navigator) — record as a
non-goal unless multi-user profiles ever land.

**C5 — verify shutdown of an in-flight launch session.**
`closeEvent` stops the controller and cancels/waits tracked workers, but
`LaunchCoordinator._session` (and its wait thread in `launch_session.py`) is not in
`_workers`. Closing RetroVault while an emulator runs should be checked for a clean thread
shutdown; if it leaks, park the session's thread handle somewhere `closeEvent` can wait on.

**C6 — remapping depth is intentionally shallow (note only).**
Only `accept_button` (south/east) is configurable. That matches the "SDL GameController
normalizes layout" philosophy, and full remap UIs are a treadmill — but once C1 adds
`Action.OPTIONS`, keep the pattern: semantic actions in `input/actions.py`, one config key
per swappable pair, labels driven by config (the #3 hint bar consumes the same data).

---

## 10. Improvement plans (per finding)

Each finding from §9 expanded into an actionable plan: the specific change, the code that
moves, tests to add, and sequencing. Effort tags: S ≈ half-day, M ≈ 1–2 days, L ≈ 3+ days.
All follow the "Rules for every delegated PR" above.

### G1 — `.bin`/disc classification (correctness) — M

**Problem recap.** `scan_roms()` flattens `config["systems"]` into a single
`ext_to_system` dict, so the last system to claim an extension wins. `genesis` is defined
after `psx` in `systems.json`, both list `.bin`, so **all `.bin` → Genesis**. And a
cue/bin disc set produces one entry per track file.

**Plan.**
1. **Cue-aware pre-pass.** In `scan_roms`, collect files per directory first. For every
   `.cue`, read it (small text file) and extract referenced data files from `FILE "<name>"
   BINARY` lines. Build a `consumed` set of those referenced paths (resolved against the
   cue's dir) and **exclude them** from becoming their own entries. The `.cue` itself
   becomes the single PSX entry for that disc. Add a tiny `parse_cue_tracks(path) -> list[str]`
   helper (pure, unit-testable, tolerant of quotes/whitespace/missing files).
2. **Disambiguate shared extensions.** Change `ext_to_system` to map an extension to a
   *list* of candidate system ids (preserving definition order). Resolve per file with a
   small `classify(path, candidates)`:
   - a `.bin` with a sibling `.cue` of the same stem, or referenced by any cue → PSX
     (already handled by step 1's `consumed` set, so it never reaches here);
   - a standalone `.bin` → size heuristic: `> ~24 MB` → PSX, else Genesis (Genesis carts
     top out ~4–8 MB; PSX tracks are tens–hundreds of MB). Pin the threshold as a module
     constant with a comment.
   - unambiguous extensions (one candidate) skip the heuristic entirely.
3. **Data hygiene.** Consider dropping `.bin` from `genesis` extensions in `systems.json`
   in favor of `.md/.gen/.smd` (real Genesis dumps almost always use those); keep the
   heuristic as the safety net for legacy `.bin` Genesis dumps. Decide in the PR; if kept,
   the heuristic is load-bearing and must be tested both ways.
4. **Follow-up (own PR): `.m3u` multi-disc.** Once cue handling exists, an `.m3u` playlist
   referencing multiple cues should collapse to one entry. Note it; don't scope-creep G1.

**Tests** (`tests/test_library.py`): a temp tree with `game.cue` + `game (Track 1).bin` +
`game (Track 2).bin` yields exactly one PSX entry; a lone `sonic.bin` (4 MB) → Genesis; a
lone `ff7.bin` (300 MB, no cue) → PSX; `parse_cue_tracks` handles quoted names, blank
lines, and a missing referenced file without raising.

**Risk (low — single-user project).** Reclassification changes the existing local library
on the next scan, but `merge_scan` keys by path so a `.bin` that flips system keeps its
enrichment. No migration/back-compat scaffolding needed — just rescan once after the change
lands. Free to pick the cleaner data model (e.g. dropping `.bin` from Genesis) without
worrying about other installs.

### G2 — atomic JSON persistence (data safety) — S

**Problem recap.** `save_library`/`save_collections`/`save_config` truncate-then-write; a
mid-write crash corrupts the file and `load_library`'s bare `except` then silently returns
`[]`, and the next save erases everything.

**Plan.**
1. Add `core/jsonio.py` with `write_json_atomic(path, data)` and
   `read_json(path, default, *, keep_backup=True)`:
   - write to `path.with_name(path.name + ".tmp")`, `flush()` + `os.fsync()` the handle,
     then `os.replace(tmp, path)` (atomic on Windows and POSIX);
   - before replacing, if `path` exists copy it to `path + ".bak"` (last-known-good);
   - `read_json` tries `path`, and on `JSONDecodeError`/empty falls back to `path + ".bak"`,
     logging a warning, before returning `default`.
2. Route `save_library`, `save_collections` (`core/library.py`) and `save_config`
   (`core/config.py`) through `write_json_atomic`; route `load_library`, `load_collections`,
   `load_config` through `read_json`. Behavior is otherwise unchanged.
3. Keep the existing swallow-and-default contract for a truly absent file (fresh install),
   but **stop swallowing a corrupt primary when a good `.bak` exists**.

**Tests** (`tests/test_library.py` / `tests/test_config.py`): writing then truncating the
primary and reloading returns the `.bak` contents, not `[]`; `write_json_atomic` leaves no
`.tmp` behind on success; a write over an existing file produces a `.bak` matching the prior
content. Use `tmp_path` and monkeypatch the module's file constants.

**Sequencing.** Deprioritized. There is no accumulated play-time/favorites/metadata to lose
yet, so the bug currently protects nothing — its value only accrues once real stats build
up. The fix is small and isolated (two core files + one new module), so the natural time to
land it is **just before the library becomes worth protecting** (e.g. once play-time
tracking has logged real hours, or right after a big scrape run), not ahead of the fun
feature work. Cheap insurance to buy before the data exists, pointless to rush while it
doesn't.

### G3 — move-resilient merge + sticky removal — M

**Problem recap.** `merge_scan` keys strictly by absolute path, so moving/renaming a ROM
drops its enrichment; `_remove_rom` doesn't survive a rescan.

**Plan.**
1. **Fallback identity in `merge_scan`.** Primary match stays path-exact. For old entries
   whose path is absent from the new scan, build a secondary index keyed by a cheap
   fingerprint — `(ext, size_bytes)`, with `name.lower()` as a tiebreak. `scan_roms` must
   start recording `size` on each entry (one `f.stat().st_size`, essentially free during the
   walk; it's also reused by G1's heuristic). When exactly one unclaimed new entry matches a
   dropped old entry's fingerprint, carry its enrichment over. Ambiguous matches (2+) are
   left alone — never guess.
2. **`hidden` flag.** `_remove_rom` sets `rom["hidden"] = True` and persists instead of
   dropping the dict; `filterAcceptsRow` returns `False` when `rom.get("hidden")`. Because
   the entry stays in `library.json`, `merge_scan` preserves the flag automatically and the
   rescan no longer resurrects it. Add a "Show removed / Unhide" affordance later (out of
   scope; the flag is the mechanism).
3. `size` is scan-owned, so add it to `SCAN_FIELDS` so `merge_scan` treats fresh scan values
   as authoritative.

**Tests**: moving a file (new path, same ext+size) preserves `favorite`/`play_seconds`;
two same-size files don't cross-contaminate; a `hidden` entry is filtered out and survives a
rescan; `size` refreshes from disk on rescan.

### G4 + C3 — recent-view refresh + router cleanup — S

**G4 plan.** In `main_window._on_play_session_finished`, after `save_library` and the
`dataChanged` emit, add: `if getattr(self.proxy, "system_key", "") == RECENT_FILTER:
self.proxy.set_system_filter(RECENT_FILTER)` (re-runs `_compute_recent` + re-sorts so the
just-played game jumps to the top live). Import `RECENT_FILTER` from `library_model`.
Same pattern belongs in `_toggle_favorite` for the `__favorites__` view for consistency —
it already calls `_refresh_sidebar`, but the visible table only re-filters if the sentinel
view is re-applied; verify and fix if needed.

**C3 plan.** Delete the unused target layer from `ControllerRouter`: `set_target`,
`_target`, `_last_target`, `_resolve_target`, and reduce `route_action` to `self.action.emit(event)`
(or inline it into `_tick`). The modal-delegation design in
`MainWindow._on_controller_action` is the one that shipped; this machinery never wired up.
Grep first to confirm zero external callers (there are none in-tree).

**Tests**: a `RECENT_FILTER`-active proxy reflects a new `last_played` after the handler
runs (drive with a fake `session_finished` dict); `test_router.py` still green after the
deletion (adjust any test that referenced the removed methods).

### C1 — controller-reachable Game Options — M

**Problem recap.** The right-click menu (launch/open location/remove/favorite/collections)
is mouse-only; from a pad only favorite-toggle (via MENU) works.

**Plan.**
1. **New semantic action.** Add `OPTIONS = "options"` to `Action` (`input/actions.py`). In
   `InputStateMachine._button_map` (`input/router.py`) bind it to `BTN_FACE_WEST`
   (`lambda b: BTN_FACE_WEST in b`) — currently unmapped, and X/□ is the natural "options"
   button. Import `BTN_FACE_WEST` alongside the others.
2. **Route it.** In `MainWindow._on_controller_action`, add an `elif action is
   Action.OPTIONS:` branch that opens the options dialog for `self._selected_rom()`,
   deferred via `QTimer.singleShot(0, ...)` exactly like `MENU` (same nested-event-loop
   reasoning — cite that comment).
3. **The dialog.** Add `_open_game_options()` that builds a `MainMenuDialog` (already
   controller-navigable) from a list of `(label, callback)` for the selected game: Launch,
   Toggle Favorite, Add to Collection ▶ (a submenu is awkward in `MainMenuDialog` — flatten
   to "Add to <collection>" / "New collection…" entries, or push a second `MainMenuDialog`),
   Open File Location, Remove. Reuse the existing `_toggle_favorite`, `_add_to_new_collection`,
   `_open_location`, `_remove_rom` handlers verbatim. Run the chosen callback after the
   dialog closes (mirror `_open_menu`).
4. **Fallbacks.** Keep a "Game Options (selected)" entry in `_menu_actions()` so it's
   reachable even on a pad without an X button, and keep the mouse context menu.
5. **Discoverability.** Feeds directly into #3's hint bar ("X: Options"); until then, a
   status-bar hint on first selection is enough.

**Tests** (`tests/test_main_window_nav.py` or a new `test_game_options.py`, headless): an
`Action.OPTIONS` event with a row selected opens the dialog (patch `exec`); each callback
mutates the right entry; no-selection shows the "No ROM selected" message and opens nothing.
Add a state-machine test that a `BTN_FACE_WEST` press emits `Action.OPTIONS`.

### C2 — controller connection indicator — S

**Plan.**
1. **Signal from the router.** `ControllerRouter` gains `connection_changed = Signal(bool)`.
   In `_tick`, every ~80 ticks (~1 s at 12 ms) call `self._backend.is_connected()`; when it
   differs from the last seen value, emit. Emit an initial state on `start()`. Keep the
   cadence coarse — `is_connected` is cheap but not free, and status doesn't need per-tick
   resolution.
2. **UI.** `MainWindow._build_controller` connects it to `_on_controller_connection(bool)`:
   set a permanent status-bar `QLabel` ("🎮" solid vs. greyed with a "no controller"
   tooltip) and flash a 3 s transient message on change. When `self.controller is None`
   (build failed / disabled), show the greyed state.
3. Respect `controller.enabled == False`: hide the indicator entirely rather than showing
   "disconnected".

**Tests**: a fake backend flipping `is_connected` drives `connection_changed` after the
cadence threshold (advance the fake clock / call `_tick` N times); the label reflects state.
No real hardware.

### C5 — clean launch-session shutdown on close — S

**Plan.** Make an in-flight emulator session joinable at close. Options, cheapest first:
1. Have `LaunchCoordinator` expose the active `LaunchSession` (it holds `self._session`),
   and in `MainWindow.closeEvent`, if a session is active, hide behavior is fine — but the
   `_WaitThread` inside `LaunchSession` should be asked to finish. Since it blocks on
   `proc.wait()`, add `LaunchSession.shutdown(timeout_ms)` that, if a thread exists, calls
   `self._thread.wait(timeout_ms)` (the emulator is the child; we don't kill it, we just
   detach cleanly) and `deleteLater`s it.
2. `closeEvent` calls `self.launch_coordinator.shutdown()` (new pass-through) before
   accepting. Guard for `launch_coordinator is None`.

This is a correctness/hygiene fix, not user-facing; verify with a test that constructs a
coordinator with a fake session whose thread ends promptly and asserts `closeEvent` returns
without leaving a running `QThread` (`thread.isRunning()` is `False`). Keep it best-effort —
never block close for more than the timeout.

### C4 / C6 — documented non-goals

No code. Record in `docs/` (or a `## Non-goals` note): single-navigator device selection is
intentional; deep remapping is deliberately shallow. Revisit only if multi-user profiles or
a remap UI are ever prioritized. Listed here so they aren't rediscovered as "bugs".

### G5 — scan/scrape race guard — S

**Plan.** Two-part, pick per taste:
- **Minimal:** disable the SCAN ROMS button (and the add-rom-dir path that triggers a scan)
  while `self._scrape_worker is not None`, mirroring the existing `scrape_btn` disable, and
  re-enable in `_scrape_cleanup`. Symmetric guard, ~4 lines.
- **Better:** make `_scrape_finished` merge by path onto the *current* `self.library`
  (re-read, don't trust the pre-scrape snapshot) so a concurrent rescan/removal isn't lost:
  build `{path: entry}` from `self.library`, overlay the worker's `media`/`metadata` onto
  matching live entries, drop results for paths no longer present.

**Tests**: mutating `self.library` (simulating a rescan) during a scrape and then delivering
`finished_library` preserves the concurrent change (better path), or the guard prevents the
concurrent scan from starting (minimal path).

### Suggested sequencing

1. **G2** (data safety) — protects everything else, isolated.
2. **G1** (scan correctness) — also lands `size` on entries, which **G3** reuses.
3. **G4+C3**, **G5** — small, independent hygiene.
4. **C1**, **C2** — controller reachability, the couch-experience payoff.
5. **G3**, **C5** — robustness once the above stabilizes.
6. Feature waves (#2 grid, #3 couch, #7 RA, #8b provisioning) resume from the roadmap.
