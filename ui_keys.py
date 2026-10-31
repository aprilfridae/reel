"""Keyboard helpers for typing into Roblox text boxes."""
import time

from game import INPUT, KEYBDINPUT, _send

SC_CTRL, SC_A, SC_BACKSPACE, SC_DELETE = 0x1D, 0x1E, 0x0E, 0x53


def _sc(sc, up, extended=False):
    inp = INPUT(type=1)
    inp.ki = KEYBDINPUT(0, sc, 0x0008 | (0x0001 if extended else 0) | (0x0002 if up else 0), 0, 0)
    _send(inp)
    time.sleep(0.02)


def clear_field():
    """Empty the focused text box: Ctrl+A then Backspace, plus plenty of
    Backspace/Delete in case select-all isn't supported."""
    _sc(SC_CTRL, False)
    _sc(SC_A, False)
    _sc(SC_A, True)
    _sc(SC_CTRL, True)
    _sc(SC_BACKSPACE, False)
    _sc(SC_BACKSPACE, True)
    for _ in range(20):
        _sc(SC_BACKSPACE, False)
        _sc(SC_BACKSPACE, True)
        _sc(SC_DELETE, False, extended=True)
        _sc(SC_DELETE, True, extended=True)


def type_text(text):
    for ch in text:
        for up in (0, 0x0002):
            inp = INPUT(type=1)
            inp.ki = KEYBDINPUT(0, ord(ch), 0x0004 | up, 0, 0)  # KEYEVENTF_UNICODE
            _send(inp)
        time.sleep(0.03)


SC_ENTER = 0x1C


def press_enter():
    _sc(SC_ENTER, False)
    _sc(SC_ENTER, True)
