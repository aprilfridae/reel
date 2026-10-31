"""The home-network website: market (#1-#10 listings), bid / buy requests, and chat.

  python web/app.py        then open http://<this PC's IP>:8080 on any device at home

It only reads and writes the shared files in web/data/; the bot does the actual
clicking in game. No login: keep it on the home network (don't port-forward it).
"""
import os
import sys
import time
import uuid

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import webstate  # noqa: E402
from paths import APP, RES  # noqa: E402

# the page is bundled in the .exe; the card pictures are saved next to it as they're found
app = Flask(__name__, static_folder=os.path.join(APP, "web", "static"))


@app.get("/")
def index():
    return send_from_directory(os.path.join(RES, "web"), "index.html")


@app.get("/api/state")
def state():
    market = webstate.load("market.json", {"cards": [], "scanned_at": None})
    now = time.time()
    market["cards"] = [c for c in market.get("cards", [])  # drop auctions that have ended
                       if not c.get("ends_ts") or c["ends_ts"] > now]
    return jsonify({
        "market": market,
        "ones": [{k: v for k, v in e.items() if k != "fp"}  # all-time #1 cards (fp is internal)
                 for e in webstate.load("ones.json", [])],
        "requests": webstate.load("requests.json", [])[-50:],
        "chat": webstate.load("chat.json", [])[-200:],
        "outbox": webstate.load("outbox.json", []),
        "status": webstate.load("status.json", {}),
        "balance": webstate.load("balance.json", {}),
        "rebirth": webstate.load("rebirth.json", {}),
        "mode": webstate.load("mode.json", {}),
        "now": time.time(),  # so the page's countdowns use this PC's clock
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


@app.post("/api/mode")
def set_mode():
    """What the bot should be doing: auto (the schedule), fish (just fish) or pause."""
    mode = request.get_json(force=True).get("mode")
    if mode not in ("auto", "fish", "pause"):
        return jsonify(error="mode must be auto, fish or pause"), 400
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
