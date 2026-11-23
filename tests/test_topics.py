import sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import insights
import topics as T

NOW = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)


def trend(q, traffic="200+", news=None):
    return {"query": q, "approx_traffic": traffic, "news": news or []}


class TopicTests(unittest.TestCase):
    def test_parse_traffic(self):
        self.assertEqual(T.parse_traffic("200+"), 200)
        self.assertEqual(T.parse_traffic("20K+"), 20000)
        self.assertEqual(T.parse_traffic("2M+"), 2000000)
        self.assertEqual(T.parse_traffic(""), 0)

    def test_matches_rules(self):
        self.assertTrue(T.matches(["zyn"], {"zyn", "gums"}))
        self.assertFalse(T.matches(["ab"], {"ab"}))                       # too short to trust
        self.assertTrue(T.matches(["tom", "jackson"], {"tom", "jackson", "dies"}))
        self.assertFalse(T.matches(["tom", "jackson"], {"tom", "hanks"}))  # one of two words is not enough

    def test_convergence_across_sources(self):
        sig = {
            "google_trends": [trend("gta 6 trailer", "500K+", [{"title": "GTA 6 trailer 3 breaks records", "url": "u"}])],
            "wikipedia": [{"title": "Grand Theft Auto VI", "views": 400000, "growth_x": 5, "url": "w"}],
            "hackernews": [{"title": "GTA 6 trailer technical breakdown", "points": 300, "discussion": "hn"}],
            "reddit": [], "youtube": {"popular": [], "shorts": []},
        }
        cl = T.build_clusters(sig)
        top = max(cl, key=lambda c: c["source_count"])
        self.assertIn("google_trends", top["sources"])
        self.assertIn("hackernews", top["sources"])
        self.assertGreaterEqual(top["source_count"], 2)

    def test_news_links_a_trend_to_a_wiki_page(self):
        sig = {
            "google_trends": [trend("iran war hormuz", "200+", [{"title": "Attacks in the Strait of Hormuz hit a high", "url": "n"}])],
            "wikipedia": [{"title": "Strait of Hormuz", "views": 90000, "growth_x": 3, "url": "w"}],
        }
        cl = T.build_clusters(sig)
        self.assertEqual(len(cl), 1)
        self.assertEqual(cl[0]["source_count"], 2)
        self.assertIn("politics_war", T.risk_flags(cl[0]))

    def test_unrelated_topics_stay_separate(self):
        sig = {"google_trends": [trend("taylor swift"), trend("nfl scores")], "wikipedia": []}
        self.assertEqual(len(T.build_clusters(sig)), 2)

    def test_risk_flags_use_word_boundaries(self):
        c = {"label": "Zyn pouches recalled", "evidence": [{"text": "gums"}]}
        self.assertEqual(T.risk_flags(c), ["nicotine"])
        self.assertEqual(T.risk_flags({"label": "Sussex weather", "evidence": []}), [])   # 'sex' inside 'Sussex'

    def test_lifecycle_stages(self):
        P = lambda *h: [["t", x, 2] for x in h]
        self.assertEqual(T.lifecycle(P(3.0))[0], "emerging")
        self.assertEqual(T.lifecycle(P(3.0, 3.4, 3.9))[0], "rising")
        self.assertEqual(T.lifecycle(P(3.0, 4.0, 4.02))[0], "peaking")
        self.assertEqual(T.lifecycle(P(3.0, 4.0, 3.5))[0], "fading")
        self.assertEqual(T.lifecycle(P(3.0, 3.4))[1], "low")           # two points: low confidence
        self.assertEqual(T.lifecycle(P(*[3 + i * 0.2 for i in range(6)]))[1], "high")

    def test_history_update_and_retire(self):
        sig = {"google_trends": [trend("gta 6 trailer", "500K+")]}
        store = {}
        for hours in (0, 3, 6):
            cl = T.build_clusters(sig)
            T.update_history(store, cl, NOW + timedelta(hours=hours))
        self.assertEqual(len(store["topics"]), 1)
        self.assertEqual(len(next(iter(store["topics"].values()))["points"]), 3)
        T.update_history(store, [], NOW + timedelta(hours=40))             # not seen for >24h
        self.assertEqual(store["topics"], {})
        self.assertEqual(store["finished_lifetimes_h"], [6.0])

    def test_attach_lifecycle_and_typical_lifetime(self):
        store = {"created": "2026-11-20T12:00:00Z", "finished_lifetimes_h": [10, 20, 30, 40, 50]}
        cl = T.build_clusters({"google_trends": [trend("gta 6 trailer", "500K+")]})
        T.update_history(store, cl, NOW)
        meta = T.attach_lifecycle(cl, store, NOW)
        self.assertEqual(cl[0]["lifecycle"], "emerging")
        self.assertEqual(meta["typical_lifetime_hours"], 30)
        self.assertEqual(meta["history_depth_hours"], 72.0)

    def test_saturation_labels(self):
        self.assertEqual(T.saturation_summary([])["label"], "untouched")
        self.assertEqual(T.saturation_summary([{"views": 500}, {"views": 300}])["label"], "open")
        self.assertEqual(T.saturation_summary([{"views": 20000}] * 3)["label"], "contested")
        self.assertEqual(T.saturation_summary([{"views": 50000}] * 9)["label"], "crowded")

    def test_rank_puts_multi_source_first(self):
        a = {"label": "A", "key": "a", "aliases": ["a"], "sources": ["wikipedia"], "source_count": 1, "heat": 9,
             "signals": {}, "evidence": [], "lifecycle": "emerging", "lifecycle_confidence": "low",
             "window_hint": "", "runs_seen": 1, "age_hours": 0, "heat_change": None}
        b = dict(a, label="B", sources=["wikipedia", "hackernews"], source_count=2, heat=3)
        self.assertEqual([r["topic"] for r in T.rank_topics([a, b])], ["B", "A"])


