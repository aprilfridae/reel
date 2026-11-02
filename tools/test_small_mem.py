"""Read-only check of the small memory readers (nothing is clicked). Usage: python tools/test_small_mem.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance  # noqa: E402
import gifts  # noqa: E402
import launcher  # noqa: E402
import mem_gui  # noqa: E402
import outbid  # noqa: E402
import rebirth  # noqa: E402
from memory_backend import get_backend  # noqa: E402

mb = get_backend()
print("alive", mb.alive(), flush=True)
print("balance", balance.read_balance(), flush=True)
print("in_game", launcher.in_game(None), "disconnected", launcher.is_disconnected(None), flush=True)
gb = gifts._child("CardsUI", "PlaytimeGiftBtn")
print("gift button", gifts._labels(gb), "ready", gifts.gift_ready() is not None, flush=True)
db = gifts._child("CardsUI", "DailyBtn")
print("daily button", gifts._labels(db), "spin btn", gifts._spin_button(), "summary", gifts._is_summary(), flush=True)
p = rebirth._panel()
print("rebirth panel", hex(p) if p else None, "open", rebirth.menu_open(), flush=True)
all_text = " ".join((mb._content_text(o) or "") for _, o in mb._walk(p, 8, 3000)) if p else ""
print("  rebirth text (hidden too):", all_text[:300], flush=True)
print("  rebirth side button", mem_gui.locate(text="Rebirth", screen="CardsUI"), flush=True)
print("outbid notice", outbid.read_notice(mb, mb._walk), flush=True)
overlay = gifts._child("CardsUI", "PlaytimeGifts")
if overlay:
    print("gift tier buttons:", [(t, gifts._labels(b, 1)) for t, b in mem_gui.buttons(overlay, depth=4)][:12], flush=True)
