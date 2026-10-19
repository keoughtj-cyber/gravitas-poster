"""Instagram look for @gravitas_ccr: hook-first motion reels, 4-slide carousels, and a restyled Story card.

Everything renders from a practice row (practice, why, pillar, area) plus the optional hook,
concept, and source in ig_extra.csv. X and LinkedIn keep the plain card in post_daily.py.
"""
import csv
import datetime as dt
import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "fonts"
EXTRA = ROOT / "ig_extra.csv"

# Pillar colors from the app.
COLORS = {"confidence": (212, 168, 67), "character": (79, 157, 122), "respect": (91, 141, 239)}
WHITE, GREY, DIM = (245, 245, 245), (160, 160, 160), (110, 110, 110)
# REP 001 is the first day of this look; the number counts up one a day from there.
REP_START = dt.date.fromisoformat(os.environ.get("IG_REP_START", "2026-10-19"))
MARGIN = 90


# ---------- content ----------

_extra = None


def extra(practice):
    """hook, concept, and source for a practice id, from ig_extra.csv."""
    global _extra
    if _extra is None:
        _extra = {}
        if EXTRA.exists():
            with EXTRA.open(encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    _extra[row["id"].strip()] = {k: (v or "").strip() for k, v in row.items()}
    return _extra.get(practice.get("id", ""), {})


def sentence(text):
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def hook_line(practice):
    """The first frame. A written hook when there is one, otherwise the why."""
    return sentence(practice.get("hook") or extra(practice).get("hook") or practice.get("why") or practice["practice"])


def rep_number(day):
    return max(1, (day - REP_START).days + 1)


def accent(practice):
    return COLORS.get(practice.get("pillar", "").lower(), WHITE)


def kicker(practice, focus):
    text = f"BUILD {practice['pillar'].upper()}"
    return f"{text}  ·  {focus.upper()}" if focus else text


# ---------- drawing helpers ----------

def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def wrap(d, text, fnt, width):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if d.textlength(trial, font=fnt) <= width:
            line = trial
        else:
            lines.append(line)
            line = w
    return lines + ([line] if line else [])


def spaced(d, xy, text, fnt, fill, tracking):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill)
        x += d.textlength(ch, font=fnt) + tracking


def spaced_width(d, text, fnt, tracking):
    return sum(d.textlength(c, font=fnt) for c in text) + tracking * (len(text) - 1)


def lines_at(d, lines, fnt, y, fill, line_h, x=MARGIN):
    for ln in lines:
        d.text((x, y), ln, font=fnt, fill=fill)
        y += line_h
    return y


_backgrounds = {}


def background(w, h, color, seed=7):
    """Near-black with a faint pillar-colored glow, a vignette, and film grain."""
    key = (w, h, color, seed)
    if key not in _backgrounds:
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        r = np.sqrt(((x - w / 2) / w) ** 2 + ((y - h * 0.42) / h) ** 2)
        glow = np.clip(1 - r / 0.6, 0, 1) ** 2.2 * 0.10
        base = np.zeros((h, w, 3), np.float32) + 8
        for i in range(3):
            base[..., i] += glow * color[i]
        base *= np.clip(1 - (r - 0.35) * 0.9, 0.55, 1)[..., None]
        grain = np.random.default_rng(seed).normal(0, 5, (h, w, 1))
        _backgrounds[key] = Image.fromarray(np.clip(base + grain, 0, 255).astype(np.uint8))
    return _backgrounds[key].copy()


def header(d, w, top, day):
    """III mark and GRAVITAS on the left, REP number on the right."""
    bar, x = 5, MARGIN
    for i in range(3):
        d.rectangle([x + i * (bar + 5), top, x + i * (bar + 5) + bar, top + 30], fill=WHITE)
    spaced(d, (x + 3 * bar + 10 + 18, top + 1), "GRAVITAS", font("Inter-Bold.otf", 26), WHITE, 6)
    rep = f"REP {rep_number(day):03d}"
    rf = font("Inter-Medium.otf", 24)
    spaced(d, (w - MARGIN - spaced_width(d, rep, rf, 4), top + 2), rep, rf, DIM, 4)


