"""Prints the chat messages read from memory and whether chat is on / its window open. Usage: python tools/test_chat_mem.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chat  # noqa: E402

print("enabled", chat.chat_enabled(), "window", chat.window_open(), "button", chat._chat_button(), flush=True)
for mid, uid, who, text in chat.messages() or []:
    print(f"  {uid:>12} {who!r}: {text!r}  ({mid[:8]})", flush=True)
