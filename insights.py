"""Competitor outliers and the format playbook (standard library only).

Reads competitors_manual.json (public stats for similar accounts, refreshed by Claude through the browser,
since Instagram has no keyless API) and finds the reels that beat their own account's normal by a wide margin.
Then combines that with this account's own results into a short, deterministic "playbook" the cloud scan uses
when it writes ready-to-shoot idea packages.
"""
from __future__ import annotations

import statistics

# Caption traits we test. Each is a cheap, explainable text check.
CAPTION_FEATURES = {
    "send_this_cta": lambda c: "send this" in c,
    "type_at_cta": lambda c: "type @" in c,
    "follow_or_name_ask": lambda c: "follow" in c or "name the" in c,
    "what_if": lambda c: "what if" in c or "#whatif" in c,
    "pov": lambda c: c.startswith("pov") or " pov:" in c,
    "question_in_hook": lambda c: "?" in c.split("\n")[0],
}


def hook(caption: str | None, n: int = 140) -> str:
    first = (caption or "").strip().split("\n")[0].strip()
    return first if len(first) <= n else first[: n - 1] + "…"


def hashtags(caption: str | None) -> list[str]:
    return sorted({t.lower().strip(".,!") for t in (caption or "").split() if t.startswith("#") and len(t) > 1})


