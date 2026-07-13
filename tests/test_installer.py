import hashlib
import io
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from retrovault.providers.installer import ChecksumError, InstallError, InstallInstruction, install
from retrovault.providers.installer import uninstall as installer_uninstall
from retrovault.providers.manifest import InstallStrategy


class FakeResponse(io.BytesIO):
    def __init__(self, payload):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def zip_payload(name="nested/emulator.exe", content=b"binary"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, content)
    return output.getvalue()


class InstallerTests(unittest.TestCase):
    def test_checksum_mismatch_is_a_hard_failure_and_removes_download(self):
        strategy = InstallStrategy(
            "download",
            url="https://example.invalid/emulator.zip",
            sha256="0" * 64,
            archive="zip",
            exe="emulator.exe",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            with self.assertRaises(ChecksumError):
                install("example", "1.0", strategy, app_dir=app_dir, opener=lambda *args, **kwargs: FakeResponse(b"bad"))

            self.assertFalse((app_dir / "downloads" / "emulator.zip").exists())
            self.assertFalse((app_dir / "emulators" / "example" / "1.0").exists())

    def test_zip_extracts_into_versioned_layout_and_reports_progress(self):
        payload = zip_payload()
        strategy = InstallStrategy(
            "download",
            url="https://example.invalid/emulator.zip",
            sha256=hashlib.sha256(payload).hexdigest(),
            archive="zip",
            exe="emulator.exe",
        )
        progress = []
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = install(
                "example",
                "1.2.3",
                strategy,
                app_dir=Path(temp_dir),
                opener=lambda *args, **kwargs: FakeResponse(payload),
                progress=lambda done, total: progress.append((done, total)),
            )

            self.assertEqual(executable, (Path(temp_dir) / "emulators/example/1.2.3/nested/emulator.exe").resolve())
            self.assertEqual(executable.read_bytes(), b"binary")
            self.assertEqual(progress[0], (0, len(payload)))
            self.assertEqual(progress[-1], (len(payload), len(payload)))

    def test_appimage_is_copied_and_made_executable(self):
        payload = b"appimage"
        strategy = InstallStrategy(
            "download",
            url="https://example.invalid/Test.AppImage",
            sha256=hashlib.sha256(payload).hexdigest(),
            archive="appimage",
            exe="Test.AppImage",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(Path, "chmod", autospec=True) as chmod:
                executable = install(
                    "example",
                    "2.0",
                    strategy,
                    app_dir=Path(temp_dir),
                    opener=lambda *args, **kwargs: FakeResponse(payload),
                )

            self.assertTrue(executable.is_file())
            mode = chmod.call_args.args[1]
            self.assertTrue(mode & stat.S_IXUSR)

    def test_7z_extracts_portable_executable(self):
        payload = b"7z-archive"
        strategy = InstallStrategy(
            "download",
            url="https://example.invalid/emulator.7z",
            sha256=hashlib.sha256(payload).hexdigest(),
            archive="7z",
            exe="Emulator.exe",
        )
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if "-tf" in command:
                return subprocess.CompletedProcess(command, 0, stdout="nested/Emulator.exe\n")
            destination = Path(command[command.index("-C") + 1])
            (destination / "nested").mkdir()
            (destination / "nested" / "Emulator.exe").write_bytes(b"portable")
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("retrovault.providers.installer.shutil.which", return_value="tar.exe"):
                executable = install(
                    "example",
                    "1.0",
                    strategy,
                    app_dir=Path(temp_dir),
                    opener=lambda *args, **kwargs: FakeResponse(payload),
                    runner=runner,
                )

            self.assertEqual(executable.read_bytes(), b"portable")
        self.assertIn("-tf", calls[0][0])
        self.assertIn("-xf", calls[1][0])

    def test_apt_returns_instruction_without_running_subprocess(self):
        calls = []
        result = install(
            "mgba",
            "0.10.5",
            InstallStrategy("apt", package="mgba-qt"),
            runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        self.assertEqual(result, InstallInstruction("sudo apt install mgba-qt"))
        self.assertEqual(calls, [])

    def test_failed_strategy_uses_nested_flatpak_fallback(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        strategy = InstallStrategy(
            "download",
            url="https://example.invalid/missing.zip",
            sha256="0" * 64,
            archive="zip",
            exe="missing.exe",
            fallback=InstallStrategy("flatpak", flatpak_id="org.example.Emulator"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = install(
                "example",
                "1.0",
                strategy,
                assume_yes=True,
                app_dir=Path(temp_dir),
                opener=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
                runner=runner,
            )

        self.assertEqual(result, "org.example.Emulator")
        self.assertEqual(calls[0][0], ["flatpak", "install", "-y", "--user", "flathub", "org.example.Emulator"])
        self.assertTrue(calls[0][1]["check"])


    def test_uninstall_download_deletes_emulator_directory(self):
        payload = zip_payload()
        strategy = InstallStrategy(
            "download",
            url="https://example.invalid/emulator.zip",
            sha256=hashlib.sha256(payload).hexdigest(),
            archive="zip",
            exe="emulator.exe",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            executable = install(
                "example",
                "managed",
                strategy,
                app_dir=app_dir,
                opener=lambda *args, **kwargs: FakeResponse(payload),
            )

            self.assertTrue(executable.is_file())

            result = installer_uninstall("example", strategy, executable, app_dir=app_dir)
            self.assertIsNone(result)
            self.assertFalse((app_dir / "emulators" / "example").exists())

    def test_uninstall_download_missing_directory_does_not_raise(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            strategy = InstallStrategy("download", url="https://example.invalid/e.zip", sha256="0" * 64, exe="e.exe")
            result = installer_uninstall("example", strategy, Path(temp_dir) / "nonexistent" / "e.exe", app_dir=app_dir)
            self.assertIsNone(result)

    def test_uninstall_flatpak_runs_uninstall_command(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        strategy = InstallStrategy("flatpak", flatpak_id="org.example.Emulator")
        result = installer_uninstall("example", strategy, "org.example.Emulator", runner=runner)

        self.assertIsNone(result)
        self.assertEqual(calls[0][0], ["flatpak", "uninstall", "-y", "--user", "org.example.Emulator"])
        self.assertTrue(calls[0][1]["check"])

    def test_uninstall_flatpak_failure_raises_install_error(self):
        def runner(command, **kwargs):
            raise subprocess.CalledProcessError(1, command)

        strategy = InstallStrategy("flatpak", flatpak_id="org.example.Missing")
        with self.assertRaises(InstallError):
            installer_uninstall("example", strategy, "org.example.Missing", runner=runner)

    def test_uninstall_apt_returns_remove_instruction(self):
        strategy = InstallStrategy("apt", package="mgba-qt")
        installed = InstallInstruction("sudo apt install mgba-qt")
        instruction = installer_uninstall("mgba", strategy, installed)

        self.assertEqual(instruction, InstallInstruction("sudo apt remove mgba-qt"))


if __name__ == "__main__":
    unittest.main()
