#!/usr/bin/env python3
"""GRAVITAS daily poster.

Picks the day's Base practice from the published library, draws a dark
1080x1350 card, and schedules it on every connected Buffer channel.

  python post_daily.py render     # writes cards/YYYY-MM-DD.jpg and cards/YYYY-MM-DD.json
  python post_daily.py publish    # schedules that card on Buffer, writes posted/YYYY-MM-DD.json
  python post_daily.py preview    # prints the practice and every caption, sends nothing

Settings come from environment variables (see README.md).
"""
import csv
import hashlib
import datetime as dt
import io
import json
import os
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
CARDS = ROOT / "cards"
POSTED = ROOT / "posted"
FONTS = ROOT / "fonts"

TZ = ZoneInfo(os.environ.get("POST_TZ", "America/New_York"))
POST_TIME = os.environ.get("POST_TIME", "07:00")
BUFFER_URL = os.environ.get("BUFFER_URL", "https://api.buffer.com")

# Base rotation settings, copied from DailyPlanner.swift.
PILLARS = [p.strip() for p in os.environ.get("BASE_PILLAR_ORDER", "Confidence,Character,Respect").split(",")]
BASE_EPOCH = dt.date.fromisoformat(os.environ.get("BASE_EPOCH", "2026-01-01"))
BASE_SEED = int(os.environ.get("BASE_SEED", "0x6761766974617321"), 0)

# Extra posts: one per Focus area, AREA_GAP_HOURS apart after the main post.
AREA_ORDER = [a.strip() for a in os.environ.get(
    "AREA_ORDER",
    "Habits and Discipline,Relationships and Friendships,Career and Leadership,Calm and Mindset,Fitness and Health",
).split(",") if a.strip()]
AREA_POSTS = os.environ.get("AREA_POSTS", "true").lower() != "false"
# Which networks get the area posts. Instagram keeps one post a day.
AREA_SERVICES = {x.strip() for x in os.environ.get("AREA_SERVICES", "twitter").split(",") if x.strip()}
AREA_GAP_HOURS = float(os.environ.get("AREA_GAP_HOURS", "2"))
# Clock times for the five area posts, in AREA_ORDER. Blank falls back to AREA_GAP_HOURS spacing.
AREA_TIMES = [t.strip() for t in os.environ.get("AREA_TIMES", "09:00,12:00,15:00,18:00,21:00").split(",") if t.strip()]
# A daily Instagram reel of one focus post, rotating through the areas by day.
REEL_POST = os.environ.get("REEL_POST", "true").lower() != "false"
REEL_TIME = os.environ.get("REEL_TIME", "19:00")
REEL_SECONDS = int(os.environ.get("REEL_SECONDS", "7"))

# Also post the main practice to the Instagram Story at the same time.
STORY_POST = os.environ.get("STORY_POST", "true").lower() != "false"
# Instagram feed posts go out as videos with music: the 10:00 post becomes a reel, and the
# 15:00 reel uses a different clip. The Story stays a still image. Other networks keep the card.
INSTAGRAM_AUDIO = os.environ.get("INSTAGRAM_AUDIO", "true").lower() != "false"
# Instagram look (ig_design.py): hook-first motion reels, a restyled Story card, and a daily
# carousel. IG_DESIGN=false brings back the plain card on Instagram. X and LinkedIn never change.
IG_DESIGN = os.environ.get("IG_DESIGN", "true").lower() != "false"
CAROUSEL_POST = os.environ.get("CAROUSEL_POST", "true").lower() != "false"
CAROUSEL_TIME = os.environ.get("CAROUSEL_TIME", "12:00")
# Short focus names for the card, as the app shows them.
AREA_SHORT = {
    "habits and discipline": "Habits",
    "relationships and friendships": "Relationships",
    "career and leadership": "Career",
    "calm and mindset": "Calm",
    "fitness and health": "Fitness",
}

# Services that get the caption only, no card image.
TEXT_ONLY = {x.strip() for x in os.environ.get("TEXT_ONLY_SERVICES", "twitter").split(",") if x.strip()}



# ---------- library ----------

