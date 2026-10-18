"""Composes a short, original backing track for the daily reel.

The sound is on brand for GRAVITAS: dark, inspiring, and manly. Each track is a
short cinematic build in a minor key: a deep impact, a driving low-string ostinato,
war drums that grow, low brass chords climbing an epic progression, a riser, and
a final hit. Every date gets its own track (key, mode, chords, tempo, rhythms,
and drum patterns come from a seed built from the date), so no two reels share
audio and a re-run of the same day makes the same track again. Everything is
synthesized here, so there is nothing to license.
"""

import hashlib
import wave

import numpy as np

SR = 44100

SCALES = {
    "aeolian": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "harmonic": [0, 2, 3, 5, 7, 8, 11],
}

# Climbing progressions in scale degrees (0 = i, 5 = VI, 2 = III, 6 = VII, 3 = iv).
PROGRESSIONS = [
    [0, 5, 2, 6], [0, 5, 6, 6], [0, 6, 5, 6], [0, 3, 5, 6], [0, 5, 3, 6],
    [0, 2, 5, 6], [0, 0, 5, 6], [0, 5, 0, 6], [0, 3, 6, 6], [5, 6, 0, 0],
]

# Ostinato rhythms per beat, as fractions of a beat.
OSTINATOS = [[0, 0.5], [0, 0.5, 0.75], [0, 0.25, 0.5], [0, 0.25, 0.5, 0.75]]

# War drum patterns per bar of four beats: (beat position, strength).
DRUMS = [
    [(0, 1), (1.5, 0.6), (2, 0.9), (3.5, 0.6)],
    [(0, 1), (0.75, 0.5), (2, 1), (2.75, 0.5), (3.5, 0.7)],
    [(0, 1), (1, 0.6), (2, 1), (3, 0.6), (3.5, 0.5)],
    [(0, 1), (2, 0.8), (2.5, 0.6), (3, 0.9)],
]


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def seed_for(day):
    return int(hashlib.sha256(f"gravitas-reel-{day.isoformat()}".encode()).hexdigest()[:16], 16)


def saw(freq, tt, harmonics, phase=0.0):
    s = np.zeros_like(tt)
    for k in range(1, harmonics + 1):
        s += np.sin(2 * np.pi * k * freq * tt + phase * k) / k
    return s


