#!/usr/bin/env python3
"""
Odyssey seat-release monitor  (browser-rendering version)
=========================================================

Alerts you when a NEW date's showtimes go on sale for "The Odyssey" (IMAX 70MM)
at Regal Mall of Georgia. Regal releases dates one at a time and good seats sell
fast, so this watches for the next drop.

WHY THIS USES A HEADLESS BROWSER (and the earlier fetch version couldn't work)
-----------------------------------------------------------------------------
Fandango serves an empty shell and fills in showtimes with JavaScript AFTER the
page loads. A plain HTTP fetch only ever sees "Loading calendar / Loading
format filters" placeholders -- the real showtimes are never in the raw HTML.
So we drive a real (headless) browser that runs the page's own JavaScript, then
read what actually rendered. Fandango has no human-check, so this is just normal
page rendering -- nothing is being bypassed. (Regal's own site DOES have a
human-check, which is why we don't touch it.)

HOW IT DECIDES A DATE IS ON SALE
--------------------------------
On future dates The Odyssey isn't listed at all (other movies fill the page).
So after the page renders, we read the movie-times section and check whether
"The Odyssey" appears there WITH showtimes. Absent = not on sale yet.

FIRST RUN -- confirm it works, paste me the output:
    python monitor.py --check
Aug 12 should come back has_showtimes=True with a nonzero time count. If it
doesn't, paste the printed region snippet and I'll adjust the selector.

SETUP (one time):
    pip install playwright
    playwright install chromium
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Playwright not installed. Run:\n"
             "    pip install playwright\n"
             "    playwright install chromium")

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
BASE_URL = "https://www.fandango.com/regal-mall-of-georgia-aankx/theater-page"
FORMAT = "IMAX 70MM"
TITLE_KEY = "the odyssey"
CHECK_AHEAD = 4                 # how many upcoming days to probe each run
NAV_TIMEOUT = 30000            # ms per page
STATE_FILE = os.path.join(os.path.dirname(__file__), "seen_dates.json")
GITHUB_MENTION = os.environ.get("GH_MENTION", "YOUR_GITHUB_USERNAME")
# ---------------------------------------------------------------------------

SHOWTIME_RE = re.compile(r"\b\d{1,2}:\d{2}\s?[apAP]\b")

# Wait until the JS-rendered showtimes have settled: skeleton placeholders gone,
# and either real times or an explicit empty-state have appeared.
_WAIT_JS = """
() => {
  const sec = document.querySelector('#lazyload-movie-times');
  if (!sec) return false;
  if (sec.querySelector('.showtimes-placeholder__loading')) return false; // still loading
  const t = sec.innerText || '';
  return /\\d{1,2}:\\d{2}\\s?[apAP]/.test(t) || /no showtimes/i.test(t) || t.trim().length > 0;
}
"""

_REGION_JS = """
() => {
  const el = document.querySelector('#lazyload-movie-times')
          || document.querySelector('main.tdp') || document.body;
  return el.innerText || '';
}
"""


def date_url(d: str) -> str:
    from urllib.parse import urlencode, quote
    return f"{BASE_URL}?{urlencode({'format': FORMAT, 'date': d}, quote_via=quote)}"


def probe_date(page, d: str) -> dict:
    info = {"date": d, "ok": False, "odyssey_in_region": False,
            "times": 0, "has": False, "region_snippet": "", "err": None}
    try:
        page.goto(date_url(d), wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        try:
            page.wait_for_function(_WAIT_JS, timeout=15000)
        except Exception:
            page.wait_for_timeout(3000)  # settle even if the wait condition never tripped
        region = page.evaluate(_REGION_JS) or ""
        info["ok"] = True
        info["odyssey_in_region"] = TITLE_KEY in region.lower()
        info["times"] = len(SHOWTIME_RE.findall(region))
        info["has"] = info["odyssey_in_region"] and info["times"] > 0
        info["region_snippet"] = " ".join(region.split())[:220]
    except Exception as e:
        info["err"] = str(e)
    return info


def upcoming_dates(seen: set, span: int) -> list:
    base = max((dt.date.fromisoformat(x) for x in seen), default=dt.date.today())
    start = max(base + dt.timedelta(days=1), dt.date.today())
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(span)]


def load_seen():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE) as f:
        return set(json.load(f))


def save_seen(dates):
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(dates), f, indent=2)


def notify_github_issue(new_dates) -> bool:
    import urllib.request, urllib.error
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return False
    body = (f"@{GITHUB_MENTION} showtimes just opened for **The Odyssey** "
            f"(IMAX 70MM) at Regal Mall of Georgia:\n\n"
            + "\n".join(f"- **{d}** -> {date_url(d)}" for d in sorted(new_dates))
            + "\n\nGrab seats now. (Regal's own site will still make you do the "
              "human check when you open it.)")
    payload = json.dumps({"title": f"Odyssey showtimes up: {', '.join(sorted(new_dates))}",
                          "body": body}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues",
                                 data=payload,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status in (200, 201)
    except urllib.error.HTTPError as e:
        print(f"[warn] GitHub issue failed: {e}", file=sys.stderr)
        return False


def notify_macos(new_dates) -> bool:
    if sys.platform != "darwin":
        return False
    msg = "Odyssey showtimes up: " + ", ".join(sorted(new_dates))
    os.system(f'osascript -e \'display notification "{msg}" '
              f'with title "Odyssey tickets" sound name "Glass"\'')
    return True


def _browser(pw):
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(
        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
        viewport={"width": 1280, "height": 900})
    return b, ctx


def cmd_check():
    seen = load_seen() or {"2026-08-12"}
    dates = ["2026-08-12"] + upcoming_dates(seen, CHECK_AHEAD)
    print("Diagnostic (Aug 12 should show has_showtimes=True, times>0):\n")
    with sync_playwright() as pw:
        b, ctx = _browser(pw)
        page = ctx.new_page()
        for d in dates:
            r = probe_date(page, d)
            if r["err"]:
                print(f"  {d}: ERROR {r['err']}")
            else:
                print(f"  {d}: has={r['has']}  times={r['times']}  "
                      f"odyssey_present={r['odyssey_in_region']}")
                print(f"        region: {r['region_snippet']!r}")
        b.close()


def cmd_run():
    seen = load_seen()
    first_run = seen is None
    if first_run:
        seen = set()
    dates = upcoming_dates(seen if seen else {"2026-08-12"}, CHECK_AHEAD)

    newly = set()
    with sync_playwright() as pw:
        b, ctx = _browser(pw)
        page = ctx.new_page()
        for d in dates:
            r = probe_date(page, d)
            if r["err"]:
                print(f"[warn] {d}: {r['err']}", file=sys.stderr)
            else:
                print(f"[info] {d}: has={r['has']} times={r['times']} "
                      f"odyssey_present={r['odyssey_in_region']}")
                if r["has"] and d not in seen:
                    newly.add(d)
        b.close()

    if first_run:
        save_seen(seen | newly)
        print(f"[info] First run recorded {sorted(newly)} silently, no alerts.")
        return
    if not newly:
        print("[info] No new dates on sale.")
        return
    print(f"[ALERT] Newly on sale: {sorted(newly)}")
    # Expose the new dates to later workflow steps (e.g. an email step) via
    # $GITHUB_ENV, so `env.NEW_DATES` is available to them.
    gh_env = os.environ.get("GITHUB_ENV")
    if gh_env:
        with open(gh_env, "a") as f:
            f.write(f"NEW_DATES={', '.join(sorted(newly))}\n")
    if not (notify_github_issue(newly) or notify_macos(newly)):
        print("[warn] No notifier configured; printing only.", file=sys.stderr)
    save_seen(seen | newly)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="diagnostic probe; prints per-date results, no alerts")
    args = ap.parse_args()
    cmd_check() if args.check else cmd_run()


if __name__ == "__main__":
    main()
