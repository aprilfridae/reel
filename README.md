# underground-rng-bot

A screen-reading bot for the Roblox game *Underground Artist RNG* (Windows only). It never
touches the game's memory or files: it watches the screen and sends keyboard/mouse input.

**Use at your own risk.** Automating a Roblox game can break the game's or Roblox's rules and
can get an account banned.

## What it does

- Fishes nonstop (computer-vision reel minigame, with the aim adjusted to the PC's input delay)
  and opens Atlantis packs from catch popups.
- Reads the event banner and opens event packs as they drop; records new #1 cards from the Index.
- Nightly (1-6 AM, in the PC's or a chosen timezone): opens every Rainbow-or-rarer and event pack,
  then rebirths with a share of your coins.
- Claims playtime gifts and the daily spin.
- Scans the Card Market for serial #1-#3 listings and places bids / buy-nows; notices the game's
  "You were outbid!" message.
- Trades, every step confirmed on the website: requests, both offers with card pictures, adding,
  taking out and asking for single cards, coins, READY. The bot never completes a trade by itself.
- Opens Roblox in fullscreen and joins the game itself if it isn't running, and again if it closes.
- Updates itself from the newest GitHub release.
- A website on your home network (`http://<this PC>:8080`): bot controls (Auto, Fish only,
  Open packs, Paused), the market, your listings and bids, a live pack log, the trade room,
  Who owns? (with Join server), your all-time #1s, rebirth, and game chat (read and send).

Bids, buys, rebirths, trades and chat from the website interrupt whatever the bot is doing, then
it carries on.

## Run it

```
pip install -r requirements.txt
python main.py                     # bot + website
python main.py --dry-run-rebirth   # rebirths stop before the confirming click
python main.py --selftest          # checks text reading and the bundled pictures (exit code 1 if not)
```

Or build a single `.exe` (no Python needed on the PC that runs it): `.\build_exe.ps1`, then
share `dist\UndergroundBot.exe`. A Python 3.12 venv with numpy 1.26 (`venv312\`) makes an .exe
that also starts on older PCs.

Settings are in `config.json`, created next to the program on first run (website, market
trips, nightly session hours, nightly rebirth share, auto-update, auto-launch...).
F8 (or creating `stop.flag`) stops the bot. Keep the Roblox window visible and the PC awake.

## Layout

| | |
|---|---|
| `main.py` | the program: starts the website, the updater and the bot (`--selftest`) |
| `bot.py` | the schedule: fishing, events, nightly session, chores, and website requests |
| `game.py`, `vision.py`, `ocr.py`, `ui_keys.py` | window capture, input, button matching, text reading, typing |
| `fisher.py` | the reel minigame |
| `events.py`, `packs.py`, `packlog.py`, `index_check.py`, `ones.py` | events, opening packs, the pack log, #1s |
| `market.py`, `market_scan.py`, `mybids.py`, `whoowns.py`, `balance.py`, `outbid.py` | the Card Market |
| `trade.py`, `trade_flow.py`, `trade_badges.py` | the Trade window, and its link to the website |
| `chat.py`, `gifts.py`, `rebirth.py`, `launcher.py` | chat, gifts and daily spin, rebirths, starting Roblox |
| `config.py`, `paths.py`, `tz.py`, `webstate.py`, `cleanup.py`, `updater.py`, `version.py` | settings, files, clock, shared state, disk clean-up, self-update |
| `web/` | the website (`app.py` + `index.html`) |
| `templates/` | the button pictures (matched at whatever UI scale the game is showing) |
| `tools/` | development helpers (deploying to a bot PC over SSH, offline tests, a website preview) |

## Notes

- Buttons are found by template matching; the UI scale is detected at runtime.
- Text is read with Windows' built-in OCR (via the `winrt-*` packages). Very short numbers
  ("5T") can't be read by it, so amounts the program types itself are not read back.
- The website has no login. Keep it on your home network and don't port-forward it.
- Everything the bot writes (settings, state, card pictures, website data) goes next to the
  program, so it survives restarts; old pictures are cleaned up automatically. The bot and the
  website share small JSON files in `web/data/` under a cross-process lock.