def _med(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def _feature_stats(items: list[dict], key: str) -> dict:
    """Median of `key` with vs without each caption trait. A trait seen in <2 reels (or absent from <2) gets no number."""
    out = {}
    for name, test in CAPTION_FEATURES.items():
        yes = [p[key] for p in items if test((p.get("caption") or "").lower())]
        no = [p[key] for p in items if not test((p.get("caption") or "").lower())]
        if len(yes) >= 2 and len(no) >= 2 and statistics.median(no) > 0:
            out[name] = {"n_with": len(yes), f"median_{key}_with": _med(yes), "n_without": len(no),
                         f"median_{key}_without": _med(no),
                         "lift_x": round(statistics.median(yes) / statistics.median(no), 2)}
    return out


def _hashtag_stats(items: list[dict], key: str) -> list[dict]:
    by_tag: dict[str, list[float]] = {}
    for p in items:
        for t in hashtags(p.get("caption")):
            by_tag.setdefault(t, []).append(p[key])
    rows = [{"tag": t, "n": len(v), f"median_{key}": _med(v)} for t, v in by_tag.items() if len(v) >= 2]
    return sorted(rows, key=lambda r: r[f"median_{key}"], reverse=True)[:10]


def analyze_instagram(ig: dict) -> dict | None:
    """What has worked on the account's own reels. Views are the goal metric, but public pages only show them
    for some reels, so likes (available for every reel, and from the API too) are analysed alongside."""
    posts = [p for p in ig.get("posts", []) if p.get("id")]
    with_views = [p for p in posts if p.get("views")]
    with_likes = [p for p in posts if p.get("likes") is not None]
    if len(with_views) < 3 and len(with_likes) < 3:
        return None
    followers = ig.get("followers")
    med_v = statistics.median(p["views"] for p in with_views) if len(with_views) >= 3 else None
    med_l = statistics.median(p["likes"] for p in with_likes) if len(with_likes) >= 3 else None
    rows = []
    for p in posts:
        v, l = p.get("views"), p.get("likes")
        row = {"id": p["id"], "views": v, "likes": l, "comments": p.get("comments")}
        if v and med_v:
            row["outlier_x"] = round(v / med_v, 1)                    # views vs this account's median reel
            row["like_rate_pct"] = round(100 * (l or 0) / v, 2)
            row["comment_rate_pct"] = round(100 * (p.get("comments") or 0) / v, 2)
            if followers:
                row["views_per_follower"] = round(v / followers, 1)
        if l is not None and med_l:
            row["likes_outlier_x"] = round(l / med_l, 1)
        rows.append(row)
    strength = lambda r: r.get("outlier_x", r.get("likes_outlier_x", 0))   # views first, likes when views are unknown
    rows.sort(key=strength, reverse=True)
    by_id = {p["id"]: p for p in posts}
    commented = max(posts, key=lambda p: p.get("comments") or 0)
    best_rate = max((r for r in rows if "comment_rate_pct" in r), key=lambda r: r["comment_rate_pct"], default=None)
    out = {
        "sample_size": len(posts), "with_views": len(with_views), "with_likes": len(with_likes),
        "caveat": ("small sample: treat as directional, not proof" if len(posts) < 30 else None),
        "views_note": (None if len(with_views) == len(posts) else
                       f"{len(posts) - len(with_views)} reels have no public view count; they are ranked by likes_outlier_x. "
                       "Reels without views were read from the profile's main grid, which tends to surface popular or "
                       "pinned posts, so the sample probably over-represents winners and 'winners' is inflated."),
        "median_views": round(med_v) if med_v else None, "median_likes": round(med_l) if med_l else None,
        "winners": [r["id"] for r in rows if strength(r) >= 2],
        "flops": [r["id"] for r in rows if 0 < strength(r) <= 0.5],
        "most_commented": {"id": commented["id"], "comments": commented.get("comments"),
                           "hook": hook(commented.get("caption"), 100)},
        "per_reel": rows,
        "caption_features": _feature_stats(with_views, "views") if len(with_views) >= 3 else {},
        "caption_features_by_likes": _feature_stats(with_likes, "likes") if len(with_likes) >= 3 else {},
        "hashtags": _hashtag_stats(with_views, "views"),
        "hashtags_by_likes": _hashtag_stats(with_likes, "likes"),
    }
    if best_rate:
        out["best_comment_rate"] = {"id": best_rate["id"], "pct": best_rate["comment_rate_pct"],
                                    "hook": hook(by_id[best_rate["id"]].get("caption"), 100)}
    return out


def analyze_competitors(data: dict | None, outlier_x: float = 3.0, min_views: int = 5000) -> dict | None:
    """Per account: median views; outliers = reels at outlier_x times that median (and above min_views)."""
    accounts = (data or {}).get("accounts") or []
    out_accounts, outliers = [], []
    for a in accounts:
        reels = [r for r in a.get("reels", []) if r.get("views")]
        if len(reels) < 4:                       # too few reels to know what "normal" is
            continue
        med = statistics.median(r["views"] for r in reels)
        followers = a.get("followers")
        best = []
        for r in reels:
            x = r["views"] / med
            if x >= outlier_x and r["views"] >= min_views:
                best.append({
                    "account": a["handle"], "id": r.get("id"), "date": r.get("date"), "views": r["views"],
                    "outlier_x": round(x, 1), "hook": hook(r.get("caption")), "hashtags": hashtags(r.get("caption")),
                    "likes": r.get("likes"), "comments": r.get("comments"),
                    "views_per_follower": round(r["views"] / followers, 1) if followers else None,
                    "platform": a.get("platform", "instagram"),
                    "url": (None if not r.get("id") else
                            f"https://www.youtube.com/watch?v={r['id']}" if a.get("platform") == "youtube" else
                            f"https://www.instagram.com/{a['handle']}/reel/{r['id']}/"),
                })
        out_accounts.append({"handle": a["handle"], "platform": a.get("platform", "instagram"),
                             "followers": followers, "reels_sampled": len(reels),
                             "median_views": round(med), "outliers": len(best)})
        outliers.extend(best)
    if not out_accounts:
        return None
    outliers.sort(key=lambda r: r["outlier_x"], reverse=True)
    all_reels = [r for a in accounts for r in a.get("reels", []) if r.get("views")]
    out_ids = {(o["account"], o["id"]) for o in outliers}
    features = {}
    for name, test in CAPTION_FEATURES.items():
        yes = [r for a in accounts for r in a.get("reels", []) if r.get("views")
               if (a["handle"], r.get("id")) in out_ids and test((r.get("caption") or "").lower())]
        base = [r for r in all_reels if test((r.get("caption") or "").lower())]
        if len(yes) >= 2:
            features[name] = {"in_outliers": len(yes), "in_all_reels": len(base),
                              "outlier_share_pct": round(100 * len(yes) / max(1, len(base)))}
    tag_counts: dict[str, int] = {}
    for o in outliers:
        for t in o["hashtags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    return {"accounts": out_accounts, "outlier_rule": f">= {outlier_x}x the account's own median and >= {min_views} views",
            "scraped_at": (data or {}).get("scraped_at"), "outliers": outliers[:25],
            "traits_in_outliers": features,
            "common_outlier_hashtags": sorted(({"tag": t, "n": n} for t, n in tag_counts.items() if n >= 2),
                                              key=lambda r: r["n"], reverse=True)[:10]}


def build_playbook(own: dict | None, own_posts: list[dict], comp: dict | None) -> dict | None:
    """Short, deterministic summary of what has worked. The cloud scan turns this into idea packages."""
    if not own and not comp:
        return None
    pb: dict = {"how_to_use": "Write each idea package in the style of these winners; avoid the patterns that lag."}
    if own:
        by_id = {p["id"]: p for p in own_posts}
        pb["own_winner_hooks"] = [hook(by_id[i].get("caption")) for i in own.get("winners", []) if i in by_id][:6]
        pb["own_flop_hooks"] = [hook(by_id[i].get("caption")) for i in own.get("flops", []) if i in by_id][:4]
        feats = own.get("caption_features", {})
        pb["own_traits_that_beat_median"] = sorted([k for k, v in feats.items() if v["lift_x"] >= 1.2])
        pb["own_traits_that_lag"] = sorted([k for k, v in feats.items() if v["lift_x"] <= 0.8])
        lf = own.get("caption_features_by_likes", {})
        pb["own_traits_that_beat_median_by_likes"] = sorted([k for k, v in lf.items() if v["lift_x"] >= 1.2])
        pb["own_traits_that_lag_by_likes"] = sorted([k for k, v in lf.items() if v["lift_x"] <= 0.8])
        top = own.get("winners", [])[:1]
        if top and top[0] in by_id:
            pb["own_top_reel_hook"] = hook(by_id[top[0]].get("caption"), 200)
        pb["own_best_hashtags"] = [h["tag"] for h in own.get("hashtags", [])[:6]]
        pb["own_best_hashtags_by_likes"] = [h["tag"] for h in own.get("hashtags_by_likes", [])[:6]]
        pb["own_sample_size"] = own.get("sample_size")
    if comp:
        pb["competitor_outlier_hooks"] = [{"hook": o["hook"], "views": o["views"], "outlier_x": o["outlier_x"],
                                           "account": o["account"]} for o in comp["outliers"][:8]]
        pb["competitor_common_hashtags"] = [h["tag"] for h in comp.get("common_outlier_hashtags", [])[:6]]
    return pb
