"""Locates the Victoria II installation and the user's save games.

Detection order (first hit wins):

1. Windows registry (Steam uninstall entry for Victoria II)
2. Default Steam library locations on any platform
3. GOG/other common install paths
4. Previously chosen path stored in the app config

Save games live under ``<Documents>/Paradox Interactive/Victoria II/save games``
(or ``Victoria II - A House Divided`` / Heart of Darkness variants), plus any
``save games`` folder inside the install directory.
"""

from __future__ import annotations

import os
import sys
import glob
from typing import List, Optional

__all__ = ["find_install", "find_save_dirs", "list_saves", "config_path", "load_config", "save_config", "paradox_victoria2_dir"]

APP_NAME = "vic2-mistral-analyzer"

_MARKERS = ("v2game.exe", "v2game", "v2game_aoh", "Victoria 2.exe")
_DIR_MARKERS = ("common", "gfx", "map", "interface")
_SAVE_MARKERS = ("common", "gfx")


def _looks_like_install(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    if any(os.path.isfile(os.path.join(path, m)) for m in _MARKERS):
        return True
    return all(os.path.isdir(os.path.join(path, m)) for m in _DIR_MARKERS)


def _registry_candidates() -> List[str]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []
    results: List[str] = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for subkey in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ):
            try:
                root = winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ)
            except OSError:
                continue
            index = 0
            while True:
                try:
                    key_name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(root, key_name) as key:
                        display, _ = winreg.QueryValueEx(key, "DisplayName")
                        if "victoria" not in str(display).lower():
                            continue
                        location, _ = winreg.QueryValueEx(key, "InstallLocation")
                        if location:
                            results.append(str(location))
                except OSError:
                    continue
            root.Close()
    return results


def _steam_candidates() -> List[str]:
    candidates: List[str] = []
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        for drive in ("C:", "D:", "E:"):
            candidates += [
                os.path.join(drive, os.sep, "Program Files (x86)", "Steam", "steamapps", "common"),
                os.path.join(drive, os.sep, "Program Files", "Steam", "steamapps", "common"),
            ]
        # Steam libraries declared in libraryfolders.vdf
        vdf = os.path.join("C:\\", "Program Files (x86)", "Steam", "steamapps", "libraryfolders.vdf")
        candidates += _parse_libraryfolders(vdf)
    elif sys.platform == "darwin":
        candidates += [
            os.path.join(home, "Library", "Application Support", "Steam", "steamapps", "common"),
        ]
    else:
        candidates += [
            os.path.join(home, ".steam", "steam", "steamapps", "common"),
            os.path.join(home, ".local", "share", "Steam", "steamapps", "common"),
            "/usr/share/steam/steamapps/common",
        ]
    out: List[str] = []
    for library in candidates:
        for name in ("Victoria II", "Victoria 2", "Victoria 2 AHD", "victoria 2"):
            out.append(os.path.join(library, name))
    return out


def _parse_libraryfolders(vdf_path: str) -> List[str]:
    paths: List[str] = []
    try:
        with open(vdf_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith('"path"'):
                    value = line.split('"', 2)
                    if len(value) >= 3:
                        raw = value[2].rstrip('"').replace("\\\\", "\\")
                        paths.append(os.path.join(raw, "steamapps", "common"))
    except OSError:
        pass
    return paths


def _gog_candidates() -> List[str]:
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "GOG Galaxy", "Games"),
        "C:\\GOG Games",
        "C:\\Program Files (x86)\\GOG Galaxy\\Games",
        "C:\\Program Files\\GOG Galaxy\\Games",
    ]
    return [os.path.join(c, "Victoria II") for c in candidates]


def find_install(configured: Optional[str] = None) -> Optional[str]:
    """Return the path of the Victoria II install directory, or None."""
    checked = []
    if configured:
        if _looks_like_install(configured):
            return configured
        checked.append(configured)
    for candidate in _registry_candidates() + _steam_candidates() + _gog_candidates():
        if candidate and _looks_like_install(candidate):
            return candidate
        if candidate:
            # some setups point at the library root; try one level down
            parent = candidate
            for _ in range(2):
                if _looks_like_install(parent):
                    return parent
                parent = os.path.dirname(parent)
        checked.append(candidate)
    return None


# --------------------------------------------------------------- save games


def _doc_dir() -> str:
    """The user's Documents folder, robust across Windows/local setups."""
    if sys.platform == "win32":
        import ctypes.wintypes
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        try:
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
            if buf.value:
                return buf.value
        except Exception:
            pass
        # OneDrive-redirected or custom Documents locations
        for env in ("USERPROFILE", "HOME"):
            base = os.environ.get(env)
            if base:
                return os.path.join(base, "Documents")
    home = os.path.expanduser("~")
    for candidate in (
        os.path.join(home, "Documents"),
        os.path.join(home, "documents"),
    ):
        if os.path.isdir(candidate):
            return candidate
    return home


def paradox_victoria2_dir() -> str:
    """The Documents/Paradox Interactive/Victoria II folder, if it exists."""
    paradox = os.path.join(_doc_dir(), "Paradox Interactive")
    for name in ("Victoria II", "Victoria 2", "Victoria II - A House Divided",
                 "Victoria II - A House Divided - Heart of Darkness"):
        path = os.path.join(paradox, name)
        if os.path.isdir(path):
            return path
    return paradox

def find_save_dirs(install_dir: Optional[str] = None) -> List[str]:
    """All plausible 'save games' directories for Victoria II."""
    dirs: List[str] = []
    doc = _doc_dir()
    paradox = os.path.join(doc, "Paradox Interactive")
    candidates = [
        os.path.join(paradox, "Victoria II", "save games"),
        os.path.join(paradox, "Victoria II - A House Divided", "save games"),
        os.path.join(paradox, "Victoria II - A House Divided - Heart of Darkness", "save games"),
        os.path.join(paradox, "Victoria 2", "save games"),
    ]
    if install_dir:
        candidates.append(os.path.join(install_dir, "save games"))
        candidates.append(os.path.join(install_dir, "saves"))
    for path in candidates:
        if os.path.isdir(path):
            dirs.append(path)
    # glob for any modded/renamed variants
    pattern = os.path.join(paradox, "*", "save games")
    for path in glob.glob(pattern):
        if path not in dirs:
            dirs.append(path)
    return dirs


def list_saves(save_dirs: List[str]) -> List[dict]:
    """List .v2/.v2e files with metadata, newest first."""
    saves = []
    for directory in save_dirs:
        if not os.path.isdir(directory):
            continue
        for name in os.listdir(directory):
            if not name.lower().endswith((".v2", ".v2e")):
                continue
            full = os.path.join(directory, name)
            if not os.path.isfile(full):
                continue
            st = os.stat(full)
            saves.append({
                "path": full,
                "name": name,
                "size": st.st_size,
                "mtime": st.st_mtime,
                "binary": name.lower().endswith(".v2e"),
            })
    saves.sort(key=lambda s: s["mtime"], reverse=True)
    return saves


# ------------------------------------------------------------------- config


def config_path() -> str:
    if sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA", _doc_dir()), APP_NAME)
    else:
        base = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "config.json")


def load_config() -> dict:
    import json
    path = config_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {}


def save_config(data: dict) -> None:
    import json
    path = config_path()
    current = load_config()
    current.update(data)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(current, fh, indent=2)
