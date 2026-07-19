"""Tests for seamless emulator controller passthrough (implementation plan 8a).

The connected pad's SDL mapping is injected into a launched emulator's environment
(SDL_GAMECONTROLLERCONFIG) so SDL-based emulators recognize it with no manual setup.
"""

import os
import unittest
from unittest import mock

from retrovault.core import launch

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from retrovault.input.backend import NullBackend
    from retrovault.input.router import ControllerRouter, InputStateMachine

    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


class EmulatorEnvTests(unittest.TestCase):
    def test_env_includes_mapping_when_enabled(self):
        cfg = {"controller": {"assist_emulator_input": True}}
        env = launch._emulator_env(cfg, "GUID,Pad,a:b0,")
        self.assertIsNotNone(env)
        self.assertEqual(env["SDL_GAMECONTROLLERCONFIG"], "GUID,Pad,a:b0,")

    def test_env_is_none_without_mapping(self):
        cfg = {"controller": {"assist_emulator_input": True}}
        self.assertIsNone(launch._emulator_env(cfg, None))
        self.assertIsNone(launch._emulator_env(cfg, ""))

    def test_env_is_none_when_assist_disabled(self):
        cfg = {"controller": {"assist_emulator_input": False}}
        self.assertIsNone(launch._emulator_env(cfg, "GUID,Pad,a:b0,"))

    def test_assist_defaults_on_when_unset(self):
        self.assertTrue(launch._assist_emulator_input({}))
        self.assertTrue(launch._assist_emulator_input({"controller": {}}))


class FlatpakEnvArgsTests(unittest.TestCase):
    def test_env_arg_present_when_enabled(self):
        cfg = {"controller": {"assist_emulator_input": True}}
        self.assertEqual(
            launch._flatpak_env_args(cfg, "GUID,Pad,a:b0,"),
            ["--env=SDL_GAMECONTROLLERCONFIG=GUID,Pad,a:b0,"],
        )

    def test_env_arg_absent_when_disabled_or_no_mapping(self):
        off = {"controller": {"assist_emulator_input": False}}
        self.assertEqual(launch._flatpak_env_args(off, "x"), [])
        self.assertEqual(launch._flatpak_env_args({}, None), [])


class BuildCommandFlatpakTests(unittest.TestCase):
    def _config(self):
        return {
            "systems": {"nes": {"extensions": [".nes"]}},
            "emulators": {"nes": {"launch_type": "flatpak", "flatpak_id": "com.example.Emu", "args": "{rom}"}},
            "emulator_profiles": {},
            "controller": {"assist_emulator_input": True},
        }

    def test_flatpak_command_carries_env_arg_before_app_id(self):
        rom = {"system": "nes", "path": "/roms/x.nes"}
        cmd, err = launch.build_launch_command(
            rom, self._config(), platform="linux", validate=False,
            controller_mapping="GUID,Pad,a:b0,",
        )
        self.assertIsNone(err)
        self.assertEqual(cmd[:2], ["flatpak", "run"])
        env_arg = "--env=SDL_GAMECONTROLLERCONFIG=GUID,Pad,a:b0,"
        self.assertIn(env_arg, cmd)
        # --env must precede the flatpak app id (flatpak parses run options first).
        self.assertLess(cmd.index(env_arg), cmd.index("com.example.Emu"))


class StartLaunchProcessEnvTests(unittest.TestCase):
    def _run(self, mapping):
        cfg = {"controller": {"assist_emulator_input": True}}
        rom = {"system": "nes", "path": "/roms/x.nes", "name": "X"}
        fake_proc = mock.Mock()
        fake_proc.pid = 123
        with (
            mock.patch.object(launch, "build_launch_command", return_value=(["/emu", "/roms/x.nes"], None)),
            mock.patch.object(launch.subprocess, "Popen", return_value=fake_proc) as popen,
        ):
            proc, err = launch.start_launch_process(rom, cfg, controller_mapping=mapping)
        self.assertIsNone(err)
        self.assertIs(proc, fake_proc)
        _, kwargs = popen.call_args
        return kwargs.get("env")

    def test_env_injected_with_mapping(self):
        env = self._run("GUID,Pad,a:b0,")
        self.assertIsNotNone(env)
        self.assertEqual(env["SDL_GAMECONTROLLERCONFIG"], "GUID,Pad,a:b0,")

    def test_env_none_without_mapping(self):
        self.assertIsNone(self._run(None))


@unittest.skipUnless(QT_AVAILABLE, "PySide6 is not installed")
class RouterMappingPassthroughTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_returns_backend_mapping_when_exposed(self):
        class MappingBackend(NullBackend):
            def controller_mapping(self):
                return "GUID,Pad,a:b0,"

        router = ControllerRouter(MappingBackend(), InputStateMachine())
        self.assertEqual(router.controller_mapping(), "GUID,Pad,a:b0,")

    def test_returns_none_when_backend_has_no_mapping(self):
        # NullBackend does not expose controller_mapping.
        router = ControllerRouter(NullBackend(), InputStateMachine())
        self.assertIsNone(router.controller_mapping())


if __name__ == "__main__":
    unittest.main()
