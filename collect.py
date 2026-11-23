"""Viral Idea Radar - local signal collector.

Pulls real trend data that the cloud scan can't reach and writes it to
signals/latest.json (plus a timestamped copy in signals/history/).
The cloud scan reads that file from the public GitHub repo.

Standard library only, so it runs on any Python 3.9+ with no installs.

Sources (each one is skipped cleanly if it fails or has no key):
  reddit         public hot.json for the subreddits in config.json
  google_trends  Google Trends "trending now" RSS feed (US)
  youtube        YouTube Data API v3: most-popular chart + fresh Shorts outliers
                 (needs YOUTUBE_API_KEY)
  instagram      Instagram Graph API: the account's own reels and their insights
                 (needs IG_ACCESS_TOKEN and IG_USER_ID)

Usage:
  python collect.py            collect everything and write signals/
  python collect.py --dry-run  collect and print a summary, write nothing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SIGNALS = ROOT / "signals"
HISTORY = SIGNALS / "history"
UA = "windows:viral-idea-radar:v1.0 (personal trend research)"


# ---------------------------------------------------------------- helpers

def load_env(path: Path) -> None:
    """Read KEY=VALUE lines from .env into os.environ (without overriding)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def http_get(url: str, params: dict | None = None, timeout: int = 20) -> bytes:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_json(url: str, params: dict | None = None, timeout: int = 20):
    return json.loads(http_get(url, params, timeout).decode("utf-8"))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clip(text: str | None, n: int = 200) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------- reddit

def parse_reddit_listing(data: dict, sub: str, now_ts: float) -> list[dict]:
    posts = []
    for child in (data.get("data") or {}).get("children", []):
        p = child.get("data") or {}
        if p.get("stickied") or p.get("over_18"):
            continue
        age_h = max(0.25, (now_ts - float(p.get("created_utc", now_ts))) / 3600)
        score = int(p.get("score") or 0)
        comments = int(p.get("num_comments") or 0)
        posts.append({
            "id": p.get("id"),
            "subreddit": sub,
            "title": clip(p.get("title"), 220),
            "score": score,
            "comments": comments,
            "age_hours": round(age_h, 1),
            "velocity": round(score / age_h, 1),          # upvotes per hour
            "comment_rate": round(comments / age_h, 1),    # comments per hour
            "url": "https://www.reddit.com" + (p.get("permalink") or ""),
        })
    return posts


def collect_reddit(cfg: dict, errors: list) -> list[dict]:
    out = []
    now_ts = time.time()
    for sub in cfg.get("subreddits", []):
        try:
            data = http_json(f"https://www.reddit.com/r/{sub}/hot.json", {"limit": 30, "raw_json": 1})
            posts = parse_reddit_listing(data, sub, now_ts)
            posts.sort(key=lambda x: x["velocity"], reverse=True)
            out.extend(posts[: cfg.get("per_sub", 6)])
        except Exception as e:  # noqa: BLE001 - keep going on any source failure
            errors.append(f"reddit r/{sub}: {e}")
        time.sleep(1.2)  # stay well under Reddit's unauthenticated rate limit
    out.sort(key=lambda x: x["velocity"], reverse=True)
    return out[: cfg.get("max_total", 60)]


# ---------------------------------------------------------------- google trends

HT = "{https://trends.google.com/trending/rss}"


