# 09 — Films: three-view recommendation sequence

**What to build:** The pinned film scene over Wavy Dots: exactly one recommendation visible at a time — info column left (view label, title, director, year, genres, Persian rationale), large vertical poster right entering from lower-right with slight rotation/scale, exiting upward as the next arrives, with 1–2 subtle paper layers behind. W04's three films (Showing Up → Perfect Days → Paterson) advance with scroll, text synced to the active poster.

**Blocked by:** 08 — Grid statement, Pixel A, Wavy Dots.

**Status:** ready-for-agent

- [ ] One active film at a time; never three posters side-by-side as static cards
- [ ] Desktop: info left, poster right (deliberate LTR grid held for Persian; text inside the column may right-align); tablet keeps two columns if readable; mobile stacks poster above/behind text without readability loss
- [ ] Three W04 films render from data in view order with exact Persian rationales; counts and content fully data-driven
- [ ] Poster enter/exit choreography per brief; posters keep natural rectangle (subtle paper edges allowed)
- [ ] No buy/like/price/favorite/cart controls; source link (if any) is the subtly clickable title/poster, opening safely in a new tab (`rel="noopener"`, announced as external) only when a `sourceUrl` exists in data
- [ ] Reverse scroll steps back through films correctly (scene-state seam maps progress → film index symmetrically)
- [ ] Reduced motion: films swap by crossfade; all three reachable
- [ ] Playwright: 3 films appear in order forward, reverse restores film 1, poster images load from local mock paths
