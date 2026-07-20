# Odyssey seat-release monitor

Alerts you when a **new date's showtimes go on sale** for *The Odyssey* (IMAX
70MM) at Regal Mall of Georgia. Regal releases dates one at a time and good
seats go fast, so this watches for the next drop.

## Why it renders a browser (and why the simple version couldn't work)

Fandango serves an **empty shell** and fills in showtimes with JavaScript after
the page loads. A plain HTTP fetch only ever sees "Loading calendar / Loading
format filters" — the real showtimes are never in the raw HTML. So this monitor
drives a headless browser that runs the page's own JavaScript, then reads what
rendered. Fandango has no human-check, so this is just normal page rendering,
not bypassing anything. (Regal's own site *does* have a human-check — that's why
we watch Fandango instead.)

**How it decides a date is on sale:** on future dates The Odyssey isn't listed
at all (other movies fill the page). After the page renders, the monitor reads
the movie-times section and checks whether "The Odyssey" appears there with
showtimes. Absent = not on sale yet.

## Setup

One-time install:

```bash
pip install playwright
playwright install chromium
```

### STEP 1 — confirm it works (paste me the output)

```bash
python monitor.py --check
```

You want Aug 12 to show `has=True times=5`. Future dates should show
`has=False`. If Aug 12 shows `has=False`, paste the printed `region:` snippet
and I'll fix the selector.

### STEP 2 — run it on a schedule

**Local on your Mac (recommended)** — residential IP, native notification, no
tokens. Your Mac must be awake/online.

```bash
cd odyssey-monitor
python monitor.py            # test once
# schedule every 20 min:
( crontab -l 2>/dev/null; echo "*/20 * * * * cd $(pwd) && /usr/bin/python3 monitor.py >> monitor.log 2>&1" ) | crontab -
```

**GitHub Actions (alternative)** — upload these files to a private repo, add an
Actions *Variable* `GH_MENTION` = your GitHub username, enable workflows. It
installs Chromium and runs on a schedule, opening an issue that @mentions you on
a new date. Note: GitHub runs on datacenter IPs, which sites sometimes treat
differently — if it acts up, use the local option.

## State / seeding

`seen_dates.json` is seeded with `2026-08-12`, so probing starts at Aug 13 and
won't false-alert on 12. Add any other already-on-sale dates to that file to
avoid a catch-up alert on first run.

## Tuning (`monitor.py`)

- `CHECK_AHEAD` — how many upcoming days to probe each run (bump if Regal drops
  several dates at once).
- Schedule frequency — the `cron` lines in `monitor.yml` or your crontab entry.
