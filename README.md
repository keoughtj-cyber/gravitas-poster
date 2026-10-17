# gravitas-poster

Posts the day's GRAVITAS practice to every connected social account, once a day, with no computer of yours switched on.

Every morning GitHub runs `post_daily.py`, which:

1. Reads the published `library_publish` CSV from the GRAVITAS Google Sheet.
2. Picks the day's Base practice (same rule as the app: pillar by day, shuffled pool per pillar).
3. Draws a 1080x1350 dark card (III GRAVITAS logo, area label in the pillar color, practice, why, date) and commits it to `cards/`.
4. Schedules it on Buffer for `POST_TIME` with a caption written for each network (`captions.json`).
5. Writes `posted/DATE.json` so a re-run never posts twice.

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
3. Optional: put your real logo at `assets/logo.png` (white or light logo, transparent background). Without it the card draws a III mark and the GRAVITAS wordmark.

### 4. Secrets and settings

In the repo: Settings, Secrets and variables, Actions.

Secrets tab:
- `BUFFER_API_KEY`: the key from step 2.

Variables tab:
- `LIBRARY_CSV_URL` (required): the published CSV link of the `library_publish` tab. In the sheet: File, Share, Publish to web, pick the `library_publish` tab, Comma-separated values, Publish, copy the link.
- `POST_TIME` (optional, default `07:30`) and `POST_TZ` (default `America/New_York`).
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
