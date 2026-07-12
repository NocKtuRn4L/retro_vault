"""Launch command construction, validation, and process launching."""

import copy
import logging
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Cache of flatpak `flatpak info <id>` results, keyed by flatpak_id, so
# validation doesn't re-shell out on every launch/audit pass.
_flatpak_info_cache = {}


def _reset_flatpak_cache():
    _flatpak_info_cache.clear()


def _strip_wrapping_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _split_args_template(args_template, rom_path, platform=None):
    platform = platform or sys.platform
    args_template = (args_template or "{rom}").strip()

    if not args_template or "{rom}" not in args_template:
        return [rom_path]

    if platform == "win32":
        placeholder = "__RETROVAULT_ROM_PATH__"
        args_str = args_template.replace("{rom}", placeholder)
        try:
            parts = shlex.split(args_str, posix=False)
        except ValueError:
            return [rom_path]
        return [
            rom_path if _strip_wrapping_quotes(part) == placeholder else _strip_wrapping_quotes(part)
            for part in parts
        ]

    rom_quoted = shlex.quote(rom_path)
    args_str = args_template.replace("{rom}", rom_quoted)
    try:
        return shlex.split(args_str, posix=True)
    except ValueError:
        return [rom_path]


def _resolve_core_arg(arg, config, system_key):
    if arg != "{core}":
        return arg
    return config.get("retroarch_cores", {}).get(system_key, "")


def get_emulator_config(system_key, config):
    emu = copy.deepcopy(config.get("emulators", {}).get(system_key, {}))
    profile_key = emu.get("profile", "custom")
    profile = config.get("emulator_profiles", {}).get(profile_key, {})
    if not emu.get("args") and profile.get("args"):
        emu["args"] = profile["args"]
    emu.setdefault("args", "{rom}")
    emu.setdefault("profile", profile_key)
    return emu


def _is_flatpak_installed(flatpak_id):
    if flatpak_id in _flatpak_info_cache:
        return _flatpak_info_cache[flatpak_id]
    try:
        result = subprocess.run(["flatpak", "info", flatpak_id], capture_output=True)
        installed = result.returncode == 0
    except OSError:
        installed = False
    _flatpak_info_cache[flatpak_id] = installed
    return installed


def _validate_flatpak_emulator(emu, system_key):
    flatpak_id = emu.get("flatpak_id", "").strip()
    if not flatpak_id:
        return f"No emulator configured for {system_key.upper()}.\nGo to Settings -> Emulators to set one up."
    if shutil.which("flatpak") is None:
        return "flatpak is not installed"
    if not _is_flatpak_installed(flatpak_id):
        return f"Flatpak app not installed: {flatpak_id}"
    return None


def validate_launch(rom, config):
    system_key = rom.get("system", "")
    rom_path = rom.get("path", "")
    if not rom_path or not Path(rom_path).is_file():
        return f"ROM file not found:\n{rom_path}"

    if config.get("use_retroarch"):
        retroarch_path = _strip_wrapping_quotes(config.get("retroarch_path", ""))
        if not retroarch_path:
            return "RetroArch is enabled, but no RetroArch binary is configured."
        if not Path(retroarch_path).is_file():
            return f"RetroArch executable not found:\n{retroarch_path}"
        core = config.get("retroarch_cores", {}).get(system_key, "")
        if not core:
            return "No RetroArch core configured for this system."
        return None

    emu = get_emulator_config(system_key, config)
    launch_type = emu.get("launch_type", "exe")

    if launch_type == "flatpak":
        return _validate_flatpak_emulator(emu, system_key)

    emu_path = _strip_wrapping_quotes(emu.get("path", ""))
    if not emu_path:
        return f"No emulator configured for {system_key.upper()}.\nGo to Settings -> Emulators to set one up."

    if launch_type == "binary":
        if shutil.which(emu_path) is None:
            return f"Emulator command not found on PATH: {emu_path}"
        return None

    if not Path(emu_path).is_file():
        return f"Emulator executable not found:\n{emu_path}\n\nCheck the path in Settings -> Emulators."
    return None