def parse_trends_rss(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter("item"):
        news = []
        for ni in it.findall(f"{HT}news_item"):
            news.append({
                "title": clip(ni.findtext(f"{HT}news_item_title"), 160),
                "source": ni.findtext(f"{HT}news_item_source") or "",
                "url": ni.findtext(f"{HT}news_item_url") or "",
            })
        items.append({
            "query": (it.findtext("title") or "").strip(),
            "approx_traffic": (it.findtext(f"{HT}approx_traffic") or "").strip(),
            "started": (it.findtext("pubDate") or "").strip(),
            "news": news[:2],
        })
    return items


def collect_google_trends(cfg: dict, errors: list) -> list[dict]:
    try:
        geo = cfg.get("geo", "US")
        return parse_trends_rss(http_get("https://trends.google.com/trending/rss", {"geo": geo}))
    except Exception as e:  # noqa: BLE001
        errors.append(f"google_trends: {e}")
        return []


# ---------------------------------------------------------------- youtube

YT = "https://www.googleapis.com/youtube/v3"


def _yt_video(v: dict, now: datetime) -> dict:
    sn, st = v.get("snippet") or {}, v.get("statistics") or {}
    pub = sn.get("publishedAt")
    age_h = None
    if pub:
        age_h = max(0.5, (now - datetime.fromisoformat(pub.replace("Z", "+00:00"))).total_seconds() / 3600)
    views = int(st.get("viewCount") or 0)
    return {
        "id": v.get("id"),
        "title": clip(sn.get("title"), 160),
        "channel": sn.get("channelTitle"),
        "published": pub,
        "views": views,
        "likes": int(st.get("likeCount") or 0),
        "comments": int(st.get("commentCount") or 0),
        "views_per_hour": round(views / age_h) if age_h else None,
        "url": f"https://www.youtube.com/watch?v={v.get('id')}",
    }


def collect_youtube(cfg: dict, errors: list) -> dict:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return {"skipped": "no YOUTUBE_API_KEY in .env"}
    now = now_utc()
    out = {"popular": [], "shorts": []}
    # 1) Most-popular chart per category (1 quota unit each)
    for cat in cfg.get("popular_categories", [20, 17, 24, 23]):
        try:
            data = http_json(f"{YT}/videos", {"part": "snippet,statistics", "chart": "mostPopular",
                                               "regionCode": cfg.get("region", "US"),
                                               "videoCategoryId": cat, "maxResults": 15, "key": key})
            for v in data.get("items", []):
                row = _yt_video(v, now)
                row["category"] = cat
                out["popular"].append(row)
        except Exception as e:  # noqa: BLE001
            errors.append(f"youtube popular cat {cat}: {e}")
    # 2) Fresh Shorts outliers per keyword (search = 100 quota units each, keep the list short)
    after = iso(now - timedelta(hours=cfg.get("shorts_window_hours", 48)))
    ids = []
    for kw in cfg.get("shorts_keywords", [])[: cfg.get("max_keyword_searches", 6)]:
        try:
            data = http_json(f"{YT}/search", {"part": "id", "q": kw, "type": "video", "videoDuration": "short",
                                               "order": "viewCount", "publishedAfter": after,
                                               "maxResults": 10, "key": key})
            ids += [(kw, it["id"]["videoId"]) for it in data.get("items", []) if it.get("id", {}).get("videoId")]
        except Exception as e:  # noqa: BLE001
            errors.append(f"youtube search '{kw}': {e}")
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            data = http_json(f"{YT}/videos", {"part": "snippet,statistics", "id": ",".join(v for _, v in chunk), "key": key})
            kw_by_id = {v: kw for kw, v in chunk}
            for v in data.get("items", []):
                row = _yt_video(v, now)
                row["keyword"] = kw_by_id.get(v.get("id"))
                out["shorts"].append(row)
        except Exception as e:  # noqa: BLE001
            errors.append(f"youtube videos: {e}")
    out["shorts"].sort(key=lambda r: r.get("views_per_hour") or 0, reverse=True)
    out["popular"].sort(key=lambda r: r.get("views_per_hour") or 0, reverse=True)
    out["popular"] = out["popular"][:40]
    out["shorts"] = out["shorts"][:40]
    return out


# ---------------------------------------------------------------- instagram

IG_METRIC_SETS = [
    # Newest names first; older API versions reject some, so fall back.
    ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions",
     "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"],
    ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions"],
    ["plays", "reach", "likes", "comments", "shares", "saved", "total_interactions"],
    ["reach", "saved", "shares"],
]


def parse_ig_insights(data: dict) -> dict:
    out = {}
    for m in data.get("data", []):
        vals = m.get("values") or [{}]
        val = m.get("total_value", {}).get("value") if "total_value" in m else vals[0].get("value")
        out[m.get("name")] = val
    if "plays" in out and "views" not in out:
        out["views"] = out.pop("plays")
    if out.get("ig_reels_avg_watch_time") is not None:
        out["avg_watch_seconds"] = round(out.pop("ig_reels_avg_watch_time") / 1000, 1)  # API returns ms
    return out


