"""RetroVault entry point: GUI by default, CLI flags for tooling."""

import os
import sys
from pathlib import Path


def _enable_portable_mode(argv):
    if "--portable" not in argv:
        return argv
    executable_dir = Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).resolve().parent
    os.environ["RETROVAULT_HOME"] = str(executable_dir / "retrovault-data")
    return [arg for arg in argv if arg != "--portable"]


def _install_desktop_entry():
    from importlib import resources
    from shutil import copyfile

    applications_dir = Path.home() / ".local" / "share" / "applications"
    icons_dir = Path.home() / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    applications_dir.mkdir(parents=True, exist_ok=True)
    icons_dir.mkdir(parents=True, exist_ok=True)
    assets = resources.files("retrovault.data")
    with resources.as_file(assets.joinpath("retrovault.desktop")) as source:
        copyfile(source, applications_dir / "retrovault.desktop")
    with resources.as_file(assets.joinpath("retrovault.svg")) as source:
        copyfile(source, icons_dir / "retrovault.svg")
    print(f"Installed desktop entry to {applications_dir / 'retrovault.desktop'}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    argv = _enable_portable_mode(list(argv))

    from .core.paths import init_app_dirs
    init_app_dirs()

    if argv and argv[0] == "--version":
        from . import __version__
        print(f"RetroVault {__version__}")
        sys.exit(0)

    if argv and argv[0] == "--audit-test-roms":
        from .core.audit import audit_test_roms, load_test_rom_manifest
        from .core.config import load_config

        manifest = load_test_rom_manifest()
        results = audit_test_roms(load_config(), manifest)
        for result in results:
            print(f"{result['system']}: {result['status']} - {result['message']}")
        sys.exit(0 if all(r["status"] == "ok" for r in results) else 1)

    if argv and argv[0] == "--install-desktop-entry":
        _install_desktop_entry()
        return

    from .ui.app import main as run_gui
    run_gui()


if __name__ == "__main__":
    main()
