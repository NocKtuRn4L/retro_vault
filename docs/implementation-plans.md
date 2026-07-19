# RetroVault — Implementation Plans

_Plans for the priority additions from `competitive-research-and-ideas.md`._
_Grounded in the current codebase (as of branch `feat/controller-support`)._

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

## 1. Metadata + artwork scraping (foundation)

**Goal:** fetch box art, title logo, screenshot, and text metadata (synopsis, genre, players,
rating, year) per game and cache them locally.

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

## 2. Cover-art grid view

**Goal:** a box-art grid alongside the current list; this is the single biggest visual win.

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

## 2b. Game detail panel (was missing from this plan)

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

## 3. Controller-first fullscreen "couch" mode (finish in-flight work)

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

## 4. Favorites, Recently Played, and Collections

**Goal:** universally expected quality-of-life organization.

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

## 5. Play-time tracking

**Goal:** log hours per game (Playnite's most-loved feature).

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

## 6. Auto-detect installed emulators on first run (mostly built — finish wiring)

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

## 7. RetroAchievements integration

**Goal:** show achievement counts per game; a strong retro-community draw.

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

## PR breakdown for parallel agent delegation

### Base branch — read this first

`feat/controller-support` was merged into `main` via PR #1 (merge commit `75629da`), **but the
merge predates the branch's final commit**: `e2f631b` ("controller-navigable on-screen keyboard
for text search") is still only on `feat/controller-support`. The `on_search_via_keyboard` flow
and `ui/onscreen_keyboard.py` are missing from `main` until it lands. **Merge `e2f631b` (a
follow-up PR from the same branch) and PR 0 into `main` before fanning out agents.**

### PR 0 — the `merge_scan` prerequisite (done)

The finished prerequisite ships as its own PR: `merge_scan` in `core/library.py`, the
`_scan_finished` wiring in `ui/main_window.py`, and `tests/test_library.py` (8 tests, green).
Everything below assumes it is merged.

### Delegation waves

Each PR maps to one feature section above, which is the agent's context packet: goal, exact
files, approach, pinned decisions, and tests. Agents must also read "Architectural notes" and
the "Library entry schema" contract at the top of this document.

**Wave 1 — fully parallelizable (disjoint or near-disjoint files):**

| PR | Feature | Files owned | Done when |
|----|---------|-------------|-----------|
| A | #6 auto-detect wiring | `ui/setup_wizard.py`, `ui/settings_dialog.py` (emulators page), `tests/test_setup_wizard.py` | Easy Mode offers detection results and `apply_detection` populates slots; wizard test green |
| B | #1a scraper backend | `core/media.py` (new), `providers/scraper.py` (new), `data/scraper.json` (new), `core/paths.py`, `core/config.py` | Client fetches media/metadata against fixture JSON, cache paths + platform map tested; **no UI files touched** |
| C | #5 play-time | `ui/launch_overlay.py`, `ui/main_window.py` (session-finished handler only), `tests/test_launch_overlay.py` | Fake start/stop delta accumulates `play_seconds`; short sessions dropped |
| D | #4 favorites/collections | `ui/library_model.py` (proxy), `ui/main_window.py` (`_refresh_sidebar`, `_open_context_menu`, `_menu_actions`), `core/paths.py` (one line), `tests/` | Sentinel filters tested; favorite toggle reachable by mouse and via MENU |
| E | #2b detail panel | `ui/detail_panel.py` (new), `ui/main_window.py` (`_build_body` only) | Renders bare and enriched entries; updates on selection change |

Contention notes for Wave 1: C, D, and E all touch `ui/main_window.py` in **different functions**
— merge in any order, rebases are trivial. B and D both add one line to `core/paths.py` —
trivial. Nothing else overlaps.

**Wave 2 — after Wave 1 merges:**

| PR | Feature | Depends on | Files owned |
|----|---------|-----------|-------------|
| F | #2 grid view | E merged (main_window churn), B for real art (placeholders OK without) | `ui/grid_view.py` (new), `ui/library_model.py` (DecorationRole), `ui/main_window.py` (`_build_body`, nav) |
| G | #1b scraper UI | B | `ui/main_window.py` (menu action + worker), `ui/settings_dialog.py` (credentials) |

F and G both touch `ui/main_window.py`; run them in parallel only if you accept one rebase, else
F first (it restructures `_build_body`).

**Wave 3 — polish and last:**

| PR | Feature | Depends on |
|----|---------|-----------|
| H | #3 couch mode | F (grid is the couch default) |
| I | #7 RetroAchievements | E (panel displays counts); B's provider pattern to copy |

### Rules for every delegated PR

- Branch from `main` (post PR 0 + controller merge); one PR per row above; don't touch files
  another in-flight wave-mate owns beyond the noted one-liners.
- Library entries: read every enrichment field with `.get()`; never assume presence. New fields
  survive rescans automatically via `merge_scan` — no registration step.
- Config changes: add to `DEFAULT_CONFIG` **and** `migrate_config()` in `core/config.py`.
- New views/dialogs must implement the controller-nav pattern (see `ui/controller_nav.py` and
  existing dialogs) and keep tests headless (see existing `tests/test_*_nav.py` for the pattern;
  CI skips Windows-only tests on Linux).
- No live network in CI — providers get fixture-based tests behind an injectable interface.

## Effort summary

| # | Feature | Effort | Key dependency |
|---|---------|--------|----------------|
| 0 | `merge_scan` prerequisite | ✅ done | commit it |
| 6 | Auto-detect emulators (finish) | S | — (logic exists) |
| 1a | Scraper backend | M–L | PR 0 |
| 1b | Scraper UI wiring | S | 1a |
| 2 | Cover-art grid view | M | #1 for art (placeholders OK) |
| 2b | Detail panel | S | — (fed by 1/5/7) |
| 3 | Couch/fullscreen mode | S–M | #2, existing window modes |
| 4 | Favorites / collections | M | PR 0 |
| 5 | Play-time tracking | S | PR 0, LaunchCoordinator |
| 7 | RetroAchievements | M–L | config, #2b panel |
| 8a | Seamless controller — SDL mapping inject | M | — |
| 8b | Seamless controller — RetroArch couch default | S–M | #3 couch mode |

---

## 8. Seamless controller passthrough to emulators

**Goal:** the pad "just works" inside launched emulators without the user hand-mapping each one.
**Chosen approach (pinned):** phased — **Lever 1 (SDL mapping inject)** first, then **Lever 2
(RetroArch autoconfig as the couch-mode default)**. Lever 3 (writing each emulator's own input
config file) is deliberately deferred; it's per-emulator and version-fragile.

### Background (why this is the design)

RetroVault is a launcher: at launch the coordinator *releases* the pad (`controller.stop()` in
`main_window._on_launch_input_disabled`) so the emulator owns the device. From then on the
**emulator's own input config** governs — RetroVault writes none today (the manifest
`FullscreenPolicy` "config" mode is metadata-only). All of RetroVault's recommended standalones
(mGBA, DuckStation, Snes9x, ares, Mesen, RMG) use **SDL2** for input, so they auto-map any pad
SDL recognizes. That's the lever.

