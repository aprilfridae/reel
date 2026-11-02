"""The home-network website: market (#1-#10 listings), bid / buy requests, and chat.

  python web/app.py        then open http://<this PC's IP>:8080 on any device at home

It only reads and writes the shared files in web/data/; the bot does the actual
clicking in game. No login: keep it on the home network (don't port-forward it).
"""
import os
import re
import sys
import time
import uuid

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import card_art  # noqa: E402
import config  # noqa: E402
import tz  # noqa: E402
import webstate  # noqa: E402
from paths import APP, RES  # noqa: E402
from version import VERSION  # noqa: E402

# the page is bundled in the .exe; the card pictures are saved next to it as they're found
app = Flask(__name__, static_folder=os.path.join(APP, "web", "static"))


@app.get("/")
def index():
    return send_from_directory(os.path.join(RES, "web"), "index.html")


_UNITS = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12, "Q": 1e15}


def _value(text):
    """'200B' / '1.5T' -> number (0 if it can't be read)."""
    try:
        t = str(text).strip().upper().replace(",", "")
        return float(t[:-1]) * _UNITS[t[-1]] if t and t[-1] in _UNITS else float(t)
    except (ValueError, IndexError):
        return 0.0


def _short(v):
    for unit, size in (("Q", 1e15), ("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= size:
            return f"{v / size:.1f}".rstrip("0").rstrip(".") + unit
    return str(int(v))


def active_bids(market, requests, now):
    """Bids placed from this website that are probably still running: the listing is still
    in the last market scan and hasn't ended, or it isn't in the scan but the bid was placed
    after that scan (and under 12 hours ago). The game's own count (it shows when a rebirth
    is attempted) is in rebirth.json."""
    cards = market.get("cards", [])
    scanned = market.get("scanned_ts", 0)
    found = []
    for r in requests:
        if r.get("kind") != "bid" or r.get("status") != "done":
            continue
        c = r.get("card", {})
        try:
            placed = time.mktime(time.strptime(r["asked_at"], "%Y-%m-%d %H:%M:%S"))
        except (KeyError, ValueError):
            continue
        live = next((m for m in cards if m.get("seller") == c.get("seller") and str(m.get("serial")) == str(c.get("serial"))
                     and m.get("name") == c.get("name")), None)
        if live is not None:
            ok = not live.get("ends_ts") or live["ends_ts"] > now
        else:
            ok = placed > scanned and now - placed < 12 * 3600
        if ok:
            found.append(r)
    total = sum(_value(r.get("amount")) for r in found)
    return {"count": len(found), "total": _short(total) if found else "0",
            "items": [{"amount": r["amount"], "serial": r.get("card", {}).get("serial"),
                       "seller": r.get("card", {}).get("seller")} for r in found]}


LOGO_FILES = ("logo.svg", "logo.gif", "logo.webp", "logo.png")


def _logo_dirs():
    # next to the program first (drop your own logo there), then the one bundled in the .exe
    return (os.path.join(APP, "web", "static"), os.path.join(RES, "web", "static"))


@app.get("/api/logo")
def logo():
    """The header logo: logo.svg / .gif / .webp / .png in web/static, whichever is there first."""
    for name in LOGO_FILES:
        if any(os.path.exists(os.path.join(d, name)) for d in _logo_dirs()):
            return jsonify(file=name)
    return jsonify(file=None)


@app.get("/brand/<name>")
def brand(name):
    if name in LOGO_FILES:
        for d in _logo_dirs():
            if os.path.exists(os.path.join(d, name)):
                return send_from_directory(d, name)
    return "", 404


@app.get("/api/state")
def state():
    market = webstate.load("market.json", {"cards": [], "scanned_at": None})
    now = time.time()
    trade = {**webstate.load("trade.json", {}), "cmds": webstate.load("trade_cmd.json", [])[-8:]}
    if trade.get("open") and now - float(trade.get("ts") or 0) > 120:
        # an open trade window is saved at least every 30 seconds: this one is left over (the bot
        # stopped, or the game closed under it), so it isn't shown as open
        trade.update(open=None, offer=None, stale=True)
    market["cards"] = [c for c in market.get("cards", [])  # drop auctions that have ended
                       if not c.get("ends_ts") or c["ends_ts"] > now]
    card_art.attach(market)  # the cards' own pictures (from the game), where known
    mybids = card_art.attach(webstate.load("mybids.json", {}))
    card_art.attach(trade)
    return jsonify({
        "market": market,
        "ones": card_art.attach([{k: v for k, v in e.items() if k != "fp"}  # all-time #1 cards (fp is internal)
                                 for e in webstate.load("ones.json", [])]),
        "requests": webstate.load("requests.json", [])[-50:],
        "chat": webstate.load("chat.json", [])[-200:],
        "outbox": webstate.load("outbox.json", []),
        "status": webstate.load("status.json", {}),
        "balance": webstate.load("balance.json", {}),
        "rebirth": webstate.load("rebirth.json", {}),
        "mode": webstate.load("mode.json", {}),
        "bids": active_bids(market, webstate.load("requests.json", []), now),
        "mybids": mybids,
        "lookup": webstate.load("lookup.json", {}),
        "bid_anyway": bid_anyway(),
        "bids_seen": webstate.load("bids_seen.json", {}),
        "trade": trade,
        "packlog": {"log": card_art.attach(webstate.load("packlog.json", [])[-80:]), "roll": webstate.load("packroll.json", {})},
        "outbid": card_art.attach(webstate.load("outbid.json", [])[-20:]),
        "mem": {  # live memory-polled data (always fresh)
            "balance": webstate.load("balance.json", {}),
            "fishing": webstate.load("mem_fishing.json", {}),
            "event": webstate.load("mem_event.json", {}),
            "trade_incoming": webstate.load("mem_trade.json", {}),
        },
        "fishing": {**webstate.load("fishcal.json", {}), "settings": webstate.load("fishing.json", {})},
        "tz": tz.info(),
        "now": time.time(),  # so the page's countdowns use this PC's clock
        "version": VERSION,  # an open page reloads itself when this changes (an update brought a new page)
    })


@app.post("/api/request")
def add_request():
    """A bid or a buy-now for one listing."""
    body = request.get_json(force=True)
    kind = body.get("kind")
    if kind not in ("bid", "buy"):
        return jsonify(error="kind must be bid or buy"), 400
    amount = str(body.get("amount", "")).strip().upper().replace(" ", "")
    if kind == "bid" and not amount:
        return jsonify(error="enter an amount, e.g. 650B"), 400
    req = {
        "id": uuid.uuid4().hex[:8],
        "kind": kind,
        "amount": amount,
        "card": {k: body.get("card", {}).get(k)
                 for k in ("name", "seller", "serial", "image", "start", "current_bid", "buy_now")},
        "status": "waiting",
        "result": "",
        "asked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    webstate.update("requests.json", [], lambda r: r + [req])
    return jsonify(req)


def bid_anyway():
    """Rebirth even with coins in Market bids (they're lost)? The website's switch, else config.json."""
    saved = webstate.load("mode.json", {}).get("bid_anyway")
    return saved if isinstance(saved, bool) else bool(config.load()["rebirth_forfeits_bids"])


@app.post("/api/bidanyway")
def set_bid_anyway():
    on = bool(request.get_json(force=True).get("on"))
    webstate.update("mode.json", {}, lambda m: {**m, "bid_anyway": on})
    return jsonify(on=on)


@app.post("/api/mode")
def set_mode():
    """What the bot should be doing: auto (the schedule), fish (just fish), packs (keep opening packs) or pause."""
    mode = request.get_json(force=True).get("mode")
    if mode not in ("auto", "fish", "packs", "pause"):
        return jsonify(error="mode must be auto, fish, packs or pause"), 400
    webstate.update("mode.json", {}, lambda m: {**m, "mode": mode})
    return jsonify(ok=True)


@app.post("/api/do")
def do_once():
    """A one-time job: open every rare pack now ("packs"), or record the #1s ("index")."""
    what = request.get_json(force=True).get("what")
    if what not in ("packs", "index"):
        return jsonify(error="what must be packs or index"), 400
    webstate.update("mode.json", {}, lambda m: {**m, "once": sorted(set(m.get("once", [])) | {what})})
    return jsonify(ok=True)


RARITIES = ("common", "uncommon", "rare", "epic", "legendary", "mythic", "secret", "glitched", "kawaii", "radiation",
            "iced", "molten", "charged", "tidal", "spooky", "acid", "meteor", "eclipse", "blood", "atlantis")


def _market_request(kind, card, amount=""):
    req = {"id": uuid.uuid4().hex[:8], "kind": kind, "amount": amount, "card": card, "status": "waiting",
           "result": "", "asked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    webstate.update("requests.json", [], lambda r: r + [req])
    return req


@app.post("/api/lookup")
def ask_lookup():
    """Who owns the lowest serials of an artist's card in one rarity (the bot reads it in game)."""
    body = request.get_json(force=True)
    artist = str(body.get("artist", "")).strip()[:40]
    rarity = str(body.get("rarity", "common")).lower()
    find = str(body.get("find", "")).strip()[:6]
    if not artist:
        return jsonify(error="enter an artist name"), 400
    if rarity not in RARITIES:
        return jsonify(error="unknown rarity"), 400
    if find and not find.isdigit():
        return jsonify(error="the serial to find must be a number"), 400
    return jsonify(_market_request("lookup", {"artist": artist, "rarity": rarity, "find": find}))


@app.post("/api/lookup/clear")
def clear_lookup():
    """The who-owns search box was emptied: forget the last results."""
    webstate.save("lookup.json", {})
    return jsonify(ok=True)


@app.post("/api/join")
def ask_join():
    """Join the server of the owner of one serial (the bot presses Join server in game)."""
    body = request.get_json(force=True)
    artist = str(body.get("artist", "")).strip()[:40]
    rarity = str(body.get("rarity", "common")).lower()
    name = str(body.get("name", "")).strip()[:40]
    try:
        serial = int(body.get("serial"))
    except (TypeError, ValueError):
        return jsonify(error="serial must be a number"), 400
    if not artist or rarity not in RARITIES or not name:
        return jsonify(error="artist, rarity and owner are needed"), 400
    return jsonify(_market_request("join", {"artist": artist, "rarity": rarity, "serial": serial, "name": name}))


TRADE_CMDS = ("accept", "decline", "send", "refresh", "search", "ready", "cancel", "addwanted", "players",
              "add", "remove", "coins", "want")


@app.post("/api/trade/cmd")
def trade_cmd():
    """Something the bot should do in the game's Trade window / request popup. Each one is pressed here, by you:
    the bot never accepts, sends, or presses READY on its own."""
    body = request.get_json(force=True)
    cmd = body.get("cmd")
    if cmd not in TRADE_CMDS:
        return jsonify(error="unknown trade command"), 400
    args = {}
    if cmd == "send":
        args["name"] = str(body.get("name", "")).strip()[:40]
        args["alt"] = str(body.get("alt", "")).strip()[:40]  # the display name, tried if the user name is misread
        if not args["name"]:
            return jsonify(error="enter the player's name"), 400
    if cmd == "search":
        args["tab"] = "mine" if body.get("tab") == "mine" else "theirs"
        args["query"] = str(body.get("query", "")).strip()[:30]
    if cmd in ("add", "remove", "want"):
        # the card as the website listed it (its name, serial / copy number and place in the game's order)
        args = {k: str(body.get(k, "")).strip()[:40] for k in ("name", "serial", "rarity", "copy", "query")}
        args["rank"] = str(int(body["rank"])) if str(body.get("rank", "")).isdigit() else ""
        if not args["name"]:
            return jsonify(error="which card?"), 400
    if cmd == "coins":
        args["amount"] = str(body.get("amount", "")).strip().replace(",", "")[:20]
        if not re.fullmatch(r"\d+(\.\d+)?[KMBTQkmbtq]?", args["amount"]):
            return jsonify(error="enter an amount like 500, 2.5B or 1T"), 400
    c = {"id": uuid.uuid4().hex[:8], "cmd": cmd, "args": args, "status": "waiting", "result": "",
         "at": time.strftime("%H:%M:%S")}
    webstate.update("trade_cmd.json", [], lambda cs: (cs + [c])[-40:])
    return jsonify(c)


@app.post("/api/fishing")
def set_fishing():
    """Ping compensation: comp (0-150 %: how much of the measured bar delay the aim-ahead allows for) or, with
    manual on, the aim-ahead itself in seconds. Takes effect from the next reel."""
    body = request.get_json(force=True)
    change = {}
    try:
        if "comp" in body:
            change["comp"] = min(150, max(0, int(float(body["comp"]))))
        if "manual" in body:
            change["manual"] = bool(body["manual"])
        if "lead" in body:
            change["lead"] = round(min(2.0, max(0.1, float(body["lead"]))), 2)
    except (TypeError, ValueError):
        return jsonify(error="those must be numbers"), 400
    webstate.update("fishing.json", {}, lambda s: {**s, **change})
    return jsonify(ok=True, **change)


@app.post("/api/tz")
def set_tz():
    """The schedule's timezone: "auto" (the PC's own) or an IANA name like America/Chicago."""
    zone = str(request.get_json(force=True).get("zone", "auto")).strip()
    if zone != "auto":
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(zone)
        except Exception:
            return jsonify(error="unknown timezone"), 400
    webstate.save("tz.json", {"zone": zone})
    return jsonify(ok=True, **tz.info())


@app.post("/api/rebirth")
def ask_rebirth():
    """Rebirth `count` times (default 1). The bot does the two clicks per rebirth."""
    try:
        count = int(float(str(request.get_json(force=True).get("count", 1))))
    except ValueError:
        return jsonify(error="count must be a number"), 400
    if not 1 <= count <= 50:
        return jsonify(error="count must be 1-50"), 400
    req = {"id": uuid.uuid4().hex[:8], "kind": "rebirth", "amount": str(count), "card": {},
           "status": "waiting", "result": "", "asked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    webstate.update("requests.json", [], lambda r: r + [req])
    return jsonify(req)


@app.post("/api/request/<rid>/cancel")
def cancel_request(rid):
    def fn(reqs):
        for r in reqs:
            if r["id"] == rid and r["status"] == "waiting":
                r["status"] = "cancelled"
        return reqs
    webstate.update("requests.json", [], fn)
    return jsonify(ok=True)


@app.get("/api/chat")
def chat_feed():
    """Just the chat, light enough for the page to ask every second."""
    return jsonify(chat=webstate.load("chat.json", [])[-200:], outbox=webstate.load("outbox.json", []))


@app.post("/api/chat")
def send_chat():
    text = str(request.get_json(force=True).get("text", "")).strip()
    if not text:
        return jsonify(error="empty message"), 400
    if len(text) > 200:
        return jsonify(error="too long (200 max)"), 400
    msg = {"id": uuid.uuid4().hex[:8], "text": text, "asked_at": time.strftime("%H:%M:%S")}
    webstate.update("outbox.json", [], lambda o: o + [msg])
    # shown in the chat straight away, as yours (the bot never reads its own account's lines back off the screen)
    entry = {"at": msg["asked_at"], "who": "You", "text": text, "mine": True, "id": msg["id"]}
    webstate.update("chat.json", [], lambda c: (c + [entry])[-500:])
    return jsonify(msg)


@app.post("/api/scan")
def ask_scan():
    """Ask the bot to check the market now instead of waiting for the hourly check."""
    webstate.save("scan_now.json", {"at": time.time()})
    return jsonify(ok=True)


def serve(port=8080):
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    serve()
