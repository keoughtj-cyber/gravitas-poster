# gravitas-poster

Posts the day's GRAVITAS practice to every connected social account, once a day, with no computer of yours switched on.

Every morning GitHub runs `post_daily.py`, which:

1. Reads the published `library_publish` CSV from the GRAVITAS Google Sheet.
2. Picks the day's Base practice (same rule as the app: pillar by day, shuffled pool per pillar).
3. Draws a 1080x1350 black card in the gravitas_ccr style (GRAVITAS, date, BUILD plus the pillar, practice, why in italics) and commits it to `cards/`.
4. Schedules it on Buffer for `POST_TIME` with a caption written for each network (`captions.json`).
5. At 7 p.m. (`REEL_TIME`) it also posts an Instagram reel: a 7-second 9:16 video with a new original track composed for that date by `music.py` (key, scale, chords, tempo, instruments, and rhythm all change daily, nothing to license) of one Focus area card (the area rotates daily through Habits, Relationships, Career, Calm, and Fitness) with the Focus caption. `REEL_POST` turns it off, `REEL_TIME` moves it. The video is built with the bundled ffmpeg from `imageio-ffmpeg` and served to Buffer through jsDelivr so it arrives as video/mp4.
6. Writes `posted/DATE.json` so a re-run never posts twice.

### Instagram look (`ig_design.py`)

Instagram gets its own design. X and LinkedIn keep the plain card above.

- Both reels are motion reels: the practice in large type from the first frame, the why fading in under it, then "Do it once. Then tell us how it went." with the follow line
- The Story is a restyled 9:16 still: III mark, pillar color, larger type, and the date in the top right.
- At `CAROUSEL_TIME` (default 12:00) a 3-slide carousel goes to the feed: the practice, why it works (principle and research source from `ig_extra.csv`), and a save and send slide. It uses a Focus area that is not the reel's or the Base post's, with the same practice as that area's X post.
- `IG_DESIGN=false` brings back the plain card on Instagram. `CAROUSEL_POST=false` stops the carousel.
- A manual run (Actions, Daily post, Run workflow) can post only some networks (`services`, for example `instagram`) and only some posts (`only`, for example `base,story,carousel`). Tick Post again when that date already ran; posts outside `only` are left alone.
- Every Instagram video gets a daily AI music track that has never been posted: the morning reel and the evening reel. The carousel is still images with no music, since Instagram only lets music span a whole carousel from its own app. `cards/music_used.json` maps each track's seed to the post that used it. When no unposted AI track is left, `music.py` composes one. The manual run's `fresh_music` box composes new tracks for that run.
- To try new music prompts, run Actions, Music test, Run workflow, and type up to four prompts (leave them blank for four built-in dark styles). It saves two 7-second clips per prompt to `music/tests/` with a `list.txt` of which prompt made which file. The poster never uses these clips; put a winning prompt in `music/prompts.json` to use it.
- `ig_extra.csv` holds id, concept, and source for every library practice, for the carousel's why-it-works slide.

Cost to start: $0 (public GitHub repo, Buffer Free plan, up to 3 accounts).

## Setup (about 30 minutes, once)

### 1. Make the social accounts ready

- Instagram: switch the account to a Professional account (Settings, Account type and tools, Switch to professional account, pick Creator or Business). Buffer can only auto-publish to professional accounts.
- X, LinkedIn, Threads, and Facebook need nothing special. For LinkedIn, decide between your personal profile and a GRAVITAS company page (Buffer supports both).

### 2. Buffer

1. Sign up at buffer.com (Free plan).
2. Connect up to 3 channels. Recommended free three: Instagram, X, and LinkedIn.
3. Open publish.buffer.com/settings/api and create an API key. Copy it.

### 3. GitHub repo

1. Create a new **public** repository on github.com named `gravitas-poster`. Public is required because Buffer and Instagram download the card from a public link. Nothing secret lives in the code.
2. Upload every file in this folder, keeping the folders (`.github/workflows/daily-post.yml`, `fonts/`, `cards/`, `posted/`, `assets/`). On github.com: Add file, Upload files, drag the whole folder in. If the `.github` folder does not upload (it is hidden on a Mac, press Cmd+Shift+period in Finder to show it), create it with Add file, Create new file, and type `.github/workflows/daily-post.yml` as the name, then paste the contents.

### 4. Secrets and settings

In the repo: Settings, Secrets and variables, Actions.

Secrets tab:
- `BUFFER_API_KEY`: the key from step 2.

Variables tab:
- `LIBRARY_CSV_URL` (required): the published CSV link of the `library_publish` tab. In the sheet: File, Share, Publish to web, pick the `library_publish` tab, Comma-separated values, Publish, copy the link.
- `POST_TIME` (optional, default `07:00`), `AREA_TIME` (the one X focus post, default `19:00`; X gets two posts a day), `REEL_TIME` (default `19:00`), and `POST_TZ` (default `America/New_York`).
- `APP_LINK` (optional): App Store link once the app is live. Added to LinkedIn and Facebook captions only.
- `BUFFER_SERVICES` (optional): limit which Buffer channels get posts, for example `instagram,twitter,linkedin`. Blank means every connected channel.

### 5. Test run

1. Actions tab, Daily post, Run workflow. Leave the date blank.
2. When it finishes (about a minute), open `cards/` to see the card, and open Buffer to see three scheduled posts.
3. If you want to look before anything is scheduled, run it locally instead (step 7).

From now on it runs every morning by itself. Buffer publishes at `POST_TIME`.

### 6. Turning it off or skipping a day

- Pause: Actions tab, Daily post, the three dots, Disable workflow.
- Skip one post: delete it in Buffer before it goes out.

### 7. Run it on your Mac (optional)

```
cd gravitas-poster
pip3 install -r requirements.txt
LIBRARY_CSV_URL="your published csv link" python3 post_daily.py preview
```

`preview` prints every caption and writes `cards/preview.jpg`. It never contacts Buffer.

### 8. Matching the app

The pick is a direct port of `DailyPlanner.computeBaseItem(for:)`: seed `0x6761766974617321`, day 0 is 2026-01-01, pillar order Confidence, Character, Respect, FNV-1a pillar hash, SplitMix64, and Swift's own `shuffle(using:)` algorithm. So the post shows the same practice as the app's Base view, as long as the published sheet is the same library the app reads.

One thing the server cannot copy: `excludingActiveElsewhere`, which depends on what each person has active on their own phone. If it removes items for someone, their Base can differ from the post.

## Files

- `post_daily.py`: the whole job (render, publish, preview).
- `captions.json`: caption variants per network. Edit freely, keep the writing rules (no emojis, Oxford comma, never the words confidence, character, or respect, never start with Today). Variants rotate by day.
- `.github/workflows/daily-post.yml`: the daily schedule.
- `fonts/`: Inter (SIL Open Font License, see `fonts/LICENSE-OFL.txt`).

## If something goes wrong

- The run is red: open it in the Actions tab. The last lines say which channel failed and Buffer's reason. Fix it, then Run workflow again. Channels that already succeeded are skipped.
- "Card image is not reachable": the repo is private. Make it public, or host cards on Cloudflare R2 and set `IMAGE_BASE_URL`.
- Instagram error about post type: Buffer changed its Instagram options. The script already retries without them; if it still fails, send Claude the error line.
- No run happened: GitHub sometimes delays scheduled runs at busy times, which is why the job runs hours before `POST_TIME`. GitHub also pauses schedules in repos with no activity for 60 days, but the daily card commit counts as activity.
