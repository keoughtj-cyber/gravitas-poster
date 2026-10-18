"""Composes a short, original backing track for the daily reel.

Every date gets its own track: the key, scale, chords, tempo, instruments, rhythm,
and melody all come from a seed built from the date, so no two reels share audio
and a re-run of the same day makes the same track again. Everything is synthesized
here, so there is nothing to license.
"""

import hashlib
import wave

import numpy as np

SR = 44100

SCALES = {
    "aeolian": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "harmonic": [0, 2, 3, 5, 7, 8, 11],
    "ionian": [0, 2, 4, 5, 7, 9, 11],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
}

# Scale-degree progressions (0 = the tonic chord), two to four chords each.
PROGRESSIONS = [
    [0, 5], [0, 3], [0, 6], [0, 5, 6], [0, 3, 4], [0, 5, 3, 4],
    [0, 2, 5], [0, 6, 5], [0, 3, 6], [5, 3, 0], [0, 4, 5, 3], [0, 1],
]


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def seed_for(day):
    return int(hashlib.sha256(f"gravitas-reel-{day.isoformat()}".encode()).hexdigest()[:16], 16)


def compose(day, seconds, out_wav):
    """Writes a stereo WAV for this date and returns a short description of it."""
    rng = np.random.default_rng(seed_for(day))
    n = int(SR * seconds)
    t = np.arange(n) / SR

    root = 36 + int(rng.integers(0, 12))
    scale_name = str(rng.choice(list(SCALES)))
    scale = SCALES[scale_name]
    prog = PROGRESSIONS[int(rng.integers(0, len(PROGRESSIONS)))]
    bpm = int(rng.integers(60, 100))
    beat = 60 / bpm
    brightness = rng.uniform(0.3, 1.0)

    def degree(d, octave=0):
        return root + 12 * (octave + d // 7) + scale[d % 7]

    def voice(freq, dur, kind):
        tt = np.arange(int(SR * dur)) / SR
        ph = 2 * np.pi * freq * tt + rng.uniform(0, 6.28)
        if kind == "pad":
            s = sum(np.sin(ph * (1 + d)) for d in (-0.003, 0, 0.003)) / 3
            s += brightness * 0.3 * np.sin(2 * ph) + brightness * 0.12 * np.sin(3 * ph)
            env = np.minimum(1, tt / min(1.2, dur / 2)) * np.minimum(1, (dur - tt) / 0.4)
        elif kind == "pluck":
            s = np.sin(ph) + 0.5 * brightness * np.sin(2 * ph) + 0.25 * np.sin(3 * ph)
            env = np.exp(-tt * rng.uniform(4, 9))
        elif kind == "bell":
            s = np.sin(ph) + 0.4 * np.sin(2.76 * ph) + 0.2 * np.sin(5.4 * ph)
            env = np.exp(-tt * 2.5)
        else:  # keys
            s = np.sin(ph) + 0.3 * np.sin(2 * ph)
            env = np.minimum(1, tt / 0.01) * np.exp(-tt * 1.8)
        return s * env

    def place(buf, sig, start, amp):
        i = int(start * SR)
        if i >= n:
            return
        sig = sig[: n - i]
        buf[i : i + len(sig)] += amp * sig

    mix = np.zeros(n)

    # Chords: pad or keys, one chord per bar or per two beats.
    chord_len = beat * float(rng.choice([2, 4]))
    chord_kind = str(rng.choice(["pad", "pad", "keys"]))
    starts = np.arange(0, seconds, chord_len)
    for k, s0 in enumerate(starts):
        d = prog[k % len(prog)]
        for interval, amp in ((0, 0.5), (2, 0.3), (4, 0.3), (6 if rng.random() < 0.4 else 7, 0.15)):
            place(mix, voice(midi_hz(degree(d + interval, 1)), chord_len + 0.6, chord_kind), s0, amp)
        place(mix, voice(midi_hz(degree(d)), chord_len + 0.6, "pad"), s0, 0.55)

    # Arpeggio, on most days.
    if rng.random() < 0.7:
        step = beat / float(rng.choice([2, 3, 4]))
        pattern = list(rng.permutation([0, 2, 4, 7]))[: int(rng.integers(3, 5))]
        for k, s0 in enumerate(np.arange(rng.choice([0, beat * 2]), seconds, step)):
            d = prog[int(s0 // chord_len) % len(prog)]
            place(mix, voice(midi_hz(degree(d + pattern[k % len(pattern)], 2)), step * 3, "pluck"), s0, 0.18)

    # A few melody notes, on some days.
    if rng.random() < 0.6:
        for s0 in np.arange(beat * 4, seconds - 1, beat * float(rng.choice([1, 2]))):
            if rng.random() < 0.6:
                place(mix, voice(midi_hz(degree(int(rng.integers(0, 8)), 3)), 1.8, "bell"), s0, 0.12)

    # Pulse: heartbeat, soft kick with hats, or none.
    pulse = str(rng.choice(["heartbeat", "kick", "kick", "none"]))
    if pulse != "none":
        for s0 in np.arange(beat * float(rng.choice([0, 2, 4])), seconds, beat):
            hits = ((0, 1.0), (0.22, 0.6)) if pulse == "heartbeat" else ((0, 1.0),)
            for off, a in hits:
                tt = np.arange(int(SR * 0.5)) / SR
                place(mix, np.sin(2 * np.pi * 55 * tt * (1 - 0.35 * tt)) * np.exp(-tt * 9), s0 + off, 0.5 * a)
            if pulse == "kick":
                tt = np.arange(int(SR * 0.06)) / SR
                hat = rng.standard_normal(len(tt)) * np.exp(-tt * 70)
                place(mix, hat, s0 + beat / 2, 0.05)

    # Room: convolve with a decaying noise tail.
    tail = rng.uniform(1.2, 3.0)
    ir = rng.standard_normal(int(SR * tail)) * np.exp(-np.arange(int(SR * tail)) / SR * (5 / tail))
    wet = np.convolve(mix, ir)[:n]
    y = 0.7 * mix / (np.abs(mix).max() or 1) + rng.uniform(0.3, 0.55) * wet / (np.abs(wet).max() or 1)
    y *= np.minimum(1, t / 0.4) * np.minimum(1, (seconds - t) / 1.0) ** 2
    y = y / (np.abs(y).max() or 1) * 0.85

    width = int(SR * rng.uniform(0.006, 0.018))
    stereo = np.stack([y, np.roll(y, width)], 1)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())

    names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    return f"{names[root % 12]} {scale_name}, {bpm} bpm, {chord_kind}, {pulse}"
