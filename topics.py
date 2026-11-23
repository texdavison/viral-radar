"""Topic engine for the Viral Idea Radar (standard library only).

Takes the raw per-source signals from collect.py and turns them into topics:
  * convergence : the same subject showing up in several independent sources (Trends, Wikipedia,
                  Hacker News, Reddit, YouTube) is a far stronger signal than a spike in one
  * lifecycle   : emerging / rising / peaking / fading, from a compact per-topic history file
  * risk flags  : topics that need care (nicotine, gambling, politics/war, death, adult)
  * saturation  : how crowded a topic already is on YouTube Shorts (summary only; fetching is in collect.py)

Matching is deliberately simple and explainable (token overlap), not a black box.
"""
from __future__ import annotations

import math
import re
import statistics
from datetime import datetime, timedelta, timezone

STOP = set("""a an and are as at be but by for from has have he her his how i if in into is it its of on or our
she so than that the their them they this to up us was we were what when where which who why will with you your vs
new news live latest today tonight""".split())

SOURCE_LABELS = {"google_trends": "Google Trends (US)", "google_trends_intl": "Google Trends (GB/CA/AU)",
                 "wikipedia": "Wikipedia", "hackernews": "Hacker News", "reddit": "Reddit", "youtube": "YouTube"}

RISK_WORDS = {
    "nicotine": ["zyn", "vape", "vaping", "nicotine", "cigarette", "cigarettes", "tobacco", "juul", "snus"],
    "gambling": ["casino", "betting", "gamble", "gambling", "sportsbook", "jackpot", "poker"],
    "politics_war": ["election", "trump", "biden", "congress", "senate", "war", "iran", "israel", "gaza",
                     "ukraine", "russia", "hormuz", "military", "strike", "sanctions", "protest"],
    "death_tragedy": ["died", "dies", "death", "dead", "killed", "shooting", "shot", "murder", "funeral",
                      "obituary", "crash", "tragedy", "suicide"],
    "adult": ["porn", "nude", "nsfw", "onlyfans", "sex"],
}
_RISK_RE = {k: re.compile(r"\b(" + "|".join(map(re.escape, v)) + r")\b", re.I) for k, v in RISK_WORDS.items()}

WINDOW_HINT = {
    "emerging": "First sighting. Highest upside but unconfirmed: check it holds on the next scan before committing.",
    "rising": "Still climbing. Best window to post is now, ideally within about 12-24h.",
    "peaking": "At or near the top. Only worth it with a fresh angle; the crowd is arriving.",
    "fading": "Past its peak. Skip unless the idea is evergreen.",
}


# ---------------------------------------------------------------- text matching

def tokens(text: str | None) -> list[str]:
    text = re.sub(r"\([^)]*\)", " ", (text or "").lower())      # drop "(film)", "(born 1951)" etc.
    out = []
    for t in re.split(r"[^a-z0-9]+", text):
        if not t or t in STOP:
            continue
        if len(t) >= 2 or t.isdigit():
            out.append(t)
    return out


def parse_traffic(s: str | None) -> float:
    """'200+' -> 200, '20K+' -> 20000, '2M+' -> 2000000."""
    m = re.match(r"\s*([\d.,]+)\s*([KMB]?)", (s or "").upper())
    if not m:
        return 0.0
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return 0.0
    return n * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)]


def matches(seed_tokens: list[str], hay_tokens: set[str]) -> bool:
    """Does this text mention the seed subject? Single words must be 3+ chars; multi-word seeds need
    at least 2 words and 60% of their words."""
    if not seed_tokens:
        return False
    if len(seed_tokens) == 1:
        t = seed_tokens[0]
        return (len(t) >= 3 or t.isdigit()) and t in hay_tokens
    hits = sum(1 for t in seed_tokens if t in hay_tokens)
    return hits >= max(2, math.ceil(0.6 * len(seed_tokens)))


# ---------------------------------------------------------------- clustering

class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.p[self.find(a)] = self.find(b)


