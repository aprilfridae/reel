"""Settings, read from config.json in the app's folder (written with the defaults the
first time, so there is always a file to edit).

Everything here has a safe default, so the program works with no config at all.
"""
import json
import os

from paths import APP

CONFIG_FILE = os.path.join(APP, "config.json")

DEFAULTS = {
    # Getting into the game
    "auto_launch": True,         # open Roblox and join the game if it isn't running
    "place_id": 78972201022064,  # Underground Artist RNG
    "server_id": "",             # optional: a server (job id) to join instead of any server
    # The website (market list, bids, rebirth button, chat), reachable from your home network
    "fullscreen": True,          # keep Roblox in F11 fullscreen (the same screen layout on every PC)
    "send_diagnostics": True,    # send reel_log.csv + a reel screenshot to the developer after the first reels
    "chat_ignore_names": [],     # more accounts whose chat lines the website leaves out (april fridae and cable always are)
    "auto_update": True,         # check GitHub for a newer release and replace this .exe with it
    "website": True,
    "website_port": 8080,
    # What the bot does
    "market_trips": True,        # hourly market check, and placing bids / buys from the website
    "market_every_minutes": 60,
    "nightly_session": True,     # open every Rainbow-or-rarer pack once a night
    "session_start_hour": 1,     # ...starting at this hour (local time)...
    "session_end_hour": 6,       # ...and not later than this one
    "nightly_rebirth": True,     # after the nightly packs, spend part of the coins on rebirths
    "rebirth_fraction": 0.25,    # ...this share of the coins on hand
    "rebirth_forfeits_bids": True,  # coins in active Market bids are lost on a rebirth: go ahead anyway (false = cancel)
    "claim_gifts": True,         # playtime gifts + the daily spin
}


def load():
    """The settings: defaults, overridden by whatever config.json says."""
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, encoding="utf-8-sig") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if not os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULTS, f, indent=2)
        except OSError:
            pass
    return cfg
