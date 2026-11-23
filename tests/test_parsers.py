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

if __name__ == "__main__":
    unittest.main()
