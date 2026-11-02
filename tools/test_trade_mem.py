"""The trade parts that need no other player: window / request popup state, the Trade menu's players, and a dry-run
send (finds the player, never clicks Send). Usage: python tools/test_trade_mem.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import trade  # noqa: E402
from game import Game  # noqa: E402

game = Game()
print("window:", trade.window_open(), "request:", trade.incoming(), flush=True)
players, total = trade.read_players(game)
print("players:", total, players[:6] if players else players, flush=True)
if players:
    p = players[len(players) // 2]
    print("dry send:", trade.send_request(game, p["user"], dry=True), flush=True)
