"""Daily GRAVITAS music clip, made with Stable Audio Open Small on CPU.

Each run builds a dark instrumental prompt for the date, generates four 11-second
candidates, keeps the best one, and saves a 7-second cut and the full clip to
music/output/YYYY-MM-DD/, with a copy of the newest cut in music/output/latest/.

Usage:
  python music/generate.py                    today in America/New_York
  python music/generate.py --date 2026-10-19  reproduce any day
  python music/generate.py --dry-run          print the prompt, pillar, and seed only

The Hugging Face token is read from the HF_TOKEN environment variable by the
Hugging Face library. This script never prints it.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"
TZ = ZoneInfo("America/New_York")

MODEL_NAME = "stabilityai/stable-audio-open-small"
SETTINGS = {"steps": 8, "cfg_scale": 1.0, "sampler_type": "pingpong", "seconds_total": 11}
CANDIDATES = 4
CUT_SECONDS = 7.0
FADE_IN = 0.1
FADE_OUT = 0.8
TARGET_LUFS = -14.0
TRUE_PEAK_DB = -1.0
MP3_BITRATE = "192k"
KEEP_DAYS = 60

# Scoring thresholds, measured on the first CUT_SECONDS of each raw candidate.
FRAME_SECONDS = 0.05          # window for the silence check
SILENT_FRAME_DBFS = -50.0     # a frame quieter than this counts as silent
MAX_SILENT_FRACTION = 0.25    # reject if more than this share of frames is silent
MIN_RMS_DBFS = -40.0          # reject if the overall level is below this
CLIP_NEAR_PEAK = 0.999        # samples this close to the peak count as flat-topped
MAX_CLIPPED_FRACTION = 0.002  # reject if more than this share of samples is flat-topped
MAX_PEAK = 1.0                # reject if the raw peak goes past full scale
STEADY_WINDOW_SECONDS = 0.5   # window for the loudness steadiness score


def log(msg):
    print(msg, flush=True)


# ---------- prompt ----------

def load_prompts():
    return json.loads((HERE / "prompts.json").read_text())


def date_seed(day):
    """A stable integer seed for the date, under 2**31."""
    return int(hashlib.sha256(f"gravitas-music-{day.isoformat()}".encode()).hexdigest()[:8], 16) % (2 ** 31)


def pillar_for(day, data):
    start = dt.date.fromisoformat(data["start_date"])
    order = data["pillar_order"]
    return order[max(0, (day - start).days) % len(order)]


def join_list(items):
    """Plain English list with the Oxford comma."""
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def build_prompt(day, pillar, data):
    bank = data["bank"]
    rng = random.Random(date_seed(day))
    style = rng.choice(bank["style"])
    bpm = rng.choice(bank["bpm"])
    instruments = rng.sample(bank["instruments"], rng.choice([2, 3]))
    mood = rng.choice(bank["mood"][pillar])
    texture = rng.choice(bank["texture"])
    return f"{style}, {bpm} BPM, {join_list(instruments)}, {mood}, {texture}, instrumental"


def prompt_ok(prompt):
    """English (plain ASCII letters), has a BPM, and ends with instrumental."""
    return (prompt.isascii()
            and re.search(r"\b\d{2,3} BPM\b", prompt) is not None
            and prompt.rstrip().endswith("instrumental"))


def choose_prompt(day, pillar, data):
    prompt = build_prompt(day, pillar, data)
    if prompt_ok(prompt):
        return prompt, "rotation"
    log(f"Built prompt failed the check, using the {pillar} template: {prompt}")
    return data["templates"][pillar], "template"


# ---------- model ----------

_model = None


def load_model():
    global _model
    if _model is None:
        import torch
        from stable_audio_tools import get_pretrained_model
        # CPU speed fixes: tiny "denormal" numbers and half-precision layers make CPU
        # convolutions crawl, which stalled the audio decoder for half an hour.
        torch.set_flush_denormal(True)
        log(f"Loading {MODEL_NAME}")
        model, config = get_pretrained_model(MODEL_NAME)
        model = model.to("cpu").float().eval()
        log(f"Model dtype: {next(model.parameters()).dtype}, threads: {torch.get_num_threads()}")
        _model = (model, config)
    return _model


def generate_raw(prompt, seed):
    """One candidate as a float array of shape (samples, channels), plus its sample rate."""
    import torch
    from stable_audio_tools.inference.generation import generate_diffusion_cond

    model, config = load_model()
    with torch.no_grad():
        audio = generate_diffusion_cond(
            model,
            steps=SETTINGS["steps"],
            cfg_scale=SETTINGS["cfg_scale"],
            conditioning=[{"prompt": prompt, "seconds_total": SETTINGS["seconds_total"]}],
            sample_size=config["sample_size"],
            sampler_type=SETTINGS["sampler_type"],
            device="cpu",
            seed=seed,
        )
    log("  Decoded")
    sr = config["sample_rate"]
    y = audio[0].to(torch.float32).cpu().numpy().T
    return y[: int(sr * SETTINGS["seconds_total"])], sr


# ---------- scoring ----------

def db(x):
    return float(20 * np.log10(max(float(x), 1e-12)))


def score(y, sr):
    """Returns (passed, metrics). Lower loudness spread means steadier, which scores higher."""
    cut = y[: int(sr * CUT_SECONDS)]
    mono = cut.mean(axis=1)
    peak = float(np.abs(cut).max())
    rms_dbfs = db(np.sqrt(np.mean(cut ** 2)))

    frame = int(sr * FRAME_SECONDS)
    frames = mono[: len(mono) // frame * frame].reshape(-1, frame)
    frame_db = np.array([db(np.sqrt(np.mean(f ** 2))) for f in frames])
    silent_fraction = float(np.mean(frame_db < SILENT_FRAME_DBFS))

    clipped_fraction = float(np.mean(np.abs(cut) >= CLIP_NEAR_PEAK * peak)) if peak > 0 else 1.0

    win = int(sr * STEADY_WINDOW_SECONDS)
    wins = mono[: len(mono) // win * win].reshape(-1, win)
    win_db = np.array([db(np.sqrt(np.mean(w ** 2))) for w in wins])
    spread = float(np.std(win_db))

    reasons = []
    if silent_fraction > MAX_SILENT_FRACTION:
        reasons.append("mostly silent")
    if rms_dbfs < MIN_RMS_DBFS:
        reasons.append("too quiet")
    if peak > MAX_PEAK or clipped_fraction > MAX_CLIPPED_FRACTION:
        reasons.append("clipping")
    metrics = {
        "peak": round(peak, 4),
        "rms_dbfs": round(rms_dbfs, 2),
        "silent_fraction": round(silent_fraction, 3),
        "clipped_fraction": round(clipped_fraction, 5),
        "loudness_spread_db": round(spread, 2),
        "score": round(-spread, 2),
        "rejected": reasons,
    }
    return not reasons, metrics


def best_of(prompt, seeds):
    results = []
    for seed in seeds:
        log(f"Generating candidate with seed {seed}")
        y, sr = generate_raw(prompt, seed)
        passed, metrics = score(y, sr)
        metrics["seed"] = seed
        log(f"  {json.dumps(metrics)}")
        results.append((passed, metrics, y, sr))
    passing = [r for r in results if r[0]]
    best = max(passing, key=lambda r: r[1]["score"]) if passing else None
    return best, [r[1] for r in results]


# ---------- post-processing ----------

def write_wav(path, y, sr):
    y = np.clip(y, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(y.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype(np.int16).tobytes())


def ffmpeg_exe():
    # The ffmpeg binary bundled with imageio-ffmpeg. The system ffmpeg package is avoided
    # because its libraries hung torch's audio decoder on GitHub's runner.
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def ffmpeg(*args):
    subprocess.run([ffmpeg_exe(), "-hide_banner", "-y", *args], check=True, capture_output=True, text=True)


def master(src, dst, seconds):
    """Fades, then two-pass loudness normalization to TARGET_LUFS with a TRUE_PEAK_DB ceiling."""
    fades = f"afade=t=in:d={FADE_IN},afade=t=out:st={seconds - FADE_OUT:.3f}:d={FADE_OUT}"
    norm = f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_DB}:LRA=11"
    probe = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(src), "-af", f"{fades},{norm}:print_format=json",
                            "-f", "null", "-"], check=True, capture_output=True, text=True).stderr
    m = json.loads(probe[probe.rindex("{"): probe.rindex("}") + 1])
    second = (f"{norm}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
              f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    ffmpeg("-i", str(src), "-af", f"{fades},{second}", "-ar", "44100", "-c:a", "pcm_s16le", str(dst))


def measure(path):
    """Integrated loudness and true peak of a finished file."""
    out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path), "-af",
                          f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_DB}:print_format=json", "-f", "null", "-"],
                         check=True, capture_output=True, text=True).stderr
    m = json.loads(out[out.rindex("{"): out.rindex("}") + 1])
    return {"lufs": float(m["input_i"]), "true_peak_db": float(m["input_tp"])}


def duration(path):
    with wave.open(str(path)) as w:
        return round(w.getnframes() / w.getframerate(), 3)


def prune(today):
    """Delete dated output folders older than KEEP_DAYS."""
    for folder in OUTPUT.iterdir():
        try:
            day = dt.date.fromisoformat(folder.name)
        except ValueError:
            continue
        if (today - day).days > KEEP_DAYS:
            shutil.rmtree(folder)
            log(f"Pruned {folder.name}")


# ---------- main ----------

def main():
    # If a step stalls, print where every thread is, every two minutes, so the log shows the cause.
    import faulthandler
    faulthandler.dump_traceback_later(120, repeat=True)
    parser = argparse.ArgumentParser(description="Generate the daily GRAVITAS music clip.")
    parser.add_argument("--date", help="YYYY-MM-DD, default today in America/New_York")
    parser.add_argument("--dry-run", action="store_true", help="print the prompt, pillar, and seed, then stop")
    args = parser.parse_args()

    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(TZ).date()
    data = load_prompts()
    pillar = pillar_for(day, data)
    prompt, source = choose_prompt(day, pillar, data)
    seed = date_seed(day)
    seeds = [(seed + i * 1000003) % (2 ** 31) for i in range(CANDIDATES)]
    log(f"Date: {day}")
    log(f"Pillar: {pillar}")
    log(f"Prompt ({source}): {prompt}")
    log(f"Date seed: {seed}")
    log(f"Candidate seeds: {seeds}")
    if args.dry_run:
        return

    best, scores = best_of(prompt, seeds)
    attempts = [{"prompt": prompt, "source": source, "candidates": scores}]
    if best is None:
        prompt = data["templates"][pillar]
        retry = [(s + 4 * 1000003) % (2 ** 31) for s in seeds]
        log(f"All candidates failed, retrying once with the {pillar} template: {prompt}")
        best, scores = best_of(prompt, retry)
        attempts.append({"prompt": prompt, "source": "template", "candidates": scores})
    if best is None:
        sys.exit("Every candidate failed the quality checks. No clip was saved.")

    _, metrics, y, sr = best
    folder = OUTPUT / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"gravitas_{day.isoformat()}"
    raw_full = folder / "_raw_full.wav"
    raw_cut = folder / "_raw_cut.wav"
    write_wav(raw_full, y / (np.abs(y).max() or 1) * 0.9, sr)
    write_wav(raw_cut, y[: int(sr * CUT_SECONDS)] / (np.abs(y).max() or 1) * 0.9, sr)

    full_wav = folder / f"{stem}_full.wav"
    cut_wav = folder / f"{stem}_7s.wav"
    cut_mp3 = folder / f"{stem}_7s.mp3"
    master(raw_full, full_wav, SETTINGS["seconds_total"])
    master(raw_cut, cut_wav, CUT_SECONDS)
    ffmpeg("-i", str(cut_wav), "-c:a", "libmp3lame", "-b:a", MP3_BITRATE, str(cut_mp3))
    raw_full.unlink()
    raw_cut.unlink()

    meta = {
        "date": day.isoformat(),
        "pillar": pillar,
        "prompt": prompt,
        "date_seed": seed,
        "chosen_seed": metrics["seed"],
        "attempts": attempts,
        "model": MODEL_NAME,
        "settings": SETTINGS,
        "post": {"cut_seconds": CUT_SECONDS, "fade_in": FADE_IN, "fade_out": FADE_OUT,
                 "target_lufs": TARGET_LUFS, "true_peak_db": TRUE_PEAK_DB, "mp3_bitrate": MP3_BITRATE},
        "result": {
            "seconds_7s": duration(cut_wav),
            "seconds_full": duration(full_wav),
            **measure(cut_wav),
            "bytes": {p.name: p.stat().st_size for p in (cut_mp3, cut_wav, full_wav)},
        },
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    latest = OUTPUT / "latest"
    latest.mkdir(exist_ok=True)
    shutil.copyfile(cut_mp3, latest / "gravitas_7s.mp3")
    shutil.copyfile(folder / "meta.json", latest / "meta.json")
    prune(day)

    log(f"Saved music/output/{folder.name}: {json.dumps(meta['result'])}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"date={day.isoformat()}\n")


if __name__ == "__main__":
    main()
