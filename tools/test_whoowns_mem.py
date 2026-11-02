"""With the market open: a Who owns? look-up from memory (never joins). Usage: python tools/test_whoowns_mem.py artist rarity"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import whoowns  # noqa: E402
from game import Game  # noqa: E402

game = Game()
r = whoowns.lookup(game, sys.argv[1] if len(sys.argv) > 1 else "krby", sys.argv[2] if len(sys.argv) > 2 else "common")
print({k: v for k, v in r.items() if k != "rows"}, flush=True)
for row in r["rows"][:15]:
    print("  ", row, flush=True)
