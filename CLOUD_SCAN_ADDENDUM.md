# Paste into the "Viral Idea Radar scan" cloud task instructions

The collector now adds four optional keys to `signals/latest.json`. Existing keys are unchanged.
If any new key is missing or empty, ignore it and carry on.

```
EXTRA SIGNALS (new in signals/latest.json; all optional)

1. instagram_analysis: what has actually worked on @how_does_it_work1, computed from its own reels.
   - per_reel[]: views, outlier_x (views vs the account's median reel; 2+ is a winner, 0.5 or less is a flop),
     like_rate_pct, comment_rate_pct, views_per_follower.
   - caption_features: for each caption trait (send_this_cta, what_if, pov, question_in_hook, follow_or_name_ask,
     type_at_cta) the median views with vs without it, and lift_x. lift_x above 1 means reels with that trait beat
     reels without it. Only traits seen in 2+ reels appear.
   - hashtags[]: hashtags used 2+ times with their median views.
   - winners / flops: reel ids. Join them to instagram.posts by id to read their captions.
   - sample_size is small (a dozen reels). Treat all of it as directional: use it to nudge scores up or down,
     never as a hard rule. When scoring an idea, compare it with the winners' topics and hooks, not just the traits.
   - Rows in instagram.posts with source "manual" have only views, likes and comments (no shares, saves, reach or
     watch time). Don't treat a missing shares/saves value as zero.

2. wikipedia[]: English Wikipedia articles with the biggest day-over-day pageview spike (growth_x). A page with
   growth_is_lower_bound true was not in yesterday's top list, so its real spike is at least that big. Spiking
   pages are curiosity signals ("what is X / how does X work"). Skip obituaries and anything not usable for a
   light 3D explainer or what-if reel.

3. hackernews[]: Hacker News front page with points per hour (velocity). Mostly tech. Use only for "how X works"
   style ideas.

4. google_trends_intl[]: trending searches in GB, CA and AU that are NOT yet trending in the US (each row has geo).
   Early-warning candidates that may reach the US within a day or two.

Rows in wikipedia and hackernews also carry new_since_last_run. Prefer new items over ones that were already
there last scan.

Score ideas the same way as before. Where one of these signals supports an idea, cite it in the idea's evidence
(e.g. "Wikipedia 'X' 8x spike", "GB trending, not yet US").
```
