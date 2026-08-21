# 06 — Pinned thesis scene

**What to build:** The pinned hero: minimal off-white scene where the three W04 hero messages (from data) replace each other under scroll — line-mask entries (`yPercent`, opacity, small blur resolving to sharp), outgoing message lifting and softening — with the optional small `W04 / BEAUTIFUL IMPERFECTION` label and the bottom orange/purple glow breathing with progress. First scene where the real editorial voice is demoable.

**Blocked by:** 03 — Immersive shell; 04 — Shared WebGL canvas (`offWhiteGlow` mode).

**Status:** ready-for-agent

- [ ] Scene pins; messages come from `heroMessages` array (count-agnostic, W04 has three); Persian renders correctly
- [ ] Line-mask transitions per brief; no typewriter or random letter effects
- [ ] Reverse scroll reverses transitions cleanly at any point (scene-state seam test for the message-index mapping + Playwright forward/reverse assertions)
- [ ] Glow grows from lower edge, never reduces text contrast below AA
- [ ] Reduced motion: messages swap by simple crossfade; all three readable
- [ ] Mobile: fewer line breaks, safe viewport units (`svh`/`dvh`), no trapped-feeling pin length
- [ ] Top-right remains empty; no CTA anywhere in the scene
