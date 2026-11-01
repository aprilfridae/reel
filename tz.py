"""The clock the schedule runs on: the nightly pack session window (1:00-6:00) and the nightly rebirth's once-a-day
marker. By default it is the PC's own timezone; the website's "schedule timezone" setting (tz.json) can name another
one (an IANA name such as America/Chicago), so a PC whose clock is in a different zone from its owner's still runs the
schedule at the owner's times, and the same schedule is the same real moment for everyone.
"""
import time
from datetime import datetime

import webstate

_cache = {"at": 0.0, "zone": None, "obj": None}


def _override():
    """The zone named on the website, as a ZoneInfo, or None for the PC's own."""
    if time.time() - _cache["at"] > 2.0:
        _cache["at"] = time.time()
        name = (webstate.load("tz.json", {}) or {}).get("zone")
        if name != _cache["zone"]:
            _cache["zone"], _cache["obj"] = name, None
            if name and name != "auto":
                try:
                    from zoneinfo import ZoneInfo
                    _cache["obj"] = ZoneInfo(name)
                except Exception:  # unknown name, or no tz database: fall back to the PC's clock
                    _cache["obj"] = None
    return _cache["obj"]


def now():
    """The current time in the schedule's zone (timezone-aware)."""
    z = _override()
    return datetime.now(z) if z else datetime.now().astimezone()


def info():
    """For the website: the zone in use, its offset and abbreviation, and the PC's own."""
    n = now()
    own = datetime.now().astimezone()
    off = n.utcoffset()
    return {"zone": _cache["zone"] or "auto", "abbr": n.tzname(), "offset": int(off.total_seconds() / 60) if off else 0,
            "pc_abbr": own.tzname(), "pc_offset": int(own.utcoffset().total_seconds() / 60), "ts": time.time(),
            "clock": n.strftime("%H:%M")}
