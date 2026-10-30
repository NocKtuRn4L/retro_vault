import copy
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from retrovault.core import launch, library
from retrovault.core.config import DEFAULT_CONFIG


def make_zip(path, entries):
    """Write a zip at ``path`` holding ``{name: bytes}`` entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


class ZipScanTests(unittest.TestCase):
    def _config(self, rom_dir, systems=None):
        return {"rom_dirs": [str(rom_dir)], "systems": systems or DEFAULT_CONFIG["systems"]}

    def _scan(self, root, systems=None):
        return {e["name"]: e for e in library.scan_roms(self._config(root, systems))}

    def test_single_rom_zip_is_a_game_named_after_the_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zpath = make_zip(root / "Tetris (World) (Rev 1).zip", {"Tetris (World) (Rev A).gb": b"x" * 64})

            lib = self._scan(root)

            self.assertEqual(list(lib), ["Tetris (World) (Rev 1)"])
            entry = lib["Tetris (World) (Rev 1)"]
            self.assertEqual(entry["system"], "gb")
            self.assertEqual(entry["path"], str(zpath))
            self.assertEqual(entry["ext"], ".zip")
            self.assertEqual(entry["size"], zpath.stat().st_size)

    def test_non_rom_extras_and_macos_forks_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_zip(root / "Kid Dracula (World).zip", {
                "Kid Dracula (World).nes": b"NES\x1a",
                "Kid Dracula (World).sav": b"\0" * 16,
                "readme.txt": b"hi",
                "__MACOSX/._Kid Dracula (World).nes": b"fork",
            })

            lib = self._scan(root)

            self.assertEqual(lib["Kid Dracula (World)"]["system"], "nes")

    def test_zip_without_a_known_rom_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_zip(root / "manual.zip", {"manual.pdf": b"%PDF", "notes.txt": b"hi"})
            make_zip(root / "empty.zip", {})

            self.assertEqual(self._scan(root), {})

    def test_zip_with_ambiguous_extension_is_skipped(self):
        # .bin is claimed by both psx and genesis; telling them apart needs the
        # contents, so a zipped .bin (here a SNES chip dump) is not guessed at.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_zip(root / "DSP1 (World) (Enhancement Chip).zip", {"DSP1 (World) (Enhancement Chip).bin": b"x" * 8192})

            with self.assertLogs(level="INFO") as logs:
                lib = self._scan(root)

            self.assertEqual(lib, {})
            self.assertIn("psx, genesis", "\n".join(logs.output))

    def test_zip_with_several_roms_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_zip(root / "pack.zip", {"a.gb": b"x", "b.gb": b"y"})
            make_zip(root / "FF7 (Disc 1).zip", {
                "FF7 (Disc 1).cue": b'FILE "FF7 (Disc 1).bin" BINARY\n',
                "FF7 (Disc 1).bin": b"x",
            })

            self.assertEqual(self._scan(root), {})

    def test_corrupt_zip_is_skipped_and_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.zip").write_bytes(b"PK\x03\x04 not really a zip")
            make_zip(root / "fine.zip", {"fine.gba": b"x"})

            with self.assertLogs(level="WARNING") as logs:
                lib = self._scan(root)

            self.assertEqual(set(lib), {"fine"})
            self.assertIn("broken.zip", "\n".join(logs.output))

    def test_multi_system_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "No-Intro"
            make_zip(root / "Nintendo - Game Boy" / "Tetris (World).zip", {"Tetris (World).gb": b"x"})
            make_zip(root / "Nintendo - Game Boy Color" / "Wario Land 3 (World).zip", {"Wario Land 3 (World).gbc": b"x"})
            make_zip(root / "Nintendo - Game Boy Advance" / "Golden Sun (USA).zip", {"Golden Sun (USA).gba": b"x"})
            make_zip(root / "Nintendo - Nintendo Entertainment System (Headered)" / "Metroid (USA).zip",
                     {"Metroid (USA).nes": b"x"})
            make_zip(root / "Nintendo - Super Nintendo Entertainment System" / "Super Metroid (Japan, USA).zip",
                     {"Super Metroid (Japan, USA).sfc": b"x"})
            (root / "Nintendo - Game Boy" / "metadata.txt").write_text("not a rom")

            lib = library.scan_roms(self._config(root))

            self.assertEqual(
                [(e["system"], e["name"]) for e in lib],
                [
                    ("gb", "Tetris (World)"),
                    ("gba", "Golden Sun (USA)"),
                    ("gbc", "Wario Land 3 (World)"),
                    ("nes", "Metroid (USA)"),
                    ("snes", "Super Metroid (Japan, USA)"),
                ],
            )

    def test_bare_roms_scan_as_before_next_to_zips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mario.nes").write_bytes(b"abc")
            (root / "sonic.bin").write_bytes(b"x" * 1024)  # small standalone .bin: genesis
            (root / "FF7.cue").write_text('FILE "FF7.bin" BINARY\n')
            (root / "FF7.bin").write_bytes(b"x")  # owned by its .cue
            make_zip(root / "zelda.zip", {"zelda.sfc": b"x"})

            lib = self._scan(root)

            self.assertEqual(set(lib), {"mario", "sonic", "FF7", "zelda"})
            self.assertEqual(lib["mario"], {
                "name": "mario", "path": str(root / "mario.nes"), "system": "nes", "ext": ".nes", "size": 3,
            })
            self.assertEqual(lib["sonic"]["system"], "genesis")
            self.assertEqual(lib["FF7"]["ext"], ".cue")
            self.assertEqual(lib["zelda"]["system"], "snes")

    def test_system_that_claims_zip_keeps_other_zips(self):
        systems = {
            "nes": {"extensions": [".nes"]},
            "arcade": {"extensions": [".zip"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_zip(root / "pacman.zip", {"pacman.6e": b"x", "pacman.6f": b"y"})
            make_zip(root / "Metroid (USA).zip", {"Metroid (USA).nes": b"x"})

            lib = self._scan(root, systems)

            self.assertEqual(lib["pacman"]["system"], "arcade")
            self.assertEqual(lib["Metroid (USA)"]["system"], "nes")


class ZipLaunchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.extracted_dir = self.root / "extracted"
        patcher = mock.patch.object(launch, "EXTRACTED_DIR", self.extracted_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Keep cores downloaded on this machine from turning core names into paths.
        patcher = mock.patch.object(launch, "CORES_DIR", self.root / "cores")
        patcher.start()
        self.addCleanup(patcher.stop)

        self.zip_path = make_zip(self.root / "roms" / "Metroid (USA).zip", {
            "Metroid (USA).nes": b"NES\x1a" + b"\1" * 100,
            "Metroid (USA).txt": b"notes",
        })
        self.rom = {"name": "Metroid (USA)", "path": str(self.zip_path), "system": "nes", "ext": ".zip"}
        self.emulator = self.root / "emulator"
        self.emulator.write_bytes(b"exe")
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.config["controller"]["prefer_retroarch"] = False
        self.config["emulators"]["nes"].update(path=str(self.emulator), args="{rom}", profile="custom")

    def test_zip_capable_emulator_gets_the_zip(self):
        for profile in ("mesen-ce", "mgba", "retroarch"):
            self.config["emulators"]["nes"]["profile"] = profile
            rom, error = launch.prepare_rom_for_launch(self.rom, self.config)
            self.assertIsNone(error)
            self.assertEqual(rom["path"], str(self.zip_path), profile)
        self.assertFalse(self.extracted_dir.exists())

    def test_retroarch_binary_gets_the_zip(self):
        self.config["use_retroarch"] = True
        self.config["retroarch_path"] = str(self.emulator)

        rom, error = launch.prepare_rom_for_launch(self.rom, self.config)
        cmd, error = launch.build_launch_command(rom, self.config)

        self.assertIsNone(error)
        self.assertEqual(cmd, [str(self.emulator), "-L", "nestopia_libretro", str(self.zip_path)])
        self.assertFalse(self.extracted_dir.exists())

    def test_other_emulators_get_an_extracted_copy(self):
        rom, error = launch.prepare_rom_for_launch(self.rom, self.config)

        self.assertIsNone(error)
        extracted = Path(rom["path"])
        self.assertEqual(extracted, self.extracted_dir / "nes" / "Metroid (USA)" / "Metroid (USA).nes")
        self.assertEqual(extracted.read_bytes(), b"NES\x1a" + b"\1" * 100)
        self.assertEqual(self.rom["path"], str(self.zip_path))  # library entry untouched
        self.assertEqual(sorted(p.name for p in extracted.parent.iterdir()), ["Metroid (USA).nes"])

    def test_extracted_copy_is_reused_and_refreshed_when_stale(self):
        first = launch.extract_zipped_rom(self.zip_path, self.config)
        save = first.with_suffix(".sav")
        save.write_bytes(b"save data")  # emulators often save beside the ROM

        with mock.patch.object(launch.shutil, "copyfileobj") as copy_spy:
            self.assertEqual(launch.extract_zipped_rom(self.zip_path, self.config), first)
        copy_spy.assert_not_called()

        first.write_bytes(b"NES\x1a" + b"\2" * 100)  # same size, different contents
        launch.extract_zipped_rom(self.zip_path, self.config)
        self.assertEqual(first.read_bytes(), b"NES\x1a" + b"\1" * 100)
        self.assertEqual(save.read_bytes(), b"save data")

    def test_entry_paths_cannot_escape_the_extract_dir(self):
        zip_path = make_zip(self.root / "evil.zip", {"../../../evil.nes": b"x"})

        extracted = launch.extract_zipped_rom(zip_path, self.config)

        self.assertEqual(extracted, self.extracted_dir / "nes" / "evil" / "evil.nes")

    def test_start_launch_process_runs_the_extracted_rom(self):
        with mock.patch.object(launch.subprocess, "Popen") as popen:
            proc, error = launch.start_launch_process(self.rom, self.config)

        self.assertIsNone(error)
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd, [str(self.emulator), str(self.extracted_dir / "nes" / "Metroid (USA)" / "Metroid (USA).nes")])

    def test_unconfigured_emulator_does_not_extract(self):
        self.config["emulators"]["nes"]["path"] = ""

        ok, error = launch.launch_rom(self.rom, self.config)

        self.assertFalse(ok)
        self.assertIn("No emulator configured", error)
        self.assertFalse(self.extracted_dir.exists())

    def test_unreadable_zip_reports_an_error(self):
        self.zip_path.write_bytes(b"garbage")

        with self.assertLogs(level="WARNING"):
            proc, error = launch.start_launch_process(self.rom, self.config)

        self.assertIsNone(proc)
        self.assertIn("Could not extract the ROM", error)

    def test_system_that_claims_zip_is_launched_with_the_zip(self):
        self.config["systems"]["nes"]["extensions"] = [".nes", ".zip"]

        rom, error = launch.prepare_rom_for_launch(self.rom, self.config)

        self.assertIsNone(error)
        self.assertEqual(rom["path"], str(self.zip_path))


if __name__ == "__main__":
    unittest.main()
