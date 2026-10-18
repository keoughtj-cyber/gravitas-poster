"""Composes a short, original backing track for the daily reel.

Every track is dark: minor chords only, low registers, phrygian and harmonic-minor
melodies, no major chords anywhere. Each day also uses a different style from
STYLES, in rotation, so back-to-back reels never sound alike, and the key, tempo,
chords, rhythm, and melody inside the style come from a seed built from the date.
A re-run of the same day makes the same track again. Everything is synthesized
here, so there is nothing to license.
"""

import datetime as dt
import hashlib
import wave

import numpy as np

SR = 44100
EPOCH = dt.date(2026, 1, 1)

PHRYGIAN = [0, 1, 3, 5, 7, 8, 10]
HARMONIC = [0, 2, 3, 5, 7, 8, 11]

# Chord roots in semitones from the key; every chord is played minor or as a bare fifth.
PROGRESSIONS = [
    [0, 8, 5, 0], [0, 1, 0, 1], [0, 6, 0, 6], [0, 8, 1, 0], [0, 5, 8, 7],
    [0, 3, 1, 0], [0, 0, 8, 7], [0, 1, 8, 7], [0, 5, 1, 0], [0, 8, 6, 1],
]


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def seed_for(day):
    return int(hashlib.sha256(f"gravitas-reel-{day.isoformat()}".encode()).hexdigest()[:16], 16)


def secs(dur):
    return np.arange(int(SR * dur)) / SR


def saw(f, tt, harmonics=8, ph=0.0):
    return sum(np.sin(2 * np.pi * k * f * tt + ph * k) / k for k in range(1, harmonics + 1))


def square(f, tt, harmonics=7):
    return sum(np.sin(2 * np.pi * k * f * tt) / k for k in range(1, 2 * harmonics, 2))


def fftconv(a, b):
    size = len(a) + len(b) - 1
    nfft = 1 << (size - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(a, nfft) * np.fft.rfft(b, nfft), nfft)[: len(a)]


def bright(x):
    """Crude high-pass, for hats and air."""
    return x - np.convolve(x, np.ones(6) / 6, mode="same")