# ---------- Story card ----------

def story_card(practice, day, out_path, focus=""):
    """9:16 still for the Story, with the header below Instagram's top bar."""
    w, h = 1080, 1920
    color = accent(practice)
    img = background(w, h, color)
    d = ImageDraw.Draw(img)
    header(d, w, 250, day)
    pf, wf, kf = font("Inter-Bold.otf", 76), font("Inter-Italic.otf", 40), font("Inter-Bold.otf", 30)
    lines = wrap(d, practice["practice"].rstrip(". "), pf, w - 2 * MARGIN)
    why = wrap(d, sentence(practice.get("why", "")), wf, w - 2 * MARGIN) if practice.get("why") else []
    y = int(h * 0.5 - (64 + 54 + len(lines) * 92 + 34 + len(why) * 52) / 2)
    spaced(d, (MARGIN, y), kicker(practice, focus), kf, color, 5)
    y += 64
    d.rectangle([MARGIN, y, MARGIN + 80, y + 6], fill=color)
    y += 54
    y = lines_at(d, lines, pf, y, WHITE, 92) + 34
    lines_at(d, why, wf, y, GREY, 52)
    spaced(d, (MARGIN, h - 300), "FOLLOW FOR ONE PRACTICE A DAY", font("Inter-Medium.otf", 24), DIM, 3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=92, optimize=True)


# ---------- carousel ----------

def carousel(practice, day, focus=""):
    """Four 4:5 slides: hook, the practice, why it works, save and send."""
    w, h = 1080, 1350
    color = accent(practice)
    more = extra(practice)
    width = w - 2 * MARGIN
    hf, pf, wf = font("Inter-Bold.otf", 104), font("Inter-Bold.otf", 74), font("Inter-Italic.otf", 42)
    kf, sf = font("Inter-Bold.otf", 30), font("Inter-Medium.otf", 30)
    slides = []

    def slide(n):
        img = background(w, h, color, seed=n)
        d = ImageDraw.Draw(img)
        header(d, w, 90, day)
        page = f"{n} / 4"
        spaced(d, (w - MARGIN - spaced_width(d, page, sf, 3), h - 120), page, sf, DIM, 3)
        return img, d

    img, d = slide(1)
    lines = wrap(d, hook_line(practice), hf, width)
    y = int(h * 0.5 - len(lines) * 122 / 2)
    spaced(d, (MARGIN, y - 80), kicker(practice, focus), kf, color, 5)
    lines_at(d, lines, hf, y, WHITE, 122)
    spaced(d, (MARGIN, h - 120), "SWIPE FOR THE PRACTICE  →", sf, GREY, 3)
    slides.append(img)

    img, d = slide(2)
    lines = wrap(d, practice["practice"].rstrip(". "), pf, width)
    y = int(h * 0.5 - (len(lines) * 92 + 80) / 2)
    spaced(d, (MARGIN, y), "THE PRACTICE", kf, color, 5)
    lines_at(d, lines, pf, y + 80, WHITE, 92)
    slides.append(img)

    img, d = slide(3)
    bf = font("Inter-Bold.otf", 70)
    y = 360
    spaced(d, (MARGIN, y), "WHY IT WORKS", kf, color, 5)
    y = lines_at(d, wrap(d, sentence(practice.get("why", "")), bf, width), bf, y + 80, WHITE, 88) + 50
    d.rectangle([MARGIN, y, MARGIN + 80, y + 6], fill=color)
    y += 50
    if more.get("concept"):
        y = lines_at(d, wrap(d, f"Principle: {sentence(more['concept'])}", wf, width), wf, y, GREY, 56) + 12
    if more.get("source"):
        lines_at(d, wrap(d, f"Source: {sentence(more['source'])}", wf, width), wf, y, GREY, 56)
    slides.append(img)

    img, d = slide(4)
    cf = font("Inter-Bold.otf", 80)
    lines = wrap(d, "Do it once. Then tell us how it went.", cf, width)
    y = lines_at(d, lines, cf, int(h * 0.44 - len(lines) * 98 / 2), WHITE, 98) + 50
    for t in ("Save this for the next time you need it.", "Send it to a friend building the same thing."):
        y = lines_at(d, wrap(d, t, wf, width), wf, y, GREY, 56) + 10
    spaced(d, (MARGIN, y + 40), "FOLLOW @GRAVITAS_CCR", kf, color, 5)
    slides.append(img)
    return slides


