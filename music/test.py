"""Try music prompts before they go into prompts.json. Never posts anything.

Each prompt gets two 7-second clips with different seeds, finished the same way as the
daily clips (fades, -14 LUFS), saved to music/tests/NAME/ with a list.txt that says
which prompt made which file. The poster never reads music/tests/.

Usage:
  python music/test.py --name round1 --prompt "dark phonk, 140 BPM, ..." --prompt "..."
  python music/test.py --name round1      with no prompts, tries the four built-in styles below
"""

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

import generate as g

TESTS = g.HERE / "tests"
TAKES = 2

# Four very different dark directions, for a first round when no prompts are given.
DEFAULT_PROMPTS = [
    "dark phonk, 140 BPM, distorted 808 bass, cowbell melody, hard trap drums, menacing and aggressive, gritty, instrumental",
    "epic dark orchestral, 85 BPM, low brass, war drums, staccato strings, ominous and powerful, huge and wide, instrumental",
    "dark synthwave, 100 BPM, analog bass arpeggio, gated drums, cold lead synth, brooding and driven, neon and cold, instrumental",
    "dark drill beat, 142 BPM, sliding 808 bass, dark piano, rapid hi-hats, cold and serious, tight and punchy, instrumental",
]


def main():
    parser = argparse.ArgumentParser(description="Try music prompts.")
    parser.add_argument("--name", required=True, help="folder name under music/tests/")
    parser.add_argument("--prompt", action="append", default=[], help="a prompt to try; repeat for more")
    args = parser.parse_args()

    prompts = [p.strip() for p in args.prompt if p.strip()] or DEFAULT_PROMPTS
    folder = TESTS / args.name
    folder.mkdir(parents=True, exist_ok=True)
    rows, summary = [], []
    for i, prompt in enumerate(prompts, start=1):
        if not prompt.endswith("instrumental"):
            prompt = f"{prompt}, instrumental"
        for take in range(TAKES):
            seed = random.randrange(2 ** 31)
            g.log(f"Prompt {i}, take {take + 1}, seed {seed}: {prompt}")
            y, sr = g.generate_raw(prompt, seed)
            passed, metrics = g.score(y, sr)
            raw = folder / "_raw.wav"
            done = folder / "_done.wav"
            g.write_wav(raw, y[: int(sr * g.CUT_SECONDS)] / (np.abs(y).max() or 1) * 0.9, sr)
            g.master(raw, done, g.CUT_SECONDS)
            mp3 = folder / f"prompt{i}_take{take + 1}.mp3"
            g.ffmpeg("-i", str(done), "-c:a", "libmp3lame", "-b:a", g.MP3_BITRATE, str(mp3))
            raw.unlink()
            done.unlink()
            note = "" if passed else " (failed the quality check, the daily job would skip it)"
            rows.append(f"{mp3.name}  seed {seed}{note}\n  {prompt}")
            summary.append({"file": mp3.name, "prompt": prompt, "seed": seed, "passed": passed, **metrics})
    (folder / "list.txt").write_text("\n\n".join(rows) + "\n")
    (folder / "scores.json").write_text(json.dumps(summary, indent=2) + "\n")
    g.log(f"Saved {len(rows)} clips to music/tests/{args.name}")


if __name__ == "__main__":
    sys.exit(main())
