"""Viral Idea Radar - local signal collector.

Pulls real trend data that the cloud scan can't reach and writes it to
signals/latest.json (plus a timestamped copy in signals/history/).
The cloud scan reads that file from the public GitHub repo.

Standard library only, so it runs on any Python 3.9+ with no installs.

Sources (each one is skipped cleanly if it fails or has no key):
  reddit         public hot.json for the subreddits in config.json
  google_trends  Google Trends "trending now" RSS feed (US), plus GB/CA/AU as google_trends_intl
  wikipedia      most-viewed Wikipedia articles, with day-over-day spike ratio (no key)
  hackernews     Hacker News front page via Algolia (no key)
  instagram_analysis  derived: outlier scores, rates and caption-feature lift from your own reels
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
import statistics
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


def collect_google_trends_intl(cfg: dict, us_rows: list[dict], errors: list) -> list[dict]:
    """Trending searches in other English-speaking regions. Things trending abroad often reach the US
    a day or two later. Rows already trending in the US are dropped."""
    seen = {r["query"].lower() for r in us_rows}
    out = []
    for geo in cfg.get("extra_geos", ["GB", "CA", "AU"]):
        try:
            rows = parse_trends_rss(http_get("https://trends.google.com/trending/rss", {"geo": geo}))
        except Exception as e:  # noqa: BLE001
            errors.append(f"google_trends {geo}: {e}")
            continue
        for r in rows[: cfg.get("intl_per_geo", 10)]:
            if r["query"].lower() in seen:
                continue
            seen.add(r["query"].lower())
            r["geo"] = geo
            out.append(r)
        time.sleep(0.5)
    return out


# ---------------------------------------------------------------- wikipedia

WIKI_SKIP_PREFIXES = ("Special:", "Wikipedia:", "Portal:", "Help:", "Category:", "File:", "Talk:",
                      "Template:", "User:")


def parse_wiki_top(data: dict) -> list[dict]:
    """Most-viewed English Wikipedia articles for one day, minus the Main Page and namespace pages."""
    rows = []
    for item in data.get("items", [])[:1]:
        for a in item.get("articles", []):
            title = a.get("article") or ""
            if title in ("Main_Page", "-") or title.startswith(WIKI_SKIP_PREFIXES):
                continue
            rows.append({"title": title.replace("_", " "), "views": int(a.get("views") or 0),
                         "rank": int(a.get("rank") or 0)})
    return rows


def collect_wikipedia(cfg: dict, errors: list) -> list[dict]:
    """Wikipedia daily pageviews: what people suddenly want to understand. Free, no key.
    Compares the latest full day to the day before to find what is spiking."""
    if not cfg.get("enabled", True):
        return []
    base = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access"
    today = now_utc().date()
    cur = prev = None
    for back in (1, 2):  # yesterday's data is sometimes not published yet
        d1, d0 = today - timedelta(days=back), today - timedelta(days=back + 1)
        try:
            cur = parse_wiki_top(http_json(f"{base}/{d1:%Y/%m/%d}"))
            prev = parse_wiki_top(http_json(f"{base}/{d0:%Y/%m/%d}"))
            break
        except Exception as e:  # noqa: BLE001
            last = e
    if cur is None:
        errors.append(f"wikipedia: {last}")
        return []
    prev_views = {r["title"]: r["views"] for r in prev}
    floor_prev = min(prev_views.values(), default=1) or 1   # a page missing from yesterday's top list had at most this
    min_views = cfg.get("min_views", 15000)
    out = []
    for r in cur:
        if r["views"] < min_views:
            continue
        old = prev_views.get(r["title"])
        r["prev_views"] = old
        r["new_in_top"] = old is None
        # For pages not in the previous list, views/floor is a conservative lower bound on the spike.
        r["growth_x"] = round(r["views"] / (old or floor_prev), 2)
        r["growth_is_lower_bound"] = old is None
        r["url"] = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(r["title"].replace(" ", "_"))
        out.append(r)
    out.sort(key=lambda r: (r["growth_x"], r["views"]), reverse=True)   # biggest spikes first
    return out[: cfg.get("max_total", 40)]


# ---------------------------------------------------------------- hacker news

def parse_hn(data: dict, now_ts: float) -> list[dict]:
    rows = []
    for h in data.get("hits", []):
        age_h = max(0.25, (now_ts - float(h.get("created_at_i") or now_ts)) / 3600)
        pts = int(h.get("points") or 0)
        rows.append({
            "id": h.get("objectID"),
            "title": clip(h.get("title"), 200),
            "points": pts,
            "comments": int(h.get("num_comments") or 0),
            "age_hours": round(age_h, 1),
            "velocity": round(pts / age_h, 1),
            "url": h.get("url") or "",
            "discussion": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
        })
    return rows


def collect_hackernews(cfg: dict, errors: list) -> list[dict]:
    """Hacker News front page. Skews tech, but 'how X works' stories do well there. Free, no key."""
    if not cfg.get("enabled", True):
        return []
    try:
        data = http_json("https://hn.algolia.com/api/v1/search", {"tags": "front_page", "hitsPerPage": 40})
    except Exception as e:  # noqa: BLE001
        errors.append(f"hackernews: {e}")
        return []
    rows = [r for r in parse_hn(data, time.time()) if r["points"] >= cfg.get("min_points", 50)]
    rows.sort(key=lambda r: r["velocity"], reverse=True)
    return rows[: cfg.get("max_total", 20)]


# ---------------------------------------------------------------- youtube

YT ="https://www.googleapis.com/youtube/v3"


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


def load_manual_instagram(errors: list) -> dict | None:
    """Fallback until the API token exists: public stats typed/scraped into ig_manual.json.
    Same row shape as the API path (plus source="manual"); shares/saves/reach/watch time are absent."""
    path = ROOT / "ig_manual.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        errors.append(f"instagram manual file: {e}")
        return None
    handle = data.get("handle", "how_does_it_work1")
    posts = []
    for r in data.get("reels", []):
        posts.append({
            "id": r.get("id"),
            "caption": clip(r.get("caption") or r.get("topic"), 700),  # long enough to keep the hashtags
            "type": "REELS",
            "permalink": f"https://www.instagram.com/{handle}/reel/{r.get('id')}/",
            "posted_at": r.get("date"),
            "likes": r.get("likes"),
            "comments": r.get("comments"),
            "views": r.get("views"),
            "source": "manual",
        })
    return {"posts": posts, "source": "manual", "manual_scraped_at": data.get("scraped_at"),
            "followers": data.get("followers"),
            "note": "Public counts only: no shares, saves, reach or watch time until the API token is set."}


def collect_instagram(cfg: dict, errors: list) -> dict:
    token, user = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    if not cfg.get("enabled", True) or not token or not user:
        manual = load_manual_instagram(errors)
        if manual:
            return manual
        if not cfg.get("enabled", True):
            return {"skipped": "disabled in config.json (instagram.enabled = false)"}
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


# ---------------------------------------------------------------- learn from your own reels

CAPTION_FEATURES = {
    "send_this_cta": lambda c: "send this" in c,
    "type_at_cta": lambda c: "type @" in c,
    "follow_or_name_ask": lambda c: "follow" in c or "name the" in c,
    "what_if": lambda c: "what if" in c or "#whatif" in c,
    "pov": lambda c: c.startswith("pov") or " pov:" in c,
    "question_in_hook": lambda c: "?" in c.split("\n")[0],
}


def _median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def analyze_instagram(ig: dict) -> dict | None:
    """Turn the account's own reels into 'what worked' stats so ideas can be scored against real results.
    Uses only likes/comments/views, so it works for both the manual file and the API path."""
    posts = [p for p in ig.get("posts", []) if p.get("views")]
    if len(posts) < 3:
        return None
    followers = ig.get("followers")
    views = [p["views"] for p in posts]
    med = statistics.median(views)
    rows = []
    for p in posts:
        v = p["views"]
        row = {
            "id": p["id"], "views": v,
            "outlier_x": round(v / med, 1),                       # views vs this account's median reel
            "like_rate_pct": round(100 * (p.get("likes") or 0) / v, 2),
            "comment_rate_pct": round(100 * (p.get("comments") or 0) / v, 2),
        }
        if followers:
            row["views_per_follower"] = round(v / followers, 1)
        rows.append(row)
    rows.sort(key=lambda r: r["views"], reverse=True)

    by_id = {p["id"]: p for p in posts}
    features = {}
    for name, test in CAPTION_FEATURES.items():
        yes = [p["views"] for p in posts if test((p.get("caption") or "").lower())]
        no = [p["views"] for p in posts if not test((p.get("caption") or "").lower())]
        if len(yes) >= 2 and len(no) >= 2:   # a single reel proves nothing, so no lift number for it
            features[name] = {"n_with": len(yes), "median_views_with": _median(yes),
                              "n_without": len(no), "median_views_without": _median(no),
                              "lift_x": round(statistics.median(yes) / statistics.median(no), 2)}
    tag_views: dict[str, list[int]] = {}
    for p in posts:
        for tag in {t.lower().strip(".,!") for t in (p.get("caption") or "").split() if t.startswith("#")}:
            tag_views.setdefault(tag, []).append(p["views"])
    hashtags = sorted(({"tag": t, "n": len(v), "median_views": _median(v)} for t, v in tag_views.items() if len(v) >= 2),
                      key=lambda r: r["median_views"], reverse=True)
    best_comment = max(rows, key=lambda r: r["comment_rate_pct"])
    return {
        "sample_size": len(posts),
        "caveat": "small sample: treat as directional, not proof" if len(posts) < 30 else None,
        "median_views": round(med), "mean_views": round(statistics.mean(views)),
        "winners": [r["id"] for r in rows if r["outlier_x"] >= 2],
        "flops": [r["id"] for r in rows if r["outlier_x"] <= 0.5],
        "best_comment_rate": {"id": best_comment["id"], "pct": best_comment["comment_rate_pct"],
                              "caption": clip(by_id[best_comment["id"]].get("caption"), 120)},
        "per_reel": rows,
        "caption_features": features,
        "hashtags": hashtags[:10],
    }


# ---------------------------------------------------------------- momentum vs last run

def add_momentum(current: dict, previous: dict | None) -> None:
    """Mark what's new or climbing since the previous snapshot."""
    if not previous:
        return
    prev_wiki = {r["title"] for r in previous.get("wikipedia", [])}
    for r in current.get("wikipedia", []):
        r["new_since_last_run"] = r["title"] not in prev_wiki
    prev_hn = {r["id"] for r in previous.get("hackernews", [])}
    for r in current.get("hackernews", []):
        r["new_since_last_run"] = r["id"] not in prev_hn
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
    # Additive sources (new keys only; existing keys above are unchanged).
    signals["google_trends_intl"] = collect_google_trends_intl(cfg.get("google_trends", {}), signals["google_trends"], errors)
    signals["wikipedia"] = collect_wikipedia(cfg.get("wikipedia", {}), errors)
    signals["hackernews"] = collect_hackernews(cfg.get("hackernews", {}), errors)
    analysis = analyze_instagram(signals["instagram"])
    if analysis:
        signals["instagram_analysis"] = analysis
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
               f"ig_posts={len(signals['instagram'].get('posts', []))} "
               f"trends_intl={len(signals['google_trends_intl'])} wiki={len(signals['wikipedia'])} "
               f"hn={len(signals['hackernews'])} ig_analysis={'yes' if analysis else 'no'} errors={len(errors)}")
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
