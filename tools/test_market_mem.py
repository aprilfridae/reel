"""Live test of getting to the Card Market from memory: teleport, walk until "Open Market" is the one prompt in range,
press E (only then), Browse tab. Usage: python tools/test_market_mem.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import packs  # noqa: E402
from game import Game  # noqa: E402

game = Game()
packs.close_popup(game)
packs.close_any_menu(game)
print("teleport", packs.teleport(game, "Spawn", settle=0.6, poll=0.25), flush=True)
print("prompts at spawn:", market.prompts(), flush=True)
print("walk stopped at prompt:", market.walk_route(game), "prompts:", market.prompts(), flush=True)
print("market opened:", market._try_prompt(game), flush=True)
print("browse tab:", market.ensure_browse_tab(game), "market open:", market.market_open(), flush=True)
print("UI scale:", game.ui_scale(), "menu_open:", game.menu_open(), flush=True)