def compose(day, seconds, out_wav):
    """Writes a stereo WAV for this date and returns a short description of it."""
    rng = np.random.default_rng(seed_for(day))
    n = int(SR * seconds)
    t = np.arange(n) / SR

    root = 33 + int(rng.integers(0, 9))  # A1 to F2
    scale_name = str(rng.choice(list(SCALES)))
    scale = SCALES[scale_name]
    prog = PROGRESSIONS[int(rng.integers(0, len(PROGRESSIONS)))]
    bpm = int(rng.integers(72, 92))
    beat = 60 / bpm
    ostinato = OSTINATOS[int(rng.integers(0, len(OSTINATOS)))]
    drums = DRUMS[int(rng.integers(0, len(DRUMS)))]
    drop = seconds - float(rng.uniform(1.4, 1.9))  # the final hit lands here
    chord_len = drop / len(prog)

    def degree(d, octave=0):
        return root + 12 * (octave + d // 7) + scale[d % 7]

    def place(buf, sig, start, amp):
        i = int(start * SR)
        if i >= n or i < 0:
            return
        sig = sig[: n - i]
        buf[i : i + len(sig)] += amp * sig

    def chord_at(time):
        return prog[min(int(time // chord_len), len(prog) - 1)]

    # Builds from about half volume to full at the drop.
    build = 0.45 + 0.55 * np.clip(t / drop, 0, 1) ** 1.3

    low = np.zeros(n)
    hits = np.zeros(n)

    # Opening impact.
    tt = np.arange(int(SR * 2.5)) / SR
    boom = np.sin(2 * np.pi * 40 * tt * (1 - 0.18 * tt)) * np.exp(-tt * 2.0)
    boom[: int(SR * 0.03)] += rng.standard_normal(int(SR * 0.03)) * 0.5
    place(hits, boom, 0, 1.0)

    # Low brass chords: root, fifth, and octave, slow swell, climbing.
    for k, d in enumerate(prog):
        s0 = k * chord_len
        dur = chord_len + 0.25
        tt = np.arange(int(SR * dur)) / SR
        env = np.minimum(1, tt / 0.35) * np.minimum(1, (dur - tt) / 0.25)
        for interval, octave, amp in ((0, 0, 0.5), (4, 0, 0.35), (0, 1, 0.3), (2, 1, 0.2)):
            f = midi_hz(degree(d + interval, octave))
            v = sum(saw(f * (1 + det), tt, 7, rng.uniform(0, 6)) for det in (-0.004, 0, 0.004)) / 3
            place(low, v * env, s0, amp)

    # Driving low-string ostinato on the chord root.
    for b in np.arange(0, drop, beat):
        for frac in ostinato:
            s0 = b + frac * beat
            if s0 >= drop:
                break
            tt = np.arange(int(SR * beat * 0.45)) / SR
            f = midi_hz(degree(chord_at(s0), 1))
            v = saw(f, tt, 9) * np.exp(-tt * 7) * np.minimum(1, tt / 0.005)
            place(low, v, s0, 0.35)

    # War drums, entering after the first bar and doubling up in the last one.
    def taiko(strength):
        tt = np.arange(int(SR * 0.9)) / SR
        body = np.sin(2 * np.pi * 62 * tt * (1 - 0.4 * tt)) * np.exp(-tt * 6)
        skin = rng.standard_normal(len(tt)) * np.exp(-tt * 40) * 0.35
        return (body + skin) * strength

    bar = beat * 4
    start = bar if drop > bar * 2 else 0
    for b0 in np.arange(start, drop, bar):
        last = b0 + bar >= drop - 0.01
        for pos, strength in drums:
            s0 = b0 + pos * beat
            if s0 < drop:
                place(hits, taiko(strength), s0, 0.75)
        if last:
            for s0 in np.arange(drop - beat, drop, beat / 4):
                place(hits, taiko(0.55), s0, 0.6)

    # Riser into the drop.
    rise_len = beat * 2
    tt = np.arange(int(SR * rise_len)) / SR
    riser = rng.standard_normal(len(tt)) * (tt / rise_len) ** 2.5
    place(hits, riser, drop - rise_len, 0.18)

    # The drop: big hit, tonic chord, and ring-out.
    tail = seconds - drop
    tt = np.arange(int(SR * tail)) / SR
    hit = np.sin(2 * np.pi * 38 * tt * (1 - 0.15 * tt)) * np.exp(-tt * 1.6)
    hit[: int(SR * 0.04)] += rng.standard_normal(int(SR * 0.04)) * 0.7
    place(hits, hit, drop, 1.2)
    for interval, octave, amp in ((0, 0, 0.6), (4, 0, 0.4), (0, 1, 0.4), (2, 1, 0.3), (0, 2, 0.15)):
        f = midi_hz(degree(interval, octave))
        place(low, saw(f, tt, 8) * np.exp(-tt * 1.1), drop, amp)

    mix = low / (np.abs(low).max() or 1) * build + 0.9 * hits / (np.abs(hits).max() or 1)

    # Hall: convolve with a decaying noise tail.
    room = rng.uniform(1.8, 2.8)
    ir = rng.standard_normal(int(SR * room)) * np.exp(-np.arange(int(SR * room)) / SR * (5 / room))
    wet = np.convolve(mix, ir)[:n]
    y = 0.75 * mix / (np.abs(mix).max() or 1) + 0.4 * wet / (np.abs(wet).max() or 1)
    y = np.tanh(1.6 * y)  # a little saturation for weight
    y *= np.minimum(1, t / 0.02) * np.minimum(1, (seconds - t) / 0.6)
    y = y / (np.abs(y).max() or 1) * 0.89

    width = int(SR * rng.uniform(0.008, 0.016))
    stereo = np.stack([y, np.roll(y, width)], 1)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())

    names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    return f"{names[root % 12]} {scale_name}, {bpm} bpm, chords {prog}, drop at {drop:.1f}s"
