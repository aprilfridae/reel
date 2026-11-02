"""Memory-based additions to game.py — drop-in replacements for template
matching. Add these methods to your Game class or use them standalone.

Provides:
    find_button_mem(text_contains)  → button instance (memory)
    button_pos_mem(instance)        → (x, y) screen coords
    click_button_mem(text_contains) → click a button by its visible text
    read_label_mem(instance)        → read a label's visible text
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

def find_button_mem(game, text_contains, under=None):
    """Find a TextButton whose visible text contains text_contains, using
    memory reading instead of template matching. Returns the instance or None."""
    return _backend().find_button(text_contains, under)

def button_pos_mem(game, inst):
    """Screen coords (x, y) of a GUI element's AbsolutePosition."""
    return _backend().button_pos(inst)

def click_button_mem(game, text_contains, under=None):
    """Find a TextButton by text and click it. Returns True on success."""
    inst = find_button_mem(game, text_contains, under)
    if not inst:
        return False
    pos = button_pos_mem(game, inst)
    if not pos:
        return False
    game.click(pos[0], pos[1])
    return True

def read_label_mem(game, inst):
    """Read visible text from a TextLabel/TextButton/TextBox instance."""
    return _backend().read_text(inst)

def close():
    global _mb
    if _mb:
        _mb.close()
        _mb = None
