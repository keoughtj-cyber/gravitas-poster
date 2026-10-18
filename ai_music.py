"""Generates the reel's backing track with Stable Audio Open Small, a free AI music model.

Stability AI Community License: free for commercial use under $1M annual revenue
(https://stability.ai/license). The model is gated on Hugging Face, so the run needs
HF_TOKEN from an account that accepted the license.

Every track is dark, and each day uses the next prompt in PROMPTS, so back-to-back
reels sound very different. The diffusion seed comes from the date, so a re-run of
the same day makes the same track again.
"""

import datetime as dt
import hashlib
import os
import wave

import numpy as np

MODEL = "stabilityai/stable-audio-open-small"
EPOCH = dt.date(2026, 1, 1)

PROMPTS = [
    ("phonk", "Dark phonk, distorted cowbell melody, heavy distorted 808 bass, hard drums, menacing, aggressive, 140 BPM"),
    ("war cinematic", "Epic dark cinematic trailer music, thunderous war drums, low brass, deep male choir, ominous, intense, 80 BPM"),
    ("dark ambient", "Dark ambient drone, deep sub bass, slow heartbeat drum, eerie distant metallic textures, tense, 60 BPM"),
    ("industrial", "Dark industrial techno, pounding kick, gritty distorted bass synth, mechanical, relentless, 125 BPM"),
    ("piano and cello", "Dark somber piano, low cello, slow, heavy, cinematic, minor key, 65 BPM"),
    ("drill", "Dark UK drill beat, sliding 808 bass, sharp hi-hats, haunting choir, menacing, 142 BPM"),
    ("dark synthwave", "Dark synthwave, pulsing analog bass, cold minor synth arpeggio, gated drums, night drive, 100 BPM"),
    ("orchestral strings", "Dark orchestral strings ostinato, staccato cellos and basses, tense, building, minor key, 90 BPM"),
    ("dark trap", "Heavy dark trap beat, deep 808, ominous bells, hard snare, minor key, 70 BPM"),
    ("tribal", "Dark tribal percussion, deep toms, low throat singing drone, primal, powerful, 90 BPM"),
]

_model = None


def _load():
    global _model
    if _model is None:
        from stable_audio_tools import get_pretrained_model
        model, config = get_pretrained_model(MODEL)
        _model = (model.to("cpu").eval(), config)
    return _model


def generate(day, seconds, out_wav):
    """Writes a stereo WAV for this date and returns a short description of it."""
    import torch
    from stable_audio_tools.inference.generation import generate_diffusion_cond

    index = max(0, (day - EPOCH).days) % len(PROMPTS)
    name, prompt = PROMPTS[index]
    seed = int(hashlib.sha256(f"gravitas-reel-{day.isoformat()}".encode()).hexdigest()[:8], 16)

    model, config = _load()
    sr = config["sample_rate"]
    with torch.no_grad():
        audio = generate_diffusion_cond(
            model,
            steps=8,
            conditioning=[{"prompt": prompt, "seconds_total": 11}],
            sample_size=config["sample_size"],
            sampler_type="pingpong",
            device="cpu",
            seed=seed,
        )
    y = audio[0].to(torch.float32).cpu().numpy().T  # (samples, channels)
    y = y[: int(sr * seconds)]
    t = np.arange(len(y)) / sr
    y = y * np.minimum(1, (seconds - t) / 0.6)[:, None]
    y = y / (np.abs(y).max() or 1) * 0.89

    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(y.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype(np.int16).tobytes())
    return f"AI track, {name}"


if __name__ == "__main__":
    # Test run: python ai_music.py 2026-10-19 3 writes that many days of tracks to cards/music_test/.
    import subprocess
    import sys
    from pathlib import Path

    import imageio_ffmpeg

    start = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today()
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    out = Path(__file__).parent / "cards" / "music_test"
    out.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        day = start + dt.timedelta(days=i)
        wav = out / f"{day}.wav"
        print(day, generate(day, float(os.environ.get("REEL_SECONDS", "7")), wav))
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(wav),
                        "-b:a", "192k", str(wav.with_suffix(".mp3"))], check=True)
        wav.unlink()
