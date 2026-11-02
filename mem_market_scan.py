"""Memory-based market scanner — replaces market_scan.py entirely.

Reads every listing card from Roblox memory: card name, serial (#1/#2/#3),
price, pack type, earnings, grade, and PLACE BID button position.
No CV, no OCR, no template matching — just direct ReadProcessMemory.

Usage:
    from mem_market_scan import scan_market
    listings = scan_market(mb)   # mb: MemoryBackend (must be started)
"""
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reader import Reader


def _valid(v):
    return v and 0x10000 < v < 0x7FFFFFFFFFFF


class MemMarketScanner:
    def __init__(self, reader):
        self.r = reader

    # ---- instance tree helpers ------------------------------------------
    def _class_name(self, inst):
        try:
            cd = self.r.u64(inst + 0x18)
            if not _valid(cd):
                return None
            p = self.r.u64(cd + 0x8)
            if not _valid(p):
                return None
            fl = self.r.u64(p + 0x18)
            if fl == 0x1F:
                p = self.r.u64(p)
                if not _valid(p):
                    return None
            return self.r.read_str(p)
        except Exception:
            return None

    def _name(self, inst):
        if not inst:
            return None
        p = self.r.u64(inst + 0x68)
        return self.r.read_str(p) if p else None

    def _parent(self, inst):
        p = self.r.u64(inst + 0x60)
        return p if _valid(p) else None

    def _children(self, inst):
        vs = self.r.u64(inst + 0x70) if inst else None
        if not _valid(vs):
            return []
        begin = self.r.u64(vs)
        end = self.r.u64(vs + 8)
        if not _valid(begin) or not end or end < begin or (end - begin) > 0x200000:
            return []
        out = []
        cur = begin
        while cur < end and len(out) < 20000:
            p = self.r.u64(cur)
            if p:
                out.append(p)
            cur += 0x10
        return out

    def _content_text(self, inst):
        ptr = self.r.u64(inst + 0xC60)
        return self.r.read_str(ptr) if _valid(ptr) else None

    def _button_pos(self, inst):
        x = self.r.f32(inst + 0xFC)
        y = self.r.f32(inst + 0x100)
        if x is None or y is None:
            return None
        return (x, y)

    def _walk(self, inst, depth=20, max_nodes=40000):
        count = 0
        stack = [(0, inst)]
        while stack and count < max_nodes:
            d, i = stack.pop()
            yield d, i
            count += 1
            if d < depth:
                for c in reversed(self._children(i)):
                    stack.append((d + 1, c))

    # ---- find MarketUI ---------------------------------------------------
    def _find_marketui(self, player_gui):
        for c in self._children(player_gui):
            if self._name(c) == "MarketUI" and self._class_name(c) == "ScreenGui":
                return c
        return None

    # ---- collect all text labels under a node ---------------------------
    def _collect_labels(self, inst):
        """Return list of (instance, text) for TextLabel/TextButton/TextBox."""
        out = []
        for d, i in self._walk(inst, depth=16):
            cls = self._class_name(i)
            if cls in ("TextLabel", "TextButton", "TextBox"):
                txt = self._content_text(i)
                if txt:
                    out.append((i, txt.strip(), cls))
        return out

    # ---- parse one listing card -----------------------------------------
    SERIAL_RE = re.compile(r"#(\d+)/\d+")
    PRICE_RE = re.compile(r"([\d.,]+\s*[KMBTQ]?)")

    # Common UI words that aren't card names
    NOT_NAME = {
        "BUY", "CANCEL", "PLACE", "BID", "GRADE", "SORT", "REFRESH", "MIN",
        "UNDERGROUND", "RNG", "EARN", "COINS", "SERIAL", "SORT BY", "PLACE BID",
    }

    def _parse_listing_card(self, card_inst):
        """Extract listing data from a card Frame."""
        data = {
            "name": None,
            "serial": None,
            "price": None,
            "pack": None,
            "seller": None,
            "earnings": None,
            "grade": None,
            "bid_btn": None,
            "bid_pos": None,
        }
        labels = self._collect_labels(card_inst)

        for i, txt, cls in labels:
            t = txt.strip()

            # Serial: '#17/969'
            m = self.SERIAL_RE.search(t)
            if m:
                data["serial"] = m.group(1)
                continue

            # Earnings: '+2700/s'
            if t.startswith("+") and "/s" in t:
                data["earnings"] = t
                continue

            # Pack name: all-caps short word (ATLANTIS, KAWAII, ICED, etc.)
            if (t.isupper() and 3 <= len(t) <= 16 and not data["pack"]
                    and t not in self.NOT_NAME):
                data["pack"] = t
                continue

            # Grade: standalone number 1-10
            if t.isdigit() and 1 <= int(t) <= 10 and not data["grade"]:
                data["grade"] = t
                continue

            # Creator: 'Underground RNG' pattern
            if "RNG" in t.upper() and not data["seller"]:
                data["seller"] = t
                continue

            # Card name: anything that's left (not earnings, serial, pack, grade, creator)
            if not data["name"] and len(t) >= 1:
                upper = t.upper()
                if (upper not in self.NOT_NAME
                        and not self.SERIAL_RE.search(t)
                        and not t.startswith("+")
                        and not t.isdigit()
                        and not t.isupper()
                        and "RNG" not in upper):
                    data["name"] = t
                    continue

            # Price on PLACE BID button: 'Buy 💰2.1B' or 'PLACE BID 💰2.1B'
            m2 = self.PRICE_RE.search(t)
            if m2 and ("buy" in upper or "PLACE BID" in upper) and not data["price"]:
                data["price"] = m2.group(1).replace(" ", "")
                continue

        # PLACE BID button: its text is on a Label child, not the button itself
        for i, txt, cls in labels:
            if cls == "TextButton":
                # check descendants for "PLACE BID" label
                for ci, ctxt, ccls in self._collect_labels(i):
                    if ctxt.strip().upper() == "PLACE BID":
                        data["bid_btn"] = i
                        data["bid_pos"] = self._button_pos(i)
                        break
                if data["bid_btn"]:
                    break

        return data

    # ---- find all listing cards -----------------------------------------
    def _find_card_frames(self, mui):
        """Find card Frame instances under MarketUI."""
        cards = []
        for d, i in self._walk(mui, depth=20):
            cls = self._class_name(i)
            nm = self._name(i) or ""
            if cls == "Frame" and nm == "Card":
                cards.append(i)
        return cards

    def scan_listings(self, player_gui):
        """Return list of listing dicts with name, serial, price, pack, bid_pos."""
        mui = self._find_marketui(player_gui)
        if not mui:
            return []
        cards = self._find_card_frames(mui)
        out = []
        for card in cards:
            data = self._parse_listing_card(card)
            if data["serial"] or data["price"] or data["name"]:
                out.append(data)
        return out


# ---- top-level convenience ---------------------------------------------
def scan_market(mb):
    """Scan the market for all listing cards. Returns list of dicts.
    
    mb: MemoryBackend instance (must be started).
    """
    scanner = MemMarketScanner(mb.r)
    pg = mb.player_gui
    if not pg:
        return []
    return scanner.scan_listings(pg)


if __name__ == "__main__":
    import memory_backend
    mb = memory_backend.MemoryBackend()
    mb.start()
    listings = scan_market(mb)
    print(f"Found {len(listings)} listing cards:")
    for l in listings:
        print(f"  {str(l['name'])[:20]:20s} | serial={str(l['serial']):>4s} | "
              f"price={str(l['price']):10s} | pack={str(l['pack']):10s} | "
              f"earnings={str(l['earnings']):12s} | grade={str(l['grade']):>2s} | "
              f"bid={l['bid_pos']}")
    mb.close()
