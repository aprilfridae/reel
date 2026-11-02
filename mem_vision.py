"""vision.py replacement — fishing state from memory instead of CV.

Provides a `detect()` function with the same return shape as the old
vision.detect(), but the busy/zone/fish values come from Roblox memory
reads (FishingUI text labels) rather than pixel analysis.

Return dict:
    busy  - True if the fishing panel is on screen
    zone  - (left, right) x of the green reel zone, or None (memory can't
            read the bar position; set to None)
    fish  - x of the fish, or None (same limitation)
    scale - always 1.0
    state - 'waiting' | 'biting' | 'caught' | None  (new field from memory)

Use `state` instead of `zone`/`fish` for reel control: when state is
'biting', hold E; when 'caught', release E.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory_backend import MemoryBackend

_mb = None

def _backend():
    global _mb
    if _mb is None:
        _mb = MemoryBackend()
        _mb.start()
    return _mb

def detect(img=None, scale=1.0, rows=None, reeling=False, half=None):
    """Memory-based replacement for vision.detect().
    img/scale/rows/reeling/half are accepted for interface compatibility
    but ignored — state comes from memory, not pixels."""
    b = _backend()
    state = b.fish_state()
    busy = state is not None
    return {
        "busy": busy,
        "zone": None,        # memory can't read the bar position
        "fish": None,        # memory can't read the bar position
        "scale": 1.0,
        "state": state,      # 'waiting' | 'biting' | 'caught' | None
    }

def get_balance():
    return _backend().get_balance()

def close():
    global _mb
    if _mb:
        _mb.close()
        _mb = None
