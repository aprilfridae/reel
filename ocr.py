"""Read text off the screen with Windows' built-in OCR (no extra install besides the
winrt-* pip packages)."""
import asyncio

import cv2
import numpy as np
from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = OcrEngine.try_create_from_user_profile_languages()
        if _engine is None:
            raise RuntimeError("Windows OCR isn't available (no OCR language installed).")
    return _engine


async def _recognize(bitmap):
    return await _get_engine().recognize_async(bitmap)


def _ocr(img, scale):
    if scale != 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    bgra = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    h, w = bgra.shape[:2]
    writer = DataWriter()
    writer.write_bytes(np.ascontiguousarray(bgra).tobytes())
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED)
    return asyncio.run(_recognize(bitmap))


def read_text(img, scale=3):
    """Text in a BGR image region. Small game text reads much better enlarged."""
    return " ".join(line.text for line in _ocr(img, scale).lines)


def read_lines(img, scale=2):
    """Each line of text, top to bottom."""
    return [line.text for line in _ocr(img, scale).lines]


def read_rows(img, scale=2, tolerance=6):
    """Text grouped by screen row, top to bottom. Unlike read_lines, words in
    different colors on the same row (a chat name and its message) stay together."""
    rows = []
    for text, x, y in sorted(read_words(img, scale), key=lambda w: w[2]):
        if rows and abs(rows[-1][0] - y) <= tolerance:
            rows[-1][1].append((x, text))
        else:
            rows.append([y, [(x, text)]])
    return [" ".join(t for _, t in sorted(words)) for _, words in rows]


def read_words(img, scale=2):
    """Every word with its center in img's pixels: [(text, x, y)]."""
    out = []
    for line in _ocr(img, scale).lines:
        for word in line.words:
            r = word.bounding_rect
            out.append((word.text, (r.x + r.width / 2) / scale, (r.y + r.height / 2) / scale))
    return out
