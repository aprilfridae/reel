"""The website's "My #1s" collection: every #1 card ever found in the Index, for every tracked rarity, kept for good
in web/data/ones.json. Each is known by its artist and rarity (read from memory, see index_check.py) and drawn on the
website from its artwork (card_art), like the game draws it.

Entries recorded before memory reading have no name (they were screenshots, since deleted). A rarity's are replaced the first time a memory sweep finds at least as many #1s there (they're all among them then); until
then they stay as they are.
"""
import re
import time

import webstate


def _key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def set_rarity(rarity, cards, found_at=None, log=print):
    """`cards` = every #1 of this rarity in the Index now ({name, art, income}). Adds the ones not kept yet (cards you
    no longer have stay: the collection is all-time). Returns the new entries."""
    found_at = found_at or time.strftime("%Y-%m-%d %H:%M")
    new = []

    def update(entries):
        legacy = [e for e in entries if e.get("rarity") == rarity and not e.get("name")]
        kept = {_key(e["name"]): e for e in entries if e.get("rarity") == rarity and e.get("name")}
        dates = sorted(e.get("found_at") or found_at for e in legacy) if len(cards) >= len(legacy) else []
        if dates:  # every old screenshot of this rarity is one of these cards: they take over its date
            entries = [e for e in entries if e not in legacy]
        for c in cards:
            k = _key(c.get("name"))
            if not k:
                continue
            if k in kept:
                if c.get("art") and kept[k].get("art") != c["art"]:
                    kept[k]["art"] = c["art"]
                continue
            had_screenshot = bool(dates)
            e = {"id": f"{rarity}_{k}", "rarity": rarity, "name": c["name"], "serial": "1", "art": c.get("art"),
                 "income": c.get("income"), "found_at": dates.pop(0) if dates else found_at}
            entries.append(e)
            kept[k] = e
            if not had_screenshot:
                new.append(e)
        return entries

    webstate.update("ones.json", [], update)
    if new:
        log(f"New #1 card(s) for the website: {len(new)} {rarity} ({', '.join(e['name'] for e in new)})")
    return new
