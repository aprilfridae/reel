"""Self-update from the newest GitHub release (packaged .exe only).

A background thread looks at the repo's latest release every half hour. If its tag is newer
than version.VERSION, it downloads UndergroundBot.exe next to the running one (checking the
size and the SHA-256 GitHub publishes for the file) and sets READY. The bot then stops at its
next safe point (between jobs, never in the middle of a bid or a pack session) and main.py
calls install_and_restart(): the running .exe is renamed to .old (Windows allows that, not an
overwrite), the new one takes its name, and it is started once this process has exited.
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

from paths import APP, FROZEN
from version import VERSION

REPO = "aprilfridae/underground-rng-bot-memory"
ASSET = "UndergroundBot.exe"
CHECK_EVERY = 1800  # seconds
EXE = sys.executable
OLD = EXE + ".old"
STAGED = os.path.join(APP, "UndergroundBot.update")
STATE = os.path.join(APP, "update_state.json")

READY = threading.Event()
_new_tag = {"tag": None}


def _log(msg):
    print(f"[update] {msg}", flush=True)


def _version(tag):
    try:
        return tuple(int(p) for p in tag.lstrip("vV").split("."))
    except ValueError:
        return None


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "UndergroundBot-updater", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def _tried():
    try:
        return json.load(open(STATE)).get("tried")
    except (OSError, ValueError):
        return None


def _remember(tag):
    try:
        json.dump({"tried": tag}, open(STATE, "w"))
    except OSError:
        pass


def newer_release():
    """(tag, download url, size, sha256) of the latest release if it is newer than this build, else None."""
    with _get(f"https://api.github.com/repos/{REPO}/releases/latest") as r:
        rel = json.load(r)
    tag = rel.get("tag_name", "")
    if rel.get("draft") or rel.get("prerelease") or not _version(tag) or _version(tag) <= _version(VERSION):
        return None
    if tag == _tried():
        return None  # already installed once and still older: a release built without bumping version.py; don't loop
    for a in rel.get("assets", []):
        digest = str(a.get("digest") or "")
        if a.get("name") == ASSET and digest.startswith("sha256:"):
            return tag, a["browser_download_url"], int(a["size"]), digest.split(":", 1)[1].lower()
    return None


def stage(url, size, sha):
    """Download to STAGED and check it. True if it is the file GitHub says it is."""
    h = hashlib.sha256()
    n = 0
    with _get(url, timeout=60) as r, open(STAGED, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            n += len(chunk)
    with open(STAGED, "rb") as f:
        mz = f.read(2) == b"MZ"
    if n == size and h.hexdigest() == sha and mz:
        return True
    os.remove(STAGED)
    return False


def check_once():
    found = newer_release()
    if not found:
        return False
    tag, url, size, sha = found
    _log(f"{tag} is out (this is {VERSION}); downloading")
    if not stage(url, size, sha):
        _log("the download didn't match GitHub's checksum; not installing")
        return False
    _new_tag["tag"] = tag
    READY.set()
    _log(f"{tag} downloaded; restarting into it when the bot is between jobs")
    return True


def _loop():
    time.sleep(20)
    while not READY.is_set():
        try:
            if check_once():
                return
        except Exception as e:  # offline, rate limited...: try again later
            _log(f"couldn't check ({type(e).__name__})")
        time.sleep(CHECK_EVERY)


def start():
    """Clean up after the last update and begin watching (packaged .exe only)."""
    if not FROZEN:
        return
    try:
        os.remove(OLD)
    except OSError:
        pass
    threading.Thread(target=_loop, daemon=True).start()


def pending():
    return READY.is_set()


def install_and_restart():
    """Swap the new .exe in and start it; the new one waits for this process to exit first."""
    os.replace(EXE, OLD)
    try:
        os.replace(STAGED, EXE)
    except OSError:
        os.replace(OLD, EXE)  # couldn't: put the working one back
        raise
    _remember(_new_tag["tag"])
    env = dict(os.environ, UB_WAIT_PID=str(os.getpid()), PYINSTALLER_RESET_ENVIRONMENT="1")
    flags = 0x00000200 | 0x01000000  # new process group, breakaway from the launcher's job
    kw = dict(env=env, stdin=subprocess.DEVNULL, stdout=sys.__stdout__, stderr=sys.__stderr__)
    try:
        subprocess.Popen([EXE], creationflags=flags, **kw)
    except OSError:  # breakaway not allowed
        subprocess.Popen([EXE], creationflags=0x00000200, **kw)
    _log(f"{_new_tag['tag']} started")


def wait_for_previous():
    """At start-up after an update: wait for the old process to exit (it holds the website's port)."""
    pid = os.environ.pop("UB_WAIT_PID", None)
    if not pid:
        return
    import ctypes
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
    if handle:
        k32.WaitForSingleObject(handle, 60000)
        k32.CloseHandle(handle)
    time.sleep(1)
