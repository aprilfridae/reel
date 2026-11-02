"""The catch popup ("You caught a Sardine!" / "You caught an Atlantis Pack!"), read from memory.

It's a frame in PlayerGui.FishingUI holding the title label, the prize lines under it, and two buttons along its top:
the fish log (the wider one, left) and the X (the narrow one, right). The frame stays in memory with the last catch's
text after it closes, so only a showing popup counts.
"""
import time

import mem_gui

_TITLE = "you caught"


def _parts(mb):
    """(popup frame, title label, close button) or None."""
    fg = mb._find_screen_gui("FishingUI")
    for top in mb._children(fg) if fg else []:
        for fr in mb._children(top):
            if mb._class_name(fr) != "Frame":
                continue
            kids = mb._children(fr)
            title = next((k for k in kids if mb._class_name(k) == "TextLabel"
                          and (mb._content_text(k) or "").lower().startswith(_TITLE)), None)
            if title is None:
                continue
            gui = mem_gui.gui()
            buttons = [(gui.geom(k), k) for k in kids if mb._class_name(k) == "TextButton"]
            buttons = [(g, k) for g, k in buttons if g]
            close = max(buttons, key=lambda b: b[0][0])[1] if buttons else None
            return fr, title, close
    return None


def showing(mb=None):
    """The showing popup's title ("You caught a Sardine!"), else None."""
    gui = mem_gui.gui()
    if gui is None:
        return None
    mb = mb or gui.mb
    p = _parts(mb)
    if not p or not gui.is_shown(p[0]):
        return None
    return (mb._content_text(p[1]) or "").strip() or None


def close_button(mb=None):
    """Centre of the showing popup's X, or None."""
    gui = mem_gui.gui()
    if gui is None:
        return None
    p = _parts(mb or gui.mb)
    if not p or not p[2] or not gui.is_shown(p[0]):
        return None
    g = gui.geom(p[2])
    return (g[0], g[1]) if g else None


def read_catch_popup_mem(game, mb, timeout=2.5):
    """Wait for the catch popup after a reel. Returns (got_atlantis, title): title None if no popup came (the fish
    got away)."""
    end = time.time() + timeout
    while time.time() < end:
        title = showing(mb)
        if title:
            return "atlantis" in title.lower(), title
        time.sleep(0.03)
    return False, None