def _seeds_and_hay(signals: dict) -> tuple[list[dict], list[dict]]:
    seeds, hay = [], []

    def add_seed(source, label, metric, url="", news=None, extra=None):
        toks = tokens(label)
        if not toks:
            return
        i = len(seeds)
        seeds.append({"i": i, "source": source, "label": label, "toks": toks, "key": " ".join(toks),
                      "metric": metric, "url": url, "extra": extra or {}})
        for n in news or []:
            nt = set(tokens(n.get("title")))
            if nt:
                hay.append({"source": source, "text": n.get("title") or "", "url": n.get("url") or "",
                            "toks": nt, "parent": i, "metric": 0, "kind": "news"})

    for r in signals.get("google_trends", []):
        add_seed("google_trends", r.get("query"), parse_traffic(r.get("approx_traffic")),
                 (r.get("news") or [{}])[0].get("url", ""), r.get("news"), {"traffic": r.get("approx_traffic")})
    for r in signals.get("google_trends_intl", []):
        add_seed("google_trends_intl", r.get("query"), parse_traffic(r.get("approx_traffic")),
                 (r.get("news") or [{}])[0].get("url", ""), r.get("news"),
                 {"traffic": r.get("approx_traffic"), "geo": r.get("geo")})
    for r in signals.get("wikipedia", []):
        add_seed("wikipedia", r.get("title"), r.get("views") or 0, r.get("url", ""), None,
                 {"views": r.get("views"), "growth_x": r.get("growth_x")})

    def add_hay(source, text, url, metric, extra=None):
        t = set(tokens(text))
        if t:
            hay.append({"source": source, "text": text, "url": url, "toks": t, "parent": None,
                        "metric": metric, "kind": "item", "extra": extra or {}})

    for r in signals.get("hackernews", []):
        add_hay("hackernews", r.get("title"), r.get("discussion") or r.get("url"), r.get("points") or 0,
                {"points": r.get("points")})
    for r in signals.get("reddit", []):
        add_hay("reddit", r.get("title"), r.get("url"), r.get("score") or 0, {"score": r.get("score")})
    yt = signals.get("youtube") or {}
    for r in (yt.get("popular") or []) + (yt.get("shorts") or []):
        add_hay("youtube", r.get("title"), r.get("url"), r.get("views_per_hour") or 0,
                {"views_per_hour": r.get("views_per_hour")})
    return seeds, hay


def build_clusters(signals: dict) -> list[dict]:
    seeds, hay = _seeds_and_hay(signals)
    uf = _UF(len(seeds))
    seed_hay = [set(s["toks"]) for s in seeds]
    # seeds that mention each other are the same topic
    for a in seeds:
        for b in seeds:
            if a["i"] < b["i"] and (matches(a["toks"], seed_hay[b["i"]]) or matches(b["toks"], seed_hay[a["i"]])):
                uf.union(a["i"], b["i"])
    # a hay item matching a seed attaches to it; a news item also links its own trend to that seed
    attached: dict[int, list[dict]] = {}
    for h in hay:
        for s in seeds:
            if h.get("parent") == s["i"]:
                continue
            if matches(s["toks"], h["toks"]):
                attached.setdefault(s["i"], []).append(h)
                if h.get("parent") is not None:
                    uf.union(s["i"], h["parent"])
    groups: dict[int, list[dict]] = {}
    for s in seeds:
        groups.setdefault(uf.find(s["i"]), []).append(s)

    clusters = []
    prio = {"google_trends": 0, "google_trends_intl": 1, "wikipedia": 2}
    for members in groups.values():
        members.sort(key=lambda s: (prio[s["source"]], -s["metric"]))
        ev, seen = [], set()
        sources = {s["source"] for s in members}
        metrics: dict[str, float] = {}
        for s in members:
            metrics[s["source"]] = max(metrics.get(s["source"], 0), s["metric"])
            ev.append({"source": s["source"], "text": s["label"], "url": s["url"]})
        for s in members:
            for h in attached.get(s["i"], []) + [x for x in hay if x.get("parent") == s["i"]]:
                k = (h["source"], h["text"])
                if k in seen:
                    continue
                seen.add(k)
                if h["kind"] == "item":
                    sources.add(h["source"])
                    metrics[h["source"]] = max(metrics.get(h["source"], 0), h["metric"])
                ev.append({"source": h["source"] if h["kind"] == "item" else h["source"] + "_news",
                           "text": h["text"], "url": h["url"]})
        heat = round(sum(math.log10(1 + m) for m in metrics.values()), 2)
        details = {}
        for s in members:
            details.setdefault(s["source"], {}).update({k: v for k, v in s["extra"].items() if v is not None})
        for h in {id(x): x for s in members for x in attached.get(s["i"], []) if x["kind"] == "item"}.values():
            details.setdefault(h["source"], {}).update({k: v for k, v in (h.get("extra") or {}).items() if v is not None})
        clusters.append({"label": members[0]["label"], "key": members[0]["key"],
                         "aliases": sorted({s["key"] for s in members}),
                         "sources": sorted(sources), "source_count": len(sources), "heat": heat,
                         "signals": details, "evidence": ev})
    return clusters


# ---------------------------------------------------------------- risk

def risk_flags(cluster: dict) -> list[str]:
    text = " ".join([cluster["label"]] + [e["text"] for e in cluster["evidence"]])
    return [name for name, rx in _RISK_RE.items() if rx.search(text)]


