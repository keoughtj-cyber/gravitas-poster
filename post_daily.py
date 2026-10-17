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
import datetime as dt
import io
import json
import os
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
POST_TIME = os.environ.get("POST_TIME", "07:30")
BUFFER_URL = os.environ.get("BUFFER_URL", "https://api.buffer.com")

# Base rotation settings, copied from DailyPlanner.swift.
PILLARS = [p.strip() for p in os.environ.get("BASE_PILLAR_ORDER", "Confidence,Character,Respect").split(",")]
BASE_EPOCH = dt.date.fromisoformat(os.environ.get("BASE_EPOCH", "2026-01-01"))
BASE_SEED = int(os.environ.get("BASE_SEED", "0x6761766974617321"), 0)

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


# ---------- captions ----------

def sentence(text):
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def build_captions(practice, day_no):
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
        if service.startswith("_") and service != "_default":
            continue
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


def render_card(practice, day, out_path):
    """Black 4:5 card in the gravitas_ccr Instagram style."""
    W, H = 1080, 1350
    white, grey, dim = (255, 255, 255), (150, 150, 150), (140, 140, 140)

    img = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    brand_f = font("Inter-Bold.otf", 22)
    date_f = font("Inter-Medium.otf", 20)
    pillar_f = font("Inter-Bold.otf", 38)
    practice_f = font("Inter-SemiBold.otf", 46)
    why_f = font("Inter-Italic.otf", 31)

    max_w = 940
    lines = wrap(draw, sentence(practice["practice"]), practice_f, max_w)
    why_lines = wrap(draw, sentence(practice.get("why", "")), why_f, max_w) if practice.get("why") else []
    date = day.strftime("%B %-d, %Y").upper()
    pillar = f"BUILD {practice['pillar'].upper()}"

    # The block is left-aligned text, centered as a whole on the card.
    widths = [draw.textlength(l, font=practice_f) for l in lines]
    widths += [draw.textlength(l, font=why_f) for l in why_lines]
    widths += [spaced_width(draw, pillar, pillar_f, 4), spaced_width(draw, date, date_f, 3)]
    x = (W - max(widths)) // 2

    line_h, why_h = 70, 40
    block_h = 26 + 22 + 48 + 24 + len(lines) * line_h + (14 + len(why_lines) * why_h if why_lines else 0)
    y = int(H * 0.53 - block_h / 2)

    spaced(draw, (x, 70), "GRAVITAS", brand_f, white, 5)
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


def create_post(channel, text, image_url, due_at):
    base = {
        "channelId": channel["id"],
        "text": text,
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due_at,
    }
    if channel["service"] not in TEXT_ONLY:
        base["assets"] = [{"image": {"url": image_url}}]
    attempts = [base]
    if channel["service"] == "instagram":
        attempts.insert(0, {**base, "metadata": {"instagram": {"type": "post", "shouldShareToFeed": True}}})
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


def due_at_iso(day):
    hh, mm = (int(x) for x in POST_TIME.split(":"))
    local = dt.datetime.combine(day, dt.time(hh, mm), TZ)
    soonest = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
    when = max(local.astimezone(dt.timezone.utc), soonest)
    return when.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def wait_for_url(url, tries=20):
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "gravitas-poster"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200 and "image" in r.headers.get("Content-Type", ""):
                    return
        except Exception:
            pass
        time.sleep(15)
    sys.exit(f"Card image is not reachable yet: {url}")


# ---------- commands ----------

def target_day():
    override = os.environ.get("POST_DATE", "").strip()
    return dt.date.fromisoformat(override) if override else dt.datetime.now(TZ).date()


def cmd_render():
    day = target_day()
    practice, idx = pick_base(load_library(), day)
    stem = day.isoformat()
    render_card(practice, day, CARDS / f"{stem}.jpg")
    meta = {"date": stem, "day_index": idx, "practice": practice,
            "captions": build_captions(practice, idx)}
    (CARDS / f"{stem}.json").write_text(json.dumps(meta, indent=2))
    print(f"Rendered {stem}: {practice.get('id', '')} {practice['practice']}")


def cmd_preview():
    day = target_day()
    practice, idx = pick_base(load_library(), day)
    print(f"{day} day {idx} {practice['pillar']} {practice.get('id', '')}")
    for service, text in build_captions(practice, idx).items():
        print(f"\n--- {service} ({len(text)} chars) ---\n{text}")
    render_card(practice, day, CARDS / "preview.jpg")
    print(f"\nCard: {CARDS / 'preview.jpg'}")


def cmd_publish():
    day = target_day()
    stem = day.isoformat()
    marker = POSTED / f"{stem}.json"
    redo = os.environ.get("REDO", "").lower() == "true"
    done = json.loads(marker.read_text())["results"] if marker.exists() and not redo else {}
    meta = json.loads((CARDS / f"{stem}.json").read_text())
    base = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")
    if not base:
        sys.exit("Set IMAGE_BASE_URL.")
    image_url = f"{base}/{stem}.jpg"
    wait_for_url(image_url)

    due = due_at_iso(day)
    results, failed = {}, []
    for ch in buffer_channels():
        if done.get(ch["service"], {}).get("post_id"):
            results[ch["service"]] = done[ch["service"]]
            print(f"Already scheduled {ch['service']}, skipping.")
            continue
        text = meta["captions"].get(ch["service"]) or meta["captions"]["_default"]
        try:
            post = create_post(ch, text, image_url, due)
            results[ch["service"]] = {"channel": ch["name"], "post_id": post["id"], "due_at": post.get("dueAt")}
            print(f"Scheduled {ch['service']} ({ch['name']}) for {due}")
        except RuntimeError as e:
            failed.append(ch["service"])
            results[ch["service"]] = {"channel": ch["name"], "error": str(e)}
            print(f"FAILED {ch['service']} ({ch['name']}): {e}")

    POSTED.mkdir(exist_ok=True)
    marker.write_text(json.dumps({"date": stem, "image": image_url, "results": results}, indent=2))
    if failed:
        sys.exit(f"Some channels failed: {', '.join(failed)}")


if __name__ == "__main__":
    cmds = {"render": cmd_render, "publish": cmd_publish, "preview": cmd_preview}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