### 8a — SDL controller-mapping injection at launch (Lever 1)

**Idea:** pass the connected pad's SDL mapping to the emulator process via environment variables
SDL reads at startup, so an otherwise-unconfigured emulator recognizes the pad immediately.

**New files**
- `retrovault/data/gamecontrollerdb.txt` — bundled community SDL mapping DB (broad pad coverage).

**Files to touch**
- `input/sdl_backend.py` — expose the open controller's SDL mapping string + GUID
  (pygame-ce `Controller.get_mapping()` / SDL `SDL_GameControllerMapping`). Add e.g.
  `SdlBackend.controller_mapping() -> str | None`.
- `core/launch.py` — **the injection point is the two `subprocess.Popen(cmd, cwd=...)` calls** in
  `launch_rom` and `start_launch_process`. Add an `env=` argument built from `os.environ` plus:
  `SDL_GAMECONTROLLERCONFIG` (the live pad's mapping line) and
  `SDL_GAMECONTROLLERCONFIG_FILE` (path to the bundled `gamecontrollerdb.txt`). Thread the mapping
  in via a new optional parameter or a field on `config` set by the launch coordinator (keep
  `launch.py` decoupled from the UI/controller — the UI supplies the string).
- `core/config.py` — `controller.assist_emulator_input: true` flag (+ migrate line) so users can
  disable it if it fights an emulator's own config.
- `ui/launch_overlay.py` / `main_window` — when launching, read the mapping from the live backend
  and hand it to the launch call.

**Notes / edge cases**
- Env-only, non-destructive: writes nothing into emulator config dirs; if disabled or no pad is
  connected, launch behaves exactly as today.
- RetroArch ignores these SDL vars (it has its own input DB) — harmless; 8b covers RetroArch.
- Flatpak launches (`flatpak run …`) need the vars passed through with `--env=` rather than the
  process environment; handle in the flatpak command branch.

**Testing**
- `build_launch_command`/launch env builder: assert the SDL vars are present when a mapping is
  supplied and absent when the flag is off or no pad. Assert the flatpak branch forwards `--env=`.
- No real emulator or hardware in tests — inject a fake mapping string.

**Effort:** M. **Independent** (no dependency on other features).

### 8b — RetroArch autoconfig as the couch-mode default (Lever 2)

**Idea:** RetroArch ships centralized controller **autoconfig** (zero-setup across all cores).
For controller-first/couch mode (#3), default launches through the existing RetroArch path so
input is guaranteed seamless everywhere, with the standalone emulators as the opt-out.

**Files to touch**
- `core/config.py` — a couch/controller-mode preference that prefers RetroArch when a core is
  configured for the system (reuse existing `use_retroarch` + `retroarch_cores`).
- `core/launch.py` — already routes RetroArch when `use_retroarch`; gate that on the couch
  preference + per-system core availability, falling back to the standalone emulator otherwise.
- `ui/` (couch mode, #3) — surface the "use RetroArch for controller mode" toggle.

**Notes**
- Tradeoff to surface in UI: RetroArch cores vs the curated standalones. Default couch → RetroArch
  only when a core is present; never block a launch if RetroArch isn't set up.

**Effort:** S–M. **Depends on:** #3 couch mode (shares the mode/preference plumbing).
