# 07 — Menu deck: stacked cards, fan, 3D flip

**What to build:** The taste edit as a physical deck: after the last thesis message leaves, a compressed stack of menu cards rises from below center, fans into small rotations/offsets showing black card backs (white DROP primary logo, nothing else), then flips 3D with 70–110ms stagger to reveal fronts — product image, name, maker, optional category label. W04 renders the fruit tart and mochi box from data; component supports 2–6 items.

**Blocked by:** 02 — Brand geometry (card-back logo); 03 — Immersive shell.

**Status:** ready-for-agent

- [ ] Entry choreography per brief: rise → fan (angles adapt to count, ~±8°/±3° starting points) → staggered flips; CSS 3D (`perspective`, `preserve-3d`, backface hidden)
- [ ] Card fronts contain image/name/maker (+ optional category) only — no rationale paragraph, price, buy, cart, or like anywhere
- [ ] Sharp corners (`border-radius: 0`); no rounded SaaS card styling
- [ ] Card count fully data-driven 2–6; no duplicated content to fake a bigger stack; fan-angle/offset adaptation verified at the scene-state seam against the ticket-01 variable-count fixture (5 items), not just W04's 2
- [ ] Reverse scroll reconstructs the stack and returns it below the viewport
- [ ] Desktop-only subtle post-flip pointer tilt; nothing depends on hover
- [ ] Safari/WebKit backface behavior verified; mobile uses narrower fan angles and vertical offsets
- [ ] Playwright: 2 cards rendered from data, flip state reachable forward and reversible backward, reduced-motion shows fronts without 3D flip
