"""Optional hook for post_daily.py: hands the reel the newest daily music clip.

Returns the path of music/output/latest/gravitas_7s.mp3 when it exists and was made for
the reel's date or up to MAX_AGE_DAYS before it. Otherwise returns None, and the reel
keeps its coded track. This never posts or schedules anything.
"""

import datetime as dt
import json
from pathlib import Path

LATEST = Path(__file__).resolve().parent / "output" / "latest"
MAX_AGE_DAYS = 2


def latest_clip(day):
    clip, meta = LATEST / "gravitas_7s.mp3", LATEST / "meta.json"
    if not (clip.exists() and meta.exists()):
        return None
    made = dt.date.fromisoformat(json.loads(meta.read_text())["date"])
    if not 0 <= (day - made).days <= MAX_AGE_DAYS:
        return None
    return clip, made
