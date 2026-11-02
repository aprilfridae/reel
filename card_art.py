"""Card pictures from the game itself instead of screenshots.

A card in the game (market, My Listings, trade window, pack reveal, ...) is a frame named "Card" whose artwork is one
ImageLabel; its Image property is the picture's asset id ("rbxassetid://93136958166288", kept as a string at +0xa78 in
the ImageLabel; found again by searching the object if a game update moves it). The rest of a card (frame, glow,
sparkles) is drawn by the game from gradients and small images, and its texts are read as usual. Cards are kept in
memory in closed menus too (the market, your own cards in CardsUI) and over players' heads (CardTag_<player>).

harvest() goes through the game's menus in memory (the memory poller runs it every so often) and records every card it
sees: artist, rarity and picture id, in web/data/art.json. Each new picture is downloaded once, in the background, from
Roblox's public thumbnail service (no login) to web/static/art/<id>.png. art_for(name, rarity) then gives the picture
for a card read anywhere, by OCR too (a close-enough name matches), and attach() adds it to the website's data.
"""
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
from difflib import SequenceMatcher

import webstate
from paths import APP

ART_DIR = os.path.join(APP, "web", "static", "art")
IMAGE_AT = 0xa78  # ImageLabel.Image (an std::string; a copy at +0x9a8 is only filled once the game has drawn it)
THUMBS = "https://thumbnails.roblox.com/v1/assets?assetIds={}&size=420x420&format=Png&isCircular=false"
_ID = re.compile(r"rbxassetid://(\d{5,20})$")

_lock = threading.Lock()
_state = {"index": None, "offset": IMAGE_AT, "queue": set(), "tries": {}, "worker": None, "fuzzy": {},
          "bad": set(), "bad_of": -1}


def _key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _index():
    if _state["index"] is None:
        _state["index"] = webstate.load("art.json", {})
    return _state["index"]


# ---- reading cards from memory ----
def image_id(mb, img):
    """The asset id (digits) an ImageLabel shows, or None."""
    m = _ID.match(mb.r.read_str(img + _state["offset"]) or "")
    return m.group(1) if m else None


def _find_offset(mb, img):
    """Where the Image string is now (after a game update moved it), from an artwork image: the first offset holding
    an asset id."""
    for off in range(0x400, 0x1400, 8):
        if _ID.match(mb.r.read_str(img + off) or ""):
            _state["offset"] = off
            return off
    return None


def _artwork(mb, card, any_image=False):
    """The card's artwork: its first image (the sparkles, reef and other decorations come after it). Its size can't
    tell: the cards shown over players' heads have meaningless screen sizes."""
    for d, o in mb._walk(card, depth=6, max_nodes=200):
        if mb._class_name(o) == "ImageLabel" and (any_image or image_id(mb, o)):
            return o
    return None


def read_card(mb, card):
    """{name, rarity, art} of a "Card" frame, or None."""
    import mem_market
    img = _artwork(mb, card)
    art = image_id(mb, img) if img else None
    if not art:
        return None
    info = mem_market.parse(mem_market._texts(mb, card, depth=8))
    return {"name": info.get("name"), "rarity": info.get("rarity"), "art": art} if info.get("name") else None


def harvest(mb, max_nodes=60000):
    """Record every card in the game's menus (shown or not). Returns how many new pictures were found."""
    new = 0
    stack, seen, cards, read = [mb.player_gui], 0, [], 0
    while stack and seen < max_nodes:
        node = stack.pop()
        seen += 1
        if mb._name(node) == "Card":
            cards.append(node)
            c = read_card(mb, node)
            read += c is not None
            if c and record(c["name"], c["rarity"], c["art"], save=False):
                new += 1
            continue  # (nothing more inside a card)
        stack.extend(mb._children(node))
    if len(cards) >= 5 and not read:  # cards but no pictures: the Image moved in a game update
        img = next((i for i in map(lambda c: _artwork(mb, c, any_image=True), cards) if i), None)
        if img and _find_offset(mb, img):
            return harvest(mb, max_nodes)
    if new:
        _save()
    return new


# ---- the index and the pictures ----
def record(name, rarity, art, save=True):
    """Remember a card's picture. True if it's new."""
    if not _key(name) or not art:
        return False  # (a name all in fancy-font letters has nothing to look it up by)
    with _lock:
        idx = _index()
        e = idx.setdefault(_key(name), {"name": name, "ids": {}})
        r = (rarity or "").upper()
        if e["ids"].get(r) == art:
            return False
        e["ids"][r] = art
        _state["fuzzy"].clear()
    if save:
        _save()
    fetch(art)
    return True


def _save():
    with _lock:
        webstate.save("art.json", _index())


def file_for(art):
    return os.path.join(ART_DIR, f"{art}.png")


def fetch(art):
    """Download a picture (in the background) if it isn't here yet."""
    if os.path.exists(file_for(art)):
        return
    with _lock:
        _state["queue"].add(art)
        if _state["worker"] is None or not _state["worker"].is_alive():
            _state["worker"] = threading.Thread(target=_download_loop, daemon=True, name="card-art")
            _state["worker"].start()


