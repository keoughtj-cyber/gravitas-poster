# Daily music clip

Every morning at 11:00 UTC (7 a.m. Eastern in summer, 6 a.m. in winter), the Daily music
workflow makes one short, dark, instrumental clip with Stable Audio Open Small, running on
GitHub's free CPU runner. It never posts anything.

Output, per day, in `music/output/YYYY-MM-DD/`:
- `gravitas_YYYY-MM-DD_7s.mp3` (192 kbps) and `gravitas_YYYY-MM-DD_7s.wav`: the 7-second cut for reels.
- `gravitas_YYYY-MM-DD_full.wav`: the full 11-second clip.
- `meta.json`: date, pillar, prompt, seeds, every candidate's scores, model, and settings.

`music/output/latest/` always holds the newest cut as `gravitas_7s.mp3`, plus its `meta.json`.
Dated folders older than 60 days are deleted. Each run is also kept as a downloadable artifact
for 30 days (Actions tab, the run, Artifacts).

## How a clip is made

1. The pillar for the date (Confidence, Character, Respect, rotating daily from 2026-01-01, the
   same rotation as the app's Base practice) picks the mood words.
2. A prompt is built from `prompts.json` with the date as the seed:
   style, BPM, two or three instruments, mood, texture, instrumental.
3. Four 11-second candidates are generated (steps 8, cfg 1.0, pingpong sampler).
4. Candidates that are mostly silent, too quiet, or clipping are rejected. The steadiest of the
   rest wins. If all four fail, it retries once with the fixed pillar template, then fails the run.
5. The winner gets a 0.1-second fade-in, a 0.8-second fade-out, and loudness normalization to
   -14 LUFS with a -1 dB true-peak ceiling.

## Setup (once)

1. Create a free account at huggingface.co.
2. Open https://huggingface.co/stabilityai/stable-audio-open-small and accept the license.
3. Create a Read token at https://huggingface.co/settings/tokens.
4. In this repo: Settings, Secrets and variables, Actions, New repository secret.
   Name `HF_TOKEN`, paste the token.
5. Actions tab, Daily music, Run workflow.
6. Read `LICENSE_NOTE.md` before posting clips commercially.

## Run it yourself

Python 3.10 and ffmpeg.

```
pip install -r music/requirements.txt
python music/generate.py --dry-run                 # prompt, pillar, and seed only, no model
python music/generate.py --date 2026-10-19 --dry-run
HF_TOKEN=your_token python music/generate.py --date 2026-10-19
```

The same date always gives the same prompt and seeds.

## Reels

The daily reel (made by `post_daily.py` at about 5 a.m. Eastern) uses
`music/output/latest/gravitas_7s.mp3` when it is at most two days old. Because this job runs
later in the morning, each reel carries the previous morning's clip. Set the repository variable
`REEL_MUSIC_FROM_LATEST` to `false` to go back to the coded tracks.