def build_launch_command(rom, config, platform=None, validate=True):
    platform = platform or sys.platform
    system_key = rom["system"]
    rom_path = rom["path"]

    if validate:
        error = validate_launch(rom, config)
        if error:
            return None, error

    if config.get("use_retroarch") and config.get("retroarch_path"):
        ra = _strip_wrapping_quotes(config["retroarch_path"])
        core = config["retroarch_cores"].get(system_key, "")
        if not core:
            return None, "No RetroArch core configured for this system."
        return [ra, "-L", core, rom_path], None

    emu = get_emulator_config(system_key, config)
    launch_type = emu.get("launch_type", "exe")

    if launch_type == "flatpak":
        flatpak_id = emu.get("flatpak_id", "").strip()
        if not flatpak_id:
            return None, f"No emulator configured for {system_key.upper()}.\nGo to Settings -> Emulators to set one up."
        extra_args = _split_args_template(emu.get("args", "{rom}"), rom_path, platform=platform)
        extra_args = [_resolve_core_arg(arg, config, system_key) for arg in extra_args]
        return ["flatpak", "run", flatpak_id] + extra_args, None

    emu_path = _strip_wrapping_quotes(emu.get("path", ""))
    if not emu_path:
        return None, f"No emulator configured for {system_key.upper()}.\nGo to Settings -> Emulators to set one up."

    if launch_type == "binary":
        resolved = shutil.which(emu_path)
        if resolved is None:
            return None, f"Emulator command not found on PATH: {emu_path}"
        emu_path = resolved

    extra_args = _split_args_template(emu.get("args", "{rom}"), rom_path, platform=platform)
    extra_args = [_resolve_core_arg(arg, config, system_key) for arg in extra_args]
    return [emu_path] + extra_args, None


def _windows_launch_details(cmd):
    exe_path = Path(cmd[0])
    working_dir = str(exe_path.parent) if exe_path.parent != Path(".") else None
    return subprocess.list2cmdline(cmd[1:]), working_dir


def _command_working_dir(cmd):
    exe_path = Path(cmd[0])
    if exe_path.parent == Path("."):
        return None
    return str(exe_path.parent)


def _windows_shell_execute(cmd, verb="open"):
    import ctypes

    params, working_dir = _windows_launch_details(cmd)
    return ctypes.windll.shell32.ShellExecuteW(
        None,       # hwnd
        verb,       # "open" respects the EXE manifest; "runas" forces elevation.
        cmd[0],     # exe path
        params,     # arguments
        working_dir,
        1,          # SW_SHOWNORMAL
    )


def launch_rom(rom, config):
    cmd, error = build_launch_command(rom, config)
    if error:
        logging.warning("Launch validation failed for %s: %s", rom.get("path"), error)
        return False, error

    try:
        logging.info("Launching ROM '%s' with command: %s", rom.get("name"), subprocess.list2cmdline(cmd))
        if sys.platform == "win32":
            try:
                proc = subprocess.Popen(cmd, cwd=_command_working_dir(cmd))
                logging.info("Launch started with pid %s", proc.pid)
                return True, f"Launched! PID {proc.pid}"
            except PermissionError:
                logging.info("Popen permission denied; retrying with ShellExecute runas")
                ret = _windows_shell_execute(cmd, verb="runas")
            except OSError as e:
                logging.info("Popen failed with %s; retrying with ShellExecute open", e)
                ret = _windows_shell_execute(cmd, verb="open")
            # ShellExecuteW returns > 32 on success
            if ret <= 32:
                logging.error("ShellExecute failed with code %s for %s", ret, cmd[0])
                return False, (
                    f"ShellExecute failed (code {ret}) launching:\n{cmd[0]}\n\n"
                    "Make sure the path is correct in Settings → Emulators."
                )
            logging.info("Launch handed to ShellExecute with code %s", ret)
        else:
            proc = subprocess.Popen(cmd, cwd=_command_working_dir(cmd), close_fds=True)
            logging.info("Launch started with pid %s", proc.pid)
        return True, "Launched!"
    except FileNotFoundError:
        logging.exception("Emulator executable not found")
        return False, (
            f"Emulator executable not found:\n{cmd[0]}\n\n"
            "Check the path in Settings → Emulators."
        )
    except PermissionError:
        logging.exception("Permission denied launching emulator")
        return False, (
            f"Permission denied launching:\n{cmd[0]}\n\n"
            "Windows blocked the launch even with elevation.\n"
            "Try running RetroVault itself as administrator."
        )
    except Exception as e:
        logging.exception("Unexpected launch error")
        return False, f"{type(e).__name__}: {e}"
