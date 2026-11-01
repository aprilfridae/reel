"""Dev preview: serves web/index.next.html (else web/index.html) with fixture data. Not shipped.
  python tools/web_preview/serve.py [full|empty]   ->  http://127.0.0.1:8099/
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import webstate  # noqa: E402
from flask import send_file  # noqa: E402
from web.app import app  # noqa: E402

fixture = sys.argv[1] if len(sys.argv) > 1 else "full"
src = os.path.join(HERE, "fixtures", fixture)
if not os.path.isdir(src):
    sys.exit(f"no fixture set {fixture!r} (use full or empty)")
tmp = tempfile.mkdtemp(prefix="web_preview_")
shutil.copytree(src, tmp, dirs_exist_ok=True)
webstate.DATA = tmp  # path() reads this global, so all reads/writes go to the copy

now = time.time()
for name, key in (("market.json", "cards"), ("mybids.json", "items")):  # relative seconds -> absolute end times
    data = webstate.load(name, None)
    if not data:
        continue
    for it in data.get(key, []):
        if "ends_in" in it:
            it["ends_ts"] = now + it.pop("ends_in")
    webstate.save(name, data)

app.static_folder = os.path.join(HERE, "fixtures", "static")
_next = os.path.join(ROOT, "web", "index.next.html")
_page = _next if os.path.exists(_next) else os.path.join(ROOT, "web", "index.html")
app.view_functions["index"] = lambda: send_file(_page, max_age=0)

if __name__ == "__main__":
    print(f"serving {fixture} fixtures from {tmp}")
    app.run(host="127.0.0.1", port=8099)
