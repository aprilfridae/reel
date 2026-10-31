# underground-rng-bot

A screen-reading bot for the Roblox game *Underground Artist RNG* (Windows only). It never
touches the game's memory or files: it watches the screen and sends keyboard/mouse input.

**Use at your own risk.** Automating a Roblox game can break the game's or Roblox's rules and
can get an account banned.

## What it does

- Fishes nonstop (computer-vision reel minigame) and opens Atlantis packs from catch popups.
- Reads the event banner and opens event packs; records new #1 cards from the Index
  (about a minute for a full sweep).
- Nightly (1-6 AM): opens every Rainbow-or-rarer and event pack, then rebirths with a share of
  your coins (25% by default).
- Claims playtime gifts and the daily spin.
- Scans the Card Market for serial #1-#3 listings and places bids / buy-nows.
- Opens Roblox and joins the game itself if it isn't running, and again if it closes.
- A website on your home network (`http://<this PC>:8080`), dark themed, with tabs for the
  market listings, your own listings and bids, and your all-time #1 collection; a rebirth
  counter and button (with a "Rebirth anyway" switch for when coins are tied up in Market
  bids, which a rebirth loses); a log of bids and buys; game chat (read and send); your coin
  balance (updated right after every buy); and a switch between Auto (the schedule), Fish
  only and Paused.

Bids, buys, rebirths and chat from the website interrupt whatever the bot is doing, then it
carries on.

## Run it

```
pip install -r requirements.txt
python main.py                     # bot + website
python main.py --dry-run-rebirth   # rebirths stop before the confirming click
python main.py --selftest          # checks text reading and the bundled pictures
```

Or build a single `.exe` (no Python needed on the PC that runs it): `.\build_exe.ps1`, then
share `dist\UndergroundBot.exe`.

Settings are in `config.json`, created next to the program on first run (website, market
trips, nightly session hours, nightly rebirth share, `rebirth_forfeits_bids`, auto-launch...).
F8 (or creating `stop.flag`) stops the bot. Keep the Roblox window visible and the PC awake.

## Notes

- The button pictures in `templates/` were cut from the game's UI at a 1369 px window height
  and are matched by template matching; the UI scale is detected at runtime.
- Text is read with Windows' built-in OCR (via the `winrt-*` packages). Very short numbers
  ("5T") can't be read by it, so amounts the program types itself are not read back.
- The website has no login. Keep it on your home network and don't port-forward it.
- Everything the bot writes (settings, state, card pictures, website data) goes next to the
  program, so it survives restarts. The bot and the website share small JSON files in
  `web/data/` under a cross-process lock.