class Track:
    def __init__(self, seconds, rng):
        self.n = int(SR * seconds)
        self.seconds = seconds
        self.rng = rng
        self.buf = np.zeros(self.n)

    def put(self, sig, start, amp=1.0):
        i = int(start * SR)
        if 0 <= i < self.n:
            sig = sig[: self.n - i]
            self.buf[i : i + len(sig)] += amp * sig

    # ----- instruments -----
    def sub808(self, m, start, dur, glide_from=None, amp=1.0):
        tt = secs(dur)
        f0 = hz(m)
        f = f0 if glide_from is None else hz(glide_from) + (f0 - hz(glide_from)) * np.minimum(1, tt / 0.12)
        sig = np.sin(2 * np.pi * np.cumsum(f * np.ones_like(tt)) / SR)
        env = np.minimum(1, tt / 0.004) * np.exp(-tt * 1.3) * np.minimum(1, (dur - tt) / 0.05)
        self.put(np.tanh(2.5 * sig) * env, start, amp)

    def kick(self, start, amp=1.0, punch=1.0):
        tt = secs(0.5)
        f = 45 + 110 * np.exp(-tt * 30 * punch)
        sig = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 7)
        self.put(np.tanh(2 * sig), start, amp)

    def snare(self, start, amp=1.0, tone=180):
        tt = secs(0.3)
        noise = bright(self.rng.standard_normal(len(tt))) * np.exp(-tt * 18)
        body = np.sin(2 * np.pi * tone * tt) * np.exp(-tt * 25)
        self.put(noise * 0.8 + body * 0.5, start, amp)

    def clap(self, start, amp=1.0):
        tt = secs(0.25)
        sig = np.zeros(len(tt))
        for off in (0, 0.011, 0.022):
            k = tt >= off
            sig[k] += np.exp(-(tt[k] - off) * 45)
        self.put(bright(self.rng.standard_normal(len(tt))) * sig, start, amp)

    def hat(self, start, amp=1.0, open_=False):
        tt = secs(0.25 if open_ else 0.05)
        sig = bright(bright(self.rng.standard_normal(len(tt)))) * np.exp(-tt * (12 if open_ else 80))
        self.put(sig, start, amp)

    def taiko(self, start, amp=1.0):
        tt = secs(0.9)
        body = np.sin(2 * np.pi * np.cumsum(62 * (1 - 0.35 * tt)) / SR) * np.exp(-tt * 6)
        skin = self.rng.standard_normal(len(tt)) * np.exp(-tt * 40) * 0.35
        self.put(body + skin, start, amp)

    def boom(self, start, amp=1.0, length=2.5):
        tt = secs(length)
        sig = np.sin(2 * np.pi * np.cumsum(38 * (1 - 0.15 * tt)) / SR) * np.exp(-tt * 1.8)
        sig[: int(SR * 0.04)] += self.rng.standard_normal(int(SR * 0.04)) * 0.6
        self.put(sig, start, amp)

    def cowbell(self, m, start, amp=1.0):
        tt = secs(0.35)
        f = hz(m)
        sig = (square(f, tt, 5) + 0.7 * square(f * 1.48, tt, 5)) * np.exp(-tt * 9)
        self.put(sig, start, amp)

    def piano(self, m, start, dur=2.5, amp=1.0):
        tt = secs(dur)
        f = hz(m)
        sig = sum(np.sin(2 * np.pi * k * f * np.sqrt(1 + 0.0004 * k * k) * tt) * np.exp(-tt * (1.2 + 0.9 * k)) / k
                  for k in range(1, 8))
        self.put(sig * np.minimum(1, tt / 0.003), start, amp)

    def cello(self, m, start, dur, amp=1.0):
        tt = secs(dur)
        f = hz(m) * (1 + 0.004 * np.sin(2 * np.pi * 5.2 * tt) * np.minimum(1, tt / 0.6))
        sig = sum(np.sin(2 * np.pi * k * np.cumsum(f) / SR) / k ** 1.3 for k in range(1, 9))
        env = np.minimum(1, tt / 0.25) * np.minimum(1, (dur - tt) / 0.3)
        self.put(sig * env, start, amp)

    def pad(self, notes, start, dur, amp=1.0, harmonics=4):
        tt = secs(dur)
        env = np.minimum(1, tt / min(1.0, dur / 2)) * np.minimum(1, (dur - tt) / 0.4)
        sig = sum(saw(hz(m) * (1 + d), tt, harmonics, self.rng.uniform(0, 6))
                  for m in notes for d in (-0.005, 0, 0.005)) / (3 * len(notes))
        self.put(sig * env, start, amp)

    def choir(self, notes, start, dur, amp=1.0):
        tt = secs(dur)
        env = np.minimum(1, tt / 0.8) * np.minimum(1, (dur - tt) / 0.5)
        sig = np.zeros(len(tt))
        for m in notes:
            f = hz(m) * (1 + 0.003 * np.sin(2 * np.pi * 4.5 * tt + self.rng.uniform(0, 6)))
            for k, a in ((1, 1), (2, 0.5), (3, 0.6), (4, 0.15), (5, 0.25)):  # "ah" formant-ish
                sig += a * np.sin(2 * np.pi * k * np.cumsum(f) / SR)
        self.put(sig * env / len(notes), start, amp)

    def metal(self, m, start, amp=1.0):
        tt = secs(2.5)
        f = hz(m)
        sig = sum(np.sin(2 * np.pi * f * r * tt) * np.exp(-tt * d) for r, d in ((1, 1.5), (2.4, 2), (3.9, 3), (5.4, 4)))
        self.put(sig, start, amp)

    def lead(self, m, start, dur, amp=1.0):
        tt = secs(dur)
        sig = saw(hz(m), tt, 10) * np.minimum(1, tt / 0.01) * np.exp(-tt * 2.5)
        self.put(sig, start, amp)

    def riser(self, end, length, amp=1.0):
        tt = secs(length)
        self.put(self.rng.standard_normal(len(tt)) * (tt / length) ** 2.5, end - length, amp)


