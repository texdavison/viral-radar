// Reads a PUBLIC Instagram profile's recent reels, logged out. Used by Claude through the browser pane
// to refresh ig_manual.json (own account) and competitors_manual.json (similar accounts).
//
// How to run: open https://www.instagram.com/<handle>/reels/ in the browser pane (decline optional cookies),
// then evaluate this file's contents there. It returns { handle, followers, reels: [...] }.
//
// Gives views (from the grid), likes, comments, date and caption. Instagram does not publish shares,
// saves, reach or watch time; those only come from the API for your own account.
//
// LIMITS (observed): view counts appear only on the /reels/ tab. Instagram sometimes shows a sign-up wall
// there for logged-out visitors (it worked early in a session, then stopped). On the main profile page the
// grid has no view counts, so views come back null. Never log in or work around the wall; if it appears,
// stop and fall back to the YouTube path or to numbers the owner pastes in.
(async () => {
  const handle = location.pathname.split('/').filter(Boolean)[0];
  const max = 12;
  const dec = s => { const t = document.createElement('textarea'); t.innerHTML = s; return t.value; };
  const num = s => {                       // "3,568" -> 3568, "20.1K" -> 20100, "1.2M" -> 1200000
    const m = (s || '').replace(/,/g, '').match(/([\d.]+)\s*([KM]?)/i);
    return m ? Math.round(parseFloat(m[1]) * ({ '': 1, K: 1e3, M: 1e6 }[m[2].toUpperCase()])) : null;
  };
  const m = document.body.innerText.match(/([\d.,]+[KM]?)\s+followers/i);
  const followers = m ? num(m[1]) : null;
  const tiles = [...document.querySelectorAll(`a[href*="/${handle}/reel/"]`)].slice(0, max);
  const reels = [];
  for (const a of tiles) {
    const id = a.getAttribute('href').split('/reel/')[1].replace(/\/$/, '');
    const views = num(a.innerText.trim().split('\n')[0]);
    let likes = null, comments = null, date = null, caption = '';
    try {
      const html = await fetch(`/${handle}/reel/${id}/`, { credentials: 'omit' }).then(r => r.text());
      const mm = html.match(/<meta[^>]+property="og:description"[^>]+content="([^"]*)"/) ||
                 html.match(/<meta[^>]+name="description"[^>]+content="([^"]*)"/);
      const d = mm ? dec(mm[1]) : '';
      const head = d.match(/^([\d.,KM]+) likes?, ([\d.,KM]+) comments?/i);
      if (head) { likes = num(head[1]); comments = num(head[2]); }
      const tail = d.match(/on ([A-Z][a-z]+ \d+, \d{4}): "([\s\S]*)"\.?\s*$/);
      if (tail) { date = new Date(tail[1] + ' UTC').toISOString().slice(0, 10); caption = tail[2]; }
    } catch (e) { /* leave nulls */ }
    reels.push({ id, date, views, likes, comments, caption });
  }
  return { handle, followers, reels };
})();
