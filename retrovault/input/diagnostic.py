"""Controller diagnostic command for RetroVault.

A small, dependency-light CLI for manual QA and CI smoke tests. It exercises the
input pipeline without requiring any physical controller hardware:

* default / ``--once``  -- start an :class:`SdlBackend`, poll a few times, and
  print the detected controllers, connection status, and a snapshot of the
  normalized :class:`BackendState`. If pygame/SDL is unavailable it prints a
  clear message and exits 0 (a diagnostic that finds "no SDL" is informative,
  not a failure).
* ``--watch [SECONDS]`` -- poll at ~10 Hz for a bounded duration so a human can
  press buttons and watch the normalized state change. Always terminates.
* ``--self-test``       -- use the hardware-free :class:`NullBackend`, assert the
  pipeline imports and that a poll returns a neutral state, print ``OK``, and
  exit 0. This is the mode CI runs.

The command never opens a display/window, never loops unbounded, and imports
pygame lazily (via :class:`SdlBackend`), so it is safe to run in headless CI.
"""

import argparse
import sys
import time
from collections.abc import Sequence

from .backend import NEUTRAL_STATE, BackendState, NullBackend
from .sdl_backend import SdlBackend

# Bound for --once polling and the default --watch duration. Kept small so the
# command always terminates quickly.
_ONCE_POLLS = 5
_DEFAULT_WATCH_SECONDS = 3.0
_WATCH_HZ = 10.0


def _format_state(state: BackendState) -> str:
    """Render a :class:`BackendState` as a compact one-line summary."""
    buttons = ", ".join(sorted(state.buttons)) if state.buttons else "(none)"
    axis_x, axis_y = state.axes
    return f"buttons=[{buttons}] axes=({axis_x:+.2f}, {axis_y:+.2f})"


def _run_self_test() -> int:
    """Exercise the pipeline with the hardware-free NullBackend."""
    backend = NullBackend()
    backend.start()
    try:
        state = backend.poll()
    finally:
        backend.stop()

    # The null backend must report disconnected and emit the neutral snapshot.
    assert backend.is_connected() is False, "NullBackend must report disconnected"
    assert state == NEUTRAL_STATE, "NullBackend must poll a neutral BackendState"
    assert not state.buttons, "neutral state must have no pressed buttons"
    assert state.axes == (0.0, 0.0), "neutral state must have centered axes"

    print("self-test OK: input pipeline imports and NullBackend polls neutral")
    return 0


def _run_once() -> int:
    """Start an SdlBackend, poll a few times, and report what was detected."""
    backend = SdlBackend()
    backend.start()
    try:
        state = NEUTRAL_STATE
        for _ in range(_ONCE_POLLS):
            state = backend.poll()
        connected = backend.is_connected()
    finally:
        backend.stop()

    if connected:
        print("controller detected: yes")
        print(f"state: {_format_state(state)}")
    else:
        print("controller detected: no (no controller connected, or SDL/pygame unavailable)")
        print(f"state: {_format_state(state)}")
    return 0


def _run_watch(seconds: float) -> int:
    """Poll at ~10 Hz for a bounded duration so a human can press buttons."""
    duration = max(0.0, seconds)
    interval = 1.0 / _WATCH_HZ
    max_iterations = int(duration * _WATCH_HZ) + 1

    backend = SdlBackend()
    backend.start()
    try:
        if not backend.is_connected():
            print("watch: no controller connected yet; press a button to connect it...")
        deadline = time.monotonic() + duration
        for _ in range(max_iterations):
            state = backend.poll()
            status = "connected" if backend.is_connected() else "disconnected"
            print(f"[{status}] {_format_state(state)}")
            if time.monotonic() >= deadline:
                break
            time.sleep(interval)
    finally:
        backend.stop()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retrovault-controller",
        description="Diagnose RetroVault controller input without requiring hardware.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--once",
        action="store_true",
        help="Poll the SDL backend a few times and print the detected state (default).",
    )
    group.add_argument(
        "--watch",
        nargs="?",
        type=float,
        const=_DEFAULT_WATCH_SECONDS,
        metavar="SECONDS",
        help=f"Poll at ~10 Hz for SECONDS (default {_DEFAULT_WATCH_SECONDS:g}s) so you can press buttons.",
    )
    group.add_argument(
        "--self-test",
        action="store_true",
        help="Run the hardware-free NullBackend self-test (used by CI) and exit 0.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``retrovault-controller`` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_test()
    if args.watch is not None:
        return _run_watch(args.watch)
    # Default behavior (with or without an explicit --once) is a single poll pass.
    return _run_once()


if __name__ == "__main__":
    sys.exit(main())
