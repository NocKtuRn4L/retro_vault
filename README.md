# RetroVault - Modular ROM Launcher

A cross-platform desktop ROM library frontend for Windows and Linux, including Raspberry Pi.
No emulation is built in. RetroVault launches your installed emulators with your ROMs.

---

## Requirements

- **Python 3.7+**
- **Tkinter** (usually bundled with Python; on Debian or Raspberry Pi install with `sudo apt install python3-tk`)

---

## Running the App

```bash
python3 launcher.py
# or on Windows:
python launcher.py
```

Config and library files are saved to `~/.retrovault/`.

For emulator smoke testing, RetroVault also looks for a test ROM manifest at
`~/.retrovault/test_roms.json`.

---

## Quick Start

1. Click **SETUP** and use Easy Mode to follow the recommended emulator links.
2. Click **+ ADD ROM DIR** and choose your ROM folder.
3. Click **SCAN ROMS** to build your library.
4. Open **SETTINGS > EMULATORS** if you want to fine-tune paths, args, or profiles.
5. Double-click any game to launch it.

---

## Supported Systems

| System | Extensions |
|--------|------------|
| NES | `.nes` |
| SNES | `.sfc`, `.smc` |
| Game Boy | `.gb` |
| Game Boy Color | `.gbc` |
| Game Boy Advance | `.gba` |
| Nintendo 64 | `.z64`, `.n64`, `.v64` |
| PlayStation 1 | `.bin`, `.cue`, `.iso`, `.img` |
| Sega Genesis | `.md`, `.bin`, `.gen`, `.smd` |

---

## Emulator Setup

### Easy Mode

Easy Mode is the intended first-run path. It recommends one standalone emulator per system, opens the official download page, and saves the matching launch profile for RetroVault.

Recommended standalone emulators:

| System | Recommendation |
|--------|----------------|
| NES | MesenCE |
| SNES | MesenCE |
| GB / GBC | mGBA |
| GBA | mGBA |
| N64 | Rosalie's Mupen GUI |
| PSX | DuckStation |
| Genesis | ares |

Notes:

- `Rosalie's Mupen GUI` is the default N64 recommendation for RetroVault.
- `Project64` remains a good Windows-specific alternate for users who prefer it.
- `ares` is the current Easy Mode Genesis default.

### RetroArch

RetroArch remains supported, but it is better treated as an advanced path.

1. Install [RetroArch](https://www.retroarch.com/).
2. Download the cores you want inside RetroArch.
3. In **SETTINGS > EMULATORS**, enable **Use RetroArch** and set the RetroArch binary path.
4. Set the matching core name for each system.

### Standalone Emulators

If you prefer manual setup, point each system at a standalone emulator executable in **SETTINGS > EMULATORS**.

- The `{rom}` placeholder in the args field is replaced with the ROM path at launch.
- The emulator profile dropdown applies known-good argument presets for common emulators.

---

## Smoke Testing Emulator Setup

RetroVault now supports a simple audit pass for emulator wiring so we can catch broken paths or bad launch templates before users do.

1. Copy [test_roms.sample.json](/C:/repos/retro_vault/test_roms.sample.json) to `~/.retrovault/test_roms.json`.
2. Replace each placeholder path with a legal homebrew or test ROM you already have.
3. Run:

```bash
python launcher.py --audit-test-roms
```

The audit checks that:

- a test ROM path is configured for the system
- the ROM file exists
- the configured emulator executable exists
- RetroVault can build a valid launch command for that pairing

This gives us a lightweight regression check for each supported system without bundling copyrighted game data.

Suggested practice:

- Keep one small, known-good smoke ROM per supported system.
- Re-run the audit after changing emulator defaults, launch args, or setup flows.
- Add the audit command to CI later if you maintain a machine with those emulator binaries installed.

Do not use public commercial ROM archives as a packaged test source. For documentation and QA, we should stick to legal homebrew, test ROMs, and user-provided content.

---

## Adding New Systems

Edit `~/.retrovault/config.json` and add an entry to the `"systems"` object:

```json
"nds": {
  "name": "Nintendo DS",
  "short": "NDS",
  "extensions": [".nds"],
  "emulator_key": "nds",
  "color": "#c0392b",
  "icon": "DS"
}
```

Then add a matching entry under `"emulators"` and restart the app.

---

## Controls

| Action | How |
|--------|-----|
| Launch game | Double-click |
| Context menu | Right-click |
| Filter by system | Click sidebar |
| Search | Type in the search box |

---

## File Locations

| File | Location |
|------|----------|
| Config | `~/.retrovault/config.json` |
| Library cache | `~/.retrovault/library.json` |
| Launch log | `~/.retrovault/retrovault.log` |

---

## Troubleshooting Launches

RetroVault validates emulator and ROM paths before launching. If a launch fails, check the popup message and `~/.retrovault/retrovault.log` for launch details.
