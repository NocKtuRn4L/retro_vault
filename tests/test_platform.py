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

    def test_is_raspberry_pi_false_on_this_machine(self):
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