class InsightTests(unittest.TestCase):
    def reels(self, views, caption="plain"):
        return [{"id": f"r{i}", "views": v, "likes": 1, "comments": 1, "caption": caption if i % 2 else "Send this to a friend\n#a #b"}
                for i, v in enumerate(views)]

    def test_competitor_outliers(self):
        data = {"accounts": [{"handle": "x", "followers": 1000, "reels": self.reels([1000, 1100, 900, 1200, 60000])},
                             {"handle": "tiny", "reels": self.reels([5, 6])}]}      # too few reels: ignored
        out = insights.analyze_competitors(data)
        self.assertEqual([a["handle"] for a in out["accounts"]], ["x"])
        self.assertEqual(len(out["outliers"]), 1)
        self.assertEqual(out["outliers"][0]["views"], 60000)
        self.assertEqual(out["outliers"][0]["outlier_x"], 54.5)
        self.assertEqual(out["outliers"][0]["hook"], "Send this to a friend")
        self.assertIsNone(insights.analyze_competitors({"accounts": []}))
        self.assertIsNone(insights.analyze_competitors(None))

    def test_min_views_floor(self):
        data = {"accounts": [{"handle": "x", "reels": self.reels([10, 11, 9, 12, 900])}]}
        self.assertEqual(insights.analyze_competitors(data)["outliers"], [])    # 900 < 5000 floor

    def test_instagram_analysis_handles_reels_without_views(self):
        posts = [{"id": f"v{i}", "views": v, "likes": v // 50, "comments": 2, "caption": "plain"} for i, v in enumerate([1000, 1200, 900, 1100])]
        posts.append({"id": "big", "views": None, "likes": 458000, "comments": 1800, "caption": "Send this\n#fyp"})
        posts.append({"id": "small", "views": None, "likes": 10, "comments": 0, "caption": "meh"})
        a = insights.analyze_instagram({"posts": posts})
        self.assertEqual(a["sample_size"], 6)
        self.assertEqual(a["with_views"], 4)
        self.assertEqual(a["per_reel"][0]["id"], "big")               # unknown views, ranked by likes
        self.assertIn("big", a["winners"])
        self.assertIn("small", a["flops"])
        self.assertEqual(a["most_commented"]["id"], "big")
        self.assertIn("2 reels have no public view count", a["views_note"])
        self.assertIn("over-represents winners", a["views_note"])
        # nothing measurable at all -> no analysis rather than a crash
        self.assertIsNone(insights.analyze_instagram({"posts": [{"id": "a", "views": None, "likes": None}] * 5}))

    def test_youtube_competitor_rows(self):
        import collect
        self.assertEqual(collect.iso_duration_seconds("PT45S"), 45)
        self.assertEqual(collect.iso_duration_seconds("PT1M5S"), 65)
        self.assertEqual(collect.iso_duration_seconds("PT1H"), 3600)
        self.assertEqual(collect.iso_duration_seconds("garbage"), 0)
        resp = {"items": [
            {"id": "short1", "snippet": {"title": "What if", "description": "d", "publishedAt": "2026-11-20T10:00:00Z"},
             "statistics": {"viewCount": "50000", "likeCount": "900", "commentCount": "12"}, "contentDetails": {"duration": "PT30S"}},
            {"id": "long1", "snippet": {"title": "Documentary"}, "statistics": {"viewCount": "9"},
             "contentDetails": {"duration": "PT12M"}}]}
        rows = collect.youtube_reel_rows(resp)
        self.assertEqual([r["id"] for r in rows], ["short1"])                  # long video dropped
        self.assertEqual(rows[0]["views"], 50000)
        data = {"accounts": [{"handle": "chan", "platform": "youtube", "followers": 5000, "reels": [
            {"id": f"s{i}", "views": v, "caption": "x"} for i, v in enumerate([1000, 1200, 900, 1100, 80000])]}]}
        out = insights.analyze_competitors(data)
        self.assertEqual(out["outliers"][0]["url"], "https://www.youtube.com/watch?v=s4")
        self.assertEqual(out["outliers"][0]["platform"], "youtube")

    def test_playbook(self):
        own = {"winners": ["a"], "flops": ["b"], "sample_size": 12,
               "caption_features": {"pov": {"lift_x": 2.0}, "what_if": {"lift_x": 0.5}, "send_this_cta": {"lift_x": 1.0}},
               "hashtags": [{"tag": "#funny"}]}
        posts = [{"id": "a", "caption": "Big hook\nmore"}, {"id": "b", "caption": "Flop hook"}]
        pb = insights.build_playbook(own, posts, None)
        self.assertEqual(pb["own_winner_hooks"], ["Big hook"])
        self.assertEqual(pb["own_traits_that_beat_median"], ["pov"])
        self.assertEqual(pb["own_traits_that_lag"], ["what_if"])
        self.assertIsNone(insights.build_playbook(None, [], None))


if __name__ == "__main__":
    unittest.main()
