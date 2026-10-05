"""Finding ffmpeg (the video encoder) even when this process's PATH is stale.

A program started before ffmpeg was installed (or from a launcher that didn't pick up a PATH change) has an old PATH,
so a bare `ffmpeg` isn't found although it's installed. Look, in order: $AFL_FFMPEG; this process's PATH; the PATH
saved in the Windows registry (user, then machine), read fresh; the usual install folders. The project's own copy
(the imageio-ffmpeg package, installed with the app's dependencies) comes straight after this process's PATH, so videos
work however the app was launched, with no system install at all.
"""
from __future__ import annotations

import glob
import os
import shutil


def _registry_paths() -> list[str]:
    if os.name != "nt":
        return []
    import winreg
    out = []
    for hive, key in ((winreg.HKEY_CURRENT_USER, r"Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(hive, key) as k:
                out += [os.path.expandvars(p) for p in str(winreg.QueryValueEx(k, "Path")[0]).split(";") if p]
        except OSError:
            pass
    return out


def find_ffmpeg() -> str | None:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    env = os.environ.get("AFL_FFMPEG")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:                                                                    # the project's own copy: always there once installed
        import imageio_ffmpeg
        own = imageio_ffmpeg.get_ffmpeg_exe()
        if own and os.path.isfile(own):
            return own
    except Exception:                                                      # noqa: BLE001
        pass
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [os.path.join(d, exe) for d in _registry_paths()]
    candidates += [os.path.join(local, "ffmpeg", "bin", exe), r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                   r"C:\ProgramData\chocolatey\bin\ffmpeg.exe", os.path.join(os.path.expanduser("~"), "scoop", "shims", exe),
                   os.path.join(local, "Microsoft", "WinGet", "Links", exe), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]
    candidates += glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "*ffmpeg*", "**", exe), recursive=True)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def use_ffmpeg() -> str:
    """Point matplotlib's video writer at ffmpeg; a clear error if there isn't one."""
    path = find_ffmpeg()
    if path is None:
        raise RuntimeError("ffmpeg isn't installed (or can't be found), so videos can't be made. Install the project's copy with `.venv\\Scripts\\python -m pip install imageio-ffmpeg`, "
                           "or set AFL_FFMPEG to the full path of ffmpeg.exe. The match itself was played and saved.")
    import matplotlib
    matplotlib.rcParams["animation.ffmpeg_path"] = path
    return path
