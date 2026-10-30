import io
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from retrovault.providers.cores import core_url, index_url, install_cores, parse_index
from retrovault.providers.installer import ChecksumError, InstallError


class FakeResponse(io.BytesIO):
    def __init__(self, payload):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def elf(machine=183, body=b"core"):
    return b"\x7fELF" + bytes(14) + struct.pack("<H", machine) + bytes(12) + body


def core_zip(filename, content):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(filename, content)
    return output.getvalue()


def index_line(filename, content, date="2026-10-30"):
    return f"{date} {zlib.crc32(content) & 0xFFFFFFFF:08x} {filename}.zip\n"


class FakeBuildbot:
    """Serves an index plus core zips for linux-aarch64 and records requested URLs."""

    def __init__(self, cores, index=None):
        self.files = {core_url(name, "linux-aarch64"): core_zip(f"{name}.so", content) for name, content in cores.items()}
        listing = index if index is not None else "".join(
            index_line(f"{name}.so", content) for name, content in cores.items()
        )
        self.files[index_url("linux-aarch64")] = listing.encode()
        self.requests = []

    def __call__(self, url, timeout=None):
        self.requests.append(url)
        if url not in self.files:
            raise OSError(f"404 {url}")
        return FakeResponse(self.files[url])


class CoreDownloaderTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.cores_dir = Path(self._temp.name) / "cores"

    def tearDown(self):
        self._temp.cleanup()

    def test_parse_index_maps_filenames_to_date_and_crc(self):
        entries = parse_index("2026-10-30 7b2eb684 nestopia_libretro.so.zip\nnot an entry\n")

        self.assertEqual(entries["nestopia_libretro.so.zip"].crc, 0x7B2EB684)
        self.assertEqual(entries["nestopia_libretro.so.zip"].date, "2026-10-30")
        self.assertEqual(len(entries), 1)

    def test_installs_each_core_once_and_reports_progress(self):
        buildbot = FakeBuildbot({"nestopia_libretro": elf(body=b"nes"), "gambatte_libretro": elf(body=b"gb")})
        progress = []

        installed = install_cores(
            ["nestopia_libretro", "gambatte_libretro", "gambatte_libretro"],
            "linux-aarch64",
            cores_dir=self.cores_dir,
            opener=buildbot,
            progress=lambda name, done, total: progress.append((name, done, total)),
        )

        self.assertEqual(installed["nestopia_libretro"], self.cores_dir / "nestopia_libretro.so")
        self.assertEqual(installed["gambatte_libretro"].read_bytes(), elf(body=b"gb"))
        self.assertEqual(sum(url.endswith("gambatte_libretro.so.zip") for url in buildbot.requests), 1)
        nes_size = len(buildbot.files[core_url("nestopia_libretro", "linux-aarch64")])
        self.assertIn(("nestopia_libretro", 0, nes_size), progress)
        self.assertIn(("nestopia_libretro", nes_size, nes_size), progress)
        self.assertEqual(sorted(path.name for path in self.cores_dir.iterdir()), ["gambatte_libretro.so", "nestopia_libretro.so"])

    def test_current_core_is_not_downloaded_again(self):
        content = elf(body=b"snes")
        self.cores_dir.mkdir()
        (self.cores_dir / "snes9x_libretro.so").write_bytes(content)
        buildbot = FakeBuildbot({"snes9x_libretro": content})

        install_cores(["snes9x_libretro"], "linux-aarch64", cores_dir=self.cores_dir, opener=buildbot)

        self.assertEqual(buildbot.requests, [index_url("linux-aarch64")])

    def test_outdated_core_is_replaced(self):
        self.cores_dir.mkdir()
        (self.cores_dir / "mgba_libretro.so").write_bytes(elf(body=b"old"))
        buildbot = FakeBuildbot({"mgba_libretro": elf(body=b"new")})

        install_cores(["mgba_libretro"], "linux-aarch64", cores_dir=self.cores_dir, opener=buildbot)

        self.assertEqual((self.cores_dir / "mgba_libretro.so").read_bytes(), elf(body=b"new"))

    def test_crc_mismatch_with_index_fails_and_leaves_nothing(self):
        buildbot = FakeBuildbot(
            {"mgba_libretro": elf(body=b"tampered")},
            index=index_line("mgba_libretro.so", elf(body=b"expected")),
        )

        with self.assertRaisesRegex(ChecksumError, "CRC-32 mismatch"):
            install_cores(["mgba_libretro"], "linux-aarch64", cores_dir=self.cores_dir, opener=buildbot)

        self.assertEqual(list(self.cores_dir.iterdir()), [])

    def test_core_for_another_cpu_is_rejected(self):
        buildbot = FakeBuildbot({"nestopia_libretro": elf(machine=62)})

        with self.assertRaisesRegex(InstallError, "different CPU"):
            install_cores(["nestopia_libretro"], "linux-aarch64", cores_dir=self.cores_dir, opener=buildbot)

        self.assertFalse((self.cores_dir / "nestopia_libretro.so").exists())

    def test_core_missing_from_index_is_reported(self):
        buildbot = FakeBuildbot({"nestopia_libretro": elf()})

        with self.assertRaisesRegex(InstallError, "no snes9x_libretro core"):
            install_cores(["snes9x_libretro"], "linux-aarch64", cores_dir=self.cores_dir, opener=buildbot)

    def test_unreachable_index_is_an_install_error(self):
        def offline(url, timeout=None):
            raise OSError("offline")

        with self.assertRaisesRegex(InstallError, "core index"):
            install_cores(["nestopia_libretro"], "linux-aarch64", cores_dir=self.cores_dir, opener=offline)

    def test_core_names_cannot_escape_the_cores_directory(self):
        buildbot = FakeBuildbot({"nestopia_libretro": elf()})

        with self.assertRaisesRegex(InstallError, "Invalid libretro core name"):
            install_cores(["../evil_libretro"], "linux-aarch64", cores_dir=self.cores_dir, opener=buildbot)

    def test_unsupported_platform_is_an_install_error(self):
        with self.assertRaisesRegex(InstallError, "not available for darwin-arm64"):
            install_cores(["nestopia_libretro"], "darwin-arm64", cores_dir=self.cores_dir)

    def test_urls_follow_the_buildbot_layout(self):
        self.assertEqual(
            core_url("snes9x_libretro", "windows-x86_64"),
            "https://buildbot.libretro.com/nightly/windows/x86_64/latest/snes9x_libretro.dll.zip",
        )
        self.assertEqual(
            index_url("linux-aarch64"),
            "https://buildbot.libretro.com/nightly/linux/aarch64/latest/.index-extended",
        )


if __name__ == "__main__":
    unittest.main()
