# RetroVault — Competitive Research & Improvement Ideas

_Research date: 2026-07-16_

## What RetroVault is today

A cross-platform (Windows / Linux / Raspberry Pi) **ROM library frontend** that launches
your installed standalone emulators or RetroArch. No bundled emulation. Current strengths:

- **Easy Mode setup** — one recommended standalone emulator per system, opens the official
  download page, saves a launch profile. This is a genuinely nice, low-friction first run.
- **Standalone + RetroArch** launch paths with per-emulator argument presets.
- **Smoke-test audit** (`--audit-test-roms`) — validates emulator/ROM wiring before users hit it.
  Most competitors have nothing like this; it's a real differentiator worth leaning into.
- 8 systems (NES, SNES, GB/GBC/GBA, N64, PSX, Genesis), keyboard/mouse UI, controller support
  in progress on `feat/controller-support`.

## The competitive landscape

| Frontend | What it's known for | Where it beats RetroVault |
|----------|--------------------|---------------------------|
| **LaunchBox / Big Box** | Polished library + arcade-cabinet fullscreen mode | Metadata scraping, artwork, video previews, themes |
| **Playnite** | Unifies Steam/GoG/Epic **+** emulators, free & open source | Multi-store, play-time tracking, plugin ecosystem, gamepad UI |
| **ES-DE** | Modern EmulationStation fork, controller-first | System carousels, artwork scraping, favorites/collections, huge theme library |
| **RetroBat** | Bundles ES-DE + 30 pre-configured emulators, one installer | Zero-config plug-and-play on Windows |
| **Pegasus** | Cross-platform incl. Android, highly themeable | Skinnable UI, broad device support |
| **Skraper / ScreenScraper** | The metadata/artwork pipeline everyone plugs into | Box art, logos, screenshots, synopsis, genre, player count, ratings |

## The single biggest gap: metadata & artwork

Every mainstream frontend organizes games around **cover art and metadata** (box art, logos,
screenshots, synopsis, genre, players, ratings). RetroVault currently presents a functional
list. This is the #1 thing users notice and the clearest reason someone would pick ES-DE or
LaunchBox over RetroVault. Closing it changes the whole feel of the app.

## Prioritized improvement ideas

### Tier 1 — highest impact, defines the product
1. **Metadata + artwork scraping.** Integrate a source (ScreenScraper API is the community
   standard; IGDB/TheGamesDB are alternates). Cache box art, title logos, screenshots, and
   text metadata under `~/.retrovault/media/`. This unlocks everything below.
2. **Cover-art grid view.** A box-art grid alongside the current list. This alone closes most
   of the visual gap with ES-DE and LaunchBox.
3. **Finish controller-first navigation + a fullscreen "couch" mode.** You're already on this
   branch. A distraction-free fullscreen mode (LaunchBox's Big Box / ES-DE's core use case) is
   what makes a frontend feel like a console. High leverage given you're mid-flight here.

### Tier 2 — expected quality-of-life features
4. **Favorites, "Recently played," and custom collections.** Cheap to build, universally expected.
5. **Play-time tracking.** Log launch/exit timestamps per game (Playnite's most-loved feature).
6. **Auto-detect installed emulators on first run.** Scan common install paths / PATH so Easy
   Mode can pre-fill profiles instead of only linking downloads. Pairs perfectly with your audit.
7. **Auto-detect systems from folder structure.** Infer systems during SCAN ROMS instead of
   requiring manual `config.json` edits to add one.

### Tier 3 — differentiators / bigger bets
8. **RetroAchievements integration.** Show achievement counts per game (RetroArch exposes this;
   standalone via RA login). Strong retro-community draw.
9. **Video/screenshot preview on hover/select.** The "premium" touch LaunchBox and Pegasus use.
10. **Import from existing setups.** Read ES-DE / EmulationStation `gamelist.xml` or LaunchBox
    XML so switchers keep their curated data. Low cost, removes adoption friction.
11. **Theme/skin support.** Longer-term; ES-DE and Pegasus win loyalty through community themes.

### Optional / large scope
12. **Multi-store integration (Steam/GoG/Epic).** This is Playnite's whole identity and a big
    lift. Only pursue if you want RetroVault to be an everything-launcher rather than a focused,
    well-engineered ROM launcher. The focused path may be the stronger niche.

## Suggested next two moves

- **Move 1:** ScreenScraper integration + media cache (Tier 1 #1). It's the foundation for the
  grid view, previews, and richer detail panels.
- **Move 2:** Ship the cover-art grid + finish the controller/fullscreen work you've started.
  Together these are the difference between "a launcher script with a GUI" and "a frontend people
  choose."

## Where RetroVault should keep its edge

Don't lose the things competitors _don't_ have: the **audit/smoke-test** discipline and the
**clean, guided Easy Mode setup**. Reliability and a painless first run are underrated — lean
into "the ROM launcher that actually works on first try" as positioning.

## Sources

- [Comparison of frontends — Emulation General Wiki](https://emulation.gametechwiki.com/index.php/Comparison_of_frontends)
- [RetroBat vs ES-DE vs Playnite vs EmulationStation 2026](https://arcadesystems.co.uk/blog/post/retrobat-vs-es-de)
- [LaunchBox Alternatives — AlternativeTo](https://alternativeto.net/software/launchbox/?platform=windows)
- [Skraper Homepage](https://www.skraper.net/)
- [Scraping & Metadata — RetroBat Wiki](https://wiki.retrobat.org/navigation/scraping-and-metadata)
- [ES-DE Frontend](https://es-de.org/)
- [Playnite](https://playnite.net/)