# ---------------------------------------------------------------- history + lifecycle

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def update_history(store: dict, clusters: list[dict], now: datetime, stale_hours: float = 24) -> dict:
    """Record this run's heat per topic; retire topics not seen for a day (their lifetime feeds the
    'typical lifetime' estimate)."""
    store.setdefault("created", _iso(now))
    topics = store.setdefault("topics", {})
    fin = store.setdefault("finished_lifetimes_h", [])
    for c in clusters:
        alias = set(c["aliases"])
        key = next((k for k, t in topics.items() if alias & set(t["aliases"])), None) or c["key"]
        t = topics.setdefault(key, {"label": c["label"], "aliases": [], "first_seen": _iso(now),
                                    "last_seen": _iso(now), "points": []})
        t["aliases"] = sorted(set(t["aliases"]) | alias)[:30]
        t["label"] = c["label"]
        t["last_seen"] = _iso(now)
        t["points"] = (t["points"] + [[_iso(now), c["heat"], c["source_count"]]])[-120:]
        c["_hist"] = key
    for k in list(topics):
        t = topics[k]
        if now - _parse(t["last_seen"]) > timedelta(hours=stale_hours):
            if len(t["points"]) >= 2:
                fin.append(round((_parse(t["last_seen"]) - _parse(t["first_seen"])).total_seconds() / 3600, 1))
            del topics[k]
    store["finished_lifetimes_h"] = fin[-200:]
    return store


def lifecycle(points: list[list]) -> tuple[str, str]:
    """(stage, confidence) from a topic's heat series. Heat is on a log scale: +0.1 is about +26%."""
    heats = [p[1] for p in points]
    if len(heats) < 2:
        return "emerging", "low"
    last, prev, mx = heats[-1], heats[-2], max(heats)
    d = last - prev
    conf = "low" if len(heats) < 3 else "medium" if len(heats) < 6 else "high"
    if last >= mx - 0.05 and d > 0.08:
        return "rising", conf
    if last < mx - 0.3 or d < -0.08:
        return "fading", conf
    return "peaking", conf


def attach_lifecycle(clusters: list[dict], store: dict, now: datetime) -> dict:
    topics = store.get("topics", {})
    fin = store.get("finished_lifetimes_h", [])
    typical = round(statistics.median(fin), 1) if len(fin) >= 5 else None
    for c in clusters:
        t = topics.get(c.get("_hist", ""), {})
        pts = t.get("points", [])
        stage, conf = lifecycle(pts)
        c["lifecycle"], c["lifecycle_confidence"] = stage, conf
        c["window_hint"] = WINDOW_HINT[stage]
        c["runs_seen"] = len(pts)
        c["age_hours"] = round((now - _parse(t["first_seen"])).total_seconds() / 3600, 1) if t else 0
        c["heat_change"] = round(pts[-1][1] - pts[-2][1], 2) if len(pts) >= 2 else None
    created = store.get("created")
    return {"history_depth_hours": round((now - _parse(created)).total_seconds() / 3600, 1) if created else 0,
            "typical_lifetime_hours": typical,
            "note": "Lifecycle needs history: until a topic has been seen on 3+ scans its stage is a first guess."}


# ---------------------------------------------------------------- saturation (summary only)

def saturation_summary(rows: list[dict]) -> dict:
    """rows: YouTube Shorts from the last 48h about the topic, each with views. Heuristic labels."""
    views = sorted((r.get("views") or 0 for r in rows), reverse=True)
    n = len(views)
    big = sum(1 for v in views if v >= 10000)
    mid = sum(1 for v in views if v >= 1000)
    if n == 0:
        label = "untouched"
    elif big >= 8:
        label = "crowded"
    elif big >= 3:
        label = "contested"
    elif mid >= 3 or n >= 5:
        label = "active"
    else:
        label = "open"
    return {"label": label, "shorts_48h": n, "shorts_over_10k": big, "top_views": views[0] if views else 0,
            "median_views": int(statistics.median(views)) if views else 0,
            "meaning": {"untouched": "Nobody has covered this in 48h. Big first-mover upside.",
                        "open": "Few videos and none big. Room to win.",
                        "active": "Some coverage. You need a distinct angle.",
                        "contested": "Several videos already above 10K. Only with a strong twist.",
                        "crowded": "Saturated. Skip or go very niche."}[label]}


def rank_topics(clusters: list[dict], limit: int = 40) -> list[dict]:
    """Multi-source topics first (that is the point of convergence), then by heat."""
    clusters.sort(key=lambda c: (c["source_count"], c["heat"]), reverse=True)
    out = []
    for c in clusters[:limit]:
        row = {"topic": c["label"], "sources": [SOURCE_LABELS.get(s, s) for s in c["sources"]],
               "source_count": c["source_count"], "heat": c["heat"],
               "lifecycle": c["lifecycle"], "lifecycle_confidence": c["lifecycle_confidence"],
               "window_hint": c["window_hint"], "runs_seen": c["runs_seen"], "age_hours": c["age_hours"],
               "heat_change": c["heat_change"], "signals": c["signals"],
               "evidence": c["evidence"][:6], "risk_flags": risk_flags(c)}
        out.append(row)
    return out
