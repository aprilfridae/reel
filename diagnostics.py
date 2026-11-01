"""Sends the fishing diagnostics (reel_log.csv from this run + one reel screenshot) to the developer.

Once per run, right after the first reels have been recorded (fisher.LOG_FIRST_REELS). The destination is a
Discord webhook whose URL is read from diag_webhook.txt, bundled into the .exe at build time (it is
not in the source repo); without that file nothing is sent. Turn it off with "send_diagnostics": false
in config.json. What is sent is printed.
"""
import json
import os
import platform
import threading
import urllib.request
import uuid

from paths import APP, RES
from version import VERSION

NOTICE = ("Diagnostics: after the first few reels, reel_log.csv and one screenshot of the game window are sent "
          "to the developer to help tune the fishing (turn off: \"send_diagnostics\": false in config.json).")


def webhook_url():
    for base in (APP, RES):
        try:
            url = open(os.path.join(base, "diag_webhook.txt")).read().strip()
            if url.startswith("https://discord.com/api/webhooks/"):
                return url
        except OSError:
            pass
    return None


def _multipart(fields, files):
    boundary = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    for i, (name, data) in enumerate(files):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[{i}]\"; filename=\"{name}\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def send(url, summary, files, timeout=30):
    body, ctype = _multipart({"payload_json": json.dumps({"content": summary[:1900]})}, files)
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype, "User-Agent": "UndergroundBot-diag"})
    urllib.request.urlopen(req, timeout=timeout).read()


def ping(extra, log=print):
    """Background: a one-line "started" message, so it's known this PC runs this build and can reach
    the channel even before any reel has been recorded. Never raises."""
    def work():
        try:
            url = webhook_url()
            if url:
                send(url, f"started, UndergroundBot {VERSION}\n{platform.platform()} / {platform.processor()}\n{extra}", [])
        except Exception as e:
            log(f"(couldn't reach the diagnostics channel: {type(e).__name__}: {e})")
    threading.Thread(target=work, daemon=True).start()


def upload_fishing(csv_path, csv_start, sample_path, extra="", log=print):
    """Background: this run's rows of the reel log + the sample screenshot. Never raises."""
    def work():
        try:
            url = webhook_url()
            if not url:
                return
            with open(csv_path, "rb") as f:
                head = f.readline()
                f.seek(csv_start)
                rows = f.read(400_000)
            files = [("reel_log.csv", head + rows)]
            if os.path.exists(sample_path):
                with open(sample_path, "rb") as f:
                    files.append(("reel_sample.jpg", f.read()))
            summary = (f"fishing diagnostics, UndergroundBot {VERSION}\n{platform.platform()} / {platform.processor()}\n"
                       f"{extra}")
            send(url, summary, files)
            log(f"Sent fishing diagnostics ({', '.join(n for n, _ in files)})")
        except Exception as e:
            log(f"(couldn't send diagnostics: {type(e).__name__}: {e})")
    threading.Thread(target=work, daemon=True).start()