def minor(m):
    return [m, m + 3, m + 7]


def fifth(m):
    return [m, m + 7, m + 12]


# ---------- styles ----------

def phonk(tr, key, rng):
    """Dark phonk: cowbell melody, distorted 808, hard hats."""
    bpm = int(rng.integers(130, 150)); beat = 60 / bpm
    prog = PROGRESSIONS[int(rng.integers(0, len(PROGRESSIONS)))]
    bar = beat * 4
    motif = [int(x) for x in rng.choice(PHRYGIAN, 8)]
    for i, s0 in enumerate(np.arange(0, tr.seconds, beat / 2)):
        if rng.random() < 0.8:
            tr.cowbell(key + 48 + motif[i % 8], s0, 0.22)
        tr.hat(s0, 0.18)
        if rng.random() < 0.25:
            tr.hat(s0 + beat / 4, 0.12)
    for b, s0 in enumerate(np.arange(0, tr.seconds, bar)):
        root = key + 12 + prog[b % len(prog)]
        tr.sub808(root, s0, beat * 1.5, root + 12 if b else None, 0.9)
        tr.sub808(root, s0 + beat * 2.5, beat * 1.4, None, 0.8)
        tr.kick(s0, 0.7)
        tr.clap(s0 + beat * 2, 0.6)
    return f"phonk, {bpm} bpm", 0.25


def cinematic(tr, key, rng):
    """War cinematic: bare-fifth low brass, taiko, choir, final hit."""
    bpm = int(rng.integers(70, 88)); beat = 60 / bpm
    prog = PROGRESSIONS[int(rng.integers(0, len(PROGRESSIONS)))]
    drop = tr.seconds - rng.uniform(1.4, 1.9)
    clen = drop / len(prog)
    tr.boom(0, 1.0)
    for k, r in enumerate(prog):
        tr.pad(fifth(key + 24 + r), k * clen, clen + 0.3, 0.6, 7)
        tr.choir(minor(key + 48 + r), k * clen, clen + 0.3, 0.25)
    for s0 in np.arange(beat, drop, beat):
        tr.taiko(s0, 0.7 if int(s0 / beat) % 2 else 0.45)
    for s0 in np.arange(drop - beat, drop, beat / 4):
        tr.taiko(s0, 0.5)
    tr.riser(drop, beat * 2, 0.15)
    tr.boom(drop, 1.2, tr.seconds - drop)
    tr.pad(fifth(key + 24), drop, tr.seconds - drop, 0.7, 7)
    return f"war cinematic, {bpm} bpm", 0.45


def drone(tr, key, rng):
    """Dark ambient: low cluster drone, heartbeat, distant metal."""
    bpm = int(rng.integers(52, 64)); beat = 60 / bpm
    tr.pad([key + 12, key + 13, key + 19, key + 24], 0, tr.seconds, 0.8, 5)
    tr.choir([key + 36, key + 39], 1.0, tr.seconds - 1.0, 0.25)
    for s0 in np.arange(beat * 2, tr.seconds, beat):
        tr.kick(s0, 0.55, 0.4)
        tr.kick(s0 + 0.22, 0.35, 0.4)
    for s0 in (0.5, 0.5 + beat * rng.integers(3, 5)):
        tr.metal(key + 36 + int(rng.choice([0, 1, 6])), s0, 0.25)
    return f"dark drone, {bpm} bpm", 0.6


