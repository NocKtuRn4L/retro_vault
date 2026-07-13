# PR12 — Hardware Matrix & Pi Kiosk Validation

Manual validation milestone for controller support. Unit tests and the headless
boot cover the logic; this checklist covers what only real hardware can prove:
mappings, latency, hot-plug, and no-desktop-flash across the launch/return
transition.

Run the diagnostic first on each machine:

```bash
retrovault-controller --once      # one snapshot: detected? buttons/axes
retrovault-controller --watch 15  # 15s live view — press every button
retrovault-controller --self-test # no-hardware pipeline check (also runs in CI)
```

> Note: some keyboards (e.g. Keychron HE) enumerate as an SDL joystick, so
> `--once` may report "controller detected: yes" with no gamepad plugged in.
> Use `--watch` and confirm real button/axis movement.

## A. Windows — controller matrix

For **each** of: Xbox (wired), Xbox (Bluetooth), DualShock 4 / DualSense, Switch Pro:

- [ ] `--watch` shows every face button, both shoulders, Start, Select, D-pad, and both sticks with correct semantic names.
- [ ] Face-button map correct: **A/south = Accept, B/east = Back** with `accept_button="south"`; flip Settings to `east` and confirm A/B swap.
- [ ] D-pad up/down moves the game row; left/right (and L/R shoulders) change the system filter.
- [ ] Left stick navigates with dead-zone applied — no drift when released; hysteresis prevents chatter at the threshold.
- [ ] Held direction: single step, then auto-repeat after the delay at a steady rate; release stops immediately.
- [ ] Start opens the emulator/settings manager; Back escapes focus to the game list.
- [ ] Accept launches the selected ROM.
- [ ] Measure **input-to-action latency < 20 ms** (visually acceptable; use high-speed capture if available).
- [ ] Idle CPU with controller connected stays negligible.

## B. Raspberry Pi 5 — Wayland/labwc

- [ ] Wired USB controller: full map via `--watch` (repeat section A nav checks).
- [ ] Bluetooth controller: pair, confirm map, and confirm reconnect after sleep.
- [ ] aarch64 wheel: `pip install "pygame-ce>=2.5"` succeeds and `python -c "import pygame"` works (CI also gates this).
- [ ] Launch RetroVault with `--kiosk`; confirm frameless fullscreen boot-to-frontend.
- [ ] Default RetroArch to fullscreen in kiosk mode (per PR8 policy resolver).

## C. Launch / return transition (both platforms)

Test with **RetroArch (Flatpak)** and **one standalone emulator** (e.g. mGBA):

- [ ] Accept → black `LAUNCHING…` overlay appears immediately; **no desktop flash** between RetroVault and the emulator.
- [ ] While the emulator runs, the **physical controller drives the emulator directly** — RetroVault is NOT polling (verify no ghost navigation).
- [ ] On emulator exit → brief `RETURNING…` overlay, RetroVault returns to foreground fullscreen, selected ROM + scroll position restored, table refocused.
- [ ] **No immediate relaunch**: hold Accept as the emulator closes — the 400 ms resume debounce must prevent an instant re-launch loop.
- [ ] Emulator that crashes / exits immediately: UI recovers cleanly, controls re-enabled, controller resumes, no stuck disabled state, no spurious error dialog for nonzero exit codes.
- [ ] A launch that fails to start (bad path) shows a warning dialog without exposing the desktop.

## D. Disconnect / edge cases

- [ ] Disconnect the controller mid-navigation → app stays responsive to keyboard/mouse; reconnect resumes without restarting the app.
- [ ] Disconnect during gameplay → emulator handles it; on return RetroVault re-detects on reconnect (periodic rescan).
- [ ] Dialogs (Settings, Setup/Emulator Manager): D-pad moves focus (skips disabled controls), L/R switches tabs, Accept activates, Back cancels.
- [ ] Controller-driven uninstall in the Emulator Manager prompts for confirmation before removing.
- [ ] Native file dialogs stay keyboard/mouse only (controller does not drive the library underneath them).

## Metrics to record

| Metric | Target | Xbox | DS/DualSense | Switch Pro | Pi USB | Pi BT |
|---|---|---|---|---|---|---|
| Input→action latency | < 20 ms | | | | | |
| Idle CPU (connected) | negligible | | | | | |
| Launch→emulator visible | — | | | | | |
| Emulator exit→frontend restored | — | | | | | |

Sign-off requires: no desktop flash, no stuck input, no duplicate launch, no
focus loss, across every row above.
