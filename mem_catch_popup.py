"""Memory-reading replacement for packs.read_catch_popup.

After a catch, walks PlayerGui looking for the catch popup and checks
whether its text mentions Atlantis. Read-only memory access — no OCR,
no template matching.
"""
import time


def read_catch_popup_mem(game, mb, timeout=2.5):
    """Wait for the catch popup after a fish is caught. Returns
    (got_atlantis, None). The image return is None since we don't
    capture frames anymore (callers that used fisher.last_popup for the
    Atlantis popup screenshot just won't get one)."""
    end = time.time() + timeout
    while time.time() < end:
        # Walk all of PlayerGui looking for any label mentioning Atlantis
        for d, i in mb._walk(mb.player_gui, depth=16):
            cls = mb._class_name(i)
            if cls in ("TextLabel", "TextButton"):
                txt = mb.read_text(i)
                if txt and "atlantis" in txt.lower():
                    return True, None
        time.sleep(0.02)
    return False, None