def industrial(tr, key, rng):
    """Industrial synth: driving 16th sub bass, gated snare, minor arp."""
    bpm = int(rng.integers(96, 112)); beat = 60 / bpm
    prog = PROGRESSIONS[int(rng.integers(0, len(PROGRESSIONS)))]
    bar = beat * 4
    for i, s0 in enumerate(np.arange(0, tr.seconds, beat / 4)):
        r = prog[int(s0 // bar) % len(prog)]
        tt = secs(beat / 4 * 0.9)
        tr.put(saw(hz(key + 24 + r), tt, 6) * np.exp(-tt * 14), s0, 0.35)
        if i % 4 == 0:
            tr.kick(s0, 0.8)
        if i % 8 == 4:
            tr.snare(s0, 0.6, 160)
        if i % 2 == 1:
            tr.hat(s0, 0.08)
    arp = minor(key + 48)
    for i, s0 in enumerate(np.arange(bar, tr.seconds, beat / 2)):
        r = prog[int(s0 // bar) % len(prog)]
        tr.lead(arp[i % 3] + r + (12 if i % 6 == 5 else 0), s0, beat / 2, 0.12)
    return f"industrial, {bpm} bpm", 0.3


def piano_cello(tr, key, rng):
    """Dark piano and cello: sparse minor piano over a low cello line."""
    bpm = int(rng.integers(60, 72)); beat = 60 / bpm
    prog = PROGRESSIONS[int(rng.integers(0, len(PROGRESSIONS)))]
    clen = tr.seconds / len(prog)
    for k, r in enumerate(prog):
        tr.cello(key + 24 + r, k * clen, clen + 0.2, 0.5)
        chord = minor(key + 48 + r)
        for j, s0 in enumerate(np.arange(k * clen, (k + 1) * clen, beat / 2)):
            tr.piano(chord[[0, 1, 2, 1][j % 4]] + (12 if j % 4 == 2 else 0), s0, 2.0, 0.28)
        tr.piano(key + 36 + r, k * clen, 3.0, 0.4)
    tr.boom(0, 0.6)
    return f"dark piano and cello, {bpm} bpm", 0.55


def drill(tr, key, rng):
    """Dark drill: sliding 808s, triplet hats, dark choir stab."""
    bpm = int(rng.integers(138, 146)); beat = 60 / bpm
    prog = PROGRESSIONS[int(rng.integers(0, len(PROGRESSIONS)))]
    bar = beat * 4
    for k, s0 in enumerate(np.arange(0, tr.seconds, bar)):
        r = prog[k % len(prog)]
        tr.choir(minor(key + 48 + r), s0, bar, 0.3)
        tr.sub808(key + 12 + r, s0, beat * 1.2, None, 0.9)
        tr.sub808(key + 12 + r + int(rng.choice([1, 3, -2])), s0 + beat * 1.5, beat * 1.0, key + 12 + r, 0.8)
        tr.sub808(key + 12 + r, s0 + beat * 3, beat * 0.9, key + 24 + r, 0.8)
        tr.kick(s0, 0.6)
        tr.snare(s0 + beat * 1.5 if k % 2 else s0 + beat * 2, 0.55, 210)
    for s0 in np.arange(0, tr.seconds, beat / 3):
        tr.hat(s0, 0.14 if rng.random() < 0.85 else 0.0)
    return f"drill, {bpm} bpm", 0.3


STYLES = [cinematic, phonk, drone, industrial, piano_cello, drill]


def compose(day, seconds, out_wav):
    """Writes a stereo WAV for this date and returns a short description of it."""
    rng = np.random.default_rng(seed_for(day))
    style = STYLES[max(0, (day - EPOCH).days) % len(STYLES)]
    key = 21 + int(rng.integers(0, 12))  # A0 to G#1; instruments add octaves
    tr = Track(seconds, rng)
    desc, wet_amount = style(tr, key, rng)

    mix = tr.buf / (np.abs(tr.buf).max() or 1)
    room = rng.uniform(1.6, 2.8)
    ir = rng.standard_normal(int(SR * room)) * np.exp(-secs(room) * (5 / room))
    wet = fftconv(mix, ir)
    y = mix + wet_amount * wet / (np.abs(wet).max() or 1)
    y = np.tanh(1.5 * y / (np.abs(y).max() or 1))
    t = secs(seconds)[: tr.n]
    y *= np.minimum(1, t / 0.01) * np.minimum(1, (seconds - t) / 0.6)
    y = y / (np.abs(y).max() or 1) * 0.89

    width = int(SR * rng.uniform(0.008, 0.016))
    stereo = np.stack([y, np.roll(y, width)], 1)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())

    names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    return f"{desc}, key {names[key % 12]} minor"