def load_library():
    url = os.environ.get("LIBRARY_CSV_URL", "").strip()
    path = os.environ.get("LIBRARY_CSV_PATH", "").strip()
    if url:
        req = urllib.request.Request(url, headers={"User-Agent": "gravitas-poster"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8-sig")
    elif path:
        text = Path(path).read_text(encoding="utf-8-sig")
    else:
        sys.exit("Set LIBRARY_CSV_URL (published library_publish CSV) or LIBRARY_CSV_PATH.")
    # Keep a copy of what was read, so a mismatch with the app can be checked later.
    CARDS.mkdir(parents=True, exist_ok=True)
    (CARDS / "library_latest.csv").write_text(text, encoding="utf-8")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if row.get("status") and row["status"].lower() != "approved":
            continue
        if row.get("practice") and row.get("pillar"):
            rows.append(row)
    if not rows:
        sys.exit("Library is empty. Check the CSV link and that rows are approved.")
    counts = {}
    for r in rows:
        counts[r["pillar"]] = counts.get(r["pillar"], 0) + 1
    print(f"Library: {len(rows)} rows, by pillar {counts}")
    return rows


# ---------- Base pick (port of DailyPlanner) ----------

MASK = (1 << 64) - 1


class SplitMix64:
    def __init__(self, seed):
        self.state = seed & MASK

    def next(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)


def stable_hash(text):
    """FNV-1a 64-bit over UTF-8, same as DailyPlanner.stableHash."""
    h = 0xCBF29CE484222325
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 0x100000001B3) & MASK
    return h


def day_index(day):
    return max(0, (day - BASE_EPOCH).days)


def random_below(rng, upper):
    """Swift's RandomNumberGenerator.next(upperBound:) (Lemire's method)."""
    product = rng.next() * upper
    if (product & MASK) < upper:
        t = ((1 << 64) - upper) % upper
        while (product & MASK) < t:
            product = rng.next() * upper
    return product >> 64


def swift_shuffle(items, rng):
    """Swift's MutableCollection.shuffle(using:), a forward Fisher-Yates."""
    amount, i = len(items), 0
    while amount > 1:
        j = i + random_below(rng, amount)
        amount -= 1
        items[i], items[j] = items[j], items[i]
        i += 1


def pick_base(rows, day):
    """Port of DailyPlanner.computeBaseItem(for:)."""
    idx = day_index(day)
    pillar = PILLARS[idx % len(PILLARS)]
    pool = [r for r in rows if r["pillar"].lower() == pillar.lower()]
    fallback = not pool
    if fallback:
        pool = list(rows)
    pool.sort(key=lambda r: r.get("id", ""))
    swift_shuffle(pool, SplitMix64(BASE_SEED ^ stable_hash("fallback" if fallback else pillar)))
    step = idx if fallback else idx // 3
    return pool[step % len(pool)], idx


def pick_area(rows, day, area, pillar, avoid_id=""):
    """The Base rule run inside one area, for the given pillar."""
    idx = day_index(day)
    in_area = [r for r in rows if r.get("area", "").lower() == area.lower()]
    if not in_area:
        return None
    pool = [r for r in in_area if r["pillar"].lower() == pillar.lower()] or in_area
    pool.sort(key=lambda r: r.get("id", ""))
    swift_shuffle(pool, SplitMix64(BASE_SEED ^ stable_hash(f"{pillar}|{area}")))
    pick = pool[(idx // 3) % len(pool)]
    if pick.get("id") == avoid_id and len(pool) > 1:
        pick = pool[(idx // 3 + 1) % len(pool)]
    return pick


def day_slots(rows, day):
    """Every post for the day: the main Base post, then one per area."""
    base, idx = pick_base(rows, day)
    slots = [{"key": "base", "area": "", "offset_hours": 0, "practice": base}]
    if STORY_POST:
        slots.append({"key": "story", "area": "", "offset_hours": 0, "practice": base, "story": True})
    if AREA_POSTS:
        for n, area in enumerate(AREA_ORDER, start=1):
            # Each later post moves to the next pillar, so the day mixes all three.
            pillar = PILLARS[(idx + n) % len(PILLARS)]
            practice = pick_area(rows, day, area, pillar, base.get("id", ""))
            if practice:
                slots.append({"key": f"area{n}", "area": area,
                              "offset_hours": area_offset(n), "practice": practice})
    if REEL_POST and AREA_ORDER:
        # Same pick as that area's X post, so the reel and the post agree.
        n = idx % len(AREA_ORDER) + 1
        area = AREA_ORDER[n - 1]
        practice = pick_area(rows, day, area, PILLARS[(idx + n) % len(PILLARS)], base.get("id", ""))
        if practice:
            slots.append({"key": "reel", "area": area, "offset_hours": hours_after_post(REEL_TIME),
                          "practice": practice, "tall": True})
    if IG_DESIGN and CAROUSEL_POST and AREA_ORDER:
        # A different area from the reel and the Base post, with the same pick as that area's X post.
        taken = {s["area"].lower() for s in slots if s["key"] == "reel"} | {base.get("area", "").lower()}
        order = [(idx + 2 + k) % len(AREA_ORDER) + 1 for k in range(len(AREA_ORDER))]
        n = next((m for m in order if AREA_ORDER[m - 1].lower() not in taken), order[0])
        area = AREA_ORDER[n - 1]
        practice = pick_area(rows, day, area, PILLARS[(idx + n) % len(PILLARS)], base.get("id", ""))
        if practice:
            slots.append({"key": "carousel", "area": area, "offset_hours": hours_after_post(CAROUSEL_TIME),
                          "practice": practice})
    return slots, idx


def area_offset(n):
    """Hours after POST_TIME for area post n (1 to 5)."""
    if len(AREA_TIMES) >= n:
        return hours_after_post(AREA_TIMES[n - 1])
    return n * AREA_GAP_HOURS


def hours_after_post(clock):
    hh, mm = (int(x) for x in clock.split(":"))
    ph, pm = (int(x) for x in POST_TIME.split(":"))
    return (hh * 60 + mm - ph * 60 - pm) / 60


# ---------- captions ----------

def sentence(text):
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def build_captions(practice, day_no, area_post=False):
    templates = json.loads((ROOT / "captions.json").read_text())
    link = os.environ.get("APP_LINK", "").strip()
    fields = {
        "practice": practice["practice"].rstrip(". "),
        "why": sentence(practice.get("why", "")),
        "area": practice.get("area", ""),
        "pillar": practice.get("pillar", "").upper(),
        "link": f"\n\n{link}" if link else "",
    }
    out = {}
    for service, variants in templates.items():
        if (service.startswith("_") and service != "_default") or service.endswith("_area"):
            continue
        if area_post and f"{service}_area" in templates:
            variants = templates[f"{service}_area"]
        text = variants[day_no % len(variants)].format(**fields)
        out[service] = text.strip()
    return out


# ---------- card ----------

def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def wrap(draw, text, fnt, width):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if draw.textlength(trial, font=fnt) <= width:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def spaced(draw, xy, text, fnt, fill, tracking):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + tracking
    return x


def spaced_width(draw, text, fnt, tracking):
    return sum(draw.textlength(c, font=fnt) for c in text) + tracking * (len(text) - 1)


def render_card(practice, day, out_path, subtitle="", story=False):
    """Black 4:5 card in the gravitas_ccr Instagram style."""
    # Feed cards are 4:5. Story cards are 9:16 with the brand kept clear of the Story bar.
    W, H = (1080, 1920) if story else (1080, 1350)
    white, grey, dim = (255, 255, 255), (150, 150, 150), (140, 140, 140)

    img = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    brand_f = font("Inter-Bold.otf", 22)
    date_f = font("Inter-Medium.otf", 20)
    pillar_f = font("Inter-Bold.otf", 38)
    practice_f = font("Inter-SemiBold.otf", 46)
    why_f = font("Inter-Italic.otf", 31)

    max_w = 940
    # Focus cards show the practice without a closing period, like the app's share card.
    text = practice["practice"].rstrip(". ") if subtitle else sentence(practice["practice"])
    lines = wrap(draw, text, practice_f, max_w)
    why_lines = wrap(draw, sentence(practice.get("why", "")), why_f, max_w) if practice.get("why") else []
    date = day.strftime("%B %-d, %Y").upper()
    pillar = f"BUILD {practice['pillar'].upper()}"
    if subtitle:
        pillar = f"{pillar} \u00b7 {subtitle.upper()}"

    # The block is left-aligned text, centered as a whole on the card.
    widths = [draw.textlength(l, font=practice_f) for l in lines]
    widths += [draw.textlength(l, font=why_f) for l in why_lines]
    widths += [spaced_width(draw, pillar, pillar_f, 4), spaced_width(draw, date, date_f, 3)]
    x = (W - max(widths)) // 2

    line_h, why_h = 70, 40
    block_h = 26 + 22 + 48 + 24 + len(lines) * line_h + (14 + len(why_lines) * why_h if why_lines else 0)
    y = int(H * (0.5 if story else 0.53) - block_h / 2)

    spaced(draw, (x, 250 if story else 70), "GRAVITAS", brand_f, white, 5)
    spaced(draw, (x, y), date, date_f, dim, 3)
    y += 26 + 22
    spaced(draw, (x, y), pillar, pillar_f, white, 4)
    y += 48 + 24
    for line in lines:
        draw.text((x, y), line, font=practice_f, fill=white)
        y += line_h
    if why_lines:
        y += 14
        for line in why_lines:
            draw.text((x, y), line, font=why_f, fill=grey)
            y += why_h

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=92, optimize=True, progressive=False)


MUSIC_USED = CARDS / "music_used.json"
# A manual run can skip the daily AI clips and compose fresh tracks instead.
MUSIC_FRESH = os.environ.get("MUSIC_FRESH", "").lower() == "true"


def claim_clip(made, track_id, use):
    """Each daily clip goes on one post only. Returns False when another post already used it."""
    used = json.loads(MUSIC_USED.read_text()) if MUSIC_USED.exists() else {}
    key = f"{made}:{track_id}"
    if used.get(key, use) != use:
        print(f"Daily music clip {key} already went out with {used[key]}, composing a new track.")
        return False
    used[key] = use
    MUSIC_USED.write_text(json.dumps(used, indent=2, sort_keys=True))
    return True


def reel_track(day, track_id="a", use=""):
    """The daily AI clip, or a track composed for this date (music.py).
    track_id "a" is the day's best clip and "b" the runner-up, so the day's two videos differ.
    use names the post (date and slot), so no clip is ever posted twice."""
    found = None if MUSIC_FRESH else reel_music_from_latest(day, track_id)
    if found and claim_clip(found[1], track_id, use or f"{day}:{track_id}"):
        return found[0]
    import music
    track = CARDS / f"_music_{track_id}.wav"
    # Track "b" composes from a shifted date so it never matches track "a".
    seed_day = day if track_id == "a" else day + dt.timedelta(days=500)
    print(f"Composed reel track: {music.compose(seed_day, REEL_SECONDS, track)}")
    return track


def ffmpeg_exe():
    try:
        import imageio_ffmpeg  # bundled ffmpeg, since GitHub's runner has none
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def make_motion_reel(practice, day, out_path, focus, track_id="a", use=""):
    """The Instagram reel: hook, then the practice and why, then a share prompt (ig_design.py)."""
    import ig_design
    track = reel_track(day, track_id, use)
    ig_design.motion_reel(practice, day, out_path, track, REEL_SECONDS, ffmpeg_exe(), focus)
    if track.parent == CARDS:
        track.unlink(missing_ok=True)


def make_reel(image_path, out_path, day, track_id="a", use=""):
    """A short still-card video with the day's music."""
    track = reel_track(day, track_id, use)
    audio = ["-i", str(track)]
    exe = ffmpeg_exe()
    cmd = [exe, "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(image_path), *audio,
           "-t", str(REEL_SECONDS), "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "medium",
           "-crf", "20", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out_path)]
    subprocess.run(cmd, check=True)
    if track.parent == CARDS:
        track.unlink(missing_ok=True)


# Optional: put the daily clip from the Daily music workflow (music/) under the reel.
# Turn off with the repository variable REEL_MUSIC_FROM_LATEST=false.
def reel_music_from_latest(day, track_id="a"):
    if os.environ.get("REEL_MUSIC_FROM_LATEST", "true").lower() == "false":
        return None
    sys.path.insert(0, str(ROOT / "music"))
    from reel_audio import latest_clip
    found = latest_clip(day, track_id)
    if not found:
        print("No recent daily music clip, composing the reel track instead.")
        return None
    clip, made = found
    print(f"Reel track: daily music clip {track_id} from {made}")
    return clip, made


# ---------- Buffer ----------

def buffer_call(query, variables=None):
    key = os.environ.get("BUFFER_API_KEY", "").strip()
    if not key:
        sys.exit("Set BUFFER_API_KEY.")
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(BUFFER_URL, data=body, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "gravitas-poster",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Buffer HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")
    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"])[:800])
    return data["data"]


def buffer_channels():
    org = os.environ.get("BUFFER_ORG_ID", "").strip()
    if not org:
        orgs = buffer_call("query { account { organizations { id name } } }")["account"]["organizations"]
        org = orgs[0]["id"]
    chans = buffer_call(
        "query($org: OrganizationId!) { channels(input: {organizationId: $org}) { id name service } }",
        {"org": org},
    )["channels"]
    only = {s.strip() for s in os.environ.get("BUFFER_SERVICES", "").split(",") if s.strip()}
    return [c for c in chans if not only or c["service"] in only]


CREATE = """
mutation($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}"""


def create_post(channel, text, image_url, due_at, story=False, video_url="", image_urls=None):
    base = {
        "channelId": channel["id"],
        "text": text,
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due_at,
    }
    if image_urls:
        # Several images on one Instagram post make a carousel.
        base["assets"] = [{"image": {"url": u}} for u in image_urls]
        base["metadata"] = {"instagram": {"type": "post", "shouldShareToFeed": True}}
        return send_post([base])
    if video_url:
        base["assets"] = [{"video": {"url": video_url}}]
        if story:
            # Stories publish automatically only with no caption, stickers, or links.
            base["text"] = ""
            base["metadata"] = {"instagram": {"type": "story", "shouldShareToFeed": False}}
        else:
            base["metadata"] = {"instagram": {"type": "reel", "shouldShareToFeed": True}}
        attempts = [base]
        if IG_DESIGN and not story:
            # Cover frame one second in, where the hook has settled. Plain video if Buffer refuses it.
            cover = {"video": {"url": video_url, "metadata": {"thumbnailOffset": 1000}}}
            attempts.insert(0, {**base, "assets": [cover]})
        return send_post(attempts)
    if channel["service"] not in TEXT_ONLY:
        base["assets"] = [{"image": {"url": image_url}}]
    if story:
        # Stories publish automatically only with no caption, stickers, or links.
        base["text"] = ""
        base["metadata"] = {"instagram": {"type": "story", "shouldShareToFeed": False}}
        attempts = [base]
    else:
        attempts = [base]
    if channel["service"] == "instagram" and not story:
        attempts.insert(0, {**base, "metadata": {"instagram": {"type": "post", "shouldShareToFeed": True}}})
    return send_post(attempts)


def send_post(attempts):
    last = None
    for payload in attempts:
        try:
            res = buffer_call(CREATE, {"input": payload})["createPost"]
        except RuntimeError as e:
            last = str(e)
            continue
        if res.get("post"):
            return res["post"]
        last = res.get("message", "unknown error")
    raise RuntimeError(last)


def due_at_iso(day, offset_hours=0):
    hh, mm = (int(x) for x in POST_TIME.split(":"))
    local = dt.datetime.combine(day, dt.time(hh, mm), TZ) + dt.timedelta(hours=offset_hours)
    soonest = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
    when = max(local.astimezone(dt.timezone.utc), soonest)
    return when.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def video_link(name, base_url):
    """Raw GitHub sends videos as application/octet-stream, so serve them through
    jsDelivr at the exact commit, which sends video/mp4 and never goes stale."""
    override = os.environ.get("VIDEO_BASE_URL", "").rstrip("/")
    if override:
        return f"{override}/{name}"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if sha:
            return f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/cards/{name}"
    return f"{base_url}/{name}"


def wait_for_url(url, tries=20):
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "gravitas-poster"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200 and r.headers.get("Content-Type", "").split("/")[0] in ("image", "video"):
                    return
        except Exception:
            pass
        time.sleep(15)
    sys.exit(f"Card image is not reachable yet: {url}")


# ---------- commands ----------

def target_day():
    override = os.environ.get("POST_DATE", "").strip()
    return dt.date.fromisoformat(override) if override else dt.datetime.now(TZ).date()


def short_area(practice):
    area = practice.get("area", "")
    return AREA_SHORT.get(area.lower(), area)


def cmd_render():
    day = target_day()
    stem = day.isoformat()
    slots, idx = day_slots(load_library(), day)
    keep = set()
    for slot in slots:
        tmp = CARDS / "_render.jpg"
        tall = slot.get("story", False) or slot.get("tall", False)
        focus = AREA_SHORT.get(slot["area"].lower(), slot["area"])
        if IG_DESIGN and slot["key"] in ("story", "reel"):
            import ig_design
            ig_design.story_card(slot["practice"], day, tmp, short_area(slot["practice"]))
        elif IG_DESIGN and slot["key"] == "carousel":
            import ig_design
            slides = ig_design.carousel(slot["practice"], day, focus)
            slides[0].save(tmp, "JPEG", quality=92, optimize=True)
        else:
            render_card(slot["practice"], day, tmp, focus, tall)
        # A new file name whenever the card changes, so no cached old image gets posted.
        digest = hashlib.sha1(tmp.read_bytes()).hexdigest()[:8]
        suffix = "" if slot["key"] == "base" else f"-{slot['key']}"
        slot["image"] = f"{stem}{suffix}-{digest}.jpg"
        tmp.rename(CARDS / slot["image"])
        keep.add(slot["image"])
        if slot["key"] == "carousel":
            slot["images"] = [slot["image"]]
            for n, img in enumerate(slides[1:], start=2):
                name = f"{stem}-carousel{n}-{digest}.jpg"
                img.save(CARDS / name, "JPEG", quality=92, optimize=True)
                slot["images"].append(name)
                keep.add(name)
        if slot["key"] == "reel":
            slot["video"] = f"{stem}-reel-{digest}.mp4"
            track_id = "b" if INSTAGRAM_AUDIO else "a"
            if IG_DESIGN:
                make_motion_reel(slot["practice"], day, CARDS / slot["video"], focus, track_id, f"{stem}:reel")
            else:
                make_reel(CARDS / slot["image"], CARDS / slot["video"], day, track_id, f"{stem}:reel")
            keep.add(slot["video"])
        slot["captions"] = build_captions(slot["practice"], idx, slot["key"] != "base")
        print(f"Rendered {stem} {slot['key']}: {slot['practice'].get('id', '')} {slot['practice']['practice']}")
    if INSTAGRAM_AUDIO:
        # A tall video of the Base card for the 10:00 Instagram reel (the Story stays a still image).
        base = next(s for s in slots if s["key"] == "base")
        story = next((s for s in slots if s["key"] == "story"), None)
        if story:
            tall_image = CARDS / story["image"]
        else:
            tall_image = CARDS / "_render.jpg"
            render_card(base["practice"], day, tall_image, "", True)
        digest = hashlib.sha1(tall_image.read_bytes()).hexdigest()[:8]
        base["ig_video"] = f"{stem}-ig-{digest}.mp4"
        if IG_DESIGN:
            make_motion_reel(base["practice"], day, CARDS / base["ig_video"], short_area(base["practice"]), "a",
                             f"{stem}:base")
        else:
            make_reel(tall_image, CARDS / base["ig_video"], day, "a", f"{stem}:base")
        keep.add(base["ig_video"])
        tall_image.with_name("_render.jpg").unlink(missing_ok=True)
    for old in [*CARDS.glob(f"{stem}*.jpg"), *CARDS.glob(f"{stem}*.mp4")]:
        if old.name not in keep:
            old.unlink()
    meta = {"date": stem, "day_index": idx, "slots": slots}
    (CARDS / f"{stem}.json").write_text(json.dumps(meta, indent=2))


def cmd_preview():
    day = target_day()
    slots, idx = day_slots(load_library(), day)
    print(f"{day} day {idx}")
    for slot in slots:
        p = slot["practice"]
        print(f"\n=== {slot['key']} +{slot['offset_hours']:g}h {slot['area'] or 'Base'}: {p.get('id', '')} ({p['pillar']})")
        for service, text in build_captions(p, idx, slot["key"] != "base").items():
            if service in ("instagram", "twitter"):
                print(f"--- {service} ---\n{text}")
        render_card(p, day, CARDS / f"preview-{slot['key']}.jpg", AREA_SHORT.get(slot["area"].lower(), slot["area"]),
                    slot.get("story", False) or slot.get("tall", False))


def cmd_publish():
    day = target_day()
    stem = day.isoformat()
    marker = POSTED / f"{stem}.json"
    redo = os.environ.get("REDO", "").lower() == "true"
    previous = json.loads(marker.read_text())["results"] if marker.exists() else {}
    done = {} if redo else previous
    # ONLY_SLOTS limits a manual run to some posts, for example base,story,carousel.
    only = {x.strip() for x in os.environ.get("ONLY_SLOTS", "").split(",") if x.strip()}
    meta = json.loads((CARDS / f"{stem}.json").read_text())
    base_url = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")
    if not base_url:
        sys.exit("Set IMAGE_BASE_URL.")

    channels = buffer_channels()
    results, failed = {}, []
    for slot in meta["slots"]:
        if only and slot["key"] not in only:
            continue
        image_url = f"{base_url}/{slot['image']}"
        wait_for_url(image_url)
        for name in {slot.get("video"), slot.get("ig_video")} - {None}:
            wait_for_url(video_link(name, base_url))
        for name in slot.get("images", [])[1:]:
            wait_for_url(f"{base_url}/{name}")
        due = due_at_iso(day, slot["offset_hours"])
        for ch in channels:
            if (slot.get("story") or slot["key"] in ("reel", "carousel")) and ch["service"] != "instagram":
                continue
            if slot["key"].startswith("area") and ch["service"] not in AREA_SERVICES:
                continue
            # The main post keeps the plain service name so older records still count.
            key = ch["service"] if slot["key"] == "base" else f"{slot['key']}:{ch['service']}"
            if done.get(key, {}).get("post_id"):
                results[key] = done[key]
                print(f"Already scheduled {key}, skipping.")
                continue
            text = slot["captions"].get(ch["service"]) or slot["captions"]["_default"]
            try:
                video = slot.get("video") or (slot.get("ig_video") if ch["service"] == "instagram" else "")
                video_url = video_link(video, base_url) if video else ""
                image_urls = [f"{base_url}/{n}" for n in slot.get("images", [])]
                post = create_post(ch, text, image_url, due, slot.get("story", False), video_url, image_urls)
                results[key] = {"channel": ch["name"], "post_id": post["id"], "due_at": post.get("dueAt")}
                print(f"Scheduled {key} ({ch['name']}) for {due}")
            except RuntimeError as e:
                if "already got this one scheduled or posted" in str(e):
                    # Buffer refuses exact repeats, so this one is already queued or out.
                    results[key] = {"channel": ch["name"], "skipped": "duplicate in Buffer"}
                    print(f"Already in Buffer {key}, skipping.")
                    continue
                failed.append(key)
                results[key] = {"channel": ch["name"], "error": str(e)}
                print(f"FAILED {key} ({ch['name']}): {e}")

    POSTED.mkdir(exist_ok=True)
    # Keep the records of posts this run did not touch.
    marker.write_text(json.dumps({"date": stem, "results": {**previous, **results}}, indent=2))
    if failed:
        sys.exit(f"Some posts failed: {', '.join(failed)}")


if __name__ == "__main__":
    cmds = {"render": cmd_render, "publish": cmd_publish, "preview": cmd_preview}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