def _download_loop():
    while True:
        with _lock:
            batch = sorted(_state["queue"])[:100]
        if not batch:
            return
        try:
            with urllib.request.urlopen(THUMBS.format(",".join(batch)), timeout=15) as r:
                data = json.load(r).get("data", [])
        except Exception:
            data = []
        done = set()
        for d in data:
            art = str(d.get("targetId"))
            if d.get("state") == "Completed" and d.get("imageUrl"):
                try:
                    os.makedirs(ART_DIR, exist_ok=True)
                    with urllib.request.urlopen(d["imageUrl"], timeout=15) as r:
                        pic = _trim(r.read())
                    tmp = file_for(art) + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(pic)
                    os.replace(tmp, file_for(art))
                    done.add(art)
                except Exception:
                    pass
            elif d.get("state") in ("Blocked", "Error"):
                done.add(art)  # (moderated or gone: not asked again)
        with _lock:
            for art in batch:  # "Pending" ones are made on Roblox's side in a few seconds: asked again, up to 10 times
                _state["tries"][art] = _state["tries"].get(art, 0) + 1
                if art in done or _state["tries"][art] >= 10:
                    _state["queue"].discard(art)
        time.sleep(3)


def _trim(pic):
    """The picture with its see-through margins cut off (a picture that isn't square comes back from Roblox padded
    to a square), so every card's art fills its window the same way. The PNG bytes, unchanged if there's nothing
    to cut."""
    try:
        import cv2
        import numpy as np
        im = cv2.imdecode(np.frombuffer(pic, np.uint8), cv2.IMREAD_UNCHANGED)
        if im is None or im.ndim != 3 or im.shape[2] != 4:
            return pic
        ys, xs = np.where(im[:, :, 3] > 8)
        if not len(ys):
            return pic
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        if (y1 - y0, x1 - x0) == im.shape[:2]:
            return pic
        ok, out = cv2.imencode(".png", im[y0:y1, x0:x1])
        return out.tobytes() if ok else pic
    except Exception:
        return pic


def fetch_missing():
    """Queue every recorded picture that isn't downloaded yet (after a restart), and trim the ones downloaded
    before pictures were trimmed."""
    for e in list(_index().values()):
        for art in e["ids"].values():
            fetch(art)
    try:
        for f in os.listdir(ART_DIR):
            if f.endswith(".png"):
                with open(os.path.join(ART_DIR, f), "rb") as fh:
                    pic = fh.read()
                cut = _trim(pic)
                if cut is not pic:
                    with open(os.path.join(ART_DIR, f), "wb") as fh:
                        fh.write(cut)
    except OSError:
        pass


# ---- using them ----
def _placeholders():
    """Pictures Roblox won't show (not approved, or taken down) all come back as the same grey picture: any picture
    that three or more different ids got is that one. Their ids (worked out again when new pictures arrive)."""
    try:
        files = [f for f in os.listdir(ART_DIR) if f.endswith(".png")]
    except OSError:
        return set()
    if len(files) != _state["bad_of"]:
        by_hash = {}
        for f in files:
            try:
                with open(os.path.join(ART_DIR, f), "rb") as fh:
                    by_hash.setdefault(hashlib.md5(fh.read()).hexdigest(), []).append(f[:-4])
            except OSError:
                pass
        _state["bad"] = {a for ids in by_hash.values() if len(ids) >= 3 for a in ids}
        _state["bad_of"] = len(files)
    return _state["bad"]


def usable(art):
    """Is this picture downloaded, and a real one?"""
    return bool(art) and os.path.exists(file_for(art)) and art not in _placeholders()


def art_for(name, rarity=None):
    """The downloaded picture id for a card by its name (a close match is enough: names read by OCR are often a
    letter off), preferring its own rarity's picture. None if there's none."""
    k = _key(name)
    if not k:
        return None
    idx = _index()
    e = idx.get(k)
    if e is None:
        if k not in _state["fuzzy"]:
            best = max(idx, key=lambda o: SequenceMatcher(None, o, k).ratio(), default=None)
            _state["fuzzy"][k] = best if best and SequenceMatcher(None, best, k).ratio() >= 0.85 else None
        e = idx.get(_state["fuzzy"][k])
    if not e:
        return None
    ids = e["ids"]
    for art in (ids.get((rarity or "").upper()), *ids.values()):
        if usable(art):
            return art
    return None


def attach(data):
    """Add "art" to every card in the website's data (a dict with a name and a serial or rarity), in place."""
    if isinstance(data, list):
        for x in data:
            attach(x)
    elif isinstance(data, dict):
        if data.get("name") and ("serial" in data or "rarity" in data):
            art = data.get("art") if usable(data.get("art")) else art_for(data["name"], data.get("rarity"))
            if art:
                data["art"] = art
            else:
                data.pop("art", None)  # (not downloaded yet, or Roblox's placeholder: the screenshot is shown)
        for v in data.values():
            if isinstance(v, (list, dict)):
                attach(v)
    return data