# ---------- motion reel ----------

def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def reel_frame(practice, day, t, dur, focus=""):
    """One 9:16 frame. Timings are written for 7 seconds and stretch with the length.
    0 to 2s hook, 2.2 to 5.4s practice and why, 5.6s on the share prompt."""
    w, h = 1080, 1920
    s = t * 7.0 / dur
    color = accent(practice)
    img = background(w, h, color).convert("RGBA")
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    header(d, w, 250, day)
    hf, pf = font("Inter-Bold.otf", 112), font("Inter-Bold.otf", 80)
    wf, kf = font("Inter-Italic.otf", 46), font("Inter-Bold.otf", 32)
    width, cy = w - 2 * MARGIN, 880  # text sits above the caption area at the bottom
    d.rectangle([MARGIN, 320, MARGIN + int(width * min(t / dur, 1)), 324], fill=color + (255,))

    def text(xy, value, fnt, fill, alpha, tracking=0):
        fill = fill + (int(255 * alpha),)
        if tracking:
            x, y = xy
            for ch in value:
                d.text((x, y), ch, font=fnt, fill=fill)
                x += d.textlength(ch, font=fnt) + tracking
        else:
            d.text(xy, value, font=fnt, fill=fill)

    a = 1 - ease((s - 1.9) / 0.35)
    if a > 0:
        lines = wrap(d, hook_line(practice), hf, width)
        y = cy - len(lines) * 132 / 2 + (1 - ease(s / 0.4)) * 30
        for ln in lines:
            text((MARGIN, y), ln, hf, WHITE, a)
            y += 132

    a = ease((s - 2.2) / 0.3) * (1 - ease((s - 5.3) / 0.3))
    if a > 0:
        lines = wrap(d, practice["practice"].rstrip(". "), pf, width)
        y = cy - (90 + len(lines) * 98 + 100) / 2
        text((MARGIN, y), kicker(practice, focus), kf, color, a, 5)
        y += 90
        for i, ln in enumerate(lines):
            ai = ease((s - 2.35 - i * 0.25) / 0.3) * a
            text((MARGIN, y + (1 - ai) * 18), ln, pf, WHITE, ai)
            y += 98
        y += 40
        aw = ease((s - 3.6) / 0.4) * a
        for ln in wrap(d, sentence(practice.get("why", "")), wf, width):
            text((MARGIN, y), ln, wf, GREY, aw)
            y += 58

    a = ease((s - 5.6) / 0.3)
    if a > 0:
        lines = wrap(d, "Send this to a friend who needs it.", pf, width)
        y = cy - (len(lines) * 98 + 100) / 2
        for ln in lines:
            text((MARGIN, y), ln, pf, WHITE, a)
            y += 98
        text((MARGIN, y + 40), "FOLLOW @GRAVITAS_CCR", kf, color, a, 5)

    img = Image.alpha_composite(img, layer)
    # A slow push-in, so no frame is ever fully still.
    z = 1 + 0.035 * (t / dur)
    zw, zh = int(w / z), int(h / z)
    img = img.crop(((w - zw) // 2, (h - zh) // 2, (w + zw) // 2, (h + zh) // 2)).resize((w, h), Image.LANCZOS)
    return img.convert("RGB")


def motion_reel(practice, day, out_path, audio_path, seconds, ffmpeg="ffmpeg", focus="", fps=30):
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1080x1920",
           "-r", str(fps), "-i", "-", "-i", str(audio_path), "-t", str(seconds), "-c:v", "libx264",
           "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-shortest", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(int(seconds * fps)):
        proc.stdin.write(reel_frame(practice, day, i / fps, seconds, focus).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed making {out_path.name}")
