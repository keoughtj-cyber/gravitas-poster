"""Hands post_daily.py daily music clips that have never been posted.

Each dated folder in music/output/ holds up to three 7-second tracks from one run of
generate.py: a (best), b, and c. Every track is known by its seed in meta.json. A track is
handed out only if its seed is not in the used set the poster keeps, newest folder first,
so no clip goes out twice. This never posts or schedules anything.
"""

import json
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent / "output"
SEED_KEYS = {"a": "chosen_seed", "b": "second_seed", "c": "third_seed"}


def clips():
    """Every saved track as (path, label, seed), newest folder first."""
    for folder in sorted((f for f in OUTPUT.iterdir() if f.is_dir() and f.name[:1].isdigit()), reverse=True):
        meta_path = folder / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        for track, key in SEED_KEYS.items():
            suffix = "" if track == "a" else f"_{track}"
            path = folder / f"gravitas_{folder.name}_7s{suffix}.mp3"
            if meta.get(key) is not None and path.exists():
                yield path, f"{folder.name} {track}", meta[key]


def unused_clip(used_seeds, prefer="a"):
    """The newest track whose seed is not in used_seeds, preferring the given track letter."""
    found = list(clips())
    for path, label, seed in sorted(found, key=lambda c: (c[1].split()[0], c[1].endswith(prefer)), reverse=True):
        if seed not in used_seeds:
            return path, label, seed
    return None


def clip_with_seed(seed):
    return next((c for c in clips() if c[2] == seed), None)
