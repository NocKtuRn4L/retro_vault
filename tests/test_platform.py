import os
import tempfile
import unittest

from retrovault.platform import detect, recommend


class DetectTests(unittest.TestCase):
    def test_current_platform_windows(self):
        self.assertEqual(detect.current_platform("win32", "AMD64"), "windows-x86_64")

    def test_current_platform_linux_aarch64(self):
        self.assertEqual(detect.current_platform("linux", "aarch64"), "linux-aarch64")

    def test_current_platform_linux_x86_64(self):
        self.assertEqual(detect.current_platform("linux", "x86_64"), "linux-x86_64")

    def test_current_platform_darwin(self):
        self.assertEqual(detect.current_platform("darwin", "arm64"), "darwin-arm64")


class RaspberryPiDetectTests(unittest.TestCase):
    """Point detection at a temp file so results don't depend on the test machine."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.model_path = os.path.join(tmp.name, "model")
        self.addCleanup(setattr, detect, "_DEVICE_TREE_MODEL", detect._DEVICE_TREE_MODEL)
        detect._DEVICE_TREE_MODEL = self.model_path

    def _write_model(self, content):
        with open(self.model_path, "wb") as f:
            f.write(content)

    def test_is_raspberry_pi_true_for_pi_model(self):
        # The kernel exposes the model string NUL-terminated.
        self._write_model(b"Raspberry Pi 5 Model B Rev 1.1\x00")
        self.assertTrue(detect.is_raspberry_pi())

    def test_is_raspberry_pi_false_for_other_model(self):
        self._write_model(b"Pine64 RockPro64 v2.1\x00")
        self.assertFalse(detect.is_raspberry_pi())

    def test_is_raspberry_pi_false_without_device_tree(self):
        # Windows and most x86 Linux machines have no device-tree model file.
        self.assertFalse(detect.is_raspberry_pi())


class RecommendTests(unittest.TestCase):
    def test_get_recommended_emulator_explicit_platform_key(self):
        recommendation = recommend.get_recommended_emulator("genesis", "linux-aarch64")

        self.assertIn("RetroArch", recommendation["name"])

    def test_default_backend_linux_aarch64(self):
        self.assertEqual(recommend.default_backend("linux-aarch64"), "retroarch")

    def test_default_backend_windows_is_none(self):
        self.assertIsNone(recommend.default_backend("windows-x86_64"))


class RecommendAutodetectTests(unittest.TestCase):
    def setUp(self):
        self._orig_current_platform = detect.current_platform
        detect.current_platform = lambda *a, **k: "linux-aarch64"
        self.addCleanup(setattr, detect, "current_platform", self._orig_current_platform)

    def test_get_recommended_emulator_autodetects_platform(self):
        recommendation = recommend.get_recommended_emulator("genesis")

        self.assertIn("RetroArch", recommendation["name"])


if __name__ == "__main__":
    unittest.main()
