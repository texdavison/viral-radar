import json, sys, time, unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect

class T(unittest.TestCase):
    def test_reddit(self):
        now = time.time()
        data = {"data": {"children": [
            {"data": {"id": "a", "title": "Pirate token odds are insane", "score": 1200, "num_comments": 300, "created_utc": now - 2*3600, "permalink": "/r/FortNiteBR/comments/a/x/"}},
            {"data": {"id": "s", "title": "Weekly thread", "score": 5, "stickied": True, "created_utc": now}},
            {"data": {"id": "n", "title": "nsfw", "score": 999, "over_18": True, "created_utc": now}}]}}
        posts = collect.parse_reddit_listing(data, "FortNiteBR", now)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["velocity"], 600.0)
        self.assertEqual(posts[0]["comment_rate"], 150.0)
        self.assertTrue(posts[0]["url"].startswith("https://www.reddit.com/r/FortNiteBR"))

    def test_youtube(self):
        now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        v = {"id": "x1", "snippet": {"title": "What if", "channelTitle": "C", "publishedAt": "2026-11-18T02:00:00Z"},
             "statistics": {"viewCount": "1000000", "likeCount": "5", "commentCount": "2"}}
        r = collect._yt_video(v, now)
        self.assertEqual(r["views_per_hour"], 100000)

    def test_instagram(self):
        ins = {"data": [{"name": "views", "values": [{"value": 6000000}]},
                        {"name": "shares", "values": [{"value": 90000}]},
                        {"name": "ig_reels_avg_watch_time", "values": [{"value": 7400}]},
                        {"name": "total_interactions", "total_value": {"value": 500000}}]}
        r = collect.parse_ig_insights(ins)
        self.assertEqual(r["views"], 6000000)
        self.assertEqual(r["avg_watch_seconds"], 7.4)
        self.assertEqual(r["total_interactions"], 500000)
        self.assertEqual(collect.parse_ig_insights({"data": [{"name": "plays", "values": [{"value": 3}]}]})["views"], 3)

    def test_momentum(self):
        cur = {"reddit": [{"id": "a", "score": 150}, {"id": "b", "score": 10}], "google_trends": [{"query": "GTA 6"}, {"query": "New"}]}
        prev = {"reddit": [{"id": "a", "score": 100}], "google_trends": [{"query": "gta 6"}]}
        collect.add_momentum(cur, prev)
        self.assertEqual(cur["reddit"][0]["score_gain"], 50)
        self.assertTrue(cur["reddit"][1]["new_since_last_run"])
        self.assertFalse(cur["google_trends"][0]["new_since_last_run"])
        self.assertTrue(cur["google_trends"][1]["new_since_last_run"])

    def test_wiki_top_filters_junk(self):
        data = {"items": [{"articles": [
            {"article": "Main_Page", "views": 9000000, "rank": 1},
            {"article": "Special:Search", "views": 800000, "rank": 2},
            {"article": "Zyn_(brand)", "views": 120000, "rank": 3}]}]}
        rows = collect.parse_wiki_top(data)
        self.assertEqual([r["title"] for r in rows], ["Zyn (brand)"])
        self.assertEqual(rows[0]["views"], 120000)

    def test_hn(self):
        now = time.time()
        data = {"hits": [{"objectID": "9", "title": "How a CPU works", "points": 400, "num_comments": 80,
                          "created_at_i": now - 4 * 3600, "url": "https://x.test"}]}
        r = collect.parse_hn(data, now)[0]
        self.assertEqual(r["velocity"], 100.0)
        self.assertEqual(r["discussion"], "https://news.ycombinator.com/item?id=9")

    def test_analyze_instagram(self):
        posts = [{"id": str(i), "views": v, "likes": v // 50, "comments": 5, "caption": c}
                 for i, (v, c) in enumerate([(1000, "Send this to a friend #a"), (1200, "Send this now #a"),
                                             (9000, "POV: roommate #b"), (8000, "POV: wedding #b"), (1100, "plain")])]
        a = collect.analyze_instagram({"posts": posts, "followers": 100})
        self.assertEqual(a["sample_size"], 5)
        self.assertEqual(a["median_views"], 1200)
        self.assertEqual(a["per_reel"][0]["id"], "2")           # biggest first
        self.assertEqual(a["per_reel"][0]["outlier_x"], 7.5)
        self.assertIn("pov", a["caption_features"])
        self.assertGreater(a["caption_features"]["pov"]["lift_x"], 1)
        self.assertNotIn("type_at_cta", a["caption_features"])   # unused feature: no stats
        self.assertIsNone(collect.analyze_instagram({"posts": posts[:2]}))   # too few reels

if __name__ == "__main__":
    unittest.main()
