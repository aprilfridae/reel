"""Live checks that never got a run: the gift and daily buttons, one dry-run rebirth (arms the confirm, never spends),
and the Trade menu's player list. Closes every menu it opens. Usage: python tools/test_finish_mem.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gifts  # noqa: E402
import mem_gui  # noqa: E402
import packs  # noqa: E402
import rebirth  # noqa: E402
import trade  # noqa: E402
from game import Game  # noqa: E402

game = Game()
packs.close_popup(game)
packs.close_any_menu(game)

gift = gifts._child("CardsUI", "PlaytimeGiftBtn")
daily = gifts._child("CardsUI", "DailyBtn")
print("gift button:", gifts._labels(gift), "ready:", gifts.gift_ready() is not None, flush=True)
print("daily button:", gifts._labels(daily), flush=True)
print("claimed gifts:", gifts.claim_gifts(game), flush=True)
print("daily spin:", gifts.daily_spin(game), flush=True)
packs.close_any_menu(game)

print("rebirth menu:", rebirth.open_menu(game), flush=True)
print("rebirth state:", rebirth.read_state(game), flush=True)
ok, msg = rebirth.rebirth_once(game, dry_run=True)
print("dry run:", ok, msg, flush=True)
packs.close_any_menu(game)
print("menu closed, still open:", rebirth.menu_open(game), flush=True)
print("reopened:", rebirth.open_menu(game), "button says:",
      mem_gui.text_of(rebirth._button(game)) if rebirth.menu_open(game) else None, flush=True)
packs.close_any_menu(game)

players, note = trade.read_players(game)
print("trade players:", None if players is None else len(players), note, flush=True)
if players:
    print(" first:", players[0], flush=True)
packs.close_any_menu(game)
print("done, menu open:", game.menu_open(), flush=True)