def collect_instagram(cfg: dict, errors: list) -> dict:
    if not cfg.get("enabled", True):
        return {"skipped": "disabled in config.json (instagram.enabled = false)"}
    token, user = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    if not token or not user:
        return {"skipped": "no IG_ACCESS_TOKEN / IG_USER_ID in .env"}
    base = cfg.get("graph_base", "https://graph.instagram.com") + "/" + cfg.get("api_version", "v23.0")
    posts = []
    try:
        media = http_json(f"{base}/{user}/media", {
            "fields": "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count",
            "limit": cfg.get("max_posts", 40), "access_token": token})
    except urllib.error.HTTPError as e:
        errors.append(f"instagram media: HTTP {e.code} {clip(e.read().decode('utf-8', 'ignore'), 300)}")
        return {"posts": []}
    except Exception as e:  # noqa: BLE001
        errors.append(f"instagram media: {e}")
        return {"posts": []}
    for m in media.get("data", []):
        row = {
            "id": m.get("id"),
            "caption": clip(m.get("caption"), 200),
            "type": m.get("media_product_type") or m.get("media_type"),
            "permalink": m.get("permalink"),
            "posted_at": m.get("timestamp"),
            "likes": m.get("like_count"),
            "comments": m.get("comments_count"),
        }
        for metrics in IG_METRIC_SETS:
            try:
                ins = http_json(f"{base}/{m['id']}/insights", {"metric": ",".join(metrics), "access_token": token})
                row.update(parse_ig_insights(ins))
                break
            except urllib.error.HTTPError:
                continue  # unsupported metric for this media type / version: try a smaller set
            except Exception as e:  # noqa: BLE001
                errors.append(f"instagram insights {m.get('id')}: {e}")
                break
        posts.append(row)
    return {"posts": posts}


# ---------------------------------------------------------------- momentum vs last run

def add_momentum(current: dict, previous: dict | None) -> None:
    """Mark what's new or climbing since the previous snapshot."""
    if not previous:
        return
    prev_reddit = {p["id"]: p for p in previous.get("reddit", []) if p.get("id")}
    for p in current.get("reddit", []):
        old = prev_reddit.get(p["id"])
        p["new_since_last_run"] = old is None
        if old:
            p["score_gain"] = p["score"] - old.get("score", 0)
    prev_q = {t["query"].lower() for t in previous.get("google_trends", [])}
    for t in current.get("google_trends", []):
        t["new_since_last_run"] = t["query"].lower() not in prev_q


# ---------------------------------------------------------------- main

def prune_history(days: int) -> None:
    cutoff = time.time() - days * 86400
    for f in HISTORY.glob("*.json"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_env(ROOT / ".env")
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    started = now_utc()

    signals = {
        "generated_at": iso(started),
        "reddit": collect_reddit(cfg.get("reddit", {}), errors),
        "google_trends": collect_google_trends(cfg.get("google_trends", {}), errors),
        "youtube": collect_youtube(cfg.get("youtube", {}), errors),
        "instagram": collect_instagram(cfg.get("instagram", {}), errors),
    }
    latest = SIGNALS / "latest.json"
    previous = None
    if latest.exists():
        try:
            previous = json.loads(latest.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
    add_momentum(signals, previous)
    signals["errors"] = errors
    signals["took_seconds"] = round((now_utc() - started).total_seconds(), 1)

    yt = signals["youtube"]
    summary = (f"reddit={len(signals['reddit'])} trends={len(signals['google_trends'])} "
               f"yt_popular={len(yt.get('popular', []))} yt_shorts={len(yt.get('shorts', []))} "
               f"ig_posts={len(signals['instagram'].get('posts', []))} errors={len(errors)}")
    print(summary)
    for e in errors:
        print("  !", e)
    if args.dry_run:
        return 0

    HISTORY.mkdir(parents=True, exist_ok=True)
    body = json.dumps(signals, ensure_ascii=False, indent=1)
    latest.write_text(body, encoding="utf-8")
    (HISTORY / (started.strftime("%Y%m%d-%H%M") + ".json")).write_text(body, encoding="utf-8")
    prune_history(cfg.get("keep_history_days", 7))
    return 0


if __name__ == "__main__":
    sys.exit(main())
