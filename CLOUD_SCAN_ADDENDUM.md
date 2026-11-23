# Paste into the "Viral Idea Radar scan" cloud task instructions

This replaces the earlier version of this file. The collector adds these optional keys to
`signals/latest.json`; existing keys are unchanged. If a key is missing or empty, ignore it and carry on.

```
EXTRA SIGNALS (new in signals/latest.json; all optional)

1. topics[]  <- START HERE. The collector has already merged the same subject across sources, so score
   topics, not raw rows. Each topic has:
   - topic, sources[], source_count: how many independent sources show it (Google Trends US, Google
     Trends GB/CA/AU, Wikipedia, Hacker News, Reddit, YouTube). 2+ sources is a much stronger signal
     than one spike; 3+ is rare and valuable.
   - lifecycle: emerging | rising | peaking | fading, with lifecycle_confidence (low until the topic has
     been seen on 3+ scans; topic_meta.history_depth_hours says how much history exists). window_hint is
     advice for that stage. Prefer rising and emerging; avoid fading unless the idea is evergreen. Treat
     peaking as "needs a fresh angle". Don't over-trust low-confidence stages.
   - signals{}: the raw numbers per source. evidence[]: the actual headlines/titles/links to cite.
   - risk_flags[]: nicotine, gambling, politics_war, death_tragedy, adult. A flag means "needs care", not
     "forbidden": either find a safe angle or mark the idea as risky and say why. Never hide a flag.
   - saturation (only on the top few topics, only when a YouTube key is set): label untouched | open |
     active | contested | crowded, plus how many Shorts in the last 48h are above 10K views. Prefer
     untouched/open; a crowded topic needs a very distinct twist or should be skipped. If saturation is
     missing, say "competition unchecked" instead of guessing.
   topic_meta explains saturation status and how much history the lifecycle has.

2. instagram_analysis: what has worked on @how_does_it_work1, from its own reels.
   - per_reel[]: outlier_x (views vs the account's median reel; 2+ is a winner, 0.5 or less a flop) when
     views are public, and likes_outlier_x (likes vs median likes) for every reel. Some reels have no
     public view count: they are ranked by likes. winners / flops are reel ids; join them to
     instagram.posts by id to read their captions.
   - caption_features and caption_features_by_likes: median result with vs without each caption trait,
     and lift_x (above 1 = reels with that trait beat reels without it). hashtags and hashtags_by_likes
     likewise. Only traits seen in 2+ reels appear.
   - views_note and caveat: the sample is small and likely biased toward winners. Use all of this to
     nudge scores up or down, never as a hard rule.
   - instagram.posts rows with source "manual" have only views/likes/comments (no shares, saves, reach,
     watch time). Don't treat a missing shares/saves value as zero.

3. format_playbook: a short summary of what has worked (own winner hooks and flop hooks, traits that beat or
   lag the median, best hashtags, and competitor outlier hooks when present). Use it for item 5 below.

4. competitor_outliers (only when competitor accounts are configured): reels or Shorts from similar accounts
   that beat their own account's normal by 3x+ (outlier_x), with hook, hashtags and link. Use them as proof
   that a format or topic works for other creators, and cite the link. Never copy a hook word for word;
   borrow the structure.

5. Other new lists: wikipedia[] (day-over-day spikes; growth_is_lower_bound true means the real spike is at
   least that big; skip obituaries), hackernews[] (tech-heavy; only for "how X works" ideas),
   google_trends_intl[] (trending in GB/CA/AU but not yet in the US: early-warning candidates).
   Rows in wikipedia and hackernews also carry new_since_last_run.

SCORING: score ideas as before, but start from topics[]. Add credit for source_count, a rising or emerging
lifecycle, an open saturation label, and fit with format_playbook. Subtract for fading, crowded, or an
unresolved risk flag. In every idea's evidence, cite what supports it (for example: "Trends US + Hacker
News, rising", "Wikipedia 8x spike", "GB trending, not yet US", "3 Shorts above 10K in 48h = contested").

IDEA PACKAGE: for each of the top ideas (up to 5 per scan), write a ready-to-shoot package:
  - hooks: 3 variants of the first line (max ~12 words each), written in the style of own_winner_hooks and
    competitor_outlier_hooks, avoiding own_flop_hooks patterns and own_traits_that_lag.
  - beats: 5 short shot beats for a 15-25 second 3D animated reel (setup, escalation, twist, payoff,
    call to action).
  - caption: one caption in the account's voice with a call to action and 5-8 hashtags, preferring
    own_best_hashtags. Use traits in own_traits_that_beat_median.
  - why_now: one sentence tying it to lifecycle and sources.
  - risk: the risk_flags and how the package handles them, or "none".
  - confidence: low | medium | high, honestly lower when the evidence is a single source, history is thin,
    or competition is unchecked.
Write the package into the idea's record on the dashboard alongside the existing fields.
```
