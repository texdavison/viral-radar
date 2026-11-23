# Viral Idea Radar: local collector

This folder collects real trend data for the @how_does_it_work1 idea pipeline and pushes it to a
public GitHub repo (the cloud scan can only read public repos). A cloud scheduled task ("Viral Idea Radar scan", 3x a day) reads
`signals/latest.json` from that repo, turns it into scored reel ideas, and writes them to the
Viral Idea Radar dashboard (https://claude.ai/artifact/98fJKAJz1xUpqrpcQ9TxKo).

## What's here
- `collect.py`: standard-library Python. Sources: Reddit hot posts (upvotes/hour), Google Trends
  "trending now" RSS, YouTube most-popular plus fresh Shorts outliers (needs `YOUTUBE_API_KEY`),
  and the account's own Instagram reels with insights (needs `IG_ACCESS_TOKEN` and `IG_USER_ID`).
  Every source is optional and fails soft; errors are listed in `signals/latest.json`.
- `config.json`: subreddits, YouTube keywords and categories, Instagram API settings. Edit freely.
- `run.ps1`: pull, collect, commit `signals/`, push. Writes `last-run.log`.
- `.env.example`: copy to `.env` for keys. `.env` is gitignored and must never be committed.

## First-time setup (Claude Code: do these steps for Tex, asking before anything that needs his input)
1. Check Python 3.9+ (`py --version` or `python --version`). If missing: `winget install Python.Python.3.12`.
2. Check git and GitHub CLI (`git --version`, `gh --version`). If missing: `winget install Git.Git GitHub.cli`,
   then `gh auth login` (Tex completes the browser sign-in himself).
3. Dry run: `py collect.py --dry-run`. Reddit and Google Trends should return rows with no keys.
4. Create the public repo and push (confirm `.env` is gitignored first):
   `git init -b main`, `git add .`, `git commit -m "collector"`,
   `gh repo create texdavison/viral-radar --public --source . --push`.
   Confirm `.env` is NOT in the commit.
5. Run once for real: `powershell -ExecutionPolicy Bypass -File run.ps1`, then check `last-run.log`
   and that `signals/latest.json` is on GitHub.
6. Schedule it every 3 hours with Task Scheduler:
   `schtasks /Create /TN "ViralRadarCollector" /SC HOURLY /MO 3 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"<full path>\run.ps1\"" /F`
   (use this folder's absolute path). Running only while Tex is signed in is fine.
7. Optional, any time: help Tex create a YouTube Data API key and put it in `.env`.
   Quota math: each run uses about 605 units (4 charts + 6 searches at 100 + 1 lookup); 8 runs/day is
   about 4,840 of the free 10,000.

## Instagram (when the founders grant admin)
Goal: fill `IG_ACCESS_TOKEN` and `IG_USER_ID` in `.env` so each run pulls the account's reels with
views, reach, likes, comments, shares, saves and average watch time. The cloud scan copies these into
the dashboard's Results tab automatically, which is what lets the scoring model learn.
Walk Tex through: the account must be a Professional (Business or Creator) account; create an app at
developers.facebook.com using the "Instagram API with Instagram login" product; add the account and
generate a token with `instagram_business_basic` and `instagram_business_manage_insights`; exchange it
for a long-lived token; get the user id from `GET https://graph.instagram.com/v23.0/me?fields=user_id,username`.
If Meta's current flow or metric names differ from this, follow Meta's current docs and update
`config.json` / `IG_METRIC_SETS` in `collect.py`. Remind Tex that long-lived tokens expire in about 60 days.

## Rules
- Never commit `.env`, tokens or keys. Never print tokens in chat.
- Keep `collect.py` standard-library only.
- Don't change the shape of `signals/latest.json` without also updating the cloud scan's instructions.
