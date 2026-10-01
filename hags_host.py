"""Host probing and the single registry write for the HAGS Selector.

Split out from hags_policy.py on purpose. That file is the rule and stays pure so
it can be tested without a GPU; this file is the part that touches the machine -
reading the adapter, reading and writing HwSchMode, and finding which game is in
front of the user.

Nothing in here decides anything. It reports what it saw and writes what it is
told to write.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import time
import winreg
from ctypes import wintypes
from pathlib import Path

# HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers -> HwSchMode
KEY_GRAPHICS_DRV = r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers"
VALUE_HAGS = "HwSchMode"
HAGS_OFF = 1
HAGS_ON = 2

# the display adapters class GUID
_DISPLAY_CLASS = (r"SYSTEM\CurrentControlSet\Control\Class"
                  r"\{4d36e968-e325-11ce-bfc1-08002be10318}")

_STATE_FILE = "hags_state.json"

# GetWindowLong-free foreground probe: QueryFullProcessImageNameW is the one API
# that works for a process we did not open with full access.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


# --------------------------------------------------------------------- paths

def app_dir() -> Path:
    """The real folder the app lives in, not the onefile extraction dir.

    A frozen build sets __file__ inside %TEMP%\\onefile_<pid>_<ts>_<rand> which is
    deleted on exit, so a state file written next to __file__ vanishes. sys.argv[0]
    is the exe itself.
    """
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return Path(sys.argv[0]).resolve().parent
    return Path(__file__).resolve().parent


def state_path() -> Path:
    return app_dir() / _STATE_FILE


# ---------------------------------------------------------------- read: GPU

def gpu_name_from_registry() -> str:
    """The adapter's marketing name, from DriverDesc.

    Picks the entry with the largest reported memory so an integrated adapter
    does not win over the discrete card.
    """
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS)
    except OSError:
        return ""
    best_name, best_mem = "", -1
    try:
        for i in range(64):
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            if not re.fullmatch(r"\d{4}", sub):
                continue
            try:
                k = winreg.OpenKey(root, sub)
            except OSError:
                continue
            try:
                name = ""
                try:
                    name, _ = winreg.QueryValueEx(k, "DriverDesc")
                except OSError:
                    pass
                mem = 0
                try:
                    qw, _ = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")
                    mem = int(qw)
                except OSError:
                    pass
                if name and mem > best_mem:
                    best_name, best_mem = str(name), mem
            finally:
                winreg.CloseKey(k)
    finally:
        winreg.CloseKey(root)
    return best_name


# ------------------------------------------------------- read/write: HwSchMode

def read_hags() -> int | None:
    """The current HwSchMode, or None if the value does not exist."""
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY_GRAPHICS_DRV)
    except OSError:
        return None
    try:
        v, _ = winreg.QueryValueEx(k, VALUE_HAGS)
        return int(v)
    except OSError:
        return None
    finally:
        winreg.CloseKey(k)


def hags_state_word(mode: int | None) -> str:
    if mode is None:
        return "not set (Windows default: off)"
    return "ON (mode 2)" if mode == HAGS_ON else f"OFF (mode {mode})"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _set_dword(root, sub_path: str, name: str, value: int) -> None:
    """Write a DWORD, creating the key if the path is missing. Raises on failure."""
    k = winreg.CreateKeyEx(root, sub_path, 0, winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(value))
    finally:
        winreg.CloseKey(k)


def apply_hags(mode: int) -> tuple[bool, str]:
    """Write HwSchMode and read it back. (ok, message).

    The read-back is the point: SetValueEx returns None whether or not the write
    landed, so the only honest way to report success is to re-read the value.
    """
    before = read_hags()
    try:
        _set_dword(winreg.HKEY_LOCAL_MACHINE, KEY_GRAPHICS_DRV, VALUE_HAGS, mode)
    except PermissionError:
        return False, ("blocked by Windows - HwSchMode is machine-wide and needs "
                       "administrator rights. Relaunch as administrator.")
    except OSError as e:
        return False, f"registry write failed: {e}"

    after = read_hags()
    if after != int(mode):
        return False, (f"write did not stick: asked for {mode}, registry reads "
                       f"{after if after is not None else 'nothing'}")

    remember(before, mode)
    return True, (f"HwSchMode written and verified as {after} "
                  f"(was {before if before is not None else 'unset'}). "
                  "Takes effect on the next boot.")


# ----------------------------------------------------------------- state file

def remember(previous: int | None, written: int) -> None:
    """Record what was there before us, so RESTORE has something to restore to."""
    data = {
        "previous_mode": previous,
        "written_mode": written,
        "written_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        state_path().write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass          # a missing state file costs the user nothing but the undo


def recall() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def restore_previous() -> tuple[bool, str]:
    """Put back the value that was there before this tool first ran."""
    st = recall()
    if "previous_mode" not in st:
        return False, ("nothing to restore - this tool has not written HwSchMode "
                       "on this machine yet")
    prev = st["previous_mode"]
    if prev is None:
        return False, ("the value did not exist before this tool ran, so there is "
                       "no earlier value to put back. Leaving HwSchMode off (mode 1) "
                       "is the Windows default - use FORCE OFF if that is what you want.")
    ok, msg = apply_hags(int(prev))
    if ok:
        # restoring is not a new change, so do not overwrite the remembered original
        try:
            state_path().unlink()
        except OSError:
            pass
        return True, f"restored HwSchMode to {prev}: {msg}"
    return False, msg


# ---------------------------------------------------------- .reg export

def export_restore_reg(mode: int, why: str) -> Path:
    """A double-clickable restore file, so the user never needs this app to undo."""
    stamp = time.strftime("%Y-%m-%d %H:%M")
    body = [
        "Windows Registry Editor Version 5.00",
        "",
        "; Written by Vortex HAGS Selector on " + stamp,
        "; " + why.replace("\r", " ").replace("\n", " "),
        "; Double-click this file and approve the prompt to set HwSchMode back.",
        "",
        "[HKEY_LOCAL_MACHINE\\" + KEY_GRAPHICS_DRV + "]",
        '"' + VALUE_HAGS + f'"=dword:{int(mode):08x}',
        "",
    ]
    out = app_dir() / "HAGS_Restore.reg"
    out.write_text("\r\n".join(body), encoding="utf-16")
    return out


# ------------------------------------------------- foreground game detection

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD

_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def foreground_exe() -> tuple[str, int] | tuple[None, None]:
    """(lowercase exe file name, pid) of the window in front, or (None, None)."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None, None
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None, None

    h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return None, None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None, None
        return os.path.basename(buf.value).lower(), pid.value
    finally:
        _kernel32.CloseHandle(h)
