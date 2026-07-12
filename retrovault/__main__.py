"""RetroVault entry point: GUI by default, CLI flags for tooling."""

import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

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

    from .ui_tk import RetroVault
    app = RetroVault()
    app.mainloop()


if __name__ == "__main__":
    main()
